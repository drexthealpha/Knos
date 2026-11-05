// node tests/web/get_never_checks.mjs
// H3: a page that opens never asks Qloo. In headless Chromium, served from web/, with the app's server answered from a
// recording: every result page under web/results/ and the front door opened as /?q=a probiotic kombucha brand send 0 POST
// to /api/check while they load and settle; each shows the recorded answer labelled recorded (or says there is none);
// a live check runs only from the reader's press (one POST for one press). No real server is asked: every request that
// is not this page's own or the mocked app is aborted.
//   [--live https://drexthealpha.github.io/Knos/]   the same against the published site (after its deploy)
import { createServer } from "node:http";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { chromiumOrSkip, TYPES } from "./overflow.mjs";

const here = dirname(fileURLToPath(import.meta.url)), web = join(here, "../../web");
const LIVE = process.argv.includes("--live") ? process.argv[process.argv.indexOf("--live") + 1] : null;
let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };

const IDEA = "a probiotic kombucha brand";
// the recorded card the app's server holds for the sample idea (its shape: knos_wanted.recorded.stored)
const RECORDED = { kind: "demand_check", idea: IDEA, hash: "a".repeat(64), made: "2026-10-28T09:00:00Z", label: "recorded 2026-10-28",
  decision: { verdict: "CANNOT_DECIDE", reasons: ["recorded answer"] }, calls: [], cities: [], gap: {}, who: {} };

let origin = LIVE ? LIVE.replace(/\/$/, "") : null, server = null;
if (!LIVE) {
  server = createServer((req, res) => {
    let path = normalize(decodeURIComponent(req.url.split("?")[0])).replace(/^([/\\])+/, "");
    if (!path || path.endsWith("/") || path.endsWith("\\")) path = join(path, "index.html");
    const file = join(web, path);
    if (!file.startsWith(web) || !existsSync(file) || statSync(file).isDirectory()) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" }); res.end(readFileSync(file));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  origin = `http://127.0.0.1:${server.address().port}`;
}

const pages = readdirSync(join(web, "results")).filter((d) => statSync(join(web, "results", d)).isDirectory() && existsSync(join(web, "results", d, "index.html")));
const browser = await chromiumOrSkip();

/** Opens `path`, lets it settle, and returns the POSTs to /api/check and the page. `press` runs after the settle. */
async function visit(path, press = null) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const posts = [], gets = [];
  await ctx.route("**/*", async (route) => {
    const req = route.request(), url = new URL(req.url());
    if (url.host === "knos.onrender.com") {
      if (url.pathname === "/api/check") { if (req.method() === "POST") posts.push(url.pathname); return route.fulfill({ status: 503, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: '{"error":"test: no live check"}' }); }
      gets.push(url.pathname);
      const body = url.pathname === "/api/recorded" ? (url.searchParams.get("idea") === IDEA ? RECORDED : null) : {};
      return route.fulfill({ status: body ? 200 : 404, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(body || { error: "no recorded answer for this idea" }) });
    }
    if (url.origin === new URL(origin).origin) return route.continue();
    return route.abort();
  });
  const page = await ctx.newPage();
  await page.goto(origin + path, { waitUntil: "load" });
  await page.waitForTimeout(2500);
  const label = await page.evaluate(() => [...document.querySelectorAll("[data-recorded]")].map((n) => n.dataset.recorded + ": " + n.textContent.trim().slice(0, 80)));
  let after = posts.length;
  if (press) { await press(page); await page.waitForTimeout(1500); after = posts.length; }
  await ctx.close();
  return { onLoad: posts.length - (press ? after - posts.length : 0), posts, gets, label, after };
}

let total = 0;
for (const d of pages) {
  const got = await visit(`/results/${d}/`);
  total += got.posts.length;
  ok(`results/${d}/ opens with 0 POST to /api/check and a recorded label`, got.posts.length === 0 && got.label.length > 0, got);
  console.log(`     ${got.label.join(" | ")}`);
}
const front = await visit(`/?q=${encodeURIComponent(IDEA)}`);
total += front.posts.length;
ok(`/?q=${IDEA} opens with 0 POST to /api/check and shows the recorded answer labelled recorded`, front.posts.length === 0 && front.label.some((l) => l.startsWith("yes")), front);
console.log(`     ${front.label.join(" | ")}`);
// a live check from a press: the result page's button sends one; the front door's Check sends one
const pressed = await visit(`/results/${pages[0]}/`, (p) => p.click("text=Check it live now"));
ok("a press of 'Check it live now' on a result page sends 1 POST", pressed.after === 1, pressed);
const checked = await visit(`/?q=${encodeURIComponent(IDEA)}`, (p) => p.click("#k-go"));
ok("a press of Check on the front door sends the POST", checked.after >= 1, checked);
console.log(`${failed ? "FAIL" : "PASS"} test_get_never_checks: ${pages.length} result pages and /?q= opened, ${total} POST to /api/check on load${LIVE ? ` (live: ${LIVE})` : ""}`);
await browser.close();
if (server) server.close();
process.exit(failed ? 1 : 0);
