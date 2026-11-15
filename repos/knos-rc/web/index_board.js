// The Agent PR Index as a leaderboard for the site. Nothing here asks the network for anything: the caller hands in
// docs/agent_weekly.json as it read it (and, when it has it, docs/index.json, which carries the disputes), and gets
// HTML back. No font, picture or script from anywhere else is used; the bars and the badges are drawn here.
//
//   renderIndexBoard(el, weekly[, week | { week, feed }])   draws the newest week (or `week`), with a picker for the others
//   indexBoardHtml(weekly, week[, feed])                    the same as a string
//   boardOf(weekly, week)                                   the rows: the same counts scripts/agent_pr_board.py `board` gives
//   agentBadgeSvg(row, week)                                one agent's row as a small badge, an SVG string
//   disputeUrl(agent, week)                                 a new "Dispute a row" issue with the agent and the week filled in
//   renderBoardStrip(el, { weekly | feed, rows, href })     the top rows as bars with whiskers, for a first screen (web/board_strip.js)
// Every row of the board names its agent as a link to that agent's public record (#record=<slug>, web/supplier_record.js).
// Every row also links its vendor's page (#vendor=<slug>, web/vendor.js): the numbers, a right of reply, the disputes.
//
// A row: of an agent's merged pull requests that claimed passing tests and whose checks had finished, how many had a
// failed check, over every week read up to and including the one shown. The share is a bar from 0; its 95% Wilson
// interval is the whisker across the bar's end; the count and its total stand beside it, so a sample size is never
// hidden behind a percentage. An agent under the file's `min_claims_to_rank` has no place and is shown with its
// counts. Bars and whiskers grow in once when the board comes into view, and again when another week is picked;
// with `prefers-reduced-motion: reduce` they are simply there. A statement on the board is 12 words at most. The
// method is docs/reference/INDEX.md.

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c]));
const pct = (x) => `${(x * 100).toFixed(1)}%`;
const num = (n) => Number(n).toLocaleString("en-US");
const r4 = (x) => Math.round(x * 1e4) / 1e4;
export const TOO_FEW = "too few to rank";
const slugOf = (agent) => String(agent).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
export const ISSUES = "https://github.com/drexthealpha/Knos/issues";
export const TEMPLATE = "dispute-index-row.yml";
export const FEED_SCHEMA = "knos.agent-pr-index/1";

// Every week any agent has a row for, newest first.
export const weeksOf = (weekly) => [...new Set(Object.values(weekly.agents || {}).flatMap((a) => (a.weeks || []).map((w) => w.week)))].sort().reverse();

// The 95% Wilson score interval of k in n, to four places: the same numbers scripts/agent_pr_index.py `wilson` gives.
export function wilson(k, n, z = 1.96) {
  if (!n) return null;
  const p = k / n, d = 1 + (z * z) / n, mid = (p + (z * z) / (2 * n)) / d, half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
  return [r4(Math.max(0, mid - half)), r4(Math.min(1, mid + half))];
}

export function disputeUrl(agent, week) {
  return `${ISSUES}/new?${new URLSearchParams({ template: TEMPLATE, title: `Dispute a row: ${agent}, week of ${week}`, agent, week })}`;
}

// The board of `week`: every agent's row over the weeks up to and including it; placed agents first, by place.
export function boardOf(weekly, week) {
  const least = weekly.min_claims_to_rank ?? 30;
  const rows = Object.entries(weekly.agents || {}).map(([agent, a]) => {
    const mine = (a.weeks || []).filter((w) => w.week <= week), judged = mine.filter((w) => w.ci_finished);
    const known = judged.every((w) => w.merged_despite_failed_check != null);
    const k = known ? judged.reduce((s, w) => s + w.merged_despite_failed_check.k, 0) : null, n = known ? judged.reduce((s, w) => s + w.merged_despite_failed_check.n, 0) : null;
    return { agent, weeks: mine.length, claimed_passing: mine.reduce((s, w) => s + (w.claimed_passing || 0), 0), merged: n, failed_at_merge: k,
      share: n ? r4(k / n) : null, ci95: n ? wilson(k, n) : null, rank: null, status: n == null ? "not read" : n >= least ? "ranked" : TOO_FEW,
      overlaps_above: false, disputed: [], dispute: disputeUrl(agent, week), verified: mine.filter((w) => w.week === week).reduce((s, w) => s + Number(w.verified || 0), 0) };
  });
  // by the exact share (k1/n1 against k2/n2 as whole numbers), so equal shares share a place whatever the rounding
  const placed = rows.filter((r) => r.status === "ranked").sort((x, y) => x.failed_at_merge * y.merged - y.failed_at_merge * x.merged);
  placed.forEach((r, i) => {
    const same = placed.findIndex((x) => x.failed_at_merge * r.merged === r.failed_at_merge * x.merged);
    r.rank = same + 1;
    r.overlaps_above = i > 0 && r.ci95[0] <= placed[i - 1].ci95[1];
  });
  const reads = Object.values(weekly.agents || {}).flatMap((a) => (a.weeks || []).filter((w) => w.week <= week).map((w) => w.read)).filter(Boolean).sort();
  return { week, read: reads[reads.length - 1] || weekly.read || null, min_claims_to_rank: least, rows: [...placed, ...rows.filter((r) => r.status !== "ranked")] };
}

// The same board with what only the feed knows: which rows are disputed, and where.
function withFeed(board, feed) {
  const theirs = feed && feed.schema === FEED_SCHEMA && Array.isArray(feed.weeks) ? feed.weeks.find((w) => w.week === board.week) : null;
  if (!theirs) return board;
  const by = Object.fromEntries((theirs.rows || []).map((r) => [r.agent, r]));
  return { ...board, rows: board.rows.map((r) => ({ ...r, disputed: Array.isArray(by[r.agent]?.disputed) ? by[r.agent].disputed.filter((d) => /^https:\/\//.test(String(d.issue))) : [] })) };
}

// ---- the badge: one agent's row, small enough for a README. Grey for every agent: a badge states a count, it does not judge.
const width = (text) => Math.round(text.length * 6.4) + 12;
export const BADGE_LABEL = "agent pr index";
export function badgeMessage(row, week) {
  const counts = row.merged ? `${row.failed_at_merge} of ${row.merged} merged had a failed check` : row.merged === 0 ? "no merged pull request read" : "not read";
  return `${row.agent}: ${counts}, week of ${week}`;
}
export function agentBadgeSvg(row, week) {
  const msg = badgeMessage(row, week), a = width(BADGE_LABEL), b = width(msg);
  const title = `Agent PR Index, week of ${week}: ${row.agent}. ${row.merged ? `Of ${row.merged} merged pull requests that claimed passing tests, ${row.failed_at_merge} had a failed check (95% interval ${pct(row.ci95[0])} to ${pct(row.ci95[1])}).` : "No merged pull request was read."} A failed check is not always a failed test or a false claim.`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${a + b}" height="20" viewBox="0 0 ${a + b} 20" role="img" aria-label="${esc(BADGE_LABEL)}: ${esc(msg)}"><title>${esc(title)}</title>`
    + `<rect width="${a}" height="20" fill="#24292f"/><rect x="${a}" width="${b}" height="20" fill="#57606a"/>`
    + `<g fill="#fff" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">`
    + `<text x="${a / 2}" y="14" textLength="${a - 12}">${esc(BADGE_LABEL)}</text><text x="${a + b / 2}" y="14" textLength="${b - 12}">${esc(msg)}</text></g></svg>`;
}

// ---- the row
function rateCell(r) {
  if (r.merged == null) return `<span class="ib-none">not read</span>`;
  if (!r.merged) return `<span class="ib-count k-num">0 of 0 merged</span>`;
  const [lo, hi] = r.ci95, said = `${r.failed_at_merge} of ${r.merged} merged had a failed check: ${pct(r.share)}, 95% interval ${pct(lo)} to ${pct(hi)}`;
  return `<span class="ib-share k-num">${pct(r.share)}</span> <span class="ib-count k-num">${esc(num(r.failed_at_merge))} of ${esc(num(r.merged))} merged</span>
    <span class="ib-bar" role="img" aria-label="${esc(said)}"><span class="ib-fill" style="width:${(r.share * 100).toFixed(1)}%"></span><span class="ib-whisker" style="left:${(lo * 100).toFixed(1)}%;width:${Math.max(1, (hi - lo) * 100).toFixed(1)}%"></span></span>
    <span class="ib-ci k-num">${pct(lo)} to ${pct(hi)}</span>`;
}

function rowHtml(r, week, least) {
  const place = r.rank != null ? `<strong class="ib-place k-num">${esc(r.rank)}</strong>${r.overlaps_above ? ` <span class="ib-none ib-overlap" title="Its interval reaches into the one above">overlaps</span>` : ""}`
    : `<span class="ib-none ib-unranked"${r.status === TOO_FEW ? ` title="Fewer than ${esc(least)} merged claims read"` : ""}>${esc(r.status)}</span>`;
  const marks = r.disputed.map((d) => ` <a class="ib-disputed" href="${esc(d.issue)}" target="_blank" rel="noopener">† disputed</a>`).join("");
  return `<tr data-agent="${esc(r.agent)}" data-placed="${r.rank != null}" data-disputed="${r.disputed.length > 0}"><td>${place}</td><th scope="row"><a class="ib-record" href="#record=${esc(slugOf(r.agent))}">${esc(r.agent)}</a>${marks}</th>
    <td class="ib-head">${rateCell(r)}</td>
    <td class="ib-n k-num">${esc(num(r.claimed_passing))}</td>
    <td class="ib-act"><a class="ib-dispute" href="${esc(disputeUrl(r.agent, week))}" target="_blank" rel="noopener">Dispute this row</a>
      <a class="ib-vendor" href="#vendor=${esc(slugOf(r.agent))}">Vendor page and reply</a>
      <details class="k-more ib-badge"><summary>Badge</summary><span class="ib-svg">${agentBadgeSvg(r, week)}</span>
        <button type="button" class="k-btn quiet ib-copy" data-agent="${esc(r.agent)}">Copy SVG</button></details></td></tr>`;
}

// Under 720 px a row is a block, not a strip to scroll: place, agent and its claims on one line, the bar under them at the
// card's width, then the row's links. The column heads stay for a screen reader.
const STYLE = `<style>
@media (max-width: 720px) { .index-board #ib-table, .index-board #ib-table tbody { display: block; min-width: 0; width: 100%; } .index-board #ib-table thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); } .index-board #ib-table tbody tr { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 4px 12px; align-items: baseline; padding: 14px 0; border-bottom: 1px solid var(--line); } .index-board #ib-table td, .index-board #ib-table th { display: block; padding: 0; border: 0; min-width: 0; } .index-board #ib-table td.ib-n { grid-row: 1; grid-column: 3; color: var(--ink-2); font-size: var(--s0); } .index-board #ib-table td.ib-n::after { content: " claimed"; } .index-board #ib-table td.ib-head, .index-board #ib-table td.ib-act { grid-column: 1 / -1; } .index-board #ib-table td.ib-act { display: flex; flex-wrap: wrap; gap: 4px 16px; align-items: baseline; } .index-board #ib-table td.ib-act details { border: 0; margin: 0; padding: 0; } .index-board .ib-bar { min-width: 0; } .index-board #ib-table td.ib-act details { min-width: 0; max-width: 100%; } .index-board .ib-svg { display: block; max-width: 100%; overflow-x: auto; } }
.index-board .ib-bar{position:relative;display:block;height:10px;min-width:200px;margin:4px 0 2px;border-radius:var(--radius,4px);background:var(--paper-2,var(--soft,#eeece5));border:1px solid var(--line,#e1dfd7)}
.index-board .ib-fill{position:absolute;left:0;top:0;bottom:0;border-radius:3px 0 0 3px;background:var(--accent,var(--ink-2,#5a606b));opacity:.7;transform-origin:left center}
.index-board .ib-whisker{position:absolute;top:50%;height:2px;margin-top:-1px;background:var(--ink,var(--fg,#15171c));transform-origin:center}
.index-board .ib-whisker::before,.index-board .ib-whisker::after{content:"";position:absolute;top:-4px;width:2px;height:10px;background:inherit}
.index-board .ib-whisker::before{left:0}.index-board .ib-whisker::after{right:0}
@media (prefers-reduced-motion: no-preference){
.index-board.ib-anim .ib-fill,.index-board.ib-anim .ib-whisker{transition:transform var(--dur-3,480ms) var(--ease,cubic-bezier(.2,.7,.2,1)),opacity var(--dur-2,240ms) var(--ease,cubic-bezier(.2,.7,.2,1))}
.index-board.ib-anim .ib-whisker{transition-delay:var(--dur-2,240ms)}
.index-board.ib-anim:not(.in) .ib-fill{transform:scaleX(0)}
.index-board.ib-anim:not(.in) .ib-whisker{transform:scaleX(0);opacity:0}
}
.index-board .ib-head .ib-share{font-size:1.25em;font-weight:700}
.index-board .ib-count{font-weight:600;white-space:nowrap}
.index-board .ib-ci,.index-board .ib-none{color:var(--ink-2,var(--muted,#5a606b));font-size:.86em}
.index-board .ib-ci{white-space:nowrap;display:block}
.index-board .ib-n,.index-board .k-num{font-variant-numeric:tabular-nums}
.index-board .ib-disputed{display:inline-block;margin-left:6px;padding:1px 8px;border-radius:999px;border:1px solid var(--bad,#a23b2a);color:var(--bad,#a23b2a);font-size:.82em;font-weight:600;white-space:nowrap;text-decoration:none}
.index-board table{border-collapse:collapse;width:100%}
.index-board th,.index-board td{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--line,#e1dfd7)}
.index-board .ib-wrap{overflow-x:auto;max-width:100%}
.index-board .ib-pick,.index-board .ib-mark{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.index-board .ib-pick select{width:auto;min-width:11em}
.index-board .ib-act{white-space:nowrap}
.index-board .ib-badge{margin-top:6px;white-space:normal}
.index-board .ib-svg{display:block;max-width:100%;overflow-x:auto;margin:6px 0}
.index-board .ib-svg svg{display:block;max-width:none}
.index-board tbody th{white-space:nowrap}
.index-board .ib-record{font-weight:600;font-size:1.05em}
.index-board .ib-notes{margin:8px 0 0;padding-left:1.2em}
</style>`;

export function indexBoardHtml(weekly, week, feed) {
  const weeks = weeksOf(weekly), name = weekly.name || "Agent PR Index";
  const shown = weeks.includes(week) ? week : (weeks.includes(weekly.latest_week) ? weekly.latest_week : weeks[0]);
  if (!shown) return `<div class="index-board"><p class="fine">Holds no week yet.</p></div>`;
  const board = withFeed(boardOf(weekly, shown), feed), least = board.min_claims_to_rank;
  const says = feed && feed.basis && typeof feed.basis.says === "string" ? feed.basis.says : "";   // index.json: which basis these shares are
  const verified = board.rows.reduce((n, r) => n + r.verified, 0), open = board.rows.filter((r) => r.disputed.length).length;
  const pick = weeks.length > 1 ? `<p class="ib-pick"><label for="ib-week">Week of</label>
      <select id="ib-week" aria-controls="ib-table">${weeks.map((w) => `<option value="${esc(w)}"${w === shown ? " selected" : ""}>${esc(w)}</option>`).join("")}</select></p>` : "";
  return `<div class="index-board" data-week="${esc(shown)}">${STYLE}
    <h3 id="ib-title">${esc(name)}, week of ${esc(shown)}</h3>
    ${pick}
    <p class="ib-mark" id="ib-read"><span class="fine">Read ${esc(board.read || "on a day the file does not name")}</span> <span class="fine" id="ib-sum">Adds up every week read through this one.</span>
      <span class="fine" id="ib-open">${open ? `Marks ${esc(open)} disputed ${open === 1 ? "row" : "rows"} with †.` : ""}</span></p>
    <div class="k-table ib-wrap table-wrap"><table id="ib-table" aria-labelledby="ib-title">
      <thead><tr><th scope="col">Place</th><th scope="col">Agent</th><th scope="col">Failed a check at merge</th><th scope="col">Claimed passing</th><th scope="col">Row</th></tr></thead>
      <tbody>${board.rows.map((r) => rowHtml(r, shown, least)).join("")}</tbody></table></div>
    <ul class="fine ib-notes">
      <li id="ib-rate">Count merged claims that had a failed check.</li>
      <li id="ib-bar">The thin line on each bar is the 95% confidence interval.</li>
      <li id="ib-rank">Mark agents under ${esc(least)} merged claims “${TOO_FEW}”.</li>
      <li id="ib-not">Treat a failed check as a record, not proof.</li>
      <li id="ib-pay">Dispute any row; no vendor pays to change one.</li>
      <li id="ib-quality">It does not say any work, code or vendor is free of defects.</li>
    </ul>
    <p class="fine" id="ib-verified"><strong>Verified: ${esc(verified)} this week.</strong> Verified means Knos also paid it on a black-box check.</p>
    ${says ? `<details class="k-more" id="ib-basis"><summary>Which pull requests these shares count</summary><p class="fine">${esc(says)}</p></details>` : ""}
  </div>`;
}

const reduced = () => typeof matchMedia !== "function" || matchMedia("(prefers-reduced-motion: reduce)").matches;

export function renderIndexBoard(el, weekly, opts) {
  const o = typeof opts === "string" || opts == null ? { week: opts } : opts;
  el.innerHTML = indexBoardHtml(weekly, o.week, o.feed);
  if (!el.querySelector) return el;
  const root = el.querySelector(".index-board"), pick = el.querySelector("#ib-week");
  if (pick) pick.addEventListener("change", () => { renderIndexBoard(el, weekly, { ...o, week: pick.value }); const again = el.querySelector("#ib-week"); if (again) again.focus(); });
  for (const b of el.querySelectorAll(".ib-copy")) b.addEventListener("click", () => {
    const svg = b.parentElement.querySelector("svg").outerHTML;
    b.textContent = "Copying";                                  // said at once; the clipboard answers later
    Promise.resolve().then(() => navigator.clipboard.writeText(svg)).then(() => { b.textContent = "Copied"; }, () => {
      const box = document.createElement("textarea");           // no clipboard here: the markup itself, to select and copy
      box.readOnly = true; box.rows = 3; box.value = svg; box.setAttribute("aria-label", "Badge SVG");
      b.replaceWith(box); box.select();
    });
  });
  if (root && !reduced() && typeof IntersectionObserver === "function") {       // the bars grow in once the board is seen
    root.classList.add("ib-anim");
    const seen = new IntersectionObserver((entries) => { if (entries.some((e) => e.isIntersecting)) { root.classList.add("in"); seen.disconnect(); } }, { threshold: 0.1 });
    requestAnimationFrame(() => seen.observe(root));
  }
  return el;
}

// ---- the strip: the board's top rows, small enough for a first screen ---------------------------------------------------
// It lives in web/board_strip.js, a file of its own, so the first screen asks for the strip and not for this whole
// board. Here the same three functions also take the weekly series (ctx.weekly), which they turn into the board first.
import * as strip from "./board_strip.js";
export { STRIP_WORDS, stripWords } from "./board_strip.js";
const boarded = (ctx = {}) => (ctx.weekly && !(ctx.feed && ctx.feed.schema === FEED_SCHEMA) && weeksOf(ctx.weekly).length ? { ...ctx, board: boardOf(ctx.weekly, weeksOf(ctx.weekly)[0]) } : ctx);
export const stripRows = (ctx) => strip.stripRows(boarded(ctx));
export const boardStripHtml = (ctx) => strip.boardStripHtml(boarded(ctx));
export const renderBoardStrip = (el, ctx) => strip.renderBoardStrip(el, boarded(ctx));
