//! One question for every input, asked of three voices: do the two copies of the claim reader that run today
//! (programs-v2/knos_oidc/src/claims.rs, which runs on chain and which knos-pay reads tokens with, and
//! crates/knos-oidc-interface, which other programs read them with) give the same answer, and is that answer what
//! serde_json reads? The rule is in ../tests/oracle/mod.rs. The third copy of the reader, programs/knos_oidc (the first
//! deployment, frozen), is not asked: it compares a key as raw bytes, and tests/test_settle_fixtures.py names that
//! difference. `agree` is what the nightly fuzz target calls on any bytes and what tests/random.rs calls under
//! `cargo test` on stable.
#[path = "../../tests/oracle/mod.rs"]
pub mod oracle;

use oracle::{Claim, Read, WANT};
use solana_program::program_error::ProgramError;

/// What claims.rs makes of `b`.
pub fn program(b: &[u8]) -> Read {
    use knos_oidc::claims::{fields, number, text};
    match fields(b, WANT) {
        Err(ProgramError::Custom(code)) => Read::Refused(code),
        Err(e) => panic!("claims.rs returns its own codes only: {e:?}"),
        Ok(got) => Read::Claims(got.iter().map(|g| g.map(|r| Claim {
            is_str: r.is_str, raw: r.bytes.to_vec(), text: text(Some(r)).ok(), number: number(Some(r)).ok() })).collect()),
    }
}

/// What the interface crate makes of `b`.
pub fn interface(b: &[u8]) -> Read {
    use knos_oidc_interface::{fields, number, text};
    match fields(b, WANT) {
        Err(e) => Read::Refused(e.code()),
        Ok(got) => Read::Claims(got.iter().map(|g| g.map(|r| Claim {
            is_str: r.is_str, raw: r.bytes.to_vec(), text: text(Some(r)).ok().map(|t| t.bytes().collect()), number: number(Some(r)).ok() })).collect()),
    }
}

/// Panics if the two readers differ on `b` (JSON or not), or if either differs from serde_json where the rule binds.
pub fn agree(b: &[u8]) {
    let (p, i) = (program(b), interface(b));
    oracle::check(b, &p, "claims.rs");
    oracle::check(b, &i, "knos-oidc-interface");
    assert_eq!(p, i, "claims.rs and knos-oidc-interface differ on: {}", String::from_utf8_lossy(b));
    // the helpers both crates carry for audiences give the same answers too
    assert_eq!(knos_oidc::claims::parse_u64(b), knos_oidc_interface::parse_u64(b));
    assert_eq!(knos_oidc::claims::b58_32(b), knos_oidc_interface::b58_32(b));
    assert_eq!(knos_oidc::claims::unhex32(b), knos_oidc_interface::unhex32(b));
    assert_eq!(knos_oidc::claims::parts::<4>(b), knos_oidc_interface::parts::<4>(b));
}
