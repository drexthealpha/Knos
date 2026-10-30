// L2 test_live_honest_v2, live: a call is "live" only when Qloo answered it with HTTP 200 during the request, the
// prefetched calls included. Pass: for 6 fresh checks the card's live count equals the number of live 200 answers in
// the server's own call log for that request; the trace and /api/report of the 22 Oct report say "recorded
// 2026-10-22"; the line "2 more examples return when Qloo answers again" is absent while Qloo answers.
//
//   node scripts/test_live_honest_v2.mjs [result file]
import { chromium } from "playwright";
import { appendFileSync } from "node:fs";

const APP = "https://knos.onrender.com", FRONT = "https://drexthealpha.github.io/Knos/";
const OUT = process.argv[2] || "";
const OLD = "2b93c7bc52db6cd819655c021e9186d4bdcaaaf32544512b141e3bb60fe48722";     // the front door's 22 Oct recording
// six ideas no check has asked before, so their Qloo questions are new to the server's cache
const stamp = new Date().toISOString().slice(5, 16).replace(/[-T:]/g, "");
// a new set each run (a run's checks fill the private cache, so its ideas are recorded for the next): `node ... <out> <run>`
const SETS = {
  1: ["a sourdough bagel bakery", "a matcha latte cafe", "a pickleball paddle brand", "a vinyl record shop", "a hot sauce subscription brand", "a climbing gym for kids"],
  2: ["a kombucha bar for runners", "a used bookshop with a cat cafe", "a mushroom coffee brand", "a pottery studio for beginners",
    "a hot pot restaurant for students", "a vegan leather sneaker brand"],
  3: ["a ceramic tea set brand", "a rooftop jazz lounge", "a bike repair shop for commuters", "a gluten free bakery for kids",
    "a k-pop dance studio", "a cold plunge spa for athletes"]};
const FRESH = SETS[process.argv[3] || "1"];
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const get = async (path) => (await fetch(APP + path, { headers: { "User-Agent": "knos-l2-test" } })).json();
const post = async (path, body) => (await fetch(APP + path, { method: "POST", headers: { "Content-Type": "application/json", "User-Agent": "knos-l2-test" }, body: JSON.stringify(body) })).json();

log(`run ${stamp}`);
for (const idea of FRESH) {
  const rep = await post("/api/check", { idea, picked: true });
  const req = rep.qloo_request?.req;
  const logged = ((await get("/api/calls")).calls || []).filter((c) => req && c.req === req);
  const live200 = logged.filter((c) => c.status === 200 && c.origin === "live").length;
  const q = rep.qloo_calls || {};
  ok(req && q.live === live200 && q.live > 0, `${idea}: the card says ${q.live} live, ${q.recorded} recorded, ${q.failed} failed; the server log has ${live200} live 200 answers of ${logged.length} for request ${req}`);
  await sleep(22000);
}
const tr = await get(`/api/trace?hash=${OLD}`);
ok(/recorded 2026-10-22/i.test(String(tr.label || "")) && !/^LIVE/.test(String(tr.label || "")), `the trace of the 22 Oct report: "${String(tr.label || "").slice(0, 60)}"`);
const rp = await get(`/api/report?hash=${OLD}`);
ok(/recorded 2026-10-22/i.test(String(rp.label || "")) && (rp.qloo_calls || {}).live === 0, `/api/report of the 22 Oct report: "${String(rp.label || "").slice(0, 60)}", ${(rp.qloo_calls || {}).live} live`);
const st = await get("/api/qloo/status");
const browser = await chromium.launch();
try {
  for (const [name, url] of [["front door", FRONT], ["/app/", APP + "/app/"]]) {
    for (const width of [390, 1280]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      await page.goto(url + "?t=" + Date.now(), { waitUntil: "networkidle", timeout: 120000 }).catch(() => null);
      await page.waitForTimeout(2500);
      const shown = await page.evaluate(() => [...document.querySelectorAll("body *")].some((e) => e.offsetParent !== null && /2 more examples return when Qloo answers again/.test(e.textContent || "") && e.children.length === 0));
      ok(st.limited || !shown, `${name} ${width}: the "2 more examples" line ${shown ? "shown" : "absent"} while Qloo ${st.limited ? "limits" : "answers"}`);
      await page.close();
    }
  }
} finally { await browser.close(); }
log(fails.length ? `FAIL test_live_honest_v2: ${fails.length} of ${lines.length - 1} checks failed; first: ${fails[0].slice(0, 150)}`
  : `PASS test_live_honest_v2: 6 of 6 fresh checks count exactly the live 200s in the server log, the 22 Oct report is "recorded 2026-10-22", the line absent at 4 views`);
if (OUT) appendFileSync(OUT, `\n${new Date().toISOString()}\n` + lines.join("\n") + "\n");
process.exit(fails.length ? 1 : 0);
