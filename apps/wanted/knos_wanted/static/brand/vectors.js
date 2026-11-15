// The five product-value vectors on a main screen (web/brand/vectors.html), each its measured number from the app's
// GET /api/vectors: cost, speed, friction, trust, status. A number with no measurement yet stays
// as the page shipped it ("…"), never a guess. Each links to where it is measured.
(() => {
  const APP = "https://knos.onrender.com";
  for (const ul of document.querySelectorAll(".k-vectors:not([data-ready])")) {
    ul.dataset.ready = "1";
    const api = ul.dataset.api === "@app" ? APP : ul.dataset.api || "";
    const set = (v, html) => { const li = ul.querySelector(`[data-v="${v}"]`); if (li && html) li.innerHTML = html; };
    const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
    const load = () => fetch(api + "/api/vectors").then((r) => (r.ok ? r.json() : null)).then((v) => {
      if (!v) return;
      const c = v.cost || {}, s = v.speed || {}, t = v.trust || {}, st = v.status || {};
      set("cost", `<b>$${esc(c.api_usd_per_check ?? 0)}</b> per check${c.usd_per_ready_brief != null ? `, <b>$${esc(c.usd_per_ready_brief)}</b> per brief` : ""}`);
      if (s.median_s != null) set("speed", `<b>${esc(s.median_s)} s</b> median to verdict`);
      if (t.held_program) set("trust", `<a href="https://explorer.solana.com/address/${esc(t.held_program)}?cluster=devnet" rel="noopener"><b>Held</b> until the check passes, on devnet</a>`);
      set("status", st.latest ? `<a href="${esc(api + st.latest)}" title="Attested on Solana devnet"><b>${esc(st.ready_cards_attested)} Ready card${st.ready_cards_attested === 1 ? "" : "s"}</b></a>`
        : `<b>0 Ready cards</b>`);
    }).catch(() => {});
    // asked for only once it is on screen (a front door view that does not show it asks nothing)
    if (!("IntersectionObserver" in window)) load();
    else { const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { io.disconnect(); load(); } }); io.observe(ul); }
  }
})();
