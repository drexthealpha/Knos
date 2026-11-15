// The mark with depth, at no download: mount3dMark(el) stacks copies of the mark (brand/mark.svg, as a mask over a
// colour: the same file the bar uses) a few pixels apart on the z axis, which reads as an extruded edge, under a face
// whose light follows the pointer. The body turns a little with the pointer and settles when it leaves. No WebGL, no
// canvas, no library. The box keeps the mark's proportions from the stylesheet (.k-mark3d), so mounting moves nothing.
// With `prefers-reduced-motion: reduce` the mark is drawn the same and stands still.
const LAYERS = 12, STEP = 4;                  // 48 px of edge behind the face

export function mount3dMark(el, { layers = LAYERS, step = STEP, within = null } = {}) {
  if (!el || typeof document === "undefined") return null;
  const body = document.createElement("span");
  body.className = "body";
  const layer = (name, z) => { const i = document.createElement("i"); i.className = name; i.style.setProperty("--z", `${z}px`); body.append(i); return i; };
  layer("shade", -(layers + 6) * step);
  for (let n = layers; n >= 1; n--) layer("edge", -n * step).style.setProperty("--k", (1 - n / layers).toFixed(2));
  layer("face", 0);
  el.classList.add("k-mark3d");
  el.setAttribute("aria-hidden", "true");
  el.replaceChildren(body);
  const still = typeof matchMedia !== "function" || matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (still) return el;
  // the pointer anywhere over `within` (the stage the mark stands on) turns it; leaving lets it settle
  const stage = within || el.closest(".k-stage") || el;
  stage.addEventListener("pointermove", (ev) => {
    if (ev.pointerType === "touch") return;
    const r = el.getBoundingClientRect(), x = (ev.clientX - (r.left + r.width / 2)) / innerWidth, y = (ev.clientY - (r.top + r.height / 2)) / innerHeight;
    const clamp = (v) => Math.max(-1, Math.min(1, v * 2));
    el.style.setProperty("--turn-y", `${(-20 + clamp(x) * 16).toFixed(1)}deg`);
    el.style.setProperty("--turn-x", `${(6 - clamp(y) * 10).toFixed(1)}deg`);
    el.style.setProperty("--light-x", `${(50 + clamp(x) * 50).toFixed(0)}%`);
    el.style.setProperty("--light-y", `${(50 + clamp(y) * 50).toFixed(0)}%`);
  });
  stage.addEventListener("pointerleave", () => { for (const p of ["--turn-x", "--turn-y", "--light-x", "--light-y"]) el.style.removeProperty(p); });
  return el;
}
