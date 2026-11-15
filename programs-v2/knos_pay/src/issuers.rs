//! ONE INTERFACE FOR EVERY ISSUER (0.3.34). Every instruction of this program that takes a token takes it through
//! `checked`: the account is knos-oidc's and VERIFIED, its issuer FAMILY is one the caller accepts, it is within
//! knos_oidc::LATE of its expiry, and the key that verified it is still usable (gh.rs `key_good`). Only then does the
//! family's own READER read the claims, and each reader turns them into what its callers judge:
//!   GitHub Actions        gh.rs   -> `Gh`   (every 2.0/2.1/2.2 instruction, unchanged)
//!   GitLab CI (gitlab.com) gl.rs  -> `Gh`   (a work order's funding and payment only, unchanged)
//!   a PRIVATE key          gh.rs  -> `Gh`   (PayOrder of a private order of the registrant's Balance only, unchanged)
//!   Google Confidential Space cs.rs -> `Cs` (PayOrder of an order that pins a container image: order_proof.rs)
//!   ORCID                  orcid.rs -> `Orcid` (BindOrcid: a researcher's ORCID iD is paid at a wallet)
//! A family is told by knos-oidc's issuer NUMBER first (GitHub 0, GitLab 1, private 3), and for a token of any other
//! registered issuer (number 2) by the sha256 of its issuer URL that knos-oidc wrote into the token account
//! (`knos_oidc::issuer_hash`, compared with the URL in Step). So a private key registered under the URL
//! "https://orcid.org" is still PRIVATE, never ORCID: nobody vouches for it.
//!
//! What GitHub and GitLab tokens may do is exactly what it was before this file: gh.rs's `read` asks `checked` with
//! the same acceptance rule and the same order of checks, so every refusal keeps its code (84 before 76-78).
//!
//! THE THIRD WAY TO PAY, with no issuer at all, is order_proof.rs: m of the n referee keys an order names sign the
//! same verdict (Ed25519, checked by Solana's precompile and read here by instruction introspection, `ed25519`).
use crate::{err, E_AUD, E_TOKEN, OIDC_ID};
use knos_oidc::claims::{self, parts};
use solana_program::{account_info::AccountInfo, hash::hashv, program_error::ProgramError, pubkey, pubkey::Pubkey};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Family { GitHub, GitLab, Private, ConfidentialSpace, Orcid, Other }

/// The issuer URLs this program reads beyond GitHub's and GitLab's, exactly as the issuers write `iss`:
///   https://confidentialcomputing.googleapis.com/.well-known/openid-configuration ("issuer"), RS256, fetched 14 Oct 2026
///   https://orcid.org/.well-known/openid-configuration ("issuer"), RS256, fetched 14 Oct 2026
/// Their keys come into knos-oidc as any other issuer's: RegisterIssuerKey (the pinned rotate workflow names the key,
/// a day's wait, the key admin's approval (the upgrade multisig vault)), then Refresh every 30 days.
pub const CS_ISSUER: &[u8] = b"https://confidentialcomputing.googleapis.com";
pub const ORCID_ISSUER: &[u8] = b"https://orcid.org";

/// Which family a VERIFIED token account (its data) belongs to.
pub fn family(d: &[u8], issuer: u8) -> Family {
    match issuer {
        knos_oidc::pins::ISSUER_GITHUB => Family::GitHub,
        knos_oidc::pins::ISSUER_GITLAB => Family::GitLab,
        knos_oidc::pins::ISSUER_PRIVATE => Family::Private,
        knos_oidc::pins::ISSUER_OTHER => match knos_oidc::issuer_hash(d) {
            Some(h) if *h == hashv(&[CS_ISSUER]).to_bytes() => Family::ConfidentialSpace,
            Some(h) if *h == hashv(&[ORCID_ISSUER]).to_bytes() => Family::Orcid,
            _ => Family::Other,
        },
        _ => Family::Other,
    }
}

/// The family of a VERIFIED token account of knos-oidc's, or None for any other account (whose refusal is then the
/// caller's ordinary one).
pub fn family_of(tok: &AccountInfo) -> Option<Family> {
    if *tok.owner != OIDC_ID { return None; }
    let d = tok.try_borrow_data().ok()?;
    let v = knos_oidc::verified(&d)?;
    Some(family(&d, v.issuer))
}

/// THE ONE FRONT DOOR. `accept` says, from the family and the account's data, whether the caller takes this token
/// at all; `read` reads its claims (payload, exp) once the key is known to be good. The checks run in the order gh.rs
/// always ran them: owner, VERIFIED, accepted and fresh (E_TOKEN), the key (E_ACCOUNTS or knos-oidc's 76-78), then
/// the reader.
pub fn checked<R>(tok: &AccountInfo, key: &AccountInfo, now: i64, accept: impl FnOnce(&knos_oidc::Verified, Family, &[u8]) -> bool,
                  read: impl FnOnce(Family, &[u8], i64) -> Result<R, ProgramError>) -> Result<R, ProgramError> {
    if *tok.owner != OIDC_ID { return Err(err(E_TOKEN)); }
    let d = tok.try_borrow_data()?;
    let v = knos_oidc::verified(&d).ok_or_else(|| err(E_TOKEN))?;
    let f = family(&d, v.issuer);
    if !accept(&v, f, &d) || !knos_oidc::fresh(v.exp, now) { return Err(err(E_TOKEN)); }
    crate::gh::key_good(&d, key, now)?;
    read(f, v.payload, v.exp)
}

/// A string claim inside a nested object: `path` names the objects from the top, the last name the string.
/// The token's payload was read whole by knos-oidc's strict reader before it was marked VERIFIED, and each level here
/// is read with `claims::fields`, which refuses a second copy of a wanted name at that level.
pub fn nested_text(payload: &[u8], path: &[&[u8]]) -> Result<Vec<u8>, ProgramError> {
    let mut at = payload;
    for (k, name) in path.iter().enumerate() {
        let [v] = claims::fields(at, [*name])?;
        let v = v.ok_or_else(|| err(claims::E_CLAIM))?;
        if k + 1 == path.len() { return claims::text(Some(v)); }
        if v.is_str || v.bytes.first() != Some(&b'{') { return Err(err(claims::E_CLAIM)); }
        at = v.bytes;
    }
    Err(err(claims::E_CLAIM))
}

/// Whether a raw JSON array of strings (as `fields` returns it) holds the string `want` (printable ASCII with no quote
/// or backslash) as one whole element.
pub fn array_has(raw: &[u8], want: &[u8]) -> bool {
    if raw.first() != Some(&b'[') { return false; }
    let quoted = [&b"\""[..], want, b"\""].concat();
    raw.windows(quoted.len()).enumerate().any(|(i, w)| {
        w == &quoted[..] && raw[..i].iter().rev().find(|c| !matches!(c, b' ' | b'\t' | b'\n' | b'\r')).is_some_and(|c| *c == b'[' || *c == b',')
            && raw[i + quoted.len()..].iter().find(|c| !matches!(c, b' ' | b'\t' | b'\n' | b'\r')).is_some_and(|c| *c == b']' || *c == b',')
    })
}

// ---- payees that are not GitHub accounts -----------------------------------------------------------------------

/// Where ORCID iDs are numbered among payee ids: OR_BASE + the iD's first fifteen digits (its check character is
/// checked, not stored). GitHub ids are below GL_NS (gl.rs `not_ours`), GitLab's are below 10^18 (gl.rs), and every
/// ORCID id is at or above 10^18: three ranges that do not meet, so a Bind, a record (Rep) or a Pair made for one is
/// never another's. An ORCID id is never read from a token's number claim (18 digits at most): only from an iD.
pub const OR_BASE: u64 = 1_000_000_000_000_000_000;
pub const OR_MAX: u64 = 999_999_999_999_999;

/// The check character of the first fifteen digits of an ORCID iD: ISO 7064 MOD 11-2, as ORCID documents it
/// (https://support.orcid.org/hc/en-us/articles/360006897674). 10 is written "X".
pub fn orcid_check(digits: &[u8; 15]) -> u8 {
    let mut total = 0u32;
    for d in digits { total = (total + (d - b'0') as u32) * 2; }
    let r = (12 - total % 11) % 11;
    if r == 10 { b'X' } else { b'0' + r as u8 }
}

/// An ORCID iD "dddd-dddd-dddd-dddC" as a payee id, or None when it is not one (form or check character).
pub fn orcid_id(s: &[u8]) -> Option<u64> {
    if s.len() != 19 || s[4] != b'-' || s[9] != b'-' || s[14] != b'-' { return None; }
    let mut digits = [0u8; 15];
    let mut k = 0;
    for (i, &c) in s[..18].iter().enumerate() {
        if i == 4 || i == 9 || i == 14 { continue; }
        if !c.is_ascii_digit() { return None; }
        digits[k] = c; k += 1;
    }
    if orcid_check(&digits) != s[18] { return None; }
    Some(OR_BASE + digits.iter().fold(0u64, |a, c| a * 10 + (c - b'0') as u64))
}

/// One payee of a proof or a verdict: a GitHub id (digits) or an ORCID iD (with its dashes), its share in basis
/// points, and an address or "-" (the payee's Bind). The same rules as order_pay::payees_of otherwise.
pub fn payees_any(list: &[u8]) -> Result<Vec<crate::order_pay::Payee>, ProgramError> {
    use crate::order_pay::Payee;
    let bad = || err(E_AUD);
    let mut out: Vec<Payee> = Vec::with_capacity(crate::MAX_PAYEES);
    for entry in list.split(|&c| c == b',') {
        let mut it = entry.split(|&c| c == b'.');
        let (Some(id), Some(bps), Some(address), None) = (it.next(), it.next(), it.next(), it.next()) else { return Err(bad()) };
        let id = if id.contains(&b'-') { orcid_id(id).ok_or_else(bad)? } else { crate::gh::n(id)? };
        let bps = crate::gh::n(bps)?;
        let address = if address == b"-" { None } else { Some(Pubkey::new_from_array(claims::b58_32(address).ok_or_else(bad)?)) };
        if out.len() == crate::MAX_PAYEES || id == 0 || bps == 0 || bps > 10_000 || out.iter().any(|p| p.id == id) { return Err(bad()); }
        out.push(Payee { id, bps, address });
    }
    if out.iter().map(|p| p.bps).sum::<u64>() != 10_000 { return Err(bad()); }
    Ok(out)
}

/// knos3:proof:<order address>:<evidence sha256 hex>:<terms hash hex>:<payees>: what a Confidential Space judge puts
/// in its token's audience (at most 512 bytes, Google's limit). Returns (order, evidence, terms, payees text).
#[allow(clippy::type_complexity)] pub fn proof_aud(aud: &[u8]) -> Result<(Pubkey, [u8; 32], [u8; 32], &[u8]), ProgramError> {
    let bad = || err(E_AUD);
    let [k, w, order, evidence, terms, list] = parts::<6>(aud).ok_or_else(bad)?;
    if k != b"knos3" || w != b"proof" { return Err(bad()); }
    Ok((Pubkey::new_from_array(claims::b58_32(order).ok_or_else(bad)?), claims::unhex32(evidence).ok_or_else(bad)?,
        claims::unhex32(terms).ok_or_else(bad)?, list))
}

// ---- Ed25519 signatures, read from Solana's precompile ------------------------------------------------------------

/// Solana's Ed25519 signature-verification precompile (https://solana.com/docs/core/programs/precompiles).
pub const ED25519_ID: Pubkey = pubkey!("Ed25519SigVerify111111111111111111111111111");
const SELF: u16 = u16::MAX;

/// The (public key, message) of every signature an Ed25519 precompile instruction with this data verified, when each
/// one's key, signature and message are all in the instruction's own data (index u16::MAX). The data is: count u8,
/// padding u8, then per signature seven u16 LE (signature offset, signature instruction, key offset, key instruction,
/// message offset, message length, message instruction). The precompile reads each part from the instruction an
/// index names, so an entry that points anywhere else is skipped here: the bytes at its offsets would not be the
/// bytes that were verified. The precompile itself fails the whole transaction when any entry does not verify.
pub fn ed25519(data: &[u8]) -> Vec<([u8; 32], &[u8])> {
    let mut out = Vec::new();
    let count = match data.first() { Some(&c) => c as usize, None => return out };
    for e in 0..count {
        let base = 2 + 14 * e;
        let Some(f) = data.get(base..base + 14) else { break };
        let n = |k: usize| u16::from_le_bytes([f[2 * k], f[2 * k + 1]]);
        if n(1) != SELF || n(3) != SELF || n(6) != SELF { continue; }
        let (Some(_sig), Some(key), Some(msg)) = (data.get(n(0) as usize..n(0) as usize + 64), data.get(n(2) as usize..n(2) as usize + 32),
                                                   data.get(n(4) as usize..n(4) as usize + n(5) as usize)) else { continue };
        out.push((key.try_into().unwrap(), msg));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_orcid_id_is_its_fifteen_digits_above_every_forge_id_and_its_check_character_is_checked() {
        // ORCID's own examples: 0000-0002-1825-0097 (Josiah Carberry) and 0000-0002-1694-233X
        assert_eq!(orcid_id(b"0000-0002-1825-0097"), Some(OR_BASE + 21_825_009));
        assert_eq!(orcid_id(b"0000-0002-1694-233X"), Some(OR_BASE + 21_694_233));
        for bad in [&b"0000-0002-1825-0098"[..], b"0000-0002-1825-009", b"0000000218250097", b"0000-0002-1825-009x", b"000a-0002-1825-0097",
                    b"0000_0002-1825-0097", b"0000-0002-1825-00970"] {
            assert!(orcid_id(bad).is_none(), "{:?}", core::str::from_utf8(bad));
        }
        // the three ranges do not meet: GitHub's below GL_NS, GitLab's below 10^18, ORCID's from 10^18, all in a u64
        const { assert!(crate::gl::GL_ID + crate::gl::GL_MAX < OR_BASE && OR_BASE.checked_add(OR_MAX).is_some()) };
        assert!(crate::gl::not_ours(OR_BASE).is_err() && claims::parse_u64(b"1000000000000000000").is_none());
        let w = Pubkey::new_from_array([9; 32]);
        let p = payees_any(format!("0000-0002-1825-0097.6000.{w},77.4000.-").as_bytes()).ok().unwrap();
        assert_eq!((p[0].id, p[0].address, p[1].id, p[1].address), (OR_BASE + 21_825_009, Some(w), 77, None));
        for bad in ["0000-0002-1825-0098.10000.-", "0000-0002-1825-0097.5000.-,0000-0002-1825-0097.5000.-", "0.10000.-", "5.9999.-"] {
            assert!(payees_any(bad.as_bytes()).is_err(), "{bad}");
        }
    }

    #[test]
    fn nested_claims_and_arrays_are_read_as_whole_names_and_elements() {
        let p = br#"{"submods":{"container":{"image_digest":"sha256:ab","x":1},"confidential_space":{"support_attributes":["LATEST", "STABLE"]}}}"#;
        assert_eq!(nested_text(p, &[b"submods", b"container", b"image_digest"]).unwrap(), b"sha256:ab");
        assert!(nested_text(p, &[b"submods", b"container", b"nope"]).is_err() && nested_text(p, &[b"submods", b"container"]).is_err());
        assert!(nested_text(br#"{"submods":{"container":{"image_digest":"a","image_digest":"b"}}}"#, &[b"submods", b"container", b"image_digest"]).is_err());
        assert!(array_has(br#"["LATEST", "STABLE"]"#, b"STABLE") && array_has(br#"["STABLE"]"#, b"STABLE") && !array_has(br#"["UNSTABLE"]"#, b"STABLE"));
        assert!(!array_has(br#"["x\"STABLE\""]"#, b"STABLE") && !array_has(br#""STABLE""#, b"STABLE"));
    }

    #[test]
    fn only_precompile_entries_that_read_their_own_data_are_taken() {
        let entry = |key_ix: u16| {
            let (sig_at, key_at, msg_at) = (2u16 + 14, 2u16 + 14 + 64, 2u16 + 14 + 96);
            let mut d = vec![1u8, 0];
            for v in [sig_at, SELF, key_at, key_ix, msg_at, 3, SELF] { d.extend_from_slice(&v.to_le_bytes()); }
            d.extend_from_slice(&[0u8; 64]); d.extend_from_slice(&[5u8; 32]); d.extend_from_slice(b"abc");
            d
        };
        let ok = entry(SELF);
        assert_eq!(ed25519(&ok), vec![([5u8; 32], &b"abc"[..])]);
        assert!(ed25519(&entry(0)).is_empty() && ed25519(&[]).is_empty() && ed25519(&ok[..ok.len() - 1]).is_empty());
        let w = Pubkey::new_from_array([7; 32]);
        let aud = format!("knos3:proof:{w}:{}:{}:5.10000.-", "ab".repeat(32), "cd".repeat(32));
        let (o, e, t, l) = proof_aud(aud.as_bytes()).ok().unwrap();
        assert_eq!((o, e, t, l), (w, [0xab; 32], [0xcd; 32], &b"5.10000.-"[..]));
        assert!(proof_aud(format!("knos3:pay:{w}:{}:{}:5.10000.-", "ab".repeat(32), "cd".repeat(32)).as_bytes()).is_err());
    }
}
