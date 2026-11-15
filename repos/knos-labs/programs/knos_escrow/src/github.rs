//! 0.3.7: a GitHub Actions OIDC token, verified on chain. A "github" job (PostGithub) names a repository and a ref
//! (their sha256). Its worker proves the work by a token GitHub signed (RS256) for a run of the pinned prove.yml
//! workflow on that repository and ref, with audience "knos:<job id hex>". The RSA-2048 check (s^65537 mod n) runs in
//! two transactions (VerifyStep1, VerifyStep2) against a key the admin registered from GitHub's JWKS (RegisterKey);
//! the token is written to a proof buffer first (BufferWrite). On a valid proof the worker is paid (price - fee +
//! stake back), the job and the buffer close. With no proof by the deadline, Refund / Settle refund the buyer.
//!
//!   15 RegisterKey  admin(s,w) config2 key(w) system
//!                   data: kid_len u8, kid, n[256] (big-endian), r2[256] (R^2 mod n, big-endian), n0inv u32
//!   16 BufferWrite  prover(s,w) buffer(w) system           data: job_id[32] total_len u16 offset u16 chunk
//!   17 VerifyStep1  prover(s) buffer(w) key                data: job_id[32]
//!   18 VerifyStep2  prover(s,w) buffer(w) key job(w) vault_token(w) vault_auth worker_token(w) fee_token(w)
//!                   buyer(w) config2 token                 data: job_id[32]
//!   19 PostGithub   buyer(s,w) job(w) buyer_token(w) vault_token(w) config2 token system
//!                   data: id[32] amount u64 work i64 review i64 brief[32] repo_hash[32] ref_hash[32]
use super::{bounty, close_job, create_pda, err, token_owner_mint, token_transfer, vseeds, Config, Job, JOB_LEN, S, TOKEN_PROGRAM};
use solana_program::{instruction::{AccountMeta, Instruction}, program::invoke_signed};
use solana_program::{
    account_info::{next_account_info, AccountInfo},
    clock::Clock,
    entrypoint::ProgramResult,
    hash::hashv,
    program_error::ProgramError,
    pubkey::Pubkey,
    system_program,
    sysvar::Sysvar,
};

// 0.3.8 github job: the job, sha256(repository), sha256(ref), checks_hash[32], stake_required u8
pub const GH_CHECKS: usize = JOB_LEN + 64;
pub const GH_STAKE_REQ: usize = GH_CHECKS + 32;
pub const GH_JOB_LEN: usize = GH_STAKE_REQ + 1;
pub const GH_V037_JOB_LEN: usize = JOB_LEN + 64; // 0.3.7 github jobs: settle by refund only
// 0.3.9: a github job funded by FundWithToken, in the faucet's (registered) mint: the github job + mint[32]
pub const GH_MINT_JOB_LEN: usize = GH_JOB_LEN + 32;
pub fn is_gh_job(len: usize) -> bool { len == GH_JOB_LEN || len == GH_MINT_JOB_LEN }

// 0.3.9 issuer registry: ["issuer", id] = claims kind u8, url_len u8, url[MAX_ISS]
pub const MAX_ISS: usize = 128;
pub const ISSUER_LEN: usize = 2 + MAX_ISS;
pub const CLAIMS_GITHUB: u8 = 0; // repository, job_workflow_sha
pub const CLAIMS_GITLAB: u8 = 1; // project_path, ci_config_sha
// FundWithToken: a funded job's work window and review; one funding per repository per hour
pub const FUND_WORK: i64 = 14 * 86_400;
pub const FUND_REVIEW: i64 = 86_400;
pub const FUND_PERIOD: i64 = 3_600;
pub const FUNDRATE_LEN: usize = 8;

fn hex_into(b: &[u8], out: &mut [u8]) {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    for (k, x) in b.iter().enumerate() { out[2 * k] = HEX[(x >> 4) as usize]; out[2 * k + 1] = HEX[(x & 15) as usize]; }
}

/// A canonical base58 32-byte public key (as Solana prints it); None for anything else.
fn b58_32(s: &[u8]) -> Option<[u8; 32]> {
    const A: &[u8] = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
    if s.is_empty() || s.len() > 44 { return None; }
    let mut out = [0u8; 32];
    for &c in s {
        let mut carry = A.iter().position(|&x| x == c)? as u32;
        for b in out.iter_mut().rev() {
            carry += (*b as u32) * 58;
            *b = carry as u8;
            carry >>= 8;
        }
        if carry != 0 { return None; }
    }
    let ones = s.iter().take_while(|&&c| c == b'1').count();
    let zeros = out.iter().take_while(|&&b| b == 0).count();
    if ones != zeros { return None; }
    Some(out)
}
pub const ISSUER: &[u8] = b"https://token.actions.githubusercontent.com";
pub const WF_PROVE: u8 = 0; // prove.yml
pub const WF_FUND: u8 = 1;  // fund.yml
pub const WF_LEN: usize = 1 + 40; // kind, sha (40 lowercase hex)

fn is_sha40(s: &[u8]) -> bool { s.len() == 40 && s.iter().all(|c| matches!(c, b'0'..=b'9' | b'a'..=b'f')) }

/// The workflow registry entry ["workflow", kind, sha] exists (owned by the program) for this sha.
fn workflow_registered(program_id: &Pubkey, wf: &AccountInfo, kind: u8, sha: &[u8]) -> bool {
    if !is_sha40(sha) { return false; }
    let (k, _) = Pubkey::find_program_address(&[b"workflow", &[kind], &sha[..20], &sha[20..]], program_id);
    *wf.key == k && wf.owner == program_id && wf.data_len() == WF_LEN
}

/// 24 SetWorkflow  admin(s,w) config2 workflow(w) system      data: kind u8 (0 prove.yml, 1 fund.yml) add u8 sha[40]
/// Adds (creates ["workflow", kind, sha]) or removes (closes it, rent to the admin) an allowed workflow commit sha.
pub fn set_workflow(program_id: &Pubkey, accounts: &[AccountInfo], rest: &[u8], config_key: &Pubkey) -> ProgramResult {
    let it = &mut accounts.iter();
    let admin = next_account_info(it)?; let config = next_account_info(it)?; let wf = next_account_info(it)?;
    let sys = next_account_info(it)?;
    let cfg = Config::load(config, program_id, config_key)?;
    if !admin.is_signer || !admin.is_writable || *admin.key != cfg.admin { return Err(err(15, "admin only")); }
    if *sys.key != system_program::ID || rest.len() != 2 + 40 { return Err(ProgramError::InvalidInstructionData); }
    let (kind, add, sha) = (rest[0], rest[1] != 0, &rest[2..42]);
    if kind > WF_FUND || !is_sha40(sha) { return Err(err(73, "workflow kind or sha")); }
    let (k, bump) = Pubkey::find_program_address(&[b"workflow", &[kind], &sha[..20], &sha[20..]], program_id);
    if *wf.key != k { return Err(err(5, "workflow address")); }
    if add {
        if !wf.data_is_empty() || *wf.owner != system_program::ID { return Err(err(6, "workflow exists")); }
        create_pda(admin, wf, sys, program_id, WF_LEN, &[b"workflow", &[kind], &sha[..20], &sha[20..], &[bump]])?;
        let mut d = wf.try_borrow_mut_data()?;
        d[0] = kind; d[1..].copy_from_slice(sha);
    } else {
        if wf.owner != program_id { return Err(err(73, "workflow not registered")); }
        let lamports = wf.lamports();
        **admin.try_borrow_mut_lamports()? = admin.lamports().checked_add(lamports).ok_or(ProgramError::ArithmeticOverflow)?;
        **wf.try_borrow_mut_lamports()? = 0;
        wf.resize(0)?;
        wf.assign(&system_program::ID);
    }
    Ok(())
}
const L: usize = 64; // 32-bit limbs of an RSA-2048 number
type Big = [u32; L];
const KEY_LEN: usize = 256 + 4 + 256; // n limbs (LE), n0inv, r2 limbs (a GitHub key at ["ghkey", sha256(kid)])
// 0.3.9: a key scoped to a registered issuer, at ["ghkey", sha256(kid), [issuer id]]: + issuer id, claims kind, sha256(url)
const KEY2_LEN: usize = KEY_LEN + 2 + 32;

struct KeyInfo { n: Big, n0inv: u32, issuer: Option<(u8, u8, [u8; 32])> }
fn load_key(program_id: &Pubkey, key: &AccountInfo) -> Result<KeyInfo, ProgramError> {
    if key.owner != program_id || (key.data_len() != KEY_LEN && key.data_len() != KEY2_LEN) { return Err(err(68, "not a registered key")); }
    let kd = key.try_borrow_data()?;
    let issuer = if kd.len() == KEY2_LEN { Some((kd[KEY_LEN], kd[KEY_LEN + 1], kd[KEY_LEN + 2..].try_into().unwrap())) } else { None };
    Ok(KeyInfo { n: load(&kd, 0), n0inv: u32::from_le_bytes(kd[256..260].try_into().unwrap()), issuer })
}

/// The claims a proof reads, by the issuer's claim names (GitHub: repository, job_workflow_sha; GitLab CI:
/// project_path, ci_config_sha). The issuer is checked: GitHub's for a legacy key, the registered url's otherwise.
struct Claims<'a> { wsha: &'a [u8], repo: &'a [u8], rf: &'a [u8], aud: &'a [u8], sha: Option<(&'a [u8], bool)>, exp: i64 }
fn claims<'a>(payload: &'a [u8], ki: &KeyInfo) -> Result<Claims<'a>, ProgramError> {
    let kind = ki.issuer.map(|i| i.1).unwrap_or(CLAIMS_GITHUB);
    let names: [&[u8]; 7] = if kind == CLAIMS_GITLAB {
        [b"iss", b"ci_config_sha", b"project_path", b"ref", b"aud", b"exp", b"sha"]
    } else {
        [b"iss", b"job_workflow_sha", b"repository", b"ref", b"aud", b"exp", b"sha"]
    };
    let [iss, wsha, repo, rf, aud, exp, sha] = fields(payload, names)?;
    let iss = want_str(iss, "iss")?;
    let ok = match ki.issuer { None => iss == ISSUER, Some((_, _, h)) => hashv(&[iss]).to_bytes() == h };
    if !ok { return Err(err(72, "issuer")); }
    let exp = match exp { Some((v, false)) if !v.is_empty() && v.len() <= 18 && v.iter().all(|c| c.is_ascii_digit()) =>
        v.iter().fold(0i64, |a, c| a * 10 + (c - b'0') as i64), _ => return Err(err(63, "exp")) };
    Ok(Claims { wsha: want_str(wsha, "workflow sha")?, repo: want_str(repo, "repository")?, rf: want_str(rf, "ref")?,
                aud: want_str(aud, "aud")?, sha, exp })
}

/// Step 2's signature check on the buffered token: step 1 ran with this key, the header names this key (RS256), and
/// s^65537 mod n is the PKCS#1 v1.5 SHA-256 encoding of the signed part. Returns the decoded payload.
fn verified_payload(program_id: &Pubkey, d: &[u8], key: &AccountInfo, ki: &KeyInfo) -> Result<Vec<u8>, ProgramError> {
    let (n, n0inv) = (&ki.n, ki.n0inv);
    if d[B_STAGE] != 1 || d[B_KEY..B_KEY + 32] != key.key.as_ref()[..] { return Err(err(70, "run step 1 first")); }
    let len = u16::from_le_bytes(d[B_LEN..B_LEN + 2].try_into().unwrap()) as usize;
    let t = &d[B_JWT..B_JWT + len];
    let (h64, p64, sig) = split_jwt(t)?;
    let s = signature(sig, n)?;
    let header = b64url(h64)?;
    let [alg, kid] = fields(&header, [b"alg", b"kid"])?;
    if want_str(alg, "alg")? != b"RS256" { return Err(err(63, "alg")); }
    let kh = hashv(&[want_str(kid, "kid")?]).to_bytes();
    let (kk, _) = match ki.issuer {
        None => Pubkey::find_program_address(&[b"ghkey", &kh], program_id),
        Some((id, _, _)) => Pubkey::find_program_address(&[b"ghkey", &kh, &[id]], program_id),
    };
    if *key.key != kk { return Err(err(68, "the token's key is not this key")); }
    // s^65537 mod n: x = (s^256)_M from step 1; 8 more squarings -> (s^65536)_M; * s (plain) -> s^65537
    let mut x = load(d, B_X);
    for _ in 0..8 { x = mont_sqr(&x, n, n0inv); }
    let em = limbs_to_be(&mont_mul(&x, &s, n, n0inv));
    let digest = hashv(&[&t[..h64.len() + 1 + p64.len()]]).to_bytes();
    let ps = 256 - 3 - DIGEST_INFO.len() - 32;
    let ok = em[0] == 0 && em[1] == 1 && em[2..2 + ps].iter().all(|&c| c == 0xff) && em[2 + ps] == 0
        && em[3 + ps..3 + ps + 19] == DIGEST_INFO && em[256 - 32..] == digest;
    if !ok { return Err(err(71, "bad signature")); }
    b64url(p64)
}

fn close_buffer<'a>(buf: &AccountInfo<'a>, to: &AccountInfo<'a>) -> ProgramResult {
    let lamports = buf.lamports();
    **to.try_borrow_mut_lamports()? = to.lamports().checked_add(lamports).ok_or(ProgramError::ArithmeticOverflow)?;
    **buf.try_borrow_mut_lamports()? = 0;
    buf.resize(0)?;
    buf.assign(&system_program::ID);
    Ok(())
}

/// 25 RegisterIssuer  admin(s,w) config2 issuer(w) system     data: id u8, claims kind u8 (0 GitHub, 1 GitLab CI), url
/// Creates ["issuer", id]. Keys registered with an issuer id (RegisterKey + id, with this account) verify only tokens
/// whose iss is this url, and read the claims by its kind's names.
pub fn register_issuer(program_id: &Pubkey, accounts: &[AccountInfo], rest: &[u8], config_key: &Pubkey) -> ProgramResult {
    let it = &mut accounts.iter();
    let admin = next_account_info(it)?; let config = next_account_info(it)?; let iss = next_account_info(it)?;
    let sys = next_account_info(it)?;
    let cfg = Config::load(config, program_id, config_key)?;
    if !admin.is_signer || !admin.is_writable || *admin.key != cfg.admin { return Err(err(15, "admin only")); }
    if *sys.key != system_program::ID || rest.len() < 3 || rest.len() > 2 + MAX_ISS { return Err(ProgramError::InvalidInstructionData); }
    let (id, kind, url) = (rest[0], rest[1], &rest[2..]);
    if kind > CLAIMS_GITLAB || !url.starts_with(b"https://") { return Err(err(79, "issuer kind or url")); }
    let (k, bump) = Pubkey::find_program_address(&[b"issuer", &[id]], program_id);
    if *iss.key != k { return Err(err(5, "issuer address")); }
    if !iss.data_is_empty() || *iss.owner != system_program::ID { return Err(err(6, "issuer exists")); }
    create_pda(admin, iss, sys, program_id, ISSUER_LEN, &[b"issuer", &[id], &[bump]])?;
    let mut d = iss.try_borrow_mut_data()?;
    d[0] = kind; d[1] = url.len() as u8; d[2..2 + url.len()].copy_from_slice(url);
    Ok(())
}

/// The registered issuer ["issuer", id]: (claims kind, sha256(url)).
fn issuer_of(program_id: &Pubkey, iss: &AccountInfo, id: u8) -> Result<(u8, [u8; 32]), ProgramError> {
    let (k, _) = Pubkey::find_program_address(&[b"issuer", &[id]], program_id);
    if *iss.key != k || iss.owner != program_id || iss.data_len() != ISSUER_LEN { return Err(err(79, "issuer not registered")); }
    let d = iss.try_borrow_data()?;
    let l = d[1] as usize;
    if l == 0 || l > MAX_ISS { return Err(err(79, "issuer not registered")); }
    Ok((d[0], hashv(&[&d[2..2 + l]]).to_bytes()))
}

fn parse_u64(s: &[u8]) -> Option<u64> {
    if s.is_empty() || s.len() > 19 || !s.iter().all(|c| c.is_ascii_digit()) || (s.len() > 1 && s[0] == b'0') { return None; }
    Some(s.iter().fold(0u64, |a, c| a * 10 + (c - b'0') as u64))
}
fn is_hex64(s: &[u8]) -> bool { s.len() == 64 && s.iter().all(|c| matches!(c, b'0'..=b'9' | b'a'..=b'f')) }
fn unhex32(s: &[u8]) -> [u8; 32] {
    let v = |c: u8| if c <= b'9' { c - b'0' } else { c - b'a' + 10 };
    let mut o = [0u8; 32];
    for (k, b) in o.iter_mut().enumerate() { *b = v(s[2 * k]) << 4 | v(s[2 * k + 1]); }
    o
}
pub const MAX_JWT: usize = 2048;
// proof buffer: stage u8 (0 written, 1 step 1 done), jwt_len u16, key[32], x limbs[256], jwt
const B_STAGE: usize = 0;
const B_LEN: usize = 1;
const B_KEY: usize = 3;
const B_X: usize = 35;
const B_JWT: usize = 291;
pub const BUF_LEN: usize = B_JWT + MAX_JWT;
const DIGEST_INFO: [u8; 19] = [0x30, 0x31, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01, 0x05, 0x00, 0x04, 0x20];

// -- RSA-2048 in Montgomery form (CIOS) ------------------------------------------------------------------------------
fn be_to_limbs(b: &[u8]) -> Big {
    let mut x = [0u32; L];
    for (i, xi) in x.iter_mut().enumerate() {
        let o = 256 - 4 * (i + 1);
        *xi = u32::from_be_bytes([b[o], b[o + 1], b[o + 2], b[o + 3]]);
    }
    x
}
fn limbs_to_be(x: &Big) -> [u8; 256] {
    let mut b = [0u8; 256];
    for (i, xi) in x.iter().enumerate() {
        let o = 256 - 4 * (i + 1);
        b[o..o + 4].copy_from_slice(&xi.to_be_bytes());
    }
    b
}
fn load(d: &[u8], off: usize) -> Big {
    let mut x = [0u32; L];
    for (i, xi) in x.iter_mut().enumerate() {
        *xi = u32::from_le_bytes(d[off + 4 * i..off + 4 * i + 4].try_into().unwrap());
    }
    x
}
fn store(d: &mut [u8], off: usize, x: &Big) {
    for (i, xi) in x.iter().enumerate() {
        d[off + 4 * i..off + 4 * i + 4].copy_from_slice(&xi.to_le_bytes());
    }
}
fn geq(a: &Big, b: &Big) -> bool {
    for i in (0..L).rev() {
        if a[i] != b[i] { return a[i] > b[i]; }
    }
    true
}
fn sub_in(a: &mut Big, b: &Big) {
    let mut borrow = 0u64;
    for i in 0..L {
        let d = (a[i] as u64).wrapping_sub(b[i] as u64).wrapping_sub(borrow);
        a[i] = d as u32;
        borrow = (d >> 63) & 1;
    }
}

/// a * b * R^-1 mod n (R = 2^2048), for a, b < n.
pub fn mont_mul(a: &Big, b: &Big, n: &Big, n0inv: u32) -> Big {
    let mut t = [0u32; L + 2];
    for i in 0..L {
        let ai = a[i] as u64;
        let mut c = 0u64;
        for j in 0..L {
            let s = t[j] as u64 + ai * b[j] as u64 + c;
            t[j] = s as u32;
            c = s >> 32;
        }
        let s = t[L] as u64 + c;
        t[L] = s as u32;
        t[L + 1] = (s >> 32) as u32;
        let m = t[0].wrapping_mul(n0inv) as u64;
        let s = t[0] as u64 + m * n[0] as u64;
        let mut c = s >> 32;
        for j in 1..L {
            let s = t[j] as u64 + m * n[j] as u64 + c;
            t[j - 1] = s as u32;
            c = s >> 32;
        }
        let s = t[L] as u64 + c;
        t[L - 1] = s as u32;
        t[L] = t[L + 1].wrapping_add((s >> 32) as u32);
        t[L + 1] = 0;
    }
    let mut r = [0u32; L];
    r.copy_from_slice(&t[..L]);
    if t[L] != 0 || geq(&r, n) { sub_in(&mut r, n); }
    r
}

/// a^2 * R^-1 mod n for a < n: the square by symmetry (each cross product once, doubled), then a separate
/// Montgomery reduction. About 1.5 L^2 limb products instead of mont_mul's 2 L^2.
pub fn mont_sqr(a: &Big, n: &Big, n0inv: u32) -> Big {
    let mut t = [0u32; 2 * L + 1];
    for i in 0..L {
        let ai = a[i] as u64;
        let mut c = 0u64;
        for j in i + 1..L {
            let s = t[i + j] as u64 + ai * a[j] as u64 + c;
            t[i + j] = s as u32;
            c = s >> 32;
        }
        t[i + L] = c as u32;
    }
    let mut top = 0u32;
    for v in t.iter_mut().take(2 * L) {
        let w = *v;
        *v = (w << 1) | top;
        top = w >> 31;
    }
    let mut c = 0u64;
    for i in 0..L {
        let d = a[i] as u64 * a[i] as u64;
        let s = t[2 * i] as u64 + (d & 0xffff_ffff) + c;
        t[2 * i] = s as u32;
        let s = t[2 * i + 1] as u64 + (d >> 32) + (s >> 32);
        t[2 * i + 1] = s as u32;
        c = s >> 32;
    }
    let mut hi = 0u64;
    for i in 0..L {
        let m = t[i].wrapping_mul(n0inv) as u64;
        let mut c = 0u64;
        for j in 0..L {
            let s = t[i + j] as u64 + m * n[j] as u64 + c;
            t[i + j] = s as u32;
            c = s >> 32;
        }
        let s = t[i + L] as u64 + c + hi;
        t[i + L] = s as u32;
        hi = s >> 32;
    }
    let mut r = [0u32; L];
    r.copy_from_slice(&t[L..2 * L]);
    if hi != 0 || geq(&r, n) { sub_in(&mut r, n); }
    r
}

// -- base64url and a flat JSON object --------------------------------------------------------------------------------
fn b64v(c: u8) -> Option<u32> {
    Some(match c {
        b'A'..=b'Z' => c - b'A',
        b'a'..=b'z' => c - b'a' + 26,
        b'0'..=b'9' => c - b'0' + 52,
        b'-' => 62,
        b'_' => 63,
        _ => return None,
    } as u32)
}
pub fn b64url(s: &[u8]) -> Result<Vec<u8>, ProgramError> {
    if s.len() % 4 == 1 { return Err(err(60, "bad base64url")); }
    let mut out = Vec::with_capacity(s.len() * 3 / 4 + 3);
    let bad = || err(60, "bad base64url");
    for ch in s.chunks(4) {
        let mut v = 0u32;
        for (k, &c) in ch.iter().enumerate() { v |= b64v(c).ok_or_else(bad)? << (18 - 6 * k as u32); }
        out.push((v >> 16) as u8);
        if ch.len() > 2 { out.push((v >> 8) as u8); }
        if ch.len() > 3 { out.push(v as u8); }
    }
    Ok(out)
}

fn ws(b: &[u8], mut i: usize) -> usize {
    while i < b.len() && matches!(b[i], b' ' | b'\t' | b'\n' | b'\r') { i += 1; }
    i
}
/// b[i] == '"': the string's raw content range and the index after its closing quote.
fn jstr(b: &[u8], i: usize) -> Result<(usize, usize, usize), ProgramError> {
    if b.get(i) != Some(&b'"') { return Err(err(61, "bad json")); }
    let mut k = i + 1;
    while k < b.len() {
        match b[k] {
            b'\\' => k += 2,
            b'"' => return Ok((i + 1, k, k + 1)),
            _ => k += 1,
        }
    }
    Err(err(61, "bad json"))
}
fn skip_value(b: &[u8], i: usize) -> Result<usize, ProgramError> {
    match b.get(i) {
        Some(b'"') => Ok(jstr(b, i)?.2),
        Some(b'{') | Some(b'[') => {
            let mut depth = 0usize;
            let mut k = i;
            while k < b.len() {
                match b[k] {
                    b'"' => { k = jstr(b, k)?.2; continue; }
                    b'{' | b'[' => depth += 1,
                    b'}' | b']' => { depth -= 1; if depth == 0 { return Ok(k + 1); } }
                    _ => {}
                }
                k += 1;
            }
            Err(err(61, "bad json"))
        }
        Some(_) => {
            let mut k = i;
            while k < b.len() && !matches!(b[k], b',' | b'}' | b']' | b' ' | b'\t' | b'\n' | b'\r') { k += 1; }
            if k == i { Err(err(61, "bad json")) } else { Ok(k) }
        }
        None => Err(err(61, "bad json")),
    }
}
/// One pass over a flat JSON object: for each wanted key, its value (a string's raw content, or the raw token) and
/// whether it was a string. A wanted key that appears twice is refused.
fn fields<'a, const N: usize>(b: &'a [u8], want: [&[u8]; N]) -> Result<[Option<(&'a [u8], bool)>; N], ProgramError> {
    let mut got: [Option<(&'a [u8], bool)>; N] = [None; N];
    let mut i = ws(b, 0);
    if b.get(i) != Some(&b'{') { return Err(err(61, "bad json")); }
    i = ws(b, i + 1);
    if b.get(i) == Some(&b'}') { return Ok(got); }
    loop {
        let (ks, ke, next) = jstr(b, i)?;
        i = ws(b, next);
        if b.get(i) != Some(&b':') { return Err(err(61, "bad json")); }
        let vs = ws(b, i + 1);
        let ve = skip_value(b, vs)?;
        let key = &b[ks..ke];
        for (w, g) in want.iter().zip(got.iter_mut()) {
            if key == *w {
                if g.is_some() { return Err(err(62, "duplicate claim")); }
                *g = Some(if b[vs] == b'"' { (&b[vs + 1..ve - 1], true) } else { (&b[vs..ve], false) });
            }
        }
        i = ws(b, ve);
        match b.get(i) {
            Some(b',') => i = ws(b, i + 1),
            Some(b'}') => return Ok(got),
            _ => return Err(err(61, "bad json")),
        }
    }
}
fn want_str<'a>(f: Option<(&'a [u8], bool)>, what: &str) -> Result<&'a [u8], ProgramError> {
    match f { Some((v, true)) => Ok(v), _ => Err(err(63, what)) }
}

fn buffer_key(program_id: &Pubkey, job_id: &[u8; 32], prover: &Pubkey) -> (Pubkey, u8) {
    Pubkey::find_program_address(&[b"ghproof", job_id, prover.as_ref()], program_id)
}
fn job_id_of(rest: &[u8]) -> Result<[u8; 32], ProgramError> {
    rest.get(0..32).ok_or(ProgramError::InvalidInstructionData).map(|s| s.try_into().unwrap())
}
/// The JWT's three parts: header, payload, signature (base64url).
fn split_jwt(t: &[u8]) -> Result<(&[u8], &[u8], &[u8]), ProgramError> {
    let a = t.iter().position(|&c| c == b'.').ok_or_else(|| err(64, "not a jwt"))?;
    let b = a + 1 + t[a + 1..].iter().position(|&c| c == b'.').ok_or_else(|| err(64, "not a jwt"))?;
    Ok((&t[..a], &t[a + 1..b], &t[b + 1..]))
}
fn signature(sig_b64: &[u8], n: &Big) -> Result<Big, ProgramError> {
    let s = b64url(sig_b64)?;
    if s.len() != 256 { return Err(err(65, "signature is not 256 bytes")); }
    let s = be_to_limbs(&s);
    if geq(&s, n) { return Err(err(65, "signature out of range")); }
    Ok(s)
}

pub fn process(program_id: &Pubkey, accounts: &[AccountInfo], tag: u8, rest: &[u8], config_key: &Pubkey,
               vault_auth: &Pubkey, vault_bump: u8) -> ProgramResult {
    let it = &mut accounts.iter();
    match tag {
        15 => {
            let admin = next_account_info(it)?; let config = next_account_info(it)?; let key = next_account_info(it)?;
            let sys = next_account_info(it)?;
            let cfg = Config::load(config, program_id, config_key)?;
            if !admin.is_signer || *admin.key != cfg.admin { return Err(err(15, "admin only")); }
            if *sys.key != system_program::ID { return Err(err(1, "system")); }
            let kl = *rest.first().ok_or(ProgramError::InvalidInstructionData)? as usize;
            let base = 1 + kl + 256 + 256 + 4;
            // 0.3.9: a trailing issuer id scopes the key to that registered issuer (5th account: ["issuer", id])
            if kl == 0 || kl > 64 || (rest.len() != base && rest.len() != base + 1) { return Err(ProgramError::InvalidInstructionData); }
            let issuer = if rest.len() == base + 1 {
                let id = rest[base];
                let (kind, h) = issuer_of(program_id, next_account_info(it)?, id)?;
                Some((id, kind, h))
            } else { None };
            let rest = &rest[..base];
            let kid = &rest[1..1 + kl];
            let n = be_to_limbs(&rest[1 + kl..1 + kl + 256]);
            let r2 = be_to_limbs(&rest[1 + kl + 256..1 + kl + 512]);
            let n0inv = u32::from_le_bytes(rest[1 + kl + 512..].try_into().unwrap());
            if n[0] & 1 == 0 || n[L - 1] >> 31 == 0 { return Err(err(66, "not a 2048-bit odd modulus")); }
            if n[0].wrapping_mul(n0inv) != u32::MAX { return Err(err(66, "n0inv")); }
            // r2 < n and r2 * R^-1 == R mod n (= 2^2048 - n, as n > 2^2047): r2 is R^2 mod n.
            if geq(&r2, &n) { return Err(err(66, "r2")); }
            let mut one = [0u32; L]; one[0] = 1;
            let r = mont_mul(&r2, &one, &n, n0inv);
            let mut r_mod_n = [0u32; L];
            sub_in(&mut r_mod_n, &n);
            if r != r_mod_n { return Err(err(66, "r2 is not R^2 mod n")); }
            let kh = hashv(&[kid]).to_bytes();
            let idb = [issuer.map(|i| i.0).unwrap_or(0)];
            let (kk, bump) = match issuer {
                None => Pubkey::find_program_address(&[b"ghkey", &kh], program_id),
                Some(_) => Pubkey::find_program_address(&[b"ghkey", &kh, &idb], program_id),
            };
            if *key.key != kk { return Err(err(5, "key address")); }
            if !key.data_is_empty() || *key.owner != system_program::ID { return Err(err(6, "key exists")); }
            match issuer {
                None => create_pda(admin, key, sys, program_id, KEY_LEN, &[b"ghkey", &kh, &[bump]])?,
                Some(_) => create_pda(admin, key, sys, program_id, KEY2_LEN, &[b"ghkey", &kh, &idb, &[bump]])?,
            }
            let mut d = key.try_borrow_mut_data()?;
            store(&mut d, 0, &n); d[256..260].copy_from_slice(&n0inv.to_le_bytes()); store(&mut d, 260, &r2);
            if let Some((id, kind, h)) = issuer { d[KEY_LEN] = id; d[KEY_LEN + 1] = kind; d[KEY_LEN + 2..].copy_from_slice(&h); }
            Ok(())
        }
        16 => {
            let prover = next_account_info(it)?; let buf = next_account_info(it)?; let sys = next_account_info(it)?;
            let job_id = job_id_of(rest)?;
            if rest.len() < 36 { return Err(ProgramError::InvalidInstructionData); }
            let total = u16::from_le_bytes(rest[32..34].try_into().unwrap()) as usize;
            let off = u16::from_le_bytes(rest[34..36].try_into().unwrap()) as usize;
            let chunk = &rest[36..];
            if total > MAX_JWT || off + chunk.len() > total { return Err(err(67, "proof too long")); }
            if !prover.is_signer || *sys.key != system_program::ID { return Err(err(8, "buffer accounts")); }
            let (bk, bump) = buffer_key(program_id, &job_id, prover.key);
            if *buf.key != bk { return Err(err(5, "buffer address")); }
            if buf.data_is_empty() {
                create_pda(prover, buf, sys, program_id, BUF_LEN, &[b"ghproof", &job_id, prover.key.as_ref(), &[bump]])?;
            } else if buf.owner != program_id || buf.data_len() != BUF_LEN {
                return Err(err(5, "buffer account"));
            }
            let mut d = buf.try_borrow_mut_data()?;
            d[B_STAGE] = 0;
            d[B_LEN..B_LEN + 2].copy_from_slice(&(total as u16).to_le_bytes());
            d[B_JWT + off..B_JWT + off + chunk.len()].copy_from_slice(chunk);
            Ok(())
        }
        17 | 18 | 26 => {
            let prover = next_account_info(it)?; let buf = next_account_info(it)?; let key = next_account_info(it)?;
            let job_id = job_id_of(rest)?;
            if !prover.is_signer { return Err(err(8, "prover signs")); }
            let (bk, _) = buffer_key(program_id, &job_id, prover.key);
            if *buf.key != bk || buf.owner != program_id || buf.data_len() != BUF_LEN { return Err(err(5, "buffer account")); }
            let ki = load_key(program_id, key)?;
            let (n, n0inv) = (ki.n, ki.n0inv);
            if tag == 17 {
                let mut d = buf.try_borrow_mut_data()?;
                let len = u16::from_le_bytes(d[B_LEN..B_LEN + 2].try_into().unwrap()) as usize;
                let (_, _, sig) = split_jwt(&d[B_JWT..B_JWT + len])?;
                let s = signature(sig, &n)?;
                let r2 = load(&key.try_borrow_data()?, 260);
                let mut x = mont_mul(&s, &r2, &n, n0inv); // s in Montgomery form
                for _ in 0..8 { x = mont_sqr(&x, &n, n0inv); }
                store(&mut d, B_X, &x);
                d[B_KEY..B_KEY + 32].copy_from_slice(key.key.as_ref());
                d[B_STAGE] = 1;
                return Ok(());
            }
            if tag == 26 { return fund_with_token(program_id, it, prover, buf, key, &ki, &job_id, config_key); }
            let job = next_account_info(it)?; let vault_tok = next_account_info(it)?; let vauth = next_account_info(it)?;
            let worker_tok = next_account_info(it)?; let fee_tok = next_account_info(it)?; let buyer = next_account_info(it)?;
            let config = next_account_info(it)?; let token = next_account_info(it)?; let wf = next_account_info(it)?;
            if !prover.is_writable || *token.key != TOKEN_PROGRAM { return Err(err(9, "verify accounts")); }
            let cfg = Config::load(config, program_id, config_key)?;
            let (jk, _) = Pubkey::find_program_address(&[b"job", &job_id], program_id);
            if *job.key != jk || job.owner != program_id || !is_gh_job(job.data_len()) { return Err(err(69, "not a github job")); }
            let now = Clock::get()?.unix_timestamp;
            let payout: Pubkey;
            let stake_required: bool;
            {
                let d = buf.try_borrow_data()?;
                let payload = verified_payload(program_id, &d, key, &ki)?;
                let c = claims(&payload, &ki)?;
                // the run's workflow file is pinned by commit: its sha must be in the registry (SetWorkflow, kind 0)
                if !workflow_registered(program_id, wf, WF_PROVE, c.wsha) { return Err(err(73, "workflow sha not registered")); }
                let jd = job.try_borrow_data()?;
                if hashv(&[c.repo]).to_bytes()[..] != jd[JOB_LEN..JOB_LEN + 32] { return Err(err(74, "repository")); }
                if hashv(&[c.rf]).to_bytes()[..] != jd[JOB_LEN + 32..JOB_LEN + 64] { return Err(err(74, "ref")); }
                // aud = "knos:<job hex 64>:<head sha 40>:<checks hash hex 64>:<payout base58>"
                let a = c.aud;
                let mut want = [0u8; 5 + 64 + 1];
                want[..5].copy_from_slice(b"knos:");
                hex_into(&job_id, &mut want[5..69]);
                want[69] = b':';
                if a.len() < 70 + 40 + 1 + 64 + 1 + 32 || a[..70] != want { return Err(err(75, "audience")); }
                let head = &a[70..110];
                let mut ch = [0u8; 64];
                hex_into(&jd[GH_CHECKS..GH_CHECKS + 32], &mut ch);
                if a[110] != b':' || a[111..175] != ch || a[175] != b':' { return Err(err(75, "audience: checks hash")); }
                if !is_sha40(head) || want_str(c.sha, "sha")? != head { return Err(err(75, "audience: head sha")); }
                payout = Pubkey::new_from_array(b58_32(&a[176..]).ok_or_else(|| err(75, "audience: payout"))?);
                stake_required = jd[GH_STAKE_REQ] != 0;
                if c.exp <= now { return Err(err(76, "token expired")); }
            }
            // pay the payout the token names: price - fee (+ the stake back, when the job required a claim stake: then
            // only the claimer can be the payout); the fee to the fee account; close the job and the buffer. Anyone
            // may relay the proof and pay the gas. A funded job (0.3.9) pays from its mint's vault; its fee goes to
            // the admin's account of that mint.
            let mut j = Job::load(&job.try_borrow_data()?)?;
            let vb = bounty::vault_bump_for(&j.mint, vauth.key, program_id, (*vault_auth, vault_bump))?;
            if now > j.deadline { return Err(err(20, "past the deadline")); }
            if stake_required {
                if j.state != S::Claimed as u8 || j.worker != payout { return Err(err(20, "a staked job pays its claimer only")); }
            } else if j.state != S::Open as u8 { return Err(err(20, "not open")); }
            let (wo, wm) = token_owner_mint(worker_tok)?;
            let jm = if j.mint == Pubkey::default() { cfg.mint } else { j.mint };
            if wo != payout || wm != jm { return Err(err(33, "payee")); }
            if j.mint == Pubkey::default() {
                if *fee_tok.key != cfg.fee_token { return Err(err(33, "payee")); }
            } else {
                let (fo, fm) = token_owner_mint(fee_tok)?;
                if fo != cfg.admin || fm != j.mint { return Err(err(33, "payee")); }
            }
            let fee = cfg.fee(j.amount).min(j.amount);
            let to_worker = (j.amount - fee).checked_add(j.stake).ok_or(ProgramError::ArithmeticOverflow)?;
            j.state = S::Released as u8; j.stake = 0; j.store(&mut job.try_borrow_mut_data()?);
            let b = [vb]; let seeds = vseeds(&j.mint, &b);
            if to_worker > 0 { token_transfer(token, vault_tok, worker_tok, vauth, to_worker, Some(&seeds[..]))?; }
            if fee > 0 { token_transfer(token, vault_tok, fee_tok, vauth, fee, Some(&seeds[..]))?; }
            close_job(&j, job, buyer)?;
            close_buffer(buf, prover)
        }
        19 => {
            let buyer = next_account_info(it)?; let job = next_account_info(it)?; let buyer_tok = next_account_info(it)?;
            let vault_tok = next_account_info(it)?; let config = next_account_info(it)?; let token = next_account_info(it)?; let sys = next_account_info(it)?;
            // data: ... repo_hash[32] ref_hash[32] checks_hash[32] stake_required u8
            if rest.len() != 32 + 8 + 8 + 8 + 32 + 64 + 33 || rest[184] > 1 { return Err(ProgramError::InvalidInstructionData); }
            let id: [u8; 32] = rest[0..32].try_into().unwrap();
            let amount = u64::from_le_bytes(rest[32..40].try_into().unwrap());
            let work = i64::from_le_bytes(rest[40..48].try_into().unwrap());
            let review = i64::from_le_bytes(rest[48..56].try_into().unwrap());
            let brief: [u8; 32] = rest[56..88].try_into().unwrap();
            if !buyer.is_signer || *token.key != TOKEN_PROGRAM || *sys.key != system_program::ID { return Err(err(3, "post accounts")); }
            let cfg = Config::load(config, program_id, config_key)?;
            if cfg.paused { return Err(err(17, "paused: no new jobs")); }
            if amount != 0 && amount < cfg.min_amount { return Err(err(18, "below the minimum job")); }
            if cfg.max_amount != 0 && amount > cfg.max_amount { return Err(err(19, "over the per-job cap")); }
            if work <= 0 || review <= 0 { return Err(err(4, "bad terms")); }
            let (job_key, bump) = Pubkey::find_program_address(&[b"job", &id], program_id);
            if *job.key != job_key { return Err(err(5, "job address")); }
            if !job.data_is_empty() || *job.owner != system_program::ID { return Err(err(6, "job exists")); }
            let (vo, vm) = token_owner_mint(vault_tok)?; let (_, bm) = token_owner_mint(buyer_tok)?;
            if vo != *vault_auth || vm != cfg.mint || bm != cfg.mint { return Err(err(7, "vault or mint")); }
            create_pda(buyer, job, sys, program_id, GH_JOB_LEN, &[b"job", &id, &[bump]])?;
            if amount > 0 { token_transfer(token, buyer_tok, vault_tok, buyer, amount, None)?; }
            let now = Clock::get()?.unix_timestamp;
            let mut d = job.try_borrow_mut_data()?;
            Job { state: S::Open as u8, buyer: *buyer.key, worker: Pubkey::default(), amount, deadline: now.saturating_add(work), review,
                  brief, result: [0; 32], verifier: Pubkey::default(), proof: [0; 32], stake: 0, mint: Pubkey::default() }
                .store(&mut d);
            d[JOB_LEN..GH_JOB_LEN].copy_from_slice(&rest[88..185]);
            Ok(())
        }
        _ => Err(ProgramError::InvalidInstructionData),
    }
}

/// 26 FundWithToken  payer(s,w) buffer(w) key job(w) vault_token(w) faucet mint(w) registry config2 token system
///                   workflow fundrate(w)                    data: job_id[32] (the buffer's; checked against the token)
/// Devnet: a fund.yml run (its job_workflow_sha registered with kind 1) proves "fund issue <issue> of <repository>
/// with <amount> test USDC": the token (BufferWrite + VerifyStep1 first, as for a proof) has
/// aud = "knos:fund:<issue>:<amount units>:<checks hash 64 hex>:<stake 0|1>". The job id is
/// sha256("knos-fund" | repository | "#" | issue); the job is a github job on the token's repository and ref with that
/// checks hash, in the faucet's mint (registered with AddMint), and the faucet mints the amount (at most its cap) into
/// that mint's vault. The payer is the job's buyer. One funding per repository per hour (["fundrate", repo hash]).
#[allow(clippy::too_many_arguments)]
fn fund_with_token<'a, 'b>(program_id: &Pubkey, it: &mut core::slice::Iter<'b, AccountInfo<'a>>, payer: &AccountInfo<'a>,
                           buf: &AccountInfo<'a>, key: &AccountInfo<'a>, ki: &KeyInfo, job_id: &[u8; 32],
                           config_key: &Pubkey) -> ProgramResult {
    if !bounty::DEVNET { return Err(err(60, "faucet: devnet only")); }
    let job = next_account_info(it)?; let vault_tok = next_account_info(it)?; let faucet = next_account_info(it)?;
    let mint = next_account_info(it)?; let reg = next_account_info(it)?; let config = next_account_info(it)?;
    let token = next_account_info(it)?; let sys = next_account_info(it)?; let wf = next_account_info(it)?;
    let rate = next_account_info(it)?;
    if !payer.is_writable || *token.key != TOKEN_PROGRAM || *sys.key != system_program::ID { return Err(err(9, "fund accounts")); }
    let cfg = Config::load(config, program_id, config_key)?;
    if cfg.paused { return Err(err(17, "paused: no new jobs")); }
    let (fk, _) = Pubkey::find_program_address(&[b"faucet"], program_id);
    if *faucet.key != fk || faucet.owner != program_id || faucet.data_len() != bounty::FAUCET_LEN { return Err(err(61, "faucet accounts")); }
    let (fmint, cap, fb) = {
        let d = faucet.try_borrow_data()?;
        (Pubkey::new_from_array(d[0..32].try_into().unwrap()), u64::from_le_bytes(d[32..40].try_into().unwrap()), d[40])
    };
    if *mint.key != fmint { return Err(err(61, "not the faucet's mint")); }
    if *vault_tok.key != bounty::registry_vault(reg, &fmint, program_id)? { return Err(err(7, "vault or mint")); }
    let now = Clock::get()?.unix_timestamp;
    let mut ext = [0u8; 97 + 32]; // repo_hash ref_hash checks_hash stake_required mint
    let (amount, brief);
    {
        let d = buf.try_borrow_data()?;
        let payload = verified_payload(program_id, &d, key, ki)?;
        let c = claims(&payload, ki)?;
        if !workflow_registered(program_id, wf, WF_FUND, c.wsha) { return Err(err(73, "fund workflow sha not registered")); }
        if c.exp <= now { return Err(err(76, "token expired")); }
        // aud = "knos:fund:<issue>:<amount>:<checks hash hex 64>:<stake 0|1>"
        let a = c.aud;
        if !a.starts_with(b"knos:fund:") { return Err(err(75, "audience")); }
        let mut parts = a[10..].split(|&x| x == b':');
        let (issue, amt, ch, st) = match (parts.next(), parts.next(), parts.next(), parts.next(), parts.next()) {
            (Some(i), Some(m), Some(h), Some(s), None) => (i, m, h, s),
            _ => return Err(err(75, "audience")),
        };
        if parse_u64(issue).is_none() || !is_hex64(ch) || (st != b"0" && st != b"1") { return Err(err(75, "audience")); }
        amount = parse_u64(amt).ok_or_else(|| err(75, "audience: amount"))?;
        if hashv(&[b"knos-fund", c.repo, b"#", issue]).to_bytes() != *job_id { return Err(err(75, "job id is not the token's issue")); }
        ext[0..32].copy_from_slice(&hashv(&[c.repo]).to_bytes());
        ext[32..64].copy_from_slice(&hashv(&[c.rf]).to_bytes());
        ext[64..96].copy_from_slice(&unhex32(ch));
        ext[96] = (st == b"1") as u8;
        ext[97..].copy_from_slice(fmint.as_ref());
        brief = hashv(&[a]).to_bytes();
    }
    if amount > cap { return Err(err(63, "over the faucet's per-call cap")); }
    if amount != 0 && amount < cfg.min_amount { return Err(err(18, "below the minimum job")); }
    if cfg.max_amount != 0 && amount > cfg.max_amount { return Err(err(19, "over the per-job cap")); }
    // one funding per repository per hour
    let (rk, rb) = Pubkey::find_program_address(&[b"fundrate", &ext[0..32]], program_id);
    if *rate.key != rk { return Err(err(5, "fundrate address")); }
    if rate.owner == program_id && rate.data_len() == FUNDRATE_LEN {
        let last = i64::from_le_bytes(rate.try_borrow_data()?[0..8].try_into().unwrap());
        if now < last.saturating_add(FUND_PERIOD) { return Err(err(80, "one funding per repository per hour")); }
    } else {
        create_pda(payer, rate, sys, program_id, FUNDRATE_LEN, &[b"fundrate", &ext[0..32], &[rb]])?;
    }
    rate.try_borrow_mut_data()?[0..8].copy_from_slice(&now.to_le_bytes());
    let (jk, jb) = Pubkey::find_program_address(&[b"job", job_id], program_id);
    if *job.key != jk { return Err(err(5, "job address")); }
    if !job.data_is_empty() || *job.owner != system_program::ID { return Err(err(6, "job exists")); }
    create_pda(payer, job, sys, program_id, GH_MINT_JOB_LEN, &[b"job", job_id, &[jb]])?;
    {
        let mut d = job.try_borrow_mut_data()?;
        Job { state: S::Open as u8, buyer: *payer.key, worker: Pubkey::default(), amount, deadline: now.saturating_add(FUND_WORK),
              review: FUND_REVIEW, brief, result: [0; 32], verifier: Pubkey::default(), proof: [0; 32], stake: 0, mint: fmint }
            .store(&mut d);
        d[JOB_LEN..GH_MINT_JOB_LEN].copy_from_slice(&ext);
    }
    if amount > 0 {
        let mut ixd = vec![7u8]; ixd.extend_from_slice(&amount.to_le_bytes()); // SPL Token MintTo
        let ix = Instruction { program_id: TOKEN_PROGRAM, data: ixd,
            accounts: vec![AccountMeta::new(*mint.key, false), AccountMeta::new(*vault_tok.key, false), AccountMeta::new_readonly(fk, true)] };
        invoke_signed(&ix, &[mint.clone(), vault_tok.clone(), faucet.clone(), token.clone()], &[&[b"faucet", &[fb]]])?;
    }
    close_buffer(buf, payer)
}
