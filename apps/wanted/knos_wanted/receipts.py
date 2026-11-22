"""A result's receipts, GET /receipts/<id> (the page) and GET /api/receipts?id= (the same rows as JSON); id: the first 16
hex of the report's hash. One row per source of a number on the card: each open signal with its value and its link, the
model's own answer, the line the Knos record keeps with its sequence number, and any devnet transaction."""
from __future__ import annotations

import html

from . import company


def record_line(rep: dict) -> dict:
    """The decision's line in the Knos record: its claim's events with their sequence numbers. A check the record
    does not hold yet is written to it now, once (company.record_check), and read back."""
    h = rep.get("hash") or ""
    rec = company._record()
    if rec is None:
        return {"recorded": False, "why": "the Knos record is not available on this server"}
    cid = company.claim_id(h)

    def events():
        return [e for e in rec.claim_events(cid, root=company.root()) or [] if isinstance(e, dict)]
    try:
        got = events()
        if not got:
            company.record_check({**rep, "stale": None})
            got = events()
    except Exception as why:  # noqa: BLE001 - a record that cannot be read is said, never guessed
        return {"recorded": False, "why": f"the Knos record could not be read here ({type(why).__name__})"}
    if not got:
        return {"recorded": False, "why": "the Knos record holds no line for this result"}
    first = got[0]
    return {"recorded": True, "claim": cid, "seq": first.get("seq"), "kind": first.get("kind"), "at": first.get("ts"),
            "lines": [{"seq": e.get("seq"), "kind": e.get("kind"), "at": e.get("ts")} for e in got[:8]]}


def rows(rep: dict) -> list[dict]:
    made = str(rep.get("made") or "")
    out: list[dict] = []
    for i, r in enumerate((rep.get("open_demand") or {}).get("rows") or [], 1):
        if isinstance(r, dict):
            out.append({"id": f"signal-{i}", "source": "signal", "what": str(r.get("name") or ""), "at": made,
                        "value": f"{r.get('value')} {r.get('unit') or ''}".strip(), "counts": bool(r.get("counts")), "link": r.get("link")})
    m = rep.get("model_alone")
    if m and m.get("city"):
        out.append({"id": "model", "source": "model", "what": "The model alone, asked once", "value": m.get("city"),
                    "who": m.get("who"), "why": m.get("why"), "model": m.get("model"), "at": m.get("at")})
    out.append({"id": "record", "source": "record", "what": "The Knos record", **record_line(rep)})
    txs = [s for s in (rep.get("signatures") or {}).values() if isinstance(s, str)]
    out.append({"id": "chain", "source": "chain", "what": "Devnet transactions", "transactions": txs,
                "said": "" if txs else "No devnet transaction for this result: no pre-order was held on it."})
    return out


def shown(rep: dict) -> str | None:
    """The verdict the card shows: the open signals' own words."""
    v = (rep.get("decision") or {}).get("verdict")
    return (rep.get("open_demand") or {}).get("head") or v


def doc(rep: dict) -> dict:
    return {"report": rep.get("hash"), "idea": rep.get("idea"), "made": rep.get("made"), "verdict": shown(rep), "rows": rows(rep),
            "recompute": {"signal": "open each source's link: it shows the count today"}}


STYLE = """body{margin:0;background:#f4f4f0;color:#14151a;font:400 16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:860px;margin:0 auto;padding:16px 16px 40px}a{color:#2b3aa8}h1{font-size:1.5rem;line-height:1.2;margin:8px 0}
table{width:100%;border-collapse:collapse;font-size:.92rem}th,td{text-align:left;vertical-align:top;padding:6px 8px;border-top:1px solid #d6d6cf;overflow-wrap:anywhere}
tr:target{background:#fff3b0}code{font-size:.82rem;overflow-wrap:anywhere}.fine{font-size:.85rem;color:#5a5d68}
@media (prefers-color-scheme:dark){body{background:#07080c;color:#e8e9ee}a{color:#9fb0ff}th,td{border-color:#2a2c35}tr:target{background:#3a3410}.fine{color:#a3a6b3}}
@media (max-width:560px){thead{display:none}table,tbody,tr,td{display:block}tr{border-top:1px solid #d6d6cf;padding:6px 0}td{border:0;padding:2px 0}}
.k-draw{vertical-align:-3px;margin-right:4px;color:#17703f}.k-draw path{stroke-dasharray:24;stroke-dashoffset:0}
@media (prefers-color-scheme:dark){.k-draw{color:#5fd28f}}
@media (prefers-reduced-motion:no-preference){.k-draw path{stroke-dashoffset:24;animation:k-draw .32s cubic-bezier(.2,.8,.2,1) .12s forwards}@keyframes k-draw{to{stroke-dashoffset:0}}}"""
CHECK = '<svg class="k-draw" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>'


def page(rep: dict | None, rid: str) -> str:
    e = html.escape
    if rep is None:
        body = '<h1>No result here</h1><p>No result has this address.</p>'
        title = "No result here"
    else:
        d = doc(rep)
        trs = []
        for r in d["rows"]:
            if r["source"] == "signal":
                cell = f'{e(r["what"])}<br><span class="fine">{e(str(r["at"]))}</span>'
                val = e(r["value"]) + (f' <a href="{e(r["link"])}" rel="noopener">source</a>' if r.get("link") else "")
            elif r["source"] == "model":
                cell, val = e(r["what"]), f'{e(r["value"])}: {e(r.get("who") or "")} <span class="fine">{e(str(r.get("model") or ""))}, {e(str(r.get("at") or "")[:10])}</span>'
            elif r["source"] == "record":
                cell = e(r["what"])
                val = (f'{CHECK}Line {e(str(r["seq"]))}, {e(str(r.get("kind")))}, {e(str(r.get("at") or ""))} <span class="fine">claim {e(str(r["claim"])[:16])}</span>'
                       if r.get("recorded") else e(r.get("why") or ""))
            else:
                cell = e(r["what"])
                val = (CHECK if r["transactions"] else "") + (" ".join(f'<a href="https://explorer.solana.com/tx/{e(s)}?cluster=devnet">{e(s[:12])}</a>' for s in r["transactions"]) or e(r["said"]))
            trs.append(f'<tr id="{e(r["id"])}" data-source="{e(r["source"])}"><td>{e(r["source"])}</td><td>{cell}</td><td>{val}</td></tr>')
        title = f"Receipts: {rep.get('idea') or 'this result'}"
        body = (f'<h1>Receipts</h1><p>{e(str(rep.get("idea") or ""))} · <a href="/r/{e(rid)}">the result</a> · '
                f'<a href="/api/receipts?id={e(rid)}">as JSON</a></p><table data-not-prose><thead><tr><th>Source</th><th>What</th><th>Receipt</th></tr></thead>'
                f'<tbody>{"".join(trs)}</tbody></table>')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Knos. {e(title)}</title><meta name="color-scheme" content="light dark"><link rel="icon" href="/static/icon.svg" type="image/svg+xml">'
            f'<style>{STYLE}</style></head><body><main data-receipts="{e(rid)}"><p class="fine"><a href="https://drexthealpha.github.io/Knos/">Knos</a> · '
            f'Devnet, test money.</p>{body}</main></body></html>')
