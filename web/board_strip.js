// The weekly leaderboard as a strip for the first screen: the board's top rows, each a bar with its interval.
//
//   renderBoardStrip(el, { feed, rows, href })   draws it in `el`; nothing is drawn when the feed holds no placed agent
//   boardStripHtml(ctx), stripRows(ctx)          the same as a string; the rows it shows
//   stripSkeleton(rows)                          grey bars of the strip's own size, shown until the feed has answered
//
// One line an agent: its name (a link to its public record, #record=<slug>), the share that failed a check at merge as
// a bar from 0 with the 95% interval across its end, and the count beside its sample ("3 of 44"). Placed agents only,
// by place. `feed` is docs/index.json as read (the site's agent_index.json); `board` is the same rows already made
// (web/index_board.js makes them from the weekly series). The bars grow in once; with `prefers-reduced-motion:
// reduce` they are simply there. This file imports nothing: the first screen asks for it after its first paint.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c]));
const pct = (x) => `${(x * 100).toFixed(1)}%`;
const num = (n) => Number(n).toLocaleString("en-US");
const FEED_SCHEMA = "knos.agent-pr-index/1";
export const STRIP_WORDS = 40;
const STRIP_STYLE = `<style>
.board-strip{display:grid;gap:8px;min-width:0}
.board-strip .bs-head{margin:0;display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline;justify-content:space-between;font-size:.86em}
.board-strip .bs-head strong{font-weight:600;color:var(--ink,#15171c)}
.board-strip .bs-head time{color:var(--ink-2,#5a606b);font-variant-numeric:tabular-nums;margin-left:6px}
.board-strip ol{list-style:none;margin:0;padding:0;display:grid;gap:6px}
.board-strip li{display:grid;grid-template-columns:6.5em minmax(60px,1fr) 5.5em;gap:10px;align-items:center;min-width:0;min-height:22px}
.board-strip li a{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.board-strip .bs-bar{position:relative;display:block;height:10px;border-radius:5px;background:var(--paper-2,#eeece5);box-shadow:inset 0 0 0 1px var(--line,#e1dfd7)}
.board-strip .bs-fill{position:absolute;left:0;top:0;bottom:0;border-radius:5px 0 0 5px;background:var(--accent,#5a606b);opacity:.75;transform-origin:left center}
.board-strip .bs-whisker{position:absolute;top:50%;height:2px;margin-top:-1px;background:var(--ink,#15171c)}
.board-strip .bs-whisker::before,.board-strip .bs-whisker::after{content:"";position:absolute;top:-4px;width:2px;height:10px;background:inherit}
.board-strip .bs-whisker::before{left:0}.board-strip .bs-whisker::after{right:0}
.board-strip .bs-n{font-variant-numeric:tabular-nums;white-space:nowrap;font-size:.86em;text-align:right;color:var(--ink-2,#5a606b)}
@media (prefers-reduced-motion: no-preference){
.board-strip.bs-anim .bs-fill{transition:transform var(--dur-3,480ms) var(--ease,cubic-bezier(.2,.7,.2,1))}
.board-strip.bs-anim .bs-whisker{transition:opacity var(--dur-2,240ms) var(--ease,cubic-bezier(.2,.7,.2,1)) var(--dur-2,240ms)}
.board-strip.bs-anim:not(.in) .bs-fill{transform:scaleX(0)}
.board-strip.bs-anim:not(.in) .bs-whisker{opacity:0}
}
</style>`;
const slugOf = (agent) => String(agent).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");

export function stripRows(ctx = {}) {
  const board = (ctx.feed && ctx.feed.schema === FEED_SCHEMA && Array.isArray(ctx.feed.weeks) ? ctx.feed.weeks[0] : null) || ctx.board || null;
  if (!board || !board.week) return { week: null, rows: [] };
  return { week: board.week, rows: (board.rows || []).filter((r) => r.rank != null && r.merged && Array.isArray(r.ci95)).slice(0, ctx.rows || 4) };
}

export function boardStripHtml(ctx = {}) {
  const { week, rows } = stripRows(ctx);
  if (!rows.length) return "";
  return `<div class="board-strip" data-week="${esc(week)}">${STRIP_STYLE}
    <p class="bs-head"><span><strong>Failed a check at merge</strong><time class="k-num" datetime="${esc(week)}" title="Week of ${esc(week)}">${esc(week)}</time></span> <a href="${esc(ctx.href || "#index")}">See the board</a></p>
    <ol class="bs-rows" data-not-prose>${rows.map((r) => { const [lo, hi] = r.ci95; return `<li data-agent="${esc(r.agent)}"><a href="#record=${esc(slugOf(r.agent))}">${esc(r.agent)}</a>
      <span class="bs-bar" role="img" aria-label="${esc(`${pct(r.share)}, 95% interval ${pct(lo)} to ${pct(hi)}`)}"><span class="bs-fill" style="width:${(r.share * 100).toFixed(1)}%"></span><span class="bs-whisker" style="left:${(lo * 100).toFixed(1)}%;width:${Math.max(1, (hi - lo) * 100).toFixed(1)}%"></span></span>
      <span class="bs-n k-num">${esc(num(r.failed_at_merge))} of ${esc(num(r.merged))}</span></li>`; }).join("")}</ol>
  </div>`;
}

/** Grey bars where the strip will be, as tall as the strip of `rows` rows: nothing moves when the feed answers.
 *  index.html holds the same markup, so the first paint has it before any script (app.css draws .bs-sk). */
export const stripSkeleton = (rows = 4) => `<div class="board-strip" aria-hidden="true"><p class="bs-head"><i class="bs-sk" style="width:12em"></i></p>
  <ol class="bs-rows">${Array.from({ length: rows }, () => "<li><i class=\"bs-sk\"></i><i class=\"bs-sk\"></i><i class=\"bs-sk\"></i></li>").join("")}</ol></div>`;

// How many words the strip says, labels and figures counted: held under STRIP_WORDS by tests/web/supplier_record.mjs.
export const stripWords = (html) => (html.replace(/<style>[\s\S]*?<\/style>/g, " ").replace(/<[^>]*>/g, " ").match(/[A-Za-z0-9][\w'%.,/-]*/g) || []).length;
const reduced = () => typeof matchMedia !== "function" || matchMedia("(prefers-reduced-motion: reduce)").matches;

export function renderBoardStrip(el, ctx = {}) {
  el.innerHTML = boardStripHtml(ctx);
  const root = el.querySelector ? el.querySelector(".board-strip") : null;
  if (root && !reduced() && typeof requestAnimationFrame === "function") {       // the bars grow in once; a reader who asked for no motion sees them drawn
    root.classList.add("bs-anim");
    requestAnimationFrame(() => requestAnimationFrame(() => root.classList.add("in")));
  }
  return el;
}
