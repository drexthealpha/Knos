// More of the app for the least technical person (static/ux.js has the basics). Each part is small and does one thing:
//   drafts      the brief being written is saved for your passkey on every change (POST /api/draft), so it is there on
//               any device you sign in on; Undo / Redo walk its versions; the timeline lists them; Fork keeps a copy
//               to try another way and Merge takes a field from it; "Forget my drafts" deletes them all
//   gestures    swipe right = back, pull down at the top = refresh, long press on a card = its menu (copy link, share)
//   share       navigator.share on a project page (the link), with a copy fallback
//   notify      an actionable notification when money locks or is released (asked once, on the first lock)
//   read aloud  speechSynthesis reads the Ready check's answer: with the microphone it is a voice conversation
//   colour      colour-vision modes (deuteranopia, protanopia, tritanopia) and dark/light/system, density compact/roomy
//   keys        keyboard first: g p projects, g h home, / the brief, ? the list of keys
//   drop        drop a paper or evidence file on the brief: signed with C2PA, like the camera
//   screen      "Capture a region of my screen" as evidence (Screen Capture API), then annotate it before signing
//   cursors     live cursors of whoever else is on the same project page (POST /api/presence, every 15 s while visible)
//   canvas      on a wide screen, a project's milestones on a canvas you can arrange (kept on this device)
//   layout      "show money first" / "show proof first" rearranges a project page on request (generative layout)
//   sound       an optional quiet cue on lock and release, panned left/right (WebAudio)
//   variant     half of new visitors see the simpler version first (an A/B kept on this device), and can switch
//   predict     the home page offers the last thing you did here, at the time of day you usually do it
//   recover     a failed step shows "Try again" that repeats it in one tap
//   help        when you pause 20 s on a Not ready brief, one hint appears; nothing listens or watches otherwise
//   privacy     "What Knos keeps" and "Forget this device": everything this app stored here, cleared in one tap
//   badge       the app icon shows how many of your milestones are waiting (Badging API, where installed)
//   stream      a crossing's steps arrive as they happen (EventSource on /api/cross/stream)
//   private     "Keep the amount private": the amount encrypted under your own ElGamal key, proven on devnet (static/zk)
//   sentence    "Say what you want, in one sentence" fills the brief; night: a large voice button after 21:00
//   act         a contextual action button on list pages; help: a panel per page with "Ask a person" (a GitHub issue)
//   edit        milestone names editable in place until money locks; speed: animations follow your tapping pace
//   screens     shift-click evidence opens it on a second screen; done: a quiet check mark on lock and release
"use strict";
(function () {
  const root = document.documentElement;
  const S = { get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
    del: (k) => { try { localStorage.removeItem(k); } catch (e) { /* private mode */ } } };
  const $ = (id) => document.getElementById(id);
  const token = () => { try { return (JSON.parse(S.get("knos.session") || "null") || {}).token; } catch (e) { return null; } };
  const post = (path, body) => fetch(path, { method: "POST", headers: { "Content-Type": "application/json", ...(token() ? { Authorization: "Bearer " + token() } : {}) },
    body: JSON.stringify(body || {}) }).then((r) => r.json());
  const say = (t) => (window.Knos && Knos.say ? Knos.say(t) : null);

  // ---- drafts: undo, timeline, fork, merge, cross-device -----------------------------------------------------------
  const D = { stack: [], at: -1, fork: null, timer: 0 };
  function brief() { try { return briefFromForm(); } catch (e) { return null; } }
  function snapshot() {
    const b = brief(); if (!b) return;
    const s = JSON.stringify(b); if (D.stack[D.at] === s) return;
    D.stack = D.stack.slice(0, D.at + 1).concat(s).slice(-100); D.at = D.stack.length - 1;
    S.set("knos.draft", s);
    clearTimeout(D.timer); D.timer = setTimeout(() => { if (token()) post("/api/draft", { brief: b, title: ($("pTitle") || {}).value || "" }).then(timeline).catch(() => {}); }, 1500);
  }
  function restore(s) { const b = JSON.parse(s), m = b.milestones[0] || {}; if (typeof fillBrief === "function") fillBrief({ ...m, deadline_days: m.deadline_days }); }
  function timeline() {
    if (!token() || !$("bTimeline")) return;
    post("/api/draft/get").then((d) => { $("bTimeline").innerHTML = (d.timeline || []).slice(-6).reverse().map((v) => `<li>${v.at.slice(11, 16)} ${v.title ? "· " + v.title.replace(/[<>&]/g, "") : ""}</li>`).join(""); }).catch(() => {});
  }
  function drafts() {
    const box = $("briefBox"); if (!box || $("bUndo")) return;
    box.insertAdjacentHTML("beforeend", `<div class="row small" id="bDraftBar"><button type="button" class="quiet" id="bUndo">Undo</button><button type="button" class="quiet" id="bRedo">Redo</button>
      <button type="button" class="quiet" id="bFork">Fork</button><button type="button" class="quiet" id="bMerge" disabled>Merge target from fork</button>
      <button type="button" class="quiet" id="bForget">Forget my drafts</button></div><ol class="small muted" id="bTimeline" aria-label="Draft history"></ol>`);
    $("bUndo").onclick = () => { if (D.at > 0) { D.at--; restore(D.stack[D.at]); } };
    $("bRedo").onclick = () => { if (D.at < D.stack.length - 1) { D.at++; restore(D.stack[D.at]); } };
    $("bFork").onclick = () => { D.fork = brief(); $("bMerge").disabled = !D.fork; say("Forked: change this draft freely; Merge takes the fork's target back."); };
    $("bMerge").onclick = () => { if (D.fork && $("bTarget")) { $("bTarget").value = D.fork.milestones[0].target || ""; $("bTarget").dispatchEvent(new Event("input", { bubbles: true })); } };
    $("bForget").onclick = () => { S.del("knos.draft"); D.stack = []; D.at = -1; if (token()) post("/api/draft/forget"); $("bTimeline").innerHTML = ""; say("Drafts forgotten."); };
    box.addEventListener("input", () => setTimeout(snapshot, 0));
    const local = S.get("knos.draft");
    if (token()) post("/api/draft/get").then((d) => { if (d.latest) restore(JSON.stringify(d.latest.brief)); else if (local) restore(local); timeline(); }).catch(() => local && restore(local));
    else if (local) restore(local);
  }

  // ---- gestures, long press, share -----------------------------------------------------------------------------------
  let t0 = null;
  document.addEventListener("touchstart", (e) => { const t = e.touches[0]; t0 = { x: t.clientX, y: t.clientY, at: Date.now(), top: scrollY === 0 }; }, { passive: true });
  document.addEventListener("touchend", (e) => {
    if (!t0) return; const t = e.changedTouches[0], dx = t.clientX - t0.x, dy = t.clientY - t0.y, dt = Date.now() - t0.at;
    if (dt < 600 && dx > 90 && Math.abs(dy) < 40 && t0.x < 40) history.back();                     // swipe from the left edge: back
    else if (dt < 900 && dy > 120 && Math.abs(dx) < 50 && t0.top) location.reload();                // pull down at the top: refresh
    t0 = null;
  }, { passive: true });
  let press = 0;
  document.addEventListener("pointerdown", (e) => {
    const card = e.target.closest && e.target.closest(".card, .pcard, .ms");
    if (!card) return;
    press = setTimeout(() => menu(card, e.clientX, e.clientY), 550);
  }, { passive: true });
  for (const ev of ["pointerup", "pointermove", "pointercancel"]) document.addEventListener(ev, () => clearTimeout(press), { passive: true });
  document.addEventListener("contextmenu", (e) => { const card = e.target.closest && e.target.closest(".pcard, .ms"); if (card) { e.preventDefault(); menu(card, e.clientX, e.clientY); } });
  function link(card) { const a = card.querySelector("a[href^='#']"); return location.origin + location.pathname + (a ? a.getAttribute("href") : location.hash); }
  function menu(card, x, y) {
    let m = $("ux-menu"); if (m) m.remove();
    m = document.createElement("div"); m.id = "ux-menu"; m.className = "ux-menu"; m.setAttribute("role", "menu");
    m.style.left = Math.min(x, innerWidth - 200) + "px"; m.style.top = Math.min(y, innerHeight - 120) + "px";
    m.innerHTML = `<button type="button" role="menuitem" data-a="copy">Copy link</button><button type="button" role="menuitem" data-a="share">Share</button><button type="button" role="menuitem" data-a="open">Open</button>`;
    document.body.appendChild(m);
    m.onclick = (e) => { const a = e.target.dataset.a, u = link(card); if (a === "copy") navigator.clipboard?.writeText(u).then(() => say("Link copied")); if (a === "share") share(u); if (a === "open") location.href = u; m.remove(); };
    setTimeout(() => document.addEventListener("pointerdown", () => m.remove(), { once: true }), 0);
  }
  function share(u) { if (navigator.share) navigator.share({ title: document.title, url: u }).catch(() => {}); else navigator.clipboard?.writeText(u).then(() => say("Link copied")); }
  window.Knos = window.Knos || {}; Knos.share = share;

  // ---- notifications, sound, badge -------------------------------------------------------------------------------------
  Knos.notify = function (title, body, url) {
    const go = () => { const n = new Notification(title, { body, icon: "/static/icon.svg", tag: "knos-" + title }); n.onclick = () => { focus(); if (url) location.href = url; }; };
    if (!("Notification" in window)) return;
    if (Notification.permission === "granted") go(); else if (Notification.permission === "default") Notification.requestPermission().then((p) => p === "granted" && go());
  };
  Knos.cue = function (kind) {
    if (S.get("knos.sound") !== "1" || !window.AudioContext) return;
    const a = new AudioContext(), o = a.createOscillator(), g = a.createGain(), p = a.createStereoPanner();
    o.frequency.value = kind === "release" ? 660 : 440; p.pan.value = kind === "release" ? 0.6 : -0.6; g.gain.value = 0.04;
    o.connect(g).connect(p).connect(a.destination); o.start(); o.stop(a.currentTime + 0.18);
  };
  Knos.badgeCount = (n) => { if (navigator.setAppBadge) (n ? navigator.setAppBadge(n) : navigator.clearAppBadge()).catch(() => {}); };
  const haptic = Knos.haptic;
  Knos.haptic = function (kind) {
    if (haptic) haptic(kind); Knos.cue(kind);
    Knos.notify(kind === "release" ? "Money released" : "Money locked", kind === "release" ? "A milestone was verified and paid." : "Your test units are held until the proof passes.", location.href);
  };

  // ---- read aloud: the Ready answer (with the microphone, a voice conversation) ---------------------------------------
  function readAloud() {
    const box = $("bReady"); if (!box || box.dataset.read || !window.speechSynthesis || S.get("knos.voice") !== "1") return;
    box.dataset.read = "1";
    new MutationObserver(() => {
      const label = ($("bLabel") || {}).textContent, q = ($("bQuestion") || {}).textContent;
      if (!label) return; speechSynthesis.cancel();
      speechSynthesis.speak(Object.assign(new SpeechSynthesisUtterance(label === "Ready" ? "Ready to fund." : `Not ready. ${q || ($("bMissing") || {}).textContent || ""}`), { lang: root.lang || "en" }));
    }).observe(box, { childList: true, subtree: true });
  }

  // ---- display: colour vision, theme, density, sound, voice ----------------------------------------------------------
  const COLOUR = { "": "Normal colour", deuteranopia: "Deuteranopia", protanopia: "Protanopia", tritanopia: "Tritanopia" };
  const MATRIX = { deuteranopia: "0.625 0.375 0 0 0 0.7 0.3 0 0 0 0 0.3 0.7 0 0 0 0 0 1 0", protanopia: "0.567 0.433 0 0 0 0.558 0.442 0 0 0 0 0.242 0.758 0 0 0 0 0 1 0",
    tritanopia: "0.95 0.05 0 0 0 0 0.433 0.567 0 0 0 0.475 0.525 0 0 0 0 0 1 0" };
  function display() {
    const s = $("ux-sheet"); if (!s || $("ux-colour")) return;
    s.insertAdjacentHTML("afterbegin", `<label class="small" for="ux-colour">Colour</label><select id="ux-colour">${Object.entries(COLOUR).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
      <label class="small" for="ux-theme">Theme</label><select id="ux-theme"><option value="">System</option><option value="dark">Dark</option><option value="light">Light</option></select>
      <label class="small" for="ux-density">Density</label><select id="ux-density"><option value="">Roomy</option><option value="compact">Compact</option></select>
      <button type="button" class="quiet" id="ux-sound" aria-pressed="${S.get("knos.sound") === "1"}">Sound cues</button>
      <button type="button" class="quiet" id="ux-voice" aria-pressed="${S.get("knos.voice") === "1"}">Read answers aloud</button>
      <button type="button" class="quiet" id="ux-privacy">What Knos keeps here</button>`);
    document.body.insertAdjacentHTML("beforeend", `<svg width="0" height="0" style="position:absolute" aria-hidden="true">${Object.entries(MATRIX).map(([k, v]) => `<filter id="cv-${k}"><feColorMatrix type="matrix" values="${v}"/></filter>`).join("")}</svg>`);
    const apply = () => { const c = S.get("knos.colour") || "", th = S.get("knos.theme") || "", d = S.get("knos.density") || "";
      root.style.filter = c ? `url(#cv-${c})` : ""; if (th) root.dataset.theme = th; else delete root.dataset.theme; root.classList.toggle("compact", d === "compact");
      $("ux-colour").value = c; $("ux-theme").value = th; $("ux-density").value = d; };
    $("ux-colour").onchange = (e) => { S.set("knos.colour", e.target.value); apply(); };
    $("ux-theme").onchange = (e) => { S.set("knos.theme", e.target.value); apply(); };
    $("ux-density").onchange = (e) => { S.set("knos.density", e.target.value); apply(); };
    $("ux-sound").onclick = (e) => { const on = S.get("knos.sound") !== "1"; S.set("knos.sound", on ? "1" : "0"); e.target.setAttribute("aria-pressed", on); };
    $("ux-voice").onclick = (e) => { const on = S.get("knos.voice") !== "1"; S.set("knos.voice", on ? "1" : "0"); e.target.setAttribute("aria-pressed", on); readAloud(); };
    $("ux-privacy").onclick = privacy;
    apply();
  }
  function privacy() {
    const keys = []; try { for (let i = 0; i < localStorage.length; i++) if (localStorage.key(i).startsWith("knos.")) keys.push(localStorage.key(i)); } catch (e) { /* none */ }
    const box = document.createElement("div"); box.className = "ux-sheet"; box.setAttribute("role", "dialog"); box.setAttribute("aria-label", "What Knos keeps here");
    box.innerHTML = `<p class="small"><strong>On this device</strong>: ${keys.length ? keys.map((k) => k.replace("knos.", "")).join(", ") : "nothing"}.</p>
      <p class="small">On the server: your passkey's public key, your drafts (if signed in), and the money steps you took (devnet). No tracking, no ads.</p>
      <button type="button" class="ghost" id="ux-forget">Forget this device</button><button type="button" class="quiet" id="ux-x">Close</button>`;
    document.body.appendChild(box);
    box.querySelector("#ux-forget").onclick = () => { keys.forEach(S.del); if (token()) post("/api/draft/forget"); box.remove(); say("This device forgets Knos."); };
    box.querySelector("#ux-x").onclick = () => box.remove();
  }

  // ---- keys, drop, screen capture with annotation ---------------------------------------------------------------------
  let g = false;
  document.addEventListener("keydown", (e) => {
    if (e.target.closest && e.target.closest("input, textarea, select, [contenteditable]")) return;
    if (e.key === "?") return keys();
    if (e.key === "/") { const f = $("bName") || $("pTitle"); if (f) { e.preventDefault(); location.hash = "#projects"; setTimeout(() => f.focus(), 50); } return; }
    if (g) { g = false; const to = { p: "#projects", h: "#home", b: "#buy", f: "#fund", t: "#teams", r: "#research" }[e.key]; if (to) location.hash = to; return; }
    if (e.key === "g") { g = true; setTimeout(() => { g = false; }, 1000); }
  });
  function keys() { say("Keys: g p projects · g h home · g b back · g f fund · g t teams · g r research · / write a brief · ? this list"); }
  async function sign(file) {
    if (!token()) return say("Sign in first to sign evidence.");
    const r = await fetch("/api/evidence/c2pa", { method: "POST", body: file, headers: { Authorization: "Bearer " + token(), "Content-Type": file.type || "image/png", "X-Claim-Id": "evidence-" + Date.now() } });
    say(r.ok ? "Signed with C2PA: it now carries who made it and when." : "Could not sign it");
  }
  document.addEventListener("dragover", (e) => { if (e.target.closest && e.target.closest("#briefBox, .ms")) e.preventDefault(); });
  document.addEventListener("drop", (e) => { const z = e.target.closest && e.target.closest("#briefBox, .ms"); if (!z) return; e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) sign(f); });
  async function capture() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) return say("This browser cannot capture the screen.");
    const s = await navigator.mediaDevices.getDisplayMedia({ video: true }), v = document.createElement("video");
    v.srcObject = s; await v.play();
    const c = document.createElement("canvas"); c.width = v.videoWidth; c.height = v.videoHeight; c.getContext("2d").drawImage(v, 0, 0);
    s.getTracks().forEach((t) => t.stop());
    annotate(c);
  }
  function annotate(c) {
    const box = document.createElement("div"); box.className = "ux-sheet"; box.setAttribute("role", "dialog"); box.setAttribute("aria-label", "Mark the evidence");
    c.style.maxWidth = "100%"; c.style.touchAction = "none"; box.append(c);
    box.insertAdjacentHTML("beforeend", `<p class="small">Draw on it to mark what matters, then sign it.</p><button type="button" id="ux-sign">Sign as evidence</button><button type="button" class="quiet" id="ux-cancel">Cancel</button>`);
    document.body.appendChild(box);
    const x = c.getContext("2d"); x.strokeStyle = "#e5484d"; x.lineWidth = Math.max(4, c.width / 200); let on = false;
    const at = (e) => { const r = c.getBoundingClientRect(); return [(e.clientX - r.left) * c.width / r.width, (e.clientY - r.top) * c.height / r.height]; };
    c.onpointerdown = (e) => { on = true; x.beginPath(); x.moveTo(...at(e)); }; c.onpointermove = (e) => { if (on) { x.lineTo(...at(e)); x.stroke(); } }; c.onpointerup = () => { on = false; };
    box.querySelector("#ux-sign").onclick = () => c.toBlob((b) => { sign(new File([b], "evidence.png", { type: "image/png" })); box.remove(); });
    box.querySelector("#ux-cancel").onclick = () => box.remove();
  }
  Knos.capture = capture;

  // ---- live cursors on a project page -------------------------------------------------------------------------------
  const me = S.get("knos.me") || Math.random().toString(36).slice(2, 10); S.set("knos.me", me);
  let pos = { x: 0, y: 0 }, cursorTimer = 0;
  document.addEventListener("pointermove", (e) => { pos = { x: e.clientX / innerWidth, y: e.clientY / innerHeight }; }, { passive: true });
  function cursors() {
    clearInterval(cursorTimer);
    const page = (location.hash.match(/^#projects=([0-9a-f]{16})/) || [])[1];
    document.querySelectorAll(".ux-cursor").forEach((n) => n.remove());
    if (!page) return;
    cursorTimer = setInterval(() => {
      if (document.hidden) return;
      post("/api/presence", { page, me, x: pos.x, y: pos.y, label: (JSON.parse(S.get("knos.session") || "null") || {}).label || "a visitor" }).then((r) => {
        document.querySelectorAll(".ux-cursor").forEach((n) => n.remove());
        for (const o of r.others || []) document.body.insertAdjacentHTML("beforeend", `<span class="ux-cursor" style="left:${o.x * 100}vw;top:${o.y * 100}vh">${String(o.label).replace(/[<>&]/g, "")}</span>`);
        const h = $("ux-here"); if (h) h.textContent = r.here > 1 ? `${r.here} people here now` : "";
      }).catch(() => {});
    }, 15000);                      // every 15 s while the tab is shown (its own server bucket, not the person's limit)
  }

  // ---- generative layout, canvas, variant, prediction, recovery, help ----------------------------------------------------
  function layout() {
    const head = $("projHead"); if (!head || $("ux-layout")) return;
    head.insertAdjacentHTML("beforeend", `<p class="small"><span id="ux-here" class="muted"></span></p><div class="row small"><label for="ux-layout">Show</label>
      <input id="ux-layout" placeholder="money first, proof first, open first" maxlength="40"><button type="button" class="quiet" id="ux-canvas">Canvas</button>
      <button type="button" class="quiet" id="ux-capture">Capture a region of my screen</button><button type="button" class="quiet" id="ux-share">Share</button></div>`);
    $("ux-share").onclick = () => share(location.href);
    $("ux-capture").onclick = () => capture().catch(() => {});
    $("ux-layout").onchange = (e) => arrange(e.target.value.toLowerCase());
    $("ux-canvas").onclick = canvas;
  }
  function arrange(ask) {
    const list = $("msList"); if (!list) return;
    const items = [...list.children], score = (li) => {
      const t = li.textContent.toLowerCase();
      if (/money|held|fund/.test(ask)) return -Number((t.match(/(\d+) test units held/) || [0, 0])[1]);
      if (/proof|evidence|verified/.test(ask)) return /released|verdict|checked/.test(t) ? -1 : 0;
      if (/open|todo|left/.test(ask)) return /released/.test(t) ? 1 : 0;
      return 0;
    };
    items.sort((a, b) => score(a) - score(b)).forEach((li) => list.appendChild(li));
    say("Rearranged: " + ask);
  }
  function canvas() {
    const list = $("msList"); if (!list) return;
    const on = list.classList.toggle("ux-canvas"), key = "knos.canvas." + location.hash;
    const saved = JSON.parse(S.get(key) || "{}");
    [...list.children].forEach((li, i) => {
      li.style.left = on ? (saved[i] ? saved[i][0] : (i % 3) * 34) + "%" : ""; li.style.top = on ? (saved[i] ? saved[i][1] : Math.floor(i / 3) * 260) + "px" : "";
      li.onpointerdown = on ? (e) => { if (e.target.closest("button, input, a, select, summary")) return; const sx = e.clientX, sy = e.clientY, l = parseFloat(li.style.left), t = parseFloat(li.style.top);
        const mv = (ev) => { li.style.left = l + (ev.clientX - sx) / list.clientWidth * 100 + "%"; li.style.top = t + ev.clientY - sy + "px"; };
        const up = () => { removeEventListener("pointermove", mv); saved[i] = [parseFloat(li.style.left), parseFloat(li.style.top)]; S.set(key, JSON.stringify(saved)); };
        addEventListener("pointermove", mv); addEventListener("pointerup", up, { once: true }); } : null;
    });
  }
  if (!S.get("knos.variant")) S.set("knos.variant", Math.random() < 0.5 ? "simple" : "full");
  if (S.get("knos.variant") === "simple" && S.get("knos.mode.simple") === null) root.classList.add("simple");
  function predict() {
    const box = $("v-home"); if (!box || $("ux-predict")) return;
    const last = JSON.parse(S.get("knos.last") || "null"), hour = new Date().getHours();
    if (last && last.view && Math.abs(last.hour - hour) <= 3) box.insertAdjacentHTML("afterbegin", `<p class="small" id="ux-predict">Pick up where you were: <a href="#${last.view}">${last.view}</a></p>`);
  }
  addEventListener("hashchange", () => { const v = location.hash.slice(1).split("=")[0]; if (v && v !== "home") S.set("knos.last", JSON.stringify({ view: v, hour: new Date().getHours() })); cursors(); });
  addEventListener("unhandledrejection", (e) => {
    const err = $("err"); if (!err || err.hidden) return;
    if (!$("ux-retry")) err.insertAdjacentHTML("beforeend", ` <button type="button" class="quiet" id="ux-retry">Try again</button>`);
    $("ux-retry").onclick = () => { const b = document.querySelector("button[aria-busy='true'], button.busy") || window.__knosLast; if (b && b.click) b.click(); else location.reload(); };
  });
  document.addEventListener("click", (e) => { const b = e.target.closest && e.target.closest("button"); if (b && b.id && !b.id.startsWith("ux-")) window.__knosLast = b; });
  let idle = 0;
  document.addEventListener("input", () => { clearTimeout(idle); idle = setTimeout(() => { if (($("bLabel") || {}).textContent === "Not ready") say("Hint: tap one of the readings under the check, or Use the rewrite."); }, 20000); });

  // ---- Wallet Standard: browser wallets that register themselves, beside passkeys (github.com/wallet-standard) -------------
  const wallets = [];
  const register = (...ws) => { for (const w of ws) if (w && w.features && w.features["solana:signTransaction"] && !wallets.includes(w)) wallets.push(w); };
  window.addEventListener("wallet-standard:register-wallet", (e) => { try { e.detail({ register }); } catch (x) { /* a wallet that cannot */ } });
  window.dispatchEvent(new CustomEvent("wallet-standard:app-ready", { detail: { register } }));
  Knos.wallets = () => wallets.map((w) => ({ name: w.name, icon: w.icon, chains: w.chains }));
  // sign a devnet transaction (bytes) with the first standard wallet the person connects; null when none registered
  Knos.standardSign = async function (bytes) {
    const w = wallets.find((x) => (x.chains || []).includes("solana:devnet")) || wallets[0];
    if (!w) return null;
    const { accounts } = await w.features["standard:connect"].connect();
    const [out] = await w.features["solana:signTransaction"].signTransaction({ account: accounts[0], transaction: bytes, chain: "solana:devnet" });
    return out.signedTransaction;
  };

  // ---- a crossing's steps as they happen ------------------------------------------------------------------------------
  Knos.streamCrossing = function (id, onStep, onDone) {
    if (!window.EventSource) return null;
    const es = new EventSource(`/api/cross/stream?id=${encodeURIComponent(id)}`);
    es.onmessage = (ev) => onStep(JSON.parse(ev.data));
    es.addEventListener("done", (ev) => { es.close(); if (onDone) onDone(JSON.parse(ev.data)); });
    es.onerror = () => es.close();
    return es;
  };

  // ---- a private pledge: the amount encrypted under the backer's own ElGamal key, two zero-knowledge proofs -----------
  // (@solana/zk-sdk, Apache-2.0, in static/zk; loaded only when a backer asks for it). The key stays in this browser.
  Knos.privatePledge = async function (order, units, api) {
    const zk = await import("/static/zk/zk_sdk.js");
    await zk.default({ module_or_path: "/static/zk/zk_sdk_bg.wasm" });
    let seed = null;
    try { seed = localStorage.getItem("knos.elgamal"); } catch (e) { /* private window */ }
    if (!seed) {
      seed = Array.from(crypto.getRandomValues(new Uint8Array(32)), (b) => b.toString(16).padStart(2, "0")).join("");
      try { localStorage.setItem("knos.elgamal", seed); } catch (e) { /* kept for this page only */ }
    }
    const kp = zk.ElGamalKeypair.fromSeedPhraseAndPassphrase(seed, "knos private pledge");
    const amount = BigInt(units), r = new zk.PedersenOpening(), ct = kp.pubkey().encryptWith(amount, r);
    const pv = new zk.PubkeyValidityProofData(kp);
    const rp = new zk.BatchedRangeProofU64Data([ct.commitment()], BigUint64Array.of(amount), Uint8Array.of(64), [r]);
    const b64 = (u) => btoa(String.fromCharCode(...u));
    return api("/api/project/private", { order, ciphertext: b64(ct.toBytes()), pubkey_proof: b64(pv.toBytes()), range_proof: b64(rp.toBytes()) });
  };

  // ---- a quiet success: a check mark that fades, no sound unless sound is on, still under reduced motion ---------------
  Knos.celebrate = function (word) {
    const el = document.createElement("p");
    el.className = "ux-done"; el.setAttribute("role", "status"); el.textContent = "✓ " + word;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 1800);
  };

  // ---- one sentence is enough: the main input for a brief -------------------------------------------------------------
  // "Cut checkout p95 under 300 ms on test_checkout within 2 weeks" -> name, target (number + unit or a test), check, deadline
  function sentence() {
    const box = $("briefBox"); if (!box || $("bSay")) return;
    box.insertAdjacentHTML("afterbegin", `<label for="bSay"><strong>Say what you want, in one sentence</strong></label>
      <textarea id="bSay" rows="2" maxlength="400" placeholder="Cut checkout p95 under 300 ms on test_checkout within 2 weeks"></textarea>
      <button type="button" class="ghost" id="bSayGo">Turn it into a brief</button>`);
    $("bSayGo").onclick = () => {
      const t = $("bSay").value.trim(); if (!t) return;
      const dm = t.match(/\b(?:within|in|by)\s+(\d+)\s*(days?|weeks?)\b/i);
      const days = dm ? (+dm[1]) * (/week/i.test(dm[2]) ? 7 : 1) : 14;
      const tm = t.match(/\b(test_[a-z0-9_]+|[\w./-]+\.(?:py|js|ts)::[\w-]+)\b/i), test = tm ? tm[1] : "";
      const nm = t.match(/(?:under|below|at least|above|over|<=|>=|<|>)?\s*\d[\d,.]*\s*(?:%|ms|s|seconds|minutes|hours|days|kb|mb|gb|users|samples|tests|units|points|score)\b/i);
      const num = nm ? nm[0].trim() : "";
      const target = [num, test ? "on " + test : ""].filter(Boolean).join(" ");
      let name = t;
      for (const cut of [dm ? dm[0] : "", test ? "on " + test : "", test, num ? "on " + num : "", num]) if (cut) name = name.split(cut).join(" ");
      name = name.replace(/\s+/g, " ").trim();
      if (typeof fillBrief === "function") fillBrief({ name: name || t.slice(0, 80), target: target || t, deadline_days: days,
        verifier: { kind: "machine", check: test ? "ci / " + test : "" } });
      say(target ? "Brief filled from your sentence: check what is missing below." : "Filled what I could: add a number with its unit.");
    };
  }

  // ---- night: a large voice button; the app icon's badge; a contextual action button ----------------------------------
  const night = () => { const h = new Date().getHours(); root.classList.toggle("night-voice", h >= 21 || h < 6); };
  night(); setInterval(night, 600000);
  async function badgeCount() {
    if (!token() || !navigator.setAppBadge) return;
    try {
      const p = await fetch("/api/projects").then((r) => r.json());
      const n = (p.projects || []).reduce((a, x) => a + x.milestones.filter((m) => m.locked_units > 0 && m.status !== "released").length, 0);
      Knos.badgeCount(n);
    } catch (e) { /* none */ }
  }
  // each view's own buttons are its actions: nothing floats over the page (scripts/test_layout_audit.mjs)
  function fab() { const f = $("ux-act"); if (f) f.remove(); }
  addEventListener("hashchange", fab);

  // ---- help beside the page, and a person when help is not enough -----------------------------------------------------
  const HELP = { home: "Pick a product to back, or write a brief: money locks only when the brief is Ready.",
    projects: "Write the brief in one sentence; the check says what is missing; tap a reading; then Open and fund.",
    buy: "Backing pre-orders a product: your test units are held until the maker proves it.",
    fund: "Funding locks test units on one milestone; it pays only on a result plus an independent check.",
    make: "Claim a milestone, post a public page with its claim id, and the referees check it.",
    teams: "Teams share a Squads multisig made by your passkey, and can sign in with SSO.",
    research: "Paste a paper or an idea; Knos asks Qloo who wants it and where." };
  function panel() {
    let p = $("ux-help");
    const v = location.hash.slice(1).split("=")[0] || "home";
    if (!p) {
      p = document.createElement("aside"); p.id = "ux-help"; p.className = "ux-help"; p.setAttribute("aria-label", "Help for this page"); p.hidden = true;
      document.body.appendChild(p);
      const b = $("ux-help-btn");                     // in the header beside Sign in (index.html): never over the page's own controls
      if (b) b.onclick = () => { p.hidden = !p.hidden; panel(); };
    }
    const ctx = encodeURIComponent(`Page: ${location.href}\nWhat I tried: \nWhat happened: ${(($("err") || {}).textContent || "").slice(0, 300)}`);
    // on a project's page: what the Ready check says about its brief right now, and the first thing missing
    const pr = typeof V !== "undefined" && V.project && location.hash.includes("=") ? V.project : null;
    const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
    const now = pr && pr.ready ? `<p class="small"><strong>This brief:</strong> ${esc(pr.ready.label)}${pr.ready.missing && pr.ready.missing[0] ? ": " + esc(pr.ready.missing[0]) : ""}</p>` : "";
    p.innerHTML = `<p class="small"><strong>This page</strong></p><p class="small">${HELP[v] || HELP.home}</p>${now}
      <p class="small"><a href="https://github.com/drexthealpha/Knos/issues/new?title=${encodeURIComponent("Help: " + v)}&body=${ctx}" rel="noopener">Ask a person</a> (opens GitHub with what you were doing)</p>
      <button type="button" class="quiet" id="ux-help-x">Close</button>`;
    $("ux-help-x").onclick = () => { p.hidden = true; };
  }
  addEventListener("hashchange", () => { if ($("ux-help") && !$("ux-help").hidden) panel(); });

  // ---- milestone names editable in place until money locks ------------------------------------------------------------
  function editable() {
    const p = typeof V !== "undefined" && V.project;
    if (!p || p.frozen || $("ux-edit-note")) return;
    document.querySelectorAll("#msList .ms h3").forEach((h, i) => {
      h.contentEditable = "true"; h.setAttribute("aria-label", "Milestone name, editable until money locks");
      h.onblur = () => {
        const name = h.textContent.trim(), m = p.milestones[i];
        if (!name || name === m.name) return;
        const b = { milestones: p.milestones.map((x, j) => ({ key: x.key, name: j === i ? name : x.name, target: x.target, verifier: x.verifier, deadline_s: x.deadline_s })),
          kill_fee_bps: p.kill_fee_bps, challenge_s: p.challenge_s };
        post("/api/project/brief", { project: p.id, brief: b }).then(() => say("Saved")).catch(() => say("Could not save that name"));
      };
    });
    const head = $("projHead");
    if (head) head.insertAdjacentHTML("beforeend", `<p class="small muted" id="ux-edit-note">Tap a milestone's name to edit it; it locks with the money.</p>`);
  }

  // ---- adaptive animation speed, a second screen for evidence ---------------------------------------------------------
  let lastTap = 0, fast = 0;
  document.addEventListener("pointerdown", () => {
    const now = Date.now(); fast = now - lastTap < 350 ? Math.min(fast + 1, 6) : Math.max(fast - 1, 0); lastTap = now;
    root.style.setProperty("--speed", String(1 - fast * 0.1));
  }, { passive: true });
  Knos.toSecondScreen = async function (url) {
    if (!window.getScreenDetails) { open(url, "_blank", "noopener"); return; }
    try {
      const d = await window.getScreenDetails(), other = d.screens.find((x) => x !== d.currentScreen) || d.currentScreen;
      open(url, "_blank", `left=${other.availLeft},top=${other.availTop},width=${other.availWidth},height=${other.availHeight}`);
    } catch (e) { open(url, "_blank", "noopener"); }
  };
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a[rel~='nofollow']");
    if (a && e.shiftKey) { e.preventDefault(); Knos.toSecondScreen(a.href); }
  });

  // ---- a crossing finished while you were elsewhere: a notification ---------------------------------------------------
  const crossDone = Knos.streamCrossing;
  Knos.streamCrossing = function (id, onStep, onDone) {
    return crossDone(id, onStep, (d) => {
      if (document.hidden) Knos.notify("Your crossing is done", "Knos has the answer for your paper or idea.", location.href);
      if (onDone) onDone(d);
    });
  };

  document.addEventListener("DOMContentLoaded", () => {
    const tick = () => { display(); drafts(); layout(); predict(); readAloud(); sentence(); editable(); };
    // at most once a frame however many nodes a render adds (a project page adds hundreds at once)
    let queued = 0;
    new MutationObserver(() => { if (!queued) queued = requestAnimationFrame(() => { queued = 0; tick(); }); })
      .observe(document.body, { childList: true, subtree: true });
    tick();
    // what the first paint does not need waits for an idle moment: cursors, the action button, help, the app badge
    const later = window.requestIdleCallback || ((f) => setTimeout(f, 1200));
    later(() => { cursors(); fab(); panel(); badgeCount(); }, { timeout: 3000 });
  });
})();
