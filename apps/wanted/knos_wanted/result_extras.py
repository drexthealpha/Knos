"""Three more ways to show a checked result, served under its address (Round 13, H3 c and d):

GET /r/<result-id>/mark    a small page another site can put in an iframe: the tool's title, the result sentence and a
                           link to the result. No script at all, at most 10 KB, framing allowed (this route only).
GET /r/<result-id>/qr.png  a QR code of the result address, drawn here (knos_wanted.qr, tool_page.png): no outside service.
GET /r/<result-id>/print   one printable page with the title, the result sentence and that QR code. No script.

LAWS/DISTRIBUTION/F5.md: "Give every checked result an embeddable mark that others can show where their own users
decide." LAWS/DISTRIBUTION/D9.md: "a physical token (a QR card) lets a person with no smartphone use a smartphone-era
product." None of these routes lists a result anywhere; they answer only for an address someone already has."""
from __future__ import annotations

import html

from . import qr, tool_page

MARK_MAX = 10_000                         # bytes: the "at most 10 KB" of H3 c
QR_PX, QR_QUIET = 8, 4                    # pixels per module, and the standard 4-module light border
# the mark: no script can run, and any site may frame it
MARK_HEADERS = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
                                           "form-action 'none'; frame-ancestors *",
                "X-Robots-Tag": "noindex", "Cache-Control": "public, max-age=3600"}
# the printed page: its own QR image only, no script, and not framed by anyone
PRINT_HEADERS = {"Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
                                            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
                 "X-Frame-Options": "DENY", "X-Robots-Tag": "noindex", "Cache-Control": "no-store"}
QR_HEADERS = {"X-Robots-Tag": "noindex", "Cache-Control": "public, max-age=86400"}


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def address(base: str, rid: str) -> str:
    return f"{base}/r/{rid}/"


def mark(title: str, sentence: str, url: str) -> str:
    """The embeddable mark: plain HTML and inline style, every link opening in the top window."""
    out = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>{_e(title)} | Knos</title>
<style>:root{{color-scheme:light dark}}html,body{{margin:0}}body{{font:16px/1.4 system-ui,sans-serif;background:Canvas;color:CanvasText}}
.m{{border:1px solid #8a8f99;border-radius:8px;padding:12px 14px;max-width:560px}}.t{{margin:0;font-size:16px}}
.s{{margin:6px 0 8px;font-size:18px;font-weight:600}}a{{color:LinkText;display:inline-flex;align-items:center;min-height:48px}}</style></head>
<body><div class="m"><p class="t">{_e(title)}</p><p class="s" data-answer>{_e(sentence)}</p>
<a href="{_e(url)}" target="_top" rel="noopener">Open the result on Knos</a></div></body></html>"""
    if len(out.encode("utf-8")) > MARK_MAX:              # a very long sentence is cut, never the 10 KB limit
        return mark(title, sentence[:max(0, len(sentence) - (len(out.encode("utf-8")) - MARK_MAX) - 2)] + "…", url)
    return out


def qr_png(text: str, px: int = QR_PX, quiet: int = QR_QUIET) -> bytes:
    """The QR code of text as an RGB PNG: dark modules on white with a quiet border, px pixels per module."""
    d = qr.encode(text)
    n = len(d)
    side = (n + 2 * quiet) * px
    white, black = b"\xff\xff\xff", b"\x00\x00\x00"
    rows = []
    for y in range(-quiet, n + quiet):
        row = b"".join((black if 0 <= y < n and 0 <= x < n and d[y][x] else white) * px for x in range(-quiet, n + quiet))
        rows.append(row * px)
    return tool_page.png(side, side, b"".join(rows))


def print_page(title: str, sentence: str, url: str, qr_src: str) -> str:
    """One printable page: title, result sentence, the QR code and the address written out for typing."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>{_e(title)} | Knos</title>
<style>body{{margin:0;background:#fff;color:#000;font:16px/1.45 system-ui,sans-serif}}main{{max-width:640px;margin:0 auto;padding:32px 20px}}
h1{{font-size:22px;margin:0 0 12px}}.s{{font-size:20px;font-weight:600;margin:0 0 20px}}img{{display:block;width:240px;height:240px;image-rendering:pixelated}}
.u{{font-family:ui-monospace,monospace;font-size:16px;word-break:break-all;margin:12px 0 0}}.u a{{display:inline-flex;align-items:center;min-height:48px}}
@page{{margin:15mm}}@media print{{main{{padding:0}}a{{color:#000;text-decoration:none}}}}</style></head>
<body><main><h1>{_e(title)}</h1><p class="s" data-answer>{_e(sentence)}</p>
<img src="{_e(qr_src)}" width="240" height="240" alt="QR code for {_e(url)}">
<p class="u"><a href="{_e(url)}">{_e(url)}</a></p>
<p>Scan the code with a phone camera to open this result.</p></main></body></html>"""
