// One agent vendor's page: #vendor=<slug>. The file is vendors.json (knos.vendors/1), the build's copy of
// docs/vendors.json, which `python scripts/agent_pr_index.py vendors` writes beside docs/reference/VENDORS.md.
//
//   renderVendor(el, ctx)   draws the vendor the address names (or ctx.slug); ctx: { slug, data, fetch, base }.
//                           Follows the address when it changes. Returns { loaded, show }.
//   vendorHtml(doc, slug)   the page of one vendor, as a string
//   slugIn(hash)            the slug in "#vendor=<slug>", or ""
//
// What it shows: the row with its sample and its 95% interval as a whisker; each week's own counts; the right of
// reply (one click opens the form; replies printed word for word); the disputes, open and closed, with what was found;
// the two steps that earn the supplier badge; and what the index is not. Nothing is sent anywhere: the page reads its
// own file. A statement here is twelve words at most.

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c]));
const pct = (x) => `${(x * 100).toFixed(1)}%`;
const num = (n) => Number(n).toLocaleString("en-US");
const safe = (u) => (/^https:\/\//.test(String(u)) ? String(u) : "#");
export const SCHEMA = "knos.vendors/1";
export const slugOf = (name) => String(name ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
export const slugIn = (hash) => { const m = /^#?vendor=([^&]*)/.exec(String(hash || "")); return m ? slugOf(decodeURIComponent(m[1])) : ""; };

const STYLE = `<style>
.vendor-page .vp-bar{position:relative;display:block;height:12px;max-width:520px;margin:8px 0;border-radius:var(--radius,4px);background:var(--paper-2,#eeece5);border:1px solid var(--line,#e1dfd7)}
.vendor-page .vp-fill{position:absolute;left:0;top:0;bottom:0;background:var(--accent,#5a606b);opacity:.7}
.vendor-page .vp-whisker{position:absolute;top:50%;height:2px;margin-top:-1px;background:var(--ink,#15171c)}
.vendor-page .vp-whisker::before,.vendor-page .vp-whisker::after{content:"";position:absolute;top:-5px;width:2px;height:12px;background:inherit}
.vendor-page .vp-whisker::before{left:0}.vendor-page .vp-whisker::after{right:0}
.vendor-page .vp-acts{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
.vendor-page .vp-reply{margin:8px 0;padding:8px 12px;border-left:3px solid var(--line,#e1dfd7);white-space:pre-wrap;overflow-wrap:anywhere}
.vendor-page table{border-collapse:collapse;width:100%}.vendor-page th,.vendor-page td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line,#e1dfd7)}
.vendor-page .k-num{font-variant-numeric:tabular-nums}
.vendor-page h3{margin-top:24px}
</style>`;

function rowHtml(row) {
  if (row.merged == null) return `<p class="fine" id="vp-row">Not read.</p>`;
  if (!row.merged) return `<p class="fine" id="vp-row">No merged pull request read.</p>`;
  const [lo, hi] = row.ci95, place = row.rank ? `Place ${esc(row.rank)}${row.overlaps_above ? ", overlaps the one above" : ""}` : esc(row.status);
  return `<p id="vp-row"><strong class="k-num">${esc(num(row.failed_at_merge))} of ${esc(num(row.merged))}</strong> merged had a failed check:
      <strong class="k-num">${pct(row.share)}</strong>, 95% interval <span class="k-num">${pct(lo)} to ${pct(hi)}</span>.</p>
    <span class="vp-bar" role="img" aria-label="${esc(`${pct(row.share)}, 95% interval ${pct(lo)} to ${pct(hi)}`)}"><span class="vp-fill" style="width:${(row.share * 100).toFixed(1)}%"></span><span class="vp-whisker" style="left:${(lo * 100).toFixed(1)}%;width:${Math.max(1, (hi - lo) * 100).toFixed(1)}%"></span></span>
    <p class="fine" id="vp-sample">${place}. ${esc(num(row.claimed_passing))} claimed passing over ${esc(row.weeks)} weeks.</p>`;
}

export function vendorHtml(doc, slug) {
  const v = doc && doc.schema === SCHEMA ? (doc.vendors || []).find((x) => x.slug === slug) : null;
  if (!v) return `<div class="vendor-page"><h2>One vendor's row and reply</h2><p class="status" id="vp-none">No vendor by that name in this week's index.</p></div>`;
  const open = v.disputes?.open || [], closed = v.disputes?.closed || [];
  const weeks = (v.weekly || []).map((w) => `<tr><td>${esc(w.week)}</td><td class="k-num">${esc(num(w.claimed_passing))}</td><td class="k-num">${w.merged == null ? "not finished" : `${esc(num(w.failed_at_merge))} of ${esc(num(w.merged))}`}</td></tr>`).join("");
  return `<div class="vendor-page" data-vendor="${esc(v.slug)}">${STYLE}
    <h2 id="vp-title">${esc(v.agent)}: row and reply</h2>
    <p class="fine">${esc(doc.name || "Agent PR Index")}, week of ${esc(doc.week)}.</p>
    ${rowHtml(v.row)}
    <div class="vp-acts">
      <a class="k-btn" id="vp-reply" href="${esc(safe(v.reply))}" target="_blank" rel="noopener">Reply to this row</a>
      <a class="k-btn quiet" id="vp-dispute" href="${esc(safe(v.dispute))}" target="_blank" rel="noopener">Dispute this row</a>
      <a class="k-btn quiet" id="vp-record" href="#record=${esc(v.slug)}">Open the supplier record</a>
    </div>
    <h3>Replies</h3>
    <div id="vp-replies">${(v.replies || []).map((r) => `<blockquote class="vp-reply">${esc(r.text)}<br><span class="fine">${esc(r.posted || "")} <a href="${esc(safe(r.issue))}" target="_blank" rel="noopener">issue</a></span></blockquote>`).join("") || `<p class="fine">No reply yet.</p>`}</div>
    <h3>Disputes</h3>
    <p class="fine" id="vp-disputes"><span class="k-num">${esc(open.length)}</span> open, <span class="k-num">${esc(closed.length)}</span> closed.</p>
    ${open.length || closed.length ? `<ul class="fine">${open.map((d) => `<li>Open since ${esc(d.opened)}: <a href="${esc(safe(d.issue))}" target="_blank" rel="noopener">issue</a></li>`).join("")}${closed.map((d) => `<li>${esc(d.status)} ${esc(d.resolved)}: ${esc(d.outcome)} <a href="${esc(safe(d.issue))}" target="_blank" rel="noopener">issue</a></li>`).join("")}</ul>` : ""}
    <h3>Earn the supplier badge</h3>
    <ol id="vp-badge">${(doc.badge || []).map((s) => `<li><strong>${esc(s.step)}.</strong> <span class="fine">Gives ${esc(s.gives)}.</span></li>`).join("")}</ol>
    <h3>Each week</h3>
    <div class="k-table table-wrap"><table id="vp-weeks"><thead><tr><th scope="col">Week</th><th scope="col">Claimed passing</th><th scope="col">Failed check, of merged</th></tr></thead><tbody>${weeks}</tbody></table></div>
    <details class="k-more" id="vp-not"><summary>What this index is not</summary><ul class="fine">${(doc.not || []).map((n) => `<li>${esc(n)}</li>`).join("")}</ul></details>
    <p class="fine" id="vp-rule">${esc(doc.rule || "")}</p>
  </div>`;
}

export function renderVendor(el, ctx = {}) {
  const get = ctx.fetch || (typeof fetch === "function" ? fetch : null);
  const loaded = ctx.data ? Promise.resolve(ctx.data)
    : get ? get(`${ctx.base || ""}vendors.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null) : Promise.resolve(null);
  const here = () => ctx.slug || (typeof location === "object" ? slugIn(location.hash) : "");
  el.innerHTML = `<div class="vendor-page"><h2>One vendor's row and reply</h2><p class="status" aria-busy="true">Reading vendors.json.</p></div>`;   // pending at once
  const show = (doc) => { el.innerHTML = vendorHtml(doc, here()); return el; };
  const done = loaded.then(show);
  if (!ctx.slug && typeof addEventListener === "function") addEventListener("hashchange", () => { if (slugIn(location.hash)) loaded.then(show); });
  return { loaded: done, show };
}
