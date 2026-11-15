//! knos-oidc, second deployment: OIDC on Solana. Verifies an RS256 token from GitHub Actions, GitLab CI or any other
//! RS256 issuer on chain, so that any program can require a fact the issuer signed ("this workflow, at this commit,
//! ran in this repository and said X") with no oracle.
//!
//! What it trusts is in pins.rs: GitHub's four keys of 2 Oct 2026, and after them only a key that GitHub's own
//! signature names (RegisterKey). Such a key waits a day and the guardian's approval before it verifies anything,
//! and every key expires 30 days after it was registered or last named by GitHub's signature (Refresh). That
//! signature is itself verified here under one of GitHub's keys, so one of them has to be refreshed in every 30
//! days: once the last one has expired nothing can be attested, and nothing verifies.
//!
//! Who can change what:
//!   - Anyone: write, verify and close their own token accounts; register or refresh a key that an attestation
//!     names; produce the attestation that refreshes a key, by running the pinned rotate workflow by hand in a
//!     repository of their own (it adds no key); send a key's Montgomery constants (they are checked here).
//!   - Any wallet: register a PRIVATE key of its own (RegisterPrivateKey), renew it and revoke it. Such a key is
//!     marked private with that wallet's address in the key account and in every token account it verifies, and
//!     is never GitHub's, GitLab's or an attested issuer's.
//!   - The guardian (pins::GUARDIAN, a multisig vault) can approve a key that an attestation admitted and can
//!     revoke any key, for ever. It cannot add a key (that takes GitHub's signature), cannot change a delay or an
//!     expiry, cannot undo a revocation, and has no instruction that touches a token account or moves anything
//!     else. So on its own it can stop tokens from verifying, and it cannot make this program accept a token the
//!     issuer did not sign.
//!   - The upgrade authority (a second multisig vault): the program is upgradeable only through that multisig, with
//!     a public 48-hour delay, until an outside review. After the review the upgrade authority is removed.
//!
//! Instructions (first byte is the tag):
//!   0 Write        payer(s,w) token(w) system            data: id[32] total u16 offset u16 chunk
//!                  Writes the token (the compact JWT) into the PDA ["tok", payer, id]; created on first use, sized
//!                  for `total` bytes (at most MAX_JWT). Chunks may be sent in any order, several per transaction.
//!   1 Step         payer(s) token(w) key                 data: id[32] squarings u8
//!                  Computes s^65537 mod n in steps: the first call puts the signature in Montgomery form, each call
//!                  does up to `squarings` of the 16 squarings, and the call that finishes them checks the PKCS#1
//!                  v1.5 SHA-256 encoding against sha256(header.payload), that alg is RS256 and that `iss` is the
//!                  key's issuer, then decodes the payload in place and marks the account VERIFIED.
//!                  Every call refuses a key that is not usable now: not ready, revoked, neither a genesis key nor
//!                  approved, before its active_at, or at or past its expires_at.
//!                  The finishing call refuses a token whose `exp` is more than AHEAD (a day) ahead of the clock.
//!                  2048-bit keys: Step(8), Step(8). 4096-bit keys: Step(2), Step(3) three times, Step(4), Step(1):
//!                  the finishing call also hashes and decodes the whole token, so it is given one squaring only.
//!   2 Close        payer(s,w) token(w)                   data: id[32]        (the rent goes back to the payer)
//!   3 RegisterKey  payer(s,w) key(w) system [attest attest_key]   data: issuer u8, n (256 or 512 bytes, big-endian)
//!                  Creates ["key", [issuer], sha256(n)]. A hash in GENESIS: usable at once (after KeyParams), until
//!                  now + KEY_TTL. Any other hash needs `attest`: a VERIFIED GitHub token, at most an hour past its
//!                  expiry, of the pinned rotate workflow (job_workflow_ref, job_workflow_sha), run on a
//!                  GitHub-hosted runner by the schedule or by hand (event_name) in one of the attester's
//!                  repositories (repository_owner_id, repository_id), whose audience is
//!                  "knos-oidc:key:<issuer>:<sha256(n) hex>"; and `attest_key`: the key account that verified it
//!                  (the one the token account names), which must be usable NOW, by the rule Step applies. That key
//!                  verifies from now + KEY_DELAY, and only once the guardian has approved it; it expires KEY_TTL
//!                  after that time. Anyone may send it.
//!   4 KeyParams    payer(s) key(w)                       data: n0inv u32, r2 (as long as n, big-endian)
//!                  The key's Montgomery constants, checked on chain; the key is ready after this. Anyone may send it.
//!   5 Refresh      payer(s) key(w) attest attest_key
//!                  The same attestation, with the key account that verified it, for a key that exists and is not
//!                  revoked: its expiry becomes now + KEY_TTL if that is later. It never moves an expiry earlier.
//!                  For Refresh, and never for RegisterKey, the run may also be ANYONE's: the same workflow file at
//!                  the same commit on a GitHub-hosted runner, started by hand (workflow_dispatch) in a repository
//!                  owned by the person who started it (repository_owner_id == actor_id). So the keys the issuer
//!                  still publishes stay alive without the attester's schedule. Anyone may send it. `attest_key` may be `key` itself while it is usable; a key that has expired
//!                  is refreshed by an attestation verified under another key that has not.
//!   6 Approve      guardian(s) key(w)
//!                  Marks a key approved. Refused for a revoked key, and for a private key.
//!   7 Revoke       guardian(s) key(w)
//!                  Marks a key revoked, for ever: no instruction clears the mark, and the account stays, so the
//!                  same modulus can never be registered for that issuer again. The wallet that registered a
//!                  private key may revoke that key in the guardian's place.
//!   8 RegisterIssuerKey  payer(s,w) key(w) iss(w) system attest attest_key
//!                  data: url_len u8, the issuer's URL (its `iss`, "https://...", at most MAX_ISS bytes), n
//!                  Any RS256 issuer. Creates ["ikey", sha256(url), sha256(n)] and, with the issuer's first key,
//!                  ["iss", sha256(url)], which holds the URL text. The attestation is RegisterKey's (the attester's
//!                  run of the pinned rotate workflow, which fetched the issuer's key set over TLS on a
//!                  GitHub-hosted runner; never anyone's run), with the audience
//!                  "knos-oidc:ikey:<sha256(url) hex>:<sha256(n) hex>". The same delay, approval, expiry, Refresh
//!                  (with that audience) and revocation as any attested key. Step under such a key requires the
//!                  token's `iss` to be that URL (it compares sha256(iss) with the hash the key account carries),
//!                  marks the token account ISSUER_OTHER and writes the issuer's hash into it (T_IHASH): never
//!                  GitHub's or GitLab's number, so a consumer that asks for one of those is not answered by this.
//!   9 RegisterPrivateKey  registrant(s,w) key(w) system    data: url_len u8, the issuer's URL, n
//!                  A PRIVATE key: any wallet registers it, with no attestation, for an issuer no public runner can
//!                  reach (a company's GitHub Enterprise Server). Creates ["pkey", registrant, sha256(url),
//!                  sha256(n)], issuer ISSUER_PRIVATE, flagged F_PRIVATE, with the registrant's address after the
//!                  issuer's hash; usable at once (after KeyParams) until now + KEY_TTL. Sent again by the same
//!                  wallet for the same key it moves the expiry to now + KEY_TTL. The registrant or the guardian
//!                  revokes it (Revoke). NOBODY vouches for such a key: it says what its registrant says. So Step
//!                  under it marks the token account ISSUER_PRIVATE and writes the registrant into it
//!                  (T_REGISTRANT), a private key is never a GitHub or GitLab key by number, its tokens attest
//!                  nothing here (RegisterKey, RegisterIssuerKey and Refresh refuse them), the guardian cannot
//!                  approve one into anything else, and every consumer must ask `is_private` and accept such a
//!                  token only from the registrant it itself trusts for that purpose.
//!
//! A consumer program takes the token account, checks that its owner is this program, and calls `verified(&data)`
//! for the issuer, the expiry and the decoded payload, then reads claims with `claims::fields`. That reader passes
//! over the values it is not asked for (it is 2.1's, unchanged, so that a consumer built from this tree is the build
//! it was); the strict one is strict.rs, which Step reads the header and the payload with before it writes VERIFIED.
//! So a payload that is VERIFIED is one JSON object of RFC 8259 in every byte, no name twice at its top level, and
//! no payload that is not ever reaches the account a consumer reads. Replay protection
//! (and the expiry check against the clock, `fresh`) is the consumer's: the same token can be verified into any
//! number of accounts. A token account that is VERIFIED stays so if its key is revoked or expires afterwards.
//! `fresh` bounds that to an hour past the token's own expiry, and Step bounds that expiry to AHEAD past the moment
//! the key was last asked about: whatever expiry its signer wrote, no token account passes `fresh` more than
//! AHEAD + LATE (25 hours) after its key stopped being usable. A consumer that wants no such tail takes the key
//! account the token names (T_KEY) and asks `key_usable` itself. RegisterKey and Refresh do exactly that for their
//! attestation (`attest_key`): a token verified under a key that has since been revoked or has expired attests
//! nothing from that second on.
pub mod claims;
pub mod strict;
pub mod pins;
pub mod rsa; pub mod es256;

use claims::{err, number, text};
use strict::fields;
use solana_program::{
    account_info::{next_account_info, AccountInfo},
    clock::Clock,
    entrypoint::ProgramResult,
    hash::hashv,
    program::invoke_signed,
    program_error::ProgramError,
    pubkey::Pubkey,
    rent::Rent,
    system_instruction, system_program,
    sysvar::Sysvar,
};

/// The version of this program, as the documents and the upgrade proposals name it. 2.2: every byte of a token's
/// header and payload is checked as JSON (strict.rs), where 2.1 passed over the values it did not read. The build
/// carries it in its security.txt (`source_release`), so it can be read from the deployed bytes.
pub const VERSION: &str = "2.2";
pub const MAX_JWT: usize = 8192;
/// How long after its `exp` a token is still accepted, here and by consumers that call `fresh`. The issuers' tokens
/// live five minutes, which is shorter than it can take a public relay to find one and land several transactions.
/// A token is not a bearer secret in this design: its audience names one action, and every consumer keeps its own
/// replay guard, so an hour of lateness gives a reader of the token nothing but the gas bill.
pub const LATE: i64 = 3600;
pub fn fresh(exp: i64, now: i64) -> bool { now < exp.saturating_add(LATE) }
/// How far ahead of the clock a token's `exp` may be when Step finishes. `exp` is whatever the holder of the key
/// signed, and a key is asked about while Step runs and never again. Without this bound the holder of a leaked key
/// could verify a token that expires in a hundred years, and the account would pass `fresh` for a hundred years after
/// the guardian revoked the key: as an attestation it would refresh and register keys all that time. With it, a
/// token account is of no use AHEAD + LATE after its last Step. An issuer's own token is far inside the bound.
pub const AHEAD: i64 = 86_400;
// token account: stage u8 (0 writing, 1 stepping, 2 VERIFIED), issuer u8, squarings done u8, limbs u8, jwt_len u16,
// payload_off u16, payload_len u16, exp i64, key[32], payer[32], id[32], x (the running power, 512 bytes), jwt
pub const T_STAGE: usize = 0;
pub const T_ISSUER: usize = 1;
pub const T_DONE: usize = 2;
pub const T_LIMBS: usize = 3;
pub const T_LEN: usize = 4;
pub const T_POFF: usize = 6;
pub const T_PLEN: usize = 8;
pub const T_EXP: usize = 10;
pub const T_KEY: usize = 18;
pub const T_PAYER: usize = 50;
pub const T_ID: usize = 82;
pub const T_X: usize = 114;
pub const T_JWT: usize = 626;
pub const VERIFIED: u8 = 2;
/// A VERIFIED token account whose issuer is not one of the two numbered ones: the running power is of no more use,
/// and its first 64 bytes become sha256 of the issuer's URL (T_IHASH) and, for a private key, the wallet that
/// registered it (T_REGISTRANT; zero otherwise). A token of GitHub's or GitLab's keeps the bytes it always had.
pub const T_IHASH: usize = T_X;
pub const T_REGISTRANT: usize = T_X + 32;
// key account: state u8 (0 created, 1 ready: Montgomery constants checked), issuer u8, limbs u8, bump u8, n0inv u32,
// active_at i64, expires_at i64, flags u8, 15 zero bytes, then n (limbs, LE) and r2 (limbs, LE). A key whose issuer
// is not one of the two numbered ones (issuer >= ISSUER_OTHER) has KEY_TAIL more bytes after r2: sha256 of the
// issuer's URL, then the wallet that registered a private key (zero for a key an attestation admitted). The keys of
// GitHub and GitLab have the layout and the addresses they always had.
// An issuer account ["iss", sha256(url)]: 3 u8, bump u8, 0 u8, url_len u8, then the URL. Its first byte is never a
// token's VERIFIED or a key's state, and its third is never a limb count.
// Both kinds of account are owned by this program. They are told apart by their first and third bytes: a key's state
// is never 2, so `verified` never reads a key account as a token; a token's third byte counts squarings (at most
// 16) where a key's holds its limb count (64 or 128), so a token account is never read as a key.
pub const K_STATE: usize = 0;
pub const K_ISSUER: usize = 1;
pub const K_LIMBS: usize = 2;
pub const K_BUMP: usize = 3;
pub const K_N0INV: usize = 4;
pub const K_ACTIVE: usize = 8;
pub const K_EXPIRES: usize = 16;
pub const K_FLAGS: usize = 24;
pub const K_HDR: usize = 40;
pub const KEY_TAIL: usize = 64;
pub const ISS_STATE: u8 = 3;
pub const ISS_HDR: usize = 4;
/// The longest issuer URL. GitHub Enterprise Server's is "https://<host>/_services/token".
pub const MAX_ISS: usize = 200;
pub const F_APPROVED: u8 = 1;
pub const F_REVOKED: u8 = 2;
pub const F_GENESIS: u8 = 4;
/// Registered by a wallet with no attestation (RegisterPrivateKey): the wallet is in the key account's last 32 bytes.
pub const F_PRIVATE: u8 = 8;

// errors: 60-63 in claims.rs (63 also from Step: `exp` more than AHEAD ahead of the clock); 64 token too long or
// chunk out of range; 65 signature length or range; 66 key parameters; 67 accounts; 68 not a key of this program
// (for Step: not a ready one, or not the one the token started with); 69 wrong stage; 70 bad signature; 71 alg is
// not RS256; 72 issuer; 73 key not in genesis and no valid attestation; 74 attestation claims; 75 attestation
// expired; 76 key not active yet (its delay has not passed, or the guardian has not approved it); 77 key expired;
// 78 key revoked; 79 not the guardian
pub const E_LEN: u32 = 64;
pub const E_SIG: u32 = 65;
pub const E_PARAMS: u32 = 66;
pub const E_ACCOUNTS: u32 = 67;
pub const E_KEY: u32 = 68;
pub const E_STAGE: u32 = 69;
pub const E_BADSIG: u32 = 70;
pub const E_ALG: u32 = 71;
pub const E_ISS: u32 = 72;
pub const E_UNTRUSTED: u32 = 73;
pub const E_ATTEST: u32 = 74;
pub const E_EXPIRED: u32 = 75;
pub const E_INACTIVE: u32 = 76;
pub const E_KEY_EXPIRED: u32 = 77;
pub const E_REVOKED: u32 = 78;
pub const E_GUARDIAN: u32 = 79;

#[cfg(not(feature = "no-entrypoint"))]
solana_program::entrypoint!(process);

#[cfg(not(feature = "no-entrypoint"))]
solana_security_txt::security_txt! {
    name: "knos-oidc",
    project_url: "https://github.com/drexthealpha/Knos",
    contacts: "link:https://github.com/drexthealpha/Knos/security/advisories/new",
    policy: "https://github.com/drexthealpha/Knos/blob/main/SECURITY.md",
    source_code: "https://github.com/drexthealpha/Knos",
    source_release: "knos-oidc 2.2"
}

/// What a consumer reads from a token account it has checked is owned by this program: None unless VERIFIED.
/// `issuer` is ISSUER_GITHUB or ISSUER_GITLAB for a token one of their keys verified, and ISSUER_OTHER for any other
/// issuer: then `issuer_hash` says which. A consumer names the issuers it accepts; none is accepted by default.
pub struct Verified<'a> { pub issuer: u8, pub exp: i64, pub payload: &'a [u8] }
pub fn verified(d: &[u8]) -> Option<Verified<'_>> {
    if d.len() < T_JWT || d[T_STAGE] != VERIFIED { return None; }
    let off = u16::from_le_bytes([d[T_POFF], d[T_POFF + 1]]) as usize;
    let len = u16::from_le_bytes([d[T_PLEN], d[T_PLEN + 1]]) as usize;
    let payload = d.get(off..off + len)?;
    Some(Verified { issuer: d[T_ISSUER], exp: i64::from_le_bytes(d[T_EXP..T_EXP + 8].try_into().ok()?), payload })
}

/// sha256 of the issuer's URL, for a VERIFIED token account whose issuer is not GitHub or GitLab by number.
pub fn issuer_hash(d: &[u8]) -> Option<&[u8; 32]> {
    if d.len() < T_JWT || d[T_STAGE] != VERIFIED || d[T_ISSUER] < pins::ISSUER_OTHER { return None; }
    d[T_IHASH..T_IHASH + 32].try_into().ok()
}

/// Whether a VERIFIED token account was verified under a private key: one a wallet registered with no attestation.
/// Such a token says what that wallet says and nothing more; `registrant` is the wallet.
pub fn is_private(d: &[u8]) -> bool { d.len() >= T_JWT && d[T_STAGE] == VERIFIED && d[T_ISSUER] == pins::ISSUER_PRIVATE }
pub fn registrant(d: &[u8]) -> Option<&[u8; 32]> {
    if !is_private(d) { return None; }
    d[T_REGISTRANT..T_REGISTRANT + 32].try_into().ok()
}

/// Whether a ready key may verify at `now`, from its flags and times: Ok, or the error code Step returns. A revoked
/// key is refused whatever else is true of it; then a key that is not active yet; then one that has expired.
/// A private key needs nobody's approval: what it is worth is the consumer's question (`is_private`), not this one's.
pub fn key_usable(flags: u8, active_at: i64, expires_at: i64, now: i64) -> Result<(), u32> {
    if flags & F_REVOKED != 0 { return Err(E_REVOKED); }
    if flags & (F_GENESIS | F_APPROVED | F_PRIVATE) == 0 || now < active_at { return Err(E_INACTIVE); }
    if now >= expires_at { return Err(E_KEY_EXPIRED); }
    Ok(())
}

fn i64_at(d: &[u8], at: usize) -> i64 { i64::from_le_bytes(d[at..at + 8].try_into().unwrap()) }
fn put_i64(d: &mut [u8], at: usize, v: i64) { d[at..at + 8].copy_from_slice(&v.to_le_bytes()); }

fn create_pda<'a>(payer: &AccountInfo<'a>, acct: &AccountInfo<'a>, sys: &AccountInfo<'a>, program_id: &Pubkey,
                  space: usize, seeds: &[&[u8]]) -> ProgramResult {
    let need = Rent::get()?.minimum_balance(space);
    // an address can be sent lamports before it exists: top up, allocate and assign instead of create_account
    let have = acct.lamports();
    if have < need {
        solana_program::program::invoke(&system_instruction::transfer(payer.key, acct.key, need - have), &[payer.clone(), acct.clone(), sys.clone()])?;
    }
    invoke_signed(&system_instruction::allocate(acct.key, space as u64), &[acct.clone(), sys.clone()], &[seeds])?;
    invoke_signed(&system_instruction::assign(acct.key, program_id), &[acct.clone(), sys.clone()], &[seeds])
}

/// The limb count of a key account of this program, created or ready; E_KEY for any other account.
fn key_limbs(program_id: &Pubkey, key: &AccountInfo) -> Result<usize, ProgramError> {
    if key.owner != program_id { return Err(err(E_KEY)); }
    let d = key.try_borrow_data()?;
    let l = if d.len() >= K_HDR { d[K_LIMBS] as usize } else { 0 };
    if (l != 64 && l != 128) || d.len() != K_HDR + 8 * l + key_tail(d[K_ISSUER]) { return Err(err(E_KEY)); }
    Ok(l)
}
/// How many bytes follow r2 in a key account of this issuer number.
fn key_tail(issuer: u8) -> usize { if issuer >= pins::ISSUER_OTHER { KEY_TAIL } else { 0 } }

struct Key { issuer: u8, l: usize, n0inv: u32, n: Vec<u32>, r2: Vec<u32>, tail: [u8; KEY_TAIL] }
/// A ready key of this program that may verify at `now`.
fn load_key(program_id: &Pubkey, key: &AccountInfo, now: i64) -> Result<Key, ProgramError> {
    let l = key_limbs(program_id, key)?;
    let d = key.try_borrow_data()?;
    if d[K_STATE] != 1 { return Err(err(E_KEY)); }
    key_usable(d[K_FLAGS], i64_at(&d, K_ACTIVE), i64_at(&d, K_EXPIRES), now).map_err(err)?;
    let (mut n, mut r2) = (vec![0u32; l], vec![0u32; l]);
    rsa::load(&d[K_HDR..], &mut n);
    rsa::load(&d[K_HDR + 4 * l..], &mut r2);
    let mut tail = [0u8; KEY_TAIL];
    if key_tail(d[K_ISSUER]) != 0 { tail.copy_from_slice(&d[K_HDR + 8 * l..]); }
    Ok(Key { issuer: d[K_ISSUER], l, n0inv: u32::from_le_bytes(d[K_N0INV..K_N0INV + 4].try_into().unwrap()), n, r2, tail })
}

/// "knos-oidc:key:<issuer>:<kh hex>": what the rotate workflow asks GitHub to sign for a key of GitHub's or GitLab's.
fn key_audience(issuer: u8, kh: &[u8; 32]) -> Vec<u8> {
    let mut want = Vec::with_capacity(80);
    want.extend_from_slice(b"knos-oidc:key:");
    want.push(b'0' + issuer);
    want.push(b':');
    push_hex(&mut want, kh);
    want
}
/// "knos-oidc:ikey:<sha256(url) hex>:<kh hex>": the same for a key of any other issuer.
fn ikey_audience(ih: &[u8; 32], kh: &[u8; 32]) -> Vec<u8> {
    let mut want = Vec::with_capacity(144);
    want.extend_from_slice(b"knos-oidc:ikey:");
    push_hex(&mut want, ih);
    want.push(b':');
    push_hex(&mut want, kh);
    want
}
fn push_hex(out: &mut Vec<u8>, h: &[u8; 32]) {
    let mut hx = [0u8; 64];
    claims::hex_into(h, &mut hx);
    out.extend_from_slice(&hx);
}

/// The issuer's URL and the modulus of RegisterIssuerKey's data: url_len u8, url, n. The URL is what the issuer
/// writes as `iss`: "https://", printable ASCII with no quote and no backslash (so it has one spelling in JSON).
fn url_and_modulus(rest: &[u8]) -> Result<(&[u8], &[u8]), ProgramError> {
    let (&ul, rest) = rest.split_first().ok_or(ProgramError::InvalidInstructionData)?;
    let ul = ul as usize;
    if rest.len() != ul + 256 && rest.len() != ul + 512 { return Err(ProgramError::InvalidInstructionData); }
    let (url, n_be) = rest.split_at(ul);
    let plain = url.iter().all(|&c| (0x21..0x7f).contains(&c) && c != b'"' && c != b'\\');
    if ul > MAX_ISS || url.len() <= 8 || !url.starts_with(b"https://") || !plain { return Err(err(E_ISS)); }
    Ok((url, n_be))
}
/// The limbs of a modulus a key account may hold: odd, and as long as it says (its top bit set).
fn modulus(n_be: &[u8]) -> Result<Vec<u32>, ProgramError> {
    let mut n = vec![0u32; n_be.len() / 4];
    rsa::be_to_limbs(n_be, &mut n);
    if n[0] & 1 == 0 || n[n.len() - 1] >> 31 == 0 { return Err(err(E_PARAMS)); }
    Ok(n)
}

/// GitHub's own signature names the key (issuer, kh): `attest` is a VERIFIED, fresh GitHub token of the pinned
/// rotate workflow, run on a GitHub-hosted runner by the schedule or by hand in one of the attester's repositories,
/// whose audience is `want` (`key_audience`, `ikey_audience`). What the workflow's own code did is as trustworthy as the
/// account it ran in, which is why the account and the repository are part of the rule and not only the file.
/// `akey` is the key account that verified the token (the token account names it) and must be usable now: a
/// VERIFIED account outlives its key by up to AHEAD + LATE, and an attestation must not.
#[inline(never)]
fn attested(program_id: &Pubkey, attest: &AccountInfo, akey: &AccountInfo, want: &[u8], refresh: bool, now: i64) -> ProgramResult {
    if attest.owner != program_id { return Err(err(E_UNTRUSTED)); }
    let ad = attest.try_borrow_data()?;
    let v = verified(&ad).ok_or_else(|| err(E_UNTRUSTED))?;
    attest_key_usable(program_id, &ad, akey, now)?;
    if v.issuer != pins::ISSUER_GITHUB { return Err(err(E_ATTEST)); }
    if !fresh(v.exp, now) { return Err(err(E_EXPIRED)); }
    let [wref, wsha, runner, owner, repo, event, actor, aud] = fields(v.payload, [b"job_workflow_ref", b"job_workflow_sha",
        b"runner_environment", b"repository_owner_id", b"repository_id", b"event_name", b"actor_id", b"aud"])?;
    let (wref, wsha, event) = (text(wref)?, text(wsha)?, text(event)?);
    let sha_ok = wsha == pins::ROTATE_SHA || wsha == pins::ROTATE_SHA2 || pins::TEST_ROTATE_SHA.is_some_and(|t| wsha == t);
    if !wref.starts_with(pins::ROTATE_REF) || !sha_ok || text(runner)? != b"github-hosted" { return Err(err(E_ATTEST)); }
    let owner = number(owner)?;
    let by_attester = pins::attester(owner, number(repo)?) && pins::ATTEST_EVENTS.iter().any(|e| *e == &event[..]);
    // Refresh only: the same file at the same commit, started by hand in a repository of the person who started it
    let by_anyone = refresh && event == pins::ANYONE_EVENT && number(actor).ok() == Some(owner);
    if !by_attester && !by_anyone { return Err(err(E_ATTEST)); }
    if text(aud)? != want { return Err(err(E_ATTEST)); }
    Ok(())
}

/// `akey` is the ready key account of this program that the VERIFIED token account `tok` names, and it may verify
/// at `now`: E_KEY for any other account, the key's own code (76, 77, 78) when it is not usable.
fn attest_key_usable(program_id: &Pubkey, tok: &[u8], akey: &AccountInfo, now: i64) -> ProgramResult {
    if akey.key.as_ref() != &tok[T_KEY..T_KEY + 32] { return Err(err(E_KEY)); }
    key_limbs(program_id, akey)?;
    let d = akey.try_borrow_data()?;
    if d[K_STATE] != 1 { return Err(err(E_KEY)); }
    // only a key of GitHub's by number attests: not a private key, whatever URL its registrant gave it
    if d[K_ISSUER] != pins::ISSUER_GITHUB || d[K_FLAGS] & F_PRIVATE != 0 { return Err(err(E_ATTEST)); }
    key_usable(d[K_FLAGS], i64_at(&d, K_ACTIVE), i64_at(&d, K_EXPIRES), now).map_err(err)
}

/// The wallet that registered `key`, when it is a private key of this program.
fn registrant_of(program_id: &Pubkey, key: &AccountInfo) -> Option<Pubkey> {
    let l = key_limbs(program_id, key).ok()?;
    let d = key.try_borrow_data().ok()?;
    if d[K_FLAGS] & F_PRIVATE == 0 || d[K_ISSUER] != pins::ISSUER_PRIVATE { return None; }
    Some(Pubkey::new_from_array(d[K_HDR + 8 * l + 32..K_HDR + 8 * l + 64].try_into().ok()?))
}

fn token_account(program_id: &Pubkey, payer: &Pubkey, id: &[u8], tok: &AccountInfo) -> Result<u8, ProgramError> {
    let (k, bump) = Pubkey::find_program_address(&[b"tok", payer.as_ref(), id], program_id);
    if *tok.key != k { return Err(err(E_ACCOUNTS)); }
    Ok(bump)
}

pub fn process(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let (&tag, rest) = data.split_first().ok_or(ProgramError::InvalidInstructionData)?;
    let it = &mut accounts.iter();
    match tag {
        0 => {
            let payer = next_account_info(it)?; let tok = next_account_info(it)?; let sys = next_account_info(it)?;
            if rest.len() < 36 { return Err(ProgramError::InvalidInstructionData); }
            let id = &rest[0..32];
            let total = u16::from_le_bytes([rest[32], rest[33]]) as usize;
            let off = u16::from_le_bytes([rest[34], rest[35]]) as usize;
            let chunk = &rest[36..];
            if total == 0 || total > MAX_JWT || off + chunk.len() > total { return Err(err(E_LEN)); }
            if !payer.is_signer || !payer.is_writable || *sys.key != system_program::ID { return Err(err(E_ACCOUNTS)); }
            let bump = token_account(program_id, payer.key, id, tok)?;
            if tok.owner != program_id {
                if !tok.data_is_empty() || *tok.owner != system_program::ID { return Err(err(E_ACCOUNTS)); }
                create_pda(payer, tok, sys, program_id, T_JWT + total, &[b"tok", payer.key.as_ref(), id, &[bump]])?;
                let mut d = tok.try_borrow_mut_data()?;
                d[T_LEN..T_LEN + 2].copy_from_slice(&(total as u16).to_le_bytes());
                d[T_PAYER..T_PAYER + 32].copy_from_slice(payer.key.as_ref());
                d[T_ID..T_ID + 32].copy_from_slice(id);
            }
            let mut d = tok.try_borrow_mut_data()?;
            if d.len() != T_JWT + total || d[T_STAGE] != 0 { return Err(err(E_STAGE)); }
            d[T_JWT + off..T_JWT + off + chunk.len()].copy_from_slice(chunk);
            Ok(())
        }
        1 => {
            let payer = next_account_info(it)?; let tok = next_account_info(it)?; let key = next_account_info(it)?;
            if rest.len() != 33 { return Err(ProgramError::InvalidInstructionData); }
            if !payer.is_signer { return Err(err(E_ACCOUNTS)); }
            token_account(program_id, payer.key, &rest[0..32], tok)?;
            if tok.owner != program_id { return Err(err(E_ACCOUNTS)); }
            // every call asks again whether the key may be used: a key revoked or expired between two calls stops here
            let now = Clock::get()?.unix_timestamp;
            let k = load_key(program_id, key, now)?;
            let l = k.l;
            let mut d = tok.try_borrow_mut_data()?;
            let len = u16::from_le_bytes([d[T_LEN], d[T_LEN + 1]]) as usize;
            if d.len() != T_JWT + len || d[T_STAGE] == VERIFIED { return Err(err(E_STAGE)); }
            let [hp, pp, sp] = claims::split_jwt(&d[T_JWT..T_JWT + len])?;
            // the signature: exactly as long as the modulus, and below it
            let mut sig = vec![0u8; 4 * l];
            if claims::b64_len(sp.1 - sp.0) != Some(4 * l) { return Err(err(E_SIG)); }
            strict::b64url_into(&d[T_JWT + sp.0..T_JWT + sp.1], &mut sig)?;
            let mut s = vec![0u32; l];
            rsa::be_to_limbs(&sig, &mut s);
            if rsa::geq(&s, &k.n) { return Err(err(E_SIG)); }
            let mut t = vec![0u32; 2 * l + 2];
            let (mut x, mut y) = (vec![0u32; l], vec![0u32; l]);
            if d[T_STAGE] == 0 {
                rsa::mont_mul(&mut x, &s, &k.r2, &k.n, k.n0inv, &mut t); // s in Montgomery form
                d[T_STAGE] = 1; d[T_DONE] = 0; d[T_ISSUER] = k.issuer; d[T_LIMBS] = l as u8;
                d[T_KEY..T_KEY + 32].copy_from_slice(key.key.as_ref());
            } else {
                if d[T_KEY..T_KEY + 32] != key.key.as_ref()[..] { return Err(err(E_KEY)); }
                rsa::load(&d[T_X..], &mut x);
            }
            let todo = (rest[32] as usize).min(16 - d[T_DONE] as usize);
            for _ in 0..todo {
                rsa::mont_sqr(&mut y, &x, &k.n, k.n0inv, &mut t);
                core::mem::swap(&mut x, &mut y);
            }
            d[T_DONE] += todo as u8;
            rsa::store(&mut d[T_X..], &x);
            if d[T_DONE] < 16 { return Ok(()); }
            // x = (s^65536) in Montgomery form; times s (plain) gives s^65537
            rsa::mont_mul(&mut y, &x, &s, &k.n, k.n0inv, &mut t);
            rsa::limbs_to_be(&y, &mut sig);
            let digest = hashv(&[&d[T_JWT..T_JWT + pp.1]]).to_bytes();
            if !rsa::pkcs1_sha256_ok(&sig, &digest) { return Err(err(E_BADSIG)); }
            let hl = claims::b64_len(hp.1 - hp.0).ok_or_else(|| err(claims::E_B64))?;
            let mut header = vec![0u8; hl];
            strict::b64url_into(&d[T_JWT + hp.0..T_JWT + hp.1], &mut header)?;
            let [alg] = fields(&header, [b"alg"])?;
            if text(alg)? != b"RS256" { return Err(err(E_ALG)); }
            let poff = T_JWT + pp.0;
            let plen = strict::b64url_in_place(&mut d, poff, pp.1 - pp.0)?;
            // strict::fields, here and for the header above: the payload is refused unless every byte of it is JSON
            // (RFC 8259). Nothing below writes VERIFIED for a payload it refused, so a consumer, whose reader
            // (claims::fields) passes over the values it does not read, is never handed one.
            let exp = {
                let [iss, exp] = fields(&d[poff..poff + plen], [b"iss", b"exp"])?;
                let iss = text(iss)?;
                // a numbered issuer's URL is a constant; any other key carries the hash of its issuer's URL
                let ours = match pins::ISSUERS.get(k.issuer as usize) { Some(url) => iss == *url, None => hashv(&[&iss]).to_bytes() == k.tail[..32] };
                if !ours { return Err(err(E_ISS)); }
                match exp { Some(r) if !r.is_str => claims::parse_u64(r.bytes).ok_or_else(|| err(claims::E_CLAIM))? as i64, _ => return Err(err(claims::E_CLAIM)) }
            };
            // the key was usable a moment ago (load_key): a token verified now is fresh for at most AHEAD + LATE more
            if exp > now.saturating_add(AHEAD) { return Err(err(claims::E_CLAIM)); }
            d[T_POFF..T_POFF + 2].copy_from_slice(&(poff as u16).to_le_bytes());
            d[T_PLEN..T_PLEN + 2].copy_from_slice(&(plen as u16).to_le_bytes());
            d[T_EXP..T_EXP + 8].copy_from_slice(&exp.to_le_bytes());
            if k.issuer >= pins::ISSUER_OTHER { d[T_IHASH..T_IHASH + KEY_TAIL].copy_from_slice(&k.tail); }
            d[T_STAGE] = VERIFIED;
            Ok(())
        }
        2 => {
            let payer = next_account_info(it)?; let tok = next_account_info(it)?;
            if rest.len() != 32 || !payer.is_signer || !payer.is_writable { return Err(err(E_ACCOUNTS)); }
            token_account(program_id, payer.key, rest, tok)?;
            if tok.owner != program_id { return Err(err(E_ACCOUNTS)); }
            **payer.try_borrow_mut_lamports()? = payer.lamports().checked_add(tok.lamports()).ok_or(ProgramError::ArithmeticOverflow)?;
            **tok.try_borrow_mut_lamports()? = 0;
            tok.resize(0)?;
            tok.assign(&system_program::ID);
            Ok(())
        }
        3 => {
            let payer = next_account_info(it)?; let key = next_account_info(it)?; let sys = next_account_info(it)?;
            if rest.len() != 1 + 256 && rest.len() != 1 + 512 { return Err(ProgramError::InvalidInstructionData); }
            let (issuer, n_be) = (rest[0], &rest[1..]);
            if issuer as usize >= pins::ISSUERS.len() { return Err(err(E_ISS)); }
            if !payer.is_signer || !payer.is_writable || *sys.key != system_program::ID { return Err(err(E_ACCOUNTS)); }
            let l = n_be.len() / 4;
            let kh = hashv(&[n_be]).to_bytes();
            let (kk, bump) = Pubkey::find_program_address(&[b"key", &[issuer], &kh], program_id);
            // a key account is never closed, so a hash that was registered once (and perhaps revoked) stops here
            if *key.key != kk || !key.data_is_empty() || *key.owner != system_program::ID { return Err(err(E_ACCOUNTS)); }
            let now = Clock::get()?.unix_timestamp;
            let genesis = pins::GENESIS.iter().chain(pins::TEST_GENESIS.iter()).any(|(i, g)| *i == issuer && *g == kh);
            if !genesis {
                let attest = next_account_info(it).map_err(|_| err(E_UNTRUSTED))?;
                attested(program_id, attest, next_account_info(it)?, &key_audience(issuer, &kh), false, now)?;
            }
            let n = modulus(n_be)?;
            create_pda(payer, key, sys, program_id, K_HDR + 8 * l, &[b"key", &[issuer], &kh, &[bump]])?;
            // a genesis key is the root and works at once; a key GitHub's signature admitted waits, and needs approval
            let (active, flags) = if genesis { (now, F_GENESIS | F_APPROVED) } else { (now.saturating_add(pins::KEY_DELAY), 0) };
            let mut d = key.try_borrow_mut_data()?;
            d[K_ISSUER] = issuer; d[K_LIMBS] = l as u8; d[K_BUMP] = bump; d[K_FLAGS] = flags;
            put_i64(&mut d, K_ACTIVE, active);
            put_i64(&mut d, K_EXPIRES, active.saturating_add(pins::KEY_TTL));
            rsa::store(&mut d[K_HDR..], &n);
            Ok(())
        }
        4 => {
            let payer = next_account_info(it)?; let key = next_account_info(it)?;
            if !payer.is_signer || key.owner != program_id { return Err(err(E_ACCOUNTS)); }
            let mut d = key.try_borrow_mut_data()?;
            if d.len() < K_HDR || d[K_STATE] != 0 { return Err(err(E_STAGE)); }
            let l = d[K_LIMBS] as usize;
            if d.len() != K_HDR + 8 * l + key_tail(d[K_ISSUER]) || rest.len() != 4 + 4 * l { return Err(ProgramError::InvalidInstructionData); }
            let n0inv = u32::from_le_bytes(rest[0..4].try_into().unwrap());
            let (mut n, mut r2) = (vec![0u32; l], vec![0u32; l]);
            rsa::load(&d[K_HDR..], &mut n);
            rsa::be_to_limbs(&rest[4..], &mut r2);
            let (mut a, mut b, mut t) = (vec![0u32; l], vec![0u32; l], vec![0u32; l + 2]);
            if !rsa::params_ok(&n, &r2, n0inv, &mut a, &mut b, &mut t) { return Err(err(E_PARAMS)); }
            d[K_N0INV..K_N0INV + 4].copy_from_slice(&n0inv.to_le_bytes());
            rsa::store(&mut d[K_HDR + 4 * l..], &r2);
            d[K_STATE] = 1;
            Ok(())
        }
        5 => {
            let payer = next_account_info(it)?; let key = next_account_info(it)?; let attest = next_account_info(it)?;
            let akey = next_account_info(it)?;
            if !rest.is_empty() { return Err(ProgramError::InvalidInstructionData); }
            if !payer.is_signer { return Err(err(E_ACCOUNTS)); }
            let l = key_limbs(program_id, key)?;
            let now = Clock::get()?.unix_timestamp;
            // the hash GitHub must have named is the hash of the modulus this account holds
            let want = {
                let d = key.try_borrow_data()?;
                if d[K_FLAGS] & F_REVOKED != 0 { return Err(err(E_REVOKED)); }
                let (mut n, mut n_be) = (vec![0u32; l], vec![0u8; 4 * l]);
                rsa::load(&d[K_HDR..], &mut n);
                rsa::limbs_to_be(&n, &mut n_be);
                let kh = hashv(&[&n_be]).to_bytes();
                match d[K_ISSUER] {
                    i if (i as usize) < pins::ISSUERS.len() => key_audience(i, &kh),
                    pins::ISSUER_OTHER => ikey_audience(d[K_HDR + 8 * l..K_HDR + 8 * l + 32].try_into().unwrap(), &kh),
                    _ => return Err(err(E_ISS)),
                }
            };
            attested(program_id, attest, akey, &want, true, now)?;
            let mut d = key.try_borrow_mut_data()?;
            let expires = i64_at(&d, K_EXPIRES).max(now.saturating_add(pins::KEY_TTL));
            put_i64(&mut d, K_EXPIRES, expires);
            Ok(())
        }
        6 => {
            let guardian = next_account_info(it)?; let key = next_account_info(it)?;
            if !rest.is_empty() { return Err(ProgramError::InvalidInstructionData); }
            if !guardian.is_signer || !pins::is_guardian(guardian.key) { return Err(err(E_GUARDIAN)); }
            key_limbs(program_id, key)?;
            let mut d = key.try_borrow_mut_data()?;
            if d[K_FLAGS] & F_REVOKED != 0 { return Err(err(E_REVOKED)); }
            // a private key stays what it is: the guardian's approval is a statement about a key GitHub named
            if d[K_FLAGS] & F_PRIVATE != 0 { return Err(err(E_KEY)); }
            d[K_FLAGS] |= F_APPROVED;
            Ok(())
        }
        7 => {
            let guardian = next_account_info(it)?; let key = next_account_info(it)?;
            if !rest.is_empty() { return Err(ProgramError::InvalidInstructionData); }
            // the guardian, for any key; or the wallet that registered a private key, for that key
            let may = pins::is_guardian(guardian.key) || registrant_of(program_id, key).as_ref() == Some(guardian.key);
            if !guardian.is_signer || !may { return Err(err(E_GUARDIAN)); }
            key_limbs(program_id, key)?;
            let mut d = key.try_borrow_mut_data()?;
            d[K_FLAGS] |= F_REVOKED;
            Ok(())
        }
        8 => {
            let payer = next_account_info(it)?; let key = next_account_info(it)?; let iss = next_account_info(it)?;
            let sys = next_account_info(it)?; let attest = next_account_info(it)?; let akey = next_account_info(it)?;
            let (url, n_be) = url_and_modulus(rest)?;
            if !payer.is_signer || !payer.is_writable || *sys.key != system_program::ID { return Err(err(E_ACCOUNTS)); }
            let (ih, kh) = (hashv(&[url]).to_bytes(), hashv(&[n_be]).to_bytes());
            let (kk, bump) = Pubkey::find_program_address(&[b"ikey", &ih, &kh], program_id);
            let (ik, ibump) = Pubkey::find_program_address(&[b"iss", &ih], program_id);
            if *key.key != kk || !key.data_is_empty() || *key.owner != system_program::ID || *iss.key != ik { return Err(err(E_ACCOUNTS)); }
            let now = Clock::get()?.unix_timestamp;
            attested(program_id, attest, akey, &ikey_audience(&ih, &kh), false, now)?;
            let n = modulus(n_be)?;
            // the issuer's URL goes on chain with its first key; the address is derived from its hash, so a later
            // key of the same issuer finds the same text there
            if iss.owner != program_id {
                if !iss.data_is_empty() || *iss.owner != system_program::ID { return Err(err(E_ACCOUNTS)); }
                create_pda(payer, iss, sys, program_id, ISS_HDR + url.len(), &[b"iss", &ih, &[ibump]])?;
                let mut d = iss.try_borrow_mut_data()?;
                d[..ISS_HDR].copy_from_slice(&[ISS_STATE, ibump, 0, url.len() as u8]);
                d[ISS_HDR..].copy_from_slice(url);
            }
            let l = n.len();
            create_pda(payer, key, sys, program_id, K_HDR + 8 * l + KEY_TAIL, &[b"ikey", &ih, &kh, &[bump]])?;
            let active = now.saturating_add(pins::KEY_DELAY);
            let mut d = key.try_borrow_mut_data()?;
            d[K_ISSUER] = pins::ISSUER_OTHER; d[K_LIMBS] = l as u8; d[K_BUMP] = bump;
            put_i64(&mut d, K_ACTIVE, active);
            put_i64(&mut d, K_EXPIRES, active.saturating_add(pins::KEY_TTL));
            rsa::store(&mut d[K_HDR..], &n);
            d[K_HDR + 8 * l..K_HDR + 8 * l + 32].copy_from_slice(&ih);
            Ok(())
        }
        9 => {
            let registrant = next_account_info(it)?; let key = next_account_info(it)?; let sys = next_account_info(it)?;
            let (url, n_be) = url_and_modulus(rest)?;
            if !registrant.is_signer || !registrant.is_writable || *sys.key != system_program::ID { return Err(err(E_ACCOUNTS)); }
            let (ih, kh) = (hashv(&[url]).to_bytes(), hashv(&[n_be]).to_bytes());
            // the registrant is part of the address: nobody registers, renews or shadows a key in another wallet's name
            let (kk, bump) = Pubkey::find_program_address(&[b"pkey", registrant.key.as_ref(), &ih, &kh], program_id);
            if *key.key != kk { return Err(err(E_ACCOUNTS)); }
            let now = Clock::get()?.unix_timestamp;
            if key.owner == program_id {
                // the same wallet, the same key: it lives KEY_TTL from now. A revoked key stays revoked.
                key_limbs(program_id, key)?;
                let mut d = key.try_borrow_mut_data()?;
                if d[K_FLAGS] & F_REVOKED != 0 { return Err(err(E_REVOKED)); }
                let expires = i64_at(&d, K_EXPIRES).max(now.saturating_add(pins::KEY_TTL));
                put_i64(&mut d, K_EXPIRES, expires);
                return Ok(());
            }
            if !key.data_is_empty() || *key.owner != system_program::ID { return Err(err(E_ACCOUNTS)); }
            let n = modulus(n_be)?;
            let l = n.len();
            create_pda(registrant, key, sys, program_id, K_HDR + 8 * l + KEY_TAIL, &[b"pkey", registrant.key.as_ref(), &ih, &kh, &[bump]])?;
            let mut d = key.try_borrow_mut_data()?;
            d[K_ISSUER] = pins::ISSUER_PRIVATE; d[K_LIMBS] = l as u8; d[K_BUMP] = bump; d[K_FLAGS] = F_PRIVATE;
            put_i64(&mut d, K_ACTIVE, now);
            put_i64(&mut d, K_EXPIRES, now.saturating_add(pins::KEY_TTL));
            rsa::store(&mut d[K_HDR..], &n);
            d[K_HDR + 8 * l..K_HDR + 8 * l + 32].copy_from_slice(&ih);
            d[K_HDR + 8 * l + 32..].copy_from_slice(registrant.key.as_ref());
            Ok(())
        }
        10..=15 => es256::process(program_id, tag, accounts, rest), _ => Err(ProgramError::InvalidInstructionData), // 10-15, ES256: es256.rs. One line: no line below moves (knos_pay links what is below)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_key_is_usable_only_when_approved_or_genesis_active_unexpired_and_not_revoked() {
        let (active, expires) = (1_000, 2_000);
        for ok in [F_GENESIS | F_APPROVED, F_APPROVED, F_GENESIS, F_PRIVATE] {
            assert_eq!(key_usable(ok, active, expires, 999), Err(E_INACTIVE));
            assert_eq!(key_usable(ok, active, expires, 1_000), Ok(()));
            assert_eq!(key_usable(ok, active, expires, 1_999), Ok(()));
            assert_eq!(key_usable(ok, active, expires, 2_000), Err(E_KEY_EXPIRED));
            assert_eq!(key_usable(ok, active, expires, i64::MAX), Err(E_KEY_EXPIRED));
        }
        // attested and waiting for the guardian: never, however much time passes
        for now in [0, 999, 1_000, 1_999, 2_000, i64::MAX] { assert_eq!(key_usable(0, active, expires, now), Err(E_INACTIVE)); }
        // revoked wins over everything
        for flags in 0..8u8 {
            for now in [0, 1_500, 5_000] {
                if flags & F_REVOKED != 0 { assert_eq!(key_usable(flags, active, expires, now), Err(E_REVOKED)); }
            }
        }
    }

    #[test]
    fn a_token_verified_while_its_key_was_usable_is_fresh_for_at_most_25_hours_more() {
        // Step accepts exp <= now + AHEAD at a moment `at` when the key is usable; `fresh` then holds until exp + LATE
        for at in [0i64, 1_790_000_000, i64::MAX - AHEAD - LATE] {
            let exp = at + AHEAD; // the furthest expiry Step lets through
            assert!(fresh(exp, at + AHEAD + LATE - 1) && !fresh(exp, at + AHEAD + LATE));
        }
        assert_eq!(AHEAD + LATE, 25 * 3600);
        assert!(fresh(i64::MAX, i64::MAX - 1)); // no overflow at the end of time
    }

    #[test]
    fn an_issuer_is_an_https_url_with_one_spelling_and_its_audience_names_two_hashes() {
        let n = [0x81u8; 256];
        let data = |url: &[u8], n: &[u8]| [&[url.len() as u8][..], url, n].concat();
        let url = b"https://ghe.example.org/_services/token";
        assert_eq!(url_and_modulus(&data(url, &n)).unwrap(), (&url[..], &n[..]));
        assert_eq!(url_and_modulus(&data(url, &[0x81; 512])).unwrap().1.len(), 512);
        let longest = [&b"https://"[..], &[b'a'; MAX_ISS - 8]].concat();
        assert!(url_and_modulus(&data(&longest, &n)).is_ok());
        for bad in [&b"https://"[..], b"http://example.org", b"HTTPS://example.org", b"https://a b", b"https://a\"b", b"https://a\\b", b"https://a\x7f",
                    b"https://\xc3\xa9", &[&longest[..], b"a"].concat()] {
            assert_eq!(url_and_modulus(&data(bad, &n)).unwrap_err(), err(E_ISS), "{:?}", core::str::from_utf8(bad));
        }
        // the length byte and the modulus's length must agree with the data
        for bad in [&[][..], &[5], &data(url, &n[..255]), &data(url, &[0x81; 257]), &[&data(url, &n)[..], &[0]].concat()] {
            assert_eq!(url_and_modulus(bad).unwrap_err(), ProgramError::InvalidInstructionData);
        }
        let (ih, kh) = ([0xabu8; 32], [0x01u8; 32]);
        assert_eq!(ikey_audience(&ih, &kh), format!("knos-oidc:ikey:{}:{}", "ab".repeat(32), "01".repeat(32)).into_bytes());
        assert_eq!(key_audience(1, &kh), format!("knos-oidc:key:1:{}", "01".repeat(32)).into_bytes());
        // no audience of one kind is an audience of the other
        assert!(claims::parts::<4>(&ikey_audience(&ih, &kh)).is_some() && claims::parts::<4>(&key_audience(0, &kh)).is_some());
        assert_ne!(claims::parts::<4>(&ikey_audience(&ih, &kh)).unwrap()[1], claims::parts::<4>(&key_audience(0, &kh)).unwrap()[1]);
        assert!(modulus(&n).is_ok() && modulus(&[0x80; 256]).is_err() && modulus(&[0x01; 256]).is_err());
    }

    #[test]
    fn only_a_verified_token_of_another_issuer_has_a_hash_and_only_a_private_one_a_registrant() {
        let mut d = vec![0u8; T_JWT + 2];
        d[T_IHASH..T_IHASH + 32].copy_from_slice(&[0xaa; 32]);
        d[T_REGISTRANT..T_REGISTRANT + 32].copy_from_slice(&[0xbb; 32]);
        for stage in [0u8, 1, VERIFIED] {
            for issuer in 0..=4u8 {
                d[T_STAGE] = stage; d[T_ISSUER] = issuer;
                let done = stage == VERIFIED;
                assert_eq!(issuer_hash(&d), (done && issuer >= pins::ISSUER_OTHER).then_some(&[0xaa; 32]));
                assert_eq!(is_private(&d), done && issuer == pins::ISSUER_PRIVATE);
                assert_eq!(registrant(&d), (done && issuer == pins::ISSUER_PRIVATE).then_some(&[0xbb; 32]));
            }
        }
        assert!(issuer_hash(&d[..T_JWT - 1]).is_none() && !is_private(&d[..T_JWT - 1]));
        // the numbers: GitHub and GitLab keep theirs, and the two new kinds are neither
        assert_eq!((pins::ISSUER_GITHUB, pins::ISSUER_GITLAB, pins::ISSUER_OTHER, pins::ISSUER_PRIVATE), (0, 1, 2, 3));
        assert_eq!(pins::ISSUERS.len(), pins::ISSUER_OTHER as usize);
        assert_eq!((key_tail(0), key_tail(1), key_tail(2), key_tail(3)), (0, 0, KEY_TAIL, KEY_TAIL));
        // an issuer account is shorter than a key's header plus a modulus and than a token's header
        const { assert!(ISS_HDR + MAX_ISS < K_HDR + 8 * 64 && ISS_HDR + MAX_ISS < T_JWT && ISS_STATE != VERIFIED && ISS_STATE > 1) };
    }

    #[test]
    fn a_key_header_can_never_read_as_a_verified_token() {
        // a 4096-bit key account is longer than a token's header; its state byte is 0 or 1, never VERIFIED
        for state in [0u8, 1] {
            let mut d = vec![0xffu8; K_HDR + 8 * 128];
            d[K_STATE] = state;
            assert!(d.len() >= T_JWT && verified(&d).is_none());
        }
    }

    #[test]
    fn the_attester_is_the_pinned_account_and_its_two_repositories() {
        for repo in pins::ATTEST_REPO_IDS { assert!(pins::attester(pins::ATTEST_OWNER_ID, repo)); }
        assert!(!pins::attester(pins::ATTEST_OWNER_ID, 1) && !pins::attester(1, pins::ATTEST_REPO_IDS[0]) && !pins::attester(0, 0));
        assert!(pins::is_guardian(&pins::GUARDIAN) && !pins::is_guardian(&Pubkey::default()));
        // the test values exist only in a testkeys build
        assert_eq!(pins::attester(424_242, 987_654_321), cfg!(feature = "testkeys"));
        assert_eq!(pins::TEST_GUARDIAN.is_some(), cfg!(feature = "testkeys"));
        assert_eq!(pins::GENESIS.len(), 4);
        assert!(pins::GENESIS.iter().all(|(issuer, _)| *issuer == pins::ISSUER_GITHUB));
    }
}
