// node tests/web/keyboard.mjs <site dir>
// A first visit on a phone with no pointer: the sample invoice run to its end with the keyboard alone, at 390 px.
// Tab reaches the skip link first, then the box, Check, and the sample; Enter runs it; the answer is said in a live
// region; past the window, Tab reaches the supplier's appeal on a line owed to the supplier; Tab goes on to Approve,
// Download and the statement, where "Open a statement file" is reached by Tab too and Enter opens the file chooser;
// every stop shows a focus ring; Escape closes the menu and gives the focus back. No browser: a failure in CI, a skip elsewhere (tests/web/overflow.mjs).
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, extname } from "node:path";
import { chromiumOrSkip, TYPES } from "./overflow.mjs";

const root = process.argv[2];
if (!root || !existsSync(join(root, "index.html"))) { console.error("usage: node tests/web/keyboard.mjs <site dir>"); process.exit(2); }
let fails = 0;
const check = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); } };
const browser = await chromiumOrSkip();
const server = createServer((req, res) => {
  const path = join(root, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/\/$/, "/index.html"));
  if (!path.startsWith(root) || !existsSync(path)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }); res.end(readFileSync(path));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;
// The page's own day decides what the sample says: its last merge is 2026-09-07 (web/front_door_sample.js), and a line
// whose policy is met and nobody authorised is owed to the supplier ACCEPT_DAYS (30) days after (web/front_door.js
// isOwed). So the day is set, never the machine's: still, inside the window; moving, past it, as a reader sees it now.
const DAYS = { still: ["2026-10-06T12:00:00Z", ""], moving: ["2026-10-09T12:00:00Z", " 2 owed to the supplier."] };

for (const reduced of [true, false]) {
  const tag = reduced ? "still" : "moving";
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, acceptDownloads: true, reducedMotion: reduced ? "reduce" : "no-preference" });
  const strangers = [];
  await ctx.route("**/*", (route) => { const u = route.request().url(); if (u.startsWith(base) || u.startsWith("blob:")) return route.continue(); strangers.push(u); return route.abort(); });
  const page = await ctx.newPage(), errors = [], [day, owed] = DAYS[tag];
  await page.clock.setFixedTime(new Date(day));                      // Date only: the timers and the frames still run
  page.on("pageerror", (e) => errors.push(String(e)));
  // file choosers are taken from the start: Playwright intercepts them only once a listener is there, and a listener
  // added at the moment of the press can come after the chooser
  const choosers = [];
  page.on("filechooser", (c) => choosers.push(c));
  await page.goto(base, { waitUntil: "load" });
  await page.waitForFunction(() => document.documentElement.dataset.ready === "check");
  await page.waitForSelector('#front-door [data-fd="sample"]');
  // where the focus is, whether a ring is drawn round it, and whether it is inside the window
  const at = async () => { if (!reduced) await page.waitForTimeout(400); return look(); };          // a ring slides in and a scroll glides: looked at once they rest
  const look = () => page.evaluate(() => { const e = document.activeElement, s = getComputedStyle(e), r = e.getBoundingClientRect();
    return { id: e.id || e.dataset.fd || e.className || e.tagName, text: (e.textContent || "").trim().slice(0, 40), ring: s.outlineStyle !== "none" && parseFloat(s.outlineWidth) >= 2, seen: r.bottom > 0 && r.top < innerHeight && r.width > 0 }; });
  const tabTo = async (want, most = 12) => { for (let i = 0; i < most; i += 1) { await page.keyboard.press("Tab"); const a = await at(); if (want(a)) return a; } return at(); };

  await page.keyboard.press("Tab");
  let a = await at();
  check(`${tag}: the first Tab lands on the skip link, drawn and ringed`, a.id === "k-skip" && a.ring && a.seen, a);
  await page.keyboard.press("Enter");
  a = await at();
  check(`${tag}: Enter on it puts the cursor in the invoice box`, a.id === "fd-in" && a.ring, a);
  await page.keyboard.press("Tab"); a = await at();
  check(`${tag}: Tab goes to Check`, a.id === "run" && a.ring && a.seen, a);
  await page.keyboard.press("Tab"); a = await at();
  check(`${tag}: then to the sample`, a.id === "sample" && a.ring && a.seen, a);
  await page.keyboard.press("Enter");
  await page.waitForSelector("#front-result[data-done]");
  const said = await page.$eval('#front-result [data-fd="said"]', (e) => [e.textContent, e.getAttribute("aria-live"), e.getAttribute("role")]);
  check(`${tag}: Enter runs it, and the answer is said in a live region`, said.join("|") === `Checked 7 lines. 5 exceptions.${owed}|polite|status`, [day, ...said]);
  check(`${tag}: the lines are in their four groups, and the answer is in the window`, await page.$$eval("#front-result .fd-group", (l) => l.map((g) => g.querySelectorAll(".fd-line").length).join()) === "2,2,2,1"
    && await page.$eval('#front-result [data-fd="said"]', (e) => { const r = e.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight; }));
  check(`${tag}: ${owed ? "past the window, the two lines whose policy is met are owed to the supplier" : "inside the window, no line is owed to the supplier"}`,
    await page.$$eval("#front-result [data-fd-owed]", (l) => l.length) === (owed ? 2 : 0));
  if (owed) {
    a = await tabTo((x) => x.text === "Supplier: appeal", 20);
    const appeal = await page.evaluate(() => [document.activeElement.closest(".fd-line")?.dataset.line, document.activeElement.parentElement.textContent.trim(), document.activeElement.getAttribute("href")]);
    check(`${tag}: Tab reaches the first owed line's appeal, ringed and in the window, beside "owed to the supplier"`, a.ring && a.seen && appeal[0] === "1"
      && appeal[1] === "Owed to the supplier: policy met, unauthorised 30 days. Supplier: appeal" && appeal[2].endsWith("docs/DISPUTES.md#the-path"), [a, appeal]);
  }
  a = await tabTo((x) => x.id === "approve", 40);
  check(`${tag}: Tab reaches Approve agreed lines, ringed and scrolled into the window`, a.id === "approve" && a.ring && a.seen, a);
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.querySelector('[data-fd="approved"]').textContent === "Accepted and authorised 2 lines. 5 exceptions left. Not paid.");
  a = await at();
  check(`${tag}: once authorised, no line is owed to the supplier`, await page.$$eval("#front-result [data-fd-owed], #front-result .fd-line[data-owed]", (l) => l.length) === 0);
  check(`${tag}: Enter approves, says so in a live region, and the focus moves on to Download CSV`, a.id === "csv" && a.ring && (await page.getAttribute('[data-fd="approved"]', "aria-live")) === "polite", a);
  const [d] = await Promise.all([page.waitForEvent("download"), page.keyboard.press("Enter")]);
  await page.waitForSelector(".k-toast");
  check(`${tag}: Enter downloads the statement, and a toast in a status region says so`, /^statement-.*\.csv$/.test(d.suggestedFilename()) && (await page.textContent(".k-toast")).startsWith("Downloaded statement-") && (await page.getAttribute(".k-toasts", "role")) === "status");
  await page.keyboard.press("Tab"); a = await at();
  check(`${tag}: Tab goes to Open the statement`, a.id === "statement" && a.ring, a);
  await page.keyboard.press("Enter");
  await page.waitForSelector("#aps-statement", { state: "visible" });
  check(`${tag}: Enter opens the Statement page with that statement and its approval`, (await page.evaluate(() => document.body.dataset.page)) === "invoice-statement" && (await page.textContent("#aps-answers")).includes("by you (approver)"));
  // the Statement page's own file: Shift+Tab from "Open the sample" reaches "Open a statement file", and Enter opens
  // the file chooser; the sample statement and its status file chosen there are opened
  await page.focus("#aps-sample"); await page.keyboard.press("Shift+Tab"); a = await at();
  check(`${tag}: on the Statement page, Tab reaches "Open a statement file", ringed`, a.id === "aps-open" && a.text === "Open a statement file" && a.ring && a.seen, a);
  await page.keyboard.press("Enter");
  for (let i = 0; i < 50 && !choosers.length; i += 1) await page.waitForTimeout(100);
  const chooser = choosers.shift() || null;
  check(`${tag}:   Enter opens the file chooser, for one or more files`, !!chooser && chooser.isMultiple(), !!chooser);
  if (chooser) {
    await chooser.setFiles([join(root, "statement_sample.json"), join(root, "statement_sample.status.json")]);
    await page.waitForFunction(() => /Invoice INV-2026-09, Acme Agents/.test(document.querySelector("#aps-result")?.textContent || ""), null, { timeout: 10000 }).catch(() => {});
    const opened = await page.textContent("#aps-result");
    check(`${tag}:   the chosen statement is opened in place of the first screen's`, /Invoice INV-2026-09, Acme Agents/.test(opened) && /Unchanged since it was made/.test(opened) && !opened.includes("by you (approver)"), opened.slice(0, 200));
  }
  // the menu, by keyboard: Enter opens it, Escape closes it and gives the focus back
  await page.focus("#menu"); await page.keyboard.press("Enter");
  check(`${tag}: Enter on Menu opens the bar's links`, (await page.getAttribute("#menu", "aria-expanded")) === "true" && await page.isVisible('#nav a[href="#pricing"]'));
  await page.keyboard.press("Escape");
  check(`${tag}: Escape closes it and gives Menu the focus back`, (await page.getAttribute("#menu", "aria-expanded")) === "false" && await page.isHidden('#nav a[href="#pricing"]') && (await at()).id === "menu");
  check(`${tag}: nobody outside the site was asked, and no error`, strangers.length === 0 && errors.length === 0, [strangers, errors]);
  await ctx.close();
}
await browser.close(); server.close();
console.log(fails ? `${fails} checks failed` : "keyboard: the sample runs to its end with the keyboard alone");
process.exit(fails ? 1 : 0);
