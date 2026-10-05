// What a status view shows about the public relay, worked out from two things anyone can read: the relay's log (the
// comments of the issue labelled knos-relay in drexthealpha/Knos, as GitHub's API returns them) and stats.json.
// Pure functions: nothing here reads the page, the network or the clock (the caller hands in `now`, in seconds).
//
// The log has one line per token the relay answered for, and one comment the relay rewrites once a minute, its
// status line (src/knos/proof/ghrelay.py, status_line):
//
//   knos-relay <kind> <owner/repo>#<n> <token id> ok sig=... [queue= workflow= wait= chain= tries=] note=... t=<s>
//   knos-relay <kind> <owner/repo>#<n> <token id | -> fail <reason>
//   knos-relay status - - ok at=<time> round=<s> tokens=<n> waiting=<n> oldest=<s> retried=<n> refused=<n>
//
// Only lines the log's own workflow wrote count (anyone can comment on a public issue). What the log cannot say is
// null here, never a guess: a relay older than the status line writes none, and then `waiting` and `lastRound` are null.

export const LOG_BOT = "github-actions[bot]";
export const RECENT = 600;          // "the worker ran": something of its own in the log within this many seconds
export const DAY = 86400;

const LINE = /^knos-relay (\S+) (\S+) (\S+) (ok|fail)\b ?(.*)$/;
const seconds = (stamp) => { const t = Date.parse(stamp); return Number.isFinite(t) ? Math.floor(t / 1000) : null; };
const fields = (text) => Object.fromEntries(text.split(/(?:^| )note=/)[0].split(" ").filter((p) => p.includes("=")).map((p) => [p.slice(0, p.indexOf("=")), p.slice(p.indexOf("=") + 1)]));

// Every line of the relay's own in `comments`, oldest first: {kind, where, id, ok, text, fields, at (the comment's
// creation), written (its last edit)}.
export function relayLines(comments) {
  const out = [];
  for (const c of Array.isArray(comments) ? comments : (comments && comments.comments) || []) {
    if (!c || (c.user || {}).login !== LOG_BOT) continue;
    const at = seconds(c.created_at), written = seconds(c.updated_at) ?? at;
    for (const raw of String(c.body || "").split("\n")) {
      const m = LINE.exec(raw.trim());
      if (m) out.push({ kind: m[1], where: m[2], id: m[3], ok: m[4] === "ok", text: m[5], fields: m[4] === "ok" ? fields(m[5]) : {}, at, written });
    }
  }
  return out.sort((a, b) => (a.at ?? 0) - (b.at ?? 0));
}

// A refusal's reason without what is particular to one token, so that the same reason counts as one.
export function reason(text) {
  return String(text).replace(/\([0-9a-f]{8}\.\.\.\)/g, "").replace(/\b[1-9A-HJ-NP-Za-km-z]{32,}\b/g, "<address>").replace(/\s+/g, " ").trim().slice(0, 160);
}

// summarise(relayLog, stats, now) -> what the view shows:
//   worker      { ranRecently, lastSeen (seconds), ago, from: "status" | "line" | null }   ran in the last 10 minutes?
//   lastRound   { at, seconds, tokens } | null         the relay's last pass and how long it took
//   waiting     { tokens, oldestSeconds, asOf } | null tokens seen and not yet answered, and the oldest's age
//   refused     { count, reasons: [{ reason, count, last }] }   lines that said fail in the last 24 h
//   retries     { count, carried }                     tries beyond the first in 24 h (the relay's count; `carried`:
//                                                      the part that shows on lines that went through)
//   answered    { ok, failed }                         token lines in the last 24 h
//   measured    { n, p50, p95, completion, updated } | null     merge to paid, from stats.json
//   headline    one sentence
export function summarise(relayLog, stats, now) {
  const lines = relayLines(relayLog), since = now - DAY;
  const status = lines.filter((l) => l.kind === "status").sort((a, b) => (a.written ?? 0) - (b.written ?? 0)).pop() || null;
  const tokens = lines.filter((l) => l.kind !== "status" && l.where !== "-"), day = tokens.filter((l) => (l.at ?? 0) >= since);
  const num = (v) => (v !== undefined && /^\d+$/.test(v) ? Number(v) : null);
  const said = status ? { at: seconds(status.fields.at) ?? status.written, round: num(status.fields.round), tokens: num(status.fields.tokens),
    waiting: num(status.fields.waiting), oldest: num(status.fields.oldest), retried: num(status.fields.retried), refused: num(status.fields.refused) } : null;
  const newest = Math.max(-1, ...lines.map((l) => Math.max(l.at ?? -1, l.kind === "status" ? l.written ?? -1 : -1)), said ? said.at ?? -1 : -1);
  const lastSeen = newest < 0 ? null : newest;
  const worker = { ranRecently: lastSeen !== null && now - lastSeen <= RECENT, lastSeen, ago: lastSeen === null ? null : Math.max(0, now - lastSeen),
    from: lastSeen === null ? null : status && Math.max(said.at ?? -1, status.written ?? -1) === lastSeen ? "status" : "line" };
  const failed = day.filter((l) => !l.ok), by = new Map();
  for (const l of failed) {
    const key = reason(l.text), had = by.get(key) || { reason: key, count: 0, last: 0 };
    by.set(key, { reason: key, count: had.count + 1, last: Math.max(had.last, l.at ?? 0) });
  }
  const carried = day.filter((l) => l.ok && num(l.fields.tries) > 1).reduce((n, l) => n + num(l.fields.tries) - 1, 0);
  const m = stats && stats.latency && stats.latency.merge_to_paid, tried = stats && stats.latency && stats.latency.attempts && stats.latency.attempts.pay;
  const out = {
    worker,
    lastRound: said && said.round !== null ? { at: said.at, seconds: said.round, tokens: said.tokens ?? 0 } : null,
    waiting: said && said.waiting !== null ? { tokens: said.waiting, oldestSeconds: said.oldest ?? 0, asOf: said.at } : null,
    refused: { count: failed.length, reasons: [...by.values()].sort((a, b) => b.count - a.count || b.last - a.last) },
    retries: { count: said && said.retried !== null ? Math.max(said.retried, carried) : carried, carried },
    answered: { ok: day.filter((l) => l.ok).length, failed: failed.length },
    measured: m && m.n ? { n: m.n, p50: m.p50, p95: m.p95, completion: tried ? tried.completion : null, updated: stats.updated || null } : null,
  };
  out.headline = headline(out);
  return out;
}

const span = (s) => (s < 90 ? `${s} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`);

// One sentence, in plain words: is it running, is anything waiting, did anything go wrong today.
export function headline(s) {
  if (s.worker.lastSeen === null) return "The relay's log has no line of its own yet.";
  const ran = s.worker.ranRecently ? `The relay ran ${span(s.worker.ago)} ago.` : `The relay has written nothing for ${span(s.worker.ago)}: tokens posted now wait until it runs again, or relay them yourself with \`knos relay\`.`;
  const waits = s.waiting === null ? "" : s.waiting.tokens ? ` ${s.waiting.tokens} token${s.waiting.tokens === 1 ? "" : "s"} waiting, the oldest for ${span(s.waiting.oldestSeconds)}.` : " Nothing is waiting.";
  const day = ` In 24 hours: ${s.answered.ok} carried, ${s.refused.count} refused, ${s.retries.count} retr${s.retries.count === 1 ? "y" : "ies"}.`;
  return ran + waits + day;
}
