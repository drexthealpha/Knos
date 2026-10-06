//! ES256: tokens signed with ECDSA on P-256 and SHA-256 (RFC 7518, section 3.4), verified in ONE transaction.
//!
//! HOW A SIGNATURE IS CHECKED. This module does no elliptic-curve arithmetic. Solana's secp256r1 precompile
//! (SIMD-0075, program Secp256r1SigVerify1111111111111111111111111) verifies a P-256 signature over sha256 of a
//! message as an instruction of its own, and a transaction in which it fails does not run. VerifyEs256 requires
//! that the instruction right before it in the same transaction is that precompile, with exactly one signature
//! whose key, signature and message are all in that instruction's own data (`precompile`), and reads from it WHAT
//! was verified:
//!   the key        must be the 33 bytes the key account holds (the issuer's key, SEC1 compressed);
//!   the message    is the token's signing input, `base64url(header) "." base64url(payload)`: it is copied from
//!                  there into the token account, so the claims a consumer reads are the bytes that were verified;
//!   the signature  r then s, 32 bytes each, as JWS writes them; s must be in the lower half of the curve order.
//!                  The precompile enforces that; it is checked again here, because a consumer names its single-use
//!                  marker by the signature (knos_pay: ["used", sha256(signature)]) and (r, n - s) verifies
//!                  whenever (r, s) does. With the upper half refused, a token has one accepted signature. An
//!                  issuer's library may write the upper one: whoever carries the token replaces s by n - s, which
//!                  needs no secret and changes nothing that is signed (docs/ES256.md).
//! So the token rides in the transaction, and a legacy transaction is 1,232 bytes: the signing input can be at most
//! 780 bytes (measured by programs-v2/handlers/tests/knos_oidc_es256.rs; docs/ES256.md has the arithmetic).
//!
//! WHAT IT WRITES. The token account ["tok", payer, id] that Step writes for an RS256 token, with the same
//! layout: stage VERIFIED, the issuer number, the key account, the expiry, the payload decoded in place, and at
//! T_JWT the compact token `header.payload.signature`, the signature written here as the unpadded base64url of the
//! 64 bytes the precompile verified. `id` is sha256 of the signing input, so one payer verifies one token into one
//! account, once: the account must not exist. Two bytes differ from an RS256 token's and say which path wrote it:
//! T_DONE (squarings) and T_LIMBS are 0. Close (2) closes it, as any token account.
//!
//! KEYS. A P-256 key is admitted as an RSA key of an issuer other than GitHub and GitLab is, in an account of its
//! own kind (EC_ACCOUNT bytes; its third byte is EC_MARK, never an RSA key's limb count, so Step refuses it and
//! VerifyEs256 refuses an RSA key):
//!   header as an RSA key's (state 1, issuer, EC_MARK, bump, 4 zero bytes, active_at i64, expires_at i64, flags u8,
//!   15 zero bytes), then the key [33], then sha256 of the issuer's URL [32], then the registrant of a private key
//!   [32] (zero for an attested key).
//! The delay, the guardian's approval, the expiry, Refresh and revocation are those of lib.rs and pins.rs.
//!
//! INSTRUCTIONS (the first byte is the tag; (s) signs, (w) is writable).
//!   10 RegisterEs256Key         payer(s,w) key(w) iss(w) system attest attest_key
//!                               data: url_len u8, the issuer's URL, key [33]
//!        RegisterIssuerKey's rule for a P-256 key. Creates ["eckey", sha256(url), sha256(key)] and, with the
//!        issuer's first key, ["iss", sha256(url)]. The attestation's audience is
//!        "knos-oidc:eckey:<sha256(url) hex>:<sha256(key) hex>". No commit of the rotate workflow that is pinned
//!        today asks for that audience, so on a real build no key enters this way until one that does is pinned.
//!   11 RegisterPrivateEs256Key  registrant(s,w) key(w) system        data: the same
//!        RegisterPrivateKey's rule: ["epkey", registrant, sha256(url), sha256(key)], ISSUER_PRIVATE, F_PRIVATE,
//!        usable at once until now + KEY_TTL; sent again by the same wallet it moves the expiry.
//!   12 RefreshEs256             payer(s) key(w) attest attest_key    Refresh's rule, for an attested P-256 key.
//!   13 ApproveEs256             guardian(s) key(w)                   Approve's rule.
//!   14 RevokeEs256              guardian(s) key(w)                   Revoke's rule (the registrant, for a private key).
//!   15 VerifyEs256              payer(s,w) token(w) key system instructions      no data
//!        The instruction before this one is the precompile, as above. Refuses a key that is not usable now, a
//!        header whose `alg` is not "ES256", a header or payload that is not one strict JSON object (strict.rs), an
//!        `iss` that is not the key's issuer, an `exp` more than AHEAD ahead of the clock, and a token account that
//!        exists. The payer pays the account's rent.
use crate::{
    claims::{self, err, text},
    pins, strict, AHEAD, E_ACCOUNTS, E_ALG, E_GUARDIAN, E_ISS, E_KEY, E_LEN, E_REVOKED, E_STAGE, F_APPROVED, F_PRIVATE, F_REVOKED, ISS_HDR,
    ISS_STATE, KEY_TAIL, K_ACTIVE, K_BUMP, K_EXPIRES, K_FLAGS, K_HDR, K_ISSUER, K_LIMBS, K_STATE, MAX_ISS, MAX_JWT, T_EXP, T_ID, T_IHASH,
    T_ISSUER, T_JWT, T_KEY, T_LEN, T_PAYER, T_PLEN, T_POFF, T_STAGE, VERIFIED,
};
use solana_program::{
    account_info::AccountInfo,
    clock::Clock,
    entrypoint::ProgramResult,
    hash::hashv,
    program_error::ProgramError,
    pubkey,
    pubkey::Pubkey,
    system_program,
    sysvar::{instructions, Sysvar},
};

/// Solana's secp256r1 signature verification precompile (SIMD-0075).
pub const SECP256R1_ID: Pubkey = pubkey!("Secp256r1SigVerify1111111111111111111111111");
pub const EC_KEY_LEN: usize = 33; // a P-256 public key, SEC1 compressed: 0x02 or 0x03, then x
pub const SIG_LEN: usize = 64;    // r, then s, 32 bytes each, big-endian: the JWS signature of an ES256 token
pub const SIG_TEXT: usize = 86;   // its unpadded base64url
/// The third byte of a P-256 key account, where an RSA key holds its limb count (64 or 128), a token account its
/// squarings (at most 16) and an issuer account 0.
pub const EC_MARK: u8 = 0xEC;
pub const EC_KEY: usize = K_HDR;
pub const EC_IHASH: usize = K_HDR + EC_KEY_LEN;
pub const EC_REGISTRANT: usize = EC_IHASH + 32;
pub const EC_ACCOUNT: usize = K_HDR + EC_KEY_LEN + KEY_TAIL; // 137
const SELF: u16 = u16::MAX; // an instruction index of the precompile: "these bytes are in my own data"

// errors, after lib.rs's 64-79
pub const E_PRECOMPILE: u32 = 80; // the instruction before this one is not one secp256r1 verification of its own data
pub const E_EC_KEY: u32 = 81;     // not a compressed P-256 key, or not a P-256 key account of this program
pub const E_SIGNER: u32 = 82;     // the signature verified is another key's, not the key account's
pub const E_HIGH_S: u32 = 83;     // the signature's s is in the upper half of the curve order

/// Half the order of P-256, big-endian. A signature (r, s) and (r, n - s) verify alike; only s <= n/2 is accepted.
pub const HALF_N: [u8; 32] = [
    0x7F, 0xFF, 0xFF, 0xFF, 0x80, 0x00, 0x00, 0x00, 0x7F, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
    0xDE, 0x73, 0x7D, 0x56, 0xD3, 0x8B, 0xCF, 0x42, 0x79, 0xDC, 0xE5, 0x61, 0x7E, 0x31, 0x92, 0xA8,
];

pub struct Checked<'a> { pub key: &'a [u8], pub signature: &'a [u8], pub message: &'a [u8] }

/// What a secp256r1 precompile instruction with this data verified, when it is exactly one signature whose key,
/// signature and message are all in the instruction's own data. The data is: count u8, padding u8, then per signature
/// seven u16 LE (signature offset, signature instruction, key offset, key instruction, message offset, message
/// length, message instruction). The precompile reads each part from the instruction an index names, so a record
/// that points anywhere else is refused here: the bytes at the offsets would not be the bytes that were verified.
/// (knos_passkey reads the precompile the same way.)
pub fn precompile(data: &[u8]) -> Option<Checked<'_>> {
    if data.len() < 16 || data[0] != 1 { return None; }
    let n = |k: usize| u16::from_le_bytes([data[2 + 2 * k], data[3 + 2 * k]]);
    if n(1) != SELF || n(3) != SELF || n(6) != SELF { return None; }
    let at = |offset: u16, len: usize| data.get(offset as usize..offset as usize + len);
    Some(Checked { signature: at(n(0), SIG_LEN)?, key: at(n(2), EC_KEY_LEN)?, message: at(n(4), n(5) as usize)? })
}

/// s <= n/2 (big-endian bytes compare as the numbers do).
pub fn low_s(signature: &[u8]) -> bool { signature.len() == SIG_LEN && signature[32..] <= HALF_N[..] }

/// Unpadded base64url of `src` into `out`, which is exactly as long as that text.
pub fn b64url(src: &[u8], out: &mut [u8]) {
    const A: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    for (k, c) in src.chunks(3).enumerate() {
        let v = (c[0] as u32) << 16 | (*c.get(1).unwrap_or(&0) as u32) << 8 | *c.get(2).unwrap_or(&0) as u32;
        for j in 0..(c.len() + 1) { out[4 * k + j] = A[(v >> (18 - 6 * j)) as usize & 63]; }
    }
}

/// "knos-oidc:eckey:<sha256(url) hex>:<sha256(key) hex>": what a rotate workflow asks GitHub to sign for a P-256 key.
/// Its second part is not "key" and not "ikey": an attestation of an RSA key never admits a P-256 key, nor the reverse.
pub fn ec_audience(ih: &[u8; 32], kh: &[u8; 32]) -> Vec<u8> {
    let mut want = Vec::with_capacity(145);
    want.extend_from_slice(b"knos-oidc:eckey:");
    super::push_hex(&mut want, ih);
    want.push(b':');
    super::push_hex(&mut want, kh);
    want
}

/// The issuer's URL and the key of the registering instructions' data: url_len u8, url, key [33]. The URL's rule is
/// RegisterIssuerKey's: "https://", printable ASCII with no quote and no backslash, at most MAX_ISS bytes.
pub fn url_and_key(rest: &[u8]) -> Result<(&[u8], &[u8]), ProgramError> {
    let (&ul, rest) = rest.split_first().ok_or(ProgramError::InvalidInstructionData)?;
    let ul = ul as usize;
    if rest.len() != ul + EC_KEY_LEN { return Err(ProgramError::InvalidInstructionData); }
    let (url, key) = rest.split_at(ul);
    let plain = url.iter().all(|&c| (0x21..0x7f).contains(&c) && c != b'"' && c != b'\\');
    if ul > MAX_ISS || url.len() <= 8 || !url.starts_with(b"https://") || !plain { return Err(err(E_ISS)); }
    if !matches!(key[0], 2 | 3) { return Err(err(E_EC_KEY)); }
    Ok((url, key))
}

/// `key` is a P-256 key account of this program: E_EC_KEY for any other account (an RSA key, a token, an issuer).
fn ec_account(program_id: &Pubkey, key: &AccountInfo) -> ProgramResult {
    if key.owner != program_id { return Err(err(E_EC_KEY)); }
    let d = key.try_borrow_data()?;
    if d.len() != EC_ACCOUNT || d[K_STATE] != 1 || d[K_LIMBS] != EC_MARK { return Err(err(E_EC_KEY)); }
    Ok(())
}

fn new_key(d: &mut [u8], issuer: u8, bump: u8, flags: u8, active: i64, key: &[u8], ih: &[u8; 32]) {
    d[K_STATE] = 1; d[K_ISSUER] = issuer; d[K_LIMBS] = EC_MARK; d[K_BUMP] = bump; d[K_FLAGS] = flags;
    super::put_i64(d, K_ACTIVE, active);
    super::put_i64(d, K_EXPIRES, active.saturating_add(pins::KEY_TTL));
    d[EC_KEY..EC_IHASH].copy_from_slice(key);
    d[EC_IHASH..EC_REGISTRANT].copy_from_slice(ih);
}

pub fn process(program_id: &Pubkey, tag: u8, accounts: &[AccountInfo], rest: &[u8]) -> ProgramResult {
    match tag {
        10 => register(program_id, accounts, rest),
        11 => register_private(program_id, accounts, rest),
        12 => refresh(program_id, accounts, rest),
        13 => approve(program_id, accounts, rest),
        14 => revoke(program_id, accounts, rest),
        15 => verify(program_id, accounts, rest),
        _ => Err(ProgramError::InvalidInstructionData),
    }
}

fn register(program_id: &Pubkey, accounts: &[AccountInfo], rest: &[u8]) -> ProgramResult {
    let [payer, key, iss, sys, attest, akey] = accounts else { return Err(err(E_ACCOUNTS)) };
    let (url, pk) = url_and_key(rest)?;
    if !payer.is_signer || !payer.is_writable || *sys.key != system_program::ID { return Err(err(E_ACCOUNTS)); }
    let (ih, kh) = (hashv(&[url]).to_bytes(), hashv(&[pk]).to_bytes());
    let (kk, bump) = Pubkey::find_program_address(&[b"eckey", &ih, &kh], program_id);
    let (ik, ibump) = Pubkey::find_program_address(&[b"iss", &ih], program_id);
    // a key account is never closed, so a key that was registered once (and perhaps revoked) stops here
    if *key.key != kk || !key.data_is_empty() || *key.owner != system_program::ID || *iss.key != ik { return Err(err(E_ACCOUNTS)); }
    let now = Clock::get()?.unix_timestamp;
    super::attested(program_id, attest, akey, &ec_audience(&ih, &kh), false, now)?;
    // the issuer's URL goes on chain with its first key, RSA or P-256: the same account, the same bytes
    if iss.owner != program_id {
        if !iss.data_is_empty() || *iss.owner != system_program::ID { return Err(err(E_ACCOUNTS)); }
        super::create_pda(payer, iss, sys, program_id, ISS_HDR + url.len(), &[b"iss", &ih, &[ibump]])?;
        let mut d = iss.try_borrow_mut_data()?;
        d[..ISS_HDR].copy_from_slice(&[ISS_STATE, ibump, 0, url.len() as u8]);
        d[ISS_HDR..].copy_from_slice(url);
    }
    super::create_pda(payer, key, sys, program_id, EC_ACCOUNT, &[b"eckey", &ih, &kh, &[bump]])?;
    // it waits, and needs the guardian's approval, as every key GitHub's signature admits
    new_key(&mut key.try_borrow_mut_data()?, pins::ISSUER_OTHER, bump, 0, now.saturating_add(pins::KEY_DELAY), pk, &ih);
    Ok(())
}

fn register_private(program_id: &Pubkey, accounts: &[AccountInfo], rest: &[u8]) -> ProgramResult {
    let [registrant, key, sys] = accounts else { return Err(err(E_ACCOUNTS)) };
    let (url, pk) = url_and_key(rest)?;
    if !registrant.is_signer || !registrant.is_writable || *sys.key != system_program::ID { return Err(err(E_ACCOUNTS)); }
    let (ih, kh) = (hashv(&[url]).to_bytes(), hashv(&[pk]).to_bytes());
    // the registrant is part of the address: nobody registers, renews or shadows a key in another wallet's name
    let (kk, bump) = Pubkey::find_program_address(&[b"epkey", registrant.key.as_ref(), &ih, &kh], program_id);
    if *key.key != kk { return Err(err(E_ACCOUNTS)); }
    let now = Clock::get()?.unix_timestamp;
    if key.owner == program_id {
        // the same wallet, the same key: it lives KEY_TTL from now. A revoked key stays revoked.
        ec_account(program_id, key)?;
        let mut d = key.try_borrow_mut_data()?;
        if d[K_FLAGS] & F_REVOKED != 0 { return Err(err(E_REVOKED)); }
        let expires = super::i64_at(&d, K_EXPIRES).max(now.saturating_add(pins::KEY_TTL));
        super::put_i64(&mut d, K_EXPIRES, expires);
        return Ok(());
    }
    if !key.data_is_empty() || *key.owner != system_program::ID { return Err(err(E_ACCOUNTS)); }
    super::create_pda(registrant, key, sys, program_id, EC_ACCOUNT, &[b"epkey", registrant.key.as_ref(), &ih, &kh, &[bump]])?;
    let mut d = key.try_borrow_mut_data()?;
    new_key(&mut d, pins::ISSUER_PRIVATE, bump, F_PRIVATE, now, pk, &ih);
    d[EC_REGISTRANT..].copy_from_slice(registrant.key.as_ref());
    Ok(())
}

fn refresh(program_id: &Pubkey, accounts: &[AccountInfo], rest: &[u8]) -> ProgramResult {
    let [payer, key, attest, akey] = accounts else { return Err(err(E_ACCOUNTS)) };
    if !rest.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !payer.is_signer { return Err(err(E_ACCOUNTS)); }
    ec_account(program_id, key)?;
    let now = Clock::get()?.unix_timestamp;
    // the hashes GitHub must have named are those of the issuer and the key this account holds
    let want = {
        let d = key.try_borrow_data()?;
        if d[K_FLAGS] & F_REVOKED != 0 { return Err(err(E_REVOKED)); }
        if d[K_ISSUER] != pins::ISSUER_OTHER { return Err(err(E_ISS)); } // a private key is renewed by its registrant
        let mut ih = [0u8; 32];
        ih.copy_from_slice(&d[EC_IHASH..EC_REGISTRANT]);
        ec_audience(&ih, &hashv(&[&d[EC_KEY..EC_IHASH]]).to_bytes())
    };
    super::attested(program_id, attest, akey, &want, true, now)?;
    let mut d = key.try_borrow_mut_data()?;
    let expires = super::i64_at(&d, K_EXPIRES).max(now.saturating_add(pins::KEY_TTL));
    super::put_i64(&mut d, K_EXPIRES, expires);
    Ok(())
}

fn approve(program_id: &Pubkey, accounts: &[AccountInfo], rest: &[u8]) -> ProgramResult {
    let [guardian, key] = accounts else { return Err(err(E_ACCOUNTS)) };
    if !rest.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !guardian.is_signer || !pins::is_guardian(guardian.key) { return Err(err(E_GUARDIAN)); }
    ec_account(program_id, key)?;
    let mut d = key.try_borrow_mut_data()?;
    if d[K_FLAGS] & F_REVOKED != 0 { return Err(err(E_REVOKED)); }
    // a private key stays what it is: the guardian's approval is a statement about a key GitHub named
    if d[K_FLAGS] & F_PRIVATE != 0 { return Err(err(E_KEY)); }
    d[K_FLAGS] |= F_APPROVED;
    Ok(())
}

fn revoke(program_id: &Pubkey, accounts: &[AccountInfo], rest: &[u8]) -> ProgramResult {
    let [guardian, key] = accounts else { return Err(err(E_ACCOUNTS)) };
    if !rest.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !guardian.is_signer { return Err(err(E_GUARDIAN)); }
    ec_account(program_id, key).map_err(|_| err(E_GUARDIAN))?;
    let mut d = key.try_borrow_mut_data()?;
    // the guardian, for any key; or the wallet that registered a private key, for that key
    let registrant = d[K_FLAGS] & F_PRIVATE != 0 && d[K_ISSUER] == pins::ISSUER_PRIVATE && d[EC_REGISTRANT..] == guardian.key.as_ref()[..];
    if !pins::is_guardian(guardian.key) && !registrant { return Err(err(E_GUARDIAN)); }
    d[K_FLAGS] |= F_REVOKED;
    Ok(())
}

fn verify(program_id: &Pubkey, accounts: &[AccountInfo], rest: &[u8]) -> ProgramResult {
    let [payer, tok, key, sys, ixs] = accounts else { return Err(err(E_ACCOUNTS)) };
    if !rest.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !payer.is_signer || !payer.is_writable || *sys.key != system_program::ID || *ixs.key != instructions::ID { return Err(err(E_ACCOUNTS)); }
    // the key: a P-256 key of this program that may verify now, by the rule Step applies to an RSA key
    ec_account(program_id, key)?;
    let now = Clock::get()?.unix_timestamp;
    let (issuer, pk, tail) = {
        let d = key.try_borrow_data()?;
        crate::key_usable(d[K_FLAGS], super::i64_at(&d, K_ACTIVE), super::i64_at(&d, K_EXPIRES), now).map_err(err)?;
        let (mut pk, mut tail) = ([0u8; EC_KEY_LEN], [0u8; KEY_TAIL]);
        pk.copy_from_slice(&d[EC_KEY..EC_IHASH]);
        tail.copy_from_slice(&d[EC_IHASH..]);
        (d[K_ISSUER], pk, tail)
    };
    if issuer < pins::ISSUER_OTHER { return Err(err(E_EC_KEY)); } // no instruction writes one; a P-256 key is never GitHub's by number

    // what was verified: the instruction right before this one is the precompile, and it read its own data only
    let at = instructions::load_current_index_checked(ixs)? as usize;
    if at == 0 { return Err(err(E_PRECOMPILE)); }
    let before = instructions::load_instruction_at_checked(at - 1, ixs)?;
    if before.program_id != SECP256R1_ID { return Err(err(E_PRECOMPILE)); }
    let v = precompile(&before.data).ok_or_else(|| err(E_PRECOMPILE))?;
    if v.key != pk { return Err(err(E_SIGNER)); }
    if !low_s(v.signature) { return Err(err(E_HIGH_S)); }

    // the message is the signing input: base64url(header) "." base64url(payload), one dot, neither part empty
    let m = v.message;
    let total = m.len() + 1 + SIG_TEXT;
    if total > MAX_JWT { return Err(err(E_LEN)); }
    let dot = m.iter().position(|&c| c == b'.').ok_or_else(|| err(claims::E_JSON))?;
    if dot == 0 || dot + 1 >= m.len() || m[dot + 1..].contains(&b'.') { return Err(err(claims::E_JSON)); }
    let mut header = vec![0u8; claims::b64_len(dot).ok_or_else(|| err(claims::E_B64))?];
    strict::b64url_into(&m[..dot], &mut header)?;
    let [alg] = strict::fields(&header, [b"alg"])?;
    if text(alg)? != b"ES256" { return Err(err(E_ALG)); }

    // the account: this payer's, for this token, and not there yet
    let id = hashv(&[m]).to_bytes();
    let bump = super::token_account(program_id, payer.key, &id, tok)?;
    if !tok.data_is_empty() || *tok.owner != system_program::ID { return Err(err(E_STAGE)); }
    super::create_pda(payer, tok, sys, program_id, T_JWT + total, &[b"tok", payer.key.as_ref(), &id, &[bump]])?;
    let mut d = tok.try_borrow_mut_data()?;
    d[T_JWT..T_JWT + m.len()].copy_from_slice(m);
    d[T_JWT + m.len()] = b'.';
    b64url(v.signature, &mut d[T_JWT + m.len() + 1..]);

    // the claims, read as Step reads them: every byte of the payload is JSON, or nothing is marked VERIFIED
    let poff = T_JWT + dot + 1;
    let plen = strict::b64url_in_place(&mut d, poff, m.len() - dot - 1)?;
    let exp = {
        let [iss, exp] = strict::fields(&d[poff..poff + plen], [b"iss", b"exp"])?;
        if hashv(&[&text(iss)?]).to_bytes() != tail[..32] { return Err(err(E_ISS)); }
        match exp { Some(r) if !r.is_str => claims::parse_u64(r.bytes).ok_or_else(|| err(claims::E_CLAIM))? as i64, _ => return Err(err(claims::E_CLAIM)) }
    };
    if exp > now.saturating_add(AHEAD) { return Err(err(claims::E_CLAIM)); }
    d[T_ISSUER] = issuer;
    d[T_LEN..T_LEN + 2].copy_from_slice(&(total as u16).to_le_bytes());
    d[T_POFF..T_POFF + 2].copy_from_slice(&(poff as u16).to_le_bytes());
    d[T_PLEN..T_PLEN + 2].copy_from_slice(&(plen as u16).to_le_bytes());
    d[T_EXP..T_EXP + 8].copy_from_slice(&exp.to_le_bytes());
    d[T_KEY..T_KEY + 32].copy_from_slice(key.key.as_ref());
    d[T_PAYER..T_PAYER + 32].copy_from_slice(payer.key.as_ref());
    d[T_ID..T_ID + 32].copy_from_slice(&id);
    d[T_IHASH..T_IHASH + KEY_TAIL].copy_from_slice(&tail);
    d[T_STAGE] = VERIFIED;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A precompile instruction's data as the clients build it: the offsets, then key, signature, message.
    fn data(key: &[u8], sig: &[u8], msg: &[u8]) -> Vec<u8> {
        let mut d = vec![1u8, 0];
        for v in [16 + 33, SELF, 16, SELF, 16 + 33 + 64, msg.len() as u16, SELF] { d.extend_from_slice(&v.to_le_bytes()); }
        [d, key.to_vec(), sig.to_vec(), msg.to_vec()].concat()
    }

    #[test]
    fn one_signature_whose_parts_are_in_the_instruction_itself_is_read_and_nothing_else() {
        let (key, sig, msg) = ([2u8; 33], [7u8; 64], b"header.payload".to_vec());
        let d = data(&key, &sig, &msg);
        let v = precompile(&d).unwrap();
        assert_eq!((v.key, v.signature, v.message), (&key[..], &sig[..], &msg[..]));
        for count in [0u8, 2, 8] { let mut x = d.clone(); x[0] = count; assert!(precompile(&x).is_none()); }
        assert!(precompile(&d[..15]).is_none() && precompile(&[]).is_none());
        // a part that lives in another instruction: the signature, the key, the message
        for field in [1usize, 3, 6] {
            for index in [0u16, 1, 0xFFFE] {
                let mut x = d.clone();
                x[2 + 2 * field..4 + 2 * field].copy_from_slice(&index.to_le_bytes());
                assert!(precompile(&x).is_none(), "field {field} index {index}");
            }
        }
        // offsets and lengths that run past the data
        for (field, value) in [(0usize, d.len() as u16 - 63), (2, d.len() as u16 - 32), (4, d.len() as u16), (5, msg.len() as u16 + 1), (0, u16::MAX), (4, u16::MAX)] {
            let mut x = d.clone();
            x[2 + 2 * field..4 + 2 * field].copy_from_slice(&value.to_le_bytes());
            assert!(precompile(&x).is_none(), "field {field} value {value}");
        }
    }

    #[test]
    fn only_the_lower_of_the_two_s_values_is_accepted() {
        let sig = |s: [u8; 32]| [[9u8; 32], s].concat();
        let (mut above, mut below) = (HALF_N, HALF_N);
        above[31] += 1;
        below[31] -= 1;
        assert!(low_s(&sig(HALF_N)) && low_s(&sig(below)) && low_s(&sig([0; 32])));
        assert!(!low_s(&sig(above)) && !low_s(&sig([0xFF; 32])) && !low_s(&[0u8; 63]) && !low_s(&[]));
    }

    #[test]
    fn a_signature_is_written_in_the_one_spelling_the_strict_decoder_takes() {
        let mut sig = [0u8; SIG_LEN];
        for (k, b) in sig.iter_mut().enumerate() { *b = (k * 37 + 11) as u8; }
        for sig in [sig, [0; SIG_LEN], [0xFF; SIG_LEN]] {
            let (mut text, mut back) = ([0u8; SIG_TEXT], [0u8; SIG_LEN]);
            b64url(&sig, &mut text);
            assert_eq!(claims::b64_len(SIG_TEXT), Some(SIG_LEN));
            strict::b64url_into(&text, &mut back).unwrap();
            assert_eq!(back, sig);
            claims::b64url_into(&text, &mut back).unwrap(); // the reader a consumer names its marker with
            assert_eq!(back, sig);
            assert!(!text.contains(&b'.') && !text.contains(&b'='));
        }
    }

    #[test]
    fn a_p256_key_account_is_no_other_kind_of_account_and_its_audience_no_other_audience() {
        // shorter than any RSA key (40 + 8 * 64) and than any token account (T_JWT + 1)
        assert_eq!(EC_ACCOUNT, 137);
        const { assert!(EC_ACCOUNT < K_HDR + 8 * 64 && EC_ACCOUNT < T_JWT) }
        // an issuer account can be 137 bytes long: its first byte is ISS_STATE and its third 0
        const { assert!(ISS_STATE != 1 && EC_MARK != 0 && EC_MARK != 64 && EC_MARK != 128 && EC_MARK > 16) }
        let (ih, kh) = ([0xabu8; 32], [0x01u8; 32]);
        assert_eq!(ec_audience(&ih, &kh), format!("knos-oidc:eckey:{}:{}", "ab".repeat(32), "01".repeat(32)).into_bytes());
        let url = b"https://issuer.example";
        let good = [&[url.len() as u8][..], url, &[2u8; 33]].concat();
        assert_eq!(url_and_key(&good).unwrap(), (&url[..], &[2u8; 33][..]));
        let mut uncompressed = good.clone();
        uncompressed[1 + url.len()] = 4;
        assert_eq!(url_and_key(&uncompressed).unwrap_err(), err(E_EC_KEY));
        assert_eq!(url_and_key(&good[..good.len() - 1]).unwrap_err(), ProgramError::InvalidInstructionData);
        assert_eq!(url_and_key(&[&[18u8][..], b"http://issuer.test", &[2u8; 33]].concat()).unwrap_err(), err(E_ISS));
    }
}
