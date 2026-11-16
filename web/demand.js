// #demand: the Qloo demand check from the front door, with the same plain controls as the app (web/demand_opts.js is the
// app's static/demand_opts.js; tests keep them identical). Added by name in web/views.js. Nothing is asked of the app
// (knos.onrender.com) until "Check demand" is pressed; Qloo itself is called there, server side, never from this page.
const APP = "https://knos.onrender.com";
const CSS = `fieldset.fam{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:10px 0;min-width:0}
fieldset.fam legend{font-weight:600;padding:0 4px}.famrow{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;margin:6px 0}
.famrow .famq{flex:0 0 7.5rem;font-weight:600}.famrow select,.famrow input{flex:1 1 8rem;min-width:0;min-height:44px}.famrow input.yr{flex:0 1 6rem}
.famrow label.chk{display:inline-flex;align-items:center;gap:4px;flex:0 0 auto;white-space:nowrap}.famrow label.chk input{flex:0 0 auto;width:auto;min-height:0}.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
details.famadv summary{cursor:pointer;min-height:44px;display:flex;align-items:center}.famgrid{display:grid;gap:10px}
.famset{display:grid;gap:4px;grid-template-columns:repeat(auto-fill,minmax(min(100%,12rem),1fr))}.famset>b{grid-column:1/-1}
@media (max-width:420px){.famrow .famq{flex-basis:100%}}`;
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function script() {
  if (window.KnosDemand) return Promise.resolve();
  return new Promise((res, rej) => { const s = document.createElement("script"); s.src = "./demand_opts.js"; s.onload = res; s.onerror = () => rej(new Error("demand_opts.js did not load")); document.head.append(s); });
}

export async function renderDemand(el) {
  if (!document.getElementById("fam-css")) { const st = document.createElement("style"); st.id = "fam-css"; st.textContent = CSS; document.head.append(st); }
  el.innerHTML = `<h2>Is it wanted?</h2>
    <p>Qloo's taste data says who wants it and where, before any money moves.</p>
    <form id="fd-demand" class="card" autocomplete="off">
      <label for="fd-idea">The product, in a sentence</label><textarea id="fd-idea" rows="2" maxlength="500" placeholder="trail running shoes for ultramarathons"></textarea>
      <label for="fd-place">Launch market (optional)</label><input id="fd-place" maxlength="60" placeholder="Austin">
      <div id="fd-opts"></div>
      <button class="k-btn" type="submit" id="fd-go">Check demand</button>
      <p class="devnet">Directional demand evidence, not a sales forecast.</p></form><div id="fd-out" aria-live="polite"></div>`;
  await script();
  window.KnosDemand.mount(el.querySelector("#fd-opts"), APP);
  el.querySelector("#fd-demand").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const out = el.querySelector("#fd-out"), go = el.querySelector("#fd-go");
    const idea = el.querySelector("#fd-idea").value.trim();
    if (idea.length < 8) { out.innerHTML = `<p class="status">Say the product in 8 characters or more.</p>`; return; }
    go.disabled = true; out.innerHTML = `<p class="status">Asking Qloo through the app (a sleeping app can take a minute)…</p>`;
    try {
      const body = { idea, place: el.querySelector("#fd-place").value.trim() || undefined, ...window.KnosDemand.values(el.querySelector("#fd-opts")) };
      const r = await fetch(APP + "/api/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const rep = await r.json();
      if (!r.ok) throw new Error(rep.error || `HTTP ${r.status}`);
      const d = rep.decision || {};
      const src = window.KnosDemand.src(APP, rep.hash);              // each Qloo-derived value links to its trace on the app
      out.innerHTML = `<div class="card"><h3 data-qloo>${esc(d.verdict === "OPEN" ? "Open for pre-orders" : d.verdict === "REFUSE" ? "Not yet" : "Cannot decide")}${src}</h3>
        ${(d.reasons || []).slice(0, 3).map((x) => `<p class="small" data-qloo>${esc(x)}${src}</p>`).join("")}${window.KnosDemand.answers(rep, APP)}
        <p><a class="k-btn" href="${APP}/app/#buy=${esc(rep.hash)}">Open it in the app →</a></p></div>`;
    } catch (e) { out.innerHTML = `<p class="status">The demand check did not answer: ${esc(e.message)}</p>`; }
    go.disabled = false;
  });
}
