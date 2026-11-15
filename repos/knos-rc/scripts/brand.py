#!/usr/bin/env python3
"""The Knos mark and wordmark, from the traced originals to every file the product shows them in.

    python scripts/brand.py            write web/brand/*, web/icon.svg and the mark inside src/knos/badge.py
    python scripts/brand.py --check    write nothing; fail when a committed file is not what this would write
    python scripts/brand.py --png      also draw the PNGs (apple-touch-icon.png, card.png): needs node, the
                                       `playwright` package and a Chromium (scripts/brand_shot.mjs)
    python scripts/brand.py --compare  render each original and its lighter copy at 64, 256 and 1024 px and count the
                                       pixels that differ (same needs as --png)

One source: web/brand/src/knos-mark.svg and knos-wordmark.svg, the founder's traced drawings (a raven whose body and
tail are the letter K; the wordmark is the mark and "nos"). A tracer writes a curve every pixel or two, so the files
are 34 KB and 40 KB. `lighten` draws the same outline with fewer curves: each outline is sampled densely, cut at its
corners, and cubic curves are fitted to the samples (Schneider's method, "An algorithm for automatically fitting
digitized curves", Graphics Gems, 1990) so that no sample is further than TOLERANCE units from the new outline. The
mark is 1856 units wide, so one unit is about half a pixel when it is drawn 1024 px wide. The tracer's own wobble is
about that size: at half a unit the fit follows the wobble (10 KB), at one unit it draws the edge under it (4 KB).
`--compare` is how that was looked at; a lighter copy that shows a difference is not to be kept.

What is written (all of it committed; the site build copies web/ as it is):
    web/brand/mark.svg, wordmark.svg       fill="currentColor": the colour of the text around them
    web/brand/mark-small.svg               the mark with coarser curves, for 16 to 32 px (the favicon, the badge)
    web/brand/wordmark-light.svg, -dark    the wordmark in a set colour, for a page that cannot hand one down (GitHub)
    web/brand/mark.js                      the small mark for web/badge.js
    web/icon.svg                           the favicon: the small mark, dark on a light tab and light on a dark one
    web/brand/apple-touch-icon.png, card.png   (--png) the home-screen icon and the 1200x630 card of a shared link
No colour is set by `fill`: a file that needs one sets `color` on its root, and every path stays currentColor.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "web" / "brand"
SRC = BRAND / "src"
TOLERANCE = 1.0            # units of the drawing: the furthest a sample of the traced outline may be from the lighter one
SMALL = 3.0                # the same, for the copy drawn at 16 to 32 px
INK, PAPER = "#15171c", "#f6f5f1"          # web/app.css --fg and --bg (light); dark: #e9ebef on #0e1014
INK_DARK = "#e9ebef"
SENTENCE = "The neutral meter for AI agent work: neither side keeps the count."
BOUNDS = {"mark.svg": 6_000, "wordmark.svg": 12_000, "mark-small.svg": 3_000}      # bytes; tests/test_brand.py holds them

_NUM = re.compile(r"-?\d*\.?\d+(?:e-?\d+)?")
_CMD = re.compile(r"([MLCZ])([^MLCZ]*)")


# ---- geometry: points are complex numbers ---------------------------------------------------------------------------------

def _dot(a: complex, b: complex) -> float:
    return a.real * b.real + a.imag * b.imag


def _unit(v: complex) -> complex:
    n = abs(v)
    return v / n if n else 0j


def _bez(b: tuple, t: float) -> complex:
    s = 1 - t
    return s * s * s * b[0] + 3 * s * s * t * b[1] + 3 * s * t * t * b[2] + t * t * t * b[3]


def subpaths(d: str) -> list[list[tuple]]:
    """A path of M, L, C and Z in absolute numbers, as closed outlines: each a list of cubic curves (a line is a flat one)."""
    out: list[list[tuple]] = []
    cur, start = 0j, 0j
    for cmd, body in _CMD.findall(d):
        n = [float(x) for x in _NUM.findall(body)]
        p = [complex(n[i], n[i + 1]) for i in range(0, len(n), 2)]
        if cmd == "M":
            out.append([])
            cur = start = p[0]
            p = p[1:]
            cmd = "L"
        if cmd == "L":
            for q in p:
                out[-1].append((cur, cur, q, q))
                cur = q
        elif cmd == "C":
            for i in range(0, len(p), 3):
                out[-1].append((cur, p[i], p[i + 1], p[i + 2]))
                cur = p[i + 2]
        elif cmd == "Z" and cur != start:
            out[-1].append((cur, cur, start, start))
            cur = start
    return [s for s in out if s]


def sample(curves: list[tuple], step: float = 1.0) -> list[complex]:
    """The outline as points about `step` apart (closed: the first point is not repeated at the end)."""
    pts = [curves[0][0]]
    for b in curves:
        length = abs(b[1] - b[0]) + abs(b[2] - b[1]) + abs(b[3] - b[2])
        k = max(1, math.ceil(length / step))
        for i in range(1, k + 1):
            q = _bez(b, i / k)
            if abs(q - pts[-1]) > 1e-9:
                pts.append(q)
    if len(pts) > 1 and abs(pts[-1] - pts[0]) < 1e-9:
        pts.pop()
    return pts


def corners(pts: list[complex], reach: int = 6, sharp: float = 32.0) -> list[int]:
    """Where the outline turns by more than `sharp` degrees within `reach` samples either side: one index per turn."""
    n = len(pts)
    turn = []
    for i in range(n):
        a, b = pts[i] - pts[(i - reach) % n], pts[(i + reach) % n] - pts[i]
        turn.append(abs(math.degrees(math.atan2(a.real * b.imag - a.imag * b.real, _dot(a, b)))))
    found = [i for i in range(n) if turn[i] > sharp and all(turn[i] >= turn[(i + j) % n] for j in range(-reach, reach + 1))]
    kept: list[int] = []
    for i in found:                                    # a flat top of equal turns is one corner
        if not kept or i - kept[-1] > reach:
            kept.append(i)
    if len(kept) > 1 and kept[0] + n - kept[-1] <= reach:
        kept.pop()
    return kept


def _generate(pts: list[complex], u: list[float], t1: complex, t2: complex) -> tuple:
    first, last = pts[0], pts[-1]
    c00 = c01 = c11 = x0 = x1 = 0.0
    for p, t in zip(pts, u):
        s = 1 - t
        a1, a2 = t1 * (3 * s * s * t), t2 * (3 * s * t * t)
        c00 += _dot(a1, a1)
        c01 += _dot(a1, a2)
        c11 += _dot(a2, a2)
        rest = p - (first * (s * s * s + 3 * s * s * t) + last * (3 * s * t * t + t * t * t))
        x0 += _dot(a1, rest)
        x1 += _dot(a2, rest)
    det = c00 * c11 - c01 * c01
    chord = abs(last - first)
    l1 = l2 = 0.0
    if abs(det) > 1e-12:
        l1, l2 = (x0 * c11 - x1 * c01) / det, (c00 * x1 - c01 * x0) / det
    if l1 < 1e-6 * chord or l2 < 1e-6 * chord:         # the fit ran away: the plain third-of-the-chord curve
        l1 = l2 = chord / 3
    return (first, first + t1 * l1, last + t2 * l2, last)


def _worst(pts: list[complex], b: tuple, u: list[float]) -> tuple[float, int]:
    worst, at = 0.0, len(pts) // 2
    for i in range(1, len(pts) - 1):
        e = abs(_bez(b, u[i]) - pts[i])
        if e > worst:
            worst, at = e, i
    return worst, at


def _nearer(b: tuple, pts: list[complex], u: list[float]) -> list[float]:
    """One Newton step for each sample towards the place on the curve nearest to it."""
    d1 = [3 * (b[i + 1] - b[i]) for i in range(3)]
    d2 = [2 * (d1[i + 1] - d1[i]) for i in range(2)]
    out = []
    for p, t in zip(pts, u):
        s = 1 - t
        q = _bez(b, t) - p
        q1 = s * s * d1[0] + 2 * s * t * d1[1] + t * t * d1[2]
        q2 = s * d2[0] + t * d2[1]
        den = _dot(q1, q1) + _dot(q, q2)
        out.append(min(1.0, max(0.0, t - _dot(q, q1) / den)) if abs(den) > 1e-12 else t)
    return out


def fit(pts: list[complex], t1: complex, t2: complex, tol: float, out: list[tuple]) -> None:
    """Cubic curves through `pts` from its first to its last, leaving the ends along t1 and t2, none further than `tol` from a point."""
    if len(pts) == 2:
        third = abs(pts[1] - pts[0]) / 3
        out.append((pts[0], pts[0] + t1 * third, pts[1] + t2 * third, pts[1]))
        return
    u = [0.0]
    for a, b in zip(pts, pts[1:]):
        u.append(u[-1] + abs(b - a))
    u = [x / u[-1] for x in u]
    curve = _generate(pts, u, t1, t2)
    worst, at = _worst(pts, curve, u)
    if worst > tol and worst < tol * 4:
        for _ in range(6):
            u = _nearer(curve, pts, u)
            curve = _generate(pts, u, t1, t2)
            worst, at = _worst(pts, curve, u)
            if worst <= tol:
                break
    if worst <= tol:
        out.append(curve)
        return
    mid = _unit(pts[at - 1] - pts[at + 1]) or _unit(pts[at - 1] - pts[at])
    fit(pts[:at + 1], t1, mid, tol, out)
    fit(pts[at:], -mid, t2, tol, out)


def refit(curves: list[tuple], tol: float) -> list[tuple]:
    """One closed outline with fewer curves: cut at its corners, each stretch fitted on its own."""
    pts = sample(curves)
    n = len(pts)
    if n < 8:
        return curves
    cuts = corners(pts)
    smooth = not cuts
    if smooth:
        cuts = [0]
    out: list[tuple] = []
    for a, b in zip(cuts, cuts[1:] + [cuts[0] + n]):
        run = [pts[i % n] for i in range(a, b + 1)]
        if smooth:                                      # no corner anywhere: leave and arrive along one direction
            t1 = _unit(pts[2 % n] - pts[-2])
            t2 = -t1
        else:
            t1, t2 = _unit(run[min(2, len(run) - 1)] - run[0]), _unit(run[max(-3, -len(run))] - run[-1])
        fit(run, t1, t2, tol, out)
    return out


# ---- writing a path -------------------------------------------------------------------------------------------------------

def _join(numbers: list[int]) -> str:
    text = ""
    for i, n in enumerate(numbers):
        text += ("" if i == 0 or n < 0 else " ") + str(n)
    return text


def write_path(outlines: list[list[tuple]]) -> str:
    """Relative commands on whole units, a straight curve as a line: the shortest text that draws these curves."""
    r = lambda p: complex(round(p.real), round(p.imag))  # noqa: E731
    d = ""
    for curves in outlines:
        cur = r(curves[0][0])
        d += f"M{_join([int(cur.real), int(cur.imag)])}"
        last = "M"
        for b in curves:
            p1, p2, p3 = r(b[1]), r(b[2]), r(b[3])
            chord = b[3] - b[0]
            off = max(abs((q - b[0]).real * chord.imag - (q - b[0]).imag * chord.real) / abs(chord) for q in (b[1], b[2])) if abs(chord) > 1e-9 else 1.0
            straight = off < 0.25 and all(-1e-9 <= _dot(q - b[0], chord) <= _dot(chord, chord) + 1e-9 for q in (b[1], b[2]))
            if p3 == cur and straight:
                continue
            if straight:
                dx, dy = int((p3 - cur).real), int((p3 - cur).imag)
                cmd, nums = ("h", [dx]) if dy == 0 else ("v", [dy]) if dx == 0 else ("l", [dx, dy])
            else:
                cmd, nums = "c", [int(v) for q in (p1, p2, p3) for v in ((q - cur).real, (q - cur).imag)]
            body = _join(nums)
            d += (cmd if cmd != last else ("" if body.startswith("-") else " ")) + body
            last, cur = cmd, p3
        d += "z"
    return d


def lighten(d: str, tol: float) -> str:
    return write_path([refit(s, tol) for s in subpaths(d)])


# ---- the files ------------------------------------------------------------------------------------------------------------

def read(name: str) -> tuple[str, list[str]]:
    """An original: its viewBox and its <path ...> elements as written."""
    text = (SRC / name).read_text(encoding="utf-8")
    return re.search(r'viewBox="([^"]+)"', text)[1], re.findall(r"<path[^>]*/>", text)


def lighter_paths(paths: list[str], tol: float) -> str:
    out = ""
    for p in paths:
        d = re.search(r' d="([^"]+)"', p)[1]
        if 'fill="currentColor"' in p and not re.search(r"[^MLCZ0-9.,\s-]", d):
            out += f'<path fill="currentColor" fill-rule="evenodd" d="{lighten(d, tol)}"/>'
        else:                                           # the s of the wordmark is a stroke of arcs, and short already
            out += re.sub(r"\s+", " ", p)
    return out


def svg(view: str, paths: str, attrs: str = "", inner: str = "") -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" role="img" aria-label="Knos"{attrs}>{inner}{paths}</svg>\n'


def square(view: str, pad: float) -> str:
    """A square viewBox around a drawing, with `pad` of its longer side left free on every side."""
    x, y, w, h = (float(v) for v in view.split())
    side = max(w, h) * (1 + 2 * pad)
    return f"{round(x - (side - w) / 2)} {round(y - (side - h) / 2)} {round(side)} {round(side)}"


def tight(view: str, paths: str) -> str:
    """The viewBox that just holds a filled path (its curves' own points bound it)."""
    xs, ys = [], []
    for d in re.findall(r' d="([^"]+)"', paths):
        for curves in subpaths(absolute(d)):
            for b in curves:
                for p in b:
                    xs.append(p.real)
                    ys.append(p.imag)
    return f"{math.floor(min(xs))} {math.floor(min(ys))} {math.ceil(max(xs) - min(xs)) + 1} {math.ceil(max(ys) - min(ys)) + 1}" if xs else view


def absolute(d: str) -> str:
    """A path write_path wrote (M c l h v z, relative) in the absolute M L C Z that subpaths reads."""
    out, cur, start = "", 0j, 0j
    for cmd, body in re.findall(r"([Mclhvz])([^Mclhvz]*)", d):
        n = [float(x) for x in _NUM.findall(body)]
        if cmd == "M":
            cur = start = complex(n[0], n[1])
            out += f"M{cur.real:g},{cur.imag:g}"
        elif cmd == "z":
            out += "Z"
            cur = start
        elif cmd == "c":
            for i in range(0, len(n), 6):
                p = [cur + complex(n[i + j], n[i + j + 1]) for j in (0, 2, 4)]
                out += "C" + " ".join(f"{q.real:g},{q.imag:g}" for q in p)
                cur = p[2]
        else:
            step = {"l": 2, "h": 1, "v": 1}[cmd]
            for i in range(0, len(n), step):
                cur += complex(n[i], n[i + 1]) if cmd == "l" else complex(n[i], 0) if cmd == "h" else complex(0, n[i])
                out += f"L{cur.real:g},{cur.imag:g}"
    return out


def badge_mark(view: str, d: str) -> dict:
    """The small mark for the badge: its path and the transform that sets it 12 units high at (5, 4) of a 20-unit-high badge."""
    x, y, w, h = (float(v) for v in tight(view, f' d="{d}"').split())
    scale = 12 / h
    return {"d": d, "transform": f"translate({5 - x * scale:.2f} {4 - y * scale:.2f}) scale({scale:.5f})", "width": round(w * scale)}


def files() -> dict[Path, str]:
    """Every text file this writes, by path."""
    mark_view, mark_paths = read("knos-mark.svg")
    word_view, word_paths = read("knos-wordmark.svg")
    mark, word, small = lighter_paths(mark_paths, TOLERANCE), lighter_paths(word_paths, TOLERANCE), lighter_paths(mark_paths, SMALL)
    # the favicon: ink on a light tab, paper-white on a dark one; drawn under 24 px, a thin outline in the same colour
    # closes the slits between the feathers, which a 16 px grid can only show as grey
    scheme = (f"<style>svg{{color:{INK}}}@media (prefers-color-scheme:dark){{svg{{color:{INK_DARK}}}}}"
              "@media (max-width:24px){path{stroke:currentColor;stroke-width:30px;stroke-linejoin:round}}</style>")
    bm = badge_mark(mark_view, re.search(r' d="([^"]+)"', small)[1])
    out = {
        BRAND / "mark.svg": svg(mark_view, mark),
        BRAND / "wordmark.svg": svg(word_view, word),
        BRAND / "mark-small.svg": svg(mark_view, small),
        BRAND / "wordmark-light.svg": svg(word_view, word, f' color="{INK}"'),
        BRAND / "wordmark-dark.svg": svg(word_view, word, f' color="{INK_DARK}"'),
        BRAND / "mark.js": ("// Written by scripts/brand.py from web/brand/src/knos-mark.svg: the small mark as web/badge.js draws it at the left\n"
                            "// of a badge (the same text is in src/knos/badge.py; tests/test_brand.py holds the two together).\n"
                            f"export const BADGE_MARK = {json.dumps(bm, indent=1)};\n"),
        ROOT / "web" / "icon.svg": svg(square(tight(mark_view, small), 0.04), small, inner=scheme),
    }
    return out


BADGE_PY = ROOT / "src" / "knos" / "badge.py"
_BADGE_LINE = re.compile(r"^(MARK(?:: dict)? = )\{.*\}  # written by scripts/brand\.py$", re.M)


def badge_py(text: str, bm: dict) -> str:
    line = f"{json.dumps(bm)}  # written by scripts/brand.py"
    if not _BADGE_LINE.search(text):
        raise SystemExit("src/knos/badge.py has no `MARK = {...}  # written by scripts/brand.py` line to write the mark into.")
    return _BADGE_LINE.sub(lambda m: m[1] + line, text)


# ---- pictures: Chromium draws them (scripts/brand_shot.mjs) -----------------------------------------------------------------

def card_html() -> str:
    """The 1200x630 card of a shared link: the wordmark and the one sentence, in the site's paper, ink and type."""
    fonts = (ROOT / "web" / "fonts").as_uri()
    word = (BRAND / "wordmark.svg").read_text(encoding="utf-8").replace("<svg ", '<svg class="w" ', 1)
    head, _, rest = SENTENCE.partition(": ")
    return f"""<!doctype html><meta charset="utf-8"><style>
@font-face {{ font-family: "Bricolage Grotesque"; src: url("{fonts}/bricolage-grotesque.woff2") format("woff2"); font-weight: 200 800; }}
html, body {{ margin: 0; }}
body {{ width: 1200px; height: 630px; box-sizing: border-box; padding: 64px 80px; background: {PAPER}; color: {INK};
  font-family: "Bricolage Grotesque", sans-serif; display: flex; flex-direction: column; justify-content: space-between; }}
.w {{ height: 150px; width: auto; align-self: flex-start; margin-left: -12px; }}
p {{ margin: 0; font-size: 45px; line-height: 1.16; font-weight: 600; letter-spacing: -.025em; max-width: 1040px; }}
p span {{ color: #5a606b; }}
</style><body>{word}<p>{head}: <span>{rest}</span></p></body>"""


def icon_html() -> str:
    """The home-screen icon: the small mark in ink on paper, with room around it (the system rounds the corners)."""
    mark = (BRAND / "mark-small.svg").read_text(encoding="utf-8")
    return (f'<!doctype html><meta charset="utf-8"><body style="margin:0;width:180px;height:180px;display:grid;place-items:center;'
            f'background:{PAPER};color:{INK}"><div style="width:132px;height:132px;display:grid">{mark}</div></body>')


def shot(*args: str) -> str:
    node = shutil.which("node")
    if not node:
        raise SystemExit("node is not installed: the pictures are drawn by scripts/brand_shot.mjs in Chromium.")
    run = subprocess.run([node, str(ROOT / "scripts" / "brand_shot.mjs"), *args], capture_output=True, text=True, timeout=300)
    if run.returncode:
        raise SystemExit(run.stdout + run.stderr)
    return run.stdout


def pngs(work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    for name, html, w, h in (("card", card_html(), 1200, 630), ("apple-touch-icon", icon_html(), 180, 180)):
        page = work / f"{name}.html"
        page.write_text(html, encoding="utf-8")
        shot("page", str(page), str(w), str(h), str(BRAND / f"{name}.png"))
        print(f"wrote web/brand/{name}.png ({(BRAND / f'{name}.png').stat().st_size} bytes)")


def compare(work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    for before, after in (("knos-mark.svg", "mark.svg"), ("knos-wordmark.svg", "wordmark.svg"), ("knos-mark.svg", "mark-small.svg")):
        for size in (64, 256, 1024):
            print(f"{after} at {size}px: {shot('diff', str(SRC / before), str(BRAND / after), str(size), str(work / f'{Path(after).stem}-{size}')).strip()}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write the Knos mark and wordmark from web/brand/src into every file that shows them.")
    ap.add_argument("--check", action="store_true", help="write nothing; fail when a committed file differs")
    ap.add_argument("--png", action="store_true", help="also draw apple-touch-icon.png and card.png (needs node, playwright and Chromium)")
    ap.add_argument("--compare", action="store_true", help="render each original and its lighter copy and count the pixels that differ")
    ap.add_argument("--work", default=str(ROOT / "out" / "brand"), help="where --png and --compare keep their working files")
    args = ap.parse_args(argv)
    out = files()
    bm = json.loads(out[BRAND / "mark.js"].split("= ", 1)[1].rstrip(";\n"))
    out[BADGE_PY] = badge_py(BADGE_PY.read_text(encoding="utf-8"), bm)
    stale = [p for p, text in out.items() if not p.is_file() or p.read_text(encoding="utf-8") != text]
    if args.check:
        for p in stale:
            print(f"{p.relative_to(ROOT).as_posix()} is not what scripts/brand.py writes: run it and commit the result.")
        return 1 if stale else 0
    for p, text in out.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {p.relative_to(ROOT).as_posix()} ({len(text.encode())} bytes)")
    if args.png:
        pngs(Path(args.work))
    if args.compare:
        compare(Path(args.work))
    return 0


if __name__ == "__main__":
    sys.exit(main())
