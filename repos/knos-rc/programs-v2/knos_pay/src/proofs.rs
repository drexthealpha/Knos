//! The arithmetic of an order's money: nothing is created and nothing is lost. Not compiled into the program: this
//! file exists only under cfg(kani) and cfg(test). `cargo kani` proves the harnesses below with the Kani model checker,
//! and `cargo test` runs the same properties, and the two that Kani is not given, on inputs made at random from fixed
//! seeds.
//!
//! WHAT IS PROVED by `cargo kani` (a mint of 6 decimals, USDC's):
//!   - order_fee is at least FEE_MIN and at most the larger of that floor and 0.30% of the amount, for every u64
//!     amount and every rate a Plan can set (10 to 30 basis points), without overflow; the amount and the fee of an order the program takes add up
//!     in a u64; a job's fee (2.0) is never more than its amount (one harness over every u64 amount and every rate:
//!     docs/kani.json records whether the solver answered it, and what is proved of the same bounds rate by rate);
//!   - the part of a payee's share that comes from the last four digits of an amount is never more than those digits;
//!   - an order paid in one payment, for every amount the program takes (5.00 to 100,000.00) and every rate: the
//!     amount and order_fee of it, which the funder put in, are exactly what the payees, the relayer's tip and
//!     FEE_OWNER take out, the tip is a whole TIP or TIP_FIRST or, when the fee is smaller, the whole fee, and nothing is left;
//!   - an order that has paid nothing has given out none of its fee (amounts and fees below 2^32);
//!   - the bookkeeping of a payment, for EVERY u64 amount, fee, paid and payment: the tip and what FEE_OWNER takes
//!     are together exactly the fee of that payment; no subtraction wraps; an account that held what is left of the
//!     amount and of the fee before the payment holds exactly what is left of both after it, and nothing after the
//!     last one.
//!
//! WHAT IS ASSUMED by that last harness, and tested here at random instead: two facts about a product rounded down.
//!   1. The fee an order has given out, fee * paid / amount rounded down, grows with `paid` and is the whole fee once
//!      paid == amount (`kani::assume` in the harness).
//!   2. The shares of all payees but the last, each `bps_of(due, bps)` rounded down, are together never more than
//!      `due` when the basis points add up to 10000: so the last payee's share, `due - sent`, exists, and with it the
//!      shares are `due` exactly (no harness: `split` is not in the one above).
//!
//! Both are a multiplication of two unknowns followed by a division, which a SAT solver handles badly. Tried when
//! this file was written, with Kani 0.68.0 (CBMC 6.11.0), amounts drawn in 32 bits and held to the limits: a harness
//! for each ran 15 minutes under CaDiCaL without an answer; the one-share form of the second (bps_of(x, b) <= x) ran
//! 200 seconds under CaDiCaL and 150 under Kissat and under z3 without one. Tried once more for 0.3.13, the same
//! Kani, each property cut down as far as it still says something: (1) with the amount, the fee and both values of
//! `paid` drawn in 8 bits (fee_at is the source's, so its division is still 128 bits wide with an unknown divisor):
//! no answer in 4 minutes of solving; (2) `split` itself with the payment drawn in 16 bits (every remainder 0..=9999
//! is in it), 1 to 4 payees and an unwinding limit of 6: no answer in 5 minutes. So they are not harnesses: a nightly
//! job that cannot finish proves nothing, and both stay randomised tests (`the_payees_shares_add_up_to_the_payment`,
//! `the_fee_an_order_has_given_out_grows_with_what_it_paid_and_ends_at_the_whole_fee`), which every push runs. In
//! words: rounding down never adds, a sum of rounded-down parts is at most the rounded-down whole, and
//! x * b / 10000 is at most x when b is at most 10000.
//!
//! WHAT IS NOT covered here. The accounts, the token program and the instruction code around this arithmetic: the
//! tests in tests/test_order_*.py and the random walk of tests/test_pay2_chain.py run those. A standing order's
//! rewriting of itself (order_terms::after_pay) is in the randomised tests only. So are mints of other decimals (the
//! fee: 0 to 18; an order's life: 0, 2, 8 and 9 beside 6).
//!
//! THE MODEL IS THE SOURCE'S. order_pay::pay_out does this arithmetic between transfers, so it cannot be called here:
//! `pay`, `split`, `settle` and `fee_at` below are its arithmetic, line for line, and the test
//! `the_model_is_the_arithmetic_of_the_source` fails when one of those lines of order_pay.rs or order_terms.rs
//! changes. order_fee, bps_of and units are the program's own functions.
#![cfg_attr(kani, allow(dead_code))] // the harnesses use part of the model; the tests use all of it
use crate::{bps_of, order_fee, state::units, MAX_PAYEES, TIP, TIP_FIRST};

/// What one payment takes out of an order's account, and where the order stands after it.
#[derive(Debug, PartialEq, Eq)]
pub struct Payment {
    pub shares: [u64; MAX_PAYEES], // to each payee, in the payees' order
    pub tip: u64,                  // to the relayer
    pub rest: u64,                 // to FEE_OWNER
    pub paid: u64,                 // the order's `paid` after it
    pub last: bool,                // the order is closed
}

/// The shares of `due` among payees with these basis points: each rounded down, the last one what rounding left.
/// order_pay::pay_out (a payment) and order_terms::after_pay (the parts of a holdback) both split this way.
pub fn split(due: u64, bps: &[u64]) -> [u64; MAX_PAYEES] {
    let (mut shares, mut sent) = ([0u64; MAX_PAYEES], 0u64);
    for (k, b) in bps.iter().enumerate() {
        let share = if k + 1 == bps.len() { due - sent } else { bps_of(due, *b) };
        sent += share;
        shares[k] = share;
    }
    shares
}

/// The fee an order has given out once `paid` of its `amount` was paid: the paid share of it, rounded down.
pub fn fee_at(fee: u64, paid: u64, amount: u64) -> u64 { (fee as u128 * paid as u128 / amount as u128) as u64 }

/// order_pay::pay_out's arithmetic: an order of `amount` and `fee`, of which `paid_before` was paid, pays `due` to
/// payees with these shares. `held`: what its token account holds. `created`: a payee's token account was created
/// in this transaction (the larger tip). None where the program refuses (nothing to pay, or more than is left).
#[allow(clippy::too_many_arguments)]
pub fn pay(amount: u64, fee: u64, paid_before: u64, due: u64, bps: &[u64], held: u64, created: bool, decimals: u8) -> Option<Payment> {
    let paid = paid_before.checked_add(due).filter(|p| due > 0 && *p <= amount)?;
    let last = paid == amount;
    let shares = split(due, bps);
    let (tip, rest) = settle(fee, fee_at(fee, paid_before, amount), fee_at(fee, paid, amount), last, due, held, created, decimals);
    Some(Payment { shares, tip, rest, paid, last })
}

/// The fee of one payment, as (the relayer's tip, what FEE_OWNER takes): `fee_before` and `fee_after` are what the
/// order's fee has given out before this payment and with it (fee_at of the old and of the new `paid`).
#[allow(clippy::too_many_arguments)]
pub fn settle(fee: u64, fee_before: u64, fee_after: u64, last: bool, due: u64, held: u64, created: bool, decimals: u8) -> (u64, u64) {
    let fee_now = if last { fee - fee_before } else { fee_after - fee_before };
    let tip = units(if created { TIP_FIRST } else { TIP }, decimals).min(fee_now);
    // with the last payment FEE_OWNER takes everything the account still holds
    let rest = if last { held - due - tip } else { fee_now - tip };
    (tip, rest)
}

/// What an order's account holds when nothing but the program's own transfers touched it.
pub fn holds(amount: u64, fee: u64, paid: u64) -> u64 { (amount - paid) + (fee - fee_at(fee, paid, amount)) }

/// The property of one payment, as a predicate both Kani and the randomised test assert: the shares are the payment,
/// the fee of the payment is within what is left of the fee, and the account goes from `holds(paid_before)` to
/// `holds(paid)`: to nothing when the order is closed. Sums are in u128, so nothing here can wrap.
pub fn conserved(amount: u64, fee: u64, paid_before: u64, due: u64, n: usize, p: &Payment) -> bool {
    let sent: u128 = p.shares.iter().map(|s| *s as u128).sum();
    let out = sent + p.tip as u128 + p.rest as u128;
    let (before, after) = (holds(amount, fee, paid_before) as u128, holds(amount, fee, p.paid) as u128);
    sent == due as u128
        && p.shares.iter().all(|s| *s <= due) && p.shares[n..].iter().all(|s| *s == 0)
        && p.paid == paid_before + due && p.last == (p.paid == amount)
        && fee_at(fee, paid_before, amount) <= fee_at(fee, p.paid, amount) && fee_at(fee, p.paid, amount) <= fee
        && before == after + out
        && (!p.last || after == 0)
}

#[cfg(kani)]
mod harness {
    use super::*;
    use crate::{fee_of, FEE_BPS, FEE_MIN, MAX_AMOUNT, ORDER_MIN_AMOUNT, PLAN_BPS_MIN};

    const DECIMALS: u8 = 6;

    /// The part of a share that comes from the last four digits of an amount: never more than those digits.
    #[kani::proof]
    fn the_remainder_of_a_share_is_never_more_than_the_remainder() {
        let (r, b): (u16, u16) = (kani::any(), kani::any());
        kani::assume(r < 10_000 && b <= 10_000);
        assert!(bps_of(r as u64, b as u64) <= r as u64);
        if b == 10_000 { assert!(bps_of(r as u64, b as u64) == r as u64); }
    }

    #[kani::proof]
    #[kani::unwind(8)]
    fn an_orders_fee_is_between_its_floor_and_the_one_rate_for_every_amount() {
        let (amount, bps): (u64, u8) = (kani::any(), kani::any());
        kani::assume(bps as u64 >= PLAN_BPS_MIN && bps as u64 <= FEE_BPS);
        let fee = order_fee(amount, bps as u64, DECIMALS);
        // one rate, and no Plan's is above it: the fee is never above 0.30% of the amount (or the floor)
        assert!(fee >= units(FEE_MIN, DECIMALS) && fee <= bps_of(amount, FEE_BPS).max(units(FEE_MIN, DECIMALS)));
        // what the funder puts in is the amount and the fee, and for an amount the program takes that sum exists
        if amount <= units(MAX_AMOUNT, DECIMALS) { assert!(amount.checked_add(fee).is_some()); }
        // a job's fee (2.0) is taken out of the amount, so it is never more than it
        assert!(fee_of(amount, DECIMALS) <= amount);
    }

    /// The bookkeeping of a payment, for every u64: given what the order's fee had given out before the payment and
    /// has given out with it (any two values in order, within the fee; the whole fee when the order is paid up), the
    /// tip and what FEE_OWNER takes are exactly the fee of this payment, no subtraction wraps, and the account goes
    /// from what it held to what it must hold: to nothing with the last payment.
    #[kani::proof]
    #[kani::unwind(8)]
    fn a_payment_takes_its_share_of_the_amount_and_of_the_fee_and_the_last_one_empties_the_order() {
        let (amount, fee, paid_before, due, fee_before, fee_after): (u64, u64, u64, u64, u64, u64) =
            (kani::any(), kani::any(), kani::any(), kani::any(), kani::any(), kani::any());
        kani::assume(paid_before < amount && due >= 1 && due <= amount - paid_before);
        let paid = paid_before + due;
        let last = paid == amount;
        // what fee_at gives (ASSUMED here; see the module documentation): it grows with `paid`, and ends at the fee
        kani::assume(fee_before <= fee_after && fee_after <= fee && (!last || fee_after == fee));
        // the account holds what is left of the amount and of the fee: a balance, so it fits a u64
        let held = (amount - paid_before).checked_add(fee - fee_before);
        kani::assume(held.is_some());
        let held = held.unwrap();
        // with the smaller tip and with the larger (a payee's token account was created): each a constant to the solver
        for created in [false, true] {
            let (tip, rest) = settle(fee, fee_before, fee_after, last, due, held, created, DECIMALS);
            assert!(tip <= units(TIP_FIRST, DECIMALS) && tip as u128 + rest as u128 == (fee_after - fee_before) as u128);
            let after = (amount - paid) as u128 + (fee - fee_after) as u128;
            assert!(held as u128 == after + due as u128 + tip as u128 + rest as u128);
            if last { assert!(after == 0); }
        }
    }

    /// One order from its funding to its end in one payment, for every amount the program takes at 6 decimals
    /// (ORDER_MIN_AMOUNT to MAX_AMOUNT) and every rate a Plan can set: what the funder put in, the amount and
    /// order_fee of it, is exactly what the payees, the relayer and FEE_OWNER take out; the tip is the whole TIP or
    /// TIP_FIRST, or the whole fee when that is smaller, and comes out of the fee; nothing is left. The payees are one, or two of whom the second takes what
    /// the first left (`split`'s last share). Nothing of the fee was given out before (0 here; the next harness
    /// proves fee_at(fee, 0, amount) == 0).
    #[kani::proof]
    #[kani::unwind(8)]
    fn what_a_funder_puts_in_is_what_the_payees_the_relayer_and_the_fee_owner_take_out() {
        let (amount, bps, first): (u64, u8, u64) = (kani::any(), kani::any(), kani::any());
        kani::assume(amount >= units(ORDER_MIN_AMOUNT, DECIMALS) && amount <= units(MAX_AMOUNT, DECIMALS) && first <= amount);
        kani::assume(bps as u64 >= PLAN_BPS_MIN && bps as u64 <= FEE_BPS);
        let fee = order_fee(amount, bps as u64, DECIMALS);
        let held = amount + fee;                      // what FundOrderWallet and FundOrderBalance take
        let payees = first as u128 + (amount - first) as u128;
        for created in [false, true] {
            let (tip, rest) = settle(fee, 0, fee, true, amount, held, created, DECIMALS);
            assert!(tip == units(if created { TIP_FIRST } else { TIP }, DECIMALS).min(fee) && tip >= units(TIP, DECIMALS) && tip as u128 + rest as u128 == fee as u128);
            assert!(amount as u128 + fee as u128 == payees + tip as u128 + rest as u128);
            assert!(held - amount - tip - rest == 0);
        }
    }

    /// Where fee_at starts, for every amount and fee below 2^32 (the limits at 6 decimals are below it; a value drawn
    /// in 32 bits and widened has its upper bits fixed before the solver starts): nothing of the fee is given out
    /// before anything is paid.
    #[kani::proof]
    fn an_order_that_has_paid_nothing_has_given_out_none_of_its_fee() {
        let (amount, fee): (u32, u32) = (kani::any(), kani::any());
        kani::assume(amount >= 1);
        assert!(fee_at(fee as u64, 0, amount as u64) == 0);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{order::Order, order_terms::due_now, state::{F_STANDING, OPEN}, FEE_BPS, FEE_MIN, MAX_AMOUNT, MAX_HOLDBACK_BPS, ORDER_MIN_AMOUNT, PLAN_BPS_MIN};
    use solana_program::pubkey::Pubkey;

    /// xorshift64*: the same inputs on every run and every machine.
    struct Rng(u64);
    impl Rng {
        fn next(&mut self) -> u64 {
            self.0 ^= self.0 >> 12; self.0 ^= self.0 << 25; self.0 ^= self.0 >> 27;
            self.0.wrapping_mul(0x2545_F491_4F6C_DD1D)
        }
        /// a..=b, with the two ends and their neighbours drawn often
        fn within(&mut self, a: u64, b: u64) -> u64 {
            let span = (b - a).wrapping_add(1);     // 0: every u64
            match self.next() % 8 { 0 => a, 1 => b, 2 => a.saturating_add(1).min(b), 3 => b.saturating_sub(1).max(a), _ if span == 0 => self.next(), _ => a + self.next() % span }
        }
        /// 1..=4 shares of at least 1 that add up to 10000
        fn shares(&mut self) -> Vec<u64> {
            let n = 1 + (self.next() % MAX_PAYEES as u64) as usize;
            let mut cuts: Vec<u64> = (1..n).map(|_| self.within(1, 9_999)).collect();
            cuts.sort_unstable();
            cuts.dedup();
            cuts.push(10_000);
            let mut at = 0;
            cuts.iter().map(|c| { let s = c - at; at = *c; s }).collect()
        }
    }

    fn order(flags: u8, amount: u64, fee: u64, holdback_bps: u16, rate: u64, paid: u64) -> Order {
        let z = Pubkey::default();
        Order { state: OPEN, mode: 0, kind: 0, flags, decimals: 6, reserve_days: 0, repo: 1, issue: 1, scope: [0; 32], seq: 0, holdback_bps, kill_bps: 0,
                fee_bps: 30, amount, fee, rate, paid, deadline: 0, not_before: 0, hold_until: 0, warranty_s: 0, reserved_by: 0, reserved_until: 0,
                cancel_at: 0, payee: 0, funder_id: 0, owner_id: 0, arbiter_id: 0, judge_repo_id: 0, source: z, refund_to: z, rent_to: z, mint: z,
                terms: [0; 32], wf_repo: [0; 32], wf_sha: [0; 40], inc: 1, grace: false }
    }

    #[test]
    fn the_model_is_the_arithmetic_of_the_source() {
        let (paying, terms) = (include_str!("order_pay.rs"), include_str!("order_terms.rs"));
        for line in ["let paid = o.paid.checked_add(due).filter(|p| due > 0 && *p <= o.amount).ok_or_else(|| err(E_STATE))?;",
                     "let last = paid == o.amount;",
                     "let (mut created, mut sent) = (false, 0u64);",
                     "let share = if k + 1 == payees.len() { due - sent } else { bps_of(due, payee.bps) };",
                     "sent += share;",
                     "let fee_before = (o.fee as u128 * o.paid as u128 / o.amount as u128) as u64;",
                     "let fee = if last { o.fee - fee_before } else { (o.fee as u128 * paid as u128 / o.amount as u128) as u64 - fee_before };",
                     "let tip = units(if created { TIP_FIRST } else { TIP }, m.decimals).min(fee);",
                     "let rest = if last { amount_of(a.ov, a.token.key, E_ACCOUNTS)? } else { fee - tip };"] {
            assert_eq!(paying.matches(line).count(), 1, "order_pay.rs no longer has: {line}");
        }
        // the three transfers of a payment move the share, the tip and the rest, and nothing else is transferred there
        let pay_out = paying.split("fn pay_out<'a>(").nth(1).unwrap().split("\n}\n").next().unwrap();
        assert_eq!(pay_out.matches("transfer(").count(), 3);
        for moved in ["dest, a.auth, share,", "a.tip_tok, a.auth, tip,", "a.fee_tok, a.auth, rest,"] { assert!(pay_out.contains(moved), "{moved}"); }
        // a holdback: what a payment leaves in the order, and its parts among the payees
        for line in ["left - bps_of(left, o.holdback_bps as u64)",
                     "let part = if k + 1 == n { held - given } else { bps_of(held, p.bps) };",
                     "let tip = units(if created { TIP_FIRST } else { TIP }, m.decimals).min(left);",
                     "if left > tip { transfer(token, ov, mint, fee_tok, auth, left - tip, m.decimals, Some(bump))?; }"] {
            assert_eq!(terms.matches(line).count(), 1, "order_terms.rs no longer has: {line}");
        }
    }

    #[test]
    fn an_orders_fee_is_its_one_rate_above_its_floor_and_a_share_is_never_more_than_the_whole() {
        let mut r = Rng(0x6b6e_6f73_2d66_6565);
        for i in 0..400_000u32 {
            let decimals = (r.next() % 19) as u8;
            let amount = if i % 3 == 0 { r.next() } else { r.within(0, units(MAX_AMOUNT, decimals)) };
            let bps = r.within(PLAN_BPS_MIN, FEE_BPS);
            let fee = order_fee(amount, bps, decimals);
            let floor = units(FEE_MIN, decimals);
            assert!(fee >= floor && fee <= bps_of(amount, FEE_BPS).max(floor), "{amount} {bps} {decimals}");
            // above the floor it is the rate of the whole amount, rounded down: no tiers
            assert_eq!(fee as u128, (amount as u128 * bps as u128 / 10_000).max(floor as u128), "{amount} {bps} {decimals}");
            // a larger order never pays a smaller fee
            let more = amount.saturating_add(r.within(0, units(1_000_000_000, decimals)));
            assert!(order_fee(more, bps, decimals) >= fee);
            let (x, b) = (r.next(), r.within(0, 10_000));
            assert!(bps_of(x, b) <= x && bps_of(x, 10_000) == x && bps_of(x, 0) == 0);
            assert_eq!(bps_of(x, b) as u128, x as u128 * b as u128 / 10_000, "{x} {b}");
            // a job's fee: the same rate and floor, never more than the amount
            assert_eq!(crate::fee_of(x, decimals), order_fee(x, FEE_BPS, decimals).min(x));
        }
    }

    #[test]
    fn the_payees_shares_add_up_to_the_payment() {
        let mut r = Rng(0x6b6e_6f73_2d73_706c);
        for i in 0..400_000u32 {
            let due = if i % 2 == 0 { r.next() } else { r.within(0, 500_000_000) };
            let bps = r.shares();
            assert!(bps.iter().sum::<u64>() == 10_000 && bps.iter().all(|b| *b >= 1) && (1..=MAX_PAYEES).contains(&bps.len()));
            let shares = split(due, &bps);
            assert_eq!(shares.iter().map(|s| *s as u128).sum::<u128>(), due as u128, "{due} {bps:?}");
            assert!(shares.iter().all(|s| *s <= due) && shares[bps.len()..].iter().all(|s| *s == 0));
            // every payee but the last gets its basis points rounded down; the last at least that
            for (k, b) in bps.iter().enumerate() {
                if k + 1 < bps.len() { assert_eq!(shares[k], bps_of(due, *b)); } else { assert!(shares[k] >= bps_of(due, *b)); }
            }
        }
    }

    /// What the Kani harness of a payment assumes of fee_at, on inputs at random and at every edge: the fee an order
    /// has given out never shrinks as more is paid, is nothing at the start and the whole fee at the end.
    #[test]
    fn the_fee_an_order_has_given_out_grows_with_what_it_paid_and_ends_at_the_whole_fee() {
        let mut r = Rng(0x6b6e_6f73_2d66_6174);
        for i in 0..400_000u32 {
            // within the limits at 6 decimals two times in three; any u64 otherwise
            let (amount, fee) = if i % 3 == 2 { (r.next().max(1), r.next()) } else { (r.within(5_000_000, 500_000_000), r.within(0, 25_000_000)) };
            let p2 = r.within(0, amount);
            let p1 = r.within(0, p2);
            let (f1, f2) = (fee_at(fee, p1, amount), fee_at(fee, p2, amount));
            assert!(f1 <= f2 && f2 <= fee, "{amount} {fee} {p1} {p2}");
            assert_eq!((fee_at(fee, 0, amount), fee_at(fee, amount, amount)), (0, fee));
            // one unit more paid gives out at most one more unit of fee when the fee is not more than the amount
            if fee <= amount && p2 < amount { assert!(fee_at(fee, p2 + 1, amount) - f2 <= 1); }
        }
    }

    /// An order from its funding to its end, in the ways the program pays one: at once, in several payments (a
    /// holdback: one payment, then the release of what was kept), with a top-up between payments. At every step the
    /// account holds what `holds` says; at the end the payees have the amount, the relayers and FEE_OWNER the fee, and
    /// the account nothing.
    #[test]
    fn nothing_is_created_or_lost_over_the_life_of_an_order() {
        let mut r = Rng(0x6b6e_6f73_2d6c_6966);
        for _ in 0..150_000u32 {
            let decimals = [6u8, 6, 6, 9, 8, 2, 0][(r.next() % 7) as usize];
            let (low, high) = (units(ORDER_MIN_AMOUNT, decimals), units(MAX_AMOUNT, decimals));
            let mut amount = r.within(low, high);
            let rate = r.within(PLAN_BPS_MIN, FEE_BPS);
            let mut fee = order_fee(amount, rate, decimals);
            // what the funder put in (top-ups are added below), and what the order's account holds
            let (mut funded, mut held) = (amount as u128 + fee as u128, amount as u128 + fee as u128);
            let (mut paid, mut to_payees, mut tips, mut to_fee_owner) = (0u64, 0u128, 0u128, 0u128);
            let holdback = if r.next() % 3 == 0 { r.within(1, MAX_HOLDBACK_BPS as u64) as u16 } else { 0 };
            let mut steps = 0;
            while paid < amount {
                // a top-up before any payment: the amount grows, and the fee to that of the new amount (never less)
                if paid == 0 && steps == 0 && r.next() % 4 == 0 && amount < high {
                    let add = r.within(1, high - amount);
                    let new_fee = order_fee(amount + add, rate, decimals).max(fee);
                    let total = add as u128 + (new_fee - fee) as u128;
                    (amount, fee, funded, held) = (amount + add, new_fee, funded + total, held + total);
                }
                assert_eq!(held, holds(amount, fee, paid) as u128);
                let left = amount - paid;
                // what one token pays: all that is left; with a holdback, all but the holdback first, then the rest
                // (Release pays the recorded parts: the same split of what was kept)
                let o = order(0, amount, fee, if paid == 0 { holdback } else { 0 }, 0, paid);
                let due = if steps > 6 { left } else if r.next() % 3 == 0 { r.within(1, left) } else { due_now(&o) };
                let bps = r.shares();
                let p = pay(amount, fee, paid, due, &bps, held as u64, r.next() % 2 == 0, decimals).expect("a payment within what is left");
                assert!(conserved(amount, fee, paid, due, bps.len(), &p), "{amount} {fee} {paid} {due} {bps:?} {p:?}");
                let out = p.shares.iter().map(|s| *s as u128).sum::<u128>() + p.tip as u128 + p.rest as u128;
                to_payees += p.shares.iter().map(|s| *s as u128).sum::<u128>();
                tips += p.tip as u128;
                to_fee_owner += p.rest as u128;
                held -= out;
                paid = p.paid;
                steps += 1;
                assert!(p.tip <= units(TIP_FIRST, decimals));
            }
            assert_eq!((held, to_payees, tips + to_fee_owner, to_payees + tips + to_fee_owner), (0, amount as u128, fee as u128, funded));
            // refused: nothing to pay, more than is left, an order already paid
            assert!(pay(amount, fee, 0, 0, &[10_000], 0, false, decimals).is_none() && pay(amount, fee, 1, amount, &[10_000], 0, false, decimals).is_none());
            assert!(pay(amount, fee, amount, 1, &[10_000], 0, false, decimals).is_none());
        }
    }

    /// A standing order pays its rate once per pull request and is rewritten as what is left of it
    /// (order_terms::after_pay): the fee it has given out and the fee it keeps are always its whole fee.
    #[test]
    fn a_standing_order_gives_out_its_fee_with_its_amount_and_keeps_the_rest_for_the_refund() {
        let after = include_str!("order_terms.rs");
        for line in ["let share = |p: u64| (o.fee as u128 * p as u128 / o.amount as u128) as u64;",
                     "let (left, took) = (o.amount - paid, share(paid) - share(o.paid));",
                     "put_u64(&mut d, O_AMOUNT, left); put_u64(&mut d, O_FEE, o.fee - took); put_u64(&mut d, O_PAID, 0);"] {
            assert_eq!(after.matches(line).count(), 1, "order_terms.rs no longer has: {line}");
        }
        let mut r = Rng(0x6b6e_6f73_2d73_7464);
        for _ in 0..60_000u32 {
            let mut amount = r.within(5_000_000, 500_000_000);
            let per = r.within((amount / 40).max(1), amount + amount / 2);      // at most forty pull requests; sometimes not even one
            let mut fee = order_fee(amount, r.within(PLAN_BPS_MIN, FEE_BPS), 6);
            let (budget, whole_fee) = (amount, fee);
            let (mut held, mut to_payees, mut fees) = (amount + fee, 0u64, 0u64);
            // one rate per pull request while a whole rate is left; then nothing is due and the rest goes back
            loop {
                let o = order(F_STANDING, amount, fee, 0, per, 0);
                let due = due_now(&o);
                if due == 0 { break; }
                assert_eq!(due, per);
                let p = pay(amount, fee, 0, due, &r.shares(), held, r.next() % 2 == 0, 6).unwrap();
                let out = p.shares.iter().sum::<u64>() + p.tip + p.rest;
                (held, to_payees, fees) = (held - out, to_payees + due, fees + p.tip + p.rest);
                if p.last { amount = 0; fee = 0; break; }
                // after_pay: the order becomes what is left of it
                let took = fee_at(fee, p.paid, amount) - fee_at(fee, 0, amount);
                (amount, fee) = (amount - p.paid, fee - took);
                assert_eq!(held, amount + fee);
            }
            // what is refunded is what is left of the amount and the fee on it: the funder gets back what was not earned
            assert_eq!((held, to_payees + amount, fees + fee), (amount + fee, budget, whole_fee));
            assert!(amount < per || amount == 0);
        }
    }
}
