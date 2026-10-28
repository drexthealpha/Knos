// test_ready_card (U1), live: every recorded chip's card on the front door at 390 and 1280 carries each part (the
// Without-Qloo count, modeled and not modeled, the signal strength, the two assumptions with their rank, the rejected
// signals, what it cannot tell, the recorded and reset dates, the three exports, the closing calls line, How sure is
// this?), with numbers equal to the recorded answer (/api/check for the same idea), the memo printing on one page, and
// 0 page errors.
//
//   node scripts/test_ready_card.mjs [result dir]
import { chromium } from "playwright";
import { appendFileSync } from "node:fs";

const SITE = "https://drexthealpha.github.io/Knos/", APP = "https://knos.onrender.com";
const DIR = process.argv[2] || "C:/Users/zulab/knos-v1-private/v0328/world";
const CHIPS = ["a solar powered music festival", "an AI recipe planner for families", "a crypto podcast for beginners", "a quantum physics book for kids",
  "a probiotic kombucha brand", "a recycled ocean plastic swimwear brand"];
const PARTS = ["recorded", "without-count", "strength", "modeled", "rejected-signals", "cannot", "exports", "closing", "sure"];
const lines = [], fails = [];
const ok = (c, w) => { lines.push(`${c ? "ok  " : "FAIL"} ${w}`); console.log(lines.at(-1)); if (!c) fails.push(w); };
const post = (body) => fetch(APP + "/api/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json());
const browser = await chromium.launch();
const errors = [];
let cards = 0;
try {
  for (const width of [390, 1280]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    page.on("pageerror", (e) => errors.push(`${width}: ${e.message}`));
    for (const chip of CHIPS) {
      const rec = await post({ idea: chip, picked: true });
      await page.goto(SITE + "?t=" + Date.now(), { waitUntil: "domcontentloaded", timeout: 90000 });
      await page.fill("#k-guess", "Austin");
      await page.fill("#k-who", "college students");
      await page.click(`.k-try [data-q="${chip}"]`);
      const got = await page.waitForSelector("#k-card [data-u1]", { timeout: 120000 }).catch(() => null);
      if (!got) { ok(false, `${width} ${chip}: no recorded card parts`); continue; }
      await page.waitForTimeout(1500);
      const parts = await page.$$eval("#k-card [data-u1] [data-part], #k-card [data-part=sure]", (es) => es.map((e) => e.dataset.part));
      const missing = PARTS.filter((p) => !parts.includes(p));
      const has = await page.evaluate(() => ({
        ents: Number(document.querySelector("#k-card [data-part=strength]")?.dataset.entities),
        strength: document.querySelector("#k-card [data-part=strength]")?.dataset.strength,
        calls: Number(document.querySelector("#k-card [data-part=closing]")?.dataset.calls),
        closing: document.querySelector("#k-card [data-part=closing]")?.textContent || "",
        assumptions: [...document.querySelectorAll("#k-card [data-assumption]")].map((a) => [a.dataset.assumption, a.dataset.verdict, a.dataset.rank]),
        exports: document.querySelectorAll("#k-card [data-export]").length, recorded: document.querySelector("#k-card [data-part=recorded]")?.textContent || "" }));
      const ents = (rec.matches || []).filter((m) => m && m.name).length;
      const st = ents >= 5 ? "strong" : ents >= 2 ? "moderate" : "weak";
      const q = rec.qloo_calls || {};
      const same = has.ents === ents && has.strength === st && has.calls === (rec.calls || []).length && has.closing.includes(`(${q.live} live, ${q.recorded} recorded)`);
      ok(!missing.length && has.exports === 3 && has.assumptions.length === 2 && same && /Recorded \d{4}-\d\d-\d\d/.test(has.recorded),
        `${width} ${chip}: ${PARTS.length - missing.length} of ${PARTS.length} parts${missing.length ? ` (missing ${missing.join(", ")})` : ""}; ${has.ents} entities ${has.strength}; ${has.closing}; assumptions ${has.assumptions.map((a) => a.join(" ")).join("; ")}`);
      cards++;
      if (width === 1280 && chip === CHIPS[0]) {
        await page.emulateMedia({ media: "print" });
        const pdf = await page.pdf({ format: "A4", printBackground: false });
        const pages = (pdf.toString("latin1").match(/\/Type\s*\/Page[^s]/g) || []).length;
        ok(pages === 1, `the one-page memo prints on ${pages} A4 page(s)`);
        await page.emulateMedia({ media: "screen" });
      }
    }
    await page.close();
  }
} finally { await browser.close(); }
ok(errors.length === 0, `${errors.length} page errors${errors.length ? ": " + errors.slice(0, 2).join(" | ") : ""}`);
const line = fails.length ? `FAIL test_ready_card: ${fails.length} check(s) failed` : `PASS test_ready_card: ${cards} recorded cards at 2 widths with all ${PARTS.length} parts, numbers equal to the recorded answers, the memo on 1 page, 0 page errors`;
lines.push(line); console.log(line);
appendFileSync(`${DIR}/test_ready_card.txt`, lines.join("\n") + "\n");
process.exit(fails.length ? 1 : 0);
