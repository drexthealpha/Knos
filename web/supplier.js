// The supplier's page: what an order will check, before any work is sent.
//
//   renderSupplier(el[, ctx])     paste an order's terms (or a link to them), or pick a published sample: the checks as a
//                                 short list, the paths as a tree (allowed / protected / allowed, not counted), one path
//                                 tried against them, and every refusal's two sentences, searchable
//   readTerms(text)               an order's terms from their JSON (the `knos-terms:` line's, or a file of terms/)
//   termsLink(text)               what a pasted link asks for: { url, issue } or null
//   rules(terms)                  { checks, protected, allowed, notCounted }: what src/knos/preflight.py says, for the
//                                 default (Python) judge; an order's own `.knos/proof.toml` can replace the judge's list
//   classify(terms, path, status) { class, code }: allowed, allowed_not_counted or refused, as `knos preflight` decides it
//   tree(rows)                    the paths as nested folders
//   search(rows, words)           the refusal rows that hold every word
//
// The refusal table is refusals.json, written from knos.ghwords.REFUSALS (scripts/supplier_docs.py), so the page, the
// command line and the comments say the same two sentences. Nothing is sent anywhere: a pasted link is read with GET and
// nothing else is asked of anyone but this site, and GitHub's API when the link is a GitHub issue.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const CLASSES = ["allowed", "protected", "allowed_not_counted"];
export const LABELS = { allowed: "allowed", protected: "protected", allowed_not_counted: "allowed, not counted" };
export const JUDGE_PROTECTS = ["tests/**", "test/**", "conftest.py", "**/conftest.py", "pytest.ini", "tox.ini"];     // knos.judge.protected_patterns, python
const CONFIG = new Set(["conftest.py", "pytest.ini", "tox.ini", ".npmrc", "Rakefile", ".rspec", "test_helper.rb", "spec_helper.rb"]);
const TEST_DIRS = ["tests", "test"];     // knos.judge.TEST_DIRS, python
// terms/bugfix/1.json and terms/feature-blackbox/1.json, their `terms`: shown when the site's terms/ cannot be read
export const SAMPLES = [
  { name: "bugfix", terms: { accept: "", checks: [{ app: 15368, name: "lint" }, { app: 15368, name: "unit" }], deny: [".github/**", ".knos/**"], mode: "merge", paths: ["src/**", "tests/**"], reserve: 7, v: 1 } },
  { name: "feature-blackbox", terms: { accept: "0".repeat(64), checks: [{ app: 15368, name: "unit" }], deny: [".github/**", ".knos/**"], mode: "tests", paths: [], reserve: 7, v: 1 } },
];

/** A terms glob as knos.terms.matches reads it. */
export function matches(path, glob) {
  const pat = glob.endsWith("/") ? `${glob}**` : glob;
  let out = "", i = 0;
  while (i < pat.length) {
    if (pat.startsWith("**/", i) && (i === 0 || pat[i - 1] === "/")) { out += "(?:.*/)?"; i += 3; }
    else if (pat.startsWith("**", i)) { out += ".*"; i += 2; }
    else if (pat[i] === "*") { out += "[^/]*"; i += 1; }
    else if (pat[i] === "?") { out += "[^/]"; i += 1; }
    else { out += pat[i].replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); i += 1; }
  }
  return new RegExp(`^${out}$`, "s").test(path);
}

/** An order's terms from text, or an Error whose message is one short sentence. */
export function readTerms(text) {
  let got;
  try { got = JSON.parse(String(text).replace(/^\s*knos-terms:\s*/, "")); } catch { throw new Error("That is not JSON."); }
  if (got && typeof got === "object" && got.terms && typeof got.terms === "object") got = got.terms;
  const list = (v) => Array.isArray(v) && v.every((x) => typeof x === "string");
  if (!got || typeof got !== "object" || !["merge", "tests"].includes(got.mode) || !list(got.deny) || !list(got.paths) || !Array.isArray(got.checks)
    || !got.checks.every((c) => c && typeof c.name === "string")) throw new Error("Those are not an order's terms.");
  return { mode: got.mode, checks: got.checks.map((c) => c.name), deny: [...got.deny].sort(), paths: [...got.paths].sort(), image: typeof got.image === "string" ? got.image : "" };
}

/** A pasted link: a file of terms ({ url }), or a GitHub issue ({ url: its comments at GitHub's API, issue }). null: not a link. */
export function termsLink(text) {
  const t = String(text).trim();
  const issue = /^https:\/\/github\.com\/([A-Za-z0-9-]+\/[A-Za-z0-9._-]+)\/issues\/([1-9][0-9]*)\/?(?:[?#].*)?$/.exec(t);
  if (issue) return { url: `https://api.github.com/repos/${issue[1]}/issues/${issue[2]}/comments?per_page=100`, issue: `${issue[1]}#${issue[2]}` };
  if (/^https:\/\/\S+$/.test(t) || /^(?:\S*\/)?terms\/[a-z0-9-]+\/[0-9]+\.json$/.test(t)) return { url: t, issue: "" };
  return null;
}

/** The terms in a GitHub issue's comments: the newest `knos-terms:` line. */
export function termsInComments(comments) {
  const found = (Array.isArray(comments) ? comments : []).flatMap((c) => [...String(c?.body ?? "").matchAll(/^knos-terms: (\{.*\})\s*$/gm)].map((m) => m[1]));
  if (!found.length) throw new Error("That issue has no funded terms.");
  return readTerms(found[found.length - 1]);
}

const judgeProtects = (path, pats) => pats.some((p) => (p.endsWith("/**") && `${path}/`.startsWith(p.slice(0, -2))) || matches(path, p) || (p.startsWith("**/") && matches(path, p.slice(3))));

/** One changed path under these terms: { class: allowed | allowed_not_counted | refused, code }. `status`: what the
 *  change does to the file: "A" adds it, "D" deletes it, anything else edits it (true is taken as "A"). The judge's
 *  rule is knos.judge.classify_path for the default (Python) judge, and the codes are those of judge.REFUSALS. */
export function classify(terms, path, status = "M") {
  const isNew = status === true || status === "A";
  if (terms.deny.some((g) => matches(path, g))) return { class: "refused", code: "terms.denied-path" };
  if (terms.paths.length && !terms.paths.some((g) => matches(path, g))) return { class: "refused", code: "terms.out-of-scope" };
  if (terms.mode !== "tests" || !judgeProtects(path, [".knos/**", ".github/**", ...JUDGE_PROTECTS])) return { class: "allowed", code: "" };
  if (path.startsWith(".knos/")) return { class: "refused", code: "judge.terms" };
  if (path.startsWith(".github/")) return { class: "refused", code: "judge.workflow" };
  const inTests = TEST_DIRS.some((d) => path.startsWith(`${d}/`));
  // test configuration outside the test directories, and anything new: the run takes the base's copy, so it decides nothing
  if (isNew || (CONFIG.has(path.split("/").pop()) && !inTests)) return { class: "allowed_not_counted", code: "" };
  return { class: "refused", code: status === "D" ? "judge.protected-test-deleted" : "judge.protected-test-edited" };
}

/** What will be checked: the named checks, and every path rule with its class. */
export function rules(terms) {
  const tests = terms.mode === "tests";
  const rows = [...terms.deny.map((p) => ({ path: p, class: "protected" })),
    ...(tests ? JUDGE_PROTECTS.filter((p) => !terms.deny.includes(p)).map((p) => ({ path: p, class: "protected" })) : []),
    ...(tests ? [{ path: "tests/<a test you add>", class: "allowed_not_counted" }] : []),
    ...(terms.paths.length ? terms.paths : ["<everything else>"]).map((p) => ({ path: p, class: "allowed" }))];
  return { checks: terms.checks, mode: terms.mode, rows };
}

/** Path rules as nested folders: [{ name, class?, children }], folders first as written, a rule's class on its last part. */
export function tree(rows) {
  const root = { name: "", children: [] };
  for (const row of rows) {
    const parts = row.path.split("/").filter(Boolean);
    let at = root;
    parts.forEach((part, i) => {
      let next = at.children.find((c) => c.name === part);
      if (!next) { next = { name: part, children: [] }; at.children.push(next); }
      if (i === parts.length - 1) next.class = row.class;
      at = next;
    });
  }
  return root.children;
}

export const PROGRAMS = ["pay", "pay1", "oidc", "meter", "passkey"];      // a program's own error numbers: shown when searched for

/** The refusal rows that hold every word typed, in the code or either sentence. With nothing typed: the rows a supplier
 *  meets (the judge's, the terms', the payee rule's, a comment's, an appeal's); a program's error numbers come when asked for. */
export function search(rows, words) {
  const want = String(words).toLowerCase().split(/\s+/).filter(Boolean);
  if (!want.length) return rows.filter((r) => !PROGRAMS.includes(r.code.split(".")[0]) && r.code !== "unknown");
  return rows.filter((r) => { const hay = `${r.code} ${r.happened} ${r.do}`.toLowerCase(); return want.every((w) => hay.includes(w)); });
}

const treeHtml = (nodes) => `<ul>${nodes.map((n) => `<li${n.class ? ` data-class="${n.class}"` : ""}><code>${esc(n.name)}${n.children.length ? "/" : ""}</code>${
  n.class ? ` <span class="sp-tag">${esc(LABELS[n.class])}</span>` : ""}${n.children.length ? treeHtml(n.children) : ""}</li>`).join("")}</ul>`;

/** The answer for one set of terms, as the page shows it. */
export function rulesHtml(terms) {
  const r = rules(terms);
  const checks = r.checks.length ? r.checks.map((c) => `<li><code>${esc(c)}</code> must pass.</li>`).join("") : "<li>No check is named.</li>";
  const paid = r.mode === "tests" ? "<li>The buyer's acceptance checks must pass.</li><li>A neutral judge runs them again.</li>" : "<li>A maintainer must merge it.</li>";
  return `<h3>What will be checked</h3><ul class="sp-checks">${checks}${paid}</ul>
    <h3>Paths</h3><div class="sp-tree" data-sp="tree">${treeHtml(tree(r.rows))}</div>
    <p class="sp-legend">${CLASSES.map((c) => `<span data-class="${c}"><span class="sp-tag">${esc(LABELS[c])}</span></span>`).join(" ")}</p>`;
}

const STYLE = `.supplier .sp-refusals{max-height:420px;overflow-y:auto;border:1px solid var(--line);border-radius:var(--radius);padding:0 12px}.supplier .sp-refusals thead th{position:sticky;top:0;background:var(--paper)}
.supplier textarea{min-height:96px;font-size:13px;width:100%}.supplier .sp-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.supplier input[type=text],.supplier input[type=search]{flex:1 1 180px;min-width:0;max-width:100%}
.supplier .sp-tree ul{list-style:none;margin:0;padding-left:18px;border-left:1px solid var(--line)}.supplier .sp-tree>ul{padding-left:0;border-left:0}
.supplier .sp-tree li{padding:3px 0;overflow-wrap:anywhere}.supplier .sp-tag{font-size:12px;padding:1px 8px;border-radius:var(--radius);border:1px solid var(--line);white-space:nowrap}
.supplier [data-class=protected]>.sp-tag,.supplier [data-class=refused]{color:var(--bad);border-color:var(--bad)}
.supplier [data-class=allowed]>.sp-tag,.supplier p[data-class=allowed]{color:var(--ok);border-color:var(--ok)}
.supplier [data-class=allowed_not_counted]>.sp-tag,.supplier p[data-class=allowed_not_counted]{color:var(--ink-2);border-style:dashed}
.supplier .sp-out{transition:opacity var(--dur-2) var(--ease)}.supplier .sp-out[data-state=pending]{opacity:.5}
.supplier table{border-collapse:collapse;width:100%}.supplier td,.supplier th{padding:6px 12px 6px 0;text-align:left;vertical-align:top;overflow-wrap:anywhere}
.supplier td code{white-space:nowrap}@media (prefers-reduced-motion:reduce){.supplier .sp-out{transition:none}}
@media (max-width:640px){.supplier thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.supplier tr{display:block;padding:8px 0;border-bottom:1px solid var(--line)}.supplier td{display:block;padding:2px 0}.supplier td code{white-space:normal;overflow-wrap:anywhere}}`;
// Under 640 px a refusal is one block (its code, then its two sentences): three columns there squeeze each sentence to a
// word a line (tests/web/overflow.mjs holds every table row of the site to ROW_MAX px).

/** Fill `el` with the supplier's page. ctx: { fetch, base } (both optional; base is where terms/ and refusals.json are). */
export function renderSupplier(el, ctx = {}) {
  const doc = el.ownerDocument, fetchFn = ctx.fetch || ((...a) => globalThis.fetch(...a)), base = ctx.base || "";
  if (!doc.getElementById("supplier-style")) { const s = doc.createElement("style"); s.id = "supplier-style"; s.textContent = STYLE; doc.head.appendChild(s); }
  el.innerHTML = `<section class="supplier k-card">
    <p class="k-kicker">For suppliers</p>
    <h2>See what will be checked</h2>
    <label for="sp-in">Paste an order's terms, or a link</label>
    <textarea id="sp-in" rows="4" spellcheck="false" autocomplete="off" placeholder='{"accept":"","checks":[...]}'></textarea>
    <p class="sp-row"><button type="button" class="k-btn" data-sp="run">Show checks</button><span data-sp="samples" class="sp-row"></span></p>
    <p class="fine">Stays in this page. A link is read, nothing is sent.</p>
    <p data-sp="said" role="status" aria-live="polite"></p>
    <div class="sp-out" data-sp="out"></div>
    <div data-sp="try" hidden>
      <h3>Try a path</h3>
      <p class="sp-row"><input type="text" id="sp-path" aria-label="A path in your change" placeholder="tests/test_new.py" spellcheck="false" autocomplete="off">
        <label><input type="checkbox" data-sp="new"> I add this file</label></p>
      <p data-sp="verdict" role="status" aria-live="polite"></p>
    </div>
    <h3>Every refusal, in plain words</h3>
    <p class="sp-row"><input type="search" id="sp-q" aria-label="Search refusals" placeholder="Search: protected, pay.83, token" autocomplete="off"></p>
    <p class="fine" data-sp="count"></p>
    <div class="k-table sp-refusals" tabindex="0" role="region" aria-label="Every refusal"><table><thead><tr><th scope="col">Code</th><th scope="col">What happened</th><th scope="col">What to do</th></tr></thead><tbody data-sp="rows"></tbody></table></div>
    <p class="fine"><a href="https://github.com/drexthealpha/Knos/blob/main/docs/SUPPLIER.md" target="_blank" rel="noopener">Read the supplier's guide.</a> Run <code>knos preflight</code> in your checkout.</p>
    <p class="fine" data-sp="kit"><a href="#record">See a public record.</a> <a href="https://github.com/drexthealpha/Knos/blob/main/docs/RECORD.md" target="_blank" rel="noopener">Get the badge, the install line and the invoice receipt.</a></p>
  </section>`;
  const $ = (name) => el.querySelector(`[data-sp="${name}"]`), box = el.querySelector("#sp-in"), pathBox = el.querySelector("#sp-path"), q = el.querySelector("#sp-q");
  let terms = null, refusals = [];
  const byCode = (code) => refusals.find((r) => r.code === code);

  const tryPath = () => {
    const path = pathBox.value.trim().replace(/^\.?\//, ""), out = $("verdict");
    if (!terms || !path) { out.textContent = ""; out.removeAttribute("data-class"); return; }
    const got = classify(terms, path, $("new").checked), row = byCode(got.code);
    out.dataset.class = got.class;
    out.innerHTML = got.class === "refused" ? `Refused. ${esc(row ? `${row.happened} ${row.do}` : "")} <code>${esc(got.code)}</code>`
      : got.class === "allowed_not_counted" ? "Allowed, not counted. The judge runs the buyer's tests." : "Allowed.";
  };
  const show = (t, what) => {
    terms = t;
    $("out").innerHTML = rulesHtml(t); $("out").dataset.state = "done"; $("try").hidden = false;
    $("said").textContent = what; tryPath();
  };
  const fail = (why) => { $("out").dataset.state = "done"; $("said").textContent = why; };
  const load = async (link, what) => {
    $("out").dataset.state = "pending"; $("said").textContent = "Reading the link.";          // a pending state at once
    try {
      const r = await fetchFn(link.url, { headers: { accept: "application/json" } });
      if (!r.ok) return fail(r.status === 403 || r.status === 429 ? "GitHub's hourly limit is spent. Paste the terms." : "That link gave nothing to read.");
      const body = await r.json();
      show(link.issue ? termsInComments(body) : readTerms(JSON.stringify(body)), what || (link.issue ? `Read from ${link.issue}.` : "Read from the link."));
    } catch (e) { fail(e instanceof Error && /terms|JSON/.test(e.message) ? e.message : "That link could not be read."); }
  };
  const run = async () => {
    const text = box.value.trim(), link = termsLink(text);
    if (!text) return fail("Paste terms, or pick a sample.");
    if (link) return load(link);
    try { return show(readTerms(text), "Read from what you pasted."); } catch (e) { return fail(e.message); }
  };
  const sampleButtons = (list) => {
    $("samples").innerHTML = list.map((s, i) => `<button type="button" class="k-btn quiet" data-sample="${i}">Sample: ${esc(s.name)}</button>`).join("");
    $("samples").querySelectorAll("button").forEach((b) => b.addEventListener("click", async () => {
      const s = list[Number(b.dataset.sample)];
      if (s.terms) { box.value = JSON.stringify(s.terms); return show(readTerms(box.value), `Sample: ${s.name}. Not a real order.`); }
      box.value = s.url; await load({ url: s.url, issue: "" }, `Sample: ${s.name}. Not a real order.`);
    }));
  };
  const table = () => {
    const rows = search(refusals, q.value);
    $("rows").innerHTML = rows.map((r) => `<tr><td><code>${esc(r.code)}</code></td><td>${esc(r.happened)}</td><td>${esc(r.do)}</td></tr>`).join("");
    $("count").textContent = refusals.length ? `${rows.length} of ${refusals.length} refusals.` : "The table could not be read.";
  };

  $("run").addEventListener("click", run);
  pathBox.addEventListener("input", tryPath); $("new").addEventListener("change", tryPath); q.addEventListener("input", table);
  sampleButtons(SAMPLES);
  const loaded = Promise.all([
    fetchFn(`${base}refusals.json`).then((r) => (r.ok ? r.json() : null)).then((j) => { refusals = Array.isArray(j?.rows) ? j.rows : []; }).catch(() => {}).then(table),
    fetchFn(`${base}terms/index.json`).then((r) => (r.ok ? r.json() : null)).then((j) => {
      const list = (j?.templates || []).filter((t) => /^[a-z0-9-]+$/.test(t.name) && Number.isInteger(t.version)).map((t) => ({ name: t.name, url: `${base}terms/${t.name}/${t.version}.json` }));
      if (list.length) sampleButtons(list);
    }).catch(() => {}),
  ]);
  return { run, loaded };
}
