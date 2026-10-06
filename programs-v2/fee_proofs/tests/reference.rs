//! `order_fee` (the program's own lines, copied by build.rs) against `reference`, the schedule written a second way
//! with 128-bit integers, which hold every product here exactly (a u64 times 250 is below 2^72):
//!   - at every amount within 20,000 units of each edge of the schedule, for every rate a Plan can set;
//!   - at 10,000,000 amounts and rates drawn from a fixed seed, over every u64 and close to the schedule;
//!   - at every amount of the first tier, 0 to 1,000.00, at the rate 250 (an order with no Plan): the one part of
//!     the bounds that Kani did not answer;
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

/// The amounts where the schedule changes: nothing, the smallest order, where 2.5% and 0.5% reach the floor, the two
/// tiers' edges, the most an order holds, and the largest u64.
fn edges() -> [u64; 8] {
    [0, ORDER_MIN_AMOUNT, ORDER_FEE_MIN * 10_000 / FEE_BPS, ORDER_FEE_MIN * 10_000 / PLAN_BPS_MIN, FEE_TIER_1, FEE_TIER_2, MAX_AMOUNT, u64::MAX]
}

/// Everything asserted of one amount and rate. Returns the fee.
fn check(amount: u64, bps: u64) -> u64 {
    let fee = order_fee(amount, bps, DECIMALS);
    assert_eq!(fee, reference(amount, bps), "order_fee({amount}, {bps})");
    assert!(fee >= ORDER_FEE_MIN, "below the floor: {amount} {bps}");
    // a Plan's rate is the first tier's alone: above 1,000.00 the schedule's 1% may be more than it
    if amount <= FEE_TIER_1 { assert!(fee == ORDER_FEE_MIN || fee as u128 * 10_000 <= amount as u128 * bps as u128, "above the rate: {amount} {bps}"); }
    assert!(fee == ORDER_FEE_MIN || fee as u128 * 10_000 <= amount as u128 * FEE_BPS as u128, "above 2.5%: {amount} {bps}");
    if amount <= MAX_AMOUNT { assert!(amount.checked_add(fee).is_some()); }
    fee
}

#[test]
fn the_schedule_is_the_one_the_documents_print() {
    assert_eq!((FEE_BPS, FEE_BPS_2, FEE_BPS_3, PLAN_BPS_MIN), (250, 100, 50, 50));
    assert_eq!((FEE_TIER_1, FEE_TIER_2, MAX_AMOUNT, ORDER_FEE_MIN, ORDER_MIN_AMOUNT), (1_000_000_000, 50_000_000_000, 100_000_000_000, 400_000, 5_000_000));
    assert_eq!(state::units(ORDER_FEE_MIN, DECIMALS), ORDER_FEE_MIN, "at 6 decimals a constant is its own number of units");
    // 5.00 -> 0.40 (the floor); 16.00 -> 0.40 (2.5% reaches the floor); 1,000 -> 25; 50,000 -> 515; 100,000 -> 765
    for (amount, fee) in [(5_000_000u64, 400_000u64), (16_000_000, 400_000), (16_000_040, 400_001), (1_000_000_000, 25_000_000), (1_000_010_000, 25_000_100),
                          (50_000_000_000, 515_000_000), (50_000_020_000, 515_000_100), (100_000_000_000, 765_000_000)] {
        assert_eq!(order_fee(amount, FEE_BPS, DECIMALS), fee, "{amount}");
    }
}

#[test]
fn what_is_proved_is_the_programs_own_text() {
    let copied = include_str!(concat!(env!("OUT_DIR"), "/fee.rs"));
    let source = concat!(include_str!("../../knos_pay/src/lib.rs"), include_str!("../../knos_pay/src/state.rs"));
    let lines: Vec<&str> = copied.lines().filter(|l| !l.starts_with("//") && *l != "pub mod state {" && *l != "}").collect();
    assert!(lines.len() >= 9 + 1 + 5 + 3, "{}", lines.len());
    for line in lines { assert!(source.lines().any(|s| s == line), "not a line of the program: {line}"); }
    assert!(copied.contains("pub fn order_fee(amount: u64, bps: u64, decimals: u8) -> u64 {") && copied.contains("pub fn bps_of(amount: u64, bps: u64) -> u64 {"));
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
    // eight edges, 201 rates, 40,001 amounts each, less the two edges that stop at 0 and at the largest u64
    assert_eq!(checked, 201 * (6 * (2 * NEAR + 1) + 2 * (NEAR + 1)));
}

#[test]
fn ten_million_amounts_and_rates_from_a_fixed_seed_are_the_reference() {
    let (mut rng, edges) = (Rng(0x4B4E_4F53_2D46_4545), edges());
    let mut tiers = [0u64; 4];
    for _ in 0..10_000_000u32 {
        let bps = PLAN_BPS_MIN + rng.next() % (FEE_BPS - PLAN_BPS_MIN + 1);
        let amount = match rng.next() % 4 {
            0 => rng.next(),                                                                     // any u64
            1 => rng.next() % (MAX_AMOUNT + 1),                                                  // an amount an order may hold
            2 => edges[(rng.next() % 8) as usize].wrapping_add(rng.next() % 2_000_001).wrapping_sub(1_000_000), // within 1.00 of an edge
            _ => rng.next() >> (rng.next() % 64),                                                // every width of amount
        };
        let fee = check(amount, bps);
        // the fee never falls when the amount grows by one unit, or by any step
        let more = amount.saturating_add(1 + rng.next() % 1_000_000);
        assert!(order_fee(amount.saturating_add(1), bps, DECIMALS) >= fee && order_fee(more, bps, DECIMALS) >= fee, "the fee fell: {amount} {bps}");
        tiers[if amount <= FEE_TIER_1 { 0 } else if amount <= FEE_TIER_2 { 1 } else if amount <= MAX_AMOUNT { 2 } else { 3 }] += 1;
    }
    assert!(tiers.iter().all(|n| *n > 500_000), "every tier was drawn often: {tiers:?}");
}

/// The part Kani did not answer (docs/kani.json, `fee_proofs.summary.parts`): the first tier at the rate 250, where
/// "at most 2.5% of the amount" is exact. Every one of its 1,000,000,001 amounts, against the reference and the bounds.
#[test]
fn every_amount_of_the_first_tier_at_the_top_rate_is_the_reference() {
    let (mut before, mut checked) = (0u64, 0u64);
    for amount in 0..=FEE_TIER_1 {
        let fee = order_fee(amount, FEE_BPS, DECIMALS);
        assert!(fee == reference(amount, FEE_BPS) && fee >= ORDER_FEE_MIN && fee >= before, "order_fee({amount}, 250)");
        assert!(fee == ORDER_FEE_MIN || fee * 10_000 <= amount * FEE_BPS, "above 2.5%: {amount}");
        before = fee;
        checked += 1;
    }
    assert_eq!(checked, 1_000_000_001);
}
