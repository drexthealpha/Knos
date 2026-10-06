//! What an opponent would try against knos_pay and knos_meter, run from Rust: the test builds in LiteSVM, sent the
//! transactions of programs-v2/testdata/adv_*.json (written by scripts/adversarial_vectors.py; replayed by
//! ../../testdata/harness.rs, which holds every answer to the recorded one). Amounts are millionths of test USDC.
//!
//!   1. accounts closed and made again at the same address      adv_reopen
//!   2. the second before, at, and after every time limit        adv_deadline, adv_hold, adv_warranty
//!   3. a payment and a refund sent together, and one after the other, in both orders   adv_deadline, adv_hold
//!   4. one token sent twice                                     adv_duplicates, adv_meter_duplicates
//!   5. one judge where an order asks for two or three           adv_quorum
//!
//! Two tests are `#[ignore]`d: each says what the program should do and fails on what it does today
//! (`cargo test --release --test adversarial -- --ignored` shows both failing). They wait for a decision about the
//! program; nothing in the program was changed for them.
#[path = "../../testdata/harness.rs"]
mod harness;
use harness::{i64_at, u64_at, Answer, Replay};
use knos_pay::state::{HELD, OPEN, O_AMOUNT, O_DEADLINE, O_HOLD_UNTIL, O_PAID, O_STATE, U_AFTER, WARRANTY};
use knos_pay::{order_fee, E_AUD, E_ORDER, E_REPLAY, E_STATE, E_TOKEN, FEE_BPS, TIP};

const USDC: u64 = 1_000_000;
const AMOUNT: u64 = 20 * USDC; // every order here
const FEE: u64 = 500_000; // 2.5% of 20.00
const HELD_BY_ORDER: u64 = AMOUNT + FEE;

const fn refused(ix: u8, code: u32) -> Answer { Answer::Refused { ix, code } }

/// Every unit in the named token accounts, together: what must not change whatever is sent.
fn all(r: &Replay, names: &[&str]) -> u64 { names.iter().map(|n| r.tokens(n)).sum() }

#[test]
fn the_fee_of_these_orders_is_what_the_literals_say() {
    assert_eq!(order_fee(AMOUNT, FEE_BPS, 6), FEE);
}

// == 1. accounts closed and made again at the same address ==============================================================

/// A paid order's address is funded again. The marker of the token that paid cannot be closed while that token could
/// still be shown (not early, and not in the last second of its time); the token is refused by the marker (E_REPLAY)
/// while it stands, and by its own age (E_TOKEN) once the marker is closed: the second order keeps every unit.
#[test]
fn a_used_marker_cannot_be_reset_and_its_token_never_pays_the_order_funded_again_at_the_address() {
    let mut r = Replay::load("adv_reopen");
    assert_eq!(r.to("pay"), Answer::Accepted);
    assert_eq!((r.tokens("dest"), r.data("paid"), r.tokens("paid_tok")), (AMOUNT, None, 0));
    let after = i64_at(&r.data("used").expect("the marker of the token that paid"), U_AFTER);
    assert_eq!(r.to("close_marker_early"), refused(1, E_STATE));
    assert!(r.now() < after && r.data("used").is_some());
    assert_eq!(r.to("old_token_while_its_marker_stands"), refused(1, E_REPLAY));
    assert_eq!((r.tokens("paid_tok"), r.tokens("dest")), (HELD_BY_ORDER, AMOUNT), "the order funded again is whole");
    assert_eq!(r.to("close_marker_at_its_time"), refused(1, E_STATE));
    assert_eq!(r.now(), after, "the last second of the marker's time is inside it");
    assert_eq!(r.to("close_marker"), Answer::Accepted);
    assert_eq!((r.now(), r.data("used")), (after + 1, None));
    assert_eq!(r.to("old_token_after_its_marker_closed"), refused(1, E_TOKEN));
    let o = r.data("paid").expect("the second order");
    assert_eq!((o[O_STATE], u64_at(&o, O_AMOUNT), u64_at(&o, O_PAID)), (OPEN, AMOUNT, 0));
    assert_eq!((r.tokens("paid_tok"), r.tokens("dest"), r.tokens("fee"), r.tokens("relayer_tok")), (HELD_BY_ORDER, AMOUNT, FEE - TIP, TIP), "one token paid one order");
}

/// A refunded order's address is funded again. A token signed for the first order and never used does not pay the
/// second (it was issued before the second existed: E_STATE); a new token pays it, once.
#[test]
fn a_token_of_a_refunded_order_does_not_pay_the_order_funded_again_at_its_address() {
    let mut r = Replay::load("adv_reopen");
    r.to("old_token_after_its_marker_closed");
    let (funder, dest) = (r.tokens("funder_tok"), r.tokens("dest"));
    assert_eq!(r.to("refund"), Answer::Accepted);
    assert_eq!((r.data("refunded"), r.tokens("refunded_tok")), (None, 0));
    assert_eq!(r.to("unused_token_of_the_refunded_order"), refused(1, E_STATE));
    assert_eq!((r.tokens("refunded_tok"), r.tokens("dest"), r.tokens("funder_tok")), (HELD_BY_ORDER, dest, funder - HELD_BY_ORDER));
    assert_eq!(u64_at(&r.data("refunded").unwrap(), O_PAID), 0);
    assert_eq!(r.to("new_token_pays_the_new_order"), Answer::Accepted);
    assert_eq!((r.tokens("dest"), r.data("refunded")), (dest + AMOUNT, None));
    assert_eq!(r.to("new_token_again"), refused(1, E_ORDER));
    assert_eq!((r.tokens("dest"), r.tokens("funder_tok")), (dest + AMOUNT, funder - HELD_BY_ORDER));
    r.finish();
}

// == 2 and 3. the time limits, and a payment and a refund together =======================================================

const DEADLINE: [&str; 9] = ["before_tok", "at_tok", "after_tok", "auto_at_tok", "auto_after_tok", "dest", "fee", "relayer_tok", "funder_tok"];

/// Three orders whose deadlines are one second apart, tried in one second of the chain's clock. A second before the
/// deadline and at it: a refund is refused and a proof pays. A second after: a proof is refused and the refund goes
/// through. No order both pays and refunds, and the units in all the accounts together never change.
#[test]
fn at_the_deadline_a_proof_still_pays_and_a_second_later_only_a_refund_does() {
    let mut r = Replay::load("adv_deadline");
    assert_eq!(r.to("refund_one_second_before"), refused(1, E_STATE));
    let (now, total, funder) = (r.now(), all(&r, &DEADLINE), r.tokens("funder_tok"));
    let deadline = |r: &Replay, name: &str| i64_at(&r.data(name).unwrap(), O_DEADLINE);
    assert_eq!((deadline(&r, "before"), deadline(&r, "at"), deadline(&r, "after")), (now + 1, now, now - 1));
    assert_eq!(r.to("pay_one_second_before"), Answer::Accepted);
    assert_eq!((r.tokens("dest"), r.data("before")), (AMOUNT, None));
    assert_eq!(r.to("refund_at_the_deadline"), refused(1, E_STATE));
    assert_eq!(r.to("pay_at_the_deadline"), Answer::Accepted);
    assert_eq!((r.tokens("dest"), r.data("at"), r.tokens("funder_tok")), (2 * AMOUNT, None, funder));
    assert_eq!(r.to("refund_after_the_payment"), refused(1, E_ORDER));
    assert_eq!(r.to("pay_one_second_after"), refused(1, E_STATE));
    assert_eq!((r.tokens("after_tok"), r.tokens("dest")), (HELD_BY_ORDER, 2 * AMOUNT));
    assert_eq!(r.to("refund_one_second_after"), Answer::Accepted);
    assert_eq!((r.tokens("funder_tok"), r.data("after"), r.tokens("dest")), (funder + HELD_BY_ORDER, None, 2 * AMOUNT));
    assert_eq!(r.to("pay_after_the_refund"), refused(1, E_ORDER));
    assert_eq!((r.tokens("dest"), r.tokens("fee"), r.tokens("relayer_tok")), (2 * AMOUNT, 2 * (FEE - TIP), 2 * TIP));
    assert_eq!((r.now(), all(&r, &DEADLINE)), (now, total), "one second, and not a unit made or lost");
}

/// PayOrder and RefundOrder for one order in ONE transaction, in both orders, at the deadline and a second after:
/// refused whole each time (the second instruction finds the order gone, or the first is out of its time), and the
/// order holds what it held.
#[test]
fn a_payment_and_a_refund_of_one_order_in_one_transaction_are_refused_whole_in_either_order() {
    let mut r = Replay::load("adv_deadline");
    r.to("refund_at_the_deadline");
    let (total, dest, funder) = (all(&r, &DEADLINE), r.tokens("dest"), r.tokens("funder_tok"));
    assert_eq!(r.to("pay_and_refund_at_the_deadline"), refused(2, E_ORDER));
    assert_eq!(r.to("refund_and_pay_at_the_deadline"), refused(1, E_STATE));
    let o = r.data("at").unwrap();
    assert_eq!((o[O_STATE], u64_at(&o, O_PAID), r.tokens("at_tok"), r.tokens("dest"), r.tokens("funder_tok")), (OPEN, 0, HELD_BY_ORDER, dest, funder));
    r.to("pay_one_second_after");
    let (dest, funder) = (r.tokens("dest"), r.tokens("funder_tok"));
    assert_eq!(r.to("pay_and_refund_one_second_after"), refused(1, E_STATE));
    assert_eq!(r.to("refund_and_pay_one_second_after"), refused(2, E_ORDER));
    assert_eq!((r.tokens("after_tok"), r.tokens("dest"), r.tokens("funder_tok"), all(&r, &DEADLINE)), (HELD_BY_ORDER, dest, funder, total));
}

/// An AUTO order (the first passing pull request is paid unmerged): its token pays at the deadline; a second after
/// it is refused and the order goes back to its funder.
#[test]
fn an_auto_order_is_paid_at_its_deadline_and_refunded_a_second_after() {
    let mut r = Replay::load("adv_deadline");
    r.to("pay_after_the_refund");
    let (now, total, dest, funder) = (r.now(), all(&r, &DEADLINE), r.tokens("dest"), r.tokens("funder_tok"));
    assert_eq!((i64_at(&r.data("auto_at").unwrap(), O_DEADLINE), i64_at(&r.data("auto_after").unwrap(), O_DEADLINE)), (now, now - 1));
    assert_eq!(r.to("auto_at_the_deadline"), Answer::Accepted);
    assert_eq!((r.tokens("dest"), r.data("auto_at")), (dest + AMOUNT, None));
    assert_eq!(r.to("auto_one_second_after"), refused(1, E_STATE));
    assert_eq!((r.tokens("dest"), r.tokens("auto_after_tok")), (dest + AMOUNT, HELD_BY_ORDER));
    assert_eq!(r.to("refund_auto_one_second_after"), Answer::Accepted);
    assert_eq!((r.tokens("funder_tok"), r.tokens("dest"), all(&r, &DEADLINE)), (funder + HELD_BY_ORDER, dest + AMOUNT, total));
    r.finish();
}

const HOLD: [&str; 7] = ["before_tok", "at_tok", "after_tok", "dest", "fee", "relayer_tok", "funder_tok"];

/// Three orders held for a payee who had no wallet, whose holds end one second apart; the payee has bound one. A
/// second before the hold ends and at it: SettleOrder pays, a refund is refused. A second after: the reverse.
#[test]
fn a_held_order_is_settled_until_its_hold_ends_and_refunded_only_after() {
    let mut r = Replay::load("adv_hold");
    assert_eq!(r.to("refund_one_second_before"), refused(1, E_STATE));
    let (now, total, funder) = (r.now(), all(&r, &HOLD), r.tokens("funder_tok"));
    for (name, until) in [("before", now + 1), ("at", now), ("after", now - 1)] {
        let o = r.data(name).unwrap();
        assert_eq!((o[O_STATE], i64_at(&o, O_HOLD_UNTIL)), (HELD, until), "{name}");
    }
    assert_eq!(r.to("settle_one_second_before"), Answer::Accepted);
    assert_eq!(r.to("refund_at_the_end"), refused(1, E_STATE));
    assert_eq!(r.to("settle_at_the_end"), Answer::Accepted);
    assert_eq!((r.tokens("dest"), r.data("before"), r.data("at"), r.tokens("funder_tok")), (2 * AMOUNT, None, None, funder));
    assert_eq!(r.to("refund_after_the_settlement"), refused(1, E_ORDER));
    assert_eq!(r.to("settle_one_second_after"), refused(1, E_STATE));
    assert_eq!(r.to("refund_one_second_after"), Answer::Accepted);
    assert_eq!((r.tokens("funder_tok"), r.data("after")), (funder + HELD_BY_ORDER, None));
    assert_eq!(r.to("settle_after_the_refund"), refused(1, E_ORDER));
    assert_eq!((r.tokens("dest"), r.tokens("fee"), r.tokens("relayer_tok")), (2 * AMOUNT, 2 * (FEE - TIP), 2 * TIP));
    assert_eq!((r.now(), all(&r, &HOLD)), (now, total));
    r.finish();
}

/// SettleOrder and RefundOrder for one held order. In one transaction, in both orders, at the end of the hold and a
/// second after: refused whole, and nothing moves. In two transactions, in both orders: exactly one is accepted
/// (the settlement up to the end of the hold, the refund after it), and the units in all accounts stay the same.
#[test]
fn settle_and_refund_sent_together_move_nothing_and_sent_apart_exactly_one_takes_effect() {
    let mut r = Replay::load("adv_hold");
    r.to("refund_at_the_end");
    let (total, dest, funder) = (all(&r, &HOLD), r.tokens("dest"), r.tokens("funder_tok"));
    // one transaction, at the end of the hold
    assert_eq!(r.to("settle_and_refund_at_the_end"), refused(2, E_ORDER));
    assert_eq!(r.to("refund_and_settle_at_the_end"), refused(1, E_STATE));
    assert_eq!((r.data("at").unwrap()[O_STATE], r.tokens("at_tok"), r.tokens("dest"), r.tokens("funder_tok")), (HELD, HELD_BY_ORDER, dest, funder));
    // two transactions: the refund came first and was refused (above, "refund_at_the_end"); the settlement pays; a refund after it finds nothing
    assert_eq!(r.to("settle_at_the_end"), Answer::Accepted);
    assert_eq!(r.to("refund_after_the_settlement"), refused(1, E_ORDER));
    assert_eq!((r.tokens("dest"), r.tokens("funder_tok"), all(&r, &HOLD)), (dest + AMOUNT, funder, total));
    // a second after the hold: the settlement comes first and is refused; together, refused whole; the refund pays; a settlement after it finds nothing
    assert_eq!(r.to("settle_one_second_after"), refused(1, E_STATE));
    assert_eq!(r.to("settle_and_refund_one_second_after"), refused(1, E_STATE));
    assert_eq!(r.to("refund_and_settle_one_second_after"), refused(2, E_ORDER));
    assert_eq!((r.data("after").unwrap()[O_STATE], r.tokens("after_tok"), r.tokens("funder_tok")), (HELD, HELD_BY_ORDER, funder));
    assert_eq!(r.to("refund_one_second_after"), Answer::Accepted);
    assert_eq!(r.to("settle_after_the_refund"), refused(1, E_ORDER));
    assert_eq!((r.tokens("dest"), r.tokens("funder_tok"), all(&r, &HOLD)), (dest + AMOUNT, funder + HELD_BY_ORDER, total));
}

const WARRANTY_ACCOUNTS: [&str; 6] = ["over_tok", "last_tok", "dest", "fee", "relayer_tok", "funder_tok"];

/// Two orders with a tenth held back, whose warranties end one second apart. In the last second of a warranty a
/// release is refused and a challenge (Revert) returns the holdback to the funder; a second after it the challenge
/// is refused and the holdback is released to the payee. Both together in one transaction: refused whole.
#[test]
fn a_holdback_is_challenged_until_its_warranty_ends_and_released_only_after() {
    const HOLDBACK: u64 = AMOUNT / 10; // and FEE / 10 of the fee with it
    let mut r = Replay::load("adv_warranty");
    assert_eq!(r.to("release_in_the_last_second"), refused(1, E_STATE));
    let (now, total, dest, funder, tip) = (r.now(), all(&r, &WARRANTY_ACCOUNTS), r.tokens("dest"), r.tokens("funder_tok"), r.tokens("relayer_tok"));
    for (name, until) in [("last", now), ("over", now - 1)] {
        let o = r.data(name).unwrap();
        assert_eq!((o[O_STATE], i64_at(&o, O_HOLD_UNTIL), r.tokens(&format!("{name}_tok"))), (WARRANTY, until, HOLDBACK + FEE / 10), "{name}");
    }
    assert_eq!(r.to("release_and_challenge_in_the_last_second"), refused(1, E_STATE));
    assert_eq!(r.to("challenge_one_second_after"), refused(1, E_STATE));
    assert_eq!(r.to("challenge_and_release_one_second_after"), refused(1, E_STATE));
    assert_eq!((r.tokens("dest"), r.tokens("funder_tok"), r.tokens("over_tok"), r.tokens("last_tok")), (dest, funder, HOLDBACK + FEE / 10, HOLDBACK + FEE / 10));
    assert_eq!(r.to("release_one_second_after"), Answer::Accepted);
    assert_eq!((r.tokens("dest"), r.tokens("relayer_tok"), r.tokens("funder_tok"), r.data("over")), (dest + HOLDBACK, tip + FEE / 10, funder, None));
    assert_eq!(r.to("challenge_after_the_release"), refused(1, E_ORDER));
    assert_eq!(r.to("challenge_in_the_last_second"), Answer::Accepted);
    assert_eq!((r.tokens("funder_tok"), r.tokens("dest"), r.data("last")), (funder + HOLDBACK + FEE / 10, dest + HOLDBACK, None));
    assert_eq!(r.to("release_after_the_challenge"), refused(1, E_ORDER));
    assert_eq!((r.now(), all(&r, &WARRANTY_ACCOUNTS)), (now, total));
    r.finish();
}

// == 4. one token, twice ================================================================================================

const DUPLICATES: [&str; 6] = ["once_tok", "standing_tok", "dest", "fee", "relayer_tok", "funder_tok"];

/// One pay token twice in one transaction: refused whole, nothing moves. Alone: it pays. Again in a second
/// transaction: refused. On an order that closes with its payment the second use finds no order (E_ORDER); on a
/// STANDING order, which stays open with money in it, the token's marker refuses it (E_REPLAY).
#[test]
fn one_pay_token_twice_in_one_transaction_or_in_two_pays_once() {
    const RATE: u64 = 6 * USDC; // what the standing order pays for one pull request
    let mut r = Replay::load("adv_duplicates");
    assert_eq!(r.to("twice_in_one_transaction"), refused(2, E_ORDER));
    let total = all(&r, &DUPLICATES);
    assert_eq!((r.tokens("dest"), r.tokens("once_tok"), r.tokens("fee"), r.tokens("relayer_tok")), (0, HELD_BY_ORDER, 0, 0));
    assert_eq!(r.to("once"), Answer::Accepted);
    assert_eq!((r.tokens("dest"), r.tokens("once_tok"), r.data("once")), (AMOUNT, 0, None));
    assert_eq!(r.to("again_in_a_second_transaction"), refused(1, E_ORDER));
    assert_eq!(r.tokens("dest"), AMOUNT);
    assert_eq!(r.to("standing_twice_in_one_transaction"), refused(2, E_REPLAY));
    assert_eq!((r.tokens("dest"), r.tokens("standing_tok")), (AMOUNT, HELD_BY_ORDER));
    assert_eq!(r.to("standing_once"), Answer::Accepted);
    let fee_of_rate = FEE * 6 / 20;
    assert_eq!((r.tokens("dest"), r.tokens("standing_tok")), (AMOUNT + RATE, HELD_BY_ORDER - RATE - fee_of_rate));
    assert_eq!(r.to("standing_again_in_a_second_transaction"), refused(1, E_REPLAY));
    assert_eq!(r.data("standing").unwrap()[O_STATE], OPEN, "the order is still open: only the marker stood in the way");
    assert_eq!((r.tokens("dest"), r.tokens("standing_tok"), all(&r, &DUPLICATES)), (AMOUNT + RATE, HELD_BY_ORDER - RATE - fee_of_rate, total));
}

/// A token GitHub signed for the meter (a knosm:eval audience), from the pinned workflow in the order's own
/// repository, shown to PayOrder: refused by its audience (E_AUD); the open order keeps what it holds.
#[test]
fn a_token_signed_for_the_meter_does_not_pay_an_order() {
    let mut r = Replay::load("adv_duplicates");
    r.to("standing_again_in_a_second_transaction");
    let (total, dest, held) = (all(&r, &DUPLICATES), r.tokens("dest"), r.tokens("standing_tok"));
    assert_eq!(r.to("meter_token_to_pay_order"), refused(1, E_AUD));
    assert_eq!((r.tokens("dest"), r.tokens("standing_tok"), all(&r, &DUPLICATES)), (dest, held, total));
    r.finish();
}

/// knos_meter. One evaluation's token twice in one transaction, and again in a second: billed once, counted once.
/// A token signed for a payment (a knos3:pay audience) shown to Record: refused (the meter's E_AUD), nothing billed.
#[test]
fn one_evaluation_sent_twice_is_billed_once_and_a_pay_token_is_not_an_evaluation() {
    use knos_meter::state::{C_EVALS, C_SPENT, M_EVALS};
    const CREDITS: u64 = 1000 * USDC;
    let mut r = Replay::load("adv_meter_duplicates");
    let billed_once = |r: &Replay| {
        let (c, m) = (r.data("credits").unwrap(), r.data("month").unwrap());
        assert_eq!((r.tokens("credits_tok"), r.tokens("fee")), (CREDITS - knos_meter::FEE, knos_meter::FEE));
        assert_eq!((u64_at(&c, C_SPENT), u64_at(&c, C_EVALS), u64_at(&m, M_EVALS)), (knos_meter::FEE, 1, 1));
    };
    assert_eq!(r.to("twice_in_one_transaction"), Answer::Accepted);
    billed_once(&r);
    assert_eq!(r.to("again_in_a_second_transaction"), Answer::Accepted);
    billed_once(&r);
    assert_eq!(r.to("pay_token_to_record"), refused(1, knos_meter::E_AUD));
    billed_once(&r);
    r.finish();
}

// == 5. one judge where two or three are asked ===========================================================================

const QUORUM: [&str; 6] = ["two_tok", "three_tok", "dest", "fee", "relayer_tok", "funder_tok"];

/// A quorum of 2. The first judge's valid token is accepted and moves nothing; so does a second token of the same
/// judge, and a third started by another account in the same repository: one judge is one judge. A second judge's
/// token for the same work pays.
#[test]
fn under_a_quorum_of_two_one_judge_moves_nothing_however_many_tokens_it_signs() {
    let mut r = Replay::load("adv_quorum");
    for label in ["two_first_judge", "two_first_judge_again", "two_first_judge_a_third_time"] {
        assert_eq!(r.to(label), Answer::Accepted, "{label}");
        let o = r.data("two").unwrap();
        assert_eq!((o[O_STATE], u64_at(&o, O_PAID), r.tokens("two_tok"), r.tokens("dest"), r.tokens("fee"), r.tokens("relayer_tok")), (OPEN, 0, HELD_BY_ORDER, 0, 0, 0), "{label}");
    }
    let total = all(&r, &QUORUM);
    assert_eq!(r.to("two_second_judge"), Answer::Accepted);
    assert_eq!((r.tokens("dest"), r.tokens("two_tok"), r.data("two"), all(&r, &QUORUM)), (AMOUNT, 0, None, total));
}

/// A quorum of 3. Two distinct judges, and more tokens from each of them, move nothing; the third judge's pays.
#[test]
fn under_a_quorum_of_three_two_judges_move_nothing() {
    let mut r = Replay::load("adv_quorum");
    r.to("two_second_judge");
    let (total, dest) = (all(&r, &QUORUM), r.tokens("dest"));
    for label in ["three_first_judge", "three_second_judge", "three_second_judge_again", "three_first_judge_again"] {
        assert_eq!(r.to(label), Answer::Accepted, "{label}");
        let o = r.data("three").unwrap();
        assert_eq!((o[O_STATE], u64_at(&o, O_PAID), r.tokens("three_tok"), r.tokens("dest")), (OPEN, 0, HELD_BY_ORDER, dest), "{label}");
    }
    assert_eq!(r.to("three_third_judge"), Answer::Accepted);
    assert_eq!((r.tokens("dest"), r.tokens("three_tok"), r.data("three"), all(&r, &QUORUM)), (dest + AMOUNT, 0, None, total));
    r.finish();
}

// == findings: what the program does today is recorded; what it should do is asserted, so these fail until it changes ====

/// FINDING 1. A wallet's order with a quorum of 2. One GitHub account starts the run in the order's repository
/// (judge a) and then, by hand, the neutral run in another repository it owns (judge b). The program counts two
/// judges and pays: order_terms::quorum tells judges apart by where a run was, and refuses a neutral run by the
/// funder or the owner only on a Balance's order (`o.kind == 1`); a wallet's order has no funder id to compare.
/// What this test asks for: two tokens whose `actor_id` is the same are one judge, and nothing is paid.
#[test]
#[ignore = "FINDING 1: fails on the program as built; kept for the decision about order_terms::quorum"]
fn finding_one_account_that_starts_both_runs_is_one_judge_not_two() {
    let mut r = Replay::load("adv_quorum_same_account");
    assert_eq!(r.to("own_run_started_by_the_account"), Answer::Accepted);
    assert_eq!((r.tokens("dest"), r.tokens("order_tok")), (0, HELD_BY_ORDER));
    r.to("neutral_run_started_by_the_same_account");
    assert_eq!((r.tokens("dest"), r.tokens("order_tok")), (0, HELD_BY_ORDER), "the same account's second run paid a quorum of 2");
}

/// FINDING 2. An order with a quorum of 2 is paid by its two judges, and its address is funded again while the
/// chain's clock still shows the second the first order was funded in. The first judge's marker of the FIRST order
/// is still there, and order_terms::said takes it for the second order's: it compares the marker's `since` with
/// the order's `not_before`, which are the same second. The second judge's new token, alone, then pays the second
/// order. What this test asks for: one judge's token moves nothing on the order funded again.
#[test]
#[ignore = "FINDING 2: fails on the program as built; kept for the decision about order_terms::said"]
fn finding_a_marker_of_the_order_before_does_not_count_for_one_funded_again_in_the_same_second() {
    let mut r = Replay::load("adv_quorum_same_second");
    assert_eq!(r.to("fund_again_in_the_same_second"), Answer::Accepted);
    let dest = r.tokens("dest");
    assert_eq!((dest, r.tokens("order_tok")), (AMOUNT, HELD_BY_ORDER));
    r.to("one_judge_alone");
    assert_eq!((r.tokens("dest"), r.tokens("order_tok")), (dest, HELD_BY_ORDER), "one judge alone paid a quorum of 2");
}
