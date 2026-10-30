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
  // ?qloo=off on the page (Start's fourth state): this one request is answered from the server's cache only, and says so
  const QOFF = new URLSearchParams(location.search).get("qloo") === "off";
  const post = async (path, body) => {
    if (QOFF && /^\/api\/(check|cross)/.test(path)) { path += (path.includes("?") ? "&" : "?") + "qloo=off"; body = { ...body, qloo: "off" }; }
    if (rid && /^\/api\/check/.test(path)) body = { ...body, req: rid };        // the check's own name in the server's call log
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
  // SOTA gap 8: the busy button keeps its label and its width ("Checking…" after a 14 px spinner, no tint), the 2 px bar
  // runs along the box's bottom edge, and the line under the box (a polite live region) says who is being asked and for
  // how long. Nothing covers the bar at the top.
  const live = document.getElementById("k-live"), liveSaid = live && live.querySelector("[data-said]"), liveT = live && live.querySelector("[data-t]");
  const liveN = live && live.querySelector("[data-count]");
  let clock = 0, since = 0, rid = "", poll = 0;
  // while a check runs: its Qloo calls and entities so far, read from the server's call log (GET /api/progress)
  const counted = (secs) => (rid ? get(`/api/progress?req=${rid}`) : Promise.resolve(null)).then((p) => {
    if (p && liveN) liveN.textContent = `Qloo calls ${p.calls} · entities ${p.entities}${secs != null ? ` · ${secs.toFixed(1)} s` : ""}`;
  }).catch(() => {});
  const tick = () => { if (liveT && since) liveT.textContent = `· ${((performance.now() - since) / 1000).toFixed(still() ? 0 : 1)} s`; };
  const busy = (on) => {
    const label = go.querySelector("[data-label]") || go;
    clearInterval(clock);
    if (!on) { label.textContent = "Check demand"; go.style.minWidth = ""; go.removeAttribute("aria-busy"); form.removeAttribute("aria-busy");
      clearInterval(poll); const secs = since ? (performance.now() - since) / 1000 : null; counted(secs);   // the last count stays
      since = 0; if (liveSaid) liveSaid.textContent = ""; if (liveT) liveT.textContent = ""; return; }
    rid = [...crypto.getRandomValues(new Uint8Array(8))].map((b) => b.toString(16).padStart(2, "0")).join("");
    if (liveN) liveN.textContent = ""; clearInterval(poll); poll = setInterval(() => counted(null), 700);
    go.style.minWidth = `${go.offsetWidth}px`;
    label.textContent = "Checking…"; go.setAttribute("aria-busy", "true"); form.setAttribute("aria-busy", "true");
    since = performance.now(); tick(); clock = setInterval(tick, still() ? 1000 : 100);
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
  const said = (t) => { if (liveSaid) liveSaid.textContent = t; };
  // R2 item 7: while a crossing runs, each Qloo call appears under the box as it finishes (the job's steps, polled every
  // 500 ms): endpoint, HTTP status, ms, live or recorded. Cleared when the next check starts.
  const flowRows = (steps) => { const box = document.getElementById("k-flow"); if (!box) return;
    const calls = steps.filter((x) => x && (x.call || x.endpoint || x.path));
    box.hidden = !calls.length;
    box.innerHTML = calls.map((x) => `<li data-flow-row>${esc(x.call || x.endpoint || x.path)}${x.status != null ? ` · ${esc(x.status)}` : ""}${Number.isFinite(x.ms) ? ` · ${esc(x.ms)} ms` : ""} · ${x.live ? "live" : x.recorded ? `recorded ${esc(x.recorded)}` : x.error ? "not answered" : "recorded"}</li>`).join(""); };
  // SOTA gap 3: a new result replaces the card in place, revealed from the box by a shared-element view transition
  // (k-ask to k-result, 320 ms, cubic-bezier(.16,1,.3,1)), its rows staggered 40 ms and capped at 280 ms; then the card is
  // scrolled into view only when its top is below 60% of the window. Reduced motion: the swap is instant.
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
    let since = 0;
    for (let i = 0; i < 240; i++) {
      const p = await get(`/api/cross?id=${encodeURIComponent(j.id)}&since=${since}`);
      since = p.total ?? since;
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
  <button type="button" class="k-chip" data-without aria-pressed="true">Without Qloo</button><span class="k-switch" role="group" aria-label="With Qloo or the model alone"><button type="button" class="k-chip" data-view="qloo" aria-pressed="false">With Qloo</button><button type="button" class="k-chip" data-view="model" aria-pressed="false">Model alone</button></span></header></article>`;
  slot.addEventListener("click", (ev) => {        // With Qloo / Model alone: the panel beside the card's own answer
    const v = ev.target instanceof Element && ev.target.closest(".k-switch [data-view]");   // the app's own views carry data-view too
    if (!v || !v.closest(".k-card")) return;
    const k = v.closest(".k-card"), model = v.dataset.view === "model";
    if (k.matches("[data-without-qloo]") && slot.last) {            // from the card without Qloo: the whole card again, then the view asked for
      slot.innerHTML = card(slot.last); const c = slot.querySelector(".k-card"); if (!c) return;
      c.querySelectorAll("[data-view]").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.view === v.dataset.view)));
      c.querySelector("[data-model-panel]")?.toggleAttribute("hidden", !model); c.querySelector(`[data-view="${v.dataset.view}"]`)?.focus(); return;
    }
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
        esc(c.call || "")} <span class="k-fine">${esc(keys)}</span> · ${Number.isFinite(c.ms) ? `${esc(c.ms)} ms` : `recorded ${esc(String(r.made || c.at || "").slice(0, 10))}`} · ${c.live ? "live" : c.recorded ? `recorded ${esc(c.recorded)}` : c.error ? "not answered" : "recorded"}${c.error ? " · failed" : ""} · ${esc([...(fed[c.n] || [])].join(", ") || String(c.effect || "").slice(0, 60) || "the verdict")}${r.signals ? ` · <span data-role="${(r.signals.decides || []).includes(c.n) ? "decides" : "context"}">${(r.signals.decides || []).includes(c.n) ? "decides" : "context"}</span>` : ""}</li>`; });
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
  // live: this request got HTTP 200 from Qloo; recorded: answered on an earlier day (the server's qloo_calls says which)
  const callsHead = (r) => { const c = Array.isArray(r.calls) ? r.calls : []; if (!c.length) return "";
    const q = r.qloo_calls || { live: c.filter((x) => x.live).length, recorded: c.filter((x) => x.recorded).length, days: [...new Set(c.map((x) => x.recorded).filter(Boolean))] };
    const ms = Number.isFinite(q.ms) ? q.ms : Number.isFinite(r.elapsed_ms) ? r.elapsed_ms : 0;
    const days = (q.days || []).length ? ` · recorded ${(q.days || []).map(esc).join(", ")}` : "";
    return `<p class="k-fine" data-part="calls-head" data-live="${q.live}" data-recorded="${q.recorded}">Qloo calls: ${q.live} live, ${q.recorded} recorded, ${Math.round(ms).toLocaleString("en-US")} ms${days}</p>`; };
  // before a check runs: the product Qloo matched to this idea, to confirm (Yes runs it; No offers the next 3)
  const confirmCard = (v, ms) => `<article class="k-card k-unknown" data-confirm data-not-prose><header class="k-card-head"><p class="k-kick">${esc(v)}</p>
  <h2 class="k-verdict">Is this what you mean? ${esc(ms[0])}</h2>
  <p data-confirm-row><button type="button" class="k-chip" data-sure>Yes</button> <button type="button" class="k-chip" data-other="${esc(JSON.stringify(ms.slice(1, 4)))}">No</button></p></header></article>`;
  const WORD = { OPEN:["Open for pre-orders", "open"], REFUSE: ["Not yet: pre-orders stay closed", "refuse"], CANNOT_DECIDE: ["Not enough evidence to decide", "unknown"] };
  // CODE.md 2.12: what an undecided verdict lacks, read from the rule's own reasons ("cannot decide: no Qloo evidence")
  const missing = (rs) => { const r = String((rs || [])[0] || "").replace(/^cannot decide:\s*/i, "").replace(/^no\s+/i, "").trim(); return r || "the evidence the rule needs"; };
  // Qloo's audience segments with their lift (check.py: the segment's mean change in affinity on the products nearest
  // the taste), signed to 4 decimals, highest first, up to 6; a lift is shown as Qloo's number, never weighed against a threshold
  const lifts = (r) => { const rows = (r.audiences || []).filter((a) => a && a.name && Number.isFinite(Number(a.lift))).slice(0, 6);
    if (!rows.length) return "";
    const f = (n) => (n > 0 ? "+" : n < 0 ? "-" : "") + Math.abs(n).toFixed(4);
    return `<ul class="k-lifts" data-part="lifts">${rows.map((a) => `<li data-call="${esc(a.src ?? "")}"><span>${esc(qlabel(a.name))}</span> <span class="k-lift">lift ${f(Number(a.lift))}</span>${Number.isFinite(Number(a.products)) ? ` <span class="k-fine">on ${esc(a.products)} products</span>` : ""}</li>`).join("")}</ul>`; };
  // R2 items 5, 6, 9, 11, 14, 15: the card opens with the check's one sentence and its 3 or 4 tiles (rep.story, the
  // server's), then what of the input it used; after the parts, the reruns a refusal offers, what was rejected and by which
  // rule, the downloads of an Open card, one question ("Was this useful?") and, only while the server's model is on, a box to ask
  const lift4 = (n) => (n > 0 ? "+" : n < 0 ? "-" : "") + Math.abs(n).toFixed(4);
  const storyHead = (r) => { const st = r.story; if (!st || !st.sentence) return "";
    const tiles = (st.tiles || []).slice(0, 4).map((t) => `<li><span>${esc(t.label)}</span><b>${esc(t.value)}</b>${t.lift != null && Number.isFinite(Number(t.lift)) ? `<i class="k-lift">lift ${lift4(Number(t.lift))}</i>` : ""}</li>`).join("");
    return `<p class="k-sentence" data-part="sentence">${esc(st.sentence)}</p>${tiles ? `<ul class="k-tiles" data-part="tiles">${tiles}</ul>` : ""}${st.used && st.used.line ? `<p class="k-fine k-used" data-part="used">${esc(st.used.line)}</p>` : ""}`; };
  const storyFoot = (r) => { const st = r.story || {}, h = /^[0-9a-f]{16,64}$/.test(r.hash || "") ? r.hash : "", out = [], id = esc(h.slice(0, 8));
    if ((st.reruns || []).length) out.push(`<p class="k-reruns" data-part="reruns">${st.reruns.slice(0, 3).map((x) => `<button type="button" class="k-chip" data-rerun="${esc(x.idea || r.idea || "")}" data-place="${esc(x.place || "")}">${esc(x.label)}</button>`).join(" ")}</p>`);
    if ((st.rejected || []).length) out.push(`<p class="k-fine" data-part="rejected-story">Rejected: ${st.rejected.map((x) => `${esc(x.name)} (${esc(x.rule)})`).join("; ")}</p>`);
    if ((r.decision || {}).verdict === "OPEN" && (st.downloads || []).length) out.push(`<p class="k-fine" data-part="downloads">${st.downloads.map((x) => `<a href="${esc(/^https?:/.test(x.url) ? x.url : API + x.url)}" download data-download="${esc(x.kind)}">${esc(x.label)}</a>`).join(" · ")}</p>`);
    if (h) out.push(`<form class="k-useful" data-useful data-hash="${esc(h)}"><span>Was this useful?</span> <button type="submit" class="k-chip" name="useful" value="yes">Yes</button> <button type="submit" class="k-chip" name="useful" value="no">No</button> <label class="k-sr" for="k-note-${id}">A note, optional</label><input id="k-note-${id}" name="note" maxlength="280" placeholder="A note (optional)"> <span class="k-fine" data-useful-said role="status"></span></form>`);
    if (h) out.push(`<form class="k-askit" data-ask-box data-hash="${esc(h)}"${modelOn ? "" : " hidden"}><label for="k-askq-${id}">Ask about this result</label> <input id="k-askq-${id}" name="question" maxlength="300" required> <button type="submit" class="k-chip">Ask</button><span class="k-fine" data-ask-said role="status"></span></form>`);
    return out.length ? `<section class="k-story-foot" data-part="story-foot">${out.join("")}</section>` : ""; };
  // the model's state, read once when a card is first drawn (GET /api/status "model"); the ask box shows only while it is "on"
  let modelOn = false, modelAsked = false;
  const askModel = () => { if (modelAsked) return; modelAsked = true;
    get("/api/status").then((st) => { modelOn = !!(st && st.model === "on"); if (modelOn) slot.querySelectorAll("[data-ask-box][hidden]").forEach((f) => { f.hidden = false; }); }).catch(() => {}); };
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
  // which one do you mean? (apps/wanted which.py): 2 to 4 readings built in code, each one line that becomes the checked
  // idea when picked; a paper shows itself first and its products as readings, or a box to name one
  const whichCard = (w) => { const pp = w.paper;
    const paperLine = pp ? `<p class="k-why" data-paper>${esc(pp.title)}${pp.year ? ` (${esc(pp.year)})` : ""}${Number.isFinite(pp.cited_by_count) ? `, cited ${Number(pp.cited_by_count).toLocaleString("en-US")} times` : ""}${(pp.concepts || []).length ? ` · ${esc(pp.concepts.slice(0, 3).join(", "))}` : ""}</p>` : "";
    const rows = (w.readings || []).map((x) => `<li><button type="button" class="k-chip" data-reading="${esc(x.text)}" data-kind="${esc(x.kind)}">${esc(x.text)}</button>${x.type ? ` <span class="k-type" data-type>${esc(x.type)}</span>` : ""}${x.description || x.line ? ` <span class="k-fine" data-line>${esc(x.description || x.line)}</span>` : ""}</li>`).join("");
    const box = w.name_box ? `<form data-name-box class="k-row"><label class="k-fine" for="k-name">${esc(w.name_prompt || "Name the product this result enables")}</label> <input id="k-name" name="name" maxlength="200" required> <button type="submit" class="k-chip">Check it</button></form>` : "";
    return `<article class="k-card k-unknown" data-which data-not-prose><header class="k-card-head"><p class="k-kick">${esc(w.asked)}</p><h2 class="k-verdict">Which one do you mean?</h2>${paperLine}${rows ? `<ul class="k-readings" data-readings>${rows}</ul>` : ""}${box}</header></article>`; };
  // the picked reading Qloo has not answered and cannot today: the one line, the Ready brief built with no Qloo, its
  // hold on devnet, and under it the nearest recorded answer as a labelled stand-in
  const queuedCard = (r) => { const b = r.brief || {}, ms = b.milestones || [], rd = r.ready || {}, st = r.stand_in;
    return `<article class="k-card k-unknown" data-queued data-not-prose><header class="k-card-head"><p class="k-kick" data-read-as>${esc(r.result_line || `Read as ${r.read_as || r.idea}`)}</p>
  <h2 class="k-verdict">${esc(r.queued.line)}</h2>
  <p class="k-why" data-brief>Ready brief: ${ms.map((m) => `${esc(m.name)}, ${esc(m.target)}`).join("; ")}${rd.criteria_hash ? ` · criteria hash <code>${esc(String(rd.criteria_hash).slice(0, 12))}</code>` : ""}</p>
  <p class="k-next"><a href="${esc(APP)}#projects" data-ready-path data-idea="${esc(r.read_as || r.idea)}">Hold devnet test money on this brief</a></p>${callsHead(r)}</header></article>
  ${st ? `<p class="k-fine" data-stand-in>${esc(st.said)}.</p>${card(st.card, `Stand-in, recorded ${st.made}`)}` : ""}`; };
  // ---- the recorded card's own parts (U1): every number is the recorded answer's; nothing is estimated ----------------
  const plainOf = (x) => String(x || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
  const rankIn = (guess, names) => { const g = plainOf(guess); if (!g) return 0; const i = names.findIndex((n) => { const v = plainOf(n); return v && (v.includes(g) || g.includes(v.split(" ")[0])); }); return i + 1; };
  // supported: in the answer's top 5; challenged: outside its top 20, or absent from an answer that lists 20 or more
  const verdictOf = (guess, names) => { const k = rankIn(guess, names);
    return k && k <= 5 ? ["Supported", k] : (k && k > 20) || (!k && names.length >= 20) ? ["Challenged", k] : ["Not established", k]; };
  const strengthOf = (n) => (n >= 5 ? "strong" : n >= 2 ? "moderate" : "weak");
  const OPEN_Q = ["no buyer count", "no price paid", "no outcome yet"];
  const u1 = (r) => { const q = r.qloo_calls || {}, ents = (r.matches || []).filter((m) => m && m.name), n = ents.length, st = strengthOf(n);
    const places = [...(r.where || []), ...(r.cities || []).map((c) => c && c.name)].filter(Boolean);
    const auds = (r.audiences || []).map((a) => a && (a.name || a)).filter(Boolean);
    const guess = slot.dataset.guess || "", who = (document.getElementById("k-who")?.value || "").trim();
    const asum = [guess ? ["Launch place", guess, verdictOf(guess, places)] : null, who ? ["Who buys it", who, verdictOf(who, auds)] : null].filter(Boolean);
    const sig = (r.signals && Array.isArray(r.signals.rows) ? r.signals.rows : []);
    const without = sig.length ? sig.filter((x) => x.changes || x.moved).length : null;
    let conf = { strong: 3, moderate: 2, weak: 1 }[st];
    const steps = OPEN_Q.map((w) => { conf = Math.max(0, conf - 1); return `<li>${esc(w)}: confidence ${["none", "low", "medium", "high"][conf]}</li>`; });
    const rej = (r.gap && r.gap.rejected) || ((r.story && r.story.rejected) || []).map((x) => ({ name: x.name, code: "rule", why: x.rule }));
    const day = String((r.stale && r.stale.from) || r.made || "").slice(0, 10), reset = r.qloo_reset || "";
    return `<section class="k-u1" data-u1 data-not-prose>
  <p class="k-fine" data-part="recorded">Recorded ${esc(day)}${reset ? ` · Run live when Qloo resets ${esc(reset)}` : ""}</p>
  <p class="k-fine" data-part="without-count" data-without-count="${without == null ? "" : without}">Without Qloo: ${without == null ? "this card's parts are each Qloo's" : `${without} of ${sig.length} of this card's signals change`}</p>
  <p class="k-fine" data-part="strength" data-strength="${st}" data-entities="${n}">Signal strength: ${st}, ${n} entit${n === 1 ? "y" : "ies"} Qloo confirmed</p>
  <div class="k-modeled" data-part="modeled"><p class="k-fine"><b>Qloo modeled:</b> taste affinity by audience, place and tag.</p><p class="k-fine"><b>Not modeled:</b> income, politics, education, job title and the price people paid.</p></div>
  ${asum.length ? `<ul class="k-fine" data-part="assumptions">${asum.map(([what, said, [v, k]]) => `<li data-assumption="${esc(what)}" data-verdict="${esc(v)}" data-rank="${k}">${esc(what)} "${esc(said)}": ${esc(v)}${k ? `, rank ${k}` : ", not in the answer"}</li>`).join("")}</ul>` : ""}
  ${rej.length ? `<p class="k-fine" data-part="rejected-signals">Signals Knos rejected: ${rej.map((o) => `${esc(o.name)} (${esc(o.code)}: ${esc(o.why)})`).join("; ")}</p>` : ""}
  <div data-part="cannot"><p class="k-fine"><b>What this cannot tell you</b></p><ul class="k-fine">${steps.join("")}</ul></div>
  <p class="k-fine" data-part="exports"><button type="button" class="k-chip" data-export="md">Markdown</button> <button type="button" class="k-chip" data-export="json">Evidence JSON</button> <button type="button" class="k-chip" data-export="print">One-page memo</button></p>
  <p class="k-fine" data-part="closing" data-calls="${(r.calls || []).length}">${(r.calls || []).length} Qloo calls (${q.live || 0} live, ${q.recorded || 0} recorded), ${Math.round(q.ms || r.elapsed_ms || 0).toLocaleString("en-US")} ms</p>
</section>`; };
  // the exports: the card as Markdown, its evidence as JSON (the recorded answer's own fields), a printable memo
  const exportCard = (kind) => { const r = slot.last; if (!r) return;
    if (kind === "print") { document.documentElement.classList.add("k-print"); print(); document.documentElement.classList.remove("k-print"); return; }
    const art = slot.querySelector("article.k-card");
    const text = kind === "json" ? JSON.stringify({ idea: r.idea, made: r.made, decision: r.decision, terms: r.terms, qloo_calls: r.qloo_calls, calls: (Array.isArray(r.calls) ? r.calls : []).map((c) => ({ call: c.call, live: c.live, recorded: c.recorded })), label: r.label }, null, 1)
      : `# ${r.idea}\n\n` + [...(art ? art.querySelectorAll("h2, p, li") : [])].map((e) => (e.tagName === "LI" ? "- " : "") + e.textContent.replace(/\s+/g, " ").trim()).filter(Boolean).join("\n\n") + "\n";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: kind === "json" ? "application/json" : "text/markdown" }));
    a.download = `knos-${String(r.hash || "card").slice(0, 16)}.${kind === "json" ? "json" : "md"}`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); };
  const recordedCard = (r, label) => !!(r && r.decision && (label || r.stale || (r.qloo_calls && r.qloo_calls.live === 0 && (r.qloo_calls.recorded || 0) > 0)));
  function card(r, label) {
    style(); askModel();
    if (r.kind === "which_one") return whichCard(r);
    if (r.queued) return queuedCard(r);
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
    const empty = !r.nearest && !(age || gender) && !segs.length && !(r.audiences || []).some((a) => a && Number.isFinite(Number(a.lift))) && !wants.length && !(r.cities || []).length && !cities.length && !tier && !also.length;     // no part answered: one next step, no empty boxes
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
  ${storyHead(r)}
  ${gapOpen(r)}
  ${guess ? yourCall(guess, terms, cities) : ""}
  ${down ? `<p class="k-terms" data-qloo-down>${esc(down)}</p>` : ""}${r.nearest && reset ? `<p class="k-fine k-terms" data-qloo-limit-line>${esc(reset.trim())}</p>` : ""}
  <header class="k-card-head"><p class="k-kick">${label ? `<span class="k-real">${esc(label)}</span> · ` : ""}${esc(r.idea || r.label || "")}</p><h2 class="k-verdict" data-part="verdict" data-qloo>${esc(word)}${src(h)}</h2>${callsHead(r)}
  ${terms && d.verdict === "OPEN" ? `<p class="k-terms" data-part="terms" data-city="${esc(terms.city)}" data-target="${esc(terms.target)}">Launch in <b>${esc(terms.city)}</b>: ${esc(terms.target)} pre-orders.${chip("rule", "rule-target")} Every pre-order is refunded if the target is missed.</p>${terms.by_population ? `<p class="k-fine" data-part="by-population" data-pop-city="${esc(terms.by_population.city)}" data-pop-target="${esc(terms.by_population.target)}">By population: ${esc(terms.by_population.city)}, ${esc(terms.by_population.target)}.${chip("rule", "rule-population")} By Qloo taste: ${esc(terms.city)}, ${esc(terms.target)}.${chip("rule", "rule-target")}</p>` : ""}` : ""}
  ${r.signals && r.signals.line ? `<p class="k-fine" data-part="signals">${esc(r.signals.line)}</p>` : ""}${gapClose(r)}
  ${read}${why ? `<p class="k-why"${d.verdict === "CANNOT_DECIDE" ? " data-missing" : ""}><b>${d.verdict === "CANNOT_DECIDE" ? "Missing:" : "Knos rule:"}</b> ${esc(d.verdict === "CANNOT_DECIDE" ? missing(d.reasons) : why)}</p>` : ""}${trendLine(r)}
  ${Array.isArray(r.calls) && r.calls.length ? `<section class="k-timeline" data-timeline aria-live="polite"><p class="k-fine" data-counter>Qloo calls this check: 0 (live 0, recorded 0)</p><ol data-rows tabindex="0" aria-label="Qloo calls, as they answered"></ol></section>` : ""}
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
        : segs.length ? `<p>${esc(segs.join(" · "))}</p>` : ""}${lifts(r)}${src(h, who.src)}</section>
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
  ${storyFoot(r)}
  ${recordedCard(r, label) ? u1(r) : ""}
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
    flowRows([]);
    let pre = null;
    if (!extra.picked && !extra.leader && !extra.exclude) {               // which one do you mean? asked before any check
      said(paper(v) ? "Reading the paper" : "Reading what you typed");
      const w = await post("/api/check", { idea: v, stage: "verdict" }).catch(() => null);
      if (w && w.kind === "which_one") {
        await cardCss(); slot.dataset.idea = v; slot.last = w; slot.dataset.ms = "0"; reveal(whichCard(w));
        go.disabled = false; root.removeAttribute("aria-busy"); busy(false); return;
      }
      extra = { ...extra, picked: true };                                 // a recorded idea, word for word: no step
      if (w && w.decision) pre = w;                                       // and its verdict card already came back
    }
    if (!sure && !extra.picked && !extra.leader && !extra.exclude && !paper(v)) {          // a recorded idea: its matched product first
      const m = await get(`/api/match?idea=${encodeURIComponent(v)}`).catch(() => null);
      if (m && (m.matches || []).length) {
        await cardCss(); slot.dataset.idea = v; reveal(confirmCard(v, m.matches));
        go.disabled = false; root.removeAttribute("aria-busy"); busy(false); return;
      }
    }
    const ref = extra.picked ? null : paper(v), t0 = performance.now();
    slot.dataset.guess = (document.getElementById("k-guess")?.value || "").trim().slice(0, 60);
    said(QOFF ? "Qloo off for this request: the cache only" : ref ? "Reading the paper" : "Talking to Qloo");
    try {
      // the verdict card first (verdict, matched product, audience); the map, also-loved and the launch terms follow
      // from the full check, whose Qloo questions the first one already sent
      const r = ref ? await crossing(ref) : pre || await post("/api/check", { idea: v, ...extra, stage: "verdict" });
      await cardCss();
      slot.last = r;
      reveal(card(r), () => document.dispatchEvent(new CustomEvent("knos:reached", { detail: r.ready && r.ready.criteria_hash ? 1 : 0 })));
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
      reveal(`<p class="k-err" role="alert">${esc(e.message || e)}. Try again, or <a href="${esc(APP)}#research">open the full crossing</a>.</p>`);
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
  // SOTA gap 2: the first screen's finished result, beside the box (under it on a phone): the real last good check,
  // read from the app at view time (GET /api/proof; the page stores no Qloo answer). Its verdict, the launch terms, the
  // top three places as bars (Qloo's concentration index, 0 to 100) and the day Qloo answered it (`made`, CODE.md 2.18).
  // "Wanted" only: an undecided check is never the first thing shown. Its room is kept from the first paint (CLS).
  const pastCard = (r, label) => {
    const d = r.decision || {}, terms = termsOf(r), open = d.verdict === "OPEN";
    let bars = cityList(r).filter((c) => c.index != null).slice(0, 3).map((c) => [c.name, c.index]);
    if (!bars.length) bars = (r.cities || []).filter((c) => c && c.name && Number.isFinite(c.affinity)).slice(0, 3).map((c) => [c.name, Math.round(Math.max(0, Math.min(1, c.affinity)) * 100)]);
    const h = /^[0-9a-f]{16}/.test(r.hash || "") ? r.hash : "";
    return `<article class="k-past-card" data-verdict="${esc(d.verdict || "")}" data-past-card data-not-prose>
  <p class="k-kick"><span class="k-real">${esc(label)}</span> · ${esc(r.idea || "")}</p>
  <h2 class="k-v${open ? "" : " k-no"}" data-part="verdict">${open ? "Wanted" : esc((WORD[d.verdict] || [d.verdict || ""])[0])}</h2>
  ${terms && open ? `<p class="k-where" data-part="terms">Launch in <b>${esc(terms.city)}</b>: ${esc(terms.target)} pre-orders</p>` : ""}
  ${bars.length ? `<ol class="k-bars" aria-label="Top places by Qloo's concentration index, 0 to 100">${bars.map(([n, v]) => `<li><span>${esc(n)}</span><b>${esc(v)}</b><i style="--w:${Math.max(2, Math.min(100, Number(v) || 0))}%"></i></li>`).join("")}</ol>` : ""}
  <p class="k-foot">${h ? `<a href="${esc(API)}/trace.html?hash=${encodeURIComponent(h)}" target="_blank" rel="noopener">Its Qloo calls</a>` : "<span></span>"} <button type="button" class="k-chip" data-whole>See the whole card</button></p>
</article>`;
  };
  const draw = (r) => {
    if (!r || slot.dataset.ms || go.hasAttribute("aria-busy")) return;
    const day = (x) => String(x.made || x.checked_at || "").slice(0, 10);
    const good = (x) => x && x.decision && x.decision.verdict && x.decision.verdict !== "CANNOT_DECIDE";
    const p = r.sample && good(r.sample) ? r.sample : r.proof && good(r.proof) && (r.proof.decision.verdict === "OPEN" || !r.sample) ? r.proof : null;
    if (!p) { slot.dataset.empty = "1"; return; }
    slot.past = `Real Qloo answer, ${day(p)}`;
    slot.innerHTML = pastCard(p, slot.past);
    slot.last = p;
    slot.dataset.past = "1";
    try { performance.mark("knos-proof-shown"); } catch { /* old browsers */ }   // when the past result was drawn
  };
  slot.addEventListener("click", (ev) => {           // the first screen's card, opened whole in place
    if (!(ev.target instanceof Element) || !ev.target.closest("[data-whole]") || !slot.last) return;
    reveal(card(slot.last, slot.past || ""));
  });
  // WebMCP (SOTA AGENT GAP 4): an agent that submits the form gets the result as JSON; a person gets the card
  form.addEventListener("submit", (ev) => { ev.preventDefault(); pressed(null);
    const run = ask(q.value);
    if (ev.agentInvoked && ev.respondWith) ev.respondWith(run.then(() => { const r = slot.last || {}, h = /^[0-9a-f]{16}/.test(r.hash || "") ? r.hash : "";
      return JSON.stringify({ verdict: (r.decision || {}).verdict || (r.kind === "which_one" ? "WHICH_ONE" : null), readings: r.readings || undefined,
        places: cityList(r).map((c) => c.name), trace: h ? `${API}/trace.html?hash=${h}` : null }); })); });
  // read-only tools for an agent in the page, where the browser offers them (document.modelContext); money stays in the app
  if ("modelContext" in document && document.modelContext && document.modelContext.registerTool) {
    try {
      document.modelContext.registerTool({ name: "open_trace", description: "Opens the Qloo trace of a past demand check by its hash",
        inputSchema: { type: "object", properties: { hash: { type: "string", description: "The check's hash, 16 to 64 hex characters" } }, required: ["hash"] },
        annotations: { readOnlyHint: true },
        execute: async ({ hash }) => { if (!/^[0-9a-f]{16,64}$/.test(String(hash || ""))) return "hash: 16 to 64 hex characters"; open(`${API}/trace.html?hash=${hash}`, "_blank", "noopener"); return `opened the trace of ${hash}`; } });
      document.modelContext.registerTool({ name: "open_preorders", description: "Opens the pre-order page of an Open check in the app; the person confirms any money there",
        inputSchema: { type: "object", properties: { hash: { type: "string", description: "The Open check's hash" } }, required: ["hash"] },
        annotations: { consequentialHint: true },
        execute: async ({ hash }) => { if (!/^[0-9a-f]{16,64}$/.test(String(hash || ""))) return "hash: 16 to 64 hex characters"; location.href = `${APP}#buy=${hash}`; return "opened the pre-order page"; } });
    } catch { /* a browser whose tools differ: the form still works */ }
  }
  // the chip pressed is the one shown pressed (its look morphs into the result's title by name, SOTA gap 14)
  const pressed = (b) => root.querySelectorAll(".k-try .k-chip").forEach((c) => c.setAttribute("aria-pressed", String(c === b)));
  // the parts of the hero after this script in the page (the chips, the shape, the proof strip): wired once parsed
  const parsed = (f) => (document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", f, { once: true }) : f());
  parsed(() => {
    // SOTA gap 10: the two optional fields wait behind one disclosure (a <details>, so it opens without script too)
    const add = document.getElementById("k-add");
    if (add) add.addEventListener("toggle", () => { if (add.open) document.getElementById("k-guess")?.focus(); });
    // Qloo's limits, read at view time: the line under the box and the two waiting examples show only while Qloo limits
    // or refuses Knos (GET /api/qloo/status, CODE.md 2.13); while it answers, neither is drawn
    const lim = root.querySelector("[data-qloo-limit]"), more = root.querySelector("[data-more-chips]");
    seen(root, () => get("/api/qloo/status").then((st) => {
      const limited = !!(st && (st.limited || st.held_s > 0));
      if (more) { more.textContent = limited ? "2 more examples return when Qloo answers again" : ""; more.hidden = !limited; }
      if (lim) { lim.textContent = limited && st.line ? st.line : ""; lim.hidden = !(limited && st.line); }
    }).catch(() => {}));
    // SOTA gap 5 and R2 item 4: the proof strip. The first two numbers are the published runs'; the last two are read from
    // the app at view time (GET /api/counter), zeros shown as zeros, "n/a" when it does not answer. Each counts up from 0
    // over 600 ms on first view (ease-out), and stands still with reduced motion.
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
        if (Number.isFinite(n)) { b.dataset.n = String(n); count(b, n); } else b.textContent = "n/a"; } })
        .catch(() => { for (const b of strip.querySelectorAll("b[data-counter]")) b.textContent = "n/a"; });
    });
  });
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
    // outside use only, this week against the last: a line only for real growth from at least 10, else nothing; the
    // comparison only once the counter has run two weeks (`since` 14 days back or more, CODE.md 2.17), before that this week alone
    if (use) get("/api/usage").then((u) => {
      const t = (u && u.trend) || {}, from = Date.parse(String((u && u.since) || "") + "T00:00:00Z");
      const twoWeeks = Number.isFinite(from) && Date.now() - from >= 14 * 864e5;
      const line = twoWeeks ? t.line : Number(t.this_week) > 0 ? `${Number(t.this_week).toLocaleString("en-US")} ideas checked this week` : "";
      use.textContent = line || "";
      use.hidden = !line;
      use.dataset.live = "1";
    }).catch(() => {});
  }));

  // each Qloo call of the card, in its order, as a row of the timeline: what it asked, what it decides, its ms, live or
  // cached; the counter counts them as they come, and the month's calls left are read once from /api/qloo/status
  const q0 = (n) => Math.max(0, Number(n) || 0);
  const play = (box, r) => {
    box.dataset.played = "1";
    const rows = box.querySelector("[data-rows]"), counter = box.querySelector("[data-counter]");
    const decides = new Set((r.signals && r.signals.decides) || []);
    const list = r.calls.filter((c) => c && typeof c === "object");
    const row = (c) => `${esc(c.call || "")} · ${esc(c.what || c.effect || "")} · ${decides.size ? (decides.has(c.n) ? "decides" : "context") : "the verdict"} · ${
        Number.isFinite(c.ms) ? `${esc(c.ms)} ms` : `recorded ${esc(String(r.made || c.at || "").slice(0, 10))}`} · ${c.live ? "live" : c.recorded ? `recorded ${esc(c.recorded)}` : c.error ? "not answered" : "recorded"}`;
    let live = 0, cached = 0, failed = 0, i = 0;
    const qc = r.qloo_calls && Number.isFinite(Number(r.qloo_calls.live)) ? r.qloo_calls : null;
    // every row is in place from the start, unseen, so revealing one moves nothing (sweep M1.md 4.5)
    rows.innerHTML = list.map((c) => `<li data-call="${esc(c.n)}" style="opacity:0">${row(c)}</li>`).join("");
    const items = [...rows.children];
    const step = () => {
      if (!box.isConnected || i >= list.length) return;
      const c = list[i];
      items[i++].style.opacity = "";
      c.live ? live++ : c.error ? failed++ : cached++;
      if (still() || i >= list.length) { items.forEach((li) => { li.style.opacity = ""; }); i = list.length;
        live = qc ? q0(qc.live) : list.filter((x) => x.live).length; failed = list.filter((x) => !x.live && x.error).length;
        cached = qc ? Math.min(q0(qc.recorded), list.length - live - failed) : list.length - live - failed; failed = list.length - live - cached; }
      counter.textContent = `Qloo calls this check: ${i} (live ${live}, recorded ${cached}${failed ? `, not answered ${failed}` : ""})`;
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
  const WORDS = { OPEN: "Open for pre-orders", REFUSE: "Not yet", CANNOT_DECIDE: "Not enough evidence" };
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
  root.addEventListener("click", (ev) => { const x = ev.target.closest && ev.target.closest("[data-export]"); if (x) exportCard(x.dataset.export); });
  root.addEventListener("click", (ev) => {          // a rerun a refusal offers: the tag or the market, asked live again
    const b = ev.target instanceof Element && ev.target.closest("[data-rerun]"); if (!b) return;
    const g = document.getElementById("k-guess"); if (g && b.dataset.place) g.value = b.dataset.place;
    q.value = b.dataset.rerun; ask(b.dataset.rerun, { picked: true, sure: true });
  });
  slot.addEventListener("submit", (ev) => {         // "Was this useful?": saved with the check's hash, never who said it
    const f = ev.target.closest && ev.target.closest("[data-useful]"); if (!f) return;
    ev.preventDefault();
    const yes = ev.submitter ? ev.submitter.value === "yes" : true, said = f.querySelector("[data-useful-said]");
    f.querySelectorAll("button").forEach((b) => { b.disabled = true; b.setAttribute("aria-pressed", String(b.value === (yes ? "yes" : "no"))); });
    post("/api/feedback", { hash: f.dataset.hash, useful: yes, note: String(new FormData(f).get("note") || "").slice(0, 280) })
      .then(() => { said.textContent = "Saved. Thank you."; }).catch((e) => { said.textContent = `Not saved: ${e.message}`; f.querySelectorAll("button").forEach((b) => { b.disabled = false; }); });
  });
  slot.addEventListener("submit", (ev) => {         // "Ask about this result": answered from the card's own data, citing its calls
    const f = ev.target.closest && ev.target.closest("[data-ask-box]"); if (!f) return;
    ev.preventDefault();
    const out = f.querySelector("[data-ask-said]"); out.textContent = "Asking…";
    post("/api/ask", { hash: f.dataset.hash, question: String(new FormData(f).get("question") || "") })
      .then((a) => { out.textContent = a.refused ? `Not answered: ${a.refused}` : `${a.answer || ""}${(a.cites || []).length ? ` (calls ${a.cites.join(", ")})` : ""}`; })
      .catch((e) => { out.textContent = `Not answered: ${e.message}`; });
  });
  root.addEventListener("submit", (ev) => {
    const f = ev.target.closest("[data-name-box]");
    if (!f) return;
    ev.preventDefault();
    const name = String(new FormData(f).get("name") || "").trim();
    if (name) { q.value = name; ask(name, { picked: true, sure: true }); }
  });
  root.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-q]"), pick = ev.target.closest("[data-pick]"), none = ev.target.closest("[data-none]");
    const sure = ev.target.closest("[data-sure]"), other = ev.target.closest("[data-other]"), reading = ev.target.closest("[data-reading]");
    if (reading) { q.value = reading.dataset.reading; ask(reading.dataset.reading, { picked: true, sure: true }); }
    else if (sure) ask(slot.dataset.idea || q.value, { sure: true });
    else if (other) {
      let next = [];
      try { next = JSON.parse(other.dataset.other || "[]"); } catch { next = []; }
      other.closest("[data-confirm-row]").outerHTML = next.length ? `<p data-confirm-next>Which one, then? ${next.map((n) => `<button type="button" class="k-chip" data-pick="${esc(n)}">${esc(n)}</button>`).join(" ")} <button type="button" class="k-chip" data-sure>None of these: check my words</button></p>`
        : `<p data-confirm-next>Qloo matched nothing else. <button type="button" class="k-chip" data-sure>Check my words</button></p>`;
    }
    else if (b) { q.value = b.dataset.q; pressed(b.closest(".k-try") ? b : null); ask(b.dataset.q); }
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
  const shown = (r) => { document.dispatchEvent(new CustomEvent("knos:proof", { detail: r }));   // the shape under the box reads it too
    return cardCss().then(() => { try { draw(r); } catch (e) { console.warn("knos: the past result was not drawn", e); } }); };
  // the Open sample, asked of the server as soon as the box is in view (no Qloo answer is ever in the page)
  if (!asked) seen(root, () => get("/api/proof").then((p) => p && shown(p)).catch(() => {}));   // one card, never redrawn
})();
