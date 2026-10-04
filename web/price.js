// The price book and the arithmetic of the calculators. Pure functions: nothing here reads the page or the network.
//
// WHERE THE NUMBERS COME FROM, in one place. Amounts are in millionths of a whole unit of the mint (USDC has six
// decimals), as the programs hold them. priceConstants() takes each constant from what sdk/settle exports (settle.js
// in the built site) and, for the ones the exported client does not have yet, from RECORDED below. RECORDED is the
// only place a price is typed in this site; tests/web/site.mjs compares every value in it with the programs' own
// source (programs-v2/knos_pay/src/lib.rs, programs-v2/knos_meter/src/lib.rs). When sdk/settle exports the 2.1
// constants (ORDER_FEE_MIN or FEE_MIN beside FEE_MAX, ORDER_FEE_MAX, TIP, TIP_FIRST, PLAN_BPS_MIN), they are used
// and `source` says "exported"; delete RECORDED then.
import * as settle from "./settle.js";

export const RECORDED = Object.freeze({
  FEE_BPS: 250, FEE_MIN: 400_000, FEE_MAX: 25_000_000, MIN_AMOUNT: 5_000_000, MAX_AMOUNT: 500_000_000, TIP: 50_000, TIP_FIRST: 300_000, PLAN_BPS_MIN: 50,
  METER_FEE: 50_000, METER_PLAN_MIN: 20_000, METER_FREE: 10_000,
});

const number = (v) => (typeof v === "number" && Number.isSafeInteger(v) ? v : undefined);
const find = (lib, names) => { for (const holder of [lib?.v2, lib]) for (const n of names) { const v = number(holder?.[n]); if (v !== undefined) return v; } return undefined; };

// The constants in use, and where each came from. `lib`: what settle.js exports.
export function priceConstants(lib = settle) {
  // today's FEE_MIN and MIN_AMOUNT of settle.js are the first kind of job's (0.05 and 1): an order's are ORDER_*
  // there, or the plain names once FEE_MAX is exported beside them
  const orders = find(lib, ["FEE_MAX", "ORDER_FEE_MAX"]) !== undefined;
  const want = {
    feeBps: ["FEE_BPS"], feeMin: orders ? ["ORDER_FEE_MIN", "FEE_MIN"] : ["ORDER_FEE_MIN"], feeMax: ["ORDER_FEE_MAX", "FEE_MAX"],
    minAmount: orders ? ["ORDER_MIN_AMOUNT", "MIN_AMOUNT"] : ["ORDER_MIN_AMOUNT"], maxAmount: ["MAX_AMOUNT"], tip: ["TIP"], tipFirst: ["TIP_FIRST"], planBpsMin: ["PLAN_BPS_MIN"],
    meterFee: ["METER_FEE"], meterPlanMin: ["METER_PLAN_MIN"], meterFree: ["METER_FREE_PER_MONTH", "METER_FREE"],
  };
  const recorded = { feeBps: "FEE_BPS", feeMin: "FEE_MIN", feeMax: "FEE_MAX", minAmount: "MIN_AMOUNT", maxAmount: "MAX_AMOUNT", tip: "TIP", tipFirst: "TIP_FIRST", planBpsMin: "PLAN_BPS_MIN",
    meterFee: "METER_FEE", meterPlanMin: "METER_PLAN_MIN", meterFree: "METER_FREE" };
  const out = { source: {} };
  for (const [name, names] of Object.entries(want)) {
    const got = find(lib, names);
    out[name] = got ?? RECORDED[recorded[name]];
    out.source[name] = got === undefined ? "recorded" : "exported";
  }
  return Object.freeze(out);
}

// The fee of an order (2.1): the funder pays it on top of the amount. As order_fee in src/knos/settle/v2/pay.py.
export const orderFee = (amount, bps, c) => Math.min(Math.max(Math.floor((amount * bps) / 10_000), c.feeMin), c.feeMax);

// What an amount of `amount` units costs and pays out, at `bps` (the standard rate unless a contract lowers it).
// The tip is the relay's, out of the fee, never more than the fee; the rest of the fee is Knos's.
export function quote(amount, c, bps = c.feeBps) {
  const fee = orderFee(amount, bps, c), tip = Math.min(c.tip, fee), first = Math.min(c.tipFirst, fee);
  return { amount, bps, fee, funderPays: amount + fee, payeeReceives: amount, tip, tipFirst: first, knos: fee - tip, knosFirst: fee - first };
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
