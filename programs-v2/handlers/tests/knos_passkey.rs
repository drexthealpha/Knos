//! knos_passkey's instruction handlers, run from Rust: the real build (tests/fixtures/knos_passkey_v2_real.so; the
//! program has no test feature) in LiteSVM with its secp256r1 precompile, sent the transactions of
//! programs-v2/testdata/passkey_wallet.json (see ../../testdata/harness.rs).
#[path = "../../testdata/harness.rs"]
mod harness;
use harness::{u64_at, Answer, Replay};
use knos_passkey::{E_NONCE, E_SIGNER, WALLET_LEN, W_KEY, W_NONCE, W_VERSION};

const PAID: u64 = 100_000_000; // what the wallet's token account was paid before the wallet was opened: 100.00
const PRECOMPILE_BAD_SIGNATURE: u32 = 2; // the secp256r1 precompile's own error for a signature that does not verify

/// Open creates the wallet account for the passkey: version 1, the compressed key, nonce 0. No money moves.
#[test]
fn open_creates_the_wallet() {
    let mut r = Replay::load("passkey_wallet");
    assert_eq!(r.data("wallet"), None);
    assert_eq!(r.to("open"), Answer::Accepted);
    let w = r.data("wallet").unwrap();
    assert_eq!((w.len(), w[W_VERSION], u64_at(&w, W_NONCE)), (WALLET_LEN, 1, 0));
    assert!(w[W_KEY] == 2 || w[W_KEY] == 3, "a compressed P-256 point");
    assert_eq!(r.tokens("source"), PAID);
}

/// An assertion another passkey signed moves nothing: checked against the wallet's key the precompile refuses it
/// (instruction 1, before the program runs); checked against its signer's own key the precompile passes and the
/// program refuses with E_SIGNER.
#[test]
fn a_withdrawal_with_a_wrong_signature_is_refused() {
    let mut r = Replay::load("passkey_wallet");
    assert_eq!(r.to("withdraw_wrong_signature"), Answer::Refused { ix: 1, code: PRECOMPILE_BAD_SIGNATURE });
    assert_eq!((r.tokens("source"), r.tokens("to"), u64_at(&r.data("wallet").unwrap(), W_NONCE)), (PAID, 0, 0));
    assert_eq!(r.to("withdraw_another_passkey"), Answer::Refused { ix: 2, code: E_SIGNER });
    assert_eq!((r.tokens("source"), r.tokens("to"), u64_at(&r.data("wallet").unwrap(), W_NONCE)), (PAID, 0, 0));
}

/// Withdraw with the wallet's own passkey pays 5.00 and counts the nonce; the same assertion again is refused (E_NONCE).
#[test]
fn a_withdrawal_pays_once() {
    let mut r = Replay::load("passkey_wallet");
    assert_eq!(r.to("withdraw"), Answer::Accepted);
    assert_eq!((r.tokens("source"), r.tokens("to"), u64_at(&r.data("wallet").unwrap(), W_NONCE)), (PAID - 5_000_000, 5_000_000, 1));
    assert_eq!(r.to("withdraw_replayed"), Answer::Refused { ix: 2, code: E_NONCE });
    assert_eq!((r.tokens("source"), r.tokens("to"), u64_at(&r.data("wallet").unwrap(), W_NONCE)), (PAID - 5_000_000, 5_000_000, 1));
    r.finish();
}
