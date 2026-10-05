// The Agent PR Index as a table for the site: one week at a time, by agent. Nothing here asks the network for
// anything: the caller hands in docs/agent_weekly.json as it read it, and gets HTML back. No font, picture or script
// from anywhere else is used; the interval bars are plain boxes.
//
//   renderIndexBoard(el, weekly[, week])   draws the newest week (or `week`), with a picker for the others
//   indexBoardHtml(weekly, week)           the same as a string
//   boardRows(weekly, week)                the rows it draws: ranked agents first, by place; the rest in the file's order
//
// Every share is written with its count and its total ("14 of 56"), so the sample size is never hidden behind a
// percentage, and each has its 95% interval drawn as a bar from 0 to 100%. An agent with too few claims has no
// place. "Verified" is the count of the week's pull requests that were also paid through Knos under terms with a
// black-box check: the file says what it was counted against, and the table repeats it.

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c]));
const pct = (x) => `${(x * 100).toFixed(1)}%`;
export const TOO_FEW = "too few to rank";

// Every week any agent has a row for, newest first.
export const weeksOf = (weekly) => [...new Set(Object.values(weekly.agents || {}).flatMap((a) => (a.weeks || []).map((w) => w.week)))].sort().reverse();

export function boardRows(weekly, week) {
  const rows = Object.entries(weekly.agents || {}).map(([agent, a]) => ({ agent, row: (a.weeks || []).find((w) => w.week === week) || null }));
  const placed = rows.filter((r) => r.row && r.row.rank != null).sort((x, y) => x.row.rank - y.row.rank);
  return [...placed, ...rows.filter((r) => !(r.row && r.row.rank != null))];
}

// One share: "k of n (share)", its interval in words, and the interval as a bar. `what` names it for a screen reader.
function rateCell(rate, what) {
  if (rate == null) return `<span class="ib-none">not read</span>`;
  if (!rate.n) return `<span class="ib-count">0 of 0</span> <span class="ib-none">nothing to take a share of</span>`;
  const [lo, hi] = rate.ci95, said = `${rate.k} of ${rate.n} ${what}: ${pct(rate.share)}, 95% interval ${pct(lo)} to ${pct(hi)}`;
  return `<span class="ib-count">${esc(rate.k)} of ${esc(rate.n)}</span> <span class="ib-share">${pct(rate.share)}</span>
    <span class="ib-bar" role="img" aria-label="${esc(said)}"><span class="ib-range" style="left:${(lo * 100).toFixed(1)}%;width:${Math.max(1, (hi - lo) * 100).toFixed(1)}%"></span><span class="ib-point" style="left:${(rate.share * 100).toFixed(1)}%"></span></span>
    <span class="ib-ci">${pct(lo)} to ${pct(hi)}</span>`;
}

function rowHtml({ agent, row }, least) {
  if (!row) return `<tr><th scope="row">${esc(agent)}</th><td colspan="7" class="ib-none">no row for this week in the file</td></tr>`;
  const place = row.rank != null ? `<strong class="ib-place">${esc(row.rank)}</strong>` : `<span class="ib-none" title="Fewer than ${esc(least)} claimed pull requests whose CI had finished this week">${TOO_FEW}</span>`;
  return `<tr data-agent="${esc(agent)}"><td>${place}</td><th scope="row">${esc(agent)}</th>
    <td class="ib-n">${row.sampled == null ? `<span class="ib-none">not kept</span>` : esc(row.sampled)}</td>
    <td class="ib-n">${esc(row.claimed_passing)}</td><td class="ib-n">${esc(row.ci_finished)}</td>
    <td>${rateCell(row.failed_a_check, "with finished CI failed a check")}</td>
    <td>${rateCell(row.merged_despite_failed_check, "merged had a failed check")}</td>
    <td class="ib-n ib-verified" data-verified="${esc(row.verified ?? 0)}">${Number(row.verified) > 0 ? `<strong>${esc(row.verified)} verified</strong>` : "0"}</td></tr>`;
}

const STYLE = `<style>
.index-board .ib-bar{position:relative;display:block;height:8px;min-width:96px;margin:4px 0 2px;border-radius:4px;background:var(--soft,#eeece5);border:1px solid var(--line,#e1dfd7)}
.index-board .ib-range{position:absolute;top:0;bottom:0;border-radius:3px;background:var(--muted,#5a606b);opacity:.55}
.index-board .ib-point{position:absolute;top:-3px;bottom:-3px;width:2px;margin-left:-1px;background:var(--fg,#15171c)}
.index-board .ib-count{font-weight:600;white-space:nowrap}
.index-board .ib-ci,.index-board .ib-none{color:var(--muted,#5a606b);font-size:.86em}
.index-board .ib-ci{white-space:nowrap}
.index-board .ib-n{font-variant-numeric:tabular-nums}
.index-board table{border-collapse:collapse;width:100%}
.index-board th,.index-board td{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--line,#e1dfd7)}
.index-board .ib-wrap{overflow-x:auto;max-width:100%}
.index-board .ib-pick{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.index-board .ib-pick select{width:auto;min-width:11em}
</style>`;

export function indexBoardHtml(weekly, week) {
  const weeks = weeksOf(weekly), name = weekly.name || "Agent PR Index", least = weekly.min_claims_to_rank ?? 30;
  const shown = weeks.includes(week) ? week : (weeks.includes(weekly.latest_week) ? weekly.latest_week : weeks[0]);
  if (!shown) return `<div class="index-board"><p class="fine">The file holds no week yet.</p></div>`;
  const rows = boardRows(weekly, shown), with_ = rows.filter((r) => r.row);
  const reads = [...new Set(with_.map((r) => r.row.read || weekly.read))].sort().join(" and ");
  const whole = with_.length > 0 && with_.every((r) => r.row.full_week);
  const verified = with_.reduce((n, r) => n + Number(r.row.verified || 0), 0);
  return `<div class="index-board">${STYLE}
    <h3 id="ib-title">${esc(name)}, week of ${esc(shown)}</h3>
    <p class="ib-pick"><label for="ib-week">Week of</label>
      <select id="ib-week" aria-controls="ib-table">${weeks.map((w) => `<option value="${esc(w)}"${w === shown ? " selected" : ""}>${esc(w)}</option>`).join("")}</select></p>
    <p class="fine" id="ib-read">Read ${esc(reads)}: ${whole ? "every pull request the week's searches returned." : "a capped sample cut by week, not the whole week."}
      Public repositories only. Each share is a count over its total, with its 95% interval (Wilson) drawn from 0 to 100%.</p>
    <div class="ib-wrap table-wrap"><table id="ib-table" aria-labelledby="ib-title">
      <thead><tr><th scope="col">Place</th><th scope="col">Agent</th><th scope="col">Sampled</th><th scope="col">Claimed passing</th><th scope="col">CI finished</th>
        <th scope="col">Failed a check anyway</th><th scope="col">Merged despite a failed check</th><th scope="col">Verified</th></tr></thead>
      <tbody>${rows.map((r) => rowHtml(r, least)).join("")}</tbody></table></div>
    <p class="fine" id="ib-rank">An agent has a place only with at least ${esc(least)} claimed pull requests whose CI had finished that week; the others are "${TOO_FEW}" and are never placed.
      A place orders what was said against what GitHub recorded that week. A failed check is not proof that the claim was false, and a place is not a ranking of the agents' code.</p>
    <p class="fine" id="ib-verified"><strong>Verified: ${esc(verified)} this week.</strong> A pull request is counted as verified only when it was also paid through Knos under terms with a black-box check, an acceptance check the pull request could not edit.
      Counted against: ${esc(weekly.verified_against || "the file does not say")}.</p>
  </div>`;
}

export function renderIndexBoard(el, weekly, week) {
  el.innerHTML = indexBoardHtml(weekly, week);
  const pick = el.querySelector ? el.querySelector("#ib-week") : null;
  if (pick) pick.addEventListener("change", () => { renderIndexBoard(el, weekly, pick.value); const again = el.querySelector("#ib-week"); if (again) again.focus(); });
  return el;
}
