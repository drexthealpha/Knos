// Price book 3 and the arithmetic of the calculators. Pure functions: nothing here reads the page or the network.
//
// WHERE THE NUMBERS COME FROM, in one place.
//   BILL      the price book's own numbers (docs/MARKET.md, "The price book"; src/knos/billing.py holds the same):
//             Meter, Acceptance and its volume rates, Record, Control, Pilot. Contract prices, typed once, here.
//   on chain  what knos_pay takes at release, in millionths of a whole unit of the mint (USDC has six decimals), as
//             the program holds it. priceConstants() takes each constant from what sdk/settle exports (settle.js in
//             the built site) and, for the ones the exported client does not have, from RECORDED below. The three
//             METER_* values are knos_meter's own on devnet: that program is unchanged, the price book's Meter is
//             charged from prepaid credits, and its numbers are BILL's.
// tests/data/billing_vectors.json holds every row and number; this file and the Python are both tested against it.
//
// THE FEE FOLLOWS THE BUILD THAT IS LIVE. knos_pay has two fee rules (settle.js v2.FEE_RULES):
//   0.3.18 (knos_pay 2.2)  0.30% of the amount, at least 0.05; one rate, no tiers; a Plan no lower than 0.10%
//   0.3.14 (knos_pay 2.1)  three tiers: 2.5% up to 1,000, 1% to 50,000, 0.5% above, at least 0.40
// The public programs charge the 0.3.14 fee until the upgrade to 2.2 executes. priceConstants(lib, version) gives the
// constants of the rule the program of `version` applies (web/version.js asks the program; web/fee_live.js asks it
// and, when devnet does not answer, reads upgrades.json); with no version it gives this tree's own, the 0.3.18 one.
// The funder pays the fee on top of the amount. Orders funded before the upgrade keep the rate fixed at their funding.
import * as settle from "./settle.js";

export const RECORDED = Object.freeze({
  MIN_AMOUNT: 5_000_000, MAX_AMOUNT: 100_000_000_000, TIP: 50_000, TIP_FIRST: 300_000,
  METER_FEE: 50_000, METER_PLAN_MIN: 20_000, METER_FREE: 10_000,
});
// the two rules as settle.js has them, for a settle.js built before it exported them
const RULES = Object.freeze({
  new: Object.freeze({ release: "0.3.18", build: "2.2", bps: 30, floor: 50_000, planMin: 10, jobBps: 30, jobFloor: 50_000, tiers: Object.freeze([]) }),
  old: Object.freeze({ release: "0.3.14", build: "2.1", bps: 250, floor: 400_000, planMin: 50, jobBps: 250, jobFloor: 50_000, tiers: Object.freeze([[1_000_000_000, 100], [50_000_000_000, 50]]) }),
});
export const FEE_VERSION = 2;                 // what knos_pay's Version logs from the build with the 0.3.18 fee on
export const KEEPS = "Orders funded before the upgrade keep the rate fixed at their funding.";
const NO_TIER = Number.MAX_SAFE_INTEGER;      // a rule with no tiers: everything is the first part

/** The fee rule of the knos_pay that answered `version`: the 0.3.18 one from 2 up or when nobody was asked, the 0.3.14 one below. */
export function feeRule(version, lib = settle) {
  const which = version === null || version === undefined || version >= FEE_VERSION ? "new" : "old";
  return lib?.v2?.FEE_RULES?.[which] ?? RULES[which];
}

const number = (v) => (typeof v === "number" && Number.isSafeInteger(v) ? v : undefined);
const find = (lib, names) => { for (const holder of [lib?.v2, lib]) for (const n of names) { const v = number(holder?.[n]); if (v !== undefined) return v; } return undefined; };

// The constants in use, and where each came from. `lib`: what settle.js exports. `version`: what the program answered
// to Version (null or undefined: nobody was asked). `fee` says which rule these are: { release, build, version, live }
// with live true when a program or the feed was asked and false when the rule is only this tree's own.
export function priceConstants(lib = settle, version = undefined) {
  const want = {
    minAmount: ["ORDER_MIN_AMOUNT"], maxAmount: ["MAX_AMOUNT"], tip: ["TIP"], tipFirst: ["TIP_FIRST"],
    meterFee: ["METER_FEE"], meterPlanMin: ["METER_PLAN_MIN"], meterFree: ["METER_FREE_PER_MONTH", "METER_FREE"],
  };
  const recorded = { minAmount: "MIN_AMOUNT", maxAmount: "MAX_AMOUNT", tip: "TIP", tipFirst: "TIP_FIRST",
    meterFee: "METER_FEE", meterPlanMin: "METER_PLAN_MIN", meterFree: "METER_FREE" };
  const out = { source: {} };
  for (const [name, names] of Object.entries(want)) {
    const got = find(lib, names);
    out[name] = got ?? RECORDED[recorded[name]];
    out.source[name] = got === undefined ? "recorded" : "exported";
  }
  // a client built before orders has a MAX_AMOUNT of 500: the book's is the orders' build
  if (out.source.minAmount === "recorded") { out.maxAmount = RECORDED.MAX_AMOUNT; out.source.maxAmount = "recorded"; }
  const rule = feeRule(version, lib), [t1, t2] = rule.tiers, from = lib?.v2?.FEE_RULES ? "exported" : "recorded";
  Object.assign(out, { feeBps: rule.bps, feeMin: rule.floor, planBpsMin: rule.planMin, jobBps: rule.jobBps, jobMin: rule.jobFloor, tiered: rule.tiers.length > 0,
    tier1: t1 ? t1[0] : NO_TIER, feeBps2: t1 ? t1[1] : rule.bps, tier2: t2 ? t2[0] : NO_TIER, feeBps3: t2 ? t2[1] : rule.bps });
  for (const name of ["feeBps", "feeMin", "planBpsMin", "tier1", "tier2", "feeBps2", "feeBps3"]) out.source[name] = from;
  out.fee = Object.freeze({ release: rule.release, build: rule.build, version: version ?? null, live: version !== null && version !== undefined });
  return Object.freeze(out);
}

// The fee of an order: the funder pays it on top of the amount. As order_fee in programs-v2/knos_pay/src/lib.rs:
// each part rounded down, then the floor (the 0.3.18 rule has one part; so has a call that names no constants). `bps` is the rate: the standard one, or a Plan's (under the 0.3.14 rule
// the first tier's only; the 0.3.18 rule has one part, the whole amount).
const part = (amount, bps) => Math.floor((amount * bps) / 10_000);
export function feeParts(amount, bps, c) {
  if (!c || !c.tiered) return [{ of: amount, bps, fee: part(amount, bps) }];
  const first = Math.min(amount, c.tier1), second = Math.min(amount, c.tier2) - first, third = amount - first - second;
  return [{ of: first, bps, fee: part(first, bps) }, { of: second, bps: c.feeBps2, fee: part(second, c.feeBps2) }, { of: third, bps: c.feeBps3, fee: part(third, c.feeBps3) }];
}
export const orderFee = (amount, bps, c) => Math.max(feeParts(amount, bps, c).reduce((sum, p) => sum + p.fee, 0), c.feeMin);
/** The fee of a job, taken out of its amount, under the rule of `c`. */
export const jobFee = (amount, c) => Math.min(Math.max(part(amount, c.jobBps), c.jobMin), amount);

const pct2 = (bps) => `${bps < 50 ? (bps / 100).toFixed(2) : bps / 100}%`;        // 30 -> "0.30%", 50 -> "0.5%", 250 -> "2.5%"
/** The rule of `c` as a rate: "0.30% of the amount, at least 0.05", or the 0.3.14 tiers. As knos.fees.Rule.rate. */
export function feeRate(c, bps = c.feeBps) {
  if (!c.tiered) return `${pct2(bps)} of the amount, at least ${show(c.feeMin)}`;
  return `${pct2(bps)} of the first ${(c.tier1 / 1e6).toLocaleString("en-US")}, ${pct2(c.feeBps2)} to ${(c.tier2 / 1e6).toLocaleString("en-US")}, ${pct2(c.feeBps3)} above, at least ${show(c.feeMin)}`;
}
/** The fee in plain words, true whichever build is live: as knos.fees.words. `version`: what the program or the feed
 *  answered; null or undefined says both rules and what decides between them. */
export function feeWords(version, lib = settle) {
  const now = priceConstants(lib, FEE_VERSION), was = priceConstants(lib, FEE_VERSION - 1);
  if (version === null || version === undefined) {
    return `Fee: ${feeRate(now)} test USDC, paid by the funder on top, once knos_pay ${now.fee.build} is live; until that upgrade executes the public program charges the ${was.fee.release} fee (${feeRate(was)}). \`knos status\` says which build runs. ${KEEPS}`;
  }
  if (version >= FEE_VERSION) return `Fee: ${feeRate(now)} test USDC, paid by the funder on top (knos_pay ${now.fee.build} is live). ${KEEPS}`;
  return `Fee today: ${feeRate(was)} test USDC, paid by the funder on top (the ${was.fee.release} fee: knos_pay ${now.fee.build} is not live yet). From knos_pay ${now.fee.build}: ${feeRate(now)}. ${KEEPS}`;
}

/** One line under a fee shown before funding: which rule the number is, and the other rule's number when it differs.
 *  True on both sides of the upgrade: `c.fee.live` says whether a program or the feed was asked. */
export function feeNote(units, c, lib = settle) {
  const other = priceConstants(lib, c.fee.release === "0.3.18" ? FEE_VERSION - 1 : FEE_VERSION), their = orderFee(units, other.feeBps, other);
  if (c.fee.release === "0.3.18") {
    return c.fee.live ? `The program on devnet charges this now (knos_pay ${c.fee.build}). ${KEEPS}`
      : `This is the fee from knos_pay ${c.fee.build}. Until that upgrade is live the public program charges ${show(their)} on this order. ${KEEPS}`;
  }
  return `The program on devnet charges this now (the ${c.fee.release} fee). From knos_pay ${other.fee.build} this order pays ${show(their)}. ${KEEPS}`;
}

/** The one line a page adds when the fee it shows is not the fee of this tree's build: { label, rate, fee } or null.
 *  `c` is the rule shown (web/fee_live.js). The 0.3.14 rule live: the next upgrade's rule and, for `units`, its fee.
 *  Nobody answered (c.fee.live false): the page shows the 0.3.18 rule, and the line is the rule charged until then. */
export function feeNext(c, units = null, lib = settle) {
  if (c.fee.release === "0.3.18" && c.fee.live) return null;
  const old = c.fee.release !== "0.3.18", other = priceConstants(lib, old ? FEE_VERSION : FEE_VERSION - 1);
  return { label: old ? "After the next upgrade" : "Until the next upgrade", rate: feeRate(other), fee: units === null ? null : orderFee(units, other.feeBps, other), release: other.fee.release };
}

// What an amount of `amount` units costs and pays out, at `bps` (the standard rate unless a contract lowers it).
// The tip is the relay's, out of the fee, never more than the fee; the rest of the fee is Knos's.
export function quote(amount, c, bps = c.feeBps) {
  const fee = orderFee(amount, bps, c), tip = Math.min(c.tip, fee), first = Math.min(c.tipFirst, fee);
  return { amount, bps, fee, funderPays: amount + fee, payeeReceives: amount, tip, tipFirst: first, knos: fee - tip, knosFirst: fee - first };
}

// The price book's numbers. Rates are in basis points, money in whole USD unless a name says cents.
export const BILL = Object.freeze({
  meterFree: 100_000, meterPerThousandCents: 200,                        // 0.002 USD an evaluation: 2.00 USD a thousand
  acceptBps: Object.freeze([30, 20, 10]), acceptAbove: Object.freeze([0, 1_000_000, 10_000_000]), acceptFloorCents: 5,      // marginal, by the month; no cap
  recordCents: 25,
  control: Object.freeze({ none: 0, team: 25_000, business: 100_000, enterprise: 400_000 }),     // USD a year; Enterprise: from
  pilot: 2_500, benefitRule: 3,
});
export const PLANS = Object.freeze([["none", "No plan"], ["team", "Team"], ["business", "Business"], ["enterprise", "Enterprise"]]);
const thousands = (n) => n.toLocaleString("en-US");
function rate(bps) { return `${(bps / 100).toFixed(2)}%`; }
const short = (n) => (n >= 1_000_000 ? `${n / 1_000_000}M` : thousands(n));
export const COLUMNS = Object.freeze(["Line", "Unit", "Price", "Who pays", "Where it is enforced"]);
// The price book, row by row, in the words of docs/MARKET.md and of src/knos/billing.py (BOOK): the five COLUMNS.
export function priceBook() {
  const k = BILL.control, [r0, r1, r2] = BILL.acceptBps, [, a1, a2] = BILL.acceptAbove;
  return [
    ["Check", "pull request or artifact checked", "free, forever", "nobody", "nowhere"],
    ["Meter", "evaluation", `${thousands(BILL.meterFree)} a month free per organisation, then ${BILL.meterPerThousandCents / 100_000} USD`, "buyer", "prepaid credits"],
    ["Acceptance", "dollar released or reconciled against a signed acceptance", `${rate(r0)}; by contract ${rate(r1)} above ${short(a1)} a month and ${rate(r2)} above ${short(a2)} a month; floor ${(BILL.acceptFloorCents / 100).toFixed(2)} USD; no cap`,
      "funder, on top of the amount", `knos_pay at release (on chain: ${rate(r0)} and the floor; volume rates are a rebate by contract, off chain)`],
    ["Record", "lookup of a supplier's delivery record through the hosted API", `${(BILL.recordCents / 100).toFixed(2)} USD, or by subscription (the public record page and its file are free)`,
      "the buyer, marketplace or insurer reading it", "API (not built: a static file today)"],
    ["Control", "organisation, per year", `Team ${thousands(k.team)}; Business ${thousands(k.business)}; Enterprise from ${thousands(k.enterprise)} (not deliverable yet: it needs single sign-on, private deployment and support that do not exist)`, "buyer", "contract"],
    ["Pilot", "one buyer, two suppliers, 30 days, one reconciled invoice", `${thousands(BILL.pilot)} USD, credited against year one`, "buyer", "contract"],
  ];
}
// The rule the book is published with (docs/MARKET.md, section 3), and the same in five words.
export const RULE = "Knos never charges the party being rated.";
export const PAYS = "The rated party never pays.";
export const CONNECT = "Connecting a supplier costs nothing.";
export const DEVNET = "test money: 0 revenue";

// ---- the billing rule -------------------------------------------------------------------------------------------------
// Acceptance at the marginal rates on the first `cents` of a period of `months` months, in ten-thousandths of a cent
// (cents x basis points), so that every figure is a whole number. `volume`: by contract; otherwise 0.30% of all of it.
function marginal(cents, volume, months) {
  if (!volume) return cents * BILL.acceptBps[0];
  const edge = BILL.acceptAbove.map((usd) => usd * 100 * months);
  let sum = 0;
  for (let n = 0; n < edge.length; n++) {
    const end = n + 1 < edge.length ? Math.min(cents, edge[n + 1]) : cents;
    if (end > edge[n]) sum += (end - edge[n]) * BILL.acceptBps[n];
  }
  return sum;
}
const halfUp = (tenThousandths) => Math.floor((tenThousandths + 5_000) / 10_000);
// How a month's value falls into the tiers: [{ bps, rate, above, of, fee }], `of` and `fee` in whole cents.
export function tiersOf(monthCents, volume = true) {
  return BILL.acceptBps.map((bps, n) => {
    const start = BILL.acceptAbove[n] * 100, end = n + 1 < BILL.acceptBps.length ? BILL.acceptAbove[n + 1] * 100 : Infinity;
    const of = volume || n === 0 ? Math.max(0, Math.min(monthCents, volume ? end : Infinity) - start) : 0;
    return { bps, rate: rate(bps), above: BILL.acceptAbove[n], of, fee: halfUp(of * bps) };
  });
}
// Acceptance on one deliverable of `cents` that lies above the first `belowCents` of its month: at least the floor.
export const acceptanceFee = (cents, belowCents = 0, volume = false) => (cents > 0 ? Math.max(BILL.acceptFloorCents, halfUp(marginal(belowCents + cents, volume, 1) - marginal(belowCents, volume, 1))) : 0);

// THE BILLING RULE for a year, as `estimate` in src/knos/billing.py: Control + Meter + Acceptance on value reconciled
// off chain + record lookups, less the volume rebate on value released on chain. In whole cents. `evaluations` and
// `lookups`: a month's; `acceptedCents`: accepted value for the YEAR; `onChainPercent`: the share of it the program
// released, which paid 0.30% there and is never charged again. A plan is a contract: it brings the volume rates.
// Twelve equal months, and no deliverable small enough to pay the floor.
export function yearEstimate({ plan = "none", evaluations = 0, acceptedCents = 0, onChainPercent = 0, lookups = 0 }) {
  const control = BILL.control[plan] * 100, volume = plan !== "none";
  const billable = Math.max(0, evaluations - BILL.meterFree), meter = Math.floor((billable * BILL.meterPerThousandCents * 12 + 500) / 1000);
  const released = Math.floor((acceptedCents * onChainPercent) / 100), reconciled = acceptedCents - released;
  const acceptance = halfUp(marginal(acceptedCents, volume, 12) - marginal(released, volume, 12));
  const paidOnChain = halfUp(released * BILL.acceptBps[0]);
  const owed = Math.max(0, halfUp(released * BILL.acceptBps[0] - marginal(released, volume, 12)));
  const records = lookups * BILL.recordCents * 12, charges = control + meter + acceptance + records, rebate = Math.min(owed, charges);
  const total = charges - rebate;
  return { plan, volume, evaluations, billable, control, meter, released, reconciled, acceptance, paidOnChain, rebate, records, total,
    tiers: tiersOf(Math.round(acceptedCents / 12), volume), benefit: total * BILL.benefitRule, deliverable: plan !== "enterprise" };
}
// whole cents as USD: 13024000 -> "130,240.00"
export const usd = (cents) => `${Math.trunc(cents / 100).toLocaleString("en-US")}.${String(cents % 100).padStart(2, "0")}`;
// "10,000,000", "1234.5": whole cents, or null for anything else or a number too big to hold exactly
export function centsOf(text) {
  const m = /^(\d{1,12})(?:\.(\d{1,2}))?$/.exec(String(text).replace(/[,\s$]/g, ""));
  return m ? Number(m[1]) * 100 + Number((m[2] || "").padEnd(2, "0") || 0) : null;
}

// What the program takes on a release of each size, and that as a share of it: under 16.67 the floor is the fee.
export const EFFECTIVE = [5, 20, 100, 1_000, 5_000, 100_000];      // whole units
export function effectiveFees(c, amounts = EFFECTIVE) {
  return amounts.map((amount) => { const fee = orderFee(amount * 1e6, c.feeBps, c); return { amount, fee, share: `${((fee / (amount * 1e6)) * 100).toFixed(2)}%` }; });
}

// Evaluations a month at the Meter: an organisation's first 100,000 are free; each after costs 0.002. Cost in cents.
export function meterCost(evaluations) {
  const billable = Math.max(0, evaluations - BILL.meterFree);
  return { evaluations, free: Math.min(evaluations, BILL.meterFree), billable, cost: Math.floor((billable * BILL.meterPerThousandCents + 500) / 1000) };
}

// "20", "7.5": digits with at most six decimals, in millionths; null for anything else or a number too big to hold.
export function unitsOf(text) {
  const m = /^(\d{1,9})(?:\.(\d{1,6}))?$/.exec(String(text).trim());
  return m ? Number(m[1]) * 1_000_000 + Number((m[2] || "").padEnd(6, "0") || 0) : null;
}

// A rate typed as a percentage ("0.3", "0.15"): basis points, at most two decimals; null for anything else.
export function bpsOf(text) {
  const m = /^(\d{1,2})(?:\.(\d{1,2}))?$/.exec(String(text).trim());
  return m ? Number(m[1]) * 100 + Number((m[2] || "").padEnd(2, "0") || 0) : null;
}

// Whole units with at least two decimals and no more than six, no trailing zeros past the second: 50000 -> "0.05".
export function show(units) {
  const whole = Math.trunc(units / 1_000_000), frac = String(units % 1_000_000).padStart(6, "0").replace(/0+$/, "").padEnd(2, "0");
  return `${whole.toLocaleString("en-US")}.${frac}`;
}
// as `show`, but a whole number of units has no decimals: 25000000 -> "25"
export const plain = (units) => (units % 1_000_000 === 0 ? String(units / 1_000_000) : show(units));
export const percent = (bps) => `${(bps / 100).toFixed(bps % 10 === 0 ? (bps % 100 === 0 ? 0 : 1) : 2)}%`;
// a rate of the price book, always with two decimals: 30 -> "0.30%"
export const rateOf = rate;
