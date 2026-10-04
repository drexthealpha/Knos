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
#[derive(Clone, Copy, Debug)]
pub struct Raw<'a> { pub bytes: &'a [u8], pub is_str: bool }

/// Whether a key whose raw content is `raw` is the name `want` (printable ASCII), however it is spelled: a JSON
/// reader that decodes escapes takes "a\u0075d" for "aud", so this one does too. An escape `unescape` refuses
/// stands for a character no wanted name has.
fn key_is(raw: &[u8], escaped: bool, want: &[u8]) -> bool {
    if !escaped { return raw == want; }
    let (mut i, mut k) = (0, 0);
    while i < raw.len() {
        let Ok((c, next)) = unescape(raw, i) else { return false };
        if want.get(k) != Some(&c) { return false; }
        i = next; k += 1;
    }
    k == want.len()
}

/// One pass over a flat JSON object: for each wanted top-level key, its value. A wanted key that appears twice is
/// refused, the whole object must parse, and nothing may follow it. A key is compared as the text it spells (its
/// escapes decoded), so that this reader and any other JSON reader find the same claim under the same name, and a
/// second copy of a claim cannot hide behind another spelling of its name.
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
            let escaped = key.contains(&b'\\');
            for (w, g) in want.iter().zip(got.iter_mut()) {
                if key_is(key, escaped, w) {
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
        let (c, next) = unescape(r, i)?;
        out.push(c);
        i = next;
    }
    Ok(out)
}
/// The byte at r[i] of a JSON string's raw content, decoded, and the index after it.
fn unescape(r: &[u8], i: usize) -> Result<(u8, usize), ProgramError> {
    if r[i] != b'\\' { return Ok((r[i], i + 1)); }
    match r.get(i + 1) {
        Some(b'/') => Ok((b'/', i + 2)),
        Some(b'\\') => Ok((b'\\', i + 2)),
        Some(b'"') => Ok((b'"', i + 2)),
        Some(b'u') => {
            let h = r.get(i + 2..i + 6).ok_or_else(|| err(E_CLAIM))?;
            let mut v = 0u32;
            for &c in h {
                v = v << 4 | match c { b'0'..=b'9' => c - b'0', b'a'..=b'f' => c - b'a' + 10, b'A'..=b'F' => c - b'A' + 10, _ => return Err(err(E_CLAIM)) } as u32;
            }
            if !(0x20..0x7f).contains(&v) { return Err(err(E_CLAIM)); }
            Ok((v as u8, i + 6))
        }
        _ => Err(err(E_CLAIM)),
    }
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base64url_is_unpadded_canonical_and_the_same_in_place_as_into_a_buffer() {
        // RFC 4648's vectors, without padding
        for (plain, coded) in [(&b""[..], &b""[..]), (b"f", b"Zg"), (b"fo", b"Zm8"), (b"foo", b"Zm9v"), (b"foob", b"Zm9vYg"), (b"fooba", b"Zm9vYmE"),
                               (b"foobar", b"Zm9vYmFy"), (&[0xfb, 0xff], b"-_8"), (&[0xff, 0xff, 0xfe], b"___-")] {
            assert_eq!(b64_len(coded.len()), Some(plain.len()));
            let mut out = vec![0u8; plain.len()];
            b64url_into(coded, &mut out).unwrap();
            assert_eq!(out, plain);
            // in place, in the middle of a longer buffer: the bytes before it are not touched
            let mut d = [&b"head."[..], coded, b"tail"].concat();
            assert_eq!(b64url_in_place(&mut d, 5, coded.len()).unwrap(), plain.len());
            assert_eq!((&d[..5], &d[5..5 + plain.len()]), (&b"head."[..], plain));
        }
        assert_eq!((b64_len(1), b64_len(5), b64_len(4), b64_len(6), b64_len(7)), (None, None, Some(3), Some(4), Some(5)));
        // a length no encoding has; the standard alphabet's + and /; padding; a space; bits left over in the last character
        for bad in [&b"Z"[..], b"Zm9vY", b"Zm+v", b"Zm/v", b"Zg==", b"Zm8=", b"Zm 9", b"Zh", b"Zm9", b"Zm9vYmF"] {
            let mut d = bad.to_vec();
            assert_eq!(b64url_in_place(&mut d, 0, bad.len()).unwrap_err(), err(E_B64), "{:?}", core::str::from_utf8(bad));
            let mut out = vec![0u8; b64_len(bad.len()).unwrap_or(0)];
            assert_eq!(b64url_into(bad, &mut out).unwrap_err(), err(E_B64), "{:?}", core::str::from_utf8(bad));
        }
        // a buffer of another length than the decoding
        assert_eq!(b64url_into(b"Zm9v", &mut [0u8; 2]).unwrap_err(), err(E_B64));
        assert_eq!(b64url_into(b"Zm9v", &mut [0u8; 4]).unwrap_err(), err(E_B64));
    }

    #[test]
    fn a_jwt_is_three_parts_none_of_them_empty() {
        assert_eq!(split_jwt(b"ab.cde.f").unwrap(), [(0, 2), (3, 6), (7, 8)]);
        for bad in [&b""[..], b"a", b"a.b", b"a.b.c.d", b".b.c", b"a..c", b"a.b.", b"..", b"a.b.c."] {
            assert_eq!(split_jwt(bad).unwrap_err(), err(E_JSON), "{:?}", core::str::from_utf8(bad));
        }
    }

    #[test]
    fn fields_reads_a_flat_object_in_one_pass() {
        let b = br#" { "a" : "x" , "n":12, "t":true, "o":{"a":"inner","k":[1,"}"]}, "s":"7" } "#;
        let [a, n, t, o, s, none] = fields(b, [b"a", b"n", b"t", b"o", b"s", b"zz"]).unwrap();
        assert!(text(a).unwrap() == b"x" && number(n) == Ok(12) && number(s) == Ok(7) && none.is_none());
        assert!(!t.unwrap().is_str && t.unwrap().bytes == b"true" && o.unwrap().bytes == br#"{"a":"inner","k":[1,"}"]}"#);
        assert_eq!(text(n).unwrap_err(), err(E_CLAIM));      // a number is not a string
        assert_eq!(number(t).unwrap_err(), err(E_CLAIM));
        assert_eq!(number(o).unwrap_err(), err(E_CLAIM));    // a claim inside another object is not the claim
        assert!(fields(b"{}", [b"a"]).unwrap()[0].is_none() && fields(b" {\t}\r\n", [b"a"]).unwrap()[0].is_none());
        // the same name wanted twice is found twice: each wanted slot is its own
        let [x, y] = fields(br#"{"a":"1"}"#, [b"a", b"a"]).unwrap();
        assert!(number(x) == Ok(1) && number(y) == Ok(1));
    }

    #[test]
    fn fields_refuses_a_second_copy_of_a_wanted_claim_and_anything_that_is_not_one_object() {
        let json = |b: &[u8]| fields(b, [b"a"]).unwrap_err();
        assert_eq!(json(br#"{"a":"x","a":"y"}"#), err(E_DUP));
        assert_eq!(json(br#"{"a":"x","b":1,"a":"x"}"#), err(E_DUP));          // the same value twice is twice
        assert_eq!(json(br#"{"a":"x","\u0061":"y"}"#), err(E_DUP));         // and so is another spelling of the name
        assert_eq!(json(br#"{"a":"x","a":"y""#), err(E_DUP));                 // found before the damage after it
        assert!(fields(br#"{"b":1,"b":2}"#, [b"a"]).is_ok());                 // only a wanted key is checked for a second copy
        for bad in [&b""[..], b" ", b"[]", b"\"a\"", b"1", b"null", b"{", b"}", br#"{"a"}"#, br#"{"a":}"#, br#"{"a":"x"} x"#, br#"{"a":"x"}{}"#,
                    br#"{"a":"x",}"#, br#"{,"a":"x"}"#, br#"{"a":"x"#, br#"{"a":[1,2"#, br#"{a:1}"#, br#"{'a':1}"#, br#"{"a":1 "b":2}"#,
                    br#"{"a":"x"\"#, br#"{"a":{"b":1}"#, br#"{"a\":1}"#] {
            assert_eq!(json(bad), err(E_JSON), "{:?}", core::str::from_utf8(bad));
        }
    }

    #[test]
    fn text_decodes_the_escapes_of_printable_ascii_and_no_other() {
        let t = |b: &'static [u8]| text(fields(b, [b"a"]).unwrap()[0]);
        assert_eq!(t(br#"{"a":"octo\/widgets \u0041\u007e \\ \" end"}"#).unwrap(), br#"octo/widgets A~ \ " end"#);
        assert_eq!(t(br#"{"a":"plain"}"#).unwrap(), b"plain");
        assert_eq!(t(br#"{"a":""}"#).unwrap(), b"");
        assert_eq!(t("{\"a\":\"caf\u{e9}\"}".as_bytes()).unwrap(), "caf\u{e9}".as_bytes());      // UTF-8 written as it is
        for bad in [&br#"{"a":"\n"}"#[..], br#"{"a":"\t"}"#, br#"{"a":"\b"}"#, br#"{"a":"\u001f"}"#, br#"{"a":"\u007f"}"#, br#"{"a":"\u00e9"}"#,
                    br#"{"a":"\ud83d\ude00"}"#, br#"{"a":"\u00g1"}"#, br#"{"a":"\u004"}"#, br#"{"a":"\x41"}"#] {
            assert_eq!(t(bad).unwrap_err(), err(E_CLAIM), "{:?}", core::str::from_utf8(bad));
        }
        assert_eq!(text(None).unwrap_err(), err(E_CLAIM));
        assert_eq!(text(Some(Raw { bytes: b"12", is_str: false })).unwrap_err(), err(E_CLAIM));
    }

    #[test]
    fn a_number_is_plain_digits_at_most_eighteen_as_a_number_or_as_a_string() {
        assert_eq!(parse_u64(b"0"), Some(0));
        assert_eq!(parse_u64(b"999999999999999999"), Some(999_999_999_999_999_999));
        for bad in [&b""[..], b"00", b"01", b"-1", b"+1", b"1.0", b"1e3", b"0x10", b"1234567890123456789", b" 1", b"1 ", b"true", b"null"] {
            assert_eq!(parse_u64(bad), None, "{:?}", core::str::from_utf8(bad));
        }
        let n = |b: &'static [u8]| number(fields(b, [b"a"]).unwrap()[0]);
        assert_eq!((n(br#"{"a":7}"#), n(br#"{"a":"7"}"#), n(br#"{"a":0}"#)), (Ok(7), Ok(7), Ok(0)));
        for bad in [&br#"{"a":-7}"#[..], br#"{"a":7.0}"#, br#"{"a":"7 "}"#, br#"{"a":"\u0037"}"#, br#"{"a":[7]}"#, br#"{"a":null}"#, br#"{"b":7}"#] {
            assert_eq!(n(bad).unwrap_err(), err(E_CLAIM), "{:?}", core::str::from_utf8(bad));
        }
        // 18 digits are below 2^63: the casts consumers make to i64 cannot wrap
        assert!(999_999_999_999_999_999u64 < i64::MAX as u64);
    }

    #[test]
    fn hex_base58_and_the_parts_of_an_audience() {
        assert_eq!(parts::<3>(b"knos:claim:abc"), Some([&b"knos"[..], b"claim", b"abc"]));
        assert_eq!(parts::<3>(b"a::c"), Some([&b"a"[..], b"", b"c"]));
        assert!(parts::<3>(b"knos:claim").is_none() && parts::<3>(b"a:b:c:d").is_none() && parts::<1>(b"").is_some());
        assert!(is_hex(&[b'a'; 40], 40) && !is_hex(&[b'A'; 40], 40) && !is_hex(&[b'a'; 39], 40) && !is_hex(&[b'g'; 40], 40));
        assert_eq!(unhex32(&[b'f'; 64]), Some([0xff; 32]));
        assert!(unhex32(&[b'f'; 63]).is_none() && unhex32(&[b'F'; 64]).is_none());
        let mut hx = [0u8; 64];
        let h: [u8; 32] = core::array::from_fn(|i| (i * 9 + 1) as u8);
        hex_into(&h, &mut hx);
        assert_eq!(unhex32(&hx), Some(h));
        assert_eq!(b58_32(b"11111111111111111111111111111111"), Some([0; 32]));
        assert_eq!(b58_32(b"FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W").map(|k| k[0]), Some(0xdb));
        // too short, too long, not the alphabet, more than 32 bytes, another spelling of the same key
        for bad in [&b"1111111111111111111111111111111"[..], &[b'1'; 45], b"0OIl0OIl0OIl0OIl0OIl0OIl0OIl0OIl", &[b'z'; 44], b"1FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3"] {
            assert!(b58_32(bad).is_none(), "{:?}", core::str::from_utf8(bad));
        }
    }
}
