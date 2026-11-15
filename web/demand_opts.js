// The Qloo demand families' controls (knos.qloo_families): ONE plain control per family, the rest under "Advanced".
// The same file runs in the app (apps/wanted static/); web/ keeps a copy for the old one-page app, not published.
// apps/wanted/tests/test_families.py keeps the two identical.
//   KnosDemand.mount(el, base)   draws the controls into el; Advanced is filled from base + /api/demand/fields when opened
//   KnosDemand.values(el)        the options as the API, /mcp and `knos demand` name them (only what is set)
//   KnosDemand.answers(rep, base) the families' answers of a report, as short HTML, each with its Qloo source
//   KnosDemand.src(base, hash, n) the link from a Qloo-derived value to its trace: the redacted request, the result
//                                excerpt and the limit (/trace.html?hash=...#call-n); every [data-qloo] holds one
(function () {
  "use strict";
  const AGES = ["24_and_younger", "25_to_29", "30_to_34", "35_to_44", "45_to_54", "55_and_older"];
  const KINDS = [["", "as the idea says"], ["film", "film"], ["tv", "TV show"], ["book", "book"], ["person", "person"], ["artist", "artist"],
    ["brand", "brand"], ["podcast", "podcast"], ["game", "video game"], ["place", "place"], ["destination", "destination"]];
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const opt = (v, l, sel) => `<option value="${esc(v)}"${sel ? " selected" : ""}>${esc(l)}</option>`;
  const PLAIN = new Set(["age", "gender", "hide_leader", "popularity_max", "near", "radius", "price_level", "references_brand", "product_kind",
    "year_min", "year_max", "lookup", "entity_id", "qloo"]);

  function mount(el, base) {
    if (!el || el.dataset.mounted) return;
    el.dataset.mounted = "1";
    const id = (n) => `${el.id}-${n}`;
    el.innerHTML = `<fieldset class="fam"><legend>Demand options (Qloo)</legend>
      <div class="famrow"><span class="famq">Who</span>
        <label class="sr" for="${id("age")}">Age</label><select id="${id("age")}" data-f="age">${opt("", "any age")}${AGES.map((a) => opt(a, a.replace(/_/g, " "))).join("")}</select>
        <label class="sr" for="${id("gender")}">Gender</label><select id="${id("gender")}" data-f="gender">${opt("", "any gender")}${opt("female", "female")}${opt("male", "male")}</select></div>
      <div class="famrow"><span class="famq">Gaps</span>
        <label class="chk"><input type="checkbox" data-f="hide_leader"> hide leaders</label>
        <label class="chk"><input type="checkbox" data-f="popularity_max" data-on="0.5"> niche only</label></div>
      <div class="famrow"><span class="famq">Where</span>
        <label class="sr" for="${id("near")}">City or region</label><input id="${id("near")}" data-f="near" maxlength="80" placeholder="city or region">
        <label class="sr" for="${id("radius")}">Radius</label><select id="${id("radius")}" data-f="radius">${opt("", "any radius")}${[500, 2000, 5000, 20000, 50000].map((m) => opt(m, m >= 1000 ? m / 1000 + " km" : m + " m")).join("")}</select></div>
      <div class="famrow"><span class="famq">Price tier</span>
        <label class="sr" for="${id("price")}">Price tier</label><select id="${id("price")}" data-f="price_level">${opt("", "any")}${[1, 2, 3, 4].map((p) => opt(p, "$".repeat(p))).join("")}</select></div>
      <div class="famrow"><span class="famq">Who serves it</span>
        <label class="sr" for="${id("brand")}">A brand that serves or stocks it</label><input id="${id("brand")}" data-f="references_brand" maxlength="80" placeholder="a brand, e.g. Whole Foods"></div>
      <div class="famrow"><span class="famq">Product kind</span>
        <label class="sr" for="${id("kind")}">Product kind</label><select id="${id("kind")}" data-f="product_kind">${KINDS.map(([v, l]) => opt(v, l)).join("")}</select>
        <label class="sr" for="${id("y0")}">From year</label><input id="${id("y0")}" data-f="year_min" inputmode="numeric" maxlength="4" placeholder="from year" class="yr">
        <label class="sr" for="${id("y1")}">To year</label><input id="${id("y1")}" data-f="year_max" inputmode="numeric" maxlength="4" placeholder="to year" class="yr"></div>
      <div class="famrow"><span class="famq">Look up</span>
        <label class="sr" for="${id("look")}">Paste a Qloo id or a place</label><input id="${id("look")}" data-f="lookup_any" maxlength="120" placeholder="paste an id or a place"></div>
      <details class="famadv"><summary>Advanced</summary><div class="famgrid" data-adv></div></details></fieldset>`;
    const adv = el.querySelector("details.famadv");
    adv.addEventListener("toggle", async () => {
      const box = adv.querySelector("[data-adv]");
      if (!adv.open || box.dataset.ready) return;
      box.dataset.ready = "1";
      box.textContent = "Loading the options…";
      try {
        const spec = await fetch((base || "") + "/api/demand/fields").then((r) => r.json());
        box.innerHTML = Object.entries(spec.families).map(([f, fam]) => {
          const rows = fam.fields.filter((x) => !PLAIN.has(x.name)).map((x) => `<label>${esc(x.name.replace(/_/g, " "))}
            <input data-f="${esc(x.name)}" data-kind="${esc(x.kind)}" placeholder="${esc(String(x.example))}" title="${esc(x.help)} (Qloo ${esc(x.qloo)})" maxlength="200"></label>`).join("");
          return rows ? `<div class="famset"><b>${esc(f)} ${esc(fam.question)}</b>${rows}</div>` : "";
        }).join("") + `<div class="famset"><b>F8 Anything else</b><label>qloo (PARAM=VALUE, one per line)
          <textarea data-f="qloo" rows="2" placeholder="bias.trends=high"></textarea></label></div>`;
      } catch (e) { box.textContent = "The options could not be read: " + e.message; }
    });
  }

  function values(el) {
    const out = {};
    if (!el) return out;
    for (const c of el.querySelectorAll("[data-f]")) {
      const f = c.dataset.f;
      let v = c.type === "checkbox" ? (c.checked ? (c.dataset.on || true) : "") : String(c.value || "").trim();
      if (v === "" || v == null) continue;
      if (f === "lookup_any") {                     // a pasted Qloo id is looked up by id, anything else by name
        if (/^[0-9A-Fa-f]{8}-[0-9A-Fa-f-]{27}$/.test(v)) out.entity_id = v; else { out.lookup = v; out.lookup_types = "urn:entity:locality,urn:entity:place,urn:entity:brand"; }
        continue;
      }
      if (f === "qloo") {
        const q = {};
        for (const line of v.split(/\n|;/)) { const [k, ...rest] = line.split("="); if (k.trim() && rest.length) q[k.trim()] = rest.join("=").trim(); }
        if (Object.keys(q).length) out.qloo = q;
        continue;
      }
      const kind = c.dataset.kind || "";
      if (["year_min", "year_max", "radius"].includes(f) || kind === "int") v = parseInt(v, 10);
      else if (f === "popularity_max" || kind === "float") v = parseFloat(v);
      else if (kind === "bool") v = /^(1|true|yes|on)$/i.test(v);
      if (typeof v === "number" && Number.isNaN(v)) continue;
      out[f] = v;
    }
    return out;
  }

  function src(base, hash, n) {
    if (!hash) return "";
    const href = (base || "") + "/trace.html?hash=" + encodeURIComponent(hash) + (n ? "#call-" + encodeURIComponent(n) : "");
    return ` <a class="qsrc small" data-trace href="${esc(href)}" target="_blank" rel="noopener" title="The Qloo request, its result and its limit">source</a>`;
  }

  function answers(rep, base) {
    const fam = (rep && rep.families) || {};
    const keys = Object.keys(fam).filter((k) => /^F\d$/.test(k));
    if (!keys.length) return "";
    const line = (k, a) => {
      const names = (a.answer || a.places || []).map((x) => x.name).filter(Boolean).slice(0, 5);
      const hot = (a.hot || []).map((h) => h.geohash).filter(Boolean).slice(0, 4);
      const byid = a.by_id && (a.by_id.answer || [])[0];
      const said = names.length ? names.join(", ") : hot.length ? "hot areas " + hot.join(", ") : byid ? `${byid.name} (${byid.type})` : "nothing under these options";
      return `<li data-qloo><b>${esc(a.question || k)}</b>: ${esc(said)}${src(base, rep.hash, a.call)}</li>`;
    };
    const g = rep.grounding || {};
    return `<div class="famans"><h4>Qloo's answers to your options</h4><ul class="small">${keys.map((k) => line(k, fam[k])).join("")}</ul>` +
      (Object.keys(g).length ? `<p class="small muted" data-qloo>Grounding (Qloo): ${esc([g.audience, (g.cities || []).join(", "), g.price_tier, (g.comparables || []).join(", ")].filter(Boolean).join(" · "))}${src(base, rep.hash)}</p>` : "") + "</div>";
  }

  window.KnosDemand = { mount, values, answers, src };
})();
