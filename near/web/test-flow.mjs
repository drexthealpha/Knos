// N8 / R11: from the browser, a real testnet fund, proof and release, then a fund and a refund after its deadline,
// the status table, the CSV a bookkeeper opens, axe at 390 and 1280. Needs near/web/serve.py on 127.0.0.1:8790.
//   node near/web/test-flow.mjs [screenshot folder]
import { chromium } from "playwright";
import fs from "node:fs";

const URL = "http://127.0.0.1:8790/";
const out = process.argv[2] || ".";
let fails = 0;
const ok = (cond, line) => { if (!cond) fails++; console.log(`${cond ? "PASS" : "FAIL"} ${line}`); };

let axe = null;
try { axe = (await import("@axe-core/playwright")).AxeBuilder; } catch { console.log("note: @axe-core/playwright not installed here; axe runs where it is"); }
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true })).newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto(URL, { waitUntil: "networkidle" });

async function fund(minutes) {
  const before = await page.locator("#rows .id").allTextContents();
  await page.fill("#minutes", String(minutes));
  await page.fill("#amount", "1000");
  await page.click("#fund button");
  await page.waitForFunction(() => /Fund: (done|refused)/.test(document.querySelector("#finding").textContent), null, { timeout: 180000 });
  const f = await page.textContent("#finding");
  // the new milestone is the id that was not in the table before the fund
  await page.waitForFunction((b) => [...document.querySelectorAll("#rows .id")].some((e) => !b.includes(e.textContent)), before, { timeout: 60000 });
  const id = (await page.locator("#rows .id").allTextContents()).find((x) => !before.includes(x));
  return { f, id };
}
const stateOf = async (id) => (await page.locator("#rows tr", { hasText: id }).locator(".pill").textContent()).trim();

const a = await fund(30);
ok(a.f.includes("done"), `fund ${a.id}: ${a.f}`);
await page.locator("#rows tr", { hasText: a.id }).getByRole("button", { name: "Send proof" }).click();
await page.waitForFunction(() => /Proof: (done|refused)/.test(document.querySelector("#finding").textContent), null, { timeout: 180000 });
const pf = await page.textContent("#finding");
let st = await stateOf(a.id);
for (let i = 0; i < 6 && st !== "released"; i++) { await page.waitForTimeout(5000); await page.reload({ waitUntil: "networkidle" }); st = await stateOf(a.id); }
ok(pf.includes("done") && st === "released", `proof for ${a.id}: ${pf} state ${st}`);

const b = await fund(1);
ok(b.f.includes("done"), `fund ${b.id} with a 1-minute deadline: ${b.f}`);
await page.waitForTimeout(75000);
await page.reload({ waitUntil: "networkidle" });
await page.locator("#rows tr", { hasText: b.id }).getByRole("button", { name: "Refund" }).click();
await page.waitForFunction(() => /Refund: (done|refused)/.test(document.querySelector("#finding").textContent), null, { timeout: 180000 });
const rf = await page.textContent("#finding");
st = await stateOf(b.id);
for (let i = 0; i < 6 && st !== "refunded"; i++) { await page.waitForTimeout(5000); await page.reload({ waitUntil: "networkidle" }); st = await stateOf(b.id); }
ok(rf.includes("done") && st === "refunded", `refund for ${b.id}: ${rf} state ${st}`);

const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#csv")]);
const csv = fs.readFileSync(await dl.path(), "utf8");
const lines = csv.trim().split(/\r?\n/);
ok(lines[0].startsWith("milestone,state,amount_test_units") && lines.some((l) => l.includes(a.id) && l.includes("Released")) && lines.some((l) => l.includes(b.id) && l.includes("Refunded")),
  `CSV ${dl.suggestedFilename()}: ${lines.length - 1} rows, header ${lines[0]}`);
const links = await page.locator(`#rows tr:has-text("${a.id}") .txs a`).count();
ok(links >= 2, `${a.id} links ${links} transactions (fund, release)`);

for (const [w, h] of [[1280, 900], [390, 844]]) {
  await page.setViewportSize({ width: w, height: h });
  await page.reload({ waitUntil: "networkidle" });
  await page.screenshot({ path: `${out}/near-app-${w}.png`, fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  if (axe) {
    const v = (await new axe({ page }).analyze()).violations;
    ok(v.length === 0 && !overflow, `${w}px: axe ${v.length} violations ${v.map((x) => x.id).join(" ")}, overflow ${overflow}`);
  } else ok(!overflow, `${w}px: overflow ${overflow}`);
}
ok(errors.length === 0, `page errors ${errors.length}`);
await browser.close();
console.log(`${fails ? "FAIL" : "PASS"} test_ui flow: ${fails} failed`);
process.exit(fails ? 1 : 0);
