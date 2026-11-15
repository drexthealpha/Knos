//! What this program reads of a WebAuthn assertion: the data of the secp256r1 precompile instruction that verified
//! it, and the two members of clientDataJSON that say what was signed. Pure functions: no account, no syscall.

pub const KEY_LEN: usize = 33; // a P-256 public key, SEC1 compressed: 0x02 or 0x03, then x
pub const SIG_LEN: usize = 64; // r, then s, 32 bytes each, big-endian
pub const AUTH_MIN: usize = 37; // authenticatorData: rpIdHash [32], flags, signCount u32; extensions may follow
pub const USER_PRESENT: u8 = 1; // bit 0 of the flags
const SELF: u16 = u16::MAX; // an instruction index of the precompile: "these bytes are in my own data"

/// Half the order of P-256, big-endian. A signature (r, s) and (r, n - s) verify alike; only s <= n/2 is accepted, so
/// one assertion has one signature.
pub const HALF_N: [u8; 32] = [
    0x7F, 0xFF, 0xFF, 0xFF, 0x80, 0x00, 0x00, 0x00, 0x7F, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
    0xDE, 0x73, 0x7D, 0x56, 0xD3, 0x8B, 0xCF, 0x42, 0x79, 0xDC, 0xE5, 0x61, 0x7E, 0x31, 0x92, 0xA8,
];

pub struct Verified<'a> { pub key: &'a [u8], pub signature: &'a [u8], pub message: &'a [u8] }

/// What a secp256r1 precompile instruction with this data verified, when it is exactly one signature whose key,
/// signature and message are all in the instruction's own data. The data is: count u8, padding u8, then per signature
/// seven u16 LE (signature offset, signature instruction, key offset, key instruction, message offset, message
/// length, message instruction). The precompile reads each part from the instruction an index names, so a record
/// that points anywhere else is refused here: the bytes at the offsets would not be the bytes that were verified.
pub fn verified(data: &[u8]) -> Option<Verified<'_>> {
    if data.len() < 16 || data[0] != 1 { return None; }
    let n = |k: usize| u16::from_le_bytes([data[2 + 2 * k], data[3 + 2 * k]]);
    if n(1) != SELF || n(3) != SELF || n(6) != SELF { return None; }
    let at = |offset: u16, len: usize| data.get(offset as usize..offset as usize + len);
    Some(Verified { signature: at(n(0), SIG_LEN)?, key: at(n(2), KEY_LEN)?, message: at(n(4), n(5) as usize)? })
}

/// s <= n/2 (big-endian bytes compare as the numbers do). The precompile enforces it too.
pub fn low_s(signature: &[u8]) -> bool { signature.len() == SIG_LEN && signature[32..] <= HALF_N[..] }

/// Unpadded base64url of a 32-byte hash: the 43 characters a browser writes as clientDataJSON's `challenge`.
pub fn b64url(hash: &[u8; 32]) -> [u8; 43] {
    const A: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = [0u8; 43];
    for (k, c) in hash.chunks(3).enumerate() {
        let v = (c[0] as u32) << 16 | (*c.get(1).unwrap_or(&0) as u32) << 8 | *c.get(2).unwrap_or(&0) as u32;
        for j in 0..(c.len() + 1) { out[4 * k + j] = A[(v >> (18 - 6 * j)) as usize & 63]; }
    }
    out
}

struct Scan<'a> { s: &'a [u8], i: usize }
impl<'a> Scan<'a> {
    fn peek(&self) -> Option<u8> { self.s.get(self.i).copied() }
    fn ws(&mut self) { while matches!(self.peek(), Some(b' ' | b'\t' | b'\n' | b'\r')) { self.i += 1; } }
    fn eat(&mut self, c: u8) -> Option<()> { if self.peek()? == c { self.i += 1; Some(()) } else { None } }
    /// A string: what is between its quotes, as written (an escape is skipped over, not decoded).
    fn string(&mut self) -> Option<&'a [u8]> {
        self.eat(b'"')?;
        let from = self.i;
        loop {
            match self.peek()? { b'"' => break, b'\\' => self.i += 2, _ => self.i += 1 }
        }
        self.i += 1;
        Some(&self.s[from..self.i - 1])
    }
    /// Any other value: up to the comma or the brace that ends the member, over nested objects, arrays and strings.
    fn skip(&mut self) -> Option<()> {
        let (from, mut depth) = (self.i, 0usize);
        loop {
            match self.peek()? {
                b'"' => { self.string()?; }
                b'{' | b'[' => { depth += 1; self.i += 1; }
                b',' | b'}' | b']' if depth == 0 => break,
                b'}' | b']' => { depth -= 1; self.i += 1; }
                _ => self.i += 1,
            }
        }
        if self.i > from { Some(()) } else { None }
    }
}

/// (type, challenge) of a clientDataJSON: its two top-level string members of those names, each exactly once, in
/// any order and among any other members (browsers add `origin`, `crossOrigin` and more). The values are returned
/// as written, to be compared with the bytes expected; this is not a JSON validator.
pub fn client_data(json: &[u8]) -> Option<(&[u8], &[u8])> {
    let mut p = Scan { s: json, i: 0 };
    let (mut ty, mut challenge) = (None, None);
    p.ws();
    p.eat(b'{')?;
    loop {
        p.ws();
        let key = p.string()?;
        p.ws();
        p.eat(b':')?;
        p.ws();
        let value = if p.peek()? == b'"' { Some(p.string()?) } else { p.skip()?; None };
        let slot = match key { b"type" => Some(&mut ty), b"challenge" => Some(&mut challenge), _ => None };
        if let Some(slot) = slot {
            if slot.is_some() { return None; } // named twice: which one counts is not ours to choose
            *slot = Some(value?);
        }
        p.ws();
        match p.peek()? { b',' => p.i += 1, b'}' => { p.i += 1; break; } _ => return None }
    }
    p.ws();
    if p.i != json.len() { return None; }
    Some((ty?, challenge?))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A precompile instruction's data as the clients build it: the offsets, then key, signature, message.
    fn precompile(key: &[u8], sig: &[u8], msg: &[u8]) -> Vec<u8> {
        let mut d = vec![1u8, 0];
        for v in [16 + 33, SELF, 16, SELF, 16 + 33 + 64, msg.len() as u16, SELF] { d.extend_from_slice(&v.to_le_bytes()); }
        [d, key.to_vec(), sig.to_vec(), msg.to_vec()].concat()
    }

    #[test]
    fn one_signature_whose_parts_are_in_the_instruction_itself_is_read_and_nothing_else() {
        let (key, sig, msg) = ([2u8; 33], [7u8; 64], b"authenticator data and a hash".to_vec());
        let d = precompile(&key, &sig, &msg);
        let v = verified(&d).unwrap();
        assert_eq!((v.key, v.signature, v.message), (&key[..], &sig[..], &msg[..]));
        // no signature, two signatures, a truncated header
        for count in [0u8, 2, 8] { let mut x = d.clone(); x[0] = count; assert!(verified(&x).is_none()); }
        assert!(verified(&d[..15]).is_none() && verified(&[]).is_none());
        // a part that lives in another instruction: the key, the signature, the message
        for field in [1usize, 3, 6] {
            for index in [0u16, 1, 0xFFFE] {
                let mut x = d.clone();
                x[2 + 2 * field..4 + 2 * field].copy_from_slice(&index.to_le_bytes());
                assert!(verified(&x).is_none(), "field {field} index {index}");
            }
        }
        // offsets and lengths that run past the data
        for (field, value) in [(0usize, d.len() as u16 - 63), (2, d.len() as u16 - 32), (4, d.len() as u16), (5, msg.len() as u16 + 1), (0, u16::MAX), (4, u16::MAX)] {
            let mut x = d.clone();
            x[2 + 2 * field..4 + 2 * field].copy_from_slice(&value.to_le_bytes());
            assert!(verified(&x).is_none(), "field {field} value {value}");
        }
        // the parts are read where the offsets say, not where a client usually puts them
        let mut moved = vec![1u8, 0];
        for v in [16u16, SELF, 16 + 64, SELF, 16 + 64 + 33, 3, SELF] { moved.extend_from_slice(&v.to_le_bytes()); }
        let moved = [moved, sig.to_vec(), key.to_vec(), b"abc".to_vec()].concat();
        let v = verified(&moved).unwrap();
        assert_eq!((v.key, v.signature, v.message), (&key[..], &sig[..], &b"abc"[..]));
    }

    #[test]
    fn only_the_lower_of_the_two_s_values_is_accepted() {
        let sig = |s: [u8; 32]| [[9u8; 32], s].concat();
        let mut above = HALF_N;
        above[31] += 1;
        let mut below = HALF_N;
        below[31] -= 1;
        assert!(low_s(&sig(HALF_N)) && low_s(&sig(below)) && low_s(&sig([0; 32])));
        assert!(!low_s(&sig(above)) && !low_s(&sig([0xFF; 32])) && !low_s(&sig([0x80; 32])));
        assert!(!low_s(&[0u8; 63]) && !low_s(&[]));
        // n = 2 * HALF_N + 1: the order of P-256
        let n: [u8; 32] = [0xFF, 0xFF, 0xFF, 0xFF, 0, 0, 0, 0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
                           0xBC, 0xE6, 0xFA, 0xAD, 0xA7, 0x17, 0x9E, 0x84, 0xF3, 0xB9, 0xCA, 0xC2, 0xFC, 0x63, 0x25, 0x51];
        let (mut twice, mut carry) = ([0u8; 32], 1u16);
        for k in (0..32).rev() { let v = 2 * HALF_N[k] as u16 + carry; twice[k] = v as u8; carry = v >> 8; }
        assert_eq!((twice, carry), (n, 0));
    }

    #[test]
    fn base64url_of_a_hash_is_what_a_browser_writes() {
        assert_eq!(&b64url(&[0; 32]), b"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA");
        assert_eq!(&b64url(&[0xFF; 32]), b"__________________________________________8");
        let mut h = [0u8; 32];
        for (k, b) in h.iter_mut().enumerate() { *b = (k * 8 + 3) as u8; }
        assert_eq!(&b64url(&h), b"AwsTGyMrMztDS1NbY2tze4OLk5ujq7O7w8vT2-Pr8_s");
    }

    #[test]
    fn type_and_challenge_are_found_at_the_top_level_once_in_any_order() {
        let chrome = br#"{"type":"webauthn.get","challenge":"abc-_","origin":"https://knos.dev","crossOrigin":false}"#;
        assert_eq!(client_data(chrome), Some((&b"webauthn.get"[..], &b"abc-_"[..])));
        let other = br#" { "origin" : "https://knos.dev" , "challenge" : "abc" , "crossOrigin" : false , "tokenBinding" : { "status" : "supported", "x": [1, {"type": "no"}] } , "type" : "webauthn.get" } "#;
        assert_eq!(client_data(other), Some((&b"webauthn.get"[..], &b"abc"[..])));
        // a value is returned as written: an escape is not decoded, so it cannot equal what is expected
        assert_eq!(client_data(br#"{"type":"webauthn.get","challenge":"a\"b"}"#), Some((&br"webauthn.get"[..], &br#"a\"b"#[..])));
        let refused: [&[u8]; 16] = [
            b"", b"{}", b"[]", br#"{"type":"webauthn.get"}"#, br#"{"challenge":"abc"}"#,
            br#"{"type":"webauthn.get","challenge":"abc","type":"webauthn.get"}"#,         // named twice
            br#"{"type":"webauthn.get","challenge":"abc","challenge":"abd"}"#,
            br#"{"type":"webauthn.get","challenge":7}"#,                                    // not a string
            br#"{"type":"webauthn.get","origin":{"challenge":"abc"}}"#,                     // only inside another member
            br#"{"type":"webauthn.get","origin":"\",\"challenge\":\"abc"}"#,               // only inside a string
            br#"{"type":"webauthn.get","challenge":"abc"}x"#,                               // something after the object
            br#"{"type":"webauthn.get","challenge":"abc""#,                                 // not closed
            br#"{"type":"webauthn.get","challenge":"abc","x":}"#,                           // a member with no value
            br#"{"type":"webauthn.get","challenge":"abc","x":[1}"#,
            br#"{"type":"webauthn.get" "challenge":"abc"}"#,
            br#"{"type":"webauthn.get","challenge":"abc\"#,
        ];
        for json in refused { assert_eq!(client_data(json), None, "{}", String::from_utf8_lossy(json)); }
    }
}
