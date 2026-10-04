//! knos_meter's instruction handlers, run from Rust: the test build (tests/fixtures/knos_meter_test.so beside
//! knos_oidc_v2_test.so) in LiteSVM, sent the transactions of programs-v2/testdata/meter_count.json (see
//! ../../testdata/harness.rs). The buyer is past the month's free evaluations, so each one costs FEE.
#[path = "../../testdata/harness.rs"]
mod harness;
use harness::{u64_at, Answer, Replay};
use knos_meter::state::{C_EVALS, C_SPENT, L_ACCEPTED, L_EVALS, L_FEES, L_KIND, L_NEXT_SEQ, L_VALUE, M_ACCEPTED, M_EVALS, M_VALUE};
use knos_meter::{E_SEQ, FEE};

const USDC: u64 = 1_000_000;
const CREDITS: u64 = 1000 * USDC; // what the wallet deposited
const BATCH: u64 = 5000; // evaluations in the batch; 4,321 accepted, worth 8,642.00

/// OpenCredits, a deposit, then Record: one evaluation costs the credits 0.05, which the fee account receives, and the
/// month's count of the buyer and seller has it.
#[test]
fn record() {
    let mut r = Replay::load("meter_count");
    assert_eq!(r.to("open_credits"), Answer::Accepted);
    assert_eq!(r.to("deposit"), Answer::Accepted);
    assert_eq!(r.tokens("credits_tok"), CREDITS);
    assert_eq!(r.to("record"), Answer::Accepted);
    assert_eq!((r.tokens("credits_tok"), r.tokens("fee")), (CREDITS - FEE, FEE));
    let (c, m) = (r.data("credits").unwrap(), r.data("month").unwrap());
    assert_eq!((u64_at(&c, C_SPENT), u64_at(&c, C_EVALS)), (FEE, 1));
    assert_eq!((u64_at(&m, M_EVALS), u64_at(&m, M_ACCEPTED), u64_at(&m, M_VALUE)), (1, 1, 2 * USDC));
}

/// RecordBatch: 5,000 evaluations are billed at once and the ledger of the pair and month counts them.
#[test]
fn record_batch() {
    let mut r = Replay::load("meter_count");
    assert_eq!(r.data("ledger"), None);
    assert_eq!(r.to("record_batch"), Answer::Accepted);
    assert_eq!((r.tokens("credits_tok"), r.tokens("fee")), (CREDITS - (BATCH + 1) * FEE, (BATCH + 1) * FEE));
    let l = r.data("ledger").unwrap();
    assert_eq!((l[L_KIND], u64_at(&l, L_NEXT_SEQ), u64_at(&l, L_EVALS), u64_at(&l, L_ACCEPTED), u64_at(&l, L_VALUE), u64_at(&l, L_FEES)),
               (0, 1, BATCH, 4321, 8_642 * USDC, BATCH * FEE));
}

/// RecordBatch with the same seq again (a new token GitHub signed for the same batch): refused with E_SEQ; no fee, and
/// the ledger is byte for byte what it was.
#[test]
fn record_batch_with_the_same_seq_again_is_refused() {
    let mut r = Replay::load("meter_count");
    r.to("record_batch");
    let (ledger, held) = (r.data("ledger"), r.tokens("credits_tok"));
    assert_eq!(r.to("record_batch_same_seq"), Answer::Refused { ix: 1, code: E_SEQ });
    assert_eq!((r.data("ledger"), r.tokens("credits_tok"), r.tokens("fee")), (ledger, held, (BATCH + 1) * FEE));
}

/// ClaimBatch: the seller's own run claims the same batch; its ledger counts it and costs nothing. WithdrawCredits:
/// the wallet that opened the credits takes back what is left.
#[test]
fn claim_batch_and_withdraw_credits() {
    let mut r = Replay::load("meter_count");
    assert_eq!(r.to("claim_batch"), Answer::Accepted);
    let l = r.data("claims").unwrap();
    assert_eq!((l[L_KIND], u64_at(&l, L_NEXT_SEQ), u64_at(&l, L_EVALS), u64_at(&l, L_ACCEPTED), u64_at(&l, L_FEES)), (1, 1, BATCH, 4321, 0));
    assert_eq!(r.to("withdraw_credits"), Answer::Accepted);
    assert_eq!((r.tokens("credits_tok"), r.tokens("wallet_tok"), r.tokens("fee")), (0, CREDITS - (BATCH + 1) * FEE, (BATCH + 1) * FEE));
    r.finish();
}
