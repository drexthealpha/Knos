//! The strict reader: what knos-oidc itself reads a token with before it marks the token account VERIFIED (lib.rs,
//! Step). Every byte of the header and of the payload is checked against RFC 8259 (since 2.2: before it, a value
//! nobody asked for was passed over unread), and the base64 of the three parts is decoded here too.
//!
//! This file is the program's own. claims.rs, beside it, is the reader every CONSUMER of a verified token compiles
//! in (knos_pay depends on this crate with the `no-entrypoint` feature and calls `claims::fields`), and it is
//! 2.1's source byte for byte: a change to it would change the bytes of knos_pay, which 0.3.16 does not change. So
//! the strictness lives here, where no consumer links it, and it does not need to be anywhere else: Step refuses a
//! header or a payload this reader refuses, so no such payload is ever in a VERIFIED account, and a VERIFIED
//! account is all a consumer reads. On every document this reader accepts, claims.rs finds the same claims
//! (fuzz/src/lib.rs and tests/claims_random.rs hold the two to that).
use crate::claims::{b64_len, err, Raw, E_B64, E_DUP, E_JSON};
use solana_program::program_error::ProgramError;

/// The six bits of each character of the URL alphabet (RFC 4648 section 5); NOT_B64 for every other byte.
const NOT_B64: u8 = 0xff;
const fn b64_table() -> [u8; 256] {
    let mut t = [NOT_B64; 256];
    let mut k = 0;
    while k < 26 { t[b'A' as usize + k] = k as u8; t[b'a' as usize + k] = 26 + k as u8; k += 1; }
    k = 0;
    while k < 10 { t[b'0' as usize + k] = 52 + k as u8; k += 1; }
    t[b'-' as usize] = 62;
    t[b'_' as usize] = 63;
    t
}
static B64: [u8; 256] = b64_table();
/// Four characters as the 24 bits they spell.
#[inline(always)]
fn quad(a: u8, b: u8, c: u8, e: u8) -> Result<u32, ProgramError> {
    let (a, b, c, e) = (B64[a as usize], B64[b as usize], B64[c as usize], B64[e as usize]);
    if (a | b | c | e) > 63 { return Err(err(E_B64)); }
    Ok((a as u32) << 18 | (b as u32) << 12 | (c as u32) << 6 | e as u32)
}
/// The last two or three characters of a string, as the bits they spell with 'A' (zero) written after them. Bits
/// left over in the last character are refused: a string has one spelling.
fn last(s: &[u8]) -> Result<u32, ProgramError> {
    let v = quad(s[0], s[1], if s.len() > 2 { s[2] } else { b'A' }, b'A')?;
    if v & (if s.len() > 2 { 0xff } else { 0xffff }) != 0 { return Err(err(E_B64)); }
    Ok(v)
}
/// Decodes unpadded base64url in place: d[from..from + len] becomes its decoding at d[from..]; returns the decoded
/// length. (The output never overtakes the input, so one buffer is enough.) Non-canonical trailing bits are refused.
pub fn b64url_in_place(d: &mut [u8], from: usize, len: usize) -> Result<usize, ProgramError> {
    let out_len = b64_len(len).ok_or_else(|| err(E_B64))?;
    let d = &mut d[from..from + len];
    let (mut r, mut w) = (0, 0);
    while len - r >= 4 {
        let v = quad(d[r], d[r + 1], d[r + 2], d[r + 3])?;
        d[w] = (v >> 16) as u8; d[w + 1] = (v >> 8) as u8; d[w + 2] = v as u8;
        r += 4; w += 3;
    }
    if r < len {
        let v = last(&d[r..])?;
        d[w] = (v >> 16) as u8; w += 1;
        if len - r > 2 { d[w] = (v >> 8) as u8; }
    }
    Ok(out_len)
}
/// Decodes unpadded base64url into `out` (which must be exactly the decoded length).
pub fn b64url_into(s: &[u8], out: &mut [u8]) -> Result<(), ProgramError> {
    if b64_len(s.len()) != Some(out.len()) { return Err(err(E_B64)); }
    let whole = s.len() / 4;
    for (ch, o) in s.chunks_exact(4).zip(out.chunks_exact_mut(3)) {
        let v = quad(ch[0], ch[1], ch[2], ch[3])?;
        o[0] = (v >> 16) as u8; o[1] = (v >> 8) as u8; o[2] = v as u8;
    }
    let (rest, o) = (&s[4 * whole..], &mut out[3 * whole..]);
    if !rest.is_empty() {
        let v = last(rest)?;
        o[0] = (v >> 16) as u8;
        if rest.len() > 2 { o[1] = (v >> 8) as u8; }
    }
    Ok(())
}

fn ws(b: &[u8], mut i: usize) -> usize {
    while i < b.len() && matches!(b[i], b' ' | b'\t' | b'\n' | b'\r') { i += 1; }
    i
}

/// How deep a document may nest: the top-level object is 1, a value inside it 2, and so on. A deeper one is refused.
pub const MAX_DEPTH: usize = 64;
/// How many members the top-level object may have. One more is refused (every name is compared with every other).
pub const MAX_MEMBERS: usize = 128;

// What a byte is inside a JSON string (RFC 8259 section 7, and RFC 3629 for the bytes of a character that is not ASCII).
const PLAIN: u8 = 0;      // itself
const QUOTE: u8 = 1;      // the end of the string
const ESCAPE: u8 = 2;     // a backslash
const NEVER: u8 = 3;      // a control character, a continuation byte with nothing before it, or a byte UTF-8 never has
const LEAD2: u8 = 4;      // C2..DF: one continuation byte follows
const LEAD_E0: u8 = 5;    // E0: A0..BF, then one (anything lower is a longer spelling of a shorter character)
const LEAD3: u8 = 6;      // E1..EC, EE, EF: two follow
const LEAD_ED: u8 = 7;    // ED: 80..9F, then one (anything higher is a surrogate)
const LEAD_F0: u8 = 8;    // F0: 90..BF, then two
const LEAD4: u8 = 9;      // F1..F3: three follow
const LEAD_F4: u8 = 10;   // F4: 80..8F, then two (anything higher is past U+10FFFF)
const fn classes() -> [u8; 256] {
    let mut t = [NEVER; 256];
    let mut c = 0x20;
    while c < 0x80 { t[c] = PLAIN; c += 1; }
    t[b'"' as usize] = QUOTE;
    t[b'\\' as usize] = ESCAPE;
    c = 0xc2;
    while c < 0xe0 { t[c] = LEAD2; c += 1; }
    while c < 0xf0 { t[c] = LEAD3; c += 1; }
    t[0xe0] = LEAD_E0; t[0xed] = LEAD_ED; t[0xf0] = LEAD_F0; t[0xf1] = LEAD4; t[0xf2] = LEAD4; t[0xf3] = LEAD4; t[0xf4] = LEAD_F4;
    t
}
static CLASS: [u8; 256] = classes();

fn tail(b: &[u8], k: usize, lo: u8, hi: u8) -> Result<(), ProgramError> {
    match b.get(k) { Some(&c) if lo <= c && c <= hi => Ok(()), _ => Err(err(E_JSON)) }
}
/// Four hexadecimal digits at b[k..k + 4], as a number.
fn hex4(b: &[u8], k: usize) -> Result<u32, ProgramError> {
    let h = b.get(k..k + 4).ok_or_else(|| err(E_JSON))?;
    let mut v = 0u32;
    for &c in h {
        v = v << 4 | match c { b'0'..=b'9' => c - b'0', b'a'..=b'f' => c - b'a' + 10, b'A'..=b'F' => c - b'A' + 10, _ => return Err(err(E_JSON)) } as u32;
    }
    Ok(v)
}
/// b[i] == '"': the string's raw content range, the index after its closing quote, and whether it holds an escape.
/// The string is checked as it is passed over: no control character, only the escapes JSON has, a `\u` escape of
/// half a surrogate pair only next to its other half, and bytes that are UTF-8 in its one spelling.
#[inline(never)]
fn jstr(b: &[u8], i: usize) -> Result<(usize, usize, usize, bool), ProgramError> {
    if b.get(i) != Some(&b'"') { return Err(err(E_JSON)); }
    let mut k = i + 1;
    let mut escaped = false;
    while k < b.len() {
        match CLASS[b[k] as usize] {
            PLAIN => k += 1,
            QUOTE => return Ok((i + 1, k, k + 1, escaped)),
            ESCAPE => {
                escaped = true;
                match b.get(k + 1) {
                    Some(b'"' | b'\\' | b'/' | b'b' | b'f' | b'n' | b'r' | b't') => k += 2,
                    Some(b'u') => {
                        let u = hex4(b, k + 2)?;
                        k += 6;
                        if (0xd800..0xdc00).contains(&u) {
                            if b.get(k) != Some(&b'\\') || b.get(k + 1) != Some(&b'u') || !(0xdc00..0xe000).contains(&hex4(b, k + 2)?) { return Err(err(E_JSON)); }
                            k += 6;
                        } else if (0xdc00..0xe000).contains(&u) {
                            return Err(err(E_JSON));
                        }
                    }
                    _ => return Err(err(E_JSON)),
                }
            }
            LEAD2 => { tail(b, k + 1, 0x80, 0xbf)?; k += 2; }
            LEAD3 => { tail(b, k + 1, 0x80, 0xbf)?; tail(b, k + 2, 0x80, 0xbf)?; k += 3; }
            LEAD_E0 => { tail(b, k + 1, 0xa0, 0xbf)?; tail(b, k + 2, 0x80, 0xbf)?; k += 3; }
            LEAD_ED => { tail(b, k + 1, 0x80, 0x9f)?; tail(b, k + 2, 0x80, 0xbf)?; k += 3; }
            LEAD4 => { tail(b, k + 1, 0x80, 0xbf)?; tail(b, k + 2, 0x80, 0xbf)?; tail(b, k + 3, 0x80, 0xbf)?; k += 4; }
            LEAD_F0 => { tail(b, k + 1, 0x90, 0xbf)?; tail(b, k + 2, 0x80, 0xbf)?; tail(b, k + 3, 0x80, 0xbf)?; k += 4; }
            LEAD_F4 => { tail(b, k + 1, 0x80, 0x8f)?; tail(b, k + 2, 0x80, 0xbf)?; tail(b, k + 3, 0x80, 0xbf)?; k += 4; }
            _ => return Err(err(E_JSON)),
        }
    }
    Err(err(E_JSON))
}
fn digits(b: &[u8], mut k: usize) -> Result<usize, ProgramError> {
    let from = k;
    while k < b.len() && b[k].is_ascii_digit() { k += 1; }
    if k == from { Err(err(E_JSON)) } else { Ok(k) }
}
/// A JSON number at b[i..] (RFC 8259 section 6): the index after it. What follows it is the caller's to check.
#[inline(never)]
fn jnum(b: &[u8], i: usize) -> Result<usize, ProgramError> {
    let mut k = if b.get(i) == Some(&b'-') { i + 1 } else { i };
    k = match b.get(k) { Some(b'0') => k + 1, Some(b'1'..=b'9') => digits(b, k)?, _ => return Err(err(E_JSON)) };
    if b.get(k) == Some(&b'.') { k = digits(b, k + 1)?; }
    if matches!(b.get(k), Some(b'e' | b'E')) {
        k += 1;
        if matches!(b.get(k), Some(b'+' | b'-')) { k += 1; }
        k = digits(b, k)?;
    }
    Ok(k)
}
/// A member's name and its colon at b[i..]: the index of the member's value.
fn name(b: &[u8], i: usize) -> Result<usize, ProgramError> {
    let k = ws(b, jstr(b, i)?.2);
    if b.get(k) != Some(&b':') { return Err(err(E_JSON)); }
    Ok(ws(b, k + 1))
}
/// One JSON value at b[i..], all of it checked against RFC 8259: the index after it. `room` is how many levels of
/// array or object it may open. No recursion: the open brackets are the bits of one word.
#[inline(never)]
fn skip_value(b: &[u8], mut i: usize, room: usize) -> Result<usize, ProgramError> {
    let mut open = 0u64;      // one bit for each array or object that is open, the innermost lowest: 1 for an object
    let mut depth = 0usize;
    loop {
        // b[i..] starts a value
        match b.get(i) {
            Some(b'"') => i = jstr(b, i)?.2,
            Some(&c @ (b'{' | b'[')) => {
                if depth == room { return Err(err(E_JSON)); }
                let object = c == b'{';
                i = ws(b, i + 1);
                if b.get(i) == Some(if object { &b'}' } else { &b']' }) {
                    i += 1;
                } else {
                    open = open << 1 | object as u64;
                    depth += 1;
                    if object { i = name(b, i)?; }
                    continue;
                }
            }
            Some(b't') => { if b.get(i..i + 4) != Some(b"true") { return Err(err(E_JSON)); } i += 4; }
            Some(b'f') => { if b.get(i..i + 5) != Some(b"false") { return Err(err(E_JSON)); } i += 5; }
            Some(b'n') => { if b.get(i..i + 4) != Some(b"null") { return Err(err(E_JSON)); } i += 4; }
            _ => i = jnum(b, i)?,
        }
        // a value ended at i: what follows it in the array or object it is in
        loop {
            if depth == 0 { return Ok(i); }
            i = ws(b, i);
            let object = open & 1 == 1;
            match b.get(i) {
                Some(b',') => {
                    i = ws(b, i + 1);
                    if object { i = name(b, i)?; }
                    break;
                }
                Some(b'}') if object => {}
                Some(b']') if !object => {}
                _ => return Err(err(E_JSON)),
            }
            i += 1;
            open >>= 1;
            depth -= 1;
        }
    }
}

/// The text a string that `jstr` passed spells, as UTF-8: its escapes decoded, a surrogate pair made one character.
#[inline(never)]
fn spelled(raw: &[u8]) -> Vec<u8> {
    let hex = |k: usize| raw[k..k + 4].iter().fold(0u32, |v, &c| v << 4 | (c as char).to_digit(16).unwrap_or(0));
    let mut out = Vec::with_capacity(raw.len());
    let mut k = 0;
    while k < raw.len() {
        if raw[k] != b'\\' { out.push(raw[k]); k += 1; continue; }
        let c = raw[k + 1];
        k += 2;
        let mut u = match c { b'b' => 8, b'f' => 12, b'n' => 10, b'r' => 13, b't' => 9, b'u' => { k += 4; hex(k - 4) } _ => c as u32 };
        if c == b'u' && (0xd800..0xdc00).contains(&u) { u = 0x10000 + ((u - 0xd800) << 10) + (hex(k + 2) - 0xdc00); k += 6; }
        let mut utf8 = [0u8; 4];
        out.extend_from_slice(char::from_u32(u).unwrap_or('\u{fffd}').encode_utf8(&mut utf8).as_bytes());
    }
    out
}

/// One pass over a JSON object: for each wanted top-level key, its value. The whole document is checked as it is
/// read, the values nobody asked for too: it must be one object of RFC 8259 (the literals `true`, `false` and `null`
/// and no other word, numbers by the grammar, strings of valid UTF-8 with JSON's escapes and no control character,
/// brackets that match), at most MAX_DEPTH deep and of at most MAX_MEMBERS members, with nothing after it. A name
/// that appears twice in the top-level object is refused (62), wanted or not. A name is compared as the text it
/// spells (its escapes decoded), so that this reader and any other JSON reader find the same claim under the same
/// name, and a second copy of a claim cannot hide behind another spelling of its name.
pub fn fields<'a, const N: usize>(b: &'a [u8], want: [&[u8]; N]) -> Result<[Option<Raw<'a>>; N], ProgramError> {
    let mut got: [Option<Raw<'a>>; N] = [None; N];
    read(b, &want, &mut got)?;
    Ok(got)
}
/// `fields`, for any number of names: one copy of the reader in a build, however many callers ask for however many.
#[inline(never)]
fn read<'a>(b: &'a [u8], want: &[&[u8]], got: &mut [Option<Raw<'a>>]) -> Result<(), ProgramError> {
    // every name so far, in the order of the first eight bytes of the SHA-256 of the text it spells (so a name is
    // looked for in a few steps however many there are), with where its raw content is and whether it has escapes
    let mut seen: Vec<(u64, u32, u32, bool)> = Vec::with_capacity(MAX_MEMBERS);      // once: a program's heap gives nothing back
    if b.len() > u32::MAX as usize { return Err(err(E_JSON)); }
    let mut i = ws(b, 0);
    if b.get(i) != Some(&b'{') { return Err(err(E_JSON)); }
    i = ws(b, i + 1);
    if b.get(i) != Some(&b'}') {
        loop {
            let (ks, ke, next, escaped) = jstr(b, i)?;
            i = ws(b, next);
            if b.get(i) != Some(&b':') { return Err(err(E_JSON)); }
            let vs = ws(b, i + 1);
            let ve = skip_value(b, vs, MAX_DEPTH - 1)?;
            let decoded = if escaped { spelled(&b[ks..ke]) } else { Vec::new() };
            let key = if escaped { &decoded[..] } else { &b[ks..ke] };
            let h = solana_program::hash::hashv(&[key]).to_bytes();
            let h = u64::from_le_bytes([h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]]);
            let at = seen.partition_point(|e| e.0 < h);
            // the same eight bytes: the same text, or (never yet seen of SHA-256) another: the texts themselves say
            for &(_, s0, e0, escaped0) in seen[at..].iter().take_while(|e| e.0 == h) {
                let earlier = &b[s0 as usize..e0 as usize];
                if if escaped0 { spelled(earlier) == key } else { earlier == key } { return Err(err(E_DUP)); }
            }
            if seen.len() == MAX_MEMBERS { return Err(err(E_JSON)); }
            seen.insert(at, (h, ks as u32, ke as u32, escaped));
            for (w, g) in want.iter().zip(got.iter_mut()) {
                if key == *w {
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
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::claims::{number, text, E_CLAIM};

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
        assert_eq!(json(br#"{"b":1,"b":2}"#), err(E_DUP));                    // a name nobody asked for is checked too
        assert_eq!(json(br#"{"b":1,"b":2}"#), err(E_DUP));
        assert_eq!(json("{\"caf\u{e9}\":1,\"caf\\u00e9\":2}".as_bytes()), err(E_DUP));          // one text, written and escaped
        assert_eq!(json("{\"\u{1f600}\":1,\"\\ud83d\\ude00\":2}".as_bytes()), err(E_DUP));      // and as a surrogate pair
        assert!(fields(br#"{"b":1,"B":2,"b ":3,"x":{"b":1,"b":2}}"#, [b"a"]).is_ok());    // other names; and only the top level is compared
        for bad in [&b""[..], b" ", b"[]", b"\"a\"", b"1", b"null", b"{", b"}", br#"{"a"}"#, br#"{"a":}"#, br#"{"a":"x"} x"#, br#"{"a":"x"}{}"#,
                    br#"{"a":"x",}"#, br#"{,"a":"x"}"#, br#"{"a":"x"#, br#"{"a":[1,2"#, br#"{a:1}"#, br#"{'a':1}"#, br#"{"a":1 "b":2}"#,
                    br#"{"a":"x"\"#, br#"{"a":{"b":1}"#, br#"{"a\":1}"#] {
            assert_eq!(json(bad), err(E_JSON), "{:?}", core::str::from_utf8(bad));
        }
    }

    #[test]
    fn every_value_is_json_whether_or_not_anyone_reads_it() {
        let read = |v: &[u8]| fields(&[&b"{\"a\":\"x\",\"v\":"[..], v, b"}"].concat(), [b"a"]).map(|_| ());
        for good in [&b"true"[..], b"false", b"null", b"0", b"-0", b"7", b"-7", b"1.5", b"0.0", b"1e3", b"1E+30", b"1e-2", b"-1.25e+7", b"12345678901234567890123",
                     b"\"\"", b"\"plain\"", br#""\" \\ \/ \b \f \n \r \t \u0000 \u00e9 \uD83D\uDE00""#, "\"caf\u{e9} \u{4e2d} \u{1f600} \u{7f} \u{ffff} \u{10ffff}\"".as_bytes(),
                     b"[]", b"{}", b"[ ]", b"{ }", b"[1,2]", b"[ 1 , [ ] , { } ]", br#"{"k":[1,{"k":null}],"k2":"}"}"#, br#"{"same":1,"same":2}"#, b"[[[[]]]]"] {
            assert_eq!(read(good), Ok(()), "{:?}", String::from_utf8_lossy(good));
        }
        for bad in [&b"tru"[..], b"truee", b"True", b"nul", b"fals", b"NaN", b"Infinity", b"-Infinity", b"undefined", b"@#$", b"01", b"-", b"-01", b"+1", b"1.", b".5", b"1.2.3", b"1e", b"1e+",
                    b"1ee2", b"0x10", b"1_000", b"1\x0c", b"/**/1", b"1//", b"'y'", b"[}", b"{]", b"[1,]", b"[,1]", b"[1 2]", b"[1,,2]", br#"{"k"}"#, br#"{"k":}"#, br#"{"k":1,}"#,
                    br#"{k:1}"#, br#"{"k":1 "j":2}"#, br#"{1:2}"#, b"[1}", br#"{"k":1]"#, b"\"a\x01b\"", b"\"a\x1fb\"", b"\"a\nb\"", b"\"a\tb\"", b"\"a\x00b\"", br#""\q""#, br#""\u12""#,
                    br#""\u12g4""#, br#""\ud800""#, br#""\ude00""#, br#""\ud800x""#, br#""\ud800\u0041""#, br#""\ude00\ud83d""#, br#""\ud83d\ud83d\ude00""#,
                    b"\"\xff\"", b"\"\xc3\x28\"", b"\"\xc3\"", b"\"\xed\xa0\x80\"", b"\"\xc0\x80\"", b"\"\xc1\xbf\"", b"\"\xe0\x80\x80\"", b"\"\xf0\x80\x80\x80\"",
                    b"\"\xf4\x90\x80\x80\"", b"\"\xf5\x80\x80\x80\"", b"\"\x80\"", b"\"\xe4\xb8\"", b"\"\xf0\x9f\x98\"", b"", b" "] {
            assert_eq!(read(bad), Err(err(E_JSON)), "{:?}", String::from_utf8_lossy(bad));
        }
        // a name is a string like any other
        for bad in [&b"{\"a\x01\":1}"[..], br#"{"\q":1}"#, b"{\"\xff\":1}", br#"{"\ud800":1}"#] {
            assert_eq!(fields(bad, [b"a"]).unwrap_err(), err(E_JSON), "{:?}", String::from_utf8_lossy(bad));
        }
    }

    #[test]
    fn a_document_is_at_most_64_deep_and_its_object_has_at_most_128_members() {
        let nest = |open: &str, close: &str, n: usize| [&b"{\"a\":"[..], open.repeat(n).as_bytes(), b"1", close.repeat(n).as_bytes(), b"}"].concat();
        for (open, close) in [("[", "]"), ("{\"k\":", "}")] {
            assert!(fields(&nest(open, close, MAX_DEPTH - 1), [b"a"]).is_ok());
            assert_eq!(fields(&nest(open, close, MAX_DEPTH), [b"a"]).unwrap_err(), err(E_JSON));
            assert_eq!(fields(&nest(open, close, 5000), [b"a"]).unwrap_err(), err(E_JSON));
        }
        // the brackets are remembered each as its own kind, all the way down
        let mixed = |n: usize, last: &str| format!("{{\"a\":{}1{}{}}}", "[{\"k\":".repeat(n), "}]".repeat(n - 1), last);
        assert!(fields(mixed(31, "}]").as_bytes(), [b"a"]).is_ok());
        assert_eq!(fields(mixed(31, "]}").as_bytes(), [b"a"]).unwrap_err(), err(E_JSON));
        assert_eq!(fields(mixed(31, "]]").as_bytes(), [b"a"]).unwrap_err(), err(E_JSON));
        let members = |n: usize| format!("{{{}}}", (0..n).map(|k| format!("\"k{k}\":{k}")).collect::<Vec<_>>().join(","));
        let full = members(MAX_MEMBERS);
        assert_eq!(number(fields(full.as_bytes(), [b"k127"]).unwrap()[0]), Ok(127));
        assert_eq!(fields(members(MAX_MEMBERS + 1).as_bytes(), [b"k127"]).unwrap_err(), err(E_JSON));
    }

    #[test]
    fn text_decodes_the_escapes_of_printable_ascii_and_no_other() {
        let t = |b: &'static [u8]| text(fields(b, [b"a"]).unwrap()[0]);
        assert_eq!(t(br#"{"a":"octo\/widgets \u0041\u007e \\ \" end"}"#).unwrap(), br#"octo/widgets A~ \ " end"#);
        assert_eq!(t(br#"{"a":"plain"}"#).unwrap(), b"plain");
        assert_eq!(t(br#"{"a":""}"#).unwrap(), b"");
        assert_eq!(t("{\"a\":\"caf\u{e9}\"}".as_bytes()).unwrap(), "caf\u{e9}".as_bytes());      // UTF-8 written as it is
        for bad in [&br#"{"a":"\n"}"#[..], br#"{"a":"\t"}"#, br#"{"a":"\b"}"#, br#"{"a":"\u001f"}"#, br#"{"a":"\u007f"}"#, br#"{"a":"\u00e9"}"#,
                    br#"{"a":"\ud83d\ude00"}"#, br#"{"a":"\r"}"#, br#"{"a":"\f"}"#, br#"{"a":"\u0000"}"#] {
            assert_eq!(t(bad).unwrap_err(), err(E_CLAIM), "{:?}", core::str::from_utf8(bad));
        }
        // an escape JSON does not have is not JSON, in a claim that is read as in one that is not
        for bad in [&br#"{"a":"\u00g1"}"#[..], br#"{"a":"\u004"}"#, br#"{"a":"\x41"}"#, br#"{"a":"\'"}"#, br#"{"a":"\U0041"}"#] {
            assert_eq!(fields(bad, [b"a"]).unwrap_err(), err(E_JSON), "{:?}", core::str::from_utf8(bad));
        }
        assert_eq!(text(None).unwrap_err(), err(E_CLAIM));
        assert_eq!(text(Some(Raw { bytes: b"12", is_str: false })).unwrap_err(), err(E_CLAIM));
    }


    #[test]
    fn a_number_claim_is_read_from_a_number_or_a_string_of_digits() {
        let n = |b: &'static [u8]| number(fields(b, [b"a"]).unwrap()[0]);
        assert_eq!((n(br#"{"a":7}"#), n(br#"{"a":"7"}"#), n(br#"{"a":0}"#)), (Ok(7), Ok(7), Ok(0)));
        for bad in [&br#"{"a":-7}"#[..], br#"{"a":7.0}"#, br#"{"a":"7 "}"#, br#"{"a":"\u0037"}"#, br#"{"a":[7]}"#, br#"{"a":null}"#, br#"{"b":7}"#] {
            assert_eq!(n(bad).unwrap_err(), err(E_CLAIM), "{:?}", core::str::from_utf8(bad));
        }
    }
}
