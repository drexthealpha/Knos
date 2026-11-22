// The demand check, the app's first screen (web/brand/hero.html, written into the app's home by scripts/sync_brand.py): a DOI, an arXiv id or an idea in,
// the open signals' verdict out, drawn as one card: the verdict, each source's count with its link (Wikipedia views,
// news articles, Hacker News stories, research papers, money already put down here) and the rule that decided. A paper
// goes through the crossing (POST /api/cross: the paper read, its product named, then the check); an idea straight to
// the check (POST /api/check). Nothing here is estimated: a source that did not answer is left out of the card.
(() => {
  const root = document.getElementById("k-hero");
  if (!root || root.dataset.ready) return;
  root.dataset.ready = "1";
  // the app's address: the front door's page names no other host (it says "@app"); the app's own page uses its own
  const API = root.dataset.api === "@app" ? "https://knos.onrender.com" : root.dataset.api || "", APP = root.dataset.app || "/";
  const form = document.getElementById("k-ask"), q = document.getElementById("k-q"), go = document.getElementById("k-go"), slot = document.getElementById("k-card");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const DOI = /^(?:doi:\s*|https?:\/\/(?:dx\.)?doi\.org\/)?(10\.\d{4,9}\/\S+)$/i;
  const ARXIV = /^(?:arxiv:\s*|https?:\/\/arxiv\.org\/(?:abs|pdf)\/)?(\d{4}\.\d{4,5}(?:v\d+)?)(?:\.pdf)?$/i;
  const paper = (v) => { const d = v.match(DOI); if (d) return d[1]; const a = v.match(ARXIV); return a ? "arXiv:" + a[1] : null; };
  const post = async (path, body) => {
    const r = await fetch(API + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.message || j.error || `the server answered ${r.status}`);
    return j;
  };
  const get = async (path) => { const r = await fetch(API + path); if (!r.ok) throw new Error(`the server answered ${r.status}`); return r.json(); };
  // motion: one move per change, transform and opacity only; with reduced motion nothing moves
  const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  // the busy button keeps its label and its width ("Checking…" after a 14 px spinner), the 2 px bar runs along the box's
  // bottom edge, and the line under the box (a polite live region) says what is being read and for how long
  const live = document.getElementById("k-live"), liveSaid = live && live.querySelector("[data-said]"), liveT = live && live.querySelector("[data-t]");
  let clock = 0, since = 0;
  const tick = () => { if (liveT && since) liveT.textContent = `· ${((performance.now() - since) / 1000).toFixed(still() ? 0 : 1)} s`; };
  const busy = (on) => {
    const label = go.querySelector("[data-label]") || go;
    clearInterval(clock);
    if (!on) { label.textContent = "Check demand →"; go.style.minWidth = ""; go.removeAttribute("aria-busy"); form.removeAttribute("aria-busy");
      since = 0; if (liveSaid) liveSaid.textContent = ""; if (liveT) liveT.textContent = ""; return; }
    go.style.minWidth = `${go.offsetWidth}px`;
    label.textContent = "Checking…"; go.setAttribute("aria-busy", "true"); form.setAttribute("aria-busy", "true");
    since = performance.now(); tick(); clock = setInterval(tick, still() ? 1000 : 100);
  };
  const said = (t) => { if (liveSaid) liveSaid.textContent = t; };
  // while a crossing runs, each step appears under the box as it finishes (the job's steps, polled every 500 ms)
  const flowRows = (steps) => { const box = document.getElementById("k-flow"); if (!box) return;
    const rows = steps.filter((x) => x && x.title);
    box.hidden = !rows.length;
    box.innerHTML = rows.map((x) => `<li data-flow-row>${esc(x.title)}${x.output ? ` · ${esc(String(x.output).slice(0, 80))}` : ""}</li>`).join(""); };
  // a new result replaces the card in place, revealed by a view transition; the card is scrolled into view only when its
  // top is below 60% of the window. Reduced motion: the swap is instant.
  const reveal = (html, after) => {
    const swap = () => { slot.innerHTML = html; delete slot.dataset.empty;
      const rows = slot.querySelector(".k-card, .k-past-card");
      if (rows && !still()) { [...rows.children].forEach((c, i) => c.style.setProperty("--i", String(i))); slot.dataset.reveal = "1"; }
      if (after) after(); };
    const done = () => {
      const top = slot.getBoundingClientRect().top;
      if (top > innerHeight * 0.6 || top < 0) scrollTo({ top: Math.max(0, scrollY + top - 88), behavior: still() ? "auto" : "smooth" });   // 88 px: under the sticky bar
      setTimeout(() => { delete slot.dataset.reveal; }, 600);
    };
    if (!still() && document.startViewTransition && document.visibilityState === "visible") {
      const html = document.documentElement; html.classList.add("k-revealing");
      try { const vt = document.startViewTransition(swap); vt.updateCallbackDone.then(done, done); return vt.finished.catch(() => {}).finally(() => html.classList.remove("k-revealing")); }
      catch { html.classList.remove("k-revealing"); /* an engine that refuses: swap at once */ }
    }
    swap(); done(); return Promise.resolve();
  };

  async function crossing(ref) {
    const j = await post("/api/cross", { ref });
    let at = 0;
    for (let i = 0; i < 240; i++) {
      const p = await get(`/api/cross?id=${encodeURIComponent(j.id)}&since=${at}`);
      at = p.total ?? at;
      const last = (p.steps || []).at(-1);
      if (last && last.title) said(last.title);
      flowRows(p.steps || []);
      if (p.status === "error") throw new Error(p.error || "the crossing stopped");
      if (p.report) return get("/api/report?hash=" + encodeURIComponent(p.report));
      if (p.status !== "running") throw new Error("the crossing ended without a demand check");
      await new Promise((ok) => setTimeout(ok, 500));
    }
    throw new Error("the crossing took too long");
  }

  // the card's own stylesheet (web/brand/card.css, beside tokens.css): asked for once, before the first card is drawn
  let cardSheet = null;
  const cardCss = () => cardSheet || (cardSheet = new Promise((done) => {
    const tokens = document.querySelector('link[rel="stylesheet"][href*="tokens.css"]');
    if (document.getElementById("k-card-sheet") || document.querySelector('link[rel="stylesheet"][href$="card.css"]')) return done();   // in the page's head: there already
    let href = null;
    try { href = tokens ? tokens.href.replace(/tokens\.css(\?.*)?$/, "card.css") : location.pathname.startsWith("/app") ? "/static/brand/card.css" : new URL("brand/card.css", document.baseURI).href; } catch { href = null; }
    if (!href) return done();                // a page with no address of its own (a test's): the card is drawn without it
    const l = Object.assign(document.createElement("link"), { rel: "stylesheet", id: "k-card-sheet", href });
    l.onload = l.onerror = () => done();
    document.head.append(l);
  }));
  const style = () => { if (document.getElementById("k-card-css")) return;
    document.head.insertAdjacentHTML("beforeend", `<style id="k-card-css">.k-rows{margin:var(--sp-2) 0 0;padding-left:1.1em}.k-rows li{margin:0 0 4px;overflow-wrap:anywhere}.k-rows li[data-counts="1"] b{color:var(--ok,inherit)}.k-mine{margin-top:var(--sp-4)}.k-mine h3{font-size:var(--s1);margin:0 0 4px}.k-mine ul{margin:4px 0;padding-left:1.1em}.k-mine li{overflow-wrap:anywhere}</style>`); };
  const WORD = { OPEN: ["Open signals say people want this", "open"], REFUSE: ["Open signals find little interest yet", "refuse"], CANNOT_DECIDE: ["No signal yet", "unknown"] };
  // the model's state, read once when a card is first drawn (GET /api/status "model"); the ask box shows only while it is "on"
  let modelOn = false, modelAsked = false;
  const askModel = () => { if (modelAsked) return; modelAsked = true;
    get("/api/status").then((st) => { modelOn = !!(st && st.model === "on"); if (modelOn) slot.querySelectorAll("[data-ask-box][hidden]").forEach((f) => { f.hidden = false; }); }).catch(() => {}); };
  // which one do you mean? (apps/wanted which.py): a paper shows itself first and its products as readings, or a box to name one
  const whichCard = (w) => { const pp = w.paper;
    const paperLine = pp ? `<p class="k-why" data-paper>${esc(pp.title)}${pp.year ? ` (${esc(pp.year)})` : ""}${Number.isFinite(pp.cited_by_count) ? `, cited ${Number(pp.cited_by_count).toLocaleString("en-US")} times` : ""}${(pp.concepts || []).length ? ` · ${esc(pp.concepts.slice(0, 3).join(", "))}` : ""}</p>` : "";
    const rows = (w.readings || []).map((x) => `<li><button type="button" class="k-chip" data-reading="${esc(x.text)}" data-kind="${esc(x.kind)}">${esc(x.text)}</button></li>`).join("");
    const box = w.name_box ? `<form data-name-box class="k-row"><label class="k-fine" for="k-name">${esc(w.name_prompt || "Name the product this result enables")}</label> <input id="k-name" name="name" maxlength="200" required> <button type="submit" class="k-chip">Check it</button></form>` : "";
    return `<article class="k-card k-unknown" data-which data-not-prose><header class="k-card-head"><p class="k-kick">${esc(w.asked)}</p><h2 class="k-verdict">Which one do you mean?</h2>${paperLine}${rows ? `<ul class="k-readings" data-readings>${rows}</ul>` : ""}${box}</header></article>`; };
  const value = (x) => (x.name === "Money down" ? `$${Number(x.value || 0).toFixed(2)}` : Number(x.value || 0).toLocaleString("en-US"));
  const rowsOf = (r) => ((r.open_demand || {}).rows || r.signals || []);
  // one card: the verdict, each source's row with its link, the rule; then share, receipts, "Was this useful?"
  function card(r, label) {
    style(); askModel();
    if (r.kind === "which_one") return whichCard(r);
    const d = r.decision || {}, fb = r.open_demand || {}, h = /^[0-9a-f]{16,64}$/.test(r.hash || "") ? r.hash : "", rid = h.slice(0, 16), id = esc(h.slice(0, 8));
    const [word, cls] = WORD[d.verdict] || [String(d.verdict || "No verdict"), "unknown"];
    const rows = rowsOf(r).map((x) => `<li data-counts="${x.counts ? 1 : 0}"><span>${esc(x.name)}</span> <b>${x.link ? `<a href="${esc(x.link)}" target="_blank" rel="noopener">${value(x)}</a>` : value(x)}</b> <span class="k-fine">${esc(x.unit)}</span></li>`).join("");
    const rule = [fb.line || r.line, fb.rule || r.rule].filter(Boolean).join(" ");
    return `<article class="k-card k-${cls}" data-verdict="${esc(d.verdict || "")}" data-open-demand data-not-prose>
  <header class="k-card-head"><p class="k-kick">${label ? `<span class="k-real">${esc(label)}</span> · ` : ""}${esc(r.idea || "")}</p><h2 class="k-verdict" data-part="verdict" tabindex="-1">${esc(fb.head || word)}</h2></header>
  ${rows ? `<ul class="k-rows" data-part="signals">${rows}</ul>` : `<p class="k-none">No source answered.</p>`}
  ${rule ? `<p class="k-fine" data-part="rule">${esc(rule)}</p>` : ""}
  ${h ? `<form class="k-useful" data-useful data-hash="${esc(h)}"><span>Was this useful?</span> <button type="submit" class="k-chip" name="useful" value="yes">Yes</button> <button type="submit" class="k-chip" name="useful" value="no">No</button> <label class="k-sr" for="k-note-${id}">A note, optional</label><input id="k-note-${id}" name="note" maxlength="280" placeholder="A note (optional)"> <span class="k-fine" data-useful-said role="status"></span></form>
  <form class="k-askit" data-ask-box data-hash="${esc(h)}"${modelOn ? "" : " hidden"}><label for="k-askq-${id}">Ask about this result</label> <input id="k-askq-${id}" name="question" maxlength="300" required> <button type="submit" class="k-chip">Ask</button><span class="k-fine" data-ask-said role="status"></span></form>` : ""}
  <footer class="k-card-foot">${rid ? `<p class="k-fine"><a href="${esc(API)}/r/${esc(rid)}" target="_blank" rel="noopener" data-share>Share this result</a> · <a href="${esc(API)}/receipts/${esc(rid)}" target="_blank" rel="noopener" data-receipts>Receipts</a></p>` : ""}<p class="k-fine">Directional demand evidence, not a sales forecast. Devnet test money.</p></footer>
</article>`;
  }
  async function ask(v, extra = {}) {
    v = v.trim();
    if (!v) { q.focus(); return; }
    go.disabled = true; root.setAttribute("aria-busy", "true"); busy(true);
    flowRows([]);
    const ref = extra.picked ? null : paper(v), t0 = performance.now();
    said(ref ? "Reading the paper" : "Checking demand");
    try {
      let r;
      if (ref) {                                       // which one do you mean? a paper is read first
        const w = await post("/api/check", { idea: v, stage: "verdict" });
        r = w && w.kind === "which_one" ? w : await crossing(ref);
      } else {
        const place = (document.getElementById("k-guess")?.value || "").trim().slice(0, 60);
        r = await post("/api/check", { idea: v, picked: true, ...(place ? { place } : {}), ...extra });
      }
      await cardCss();
      slot.last = r;
      reveal(card(r), () => document.dispatchEvent(new CustomEvent("knos:reached", { detail: 0 })));
      slot.dataset.idea = v;
      if (r.kind !== "which_one") keepMine(r, v);
      delete slot.dataset.past;
      slot.dataset.ms = String(Math.round(performance.now() - t0));
      slot.querySelector(".k-verdict")?.focus?.();
    } catch (e) {
      reveal(`<p class="k-err" role="alert">${esc(e.message || e)}. Try again, or <a href="${esc(APP)}#research">open the full crossing</a>.</p>`);
    } finally { go.disabled = false; root.removeAttribute("aria-busy"); busy(false); }
  }
  // a link that names an idea (?q=, from the fields page or a share) fills the box; the check runs when the reader presses
  // Check (a crawler or a preview asks no source)
  const asked = new URLSearchParams(location.search).get("q");
  if (asked) q.value = asked.slice(0, 500);
  const seen = (el, then) => {
    if (!("IntersectionObserver" in window)) return then();
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { io.disconnect(); then(); } });
    io.observe(el);
  };
  // the first screen's finished result: the real last Open check this server ran (GET /api/proof), labelled as a past
  // check; the visitor's own check replaces it
  const pastCard = (r, label) => {
    const d = r.decision || {}, rows = rowsOf(r).filter((x) => x.link).slice(0, 3), h = /^[0-9a-f]{16}/.test(r.hash || "") ? r.hash.slice(0, 16) : "";
    return `<article class="k-past-card" data-verdict="${esc(d.verdict || "")}" data-past-card data-not-prose>
  <p class="k-kick"><span class="k-real">${esc(label)}</span> · ${esc(r.idea || "")}</p>
  <h2 class="k-v" data-part="verdict">Wanted</h2>
  ${rows.length ? `<ul class="k-rows">${rows.map((x) => `<li><span>${esc(x.name)}</span> <b>${value(x)}</b> <span class="k-fine">${esc(x.unit)}</span></li>`).join("")}</ul>` : ""}
  <p class="k-foot">${h ? `<a href="${esc(API)}/r/${esc(h)}" target="_blank" rel="noopener">The result</a>` : "<span></span>"} <button type="button" class="k-chip" data-whole>See the whole card</button></p>
</article>`;
  };
  const draw = (r) => {
    if (!r || slot.dataset.ms || go.hasAttribute("aria-busy")) return;
    const p = r.proof && r.proof.decision && r.proof.decision.verdict === "OPEN" ? r.proof : null;
    if (!p) { slot.dataset.empty = "1"; return; }
    slot.past = `A past check, ${String(p.made || p.checked_at || "").slice(0, 10)}`;
    slot.innerHTML = pastCard(p, slot.past);
    slot.last = p;
    slot.dataset.past = "1";
    try { performance.mark("knos-proof-shown"); } catch { /* old browsers */ }   // when the past result was drawn
  };
  slot.addEventListener("click", (ev) => {           // the first screen's card, opened whole in place
    if (!(ev.target instanceof Element) || !ev.target.closest("[data-whole]") || !slot.last) return;
    reveal(card(slot.last, slot.past || ""));
  });
  // WebMCP: an agent that submits the form gets the result as JSON; a person gets the card
  form.addEventListener("submit", (ev) => { ev.preventDefault(); pressed(null);
    const run = ask(q.value);
    if (ev.agentInvoked && ev.respondWith) ev.respondWith(run.then(() => { const r = slot.last || {}, h = /^[0-9a-f]{16}/.test(r.hash || "") ? r.hash : "";
      return JSON.stringify({ verdict: (r.decision || {}).verdict || (r.kind === "which_one" ? "WHICH_ONE" : null), readings: r.readings || undefined,
        signals: rowsOf(r).map((x) => ({ name: x.name, value: x.value, unit: x.unit, link: x.link || null })), result: h ? `${API}/r/${h.slice(0, 16)}` : null }); })); });
  // read-only tools for an agent in the page, where the browser offers them (document.modelContext); money stays in the app
  if ("modelContext" in document && document.modelContext && document.modelContext.registerTool) {
    try {
      document.modelContext.registerTool({ name: "open_result", description: "Opens the page of a past demand check by its hash",
        inputSchema: { type: "object", properties: { hash: { type: "string", description: "The check's hash, 64 hex characters" } }, required: ["hash"] },
        annotations: { readOnlyHint: true },
        execute: async ({ hash }) => { if (!/^[0-9a-f]{64}$/.test(String(hash || ""))) return "hash: 64 hex characters"; open(`${API}/r/${hash.slice(0, 16)}`, "_blank", "noopener"); return `opened the result ${hash}`; } });
      document.modelContext.registerTool({ name: "open_preorders", description: "Opens the pre-order page of an Open check in the app; the person confirms any money there",
        inputSchema: { type: "object", properties: { hash: { type: "string", description: "The Open check's hash" } }, required: ["hash"] },
        annotations: { consequentialHint: true },
        execute: async ({ hash }) => { if (!/^[0-9a-f]{64}$/.test(String(hash || ""))) return "hash: 64 hex characters"; location.href = `${APP}#buy=${hash}`; return "opened the pre-order page"; } });
    } catch { /* a browser whose tools differ: the form still works */ }
  }
  // the chip pressed is the one shown pressed
  const pressed = (b) => root.querySelectorAll(".k-try .k-chip").forEach((c) => c.setAttribute("aria-pressed", String(c === b)));
  // the parts of the hero after this script in the page (the chips, the shape, the proof strip): wired once parsed
  const parsed = (f) => (document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", f, { once: true }) : f());
  parsed(() => {
    // the two optional fields wait behind one disclosure (a <details>, so it opens without script too)
    const add = document.getElementById("k-add");
    if (add) add.addEventListener("toggle", () => { if (add.open) document.getElementById("k-guess")?.focus(); });
    // the proof strip: the first two numbers are the published runs'; the last two are read from the app at view time
    // (GET /api/counter), zeros shown as zeros, the tile left out when it does not answer. Each counts up from 0 over
    // 600 ms on first view (ease-out), and stands still with reduced motion.
    const strip = document.getElementById("k-strip");
    if (!strip) return;
    const show = (b, n) => { const dp = Number(b.dataset.dp || 0), tail = b.dataset.tail || "";
      b.textContent = n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp }) + tail; };
    const count = (b, to) => { if (still() || !(to > 0)) return show(b, to);
      const t0 = performance.now(), f = (now) => { const k = Math.min(1, (now - t0) / 600); show(b, to * (1 - (1 - k) ** 3)); if (k < 1) requestAnimationFrame(f); };
      requestAnimationFrame(f); };
    seen(strip, () => {
      for (const b of strip.querySelectorAll("b[data-n]")) count(b, Number(b.dataset.n));
      get("/api/counter").then((c) => { for (const b of strip.querySelectorAll("b[data-counter]")) { const n = c && Number(c[b.dataset.counter]);
        if (Number.isFinite(n)) { b.dataset.n = String(n); count(b, n); } else b.closest("li").remove(); } })
        .catch(() => { for (const b of strip.querySelectorAll("b[data-counter]")) b.closest("li").remove(); });
    });
  });
  // below the first screen: the newest payout to an agent, as the chain has it, and the usage counter (checks and
  // briefs from the app's store, the payment program's devnet transactions). The build wrote both into the page
  // (scripts/live_snapshot.py); they are asked again after the reader's first move, as the product list is (web/home.js)
  let moved = false;
  const later = (f) => { const go = () => { if (moved) return; moved = true; f(); };
    for (const t of ["pointermove", "pointerdown", "touchstart", "keydown", "scroll", "focusin"]) addEventListener(t, go, { once: true, passive: true, capture: true }); };
  // and only once the last step is in view: the first screen asks nobody
  later(() => seen(document.getElementById("step-released") || root, () => {
    const use = document.getElementById("k-usage"), oidc = document.getElementById("k-oidc");
    // the newest signature check knos_oidc ran on devnet (the program reads GitHub's signature itself), from devnet
    // the program's address is read from the program_ids.json the site's build ships, never typed into the page
    if (oidc) fetch("https://drexthealpha.github.io/Knos/program_ids.json").then((r) => r.json()).then((ids) => fetch("https://api.devnet.solana.com", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "getSignaturesForAddress", params: [ids.knos_oidc, { limit: 20, commitment: "confirmed" }] }) }))
      .then((r) => r.json()).then((j) => {
        const x = (j.result || []).find((t) => t.err === null);
        if (!x) return;
        const day = x.blockTime ? new Date(x.blockTime * 1000).toISOString().slice(0, 10) : "";
        oidc.innerHTML = `Latest signature check on devnet${day ? `, ${esc(day)}` : ""} · <a href="https://explorer.solana.com/tx/${esc(x.signature)}?cluster=devnet" target="_blank" rel="noopener">the transaction</a>`;
        oidc.dataset.live = "1";
      }).catch(() => {});
    // outside use only, this week against the last: a line only for real growth from at least 10, else nothing; the
    // comparison only once the counter has run two weeks (`since` 14 days back or more), before that this week alone
    if (use) get("/api/usage").then((u) => {
      const t = (u && u.trend) || {}, from = Date.parse(String((u && u.since) || "") + "T00:00:00Z");
      const twoWeeks = Number.isFinite(from) && Date.now() - from >= 14 * 864e5;
      const line = twoWeeks ? t.line : Number(t.this_week) > 0 ? `${Number(t.this_week).toLocaleString("en-US")} ideas checked this week` : "";
      use.textContent = line || "";
      use.hidden = !line;
      use.dataset.live = "1";
    }).catch(() => {});
  }));
  // "Your past checks": the results this browser checked (kept in its own storage: id, idea, day), each read back from
  // its line in the Knos record (GET /api/receipts?id=); "Forget mine" empties this browser's list only
  const MINE = "knos-past-checks";
  const mine = () => { try { return JSON.parse(localStorage.getItem(MINE) || "[]"); } catch { return []; } };
  const keepMine = (r, asked) => {
    const id = /^[0-9a-f]{16}/.test(r.hash || "") ? r.hash.slice(0, 16) : "";
    if (!id) return;
    const list = [{ id, idea: asked, at: new Date().toISOString().slice(0, 10) }, ...mine().filter((x) => x.id !== id || x.idea !== asked)].slice(0, 20);
    try { localStorage.setItem(MINE, JSON.stringify(list)); } catch { /* storage refused: nothing kept */ }
    pastChecks();
  };
  async function pastChecks() {
    style();
    let box = root.querySelector("[data-past-checks]");
    const list = mine();
    if (!list.length) { if (box) box.hidden = true; return; }
    if (!box) {
      slot.insertAdjacentHTML("afterend", `<section class="k-mine" data-past-checks aria-labelledby="k-mine-h"><h3 id="k-mine-h">Your past checks</h3>
        <p class="k-fine">Each read from its line in the Knos record.</p><ul data-mine></ul>
        <p><button type="button" class="k-chip" data-forget>Forget mine</button> <span class="k-fine" data-forgot role="status"></span></p></section>`);
      box = root.querySelector("[data-past-checks]");
    }
    box.hidden = false;
    box.querySelector("[data-forgot]").textContent = "";
    const ul = box.querySelector("[data-mine]");
    ul.innerHTML = list.map((x) => `<li data-id="${esc(x.id)}"><a href="${esc(API)}/r/${esc(x.id)}" target="_blank" rel="noopener">${esc(x.idea)}</a> · <span data-v>reading the record…</span> · ${esc(x.at)}</li>`).join("");
    for (const x of list) {
      get(`/api/receipts?id=${encodeURIComponent(x.id)}`).then((d) => {
        const li = ul.querySelector(`li[data-id="${x.id}"] [data-v]`), rec = (d.rows || []).find((r) => r.id === "record") || {};
        if (li) li.innerHTML = `${esc(d.verdict || "no verdict")} · ${rec.recorded ? `<a href="${esc(API)}/receipts/${esc(x.id)}#record" data-record>see it saved in the public record (entry ${esc(rec.seq)})</a>` : `<span data-record-none>${esc(rec.why || "not in the record")}</span>`}`;
      }).catch(() => { const li = ul.querySelector(`li[data-id="${x.id}"] [data-v]`); if (li) li.textContent = "the record did not answer"; });
    }
  }
  root.addEventListener("click", (ev) => {
    if (!(ev.target instanceof Element) || !ev.target.closest("[data-forget]")) return;
    try { localStorage.removeItem(MINE); } catch { /* nothing kept */ }
    const box = root.querySelector("[data-past-checks]");
    box.querySelector("[data-mine]").innerHTML = "";
    box.querySelector("[data-forgot]").textContent = "Removed from this browser. The public Knos record keeps each check's decision line, never its words.";
  });
  if (mine().length) pastChecks();
  slot.addEventListener("submit", (ev) => {         // "Was this useful?": saved with the check's hash, never who said it
    const f = ev.target.closest && ev.target.closest("[data-useful]"); if (!f) return;
    ev.preventDefault();
    const yes = ev.submitter ? ev.submitter.value === "yes" : true, out = f.querySelector("[data-useful-said]");
    f.querySelectorAll("button").forEach((b) => { b.disabled = true; b.setAttribute("aria-pressed", String(b.value === (yes ? "yes" : "no"))); });
    post("/api/feedback", { hash: f.dataset.hash, useful: yes, note: String(new FormData(f).get("note") || "").slice(0, 280) })
      .then(() => { out.textContent = "Saved. Thank you."; }).catch((e) => { out.textContent = `Not saved: ${e.message}`; f.querySelectorAll("button").forEach((b) => { b.disabled = false; }); });
  });
  slot.addEventListener("submit", (ev) => {         // "Ask about this result": answered from the card's own data, citing its sources
    const f = ev.target.closest && ev.target.closest("[data-ask-box]"); if (!f) return;
    ev.preventDefault();
    const out = f.querySelector("[data-ask-said]"); out.textContent = "Asking…";
    post("/api/ask", { hash: f.dataset.hash, question: String(new FormData(f).get("question") || "") })
      .then((a) => { out.textContent = a.refused ? `Not answered: ${a.refused}` : `${a.answer || ""}${(a.cites || []).length ? ` (sources ${a.cites.join(", ")})` : ""}`; })
      .catch((e) => { out.textContent = `Not answered: ${e.message}`; });
  });
  root.addEventListener("submit", (ev) => {
    const f = ev.target.closest("[data-name-box]");
    if (!f) return;
    ev.preventDefault();
    const name = String(new FormData(f).get("name") || "").trim();
    if (name) { q.value = name; ask(name, { picked: true }); }
  });
  root.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-q]"), reading = ev.target.closest("[data-reading]");
    if (reading) { q.value = reading.dataset.reading; ask(reading.dataset.reading, { picked: true }); }
    else if (b) { q.value = b.dataset.q; pressed(b.closest(".k-try") ? b : null); ask(b.dataset.q); }
  });
  // the past result, drawn last: every chip and the box already answer
  const shown = (r) => { document.dispatchEvent(new CustomEvent("knos:proof", { detail: r }));   // the shape under the box reads it too
    return cardCss().then(() => { try { draw(r); } catch (e) { console.warn("knos: the past result was not drawn", e); } }); };
  // the last Open check, drawn once the stranger opens "Try a sample", so the first screen holds the question and nothing else
  const samples = document.getElementById("k-samples");
  if (!asked && samples) samples.addEventListener("toggle", () => { if (samples.open && !slot.innerHTML) get("/api/proof").then((p) => p && !slot.innerHTML && shown(p)).catch(() => {}); }, { once: true });
})();
