// What memory says of an exception: how the same one under the same terms ended before.
//
//   renderRecall(el, rows)   draws the rows into `el` and returns { rows: how many were drawn }
//   recallHtml(rows)         the same, as a string
//   took(seconds)            "40 s", "12 min", "5 h", "3 days"
//
// `rows` is what `knos recall exception --json` prints (one object) or `knos recall queue --json` prints (a list),
// schema knos.recall/1 (src/knos/recall.py):
//
//   { kind: "knos.recall/1", terms: "<64 hex>", reason: "disputed", supplier: "acme" | "",
//     seen: 3, endings: { accepted_on_appeal: 2, corrected_and_passed: 0, refused: 1 }, most_often: "accepted_on_appeal",
//     seconds: { median, fastest, slowest, timed } | null, evidence: ["evl_..", ..], open: 1, said: "...", words: "...",
//     cases: [{ id, reason, ending, at, period, seconds | null, evidence: [..], supplier }],   // the newest five
//     terms_text_kept: true, memory: true,
//     id, opened_at, open_evidence }                                                          // only in a queue row
//
// Nothing is fetched and nothing is sent: the page hands the rows in. A statement here is twelve words at most.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c]));
export const SCHEMA = "knos.recall/1";
export const ENDINGS = ["accepted_on_appeal", "corrected_and_passed", "refused"];
export const WORDS = { accepted_on_appeal: "accepted on appeal", corrected_and_passed: "corrected and passed", refused: "refused" };

export function took(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) return "";
  const s = Number(seconds);
  for (const [size, unit] of [[86400, "day"], [3600, "h"], [60, "min"]]) {
    if (s >= size) { const n = Math.floor(s / size); return `${n} ${unit}${unit === "day" && n !== 1 ? "s" : ""}`; }
  }
  return `${Math.floor(s)} s`;
}

const STYLE = `
.k-recall{display:grid;gap:10px;min-width:0}
.k-recall .rc-row{padding:12px 14px;display:grid;gap:6px;min-width:0}
.k-recall .rc-head{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}
.k-recall .rc-head code,.k-recall .rc-ev code{overflow-wrap:anywhere}
.k-recall .rc-bar{display:flex;height:8px;border-radius:var(--radius,4px);overflow:hidden;background:var(--paper-2,#f4f2ec);border:1px solid var(--line,#e1dfd7)}
.k-recall .rc-bar i{display:block;height:100%;transition:flex-grow var(--dur-2,240ms) var(--ease,ease)}
.k-recall .rc-bar i[data-e="accepted_on_appeal"]{background:var(--ok,#1c7c4a)}
.k-recall .rc-bar i[data-e="corrected_and_passed"]{background:var(--accent,#5a606b)}
.k-recall .rc-bar i[data-e="refused"]{background:var(--bad,#b3261e)}
.k-recall .rc-ends{display:flex;flex-wrap:wrap;gap:4px 14px;margin:0;padding:0;list-style:none;color:var(--ink-2,#5a606b);font-size:.9em}
.k-recall .rc-ends strong{color:var(--ink,#15171c)}
.k-recall .rc-ev{color:var(--ink-2,#5a606b);font-size:.86em;overflow-wrap:anywhere}
.k-recall .rc-none{color:var(--ink-2,#5a606b)}
@media (prefers-reduced-motion: reduce){.k-recall .rc-bar i{transition:none}}
`;

function rowHtml(r) {
  const seen = Number(r.seen) || 0;
  const head = `<div class="rc-head"><span class="k-kicker">${esc(r.reason)}</span>${r.supplier ? `<span>${esc(r.supplier)}</span>` : ""}${r.id ? `<code>${esc(r.id)}</code>` : ""}</div>`;
  if (!seen) return `<div class="k-card rc-row" data-seen="0">${head}<p class="rc-none">Not seen before under these terms.</p></div>`;
  const ends = r.endings || {};
  const bar = ENDINGS.map((e) => `<i data-e="${e}" style="flex-grow:${Number(ends[e]) || 0}"></i>`).join("");
  const list = ENDINGS.filter((e) => Number(ends[e]) > 0).map((e) => `<li><strong class="k-num">${Number(ends[e])}</strong> ${WORDS[e]}</li>`).join("");
  const time = r.seconds ? `<li>median <strong>${esc(took(r.seconds.median))}</strong></li>` : "";
  const ev = (r.evidence || []).slice(0, 4).map((x) => `<code>${esc(x)}</code>`).join(" ");
  return `<div class="k-card rc-row" data-seen="${seen}" data-most="${esc(r.most_often || "")}">${head}
<p>Seen <strong class="k-num">${seen}</strong> time${seen === 1 ? "" : "s"} under these terms.</p>
<div class="rc-bar" role="img" aria-label="${esc(r.words || "")}">${bar}</div>
<ul class="rc-ends">${list}${time}</ul>${ev ? `<p class="rc-ev">Evidence: ${ev}</p>` : ""}</div>`;
}

export function recallHtml(rows) {
  const list = (Array.isArray(rows) ? rows : rows ? [rows] : []).filter((r) => r && r.kind === SCHEMA);
  if (!list.length) return `<p class="rc-none">No memory of this exception.</p>`;
  return list.map(rowHtml).join("");
}

export function renderRecall(el, rows) {
  const doc = el.ownerDocument;
  if (doc && !doc.getElementById("k-recall-style")) {
    const style = doc.createElement("style");
    style.id = "k-recall-style";
    style.textContent = STYLE;
    doc.head.appendChild(style);
  }
  el.classList.add("k-recall");
  el.innerHTML = recallHtml(rows);
  return { rows: el.querySelectorAll(".rc-row").length };
}
