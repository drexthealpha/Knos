// Q1 test_view_buttons, live: on /app/, the Without Qloo, With Qloo and Model alone buttons each answer 6 of 6 clicks
// at 1280 px and 390 px, light and dark. A click answers when the card shows what the button names: Without Qloo the
// card with every Qloo answer removed, With Qloo the full card with its model panel shut, Model alone the panel open.
//
//   node scripts/test_view_buttons.mjs [result file] [idea]
import { chromium } from "playwright";
import { appendFileSync } from "node:fs";

const APP = "https://knos.onrender.com/app/";
const OUT = process.argv[2] || "";
const IDEA = process.argv[3] || "a probiotic kombucha brand";
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); if (OUT) appendFileSync(OUT, s + "\n"); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const state = (page) => page.evaluate(() => {
  const k = document.querySelector("#k-card .k-card");
  if (!k) return "none";
  if (k.matches("[data-without-qloo]")) return "without";
  const panel = k.querySelector("[data-model-panel]");
  const pressed = k.querySelector('.k-switch [data-view][aria-pressed="true"]')?.dataset.view;
  return panel && !panel.hidden && pressed === "model" ? "model" : pressed === "qloo" && (!panel || panel.hidden) ? "qloo" : "other";
});
const press = async (page, sel, want) => {
  try {
    await page.click(`#k-card ${sel}`, { timeout: 10000 });
    for (let i = 0; i < 20; i++) { if (await state(page) === want) return true; await sleep(100); }
  } catch { /* a button that is not there does not answer */ }
  return false;
};

const browser = await chromium.launch();
let total = 0, answered = 0;
try {
  for (const width of [1280, 390]) {
    for (const scheme of ["light", "dark"]) {
      const ctx = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 800 }, colorScheme: scheme });
      const page = await ctx.newPage();
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      try {
        await page.goto(APP + "?q=" + encodeURIComponent(IDEA), { waitUntil: "domcontentloaded", timeout: 120000 });
        await page.waitForSelector("#k-card .k-card [data-without]", { timeout: 150000 });
        const n = { without: 0, qloo: 0, model: 0 };
        for (let round = 0; round < 6; round++) {
          if (await press(page, "[data-without]", "without")) n.without++;
          if (await press(page, '.k-switch [data-view="qloo"]', "qloo")) n.qloo++;
          if (await press(page, '.k-switch [data-view="model"]', "model")) n.model++;
        }
        total += 18; answered += n.without + n.qloo + n.model;
        ok(n.without === 6 && n.qloo === 6 && n.model === 6 && !errors.length,
          `${width} ${scheme}: Without Qloo ${n.without} of 6, With Qloo ${n.qloo} of 6, Model alone ${n.model} of 6, ${errors.length} page errors`);
      } catch (e) {
        total += 18;
        ok(false, `${width} ${scheme}: ${e.name}: ${String(e.message).split("\n")[0].slice(0, 120)}`);
      }
      await ctx.close();
    }
  }
} finally { await browser.close(); }
log(fails.length ? `FAIL test_view_buttons: ${answered} of ${total} clicks answered; first: ${fails[0].slice(0, 140)}`
  : `PASS test_view_buttons: ${answered} of ${total} clicks answered, each button 6 of 6 at 1280 and 390 px in light and dark`);
process.exit(fails.length ? 1 : 0);
