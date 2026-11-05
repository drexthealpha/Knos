// U7 on the web app: a stranger types one idea into the live front door and presses Check demand (one live check).
//   node scripts/test_front_door_demand.mjs <site URL> <idea> <out dir>
// Records clicks, seconds to the verdict (the Qloo wait logged apart), the verdict text and a screenshot.
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const [site = "https://drexthealpha.github.io/Knos/", idea = "a probiotic kombucha brand", out = "front-door-demand"] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
const t0 = Date.now();
await page.goto(site + "?u7=" + Date.now(), { waitUntil: "domcontentloaded", timeout: 120000 });
await page.fill("#k-q", idea);
const t1 = Date.now();
await page.click("#k-go");
let verdict = null, note = "";
try {
  await page.waitForFunction(() => {
    const c = document.querySelector("#k-card .k-card .k-verdict, #k-card [data-which], #k-card .k-past-card");
    return c ? c.textContent.trim() : null;
  }, null, { timeout: 120000 });
  verdict = (await page.locator("#k-card").innerText()).replace(/\s+/g, " ").slice(0, 400);
} catch (e) { note = String(e).slice(0, 200); }
const t2 = Date.now();
await page.screenshot({ path: path.join(out, "front-door-demand-1280.png") });
const row = { idea, clicks: 1, typed: true, seconds_before_press: Math.round((t1 - t0) / 100) / 10, seconds_to_answer: Math.round((t2 - t1) / 100) / 10, verdict, note, errors };
fs.writeFileSync(path.join(out, "front-door-demand.json"), JSON.stringify(row, null, 1));
console.log(JSON.stringify(row));
await browser.close();
