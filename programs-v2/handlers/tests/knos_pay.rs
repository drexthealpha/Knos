//! knos_pay's instruction handlers, run from Rust: the test builds (tests/fixtures/knos_pay_v2_test.so beside
//! knos_oidc_v2_test.so) in LiteSVM, sent the transactions of programs-v2/testdata/{pay_order,double_pay,order_fees,order_plan,job_fee}.json
//! (see ../../testdata/harness.rs). Amounts are in millionths of test USDC.
#[path = "../../testdata/harness.rs"]
mod harness;
use harness::{i64_at, u64_at, Answer, Replay};
use knos_pay::order_terms::NOTICE;
use knos_pay::state::{O_AMOUNT, O_CANCEL_AT, O_DEADLINE, O_FEE, O_FEE_BPS, O_PAID, O_STATE, OPEN, P_BPS, U_AFTER};
use knos_pay::{fee_of, order_fee, E_ACCOUNTS, E_ORDER, E_PLAN, E_REPLAY, E_STATE, FEE_BPS, TIP};

const USDC: u64 = 1_000_000;
const FUNDER: u64 = 1_000_000 * USDC; // what the funding wallet starts with
const BALANCE: u64 = 100_000 * USDC; // what the repository owner's Balance starts with
const FEE_100: u64 = 300_000; // 0.30% of 100.00

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

/// What FundOrderWallet escrows on top of the amount is `order_fee`: 0.30% with a floor of 0.05, one rate, no tiers.
/// The price book's examples (5.00 -> 0.05, 100.00 -> 0.30, 1,000.00 -> 3.00, 5,000.00 -> 15.00, 100,000.00 ->
/// 300.00) and the two amounts either side of the floor. Three ways: the literal, the function, and what the program moved.
#[test]
fn the_fee_is_thirty_basis_points_with_a_floor_of_five_cents_at_every_size() {
    let mut r = Replay::load("order_fees");
    let mut left = FUNDER;
    for (units, fee) in [(5u64, 50_000u64), (16, 50_000), (17, 51_000), (100, 300_000), (1_000, 3_000_000), (5_000, 15_000_000), (100_000, 300_000_000)] {
        let amount = units * USDC;
        assert_eq!(order_fee(amount, FEE_BPS, 6), fee, "order_fee({units})");
        assert_eq!(r.to(&format!("fund_{units}")), Answer::Accepted);
        let o = r.data(&format!("order_{units}")).unwrap();
        assert_eq!((u64_at(&o, O_AMOUNT), u64_at(&o, O_FEE), u16::from_le_bytes([o[O_FEE_BPS], o[O_FEE_BPS + 1]])), (amount, fee, 30), "the order of {units}");
        assert_eq!(r.tokens(&format!("order_tok_{units}")), amount + fee, "escrowed for {units}");
        left -= amount + fee;
        assert_eq!(r.tokens("funder_tok"), left, "the funder after {units}");
    }
}

/// A Plan lowers the rate to no less than 10 basis points and no more than the standard 30: 9 and 31 are refused
/// (E_PLAN), 10 is set, and 1,000.00 funded from the owner's Balance then escrows 1.00 on top.
#[test]
fn a_plan_lowers_the_rate_to_no_less_than_ten_basis_points() {
    let mut r = Replay::load("order_plan");
    assert_eq!(r.to("plan_of_9"), Answer::Refused { ix: 1, code: E_PLAN });
    assert_eq!(r.to("plan_of_31"), Answer::Refused { ix: 1, code: E_PLAN });
    assert_eq!(r.data("plan"), None);
    assert_eq!(r.to("plan_of_10"), Answer::Accepted);
    let p = r.data("plan").unwrap();
    assert_eq!(u16::from_le_bytes([p[P_BPS], p[P_BPS + 1]]), 10);
    assert_eq!(r.to("fund_under_the_plan"), Answer::Accepted);
    let o = r.data("order").unwrap();
    assert_eq!((u64_at(&o, O_AMOUNT), u64_at(&o, O_FEE), u16::from_le_bytes([o[O_FEE_BPS], o[O_FEE_BPS + 1]])), (1_000 * USDC, USDC, 10));
    assert_eq!((r.tokens("order_tok"), r.tokens("balance_tok")), (1_001 * USDC, BALANCE - 1_001 * USDC));
    r.finish();
}

/// Jobs (2.0) pay the same rate, out of their amount: 1.00 pays the floor (0.05), 100.00 pays 0.30, 5,000.00 pays
/// 15.00; the payee gets the rest and the funder paid the amount and nothing on top.
#[test]
fn a_job_pays_the_same_rate_out_of_its_amount() {
    let mut r = Replay::load("job_fee");
    let (mut dest, mut fees, mut left) = (0, 0, FUNDER);
    for (units, fee) in [(1u64, 50_000u64), (100, 300_000), (5_000, 15_000_000)] {
        let amount = units * USDC;
        assert_eq!(fee_of(amount, 6), fee, "fee_of({units})");
        assert_eq!(r.to(&format!("fund_{units}")), Answer::Accepted);
        assert_eq!(r.to(&format!("pay_{units}")), Answer::Accepted);
        (dest, fees, left) = (dest + amount - fee, fees + fee, left - amount);
        assert_eq!((r.tokens("dest"), r.tokens("fee"), r.tokens("funder_tok")), (dest, fees, left), "the job of {units}");
    }
    r.finish();
}
