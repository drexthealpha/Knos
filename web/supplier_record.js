// A supplier's public record, as a page: #record=<slug>. The file is docs/records/<slug>.json (knos.supplier-record/1,
// docs/RECORD.md), written by `knos record build`; the build puts it at records/<slug>.json beside the site.
//
//   renderSupplierRecord(el, ctx)   draws the record the address names (or ctx.slug) and follows the address when it
//                                   changes. ctx: { slug, fetch, base, doc }. Returns { loaded, show }.
//   recordHtml(doc)                 the page of one record, as a string
//   evidenceRows(doc)               every piece of evidence behind every count, one row each
//
// What it shows: the counts of work settled through Knos as tiles that count up once (motion.js countTo; simply there
// under reduced motion), the evidence behind them, the public row with its 95% interval as a whisker, the badge, the
// one line that installs the free check, "Dispute this record", and that the record cannot be bought. Nothing is
// sent anywhere: the page reads its own files. A statement here is twelve words at most.
import { countTo } from "./motion.js";
import { recordBadge, recordBadgeSvg, recordBadgeMarkdown } from "./badge.js";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c]));
const pct = (x) => `${(x * 100).toFixed(1)}%`;
export const SCHEMA = "knos.supplier-record/1";
export const TILES = ["accepted", "rejected", "insufficient_evidence", "disputed", "overturned", "reverted"];
export const WORDS = { accepted: "accepted", rejected: "rejected", insufficient_evidence: "insufficient evidence", disputed: "disputed", appealed: "appealed",
  overturned: "overturned on appeal", reverted: "reverted" };
export const INSTALL = "uses: drexthealpha/Knos/.github/workflows/supplier.yml@v0.3.19";
export const slugOf = (name) => String(name ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
export const slugIn = (hash) => { const m = /^#?record=([^&]*)/.exec(String(hash || "")); return m ? slugOf(decodeURIComponent(m[1])) : ""; };

const STYLE = `
.supplier-record .sr-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(104px,1fr));gap:10px;margin:12px 0}
.supplier-record[data-orders="0"] .sr-tile{padding:8px 12px}.supplier-record[data-orders="0"] .sr-tile strong{font-size:1.25em}
.supplier-record h2{margin-top:4px}.supplier-record h3{margin-top:28px}
.supplier-record .sr-tile{margin:0;padding:12px 14px;display:grid;gap:2px}
.supplier-record .sr-tile strong{font-size:1.9em;line-height:1.1}
.supplier-record .sr-tile span{color:var(--ink-2,#5a606b);font-size:.86em}
.supplier-record .sr-tile[data-n="0"] strong{color:var(--ink-2,#5a606b)}
.supplier-record .sr-bar{position:relative;display:block;height:12px;max-width:520px;margin:8px 0;border-radius:var(--radius,4px);background:var(--paper,#fff);border:1px solid var(--line,#e1dfd7)}
.supplier-record .sr-fill{position:absolute;left:0;top:0;bottom:0;background:var(--accent,#5a606b);opacity:.7}
.supplier-record .sr-whisker{position:absolute;top:50%;height:2px;margin-top:-1px;background:var(--ink,#15171c)}
.supplier-record .sr-whisker::before,.supplier-record .sr-whisker::after{content:"";position:absolute;top:-5px;width:2px;height:12px;background:inherit}
.supplier-record .sr-whisker::before{left:0}.supplier-record .sr-whisker::after{right:0}
.supplier-record .sr-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.supplier-record .sr-svg{display:block;max-width:100%;overflow-x:auto;margin:6px 0}
.supplier-record .sr-svg svg{display:block;max-width:none}
.supplier-record pre{overflow-x:auto;max-width:100%}
.supplier-record td,.supplier-record th{text-align:left;vertical-align:top;padding:6px 10px;border-bottom:1px solid var(--line,#e1dfd7)}
.supplier-record td code{overflow-wrap:anywhere}`;

// Every piece of evidence behind every count: {count, what, where, url}.
export function evidenceRows(doc) {
  const out = [];
  for (const [count, c] of Object.entries(doc.orders.counts)) for (const e of c.evidence) {
    const pull = e.pull_request != null;
    out.push({ count, from: c.from, what: pull ? `${e.repository}#${e.pull_request}` : e.deliverable || e.event, where: pull ? (e.appeal ? `appeal ${e.appeal}` : "pull request") : `line ${e.line}: ${e.evidence || "no evidence named"}`,
      url: pull && /^https:\/\/github\.com\//.test(e.url || "") ? e.url : "" });
  }
  return out;
}

function publicHtml(p) {
  if (!p) return `<p class="fine" data-sr="no-public">Holds no row in the Agent PR Index.</p>`;
  const rate = p.sample && p.ci95 ? `<p class="sr-row"><strong class="k-num" data-sr="share">${pct(p.share)}</strong> <span class="k-num" data-sr="sample">${esc(p.failed_at_merge)} of ${esc(p.sample)} merged</span></p>
    <span class="sr-bar" role="img" aria-label="${esc(`${pct(p.share)}, 95% interval ${pct(p.ci95[0])} to ${pct(p.ci95[1])}`)}"><span class="sr-fill" style="width:${(p.share * 100).toFixed(1)}%"></span><span class="sr-whisker" style="left:${(p.ci95[0] * 100).toFixed(1)}%;width:${Math.max(1, (p.ci95[1] - p.ci95[0]) * 100).toFixed(1)}%"></span></span>
    <p class="fine"><span class="k-num" data-sr="ci">95% interval ${pct(p.ci95[0])} to ${pct(p.ci95[1])}.</span> Failed a check at merge.</p>`
    : `<p class="fine">Holds no merged claim yet.</p>`;
  return `${rate}
    <p class="fine" data-sr="period">Week of ${esc(p.week)}; ${esc(p.weeks)} weeks read. ${p.rank == null ? "Too few to rank." : ""}</p>
    <p class="fine">Counts merged pull requests that claimed passing tests. <a href="${esc(p.method)}" target="_blank" rel="noopener">Read the method.</a></p>`;
}

export function recordHtml(doc) {
  const o = doc.orders, rows = evidenceRows(doc), span = o.period.from ? `${o.period.from} to ${o.period.to}` : `as of ${doc.as_of}`;
  // what there is to see leads: a supplier with no Knos order yet opens on its public row, and the six counts follow
  const ORDERS = `    <h3>Work settled through Knos</h3>
    <p class="fine" data-sr="orders-sample"><span class="k-num">Sample ${esc(o.sample)}, ${esc(span)}.</span> ${o.sample ? "" : "Holds no Knos order yet."}</p>
    <div class="sr-tiles k-stage" data-not-prose>${TILES.map((k) => `<div class="sr-tile k-card" data-count="${k}" data-n="${esc(o.counts[k].n)}"><strong class="k-num">0</strong><span>${WORDS[k]}</span></div>`).join("")}</div>
    ${rows.length ? `<div class="k-table"><table data-sr="evidence"><thead><tr><th scope="col">Count</th><th scope="col">Work</th><th scope="col">Evidence</th></tr></thead>
      <tbody>${rows.map((r) => `<tr data-count="${esc(r.count)}"><td>${esc(WORDS[r.count])}</td><td>${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.what)}</a>` : `<code>${esc(r.what)}</code>`}</td><td><code>${esc(r.where)}</code></td></tr>`).join("")}</tbody></table></div>`
      : `<p class="fine" data-sr="evidence">Lists evidence here once an order settles.</p>`}`, PUBLIC = `
    <h3>From public pull requests, not Knos orders</h3>
    ${publicHtml(doc.public)}`;
  return `<section class="supplier-record k-card" data-supplier="${esc(doc.supplier)}" data-orders="${esc(o.sample)}">
    <p class="k-kicker">Supplier record</p>
    <h2>Public record of ${esc(doc.name)}</h2>
    <p class="fine" data-sr="rule">This record cannot be bought.</p>
    ${o.sample ? ORDERS + PUBLIC : PUBLIC + ORDERS}
    <p class="sr-row"><a class="k-btn" data-sr="dispute" href="${esc(doc.links.dispute)}" target="_blank" rel="noopener">Dispute this record</a>
      <a class="k-btn quiet" data-sr="file" href="records/${esc(doc.supplier)}.json">Open the file</a></p>
    <h3>Show it where you work</h3>
    <span class="sr-svg" data-sr="badge">${recordBadgeSvg(doc).trim()}</span>
    <p class="sr-row"><button type="button" class="k-btn quiet" data-sr="copy">Copy badge Markdown</button></p>
    <p class="fine">Add the free check with one line.</p>
    <pre><code data-sr="install">${esc(INSTALL)}</code></pre>
    <p class="fine" data-sr="limits">Counts with samples, never a score. <a href="https://github.com/drexthealpha/Knos/blob/main/docs/RECORD.md" target="_blank" rel="noopener">Read the limits.</a></p>
  </section>`;
}

const pickHtml = (list, why) => `<section class="supplier-record k-card">
    <p class="k-kicker">Supplier record</p>
    <h2>Pick a supplier's record</h2>
    <p class="fine" data-sr="rule">No record here can be bought.</p>
    ${why ? `<p data-sr="said" role="status">${esc(why)}</p>` : ""}
    <div class="sr-row" data-sr="pick">${list.map((s) => `<a class="k-btn quiet" href="#record=${esc(s)}">${esc(s)}</a>`).join("") || "Holds no record yet."}</div>
  </section>`;

export function renderSupplierRecord(el, ctx = {}) {
  const doc = el.ownerDocument, fetchFn = ctx.fetch || ((...a) => globalThis.fetch(...a)), base = ctx.base || "", win = doc.defaultView;
  if (!doc.getElementById("supplier-record-style")) { const s = doc.createElement("style"); s.id = "supplier-record-style"; s.textContent = STYLE; doc.head.appendChild(s); }
  const json = (path) => fetchFn(`${base}${path}`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  const pick = async (why) => {
    const feed = await json("agent_index.json");
    el.innerHTML = pickHtml(((feed && feed.weeks && feed.weeks[0] && feed.weeks[0].rows) || []).map((r) => slugOf(r.agent)), why);
  };
  const draw = (record) => {
    el.innerHTML = recordHtml(record);
    for (const tile of el.querySelectorAll(".sr-tile")) countTo(tile.querySelector("strong"), Number(tile.dataset.n), { from: 0 });      // counts up once; exact at once under reduced motion
    const copy = el.querySelector("[data-sr=copy]");
    copy.addEventListener("click", () => {
      const line = recordBadgeMarkdown(record, `https://raw.githubusercontent.com/drexthealpha/Knos/main/docs/records/${record.supplier}.svg`);
      copy.textContent = "Copying";                                 // said at once; the clipboard answers later
      Promise.resolve().then(() => win.navigator.clipboard.writeText(line)).then(() => { copy.textContent = "Copied"; }, () => {
        const box = doc.createElement("textarea");                  // no clipboard here: the line itself, to select and copy
        box.readOnly = true; box.rows = 3; box.value = line; box.setAttribute("aria-label", "Badge Markdown");
        copy.replaceWith(box); box.select();
      });
    });
  };
  const show = async (slug) => {
    if (!slug) return pick("");
    el.setAttribute("aria-busy", "true");
    const record = ctx.doc && ctx.doc.supplier === slug ? ctx.doc : await json(`records/${slug}.json`);
    el.removeAttribute("aria-busy");
    if (!record || record.schema !== SCHEMA || record.supplier !== slug) return pick(`Holds no record named ${slug}.`);
    return draw(record);
  };
  const now = () => ctx.slug || slugIn(win ? win.location.hash : "");
  if (win && !ctx.slug) win.addEventListener("hashchange", () => { if (/^#record(=|$)/.test(win.location.hash)) show(now()); });
  const loaded = show(now());
  return { loaded, show, badge: recordBadge };
}
