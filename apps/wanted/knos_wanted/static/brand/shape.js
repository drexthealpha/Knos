// The crossing as one shape (the front door, under the box): one path morphs through idea or paper, demand, Ready brief,
// money held and paid on proof, one dot travels it, and each state shows one real number from the live record (the
// latest real check's verdict, its criteria hash, the devnet hold, the paid signature). It plays once in 6 s, then holds
// still; hover or focus plays it again. Every frame is a function of the time since it started. With reduced motion,
// or with no script, the last frame is shown as the page carries it.
(() => {
  const fig = document.getElementById("k-shape");
  if (!fig || !fig.animate) return;
  const path = fig.querySelector("[data-shape]"), dot = fig.querySelector("[data-dot]"), word = fig.querySelector("[data-state]"), num = fig.querySelector("[data-num]");
  // five shapes of one path: the same 6 points each time, so the browser morphs it (an idea, a peak, a block, a vault, a tick)
  const D = ["M10 40 C40 40 60 40 90 40 C120 40 140 40 170 40", "M10 52 C40 52 60 8 90 8 C120 8 140 52 170 52",
    "M10 56 C40 56 40 14 90 14 C140 14 140 56 170 56", "M10 56 C30 30 60 24 90 24 C120 24 150 30 170 56",
    "M10 34 C40 34 60 56 80 56 C100 56 140 12 170 12"];
  const STATES = ["Idea or paper", "Demand", "Ready brief", "Money held", "Paid on proof"];
  const nums = STATES.map((_s, i) => fig.dataset["n" + i] || "");
  const T = 5600, n = STATES.length;
  const frame = (t) => { const i = Math.min(n - 1, Math.floor((t / T) * n));
    if (word.dataset.i !== String(i)) { word.dataset.i = String(i); word.textContent = STATES[i]; num.textContent = nums[i]; fig.dataset.state = String(i); } };
  let raf = 0;
  const play = () => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    cancelAnimationFrame(raf);
    path.animate(D.map((d) => ({ d: `path("${d}")` })), { duration: T, easing: "ease-in-out", fill: "forwards" });
    dot.animate([{ offsetDistance: "0%" }, { offsetDistance: "100%" }], { duration: T, easing: "linear", fill: "forwards" });
    const t0 = performance.now();
    const tick = (now) => { const t = now - t0; frame(Math.min(t, T - 1)); if (t < T) raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick);
  };
  // the live record's numbers: the latest real verdict and its hash, from the proof the box itself reads (hero.js sends
  // it as knos:proof; this asks nobody); the held units are the crossing's record, carried in the page (data-n3)
  const take = (p) => {
    const pr = (p && (p.sample || p.proof || p)) || {};
    if (pr.decision && pr.decision.verdict) fig.dataset.n1 = nums[1] = String(pr.decision.verdict).replace("_", " ").toLowerCase();
    const h = (pr.ready && pr.ready.criteria_hash) || pr.criteria_hash || pr.hash;
    if (h) fig.dataset.n2 = nums[2] = String(h).slice(0, 8);
    if (pr.idea) fig.dataset.n0 = nums[0] = String(pr.idea).slice(0, 40);
    // the paid signature: the newest payout the page carries (#k-paid, written from the chain at the build)
    const paid = (document.querySelector("#k-paid a")?.href || "").match(/tx\/([1-9A-HJ-NP-Za-km-z]{8})/);
    if (paid) fig.dataset.n4 = nums[4] = paid[1];
    fig.dataset.ready = "1";
    play();
  };
  document.addEventListener("knos:proof", (e) => take(e.detail), { once: true });
  fig.addEventListener("mouseenter", play);
  fig.addEventListener("focusin", play);
})();
