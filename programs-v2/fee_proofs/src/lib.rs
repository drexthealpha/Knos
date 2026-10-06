//! The bounds of an order's fee (knos_pay 2.1), for a mint of 6 decimals: `order_fee` is the program's own function,
//! copied as text from programs-v2/knos_pay/src/lib.rs by build.rs (with `bps_of`, `units` and the constants).
//!
//! The schedule: `bps` (a Plan's rate, 50 to 250 basis points; 250 without a Plan) of the first 1,000.00 of the
//! amount, 1% of what lies between 1,000.00 and 50,000.00, 0.5% of what lies above; each part rounded down; at least
//! 0.40. An order holds 5.00 to 100,000.00.
//!
//! WHAT `cargo kani` IS ASKED TO PROVE. docs/kani.json (`fee_proofs`, written by scripts/kani_fee_record.py) records
//! which harnesses the solver answered within the limit; one that is not recorded as verified proves nothing. Each
//! harness asserts, of the fee the program computes for an amount in its range:
//!   - it is at least the floor (0.40);
//!   - it is the floor, or at most 2.5% of the amount;
//!   - the amount and the fee add up in a u64.
//! The ranges, which together are every amount from 0 to 100,000.00 (every amount the program takes):
//!   - the first tier (0 to 1,000.00) at the rates 50..=249, in eight harnesses that go through the rates one by one
//!     (fifty at a time, then twenty-five, then six: the nearer the rate is to 250 the longer the solver takes);
//!   - the first tier at the rate 250 (an order with no Plan): the floor and the sum ONLY. The 2.5% is not proved
//!     there: at that rate the bound is exact, with nothing to spare, and neither CaDiCaL (150 seconds) nor Kissat
//!     (130) answered. tests/reference.rs checks it at each of the 1,000,000,001 amounts of the tier instead;
//!   - the second tier (above 1,000.00, to 50,000.00) for every rate;
//!   - the third tier (above 50,000.00, to 100,000.00) for every rate.
//! A last harness asks the floor and the 2.5% of every u64 amount above 100,000.00, where no order can be.
//!
//! WHY PER TIER, AND WHY THE FIRST TIER RATE BY RATE. One harness over every u64 amount and every rate (the one in
//! knos_pay/src/proofs.rs) leaves the solver the product of two unknowns, the amount's ten-thousands and the rate,
//! to compare with another product, and it did not answer in 180 seconds; nor did the first tier alone with the rate
//! unknown, in 165. Above the first tier the first tier's part is a constant times the rate and the other rates are
//! constants, and the solver answers in seconds. Inside the first tier a harness goes through its rates one after
//! the other, so each product is a number times a constant.
//!
//! WHAT IS TESTED INSTEAD OF PROVED (tests/reference.rs, `cargo test --release`): the same function against a
//! reference written with 128-bit integers, at every amount within 20,000 of each edge of the schedule for every
//! rate, at 10,000,000 amounts drawn from a fixed seed, and at every amount of the first tier at the rate 250; that
//! the fee never falls when the amount grows.
include!(concat!(env!("OUT_DIR"), "/fee.rs"));

pub const DECIMALS: u8 = 6;

/// The schedule written a second way, in 128 bits, with each tier's product divided once: what `order_fee` must be.
pub fn reference(amount: u64, bps: u64) -> u64 {
    let (a, t1, t2) = (amount as u128, FEE_TIER_1 as u128, FEE_TIER_2 as u128);
    let first = a.min(t1);
    let second = a.min(t2) - first;
    let third = a - first - second;
    let fee = first * bps as u128 / 10_000 + second * FEE_BPS_2 as u128 / 10_000 + third * FEE_BPS_3 as u128 / 10_000;
    fee.max(ORDER_FEE_MIN as u128) as u64
}

#[cfg(kani)]
mod harness {
    use super::*;

    const FLOOR: u64 = ORDER_FEE_MIN;

    /// A Plan's rate: 50 to 250 basis points.
    fn rate() -> u64 {
        let bps: u8 = kani::any();
        kani::assume(bps as u64 >= PLAN_BPS_MIN && bps as u64 <= FEE_BPS);
        bps as u64
    }

    /// An amount of at most 40 bits, drawn as 8 bits above 32: the upper 24 bits are fixed before the solver starts.
    /// 100,000.00 is below 2^37.
    fn amount() -> u64 {
        let (high, low): (u8, u32) = (kani::any(), kani::any());
        (high as u64) << 32 | low as u64
    }

    /// What every harness asserts of the fee the program computes for an amount of at most 100,000.00: it is at
    /// least the floor; it is the floor, or at most 2.5% of the amount (written without a division: ten thousand
    /// fees are at most 250 amounts); and the amount and the fee add up in a u64.
    fn bounded(amount: u64, fee: u64) {
        assert!(fee >= FLOOR);
        assert!(fee == FLOOR || fee * 10_000 <= amount * FEE_BPS);
        assert!(amount.checked_add(fee).is_some());
    }

    /// The first tier at each rate from `from` to `to`, one after the other: with the rate a constant, every product
    /// the solver meets is a number times a constant.
    fn each_rate(amount: u64, from: u64, to: u64) {
        let mut bps = from;
        while bps <= to {
            bounded(amount, order_fee(amount, bps, DECIMALS));
            bps += 1;
        }
    }

    /// 0 to 1,000.00 at the rates 50 to 100.
    #[kani::proof]
    #[kani::unwind(53)]
    fn the_fee_of_an_amount_in_the_first_tier_is_within_its_bounds_at_the_rates_50_to_100() {
        let amount = amount();
        kani::assume(amount <= FEE_TIER_1);
        each_rate(amount, 50, 100);
    }

    /// 0 to 1,000.00 at the rates 101 to 150.
    #[kani::proof]
    #[kani::unwind(53)]
    fn the_fee_of_an_amount_in_the_first_tier_is_within_its_bounds_at_the_rates_101_to_150() {
        let amount = amount();
        kani::assume(amount <= FEE_TIER_1);
        each_rate(amount, 101, 150);
    }

    /// 0 to 1,000.00 at the rates 151 to 200.
    #[kani::proof]
    #[kani::unwind(53)]
    fn the_fee_of_an_amount_in_the_first_tier_is_within_its_bounds_at_the_rates_151_to_200() {
        let amount = amount();
        kani::assume(amount <= FEE_TIER_1);
        each_rate(amount, 151, 200);
    }

    /// 0 to 1,000.00 at the rates 201 to 225.
    #[kani::proof]
    #[kani::unwind(28)]
    fn the_fee_of_an_amount_in_the_first_tier_is_within_its_bounds_at_the_rates_201_to_225() {
        let amount = amount();
        kani::assume(amount <= FEE_TIER_1);
        each_rate(amount, 201, 225);
    }

    /// 0 to 1,000.00 at the rates 226 to 231.
    #[kani::proof]
    #[kani::unwind(9)]
    fn the_fee_of_an_amount_in_the_first_tier_is_within_its_bounds_at_the_rates_226_to_231() {
        let amount = amount();
        kani::assume(amount <= FEE_TIER_1);
        each_rate(amount, 226, 231);
    }

    /// 0 to 1,000.00 at the rates 232 to 237.
    #[kani::proof]
    #[kani::unwind(9)]
    fn the_fee_of_an_amount_in_the_first_tier_is_within_its_bounds_at_the_rates_232_to_237() {
        let amount = amount();
        kani::assume(amount <= FEE_TIER_1);
        each_rate(amount, 232, 237);
    }

    /// 0 to 1,000.00 at the rates 238 to 243.
    #[kani::proof]
    #[kani::unwind(9)]
    fn the_fee_of_an_amount_in_the_first_tier_is_within_its_bounds_at_the_rates_238_to_243() {
        let amount = amount();
        kani::assume(amount <= FEE_TIER_1);
        each_rate(amount, 238, 243);
    }

    /// 0 to 1,000.00 at the rates 244 to 249.
    #[kani::proof]
    #[kani::unwind(9)]
    fn the_fee_of_an_amount_in_the_first_tier_is_within_its_bounds_at_the_rates_244_to_249() {
        let amount = amount();
        kani::assume(amount <= FEE_TIER_1);
        each_rate(amount, 244, 249);
    }

    /// 0 to 1,000.00 at the rate 250, the rate of an order with no Plan: the floor and the sum only. The third bound
    /// (at most 2.5% of the amount) is exact here, with nothing to spare, and the solver did not answer it; it is
    /// tested at every amount of the tier instead (tests/reference.rs).
    #[kani::proof]
    #[kani::unwind(8)]
    fn the_fee_of_an_amount_in_the_first_tier_at_the_rate_250_is_at_least_the_floor_and_adds_up() {
        let amount = amount();
        kani::assume(amount <= FEE_TIER_1);
        let fee = order_fee(amount, FEE_BPS, DECIMALS);
        assert!(fee >= FLOOR);
        assert!(amount.checked_add(fee).is_some());
    }

    /// Above 1,000.00 and up to 50,000.00, every rate.
    #[kani::proof]
    #[kani::unwind(8)]
    fn the_fee_of_an_amount_in_the_second_tier_is_within_its_bounds() {
        let (amount, bps) = (amount(), rate());
        kani::assume(amount > FEE_TIER_1 && amount <= FEE_TIER_2);
        bounded(amount, order_fee(amount, bps, DECIMALS));
    }

    /// Above 50,000.00 and up to 100,000.00, the most an order holds, every rate.
    #[kani::proof]
    #[kani::unwind(8)]
    fn the_fee_of_an_amount_in_the_third_tier_is_within_its_bounds() {
        let (amount, bps) = (amount(), rate());
        kani::assume(amount > FEE_TIER_2 && amount <= MAX_AMOUNT);
        bounded(amount, order_fee(amount, bps, DECIMALS));
    }

    /// Every u64 amount above 100,000.00, where the program takes no order: the floor and the 2.5%, in 128 bits.
    #[kani::proof]
    #[kani::unwind(8)]
    fn the_fee_of_an_amount_above_the_most_an_order_holds_is_within_its_bounds() {
        let (amount, bps): (u64, u64) = (kani::any(), rate());
        kani::assume(amount > MAX_AMOUNT);
        let fee = order_fee(amount, bps, DECIMALS);
        assert!(fee >= FLOOR && fee as u128 * 10_000 <= amount as u128 * FEE_BPS as u128);
    }
}
