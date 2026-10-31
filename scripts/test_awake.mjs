// J4 test_awake: something outside this PC (GitHub's runners, .github/workflows/live-window.yml) asks for the front door,
// /app/ and /api/proof at least every 10 minutes until 6 Nov 2026 06:00 UTC; shown by 3 logged asks in a row for each,
// each 10 minutes or less after the one before, all HTTP 200, read from the finished runs' own logs.
//
//   node scripts/test_awake.mjs [result file]
import { appendFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

const OUT = process.argv[2] || "";
const URLS = ["https://drexthealpha.github.io/Knos/", "https://knos.onrender.com/app/", "https://knos.onrender.com/api/proof"];
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); if (OUT) appendFileSync(OUT, s + "\n"); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const gh = (a) => execFileSync("gh", a, { encoding: "utf8", timeout: 300000 });

const wf = gh(["api", "repos/drexthealpha/Knos/contents/.github/workflows/live-window.yml", "--jq", ".content"]);
const text = Buffer.from(wf.replace(/\s/g, ""), "base64").toString("utf8");
ok(/2026-11-06T06:00:00Z/.test(text) && /gh workflow disable live-window\.yml/.test(text) && URLS.every((u) => text.includes(u)),
  "live-window.yml on main asks for the three pages and stops itself from 6 Nov 06:00 UTC");
const runs = JSON.parse(gh(["run", "list", "--workflow", "live-window.yml", "-L", "20", "--json", "databaseId,status,conclusion,createdAt,event"]));
const done = runs.filter((r) => r.status === "completed" && r.conclusion === "success");
let asked = [];
for (const r of done.slice(0, 3)) {
  const logText = gh(["run", "view", String(r.databaseId), "--log"]);
  for (const m of logText.matchAll(/ASKED (\S+) (\S+) (\d{3}) ([\d.]+)/g)) asked.push({ at: Date.parse(m[1]), when: m[1], url: m[2], code: m[3], run: r.databaseId });
}
log(`runs: ${runs.length} (${done.length} finished), asks read: ${asked.length}; on GitHub's runners, outside this PC`);
for (const u of URLS) {
  const rows = asked.filter((a) => a.url === u).sort((a, b) => a.at - b.at);
  let best = 1, run = 1;
  for (let i = 1; i < rows.length; i++) { run = rows[i].at - rows[i - 1].at <= 600000 && rows[i].code === "200" && rows[i - 1].code === "200" ? run + 1 : 1; best = Math.max(best, run); }
  const gaps = rows.slice(1).map((r, i) => Math.round((r.at - rows[i].at) / 1000));
  ok(rows.length >= 3 && best >= 3, `${u}: ${rows.length} asks, ${best} in a row at most 10 minutes apart, all 200 (${rows.slice(-3).map((r) => `${r.when} ${r.code}`).join(", ")}; gaps ${gaps.slice(-3).join(", ")} s)`);
}
log(fails.length ? `FAIL test_awake: ${fails.length} of ${lines.length - 1} checks failed; first: ${fails[0].slice(0, 160)}`
  : `PASS test_awake: the front door, /app/ and /api/proof each asked 3 times in a row at most 10 minutes apart, from GitHub's runners, until 6 Nov 06:00 UTC`);
process.exit(fails.length ? 1 : 0);
