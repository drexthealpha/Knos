//! `order_fee` and `fee_of` (the program's own lines, copied by build.rs) against `reference` and `job_reference`,
//! the schedule written a second way with 128-bit integers, which hold every product here exactly (a u64 times 30
//! is below 2^69):
//!   - at every amount within 20,000 units of each edge of the schedule, for every rate a Plan can set;
//!   - at 10,000,000 amounts and rates drawn from a fixed seed, over every u64 and close to the schedule;
//!   - at the rate 30 (an order with no Plan), where "at most 0.30% of the amount" is exact and Kani did not answer
//!     it: at every remainder of an amount by ten thousand (all 10,000 of them) on 2,001 amounts' ten-thousands
//!     spread from 0 to the most an order holds, 20,010,000 amounts in all;
//! and the bounds the Kani harnesses of src/lib.rs state, and that the fee never falls when the amount grows.
//!
//!   cd programs-v2/fee_proofs && cargo test --release
use knos_fee_proofs::*;

const NEAR: u64 = 20_000;

/// xorshift64*: the same inputs on every run and every machine.
struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 >> 12; self.0 ^= self.0 << 25; self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
}

/// The amounts where the schedule changes: nothing, the smallest order, where 0.30% and 0.10% reach the floor, the
/// most an order holds, and the largest u64.
fn edges() -> [u64; 6] {
    [0, ORDER_MIN_AMOUNT, FEE_MIN * 10_000 / FEE_BPS, FEE_MIN * 10_000 / PLAN_BPS_MIN, MAX_AMOUNT, u64::MAX]
}

/// Everything asserted of one amount and rate. Returns the fee.
fn check(amount: u64, bps: u64) -> u64 {
    let fee = order_fee(amount, bps, DECIMALS);
    assert_eq!(fee, reference(amount, bps), "order_fee({amount}, {bps})");
    assert!(fee >= FEE_MIN, "below the floor: {amount} {bps}");
    assert!(fee == FEE_MIN || fee as u128 * 10_000 <= amount as u128 * bps as u128, "above the rate: {amount} {bps}");
    assert!(fee == FEE_MIN || fee as u128 * 10_000 <= amount as u128 * FEE_BPS as u128, "above 0.30%: {amount} {bps}");
    if amount <= MAX_AMOUNT { assert!(amount.checked_add(fee).is_some()); }
    // a job's fee: the same at the standard rate, never more than the amount it is taken out of
    let job = fee_of(amount, DECIMALS);
    assert!(job == job_reference(amount) && job <= amount, "fee_of({amount})");
    fee
}

#[test]
fn the_schedule_is_the_one_the_documents_print() {
    assert_eq!((FEE_BPS, PLAN_BPS_MIN, FEE_MIN, MAX_AMOUNT, ORDER_MIN_AMOUNT), (30, 10, 50_000, 100_000_000_000, 5_000_000));
    assert_eq!(state::units(FEE_MIN, DECIMALS), FEE_MIN, "at 6 decimals a constant is its own number of units");
    // 5.00 -> 0.05 (the floor); 100.00 -> 0.30; 1,000.00 -> 3.00; 5,000.00 -> 15.00; 100,000.00 -> 300.00
    for (amount, fee) in [(5_000_000u64, 50_000u64), (100_000_000, 300_000), (1_000_000_000, 3_000_000), (5_000_000_000, 15_000_000), (100_000_000_000, 300_000_000),
                          // where 0.30% passes the floor
                          (16_666_666, 50_000), (16_670_000, 50_010)] {
        assert_eq!((order_fee(amount, FEE_BPS, DECIMALS), fee_of(amount, DECIMALS)), (fee, fee), "{amount}");
    }
    // a job of less than the floor pays all of itself; an order's fee is the floor whatever the amount
    assert_eq!((fee_of(49_999, DECIMALS), fee_of(0, DECIMALS), order_fee(0, FEE_BPS, DECIMALS)), (49_999, 0, 50_000));
}

#[test]
fn what_is_proved_is_the_programs_own_text() {
    let copied = include_str!(concat!(env!("OUT_DIR"), "/fee.rs"));
    let source = concat!(include_str!("../../knos_pay/src/lib.rs"), include_str!("../../knos_pay/src/state.rs"));
    let lines: Vec<&str> = copied.lines().filter(|l| !l.starts_with("//") && *l != "pub mod state {" && *l != "}").collect();
    // five constants, bps_of, fee_of, order_fee, and the lines of units
    assert!(lines.len() >= 5 + 3 + 3, "{}", lines.len());
    for line in lines { assert!(source.lines().any(|s| s == line), "not a line of the program: {line}"); }
    assert!(copied.contains("pub fn order_fee(amount: u64, bps: u64, decimals: u8) -> u64 {") && copied.contains("pub fn bps_of(amount: u64, bps: u64) -> u64 {")
            && copied.contains("pub fn fee_of(amount: u64, decimals: u8) -> u64 {"));
    // one rate: nothing of a tier is left in what is copied
    assert!(!copied.contains("TIER") && !copied.contains("ORDER_FEE_MIN"));
}

#[test]
fn every_amount_near_an_edge_of_the_schedule_at_every_rate_is_the_reference() {
    let mut checked = 0u64;
    for edge in edges() {
        let (from, to) = (edge.saturating_sub(NEAR), edge.saturating_add(NEAR));
        for bps in PLAN_BPS_MIN..=FEE_BPS {
            let mut before = 0;
            for amount in from..=to {
                let fee = check(amount, bps);
                assert!(amount == from || fee >= before, "the fee fell: {amount} {bps}");
                before = fee;
                checked += 1;
            }
        }
    }
    // six edges, 21 rates, 40,001 amounts each, less the two edges that stop at 0 and at the largest u64
    assert_eq!(checked, 21 * (4 * (2 * NEAR + 1) + 2 * (NEAR + 1)));
}

#[test]
fn ten_million_amounts_and_rates_from_a_fixed_seed_are_the_reference() {
    let (mut rng, edges) = (Rng(0x4B4E_4F53_2D46_4545), edges());
    let mut ranges = [0u64; 3];
    for _ in 0..10_000_000u32 {
        let bps = PLAN_BPS_MIN + rng.next() % (FEE_BPS - PLAN_BPS_MIN + 1);
        let amount = match rng.next() % 4 {
            0 => rng.next(),                                                                     // any u64
            1 => rng.next() % (MAX_AMOUNT + 1),                                                  // an amount an order may hold
            2 => edges[(rng.next() % 6) as usize].wrapping_add(rng.next() % 2_000_001).wrapping_sub(1_000_000), // within 1.00 of an edge
            _ => rng.next() >> (rng.next() % 64),                                                // every width of amount
        };
        let fee = check(amount, bps);
        // the fee never falls when the amount grows by one unit, or by any step
        let more = amount.saturating_add(1 + rng.next() % 1_000_000);
        assert!(order_fee(amount.saturating_add(1), bps, DECIMALS) >= fee && order_fee(more, bps, DECIMALS) >= fee, "the fee fell: {amount} {bps}");
        ranges[if amount < ORDER_MIN_AMOUNT { 0 } else if amount <= MAX_AMOUNT { 1 } else { 2 }] += 1;
    }
    assert!(ranges.iter().all(|n| *n > 500_000), "below, within and above what an order holds were each drawn often: {ranges:?}");
}

/// The part Kani did not answer (docs/kani.json, `fee_proofs.summary.parts`): at the rate 30, "at most 0.30% of the
/// amount" exactly. `bps_of` takes an amount apart into its ten-thousands and a remainder below ten thousand, so
/// the remainder is where rounding happens: every one of the 10,000 remainders, on 2,001 values of the
/// ten-thousands from 0 to the most an order holds (10,000,000 of them), against the reference and the bound.
#[test]
fn every_remainder_at_the_top_rate_is_the_reference_and_within_thirty_basis_points() {
    let top = MAX_AMOUNT / 10_000;
    let mut checked = 0u64;
    for step in 0..=2_000u64 {
        let q = if step == 2_000 { top - 1 } else { step * (top / 2_000) + step % 7 };
        for r in 0..10_000u64 {
            let amount = q * 10_000 + r;
            let fee = order_fee(amount, FEE_BPS, DECIMALS);
            assert!(fee == reference(amount, FEE_BPS) && fee >= FEE_MIN, "order_fee({amount}, 30)");
            assert!(fee == FEE_MIN || fee * 10_000 <= amount * FEE_BPS, "above 0.30%: {amount}");
            // and it is the largest whole number of units that is: one more would be above 0.30%
            assert!(fee == FEE_MIN || (fee + 1) * 10_000 > amount * FEE_BPS, "not the 0.30% rounded down: {amount}");
            checked += 1;
        }
    }
    assert!(order_fee(MAX_AMOUNT, FEE_BPS, DECIMALS) == 300_000_000);
    assert_eq!(checked, 20_010_000);
}
