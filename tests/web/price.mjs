// Price book 3.1's arithmetic (web/price.js), with no browser: node tests/web/price.mjs
// What the program takes at release is one rate with a floor and no cap; the invoice is Control + Meter + Acceptance on
// value reconciled off chain + record lookups. The expected values are worked by hand in tests/data/billing_vectors.json,
// which src/knos/billing.py is held to as well (tests/test_billing.py).
// The fee of an order follows the build that is live: 0.30% with a floor of 0.05 (0.3.18, knos_pay 2.2), or the three
// tiers and the floor of 0.40 before it (0.3.14).
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), dir = mkdtempSync(join(tmpdir(), "price-"));
// price.js imports ./settle.js, which only the built site has: an empty one makes every constant "recorded"
writeFileSync(join(dir, "settle.js"), "export {};\n");
writeFileSync(join(dir, "price.js"), readFileSync(join(here, "../../web/price.js"), "utf8"));
const { priceConstants, priceBook, COLUMNS, effectiveFees, nettedFee, enforcedNow, orderFee, jobFee, feeParts, feeRate, feeWords, KEEPS, quote, meterCost, show, plain, RECORDED, RULE, PAYS, CONNECT, DEVNET, BILL, PLANS, yearEstimate, tiersOf, acceptanceFee, usd, centsOf, unitsOf } = await import(pathToFileURL(join(dir, "price.js")).href);

let failed = 0;
const same = (what, got, want) => { const ok = JSON.stringify(got) === JSON.stringify(want); if (!ok) failed++; console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : `: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`); };
const vectors = JSON.parse(readFileSync(join(here, "../data/billing_vectors.json"), "utf8")), book = vectors.book, chain = vectors.on_chain;
const c = priceConstants(), u = (n) => Math.round(n * 1e6), fee = (amount, bps = c.feeBps) => show(orderFee(u(amount), bps, c));

// ---- what the program takes at release -----------------------------------------------------------------------------
same("every constant is recorded when the client exports none", [...new Set(Object.values(c.source))], ["recorded"]);
same("one rate, 0.30%, a floor of 0.05, a Plan no lower than 0.10%, and an order of 100,000 at most", [c.feeBps, c.feeMin, c.planBpsMin, c.maxAmount], [chain.bps, chain.floor_units, chain.plan_bps_min, u(Number(chain.max_amount))]);
same("there is no tier and no maximum fee in the book", ["FEE_MAX", "FEE_TIER_1", "FEE_TIER_2", "FEE_BPS_2", "FEE_BPS_3"].filter((k) => k in RECORDED).concat(["feeMax"].filter((k) => k in c)).concat(c.tiered ? ["tiered"] : []), []);
same("with no version asked it is this tree's own rule, the 0.3.18 fee of knos_pay 2.2", [c.fee.release, c.fee.build, c.fee.live], ["0.3.18", "2.2", false]);
for (const [amount, want] of chain.fees) same(`a release of ${amount} pays ${want}`, show(orderFee(unitsOf(amount), c.feeBps, c)), want);
same("16.666666 still pays the floor, and it is rounded down", [fee(16.666666), show(orderFee(16_669_999, c.feeBps, c))], ["0.05", "0.050009"]);
same("a Plan at 0.10%: 100,000 pays 100.00, and 10 pays the floor", [fee(100000, 10), fee(10, 10)], ["100.00", "0.05"]);
same("the fee is one part", feeParts(u(5000), c.feeBps).map((p) => [p.of, p.bps, p.fee]), [[u(5000), 30, u(15)]]);
same("a client that exports the old rate does not change the book", (() => { const old = priceConstants({ FEE_BPS: 250, ORDER_FEE_MIN: 400_000, PLAN_BPS_MIN: 50 }); return [old.feeBps, old.feeMin, old.planBpsMin, old.source.feeBps]; })(), [30, 50_000, 10, "recorded"]);
// who gets what: the tip comes out of the fee, the payee receives the posted amount
const q = quote(u(5000), c);
same("5,000: the funder pays 5,015, the payee gets 5,000, the relay's tip comes out of the 15.00", [q.funderPays, q.payeeReceives, q.fee, q.tip + q.knos].map(show), ["5,015.00", "5,000.00", "15.00", "15.00"]);
same("the relay's tip is never more than the fee", [quote(u(5), c).tip <= quote(u(5), c).fee, quote(u(5), c).tipFirst <= quote(u(5), c).fee, quote(u(5), c).knos >= 0], [true, true, true]);
const eff = effectiveFees(c).map((r) => [r.amount, plain(r.fee), r.share]);
same("the fee as a share: 5 pays 1.00%, 20 and above pay 0.30%", eff, [[5, "0.05", "1.00%"], [20, "0.06", "0.30%"], [100, "0.30", "0.30%"], [1000, "3", "0.30%"], [5000, "15", "0.30%"], [100000, "300", "0.30%"]]);

// ---- the fee follows the build that is live -------------------------------------------------------------------------
same("a job's fee is the same rate and floor, out of the amount", [jobFee(u(20), c), jobFee(u(1000), c)], [u(0.06), u(3)]);
same("the rule in words", feeRate(c), "0.30% of the amount, at least 0.05");
same("one part, rounded down, with the constants named too", feeParts(1_000_000_099, 30, c).map((p) => p.fee), [3_000_000]);
// ... and while knos_pay 2.1 is live (the program answers version 1, or 0 for 2.0) it is the 0.3.14 fee, which the public program charges until the upgrade executes
const old = priceConstants(undefined, 1), was = (amount, bps = old.feeBps) => show(orderFee(u(amount), bps, old));
same("version 1 and version 0 are the 0.3.14 rule; 2 and later the 0.3.18 rule; a version given is a live answer", [0, 1, 2, 3].map((v) => [priceConstants(undefined, v).fee.release, priceConstants(undefined, v).fee.live]),
  [["0.3.14", true], ["0.3.14", true], ["0.3.18", true], ["0.3.18", true]]);
same("0.3.14, the tiers: 2.5% to 1,000, 1% to 50,000, 0.5% above; minimum 0.40", [old.feeBps, old.tier1, old.feeBps2, old.tier2, old.feeBps3, old.feeMin, old.tiered, old.planBpsMin], [250, u(1000), 100, u(50000), 50, u(0.4), true, 50]);
same("0.3.14: 5 pays the minimum", was(5), "0.40");
same("0.3.14: 16 is where 2.5% reaches the minimum", [was(15.99), was(16), was(16.04)], ["0.40", "0.40", "0.401"]);
same("0.3.14: 100 pays 2.50", was(100), "2.50");
same("0.3.14: 1,000 pays 25.00, and one more whole unit pays 1% of it", [was(1000), was(1001)], ["25.00", "25.01"]);
same("0.3.14: 5,000 pays 25 + 40 = 65.00", was(5000), "65.00");
same("0.3.14: 50,000 pays 25 + 490 = 515.00, and one more whole unit pays 0.5% of it", [was(50000), was(50001)], ["515.00", "515.005"]);
same("0.3.14: 100,000, the most an order holds on devnet, pays 515 + 250 = 765.00", was(100000), "765.00");
same("0.3.14: a Plan at 0.5%: 100 pays 0.50, 5,000 pays 5 + 40, 50,000 pays 5 + 490", [was(100, 50), was(5000, 50), was(50000, 50)], ["0.50", "45.00", "495.00"]);
same("0.3.14: each part is rounded down by itself", feeParts(1_000_000_099, 250, old).map((p) => p.fee), [25_000_000, 0, 0]);
same("0.3.14: a job pays 2.5%, at least 0.05, out of the amount", [jobFee(u(20), old), jobFee(u(1), old)], [u(0.5), u(0.05)]);
same("0.3.14: the rule in words", feeRate(old), "2.5% of the first 1,000, 1% to 50,000, 0.5% above, at least 0.40");
// the fee in a sentence is true on both sides of the upgrade, and says that an order keeps the rate of its funding
same("the fee in words, when nobody was asked: both rules and what decides", feeWords(null),
  "Fee: 0.30% of the amount, at least 0.05 test USDC, paid by the funder on top, once knos_pay 2.2 is live; until that upgrade executes the public program charges the 0.3.14 fee (2.5% of the first 1,000, 1% to 50,000, 0.5% above, at least 0.40). `knos status` says which build runs. Orders funded before the upgrade keep the rate fixed at their funding.");
same("the fee in words while 2.1 is live", feeWords(1),
  "Fee today: 2.5% of the first 1,000, 1% to 50,000, 0.5% above, at least 0.40 test USDC, paid by the funder on top (the 0.3.14 fee: knos_pay 2.2 is not live yet). From knos_pay 2.2: 0.30% of the amount, at least 0.05. Orders funded before the upgrade keep the rate fixed at their funding.");
same("the fee in words once 2.2 is live", feeWords(2), "Fee: 0.30% of the amount, at least 0.05 test USDC, paid by the funder on top (knos_pay 2.2 is live). Orders funded before the upgrade keep the rate fixed at their funding.");
same("every statement of the fee says what an older order keeps", [null, 0, 1, 2].every((v) => feeWords(v).endsWith(KEEPS)), true);
same("the effective fee under the 0.3.14 rule: 5 pays 8.00%, 20 and 1,000 pay 2.50%, 5,000 pays 1.30%, 100,000 pays 0.77%", effectiveFees(old).map((r) => [r.amount, plain(r.fee), r.share]),
  [[5, "0.40", "8.00%"], [20, "0.50", "2.50%"], [100, "2.50", "2.50%"], [1000, "25", "2.50%"], [5000, "65", "1.30%"], [100000, "765", "0.77%"]]);

// ---- the price book -------------------------------------------------------------------------------------------------
const market = readFileSync(join(here, "../../docs/MARKET.md"), "utf8");
same("the price book has six lines, in the book's order", priceBook().map((r) => r[0]), ["Check", "Meter", "Acceptance", "Record", "Control", "Pilot"]);
same("and they are the lines of tests/data/billing_vectors.json, five columns each", [priceBook(), COLUMNS], [vectors.lines, vectors.columns]);
same("Verify, Settle and Supplier connection are not lines", priceBook().map((r) => r[0]).filter((name) => vectors.removed.includes(name)), []);
const row = (name) => priceBook().find((r) => r[0] === name);
same("Check is free, forever, and nobody pays", row("Check").slice(2), ["free, forever", "nobody", "nowhere"]);
same("Acceptance never goes below 0.20%, nets small tickets, and Record is 0.10 a lookup paid per call", [/never goes below 0\.20%/.test(row("Acceptance")[2]), /one release per payee per period/.test(row("Acceptance")[2]), /^0\.10 USD a lookup, paid per call/.test(row("Record")[2]), /by subscription|hosted API/.test(row("Record").join(" "))], [true, true, true, false]);
same("Acceptance has no cap, the funder pays it on top, and the program enforces 0.30% and the floor", [/no cap$/.test(row("Acceptance")[2]), row("Acceptance")[3], /^knos_pay at release/.test(row("Acceptance")[4])], [true, "funder, on top of the amount", true]);
same("Control says Enterprise is not deliverable", [/^Team 25,000; Business 100,000; Enterprise from 400,000 /.test(row("Control")[2]), /not deliverable yet/.test(row("Control")[2])], [true, true]);
same("the Pilot is credited against year one", row("Pilot")[2], "2,500 USD, credited against year one");
same("no line is paid by a supplier, a payee or the rated party", priceBook().filter((r) => /supplier|payee|rated/.test(r[3])).map((r) => r[0]), []);
same("the rule is published with the book, in the document too", [RULE, market.includes(`**The rule: ${RULE}**`), PAYS, CONNECT, DEVNET], ["Knos never charges the party being rated.", true, "The rated party never pays.", "Connecting a supplier costs nothing.", "test money: 0 revenue"]);
same("every line of the price book is a row of docs/MARKET.md, word for word", priceBook().filter((r) => !market.includes(`| ${r.join(" | ")} |`)).map((r) => r[0]), []);

// ---- the billing rule: the numbers src/knos/billing.py gives ---------------------------------------------------------
same("the constants of the billing rule are the book's", [BILL.meterFree, BILL.meterPerThousandCents / 100_000, BILL.acceptBps.map((b) => b / 10_000), BILL.acceptAbove, BILL.acceptFloorCents / 100, BILL.recordCents / 100, BILL.control, BILL.pilot, BILL.benefitRule, BILL.netBelowCents / 100],
  [book.meter_free, Number(book.meter_price), book.acceptance_tiers.map((t) => Number(t[1])), book.acceptance_tiers.map((t) => Number(t[0])), Number(book.acceptance_floor), Number(book.record_price), Object.fromEntries(Object.entries(book.control).map(([k, v]) => [k, Number(v)])), Number(book.pilot), book.benefit_rule, Number(book.net_below)]);
same("the plans offered are the book's", PLANS.map((p) => p[0]), Object.keys(book.control));
const year = (y) => yearEstimate({ plan: y.in.plan, evaluations: y.in.evaluations, acceptedCents: centsOf(y.in.accepted), onChainPercent: y.in.on_chain_percent, lookups: y.in.lookups });
for (const y of vectors.years) {
  const e = year(y);
  same(`a year: ${y.name}`, { control: usd(e.control), meter: usd(e.meter), acceptance: usd(e.acceptance), paid_on_chain: usd(e.paidOnChain), rebate: usd(e.rebate), records: usd(e.records), total: usd(e.total), benefit_to_demand: usd(e.benefit) }, y.out);
}
same("the total is the lines added once, less the rebate: nothing released on chain is in it", vectors.years.every((y) => { const e = year(y); return e.total === e.control + e.meter + e.acceptance + e.records - e.rebate; }), true);
same("the worked customer pays 130,240.00 a year", usd(year(vectors.years[0]).total), "130,240.00");
// the tiers of a month, and a deliverable's own fee
same("20 million in a month: 1M at 0.30%, 19M at 0.20%, and no rate under 0.20%", tiersOf(2_000_000_000).map((t) => [t.rate, usd(t.of), usd(t.fee)]), [["0.30%", "1,000,000.00", "3,000.00"], ["0.20%", "19,000,000.00", "38,000.00"]]);
same("with no contract all of it pays 0.30%", tiersOf(2_000_000_000, false).map((t) => usd(t.of)), ["20,000,000.00", "0.00"]);
// small tickets, netted: one release per payee per period, the floor once
for (const [outcomes, fee, alone] of vectors.netting.rows) same(`netted: ${outcomes.length} outcomes of ${usd(outcomes[0])} pay ${usd(fee)}, not ${usd(alone)}`, [nettedFee(outcomes).fee, nettedFee(outcomes).individually], [fee, alone]);
same("an outcome of 20 or more is not small, and nothing is not a release", [nettedFee([2000]), nettedFee([])], [null, null]);
same("0.99 by itself pays 5.05% in fees; a hundred of them netted pay 0.30%", [(5 / 99 * 100).toFixed(2), (nettedFee(Array(100).fill(99)).fee / 9900 * 100).toFixed(2)], ["5.05", "0.30"]);
// who earns what at the floor, under both builds (the tip comes out of the fee; 0.30 on a payee's first payment)
for (const [build, version] of [["2.1", 1], ["2.2", 2]]) {
  const k = priceConstants(undefined, version);
  same(`knos_pay ${build}: fee, tip and fee owner on 5, 20, 100 and 1,000, and on a payee's first payment`, [5, 20, 100, 1000].map((a) => { const s = quote(u(a), k); return [usd(a * 100), show(s.fee), show(s.tip), show(s.knos), show(s.tipFirst), show(s.knosFirst)]; }), vectors.floor[build].rows);
}
same("under 2.2 the fee owner earns nothing at 16.66 and on a first payment of 100.00", [quote(u(16.66), c).knos, quote(u(16.67), c).knos > 0, quote(u(100), c).knosFirst, quote(u(100.01), c).knosFirst > 0], [0, true, 0, true]);
// the book's on-chain cell follows the build that is live
same("the on-chain cell: the book's own once 2.2 is live; today and after the next upgrade while 2.1 is; both when nobody answered; reading before", [enforcedNow(priceConstants(undefined, 2)), enforcedNow(priceConstants(undefined, 1)), enforcedNow(priceConstants()), enforcedNow(null)],
  [vectors.lines[2][4], "knos_pay at release (on chain today: 2.5% of the first 1,000, 1% to 50,000, 0.5% above, at least 0.40; after the next upgrade: 0.30% and the floor; volume rates are a rebate by contract, off chain)",
    "knos_pay at release (on chain until the next upgrade: 2.5% of the first 1,000, 1% to 50,000, 0.5% above, at least 0.40; after it: 0.30% and the floor; volume rates are a rebate by contract, off chain)", "knos_pay at release (reading the rate on chain today)"]);
same("a deliverable: the floor is 0.05, nothing for no value, and there is no cap", [0, 1, 500, 1667, 2000, 400_000_000].map((v) => usd(acceptanceFee(v))), ["0.00", "0.05", "0.05", "0.05", "0.06", "12,000.00"]);
same("a deliverable that crosses a tier pays each rate on its own part", usd(acceptanceFee(200_000_00, 900_000_00, true)), "500.00");
same("the Meter: 1,000,000 evaluations a month are 900,000 billable: 1,800.00", [meterCost(1e6).free, meterCost(1e6).billable, usd(meterCost(1e6).cost)], [100000, 900000, "1,800.00"]);
same("dollars typed with commas, a sign or cents are read exactly; anything else is not read", ["10,000,000", "$1,234.5", "0.07", "1e6", "-5", "1.234"].map(centsOf), [1_000_000_000, 123_450, 7, null, null, null]);
// the two words a revenue scenario is written with are spelled in halves here, so that this file does not hold them
const banned = new RegExp(["1,000 million", "\\b1B\\b", "\\bAR" + "R\\b", "\\bbil" + "lion USD a year", "One bil" + "lion"].join("|"));
same("no public page or price document prints a revenue scenario", ["docs/MARKET.md", "docs/PILOT.md", "docs/COMPARE.md", "docs/UNIT_COSTS.md", "web/pricing.js", "web/price.js", "src/knos/billing.py", "tests/data/billing_vectors.json"].filter((f) => banned.test(readFileSync(join(here, "../..", f), "utf8"))), []);
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
