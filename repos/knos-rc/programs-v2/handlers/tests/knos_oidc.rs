//! knos_oidc's instruction handlers, run from Rust: the test build (tests/fixtures/knos_oidc_v2_test.so) in LiteSVM,
//! sent the transactions of programs-v2/testdata/oidc_verify.json (see ../../testdata/harness.rs; run: cd programs-v2/handlers && cargo test).
#[path = "../../testdata/harness.rs"]
mod harness;
use harness::{Answer, Replay};
use knos_oidc::{E_BADSIG, T_STAGE, VERIFIED};

/// RegisterKey and KeyParams make a genesis key usable; Write stores the token; Verify, in two transactions, checks
/// GitHub's signature and marks the account VERIFIED.
#[test]
fn a_token_is_verified_in_two_transactions() {
    let mut r = Replay::load("oidc_verify");
    assert_eq!(r.to("register_key"), Answer::Accepted);
    assert_eq!(r.to("key_params"), Answer::Accepted);
    assert!(r.data("key").is_some());
    assert_eq!(r.to("token_step1"), Answer::Accepted);
    let half = r.data("token").unwrap();
    assert!(half[T_STAGE] != VERIFIED && half[T_STAGE] != 0, "one transaction is half of the work");
    assert_eq!(r.to("token_step2"), Answer::Accepted);
    assert_eq!(r.data("token").unwrap()[T_STAGE], VERIFIED);
}

/// One bit of the signature flipped: the second transaction refuses with E_BADSIG and the account is not VERIFIED.
#[test]
fn a_token_with_a_bad_signature_is_refused() {
    let mut r = Replay::load("oidc_verify");
    assert_eq!(r.to("forged_step1"), Answer::Accepted);
    assert_eq!(r.to("forged_step2"), Answer::Refused { ix: 1, code: E_BADSIG });
    assert_ne!(r.data("forged").unwrap()[T_STAGE], VERIFIED);
    assert_eq!(r.data("token").unwrap()[T_STAGE], VERIFIED, "the good token is as it was");
    r.finish();
}
