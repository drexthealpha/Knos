// Terms: the published terms templates (terms/, docs/TERMS.md "Knos Terms 1"), as a list a person can browse.
//
//   renderTerms(el, env)   draws the registry into `el`: one card a template with its sentence, what it trusts, its
//                          hash, "Cite in a contract" and "Fund with this"; a box that says which published template
//                          a pasted terms JSON or hash is; and a table of every version.
//
// It reads one file of this site, terms/index.json (scripts/build_site.sh copies terms/ there), and asks nobody else.
// The hash of pasted terms is computed here, from the same canonical bytes knos.terms.canonical writes: keys sorted,
// "," and ":" with no space, ASCII with \uXXXX for everything else, every list sorted with no repeat, 600 bytes at
// most. `env`: { index } the registry already read, { fetchJson(path) } another reader, { copy(text) } another clipboard.
export const STANDARD = "Knos Terms 1";
export const MAX_BYTES = 600;
const KEYS = ["accept", "checks", "deny", "mode", "paths", "reserve", "v"], MORE = ["image", "policy", "vendor"];
const HASH = /^[0-9a-f]{64}$/;

const esc = (s) => String(s).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
const byPoint = (a, b) => { const x = [...a], y = [...b]; for (let i = 0; i < Math.min(x.length, y.length); i++) { const d = x[i].codePointAt(0) - y[i].codePointAt(0); if (d) return d; } return x.length - y.length; };
const sortedSet = (list) => [...new Set(list)].sort(byPoint);
const whole = (n) => typeof n === "number" && Number.isSafeInteger(n);

// The canonical text of terms, as knos.terms.canonical writes it; throws with a plain reason for what is not terms.
// This puts the fields in order and the lists in order. It does not judge every field as the program's reader does:
// a hash that is published was made from terms that reader accepted.
export function canonicalTerms(terms) {
  if (!terms || typeof terms !== "object" || Array.isArray(terms)) throw new Error("Not a terms object.");
  const have = Object.keys(terms), extra = have.filter((k) => !KEYS.includes(k) && !MORE.includes(k));
  if (extra.length || KEYS.some((k) => !have.includes(k))) throw new Error(`Terms have exactly these fields: ${KEYS.join(", ")}.`);
  if (terms.v !== 1 || !["merge", "tests"].includes(terms.mode) || typeof terms.accept !== "string" || !whole(terms.reserve)) throw new Error("Not Knos Terms 1.");
  if (![terms.checks, terms.deny, terms.paths].every(Array.isArray)) throw new Error("checks, deny and paths are lists.");
  if ("vendor" in terms && !whole(terms.vendor)) throw new Error("This vendor id is too large to check in a browser.");
  const checks = new Map();
  for (const c of terms.checks) {
    if (!c || typeof c.name !== "string" || !whole(c.app) || Object.keys(c).length !== 2) throw new Error('Each check is {"app": id, "name": name}.');
    checks.set(JSON.stringify([c.name, c.app]), c);
  }
  if (![...terms.deny, ...terms.paths].every((g) => typeof g === "string")) throw new Error("deny and paths hold globs.");
  const sorted = [...checks.values()].sort((a, b) => byPoint(a.name, b.name) || a.app - b.app);
  const out = { accept: terms.accept, checks: sorted.map((c) => ({ app: c.app, name: c.name })), deny: sortedSet(terms.deny) };
  if ("image" in terms) out.image = terms.image;
  out.mode = terms.mode; out.paths = sortedSet(terms.paths);
  if ("policy" in terms) out.policy = terms.policy;
  out.reserve = terms.reserve; out.v = 1;
  if ("vendor" in terms) out.vendor = terms.vendor;
  const text = JSON.stringify(out).replace(/[^\x00-\x7e]/g, (ch) => `\\u${ch.charCodeAt(0).toString(16).padStart(4, "0")}`);
  if (text.length > MAX_BYTES) throw new Error(`These terms take ${text.length} bytes; terms hold at most ${MAX_BYTES}.`);
  return text;
}

export async function sha256Hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// The sha256 a pasted text stands for: itself when it is one, else the hash of the terms it holds (a terms object,
// or a file that carries one under "terms"). Throws with a plain reason.
export async function hashOf(pasted) {
  const text = String(pasted).trim();
  if (HASH.test(text.toLowerCase())) return text.toLowerCase();
  let data;
  try { data = JSON.parse(text); } catch { throw new Error("Neither a sha256 nor JSON."); }
  if (data && typeof data === "object" && data.terms && typeof data.terms === "object") data = data.terms;
  return sha256Hex(canonicalTerms(data));
}

// The published versions with that hash, oldest first.
export const published = (index, hash) => (index?.templates || []).filter((t) => t.hash === hash);
export const citeSentence = (t) => `Acceptance is governed by ${STANDARD}, template ${t.name} version ${t.version}, sha256 ${t.hash}`;
export const fileOf = (t) => `terms/${t.name}/${t.version}.json`;
// The newest version of each template, in the registry's order.
export function newest(index) {
  const out = new Map();
  for (const t of index?.templates || []) if (!out.has(t.name) || out.get(t.name).version < t.version) out.set(t.name, t);
  return [...out.values()];
}
const JUDGE = { merge: "a maintainer's merge", "in-process": "in-process", "black-box": "black-box", hermetic: "hermetic" };
export const trustOf = (t) => `Judge: ${JUDGE[t.trust?.judge] || "not said"}. Quorum: ${t.trust?.quorum || 1}.`;

export async function renderTerms(el, env = {}) {
  if (el.dataset.terms) return;                 // drawn once, whoever calls
  el.dataset.terms = "1";
  const fetchJson = env.fetchJson || (async (path) => { const r = await fetch(path); if (!r.ok) throw new Error(`${path}: ${r.status}`); return r.json(); });
  const copy = env.copy || ((text) => navigator.clipboard.writeText(text));
  let index;
  try { index = env.index || await fetchJson("terms/index.json"); } catch { index = null; }
  if (!index || !Array.isArray(index.templates) || !index.templates.length) {
    el.innerHTML = `<h2>Terms</h2><p class="status" id="terms-none">This build holds no terms registry.</p>`;
    return;
  }
  const rows = newest(index);
  el.innerHTML = `
    <p class="k-kicker">${esc(index.standard || STANDARD)}</p>
    <h2>Terms a contract cites by hash</h2>
    <p class="devnet">Test USDC on Solana devnet.</p>
    <div id="terms-list">${rows.map((t, i) => `
      <section class="k-card" data-tilt data-template="${esc(t.name)}">
        <p class="k-kicker">Version ${t.version}</p>
        <h3>${esc(t.name)}</h3>
        <p class="terms-sentence">${esc(t.sentence).replace(/`([^`]*)`/g, "<code>$1</code>")}.</p>
        <p class="terms-trust">${esc(trustOf(t))}</p>
        <p class="terms-hash"><code class="k-num" data-copy>${esc(t.hash)}</code></p>
        <p class="terms-act">
          <button type="button" class="k-btn quiet" data-copy="hash" data-i="${i}">Copy hash</button>
          <button type="button" class="k-btn" data-copy="cite" data-i="${i}">Cite in a contract</button>
          <button type="button" class="k-btn quiet" data-copy="fund" data-i="${i}">Fund with this</button>
          <a href="${esc(fileOf(t))}">Open the file</a>
        </p>
        <output class="terms-copied" aria-live="polite"></output>
      </section>`).join("")}
    </div>
    <section class="k-card" id="terms-check">
      <h3><label for="terms-paste">Paste a terms JSON or hash</label></h3>
      <textarea id="terms-paste" rows="4" spellcheck="false" autocomplete="off"></textarea>
      <p><button type="button" class="k-btn" id="terms-which">Find the template</button></p>
      <output id="terms-answer" aria-live="polite"></output>
    </section>
    <section class="k-card" id="terms-versions">
      <h3>Every published version</h3>
      <div class="k-table"><table>
        <thead><tr><th>Template</th><th>Version</th><th>sha256</th></tr></thead>
        <tbody>${index.templates.map((t) => `<tr><td><a href="${esc(fileOf(t))}">${esc(t.name)}</a></td><td class="k-num">${t.version}</td><td><code class="k-num">${esc(t.hash)}</code></td></tr>`).join("")}</tbody>
      </table></div>
      <p><a href="https://github.com/drexthealpha/Knos/blob/main/docs/TERMS.md">Read the standard</a></p>
    </section>`;
  const text = { hash: (t) => t.hash, cite: citeSentence, fund: (t) => t.comment };
  const done = { hash: "Hash copied", cite: "Sentence copied", fund: "Comment copied" };
  for (const button of el.querySelectorAll("button[data-copy]")) {
    button.addEventListener("click", async () => {
      const t = rows[Number(button.dataset.i)], what = text[button.dataset.copy](t);
      const shown = button.closest("section").querySelector(".terms-copied");
      shown.textContent = what;                 // what was copied stays in view: a clipboard that refuses still leaves it to select
      try { await copy(what); button.textContent = done[button.dataset.copy]; } catch { button.textContent = "Select it below"; }
    });
  }
  const answer = el.querySelector("#terms-answer"), paste = el.querySelector("#terms-paste");
  const which = async () => {
    answer.dataset.found = "";
    if (!paste.value.trim()) { answer.textContent = ""; return; }
    let hash;
    try { hash = await hashOf(paste.value); } catch (why) { answer.textContent = why.message; answer.dataset.found = "error"; return; }
    const found = published(index, hash);
    answer.dataset.found = found.length ? "yes" : "no";
    answer.innerHTML = found.length
      ? found.map((t) => `<strong>${esc(t.name)}</strong> version ${t.version}. <a href="${esc(fileOf(t))}">Open the file</a>`).join("<br>")
      : `Not a published template. sha256 <code>${esc(hash)}</code>`;
  };
  el.querySelector("#terms-which").addEventListener("click", which);
  paste.addEventListener("paste", () => setTimeout(which, 0));
}
