"""The outside counter: crossings and pre-order commitments made by people outside Knos, counted
from the store and nothing else, never seeded.

Each counted event is one row of the day's record (kind "outside", key the UTC day, kept on devnet by
knos_wanted.chainstate like a project): {kind: "crossing" | "commitment", at, ref, via}. `ref` is the crossing's id or
the order's address; no personal data is kept (no address, no label, no wallet). GET /api/outside sums the rows; the
same rows are listed at GET /api/outside/rows, so the counter equals the store.

Left out, and said on the invite page (RULE): the operator's own runs (a request carrying the X-Knos-Admin key), the
team's and the test runs' guest sessions (a label naming Knos, a test, a proof run or CI), automated clients (a
user agent of a headless browser, a script, curl, a bot or GitHub Actions) and orders funded from one of Knos's own
wallets (own_wallets.WALLETS). That last rule is applied when a row is read too, so a row written before it is left out
by the same rule. Nothing is added or removed by hand.
"""
from __future__ import annotations

import datetime as dt
import re
import threading

from . import own_wallets

RULE = ("Counted: crossings started and pre-order commitments locked by people outside Knos. Left out: the operator's own "
        "runs (its admin key), guest sessions labelled as Knos, a test, a proof run or CI, and automated clients (headless "
        "browsers, scripts, curl, bots, GitHub Actions), and orders funded from Knos's own wallets. No row is added or removed by hand.")
_AUTO = re.compile(r"headless|python|curl|wget|bot\b|crawler|spider|github|playwright|puppeteer|httpx|node-fetch|undici|go-http|java/",
                   re.I)
_TEST_LABEL = re.compile(r"\b(knos|test\w*|proof|ci|demo|founder|drexthealpha)\b", re.I)
_lock = threading.Lock()
CTX = threading.local()          # the request being served: its headers (set by the server for each request)


def begin(headers) -> None:
    CTX.headers = headers


def note(kind: str, ref: str, via: str, wallet: str | None = None) -> bool:
    """Count an event of the request being served; with no request (a background job) nothing is counted."""
    headers = getattr(CTX, "headers", None)
    if headers is None:
        return False
    from . import auth, product_routes
    try:
        user = auth.who(headers.get("Authorization"))
    except Exception:  # noqa: BLE001 - an unreadable session is no outside person
        user = None
    try:
        return record(kind, ref, via, headers, user, product_routes._admin(headers.get("X-Knos-Admin")), wallet)
    except Exception:  # noqa: BLE001 - the counter never stops a lock or a crossing
        return False


def excluded(headers, user: dict | None, admin: bool, wallet: str | None = None) -> str | None:
    """Why a request is not an outside one, or None when it counts."""
    if admin:
        return "the operator's key"
    if wallet and str(wallet) in own_wallets.WALLETS:
        return "one of Knos's own wallets"
    if _AUTO.search(str(headers.get("User-Agent") or "")):
        return "an automated client"
    label = str((user or {}).get("label") or "")
    if (user or {}).get("kind") == "guest" and ((user or {}).get("test") or _TEST_LABEL.search(label)):
        return "a Knos or test guest session"
    return None


def record(kind: str, ref: str, via: str, headers, user: dict | None, admin: bool, wallet: str | None = None) -> bool:
    """Count one event when it is an outside one. Returns whether it was counted."""
    if kind not in ("crossing", "commitment") or excluded(headers, user, admin, wallet):
        return False
    from . import valley
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    key = "day-" + day
    with _lock:
        try:
            doc = valley._load("outside", key)
        except valley.Refused:
            doc = {"day": day, "rows": []}
        if any(r["ref"] == str(ref)[:90] and r["kind"] == kind for r in rows()):
            return False                                      # one row per crossing or order, whatever the day
        doc["rows"].append({"kind": kind, "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "ref": str(ref)[:90],
                            "via": str(via)[:40]})
        valley._save("outside", key, doc)
    return True


def _own_order(r: dict) -> bool:
    """A commitment row whose order was funded from one of Knos's own wallets."""
    if r.get("kind") != "commitment":
        return False
    from . import valley
    o = valley._safe_order(str(r.get("ref") or ""))
    return bool(o) and str(o.get("funder") or "") in own_wallets.WALLETS


def rows() -> list[dict]:
    from . import valley
    return sorted((r for d in valley._all("outside") for r in d.get("rows") or [] if not _own_order(r)), key=lambda r: r["at"])


def totals() -> dict:
    rs = rows()
    return {"crossings": sum(1 for r in rs if r["kind"] == "crossing"), "commitments": sum(1 for r in rs if r["kind"] == "commitment"),
            "rows": len(rs), "since": rs[0]["at"] if rs else None, "rule": RULE, "rows_at": "/api/outside/rows"}
