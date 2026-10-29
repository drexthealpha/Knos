"""A demand result's permanent page, GET /r/<id> (id: the first 16 hex of the report's hash), drawn on the server from
the report this server keeps (its private cache, the recorded sample cards, the reports kept across restarts): the
verdict, the launch city and its pre-order target, a share button, a QR code of the page's address and a print
stylesheet that keeps the brief on one page. An empty, thin, failed or Qloo-outage result says so in one sentence.
Nothing here asks Qloo."""
from __future__ import annotations

import html
import json
import re

from . import escrow, metros, qr, recorded

WORD = {"OPEN": "Open for pre-orders", "REFUSE": "Not yet: pre-orders stay closed", "CANNOT_DECIDE": "Not enough evidence to decide"}
SITE = "https://drexthealpha.github.io/Knos/"
ID = re.compile(r"/r/([0-9a-f]{16})")
# the one plain sentence for each state that is not a full answer
SAY = {"empty": "Qloo matched no product to this idea, so there is nothing to measure yet.",
       "thin": metros.NO_MAP,                     # the card's own words when Qloo's map names no launch city
       "outage": "Qloo did not answer this time, so this is its last full answer.",
       "error": "No result has this address, so check a product on the front door to make one."}


def find(state, rid: str) -> dict | None:
    """The kept report whose hash starts with rid: a recorded sample card first (the real answer; a press while Qloo was
    down keeps a copy of it marked stale under the same hash), then this server's memory, then a report file."""
    with recorded._lock:
        for rep in [*recorded._last.values(), *recorded._answered.values()]:
            if str(rep.get("hash") or "").startswith(rid):
                return rep
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
    """error (no such result), outage (Qloo failed: its last real card), empty (nothing matched), thin (no launch city),
    or None for a full answer."""
    if rep is None:
        return "error"
    if rep.get("qloo_down") or rep.get("stale"):
        return "outage"
    if not rep.get("matches"):
        return "empty"
    if not terms_of(rep):
        return "thin"
    return None


def terms_of(rep: dict) -> dict | None:
    """The launch terms the card draws: the report's own, else the check's rule over its heatmap cells."""
    return metros.launch_terms(rep)


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
    st = state_of(rep)
    if rep is None:
        title, body = "No result here", f'<h1>No result here</h1><p class="say" data-state="error">{e(SAY["error"])}</p>'
    else:
        idea = str(rep.get("idea") or "this idea")
        word = WORD.get(str((rep.get("decision") or {}).get("verdict") or ""), "Qloo cannot decide this one")
        if word == WORD["OPEN"] and not terms_of(rep):              # Open needs a launch city, as on the card
            word = "Not yet: Qloo sets no launch city for this idea"
        t = terms_of(rep)                     # the one answer the card and the trace draw (metros.launch_terms), whatever the state
        made = str(rep.get("made") or "")[:10]
        # the launch city and target as the card has them; with no terms those rows are left out (the sentence says why)
        rows = ([("Launch city", e(t["city"])), ("Pre-order target", f"{t['target']}, all refunded if it falls short"),
                 ("Launch cities", f'<span data-cities>{e(", ".join(t["cities"]))}</span>')] if t else []) + [
                ("Qloo calls", f'<a href="/trace.html?hash={e(str(rep.get("hash") or ""))}">{len(rep.get("calls") or [])}, read {e(made)}</a>')]
        title = f"{idea}: {word}"
        body = (f'<h1>{e(idea)}</h1><p class="verdict" data-verdict="{e(str((rep.get("decision") or {}).get("verdict") or ""))}">{e(word)}</p>'
                + (f'<p class="say" data-state="{st}">{e(SAY[st])}</p>' if st else "")
                + '<dl data-not-prose>' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"
                + '<p class="fine">Aggregate taste of many people from Qloo, never about one person: directional demand evidence for this idea.</p>')
    share = (f'<div class="row"><figure id="r-qr">{qr.svg(url, px=4)}<figcaption>{e(url)}</figcaption></figure>'
             f'<p class="noprint"><button type="button" id="r-share" data-url="{e(url)}">Share this result</button> '
             f'<button type="button" id="r-print">Print</button><br><span class="fine" id="r-said" role="status"></span></p></div>')
    if rep is not None:                       # the downloads: the brief in the print layout's fields, the calls, the Ready brief
        share += (f'<p class="noprint" data-exports><a href="/r/{e(rid)}.pdf" download>Download brief (PDF)</a> · '
                  f'<a href="/r/{e(rid)}.csv" download>Download calls (CSV)</a> · <a href="/r/{e(rid)}.json" download>Download Ready brief (JSON)</a></p>')
    script = ("<script>document.getElementById('r-print').addEventListener('click',()=>print());"
              "document.getElementById('r-share').addEventListener('click',async(ev)=>{const u=ev.currentTarget.dataset.url,said=document.getElementById('r-said');"
              "try{if(navigator.share){await navigator.share({title:document.title,url:u});return;}await navigator.clipboard.writeText(u);said.textContent='Link copied.';}"
              "catch(e){said.textContent=u;}});</script>")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Knos. {e(title)}</title><meta name="description" content="{e(title)}. A demand check by Knos, from Qloo\'s taste data.">'
            f'<link rel="canonical" href="{e(url)}"><meta name="color-scheme" content="light dark"><link rel="icon" href="/static/icon.svg" type="image/svg+xml">'
            f'<style>{STYLE}</style></head><body><main data-r="{e(rid)}">'
            f'<p class="fine noprint"><a href="{SITE}">Knos</a> · Devnet, test money.</p>{body}{share}'
            f'<p class="fine noprint"><a href="{SITE}">Check another idea</a></p></main>{script}</body></html>')
