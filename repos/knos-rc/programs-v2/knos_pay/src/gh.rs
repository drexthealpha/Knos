//! Reading a GitHub Actions token that knos-oidc verified, and the audiences this program understands.
use crate::{err, state::{b58, i64_at}, E_ACCOUNTS, E_AUD, E_CLAIMS, E_TOKEN, OIDC_ID, TOKEN_AHEAD, TOKEN_LIFE};
use knos_oidc::claims::{self, fields, number, parts, text};
use knos_oidc::{K_ACTIVE, K_EXPIRES, K_FLAGS, K_HDR, T_JWT, T_KEY, T_LEN};
use solana_program::{account_info::AccountInfo, entrypoint::ProgramResult, hash::hashv, program_error::ProgramError, pubkey::Pubkey};

/// The claims this program reads, taken once from the token account.
pub struct Gh {
    pub repo_id: u64, pub owner_id: u64, pub actor_id: u64, pub iat: i64,
    pub wf_ref: Vec<u8>,      // job_workflow_ref, whole: "<owner>/<name>/.github/workflows/<file>@<ref>"
    pub wf_repo: [u8; 32],    // sha256 of its "<owner>/<name>"
    pub wf_file: Vec<u8>,     // its "<file>"
    pub wf_sha: Vec<u8>,      // job_workflow_sha: the commit that fixes the workflow file's content
    pub aud: Vec<u8>, pub event: Vec<u8>,
    pub repository: Option<Vec<u8>>,  // read by Bind only
    pub first_attempt: bool,  // run_attempt is 1: the run was started by the event's actor, not re-run later by someone else
}

/// The rule every instruction that takes a token starts from: the account is owned by knos-oidc and VERIFIED (GitHub's
/// signature was checked on chain), the issuer is GitHub, the token is at most knos_oidc::LATE past its expiry, the
/// key that verified it is still good (`key_good`), and the run was on a GitHub-hosted runner. What the token may
/// then do is decided by its claims, per instruction.
///
/// GitHub's tokens live five minutes from `iat`. One that says it was issued more than TOKEN_AHEAD in the future, or
/// that it lives longer than TOKEN_LIFE, was not written by GitHub's clock and is refused. So every token works only
/// from TOKEN_AHEAD before its `iat` until TOKEN_LIFE + LATE after it: none works for ever, whatever expiry it
/// carries, and none can date itself far ahead to count as newer than every job and every token still to come.
pub fn github(tok: &AccountInfo, key: &AccountInfo, now: i64) -> Result<Gh, ProgramError> { read(tok, key, now, false, |_| false) }

/// `github`, for the two instructions of a work order that also take a gitlab.com token (FundOrderBalance here,
/// PayOrder through `token_of`). No other instruction calls it, so a 2.0 job, a Bind, the faucet, a Reserve, a Cancel
/// and a Revert refuse a GitLab token as they refuse any token GitHub did not sign (E_TOKEN), whatever it says.
pub fn order_token(tok: &AccountInfo, key: &AccountInfo, now: i64) -> Result<Gh, ProgramError> { read(tok, key, now, true, |_| false) }

/// `github`, for the one caller that also takes a token GitHub did not sign (order_judge::token): a token verified
/// under a PRIVATE key (a key some wallet registered itself, which nobody checked) passes when `ours` accepts the
/// wallet that registered it. Such a token is that wallet's word, not GitHub's, and every other rule above holds for
/// it unchanged. A token of a registered issuer is refused whatever `ours` says; a gitlab.com token is read by gl.rs.
pub fn token_of(tok: &AccountInfo, key: &AccountInfo, now: i64, ours: impl Fn(&[u8; 32]) -> bool) -> Result<Gh, ProgramError> {
    read(tok, key, now, true, ours)
}

/// `orders`: the caller is an instruction of a work order that gl.rs gives an audience to. Only then is a GitLab
/// token read at all.
fn read(tok: &AccountInfo, key: &AccountInfo, now: i64, orders: bool, ours: impl Fn(&[u8; 32]) -> bool) -> Result<Gh, ProgramError> {
    if *tok.owner != OIDC_ID { return Err(err(E_TOKEN)); }
    let d = tok.try_borrow_data()?;
    let v = knos_oidc::verified(&d).ok_or_else(|| err(E_TOKEN))?;
    let gitlab = orders && v.issuer == knos_oidc::pins::ISSUER_GITLAB;    // read by gl.rs, into ids no GitHub token can carry
    let signed = v.issuer == knos_oidc::pins::ISSUER_GITHUB || knos_oidc::registrant(&d).is_some_and(ours);
    if !(signed || gitlab) || !knos_oidc::fresh(v.exp, now) { return Err(err(E_TOKEN)); }
    key_good(&d, key, now)?;
    if gitlab { return crate::gl::read(v.payload, v.exp, now); }
    let [repo_id, owner_id, actor_id, iat, wref, wsha, runner, aud, event, repository, run_attempt] = fields(v.payload,
        [b"repository_id", b"repository_owner_id", b"actor_id", b"iat", b"job_workflow_ref", b"job_workflow_sha", b"runner_environment", b"aud",
         b"event_name", b"repository", b"run_attempt"])?;
    if text(runner)? != b"github-hosted" { return Err(err(E_CLAIMS)); }
    let iat = number(iat)? as i64;
    if iat > now.saturating_add(TOKEN_AHEAD) || v.exp.saturating_sub(iat) > TOKEN_LIFE { return Err(err(E_TOKEN)); }
    let wf_ref = text(wref)?;
    const MID: &[u8] = b"/.github/workflows/";
    let at = wf_ref.windows(MID.len()).position(|w| w == MID).ok_or_else(|| err(E_CLAIMS))?;
    let rest = &wf_ref[at + MID.len()..];
    let end = rest.iter().position(|&c| c == b'@').ok_or_else(|| err(E_CLAIMS))?;
    let wf_sha = text(wsha)?;
    if !claims::is_hex(&wf_sha, 40) { return Err(err(E_CLAIMS)); }
    let id = crate::gl::not_ours;    // a GitHub id is below the ranges GitLab ids are read into
    Ok(Gh { repo_id: id(number(repo_id)?)?, owner_id: id(number(owner_id)?)?, actor_id: id(number(actor_id)?)?, iat,
            wf_repo: hashv(&[&wf_ref[..at]]).to_bytes(), wf_file: rest[..end].to_vec(), wf_sha, aud: text(aud)?, event: text(event)?,
            repository: text(repository).ok(), first_attempt: number(run_attempt).ok() == Some(1), wf_ref })
}

/// sha256 of the signature bytes of the token in a VERIFIED token account (one `github` or `token_of` accepted): what
/// a single-use marker ["used", sig] is named by. The verifier decodes the payload in place and leaves the signature
/// as the token carried it, after the last dot; it took that text only in its one canonical base64url form and only
/// as a number below the modulus, so one token has one hash and cannot be respelled to be used twice.
/// Every instruction that takes a token calls this once, for state::mark_used: decoding the 342 characters costs
/// 13,900 compute units (measured).
pub fn sig_hash(tok: &AccountInfo) -> Result<[u8; 32], ProgramError> {
    let tok = tok.try_borrow_data()?;
    let len = u16::from_le_bytes([tok[T_LEN], tok[T_LEN + 1]]) as usize;
    let jwt = tok.get(T_JWT..T_JWT + len).ok_or_else(|| err(E_TOKEN))?;
    let dot = jwt.iter().rposition(|&c| c == b'.').ok_or_else(|| err(E_TOKEN))?;
    let text = &jwt[dot + 1..];
    let mut sig = vec![0u8; claims::b64_len(text.len()).filter(|n| *n > 0).ok_or_else(|| err(E_TOKEN))?];
    claims::b64url_into(text, &mut sig)?;
    Ok(hashv(&[&sig]).to_bytes())
}

/// A token stops working when the key that verified it does. `key` must be the account the token account names (the
/// verifier wrote its address there when the verification began, and never closes a key account), owned by the
/// verifier, and usable now by the verifier's own rule: not revoked, not expired. So when the guardian revokes a key
/// (the issuer's private key leaked, say), or nothing has attested a key for KEY_TTL, the tokens that key verified
/// earlier are refused from that moment on, as the verifier refuses new ones. Another account in the key's place is
/// E_ACCOUNTS; a key that is not usable is refused with the verifier's own code (76 not active, 77 expired, 78 revoked).
/// `tok`: the data of a VERIFIED token account, so at least T_JWT bytes.
fn key_good(tok: &[u8], key: &AccountInfo, now: i64) -> ProgramResult {
    if *key.owner != OIDC_ID || key.key.as_ref() != &tok[T_KEY..T_KEY + 32] { return Err(err(E_ACCOUNTS)); }
    let k = key.try_borrow_data()?;
    if k.len() < K_HDR { return Err(err(E_ACCOUNTS)); }
    knos_oidc::key_usable(k[K_FLAGS], i64_at(&k, K_ACTIVE), i64_at(&k, K_EXPIRES), now).map_err(err)
}

pub fn n(s: &[u8]) -> Result<u64, ProgramError> { claims::parse_u64(s).ok_or_else(|| err(E_AUD)) }

/// knos2:fund:<issue>:<amount units>:<mode 0|1>:<terms hash hex>:<work seconds>:<balance address>
pub struct FundAud { pub issue: u64, pub amount: u64, pub mode: u8, pub terms: [u8; 32], pub work: i64 }
/// `balance`: the Balance the instruction is about to spend or fill. The audience must name it, exactly as Solana
/// prints its address: the funder's own workflow chose the Balance when it asked GitHub for the token, and no relayer
/// can point the token at another one. (The address is printed and compared, which costs less than decoding the
/// audience's; one address has one base58 form.)
pub fn fund_aud(aud: &[u8], balance: &Pubkey) -> Result<FundAud, ProgramError> {
    let [k, f, issue, amount, mode, terms, work, named] = parts::<8>(aud).ok_or_else(|| err(E_AUD))?;
    if k != b"knos2" || f != b"fund" || (mode != b"0" && mode != b"1") || named != b58(balance).as_bytes() { return Err(err(E_AUD)); }
    Ok(FundAud { issue: n(issue)?, amount: n(amount)?, mode: mode[0] - b'0', terms: claims::unhex32(terms).ok_or_else(|| err(E_AUD))?, work: n(work)? as i64 })
}

/// knos2:pay:<repository id>:<issue>:<payee github id>:<head sha>:<terms hash hex>:<mode>:<address or ->
pub struct PayAud { pub repo: u64, pub issue: u64, pub payee: u64, pub terms: [u8; 32], pub mode: u8, pub address: Option<Pubkey> }
pub fn pay_aud(aud: &[u8]) -> Result<PayAud, ProgramError> {
    let [k, p, repo, issue, payee, head, terms, mode, address] = parts::<9>(aud).ok_or_else(|| err(E_AUD))?;
    if k != b"knos2" || p != b"pay" || !claims::is_hex(head, 40) || (mode != b"0" && mode != b"1") { return Err(err(E_AUD)); }
    let address = if address == b"-" { None } else { Some(Pubkey::new_from_array(claims::b58_32(address).ok_or_else(|| err(E_AUD))?)) };
    let payee = n(payee)?;
    if payee == 0 { return Err(err(E_AUD)); }
    Ok(PayAud { repo: n(repo)?, issue: n(issue)?, payee, terms: claims::unhex32(terms).ok_or_else(|| err(E_AUD))?, mode: mode[0] - b'0', address })
}

/// knos2:bind:<address>
pub fn bind_aud(aud: &[u8]) -> Result<Pubkey, ProgramError> {
    let [k, b, address] = parts::<3>(aud).ok_or_else(|| err(E_AUD))?;
    if k != b"knos2" || b != b"bind" { return Err(err(E_AUD)); }
    Ok(Pubkey::new_from_array(claims::b58_32(address).ok_or_else(|| err(E_AUD))?))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_fund_audience_names_one_balance_as_solana_prints_it() {
        let terms = "ab".repeat(32);
        let mut zeros = [9u8; 32];
        zeros[..3].copy_from_slice(&[0; 3]);
        for key in [Pubkey::new_from_array([7; 32]), Pubkey::new_from_array(zeros), Pubkey::new_from_array([0; 32]), Pubkey::new_from_array([255; 32])] {
            let aud = format!("knos2:fund:7:5000000:1:{terms}:3600:{key}");
            let f = fund_aud(aud.as_bytes(), &key).unwrap();
            assert_eq!((f.issue, f.amount, f.mode, f.terms, f.work), (7, 5_000_000, 1, [0xab; 32], 3600));
            // another Balance; no Balance; something after it; another spelling of the same address
            let other = Pubkey::new_from_array([8; 32]);
            let refused = [(aud.clone(), other), (format!("knos2:fund:7:5000000:1:{terms}:3600"), key), (format!("{aud}:x"), key),
                           (format!("knos2:fund:7:5000000:1:{terms}:3600:1{key}"), key), (format!("knos2:fund:7:5000000:1:{terms}:3600:{key} "), key)];
            for (aud, balance) in refused {
                assert!(fund_aud(aud.as_bytes(), &balance).err() == Some(err(E_AUD)), "{aud}");
            }
        }
    }
}
