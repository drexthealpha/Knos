//! knos-oidc: OIDC on Solana. Verifies an RS256 token from GitHub Actions or GitLab CI on chain, so that any program
//! can require a fact the issuer signed ("this workflow, at this commit, ran in this repository and said X") with no
//! oracle and no admin: the trusted keys are constants in this binary (pins.rs), new keys are added by the issuer's
//! own signature (RegisterKey), and no instruction changes anything else. Deploy it, then make it immutable.
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
//!                  2048-bit keys: Step(8), Step(8). 4096-bit keys: Step(2), Step(3) four times, Step(2).
//!   2 Close        payer(s,w) token(w)                   data: id[32]        (the rent goes back to the payer)
//!   3 RegisterKey  payer(s,w) key(w) system [attest]     data: issuer u8, n (256 or 512 bytes, big-endian)
//!                  Creates ["key", [issuer], sha256(n)]. Allowed when that hash is in GENESIS, or when `attest` is a
//!                  VERIFIED GitHub token of the pinned rotate workflow whose audience is
//!                  "knos-oidc:key:<issuer>:<sha256(n) hex>", at most an hour past its expiry. Anyone may send it.
//!   4 KeyParams    payer(s) key(w)                       data: n0inv u32, r2 (as long as n, big-endian)
//!                  The key's Montgomery constants, checked on chain; the key is usable after this. Anyone may send it.
//!
//! A consumer program takes the token account, checks `owner == knos_oidc::ID`, and calls `verified(&data)` for the
//! issuer, the expiry and the decoded payload, then reads claims with `claims::fields`. Replay protection (and the
//! expiry check against the clock, `fresh`) is the consumer's: the same token can be verified into any number of accounts.
pub mod claims;
pub mod pins;
pub mod rsa;

use claims::{err, fields, text};
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

pub const MAX_JWT: usize = 8192;
/// How long after its `exp` a token is still accepted, here and by consumers that call `fresh`. The issuers' tokens
/// live five minutes, which is shorter than it can take a public relay to find one and land several transactions.
/// A token is not a bearer secret in this design: its audience names one action, and every consumer keeps its own
/// replay guard, so an hour of lateness gives a reader of the token nothing but the gas bill.
pub const LATE: i64 = 3600;
pub fn fresh(exp: i64, now: i64) -> bool { now < exp.saturating_add(LATE) }
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
// key account: ready u8, issuer u8, limbs u8, bump u8, n0inv u32, n (limbs, LE), r2 (limbs, LE)
pub const K_HDR: usize = 8;

// errors: 60-63 in claims.rs; 64 token too long or chunk out of range; 65 signature length or range; 66 key
// parameters; 67 accounts; 68 not a ready key of this program; 69 wrong stage; 70 bad signature; 71 alg is not
// RS256; 72 issuer; 73 key not in genesis and no valid attestation; 74 attestation claims; 75 attestation expired
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

#[cfg(not(feature = "no-entrypoint"))]
solana_program::entrypoint!(process);

#[cfg(not(feature = "no-entrypoint"))]
solana_security_txt::security_txt! {
    name: "knos-oidc",
    project_url: "https://github.com/drexthealpha/Knos",
    contacts: "link:https://github.com/drexthealpha/Knos/security/advisories/new",
    policy: "https://github.com/drexthealpha/Knos/blob/main/SECURITY.md",
    source_code: "https://github.com/drexthealpha/Knos"
}

/// What a consumer reads from a token account it has checked is owned by this program: None unless VERIFIED.
pub struct Verified<'a> { pub issuer: u8, pub exp: i64, pub payload: &'a [u8] }
pub fn verified(d: &[u8]) -> Option<Verified<'_>> {
    if d.len() < T_JWT || d[T_STAGE] != VERIFIED { return None; }
    let off = u16::from_le_bytes([d[T_POFF], d[T_POFF + 1]]) as usize;
    let len = u16::from_le_bytes([d[T_PLEN], d[T_PLEN + 1]]) as usize;
    let payload = d.get(off..off + len)?;
    Some(Verified { issuer: d[T_ISSUER], exp: i64::from_le_bytes(d[T_EXP..T_EXP + 8].try_into().ok()?), payload })
}

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

struct Key { issuer: u8, l: usize, n0inv: u32, n: Vec<u32>, r2: Vec<u32> }
fn load_key(program_id: &Pubkey, key: &AccountInfo) -> Result<Key, ProgramError> {
    if key.owner != program_id { return Err(err(E_KEY)); }
    let d = key.try_borrow_data()?;
    if d.len() < K_HDR || d[0] != 1 { return Err(err(E_KEY)); }
    let l = d[2] as usize;
    if (l != 64 && l != 128) || d.len() != K_HDR + 8 * l { return Err(err(E_KEY)); }
    let (mut n, mut r2) = (vec![0u32; l], vec![0u32; l]);
    rsa::load(&d[K_HDR..], &mut n);
    rsa::load(&d[K_HDR + 4 * l..], &mut r2);
    Ok(Key { issuer: d[1], l, n0inv: u32::from_le_bytes(d[4..8].try_into().unwrap()), n, r2 })
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
            let k = load_key(program_id, key)?;
            let l = k.l;
            let mut d = tok.try_borrow_mut_data()?;
            let len = u16::from_le_bytes([d[T_LEN], d[T_LEN + 1]]) as usize;
            if d.len() != T_JWT + len || d[T_STAGE] == VERIFIED { return Err(err(E_STAGE)); }
            let [hp, pp, sp] = claims::split_jwt(&d[T_JWT..T_JWT + len])?;
            // the signature: exactly as long as the modulus, and below it
            let mut sig = vec![0u8; 4 * l];
            if claims::b64_len(sp.1 - sp.0) != Some(4 * l) { return Err(err(E_SIG)); }
            claims::b64url_into(&d[T_JWT + sp.0..T_JWT + sp.1], &mut sig)?;
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
            claims::b64url_into(&d[T_JWT + hp.0..T_JWT + hp.1], &mut header)?;
            let [alg] = fields(&header, [b"alg"])?;
            if text(alg)? != b"RS256" { return Err(err(E_ALG)); }
            let poff = T_JWT + pp.0;
            let plen = claims::b64url_in_place(&mut d, poff, pp.1 - pp.0)?;
            let exp = {
                let [iss, exp] = fields(&d[poff..poff + plen], [b"iss", b"exp"])?;
                if text(iss)? != pins::ISSUERS[k.issuer as usize] { return Err(err(E_ISS)); }
                match exp { Some(r) if !r.is_str => claims::parse_u64(r.bytes).ok_or_else(|| err(claims::E_CLAIM))? as i64, _ => return Err(err(claims::E_CLAIM)) }
            };
            d[T_POFF..T_POFF + 2].copy_from_slice(&(poff as u16).to_le_bytes());
            d[T_PLEN..T_PLEN + 2].copy_from_slice(&(plen as u16).to_le_bytes());
            d[T_EXP..T_EXP + 8].copy_from_slice(&exp.to_le_bytes());
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
            if *key.key != kk || !key.data_is_empty() || *key.owner != system_program::ID { return Err(err(E_ACCOUNTS)); }
            let trusted = pins::GENESIS.iter().chain(pins::TEST_GENESIS.iter()).any(|(i, g)| *i == issuer && *g == kh);
            if !trusted {
                // GitHub's own signature, from the pinned rotate workflow, names this key
                let attest = next_account_info(it).map_err(|_| err(E_UNTRUSTED))?;
                if attest.owner != program_id { return Err(err(E_UNTRUSTED)); }
                let ad = attest.try_borrow_data()?;
                let v = verified(&ad).ok_or_else(|| err(E_UNTRUSTED))?;
                if v.issuer != pins::ISSUER_GITHUB { return Err(err(E_ATTEST)); }
                if !fresh(v.exp, Clock::get()?.unix_timestamp) { return Err(err(E_EXPIRED)); }
                let [wref, wsha, runner, aud] = fields(v.payload, [b"job_workflow_ref", b"job_workflow_sha", b"runner_environment", b"aud"])?;
                let (wref, wsha) = (text(wref)?, text(wsha)?);
                let sha_ok = wsha == pins::ROTATE_SHA || pins::TEST_ROTATE_SHA.is_some_and(|t| wsha == t);
                if !wref.starts_with(pins::ROTATE_REF) || !sha_ok || text(runner)? != b"github-hosted" { return Err(err(E_ATTEST)); }
                let mut want = Vec::with_capacity(80);
                want.extend_from_slice(b"knos-oidc:key:");
                want.push(b'0' + issuer);
                want.push(b':');
                let mut hx = [0u8; 64];
                claims::hex_into(&kh, &mut hx);
                want.extend_from_slice(&hx);
                if text(aud)? != want { return Err(err(E_ATTEST)); }
            }
            let mut n = vec![0u32; l];
            rsa::be_to_limbs(n_be, &mut n);
            if n[0] & 1 == 0 || n[l - 1] >> 31 == 0 { return Err(err(E_PARAMS)); }
            create_pda(payer, key, sys, program_id, K_HDR + 8 * l, &[b"key", &[issuer], &kh, &[bump]])?;
            let mut d = key.try_borrow_mut_data()?;
            d[1] = issuer; d[2] = l as u8; d[3] = bump;
            rsa::store(&mut d[K_HDR..], &n);
            Ok(())
        }
        4 => {
            let payer = next_account_info(it)?; let key = next_account_info(it)?;
            if !payer.is_signer || key.owner != program_id { return Err(err(E_ACCOUNTS)); }
            let mut d = key.try_borrow_mut_data()?;
            if d.len() < K_HDR || d[0] != 0 { return Err(err(E_STAGE)); }
            let l = d[2] as usize;
            if d.len() != K_HDR + 8 * l || rest.len() != 4 + 4 * l { return Err(ProgramError::InvalidInstructionData); }
            let n0inv = u32::from_le_bytes(rest[0..4].try_into().unwrap());
            let (mut n, mut r2) = (vec![0u32; l], vec![0u32; l]);
            rsa::load(&d[K_HDR..], &mut n);
            rsa::be_to_limbs(&rest[4..], &mut r2);
            let (mut a, mut b, mut t) = (vec![0u32; l], vec![0u32; l], vec![0u32; l + 2]);
            if !rsa::params_ok(&n, &r2, n0inv, &mut a, &mut b, &mut t) { return Err(err(E_PARAMS)); }
            d[4..8].copy_from_slice(&n0inv.to_le_bytes());
            rsa::store(&mut d[K_HDR + 4 * l..], &r2);
            d[0] = 1;
            Ok(())
        }
        _ => Err(ProgramError::InvalidInstructionData),
    }
}
