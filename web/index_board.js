// The Agent PR Index as a table for the site: one week at a time, by agent. Nothing here asks the network for
// anything: the caller hands in docs/agent_weekly.json as it read it, and gets HTML back. No font, picture or script
// from anywhere else is used; the interval bars are plain boxes.
//
//   renderIndexBoard(el, weekly[, week])   draws the newest week (or `week`), with a picker for the others
//   indexBoardHtml(weekly, week)           the same as a string
//   boardRows(weekly, week)                the rows it draws: placed agents first, by place; the rest in the file's order
//   sampleOf(row)                          how a row was read: {capped, design, drawn, planned, reported}
//
// The headline of a row is its verified acceptance rate: of the pull requests that claimed passing tests and whose
// checks were read, the share whose checks all passed. It is written with its count and its total ("42 of 56"), so
// the sample size is never hidden behind a percentage, and its 95% interval is drawn as a bar from 0 to 100%. Every
// row also says how it was sampled and whether the sample was capped: that mark is never left out. An agent with too
// few claims has no place, and neither has a row whose rate the file does not hold. Words on the page keep to the
// site's budget: a statement is 12 words at most. The method is docs/INDEX.md.
//
// The table sits in `.k-table` (the site's table that scrolls inside itself); the rules below keep it inside its box
// where that class is not defined yet.

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c]));
const pct = (x) => `${(x * 100).toFixed(1)}%`;
const num = (n) => Number(n).toLocaleString("en-US");
export const TOO_FEW = "too few to rank";
export const NO_RATE = "rate not recorded";
const HEADLINE = "verified_acceptance_rate";

// Every week any agent has a row for, newest first.
export const weeksOf = (weekly) => [...new Set(Object.values(weekly.agents || {}).flatMap((a) => (a.weeks || []).map((w) => w.week)))].sort().reverse();

// A row has a place only when the file ranked it by the headline rate.
const placed = (row) => !!row && row.rank != null && row[HEADLINE] != null && (row.ranked_by ?? HEADLINE) === HEADLINE;

export function boardRows(weekly, week) {
  const rows = Object.entries(weekly.agents || {}).map(([agent, a]) => ({ agent, row: (a.weeks || []).find((w) => w.week === week) || null }));
  return [...rows.filter((r) => placed(r.row)).sort((x, y) => x.row.rank - y.row.rank), ...rows.filter((r) => !placed(r.row))];
}

// How a row was read. `capped` is true unless the file says false: a row that does not say is not called complete.
export function sampleOf(row) {
  const days = Object.values(row.strata || {});
  const known = days.filter((d) => d.reported != null);
  return { capped: row.capped !== false, said: typeof row.capped === "boolean", design: row.design || null,
    drawn: days.length ? days.reduce((n, d) => n + (d.drawn || 0), 0) : null, planned: days.length ? days.reduce((n, d) => n + (d.planned || 0), 0) : null,
    reported: known.length ? known.reduce((n, d) => n + d.reported, 0) : null, days: days.length, daysKnown: known.length };
}

// One share: "k of n", the share, its interval as a bar and in words. `what` names it for a screen reader.
function rateCell(rate, what, none = "not read") {
  if (rate == null) return `<span class="ib-none">${esc(none)}</span>`;
  if (!rate.n) return `<span class="ib-count k-num">0 of 0</span>`;
  const [lo, hi] = rate.ci95, said = `${rate.k} of ${rate.n} ${what}: ${pct(rate.share)}, 95% interval ${pct(lo)} to ${pct(hi)}`;
  return `<span class="ib-share k-num">${pct(rate.share)}</span> <span class="ib-count k-num">${esc(rate.k)} of ${esc(rate.n)}</span>
    <span class="ib-bar" role="img" aria-label="${esc(said)}"><span class="ib-range" style="left:${(lo * 100).toFixed(1)}%;width:${Math.max(1, (hi - lo) * 100).toFixed(1)}%"></span><span class="ib-point" style="left:${(rate.share * 100).toFixed(1)}%"></span></span>
    <span class="ib-ci k-num">${pct(lo)} to ${pct(hi)}</span>`;
}

function cappedMark(s) {
  const word = s.capped ? "capped" : "not capped";
  return `<span class="ib-capped" data-capped="${s.capped}"${s.said ? "" : ` title="The file does not say; treated as capped"`}>${word}</span>`;
}

function sampleCell(row) {
  const s = sampleOf(row);
  const sizes = s.drawn == null ? "" : `<span class="ib-count k-num">drew ${num(s.drawn)} of ${num(s.planned)}</span>
    <span class="ib-ci k-num">${s.reported == null ? "search count not read" : `${num(s.reported)} reported${s.daysKnown < s.days ? ` on ${s.daysKnown} of ${s.days} days` : ""}`}</span>`;
  return `${cappedMark(s)} ${sizes}<span class="ib-ci">${esc(s.design || "design not recorded")}</span>`;
}

function rowHtml({ agent, row }, least) {
  if (!row) return `<tr><td></td><th scope="row">${esc(agent)}</th><td colspan="6" class="ib-none">no row this week</td></tr>`;
  const place = placed(row) ? `<strong class="ib-place k-num">${esc(row.rank)}</strong>`
    : row[HEADLINE] == null ? `<span class="ib-none ib-unranked">${NO_RATE}</span>`
    : `<span class="ib-none ib-unranked" title="Fewer than ${esc(least)} claims with checks read this week">${TOO_FEW}</span>`;
  return `<tr data-agent="${esc(agent)}" data-placed="${placed(row)}"><td>${place}</td><th scope="row">${esc(agent)}</th>
    <td class="ib-head">${rateCell(row[HEADLINE], "claims with checks read passed every check", "not recorded")}</td>
    <td class="ib-n k-num">${row.sampled == null ? `<span class="ib-none">not kept</span>` : esc(num(row.sampled))}</td>
    <td class="ib-n k-num">${esc(num(row.claimed_passing))}</td>
    <td>${rateCell(row.failed_a_check, "with finished CI failed a check")}</td>
    <td>${rateCell(row.merged_despite_failed_check, "merged had a failed check")}</td>
    <td class="ib-sample">${sampleCell(row)}</td></tr>`;
}

const STYLE = `<style>
.index-board .ib-bar{position:relative;display:block;height:8px;min-width:96px;margin:4px 0 2px;border-radius:var(--radius,4px);background:var(--paper-2,var(--soft,#eeece5));border:1px solid var(--line,#e1dfd7)}
.index-board .ib-range{position:absolute;top:0;bottom:0;border-radius:3px;background:var(--ink-2,var(--muted,#5a606b));opacity:.55}
.index-board .ib-point{position:absolute;top:-3px;bottom:-3px;width:2px;margin-left:-1px;background:var(--ink,var(--fg,#15171c))}
.index-board .ib-head .ib-share{font-size:1.25em;font-weight:700}
.index-board .ib-head .ib-range{background:var(--accent,var(--ink-2,#5a606b))}
.index-board .ib-count{font-weight:600;white-space:nowrap}
.index-board .ib-ci,.index-board .ib-none{color:var(--ink-2,var(--muted,#5a606b));font-size:.86em}
.index-board .ib-ci{white-space:nowrap;display:block}
.index-board .ib-n,.index-board .k-num{font-variant-numeric:tabular-nums}
.index-board .ib-capped{display:inline-block;padding:1px 8px;border-radius:999px;border:1px solid var(--line,#e1dfd7);font-size:.82em;font-weight:600;white-space:nowrap}
.index-board .ib-capped[data-capped="true"]{border-color:var(--bad,#a23b2a);color:var(--bad,#a23b2a)}
.index-board .ib-capped[data-capped="false"]{border-color:var(--ok,#2c6e49);color:var(--ok,#2c6e49)}
.index-board table{border-collapse:collapse;width:100%}
.index-board th,.index-board td{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--line,#e1dfd7)}
.index-board .ib-wrap{overflow-x:auto;max-width:100%}
.index-board .ib-pick,.index-board .ib-mark{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.index-board .ib-pick select{width:auto;min-width:11em}
.index-board .ib-notes{margin:8px 0 0;padding-left:1.2em}
</style>`;

export function indexBoardHtml(weekly, week) {
  const weeks = weeksOf(weekly), name = weekly.name || "Agent PR Index", least = weekly.min_claims_to_rank ?? 30;
  const shown = weeks.includes(week) ? week : (weeks.includes(weekly.latest_week) ? weekly.latest_week : weeks[0]);
  if (!shown) return `<div class="index-board"><p class="fine">Holds no week yet.</p></div>`;
  const rows = boardRows(weekly, shown), with_ = rows.filter((r) => r.row);
  const reads = [...new Set(with_.map((r) => r.row.read || weekly.read))].sort().join(" and ");
  const capped = with_.some((r) => sampleOf(r.row).capped);
  const designs = [...new Set(with_.map((r) => r.row.design || "design not recorded"))].join(", ");
  const verified = with_.reduce((n, r) => n + Number(r.row.verified || 0), 0);
  return `<div class="index-board">${STYLE}
    <h3 id="ib-title">${esc(name)}, week of ${esc(shown)}</h3>
    <p class="ib-pick"><label for="ib-week">Week of</label>
      <select id="ib-week" aria-controls="ib-table">${weeks.map((w) => `<option value="${esc(w)}"${w === shown ? " selected" : ""}>${esc(w)}</option>`).join("")}</select></p>
    <p class="ib-mark" id="ib-read">${cappedMark({ capped, said: true })} <span class="fine">Read ${esc(reads)}</span> <span class="fine" id="ib-design">${esc(designs)}</span></p>
    <div class="k-table ib-wrap table-wrap"><table id="ib-table" aria-labelledby="ib-title">
      <thead><tr><th scope="col">Place</th><th scope="col">Agent</th><th scope="col">Verified acceptance rate</th><th scope="col">Sampled</th><th scope="col">Claimed passing</th>
        <th scope="col">Failed a check anyway</th><th scope="col">Merged despite a failed check</th><th scope="col">Sample</th></tr></thead>
      <tbody>${rows.map((r) => rowHtml(r, least)).join("")}</tbody></table></div>
    <ul class="fine ib-notes">
      <li id="ib-rate">Count claims whose checks all passed, over claims read.</li>
      <li id="ib-bar">Read each bar as a 95% interval, 0 to 100%.</li>
      <li id="ib-rank">Place only agents with ${esc(least)} claims read; others stay unranked.</li>
      <li id="ib-not">Treat a failed check as a record, not proof.</li>
    </ul>
    <p class="fine" id="ib-verified"><strong>Verified: ${esc(verified)} this week.</strong> Counts claims Knos also paid on a black-box check.</p>
  </div>`;
}

export function renderIndexBoard(el, weekly, week) {
  el.innerHTML = indexBoardHtml(weekly, week);
  const pick = el.querySelector ? el.querySelector("#ib-week") : null;
  if (pick) pick.addEventListener("change", () => { renderIndexBoard(el, weekly, pick.value); const again = el.querySelector("#ib-week"); if (again) again.focus(); });
  return el;
}
