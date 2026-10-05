// Motion: the five things of the design contract, and nothing that loops. A state change moves once (a token travels,
// the mark flies, a card leans to the pointer, a section enters); with `prefers-reduced-motion: reduce` nothing moves
// and every promise here resolves at once, so the state a caller sets afterwards is set all the same.
// Durations and the easing are the stylesheet's (--dur-1 --dur-2 --dur-3, --ease). No library, no canvas, no request.
//
//   prefersReduced()                 true when the reader asked for no movement
//   tilt(el)                         el leans a few degrees to the pointer, with a light that follows it ([data-tilt])
//   reveal(root)                     every .k-reveal under root enters once, when it is scrolled into view
//   travel(node, fromEl, toEl, ms)   node goes from the middle of one element to the middle of another, on an arc
//   raven(fromEl, toEl)              the mark flies that way (a payment lands)
//   morph(update)                    a change of page, as a view transition where the browser has them
//   init(root)                       does tilt and reveal for what is under root now and for what a module adds later

const has = (name) => typeof globalThis[name] !== "undefined";
export const prefersReduced = () => !has("matchMedia") || matchMedia("(prefers-reduced-motion: reduce)").matches;
const css = (name, or) => (has("document") && getComputedStyle(document.documentElement).getPropertyValue(name).trim()) || or;
const ms = (name, or) => parseFloat(css(name, "")) || or;
const middle = (el) => { const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; };

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

let seen;
export function reveal(root = document) {
  const all = [...(root.matches?.(".k-reveal") ? [root] : []), ...root.querySelectorAll(".k-reveal:not(.in)")];
  if (prefersReduced() || !has("IntersectionObserver")) { for (const el of all) el.classList.add("in"); return; }
  seen ||= new IntersectionObserver((list) => { for (const e of list) if (e.isIntersecting) { e.target.classList.add("in"); seen.unobserve(e.target); } }, { rootMargin: "0px 0px -8% 0px" });
  document.documentElement.classList.add("k-motion");            // only now may the stylesheet hold a .k-reveal back
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

export function morph(update) {
  if (prefersReduced() || !has("document") || !document.startViewTransition) return Promise.resolve(update());
  return document.startViewTransition(update).finished.catch(() => {});
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
