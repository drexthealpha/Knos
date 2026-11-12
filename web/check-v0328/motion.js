// Motion: a state change moves once to show what happened, and nothing loops. With `prefers-reduced-motion: reduce`
// nothing moves and every promise here resolves at once, so the state a caller sets afterwards is set all the same.
// Durations and the easing are the stylesheet's (--dur-1 --dur-2 --dur-3, --ease). No library, no canvas, no request.
//
//   prefersReduced()                 true when the reader asked for no movement
//   tilt(el)                         el leans a few degrees to the pointer, with a light that follows it ([data-tilt])
//   reveal(root)                     every .k-reveal under root enters once: with the scroll where CSS can tie an
//                                    animation to it (animation-timeline: view()), by an observer elsewhere
//   travel(node, fromEl, toEl, ms)   node goes from the middle of one element to the middle of another, on an arc
//   raven(fromEl, toEl)              the mark flies that way (a payment lands)
//   morph(update)                    a change of page, as a view transition where the browser has them: the page's
//                                    heading and the mark each cross by themselves (named `title` and `mark`)
//   init(root)                       does tilt and reveal for what is under root now and for what a module adds later
//
// 0.3.17:
//   countTo(el, n, { digits, from, ms, format })
//                                    el's number counts to n once and ends on exactly n; el gets .k-num (tabular
//                                    figures, so the line does not shift). Keep el out of an aria-live region.
//   sort(el, toGroupEl, { before, state })
//                                    a statement line changes group: el is moved into toGroupEl (before `before`, or
//                                    last) and data-state is set to `state` AT ONCE; then it and every line it
//                                    displaced slide from where they were. Resolves when they have landed.
//                                        await sort(row, document.querySelector('[data-group="agreed"]'), { state: "agreed" });
//   toast(text, kind)                one line at the foot of the window for 2.4 s: "Copied", "Downloaded", "Approved".
//                                    kind "ok" (the default) or "bad". Read out by a screen reader (role=status).
//   skeleton(el, lines)              the pending state: el shows grey bars and aria-busy until the returned function is
//                                    called (or el is filled and the function called with nothing): const done = skeleton(el);
//   leave(el)                        el goes out (.k-out) and is removed. Entry needs no call: give it class .k-enter.
//   palette()                        opens the command palette (web/palette.js, fetched on first use). Ctrl/Cmd+K and
//                                    "/" (when no field has the focus) call it, and so does a click on [data-palette].

const has = (name) => typeof globalThis[name] !== "undefined";
export const prefersReduced = () => !has("matchMedia") || matchMedia("(prefers-reduced-motion: reduce)").matches;
const css = (name, or) => (has("document") && getComputedStyle(document.documentElement).getPropertyValue(name).trim()) || or;
const ms = (name, or) => parseFloat(css(name, "")) || or;
const middle = (el) => { const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; };
const landed = (runs) => Promise.all(runs.map((a) => a.finished.catch(() => {}))).then(() => {});

const leaning = new WeakSet();
export function tilt(el, degrees = 4) {
  if (!el || leaning.has(el) || prefersReduced() || !matchMedia("(hover: hover) and (pointer: fine)").matches) return;
  leaning.add(el);
  el.addEventListener("pointermove", (ev) => {
    const r = el.getBoundingClientRect(), x = (ev.clientX - r.left) / r.width, y = (ev.clientY - r.top) / r.height;
    el.style.setProperty("--tilt-y", `${((x - 0.5) * 2 * degrees).toFixed(2)}deg`);
    el.style.setProperty("--tilt-x", `${((0.5 - y) * 2 * degrees).toFixed(2)}deg`);
    el.style.setProperty("--light-x", `${(x * 100).toFixed(1)}%`);
    el.style.setProperty("--light-y", `${(y * 100).toFixed(1)}%`);
  });
  el.addEventListener("pointerleave", () => { for (const p of ["--tilt-x", "--tilt-y", "--light-x", "--light-y"]) el.style.removeProperty(p); });
}

// .in is set once a section is 120px inside the window: where CSS ties the entry to the scroll that is the moment its
// animation ends (app.css: animation-range), so the class only makes the entry final; elsewhere the class is the entry.
let seen;
export function reveal(root = document) {
  const all = [...(root.matches?.(".k-reveal") ? [root] : []), ...root.querySelectorAll(".k-reveal:not(.in)")];
  if (prefersReduced() || !has("IntersectionObserver")) { for (const el of all) el.classList.add("in"); return; }
  const tied = has("CSS") && CSS.supports?.("animation-timeline: view()");
  seen ||= new IntersectionObserver((list) => { for (const e of list) if (e.isIntersecting) { e.target.classList.add("in"); seen.unobserve(e.target); } }, { rootMargin: tied ? "0px 0px -120px 0px" : "0px 0px -8% 0px" });
  document.documentElement.classList.add("k-motion");            // only now may the stylesheet hold a .k-reveal back
  if (tied) document.documentElement.classList.add("k-scroll");
  for (const el of all) seen.observe(el);
}

export function travel(node, fromEl, toEl, time) {
  if (!node || !fromEl || !toEl || prefersReduced() || !node.animate) return Promise.resolve();
  const a = middle(fromEl), b = middle(toEl), took = time || ms("--dur-3", 480), ease = css("--ease", "ease");
  Object.assign(node.style, { position: "fixed", left: "0", top: "0", margin: "0", zIndex: "60", pointerEvents: "none" });
  node.setAttribute("aria-hidden", "true");
  document.body.append(node);
  const w = node.offsetWidth / 2, h = node.offsetHeight / 2, rise = Math.min(140, Math.max(24, Math.hypot(b.x - a.x, b.y - a.y) / 4));
  const top = Math.min(a.y, b.y) - rise;
  // across in one stroke, up and down in two: together an arc
  node.animate({ translate: [`${a.x - w}px 0`, `${b.x - w}px 0`] }, { duration: took, easing: ease, fill: "both" });
  const fall = node.animate([{ transform: `translateY(${a.y - h}px)`, easing: "cubic-bezier(0,0,.4,1)" }, { transform: `translateY(${top - h}px)`, easing: "cubic-bezier(.6,0,1,1)" },
    { transform: `translateY(${b.y - h}px)` }], { duration: took, fill: "both" });
  return fall.finished.catch(() => {}).then(() => { node.remove(); });
}

export function raven(fromEl, toEl) {
  if (!fromEl || !toEl || prefersReduced()) return Promise.resolve();
  const bird = document.createElement("span");
  bird.className = "k-raven";
  return travel(bird, fromEl, toEl).then(() => { toEl.animate?.({ scale: ["1", "1.04", "1"] }, { duration: ms("--dur-2", 240), easing: css("--ease", "ease") }); });
}

// The heading and the mark are named only for the crossing, so no two things ever share a name: the first heading in
// the window before and after, and the mark of the first screen (in the bar on every other page). Nothing else is
// pictured (app.css: the root has no transition name), so the new page itself is drawn live, as soon as `update` has run.
// A crossing costs the browser a picture of the old state first. Where that took longer than MORPH_BUDGET_MS from the
// press to the new page (a machine that draws in software), the next changes of page skip it: the page is swapped in
// the same task as the press and its section comes up into place (.k-enter) instead.
export const MORPH_BUDGET_MS = 200;
let slowMorph = false;
export const morphIsSlow = () => slowMorph;
export function morph(update) {
  if (slowMorph || prefersReduced() || !has("document") || !document.startViewTransition) return Promise.resolve(update());
  const named = [], t0 = performance.now();
  const name = (el, n) => { if (el) { el.style.viewTransitionName = n; named.push(el); } };
  const clear = () => { for (const el of named.splice(0)) { el.style.removeProperty("view-transition-name"); if (!el.getAttribute("style")) el.removeAttribute("style"); } };
  const inView = (el) => { if (!el || !el.checkVisibility?.()) return null; const r = el.getBoundingClientRect(); return r.width > 0 && r.bottom > 0 && r.top < innerHeight ? el : null; };
  const title = () => [...document.querySelectorAll("main h1, main h2")].find(inView);
  const hero = () => inView(document.getElementById("mark3d"));
  const had = hero();
  name(had, "mark"); name(title(), "title");
  // the pending state, at once: the page that is leaving dims in this frame, before the browser has taken its picture
  const root = document.documentElement, rest = () => { delete root.dataset.morph; };
  root.dataset.morph = "";
  let crossing;
  try {
    crossing = document.startViewTransition(async () => { try { await update(); } finally { if (performance.now() - t0 > MORPH_BUDGET_MS) slowMorph = true; rest(); clear(); name(hero() || (had && inView(document.querySelector(".brand .wordmark"))), "mark"); name(title(), "title"); } });
  } catch { rest(); clear(); return Promise.resolve(update()); }
  return crossing.finished.catch(() => {}).then(() => { rest(); clear(); });
}

const counting = new WeakMap();
export function countTo(el, n, o = {}) {
  if (!el) return Promise.resolve();
  const to = Number(n), digits = o.digits ?? (String(n).split(".")[1] || "").length;
  const say = o.format || ((v) => v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }));
  const from = o.from ?? (parseFloat(el.textContent.replace(/[^\d.-]/g, "")) || 0), run = (counting.get(el) || 0) + 1;
  counting.set(el, run);
  el.classList.add("k-num");
  if (prefersReduced() || !has("requestAnimationFrame") || from === to || !Number.isFinite(to)) { el.textContent = Number.isFinite(to) ? say(to) : String(n); return Promise.resolve(); }
  const took = o.ms || ms("--dur-3", 480);
  return new Promise((done) => {
    const t0 = performance.now(), tick = (t) => {
      if (counting.get(el) !== run) return done();                    // a newer count took over
      const p = Math.min(1, (t - t0) / took);
      if (p >= 1 || !el.isConnected) { el.textContent = say(to); return done(); }
      el.textContent = say(from + (to - from) * (1 - (1 - p) ** 3));
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

export function sort(el, toGroupEl, o = {}) {
  if (!el || !toGroupEl) return Promise.resolve();
  const still = prefersReduced() || !el.animate;
  const lines = still ? [] : [...new Set([el, ...(el.parentNode?.children || []), ...toGroupEl.children])];
  const was = lines.map((k) => k.getBoundingClientRect());
  if (o.state) el.dataset.state = o.state;
  toGroupEl.insertBefore(el, o.before || null);
  if (still) return Promise.resolve();
  const took = ms("--dur-2", 240), ease = css("--ease", "ease"), runs = [];
  lines.forEach((k, i) => {
    const now = k.getBoundingClientRect(), dx = was[i].left - now.left, dy = was[i].top - now.top;
    if (dx || dy) runs.push(k.animate({ translate: [`${dx}px ${dy}px`, "0px 0px"] }, { duration: took, easing: ease }));
  });
  el.classList.add("k-moved");
  return landed(runs).then(() => { el.classList.remove("k-moved"); });
}

export function leave(el) {
  if (!el?.isConnected) return Promise.resolve();
  if (prefersReduced()) { el.remove(); return Promise.resolve(); }
  el.classList.add("k-out");
  return new Promise((done) => { setTimeout(() => { el.remove(); done(); }, ms("--dur-1", 120) + 30); });
}

export function toast(text, kind = "ok", time = 2400) {
  if (!has("document")) return null;
  let box = document.querySelector(".k-toasts");
  if (!box) { box = document.createElement("div"); box.className = "k-toasts"; box.setAttribute("role", "status"); box.setAttribute("aria-live", "polite"); document.body.append(box); }
  for (const old of [...box.children]) old.remove();                     // one thing happened last: one line says it
  const line = document.createElement("p");
  line.className = "k-toast"; line.dataset.kind = kind; line.textContent = text;
  box.append(line);
  setTimeout(() => leave(line), time);
  return line;
}

export function skeleton(el, lines = 3) {
  if (!el) return () => {};
  const bars = document.createElement("div");
  bars.className = "k-skeleton";
  bars.innerHTML = `<span class="k-sr">Working</span>${"<i></i>".repeat(lines)}`;
  el.setAttribute("aria-busy", "true");
  el.replaceChildren(bars);
  return (content) => { el.removeAttribute("aria-busy"); bars.remove(); if (content !== undefined) el.replaceChildren(...[content].flat()); };
}

let pal;
export function palette() {
  pal ||= import("./palette.js");
  return pal.then((m) => m.open()).catch(() => { pal = null; });
}
if (has("document") && has("addEventListener")) {
  const typing = (el) => !!el && (el.isContentEditable || /^(input|textarea|select)$/i.test(el.tagName));
  addEventListener("keydown", (ev) => {
    const k = ev.key.toLowerCase?.() === "k" && (ev.ctrlKey || ev.metaKey) && !ev.altKey && !ev.shiftKey;
    const slash = ev.key === "/" && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !typing(document.activeElement);
    if ((k || slash) && !ev.defaultPrevented && !document.querySelector("dialog.k-pal[open]")) { ev.preventDefault(); palette(); }
  });
  addEventListener("click", (ev) => { if (ev.target.closest?.("[data-palette]")) { ev.preventDefault(); palette(); } });
}

export function init(root = document.querySelector("main") || document.body) {
  if (prefersReduced()) return;
  const dress = (node) => {
    if (node.nodeType !== 1) return;
    if (node.matches("[data-tilt]")) tilt(node);
    for (const el of node.querySelectorAll("[data-tilt]")) tilt(el);
    reveal(node);
  };
  dress(root);
  new MutationObserver((list) => { for (const m of list) for (const n of m.addedNodes) dress(n); }).observe(root, { childList: true, subtree: true });
}
