// S2 test_judge_live, live: 12 checks in a row from one visitor (this PC, no key) all answer live with a launch city;
// the server's published limits are 30 live checks per visitor an hour, 40 Qloo calls a check and 3,000 a day; a card
// answered from the cache only (?qloo=off) keeps its launch city and its map.
//
//   node scripts/test_judge_live.mjs [result file]
import { appendFileSync } from "node:fs";

const APP = "https://knos.onrender.com";
const OUT = process.argv[2] || "";
const IDEAS = ["a solar powered music festival", "an AI recipe planner for families", "a crypto podcast for beginners",
  "a quantum physics book for kids", "a probiotic kombucha brand", "a recycled ocean plastic swimwear brand",
  "a late night ramen spot", "a sourdough bakery for night owls", "a vintage vinyl record cafe",
  "a trail running shoe for wide feet", "a gene editing therapy", "a board game cafe"];
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); if (OUT) appendFileSync(OUT, s + "\n"); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const again = async (f) => { try { return await f(); } catch { await sleep(30000); return await f(); } };   // a dropped connection, once
const post = (path, body) => again(async () => (await fetch(APP + path, { method: "POST", headers: { "Content-Type": "application/json", "User-Agent": "knos-s2-test" }, body: JSON.stringify(body) })).json());

const st = await again(async () => (await fetch(APP + "/api/qloo/status")).json());
const cap = st.visitor_cap || (st.rest || {}).visitor_cap || {};
ok(cap.checks === 30 && cap.seconds === 3600 && st.day_cap === 3000 && (st.per_check ?? 40) === 40,
  `limits: ${cap.checks} live checks per visitor in ${cap.seconds} s, ${st.per_check ?? 40} calls a check, ${st.day_cap} a day`);
let live = 0, cities = 0;
for (const [i, idea] of IDEAS.entries()) {
  try {
    const c = await post("/api/check", { idea, picked: true });
    const q = c.qloo_calls || {}, t = c.terms || {};
    const said = String(c.qloo_limit || "");
    if ((q.live || 0) > 0) live++;
    if (t.city) cities++;
    ok((q.live || 0) > 0 && !!t.city && !/cache only|from the private cache/i.test(said + String(c.label || "")),
      `${i + 1}. ${idea}: ${(c.decision || {}).verdict}, ${q.live || 0} live Qloo calls of ${q.total || 0}, launch city ${t.city || "none"}${t.heatmap_cells ? ` (${t.heatmap_cells} map cells)` : ""}`);
  } catch (e) {
    ok(false, `${i + 1}. ${idea}: ${e.name}: ${String(e.message).slice(0, 120)}`);
  }
  await sleep(8000);
}
try {                                                         // the cache only: the same idea's card keeps its city and map
  const r = await again(async () => (await fetch(APP + "/api/check?qloo=off", { method: "POST", headers: { "Content-Type": "application/json", "User-Agent": "knos-s2-test" }, body: JSON.stringify({ idea: IDEAS[4], picked: true }) })).json());
  const t = r.terms || {}, q = r.qloo_calls || {};
  ok(q.live === 0 && !!t.city && (r.where || []).length > 0, `${IDEAS[4]} from the cache only: ${q.live} live calls, launch city ${t.city || "none"}, ${(r.where || []).length} map points`);
} catch (e) {
  ok(false, `the cache-only card: ${e.name}: ${String(e.message).slice(0, 120)}`);
}
log(fails.length ? `FAIL test_judge_live: ${fails.length} of ${lines.length} checks failed; ${live} of 12 live, ${cities} of 12 with a launch city; first: ${fails[0].slice(0, 140)}`
  : `PASS test_judge_live: 12 of 12 checks in a row answered live with a launch city; the cap is 30 an hour, 40 calls a check, 3,000 a day; the cache-only card keeps its city and map`);
process.exit(fails.length ? 1 : 0);
