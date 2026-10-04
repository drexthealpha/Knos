//! What a claim reader has to agree with serde_json about, and documents to ask it on. Shared by the randomised test
//! of claims.rs (tests/claims_random.rs, stable, runs under `cargo test`), the fuzz target (fuzz/), and the interface
//! crate's own test (crates/knos-oidc-interface/tests/differential.rs).
//!
//! The rule, for a document serde_json reads as a JSON object:
//!   - the reader accepts it, unless a wanted name appears twice (as the text the key spells): then it says 62;
//!   - a wanted name is found exactly when serde_json finds it, as a string exactly when serde_json has a string;
//!   - a text the reader returns is serde_json's string, byte for byte; it may refuse a string only if the string
//!     holds a character outside printable ASCII that was written as an escape;
//!   - a number the reader returns is serde_json's (a JSON integer, or a string of digits); it returns one for
//!     every integer below 10^18 and every plain string of at most 18 digits with no leading zero.
//!
//! For anything else (not JSON, not an object) the reader may answer what it likes, and must not panic.
#![allow(dead_code)]
use serde::de::{Deserialize, Deserializer, MapAccess, Visitor};
use serde_json::Value;

/// The claims knos-oidc and knos-pay ask for.
pub const WANT: [&[u8]; 14] = [b"iss", b"aud", b"exp", b"iat", b"repository_id", b"repository_owner_id", b"actor_id", b"job_workflow_ref",
                               b"job_workflow_sha", b"runner_environment", b"event_name", b"run_attempt", b"repository", b"alg"];

/// What one reader made of one wanted claim, and of one document.
#[derive(Debug, PartialEq, Eq, Clone)]
pub struct Claim { pub is_str: bool, pub raw: Vec<u8>, pub text: Option<Vec<u8>>, pub number: Option<u64> }
#[derive(Debug, PartialEq, Eq, Clone)]
pub enum Read { Refused(u32), Claims(Vec<Option<Claim>>) }

/// Every member of the top-level object, in order, duplicates kept (serde_json's own map keeps the last one only).
struct Pairs(Vec<(String, Value)>);
impl<'de> Deserialize<'de> for Pairs {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = Pairs;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result { f.write_str("a JSON object") }
            fn visit_map<A: MapAccess<'de>>(self, mut m: A) -> Result<Pairs, A::Error> {
                let mut out = Vec::new();
                while let Some(pair) = m.next_entry::<String, Value>()? { out.push(pair); }
                Ok(Pairs(out))
            }
        }
        d.deserialize_map(V)
    }
}
pub fn pairs(b: &[u8]) -> Option<Vec<(String, Value)>> { serde_json::from_slice::<Pairs>(b).ok().map(|p| p.0) }

fn plain_digits(s: &[u8]) -> Option<u64> {
    if s.is_empty() || s.len() > 18 || !s.iter().all(u8::is_ascii_digit) || (s.len() > 1 && s[0] == b'0') { return None; }
    std::str::from_utf8(s).ok()?.parse().ok()
}

/// Panics, saying what differs, if `read` is not what the rule above allows for `b`.
pub fn check(b: &[u8], read: &Read, who: &str) {
    let Some(pairs) = pairs(b) else { return };
    let doc = String::from_utf8_lossy(b);
    let count = |w: &[u8]| pairs.iter().filter(|(k, _)| k.as_bytes() == w).count();
    let twice = WANT.iter().any(|w| count(w) > 1);
    let got = match read {
        Read::Refused(code) => { assert!(twice && *code == 62, "{who} refused ({code}) an object serde_json reads: {doc}"); return; }
        Read::Claims(got) => got,
    };
    assert!(!twice, "{who} accepted a wanted claim that appears twice: {doc}");
    for (w, g) in WANT.iter().zip(got) {
        let name = String::from_utf8_lossy(w);
        let v = pairs.iter().find(|(k, _)| k.as_bytes() == *w).map(|(_, v)| v);
        let (g, v) = match (g, v) {
            (None, None) => continue,
            (Some(g), Some(v)) => (g, v),
            (g, v) => panic!("{who}: {name} is {g:?}, serde_json has {v:?}: {doc}"),
        };
        assert_eq!(g.is_str, v.is_string(), "{who}: {name} string or not: {doc}");
        match (&g.text, v.as_str()) {
            (Some(t), Some(s)) => assert_eq!(t.as_slice(), s.as_bytes(), "{who}: {name} text: {doc}"),
            (Some(t), None) => panic!("{who}: {name} read as the text {t:?} of {v}: {doc}"),
            (None, Some(s)) => assert!(g.raw.contains(&b'\\') && s.chars().any(|c| !(' '..='~').contains(&c)), "{who}: {name} refused the text {s:?}: {doc}"),
            (None, None) => {}
        }
        let theirs = match v {
            Value::Number(n) => n.as_u64().filter(|x| *x < 1_000_000_000_000_000_000),
            Value::String(s) => plain_digits(s.as_bytes()),
            _ => None,
        };
        if let Some(n) = g.number { assert_eq!(Some(n), theirs, "{who}: {name} number: {doc}"); }
        // a digit written as an escape ("1") is a number to serde_json's string and refused here: refusing is allowed
        if theirs.is_some() && !g.raw.contains(&b'\\') { assert_eq!(g.number, theirs, "{who}: {name} number refused: {doc}"); }
    }
}

/// xorshift64*: the same documents on every run and every machine.
pub struct Rng(pub u64);
impl Rng {
    pub fn next(&mut self) -> u64 {
        self.0 ^= self.0 >> 12; self.0 ^= self.0 << 25; self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
    pub fn below(&mut self, n: usize) -> usize { (self.next() % n as u64) as usize }
    pub fn one_in(&mut self, n: usize) -> bool { self.below(n) == 0 }
}

fn space(r: &mut Rng, out: &mut Vec<u8>) {
    if r.one_in(4) { for _ in 0..r.below(3) { out.push(b" \t\n\r"[r.below(4)]); } }
}
/// A JSON string for `s`: plain, or with some characters spelled as escapes (every spelling JSON allows).
fn string(r: &mut Rng, s: &str, out: &mut Vec<u8>) {
    out.push(b'"');
    for c in s.chars() {
        let escape = c == '"' || c == '\\' || (c as u32) < 0x20 || r.one_in(6);
        if !escape { out.extend_from_slice(c.to_string().as_bytes()); continue; }
        match c {
            '/' if r.one_in(2) => out.extend_from_slice(b"\\/"),
            '"' if r.one_in(2) => out.extend_from_slice(b"\\\""),
            '\\' if r.one_in(2) => out.extend_from_slice(b"\\\\"),
            '\n' if r.one_in(2) => out.extend_from_slice(b"\\n"),
            '\t' if r.one_in(2) => out.extend_from_slice(b"\\t"),
            _ => {
                let mut units = [0u16; 2];
                for u in c.encode_utf16(&mut units) {
                    let hex = if r.one_in(2) { format!("\\u{u:04x}") } else { format!("\\u{u:04X}") };
                    out.extend_from_slice(hex.as_bytes());
                }
            }
        }
    }
    out.push(b'"');
}
fn value(r: &mut Rng, depth: usize, out: &mut Vec<u8>) {
    const TEXTS: [&str; 14] = ["", "x", "https://token.actions.githubusercontent.com", "octo/widgets", "knos2:pay:1:2:3", "github-hosted",
                               "a\"b\\c", "line\nbreak\ttab", "caf\u{e9}", "\u{1f600}", "}{][,:", "1790000300", "007", "999999999999999999"];
    const NUMBERS: [&str; 14] = ["0", "1", "1790000300", "999999999999999999", "1000000000000000000", "18446744073709551615", "-1", "-0",
                                 "1.5", "1e3", "1E+2", "0.0", "12345678901234567890123", "17"];
    match r.below(if depth > 2 { 8 } else { 10 }) {
        0..=3 => { let s = TEXTS[r.below(TEXTS.len())]; string(r, s, out) }
        4..=6 => out.extend_from_slice(NUMBERS[r.below(NUMBERS.len())].as_bytes()),
        7 => out.extend_from_slice([&b"true"[..], b"false", b"null"][r.below(3)]),
        8 => {
            out.push(b'[');
            for i in 0..r.below(4) { if i > 0 { out.push(b','); } space(r, out); value(r, depth + 1, out); }
            out.push(b']');
        }
        _ => object(r, depth + 1, out),
    }
}
fn object(r: &mut Rng, depth: usize, out: &mut Vec<u8>) {
    const OTHER: [&str; 6] = ["sub", "jti", "au", "audience", "a\"ud", "https://example.com/roles"];
    out.push(b'{');
    for i in 0..r.below(7) {
        if i > 0 { out.push(b','); }
        space(r, out);
        let name = if r.one_in(4) { OTHER[r.below(OTHER.len())] } else { std::str::from_utf8(WANT[r.below(WANT.len())]).unwrap() };
        string(r, name, out);
        space(r, out);
        out.push(b':');
        space(r, out);
        value(r, depth, out);
        space(r, out);
    }
    out.push(b'}');
}
/// A document: most are JSON objects whose members are the wanted claims in every spelling, some of them twice;
/// one in three is then damaged (a byte changed, dropped, added, or the end cut off).
pub fn document(r: &mut Rng) -> Vec<u8> {
    let mut out = Vec::new();
    space(r, &mut out);
    object(r, 0, &mut out);
    space(r, &mut out);
    if r.one_in(3) {
        for _ in 0..1 + r.below(3) {
            if out.is_empty() { break; }
            let at = r.below(out.len());
            match r.below(4) {
                0 => out[at] = b"\"\\{},:u0 \xff\0"[r.below(11)],
                1 => { out.remove(at); }
                2 => out.insert(at, b"\"\\{}[],:x"[r.below(9)]),
                _ => out.truncate(at),
            }
        }
    }
    out
}
