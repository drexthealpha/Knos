"""The seven product-value vectors, measured, and the proof shown first.

    note(kind, ms, rep)   after each demand check or crossing: how long it took, how many open sources answered
    vectors()             GET /api/vectors: cost, speed, friction, trust, capability, access, status, each measured
    proof()               GET /api/proof: the latest real verdict, as the front doors draw it at load

Speed is the median of the checks this server ran (cached answers included, and said so); cost is the API spend of a
check (the open sources and the free hosting cost nothing per call) and the measured cost of a Ready brief (the
IDT benchmark, docs/idt/summary.json). Nothing is estimated: a vector with no measurement yet says so.
"""
from __future__ import annotations

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
    from . import check, valley
    doc = valley._safe_load("pages", "vectors") or {}
    with _lock:
        _loaded[0] = True
        if not _runs:
            _runs.extend(doc.get("runs") or [])
        p = doc.get("proof") or {}
        if _proof is None and public(p) and (p.get("decision") or {}).get("verdict") == "OPEN" and p.get("label") == check.LABEL:
            _proof = p


_public: set[str] = set()


def _norm(idea) -> str:
    return " ".join(str(idea or "").lower().split()).rstrip(".")


def public(rep: dict) -> bool:
    """Is this check one the site itself offers (a hero example or a front-door product)? Only such a check is shown to
    the next visitor: what a person typed stays theirs."""
    if not _public:
        import re

        from . import front
        page = (Path(__file__).resolve().parent / "static" / "index.html").read_text(encoding="utf-8")
        _public.update(_norm(x) for x in re.findall(r'data-q="([^"]+)"', page))
        _public.update(_norm(s.get("idea")) for s in front.SEEDS if s.get("idea"))
        _public.discard("")
    return _norm(rep.get("idea")) in _public or _norm(rep.get("ref")) in _public


def _card(rep: dict) -> dict:
    """What a front door draws for a verdict: the decision and each open signal's row with its link."""
    d = rep.get("decision") or {}
    fb = rep.get("open_demand") or {}
    return {"hash": rep.get("hash"), "idea": rep.get("idea"), "label": rep.get("label"), "made": rep.get("made"),
            "decision": {"verdict": d.get("verdict"), "reasons": (d.get("reasons") or [])[:2]},
            "signals": fb.get("rows") or [], "line": fb.get("line"), "rule": fb.get("rule")}


def note(kind: str, ms: float, rep: dict, state=None) -> None:
    """One measured run. A real Open verdict on a public example becomes the proof shown first."""
    global _proof
    _load()
    from . import check
    answered = [r for r in (rep.get("open_demand") or {}).get("rows") or [] if r.get("link")]
    verdict = (rep.get("decision") or {}).get("verdict")
    row = {"kind": kind, "ms": round(ms), "calls": len(answered), "cached": False,
           "verdict": verdict, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    real = verdict == "OPEN" and rep.get("label") == check.LABEL and bool(answered) and not rep.get("private") and public(rep)
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


def _idt() -> dict:
    try:
        return json.loads(IDT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _program(escrow=None) -> str | None:
    """The program that holds this app's pre-orders, milestones and payouts on devnet (preorder.program(): the knos_pay
    TEST build, unless KNOS_WANTED_PROGRAM names another)."""
    try:
        from . import preorder
        return str(preorder.program())
    except Exception:  # noqa: BLE001 - no solders here: the vector says so
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
        "cost": {"api_usd_per_check": 0.0, "why": "the open sources and the free hosting cost nothing per call",
                 "sources_per_check": round(statistics.median([r["calls"] for r in checks])) if checks else None,
                 "usd_per_ready_brief": round(idt["ready_cost_usd"] / tasks, 4) if tasks else None,
                 "brief_source": "docs/idt/summary.json (measured agent runs)"},
        "speed": {"median_s": med([r["ms"] for r in checks]), "median_s_fresh": med([r["ms"] for r in fresh]),
                  "checks": len(checks), "fresh": len(fresh),
                  "paper_median_s": med([r["ms"] for r in runs if r["kind"] == "crossing"]),
                  "papers": sum(1 for r in runs if r["kind"] == "crossing")},
        "friction": {"steps_to_verdict": 2, "steps": ["paste", "press"], "sign_up": False},
        "trust": {"escrow_program": _program(escrow), "held_program": _program(escrow), "cluster": "devnet",
                  "proof": "every open signal links to its source"},
        "capability": {"idt_ratio": idt.get("ratio_vague_to_ready"), "ready_pass": idt.get("ready_pass_rate"),
                       "vague_pass": idt.get("vague_pass_rate"), "tasks": tasks},
        "access": {"fields": 7, "countries": "any (World Bank country codes)", "phone": True, "sign_up": False},
        "status": track.ready_cards_summary(),
    }


def proof() -> dict:
    _load()
    with _lock:
        p = dict(_proof) if _proof else None
    return {"proof": p, "label": "A real check this server ran" if p else "No real check yet"}


SPEED = '<li data-v="speed"><b>…</b> median to verdict</li>'
STATUS = '<li data-v="status"><b>Ready cards</b></li>'
COST = '<li data-v="cost"><b>$0</b> per check</li>'


TRUST = '<li data-v="trust"><b>Held</b> until the check passes, on devnet</li>'


def fill(html: str, v: dict, base: str = "") -> str:
    """The measured numbers written into a page's vectors (web/brand/vectors.html) before it is sent, so a reader with no
    script, or one that has not scrolled yet, sees the number and not "…"; vectors.js writes the same words and links.
    `base`: the app's address for a link to one of its pages ("" on the app itself)."""
    from html import escape
    t = (v.get("trust") or {}).get("escrow_program")
    if t:
        html = html.replace(TRUST, f'<li data-v="trust"><a href="https://explorer.solana.com/address/{escape(str(t))}?cluster=devnet" '
                                   'rel="noopener"><b>Held</b> until the check passes, on devnet</a></li>')
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
