"""The tool's pages and link images (Round 13, B1 and B2): /t/<id>/ and /r/<result-id>/ as server-written HTML whose
first response already holds og:title, og:description and og:image (a reader with no script, a chat app's link
preview), and GET /og/<t|r>/<id>.png, a 1200 x 630 PNG with the Knos mark, the title and, for a result, the result line.

Standard library only (the app has no image library): the PNG is written with zlib, the mark is the app's own
icon-192.png decoded here, and the letters are a 5 x 8 bitmap font drawn as blocks.

Round 13, H3: every visible string of the two pages comes from web/i18n/<lang>.json, in the language ?lang= names or
the browser's Accept-Language asks for (a, U7 R1 to R7 and R13 to R17); the result page's fold has Listen (b), the
line of HTML that shows the result on another site and the printed page (c, d); the fold opens with the five answers (f)."""
from __future__ import annotations

import csv
import html
import io
import json
import os
import re
import struct
import zlib
from collections import OrderedDict
from pathlib import Path

STATIC = Path(__file__).parent / "static"

# 5 x 8 bitmap font, printable ASCII from 0x20: five columns per glyph, bit 0 the top row (bit 7 a descender's row)
_FONT_HEX = (
    "0000000000" "00005f0000" "0007000700" "147f147f14" "242a7f2a12" "2313086462" "3649562050" "0008070300"
    "001c224100" "0041221c00" "2a1c7f1c2a" "08083e0808" "0080703000" "0808080808" "0000606000" "2010080402"
    "3e5149453e" "00427f4000" "7249494946" "2141494d33" "1814127f10" "2745454539" "3c4a494931" "4121110907"
    "3649494936" "464949291e" "0000140000" "0040340000" "0008142241" "1414141414" "0041221408" "0201590906"
    "3e415d594e" "7c1211127c" "7f49494936" "3e41414122" "7f4141413e" "7f49494941" "7f09090901" "3e41415173"
    "7f0808087f" "00417f4100" "2040413f01" "7f08142241" "7f40404040" "7f021c027f" "7f0408107f" "3e4141413e"
    "7f09090906" "3e4151215e" "7f09192946" "2649494932" "03017f0103" "3f4040403f" "1f2040201f" "3f4038403f"
    "6314081463" "0304780403" "61594d4943" "007f414141" "0204081020" "004141417f" "0402010204" "4040404040"
    "0003070800" "2054547840" "7f28444438" "3844444428" "384444287f" "3854545418" "00087e0902" "18a4a49c78"
    "7f08040478" "00447d4000" "2040403d00" "7f10284400" "00417f4000" "7c04780478" "7c08040478" "3844444438"
    "fc18242418" "18242418fc" "7c08040408" "4854545424" "04043f4424" "3c4040207c" "1c2040201c" "3c4030403c"
    "4428102844" "4c9090907c" "4464544c44" "0008364100" "0000770000" "0041360800" "0201020402"
)
FONT = {chr(0x20 + i): bytes.fromhex(_FONT_HEX[i * 10:i * 10 + 10]) for i in range(len(_FONT_HEX) // 10)}

W, H = 1200, 630
INK = (0x15, 0x17, 0x1c)
ACCENT = (0x2b, 0x3b, 0xb5)
MUTED = (0x4a, 0x50, 0x5c)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png(w: int, h: int, rgb: bytes | bytearray) -> bytes:
    """An 8-bit RGB PNG of w x h pixels from rows of RGB bytes."""
    row = w * 3
    raw = b"".join(b"\x00" + bytes(rgb[y * row:(y + 1) * row]) for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw, 6)) + _chunk(b"IEND", b""))


def decode_rgb(data: bytes) -> tuple[int, int, bytearray]:
    """An 8-bit RGB, non-interlaced PNG (the app's icons) as (w, h, RGB bytes)."""
    pos, idat = 8, b""
    w = h = 0
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, lace = struct.unpack(">IIBBBBB", body)
            if (depth, ctype, lace) != (8, 2, 0):
                raise ValueError("only 8-bit RGB, non-interlaced")
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    raw, bpp, row = zlib.decompress(idat), 3, w * 3
    out = bytearray(h * row)
    prev = bytearray(row)
    for y in range(h):
        f, line = raw[y * (row + 1)], bytearray(raw[y * (row + 1) + 1:(y + 1) * (row + 1)])
        for i in range(row):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out[y * row:(y + 1) * row] = line
        prev = line
    return w, h, out


class Canvas:
    def __init__(self, w: int, h: int, bg: tuple):
        self.w, self.h = w, h
        self.buf = bytearray(bytes(bg) * (w * h))

    def rect(self, x: int, y: int, w: int, h: int, color: tuple) -> None:
        x0, x1 = max(0, x), min(self.w, x + w)
        if x1 <= x0:
            return
        line = bytes(color) * (x1 - x0)
        for yy in range(max(0, y), min(self.h, y + h)):
            s = (yy * self.w + x0) * 3
            self.buf[s:s + len(line)] = line

    def text(self, x: int, y: int, s: str, scale: int, color: tuple) -> None:
        for ch in s:
            g = FONT.get(ch) or FONT["?"]
            for col, bits in enumerate(g):
                for r in range(8):
                    if bits >> r & 1:
                        self.rect(x + col * scale, y + r * scale, scale, scale, color)
            x += 6 * scale

    def paste(self, w: int, h: int, rgb: bytes | bytearray, x: int, y: int) -> None:
        for yy in range(h):
            if 0 <= y + yy < self.h:
                s = ((y + yy) * self.w + x) * 3
                self.buf[s:s + w * 3] = rgb[yy * w * 3:(yy + 1) * w * 3]


def _wrap(s: str, per_line: int) -> list[str]:
    lines, cur = [], ""
    for word in s.split():
        if cur and len(cur) + 1 + len(word) > per_line:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + ([cur] if cur else [])


_icon: dict = {}
_cache: "OrderedDict[tuple, bytes]" = OrderedDict()


def og_png(title: str, line: str | None = None) -> bytes:
    """The link image: the Knos mark and name, the title, and the result line when there is one (1200 x 630)."""
    key = (title, line)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    if "mark" not in _icon:
        _icon["mark"] = decode_rgb((STATIC / "brand" / "icon-192.png").read_bytes())
    iw, ih, rgb = _icon["mark"]
    bg = tuple(rgb[0:3])                         # the icon's own paper: the mark sits on the page with no box
    c = Canvas(W, H, bg)
    c.paste(iw, ih, rgb, 64, 40)
    c.text(64 + iw + 16, 40 + (ih - 80) // 2, "Knos", 10, INK)
    margin, width = 80, W - 160
    lines = _wrap(title, width // 48)[:2]
    y = 270
    for t in lines:
        c.text(margin, y, t, 8, INK)
        y += 84
    if line:
        for t in _wrap(line, width // 30)[:3]:          # scale 5: 30 px a letter, up to three lines
            c.text(margin, y + 20, t, 5, ACCENT)
            y += 52
    c.rect(0, H - 16, W, 16, ACCENT)
    out = png(W, H, c.buf)
    _cache[key] = out
    while len(_cache) > 64:
        _cache.popitem(last=False)
    return out




# ---- languages (Round 13, H3 a) --------------------------------------------------------------------------------------
# Every visible string of these pages, the front door and the pricing page comes from one file per language,
# web/i18n/<lang>.json (U7 R19). The server reads them from the repository's root (KNOS_NEAR_ROOT in the image, as
# tool_run.root()); scripts/site_pages.py reads the same files when it builds the Pages site. A value that is an object
# holds one form per CLDR plural category of its language (U7 R7), chosen by {n}.
ROOT = Path(os.environ.get("KNOS_NEAR_ROOT") or Path(__file__).resolve().parents[3])
LANGS = ("en", "ar", "hi", "es", "fr", "pt", "zh-Hans", "id", "sw", "ru")
ISSUES = "https://github.com/drexthealpha/Knos/issues"
PRICING_FILE = "https://drexthealpha.github.io/Knos/data/pricing.json"
TEST_URL = "https://github.com/drexthealpha/Knos/blob/main/near/agents/job/test_limit.py"   # the locked test (tool_run.TEST_URL)
_tables: dict = {}


def i18n_dir() -> Path:
    return ROOT / "web" / "i18n"


CATS = ("zero", "one", "two", "few", "many", "other")


def message(v):
    """A message as the pages use it: its text, or its plural forms. In en.json each message also carries, for the
    translator, a description and a max_length (U7 R31): {"text", "description", "max_length"}, or the plural forms beside
    the two fields; the other files hold the text or the forms alone."""
    if isinstance(v, dict):
        return v["text"] if "text" in v else {c: v[c] for c in CATS if c in v}
    return v


def read_file(path: Path) -> dict:
    """A locale file with every message as message() gives it."""
    d = json.loads(path.read_text(encoding="utf-8"))
    d["strings"] = {k: message(v) for k, v in d["strings"].items()}
    return d


def table(lang: str) -> dict:
    """One language's file: {"_meta": {...}, "strings": {...}}, read once, each message as message() gives it."""
    if lang not in _tables:
        _tables[lang] = read_file(i18n_dir() / f"{lang}.json")
    return _tables[lang]


def meta(lang: str) -> dict:
    return table(lang)["_meta"]


def match(tag: str | None) -> str | None:
    """A language tag (ar-EG, pt-BR, zh-CN, fr) as one of LANGS, else None. Never a guess from a place (U7 R17)."""
    t = str(tag or "").strip().lower()
    if not t:
        return None
    for code in LANGS:
        if t == code.lower():
            return code
    base = t.split("-")[0].split("_")[0]
    if base == "zh":
        return "zh-Hans"
    return base if base in LANGS else None


def pick(asked: str | None, accept: str | None) -> str:
    """The page's language: ?lang= when it names one Knos ships, else the first of the browser's Accept-Language list
    (by its q weights) that Knos ships, else English (U7 R17)."""
    got = match(asked)
    if got:
        return got
    tags = []
    for i, part in enumerate(str(accept or "").split(",")):
        bits = part.strip().split(";")
        q = 1.0
        for b in bits[1:]:
            if b.strip().startswith("q="):
                try:
                    q = float(b.strip()[2:])
                except ValueError:
                    q = 0.0
        tags.append((-q, i, bits[0]))
    for _, _, tag in sorted(tags):
        got = match(tag)
        if got:
            return got
    return "en"


def plural(lang: str, n) -> str:
    """The CLDR cardinal plural category of n in this language (the rules Intl.PluralRules applies; tested against it)."""
    n = abs(float(n))
    i, whole = int(n), float(n).is_integer()
    if lang in ("zh-Hans", "id"):
        return "other"
    if lang in ("en", "sw"):
        return "one" if n == 1 and whole else "other"
    if lang == "hi":
        return "one" if i == 0 or n == 1 else "other"
    million = whole and i != 0 and i % 1000000 == 0
    if lang == "es":
        return "one" if n == 1 else "many" if million else "other"
    if lang in ("fr", "pt"):
        return "one" if i in (0, 1) else "many" if million else "other"
    if lang == "ru":
        if not whole:
            return "other"
        m10, m100 = i % 10, i % 100
        return "one" if m10 == 1 and m100 != 11 else "few" if 2 <= m10 <= 4 and not 12 <= m100 <= 14 else "many"
    if lang == "ar":
        if not whole:
            return "other"
        m100 = i % 100
        return {0: "zero", 1: "one", 2: "two"}.get(i) or ("few" if 3 <= m100 <= 10 else "many" if 11 <= m100 <= 99 else "other")
    return "other"


# how each language writes a count and a sum of US dollars (CLDR, as Intl.NumberFormat writes them; a test holds the two
# to each other, U7 R13 and R14). Values read from a person's file are never reformatted: they stay as the file has them.
GROUP = {"en": ",", "ar": ",", "hi": ",", "es": ".", "fr": "\u202f", "pt": ".", "zh-Hans": ",", "id": ".", "sw": ",", "ru": "\u00a0"}
DECIMAL = {"es": ",", "fr": ",", "pt": ",", "id": ",", "ru": ","}
MONEY = {"en": "${}", "ar": "\u200f{}\u00a0US$", "hi": "${}", "es": "{}\u00a0$", "fr": "{}\u00a0$", "pt": "$\u00a0{}",
         "zh-Hans": "${}", "id": "${}", "sw": "$\u00a0{}", "ru": "{}\u00a0$"}


def nf(lang: str, n) -> str:
    """A whole count in the language's own grouping (Hindi groups by lakh; Spanish leaves four digits ungrouped)."""
    neg, s = int(n) < 0, str(abs(int(n)))
    g = GROUP.get(lang, ",")
    if lang == "es" and len(s) <= 4:
        out = s
    elif lang == "hi" and len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        out = g.join(([head] if head else []) + parts) + g + tail
    else:
        out = f"{int(s):,}".replace(",", g)
    return ("-" if neg else "") + out


def money(lang: str, x) -> str:
    x = float(x)
    num = nf(lang, int(x)) if x.is_integer() else nf(lang, int(x)) + DECIMAL.get(lang, ".") + f"{x:.2f}".split(".")[1]
    return MONEY.get(lang, "${}").format(num)


class Bdi(str):
    """A value inserted into a sentence that keeps its own direction (U7 R2): a number or name from the person's file."""


def raw(lang: str, key: str, n=None) -> str:
    s = table(lang)["strings"].get(key)
    if s is None:
        s = table("en")["strings"][key]
    if isinstance(s, dict):
        s = s.get(plural(lang, n or 0)) or s["other"]
    return s


def _val(lang: str, name: str, x) -> str:
    if name in ("price", "low", "high"):
        return money(lang, x)
    if name in ("n", "free", "r") and isinstance(x, (int, float)) and not isinstance(x, bool):
        return nf(lang, x)
    return str(x)


def t(lang: str, key: str, **v) -> str:
    """A string as plain text (an attribute, a title, a sentence read aloud)."""
    return re.sub(r"\{(\w+)\}", lambda m: _val(lang, m[1], v[m[1]]) if m[1] in v else m[0], raw(lang, key, v.get("n")))


def h(lang: str, key: str, spans: dict | None = None, **v) -> str:
    """A string as HTML: the file's own markup (links only) kept, every value escaped; a value named in `spans` is
    wrapped in <span data-n="name"> so the build's number checks can find it; a Bdi value is isolated in <bdi>."""
    spans = spans or {}
    attr = lambda name: spans[name] if "=" in spans[name] else f'data-n="{spans[name]}"'   # noqa: E731

    def one(m):
        name = m[1]
        if name not in v:
            return m[0]
        x = v[name]
        if name in spans and name in ("price", "low", "high"):
            num = _val(lang, "n", int(float(x))) if float(x).is_integer() else str(x)
            return _e(MONEY.get(lang, "${}")).replace("{}", f'<span {attr(name)}>{_e(num)}</span>')
        out = _e(_val(lang, name, x))
        if name in spans:
            out = f'<span {attr(name)}>{out}</span>'
        return f"<bdi>{out}</bdi>" if isinstance(x, Bdi) else out
    return re.sub(r"\{(\w+)\}", one, raw(lang, key, v.get("n")))


# the result sentence comes from the released program, in English, from a fixed template (SPEC2); other languages show
# the same facts through that template's translation, and the fold keeps the program's own words
RS = re.compile(r"^(?:Failed at row (\d+): (.+?) is not (above|below) (.+?)\. It passed for the (\d+) rows before that\."
                r"|Passed: all (\d+) rows stay (above|below) (.+?)\.)(?: (\d+) rows were skipped because they are not numbers\.)?$")


# what sets two sentences of the result apart: a space, except in Chinese, which writes them side by side (a rule of the
# script, not a message to translate, so it is not in the locale files)
SEP = {"zh-Hans": ""}


def sentence(lang: str, text: str, as_html: bool = True) -> str:
    """The program's result sentence in this language: English as the program wrote it; any other language from the
    fixed template, every count in the language's digits, every value from the file as written there."""
    if text == UNKNOWN:
        return _e(t(lang, "rs.unknown")) if as_html else t(lang, "rs.unknown")
    m = RS.match(text or "")
    if lang == "en" or not m:
        return _e(text) if as_html else str(text or "")
    f = h if as_html else (lambda lg, k, **v: t(lg, k, **v))
    if m[1]:
        parts = [f(lang, f"rs.fail_{m[3]}", r=int(m[1]), value=Bdi(m[2]), limit=Bdi(m[4])), f(lang, "rs.before", n=int(m[5]))]
    else:
        parts = [f(lang, f"rs.pass_{m[7]}", n=int(m[6]), limit=Bdi(m[8]))]
    if m[9]:
        parts.append(f(lang, "rs.skipped", n=int(m[9])))
    return SEP.get(lang, " ").join(parts)


# The verdict (U6 Rules 5 to 7, 10, 15 and 20): one of three states, each with its own icon and word; the result
# sentence first; then the evidence (the rows checked and the test the program passed), or, when no row held a number,
# the reason; then one next step. A result with no numeric row is "cannot tell" (tool_run.verdict_of), never a pass.
UNKNOWN = "I cannot tell: no row held a number."
STATES = ("pass", "fail", "unknown")
_SHAPES = {"pass": '<circle cx="12" cy="12" r="10"/><path d="M7 12.5l3.5 3.5L17 9"/>',
           "fail": '<rect x="2.5" y="2.5" width="19" height="19" rx="3"/><path d="M8.5 8.5l7 7M15.5 8.5l-7 7"/>',
           "unknown": '<path d="M12 2.5l10 18H2z"/><path d="M12 9.5v5M12 17.5v.5"/>'}


def verdict_of(r: dict) -> str:
    """pass, fail or unknown: the stored verdict, else the first failing row, else whether any row held a number."""
    v = r.get("verdict")
    if v in STATES:
        return v
    ffr = r.get("first_failing_row")
    if isinstance(ffr, int) and not isinstance(ffr, bool):
        return "fail"
    return "pass" if int(r.get("rows") or 0) > 0 else "unknown"


def icon(lang: str, state: str) -> str:
    """The verdict's icon: a tick in a circle, a cross in a square, a mark in a triangle; named in the page's language."""
    return (f'<svg role="img" aria-label="{_e(t(lang, "v." + state))}" viewBox="0 0 24 24" width="28" height="28" fill="none" '
            f'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">{_SHAPES[state]}</svg>')


def answer_html(lang: str, r: dict, test_url: str = TEST_URL) -> str:
    """The answer block: icon, sentence (p.big#about), evidence or reason, next step."""
    state = verdict_of(r)
    m = RS.match(r.get("result") or "")
    col = Bdi(r.get("column") or "")
    lim = Bdi(m[4] if m and m[1] else m[8] if m else shown_limit(r.get("limit") or 0))
    out = f'{icon(lang, state)}<p class="big" id="about">{sentence(lang, r.get("result") or "")}</p>'
    if state == "unknown":
        out += (f'<p data-reason data-uncertain="true">{h(lang, "why.unknown", column=col)}</p>'
                f'<p data-next-step>{h(lang, "next.unknown")}</p>')
    else:
        ffr = r.get("first_failing_row") or 0
        ev = (h(lang, "ev.fail", r=int(ffr), column=col, value=Bdi(m[2]), limit=lim) if state == "fail" and m and m[1]
              else h(lang, "ev.pass", n=int(r.get("rows") or 0), column=col, limit=lim))
        # the first screen holds the verdict and its comparison, the row quoted from the file (U6 Rules 10 and 11); what to
        # do next and the test behind it open the part below it, under a heading (U3 Rule 1a: three controls on the first
        # screen; U2 R3: 40 words a section), still inside the answer, so the source stays the answer's own (U4 R12)
        out += (f'<p data-evidence><span data-compare data-quote>{ev}</span></p>'
                f'<div class="later"><h2>{_e(t(lang, "q.next"))}</h2><p data-next-step>{h(lang, "next." + state, r=int(ffr))}</p>'
                f'<p><a class="src" href="{_e(test_url)}" data-verified>{_e(t(lang, "res.shown_by"))}</a></p></div>')
    return f'<div class="answer" data-answer data-verdict data-state="{state}">{out}</div>'


def strings_for(lang: str, keys) -> dict:
    """The strings a page's script needs, in one language (English where a key is missing)."""
    s, en = table(lang)["strings"], table("en")["strings"]
    return {k: s.get(k, en[k]) for k in keys}


def keys_in(js: str) -> list[str]:
    return sorted(set(re.findall(r"""\bT\(\s*["']([\w.]+)["']""", js)) | set(re.findall(r'"([a-z]+\.[\w.]+)"', js)) & set(table("en")["strings"]))


GLOBE = ('<svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
         '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/></svg>')


def switcher(lang: str) -> str:
    """The language control (U7 R18): at the top of every screen, a word as well as an icon, each language written in
    itself, the current one first. Plain links: it works with no script. A plain <details>, like the fold."""
    order = [lang] + [c for c in LANGS if c != lang]
    cur = ' aria-current="true"'
    links = "".join(f'<a href="?lang={c}" lang="{c}" hreflang="{c}" dir="{meta(c)["dir"]}"'
                    f'{cur if c == lang else ""}>{_e(meta(c)["name"])}</a>' for c in order)
    return (f'<div class="klang" data-language-switcher><details><summary aria-label="{_e(t(lang, "lang.label"))}">{GLOBE}'
            f'<span lang="{lang}">{_e(meta(lang)["name"])}</span></summary><div class="klang-list">{links}</div></details></div>')


def warm_names() -> str:
    """Every language's own name, laid out unseen, so the scripts' fonts are ready before the language control opens
    (U1 R3: drawing ten scripts for the first time took 170 to 190 ms at 4x CPU when the list opened on the tool page)."""
    return '<span class="klang-list kwarm" aria-hidden="true">' + "".join(f'<span lang="{c}">{_e(meta(c)["name"])}</span>' for c in LANGS) + "</span>"


SWITCH_CSS = (".klang-list.kwarm{display:block;position:absolute;visibility:hidden;inline-size:1px;block-size:1px;overflow:hidden;padding:0;border:0}"
              ".klang-list.kwarm>span{position:absolute;inset-inline-start:0;inset-block-start:0}"
              ".klang{position:relative}.klang details{margin:0;padding:0;border:0}"
              ".klang summary{display:inline-flex;align-items:center;gap:6px;min-height:48px;min-width:48px;padding:0 10px;cursor:pointer;"
              "list-style:none;border:2px solid var(--line);border-radius:10px;font-size:1rem;font-weight:400}"
              ".klang details summary::before{content:none}.klang summary::-webkit-details-marker{display:none}"
              ".klang-list{position:absolute;inset-inline-end:0;top:50px;z-index:40;display:flex;flex-direction:column;min-width:min(11em,calc(100vw - 32px));max-width:calc(100vw - 32px);"
              "padding:6px 10px;background:var(--paper-2,var(--card));border:1px solid var(--line);border-radius:10px}"
              ".klang-list a{display:flex;align-items:center;min-height:48px;color:inherit;text-decoration:none}"
              ".klang-list a[aria-current]{font-weight:700}details:not([open])>:not(summary){display:none}"
              ":lang(ar){line-height:1.65}:lang(hi){line-height:1.85}"
              ".five dt{font-weight:700;margin:10px 0 0}.five dd{margin:0}.tgt{display:none}.tgt:target{display:block}")


def five(lang: str, answers: list[str]) -> str:
    """The fold's first five lines (H3 f; Plain Language Spec section 2), in this order, each answer as HTML."""
    qs = ("q.get", "q.next", "q.pay", "q.why", "q.who")
    return '<dl class="five">' + "".join(f"<dt>{_e(t(lang, q))}</dt><dd>{a}</dd>" for q, a in zip(qs, answers)) + "</dl>"


def facts() -> dict:
    """What the fold says about the tool: the sample's numbers, the test, the prices and the release (tool_run)."""
    from . import tool_run
    from .runner_conf import CONF
    text = tool_run.sample()
    rows = list(csv.DictReader(io.StringIO(text))) if text else []
    col = CONF["sample_column"]
    return {"made_up": bool(CONF.get("sample_made_up")), "first": rows[0][col] if rows else "", "last": rows[-1][col] if rows else "",
            "rows": len(rows), "limit": shown_limit(CONF["sample_limit"]), "url": CONF["limit_rule_url"],
            "longest": tool_run.longest_test_file(), "test_url": tool_run.TEST_URL, "job": tool_run.job_link(),
            "ready": tool_run.ready(), "free": int(CONF["free_runs_a_day"]), "runs": int(CONF["pack_runs"]),
            "price": float(str(CONF["pack_price"]).lstrip("US$ "))}


def fold_items(lang: str, f: dict, spans: dict | None = None) -> list[str]:
    """The fold after the five lines, in A5's order: the sample's source, what it does not do, your file, the test,
    the price, who built it (each as HTML)."""
    sp = spans or {}
    first = (h(lang, "fold.sample_made_up", n=f["rows"], first=Bdi(f["first"]), last=Bdi(f["last"]), limit=Bdi(f["limit"]), url=f["url"])
             if f["made_up"] else h(lang, "fold.sample_nasa", url=f["url"]))
    return [first, h(lang, "fold.not_do"), h(lang, "fold.file"), h(lang, "fold.test", n=f["longest"], url=f["test_url"]),
            h(lang, "fold.price", {k: v for k, v in sp.items() if k in ("free", "n", "price")}, free=f["free"], n=f["runs"], price=f["price"]),
            h(lang, "fold.built_released", url=f["job"]) if f["job"] else h(lang, "fold.built_unreleased")]


def answers(lang: str, screen: str, f: dict) -> list[str]:
    """The five answers of the tool screen ("tool") or the result screen ("result")."""
    why = "a.why_released" if f["ready"] else "a.why_unreleased"
    head = [h(lang, "a.tool.get"), h(lang, "a.tool.next")] if screen == "tool" else [h(lang, "a.res.get"), h(lang, "a.res.next")]
    return head + [h(lang, "a.pay", free=f["free"], price=f["price"], n=f["runs"]), h(lang, why, n=f["longest"]),
                   h(lang, "a.tool.who", issues=ISSUES)]


def price_answers(lang: str, n: dict, spans: dict | None = None) -> list[str]:
    """The five answers of the pricing page, from docs/data/pricing.json's numbers (free_runs_per_day, pack_runs, pack_price)."""
    v = {"free": n["free_runs_per_day"], "n": n["pack_runs"], "price": n["pack_price"]}
    sp = spans or {}
    return [h(lang, "a.price.get", sp, **v), h(lang, "a.price.next"), h(lang, "a.price.pay", sp, **v),
            h(lang, "a.price.why", url=PRICING_FILE, test=TEST_URL), h(lang, "a.price.who", issues=ISSUES)]


def speech_lang(lang: str) -> str:
    return {"zh-Hans": "zh-CN"}.get(lang, lang)


# the shared runtime of the pages' scripts: the strings of one language, their plural forms, counts and sums of money
# in that language's own writing, and the result sentence from its fixed template (the same rules as the Python above)
I18N_JS = r"""window.KI = window.KI || (() => {
  let L = "en", S = {};
  // one formatter of each kind per language, made once (making one costs far more than using it: over 100 ms at 4x CPU
  // on the first press), and made ahead when the page is idle
  const made = new Map(), once = (k, f) => { const key = L + " " + k; if (!made.has(key)) made.set(key, f()); return made.get(key); };
  const plural = (n) => { try { return once("p", () => new Intl.PluralRules(L)).select(n); } catch (e) { return "other"; } };
  const nf = (n) => { try { return once("n", () => new Intl.NumberFormat(L)).format(n); } catch (e) { return String(n); } };
  const money = (x) => { try { const d = x % 1 ? 2 : 0; return once("m" + d, () => new Intl.NumberFormat(L, { style: "currency", currency: "USD", currencyDisplay: "narrowSymbol", minimumFractionDigits: d, maximumFractionDigits: d })).format(x); } catch (e) { return String(x) + " USD"; } };
  const warm = () => { plural(1); nf(1); money(1); }, idle = (f) => (window.requestIdleCallback || ((g) => setTimeout(g, 200)))(f);
  const raw = (k, v) => { let s = S[k]; if (s == null) return k; if (typeof s === "object") s = s[plural(v && v.n != null ? +v.n : 0)] || s.other; return s; };
  const val = (name, x) => /^(price|low|high)$/.test(name) ? money(+x) : /^(n|free|r)$/.test(name) && typeof x === "number" ? nf(x) : String(x);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const bdi = new Set(["value", "limit", "first", "last", "column", "names"]);
  const t = (k, v) => raw(k, v).replace(/\{(\w+)\}/g, (m, n) => v && v[n] != null ? val(n, v[n]) : m);
  const html = (k, v) => raw(k, v).replace(/\{(\w+)\}/g, (m, n) => v && v[n] != null ? (bdi.has(n) ? "<bdi>" + esc(val(n, v[n])) + "</bdi>" : esc(val(n, v[n]))) : m);
  const sep = () => L === "zh-Hans" ? "" : " ";   // Chinese sets sentences side by side, with no space (SEP)
  const RS = /^(?:Failed at row (\d+): (.+?) is not (above|below) (.+?)\. It passed for the (\d+) rows before that\.|Passed: all (\d+) rows stay (above|below) (.+?)\.)(?: (\d+) rows were skipped because they are not numbers\.)?$/;
  function sentence(text, plain) {
    if (text === "I cannot tell: no row held a number." && S["rs.unknown"] != null) return plain ? t("rs.unknown") : esc(t("rs.unknown"));
    const m = RS.exec(text || ""), f = plain ? t : html;
    if (L === "en" || !m) return plain ? String(text || "") : esc(text || "");
    const parts = m[1] ? [f("rs.fail_" + m[3], { r: +m[1], value: m[2], limit: m[4] }), f("rs.before", { n: +m[5] })] : [f("rs.pass_" + m[7], { n: +m[6], limit: m[8] })];
    if (m[9]) parts.push(f("rs.skipped", { n: +m[9] }));
    return parts.join(sep());
  }
  // a number typed in any of the digit sets people use (U7 R13): Arabic-Indic, Persian, Devanagari and Bengali digits,
  // the Arabic decimal mark, or a decimal comma, read as the same number
  function num(s) {
    let x = String(s).trim().replace(/[\u0660-\u0669]/g, (c) => c.charCodeAt(0) - 0x660).replace(/[\u06f0-\u06f9]/g, (c) => c.charCodeAt(0) - 0x6f0)
      .replace(/[\u0966-\u096f]/g, (c) => c.charCodeAt(0) - 0x966).replace(/[\u09e6-\u09ef]/g, (c) => c.charCodeAt(0) - 0x9e6).replace(/\u066b/g, ".").replace(/[\s\u00a0\u202f]/g, "");
    if (!x.includes(".") && (x.match(/,/g) || []).length === 1) x = x.replace(",", ".");
    return x;
  }
  const speech = () => L === "zh-Hans" ? "zh-CN" : L;
  const on = [];
  idle(warm);
  return { set(l, s) { L = l; S = s || S; idle(warm); on.forEach((f) => f()); }, lang: () => L, has: (k) => S[k] != null, t, html, esc, nf, money, plural, sentence, num, speech, changed: (f) => on.push(f) };
})();"""

# the static pages' runtime (the front door and the pricing page on GitHub Pages, written by scripts/site_pages.py): the
# page is built in English from en.json; the language comes from ?lang=, then the person's stored choice, then the
# browser's list (navigator.languages), never a place (U7 R17); a language other than English is read from its file and
# every string swapped: a plain one found by its English text, a composite one between <!--k:key {vars}--> and <!--/k-->
STATIC_JS = r"""(() => {
  const EN = /*EN*/{}, LANGS = /*LANGS*/[], BASE = /*BASE*/"i18n/";
  KI.set("en", EN);
  const match = (tag) => { const t = String(tag || "").toLowerCase(); if (!t) return null; for (const l of LANGS) if (l.code.toLowerCase() === t) return l.code;
    const b = t.split(/[-_]/)[0]; if (b === "zh") return "zh-Hans"; return LANGS.some((l) => l.code === b) ? b : null; };
  const store = { get() { try { return localStorage.getItem("knos.lang"); } catch (e) { return null; } }, set(v) { try { localStorage.setItem("knos.lang", v); } catch (e) { /* no storage */ } } };
  const asked = match(new URLSearchParams(location.search).get("lang"));
  if (asked) store.set(asked);
  const want = asked || match(store.get()) || (navigator.languages || [navigator.language]).map(match).find(Boolean) || "en";
  addEventListener("click", (e) => { const a = e.target.closest && e.target.closest("[data-language-switcher] a[lang]"); if (a) store.set(a.getAttribute("lang")); }, true);
  const plain = new Map();
  for (const k in EN) { const v = EN[k]; if (typeof v === "string" && !/[{<]/.test(v) && !plain.has(v)) plain.set(v, k); }
  function swap(m) {
    const de = document.documentElement; de.lang = KI.lang(); de.dir = m.dir;
    const w = document.createTreeWalker(document.documentElement, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_COMMENT), texts = [], marks = [];
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      if (n.nodeType === 8) { if (/^k:/.test(n.data)) marks.push(n); continue; }
      const p = n.parentNode; if (!p || /^(SCRIPT|STYLE|TEXTAREA)$/.test(p.nodeName)) continue;
      const s = n.nodeValue.trim(); if (s && plain.has(s)) texts.push(n);
    }
    for (const n of texts) { const s = n.nodeValue, k = plain.get(s.trim()); n.nodeValue = s.slice(0, s.indexOf(s.trim())) + KI.t(k) + s.slice(s.indexOf(s.trim()) + s.trim().length); }
    for (const a of ["placeholder", "aria-label", "title"]) document.querySelectorAll("[" + a + "]").forEach((e) => { const k = plain.get(e.getAttribute(a)); if (k) e.setAttribute(a, KI.t(k)); });
    for (const c of marks) {
      const sp = c.data.indexOf(" "), key = c.data.slice(2, sp < 0 ? undefined : sp); let v = {}; try { v = sp < 0 ? {} : JSON.parse(c.data.slice(sp + 1)); } catch (e) { v = {}; }
      while (c.nextSibling && !(c.nextSibling.nodeType === 8 && c.nextSibling.data === "/k")) c.nextSibling.remove();
      const tpl = document.createElement("template"); tpl.innerHTML = KI.html(key, v); c.after(tpl.content);
    }
    document.querySelectorAll("[data-language-switcher]").forEach((s) => {
      const span = s.querySelector("summary span"); if (span) { span.textContent = m.name; span.lang = KI.lang(); }
      const list = s.querySelector(".klang-list"), mine = list && list.querySelector('a[lang="' + KI.lang() + '"]');
      if (mine) { list.querySelectorAll("a").forEach((a) => a.removeAttribute("aria-current")); mine.setAttribute("aria-current", "true"); list.prepend(mine); }
    });
    document.querySelectorAll("[data-mt]").forEach((p) => { p.textContent = KI.t("fold.mt"); p.hidden = false; });
  }
  if (want === "en") document.documentElement.dir = "ltr";
  else fetch(BASE + want + ".json").then((r) => r.ok ? r.json() : null).then((d) => { if (d && d.strings) { KI.set(want, d.strings); swap(d._meta); } }).catch(() => { /* stays in English */ });
})();"""


def static_runtime(base: str, used: list[str] | None = None) -> str:
    """The two scripts above for a static page, with its English strings (all of them, or only `used`) written in."""
    en = table("en")["strings"]
    keep = {k: en[k] for k in (used or en)}
    langs = [{"code": c, "name": meta(c)["name"], "dir": meta(c)["dir"]} for c in LANGS]
    js = (STATIC_JS.replace("/*EN*/{}", json.dumps(keep, ensure_ascii=False).replace("</", "<\\/"))
          .replace("/*LANGS*/[]", json.dumps(langs, ensure_ascii=False)).replace('/*BASE*/"i18n/"', json.dumps(base)))
    return I18N_JS + "\n" + js


CSS = """:root{--bg:#f4f4f0;--card:#fff;--fg:#15171c;--muted:#4a505c;--line:#767b85;--accent:#2b3bb5;--accent-fg:#fff;--bad:#b3261e;--ok:#1b6e2e;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#07080c;--card:#0f1118;--fg:#e9ebef;--muted:#b4bac8;--line:#6b7080;--accent:#93a5ff;--accent-fg:#07080c;--bad:#ff8a80;--ok:#7fd18f}}:root[data-theme=dark]{--bg:#07080c;--card:#0f1118;--fg:#e9ebef;--muted:#b4bac8;--line:#6b7080;--accent:#93a5ff;--accent-fg:#07080c;--bad:#ff8a80;--ok:#7fd18f;color-scheme:dark}:root[data-theme=light]{color-scheme:light}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:1.125rem/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;overflow-wrap:anywhere}
main{max-width:640px;margin:0 auto;padding:4px 16px 48px}
a{color:var(--accent)}
.top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.brand{display:inline-flex;align-items:center;min-height:48px;min-width:48px;font-weight:700;font-size:1.25rem;color:var(--fg);text-decoration:none}
h1{font-size:1.625rem;line-height:1.2;margin:2px 0 4px}h1 label{font-weight:inherit;margin:0}h2{font-size:1.375rem;line-height:1.25;margin:12px 0 6px}
h1{font-size:2rem}.who{margin:0 0 10px;color:var(--muted)}
label{display:block;font-weight:600;margin-bottom:4px}
textarea{display:block;width:100%;height:6.4em;font:1.125rem/1.4 ui-monospace,Consolas,monospace;padding:8px 10px;border:2px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);resize:vertical;white-space:pre;overflow:auto}
select,input{font:inherit;min-height:48px;min-width:48px;max-width:100%;padding:4px 8px;border:2px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}
input[type=file]{width:100%;padding:8px}
.rule{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:10px 0 0}.rule input{width:7em}
.field{margin:10px 0 0}#col{min-width:10em}
button{font:inherit;min-height:48px;min-width:48px;padding:8px 16px;border-radius:8px;border:2px solid var(--accent);background:transparent;color:var(--accent);cursor:pointer;margin-block:8px 0;margin-inline:0 8px}
button.primary{width:100%;margin-block:10px 0;margin-inline:0;background:var(--accent);color:var(--accent-fg);font-weight:700}#go{display:flex;align-items:center;justify-content:center;gap:8px}#tool{display:flex;flex-direction:column}#go{order:1}#tool>label{align-self:flex-start}
button:disabled,button[aria-disabled=true]{opacity:.75;cursor:default}
button:focus-visible,textarea:focus-visible,summary:focus-visible,a:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.big{font-size:1.375rem;font-weight:700;margin:14px 0 0}#out .big{scroll-margin-top:8px}.big+p{margin:2px 0 0}
.answer{display:grid;grid-template-columns:auto 1fr;column-gap:8px;align-items:start;margin:14px 0 0}
.answer>*{grid-column:1/-1}.answer>svg{grid-column:1;width:1.75rem;height:1.75rem;margin-block-start:2px}.answer>svg+*{grid-column:2;margin:0}
.answer p{margin-block:6px 0;margin-inline:0}.answer[data-state=pass]>svg{color:var(--ok)}.answer[data-state=fail]>svg{color:var(--bad)}.answer[data-state=unknown]>svg{color:var(--muted)}
.first{display:flex;flex-direction:column;min-height:100vh;min-height:100svh}
.first:has(.later){min-height:calc(100vh + 11rem);min-height:calc(100svh + 11rem)}
.first>#out{flex:1 0 auto;display:flex;flex-direction:column}#out>.answer{flex:1 0 auto}
.answer:has(.later){grid-template-rows:auto auto 1fr}.later{align-self:end;min-height:11rem}.src{display:inline-flex;align-items:center;min-height:48px}.later h2{font-size:1.125rem;margin:12px 0 0}
#k-input pre{font:1rem/1.4 ui-monospace,Consolas,monospace;white-space:pre;overflow:auto;max-height:12em;margin:0}
.chart{display:block;width:100%;height:auto;max-height:220px;margin:10px 0 0;color:var(--fg)}
.muted{color:var(--muted)}.bad{color:var(--bad);font-weight:600}
.bar{height:6px;border-radius:3px;background:var(--line);overflow:hidden;margin:12px 0 4px}
.bar i{display:block;height:100%;width:30%;background:var(--accent);animation:k-move 1.2s ease-in-out infinite alternate}
@keyframes k-move{from{transform:translateX(0)}to{transform:translateX(233%)}}
@media (prefers-reduced-motion:reduce){.bar i{animation:none;width:100%}}
main>details{margin-top:24px;border-top:1px solid var(--line);padding-top:4px}
summary{min-height:48px;display:flex;align-items:center;cursor:pointer;font-weight:600}
main>details>summary::before{content:"+";display:inline-block;width:1.2em;color:var(--accent)}main>details[open]>summary::before{content:"\\2212"}
details li{margin:6px 0}.fold-links a{display:inline-flex;align-items:center;min-height:48px;margin-inline-end:16px}
.tgt input{width:100%;font:1rem ui-monospace,Consolas,monospace}
.home a{display:inline-flex;align-items:center;min-height:48px;min-width:48px}#theme{display:inline-flex;align-items:center;gap:8px;min-height:48px;min-width:48px;padding:0 16px;margin-inline-start:12px;border:2px solid var(--line);border-radius:10px;background:transparent;color:var(--fg);font:inherit;cursor:pointer}
[hidden]{display:none!important}""" + "\n" + SWITCH_CSS

# The table reader and the chart, the same code on the front door (web/door.html): the column names by the program's rule
# (a first row with any cell that is not a number is the header), and the values as a line, the limit as a straight
# dashed line, the first failing value marked with a ring and its row number. Charts keep left to right (U7 R4).
TABLE_JS = r"""const num = (s) => { const t = String(s).trim(); return t !== "" && Number.isFinite(Number(t)); };
function rowsOf(text) {
  const out = []; let row = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) { if (ch === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; } else cell += ch; }
    else if (ch === '"') q = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") { if (ch === "\r" && text[i + 1] === "\n") i++; row.push(cell); out.push(row); row = []; cell = ""; }
    else cell += ch;
  }
  row.push(cell); out.push(row);
  return out.filter((r) => r.some((c) => c.trim()));
}
function columnsOf(text) {
  const rows = rowsOf(text);
  if (!rows.length) return [];
  if (rows[0].some((c) => !num(c))) return rows[0].map((c) => c.trim());
  return Array.from({ length: Math.max(...rows.map((r) => r.length)) }, (_, i) => "column " + (i + 1));
}
function chartSvg(c, row) {
  const NS = "http://www.w3.org/2000/svg", W = 320, H = 150, P = 10, r1 = (v) => Math.round(v * 10) / 10;
  const el = (tag, at) => { const e = document.createElementNS(NS, tag); for (const k in at) e.setAttribute(k, at[k]); return e; };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", dir: "ltr", "data-no-mirror": "", "aria-label": KI.t(c && c.fail ? "chart.label_fail" : "chart.label") });
  if (!c || !c.points || !c.points.length) return svg;
  const vs = c.points.map((p) => p[1]).concat([c.limit]), lo = Math.min(...vs), hi = Math.max(...vs), pad = (hi - lo) * 0.1 || 1;
  const n = Math.max(2, c.n), X = (x) => P + (x - 1) / (n - 1) * (W - 2 * P), Y = (v) => H - P - (v - lo + pad) / (hi - lo + 2 * pad) * (H - 2 * P);
  svg.append(el("polyline", { points: c.points.map((p) => r1(X(p[0])) + "," + r1(Y(p[1]))).join(" "), fill: "none", stroke: "currentColor", "stroke-width": 2 }));
  svg.append(el("line", { x1: P, x2: W - P, y1: r1(Y(c.limit)), y2: r1(Y(c.limit)), stroke: "#b3261e", "stroke-width": 2, "stroke-dasharray": "6 4" }));
  if (c.fail) {
    const fx = r1(X(c.fail[0])), fy = r1(Y(c.fail[1]));
    svg.append(el("circle", { cx: fx, cy: fy, r: 6, fill: "none", stroke: "#b3261e", "stroke-width": 3 }));
    // 18 units: at the narrowest page (320 px, the chart 288 px wide for its 320 units) the label is still 16 px
    const t = el("text", { x: r1(Math.min(W - 84, Math.max(P, fx - 30))), y: r1(Math.max(20, fy - 10)), fill: "currentColor", "font-size": 18 });
    t.textContent = KI.t("chart.row", { r: row }); svg.append(t);
  }
  return svg;
}"""

SCRIPT = r"""(() => {
const D = JSON.parse(document.getElementById("k-tool").textContent);
KI.set(D.lang, D.t);
const T = KI.t;
const $ = (id) => document.getElementById(id);
// the person's stored language wins over the browser's (U7 R17): a page served in another language is asked for again
try { const q = new URLSearchParams(location.search), want = localStorage.getItem("knos.lang");
  if (q.get("lang")) localStorage.setItem("knos.lang", D.lang);
  else if (want && want !== D.lang && D.langs.includes(want)) { q.set("lang", want); location.replace(location.pathname + "?" + q); }
} catch (e) { /* no storage */ }
const box = $("list"), go = $("go"), out = $("out"), lab = $("lab"), form = $("tool"), pay = $("pay");
const test = new URLSearchParams(location.search).get("test") === "1";
const store = (() => { try { return window.localStorage; } catch (e) { return null; } })();
const get = (k) => { try { return store && store.getItem(k); } catch (e) { return null; } };
const put = (k, v) => { try { store && store.setItem(k, v); } catch (e) { /* private window */ } };
const browser = () => get("knos-count") === "yes" ? (get("knos-browser") || "") : "";
// the free runs are counted per browser (pricing: "5 free a day, in each browser"): a random id kept here for that alone,
// not a count of visitors; the server holds it only in memory, under a keyed hash (tool_run._key)
let runs = null;
const runsId = () => { if (runs) return runs; runs = get("knos-runs"); if (!runs) { const a = new Uint8Array(12); crypto.getRandomValues(a); runs = Array.from(a, (x) => x.toString(16).padStart(2, "0")).join(""); put("knos-runs", runs); } return runs; };
// the first action's source (U3 Rule 11): how the table got into the box when Try it is first pressed (the sample as it
// stood, typed, or pasted or chosen from a file); kept in this browser, sent once as the event first_action, only after
// the person says yes to being counted
let how = "starter";
box.addEventListener("input", (e) => { if (how !== "pasted") how = e.inputType === "insertFromPaste" || e.inputType === "insertFromDrop" ? "pasted" : "typed"; });
const sendFirst = () => { const s = get("knos-first"); if (!s || get("knos-first-sent") || !browser()) return; put("knos-first-sent", "1");
  fetch(D.api + "/api/first_action", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ event: "first_action", source: s, browser: browser(), test }), keepalive: true }).catch(() => { /* not counted */ }); };
const firstAction = () => { if (!get("knos-first")) put("knos-first", how); sendFirst(); };
let xhr = null, tick = null, link = D.result ? D.result.link : "", mineOn = false, said = D.result ? D.result.result : "";
const make = (tag, text, cls) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; };
const btn = (text, on, primary) => { const b = make("button", text, primary ? "primary" : ""); b.type = "button"; b.addEventListener("click", on); return b; };
const under = $("more");
const show = (...nodes) => { out.replaceChildren(...nodes); under.replaceChildren(); };
/*TABLE*/
function fillColumns(keep) {
  const names = columnsOf(box.value), sel = $("col"), was = keep || sel.value;
  sel.replaceChildren(...names.map((c) => { const o = make("option", c); o.value = c; return o; }));
  if (names.includes(was)) sel.value = was; else if (names.length) sel.value = names[names.length - 1];
}
function idle() { clearInterval(tick); tick = null; xhr = null; go.removeAttribute("aria-disabled"); $("go-label").textContent = T("tool.try"); out.removeAttribute("aria-busy"); out.dataset.state = "done"; }
function left(r) {
  if (r.mode !== "own" || r.runs_left == null) return null;
  if (r.paid_left > 0) return make("p", T("res.runs_left", { n: r.runs_left }));
  return make("p", T("res.free_left", { n: r.free_left }));
}
function copy(b) {
  const done = () => { b.textContent = T("res.copied"); if (navigator.share) navigator.share({ url: link, title: T("tool.title") }).catch(() => {}); };
  b.textContent = T("res.copied");
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(link).then(done, () => fallback(b, done));
  else fallback(b, done);
}
function fallback(b, done) {
  const t = make("textarea"); t.value = link; t.setAttribute("readonly", ""); t.style.position = "fixed"; t.style.opacity = "0"; document.body.append(t); t.select();
  let ok = false; try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  t.remove();
  if (ok) done(); else { b.textContent = T("res.copy"); const p = make("p", T("res.by_hand") + " "); const i = make("input"); i.value = link; i.readOnly = true; i.dir = "ltr"; i.setAttribute("aria-label", T("res.link_label")); p.append(i); b.after(p); i.select(); }
}
function ask() {
  if (get("knos-count") || ask.shown) return null;
  ask.shown = true;
  const p = make("p", T("res.count_q") + " ");
  const answer = (yes) => { put("knos-count", yes ? "yes" : "no"); if (yes && !get("knos-browser")) { const a = new Uint8Array(12); crypto.getRandomValues(a); put("knos-browser", Array.from(a, (x) => x.toString(16).padStart(2, "0")).join("")); } if (yes) sendFirst(); p.remove(); };
  p.append(btn(T("yes"), () => answer(true)), btn(T("no"), () => answer(false)));
  return p;
}
// the verdict block, as the server writes it (tool_page.answer_html): icon, sentence, evidence or reason, next step
const icon = (st) => { const x = document.createElement("template"); x.innerHTML = D.icons[st]; return x.content.firstChild; };
const RSX = /^(?:Failed at row (\d+): (.+?) is not (?:above|below) (.+?)\. It passed|Passed: all \d+ rows stay (?:above|below) (.+?)\.)/;
const verdictOf = (r) => /^(pass|fail|unknown)$/.test(r.verdict || "") ? r.verdict : r.first_failing_row ? "fail" : r.rows > 0 ? "pass" : "unknown";
function part(tag, key, v, attrs) { const e = make(tag); e.innerHTML = KI.html(key, v); for (const a in attrs || {}) e.setAttribute(a, attrs[a]); return e; }
function answer(r) {
  const st = verdictOf(r), m = RSX.exec(r.result || ""), col = r.column || D.column;
  const lim = m ? (m[1] ? m[3] : m[4]) : String(r.limit);
  const a = make("div", null, "answer"); a.dataset.answer = ""; a.dataset.verdict = ""; a.dataset.state = st;
  const big = make("p", null, "big"); big.id = "about"; big.innerHTML = KI.sentence(r.result);
  a.append(icon(st), big);
  if (st === "unknown") a.append(part("p", "why.unknown", { column: col }, { "data-reason": "", "data-uncertain": "true" }), part("p", "next.unknown", {}, { "data-next-step": "" }));
  else {
    const ev = make("p"); ev.dataset.evidence = "";
    const c = st === "fail" && m && m[1] ? part("span", "ev.fail", { r: +m[1], column: col, value: m[2], limit: lim }) : part("span", "ev.pass", { n: r.rows || 0, column: col, limit: lim });
    c.dataset.compare = ""; c.dataset.quote = "";
    const src = make("a", T("res.shown_by"), "src"); src.href = D.test_url; src.dataset.verified = "";
    ev.append(c);
    const later = make("div", null, "later"), sp = make("p"); sp.append(src);
    later.append(make("h2", T("q.next")), part("p", "next." + st, { r: r.first_failing_row || 0 }, { "data-next-step": "" }), sp);
    a.append(ev, later);
  }
  return a;
}
// after a verdict the box is empty and ready for the next table (U6 Rule 2); the table just checked is kept: shown under
// the answer, and put back in the box when the person comes back to this page (section 12: going back keeps the request)
let kept = null, fresh = false;   // fresh: the box was emptied by a verdict and not touched since
function checked(table) { const k = $("k-input"); if (!k) return; k.querySelector("pre").textContent = table; k.hidden = false; }
function result(r, ran) {
  link = r.link; said = r.result;
  // only the person's own run empties the box (U6 Rule 2); a result opened from its link shows its table in the box (G2 6)
  if (ran && box.value.trim()) { kept = { table: box.value, col: mineOn ? $("col").value : "", rule: $("rule").value, limit: $("limit").value }; box.value = ""; lab.hidden = true; }
  const was = kept ? kept.table : D.result && D.result.input;
  fresh = !box.value;
  const nodes = [];
  if (r.chart && r.chart.points && r.chart.points.length) nodes.push(chartSvg(r.chart, r.first_failing_row));
  const l = left(r);   // the runs left stay in the answer region, beside the run they follow
  if (r.mode === "own") nodes.push(make("p", T("res.private")));
  const row = make("div");
  // Change the limit follows the person's own run; a result someone shared offers their own data and its link (U2 R13:
  // the first screen holds most of the page's words)
  const PIC = { mine: '<path d="M6 2h9l5 5v15H6z"/><path d="M14 2v6h6"/>', limit: '<circle cx="12" cy="12" r="8"/><path d="M12 12l4-4"/>', copy: '<path d="M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1"/><path d="M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l1-1"/>' };
  const more = [btn(T("res.mine"), mine), ...(ran ? [btn(T("res.change_limit"), changeLimit)] : []), btn(T("res.copy"), (e) => copy(e.currentTarget))];
  // each choice carries a picture and its word (U7 R26): a file, a dial, a link
  const PICS = [PIC.mine, ...(ran ? [PIC.limit] : []), PIC.copy];
  more.forEach((b, i) => { b.dataset.followup = ""; const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("aria-hidden", "true"); s.setAttribute("width", "18"); s.setAttribute("height", "18"); s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor"); s.setAttribute("stroke-width", "2"); s.innerHTML = PICS[i]; b.prepend(s); });
  row.append(...more);
  nodes.push(row);
  // the counting question follows a run the person made, not the opening of a result someone shared
  const q = ran ? ask() : null; if (q) nodes.push(q);
  if (was) checked(was);
  const a = answer(r), old = ran ? null : $("about"), fresh_big = a.querySelector("#about");
  if (old && fresh_big && old.textContent.trim() === fresh_big.textContent.trim()) fresh_big.replaceWith(old);   // keep the server's verdict node: the page's largest paint stays on screen
  show(...[a, l].filter(Boolean)); under.replaceChildren(...nodes);
  try { if (location.origin === new URL(r.link).origin && location.pathname !== new URL(r.link).pathname) history.replaceState(null, "", new URL(r.link).pathname + location.search); } catch (e) { /* another site */ }
}
function ownMode() {
  mineOn = true; $("own").hidden = false; $("which").hidden = false; $("colname").hidden = true; editOn();
  lab.textContent = T("tool.paste"); lab.hidden = false;
  $("lims").textContent = T("tool.lim_rows", { n: D.limits.max_rows }) + " " + T("tool.lim_secs", { n: D.limits.max_seconds }); $("lims").hidden = false;
}
function mine() { box.value = ""; kept = null; fresh = false; $("limit").value = ""; ownMode(); fillColumns(); show(); $("file").focus(); }
function editOn() { $("k-rule").hidden = false; $("rule-shown").hidden = true; $("rule-edit").hidden = false; }
function changeLimit() { editOn(); $("limit").focus(); $("limit").select(); }
// an error is a "cannot tell" answer (U6 Rules 15 and 17): the reason in the first person, the person's file kept in
// the box, and a next step that leaves the error; Try again beside it where the server may answer next time
function trouble(text, label, then, retry) {
  const a = make("div", null, "answer"); a.dataset.verdict = ""; a.dataset.state = "unknown";
  const p = make("p", text, "bad"); p.setAttribute("role", "alert"); p.dataset.answer = ""; p.dataset.reason = "";
  const next = btn(label, then); next.dataset.nextStep = "";
  a.append(icon("unknown"), p, next);
  if (retry) a.append(btn(T("btn.retry"), run));
  show(a);
}
function edit() { show(); box.focus(); }
function chooseColumn() { show(); ownMode(); fillColumns(); $("col").focus(); }
function working(rows) {
  const t0 = Date.now(), max = D.limits.max_seconds;
  let step = T("work.sending"), built = false, status, bar;
  out.dataset.state = "working"; out.setAttribute("aria-busy", "true");
  go.setAttribute("aria-disabled", "true"); $("go-label").textContent = T("tool.checking");
  const got = make("p", T("work.rows", { n: rows })); got.dataset.partial = "";
  show(make("p", T("tool.checking")), got);
  tick = setInterval(() => {
    const ms = Date.now() - t0, s = Math.floor(ms / 1000);
    // the moving bar from 0.6 s (none before 0.5 s, U1 R10; the screen never the same for a second, U1 R8)
    if (ms < 600) return;
    if (!built) {
      built = true;
      // the bar's value is the run's time against its time limit, both in seconds (U1 R11): a number, never a guess
      bar = make("div", null, "bar"); bar.setAttribute("role", "progressbar"); bar.setAttribute("aria-label", T("tool.checking"));
      bar.setAttribute("aria-valuemin", "0"); bar.setAttribute("aria-valuemax", String(max)); bar.append(make("i"));
      status = make("p"); status.dataset.status = ""; status.setAttribute("aria-live", "polite");
      show(bar, status, got, btn(T("stop"), stop));
    }
    const line = T("work.secs", { what: step, n: s });
    bar.setAttribute("aria-valuenow", String(Math.min(s, max))); bar.setAttribute("aria-valuetext", line);
    if (status.textContent !== line) status.textContent = line;
  }, 200);
  return { step: (x) => { step = x; } };
}
function stop() {
  if (xhr) xhr.abort();
  idle();
  show(make("p", T("err.stopped")));
}
function run() {
  if (xhr) return;
  // a box a verdict emptied, untouched since: Try it checks the table just checked again (the one in the fold); a box
  // the person emptied is an empty file
  const again = fresh && !box.value.trim() && (kept || (D.result && D.result.input ? { table: D.result.input, col: D.result.column } : null));
  const table = again ? again.table : box.value, column = again && again.col ? again.col : mineOn ? $("col").value : D.column, rule = $("rule").value, limit = KI.num($("limit").value);
  // a table this page just checked goes back in the box while it runs, so an error keeps it there; a shared result's table
  // stays in the fold (the box is as the person left it)
  if (again && again === kept) { box.value = table; fresh = false; }
  if (!table.trim()) return trouble(T("err.empty"), T("btn.back"), edit);
  if (!num(limit)) return trouble(T("err.limit"), T("btn.type_limit"), () => { show(); changeLimit(); });
  const names = columnsOf(table);
  if (!names.includes(column)) return trouble(T("err.column", { column, names: names.slice(0, 12).join(", ") }), T("btn.column"), chooseColumn);
  firstAction();
  const w = working(Math.max(0, rowsOf(table).length - (rowsOf(table)[0].some((c) => !num(c)) ? 1 : 0)));
  xhr = new XMLHttpRequest();
  xhr.open("POST", D.api + "/api/run");
  xhr.setRequestHeader("Content-Type", "application/json");
  xhr.timeout = (D.limits.max_seconds + 90) * 1000;
  xhr.upload.onprogress = (e) => { if (e.lengthComputable && e.total > 50000) w.step(T("work.sending_pct", { p: Math.round(100 * e.loaded / e.total) })); };
  xhr.upload.onload = () => w.step(T("work.checking"));
  const x = xhr;
  x.onload = () => {
    idle();
    let body = {}; try { body = JSON.parse(x.responseText); } catch (e) { body = {}; }
    if (x.status === 200) return result(body, true);
    if (x.status === 402 && body.pay) return payScreen(body.pay);
    if (x.status === 413) return trouble(T("err.too_big", { n: D.limits.max_rows }), T("btn.smaller"), edit);
    if (x.status === 408) return trouble(T("err.too_long", { n: D.limits.max_seconds }), T("btn.smaller"), edit);
    if (x.status === 503) return trouble(T("err.not_ready"), T("btn.back"), edit, true);
    if (x.status === 400) return trouble(T("err.bad"), T("btn.back"), edit);
    trouble(T("err.none"), T("btn.back"), edit, true);
  };
  x.onerror = x.ontimeout = () => { idle(); trouble(T("err.reach"), T("btn.back"), edit, true); };
  x.send(JSON.stringify({ id: D.id, table, column, rule, limit: Number(limit), mode: table === D.sample ? "sample" : "own", browser: browser(), runs: runsId(), test }));
}
function back(nodes) { pay.hidden = true; pay.replaceChildren(); form.hidden = false; show(...(nodes || [])); go.focus(); }
const price = (p) => Number(String(p.price || "").replace(/[^0-9.]/g, "")) || 0;
function payScreen(p) {
  const press = Array.from(crypto.getRandomValues(new Uint8Array(12)), (x) => x.toString(16).padStart(2, "0")).join("");
  form.hidden = true; show();
  const h = make("h2", T("pay.headline", { n: p.runs, price: price(p) })); h.tabIndex = -1;
  pay.replaceChildren(h, make("p", T("pay.line")), btn(T("pay.go"), () => confirm(p, press), true), btn(T("pay.not_now"), () => back()));
  pay.hidden = false; h.focus();
}
// the confirm step (U6 Rule 23): a dialog that says what will be recorded, with two named buttons; focus starts on Yes
// and stays inside it; Escape is Not now. Nothing is sent before Yes.
function confirm(p, press) {
  const d = make("div"); d.setAttribute("role", "dialog"); d.setAttribute("aria-modal", "true");
  d.setAttribute("aria-labelledby", "k-pay-h"); d.setAttribute("aria-describedby", "k-pay-d");
  const h = make("h2", T("pay.headline", { n: p.runs, price: price(p) })); h.id = "k-pay-h";
  const sure = make("p", T("pay.confirm", { n: p.runs, price: price(p) })); sure.id = "k-pay-d";
  const yes = btn(T("pay.yes"), () => record(yes, press), true), no = btn(T("pay.not_now"), () => back());
  d.append(h, sure, yes, no);
  d.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); back(); return; }
    if (e.key !== "Tab") return;
    const f = [yes, no].filter((b) => !b.disabled), i = f.indexOf(document.activeElement);
    if (e.shiftKey ? i <= 0 : i === f.length - 1) { e.preventDefault(); f[e.shiftKey ? f.length - 1 : 0].focus(); }
  });
  pay.replaceChildren(d);
  yes.focus();
}
const post = (path, body, done, fail) => {
  const x = new XMLHttpRequest();
  x.open("POST", D.api + path); x.setRequestHeader("Content-Type", "application/json");
  x.onload = () => { let b = {}; try { b = JSON.parse(x.responseText); } catch (e) { b = {}; } if (x.status === 200) done(b); else fail(x.status, b); };
  x.onerror = () => fail(0, {});
  x.send(JSON.stringify(body));
};
function record(b, press) {
  if (b.disabled) return;
  b.disabled = true; b.textContent = T("pay.recording");
  post("/api/pay", { browser: browser(), runs: runsId(), press, test }, (body) => back([recorded(body, press)]), (code) => {
    b.disabled = false; b.textContent = T("btn.retry");
    if (!code) return;
    const m = make("p", T("pay.error"), "bad"); m.setAttribute("role", "alert");
    pay.querySelector("[role=dialog]").append(m);
  });
}
// what the test payment did, why, and its undo (U6 Rule 22): Undo takes the 20 runs back while none of them is used
function recorded(body, press) {
  const r = make("div"); r.dataset.actionResult = "";
  const why = make("p", T("act.why"), "muted"); why.dataset.why = "";
  const u = btn(T("act.undo"), () => {
    if (u.disabled) return;
    u.disabled = true;
    post("/api/pay", { browser: browser(), runs: runsId(), press, test, undo: true }, (b) => {
      r.replaceChildren(make("p", T("act.undone")), make("p", T("res.runs_left", { n: b.runs_left }))); go.focus();
    }, () => { u.disabled = false; const m = make("p", T("act.undo_error"), "bad"); m.setAttribute("role", "alert"); r.append(m); });
  });
  u.dataset.undo = "";
  r.append(make("p", T("res.runs_left", { n: body.runs_left })), why, u);
  return r;
}
// Listen (H3 b): the result sentence read aloud in the page's language by the browser's own speech; shown only where
// the browser has it, and never fetched from anywhere
const listen = $("listen");
if (listen && "speechSynthesis" in window && window.SpeechSynthesisUtterance) {
  listen.hidden = false;
  listen.addEventListener("click", () => {
    const s = window.speechSynthesis;
    if (s.speaking) { s.cancel(); listen.textContent = T("fold.listen"); return; }
    const u = new SpeechSynthesisUtterance(KI.sentence(said, true)); u.lang = KI.speech();
    u.onend = u.onerror = () => { listen.textContent = T("fold.listen"); };
    listen.textContent = T("stop"); s.speak(u);
  });
}
$("file").addEventListener("change", () => {
  const f = $("file").files[0]; if (!f) return;
  if (how !== "pasted") how = "pasted";   // a file put in whole, as a paste is
  const r = new FileReader(); r.onload = () => { box.value = String(r.result); fillColumns(); draftSave(); }; r.readAsText(f);
});
// on a result page the rule shows once a new table is typed in the empty box (the verdict above already says it)
box.addEventListener("input", () => { fresh = false; $("k-rule").hidden = false; if (lab.dataset.checked != null) { delete lab.dataset.checked; lab.textContent = T("tool.paste"); } if (mineOn) fillColumns(); });
box.addEventListener("focus", () => { fresh = false; });   // a person who goes into the empty box means an empty one
form.addEventListener("submit", (e) => { e.preventDefault(); run(); });
if (D.result && D.result.mode === "own") { ownMode(); fillColumns(D.result.column); }
if (D.result && box.value.trim()) { lab.textContent = T("res.input"); lab.dataset.checked = ""; lab.hidden = false; }
if (D.result) result(D.result);
// section 12 of the plain-language spec: going back or forward (or a reload) keeps the request typed in this tab, sent
// or not, and from the pay screen too; kept for this tab only (sessionStorage), and a page without storage still works
const DRAFT = "knos.draft.tool." + D.id;
function draftSave() {
  const k = !box.value && kept ? kept : null;
  try { sessionStorage.setItem(DRAFT, JSON.stringify({ mine: mineOn, table: k ? k.table : box.value, col: k ? k.col : mineOn ? $("col").value : "", rule: $("rule").value, limit: $("limit").value })); } catch (e) { /* no storage */ }
}
function draftLoad(again) {
  let nav = "", d = null;
  try { nav = (performance.getEntriesByType("navigation")[0] || {}).type || ""; } catch (e) { nav = ""; }
  if (!again && nav !== "back_forward" && nav !== "reload") return;
  try { d = JSON.parse(sessionStorage.getItem(DRAFT) || "null"); } catch (e) { d = null; }
  if (!d || typeof d.table !== "string") return;
  if (d.mine && !mineOn) ownMode();
  box.value = d.table; if (d.table) $("k-rule").hidden = false;
  if (mineOn) fillColumns(String(d.col || ""));
  if ([...$("rule").options].some((o) => o.value === d.rule)) $("rule").value = d.rule;
  $("limit").value = String(d.limit == null ? "" : d.limit);
  if ($("rule").value !== $("rule").defaultValue || $("limit").value !== $("limit").defaultValue || [...$("rule").options].some((o) => o.selected !== o.defaultSelected)) editOn();
}
draftLoad();
addEventListener("pageshow", (e) => { if (e.persisted) draftLoad(true); });
for (const [el, ev] of [[box, "input"], [$("col"), "change"], [$("rule"), "change"], [$("limit"), "input"]]) el.addEventListener(ev, draftSave);
go.addEventListener("click", draftSave);
window.addEventListener("pagehide", draftSave);
// real visitors' speed (U1 R13): the largest paint, the slowest press and the layout shift, observed in this browser;
// sent once, when the page is left, only from a browser whose person said yes to being counted
(() => {
  const sup = (window.PerformanceObserver && PerformanceObserver.supportedEntryTypes) || [], v = { lcp: null, inp: 0, cls: 0 };
  const watch = (type, f, o) => { if (!sup.includes(type)) return; try { new PerformanceObserver((l) => l.getEntries().forEach(f)).observe(Object.assign({ type, buffered: true }, o || {})); } catch (e) { /* not here */ } };
  watch("largest-contentful-paint", (e) => { v.lcp = Math.round(e.startTime); });
  watch("event", (e) => { if (e.interactionId) v.inp = Math.max(v.inp, Math.round(e.duration)); }, { durationThreshold: 16 });
  watch("layout-shift", (e) => { if (!e.hadRecentInput) v.cls += e.value; });
  for (const type of ["soft-navigation", "interaction-contentful-paint"]) watch(type, () => {});
  let sent = false;
  addEventListener("visibilitychange", () => {
    if (sent || document.visibilityState !== "hidden" || get("knos-count") !== "yes" || !navigator.sendBeacon) return;
    sent = true;
    navigator.sendBeacon(D.api + "/api/vitals", new Blob([JSON.stringify({ screen: D.result ? "result" : "tool", lcp: v.lcp, inp: v.inp, cls: Math.round(v.cls * 1000) / 1000, browser: browser(), test })], { type: "application/json" }));
  });
})();
})();""".replace("/*TABLE*/", TABLE_JS)


SCRIPT_KEYS = sorted(set(keys_in(SCRIPT)) | {"rs.fail_above", "rs.fail_below", "rs.before", "rs.pass_above", "rs.pass_below",
                                                "rs.skipped", "chart.label", "chart.label_fail", "chart.row", "fold.listen", "stop", "rs.unknown",
                                                "next.pass", "next.fail", "next.unknown", "ev.pass", "ev.fail", "why.unknown", "theme.dark", "theme.light",
                                                "q.next", "res.input", "tool.paste"}) if (ROOT / "web" / "i18n" / "en.json").is_file() else []


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def shown_limit(v) -> str:
    """The limit as a person typed it: 1.4, not 1.40; a whole number with no point."""
    f = float(v)
    return str(int(f)) if f.is_integer() else repr(f)


# the light or dark choice kept in this browser, set before the first paint; the switch at the page's end (U5 R12)
THEME_HEAD = r"""try { const k = localStorage.getItem("knos-theme"); if (k === "light" || k === "dark") document.documentElement.dataset.theme = k; } catch (e) { /* no storage */ }"""
THEME_JS = r"""(() => { const b = document.getElementById("theme"), de = document.documentElement; if (!b) return;
  const now = () => de.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const label = () => { document.getElementById("theme-label").textContent = KI.t(now() === "light" ? "theme.dark" : "theme.light"); };
  b.hidden = false; label();
  b.addEventListener("click", () => { de.dataset.theme = now() === "light" ? "dark" : "light"; try { localStorage.setItem("knos-theme", de.dataset.theme); } catch (e) { /* no storage */ } label(); });
})();"""
OFFLINE_JS = r"""if ("serviceWorker" in navigator) navigator.serviceWorker.register("/tool-sw.js", { scope: location.pathname.startsWith("/r/") ? "/r/" : "/t/" }).catch(() => { /* no worker: the page still works online */ });
addEventListener("DOMContentLoaded", () => { const o = document.getElementById("k-offline"), f = () => { o.hidden = navigator.onLine !== false; }; f(); addEventListener("online", f); addEventListener("offline", f); });"""


def page(tool: dict, base: str, result: dict | None = None, front: str = "https://drexthealpha.github.io/Knos/", lang: str = "en",
         test: bool = False, sent: dict | None = None, lite: bool = False) -> str:
    """One tool page (/t/<id>/) or one result page (/r/<id>/) in one language: the og tags first, then the tool, then
    its fold, which opens with the five answers (H3 f). The result sentence is in the first response, so it shows with
    scripts blocked (H3 e). The tool is a form too: with no script, Try it posts it to /t/<id>/run (tool_run.form_run),
    which answers with the result page, or with this page again holding what was sent (`sent`) and why it was not run."""
    lang = lang if lang in LANGS else "en"
    L = lang
    rid = (result or {}).get("id")
    url = f"{base}/r/{rid}/" if rid else f"{base}/t/{tool['id']}/"
    image = f"{base}/og/r/{rid}.png" if rid else f"{base}/og/t/{tool['id']}.png"
    title = t(L, "tool.title")
    desc = first_sentence(sentence(L, result["result"], as_html=False)) if result else t(L, "tool.line")
    sent = sent or {}
    # a result page opened from its link shows the table it checked in the box (G2 step 6: the same input and result); the
    # box is emptied for the next table only by the person's own run on the page (U6 Rule 2, in the page's script)
    text = sent["table"] if "table" in sent else (result.get("input") or "") if result else tool["sample"]
    shown = bool(result and not sent and text.strip())
    own = bool(result and result.get("mode") == "own")
    column = sent.get("column") or (result["column"] if result else tool["column"])
    rule = sent.get("rule") or (result["rule"] if result else tool["rule"])
    limit = sent["limit"] if "limit" in sent else shown_limit(result["limit"] if result else tool["limit"])
    # U3 Rule 1a (UX/U3.md:21): the first screen holds the box, Try it and the language control; the rule and the limit
    # show as words, and their fields open with Use my data or Change the limit (open at once for a person's own file)
    edit = own or bool(sent)
    f = facts()
    label = t(L, "tool.sample_made_up" if f["made_up"] else "tool.sample_nasa")
    data = {"id": tool["id"], "sample": tool["sample"], "api": base, "limits": tool["limits"], "column": tool["column"],
            "lang": L, "langs": list(LANGS), "t": strings_for(L, SCRIPT_KEYS),
            "icons": {st: icon(L, st) for st in STATES}, "test_url": TEST_URL,
            "result": result and {**{k: result.get(k) for k in ("result", "first_failing_row", "rows", "skipped", "shown_by", "link",
                                                                 "mode", "chart", "column", "rule", "limit", "input")}, "verdict": verdict_of(result)}}
    ssr, below = sent.get("error_html", ""), ""
    if result:
        ssr = answer_html(L, result)
        below = ((f'<p>{_e(t(L, "res.private"))}</p>' if own else "")
                 + (f'<p class="muted">{_e(t(L, "res.cut", shown=nf(L, result["shown_lines"]), n=result["lines"]))}</p>' if result.get("cut") else ""))
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    items = "".join(f"<li>{x}</li>" for x in fold_items(L, f))
    # the table a result checked, in the fold (the box itself is empty, for the next table: U6 Rule 2)
    extra = (f'<div id="k-input"{"" if result else " hidden"}><p class="muted">{_e(t(L, "res.input"))}</p>'
             f'<pre data-user-content dir="auto">{_e((result or {}).get("input") or "")}</pre></div>')
    if result:
        line = (f'<iframe src="{base}/r/{rid}/mark" width="360" height="180" style="border:0" '
                f'title="{t(L, "embed.title")}" loading="lazy"></iframe>')
        extra += (f'<p class="fold-links"><button type="button" id="listen" hidden>{_e(t(L, "fold.listen"))}</button>'
                 f'<a href="#k-embed">{_e(t(L, "fold.embed"))}</a><a href="{_e(base)}/r/{_e(rid)}/print">{_e(t(L, "fold.print"))}</a></p>'
                 f'<p id="k-embed" class="tgt"><label for="k-embed-line">{_e(t(L, "fold.embed_label"))}</label>'
                 f'<input id="k-embed-line" readonly dir="auto" value="{_e(line)}"></p>'
                 + (f'<p class="muted" lang="en" dir="ltr">{_e(t(L, "fold.original", text=result.get("program_result") or result["result"]))}</p>' if L != "en" else ""))
    if L != "en":
        extra += f'<p class="muted">{_e(t(L, "fold.mt"))}</p>'
    opts = "".join(f'<option value="{r}"{" selected" if r == rule else ""}>{_e(t(L, "rule." + r))}</option>' for r in ("above", "below"))
    alt = "".join(f'<link rel="alternate" hreflang="{c}" href="{_e(url)}?lang={c}">' for c in LANGS)
    # a tool page or a sample's result is kept for a visit with no network (tool_run.OFFLINE_SW); a result from a person's
    # own file registers nothing and is never kept
    # with Save-Data on (lite) the page comes without its script: the form runs on the server, as with scripts off (U7 R25)
    worker = "" if own or lite else f"<script>{OFFLINE_JS}</script>\n"
    # with no script, an empty box sent from a result page checks that result's table again (tool_run.form_run)
    again = f'<input type="hidden" dir="auto" name="again" value="{_e(rid)}">' if rid and not sent else ""
    scripts = "" if lite else (f'<script type="application/json" id="k-tool">{blob}</script>\n'
                               f"<script>{I18N_JS}\n{SCRIPT}\n{THEME_JS}</script>")
    return f"""<!doctype html>
<html lang="{L}" dir="{meta(L)['dir']}">
<head>
<meta charset="utf-8">
<script>{THEME_HEAD}</script>
{worker}<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)} | Knos</title>
<meta name="description" content="{_e(desc)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Knos">
<meta property="og:title" content="{_e(title)}">
<meta property="og:description" content="{_e(desc)}">
<meta property="og:image" content="{_e(image)}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:url" content="{_e(url)}">
<meta name="twitter:card" content="summary_large_image">
{'<meta name="robots" content="noindex">' if own else f'<link rel="canonical" href="{_e(url)}">{alt}'}
<link rel="icon" href="/favicon.ico">
<style>{CSS}</style>
</head>
<body>
<main>
<div class="first">
<div class="top"><span class="brand" data-no-mirror>Knos</span>{switcher(L)}{warm_names()}</div>
<h1><label for="list" id="k-name">{_e(title)}</label></h1>
<p class="who" id="k-offline" role="status" hidden>{_e(t(L, "offline.line"))}</p>
<form id="tool" method="post" action="{_e(base)}/t/{_e(tool['id'])}/run">
<input type="hidden" dir="auto" name="lang" value="{L}">{again}<input type="hidden" dir="auto" name="column" value="{_e(column)}">{'<input type="hidden" dir="auto" name="test" value="1">' if test else ""}
<button id="go" class="primary" type="submit" data-primary><svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg><span id="go-label">{_e(t(L, "tool.try"))}</span></button>
<div id="own" class="field" hidden><label for="file">{_e(t(L, "tool.choose_file"))}</label><input id="file" type="file" dir="auto" accept=".csv,text/csv,text/plain"></div>
<label id="lab" for="list"{" hidden" if result and not own and not shown else ""}>{_e(t(L, "res.input")) if shown else _e(t(L, "tool.paste")) if own or result else _e(label)}</label>
<textarea id="list" dir="auto" name="table" spellcheck="false" autocomplete="off" wrap="off">{_e(text)}</textarea>
<div id="which" class="field" hidden><label for="col">{_e(t(L, "tool.which"))}</label><select id="col" dir="auto"></select></div>
<p class="rule" id="k-rule"{" hidden" if result and not own and not edit else ""}><span id="colname" data-user-content><bdi>{_e(column)}</bdi></span> <span id="rule-shown"{" hidden" if edit else ""}>{_e(t(L, "rule." + rule))} <bdi data-no-mirror>{_e(limit)}</bdi></span><span id="rule-edit"{"" if edit else " hidden"}><label for="rule">{_e(t(L, "tool.rule_label"))}</label> <select id="rule" name="rule" aria-label="{_e(t(L, "tool.rule_label"))}">{opts}</select> <label for="limit">{_e(t(L, "tool.limit_label"))}</label> <input id="limit" dir="auto" name="limit" inputmode="decimal" autocomplete="off" aria-label="{_e(t(L, "tool.limit_label"))}" value="{_e(limit)}"></span></p>
<p id="lims" class="muted" hidden></p>
</form>
<section id="pay" hidden></section>
<div id="out" aria-live="polite" data-state="{'done' if result else 'ready'}">{ssr}</div>
</div>
<div id="more">{below}</div>
<p class="who" id="who"{" hidden" if result else ""}>{_e(t(L, "tool.line"))}</p>
<details>
<summary>{_e(t(L, "how"))}</summary>
{five(L, answers(L, "result" if result else "tool", f))}
<ol>{items}</ol>
{extra}
</details>
<div class="home"><a href="{_e(front)}" data-no-mirror>Knos</a> <button type="button" id="theme" hidden><svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg><span id="theme-label"></span></button></div>
</main>
{scripts}
</body>
</html>"""


def first_sentence(result: str) -> str:
    return result.split(". ", 1)[0].rstrip(".") + "." if result else ""


def missing(front: str = "https://drexthealpha.github.io/Knos/", lang: str = "en") -> str:
    """The page for an address with no tool or result behind it (every unknown /t/ and /r/ address): what happened, and
    one control, back to the tool. `front` is kept for the callers; the way on is the tool's own page on this server."""
    from .runner_conf import CONF
    L = lang if lang in LANGS else "en"
    to = f"/t/{CONF['tool']}/" + ("" if L == "en" else f"?lang={L}")
    return f"""<!doctype html>
<html lang="{L}" dir="{meta(L)['dir']}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(t(L, "nf.title"))} | Knos</title><meta name="robots" content="noindex"><style>{CSS}
.go{{display:flex;align-items:center;justify-content:center;min-height:48px;padding:8px 16px;border-radius:8px;background:var(--accent);color:var(--accent-fg);font-weight:700;text-decoration:none}}</style></head>
<body><main><div class="top"><span class="brand" data-no-mirror>Knos</span>{switcher(L)}{warm_names()}</div>
<h1>{_e(t(L, "nf.h"))}</h1>
<p data-answer>{_e(t(L, "nf.p"))}</p>
<p><a class="go" href="{_e(to)}" data-primary>{_e(t(L, "nf.link"))}</a></p>
</main></body></html>"""
