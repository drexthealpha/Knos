// Q4 test_audience_live, live: the 6 front-door chips each read who buys live from Qloo, through /v2/audiences and
// through insights with signal.demographics.audiences; across the 6, at least 4 distinct lift values; 0 audience
// answers from the cache. A question this check asked Qloo live and then read back within the same check counts as live
// (the server's call log, GET /api/calls, by the check's request id).
//
//   node scripts/test_audience_live.mjs [result file]
import { appendFileSync } from "node:fs";
import { randomBytes } from "node:crypto";

const APP = "https://knos.onrender.com";
const OUT = process.argv[2] || "";
const CHIPS = ["a solar powered music festival", "an AI recipe planner for families", "a crypto podcast for beginners",
  "a quantum physics book for kids", "a probiotic kombucha brand", "a recycled ocean plastic swimwear brand"];
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); if (OUT) appendFileSync(OUT, s + "\n"); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const again = async (f) => { try { return await f(); } catch { await sleep(30000); return await f(); } };
const post = (body) => again(async () => (await fetch(APP + "/api/check", { method: "POST", headers: { "Content-Type": "application/json", "User-Agent": "knos-q4-test" }, body: JSON.stringify(body) })).json());
const calls = async () => ((await again(async () => (await fetch(APP + "/api/calls")).json())).calls || []);
const isAud = (c) => /\/v2\/audiences/.test(c.call) || Object.keys(c.params || {}).some((k) => k.startsWith("signal.demographics.audiences"));
const keyOf = (c) => c.call + " " + JSON.stringify(Object.keys(c.params || {}).sort().map((k) => [k, c.params[k]]));

const lifts = new Set();
let live = 0;
for (const idea of CHIPS) {
  try {
    const req = randomBytes(8).toString("hex");
    const c = await post({ idea, picked: true, req });
    const mine = (await calls()).filter((x) => x.req === req && isAud(x));
    const asked = new Set(mine.filter((x) => x.origin === "live").map(keyOf));
    const listing = mine.filter((x) => /\/v2\/audiences/.test(x.call) && x.origin === "live").length;
    const lifted = mine.filter((x) => !/\/v2\/audiences/.test(x.call) && x.origin === "live").length;
    const old = mine.filter((x) => x.origin !== "live" && !asked.has(keyOf(x))).length;     // from the cache, never asked now
    const rows = (c.audiences || []).filter((a) => typeof a.lift === "number");
    for (const a of rows) lifts.add(a.lift.toFixed(4));
    live += mine.filter((x) => x.origin === "live").length;
    ok(listing >= 1 && lifted >= 1 && old === 0,
      `${idea}: /v2/audiences ${listing} live, audience lift calls ${lifted} live, ${old} answers from the cache; lifts ${rows.slice(0, 4).map((a) => `${a.name} ${a.lift.toFixed(4)}`).join(", ") || "none"}`);
  } catch (e) {
    ok(false, `${idea}: ${e.name}: ${String(e.message).slice(0, 120)}`);
  }
  await sleep(22000);
}
ok(lifts.size >= 4, `distinct lift values across the 6 chips: ${lifts.size}`);
log(fails.length ? `FAIL test_audience_live: ${fails.length} of ${lines.length} checks failed; first: ${fails[0].slice(0, 160)}`
  : `PASS test_audience_live: 6 of 6 chips read audiences live through /v2/audiences and signal.demographics.audiences, ${lifts.size} distinct lifts, 0 from the cache; ${live} live audience calls`);
process.exit(fails.length ? 1 : 0);
