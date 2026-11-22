"""A demand result's permanent page, GET /r/<id> (id: the first 16 hex of the report's hash), drawn on the server from
the report this server keeps (its memory, the reports kept across restarts): the verdict, each open signal with its
link, a share button, a QR code of the page's address and a print stylesheet that keeps the brief on one page."""
from __future__ import annotations

import html
import json
import re

from . import escrow, qr

WORD = {"OPEN": "Open signals say people want this", "REFUSE": "Open signals find little interest yet", "CANNOT_DECIDE": "No signal yet"}
SITE = "https://drexthealpha.github.io/Knos/"
ID = re.compile(r"/r/([0-9a-f]{16})")
SAY = {"error": "No result has this address, so check a product on the front door to make one."}


def find(state, rid: str) -> dict | None:
    """The kept report whose hash starts with rid: this server's memory, then a report file."""
    with state.lock:
        for h, rep in state.reports.items():
            if isinstance(h, str) and h.startswith(rid):
                return rep
    d = escrow._state_dir() / "reports"
    for f in sorted(d.glob(f"{rid}*.report")) if d.is_dir() else []:
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


def state_of(rep: dict | None) -> str | None:
    """error (no such result), or None for an answer."""
    return "error" if rep is None else None


STYLE = """body{margin:0;background:#f4f4f0;color:#14151a;font:400 16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:720px;margin:0 auto;padding:16px 16px 40px}a{color:#2b3aa8;padding-block:max(0px,calc((24px - 1em) / 2))}h1{font-size:1.6rem;line-height:1.2;margin:8px 0 4px}
.verdict{font-weight:600;font-size:1.15rem;margin:0 0 12px}.say{border-left:3px solid #8a8d99;padding-left:10px}
dl{display:grid;grid-template-columns:minmax(0,max-content) minmax(0,1fr);gap:4px 16px;margin:12px 0}dd{margin:0;overflow-wrap:anywhere}
.row{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start;margin:16px 0}figure{margin:0}figcaption{font-size:.8rem;overflow-wrap:anywhere;max-width:180px}
button{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid #2b3aa8;background:#2b3aa8;color:#fff;cursor:pointer}
.fine{font-size:.85rem;color:#5a5d68}
@media (prefers-color-scheme:dark){body{background:#07080c;color:#e8e9ee}a{color:#9fb0ff}.fine{color:#a3a6b3}button{background:#3a4bd0;border-color:#3a4bd0}}
@media print{@page{size:A4;margin:14mm}body{background:#fff;color:#000;font-size:11pt}main{max-width:none;padding:0}
button,.noprint{display:none}a{color:#000;text-decoration:none}figure svg{width:30mm;height:30mm}}"""


def page(rep: dict | None, url: str, rid: str) -> str:
    e = html.escape
    if rep is None:
        title, body = "No result here", f'<h1>No result here</h1><p class="say" data-state="error">{e(SAY["error"])}</p>'
    else:
        idea = str(rep.get("idea") or "this idea")
        fb = rep.get("open_demand") or {}
        v = str((rep.get("decision") or {}).get("verdict") or "")
        word = fb.get("head") or WORD.get(v, WORD["CANNOT_DECIDE"])
        rows = [(e(str(r.get("name") or "")), (f'<a href="{e(str(r["link"]))}" rel="noopener">' if r.get("link") else "")
                 + e(f"{r.get('value')} {r.get('unit') or ''}") + ("</a>" if r.get("link") else ""))
                for r in fb.get("rows") or [] if isinstance(r, dict)]
        title = f"{idea}: {word}"
        body = (f'<h1>{e(idea)}</h1><p class="verdict" data-verdict="{e(v)}">{e(word)}</p>'
                + '<dl data-not-prose>' + "".join(f"<dt>{k}</dt><dd>{val}</dd>" for k, val in rows) + "</dl>"
                + (f'<p class="fine">{e(" ".join(x for x in (fb.get("line"), fb.get("rule")) if x))}</p>' if fb else ""))
    share = (f'<div class="row"><figure id="r-qr">{qr.svg(url, px=4)}<figcaption>{e(url)}</figcaption></figure>'
             f'<p class="noprint"><button type="button" id="r-share" data-url="{e(url)}">Share this result</button> '
             f'<button type="button" id="r-print">Print</button><br><span class="fine" id="r-said" role="status"></span></p></div>')
    if rep is not None:                       # the downloads: the brief in the print layout's fields, the calls, the Ready brief
        share += (f'<p class="noprint" data-exports><a href="/r/{e(rid)}.pdf" download>Download brief (PDF)</a> · '
                  f'<a href="/r/{e(rid)}.csv" download>Download signals (CSV)</a> · <a href="/r/{e(rid)}.json" download>Download Ready brief (JSON)</a></p>')
    script = ("<script>document.getElementById('r-print').addEventListener('click',()=>print());"
              "document.getElementById('r-share').addEventListener('click',async(ev)=>{const u=ev.currentTarget.dataset.url,said=document.getElementById('r-said');"
              "try{if(navigator.share){await navigator.share({title:document.title,url:u});return;}await navigator.clipboard.writeText(u);said.textContent='Link copied.';}"
              "catch(e){said.textContent=u;}});</script>")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Knos. {e(title)}</title><meta name="description" content="{e(title)}. A demand check by Knos, from free public signals.">'
            f'<link rel="canonical" href="{e(url)}"><meta name="color-scheme" content="light dark"><link rel="icon" href="/static/icon.svg" type="image/svg+xml">'
            f'<style>{STYLE}</style></head><body><main data-r="{e(rid)}">'
            f'<p class="fine noprint"><a href="{SITE}">Knos</a> · Devnet, test money.</p>{body}{share}'
            f'<p class="fine noprint"><a href="{SITE}">Check another idea</a></p></main>{script}</body></html>')
