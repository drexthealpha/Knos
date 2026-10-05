// The price book's arithmetic (web/price.js), with no browser: node tests/web/price.mjs
// The fee of an order is marginal in three tiers and has a floor and no cap; the expected values are worked by hand
// from the price book (docs/MARKET.md) and are the ones order_fee in programs-v2/knos_pay/src/lib.rs must give.
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), dir = mkdtempSync(join(tmpdir(), "price-"));
// price.js imports ./settle.js, which only the built site has: an empty one makes every constant "recorded"
writeFileSync(join(dir, "settle.js"), "export {};\n");
writeFileSync(join(dir, "price.js"), readFileSync(join(here, "../../web/price.js"), "utf8"));
const { priceConstants, priceBook, effectiveFees, orderFee, feeParts, quote, meterCost, show, plain, RECORDED, RULE } = await import(pathToFileURL(join(dir, "price.js")).href);

let failed = 0;
const same = (what, got, want) => { const ok = JSON.stringify(got) === JSON.stringify(want); if (!ok) failed++; console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : `: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`); };
const c = priceConstants(), u = (n) => Math.round(n * 1e6), fee = (amount, bps = c.feeBps) => show(orderFee(u(amount), bps, c));

same("every constant is recorded when the client exports none", [...new Set(Object.values(c.source))], ["recorded"]);
same("the tiers: 2.5% to 1,000, 1% to 50,000, 0.5% above; minimum 0.40", [c.feeBps, c.tier1, c.feeBps2, c.tier2, c.feeBps3, c.feeMin], [250, u(1000), 100, u(50000), 50, u(0.4)]);
same("there is no maximum fee in the book", ["FEE_MAX" in RECORDED, "feeMax" in c], [false, false]);
// the floor: 0.40 is the fee up to 16
same("5 pays the minimum", fee(5), "0.40");
same("16 is where 2.5% reaches the minimum", [fee(15.99), fee(16), fee(16.04)], ["0.40", "0.40", "0.401"]);
same("100 pays 2.50", fee(100), "2.50");
// the tier edges
same("1,000 pays 25.00, and one more whole unit pays 1% of it", [fee(1000), fee(1001)], ["25.00", "25.01"]);
same("5,000 pays 25 + 40 = 65.00", fee(5000), "65.00");
same("50,000 pays 25 + 490 = 515.00, and one more whole unit pays 0.5% of it", [fee(50000), fee(50001)], ["515.00", "515.005"]);
same("100,000, the most an order holds on devnet, pays 515 + 250 = 765.00", fee(100000), "765.00");
// a Plan lowers the first tier's rate only
same("a Plan at 0.5%: 100 pays 0.50, 5,000 pays 5 + 40, 50,000 pays 5 + 490", [fee(100, 50), fee(5000, 50), fee(50000, 50)], ["0.50", "45.00", "495.00"]);
same("a Plan at 1.5%: 1,000 pays 15.00", fee(1000, 150), "15.00");
same("each part is rounded down by itself", feeParts(1_000_000_099, 250, c).map((p) => p.fee), [25_000_000, 0, 0]);
// who gets what: the tip comes out of the fee, the payee receives the posted amount
const q = quote(u(5000), c);
same("5,000: the funder pays 5,065, the payee gets 5,000, the relay 0.05 (0.30 on a first payment), Knos the rest",
  [q.funderPays, q.payeeReceives, q.tip, q.tipFirst, q.knos, q.knosFirst].map(show), ["5,065.00", "5,000.00", "0.05", "0.30", "64.95", "64.70"]);
same("the meter: 1,000,000 evaluations a month are 990,000 billable: 49,500 at 0.05 and 19,800 at 0.02",
  [meterCost(1e6, c).billable, show(meterCost(1e6, c).cost), show(meterCost(1e6, c, c.meterPlanMin).cost)], [990000, "49,500.00", "19,800.00"]);
// the price book's rows and the effective fee, as docs/MARKET.md prints them
const market = readFileSync(join(here, "../../docs/MARKET.md"), "utf8");
same("the price book has eight lines, in the book's order", priceBook(c).map((r) => r[0]), ["Check", "Meter", "Verify", "Control", "Supplier connection", "Pilot", "Settle", "Index data, Advance, Assurance"]);
const row = (name) => priceBook(c).find((r) => r[0] === name)[2];
same("Check is free, forever", row("Check"), "free, forever");
same("Verify is a share of the outcome billing verified, and says nobody has bought it", [/^0\.5% to 1\.0%, the greater of this and the Meter fee, capped per deliverable/.test(row("Verify")), /proposed; nobody has bought it/.test(row("Verify"))], [true, true]);
same("Control has three tiers, and says Enterprise is not deliverable", [/^Team 25,000 USD; Business 80,000; Enterprise from 250,000 /.test(row("Control")), /Enterprise is not deliverable yet/.test(row("Control"))], [true, true]);
same("a supplier never pays to be counted", /the buyer pays; a supplier never pays to be counted$/.test(row("Supplier connection")), true);
same("the Pilot is credited against the first year of Control", /^2,500 USD, credited against the first year of Control /.test(row("Pilot")), true);
same("the Settle line says that on devnet it is test money", /minimum 0\.40\. On devnet this is test money: zero revenue$/.test(row("Settle")), true);
same("Index data, Advance and Assurance are not offered", row("Index data, Advance, Assurance"), "not offered");
same("the rule is published with the book, in the document too", [RULE, market.includes(`**The rule: ${RULE}**`)], ["Knos never charges the party being rated.", true]);
same("every line of the price book is a row of docs/MARKET.md, word for word", priceBook(c).filter((r) => !market.includes(`| ${r[0]} | ${r[1]}${r[1] ? " " : ""}| ${r[2]} |`)).map((r) => r[0]), []);
const eff = effectiveFees(c).map((r) => [r.amount, plain(r.fee), r.share]);
same("the effective fee: 5 pays 8.00%, 20 and 1,000 pay 2.50%, 5,000 pays 1.30%, 50,000 pays 1.03%", eff, [[5, "0.40", "8.00%"], [20, "0.50", "2.50%"], [1000, "25", "2.50%"], [5000, "65", "1.30%"], [50000, "515", "1.03%"]]);
same("and docs/MARKET.md prints the same five rows", eff.filter(([a, f, s]) => !market.includes(`| ${a.toLocaleString("en-US")} | ${f} | ${s} |`)), []);
// the two words a revenue scenario is written with are spelled in halves here, so that this file does not hold them
const banned = new RegExp(["1,000 million", "\\b1B\\b", "\\bAR" + "R\\b", "\\bbil" + "lion USD a year", "One bil" + "lion"].join("|"));
same("no public page or price document prints a revenue scenario", ["docs/MARKET.md", "docs/PILOT.md", "web/pricing.js", "web/price.js"].filter((f) => banned.test(readFileSync(join(here, "../..", f), "utf8"))), []);
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
