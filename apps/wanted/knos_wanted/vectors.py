"""The seven product-value vectors, measured, and the proof shown first.

    note(kind, ms, rep)   after each demand check or crossing: how long it took, how many Qloo calls it made
    vectors()             GET /api/vectors: cost, speed, friction, trust, capability, access, status, each measured
    proof()               GET /api/proof: the latest real verdict, as the front doors draw it at load

Speed is the median of the checks this server ran (cached answers included, and said so); cost is the API spend of a
check (the Qloo key and the free hosting cost nothing per call) and the measured cost of a Ready brief (the
IDT benchmark, docs/idt/summary.json). Nothing is estimated: a vector with no measurement yet says so.
"""
from __future__ import annotations

import copy
import json
import statistics
import threading
import time
from pathlib import Path

_lock = threading.Lock()
_runs: list[dict] = []
_proof: dict | None = None
_saved_at = [0.0]
KEEP, SAVE_EVERY_S = 300, 600.0
IDT = Path(__file__).resolve().parents[3] / "docs" / "idt" / "summary.json"


_loaded = [False]


def _load() -> None:
    """The saved runs and proof, read once a process (the page that shows them must not wait on the store each time)."""
    global _proof
    if _loaded[0]:
        return
    from . import valley
    doc = valley._safe_load("pages", "vectors") or {}
    with _lock:
        _loaded[0] = True
        if not _runs:
            _runs.extend(doc.get("runs") or [])
        if _proof is None and public(doc.get("proof") or {}) and ((doc.get("proof") or {}).get("decision") or {}).get("verdict") == "OPEN":
            _proof = shape(doc.get("proof"))


CALL_KEYS = ("n", "call", "params", "cached", "ms", "at", "effect", "error")


def shape(p: dict | None) -> dict | None:
    """A proof as the front doors read it: `calls` a list of calls (their requests, never Qloo's answers) and `n_calls`
    their count. A proof saved before held the count in `calls`: it becomes `n_calls`, with no list."""
    if not isinstance(p, dict):
        return p
    calls = p.get("calls")
    rows = [{k: c.get(k) for k in CALL_KEYS if k in c} for c in calls if isinstance(c, dict)] if isinstance(calls, list) else []
    n = len(calls) if isinstance(calls, list) else calls if isinstance(calls, int) else len(rows)
    return {**p, "calls": rows, "n_calls": n}


_public: set[str] = set()


def _norm(idea) -> str:
    return " ".join(str(idea or "").lower().split()).rstrip(".")


def public(rep: dict) -> bool:
    """Is this check one the site itself offers (a hero example or a front-door product: each chosen because Qloo answers
    it in full)? Only such a check is shown to the next visitor: what a person typed stays theirs."""
    if not _public:
        import re

        from . import front
        page = (Path(__file__).resolve().parent / "static" / "index.html").read_text(encoding="utf-8")
        _public.update(_norm(x) for x in re.findall(r'data-q="([^"]+)"', page))
        _public.update(_norm(s.get("idea")) for s in front.SEEDS if s.get("idea"))
        _public.discard("")
    return _norm(rep.get("idea")) in _public or _norm(rep.get("ref")) in _public


def _terms(rep: dict) -> dict | None:
    """The report's launch terms with the metros the card maps (metros.terms), by the one rule every page draws."""
    from . import metros
    t = metros.with_terms(rep).get("terms")
    return {k: t.get(k) for k in ("city", "target", "cells", "refund_rule", "metros", "by_population")} if t else None


def _card(rep: dict) -> dict:
    """What a front door draws for a verdict: the decision, who, where (with coordinates), the price tier, the trace."""
    d = rep.get("decision") or {}
    return {"hash": rep.get("hash"), "idea": rep.get("idea"), "label": rep.get("label"), "made": rep.get("made"),
            "decision": {"verdict": d.get("verdict"), "reasons": (d.get("reasons") or [])[:2], "plan": d.get("plan")},
            "who": rep.get("who"), "audiences": (rep.get("audiences") or [])[:3], "cities": (rep.get("cities") or [])[:5],
            "price": rep.get("price"), "terms": _terms(rep), "no_map": rep.get("no_map"), "calls": shape({"calls": rep.get("calls") or []})["calls"], "n_calls": len(rep.get("calls") or []),
            "leader": {k: (rep.get("leader") or {}).get(k) for k in ("name", "id")} if isinstance(rep.get("leader"), dict) else None}


def note(kind: str, ms: float, rep: dict, state=None) -> None:
    """One measured run. A real Open verdict (with Qloo's cities) on a public example becomes the proof shown first."""
    global _proof
    _load()
    calls = rep.get("calls") or []
    verdict = (rep.get("decision") or {}).get("verdict")
    row = {"kind": kind, "ms": round(ms), "calls": len(calls), "cached": bool(calls) and all(c.get("cached") for c in calls),
           "verdict": verdict, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    real = verdict == "OPEN" and rep.get("cities") and not rep.get("without_qloo") and not rep.get("private") and public(rep)   # a Wanted verdict leads
    with _lock:
        _runs.append(row)
        del _runs[:-KEEP]
        if real:
            _proof = {**_card(rep), "checked_at": row["at"]}
        due = time.time() - _saved_at[0] > SAVE_EVERY_S or (real and (_proof or {}).get("hash") == rep.get("hash"))
        if due:
            _saved_at[0] = time.time()
        doc = {"runs": list(_runs), "proof": _proof}
    if due:
        from . import valley
        valley._save("pages", "vectors", doc)
    if real and state is not None:
        try:
            from . import trace
            trace.keep(state, rep.get("hash") or "")              # the proof's trace survives a redeploy
        except Exception:  # noqa: BLE001 - the trace is a link of the card; the card is shown either way
            pass


def _idt() -> dict:
    try:
        return json.loads(IDT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _program(escrow=None) -> str | None:
    """The escrow program's devnet id, as the package ships it (knos/settle/v2/program_ids.json)."""
    try:
        import knos.settle.v2 as v2
        return json.loads((Path(v2.__file__).parent / "program_ids.json").read_text(encoding="utf-8"))["knos_pay"]
    except Exception:  # noqa: BLE001 - no escrow package here: the vector says so
        return None


def vectors() -> dict:
    _load()
    with _lock:
        runs = list(_runs)
    checks = [r for r in runs if r["kind"] == "check"]
    fresh = [r for r in checks if not r["cached"]]
    med = lambda xs: round(statistics.median(xs) / 1000, 1) if xs else None  # noqa: E731
    idt = _idt()
    tasks = idt.get("tasks") or 0
    from . import escrow, track
    return {
        "cost": {"api_usd_per_check": 0.0, "why": "the Qloo key and the free hosting cost nothing per call",
                 "qloo_calls_per_check": round(statistics.median([r["calls"] for r in checks])) if checks else None,
                 "usd_per_ready_brief": round(idt["ready_cost_usd"] / tasks, 4) if tasks else None,
                 "brief_source": "docs/idt/summary.json (measured agent runs)"},
        "speed": {"median_s": med([r["ms"] for r in checks]), "median_s_fresh": med([r["ms"] for r in fresh]),
                  "checks": len(checks), "fresh": len(fresh),
                  "paper_median_s": med([r["ms"] for r in runs if r["kind"] == "crossing"]),
                  "papers": sum(1 for r in runs if r["kind"] == "crossing")},
        "friction": {"steps_to_verdict": 2, "steps": ["paste", "press"], "sign_up": False},
        "trust": {"escrow_program": _program(escrow), "held_program": _program(escrow), "cluster": "devnet",
                  "proof": "every Qloo value links to its call (/trace.html)"},
        "capability": {"idt_ratio": idt.get("ratio_vague_to_ready"), "ready_pass": idt.get("ready_pass_rate"),
                       "vague_pass": idt.get("vague_pass_rate"), "tasks": tasks},
        "access": {"fields": 7, "countries": "any (Qloo's geocodes)", "phone": True, "sign_up": False},
        "status": track.ready_cards_summary(),
    }


def proof() -> dict:
    _load()
    with _lock:
        p = shape(dict(_proof)) if _proof else None
    return {"proof": p, "label": "A real check this server ran" if p else "No real check yet", "sample": open_sample(),
            "qloo_line": _qloo_line()}


def _qloo_line() -> str | None:
    from . import qloo_status
    return qloo_status.doc()["line"]


def open_sample() -> dict | None:
    """The first sample chip (recorded.CHIPS order) whose recorded card opens pre-orders in a launch city: the finished
    result the front door draws at load. From the private recordings, never the page."""
    from . import metros, recorded
    with recorded._lock:
        cards = [recorded._last.get(recorded.key(c)) for c in recorded.CHIPS]
    for r in cards:
        if r and (r.get("decision") or {}).get("verdict") == "OPEN" and metros.launch_terms(r):
            return copy.deepcopy(r)
    return None


SPEED = '<li data-v="speed"><b>…</b> median to verdict</li>'
STATUS = '<li data-v="status"><b>Ready cards</b></li>'
COST = '<li data-v="cost"><b>$0</b> per check</li>'


TRUST = '<li data-v="trust"><b>Held</b> until proof, on devnet</li>'


def fill(html: str, v: dict, base: str = "") -> str:
    """The measured numbers written into a page's vectors (web/brand/vectors.html) before it is sent, so a reader with no
    script, or one that has not scrolled yet, sees the number and not "…"; vectors.js writes the same words and links.
    `base`: the app's address for a link to one of its pages ("" on the app itself)."""
    from html import escape
    t = (v.get("trust") or {}).get("escrow_program")
    if t:
        html = html.replace(TRUST, f'<li data-v="trust"><a href="https://explorer.solana.com/address/{escape(str(t))}?cluster=devnet" '
                                   'rel="noopener"><b>Held</b> until proof, on devnet</a></li>')
    s = (v.get("speed") or {}).get("median_s")
    if isinstance(s, (int, float)):
        html = html.replace(SPEED, f'<li data-v="speed"><b>{s:g} s</b> median to verdict</li>')
    c = v.get("cost") or {}
    per, brief = c.get("api_usd_per_check"), c.get("usd_per_ready_brief")
    if isinstance(per, (int, float)):                # the same words vectors.js writes: nothing moves when it runs
        html = html.replace(COST, f'<li data-v="cost"><b>${per:g}</b> per check' + (f", <b>${brief:g}</b> per brief" if isinstance(brief, (int, float)) else "")
                            + "</li>")
    st = v.get("status") or {}
    n = st.get("ready_cards_attested")
    if isinstance(n, int) and not isinstance(n, bool):
        word = f'<b>{n} Ready card{"" if n == 1 else "s"}</b>'
        link = f'<a href="{escape(base + str(st["latest"]))}" title="Attested on Solana devnet">{word}</a>' if st.get("latest") else word
        html = html.replace(STATUS, f'<li data-v="status">{link}</li>')
    return html


_filled: list = [0.0, None]


def filled(html: str) -> str:
    """fill() with this server's numbers, read at most once a minute."""
    if SPEED not in html and STATUS not in html and COST not in html and TRUST not in html:
        return html
    if _filled[1] is None or time.monotonic() - _filled[0] > 60:
        try:
            _filled[:] = [time.monotonic(), vectors()]
        except Exception:  # noqa: BLE001 - the page goes out as it shipped; vectors.js asks again
            return html
    return fill(html, _filled[1])
