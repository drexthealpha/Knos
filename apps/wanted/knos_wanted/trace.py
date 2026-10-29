"""The Qloo trace of a demand report: every Qloo call it made, redacted, so each Qloo-derived value Knos shows can link
to where it came from.

A trace holds, per call: the endpoint, the parameters exactly as sent (entity and tag ids included; the API key is a
request header and never appears), when, what Knos used it for, and an excerpt of the result (a few names, as the
report's digest kept them). With it the decision the calls led to, and the limit every Qloo result carries
(`LIMIT`). No person's data is in it: Knos sends none to Qloo (knos_wanted.privacy).

    GET  /api/trace?hash=<report>      the trace (from the report, or a kept copy after a redeploy)
    POST /api/trace/keep {"hash"}      keep a copy on devnet (knos_wanted.chainstate), so links to it survive redeploys
    /trace.html?hash=<report>          the page that draws it

A trace is kept on devnet only when something links to it: a project opened on the report, or the "With and without
Qloo" table. Kept copies are what the kit allows: "Cache only what your project needs" (Qloo's
docs/API_ACCESS.md).
"""
from __future__ import annotations

import json
import re

from . import escrow

LIMIT = ("Qloo describes aggregate cultural taste: affinities of many people, not a cause, not a forecast, and not a "
         "statement about any one person.")
_HASH = re.compile(r"[0-9a-f]{64}")


def _dir():
    d = escrow._state_dir() / "valley" / "traces"
    d.mkdir(parents=True, exist_ok=True)
    return d


def build(rep: dict) -> dict:
    from . import recorded                     # a stored report is "recorded <its day>", never LIVE, whatever its old label
    rep = recorded.stored(rep)
    d = rep.get("decision") or {}
    calls = [{"n": c.get("n"), "endpoint": c.get("call"), "params": c.get("params") or {}, "at": c.get("at"), "cached": bool(c.get("cached")), "surface": c.get("surface"),
              "what": c.get("what"), "used_for": c.get("effect"), "excerpt": c.get("body_digest") or c.get("out")}
             for c in rep.get("calls") or []]
    return {"v": 1, "hash": rep.get("hash"), "idea": rep.get("idea"), "made": rep.get("made"), "label": rep.get("label"),
            "without_qloo": bool(rep.get("without_qloo")), "decision": {"verdict": d.get("verdict"), "reasons": (d.get("reasons") or [])[:4]},
            "calls": calls, "limit": LIMIT, "page": f"/trace.html?hash={rep.get('hash')}"}


def load(state, h: str) -> dict | None:
    if not isinstance(h, str) or not _HASH.fullmatch(h):
        return None
    rep = state.report(h)
    if rep is not None:
        return build(rep)
    f = _dir() / f"{h}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def keep(state, h: str) -> dict:
    """Write the trace beside the state and on devnet; idempotent. Refused for a report this server does not have."""
    t = load(state, h)
    if t is None:
        raise ValueError("unknown report: run the demand check first")
    f = _dir() / f"{h}.json"
    if not f.exists():
        f.write_text(json.dumps(t, default=str), encoding="utf-8")
        from . import chainstate
        chainstate.queue_save("traces", h, t)
    return {"kept": True, "hash": h, "page": t["page"], "calls": len(t["calls"])}


def restore_save(kind: str, key: str, obj: dict) -> None:
    """chainstate.restore's writer for traces (projects go through knos_wanted.valley)."""
    (_dir() / f"{key}.json").write_text(json.dumps(obj, default=str), encoding="utf-8")
