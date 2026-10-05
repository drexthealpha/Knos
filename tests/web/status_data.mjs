// What the status view is told (web/status_data.js), with no browser: node tests/web/status_data.mjs
// Read from the recorded sample of the relay log (tests/web/recorded/relay_log_stages.json) and from small logs
// written here; every expected value is worked by hand from those lines.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { summarise, relayLines, reason, headline, LOG_BOT, RECENT } from "../../web/status_data.js";

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

console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
