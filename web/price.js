// The price book and the arithmetic of the calculators. Pure functions: nothing here reads the page or the network.
//
// WHERE THE NUMBERS COME FROM, in one place. Amounts are in millionths of a whole unit of the mint (USDC has six
// decimals), as the programs hold them. priceConstants() takes each constant from what sdk/settle exports (settle.js
// in the built site) and, for the ones the exported client does not have yet, from RECORDED below. RECORDED is the
// only place a price is typed in this site; tests/web/site.mjs compares every value in it with the programs' own
// source (programs-v2/knos_pay/src/lib.rs, programs-v2/knos_meter/src/lib.rs). When sdk/settle exports an order's
// constants (ORDER_FEE_MIN, FEE_TIER_1, FEE_TIER_2, FEE_BPS_2, FEE_BPS_3, TIP, TIP_FIRST, PLAN_BPS_MIN), they are
// used and `source` says "exported"; delete RECORDED then.
//
// The fee of an order is marginal, in three tiers, and the funder pays it on top of the amount: FEE_BPS (2.5%, or a
// Plan's lower rate) of the first FEE_TIER_1 (1,000), FEE_BPS_2 (1%) of what lies between FEE_TIER_1 and FEE_TIER_2
// (50,000), FEE_BPS_3 (0.5%) of what lies above; at least FEE_MIN (0.40); no maximum.
import * as settle from "./settle.js";

export const RECORDED = Object.freeze({
  FEE_BPS: 250, FEE_MIN: 400_000, FEE_TIER_1: 1_000_000_000, FEE_TIER_2: 50_000_000_000, FEE_BPS_2: 100, FEE_BPS_3: 50,
  MIN_AMOUNT: 5_000_000, MAX_AMOUNT: 100_000_000_000, TIP: 50_000, TIP_FIRST: 300_000, PLAN_BPS_MIN: 50,
  METER_FEE: 50_000, METER_PLAN_MIN: 20_000, METER_FREE: 10_000,
});

const number = (v) => (typeof v === "number" && Number.isSafeInteger(v) ? v : undefined);
const find = (lib, names) => { for (const holder of [lib?.v2, lib]) for (const n of names) { const v = number(holder?.[n]); if (v !== undefined) return v; } return undefined; };

// The constants in use, and where each came from. `lib`: what settle.js exports.
export function priceConstants(lib = settle) {
  // settle.js's plain FEE_MIN and MIN_AMOUNT are the first kind of job's (0.05 and 1): an order's are ORDER_* there
  const want = {
    feeBps: ["FEE_BPS"], feeMin: ["ORDER_FEE_MIN"], tier1: ["FEE_TIER_1"], tier2: ["FEE_TIER_2"], feeBps2: ["FEE_BPS_2"], feeBps3: ["FEE_BPS_3"],
    minAmount: ["ORDER_MIN_AMOUNT"], maxAmount: ["MAX_AMOUNT"], tip: ["TIP"], tipFirst: ["TIP_FIRST"], planBpsMin: ["PLAN_BPS_MIN"],
    meterFee: ["METER_FEE"], meterPlanMin: ["METER_PLAN_MIN"], meterFree: ["METER_FREE_PER_MONTH", "METER_FREE"],
  };
  const recorded = { feeBps: "FEE_BPS", feeMin: "FEE_MIN", tier1: "FEE_TIER_1", tier2: "FEE_TIER_2", feeBps2: "FEE_BPS_2", feeBps3: "FEE_BPS_3",
    minAmount: "MIN_AMOUNT", maxAmount: "MAX_AMOUNT", tip: "TIP", tipFirst: "TIP_FIRST", planBpsMin: "PLAN_BPS_MIN",
    meterFee: "METER_FEE", meterPlanMin: "METER_PLAN_MIN", meterFree: "METER_FREE" };
  const out = { source: {} };
  for (const [name, names] of Object.entries(want)) {
    const got = find(lib, names);
    out[name] = got ?? RECORDED[recorded[name]];
    out.source[name] = got === undefined ? "recorded" : "exported";
  }
  // a client built before the tiers has a MAX_AMOUNT of 500: the book's is the tiers' build, so take them together
  if (out.source.tier1 === "recorded") { out.maxAmount = RECORDED.MAX_AMOUNT; out.source.maxAmount = "recorded"; }
  return Object.freeze(out);
}

// The fee of an order: the funder pays it on top of the amount. As order_fee in programs-v2/knos_pay/src/lib.rs:
// each tier's part rounded down, then the floor. `bps` is the first tier's rate: the standard one, or a Plan's.
const part = (amount, bps) => Math.floor((amount * bps) / 10_000);
export function feeParts(amount, bps, c) {
  const first = Math.min(amount, c.tier1), second = Math.min(amount, c.tier2) - first, third = amount - first - second;
  return [{ of: first, bps, fee: part(first, bps) }, { of: second, bps: c.feeBps2, fee: part(second, c.feeBps2) }, { of: third, bps: c.feeBps3, fee: part(third, c.feeBps3) }];
}
export const orderFee = (amount, bps, c) => Math.max(feeParts(amount, bps, c).reduce((sum, p) => sum + p.fee, 0), c.feeMin);

// What an amount of `amount` units costs and pays out, at `bps` (the standard rate unless a contract lowers it).
// The tip is the relay's, out of the fee, never more than the fee; the rest of the fee is Knos's.
export function quote(amount, c, bps = c.feeBps) {
  const fee = orderFee(amount, bps, c), tip = Math.min(c.tip, fee), first = Math.min(c.tipFirst, fee);
  return { amount, bps, fee, funderPays: amount + fee, payeeReceives: amount, tip, tipFirst: first, knos: fee - tip, knosFirst: fee - first };
}

// The price book, row by row, in the words of docs/MARKET.md ("The price book"): [line, unit, price]. The Meter and
// Settle prices are written from the programs' constants; Control and the Pilot are contract prices nothing on chain
// enforces, so they are words here and nowhere else in the site.
const whole = (units) => (units / 1e6).toLocaleString("en-US");
export function priceBook(c) {
  return [
    ["Check", "pull request checked", "free"],
    ["Meter", "evaluation", `${c.meterFree.toLocaleString("en-US")} a month free per organisation, then ${plain(c.meterFee)} USD; ${plain(c.meterPlanMin)} on a committed-volume plan`],
    ["Control", "organisation", "25,000 USD a year entry, 80,000 organisation tier (nobody has bought it)"],
    ["Settle", "dollar settled, paid by the funder on top", `${percent(c.feeBps)} of the first ${whole(c.tier1)}, ${percent(c.feeBps2)} from ${whole(c.tier1)} to ${whole(c.tier2)}, ${percent(c.feeBps3)} above; minimum ${plain(c.feeMin)}`],
    ["Pilot", "one buyer and its suppliers, 30 days", "2,500 USD, invoiced off chain: reconcile the buyer's accepted work from more than one supplier, name every mismatch between acceptance and billing, deliver a statement both sides verify (nobody has bought it; there is no legal entity to invoice from yet)"],
    ["Advance, Assurance", "", "not offered; needs loss history"],
  ];
}

// The effective settle fee at the standard rate, shown before funding: what an order of each size pays, and that as
// a share of the order. A small order pays the minimum, which is a far larger share than the first tier's rate.
export const EFFECTIVE = [5, 20, 1_000, 5_000, 50_000];      // whole units
export function effectiveFees(c, amounts = EFFECTIVE) {
  return amounts.map((amount) => { const fee = orderFee(amount * 1e6, c.feeBps, c); return { amount, fee, share: `${((fee / (amount * 1e6)) * 100).toFixed(2)}%` }; });
}

// Evaluations a month at the Meter: an owner's first `meterFree` are free; each after costs `rate`.
export function meterCost(evaluations, c, rate = c.meterFee) {
  const billable = Math.max(0, evaluations - c.meterFree);
  return { evaluations, free: Math.min(evaluations, c.meterFree), billable, rate, cost: billable * rate };
}

// "20", "7.5": digits with at most six decimals, in millionths; null for anything else or a number too big to hold.
export function unitsOf(text) {
  const m = /^(\d{1,9})(?:\.(\d{1,6}))?$/.exec(String(text).trim());
  return m ? Number(m[1]) * 1_000_000 + Number((m[2] || "").padEnd(6, "0") || 0) : null;
}

// A rate typed as a percentage ("1.5", "0.5"): basis points, at most two decimals; null for anything else.
export function bpsOf(text) {
  const m = /^(\d{1,2})(?:\.(\d{1,2}))?$/.exec(String(text).trim());
  return m ? Number(m[1]) * 100 + Number((m[2] || "").padEnd(2, "0") || 0) : null;
}

// Whole units with at least two decimals and no more than six, no trailing zeros past the second: 400000 -> "0.40".
export function show(units) {
  const whole = Math.trunc(units / 1_000_000), frac = String(units % 1_000_000).padStart(6, "0").replace(/0+$/, "").padEnd(2, "0");
  return `${whole.toLocaleString("en-US")}.${frac}`;
}
// as `show`, but a whole number of units has no decimals: 25000000 -> "25"
export const plain = (units) => (units % 1_000_000 === 0 ? String(units / 1_000_000) : show(units));
export const percent = (bps) => `${(bps / 100).toFixed(bps % 10 === 0 ? (bps % 100 === 0 ? 0 : 1) : 2)}%`;
