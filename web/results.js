// A result page's Qloo part, read from the app's server when the page is viewed: the page itself holds the idea, the
// verdict and the date only, so no Qloo answer is ever stored in the site. The server serves its private recording.
(() => {
  const box = document.getElementById("r-live");
  if (!box) return;
  const e = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const sec = (h, p) => (p ? `<h2>${e(h)}</h2><p>${p}</p>` : "");
  fetch("https://knos.onrender.com/api/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ idea: box.dataset.idea }) })
    .then((r) => (r.ok ? r.json() : null))
    .then((r) => {
      if (!r) return;
      const g = r.gap || {}, t = r.terms, who = r.who || {};
      const cities = (r.cities || []).map((c) => c && c.name).filter(Boolean).slice(0, 5);
      const where = t && t.city ? `Launch in ${e(t.city)}: ${e(t.target)} pre-orders. ${e(t.rule || "")}`
        : `No launch city: Qloo gave no heatmap for this idea, so pre-orders cannot open.${cities.length ? ` The cities Qloo named: ${e(cities.join(", "))}.` : ""}`;
      const aud = [String(who.top_age || "").replace(/_/g, " "), who.top_gender].filter(Boolean).join(", ");
      const rej = (g.rejected || []).map((o) => `${e(o.name)} (${e(o.code)}: ${e(o.why)})`).join("; ");
      const flip = String((g.flip && g.flip.said) || "").replace(/^What would flip this verdict: /, "");
      const head = g.headline && g.headline.said ? `<p class="fine">${e(g.headline.said)}</p>` : "";
      box.insertAdjacentHTML("afterbegin", sec("What does Qloo say beside the model alone?", g.sentence ? e(g.sentence) : "") + head +
        sec("Where would it launch?", where) + sec("Who wants it?", aud ? `Qloo reads ${e(aud)} as the core audience.` : "") +
        sec("What would flip this verdict?", flip ? e(flip[0].toUpperCase() + flip.slice(1)) : "") + sec("What did Knos reject?", rej ? rej + "." : "") +
        `<p class="fine">Read from the app's server, ${e(r.made ? "recorded " + String(r.made).slice(0, 10) : "today")}.</p>`);
    })
    .catch(() => {});
})();
