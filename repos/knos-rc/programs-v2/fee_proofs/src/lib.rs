//! The bounds of the fee (knos_pay 2.2), for a mint of 6 decimals: `order_fee` and `fee_of` are the program's own
//! functions, copied as text from programs-v2/knos_pay/src/lib.rs by build.rs (with `bps_of`, `units` and the
//! constants).
//!
//! The schedule: ONE rate, no tiers. An order's fee is `bps` basis points of the amount rounded down (30 without a
//! Plan; a Plan lowers it to no less than 10), at least 0.05, paid on top of the amount; a job's is the same at the
//! rate 30 and never more than the amount, taken out of it. An order holds 5.00 to 100,000.00.
//!
//! WHAT `cargo kani` IS ASKED TO PROVE. docs/kani.json (`fee_proofs`, written by scripts/kani_fee_record.py) records
//! which harnesses the solver answered within the limit; one that is not recorded as verified proves nothing. The
//! range of every harness about an order is every amount from 0 to 100,000.00: every amount the program takes, and
//! every smaller one. One rate, so there are no tiers to take apart.
//!   - at the rates 10 to 19 and 20 to 29, each in one harness that goes through its rates one by one: the fee is at
//!     least the floor (0.05); it is the floor, or at most 0.30% of the amount (ten thousand fees are at most thirty
//!     amounts); the amount and the fee add up in a u64;
//!   - at the rate 30 (an order with no Plan): the floor, the sum, and at most 0.31% of the amount;
//!   - at the rate 30, the exact bound: the fee is the floor or at most 0.30% of the amount, and it is 0.30% of the
//!     amount rounded down, or the floor, and nothing else (stated without a division, in 128 bits);
//!   - a job's fee, at every u64 amount: never more than the amount, and at least the floor or the whole amount.
//!
//! THE EXACT 0.30% AND ITS SOLVER. At the rate 30 the fee is exactly 0.30% rounded down, with nothing to spare.
//! `bps_of` divides the amount by ten thousand and takes its remainder by ten thousand, and the verifier gives each
//! its own quotient and remainder; the exact bound needs the two to agree, and no solver working on bits found that
//! within the limit: not CaDiCaL, Kissat or Z3 on the bound, on its form without a division, or on a sixteenth of the
//! amounts, and not even on the division's identity alone (docs/kani.json, `not_answered`, lists each once, as run on
//! 2026-10-07). With one basis point to spare the agreement is not needed, and CaDiCaL answers in under a second.
//! So that one harness is marked `#[kani::solver(cvc5)]` and is answered by cvc5 with bit-vectors solved as integers
//! (`--solve-bv-as-int=sum`), where a division by a constant is linear arithmetic: seconds. Kani has no way to pass
//! a solver its options, so solvers/cvc5 is a script that adds the option, and scripts/kani_fee_record.py puts it
//! first on PATH; plain `cargo kani` here finds the installed cvc5 without the option and does not finish that
//! harness. That result rests on cvc5's translation as well as on Kani and CBMC; the same setup refuted the bound
//! written with `<` in place of `<=`. Every rate at once with the rate unknown was not answered either way. The one
//! harness over every u64 amount and every rate (knos_pay/src/proofs.rs) is recorded at the top of docs/kani.json
//! with what it got.
//!
//! WHY RATE BY RATE. With the rate unknown the solver is left the product of two unknowns, the amount's ten-thousands
//! and the rate, to compare with another product. A harness that goes through its rates one after the other meets
//! only a number times a constant.
//!
//! WHAT IS TESTED BESIDE THE PROOFS (tests/reference.rs, `cargo test --release`): the same functions against a
//! reference written with 128-bit integers, at every amount within 20,000 of each edge of the schedule for every
//! rate, at 10,000,000 amounts drawn from a fixed seed, at the rate 30 at every remainder of an amount by ten
//! thousand on 2,001 values of its ten-thousands (the exact 0.30%, and that one unit more would be above it), and
//! that the fee never falls when the amount grows.
include!(concat!(env!("OUT_DIR"), "/fee.rs"));

pub const DECIMALS: u8 = 6;

/// The schedule written a second way, in 128 bits, the product divided once: what `order_fee` must be.
pub fn reference(amount: u64, bps: u64) -> u64 { (amount as u128 * bps as u128 / 10_000).max(FEE_MIN as u128) as u64 }

/// A job's fee written the same way: the order's at the standard rate, never more than the amount.
pub fn job_reference(amount: u64) -> u64 { reference(amount, FEE_BPS).min(amount) }

#[cfg(kani)]
mod harness {
    use super::*;

    const FLOOR: u64 = FEE_MIN;

    /// An amount of at most 40 bits, drawn as 8 bits above 32: the upper 24 bits are fixed before the solver starts.
    /// 100,000.00 is below 2^37.
    fn amount() -> u64 {
        let (high, low): (u8, u32) = (kani::any(), kani::any());
        (high as u64) << 32 | low as u64
    }

    /// What every harness asserts of the fee the program computes for an amount of at most 100,000.00 at the rate
    /// `bps`: it is at least the floor; it is the floor, or at most `bps` of the amount and so at most 0.30% of it
    /// (written without a division: ten thousand fees are at most `bps` amounts); and the amount and the fee add up
    /// in a u64.
    fn bounded(amount: u64, fee: u64) {
        assert!(fee >= FLOOR);
        assert!(fee == FLOOR || fee * 10_000 <= amount * FEE_BPS);
        assert!(amount.checked_add(fee).is_some());
    }

    /// Each rate from `from` to `to`, one after the other: with the rate a constant, every product the solver meets
    /// is a number times a constant.
    fn each_rate(amount: u64, from: u64, to: u64) {
        let mut bps = from;
        while bps <= to {
            bounded(amount, order_fee(amount, bps, DECIMALS));
            bps += 1;
        }
    }

    /// 0 to 100,000.00 at the rates 10 to 19.
    #[kani::proof]
    #[kani::unwind(12)]
    fn the_fee_of_an_order_is_within_its_bounds_at_the_rates_10_to_19() {
        let amount = amount();
        kani::assume(amount <= MAX_AMOUNT);
        each_rate(amount, 10, 19);
    }

    /// 0 to 100,000.00 at the rates 20 to 29.
    #[kani::proof]
    #[kani::unwind(12)]
    fn the_fee_of_an_order_is_within_its_bounds_at_the_rates_20_to_29() {
        let amount = amount();
        kani::assume(amount <= MAX_AMOUNT);
        each_rate(amount, 20, 29);
    }

    /// 0 to 100,000.00 at the rate 30, the rate of an order with no Plan: the floor, the sum, and at most 0.31% of the
    /// amount, with Kani's default solver. The 0.30% itself, exact at this rate, is the last harness of this file,
    /// which needs another solver (the module documentation says why).
    #[kani::proof]
    #[kani::unwind(8)]
    fn the_fee_of_an_order_at_the_rate_30_is_at_least_the_floor_adds_up_and_is_below_31_basis_points() {
        let amount = amount();
        kani::assume(amount <= MAX_AMOUNT);
        let fee = order_fee(amount, FEE_BPS, DECIMALS);
        assert!(fee >= FLOOR);
        assert!(fee == FLOOR || fee * 10_000 <= amount * (FEE_BPS + 1));
        assert!(amount.checked_add(fee).is_some());
    }

    /// A job's fee (2.0), at every u64 amount: never more than the amount it is taken out of, and the order's fee at
    /// the standard rate or the whole amount, whichever is smaller.
    #[kani::proof]
    #[kani::unwind(8)]
    fn the_fee_of_a_job_is_never_more_than_its_amount() {
        let amount: u64 = kani::any();
        let fee = fee_of(amount, DECIMALS);
        assert!(fee <= amount && fee >= FLOOR.min(amount));
    }

    /// 0 to 100,000.00 at the rate 30: the exact bound. The fee is the floor, or at most 0.30% of the amount; and,
    /// written without a division in 128 bits, `bps_of` is 0.30% of the amount rounded down and nothing else
    /// (`q * 10,000 <= amount * 30 < (q + 1) * 10,000`), and the fee is that or the floor, whichever is larger.
    /// Answered by cvc5 with bit-vectors solved as integers (solvers/cvc5); the module documentation says why.
    #[kani::proof]
    #[kani::unwind(8)]
    #[kani::solver(cvc5)]
    fn the_fee_of_an_order_at_the_rate_30_is_30_basis_points_rounded_down_or_the_floor() {
        let amount = amount();
        kani::assume(amount <= MAX_AMOUNT);
        let fee = order_fee(amount, FEE_BPS, DECIMALS);
        assert!(fee == FLOOR || fee * 10_000 <= amount * FEE_BPS);
        let (q, p) = (bps_of(amount, FEE_BPS) as u128, amount as u128 * FEE_BPS as u128);
        assert!(q * 10_000 <= p && p < (q + 1) * 10_000);
        assert!(fee as u128 == q.max(FLOOR as u128));
    }
}
