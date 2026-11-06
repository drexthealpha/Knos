// The pointer (UX rule I2): once per visitor, when nobody has tapped 3 s after the page opened, a 48 px pointer glides to
// the one button in 0.85 s, presses (0.84 for 0.1 s), releases in 0.22 s while the button dips to 94%, then fades. Gone at
// the first tap; never with reduced motion. All of it ends within 5 s.
(() => {
  const btn = document.getElementById("k-go");
  if (!btn || !btn.animate || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  let seen = false;
  try { seen = localStorage.getItem("k-pointer") === "1"; } catch { seen = false; }
  if (seen) return;
  let tapped = false, hand = null;
  const stop = () => { tapped = true; if (hand) hand.remove(); };
  addEventListener("pointerdown", stop, { once: true, capture: true });
  addEventListener("keydown", stop, { once: true, capture: true });
  setTimeout(async () => {
    const r = btn.getBoundingClientRect();
    if (tapped || r.bottom < 0 || r.top > innerHeight) return;
    try { localStorage.setItem("k-pointer", "1"); } catch { /* shown again next time: harmless */ }
    hand = document.createElement("div");
    hand.className = "k-pointer";
    hand.setAttribute("aria-hidden", "true");
    hand.style.cssText = "position:fixed;left:0;top:0;width:48px;height:48px;z-index:50;pointer-events:none;transform-origin:8px 6px";
    hand.innerHTML = '<svg viewBox="0 0 48 48" width="48" height="48"><path d="M8 6 L8 38 L17 30 L23 43 L29 40 L23 27 L35 27 Z" fill="#fff" stroke="#16161d" stroke-width="2.5" stroke-linejoin="round"/></svg>';
    document.body.append(hand);
    const x1 = r.left + r.width * 0.55 - 8, y1 = r.top + r.height * 0.55 - 6;
    const x0 = Math.min(innerWidth - 56, x1 + 220), y0 = Math.min(innerHeight - 56, y1 + 160);
    const at = (x, y, s) => ({ transform: `translate(${x}px, ${y}px) scale(${s})` });
    try {
      await hand.animate([at(x0, y0, 1), at(x1, y1, 1)], { duration: 850, easing: "cubic-bezier(.2,0,0,1)", fill: "forwards" }).finished;
      await hand.animate([at(x1, y1, 1), at(x1, y1, 0.84)], { duration: 100, fill: "forwards" }).finished;
      btn.animate([{ scale: "1" }, { scale: "0.94" }, { scale: "1" }], { duration: 320, easing: "cubic-bezier(.2,0,0,1)" });
      await hand.animate([at(x1, y1, 0.84), at(x1, y1, 1)], { duration: 220, fill: "forwards" }).finished;
      await hand.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 400, delay: 1200, fill: "forwards" }).finished;
    } catch { /* stopped by a tap */ }
    hand.remove();
  }, 3000);
})();
