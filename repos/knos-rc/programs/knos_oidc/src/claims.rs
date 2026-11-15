//! Reading a token: base64url, the three JWT parts, and the claims of a flat JSON object. Shared with every program
//! that consumes a verified token (it depends on this crate with the `no-entrypoint` feature).
use solana_program::program_error::ProgramError;

pub fn err(code: u32) -> ProgramError { ProgramError::Custom(code) }
// error codes (also in the IDL): 60 base64url, 61 json, 62 duplicate claim, 63 claim missing or of the wrong type
pub const E_B64: u32 = 60;
pub const E_JSON: u32 = 61;
pub const E_DUP: u32 = 62;
pub const E_CLAIM: u32 = 63;

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
/// Decoded length of an unpadded base64url string, or None if its length is impossible.
pub fn b64_len(n: usize) -> Option<usize> {
    match n % 4 { 0 => Some(n / 4 * 3), 2 => Some(n / 4 * 3 + 1), 3 => Some(n / 4 * 3 + 2), _ => None }
}
/// Decodes unpadded base64url in place: d[from..from + len] becomes its decoding at d[from..]; returns the decoded
/// length. (The output never overtakes the input, so one buffer is enough.) Non-canonical trailing bits are refused.
pub fn b64url_in_place(d: &mut [u8], from: usize, len: usize) -> Result<usize, ProgramError> {
    let out_len = b64_len(len).ok_or_else(|| err(E_B64))?;
    let (mut r, mut w) = (from, from);
    let end = from + len;
    while r < end {
        let take = (end - r).min(4);
        let mut v = 0u32;
        for k in 0..take { v |= b64v(d[r + k]).ok_or_else(|| err(E_B64))? << (18 - 6 * k as u32); }
        if take == 2 && v & 0xffff != 0 { return Err(err(E_B64)); }
        if take == 3 && v & 0xff != 0 { return Err(err(E_B64)); }
        r += take;
        d[w] = (v >> 16) as u8; w += 1;
        if take > 2 { d[w] = (v >> 8) as u8; w += 1; }
        if take > 3 { d[w] = v as u8; w += 1; }
    }
    debug_assert_eq!(w - from, out_len);
    Ok(out_len)
}
/// Decodes unpadded base64url into `out` (which must be exactly the decoded length).
pub fn b64url_into(s: &[u8], out: &mut [u8]) -> Result<(), ProgramError> {
    if b64_len(s.len()) != Some(out.len()) { return Err(err(E_B64)); }
    let mut w = 0;
    for ch in s.chunks(4) {
        let mut v = 0u32;
        for (k, &c) in ch.iter().enumerate() { v |= b64v(c).ok_or_else(|| err(E_B64))? << (18 - 6 * k as u32); }
        if ch.len() == 2 && v & 0xffff != 0 { return Err(err(E_B64)); }
        if ch.len() == 3 && v & 0xff != 0 { return Err(err(E_B64)); }
        out[w] = (v >> 16) as u8; w += 1;
        if ch.len() > 2 { out[w] = (v >> 8) as u8; w += 1; }
        if ch.len() > 3 { out[w] = v as u8; w += 1; }
    }
    Ok(())
}

/// The JWT's three parts as (start, end) ranges: header, payload, signature. Exactly two dots.
pub fn split_jwt(t: &[u8]) -> Result<[(usize, usize); 3], ProgramError> {
    let mut dots = [0usize; 2];
    let mut k = 0;
    for (i, &c) in t.iter().enumerate() {
        if c == b'.' {
            if k == 2 { return Err(err(E_JSON)); }
            dots[k] = i; k += 1;
        }
    }
    if k != 2 || dots[0] == 0 || dots[1] == dots[0] + 1 || dots[1] + 1 >= t.len() { return Err(err(E_JSON)); }
    Ok([(0, dots[0]), (dots[0] + 1, dots[1]), (dots[1] + 1, t.len())])
}

fn ws(b: &[u8], mut i: usize) -> usize {
    while i < b.len() && matches!(b[i], b' ' | b'\t' | b'\n' | b'\r') { i += 1; }
    i
}
/// b[i] == '"': the string's raw content range and the index after its closing quote.
fn jstr(b: &[u8], i: usize) -> Result<(usize, usize, usize), ProgramError> {
    if b.get(i) != Some(&b'"') { return Err(err(E_JSON)); }
    let mut k = i + 1;
    while k < b.len() {
        match b[k] {
            b'\\' => k += 2,
            b'"' => return Ok((i + 1, k, k + 1)),
            _ => k += 1,
        }
    }
    Err(err(E_JSON))
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
            Err(err(E_JSON))
        }
        Some(_) => {
            let mut k = i;
            while k < b.len() && !matches!(b[k], b',' | b'}' | b']' | b' ' | b'\t' | b'\n' | b'\r') { k += 1; }
            if k == i { Err(err(E_JSON)) } else { Ok(k) }
        }
        None => Err(err(E_JSON)),
    }
}

/// A claim's value as it stands in the JSON: the raw content of a string, or the raw token of a number/literal.
#[derive(Clone, Copy)]
pub struct Raw<'a> { pub bytes: &'a [u8], pub is_str: bool }

/// One pass over a flat JSON object: for each wanted top-level key, its value. A wanted key that appears twice is
/// refused, the whole object must parse, and nothing may follow it. Keys are compared raw (GitHub's and GitLab's
/// claim names have no escapes).
pub fn fields<'a, const N: usize>(b: &'a [u8], want: [&[u8]; N]) -> Result<[Option<Raw<'a>>; N], ProgramError> {
    let mut got: [Option<Raw<'a>>; N] = [None; N];
    let mut i = ws(b, 0);
    if b.get(i) != Some(&b'{') { return Err(err(E_JSON)); }
    i = ws(b, i + 1);
    if b.get(i) != Some(&b'}') {
        loop {
            let (ks, ke, next) = jstr(b, i)?;
            i = ws(b, next);
            if b.get(i) != Some(&b':') { return Err(err(E_JSON)); }
            let vs = ws(b, i + 1);
            let ve = skip_value(b, vs)?;
            let key = &b[ks..ke];
            for (w, g) in want.iter().zip(got.iter_mut()) {
                if key == *w {
                    if g.is_some() { return Err(err(E_DUP)); }
                    *g = Some(if b[vs] == b'"' { Raw { bytes: &b[vs + 1..ve - 1], is_str: true } } else { Raw { bytes: &b[vs..ve], is_str: false } });
                }
            }
            i = ws(b, ve);
            match b.get(i) {
                Some(b',') => i = ws(b, i + 1),
                Some(b'}') => break,
                _ => return Err(err(E_JSON)),
            }
        }
    }
    if ws(b, i + 1) != b.len() { return Err(err(E_JSON)); }
    Ok(got)
}

/// A string claim's text. JSON escapes for printable ASCII are decoded (\/ \\ \" and \u00XX), so a value compares
/// equal however the issuer chose to escape it; any other escape is refused.
pub fn text(f: Option<Raw>) -> Result<Vec<u8>, ProgramError> {
    let r = match f { Some(r) if r.is_str => r.bytes, _ => return Err(err(E_CLAIM)) };
    let mut out = Vec::with_capacity(r.len());
    let mut i = 0;
    while i < r.len() {
        if r[i] != b'\\' { out.push(r[i]); i += 1; continue; }
        match r.get(i + 1) {
            Some(b'/') => { out.push(b'/'); i += 2; }
            Some(b'\\') => { out.push(b'\\'); i += 2; }
            Some(b'"') => { out.push(b'"'); i += 2; }
            Some(b'u') => {
                let h = r.get(i + 2..i + 6).ok_or_else(|| err(E_CLAIM))?;
                let mut v = 0u32;
                for &c in h {
                    v = v << 4 | match c { b'0'..=b'9' => c - b'0', b'a'..=b'f' => c - b'a' + 10, b'A'..=b'F' => c - b'A' + 10, _ => return Err(err(E_CLAIM)) } as u32;
                }
                if !(0x20..0x7f).contains(&v) { return Err(err(E_CLAIM)); }
                out.push(v as u8); i += 6;
            }
            _ => return Err(err(E_CLAIM)),
        }
    }
    Ok(out)
}
/// A non-negative integer claim, given as a JSON number or as a string of digits (GitHub sends ids as strings).
/// No sign, no leading zero, no fraction; at most 18 digits.
pub fn number(f: Option<Raw>) -> Result<u64, ProgramError> {
    let r = f.ok_or_else(|| err(E_CLAIM))?;
    parse_u64(r.bytes).ok_or_else(|| err(E_CLAIM))
}
pub fn parse_u64(s: &[u8]) -> Option<u64> {
    if s.is_empty() || s.len() > 18 || !s.iter().all(|c| c.is_ascii_digit()) || (s.len() > 1 && s[0] == b'0') { return None; }
    Some(s.iter().fold(0u64, |a, c| a * 10 + (c - b'0') as u64))
}
pub fn is_hex(s: &[u8], len: usize) -> bool { s.len() == len && s.iter().all(|c| matches!(c, b'0'..=b'9' | b'a'..=b'f')) }
pub fn unhex32(s: &[u8]) -> Option<[u8; 32]> {
    if !is_hex(s, 64) { return None; }
    let v = |c: u8| if c <= b'9' { c - b'0' } else { c - b'a' + 10 };
    let mut o = [0u8; 32];
    for (k, b) in o.iter_mut().enumerate() { *b = v(s[2 * k]) << 4 | v(s[2 * k + 1]); }
    Some(o)
}
pub fn hex_into(b: &[u8], out: &mut [u8]) {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    for (k, x) in b.iter().enumerate() { out[2 * k] = HEX[(x >> 4) as usize]; out[2 * k + 1] = HEX[(x & 15) as usize]; }
}
/// A canonical base58 32-byte public key (as Solana prints it); None for anything else.
pub fn b58_32(s: &[u8]) -> Option<[u8; 32]> {
    const A: &[u8] = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
    if s.len() < 32 || s.len() > 44 { return None; }
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
/// Splits `s` on ':' into exactly N parts.
pub fn parts<const N: usize>(s: &[u8]) -> Option<[&[u8]; N]> {
    let mut out: [&[u8]; N] = [&[]; N];
    let mut it = s.split(|&c| c == b':');
    for o in out.iter_mut() { *o = it.next()?; }
    if it.next().is_some() { return None; }
    Some(out)
}
