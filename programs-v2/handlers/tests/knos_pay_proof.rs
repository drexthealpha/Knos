//! knos_pay 0.3.34, pay after proof with no issuer: the test build in LiteSVM, sent the transactions of
//! programs-v2/testdata/pay_on_proof.json (scripts/rust_test_vectors.py `pay_on_proof`). An order judged by a
//! 2-of-3 referee panel: one referee twice in one transaction counts once; that referee again, and a verdict signed
//! for another order, are refused; the second distinct referee pays. Amounts are millionths of test USDC.
#[path = "../../testdata/harness.rs"]
mod harness;
use harness::{u64_at, Answer, Replay};
use knos_pay::order_proof::{PANEL, O_JUDGE, V_BITS, VOTE_LEN};
use knos_pay::state::{O_PAID, O_STATE, OPEN};
use knos_pay::{E_CLAIMS, E_REPLAY, TIP_FIRST};

const USDC: u64 = 1_000_000;
const FEE_20: u64 = 60_000; // 0.30% of 20.00

#[test]
fn a_panel_order_is_paid_by_two_distinct_referees_and_by_nothing_less() {
    let mut r = Replay::load("pay_on_proof");
    assert_eq!(r.to("fund_a"), Answer::Accepted);
    let o = r.data("order").unwrap();
    assert_eq!((o[O_STATE], o[O_JUDGE], u64_at(&o, O_PAID)), (OPEN, PANEL, 0));
    assert_eq!(r.tokens("order_tok"), 20 * USDC + FEE_20);
    // BELOW THRESHOLD and DUPLICATE SIGNER: two entries of one key are one referee; recorded, nothing moves
    assert_eq!(r.to("one_referee_twice"), Answer::Accepted);
    let vote = r.data("vote").unwrap();
    assert_eq!((vote.len(), vote[V_BITS]), (VOTE_LEN, 0b001));
    assert_eq!((r.tokens("order_tok"), r.tokens("dest")), (20 * USDC + FEE_20, 0));
    // REPLAY of the same referee, and a verdict signed for ANOTHER ORDER (the second instruction refuses)
    assert_eq!(r.to("same_referee_again"), Answer::Refused { ix: 2, code: E_REPLAY });
    assert_eq!(r.to("signed_for_another_order"), Answer::Refused { ix: 2, code: E_CLAIMS });
    assert_eq!(r.tokens("dest"), 0);
    // the second distinct referee: the payee is paid the whole amount. Its token account was created by this payment,
    // so the relayer's tip is TIP_FIRST capped at the fee: on 20.00 the whole 0.06 fee goes to the relayer
    assert_eq!(r.to("second_referee_pays"), Answer::Accepted);
    assert_eq!((r.tokens("dest"), r.tokens("order_tok"), r.data("order")), (20 * USDC, 0, None));
    assert_eq!((r.tokens("relayer_tok"), r.tokens("fee")), (FEE_20.min(TIP_FIRST), FEE_20 - FEE_20.min(TIP_FIRST)));
    r.finish();
}
