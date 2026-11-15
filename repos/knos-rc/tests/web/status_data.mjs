// What the status view is told (web/status_data.js), with no browser: node tests/web/status_data.mjs
// Read from the recorded sample of the relay log (tests/web/recorded/relay_log_stages.json) and from small logs
// written here; every expected value is worked by hand from those lines.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { summarise, relayLines, reason, headline, statesOfLine, statesHtml, STATES, LOG_BOT, RECENT } from "../../web/status_data.js";

const here = dirname(fileURLToPath(import.meta.url));
const doc = JSON.parse(readFileSync(join(here, "recorded", "relay_log_stages.json"), "utf8"));
let failed = 0;
const same = (what, got, want) => { const ok = JSON.stringify(got) === JSON.stringify(want); if (!ok) failed++; console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : `: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`); };
const iso = (t) => new Date(t * 1000).toISOString().replace(".000Z", "Z");
const T = 1791100000, now = doc.now;      // the sample's own clock: its last comment is at T + 5500, its status line was rewritten at T + 5460
const stats = { updated: "2026-10-05 00:32 UTC", latency: { merge_to_paid: { n: 39, p50: 25, p95: 164 }, attempts: { pay: { completion: 0.9 } } } };

const s = summarise(doc.comments, stats, now);
same("only the log's own workflow counts: a stranger's comment is no line", relayLines(doc.comments).some((l) => l.text.includes("thanks")), false);
same("the worker ran in the last 10 minutes, by its status line", [s.worker.ranRecently, s.worker.ago, s.worker.from], [true, 60, "status"]);
same("the last round and its duration", s.lastRound, { at: T + 5458, seconds: 1, tokens: 0 });
same("nothing is waiting", s.waiting, { tokens: 0, oldestSeconds: 0, asOf: T + 5458 });
same("refused in 24 h, with the reasons (the misposted copy among them, its token's id left out)", s.refused, { count: 3, reasons: [
  { reason: "no open bounty for this issue: it was refunded at its deadline", count: 1, last: T + 5400 },
  { reason: "this comment cannot carry its token : posted as knos-proof, but its audience is a fund token's", count: 1, last: T + 5400 },
  { reason: "the terms the token names are not the bounty's (error 87)", count: 1, last: T + 4830 }] });
same("retries in 24 h: the relay's own count, and the part that shows on carried lines", s.retries, { count: 5, carried: 5 });
same("answered in 24 h (the crank's lines name no token and are not counted)", s.answered, { ok: 10, failed: 3 });
same("the measured wait comes from stats.json as it is", s.measured, { n: 39, p50: 25, p95: 164, completion: 0.9, updated: "2026-10-05 00:32 UTC" });
same("the headline", s.headline, "The relay ran 60 s ago. Nothing is waiting. In 24 hours: 10 carried, 3 refused, 5 retries.");

// eleven minutes on with nothing new: the worker did not run, and the view says what to do
const late = summarise(doc.comments, stats, T + 5460 + RECENT + 60);
same("not in the last 10 minutes", [late.worker.ranRecently, late.worker.ago], [false, 660]);
same("the headline then", late.headline.startsWith("The relay has written nothing for 11 min: tokens posted now wait until it runs again, or relay them yourself with `knos relay`."), true);

// tokens waiting, and the oldest's age; a day later the old refusals are out of the window
const bot = { login: LOG_BOT };
const waiting = [{ user: bot, created_at: iso(T), updated_at: iso(T + 300), body: `knos-relay status - - ok at=${iso(T + 299)} round=4 tokens=2 waiting=3 oldest=185 retried=7 refused=1` },
  { user: bot, created_at: iso(T + 200), body: "knos-relay proof o/r#5 " + "ab".repeat(8) + " ok sig=s1 wait=3 chain=9 tries=3 note=paid tries=40 t=12" },
  { user: bot, created_at: iso(T - 2 * 86400), body: "knos-relay fund o/r#1 " + "cd".repeat(8) + " fail the balance does not hold that much" }];
const w = summarise(waiting, null, T + 301);
same("three tokens waiting, the oldest for 185 s; the round took 4 s and carried 2", [w.waiting, w.lastRound], [{ tokens: 3, oldestSeconds: 185, asOf: T + 299 }, { at: T + 299, seconds: 4, tokens: 2 }]);
same("tries= is read before note=, and the relay's count includes tokens still waiting", w.retries, { count: 7, carried: 2 });
same("a refusal older than 24 h is not counted, and stats that are missing are null", [w.refused.count, w.measured], [0, null]);
same("its headline", w.headline, "The relay ran 1 s ago. 3 tokens waiting, the oldest for 3 min. In 24 hours: 1 carried, 0 refused, 7 retries.");

// a log from a relay that writes no status line yet: what it cannot say is null, and its newest line still tells whether it ran
const old = summarise(waiting.slice(1), stats, T + 260);
same("no status line: waiting and the last round are unknown, not zero", [old.waiting, old.lastRound, old.worker.ranRecently, old.worker.from, old.retries], [null, null, true, "line", { count: 2, carried: 2 }]);
same("an empty log", [summarise([], null, T).worker, summarise({ comments: [] }, null, T).headline], [{ ranRecently: false, lastSeen: null, ago: null, from: null }, "The relay's log has no line of its own yet."]);
same("a reason keeps its words and drops what names one token", reason("this comment cannot carry its token (0a1b2c3d...): posted  as knos-proof"), "this comment cannot carry its token : posted as knos-proof");
same("the headline is a function of the summary alone", headline(s), s.headline);

// ---- the five states of the latest round, and the status comment's last rounds -------------------------------------------
same("the recorded log is 0.3.15's: no line has its times, so no round's states are claimed, and it lists no rounds", [s.latest, s.rounds], [null, []]);
const id = "ab".repeat(8), id2 = "cd".repeat(8);
const timed = [{ user: bot, created_at: iso(T), updated_at: iso(T + 300), body: [`knos-relay status - - ok at=${iso(T + 299)} round=4 tokens=2 waiting=1 oldest=20 retried=0 refused=1`,
    `knos-relay round o/r#6 ${id2.slice(0, 8)} ok order=- state=waiting seconds=20 kind=proof`, `knos-relay round o/r#5 ${id.slice(0, 8)} ok order=${"J".repeat(44)} state=confirmed seconds=12 kind=proof`,
    "knos-relay round o/r#1 0123abcd ok order=- state=refused seconds=0 kind=fund"].join("\n") },
  { user: bot, created_at: iso(T + 100), body: `knos-relay fund o/r#4 ${"ef".repeat(8)} ok sig=s0 wait=2 chain=3 note=funded t=5` },      // an older line, with no times
  { user: bot, created_at: iso(T + 200), body: `knos-relay proof o/r#5 ${id} ok sig=s1,s2 queue=1 workflow=6 wait=3 chain=9 queued_at=${T + 188}.0 seen_at=${T + 191}.0 sent_at=${T + 191}.4 confirmed_at=${T + 200}.0 note=paid sent_at=1 to W t=12` },
  { user: { login: "mallory" }, created_at: iso(T + 250), body: `knos-relay round o/r#9 deadbeef ok order=- state=confirmed seconds=1 kind=proof` }];
const t = summarise(timed, null, T + 301);
same("the latest round: the five states by name, each with the time its log line gives and its seconds from the one before", t.latest, { kind: "proof", where: "o/r#5", id, states: [
  { name: "received", at: T + 182, seconds: null }, { name: "accepted", at: T + 188, seconds: 6 }, { name: "submitted", at: T + 191.4, seconds: 3 },
  { name: "confirmed", at: T + 200, seconds: 9 }, { name: "finalized", at: null, seconds: null }] });
same("the names are the five, in order", [STATES, t.latest.states.map((x) => x.name)], [["received", "accepted", "submitted", "confirmed", "finalized"], STATES]);
same("the status comment's rounds, newest first: where, the order when the relay named one, the state and the seconds", t.rounds, [
  { where: "o/r#6", id: id2.slice(0, 8), order: null, state: "waiting", seconds: 20, kind: "proof" }, { where: "o/r#5", id: id.slice(0, 8), order: "J".repeat(44), state: "confirmed", seconds: 12, kind: "proof" },
  { where: "o/r#1", id: "0123abcd", order: null, state: "refused", seconds: 0, kind: "fund" }]);
same("a round line is no token's verdict: the counts are as before (one carried with times, one without; nobody else's line counts)", [t.answered, t.refused.count, t.waiting], [{ ok: 2, failed: 0 }, 0, { tokens: 1, oldestSeconds: 20, asOf: T + 299 }]);
same("a line whose relay sent nothing (`-`) claims no time for it", statesOfLine({ fields: { queued_at: "100.0", seen_at: "103.0", sent_at: "-", confirmed_at: "-" } }).map((x) => x.at), [null, 100, null, null, null]);
const html = statesHtml(t.latest);
same("the states as the page shows them: .k-step with data-state, a time only where the log has one", [(html.match(/class="k-step"/g) || []).length, (html.match(/data-state="done"/g) || []).length, html.includes('data-step="finalized" data-state="idle"><strong>finalized</strong> <span class="k-num">not in the log'),
  html.includes(`data-step="accepted" data-state="done"><strong>accepted</strong> <span class="k-num">${iso(T + 188).slice(11, 19)} UTC, 6 s`), statesHtml(null)], [5, 4, true, true, ""]);
same("text from the log is escaped", statesHtml({ where: '"><img src=x>', states: [] }).includes("<img"), false);

console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
