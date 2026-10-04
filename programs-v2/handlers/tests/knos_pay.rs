//! knos_pay's instruction handlers, run from Rust: the test builds (tests/fixtures/knos_pay_v2_test.so beside
//! knos_oidc_v2_test.so) in LiteSVM, sent the transactions of programs-v2/testdata/{pay_order,double_pay,order_fees}.json
//! (see ../../testdata/harness.rs). Amounts are in millionths of test USDC.
#[path = "../../testdata/harness.rs"]
mod harness;
use harness::{i64_at, u64_at, Answer, Replay};
use knos_pay::order_terms::NOTICE;
use knos_pay::state::{O_AMOUNT, O_CANCEL_AT, O_DEADLINE, O_FEE, O_PAID, O_STATE, OPEN, U_AFTER};
use knos_pay::{order_fee, E_ACCOUNTS, E_ORDER, E_REPLAY, E_STATE, FEE_BPS, TIP};

const USDC: u64 = 1_000_000;
const FUNDER: u64 = 1_000_000 * USDC; // what the funding wallet starts with
const BALANCE: u64 = 100_000 * USDC; // what the repository owner's Balance starts with
const FEE_100: u64 = 2_500_000; // 2.5% of 100.00

/// FundOrderWallet: the wallet pays the amount and the fee on top into the order's own token account, and the order
/// account says so.
#[test]
fn fund_order_wallet() {
    let mut r = Replay::load("pay_order");
    assert_eq!(r.to("fund_order_wallet"), Answer::Accepted);
    assert_eq!((r.tokens("funder_tok"), r.tokens("order_tok"), r.tokens("fee")), (FUNDER - 100 * USDC - FEE_100, 100 * USDC + FEE_100, 0));
    let o = r.data("order").unwrap();
    assert_eq!((o[O_STATE], u64_at(&o, O_AMOUNT), u64_at(&o, O_FEE), u64_at(&o, O_PAID)), (OPEN, 100 * USDC, FEE_100, 0));
    assert!(i64_at(&o, O_DEADLINE) > r.now() && i64_at(&o, O_CANCEL_AT) == 0);
}

/// PayOrder: the payee gets the whole amount, the fee is split between the relayer's tip and the fee account, the
/// order and its token account are gone, and the token's single-use marker is left behind.
#[test]
fn pay_order() {
    let mut r = Replay::load("pay_order");
    assert_eq!(r.to("pay_order"), Answer::Accepted);
    assert_eq!((r.tokens("dest"), r.tokens("relayer_tok"), r.tokens("fee")), (100 * USDC, TIP, FEE_100 - TIP));
    assert_eq!((r.tokens("order_tok"), r.data("order"), r.data("order_tok")), (0, None, None));
    assert_eq!(r.tokens("funder_tok"), FUNDER - 100 * USDC - FEE_100, "the funder paid once");
    let used = r.data("used").expect("the marker of the pay token");
    assert!(i64_at(&used, U_AFTER) > r.now(), "the marker cannot be closed while the token could still be shown");
}

/// PayOrder with the same token again, as the accounts stand: refused (the order is gone: E_ORDER), nothing moves.
#[test]
fn pay_order_with_the_same_token_again_is_refused() {
    let mut r = Replay::load("pay_order");
    assert_eq!(r.to("pay_order_again"), Answer::Refused { ix: 1, code: E_ORDER });
    assert_eq!((r.tokens("dest"), r.tokens("relayer_tok"), r.tokens("fee")), (100 * USDC, TIP, FEE_100 - TIP));
    r.finish();
}

/// The same order address funded a second time (FundOrderBalance, a second fund token for the issue): the pay token
/// that paid the first order is refused by its marker (E_REPLAY), and the second order keeps every unit.
#[test]
fn pay_order_after_refunding_the_same_address_with_the_old_token_is_refused() {
    let mut r = Replay::load("double_pay");
    assert_eq!(r.to("fund_order_balance"), Answer::Accepted);
    assert_eq!((r.tokens("balance_tok"), r.tokens("order_tok")), (BALANCE - 100 * USDC - FEE_100, 100 * USDC + FEE_100));
    assert_eq!(r.to("pay_order"), Answer::Accepted);
    assert_eq!((r.tokens("dest"), r.data("order")), (100 * USDC, None));
    assert_eq!(r.to("fund_same_address"), Answer::Accepted);
    assert_eq!((r.tokens("balance_tok"), r.tokens("order_tok")), (BALANCE - 2 * (100 * USDC + FEE_100), 100 * USDC + FEE_100));
    assert_eq!(r.to("pay_with_old_token"), Answer::Refused { ix: 1, code: E_REPLAY });
    assert_eq!((r.tokens("dest"), r.tokens("order_tok")), (100 * USDC, 100 * USDC + FEE_100), "one token paid one order");
    assert_eq!(u64_at(&r.data("order").unwrap(), O_PAID), 0);
}

/// RefundOrder: refused before the deadline (E_STATE); after it the amount and the fee go back whole to the Balance
/// they came from and the order is gone.
#[test]
fn refund_order_after_the_deadline() {
    let mut r = Replay::load("double_pay");
    assert_eq!(r.to("refund_early"), Answer::Refused { ix: 1, code: E_STATE });
    let deadline = i64_at(&r.data("order").unwrap(), O_DEADLINE);
    assert!(r.now() <= deadline);
    assert_eq!(r.to("refund_order"), Answer::Accepted);
    assert!(r.now() > deadline);
    assert_eq!((r.tokens("balance_tok"), r.tokens("order_tok"), r.data("order")), (BALANCE - 100 * USDC - FEE_100, 0, None));
    assert_eq!((r.tokens("dest"), r.tokens("fee")), (100 * USDC, FEE_100 - TIP), "the first order's payment stands, and no second fee was taken");
    r.finish();
}

/// Cancel: only the funding wallet (E_ACCOUNTS for another signer), once (E_STATE the second time). The order stays
/// open with its money, takes a proof for NOTICE more and no longer.
#[test]
fn cancel() {
    let mut r = Replay::load("order_fees");
    assert_eq!(r.to("cancel_by_stranger"), Answer::Refused { ix: 1, code: E_ACCOUNTS });
    assert_eq!(i64_at(&r.data("order_100").unwrap(), O_CANCEL_AT), 0);
    assert_eq!(r.to("cancel"), Answer::Accepted);
    let o = r.data("order_100").unwrap();
    assert_eq!((o[O_STATE], i64_at(&o, O_CANCEL_AT), i64_at(&o, O_DEADLINE)), (OPEN, r.now(), r.now() + NOTICE));
    assert_eq!(r.tokens("order_tok_100"), 100 * USDC + FEE_100);
    assert_eq!(r.to("cancel_again"), Answer::Refused { ix: 1, code: E_STATE });
    r.finish();
}

/// What FundOrderWallet escrows on top of the amount is `order_fee`, at each edge of the tiers: 2.5% of the first
/// 1,000, 1% from there to 50,000, 0.5% above. Three ways: the literal, the function, and what the program moved.
#[test]
fn the_fee_is_order_fee_at_the_edges_of_the_tiers() {
    let mut r = Replay::load("order_fees");
    let mut left = FUNDER;
    for (units, fee) in [(100u64, 2_500_000u64), (1_000, 25_000_000), (1_001, 25_010_000), (50_000, 515_000_000), (50_001, 515_005_000)] {
        let amount = units * USDC;
        assert_eq!(order_fee(amount, FEE_BPS, 6), fee, "order_fee({units})");
        assert_eq!(r.to(&format!("fund_{units}")), Answer::Accepted);
        let o = r.data(&format!("order_{units}")).unwrap();
        assert_eq!((u64_at(&o, O_AMOUNT), u64_at(&o, O_FEE)), (amount, fee), "the order of {units}");
        assert_eq!(r.tokens(&format!("order_tok_{units}")), amount + fee, "escrowed for {units}");
        left -= amount + fee;
        assert_eq!(r.tokens("funder_tok"), left, "the funder after {units}");
    }
}
