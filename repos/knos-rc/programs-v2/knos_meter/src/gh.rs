//! Reading a GitHub Actions token that knos-oidc verified (through knos-oidc-interface), the rule for the key that
//! verified it, and the audiences this program understands.
//!
//! THE THREE AUDIENCES (the `aud` claim; parts split on ':', nothing before, between or after them).
//!   knosm:eval:<buyer owner id>:<seller id>:<work order hex32>:<artifact hex40>:<policy hex32>:<milestone>:<verdict 0|1>:<rate>
//!   knosm:batch:<buyer owner id>:<seller id>:<month>:<seq>:<count>:<accepted>:<value>:<root>
//!   knosm:claim:<buyer owner id>:<seller id>:<month>:<seq>:<count>:<accepted>:<value>:<root>
//! A batch and a claim have ten parts each:
//!   buyer owner id, seller id   GitHub owner ids, decimal, not 0
//!   month      yyyymm (UTC) of the evaluations, six digits, e.g. 202610
//!   seq        the batch's number in its Ledger: 0 for the first of a (buyer, seller, month), then 1, 2, ...
//!   count      evaluations in the batch, 1..=100000
//!   accepted   how many of them were accepted, 0..=count
//!   value      the sum of `rate` over the accepted, in the smallest units of whatever the two settle in
//!   root       the RFC 6962 Merkle root over the batch's evaluation keys, 64 lowercase hex characters
//! Every number is decimal with no sign and no leading zero ("0" itself is written 0), at most 18 digits.
//! Example: the first batch of October 2026 of buyer 424242 with seller 555000, 5,000 evaluations, 4,321 accepted,
//! worth 8,642,000,000 units, with a root of 32 bytes 0xab:
//!   knosm:batch:424242:555000:202610:0:5000:4321:8642000000:abababababababababababababababababababababababababababababababab
//! knosm:batch is asked for by a run in a repository of the BUYER (RecordBatch), knosm:claim by a run in a repository
//! of the SELLER (ClaimBatch); a token of one kind is never taken as the other.
use crate::{err, state::i64_at, E_ACCOUNTS, E_AUD, E_CLAIMS, E_KEY_KIND, E_TOKEN, OIDC_ID, TOKEN_AHEAD, TOKEN_LIFE};
use knos_oidc_interface::{is_hex, number, parse_u64, parts, text, unhex32, Raw, Text, Token, ISSUER_GITHUB, T_KEY};
use solana_program::{account_info::AccountInfo, entrypoint::ProgramResult, hash::hashv, program_error::ProgramError};

// knos-oidc's key account, as programs-v2/knos_oidc/src/lib.rs lays it out: state u8 (1 ready), issuer u8, limbs u8
// (64 or 128), bump u8, n0inv u32, active_at i64, expires_at i64, flags u8, zeros to 40, then n and r2 (4 bytes a limb)
const K_STATE: usize = 0;
const K_LIMBS: usize = 2;
const K_ACTIVE: usize = 8;
const K_EXPIRES: usize = 16;
const K_FLAGS: usize = 24;
const K_HDR: usize = 40;
pub const F_APPROVED: u8 = 1;
pub const F_REVOKED: u8 = 2;
pub const F_GENESIS: u8 = 4;
// the verifier's own codes for a key that may not verify now
pub const E_KEY_INACTIVE: u32 = 76;
pub const E_KEY_EXPIRED: u32 = 77;
pub const E_KEY_REVOKED: u32 = 78;

/// The claims this program reads, taken once from the token account.
pub struct Gh {
    pub owner_id: u64,        // repository_owner_id: whose repository the run was in
    pub wf_repo: [u8; 32],    // sha256 of the "<owner>/<name>" of job_workflow_ref
    pub wf_file: Vec<u8>,     // its "<file>"
    pub wf_sha: Vec<u8>,      // job_workflow_sha: the commit that fixes the workflow file's content
    pub aud: Vec<u8>,
    pub first_attempt: bool,  // run_attempt is 1: the run was started by its event, not re-run later by someone else
}

fn claim(e: knos_oidc_interface::Error) -> ProgramError { err(e.code()) }
fn owned(t: Text) -> Vec<u8> { t.bytes().collect() }
fn num(f: Option<Raw>) -> Result<u64, ProgramError> { number(f).map_err(claim) }

/// The rule Record starts from: the account is owned by knos-oidc (the second deployment) and VERIFIED (GitHub's
/// signature was checked on chain), the issuer is GitHub, the token is at most an hour past its expiry, the key that
/// verified it is still good (`key_good`), and the run was on a GitHub-hosted runner.
///
/// GitHub's tokens live five minutes from `iat`. One that says it was issued more than TOKEN_AHEAD in the future, or
/// that it lives longer than TOKEN_LIFE, was not written by GitHub's clock and is refused.
pub fn github(tok: &AccountInfo, key: &AccountInfo, now: i64) -> Result<Gh, ProgramError> {
    let d = tok.try_borrow_data()?;
    let t = Token::read_from(&OIDC_ID.to_bytes(), &tok.owner.to_bytes(), &d, now).map_err(|_| err(E_TOKEN))?;
    if t.issuer() != ISSUER_GITHUB { return Err(err(E_TOKEN)); }
    key_good(&d, key, now)?;
    let [owner_id, iat, wref, wsha, runner, aud, run_attempt] = t.claims(
        [b"repository_owner_id", b"iat", b"job_workflow_ref", b"job_workflow_sha", b"runner_environment", b"aud", b"run_attempt"]).map_err(claim)?;
    if !text(runner).map_err(claim)?.is("github-hosted") { return Err(err(E_CLAIMS)); }
    let iat = num(iat)? as i64;
    if iat > now.saturating_add(TOKEN_AHEAD) || t.exp().saturating_sub(iat) > TOKEN_LIFE { return Err(err(E_TOKEN)); }
    let wf_ref = owned(text(wref).map_err(claim)?);
    const MID: &[u8] = b"/.github/workflows/";
    let at = wf_ref.windows(MID.len()).position(|w| w == MID).ok_or_else(|| err(E_CLAIMS))?;
    let rest = &wf_ref[at + MID.len()..];
    let end = rest.iter().position(|&c| c == b'@').ok_or_else(|| err(E_CLAIMS))?;
    let wf_sha = owned(text(wsha).map_err(claim)?);
    if !is_hex(&wf_sha, 40) { return Err(err(E_CLAIMS)); }
    Ok(Gh { owner_id: num(owner_id)?, wf_repo: hashv(&[&wf_ref[..at]]).to_bytes(), wf_file: rest[..end].to_vec(), wf_sha,
            aud: owned(text(aud).map_err(claim)?), first_attempt: number(run_attempt).ok() == Some(1) })
}

/// Whether a key may stand behind a count now, from its flags and times: Ok, or the error code. The verifier's own
/// rule and codes (a revoked key first, then one that is not active yet, then one that has expired), and one more:
/// a flag this program does not know is refused (E_KEY_KIND). That is how a PRIVATE key is refused (a key any wallet
/// registered with no attestation, for an issuer no public runner can reach), and any kind of key added later: a
/// neutral count stands only on keys GitHub's own signature admitted.
pub fn key_usable(flags: u8, active_at: i64, expires_at: i64, now: i64) -> Result<(), u32> {
    if flags & F_REVOKED != 0 { return Err(E_KEY_REVOKED); }
    if flags & !(F_APPROVED | F_REVOKED | F_GENESIS) != 0 { return Err(E_KEY_KIND); }
    if flags & (F_GENESIS | F_APPROVED) == 0 || now < active_at { return Err(E_KEY_INACTIVE); }
    if now >= expires_at { return Err(E_KEY_EXPIRED); }
    Ok(())
}

/// A token stops working when the key that verified it does. `key` must be the account the token account names (the
/// verifier wrote its address there when the verification began, and never closes a key account), owned by the
/// verifier, a ready key of the layout above and nothing longer, and usable now (`key_usable`). Another account in the
/// key's place is E_ACCOUNTS. `tok`: the data of a VERIFIED token account.
fn key_good(tok: &[u8], key: &AccountInfo, now: i64) -> ProgramResult {
    if *key.owner != OIDC_ID || key.key.as_ref() != &tok[T_KEY..T_KEY + 32] { return Err(err(E_ACCOUNTS)); }
    let k = key.try_borrow_data()?;
    let limbs = if k.len() >= K_HDR { k[K_LIMBS] as usize } else { 0 };
    if (limbs != 64 && limbs != 128) || k.len() != K_HDR + 8 * limbs || k[K_STATE] != 1 { return Err(err(E_KEY_KIND)); }
    key_usable(k[K_FLAGS], i64_at(&k, K_ACTIVE), i64_at(&k, K_EXPIRES), now).map_err(err)
}

/// knosm:eval:<buyer owner id>:<seller id>:<work order hex32>:<artifact hex40>:<policy hex32>:<milestone>:<verdict>:<rate>
/// hex32 is 32 bytes as 64 lowercase hex characters; the artifact is a commit, 40. verdict: 1 accepted, 0 rejected.
/// rate: what the seller bills for this outcome when it is accepted, in the smallest units of whatever the two
/// parties settle in; this program only adds it up.
pub struct EvalAud { pub buyer: u64, pub seller: u64, pub order: [u8; 32], pub artifact: [u8; 40], pub policy: [u8; 32], pub milestone: u32, pub accepted: bool, pub rate: u64 }
impl EvalAud {
    /// What makes an evaluation billable once: the work order, the artifact, the policy and the milestone.
    pub fn key(&self) -> [u8; 32] { hashv(&[&self.order, &self.artifact, &self.policy, &self.milestone.to_le_bytes()]).to_bytes() }
}
pub fn eval_aud(aud: &[u8]) -> Result<EvalAud, ProgramError> {
    let bad = || err(E_AUD);
    let n = |s: &[u8]| parse_u64(s).ok_or_else(bad);
    let [k, e, buyer, seller, order, artifact, policy, milestone, verdict, rate] = parts::<10>(aud).ok_or_else(bad)?;
    if k != b"knosm" || e != b"eval" || !is_hex(artifact, 40) || (verdict != b"0" && verdict != b"1") { return Err(bad()); }
    let (buyer, seller, milestone) = (n(buyer)?, n(seller)?, n(milestone)?);
    if buyer == 0 || seller == 0 || milestone > u32::MAX as u64 { return Err(bad()); }
    Ok(EvalAud { buyer, seller, order: unhex32(order).ok_or_else(bad)?, artifact: artifact.try_into().unwrap(), policy: unhex32(policy).ok_or_else(bad)?,
                 milestone: milestone as u32, accepted: verdict == b"1", rate: n(rate)? })
}

/// knosm:batch:... or knosm:claim:... (the layout is at the top of this file). `month` is held to the chain's clock
/// and `count` to MAX_BATCH by the instruction; here only the shape.
pub struct BatchAud { pub buyer: u64, pub seller: u64, pub month: u32, pub seq: u64, pub count: u64, pub accepted: u64, pub value: u64, pub root: [u8; 32] }
impl BatchAud {
    /// The Ledger's running hash after this batch: sha256(chain || root || seq || count || accepted || value).
    pub fn chain(&self, before: &[u8]) -> [u8; 32] {
        hashv(&[before, &self.root, &self.seq.to_le_bytes(), &self.count.to_le_bytes(), &self.accepted.to_le_bytes(), &self.value.to_le_bytes()]).to_bytes()
    }
}
/// `kind`: b"batch" (the buyer's record) or b"claim" (the seller's).
pub fn batch_aud(aud: &[u8], kind: &[u8]) -> Result<BatchAud, ProgramError> {
    let bad = || err(E_AUD);
    let n = |s: &[u8]| parse_u64(s).ok_or_else(bad);
    let [k, e, buyer, seller, month, seq, count, accepted, value, root] = parts::<10>(aud).ok_or_else(bad)?;
    if k != b"knosm" || e != kind || month.len() != 6 { return Err(bad()); }
    let (buyer, seller) = (n(buyer)?, n(seller)?);
    if buyer == 0 || seller == 0 { return Err(bad()); }
    Ok(BatchAud { buyer, seller, month: n(month)? as u32, seq: n(seq)?, count: n(count)?, accepted: n(accepted)?, value: n(value)?, root: unhex32(root).ok_or_else(bad)? })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_key_stands_behind_a_count_only_while_the_verifier_would_use_it_and_never_a_private_one() {
        for flags in 0..=255u8 {
            let got = key_usable(flags, 100, 200, 150);
            let want = if flags & F_REVOKED != 0 { Err(E_KEY_REVOKED) } else if flags & !7 != 0 { Err(E_KEY_KIND) }
                       else if flags & (F_GENESIS | F_APPROVED) == 0 { Err(E_KEY_INACTIVE) } else { Ok(()) };
            assert_eq!(got, want, "{flags}");
        }
        assert_eq!(key_usable(F_APPROVED, 100, 200, 99), Err(E_KEY_INACTIVE));
        assert_eq!(key_usable(F_APPROVED, 100, 200, 100), Ok(()));
        assert_eq!(key_usable(F_GENESIS, 100, 200, 199), Ok(()));
        assert_eq!(key_usable(F_GENESIS, 100, 200, 200), Err(E_KEY_EXPIRED));
        assert_eq!(key_usable(F_APPROVED | 8, 100, 200, 150), Err(E_KEY_KIND));
    }

    #[test]
    fn a_batch_audience_is_ten_parts_of_its_own_kind() {
        let root = "ab".repeat(32);
        let aud = format!("knosm:batch:424242:555000:202610:0:5000:4321:8642000000:{root}");
        let b = batch_aud(aud.as_bytes(), b"batch").unwrap();
        assert_eq!((b.buyer, b.seller, b.month, b.seq, b.count, b.accepted, b.value, b.root), (424242, 555000, 202610, 0, 5000, 4321, 8_642_000_000, [0xab; 32]));
        assert_eq!(b.chain(&[0u8; 32]), hashv(&[&[0u8; 32], &[0xab; 32], &0u64.to_le_bytes(), &5000u64.to_le_bytes(), &4321u64.to_le_bytes(), &8_642_000_000u64.to_le_bytes()]).to_bytes());
        assert!(batch_aud(aud.as_bytes(), b"claim").is_err() && eval_aud(aud.as_bytes()).is_err());
        assert_eq!(batch_aud(aud.replace("knosm:batch", "knosm:claim").as_bytes(), b"claim").unwrap().seq, 0);
        for bad in [format!("knosm:batch:0:555000:202610:0:5:4:8:{root}"), format!("knosm:batch:424242:0:202610:0:5:4:8:{root}"),
                    format!("knosm:batch:424242:555000:20261:0:5:4:8:{root}"), format!("knosm:batch:424242:555000:2026100:0:5:4:8:{root}"),
                    format!("knosm:batch:424242:555000:202610:00:5:4:8:{root}"), format!("knosm:batch:424242:555000:202610:0:-5:4:8:{root}"),
                    format!("knosm:batch:424242:555000:202610:0:5:4:8:{}", &root[1..]), format!("knosm:batch:424242:555000:202610:0:5:4:8:{}", "AB".repeat(32)),
                    format!("knosm:batch:424242:555000:202610:0:5:4:8:{root}:x"), format!("knosm:batch:424242:555000:202610:0:5:4:{root}"),
                    format!("knos2:batch:424242:555000:202610:0:5:4:8:{root}")] {
            assert!(batch_aud(bad.as_bytes(), b"batch").err() == Some(err(E_AUD)), "{bad}");
        }
    }

    #[test]
    fn an_eval_audience_is_ten_parts_and_nothing_else() {
        let (order, policy, sha) = ("ab".repeat(32), "cd".repeat(32), "e".repeat(40));
        let aud = format!("knosm:eval:424242:555000:{order}:{sha}:{policy}:3:1:2500000");
        let e = eval_aud(aud.as_bytes()).unwrap();
        assert_eq!((e.buyer, e.seller, e.order, e.policy, e.milestone, e.accepted, e.rate), (424242, 555000, [0xab; 32], [0xcd; 32], 3, true, 2_500_000));
        assert_eq!(&e.artifact[..], sha.as_bytes());
        assert_eq!(e.key(), hashv(&[&[0xab; 32], sha.as_bytes(), &[0xcd; 32], &3u32.to_le_bytes()]).to_bytes());
        assert!(!eval_aud(format!("knosm:eval:424242:555000:{order}:{sha}:{policy}:3:0:0").as_bytes()).unwrap().accepted);
        for bad in [format!("knos2:eval:424242:555000:{order}:{sha}:{policy}:3:1:25"), format!("knosm:pay:424242:555000:{order}:{sha}:{policy}:3:1:25"),
                    format!("knosm:eval:0:555000:{order}:{sha}:{policy}:3:1:25"), format!("knosm:eval:424242:0:{order}:{sha}:{policy}:3:1:25"),
                    format!("knosm:eval:424242:555000:{}:{sha}:{policy}:3:1:25", &order[1..]), format!("knosm:eval:424242:555000:{order}:{}:{policy}:3:1:25", "E".repeat(40)),
                    format!("knosm:eval:424242:555000:{order}:{sha}:{policy}:4294967296:1:25"), format!("knosm:eval:424242:555000:{order}:{sha}:{policy}:3:2:25"),
                    format!("knosm:eval:424242:555000:{order}:{sha}:{policy}:3:1:-1"), format!("knosm:eval:424242:555000:{order}:{sha}:{policy}:3:1:25:x"),
                    format!("knosm:eval:424242:555000:{order}:{sha}:{policy}:3:1"), format!("knosm:eval:424242:555000:{order}:{sha}:{policy}:03:1:25")] {
            assert!(eval_aud(bad.as_bytes()).err() == Some(err(E_AUD)), "{bad}");
        }
    }
}
