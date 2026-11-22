// L34: the product video and the intro loop, recorded from the real local product with Playwright's video recording.
// The built site (scripts/build_site.sh) is served at /Knos/ and every call the front door makes to the hosted server is
// answered by the local app (python -m knos_wanted serve), so the check, the price and the test payment are the product's
// own. Before recording, the day's free runs of one browser id are used up on the local app, so the recorded press meets
// the price. No voice, no music, no stock footage.
//
//   node bench/video/capture.mjs <built site dir> <local app url> <out dir>
// writes <out dir>/knos-demo.mp4, knos-loop.mp4 and capture.json (the times, in seconds from the video's first frame).
// Needs playwright (NODE_PATH), Chrome (CHROME_PATH) and ffmpeg/ffprobe on PATH.
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { delimiter } from "node:path";
import { createServer } from "node:http";
import { mkdirSync, readFileSync, existsSync, writeFileSync, statSync, rmSync } from "node:fs";
import { join, extname, resolve } from "node:path";
import { randomBytes } from "node:crypto";

const req = createRequire(import.meta.url);
const { chromium } = req(req.resolve("playwright", { paths: (process.env.NODE_PATH || "").split(delimiter).filter(Boolean) }));
const [site, app, out] = process.argv.slice(2).map((x, i) => (i === 1 ? x.replace(/\/$/, "") : resolve(x)));
const ROOT = resolve(new URL("../..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
mkdirSync(out, { recursive: true });
const raw = join(out, "raw");
mkdirSync(raw, { recursive: true });

const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2", ".ico": "image/x-icon", ".txt": "text/plain" };
const server = createServer((req, res) => {
  let p = decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/^\/Knos\//, "/");
  let f = join(site, p);
  if (existsSync(f) && statSync(f).isDirectory()) f = join(f, "index.html");
  if (!existsSync(f)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { "content-type": TYPES[extname(f)] || "application/octet-stream" });
  res.end(readFileSync(f));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/Knos/`;

// the job: a made-up battery test of 200 cycles (the locked comparison's file h01), a file of the person's own, so the free runs count
const sample = readFileSync(join(ROOT, "bench/limit-vs-sheet/heldout/h01.csv"), "utf8");
const runs = randomBytes(12).toString("hex");
const body = { id: "limit-check", table: sample, column: "capacity_ah", rule: "above", limit: 1.4, mode: "own", browser: "", runs, test: true };
let used = 0;
for (; used < 12; used++) {   // the day's free runs of this browser id, used on the local app before recording
  const r = await fetch(app + "/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (r.status === 402) break;
  if (!r.ok) throw new Error(`local app answered ${r.status}`);
}

const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, colorScheme: "dark", recordVideo: { dir: raw, size: { width: 1280, height: 720 } } });
const t0 = Date.now();
const at = () => (Date.now() - t0) / 1000;
await ctx.addInitScript((id) => { try { localStorage.setItem("knos-runs", id); localStorage.setItem("knos.count", "no"); localStorage.setItem("knos.pointer", "1"); } catch { /* none */ } }, runs);
await ctx.route(/^https:\/\/knos\.onrender\.com\//, async (route) => {
  const u = new URL(route.request().url());
  const resp = await route.fetch({ url: app + u.pathname + u.search });
  await route.fulfill({ response: resp, headers: { ...resp.headers(), "access-control-allow-origin": "*" } });
});
await ctx.route(/^https:\/\/(fonts\.|api\.github\.com)/, (r) => r.abort());
const page = await ctx.newPage();
await page.goto(base, { waitUntil: "load" });
await page.fill("#list", sample);
await page.locator("#col").waitFor({ state: "visible" });
await page.selectOption("#col", "capacity_ah");
await page.locator("#list").evaluate((el) => { el.scrollTop = 0; el.blur(); });
await page.waitForTimeout(400);
const start = at();                       // the video's first frame: the box holding the battery file, the Check button
await page.waitForTimeout(1200);
await page.click("#try");
await page.locator("#pay").waitFor({ state: "visible" });
const price = at();
await page.waitForTimeout(1300);
await page.click("#pay-go");
await page.locator("#pay-yes").waitFor({ state: "visible" });
await page.waitForTimeout(900);
await page.click("#pay-yes");
await page.locator("#pay").waitFor({ state: "hidden" });
const paid = at();
await page.waitForTimeout(1500);
await page.click("#try");
await page.locator("#result").waitFor({ state: "visible", timeout: 60000 });
const result = at();
const said = (await page.locator("#about").innerText()).trim();
await page.waitForTimeout(2000);
await page.mouse.wheel(0, 420);           // the verdict's chart and the row that broke the limit
await page.waitForTimeout(3500);
await page.click("#how > summary");       // How it works: the test that judged the program, the price
await page.locator("#how > summary").evaluate((el) => el.scrollIntoView({ behavior: "smooth", block: "start" }));
await page.waitForTimeout(4500);
const end = at();
const video = page.video();
await ctx.close();
const webm = await video.path();
await browser.close();
server.close();

const enc = ["-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "slow", "-crf", "28", "-movflags", "+faststart"];
const demo = join(out, "knos-demo.mp4"), loop = join(out, "knos-loop.mp4");
execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-ss", start.toFixed(2), "-to", end.toFixed(2), "-i", webm, ...enc, demo]);
const loopLen = Math.min(13.5, end - start);
execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-ss", start.toFixed(2), "-t", loopLen.toFixed(2), "-i", webm, ...enc, loop]);
const dur = (f) => Number(execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f]).toString().trim());
const doc = {
  recorded_at: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
  how: "Playwright recordVideo of the local build of web/ with the local app (apps/wanted) answering every call; no voice, no music",
  free_runs_used_before: used,
  price_s: +(price - start).toFixed(2), paid_s: +(paid - start).toFixed(2), result_s: +(result - start).toFixed(2),
  result: said, demo_s: +dur(demo).toFixed(2), loop_s: +dur(loop).toFixed(2),
};
writeFileSync(join(out, "capture.json"), JSON.stringify(doc, null, 1) + "\n");
rmSync(raw, { recursive: true, force: true });   // the raw recording folder this script made
console.log(JSON.stringify(doc));
