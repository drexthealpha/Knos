// Q3 test_paper_live, live: three DOIs each get Open or Not yet (REFUSE) with at least 3 live Qloo signals, and the
// server's own call log holds 0 Qloo HTTP 400 lines for those checks (GET /api/calls, by the check's request id).
//
//   node scripts/test_paper_live.mjs [result file]
import { appendFileSync } from "node:fs";
import { randomBytes } from "node:crypto";

const APP = "https://knos.onrender.com";
const OUT = process.argv[2] || "";
const DOIS = ["10.1038/nature14539", "10.1126/science.1225829", "10.1038/s41586-021-03819-2"];
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); if (OUT) appendFileSync(OUT, s + "\n"); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const again = async (f) => { try { return await f(); } catch { await sleep(30000); return await f(); } };   // a dropped connection, once
const post = (body) => again(async () => (await fetch(APP + "/api/check", { method: "POST", headers: { "Content-Type": "application/json", "User-Agent": "knos-q3-test" }, body: JSON.stringify(body) })).json());
const calls = async () => ((await again(async () => (await fetch(APP + "/api/calls")).json())).calls || []);

let live = 0;
for (const doi of DOIS) {
  try {
    const w = await post({ idea: doi });
    const pick = (w.readings || []).find((r) => r.kind === "product") || (w.readings || []).find((r) => r.kind !== "exact");
    const idea = pick ? pick.text : doi;
    const req = randomBytes(8).toString("hex");
    await sleep(22000);                                          // the visitor's pace
    const c = await post({ idea, picked: true, req });
    const v = (c.decision || {}).verdict, n = (c.qloo_calls || {}).live || 0;
    const mine = (await calls()).filter((x) => x.req === req);
    const bad = mine.filter((x) => String(x.status) === "400").length;
    live += n;
    ok(["OPEN", "REFUSE"].includes(v) && n >= 3 && bad === 0,
      `${doi} read as "${idea}": ${v === "OPEN" ? "Open" : v === "REFUSE" ? "Not yet" : v}, ${n} live Qloo signals, ${bad} HTTP 400 lines of ${mine.length} in the server log`);
  } catch (e) {
    ok(false, `${doi}: ${e.name}: ${String(e.message).slice(0, 120)}`);
  }
  await sleep(22000);
}
log(fails.length ? `FAIL test_paper_live: ${fails.length} of ${DOIS.length} DOIs failed; first: ${fails[0].slice(0, 160)}`
  : `PASS test_paper_live: ${DOIS.length} of ${DOIS.length} DOIs answered Open or Not yet with 3+ live Qloo signals, 0 HTTP 400 lines; ${live} live calls`);
process.exit(fails.length ? 1 : 0);
