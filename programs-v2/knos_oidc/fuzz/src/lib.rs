//! One question for every input, asked of four voices: the program's own reader (programs-v2/knos_oidc/src/strict.rs,
//! which Step reads a token with before it marks it VERIFIED), the two readers that consumers read a verified token
//! with (programs-v2/knos_oidc/src/claims.rs, compiled into knos-pay, and crates/knos-oidc-interface) and serde_json.
//! Since knos-oidc 2.2 the program's reader is strict: it accepts exactly the documents serde_json reads as an object
//! (but for a name twice, 64 levels and 128 members). The two consumers' readers pass over the values they do not
//! read, and they only ever read what the program verified: so each must give the same claims as the program for
//! every document the program accepts. What they make of a document the program refuses is held to the older rule
//! only (agree with serde_json where serde_json reads it). The rules are in ../tests/oracle/mod.rs. The last copy of
//! the reader, programs/knos_oidc (the first
//! deployment, frozen), is not asked: it compares a key as raw bytes, and tests/test_settle_fixtures.py names that
//! difference. `agree` is what the nightly fuzz target calls on any bytes and what tests/random.rs calls under
//! `cargo test` on stable.
#[path = "../../tests/oracle/mod.rs"]
pub mod oracle;
/// The second target's check: the RSA arithmetic against big integers and the `rsa` crate.
pub mod rsa_diff;

use oracle::{Claim, Read, WANT};
use solana_program::program_error::ProgramError;

fn made(got: Result<[Option<knos_oidc::claims::Raw>; WANT.len()], ProgramError>, who: &str) -> Read {
    use knos_oidc::claims::{number, text};
    match got {
        Err(ProgramError::Custom(code)) => Read::Refused(code),
        Err(e) => panic!("{who} returns its own codes only: {e:?}"),
        Ok(got) => Read::Claims(got.iter().map(|g| g.map(|r| Claim {
            is_str: r.is_str, raw: r.bytes.to_vec(), text: text(Some(r)).ok(), number: number(Some(r)).ok() })).collect()),
    }
}
/// What strict.rs, the reader the program verifies a token with, makes of `b`.
pub fn program(b: &[u8]) -> Read { made(knos_oidc::strict::fields(b, WANT), "strict.rs") }
/// What claims.rs, the reader knos-pay reads a verified token with (2.1's, unchanged), makes of `b`.
pub fn consumer(b: &[u8]) -> Read { made(knos_oidc::claims::fields(b, WANT), "claims.rs") }

/// What the interface crate makes of `b`.
pub fn interface(b: &[u8]) -> Read {
    use knos_oidc_interface::{fields, number, text};
    match fields(b, WANT) {
        Err(e) => Read::Refused(e.code()),
        Ok(got) => Read::Claims(got.iter().map(|g| g.map(|r| Claim {
            is_str: r.is_str, raw: r.bytes.to_vec(), text: text(Some(r)).ok().map(|t| t.bytes().collect()), number: number(Some(r)).ok() })).collect()),
    }
}

/// Panics if the program's reader is not strict on `b`, if a consumer's reader reads a document the program accepts
/// in any other way, or if any of the three differs from serde_json where its rule binds.
pub fn agree(b: &[u8]) {
    let (p, c, i) = (program(b), consumer(b), interface(b));
    oracle::check_strict(b, &p, "strict.rs");
    oracle::check(b, &c, "claims.rs");
    oracle::check(b, &i, "knos-oidc-interface");
    assert_eq!(c, i, "claims.rs and knos-oidc-interface differ on: {}", String::from_utf8_lossy(b));
    if matches!(p, Read::Claims(_)) {
        assert_eq!(p, c, "strict.rs and claims.rs differ on a document the program accepts: {}", String::from_utf8_lossy(b));
    }
    // the helpers both crates carry for audiences give the same answers too
    assert_eq!(knos_oidc::claims::parse_u64(b), knos_oidc_interface::parse_u64(b));
    assert_eq!(knos_oidc::claims::b58_32(b), knos_oidc_interface::b58_32(b));
    assert_eq!(knos_oidc::claims::unhex32(b), knos_oidc_interface::unhex32(b));
    assert_eq!(knos_oidc::claims::parts::<4>(b), knos_oidc_interface::parts::<4>(b));
}
