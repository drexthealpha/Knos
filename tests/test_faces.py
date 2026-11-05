"""The three faces tell one story with one design (TASK-FOUR F1, F4): the front door (web/home.html, its bar from
web/brand/bar.html), the NEAR app (near/web/index.html and its story) and the IRIS page (iris/web/dashboard.html).
Each has the same nav, none says "n/a", "IDT" or "record line", each loads web/brand/tokens.css, and none declares a
colour or a font of its own: every colour and face comes from that one file."""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FACES = {"front door": "web/home.html", "NEAR app": "near/web/index.html", "NEAR story": "near/web/story/index.html", "IRIS page": "iris/web/dashboard.html"}
NAV = ["Home", "NEAR app", "IRIS", "Proof"]
COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")


def text(name):
    return (ROOT / FACES[name]).read_text(encoding="utf-8")


def nav(html):
    m = re.search(r'<nav\b[^>]*aria-label="Knos"[^>]*>(.*?)</nav>', html, re.S)
    return [re.sub(r"<[^>]+>", "", a).strip() for a in re.findall(r"<a\b[^>]*>.*?</a>", m.group(1), re.S)] if m else []


def own_css(html):
    """The page's own CSS: its style blocks and style attributes (tokens.css itself is the one place values live)."""
    return " ".join(re.findall(r"<style\b[^>]*>(.*?)</style>", html, re.S) + re.findall(r'\sstyle="([^"]*)"', html))


@pytest.mark.parametrize("name", FACES)
def test_each_face_has_the_one_nav(name):
    assert nav(text(name)) == NAV


@pytest.mark.parametrize("name", FACES)
def test_no_face_says_n_a_idt_or_record_line(name):
    shown = re.sub(r"<(script|style)\b.*?</\1>", " ", text(name), flags=re.S)
    shown = re.sub(r"<[^>]+>", " ", shown)
    for w in ("n/a", "IDT", "record line"):
        assert w not in shown, (name, w)


@pytest.mark.parametrize("name", FACES)
def test_each_face_loads_the_one_tokens_file_and_declares_no_colour_or_font(name):
    html = text(name)
    assert re.search(r'<link rel="stylesheet" href="[^"]*brand/tokens\.css">', html), name
    css = own_css(html)
    assert not COLOUR.findall(css), (name, COLOUR.findall(css)[:5])
    assert not [f for f in re.findall(r"font-family\s*:\s*([^;}]*)", css) if "var(" not in f], name
    for sheet in re.findall(r'<link rel="stylesheet" href="([^"]+)">', html):
        if not sheet.endswith("tokens.css"):
            body = (ROOT / FACES[name]).parent.joinpath(sheet).read_text(encoding="utf-8")
            assert not COLOUR.findall(body), (name, sheet)


def test_the_front_doors_bar_template_has_the_one_nav():
    assert nav((ROOT / "web/brand/bar.html").read_text(encoding="utf-8").replace("{SP}", "./")) == NAV
