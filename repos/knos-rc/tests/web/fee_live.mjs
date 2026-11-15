// node tests/web/fee_live.mjs <site dir>
// The truth about the fee, on a build of the site (scripts/build_site.sh), under BOTH builds of knos_pay:
//   2.1  the 0.3.14 fee (three tiers, at least 0.40): what the public program charges until the next upgrade executes
//   2.2  the 0.3.18 fee (0.30%, at least 0.05)
// First with no browser: the one line "After the next upgrade" (web/price.js feeNext) is there exactly when the fee
// shown is not this tree's, and an order's refund time is its deadline, or the end of its presentation grace when it
// was funded with one (web/buyer.js orderState, web/console.js exceptionsOf). Then in headless Chromium, with devnet
// unreachable so the page reads the upgrade feed (upgrades.json, a file of the site, here as each build would leave
// it): the pricing calculator and the Console's escrow step show the fee of the build that is live, the next-upgrade
// line only under 2.1, and nobody is asked but this site and devnet. No browser: a failure in CI, a skip elsewhere.
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, extname } from "node:path";
import { pathToFileURL } from "node:url";
import { chromiumOrSkip, TYPES, measure } from "./overflow.mjs";

const root = process.argv[2];
if (!root || !existsSync(join(root, "index.html"))) { console.error("usage: node tests/web/fee_live.mjs <site dir>"); process.exit(2); }
let fails = 0;
const check = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); } };
const at = (f) => pathToFileURL(join(root, f)).href;
const knos = await import(at("settle.js")), price = await import(at("price.js")), buyer = await import(at("buyer.js")), con = await import(at("console.js"));
const { priceConstants, feeNext, orderFee, show, FEE_VERSION } = price;

// ---- no browser ---------------------------------------------------------------------------------------------------------
const old = priceConstants(knos, 1), now = priceConstants(knos, FEE_VERSION), unknown = priceConstants(knos, null), u = (n) => n * 1e6;
check("2.1 live: 50 pays 1.25 today, and one line says 0.15 after the next upgrade", show(orderFee(u(50), old.feeBps, old)) === "1.25" && feeNext(old, u(50)).label === "After the next upgrade" && show(feeNext(old, u(50)).fee) === "0.15"
  && feeNext(old).rate === "0.30% of the amount, at least 0.05", feeNext(old, u(50)));
check("2.2 live: 50 pays 0.15, and there is no line about an upgrade", show(orderFee(u(50), now.feeBps, now)) === "0.15" && feeNext(now, u(50)) === null);
check("nobody answered: the next build's fee is shown, and the line says what is charged until then", unknown.fee.live === false && feeNext(unknown, u(50)).label === "Until the next upgrade" && show(feeNext(unknown, u(50)).fee) === "1.25");
const T = 1790000000, order = { state: "open", amount: u(50), paid: 0, deadline: T, grace: false, payUntil: T };
const graced = { ...order, grace: true, payUntil: T + knos.v2.GRACE }, when = (t) => `${new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ")} UTC`;
check("an order's refund time is its deadline", buyer.refundAt(order) === T && buyer.orderState(order, [], T - 9).words === `Funded: 50.00 is in the order's own escrow account. Unpaid by ${when(T)}, anyone can send it back.`, buyer.orderState(order, [], T - 9).words);
check("an order funded with a grace says its grace: refundable two hours after its deadline", knos.v2.GRACE === 7200 && buyer.refundAt(graced) === T + 7200
  && buyer.orderState(graced, [], T - 9).words === `Funded: 50.00 is in the order's own escrow account. Unpaid by ${when(T + 7200)}, anyone can send it back: its deadline, ${when(T)}, and 2 hours' grace.`, buyer.orderState(graced, [], T - 9).words);
const line = { order: "A", kind: "funded", repository_id: 1, issue: 7, private: 0, transaction: "" };
const needs = (o, t) => con.exceptionsOf({ lines: [line], live: new Map([["A", o]]), now: t }).map((r) => r.kind);
check("past its deadline an order with no grace is refundable at once", JSON.stringify(needs(order, T + 1)) === '["refundable"]', needs(order, T + 1));
check("inside its grace an order is not refundable yet, and the page says until when", JSON.stringify(needs(graced, T + 1)) === '["grace"]' && con.exceptionsOf({ lines: [line], live: new Map([["A", graced]]), now: T + 1 })[0].what.includes(when(T + 7200)), needs(graced, T + 1));
check("after its grace it is refundable, and both times are said", JSON.stringify(needs(graced, T + 7201)) === '["refundable"]' && /and its grace \(/.test(con.exceptionsOf({ lines: [line], live: new Map([["A", graced]]), now: T + 7201 })[0].what));

// ---- the pages, under each build ----------------------------------------------------------------------------------------
const browser = await chromiumOrSkip();
const feed = JSON.parse(readFileSync(join(root, "upgrades.json"), "utf8"));
const FEEDS = {
  "2.1": { ...feed, entries: feed.entries.filter((e) => !(e.program === "knos_pay" && e.index > 4)) },
  "2.2": { ...feed, entries: [{ index: 8, program: "knos_pay", status: "executed", words: "Proposal 8 replaced the code of knos_pay." }, ...feed.entries] },
};
check("the two feeds name the two builds", knos.v2.feedFeeVersion(FEEDS["2.1"]) === 1 && knos.v2.feedFeeVersion(FEEDS["2.2"]) === FEE_VERSION);
const WANT = {
  "2.1": { release: "0.3.14", rate: price.feeRate(old), task: "0.50", next: "After the next upgrade: 0.06 on this order.", buy: "1.25", pays: "51.25", buyNext: "After the next upgrade: 0.15 on this order." },
  "2.2": { release: "0.3.18", rate: "0.30% of the amount, at least 0.05", task: "0.06", next: null, buy: "0.15", pays: "50.15", buyNext: null },
};
for (const build of ["2.1", "2.2"]) {
  const server = createServer((req, res) => {
    const name = decodeURIComponent(new URL(req.url, "http://x").pathname), path = join(root, name.replace(/\/$/, "/index.html"));
    if (name === "/upgrades.json") { res.writeHead(200, { "content-type": "application/json" }); return res.end(JSON.stringify(FEEDS[build])); }
    if (!path.startsWith(root) || !existsSync(path)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }); res.end(readFileSync(path));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${server.address().port}/`, want = WANT[build], strangers = [];
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" });
  await ctx.route("**/*", (route) => {            // devnet does not answer, so the page reads the feed; anybody else is a stranger
    const url = route.request().url();
    if (url.startsWith(base)) return route.continue();
    if (!/^https:\/\/api\.devnet\.solana\.com\//.test(url) && !/^https:\/\/api\.github\.com\//.test(url)) strangers.push(url);
    return route.abort();
  });
  const page = await ctx.newPage();
  await page.goto(`${base}#pricing`, { waitUntil: "load" });
  await page.waitForFunction((r) => document.getElementById("bill-live")?.dataset.fee === r && document.getElementById("calc-settle")?.dataset.fee === r, want.release);
  const live = await page.$$eval("#bill-live dt, #bill-live dd", (l) => l.map((e) => e.textContent));
  check(`${build}: the pricing calculator says the fee the program charges today`, live[0] === "Fee on devnet today" && live[1] === want.rate && (await page.getAttribute("#bill-live", "data-source")) === "feed", live);
  check(`${build}: ${want.next ? "and one line for the next upgrade" : "and no line about an upgrade"}`, want.next ? live.length === 4 && live[2] === "After the next upgrade" && live[3] === WANT["2.2"].rate : live.length === 2, live);
  await page.fill("#calc-amount", "20");
  check(`${build}: a task of 20 pays the live fee, ${want.task}`, (await page.textContent('#calc-table [data-key="fee"] td')) === want.task && (await page.textContent('#calc-table [data-key="funder"] td')) === show(u(20) + Math.round(Number(want.task) * 1e6)));
  check(`${build}: ${want.next ? "with what the same task pays after the next upgrade" : "with nothing more to say"}`, want.next ? (await page.textContent("#calc-next")) === want.next : (await page.$("#calc-next")) === null);
  const table = await page.$$eval("#fee-effective tbody tr", (rows) => rows.map((r) => [r.dataset.amount, r.children[1].textContent]));
  check(`${build}: the table of effective fees is the live rule's`, table.find((r) => r[0] === "5")[1] === (build === "2.1" ? "0.40" : "0.05") && table.find((r) => r[0] === "1000")[1] === (build === "2.1" ? "25" : "3"), table);
  check(`${build}: the pricing page does not scroll sideways at 390 px`, (await measure(page)).over <= 0, await measure(page));
  await page.goto(`${base}#buy`, { waitUntil: "load" });
  await page.waitForFunction((r) => document.getElementById("buy")?.dataset.fee === r && !document.getElementById("buy-fee-now").hidden && document.getElementById("buy-fee-now").dataset.fee === r, want.release);
  check(`${build}: the Console's escrow step shows the live fee on 50: ${want.buy} on top, ${want.pays} in all`, (await page.textContent("#buy-fee-is")) === want.buy && (await page.textContent("#buy-pays-is")) === want.pays && await page.isVisible("#buy-fee-now"));
  check(`${build}: ${want.buyNext ? "and one line for the next upgrade" : "and no line about an upgrade"}`, want.buyNext ? (await page.textContent("#buy-fee-next")) === want.buyNext && await page.isVisible("#buy-fee-next") : await page.isHidden("#buy-fee-next"));
  check(`${build}: nobody but this site, devnet and GitHub is asked`, strangers.length === 0, strangers);
  await ctx.close(); server.close();
}
await browser.close();
console.log(fails ? `${fails} failed` : "all passed");
process.exit(fails ? 1 : 0);
