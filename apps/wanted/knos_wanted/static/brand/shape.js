// The crossing as one shape (the front door, under the box): one curve across the hero column with its four stops
// labelled (Demand, Ready brief, Money held, Paid on proof). One dot rides the curve on offset-path: it rests 600 ms at
// each stop and moves between them on a critically damped ease (no overshoot), a 4 s loop played 3 times and then held
// at Paid on proof. It starts when the shape is first in view, pauses while the tab is hidden, and with reduced motion
// or no script the last frame is shown as the page carries it. A real check moves the dot to the stop it reached
// (hero.js sends knos:reached with the stop's index).
(() => {
  const fig = document.getElementById("k-shape");
  if (!fig) return;
  const dot = fig.querySelector("[data-dot]"), labels = [...fig.querySelectorAll(".k-stops li")];
  const path = fig.querySelector("[data-shape]");
  const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const lit = (i) => labels.forEach((l, k) => l.toggleAttribute("data-on", k === i));
  // each stop's place along the curve, in percent of its length: the curve is three segments, one stop at each end
  const d = path.getAttribute("d"), seg = d.match(/[MCS][^MCS]*/g) || [];
  let stops = [0, 33.3, 66.7, 100];
  try {
    const at = [0];
    for (let k = 2; k <= seg.length; k++) {
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", seg.slice(0, k).join(" "));
      at.push(p.getTotalLength());
    }
    const total = at.at(-1);
    if (total > 0 && at.length === 4) stops = at.map((x) => Math.round((x / total) * 1000) / 10);
  } catch { /* an engine with no geometry: the even spacing above */ }
  const HOLD = 600, LOOP = 4000, MOVE = (LOOP - HOLD * stops.length) / (stops.length - 1), EASE = "cubic-bezier(.16,1,.3,1)";
  // keyframes over one loop: rest at a stop, move to the next, rest...; the offsets are fractions of the 4 s
  const frames = [], marks = [];
  let t = 0;
  stops.forEach((s, i) => {
    frames.push({ offset: t / LOOP, offsetDistance: `${s}%`, easing: "linear" });
    marks.push(t);
    t += HOLD;
    frames.push({ offset: t / LOOP, offsetDistance: `${s}%`, easing: EASE });
    if (i < stops.length - 1) t += MOVE;
  });
  frames.at(-1).offset = 1;
  let anim = null, timers = [];
  const clear = () => { timers.forEach(clearTimeout); timers = []; };
  // the label of the stop the dot rests at: one timer per stop per loop, set when the loop (re)starts
  const schedule = (from) => { clear(); for (let loop = 0; loop < 3; loop++) marks.forEach((m, i) => { const at = loop * LOOP + m - from; if (at >= 0) timers.push(setTimeout(() => lit(i), at)); }); };
  const play = () => {
    if (still() || !dot.animate || anim) return;
    anim = dot.animate(frames, { duration: LOOP, iterations: 3, fill: "forwards" });
    lit(0); schedule(0);
    anim.finished.then(() => { lit(stops.length - 1); }, () => {});
  };
  document.addEventListener("visibilitychange", () => {
    if (!anim || anim.playState === "finished") return;
    if (document.hidden) { anim.pause(); clear(); } else if (shown) { anim.play(); schedule(Number(anim.currentTime) || 0); }
  });
  // a real check: the dot goes to the stop the result reached, and stays
  document.addEventListener("knos:reached", (e) => {
    const i = Math.max(0, Math.min(stops.length - 1, Number(e.detail) || 0));
    if (anim) { anim.cancel(); anim = null; } clear();
    dot.style.offsetDistance = `${stops[i]}%`; lit(i);
    fig.dataset.reached = String(i);
  });
  if (!("IntersectionObserver" in window)) return;
  // played while the shape is on screen: out of view (scrolled away, or its page hidden) the loop pauses where it is
  let shown = false;
  const io = new IntersectionObserver((es) => { const on = es.some((e) => e.isIntersecting); if (on === shown) return; shown = on;
    if (fig.dataset.reached) return;
    if (!anim) { if (on) play(); return; }
    if (anim.playState === "finished") { io.disconnect(); return; }
    if (on) { anim.play(); schedule(Number(anim.currentTime) || 0); } else { anim.pause(); clear(); } }, { threshold: 0.35 });
  io.observe(fig);
})();
