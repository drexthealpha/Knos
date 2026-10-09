"""The mark and the wordmark: one source (web/brand/), small files that carry no script, no address and no colour of
their own, and every place that shows them shows the same drawing. scripts/brand.py writes them from the traced
originals in web/brand/src; nothing here needs a browser."""

from __future__ import annotations

import importlib.util
import json
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from knos import badge

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "web" / "brand"
SVGS = ["mark.svg", "wordmark.svg", "mark-small.svg", "wordmark-light.svg", "wordmark-dark.svg"]
BOUNDS = {"mark.svg": 6_000, "wordmark.svg": 12_000, "mark-small.svg": 3_000, "wordmark-light.svg": 12_000, "wordmark-dark.svg": 12_000}
NS = "{http://www.w3.org/2000/svg}"


def _tool():
    spec = importlib.util.spec_from_file_location("knos_brand_tool", ROOT / "scripts" / "brand.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _paths(text: str) -> list[str]:
    return re.findall(r' d="([^"]+)"', text)


def _png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR"
    return struct.unpack(">II", head[16:24])


def test_the_files_exist_and_are_under_their_bounds():
    for name in SVGS:
        size = (BRAND / name).stat().st_size
        assert 500 < size < BOUNDS[name], (name, size)
    for name in ("knos-mark.svg", "knos-wordmark.svg"):                     # the traced originals stay beside them
        assert (BRAND / "src" / name).stat().st_size > 30_000
    assert (ROOT / "web" / "icon.svg").stat().st_size < 3_000
    assert _png_size(BRAND / "card.png") == (1200, 630) and (BRAND / "card.png").stat().st_size < 300_000
    assert _png_size(BRAND / "apple-touch-icon.png") == (180, 180)
    assert _tool().BOUNDS == {k: BOUNDS[k] for k in ("mark.svg", "wordmark.svg", "mark-small.svg")}


@pytest.mark.parametrize("path", [*(BRAND / n for n in SVGS), ROOT / "web" / "icon.svg", BRAND / "src" / "knos-mark.svg", BRAND / "src" / "knos-wordmark.svg"],
                         ids=lambda p: p.name)
def test_an_svg_has_no_script_no_address_and_no_colour_but_the_readers(path: Path):
    text = _text(path)
    root = ET.fromstring(text)
    assert root.tag == f"{NS}svg" and root.get("viewBox") and root.get("role") == "img" and root.get("aria-label") == "Knos"
    low = text.lower()
    assert not any(w in low for w in ("<script", "<image", "<use", "<a ", "href", "@import", "@font-face", "url(", "<foreignobject", "javascript:", "<!entity", "<!doctype"))
    assert not re.search(r"\son[a-z]+\s*=", low)                                     # no event handler
    assert text.count("http") == 1 and 'xmlns="http://www.w3.org/2000/svg"' in text     # the namespace is the only address
    drawn = [e for e in root.iter() if e.tag in (f"{NS}path", f"{NS}g", f"{NS}circle", f"{NS}rect", f"{NS}ellipse", f"{NS}polygon")]
    assert drawn and all(e.tag == f"{NS}path" for e in drawn)
    for e in root.iter():
        assert e.get("fill") in (None, "currentColor", "none"), (path.name, e.get("fill"))
        assert e.get("stroke") in (None, "currentColor", "none"), (path.name, e.get("stroke"))
        assert "fill" not in (e.get("style") or "")
    for style in root.iter(f"{NS}style"):                                            # a style may set `color` and the outline, never a fill
        assert "fill" not in style.text and set(re.findall(r"stroke:([^;}]*)", style.text)) <= {"currentColor"}
    assert any(e.get("fill") == "currentColor" for e in root.iter(f"{NS}path"))


def test_every_copy_is_the_same_drawing():
    word, small = _paths(_text(BRAND / "wordmark.svg")), _paths(_text(BRAND / "mark-small.svg"))
    assert len(word) == 2 and len(small) == 1 and len(_paths(_text(BRAND / "mark.svg"))) == 1
    assert _paths(_text(BRAND / "wordmark-light.svg")) == word == _paths(_text(BRAND / "wordmark-dark.svg"))
    assert 'color="#15171c"' in _text(BRAND / "wordmark-light.svg") and 'color="#e9ebef"' in _text(BRAND / "wordmark-dark.svg")
    assert _paths(_text(ROOT / "web" / "icon.svg")) == small                         # the favicon is the mark
    icon = _text(ROOT / "web" / "icon.svg")
    assert "prefers-color-scheme:dark" in icon and "#15171c" in icon and "#e9ebef" in icon
    js = json.loads(_text(BRAND / "mark.js").split("BADGE_MARK = ", 1)[1].rstrip().rstrip(";"))
    assert js == badge.MARK and js["d"] == small[0]                                  # the badge of the site and of `knos badge`
    card = _text(ROOT / "scripts" / "video" / "sample" / "card.svg")                  # the title card of the sample video
    assert all(d in card for d in word) and "Sample storyboard" in card


def test_the_badge_has_the_mark_at_its_left():
    text = badge.svg({"repo": "o/r", "pr": 12, "amount": "100.00", "money": "test USDC", "date": "2026-10-03"})
    root = ET.fromstring(text)
    path = root.find(f"{NS}g/{NS}path")
    assert path is not None and path.get("d") == badge.MARK["d"] and path.get("transform") == badge.MARK["transform"]
    label = root.find(f"{NS}g/{NS}text")
    left = float(label.get("x")) - float(label.get("textLength")) / 2                # where the words begin
    assert 5 + badge.MARK["width"] <= left <= 5 + badge.MARK["width"] + 10 and 8 <= badge.MARK["width"] <= 16


def test_the_lighter_outline_stays_on_the_traced_one():
    """Every point of the traced outline is within two units (of 1856: a pixel at 1024 px) of the committed mark."""
    tool = _tool()
    view, paths = tool.read("knos-mark.svg")
    assert view == re.search(r'viewBox="([^"]+)"', _text(BRAND / "mark.svg"))[1]
    before = [p for s in tool.subpaths(re.search(r' d="([^"]+)"', paths[0])[1]) for p in tool.sample(s, 2.0)]
    after_outlines = tool.subpaths(tool.absolute(_paths(_text(BRAND / "mark.svg"))[0]))
    assert len(after_outlines) == 5 == len(tool.subpaths(re.search(r' d="([^"]+)"', paths[0])[1]))
    cells: dict[tuple[int, int], list[complex]] = {}
    for s in after_outlines:
        for p in tool.sample(s, 0.5):
            cells.setdefault((int(p.real) // 4, int(p.imag) // 4), []).append(p)
    far = 0.0
    for p in before:
        cx, cy = int(p.real) // 4, int(p.imag) // 4
        near = [q for dx in (-1, 0, 1) for dy in (-1, 0, 1) for q in cells.get((cx + dx, cy + dy), ())]
        assert near, p
        far = max(far, min(abs(p - q) for q in near))
    assert far <= 2.0, far
    assert sum(len(s) for s in after_outlines) < 400                                 # and it takes a quarter of the curves


def test_fitting_keeps_a_shape_and_drops_its_curves():
    tool = _tool()
    square_of_steps = "M0,0" + "".join(f"L{x},0" for x in range(10, 410, 10)) + "".join(f"L400,{y}" for y in range(10, 310, 10)) + "L0,300Z"
    assert tool.lighten(square_of_steps, 1.0) in ("M0 0h400v300h-400z", "M0 0h400v300h-400v-300z")
    assert tool.absolute("M5 6h10v20l-10-20z") == "M5,6L15,6L15,26L5,6Z"


def test_the_readme_header_shows_the_wordmark_on_both_of_githubs_themes_and_on_pypi():
    """GitHub picks a <source> by theme; PyPI drops <source> and keeps an <img> whose src is absolute (its cleaner,
    readme_renderer's clean.py, allows img src and no source tag), so every address names the file at this release's
    tag: a relative path was a broken image on the PyPI page of 0.3.22. scripts/bump_version.py moves the tag."""
    head = "\n".join(_text(ROOT / "README.md").splitlines()[:12])
    at = f"https://raw.githubusercontent.com/drexthealpha/Knos/v{_version()}/"
    sources = re.findall(r'<source media="\(prefers-color-scheme: (dark|light)\)" srcset="([^"]+)">', head)
    assert dict(sources) == {"dark": at + "web/brand/wordmark-dark.svg", "light": at + "web/brand/wordmark-light.svg"}
    img = re.search(r'<img alt="Knos" src="([^"]+)"', head)
    assert "<picture>" in head and "</picture>" in head and img and img[1] == at + "web/brand/wordmark-light.svg"
    for ref in {img[1], *(s for _, s in sources)}:
        assert (ROOT / ref.removeprefix(at)).is_file()
    assert "**The neutral meter for AI agent work: neither side keeps the count.**" in head                                  # the one sentence, and no other


def test_the_site_names_its_own_files_for_the_icon_and_the_card():
    page = _text(ROOT / "web" / "index.html")
    assert '<link rel="icon" href="icon.svg" type="image/svg+xml">' in page and '<link rel="apple-touch-icon" href="brand/apple-touch-icon.png">' in page
    assert '<meta property="og:image" content="https://drexthealpha.github.io/Knos/brand/card.png">' in page
    assert badge.SITE == "https://drexthealpha.github.io/Knos"
    head = page.split("</head>")[0]
    assert not re.findall(r'(?:href|src)="(?:https?:)?//', head)                     # the head asks no other host for anything
    css = _text(ROOT / "web" / "app.css")
    assert 'url("brand/wordmark.svg")' in css and 'url("brand/mark.svg")' in css
    for slot in ("status", "index", "pilot", "reproduce", "shadow", "verifier", "playground"):      # pages other modules fill: empty, hidden
        assert f'<section id="{slot}" class="mount" aria-label="{slot.capitalize()}" hidden></section>' in page
        assert f'<a href="#{slot}" data-mount="{slot}" hidden>' in page and f'"{slot}"' in _text(ROOT / "web" / "front.js")


def test_the_mark_with_depth_is_the_same_drawing_and_costs_no_download():
    """web/brand/mark3d.js draws no path of its own: every layer is brand/mark.svg as a mask (the stylesheet names the
    file), stacked on the z axis. No canvas, no WebGL, no library, no address; with motion.js under 18 KB (the budget
    tests/web/motion.mjs holds: 0.3.17 added countTo, sort, toast, skeleton and leave)."""
    js, motion, css = _text(BRAND / "mark3d.js"), _text(ROOT / "web" / "motion.js"), _text(ROOT / "web" / "app.css")
    assert "export function mount3dMark(el" in js and len(js.encode()) + len(motion.encode()) < 18_000
    code = re.sub(r"^\s*//.*$", "", js + motion, flags=re.M)
    assert not re.search(r"canvas|webgl|three|fetch\(|XMLHttpRequest|https?:|import\s|require\(| d=", code, re.I)
    assert "prefers-reduced-motion: reduce" in js and "prefers-reduced-motion: reduce" in motion and "prefers-reduced-motion: reduce" in css
    for name in ("prefersReduced", "tilt", "reveal", "travel", "raven"):                 # the design contract's five
        assert re.search(rf"export (?:const|function) {name}\b", motion), name
    for rule in (".k-mark3d i {", ".k-raven {"):
        assert 'mask: url("brand/mark.svg") center / contain no-repeat' in css.split(rule, 1)[1].split("}", 1)[0]
    assert "aspect-ratio: 1856 / 1756" in css.split(".k-mark3d {", 1)[1].split("}", 1)[0]       # the box is the mark's before it is drawn
    assert re.search(r'viewBox="0 0 1856 1756"', _text(BRAND / "mark.svg"))
    page = _text(ROOT / "web" / "index.html")
    assert '<div class="hero-mark" id="mark3d" aria-hidden="true"></div>' in page and "<canvas" not in page
    for name in ("--ink", "--ink-2", "--paper", "--paper-2", "--line", "--accent", "--ok", "--bad", "--radius", "--depth-1", "--depth-2", "--depth-3", "--ease", "--dur-1", "--dur-2", "--dur-3"):
        assert f"{name}:" in css, name
    for cls in (".k-card", ".k-btn", ".k-btn.quiet", ".k-kicker", ".k-num", ".k-step", ".k-stage", ".k-reveal", ".k-table", "[data-tilt]"):
        assert cls in css, cls
    for state in ("live", "done", "bad"):
        assert f'.k-step[data-state="{state}"]' in css


def _version() -> str:
    return re.search(r'(?m)^version = "([^"]+)"', _text(ROOT / "pyproject.toml"))[1]


def test_a_bump_moves_the_readme_logo_to_the_new_tag(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("bump_version", ROOT / "scripts" / "bump_version.py")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    head = "\n".join(_text(ROOT / "README.md").splitlines()[:7])
    spans = [m.span() for m in b.PIN.finditer(head)]
    assert len(spans) == 3 and all(head[x:y].startswith("raw.githubusercontent.com/drexthealpha/Knos/v" + _version()) for x, y in spans)
