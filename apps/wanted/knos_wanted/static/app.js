// Knos: six roles on one phone page. No framework; every taste call happens on the server.
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const X = (sig, kind) => `https://explorer.solana.com/${kind || "tx"}/${sig}?cluster=devnet`;
const short = (s) => String(s || "").slice(0, 8) + "…";
let session = null, report = null, status = {};
try { session = JSON.parse(localStorage.getItem("knos.session") || "null"); } catch (e) { session = null; }

// ---- i18n ----------------------------------------------------------------------------------------------------------
const I = window.KNOS_I18N || { langs: { en: "English" }, rtl: [], en: {} };
let LANG = "en";
try { LANG = localStorage.getItem("knos.lang") || (navigator.language || "en").slice(0, 2); } catch (e) { /* private */ }
if (!I.langs[LANG]) LANG = "en";
const t = (k) => (I[LANG] && I[LANG][k]) || I.en[k] || k;
function applyLang() {
  document.documentElement.lang = LANG;
  document.documentElement.dir = I.rtl.includes(LANG) ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-ph]").forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
  if (session) $("whoBtn").textContent = session.label;
}
function langMenu() {
  // Only the current language is listed until the menu is used: the other names (Arabic, Hindi, Chinese scripts) make
  // the browser load fallback fonts, which cost seconds of style and layout on a phone's first paint (Lighthouse).
  const fill = (all) => { $("lang").innerHTML = Object.entries(I.langs).filter(([k]) => all || k === LANG).map(([k, v]) => `<option value="${k}" ${k === LANG ? "selected" : ""}>${esc(v)}</option>`).join(""); };
  fill(false);
  const more = () => { if (!$("lang").dataset.full) { $("lang").dataset.full = "1"; fill(true); } };
  for (const ev of ["focus", "pointerdown", "touchstart", "keydown"]) $("lang").addEventListener(ev, more, { passive: true });
  $("lang").onchange = () => { LANG = $("lang").value; try { localStorage.setItem("knos.lang", LANG); } catch (e) { } applyLang(); show(); };
}

// ---- plumbing ------------------------------------------------------------------------------------------------------
async function api(path, body) {
  const headers = { "Content-Type": "application/json" };
  if (session && session.token) headers.Authorization = "Bearer " + session.token;
  const r = await fetch(path, body === undefined ? { headers } : { method: "POST", headers, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  // a failure in one plain sentence: the server's own words, else what happened (never a bare status code)
  if (!r.ok) throw new Error(data.error || data.message || (r.status >= 500 ? "The server did not answer this time. Try again in a moment." : "The server refused this request."));
  return data;
}
let slowTimer = null;
function slow(on, what) {
  clearTimeout(slowTimer); const el = $("slow");
  if (!on) { el.hidden = true; return; }
  el.hidden = false; $("slowText").textContent = what + "…";
  slowTimer = setTimeout(() => { $("slowText").textContent = what + "… (" + t("loading") + ")"; }, 6000);
}
function err(e) { const b = $("err"); b.hidden = !e; b.textContent = e ? String(e.message || e) : ""; if (e) b.scrollIntoView({ block: "nearest" }); }
async function busy(btn, text, fn) {
  const was = btn.textContent; btn.disabled = true; btn.textContent = text; slow(true, text); err(null);
  try { return await fn(); } catch (e) { err(e); } finally { btn.disabled = false; btn.textContent = was; slow(false); }
}

// ---- views ---------------------------------------------------------------------------------------------------------
const VIEWS = ["home", "research", "buy", "fund", "contribute", "make", "projects", "teams", "agents"];
function show() {
  err(null); slow(false, "");
  const h = location.hash;
  const m = h.match(/^#buy=([0-9a-f]{64})/);
  const one = h.match(/^#(back|fund|contribute)=([a-z0-9-]{3,64})$/);       // a one-tap action from the front door
  if (one && one[1] === "back") return goBack(one[2]);
  if (h === "#verify") return location.replace("/verify");          // the front door's link to How we verify (through the wake page)
  if (h === "#signin") { history.replaceState(null, "", "#home"); $("signin").hidden = false; $("pkName").focus(); return show(); }   // the bar's Sign in, from another page
  let view = m ? "buy" : (h.slice(1).split("=")[0] || "home");
  if (!VIEWS.includes(view)) view = "home";
  for (const v of VIEWS) $("v-" + v).hidden = v !== view;
  document.documentElement.dataset.view = view;
  document.querySelectorAll("nav.roles a").forEach((a) => {
    a.classList.toggle("on", a.dataset.view === view);
    a.setAttribute("aria-current", a.dataset.view === view ? "page" : "false");
  });
  if (m) loadProduct(m[1]); else if (view === "buy") loadCrossings($("buyList"), true).then(() => released($("buyItems")));
  if (view === "home") loadHome();
  if (view === "make") loadMaker().then(() => released($("makeList")));
  if (view === "fund") loadFund(one && one[2]).then(() => released($("fundList")));
  if (view === "contribute") loadTasks(one && one[2]);
  if (view === "agents") loadAgents();
  if (window.KNOS_VIEW) window.KNOS_VIEW(view);       // projects + teams (valley.js)
}

// ---- home: the research products open for backing now (GET /api/front), each with three one-tap actions --------------
let BOARD = null;
async function board(fresh) {
  if (BOARD && !fresh) return BOARD;
  BOARD = await api("/api/front");
  return BOARD;
}
const pct = (a, b) => (b ? Math.max(2, Math.min(100, Math.round((100 * a) / b))) : 0);
function card(p) {
  const where = (p.where || []).join(", ");
  return `<li class="card hp-card" data-slug="${esc(p.slug)}"><p class="small muted"${where ? " data-qloo" : ""}>${esc([p.tech_name, p.paper, where].filter(Boolean).join(" · "))}${where ? (window.KnosDemand ? KnosDemand.src("", p.report) : "") : ""}</p>
    <h2 class="hp-t">${esc(p.title)}</h2>
    <div class="meter" aria-hidden="true"><span style="width:${pct(p.backed_units, p.reserve_units)}%"></span></div>
    <p class="small"><b>${esc(p.backed_units)}</b> ${t("of")} ${esc(p.reserve_units)} ${t("backed_l")}${p.escrow_units ? ` · <b>${esc(p.escrow_units)}</b> ${t("escrow_l")}` : ""}${p.maker ? "" : ` · ${t("maker_wanted")}`}</p>
    <div class="row acts"><a class="button" href="#buy=${esc(p.report)}">${t("back_btn")}</a>
      <a class="button ghost" href="#fund=${esc(p.slug)}">${t("fundm_btn")}</a>
      <a class="button ghost" href="#contribute=${esc(p.slug)}">${t("contrib_btn")}</a></div></li>`;
}
async function loadHome() {
  const box = $("homeList");
  try {
    const b = await board(true);
    box.removeAttribute("aria-busy");
    box.innerHTML = b.products.map(card).join("") + (b.crossing_now.length ? `<li class="note row"><span class="spin" aria-hidden="true"></span>${t("checking")}…</li>` : "") ||
      `<li class="empty">${t("empty")}</li>`;
    if (b.crossing_now.length && !b.products.length) setTimeout(() => { if (document.documentElement.dataset.view === "home") loadHome(); }, 5000);
  } catch (e) { box.removeAttribute("aria-busy"); box.innerHTML = `<li class="empty">${esc(e.message)}</li>`; }
}
async function product(slug) {
  for (let i = 0; i < 60; i++) {
    const p = await api("/api/front?slug=" + encodeURIComponent(slug));
    if (!p.pending) return p;
    slow(true, t("checking"));
    await new Promise((r) => setTimeout(r, 4000));
  }
  throw new Error(t("checking"));
}
async function goBack(slug) {
  try { const p = await product(slug); location.replace("#buy=" + p.report); } catch (e) { err(e); }
}
window.addEventListener("hashchange", show);

// ---- sign in -------------------------------------------------------------------------------------------------------
function b64u(buf) { return btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); }
function unb64u(s) { s = s.replace(/-/g, "+").replace(/_/g, "/"); const b = atob(s + "===".slice((s.length + 3) % 4)); return Uint8Array.from(b, (c) => c.charCodeAt(0)); }
function setSession(s) {
  session = s; try { s ? localStorage.setItem("knos.session", JSON.stringify(s)) : localStorage.removeItem("knos.session"); } catch (e) { /* private */ }
  $("whoBtn").textContent = s ? s.label : t("sign_in"); $("outBtn").hidden = !s; if (s) $("signin").hidden = true;
}
async function passkeyNew() {
  const ch = await api("/api/auth/challenge", {}); const label = $("pkName").value.trim() || "Knos user";
  const cred = await navigator.credentials.create({ publicKey: { challenge: unb64u(ch.challenge), rp: { name: "Knos", id: ch.rp_id },
    user: { id: crypto.getRandomValues(new Uint8Array(16)), name: label, displayName: label }, pubKeyCredParams: [{ type: "public-key", alg: -7 }],
    attestation: "none", timeout: 60000, authenticatorSelection: { residentKey: "preferred", userVerification: "preferred" } } });
  setSession(await api("/api/auth/passkey/register", { id: cred.id, clientDataJSON: b64u(cred.response.clientDataJSON),
    publicKey: b64u(cred.response.getPublicKey()), alg: cred.response.getPublicKeyAlgorithm(), label,
    authenticatorData: b64u(cred.response.getAuthenticatorData()) }));
}
async function passkeyUse() {
  const ch = await api("/api/auth/challenge", {});
  const a = await navigator.credentials.get({ publicKey: { challenge: unb64u(ch.challenge), rpId: ch.rp_id, userVerification: "preferred", timeout: 60000 } });
  setSession(await api("/api/auth/passkey/login", { id: a.id, clientDataJSON: b64u(a.response.clientDataJSON),
    authenticatorData: b64u(a.response.authenticatorData), signature: b64u(a.response.signature) }));
}
// The sheet shows only what works: a passkey is the one sign-in, for everyone, and it is the wallet that signs every
// payment. Nothing here needs an account anywhere. (A company signs in with its own SSO on /companies.)

// ---- researcher ----------------------------------------------------------------------------------------------------
const KIND = { memory: "Memory", paper: "Paper", qloo: "Qloo", decision: "Decision" };
function stepHtml(s) {
  // a Qloo call, or a decision made from Qloo's answers (who, where, the price tier, the hold): each links to its trace
  return `<li class="step ${esc(s.kind)}"${s.kind === "qloo" || s.kind === "decision" ? ` data-qloo data-call="${esc(s.call || "")}"` : ""}><div class="row"><span class="tag">${KIND[s.kind] || s.kind}</span><b>${esc(s.title)}</b><span class="muted small">${esc(s.at)}</span></div>` +
    (s.tool ? `<p class="small mono muted">${esc(s.tool)}</p>` : "") + (s.output ? `<p>${esc(s.output)}</p>` : "") +
    (s.effect ? `<p class="effect">→ ${esc(s.effect)}</p>` : "") +
    (s.input && typeof s.input === "object" ? `<details class="small"><summary>input</summary><pre>${esc(JSON.stringify(s.input, null, 1))}</pre></details>` : "") + "</li>";
}
async function cross() {
  const body = { ref: $("ref").value.trim() || undefined, idea: $("idea").value.trim() || undefined, product: $("product").value.trim() || undefined, place: $("place").value.trim() || undefined,
    ...(window.KnosDemand ? KnosDemand.values($("demandOpts")) : {}) };     // the Qloo families' options (static/demand_opts.js)
  const j = await api("/api/cross", body);
  $("timeline").hidden = false; $("steps").innerHTML = ""; $("outcome").innerHTML = ""; $("timeline").scrollIntoView({ behavior: "smooth" });
  $("stepsBox").open = true;                         // the log is open while the crossing runs, folded once the verdict is in
  let since = 0;
  if (window.Knos && Knos.streamCrossing) {          // static/ux_more.js: the steps pushed as they happen (Server-Sent Events)
    const done = await new Promise((res) => {
      const es = Knos.streamCrossing(j.id, (s) => { $("steps").insertAdjacentHTML("beforeend", stepHtml(s)); since++; }, res);
      if (!es) res(null); else es.addEventListener("error", () => res(null));
    });
    if (done && done.status === "done") {
      const p = await api(`/api/cross?id=${j.id}&since=${since}`);
      if (p.report) { const r = await api("/api/report?hash=" + p.report); report = r; outcome(r); }
      return;
    }
  }
  for (let i = 0; i < 400; i++) {
    const p = await api(`/api/cross?id=${j.id}&since=${since}`);
    for (const s of p.steps) $("steps").insertAdjacentHTML("beforeend", stepHtml(s));
    since = p.total;
    if (p.status !== "running") {
      if (p.status === "error") throw new Error(p.error || "stopped");
      if (p.report) { const r = await api("/api/report?hash=" + p.report); report = r; outcome(r); }
      return;
    }
    await new Promise((res) => setTimeout(res, 900));
  }
}
// each live Qloo step, once the report exists: its link to the trace (the redacted request, the result, the limit)
function linkSteps(r) {
  if (!window.KnosDemand || !r || !r.hash) return;
  for (const li of document.querySelectorAll("#steps li.step[data-qloo]")) {
    if (!li.querySelector("a[data-trace]")) li.insertAdjacentHTML("beforeend", `<p class="small muted">aggregate taste, not causal, not about a person ·${KnosDemand.src("", r.hash, li.dataset.call)}</p>`);
  }
}
function outcome(r) {
  linkSteps(r);
  $("stepsBox").open = false;
  const d = r.decision || {}, p = d.plan;
  const word = d.verdict === "OPEN" ? t("open_v") : d.verdict === "REFUSE" ? t("refuse") : t("cannot");
  const src = window.KnosDemand ? KnosDemand.src("", r.hash) : "";
  $("outcome").innerHTML = `<div class="decision ${esc((d.verdict || "").toLowerCase())}"><h3 data-qloo>${esc(word)}${src}</h3>` +
    (p ? `<p data-qloo><b>${t("for_l")}:</b> ${esc((p.who.age || "").replace(/_/g, " "))}, ${esc(p.who.gender)} · ${esc((p.who.segments || []).slice(0, 3).join(", "))}${(window.KnosDemand ? KnosDemand.src("", r.hash) : "")}</p>
      <p data-qloo><b>${t("where_l")}:</b> ${esc((p.where || []).join(", ") || "-")}${(window.KnosDemand ? KnosDemand.src("", r.hash) : "")}</p><p data-qloo><b>${t("price_l")}:</b> ${p.unit_price} ${esc(status.money_word || "test units")} (${esc(p.tier)})${(window.KnosDemand ? KnosDemand.src("", r.hash) : "")}</p>
      <p data-qloo><b>${t("goal_l")}:</b> ${p.target_units} · ${t("reserve")} ${p.reserve_units}${(window.KnosDemand ? KnosDemand.src("", r.hash) : "")}</p>
      <p><a class="button" href="#buy=${r.hash}">${t("open_product")}</a></p>` : `<ul>${(d.reasons || []).map((x) => `<li data-qloo>${esc(x)}${src}</li>`).join("")}</ul>`) + "</div>" +
    (window.KnosDemand ? KnosDemand.answers(r, "") : "") +
    `<p><button type="button" class="ghost" id="toBrief">Write a Ready brief from this check</button></p>`;
  $("toBrief").onclick = () => {       // the brief's project keeps this report: its Qloo facts ground the brief
    try { sessionStorage.setItem("knos.report", r.hash); } catch (e) { /* private window: the brief is still written */ }
    location.hash = "#projects";
  };
}

// ---- buyer ---------------------------------------------------------------------------------------------------------
async function loadCrossings(el, withTitle) {
  try {
    const b = await board(true);
    el.innerHTML = (withTitle ? `<h1>${t("buy_t")}</h1>` : "") + `<ul class="plist hp" id="buyItems">${b.products.map(card).join("") || `<li class="empty">${t("empty")}</li>`}</ul>` +
      `<p class="small"><a href="#research">${t("home_own")}</a></p>`;
    $("buyBox").hidden = true; $("tracker").hidden = true;
  } catch (e) { err(e); }
}
// the crossing Knos released on devnet (its facts, published with the front door): first in Pre-order, Back a milestone
// and Milestones and payouts, each with its whole record one press away
const CROSSING = "https://drexthealpha.github.io/Knos/crossing/7b4ed16b8c2903dc/";
let crossed = null;
async function released(list) {
  if (!list) return;
  crossed = crossed || fetch(CROSSING + "facts.json").then((r) => r.json()).catch(() => null);
  const f = await crossed;
  if (!f || list.querySelector("[data-crossing]")) return;
  const d = f.demand || {}, n = (f.orders || []).filter((o) => o.status === "released").length;
  list.querySelector(":scope > .empty")?.remove();
  list.insertAdjacentHTML("afterbegin", `<li class="card" data-crossing="${esc(f.project)}"><b>${esc(d.idea || f.title)}</b>
    <p class="small">${esc(n)} pre-orders from ${esc(d.city || "")} · ${f.status === "released" ? "Released by the referee's verdict" : esc(f.status)}</p>
    <p class="small"><a href="${CROSSING}">The whole crossing</a></p></li>`);
}
async function loadProduct(h) {
  try {
    const r = await api("/api/report?hash=" + h); report = r;
    const d = r.decision || {}, p = d.plan || {}, rs = r.research;
    $("productCard").innerHTML = `<p class="small muted">${esc(r.label)}</p><h1>${esc(r.idea)}</h1>` +
      (rs ? `<p class="small">${esc(rs.title)} (${esc(rs.year)}; cited ${esc(rs.cited_by_count)})${rs.regulator ? ` · <b>${esc(rs.regulator)}</b>` : ""} <a href="${esc(rs.proven_result.source || "#")}" target="_blank" rel="noopener">→</a> <span class="muted" data-source="openalex">paper data: OpenAlex and Crossref, not Qloo</span></p>` : "") +
      (p.who ? `<div class="grid"><div data-qloo><h3>${t("for_l")}</h3><p>${esc((p.who.age || "").replace(/_/g, " "))}, ${esc(p.who.gender)}</p><p class="small muted">${esc((p.who.segments || []).join(", "))}</p>${(window.KnosDemand ? KnosDemand.src("", r.hash) : "")}</div>
        <div data-qloo><h3>${t("where_l")}</h3><p>${esc((p.where || []).join(", "))}${(window.KnosDemand ? KnosDemand.src("", r.hash) : "")}</p></div><div data-qloo><h3>${t("price_l")}</h3><p>${p.unit_price} / ${esc(p.tier)}${(window.KnosDemand ? KnosDemand.src("", r.hash) : "")}</p></div>
        <div data-qloo><h3>${t("goal_l")}</h3><p>${t("target")} ${p.target_units} · ${t("reserve")} ${p.reserve_units}${(window.KnosDemand ? KnosDemand.src("", r.hash) : "")}</p></div></div>` +
        (p.unserved_audience && p.unserved_audience.length ? `<p class="small" data-qloo>${t("unserved_l")}: ${esc(p.unserved_audience.join(", "))}${(window.KnosDemand ? KnosDemand.src("", r.hash) : "")}</p>` : "")
        : `<div class="decision ${esc((d.verdict || "").toLowerCase())}">${esc((d.reasons || []).join("; "))}</div>`);
    $("buyBox").hidden = d.verdict !== "OPEN";
    // no maker has claimed it yet: a buyer commits (an allowance, paid only when it is made) instead of pre-ordering
    const fp = await api("/api/front?slug=" + h).catch(() => null);
    report.front = fp && !fp.pending ? fp : null;
    const noMaker = !!(report.front && !report.front.maker && report.front.project && report.front.first_milestone);
    $("noMaker").hidden = !noMaker; $("preBtn").hidden = noMaker;
    loadWallet();
    if (r.limits) $("productCard").insertAdjacentHTML("beforeend", `<p class="small muted">${esc(r.limits)}</p>`);
    const all = [...(r.matches || []).map((m) => ({ ...m, kept: true })), ...(r.unrelated || []).map((u) => ({ name: u.name, kept: false }))];
    if (all.length) $("productCard").insertAdjacentHTML("beforeend",
      `<details class="small"><summary>Show all Qloo matches (${all.length})</summary>` +
      all.map((m) => `<p class="small" data-qloo>${esc(m.name)} <span class="muted">${m.kept ? "counted" : "left out: " + esc(m.why || "shares too few of the idea's words")}</span>${(window.KnosDemand ? KnosDemand.src("", r.hash, 1) : "")}</p>`).join("") + "</details>");
    if (r.fees && r.fees.text) $("feeLine").textContent = r.fees.text + ".";
    const action = `${location.origin}/api/actions/preorder?report=${r.hash}`;
    $("blinkLink").href = "https://dial.to/?action=" + encodeURIComponent("solana-action:" + action) + "&cluster=devnet";
    $("tracker").hidden = false;
    const res = r.reserve || {};
    $("trackList").innerHTML = (res.reserve_units ? `<li>${t("reserve")}: ${res.pre_ordered_units} / ${res.reserve_units} <progress max="${res.reserve_units}" value="${Math.min(res.pre_ordered_units, res.reserve_units)}"></progress></li>` : "") +
      ((r.preorders || []).map((o) => `<li>${esc(o.units)} · <b>${esc(o.status)}</b> · <a href="${X(o.order, "address")}" target="_blank" rel="noopener">${short(o.order)}</a></li>`).join("") || `<li class="muted">${t("empty")}</li>`);
  } catch (e) { err(e); }
}
// what Sibyl keeps of the receipt's record line: its tier and the verdict Sibyl's search gives for it (valley.remembered)
const sibylLine = (s) => (s && s.tier ? `<p class="small" data-sibyl>Remembered by Sibyl: ${esc(s.tier)}, verdict ${esc(s.verdict || "none")}</p>` : "");
function receipt(p) {
  const sigs = p.signatures || {};
  $("receipt").innerHTML = `<div class="decision open"><h3>${t("receipt_t")}</h3><p class="testmoney">${t("test_money")}</p><p>${esc(p.units)} · <a href="${X(p.commitment, "address")}" target="_blank" rel="noopener">${short(p.commitment)}</a></p>` +
    Object.entries(sigs).map(([k, s]) => `<p class="small">${esc(k.replace(/_/g, " "))}: <a href="${X(s)}" target="_blank" rel="noopener">${short(s)}</a>${p.finality && p.finality[k] ? ` <span class="muted">· final in ${p.finality[k].final_ms} ms (${esc(p.finality[k].commitment)})</span>` : ""}</p>`).join("") +
    (p.verified && p.verified.chain_pin ? `<p class="small">${t("evidence_pin")}: <span class="mono">${esc(p.verified.chain_pin.slice(0, 16))}…</span><br>${t("page_sha")}: <span class="mono">${esc((p.verified.sha256 || "").slice(0, 16))}…</span></p>` : "") +
    (p.verifier ? `<p class="small muted">${esc(p.verifier)}</p>` : "") + sibylLine(p.sibyl) +
    `<p class="small muted">${t("claim_id")}: <span class="mono">${esc(p.claim_id)}</span></p></div>` +
    `<p class="small" id="receipt-final" aria-live="polite"></p>`;
  const lock = sigs.lock || sigs.preorder || sigs.fund || Object.values(sigs)[0];
  if (lock && window.Knos) {          // static/ux.js: the signature's finality, pushed over devnet's WebSocket and timed here
    Knos.haptic(sigs.release || sigs.referee_group_pass ? "release" : "lock");
    $("receipt-final").textContent = "Waiting for finality…";
    Knos.finality(lock).then((r) => { $("receipt-final").textContent = r.seconds ? `Finalized in ${r.seconds.toFixed(1)} s (${r.via}).` : "Not finalized yet."; });
  }
}
async function loadWeb3() {
  if (window.solanaWeb3) return window.solanaWeb3;
  await new Promise((res, rej) => { const s = document.createElement("script"); s.src = "https://unpkg.com/@solana/web3.js@1.98.0/lib/index.iife.min.js"; s.onload = res; s.onerror = rej; document.head.appendChild(s); });
  return window.solanaWeb3;
}
async function walletPreorder() {
  const w = window.phantom && window.phantom.solana || window.solflare || window.solana;
  if (!w) { window.open($("blinkLink").href, "_blank"); throw new Error("No wallet here: the Blink opened in a new tab."); }
  const web3 = await loadWeb3(); await w.connect(); const account = w.publicKey.toString();
  const r = await fetch(`/api/actions/preorder?report=${report.hash}&units=${parseInt($("units").value, 10)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ account }) });
  const a = await r.json(); if (!r.ok) throw new Error(a.message || "failed");
  const tx = web3.Transaction.from(Uint8Array.from(atob(a.transaction), (c) => c.charCodeAt(0)));
  const signed = await w.signTransaction(tx);
  const sig = await new web3.Connection("https://api.devnet.solana.com", "confirmed").sendRawTransaction(signed.serialize());
  receipt({ units: $("units").value, commitment: a.commitment, signatures: { lock: sig }, claim_id: a.claim_id || "…" });
  setTimeout(() => loadProduct(report.hash), 8000);
}

// ---- funder --------------------------------------------------------------------------------------------------------
// One passkey step, shown in the card that asked for it (a note under the button; never a wall of text).
function inCard(b, fn) {
  return async () => {
    const card = b.closest("li"); card.querySelectorAll(".note").forEach((n) => n.remove());
    const put = (cls, html) => card.insertAdjacentHTML("beforeend", `<div class="note ${cls}" role="status">${html}</div>`);
    if (!session) { $("signin").hidden = false; $("pkNew").focus(); put("err", esc(t("err_signin"))); return; }
    const was = b.textContent; b.disabled = true; b.textContent = t("pk_sign") + "…";
    try { put("ok", await fn(card)); } catch (e) { put("err", esc(e.message)); } finally { b.disabled = false; b.textContent = was; }
  };
}
const tx = (sig) => (sig ? ` · <a href="${X(sig)}" target="_blank" rel="noopener">tx ${short(sig)} ↗</a>` : "");
async function fundMilestone(p, units) {
  const got = await KnosPasskey.approve(await api("/api/project/fund", { passkey: true, project: p.project, milestone: p.first_milestone, units, kind: "funder" }), api);
  return `${sibylLine(got.sibyl)}✓ ${esc(got.units)} ${t("escrow_l")} · <a href="${esc(got.explorer)}" target="_blank" rel="noopener">money held ${short(got.order)} ↗</a>${tx((got.signatures || {}).lock)} · <a href="#projects=${esc(p.project)}">${t("open_project")}</a>`;
}
async function loadFund(focus) {
  try {
    const b = await board(true);
    const rows = b.products.filter((p) => p.project && p.first_milestone);
    $("fundList").innerHTML = rows.map((p) => `<li class="card${focus === p.slug ? " on" : ""}" data-slug="${esc(p.slug)}"><b>${esc(p.title)}</b>
      <p class="small muted">${esc(p.escrow_units)} ${t("escrow_l")}</p>
      <div class="row"><input class="fu" type="number" min="5" max="1000" value="10" aria-label="${t("units")}" style="max-width:110px">
        <button class="fundBtn" data-slug="${esc(p.slug)}" type="button">${t("fundm_btn")}</button></div></li>`).join("") || `<li class="empty">${t("empty")}</li>`;
    document.querySelectorAll(".fundBtn").forEach((btn) => { const p = rows.find((x) => x.slug === btn.dataset.slug);
      btn.onclick = inCard(btn, (cardEl) => fundMilestone(p, parseInt(cardEl.querySelector(".fu").value, 10))); });
    const f = focus && document.querySelector(`#fundList li[data-slug="${focus}"]`);
    if (f) f.scrollIntoView({ block: "center" });
  } catch (e) { err(e); }
}
// the wallet's track-record badges (Token-2022, non-transferable), read from devnet: getTokenAccountsByOwner, then each
// one's balance with getTokenAccountBalance
async function badges(owner) {
  const rpc = (m, p) => fetch("https://api.devnet.solana.com", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: m, params: p }) }).then((r) => r.json()).then((j) => j.result);
  const got = await rpc("getTokenAccountsByOwner", [owner, { programId: "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb" }, { encoding: "jsonParsed" }]);
  const rows = (got && got.value) || [];
  const bal = await Promise.all(rows.map((a) => rpc("getTokenAccountBalance", [a.pubkey]).catch(() => null)));
  let el = $("pkBadges");
  if (!el) { $("pkWallet").insertAdjacentHTML("beforeend", `<p class="small" id="pkBadges"></p>`); el = $("pkBadges"); }
  el.innerHTML = rows.length ? `Track-record badges: ${rows.map((a, i) => `<a href="${X(a.account.data.parsed.info.mint, "address")}" rel="noopener">${short(a.account.data.parsed.info.mint)}</a> ×${esc((bal[i] && bal[i].value && bal[i].value.uiAmountString) || "1")}`).join(" · ")}` : "No track-record badges yet: a verified milestone gives one.";
}
async function loadWallet() {
  if (!session || session.kind !== "passkey") { $("pkWallet").hidden = true; return; }
  try { const w = await api("/api/wallet", {}); $("pkWallet").hidden = false; $("pkVault").textContent = short(w.vault); $("pkVault").href = w.explorer; $("pkUnits").textContent = w.balance_units;
    badges(w.vault).catch(() => {}); }
  catch (e) { $("pkWallet").hidden = true; }
}
// server notes the page knows are shown in the reader's language (the server's English stays in the API)
function viaLabel(c) { return { preorder: t("via_preorder"), funder: t("via_funder"), blink: t("via_blink") }[c.via_kind] || c.via || ""; }
function receiptInto(el, p) {
  el.insertAdjacentHTML("beforeend", `<p class="small">✓ ${esc(p.units)} → <a href="${X(p.commitment, "address")}" target="_blank" rel="noopener">${short(p.commitment)}</a>${(p.signatures || {}).lock ? ` · <a href="${X(p.signatures.lock)}" target="_blank" rel="noopener">${short(p.signatures.lock)}</a>` : ""}</p>`);
}

// ---- contributor ---------------------------------------------------------------------------------------------------
async function loadNeed(focus) {
  const b = await board(true).catch(() => ({ products: [] }));
  const rows = b.products.filter((p) => p.project && p.first_milestone);
  $("needList").innerHTML = rows.map((p) => `<li class="card${focus === p.slug ? " on" : ""}" data-slug="${esc(p.slug)}"><b>${esc(p.title)}</b>
    <p class="small muted">${esc(p.open_milestones)} ${t("open_ms")}</p>
    <button class="makeBtn" data-slug="${esc(p.slug)}" type="button">${t("make_btn")}</button> <a class="small" href="#projects=${esc(p.project)}">${t("open_project")}</a></li>`).join("") ||
    `<li class="empty">${t("empty")}</li>`;
  document.querySelectorAll(".makeBtn").forEach((btn) => { const p = rows.find((x) => x.slug === btn.dataset.slug);
    btn.onclick = inCard(btn, async () => {
      const a = await api("/api/project/claim", { passkey: true, project: p.project, milestone: p.first_milestone });
      return `✓ ${t("attempt_l")} <span class="mono">${esc(a.id)}</span> · ${t("paid_passkey")} · <a href="#projects=${esc(p.project)}">${t("open_project")}</a>`;
    }); });
  const f = focus && document.querySelector(`#needList li[data-slug="${focus}"]`);
  if (f) f.scrollIntoView({ block: "center" });
}
async function loadTasks(focus) {
  loadNeed(focus);
  try {
    const got = await api("/api/tasks");
    const box = $("taskBox");
    box.innerHTML = (got.rounds && got.rounds.length ? got.rounds.map((r) => { const s = r.submit || {}; return `<div class="card"><div class="row spread"><h3>${esc(r.title || r.id)}</h3><span class="testmoney">${t("test_money")}</span></div>
      <p class="small muted">${esc(r.label || "")}</p>
      <p><b>What to submit:</b> ${esc(s.what || "")}. Start from <a href="${esc(s.baseline || "#")}" target="_blank" rel="noopener">${esc(s.file || "train.py")}</a> and read the <a href="${esc(s.readme || "#")}" target="_blank" rel="noopener">task's README</a>.</p>
      <p class="small muted">Round ${esc(r.round)} · ${esc(String(r.players ?? 0))} players · up to ${esc(s.attempts_per_round)} attempts per round · ${esc(s.time_budget_s)} s per run · ${esc(s.prize || "")}</p>
      <label for="tn-${esc(r.id)}">Your name</label><input id="tn-${esc(r.id)}" class="tname" data-g="${esc(r.id)}" maxlength="40" placeholder="ada">
      <label for="tw-${esc(r.id)}">Payout wallet (devnet, optional)</label><input id="tw-${esc(r.id)}" class="twal" data-g="${esc(r.id)}" maxlength="44" placeholder="Solana address">
      <label for="ts-${esc(r.id)}">The whole ${esc(s.file || "train.py")}</label><textarea id="ts-${esc(r.id)}" class="tsub mono" data-g="${esc(r.id)}" rows="8" maxlength="100000"></textarea>
      <button class="tBtn" data-g="${esc(r.id)}" type="button">Submit work</button></div>`; }).join("") :
      `<p class="note">${t("contribute_none")} ${esc(got.why || "")}</p>`) +
      (got.milestones && got.milestones.length ? `<ul class="list">` + got.milestones.map((m) => `<li>${esc((m.idea || "").slice(0, 70))} · <span class="mono small">${esc(m.claim_id)}</span> · <a href="#make">${t("milestone_prove")}</a></li>`).join("") + "</ul>" : "");
    document.querySelectorAll(".tBtn").forEach((b) => b.onclick = async () => {
      const card = b.closest(".card"); card.querySelectorAll(".note").forEach((n) => n.remove());
      const put = (cls, html) => card.insertAdjacentHTML("beforeend", `<div class="note ${cls}" role="status">${html}</div>`);
      if (!session) { $("signin").hidden = false; $("pkNew").focus(); put("err", esc(t("err_signin"))); return; }
      const g = b.dataset.g, was = b.textContent; b.disabled = true; b.textContent = "Judging…";
      try {
        const out = await api("/api/task/submit", { round: g, name: card.querySelector(".tname").value, wallet: card.querySelector(".twal").value || undefined, code: card.querySelector(".tsub").value });
        const r = out.result || {}, pz = out.prize;
        put(r.decision === "scored" ? "ok" : "", `<b>${esc(out.name)}</b>, attempt ${esc(r.n)}: <b>${esc(r.decision)}</b>${r.shown != null ? ` · shown score ${esc(r.shown)}` : ""}` +
          (r.reasons && r.reasons.length ? `<br><span class="small">${esc(r.reasons.join("; "))}</span>` : "") +
          `<br><span class="small mono">sha256 ${esc(String(r.sha256 || "").slice(0, 16))}… (your file: ${esc(out.submitted_sha256.slice(0, 16))}…)</span>` +
          (pz ? `<br>${pz.paid ? `Prize: ${esc(pz.units)} test units → <a href="${esc((pz.explorer || []).slice(-1)[0] || "#")}" target="_blank" rel="noopener">release ↗</a>` :
            pz.status === "signing" ? `<span class="prizeSigning">Prize: ${esc(pz.units)} test units locked (<a href="${esc((pz.explorer || [])[0] || "#")}" target="_blank" rel="noopener">tx ↗</a>), funded by the round's sponsor; released when 2 of 3 referee hosts sign (session <span class="mono">${esc(String(pz.session).slice(0, 8))}</span>)</span>` :
            `Prize not paid: ${esc(pz.why || "")}`}` : ""));
      } catch (e) { put("err", esc(e.message)); } finally { b.disabled = false; b.textContent = was; }
    });
  } catch (e) { err(e); }
  $("v-contribute").dataset.tasks = "1";        // the rounds have their place: what follows them is shown where it stays (style.css)
}

// ---- maker ---------------------------------------------------------------------------------------------------------
async function loadMaker() {
  try {
    const { commitments } = await api("/api/commitments");
    $("makeList").innerHTML = commitments.map((c) => `<li class="card"><b>${esc((c.idea || "").slice(0, 80))}</b> · ${esc(c.units)} × ${esc(c.unit_price)} · <b>${esc(c.status)}</b>
      <p class="small"><a href="${X(c.commitment, "address")}" target="_blank" rel="noopener">${short(c.commitment)}</a> · <span class="mono">${esc(c.claim_id)}</span> · ${esc(viaLabel(c))}</p>
      ${Object.entries(c.signatures || {}).map(([k, s]) => `<span class="small">${esc(k.replace(/_/g, " "))}: <a href="${X(s)}" target="_blank" rel="noopener">${short(s)}</a></span>`).join(" · ")}
      ${c.status === "locked" ? `<label>${t("evidence_url")}</label><div class="row"><input class="ev" data-c="${esc(c.commitment)}" type="url" placeholder="https://…"><button class="msBtn" data-c="${esc(c.commitment)}" type="button">${t("milestone_prove")}</button></div>` : ""}</li>`).join("") || `<li class="empty">${t("empty")}</li>`;
    document.querySelectorAll(".msBtn").forEach((b) => b.onclick = () => busy(b, t("loading"), async () => {
      if (!session) { $("signin").hidden = false; throw new Error(t("err_signin")); }
      const url = document.querySelector(`.ev[data-c="${b.dataset.c}"]`).value;
      const got = await api("/api/milestone", { commitment: b.dataset.c, evidence_url: url });
      receipt(got); loadMaker(); }));
  } catch (e) { err(e); }
}

// ---- agents --------------------------------------------------------------------------------------------------------
async function loadAgents() {
  $("mcpUrl").textContent = location.origin + "/mcp";
  const box = $("memBox");
  if (box && !box.dataset.wired) {
    box.dataset.wired = "1";
    box.querySelector("input").placeholder = t("mem_search");
    box.querySelector("form").onsubmit = async (ev) => {
      ev.preventDefault(); const out = box.querySelector(".memOut");
      out.innerHTML = `<span class="spin"></span>`;
      try {
        const g = await api("/api/memory/search?q=" + encodeURIComponent(box.querySelector("input").value));
        out.innerHTML = `<p class="small muted">${esc(g.said || "")}</p>` +
          (g.rows || []).map((r) => `<p class="small"><span class="tag">${esc(r.tier || "")}</span>${esc(r.name || r.key || r.doc_key || "")} <span class="muted">${esc((r.snippet || "").slice(0, 140))}</span></p>`).join("");
      } catch (e) { out.innerHTML = `<p class="small muted">${esc(e.message)}</p>`; }
    };
  }
  try {
    const r = await fetch("/mcp", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }) });
    const j = await r.json();
    $("mcpTools").innerHTML = ((j.result || {}).tools || []).map((x) => `<p><b class="mono">${esc(x.name)}</b><br><span class="small muted">${esc(x.description)}</span></p>`).join("");
  } catch (e) { $("mcpTools").innerHTML = ""; }
}

// ---- boot ----------------------------------------------------------------------------------------------------------
async function boot() {
  langMenu(); applyLang();
  const h = location.hash;
  const m = h.match(/session=([^&]+)/);
  if (m) { try { const tok = decodeURIComponent(m[1]); const b = tok.split(".")[0]; const pad = b + "===".slice((b.length + 3) % 4); setSession({ token: tok, ...JSON.parse(atob(pad.replace(/-/g, "+").replace(/_/g, "/"))) }); } catch (e) { } history.replaceState(null, "", "#home"); }
  const mg = h.match(/magic=([^&]+)/);
  if (mg) { try { setSession(await api("/api/auth/email/verify", { token: decodeURIComponent(mg[1]) })); } catch (e) { err(e); } history.replaceState(null, "", "#home"); }
  setSession(session);
  try {
    status = await api("/api/status");
    const rest = status.qloo_rest || {};
    // live only while Qloo answers: its 429 pause (GET /api/qloo/status, this server's own traffic) says limited
    const limited = rest.rest && (await api("/api/qloo/status").catch(() => ({}))).limited === true;
    $("modeBadge").textContent = limited ? t("status_limited") : rest.rest ? t("status_live") : t("status_off");
    $("modeBadge").className = "badge " + (rest.rest && !limited ? "live" : "off");
    const a = status.auth || {};
    if (!a.passkey || !window.PublicKeyCredential) { $("pkNew").disabled = $("pkUse").disabled = true; $("pkNote").textContent = t("pk_none"); }
  } catch (e) { err(e); }
  show();
}
$("whoBtn").onclick = (ev) => { ev.preventDefault(); const sh = $("signin"); sh.hidden = !sh.hidden; if (!sh.hidden) $("pkName").focus(); };
$("signinClose").onclick = () => { $("signin").hidden = true; $("whoBtn").focus(); };
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !$("signin").hidden) { $("signin").hidden = true; $("whoBtn").focus(); } });
$("outBtn").onclick = () => setSession(null);
$("pkNew").onclick = () => busy($("pkNew"), t("loading"), passkeyNew);
$("pkUse").onclick = () => busy($("pkUse"), t("loading"), passkeyUse);
document.querySelectorAll(".chip").forEach((c) => c.onclick = () => { $("ref").value = c.dataset.ref; });
$("crossForm").onsubmit = (ev) => { ev.preventDefault(); busy($("crossBtn"), t("cross_busy"), cross); };
// the demand options draw once the deferred script is there (DOMContentLoaded runs after every deferred script)
document.addEventListener("DOMContentLoaded", () => { if (window.KnosDemand) KnosDemand.mount($("demandOpts"), ""); });
$("walletBtn").onclick = () => busy($("walletBtn"), t("loading"), walletPreorder);
$("preBtn").onclick = () => busy($("preBtn"), t("loading"), async () => {
  if (!session) { $("signin").hidden = false; throw new Error(t("err_signin")); }
  const step = await api("/api/preorder", { report: report.hash, units: parseInt($("units").value, 10) });
  const p = await KnosPasskey.approve(step, api); receipt(p); loadProduct(report.hash); });
$("faucetBtn").onclick = () => busy($("faucetBtn"), t("loading"), async () => { await api("/api/wallet/faucet", {}); loadWallet(); });
// devnet SOL from the cluster's own faucet (requestAirdrop): rate limited per address and per day, which it says
$("solBtn").onclick = () => busy($("solBtn"), t("loading"), async () => {
  const w = await api("/api/wallet", {});
  const r = await fetch("https://api.devnet.solana.com", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "requestAirdrop", params: [w.vault, 500000000] }) }).then((x) => x.json()).catch((e) => ({ error: { message: e.message } }));
  $("solOut").innerHTML = r.result ? `0.5 devnet SOL on its way: <a href="${X(r.result)}" rel="noopener">${short(r.result)}</a>. Devnet may reset.`
    : `The devnet faucet said no (${esc((r.error || {}).message || "unknown")}): try <a href="https://faucet.solana.com" rel="noopener">faucet.solana.com</a>.`;
});
$("claimBtn").onclick = () => busy($("claimBtn"), t("loading"), async () => {
  if (!session) { $("signin").hidden = false; throw new Error(t("err_signin")); }
  const c = await api("/api/maker/claim", { report: report.hash }); await loadProduct(report.hash);
  $("claimNote").textContent = `${t("claimed")}: ${c.maker} · ${short(c.main_wallet)}`; });
$("amcBtn").onclick = () => busy($("amcBtn"), t("pk_sign"), async () => {
  if (!session) { $("signin").hidden = false; throw new Error(t("err_signin")); }
  const p = report.front, units = parseInt($("units").value, 10) * ((((report.decision || {}).plan) || {}).unit_price || 1);
  const got = await KnosPasskey.approve(await api("/api/project/amc", { passkey: true, project: p.project, milestone: p.first_milestone, units }), api);
  $("receipt").innerHTML = `<div class="decision open"><h3>${t("committed_l")}</h3><p class="testmoney">${t("test_money")}</p><p>${esc(got.units)} · ${t("amc_rule")}${tx((got.signatures || {}).approve)}</p></div>`; });
boot();
