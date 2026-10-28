// The one box of both front doors (web/brand/hero.html): a DOI, an arXiv id or an idea in, Qloo's demand verdict out,
// drawn as one card: open or refuse, who, where (on a map), and the price tier, each part linked to the Qloo call it
// came from (the app's /trace.html: the redacted request, the result excerpt and the limit). A paper goes through the
// crossing (POST /api/cross: the paper read, its product named, then the check); an idea straight to the check
// (POST /api/check). Nothing here is estimated: an empty part says what Qloo did not answer.
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
  const src = (hash, n) => hash ? ` <a class="k-src" href="${esc(API)}/trace.html?hash=${encodeURIComponent(hash)}${n ? "#call-" + encodeURIComponent(n) : ""}" target="_blank" rel="noopener" title="The Qloo request, its result and its limit">source</a>` : "";
  const post = async (path, body) => {
    const r = await fetch(API + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.message || j.error || `the server answered ${r.status}`);
    return j;
  };
  const get = async (path) => { const r = await fetch(API + path); if (!r.ok) throw new Error(`the server answered ${r.status}`); return r.json(); };
  // a map's tiles are asked for when the map comes into view (a card below the screen, or folded, asks for none)
  const tileIO = "IntersectionObserver" in window ? new IntersectionObserver((es) => { for (const e of es) if (e.isIntersecting) {
    tileIO.unobserve(e.target); for (const i of e.target.querySelectorAll("img[data-src]")) { i.src = i.dataset.src; i.removeAttribute("data-src"); } } }) : null;
  new MutationObserver(() => { for (const m of slot.querySelectorAll(".k-osm:not([data-watched])")) { m.dataset.watched = "";
    if (tileIO) tileIO.observe(m); else for (const i of m.querySelectorAll("img[data-src]")) i.src = i.dataset.src; } }).observe(slot, { childList: true, subtree: true });
  // motion (sweep M1.md 4.3 and 4.7): one move per change, transform and opacity only; with reduced motion nothing moves
  const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const SPRING = "linear(0,.054,.181,.339,.499,.644,.766,.862,.933,.982,1.013,1.03,1.038,1.038,1.034,1.029,1.023,1.017,1.012,1.007,1)";
  const busy = (on) => {                 // P1: the button keeps its box; its label leaves upward and a spinner springs in where it was
    const label = go.querySelector("span:not(.k-spin)") || go;
    if (!on) { go.innerHTML = "<span>Check demand</span>"; go.style.minWidth = ""; return; }
    go.style.minWidth = `${go.offsetWidth}px`;
    const swap = () => { go.innerHTML = still() ? "<span>Checking</span>" : '<span class="k-spin" aria-hidden="true" style="display:inline-block;vertical-align:middle"></span><span class="k-sr">Checking</span>';
      if (!still()) go.firstChild.animate([{ opacity: 0, scale: 0.6 }, { opacity: 1, scale: 1 }], { duration: 240, easing: SPRING }); };
    if (still() || !label.animate) return swap();
    label.animate([{ opacity: 1, translate: "0 0" }, { opacity: 0, translate: "0 -4px" }], { duration: 120, easing: "cubic-bezier(.4,0,1,1)" }).finished.then(swap, swap);
  };
  const slide = (sw, to, was) => {      // P2: the indicator rides to the pressed tab, its leading edge stretched ahead
    let i = sw.querySelector("i");
    if (!i) { i = document.createElement("i"); i.setAttribute("aria-hidden", "true"); sw.prepend(i); }
    const from = i.offsetWidth ? i.offsetLeft : (was || to).offsetLeft;
    Object.assign(i.style, { left: `${to.offsetLeft}px`, width: `${to.offsetWidth}px` });
    const d = to.offsetLeft - from;
    if (!d || still() || !i.animate) return;
    i.style.transformOrigin = d > 0 ? "left" : "right";
    i.animate([{ translate: `${-d}px 0`, scale: "1 1" }, { offset: 0.5, scale: `${1 + Math.abs(d) / to.offsetWidth * 0.3} 1` }, { translate: "0 0", scale: "1 1" }], { duration: 320, easing: SPRING });
  };
  const said = (t) => { slot.innerHTML = `<p class="k-status" role="status"><span class="k-spin" aria-hidden="true"></span>${esc(t)}</p>`; };

  async function crossing(ref) {
    const j = await post("/api/cross", { ref });
    let since = 0;
    for (let i = 0; i < 240; i++) {
      const p = await get(`/api/cross?id=${encodeURIComponent(j.id)}&since=${since}`);
      since = p.total ?? since;
      const last = (p.steps || []).at(-1);
      if (last && last.title) said(last.title);
      if (p.status === "error") throw new Error(p.error || "the crossing stopped");
      if (p.report) return get("/api/report?hash=" + encodeURIComponent(p.report));
      if (p.status !== "running") throw new Error("the crossing ended without a demand check");
      await new Promise((ok) => setTimeout(ok, 500));
    }
    throw new Error("the crossing took too long");
  }

  // the launch cities on OpenStreetMap's tiles, at the closest zoom that holds them all; Qloo's heatmap points as
  // light rings. Tiles are asked only once a result is drawn (the first screen asks no host but its own)
  function map(cities, where = []) {
    const pts = cities.filter((c) => Number.isFinite(c.lat) && Number.isFinite(c.lon));
    if (!pts.length) return `<p class="k-none">Qloo named the cities but no coordinates came with them.</p>`;
    const W = 320, H = 200, T = 256;
    const px = (lat, lon, z) => { const n = T * 2 ** z, r = (lat * Math.PI) / 180;
      return [((lon + 180) / 360) * n, ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * n]; };
    let z = 12;
    for (; z > 1; z--) {
      const xy = pts.map((c) => px(c.lat, c.lon, z)), xs = xy.map((q) => q[0]), ys = xy.map((q) => q[1]);
      if (Math.max(...xs) - Math.min(...xs) < W - 48 && Math.max(...ys) - Math.min(...ys) < H - 48) break;
    }
    const xy = pts.map((c) => px(c.lat, c.lon, z)), xs = xy.map((q) => q[0]), ys = xy.map((q) => q[1]);
    const cx = (Math.max(...xs) + Math.min(...xs)) / 2, cy = (Math.max(...ys) + Math.min(...ys)) / 2, x0 = cx - W / 2, y0 = cy - H / 2;
    const n = 2 ** z, tiles = [];
    for (let tx = Math.floor(x0 / T); tx <= Math.floor((x0 + W) / T); tx++)
      for (let ty = Math.max(0, Math.floor(y0 / T)); ty <= Math.min(n - 1, Math.floor((y0 + H) / T)); ty++)
        tiles.push(`<img class="k-tile" alt="" data-src="https://tile.openstreetmap.org/${z}/${((tx % n) + n) % n}/${ty}.png" style="left:${(tx * T - x0).toFixed(0)}px;top:${(ty * T - y0).toFixed(0)}px">`);
    const heat = where.filter((w) => Number.isFinite(w.lat) && Number.isFinite(w.lon)).map((w) => { const [x, y] = px(w.lat, w.lon, z);
      return `<span class="k-heat" style="left:${(x - x0).toFixed(0)}px;top:${(y - y0).toFixed(0)}px"></span>`; }).join("");
    const pins = pts.map((c, i) => `<span class="k-pin" title="${esc(c.name)}" style="left:${(xy[i][0] - x0).toFixed(0)}px;top:${(xy[i][1] - y0).toFixed(0)}px">${i + 1}</span>`).join("");
    return `<div class="k-osm" role="group" aria-label="Launch cities on a map: ${esc(pts.map((c) => c.name).join(", "))}">${tiles.join("")}${heat}${pins}` +
      `<a class="k-osm-credit" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap</a></div>` +
      (pts.some((c) => c.coords_from === "Wikidata") ? `<p class="k-fine">Coordinates: Wikidata</p>` : "");
  }

  // the answer Claude gave alone for the same idea (the published table behind "With and without Qloo"), beside Knos's
  let table = null;
  const norm = (t) => String(t || "").toLowerCase().replace(/\s+/g, " ").trim();
  async function claudeAlone(idea, mine) {
    table = table || await get("/api/qloo-diff").catch(() => ({ rows: [] }));
    const row = (table.rows || []).find((x) => norm(x.idea) === norm(idea));
    const c = row && row.claude;
    if (!c) return `<p class="k-none">Claude was not asked about this idea alone.</p>`;
    const side = (who, v) => `<div><h4>${who}</h4><p class="k-big">${esc((WORD[v.verdict] || [v.verdict || "-"])[0])}</p>
      <p>${esc(v.audience || "no audience")}</p><p data-cities>${esc((v.cities || []).join(", ") || "no cities")}</p><p>${esc(v.tier ? "price tier " + v.tier : "no price tier")}</p></div>`;
    return `<div class="k-vs">${side("Claude alone", c)}${side("Knos with Qloo", mine)}</div>${c.why ? `<p class="k-fine">Claude: ${esc(c.why)}</p>` : ""}`;
  }

  // the parts of the card that read Qloo's answers already in the report (no new call): each value names its call
  // a Qloo label as the card shows it: title case, and no "(Lifestyle Preferences ...)" type suffix
  const qlabel = (s) => String(s || "").replace(/\s*\(Lifestyle Preferences[^)]*\)/gi, "").trim().replace(/(^|[\s/-])([a-z])/g, (m, a, b) => a + b.toUpperCase());
  let traceOf = "";
  const val = (n, html) => `<li data-call="${esc(n ?? "")}"><a class="k-val" href="${esc(API)}/trace.html?hash=${encodeURIComponent(traceOf)}#call-${esc(n ?? "")}" target="_blank" rel="noopener">${html}</a></li>`;
  function more(r) {
    const h = r.hash, ids = Object.fromEntries((r.matches || []).filter((m) => m && m.id).map((m) => [m.id, m.name]));
    traceOf = h || "";
    // a word of at least 4 letters, its plural folded: the words of the idea, its matched products and Qloo's tags for it
    const stems = (t) => String(t || "").toLowerCase().match(/[a-z0-9]{4,}/g)?.map((w) => w.replace(/(ies|es|s)$/, "")) || [];
    const own = new Set([r.idea, ...Object.values(ids), ...(r.tags || []).map((t) => (t && t.name) || t)].flatMap(stems));
    const tied = (x) => stems(x && x.name).some((w) => own.has(w));
    const vs = r.versus || null, persona = (r.persona || []).filter(tied), ladder = r.ladder || [],
      rec = ((r.recommended && r.recommended.items) || []).filter(tied);
    const parts = [];
    if (vs && (vs.whitespace || []).length) parts.push(`<section class="k-part" data-part="whitespace" data-qloo><h3>Room against ${esc(vs.leader)}</h3><ul class="k-vals">${
      vs.whitespace.slice(0, 6).map((w) => val(vs.src, esc(qlabel(w)))).join("")}</ul><p class="k-fine">overlap ${Math.round((vs.overlap || 0) * 100)}%${chip("qloo", `call-${vs.src}`)}</p>${src(h, vs.src)}</section>`);
    if (persona.length) parts.push(`<section class="k-part" data-part="persona" data-qloo><h3>Taste persona</h3><ul class="k-vals">${
      persona.slice(0, 6).map((t) => val(t.src, esc(qlabel(t.name)))).join("")}</ul>${src(h, persona[0].src)}</section>`);
    if (ladder.length) parts.push(`<section class="k-part" data-part="ladder" data-qloo><h3>Brand ladder</h3><ol class="k-vals">${
      ladder.slice(0, 6).map((b) => val(b.src, `${esc(b.name)} <span class="k-fine">${esc(Number(b.affinity || 0).toFixed(2))}</span>`) .replace("</a></li>", `</a>${chip("qloo", `call-${b.src}`)}</li>`)).join("")}</ol>${src(h, ladder[0].src)}</section>`);
    if (rec.length) parts.push(`<section class="k-part" data-part="recommendations" data-qloo><h3>Next to it</h3><ul class="k-vals">${
      rec.slice(0, 6).map((x) => val(r.recommended.src, esc(x.name))).join("")}</ul>${src(h, r.recommended.src)}</section>`);
    return parts.join("");
  }
  // the leader's weekly trend from /v2/trending (check.py _trend): its direction and the last week Qloo has
  const trendLine = (r) => { const t = r.trend || {};
    return t.data_through && t.direction ? `<p class="k-fine" data-part="trend">Trend of ${esc(t.entity || "the leader")}: ${esc(t.direction)}, data through ${esc(t.data_through)}${src(r.hash, t.src)}</p>` : ""; };
  // the same card with every Qloo answer removed, by the check's rule (check.py decide: no live Qloo evidence, no
  // verdict): no launch city, no pre-order target, and pre-orders cannot open. From the card's own data, offline.
  const without = (r) => `<article class="k-card k-unknown" data-verdict="CANNOT_DECIDE" data-without-qloo data-not-prose>
  <header class="k-card-head"><p class="k-kick">${esc(r.idea || "")} · without Qloo</p><h2 class="k-verdict">${esc(WORD.CANNOT_DECIDE[0])}</h2>
  <p class="k-why">With every Qloo answer removed there is no launch city and no pre-order target, so pre-orders cannot open.</p>
  <button type="button" class="k-chip" data-without aria-pressed="true">Without Qloo</button></header></article>`;
  slot.addEventListener("click", (ev) => {        // With Qloo / Model alone: the panel beside the card's own answer
    const v = ev.target instanceof Element && ev.target.closest("[data-view]");
    if (!v) return;
    const k = v.closest(".k-card"), model = v.dataset.view === "model";
    const was = k.querySelector('[data-view][aria-pressed="true"]');
    k.querySelectorAll("[data-view]").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.view === v.dataset.view)));
    slide(v.closest(".k-switch"), v, was);
    k.querySelector("[data-model-panel]")?.toggleAttribute("hidden", !model);
  });
  slot.addEventListener("click", (ev) => {
    const b = ev.target instanceof Element && ev.target.closest("[data-without]");
    if (!b || !slot.last) return;
    slot.innerHTML = b.getAttribute("aria-pressed") === "true" ? card(slot.last) : without(slot.last);
    slot.querySelector("[data-without]")?.focus();
  });
  // every Qloo call behind the card: what it asked, how long it took and which part of the card it fed
  // the lists and the calls panel are styled when a card first needs them: the first screen's stylesheet stays within its
  // weight (tests/web/perf.mjs)
  // the card's own stylesheet (web/brand/card.css, beside tokens.css): asked for once, before the first card is drawn
  let cardSheet = null;
  const cardCss = () => cardSheet || (cardSheet = new Promise((done) => {
    const tokens = document.querySelector('link[rel="stylesheet"][href*="tokens.css"]');
    if (document.getElementById("k-card-sheet") || document.querySelector('link[rel="stylesheet"][href$="card.css"]')) return done();   // in the page's head: there already
    // both front doors write tokens.css into the page (server.inline_css, scripts/inline_css.py): the app's static path, else beside the page
    let href = null;
    try { href = tokens ? tokens.href.replace(/tokens\.css(\?.*)?$/, "card.css") : location.pathname.startsWith("/app") ? "/static/brand/card.css" : new URL("brand/card.css", document.baseURI).href; } catch { href = null; }
    if (!href) return done();                // a page with no address of its own (a test's): the card is drawn without it
    const l = Object.assign(document.createElement("link"), { rel: "stylesheet", id: "k-card-sheet", href });
    l.onload = l.onerror = () => done();
    document.head.append(l);
  }));
  const style = () => { if (document.getElementById("k-card-css")) return;
    document.head.insertAdjacentHTML("beforeend", `<style id="k-card-css">.k-vals{margin:0;padding-left:1.1em}.k-vals li{margin:0 0 4px}.k-val{color:inherit;text-decoration:none}.k-val:hover{text-decoration:underline}.k-calls{margin:var(--sp-3) var(--sp-5);font-size:var(--s-1)}.k-calls ol{margin:var(--sp-2) 0 0;padding-left:1.1em}.k-calls li{margin:0 0 4px;overflow-wrap:anywhere}.k-switch{display:inline-flex;gap:4px;margin-left:6px}.k-model{margin:var(--sp-3) var(--sp-5)}.k-vs-t{width:100%;border-collapse:collapse;font-size:var(--s0)}.k-vs-t th,.k-vs-t td{text-align:left;vertical-align:top;padding:6px 8px;border-top:1px solid var(--line);overflow-wrap:anywhere}.k-vs-t mark{background:color-mix(in srgb,var(--accent) 22%,transparent);color:inherit;border-radius:3px;padding:0 2px}.k-timeline{margin:var(--sp-2) 0 0}.k-timeline ol{margin:4px 0 0;padding-left:1.4em;font-size:var(--s-1);max-height:12em;overflow:auto}.k-timeline li{overflow-wrap:anywhere}.k-schip{display:inline-block;height:14px;padding:0 5px;margin-left:4px;border:1px solid var(--line);border-radius:7px;font:600 10px/12px var(--text);vertical-align:middle;color:var(--muted);text-decoration:none}.k-schip:hover{color:var(--fg)}.k-mine{margin-top:var(--sp-4)}.k-mine h3{font-size:var(--s1);margin:0 0 4px}.k-mine ul{margin:4px 0;padding-left:1.1em}.k-mine li{overflow-wrap:anywhere}</style>`); };
  function calls(r) {
    style();
    const fed = {}, add = (n, part) => { if (n != null) (fed[n] ||= new Set()).add(part); };
    (r.cities || []).forEach((c) => add(c.src, "launch cities"));
    (r.where || []).forEach((c) => add(c.src, "map"));
    add(r.who && r.who.src, "who wants it"); add(r.price && r.price.src, "price tier");
    ((r.also_love && r.also_love.domains) || []).forEach((d) => add(d.src, "they also love"));
    (r.persona || []).forEach((t) => add(t.src, "taste persona")); (r.ladder || []).forEach((b) => add(b.src, "brand ladder"));
    add(r.versus && r.versus.src, "room against the leader"); add(r.recommended && r.recommended.src, "next to it");
    (r.cities || []).filter((c) => (c.because || []).length).forEach((c) => add(c.src, "because"));
    const words = String(r.idea || "").match(/[^\W\d_][\w-]*/gu) || [];
    const own = (v) => String(v).replace(/[^\W\d_][\w-]*/gu, (w) => words.find((x) => x.toLowerCase() !== w.toLowerCase() && x.toLowerCase().startsWith(w.toLowerCase()) && x.length - w.length <= 2) || w);
    const rows = (Array.isArray(r.calls) ? r.calls : []).map((c) => { const p = c.params || {};
      const keys = Object.keys(p).filter((k) => p[k] != null && p[k] !== "").map((k) => `${k}=${own(String(p[k])).slice(0, 40)}`).join(", ");
      return `<li data-call="${esc(c.n)}"><a href="${esc(API)}/trace.html?hash=${encodeURIComponent(r.hash || "")}#call-${esc(c.n)}" target="_blank" rel="noopener">#${esc(c.n)}</a> ${
        esc(c.call || "")} <span class="k-fine">${esc(keys)}</span> · ${Number.isFinite(c.ms) ? `${esc(c.ms)} ms` : `recorded ${esc(String(r.made || c.at || "").slice(0, 10))}`} · ${c.cached ? "cached" : "live"}${c.error ? " · failed" : ""} · ${esc([...(fed[c.n] || [])].join(", ") || String(c.effect || "").slice(0, 60) || "the verdict")}${r.signals ? ` · <span data-role="${(r.signals.decides || []).includes(c.n) ? "decides" : "context"}">${(r.signals.decides || []).includes(c.n) ? "decides" : "context"}</span>` : ""}</li>`; });
    const first = (Array.isArray(r.calls) && r.calls[0] && r.calls[0].n) || 1;
    return rows.length ? `<details class="k-calls" data-part="calls"><summary>Qloo calls (${rows.length})</summary><p class="k-fine">${chip("qloo", `call-${first}`)}</p><ol>${rows.join("")}</ol></details>` : "";
  }

  // a number's source as a chip at most 16 px tall (Qloo, rule, model or chain), opening its row of the result's receipts
  let rcpt = "";
  const chip = (kind, row) => rcpt ? ` <a class="k-schip" data-src="${esc(kind)}" href="${esc(API)}/receipts/${esc(rcpt)}#${esc(row)}" target="_blank" rel="noopener" aria-label="Source: ${esc(kind)}, ${esc(row.replace("-", " "))}">${esc({ qloo: "Qloo", rule: "rule", model: "model", chain: "chain" }[kind])}</a>` : "";
  // Qloo's concentration index of a launch city, 0 to 100, as Qloo's page defines it ("each row's place among the ...
  // fetched at this scale, rescaled"): each metro's mean affinity over Qloo's heatmap cells in it (the terms' metros,
  // apps/wanted metros.stats), rescaled over the card's metros, the highest 100 and the lowest 0
  const indexer = (ms) => { const a = ms.map((m) => m.affinity).filter(Number.isFinite), lo = Math.min(...a), hi = Math.max(...a);
    return (m) => !Number.isFinite(m && m.affinity) ? null : hi > lo ? Math.round((100 * (m.affinity - lo)) / (hi - lo)) : 100; };
  const INDEX = `<a href="https://qloo.com/use-cases/expand-to-a-new-market" target="_blank" rel="noopener">Qloo concentration index (0-100)</a>`;
  // the reader's own call, first: "You said <city>. Qloo says <city>." with both cities' concentration indexes
  const yourCall = (guess, terms, cities) => {
    if (!terms) return `<p class="k-terms" data-guess>You said ${esc(guess)}. Qloo sets no launch city for this idea.</p>`;
    const g = guess.toLowerCase().split(",")[0].trim(), mine = cities.find((c) => c.name.toLowerCase().includes(g)), top = cities.find((c) => c.name === terms.city);
    const diff = mine && top && mine.index != null && top.index != null ? top.index - mine.index : null;
    return `<p class="k-terms" data-guess${diff == null ? "" : ` data-diff="${diff}"`}>You said ${esc(guess)}. Qloo says ${esc(terms.city)}.${diff == null
      ? ` Qloo's map has no cells in ${esc(guess)} for this idea.`
      : mine === top ? ` The same city: index ${esc(top.index)}.` : ` Qloo concentration index: ${esc(top.index)} against ${esc(mine.index)} for ${esc(mine.name)}, ${esc(Math.abs(diff))} ${diff >= 0 ? "higher" : "lower"}.`}</p>`;
  };
  // the launch terms a card draws (apps/wanted metros.launch_terms): a city only when Qloo matched a product to the idea
  const termsOf = (r) => r && r.terms && r.terms.city && (r.matches || []).length ? r.terms : null;
  const cityList = (r) => { const t = termsOf(r);
    const ms = (t && t.metros) || [], index = indexer(ms);
    const heat = ms.map((m) => ({ name: m.city, lat: m.lat, lon: m.lon, src: (r.where || [])[0]?.src, index: index(m) }));
    heat.sort((x, y) => (y.name === t.city) - (x.name === t.city));
    return heat.slice(0, 5); };
  // the server's lines for a recorded card (apps/wanted signals.gap): the model's city beside Qloo's, then /proof/'s number
  const gapOpen = (r) => { const g = r.gap, h = g && g.headline;
    return g && g.sentence ? `<p class="k-gap" data-part="gap">${esc(g.sentence)}</p>${h ? `<p class="k-fine" data-part="headline"><a href="${esc(h.href)}" rel="noopener">${esc(h.said)}</a></p>` : ""}` : ""; };
  // what would flip the verdict, and each option Knos did not take with its rule's code
  const gapClose = (r) => { const g = r.gap, rej = (g && g.rejected) || [];
    return g && g.flip ? `<p class="k-fine" data-part="flip">${esc(g.flip.said)}</p><p class="k-fine" data-part="rejected">Options Knos rejected: ${rej.length
      ? rej.map((o) => `<span data-reject data-code="${esc(o.code)}">${esc(o.name)} <abbr title="${esc(o.why)}">${esc(o.code)}</abbr></span>`).join("; ")
      : "none, as Qloo offered no city or product to weigh"}.</p>` : ""; };
  // the run's Qloo calls in one line: live, cached, and the time the check took (its own clock, else the calls' sum)
  const callsHead = (r) => { const c = Array.isArray(r.calls) ? r.calls : []; if (!c.length) return "";
    const ms = Number.isFinite(r.elapsed_ms) ? r.elapsed_ms : c.reduce((n, x) => n + (Number.isFinite(x.ms) ? x.ms : 0), 0);
    return `<p class="k-fine" data-part="calls-head">Qloo calls: ${c.filter((x) => !x.cached).length} live, ${c.filter((x) => x.cached).length} cached, ${Math.round(ms).toLocaleString("en-US")} ms</p>`; };
  // before a check runs: the product Qloo matched to this idea, to confirm (Yes runs it; No offers the next 3)
  const confirmCard = (v, ms) => `<article class="k-card k-unknown" data-confirm data-not-prose><header class="k-card-head"><p class="k-kick">${esc(v)}</p>
  <h2 class="k-verdict">Is this what you mean? ${esc(ms[0])}</h2>
  <p data-confirm-row><button type="button" class="k-chip" data-sure>Yes</button> <button type="button" class="k-chip" data-other="${esc(JSON.stringify(ms.slice(1, 4)))}">No</button></p></header></article>`;
  const WORD = { OPEN:["Open for pre-orders", "open"], REFUSE: ["Not yet: pre-orders stay closed", "refuse"], CANNOT_DECIDE: ["Qloo cannot decide this one", "unknown"] };
  const TIERS = ["budget", "mid", "premium", "luxury"];
  const HEALTH = /\b(health\w*|patient\w*|medic\w*|clinic\w*|disease\w*|drug\w*|therap\w*|diagnos\w*|supplement\w*|glucose|diabet\w*)\b/i;
  // the model's own answer for the idea (claude -p, no Qloo, recorded with the card), beside Knos's; what differs is marked
  const modelPanel = (r, terms, who) => {
    const m = r.model_alone;
    if (!m || !m.city) return `<div class="k-model" data-model-panel hidden><p class="k-none" data-model-none>Model-alone answer not recorded for this idea</p></div>`;
    const city = terms ? terms.city : "no launch city", head = (c) => String(c || "").split(/[-,]/)[0].trim().toLowerCase();
    const same = terms && head(m.city) === head(city);
    const cell = (v, diff) => diff ? `<mark>${esc(v)}</mark>` : esc(v);
    return `<div class="k-model" data-model-panel hidden><table class="k-vs-t" data-not-prose><thead><tr><th scope="col"></th><th scope="col">Knos with Qloo</th><th scope="col">Model alone</th></tr></thead><tbody>
      <tr data-row="city"><th scope="row">Launch city</th><td data-knos>${cell(city, !same)}</td><td data-model>${cell(m.city, !same)}</td></tr>
      <tr data-row="who"><th scope="row">Who</th><td data-knos>${cell(who || "Qloo named no audience", true)}</td><td data-model>${cell(m.who || "", true)}</td></tr>
      <tr data-row="why"><th scope="row">Why</th><td data-knos>${esc(terms ? `Qloo's heatmap: the highest lift, ${terms.cells} cells` : "Qloo's map names no launch city")}</td><td data-model>${esc(m.why || "")}</td></tr></tbody></table>
      <p class="k-fine">Model alone: ${esc(m.model || "Claude")}, asked once with no Qloo data, ${esc(String(m.at || "").slice(0, 10))}.${chip("model", "model")}</p></div>`;
  };
  // Qloo cannot answer and no idea it answered shares 2 words with this one (apps/wanted nearest.py): the 3 nearest
  const ideaButtons = (list) => (list || []).map((x) => `<button type="button" class="k-chip" data-q="${esc(x)}">${esc(x)}</button>`).join(" ");
  const options = (r) => `<article class="k-card k-unknown" data-nearest-options data-not-prose>
  <header class="k-card-head"><p class="k-kick">${esc(r.idea || "")}</p><h2 class="k-verdict">Qloo has not answered an idea close to this yet.</h2>${r.qloo_reset ? `<p class="k-why" data-qloo-reset>Its monthly limit resets on ${esc(r.qloo_reset)}.</p>` : ""}
  ${(r.nearest_options || []).length ? `<p class="k-why">The closest ideas it has answered:</p><p>${ideaButtons(r.nearest_options)}</p>` : ""}
  <p class="k-next">A Ready brief needs no Qloo: <a href="${esc(APP)}#projects" data-ready-path>write the brief for this idea</a>.</p></header></article>`;
  function card(r, label) {
    style();
    if (r.nearest_options || (r.qloo_down && !r.stale && !r.nearest)) return options(r);
    const d = r.decision || {}, p = d.plan || {}, h = r.hash;
    rcpt = /^[0-9a-f]{16}/.test(h || "") ? h.slice(0, 16) : "";
    let [word, cls] = WORD[d.verdict] || [String(d.verdict || "No verdict"), "unknown"];
    const who = r.who || {}, age = (p.who?.age || who.top_age || "").replace(/_/g, " ").replace(" and ", " and "), gender = p.who?.gender || who.top_gender || "";
    const segs = (p.who?.segments || (r.audiences || []).filter((a) => a.tied).map((a) => a.name)).filter(Boolean).slice(0, 3).map(qlabel);
    // Qloo's audiences for the idea's own tags (or products), each naming what ties it: none is unrelated
    const wants = (r.who_wants || []).filter((a) => a && a.name && a.tie && a.tie.name).slice(0, 4);
    const terms = termsOf(r);
    // Open needs a launch city: with none, pre-orders cannot open (apps/wanted metros.launch_terms is the one answer)
    if (d.verdict === "OPEN" && !terms && (r.stage !== "verdict" || r.no_map)) [word, cls] = ["Not yet: Qloo sets no launch city for this idea", "refuse"];
    // the one city list of a result: the terms' Census metros, the launch city first (the map, the list, Claude alone, /r/)
    const cities = cityList(r);
    const guess = label ? "" : slot.dataset.guess || "";
    const where = ((r.where || []).length ? r.where : (r.launch || {}).where || []).slice(0, 8), also = (r.also_love && r.also_love.domains) || [];
    const price = r.price || {}, tier = String(price.tier || "").toLowerCase();
    // which product Qloo read the idea as (kit SAFE_USE: ask when that choice changes the result): on a new check the
    // visitor can pick another match, or none of them; the verdict's reason is Knos's rule, apart from Qloo's data
    const lead = r.leader && typeof r.leader === "object" ? r.leader : null, why = (d.reasons || [])[0];
    const empty = !r.nearest && !(age || gender) && !segs.length && !wants.length && !(r.cities || []).length && !cities.length && !tier && !also.length;     // no part answered: one next step, no empty boxes
    if (empty && d.verdict !== "OPEN" && !r.qloo_down) [word, cls] = ["No taste data from Qloo", "unknown"];   // a real empty answer only
    // Qloo not answering (apps/wanted recorded.py): said first, with the sample's last real card when there is one
    const at = (t) => String(t || "").replace("T", " ").slice(0, 16) + " UTC";
    // the card's dated label: what Qloo answered, and when; Qloo's month only here (and on /status/), never on the first screen
    const reset = r.qloo_reset ? ` Qloo's monthly limit resets on ${r.qloo_reset}.` : "";
    const down = r.nearest ? `Qloo has not answered your exact idea yet. Closest idea it has answered: ${r.nearest.idea}, answered ${r.nearest.on}.`
      : r.stale && reset ? `Recorded ${String(r.stale.from || r.made || "").slice(0, 10)}.${reset}` : r.stale ? `Qloo is not answering right now (HTTP ${r.stale.code}). Showing the last real answer from ${at(r.stale.from)}.`
      : r.qloo_down ? `Qloo is not answering right now (HTTP ${r.qloo_down.code}). Try again in a few minutes.` : "";
    const undecided = d.verdict === "CANNOT_DECIDE" || (r.qloo_down && !r.stale);   // nothing to share or launch yet
    const others = (r.matches || []).filter((m) => m && m.name && (!lead || m.id !== lead.id)).slice(0, 3);
    const read = lead ? `<p class="k-read" data-part="match">Read as <b>${esc(lead.name)}</b>${label ? "" : ` · Not it? ${others.map((m) =>
      `<button type="button" class="k-chip" data-pick="${esc(m.name)}">${esc(m.name)}</button>`).join(" ")} <button type="button" class="k-chip" data-none="${
      esc([lead.id, ...others.map((m) => m.id)].filter(Boolean).join(","))}">None of these</button>`}</p>` : "";
    return `<article class="k-card k-${cls}" data-verdict="${esc(d.verdict || "")}" data-not-prose>
  ${gapOpen(r)}
  ${guess ? yourCall(guess, terms, cities) : ""}
  ${down ? `<p class="k-terms" data-qloo-down>${esc(down)}</p>` : ""}${r.nearest && reset ? `<p class="k-fine k-terms" data-qloo-limit-line>${esc(reset.trim())}</p>` : ""}
  <header class="k-card-head"><p class="k-kick">${label ? `<span class="k-real">${esc(label)}</span> · ` : ""}${esc(r.idea || r.label || "")}</p><h2 class="k-verdict" data-part="verdict" data-qloo>${esc(word)}${src(h)}</h2>${callsHead(r)}
  ${terms ? `<p class="k-terms" data-part="terms" data-city="${esc(terms.city)}" data-target="${esc(terms.target)}">Launch in <b>${esc(terms.city)}</b>: ${esc(terms.target)} pre-orders.${chip("rule", "rule-target")} Every pre-order is refunded if the target is missed.</p>${terms.by_population ? `<p class="k-fine" data-part="by-population" data-pop-city="${esc(terms.by_population.city)}" data-pop-target="${esc(terms.by_population.target)}">By population: ${esc(terms.by_population.city)}, ${esc(terms.by_population.target)}.${chip("rule", "rule-population")} By Qloo taste: ${esc(terms.city)}, ${esc(terms.target)}.${chip("rule", "rule-target")}</p>` : ""}` : ""}
  ${r.signals && r.signals.line ? `<p class="k-fine" data-part="signals">${esc(r.signals.line)}</p>` : ""}${gapClose(r)}
  ${read}${why ? `<p class="k-why"><b>Knos rule:</b> ${esc(why)}</p>` : ""}${trendLine(r)}
  ${Array.isArray(r.calls) && r.calls.length ? `<section class="k-timeline" data-timeline aria-live="polite"><p class="k-fine" data-counter>Qloo calls this check: 0 (live 0, cached 0)</p><ol data-rows tabindex="0" aria-label="Qloo calls, as they answered"></ol></section>` : ""}
  ${r.decision ? `<button type="button" class="k-chip" data-without aria-pressed="false">Without Qloo</button>` : ""}
  ${r.decision ? `<span class="k-switch" role="group" aria-label="With Qloo or the model alone"><button type="button" class="k-chip" data-view="qloo" aria-pressed="true">With Qloo</button><button type="button" class="k-chip" data-view="model" aria-pressed="false">Model alone</button></span>` : ""}</header>
  ${r.decision ? modelPanel(r, terms, [age, gender].filter(Boolean).join(", ") || segs.join(", ")) : ""}
  ${empty && r.no_map ? `<p class="k-terms" data-no-map>${esc(r.no_map)}</p>` : ""}
  ${empty && !r.qloo_down ? `<p class="k-next" data-part="next">Qloo has no taste data for this yet. Name who it is for and what it is like, as in "a vegan meal kit for students, like HelloFresh". Science, B2B or lab work: <a href="${esc(API)}/companies">companies mode</a>.</p>
  <form class="k-like" data-like><label>Most like <input name="like" maxlength="80" placeholder="a product or brand you know" aria-label="What is it most like?"></label> <button type="submit">Check</button></form>` : `<div class="k-parts">`}
    ${empty ? "" : `<section class="k-part" data-part="audience" data-qloo><h3>Who wants it</h3>
      ${age || gender ? `<p class="k-big">${esc([age, gender].filter(Boolean).join(", "))}</p>` : `<p class="k-none">Qloo did not answer who.</p>`}
      ${wants.length ? `<ul class="k-wants">${wants.map((a) => `<li><b>${esc(qlabel(a.name))}</b> <span class="k-fine">tied by Qloo ${
        a.tie.kind === "tag" ? "tag" : "product"} ${esc(a.tie.name || "")}${a.tie.via ? `, through ${esc(a.tie.via)}` : ""}</span></li>`).join("")}</ul>`
        : segs.length ? `<p>${esc(segs.join(" · "))}</p>` : ""}${src(h, who.src)}</section>
    ${cities.length ? `<section class="k-part k-where" data-part="cities" data-qloo data-heat="${cities.length}"><h3>Where to launch</h3>
      ${map(cities, where)}<p class="k-fine" data-index-label>${INDEX}</p><ol class="k-cities">${cities.map((c) => `<li><span data-city>${esc(c.name)}</span>${c.index == null ? "" : ` <span class="k-fine" data-index="${esc(c.index)}">${esc(c.index)}</span>`}${c.src != null ? chip("qloo", `call-${c.src}`) : ""}</li>`).join("")}</ol>${src(h, cities[0]?.src)}</section>`
      : r.stage === "verdict" && (r.matches || []).length ? `<p class="k-none" data-pending>Qloo's map is on its way.</p>` : !empty && r.no_map && (r.matches || []).length ? `<p class="k-terms" data-no-map>${esc(r.no_map)}</p>` : ""}
    ${also.length ? `<section class="k-part" data-part="also" data-qloo><h3>They also love</h3>${also.map((d) =>
      `<p class="k-also" data-domain="${esc(d.domain)}"><b>${esc(d.domain === "music" ? "Music" : d.domain === "film" ? "Film" : d.domain)}</b> ${
      d.items.map((x) => esc(x.name)).join(", ")}${src(h, d.src)}</p>`).join("")}</section>` : ""}
    <section class="k-part" data-part="price" data-qloo><h3>Price tier</h3>
      ${tier ? `<p class="k-tier-said" data-price-said>Price tier: ${esc(tier)}</p><ol class="k-tiers" aria-label="Price tier: ${esc(tier)}">${TIERS.map((t) => `<li${t === tier ? ' aria-current="true"' : ""}>${t}</li>`).join("")}</ol>` : `<p class="k-none">Qloo gave no price signal.</p>`}
${src(h, price.src)}</section>
    ${more(r)}
  </div>`}
  ${calls(r)}
  ${r.nearest && (r.nearest_next || []).length ? `<p class="k-terms" data-nearest-next>Other ideas Qloo has answered: ${ideaButtons(r.nearest_next)}</p>` : ""}
  <details class="k-claude" data-claude hidden><summary>Claude alone</summary><div class="k-claude-body" data-claude-body></div></details>
  <footer class="k-card-foot">${rcpt ? `<p class="k-fine"><a href="${esc(API)}/receipts/${esc(rcpt)}" target="_blank" rel="noopener" data-receipts>Receipts</a></p>` : ""}<p class="k-fine">Aggregate taste from Qloo: not causal, not a forecast, not about any one person.${
    HEALTH.test(r.idea || "") ? " Not medical advice: Qloo has no medical demand." : ""}</p>
    ${undecided ? "" : `${d.verdict === "OPEN" ? `<a class="k-cta" href="${esc(APP)}#buy=${esc(h)}">Open pre-orders for it →</a>` : `<a class="k-cta quiet" href="${esc(APP)}#research">Try it with a launch market →</a>`}${/^[0-9a-f]{16}/.test(h || "") ? ` <a class="k-cta quiet" href="${esc(API)}/r/${esc(h.slice(0, 16))}" data-share>Share this result</a>` : ""}`}</footer>
</article>`;
  }

  async function ask(v, extra = {}) {
    v = v.trim();
    if (!extra.exclude && !extra.leader) slot.dataset.ex = "[]";
    if (!v) { q.focus(); return; }
    const { sure, ...send } = extra;
    extra = send;
    go.disabled = true; root.setAttribute("aria-busy", "true"); busy(true);
    if (!sure && !extra.leader && !extra.exclude && !paper(v)) {          // a recorded idea: its matched product first
      const m = await get(`/api/match?idea=${encodeURIComponent(v)}`).catch(() => null);
      if (m && (m.matches || []).length) {
        await cardCss(); slot.dataset.idea = v; slot.innerHTML = confirmCard(v, m.matches);
        go.disabled = false; root.removeAttribute("aria-busy"); busy(false); return;
      }
    }
    const ref = paper(v), t0 = performance.now();
    slot.dataset.guess = (document.getElementById("k-guess")?.value || "").trim().slice(0, 60);
    said(ref ? "Reading the paper…" : "Asking Qloo…");
    try {
      // the verdict card first (verdict, matched product, audience); the map, also-loved and the launch terms follow
      // from the full check, whose Qloo questions the first one already sent
      const r = ref ? await crossing(ref) : await post("/api/check", { idea: v, ...extra, stage: "verdict" });
      await cardCss();
      slot.innerHTML = card(r);
      slot.last = r;
      slot.dataset.idea = v;
      keepMine(r, v);
      delete slot.dataset.past;
      slot.dataset.ms = String(Math.round(performance.now() - t0));
      slot.querySelector(".k-verdict")?.focus?.();
      if (!ref && r.stage === "verdict") {
        const full = await post("/api/check", { idea: v, ...extra }).catch(() => null);
        if (full && slot.dataset.idea === v && slot.last === r) {
          // what the reader already pressed on the first card stays pressed on the full one
          const off = !!slot.querySelector("[data-without-qloo]"), open = [...slot.querySelectorAll("details[data-claude], details[data-part=calls]")].filter((x) => x.open).map((x) => x.matches("[data-claude]") ? "details[data-claude]" : "details[data-part=calls]");
          slot.innerHTML = off ? without(full) : card(full);
          slot.last = full;
          slot.dataset.full = String(Math.round(performance.now() - t0));
          for (const s of open) slot.querySelector(s)?.setAttribute("open", "");
        }
      }
    } catch (e) {
      slot.innerHTML = `<p class="k-err" role="alert">${esc(e.message || e)}. Try again, or <a href="${esc(APP)}#research">open the full crossing</a>.</p>`;
    } finally { go.disabled = false; root.removeAttribute("aria-busy"); busy(false); }
  }
  // a link that names an idea (?q=, from the fields page) runs its check at once: one press, already pressed
  const asked = new URLSearchParams(location.search).get("q");
  if (asked) { q.value = asked.slice(0, 500); ask(q.value); }
  // proof first: the latest real verdict this server reached, drawn at load and labelled as a past check;
  // the visitor's own check replaces it
  const seen = (el, then) => {
    if (!("IntersectionObserver" in window)) return then();
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { io.disconnect(); then(); } });
    io.observe(el);
  };
  const draw = (r) => {
    if (!r || slot.dataset.ms || slot.querySelector(".k-status")) return;
    // a finished real result, whole, before any press: the recorded sample whose verdict is Open (vectors.open_sample),
    // labelled with the day Qloo answered it; else the last real check, folded to one line
    if (r.sample) {
      const s = r.sample, day = String(s.made || "").slice(0, 10);
      slot.innerHTML = card(s, `Real Qloo answer, ${day}`);
      slot.last = s;
    } else {
      const p = r.proof || r, when = String(p.checked_at || "").replace("T", " ").replace(/:\d\dZ$/, " UTC");
      if (!p.decision) return;
      const w = (WORD[p.decision.verdict] || [p.decision.verdict || ""])[0];
      slot.innerHTML = `<details class="k-more k-past"><summary>Real check, ${esc(when)}: ${esc(p.idea || "")}, ${esc(w)}</summary>${card(p, `Real check, ${when}`)}</details>`;
      slot.last = p;
    }
    slot.dataset.past = "1";
    try { performance.mark("knos-proof-shown"); } catch { /* old browsers */ }   // when the past result was drawn
  };
  form.addEventListener("submit", (ev) => { ev.preventDefault(); ask(q.value); });
  // below the first screen: the newest payout to an agent, as the chain has it, and the usage counter (checks and
  // briefs from the app's store, the payment program's devnet transactions). The build wrote both into the page
  // (scripts/live_snapshot.py); they are asked again after the reader's first move, as the product list is (web/home.js)
  let moved = false;
  const later = (f) => { const go = () => { if (moved) return; moved = true; f(); };
    for (const t of ["pointermove", "pointerdown", "touchstart", "keydown", "scroll", "focusin"]) addEventListener(t, go, { once: true, passive: true, capture: true }); };
  // and only once Paid on proof is in view: the first screen asks nobody
  later(() => seen(document.getElementById("paid-on-proof") || root, () => {
    const paid = document.getElementById("k-paid"), use = document.getElementById("k-usage"), oidc = document.getElementById("k-oidc");
    // the newest signature check knos_oidc ran on devnet (the program reads GitHub's signature itself), from devnet
    // the program's address is read from the program_ids.json the build ships, never typed into the page
    if (oidc) fetch("program_ids.json").then((r) => r.json()).then((ids) => fetch("https://api.devnet.solana.com", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "getSignaturesForAddress", params: [ids.knos_oidc, { limit: 20, commitment: "confirmed" }] }) }))
      .then((r) => r.json()).then((j) => {
        const x = (j.result || []).find((t) => t.err === null);
        if (!x) return;
        const day = x.blockTime ? new Date(x.blockTime * 1000).toISOString().slice(0, 10) : "";
        oidc.innerHTML = `Latest signature check on devnet${day ? `, ${esc(day)}` : ""} · <a href="https://explorer.solana.com/tx/${esc(x.signature)}?cluster=devnet" target="_blank" rel="noopener">the transaction</a>`;
        oidc.dataset.live = "1";
      }).catch(() => {});
    if (paid) get("/api/agent/payout/latest").then((x) => {
      if (!x || !x.found || !(x.units > 0)) return;
      const day = String(x.at || "").slice(0, 10);
      // what released it is the link to its transaction: twelve words at most for the line (tests/test_site_overflow.py)
      paid.innerHTML = `Agent paid <b>${esc(x.units)} test units</b>${day ? `, ${esc(day)}` : ""} · <a href="${esc(x.explorer)}" target="_blank" rel="noopener">${esc(x.released || "the transaction")}</a>`;
      paid.hidden = false;
      paid.dataset.live = "1";
    }).catch(() => {});
    // outside use only, this week against the last: a line only for real growth from at least 10, else nothing
    if (use) get("/api/usage").then((u) => {
      const line = u && u.trend && u.trend.line;
      use.textContent = line || "";
      use.hidden = !line;
      use.dataset.live = "1";
    }).catch(() => {});
  }));

  // each Qloo call of the card, in its order, as a row of the timeline: what it asked, what it decides, its ms, live or
  // cached; the counter counts them as they come, and the month's calls left are read once from /api/qloo/status
  const play = (box, r) => {
    box.dataset.played = "1";
    const rows = box.querySelector("[data-rows]"), counter = box.querySelector("[data-counter]");
    const decides = new Set((r.signals && r.signals.decides) || []);
    const list = r.calls.filter((c) => c && typeof c === "object");
    let live = 0, cached = 0, i = 0;
    const step = () => {
      if (!box.isConnected || i >= list.length) return;
      const c = list[i++];
      c.cached ? cached++ : live++;
      rows.insertAdjacentHTML("beforeend", `<li data-call="${esc(c.n)}">${esc(c.call || "")} · ${esc(c.what || c.effect || "")} · ${decides.size ? (decides.has(c.n) ? "decides" : "context") : "the verdict"} · ${
        Number.isFinite(c.ms) ? `${esc(c.ms)} ms` : `recorded ${esc(String(r.made || c.at || "").slice(0, 10))}`} · ${c.cached ? "cached" : "live"}</li>`);
      counter.textContent = `Qloo calls this check: ${i} (live ${live}, cached ${cached})`;
      setTimeout(step, 90);
    };
    step();
  };
  new MutationObserver(() => {
    const box = slot.querySelector("[data-timeline]:not([data-played])");
    if (box && slot.last && !box.closest(".k-past")) play(box, slot.last);
  }).observe(slot, { childList: true, subtree: true });
  // "Your past checks": the results this browser checked (kept in its own storage: id, idea, day), each read back from
  // its line in the Knos record in Sibyl (GET /api/receipts?id=); "Forget mine" empties this browser's list only
  const MINE = "knos-past-checks";
  const mine = () => { try { return JSON.parse(localStorage.getItem(MINE) || "[]"); } catch { return []; } };
  const keepMine = (r, asked) => {
    const id = /^[0-9a-f]{16}/.test(r.hash || "") ? r.hash.slice(0, 16) : "";
    if (!id) return;
    const list = [{ id, idea: asked, at: new Date().toISOString().slice(0, 10) }, ...mine().filter((x) => x.id !== id || x.idea !== asked)].slice(0, 20);
    try { localStorage.setItem(MINE, JSON.stringify(list)); } catch { /* storage refused: nothing kept */ }
    pastChecks();
  };
  const WORDS = { OPEN: "Open for pre-orders", REFUSE: "Not yet", CANNOT_DECIDE: "Cannot decide" };
  async function pastChecks() {
    style();
    let box = root.querySelector("[data-past-checks]");
    const list = mine();
    if (!list.length) { if (box) box.hidden = true; return; }
    if (!box) {
      slot.insertAdjacentHTML("afterend", `<section class="k-mine" data-past-checks aria-labelledby="k-mine-h"><h3 id="k-mine-h">Your past checks</h3>
        <p class="k-fine">Each read from its line in the Knos record in Sibyl.</p><ul data-mine></ul>
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
        if (li) li.innerHTML = `${esc(WORDS[d.verdict] || d.verdict || "no verdict")} · ${rec.recorded ? `<a href="${esc(API)}/receipts/${esc(x.id)}#record" target="_blank" rel="noopener" data-record>record line ${esc(rec.seq)}</a>` : `<span data-record-none>${esc(rec.why || "not in the record")}</span>`}`;
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
  // the fold "Claude alone": filled when it is first opened, from the published table, beside this card's answer
  slot.addEventListener("toggle", async (ev) => {
    const box = ev.target;
    if (!(box instanceof HTMLDetailsElement) || !box.matches("[data-claude]") || !box.open) return;
    const body = box.querySelector("[data-claude-body]");
    if (!body || body.dataset.done) return;
    body.dataset.done = "1";
    const r = slot.last || {}, d = r.decision || {}, who = r.who || {}, p = d.plan || {};
    const cities = cityList(r).map((c) => c.name);
    const mine = { verdict: d.verdict, audience: [(p.who?.age || who.top_age || "").replace(/_/g, " "), p.who?.gender || who.top_gender || ""].filter(Boolean).join(", ")
                     || (p.who?.segments || (r.audiences || []).filter((x) => x.tied).map((x) => x.name)).filter(Boolean).slice(0, 2).join(", "),
                   cities, tier: (r.price || {}).tier };
    body.innerHTML = await claudeAlone(r.idea || slot.dataset.idea, mine);
  }, true);
  // "Claude alone" is shown only when the published table has Claude's answer for this idea; a card drawn by a press
  // asks (the past result in its fold, drawn at the first paint, asks nobody)
  new MutationObserver(async () => {
    const box = slot.querySelector("details[data-claude][hidden]");
    if (!box || box.closest(".k-past") || box.dataset.asked) return;
    box.dataset.asked = "1";
    table = table || await get("/api/qloo-diff").catch(() => ({ rows: [] }));
    const idea = (slot.last || {}).idea || slot.dataset.idea;
    if ((table.rows || []).some((x) => x.claude && norm(x.idea) === norm(idea))) box.hidden = false;
  }).observe(slot, { childList: true });
  slot.addEventListener("submit", (ev) => {                 // "most like ...": the named product is the one to compare with
    const f = ev.target.closest("[data-like]");
    if (!f) return;
    ev.preventDefault();
    const like = String(new FormData(f).get("like") || "").trim();
    if (like) ask(slot.dataset.idea || q.value, { leader: like });
  });
  root.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-q]"), pick = ev.target.closest("[data-pick]"), none = ev.target.closest("[data-none]");
    const sure = ev.target.closest("[data-sure]"), other = ev.target.closest("[data-other]");
    if (sure) ask(slot.dataset.idea || q.value, { sure: true });
    else if (other) {
      let next = [];
      try { next = JSON.parse(other.dataset.other || "[]"); } catch { next = []; }
      other.closest("[data-confirm-row]").outerHTML = next.length ? `<p data-confirm-next>Which one, then? ${next.map((n) => `<button type="button" class="k-chip" data-pick="${esc(n)}">${esc(n)}</button>`).join(" ")} <button type="button" class="k-chip" data-sure>None of these: check my words</button></p>`
        : `<p data-confirm-next>Qloo matched nothing else. <button type="button" class="k-chip" data-sure>Check my words</button></p>`;
    }
    else if (b) { q.value = b.dataset.q; ask(b.dataset.q); }
    else if (pick) ask(slot.dataset.idea || q.value, { leader: pick.dataset.pick });
    else if (none) {
      let prev = [];
      try { prev = JSON.parse(slot.dataset.ex || "[]"); } catch { prev = []; }
      const all = [...new Set([...prev, ...none.dataset.none.split(",").filter(Boolean)])].slice(-20);
      slot.dataset.ex = JSON.stringify(all);
      ask(slot.dataset.idea || q.value, { exclude: all });
    }
  });
  // the past result, drawn last: every chip and the box already answer, and a snapshot the card cannot read leaves
  // the first screen as it is (the chips still check)
  const shown = (r) => cardCss().then(() => { try { draw(r); } catch (e) { console.warn("knos: the past result was not drawn", e); } });
  let carried = null;
  try { carried = JSON.parse(document.getElementById("k-proof")?.textContent || "null"); } catch { carried = null; }
  if (carried) shown({ proof: carried });                      // in the page: at the first paint
  // the Open sample, asked as soon as the box is in view (no stored answer in the page; a hidden box asks nobody)
  if (!asked) seen(root, () => get("/api/proof").then((p) => p && shown(p)).catch(() => {}));
})();
