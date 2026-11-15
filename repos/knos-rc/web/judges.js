// "Check every claim yourself" (#judges): the rows of docs/JUDGES.md, as judges.json holds them (scripts/judges.py; copied by
// scripts/build_site.sh): { entry: { manifest, witnessed: [{ label, link }], yourself }, rows: [{ thing, sentence, link,
// label }], not_real: [..] }. The entry first (the manifest, then the witnessed transaction's links); then one row a
// judged thing, one sentence, one link a judge can open; then what is not real yet.
const DOC = "https://github.com/drexthealpha/Knos/blob/main/docs/JUDGES.md";
// On a phone the three columns would leave the sentence a few words a line: each row is drawn as a block instead.
const STYLE = `@media (max-width: 560px) {
  .kj thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  .kj table, .kj tbody, .kj tr, .kj th, .kj td { display: block; width: auto; }
  .kj tr { padding: 10px 0; border-bottom: 1px solid var(--line); }
  .kj tbody th, .kj td { border: 0; padding: 2px 0; }
}`;
export function renderJudges(el, { esc, data } = {}) {
  const rows = Array.isArray(data?.rows) ? data.rows.filter((r) => r && (r.thing || r.sentence)) : [];
  if (!el || !rows.length) return;
  const zeros = Array.isArray(data.not_real) ? data.not_real : [];
  if (!document.getElementById("kj-style")) { const s = document.createElement("style"); s.id = "kj-style"; s.textContent = STYLE; document.head.append(s); }
  const entry = data.entry && typeof data.entry === "object" ? data.entry : null;
  const link = (href, text) => `<a href="${esc(href)}"${/^https?:/.test(href) ? ' target="_blank" rel="noopener"' : ""}>${esc(text)}</a>`;
  const seen = entry ? (Array.isArray(entry.witnessed) ? entry.witnessed : []).filter((w) => w && w.link) : [];
  el.innerHTML = `<h2>Check every claim yourself (for judges and buyers)</h2>
    ${entry ? `<ol class="kj-entry" id="judges-entry" data-keep>
      ${entry.manifest ? `<li>${link(entry.manifest, "Open the release manifest")}: code, build, payments, fees.</li>` : ""}
      ${seen.length ? `<li>Follow the witnessed transaction: ${seen.map((w) => link(w.link, w.label || "Open")).join(", ")}.</li>` : ""}
      ${entry.yourself ? `<li>${link(entry.yourself, "Run it yourself")}.</li>` : ""}
    </ol>` : ""}
    <p class="lede">One link for each row.</p>
    <div class="card" data-keep><div class="k-table kj"><table>
      <thead><tr><th scope="col">Judged</th><th scope="col">What exists</th><th scope="col">Evidence</th></tr></thead>
      <tbody>${rows.map((r) => `<tr><th scope="row">${esc(r.thing || "")}</th><td>${esc(r.sentence || "")}</td>
        <td>${r.link ? `<a href="${esc(r.link)}"${/^https?:/.test(r.link) ? ' target="_blank" rel="noopener"' : ""}>${esc(r.label || "Open")}</a>` : ""}</td></tr>`).join("")}</tbody>
    </table></div></div>
    ${zeros.length ? `<h3 id="judges-zeros">Not real yet</h3><div class="k-table" data-keep><table><tbody>${zeros.map((z) => `<tr><td>${esc(z)}</td></tr>`).join("")}</tbody></table></div>` : ""}
    <p class="fine" data-keep><a id="judges-doc" href="${DOC}">The same page as a document</a></p>`;
}
