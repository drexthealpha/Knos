// The app for the least technical person: the same flows, with fewer things to read and more ways to give input.
//   Knos.finality(sig)   signatureSubscribe over devnet's WebSocket: resolves when the signature is finalized, with the
//                        measured seconds from the call (no polling); getSignatureStatuses answers if the socket cannot
//   Knos.haptic(kind)    a short vibration on lock and release (navigator.vibrate, where the device has it)
//   Knos.queue(path, b)  a POST kept in IndexedDB while offline and sent by Background Sync later (static/sw.js)
//   display sheet        simpler mode, high contrast, dyslexia-friendly type, reduced motion, left/right hand; kept per
//                        device; a triple tap anywhere switches simpler mode (the emergency simple mode)
//   voice                a microphone button on the brief's text fields (Web Speech API, where the browser has it)
//   camera               "Photo of the paper or evidence": the camera's picture, signed with C2PA by the server
//   frustration cue      three fast taps on the same control, or a field cleared twice, offers simpler mode once
//   saving data          Data Saver, a 2G link or a low battery not charging: lite mode (no motion, no prefetch)
//   prefetch             a press on a tab asks for its data before the view opens
//   "what is happening"  a pill that says when the app is talking to devnet or the server, and stops when it is done
"use strict";
(function () {
  const WSS = "wss://api.devnet.solana.com", RPC = "https://api.devnet.solana.com";
  const store = { get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } } };
  const root = document.documentElement;
  const Knos = window.Knos = window.Knos || {};

  Knos.finality = function (sig, timeoutMs = 90000) {
    const t0 = performance.now();
    const viaStatus = async () => {
      for (let i = 0; i < 45; i++) {
        const r = await fetch(RPC, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "getSignatureStatuses", params: [[sig], { searchTransactionHistory: true }] }) }).then((x) => x.json()).catch(() => null);
        const v = r && r.result && r.result.value[0];
        if (v && v.confirmationStatus === "finalized") return { seconds: (performance.now() - t0) / 1000, err: v.err, via: "getSignatureStatuses" };
        await new Promise((ok) => setTimeout(ok, 2000));
      }
      return { seconds: null, err: "not finalized yet", via: "getSignatureStatuses" };
    };
    if (!window.WebSocket) return viaStatus();
    return new Promise((ok) => {
      let done = false;
      const ws = new WebSocket(WSS);
      let sub = null;           // a notified signature's stream ends by itself; one still open (a timeout) is unsubscribed
      const end = (v) => { if (!done) { done = true; try { if (sub !== null && !v.via.startsWith("signatureSubscribe")) ws.send(JSON.stringify({ jsonrpc: "2.0", id: 2, method: "signatureUnsubscribe", params: [sub] })); ws.close(); } catch (e) { /* closed */ } ok(v); } };
      ws.onopen = () => ws.send(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "signatureSubscribe", params: [sig, { commitment: "finalized" }] }));
      ws.onmessage = (ev) => {
        const m = JSON.parse(ev.data);
        if (m.id === 1 && typeof m.result === "number") sub = m.result;
        if (m.method === "signatureNotification") end({ seconds: (performance.now() - t0) / 1000, err: m.params.result.value.err, via: "signatureSubscribe" });
      };
      ws.onerror = () => viaStatus().then(end);
      setTimeout(() => viaStatus().then(end), timeoutMs);
    });
  };

  Knos.haptic = function (kind) {
    if (navigator.vibrate && !root.classList.contains("reduce-motion")) navigator.vibrate(kind === "release" ? [30, 60, 30] : 40);
  };

  function idb() {
    return new Promise((ok, bad) => { const r = indexedDB.open("knos-queue", 1); r.onupgradeneeded = () => r.result.createObjectStore("q", { autoIncrement: true });
      r.onsuccess = () => ok(r.result); r.onerror = () => bad(r.error); });
  }
  Knos.queue = async function (path, body, auth) {
    if (navigator.onLine) return fetch(path, { method: "POST", headers: { "Content-Type": "application/json", ...(auth ? { Authorization: auth } : {}) }, body: JSON.stringify(body) });
    const d = await idb();
    await new Promise((ok) => { const t = d.transaction("q", "readwrite"); t.objectStore("q").add({ path, body, auth }); t.oncomplete = ok; });
    const reg = await navigator.serviceWorker?.ready;
    if (reg && reg.sync) await reg.sync.register("knos-queue");
    say("Saved offline: it is sent when you are back online.");
    return null;
  };

  // ---- display sheet ------------------------------------------------------------------------------------------------
  const MODES = [["simple", "Make it simpler"], ["contrast", "High contrast"], ["dyslexia", "Easier-to-read type"], ["reduce-motion", "Reduced motion"], ["left-hand", "Left-hand mode"]];
  for (const [m] of MODES) if (store.get("knos.mode." + m) === "1") root.classList.add(m);
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) root.classList.add("reduce-motion");
  if (matchMedia("(prefers-contrast: more)").matches) root.classList.add("contrast");
  function setMode(m, on) { root.classList.toggle(m, on); store.set("knos.mode." + m, on ? "1" : "0"); const b = document.getElementById("mode-" + m); if (b) b.setAttribute("aria-pressed", on); }
  function sheet() {
    const s = document.createElement("div");
    s.id = "ux-sheet"; s.className = "ux-sheet"; s.setAttribute("role", "dialog"); s.setAttribute("aria-label", "Display"); s.hidden = true;
    s.innerHTML = `<p class="small"><strong>Display</strong></p>` + MODES.map(([m, label]) =>
      `<button type="button" class="quiet" id="mode-${m}" aria-pressed="${root.classList.contains(m)}">${label}</button>`).join("") +
      `<button type="button" class="ghost" id="ux-close">Done</button>`;
    document.body.appendChild(s);
    for (const [m] of MODES) s.querySelector("#mode-" + m).onclick = () => setMode(m, !root.classList.contains(m));
    s.querySelector("#ux-close").onclick = () => { s.hidden = true; };
    const fab = document.createElement("button");
    // in the footer, never floating over the page (scripts/test_layout_audit.mjs: no button covers a card)
    fab.type = "button"; fab.id = "ux-fab"; fab.className = "quiet"; fab.textContent = "Display"; fab.setAttribute("aria-label", "Display: simpler, contrast, type, motion");
    fab.onclick = () => { s.hidden = !s.hidden; };
    (document.getElementById("footTools") || document.querySelector("footer") || document.body).appendChild(fab);
  }
  let taps = [];
  document.addEventListener("pointerdown", (e) => {
    const now = Date.now(); taps = taps.filter((t) => now - t.at < 600); taps.push({ at: now, el: e.target });
    if (taps.length >= 3 && taps.every((t) => t.el === e.target) && !e.target.closest("input, textarea, button, a, select")) { setMode("simple", !root.classList.contains("simple")); taps = []; say(root.classList.contains("simple") ? "Simpler mode on" : "Simpler mode off"); }
    else if (taps.length >= 3 && taps.every((t) => t.el === e.target) && !offered) { offered = true; say("Stuck? The Aa button makes this simpler."); }
  }, { passive: true });
  let offered = false, clears = 0;
  document.addEventListener("input", (e) => { if (e.target.value === "" && ++clears >= 2 && !offered) { offered = true; say("Stuck? The Aa button makes this simpler."); } });

  // ---- lite mode: Data Saver, a slow link, a low battery not charging ----------------------------------------------
  const c = navigator.connection;
  if (c && (c.saveData || /2g/.test(c.effectiveType || ""))) root.classList.add("lite", "reduce-motion");
  if (navigator.getBattery) navigator.getBattery().then((b) => { if (b.level < 0.2 && !b.charging) root.classList.add("lite", "reduce-motion"); }).catch(() => {});

  // ---- voice and camera on the brief --------------------------------------------------------------------------------
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  function voice() {
    if (!SR) return;
    for (const id of ["bName", "bTarget", "pTitle"]) {
      const f = document.getElementById(id);
      if (!f || f.dataset.voice) continue;
      f.dataset.voice = "1";
      const b = document.createElement("button");
      b.type = "button"; b.className = "quiet mic"; b.textContent = "🎤"; b.setAttribute("aria-label", "Say it: " + (f.labels && f.labels[0] ? f.labels[0].textContent : id));
      b.onclick = () => { const r = new SR(); r.lang = root.lang || "en"; r.interimResults = false;
        r.onresult = (ev) => { f.value = ev.results[0][0].transcript; f.dispatchEvent(new Event("input", { bubbles: true })); }; r.start(); };
      f.insertAdjacentElement("afterend", b);
    }
  }
  function camera() {
    const box = document.getElementById("briefBox");
    if (!box || document.getElementById("bPhoto")) return;
    box.insertAdjacentHTML("beforeend", `<label for="bPhoto" class="small">Photo of the paper or evidence</label>
      <input id="bPhoto" type="file" accept="image/*" capture="environment"><p id="bPhotoOut" class="small" aria-live="polite"></p>`);
    document.getElementById("bPhoto").onchange = async (e) => {
      const f = e.target.files[0]; if (!f) return;
      let token = null; try { token = (JSON.parse(store.get("knos.session") || "null") || {}).token; } catch (x) { /* none */ }
      if (!token) { document.getElementById("bPhotoOut").textContent = "Sign in first to sign the photo."; return; }
      const r = await fetch("/api/evidence/c2pa", { method: "POST", body: f, headers: { Authorization: "Bearer " + token, "Content-Type": f.type || "image/jpeg", "X-Claim-Id": "brief-photo-" + Date.now() } });
      const j = await r.json().catch(() => ({}));
      document.getElementById("bPhotoOut").textContent = r.ok ? `Signed with C2PA (${Math.round((j.bytes || f.size) / 1024)} KB): the photo now carries who took it and when.` : (j.error || "Could not sign it");
    };
  }

  // ---- what is happening now, and prefetch ---------------------------------------------------------------------------
  let busyN = 0;
  const pill = () => document.getElementById("ux-now");
  const rawFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const url = String(input && input.url || input);
    // a stream or a presence poll is not "talking to the server": it never ends, and the pill stayed up for good
    const loud = /api\.devnet\.solana\.com|\/api\//.test(url) && !/\/stream|\/presence|\/api\/vectors|\/api\/proof|\/api\/(check|cross|match|report|receipts|counter|usage|qloo\/status|qloo-diff)/.test(url);   // the check's own box says its progress under the input (hero.js): no pill over the bar
    let done = false;
    const end = () => { if (!done && loud) { done = true; if (--busyN <= 0) { busyN = 0; const p = pill(); if (p) p.hidden = true; } } };
    if (loud) {
      busyN++; const p = pill(); if (p) { p.hidden = false; p.textContent = /devnet/.test(url) ? "Talking to Solana devnet…" : "Talking to the server…"; }
      setTimeout(end, 30000);                            // a call still open after 30 s stops holding the pill up
    }
    return rawFetch(input, init).finally(end);
  };
  const PREFETCH = { "#projects": "/api/projects", "#teams": "/api/companies", "#buy": "/api/products" };
  document.addEventListener("pointerdown", (e) => {
    const a = e.target.closest && e.target.closest("a[href^='#']");
    const u = a && PREFETCH[a.getAttribute("href")];
    if (u && !root.classList.contains("lite")) rawFetch(u).catch(() => {});
  }, { passive: true });

  function say(text) {
    let t = document.getElementById("ux-toast");
    if (!t) { t = document.createElement("p"); t.id = "ux-toast"; t.className = "ux-toast k-toast"; t.setAttribute("role", "status"); document.body.appendChild(t); }
    t.textContent = text; t.hidden = false; clearTimeout(t._h); t._h = setTimeout(() => { t.hidden = true; }, 4000);
  }
  Knos.say = say;

  document.addEventListener("DOMContentLoaded", () => {
    sheet();
    document.body.insertAdjacentHTML("beforeend", `<p id="ux-now" class="ux-now" role="status" hidden></p>`);
    let queued = 0;                 // at most once a frame, however many nodes a render adds
    new MutationObserver(() => { if (!queued) queued = requestAnimationFrame(() => { queued = 0; voice(); camera(); }); })
      .observe(document.body, { childList: true, subtree: true });
    voice(); camera();
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
  });
})();
