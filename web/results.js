// A result page's Qloo part: on load, only what the app's server recorded for this idea (GET /api/recorded), labelled
// recorded with its day. A page that opens never asks Qloo: a crawler, a preview or a sitemap bot cost no call. A live
// check runs only from the reader's own press of "Check it live now".
(() => {
  const box = document.getElementById("r-live");
  if (!box) return;
  const APP = "https://knos.onrender.com";
  const e = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const sec = (h, p) => (p ? `<h2>${e(h)}</h2><p>${p}</p>` : "");
  const show = (r, when) => {
    const g = r.gap || {}, t = r.terms, who = r.who || {};
    const cities = (r.cities || []).map((c) => c && c.name).filter(Boolean).slice(0, 5);
    const where = t && t.city ? `Launch in ${e(t.city)}: ${e(t.target)} pre-orders. ${e(t.rule || "")}`
      : `No launch city: Qloo gave no heatmap for this idea, so pre-orders cannot open.${cities.length ? ` The cities Qloo named: ${e(cities.join(", "))}.` : ""}`;
    const aud = [String(who.top_age || "").replace(/_/g, " "), who.top_gender].filter(Boolean).join(", ");
    const rej = (g.rejected || []).map((o) => `${e(o.name)} (${e(o.code)}: ${e(o.why)})`).join("; ");
    const flip = String((g.flip && g.flip.said) || "").replace(/^What would flip this verdict: /, "");
    const head = g.headline && g.headline.said ? `<p class="fine">${e(g.headline.said)}</p>` : "";
    return `<p class="fine" data-recorded="${when === "live" ? "no" : "yes"}">${when === "live" ? "Checked live just now." : `Recorded ${e(String(r.made || "").slice(0, 10) || "earlier")}: not a live answer.`}</p>` +
      sec("What does Qloo say beside the model alone?", g.sentence ? e(g.sentence) : "") + head +
      sec("Where would it launch?", where) + sec("Who wants it?", aud ? `Qloo reads ${e(aud)} as the core audience.` : "") +
      sec("What would flip this verdict?", flip ? e(flip[0].toUpperCase() + flip.slice(1)) : "") + sec("What did Knos reject?", rej ? rej + "." : "");
  };
  const out = document.createElement("div");
  const live = document.createElement("button");
  live.type = "button"; live.className = "k-chip"; live.textContent = "Check it live now";
  live.addEventListener("click", () => {
    live.disabled = true; live.textContent = "Asking Qloo…";
    fetch(`${APP}/api/check`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ idea: box.dataset.idea }) })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((r) => { out.innerHTML = show(r, "live"); live.remove(); })
      .catch((err) => { live.disabled = false; live.textContent = "Check it live now"; out.insertAdjacentHTML("beforeend", `<p class="fine" role="alert">Not answered: ${e(err.message)}</p>`); });
  });
  box.prepend(out, live);
  fetch(`${APP}/api/recorded?idea=${encodeURIComponent(box.dataset.idea || "")}`)
    .then((r) => (r.ok ? r.json() : null))
    .then((r) => { out.innerHTML = r ? show(r, "recorded") : `<p class="fine" data-recorded="none">No recorded answer for this idea.</p>`; })
    .catch(() => { out.innerHTML = `<p class="fine" data-recorded="none">No recorded answer for this idea.</p>`; });
})();
