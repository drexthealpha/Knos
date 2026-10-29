"""The public usage counter: demand checks run and Ready briefs made, persisted in the app's store (valley, mirrored on
devnet so a redeploy keeps it), and the transactions of the knos_pay program on devnet, counted with
getSignaturesForAddress. GET /api/usage answers all three; the front door shows them."""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path

KEY = "usage-counter"
_lock = threading.Lock()
_chain: dict = {"at": 0.0, "n": None}
CHAIN_S = 15                          # how long a devnet count is reused (a count takes about 8 s)


def _doc() -> dict:
    from . import valley
    return valley._safe_load("pages", KEY) or {"checks": 0, "briefs": 0,
                                               "since": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")}


def outside_now() -> bool:
    """Whether the request being served is outside use: what knos_wanted.outside counts (no operator key, no automated
    client, no guest session flagged as a test). No request (a boot run, a script in process) is not outside use."""
    from . import auth, outside, product_routes
    h = getattr(outside.CTX, "headers", None)
    if h is None:
        return False
    return outside.excluded(h, auth.who(h.get("Authorization")), product_routes._admin(h.get("X-Knos-Admin"))) is None


def bump(checks: int = 0, briefs: int = 0, outside_use: bool | None = None) -> None:
    """Count what was just made, and, when it is outside use, on its day; a failure to count never fails the request."""
    from . import valley
    try:
        outside_use = outside_now() if outside_use is None else outside_use
        with _lock:
            d = _doc()
            d["checks"] = int(d.get("checks") or 0) + checks
            d["briefs"] = int(d.get("briefs") or 0) + briefs
            if outside_use:
                today = dt.datetime.now(dt.timezone.utc).date()
                days = {k: v for k, v in (d.get("days") or {}).items() if k >= (today - dt.timedelta(days=30)).isoformat()}
                row = days.setdefault(today.isoformat(), {"checks": 0, "briefs": 0})
                row["checks"] += checks
                row["briefs"] += briefs
                d["days"] = days
            valley._save("pages", KEY, d)
    except Exception as why:  # noqa: BLE001
        print(f"knos usage: not counted: {type(why).__name__}: {str(why)[:120]}", flush=True)


def bump_live(live_calls: int) -> None:
    """A check that Qloo answered live (at least one HTTP 200 during its request): counted on its UTC day, whoever ran it."""
    from . import valley
    if live_calls <= 0:
        return
    try:
        with _lock:
            d = _doc()
            today = dt.datetime.now(dt.timezone.utc).date()
            live = {k: v for k, v in (d.get("live_days") or {}).items() if k >= (today - dt.timedelta(days=30)).isoformat()}
            live[today.isoformat()] = int(live.get(today.isoformat()) or 0) + 1
            d["live_days"] = live
            valley._save("pages", KEY, d)
    except Exception as why:  # noqa: BLE001
        print(f"knos usage: live check not counted: {type(why).__name__}: {str(why)[:120]}", flush=True)


def feedback(check_hash: str, useful: bool, note: str, visitor: str) -> dict:
    """One "Was this useful?" answer, kept with the check's hash and a salted visitor hash (never an address or an email);
    one answer per visitor and check, the latest kept. The note is at most 280 characters."""
    from . import valley
    if not isinstance(check_hash, str) or not (8 <= len(check_hash) <= 80) or not check_hash.isalnum():
        raise ValueError("check: the result's hash")
    note = " ".join(str(note or "").split())[:280]
    with _lock:
        d = _doc()
        fb = d.get("feedback") or {}
        fb[f"{check_hash}:{visitor[:16]}"] = {"check": check_hash, "visitor": visitor[:16], "useful": bool(useful), "note": note,
                                              "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        while len(fb) > 5_000:
            fb.pop(next(iter(fb)))
        d["feedback"] = fb
        valley._save("pages", KEY, d)
    return {"saved": True, **feedback_counts(fb)}


def feedback_counts(fb: dict | None = None) -> dict:
    fb = _doc().get("feedback") or {} if fb is None else fb
    return {"feedback_yes": sum(1 for v in fb.values() if v.get("useful")), "feedback_no": sum(1 for v in fb.values() if not v.get("useful"))}


def counter(orders: dict | None = None) -> dict:
    """The public live counter (/api/counter, /proof/, /status/qloo): live checks today and this week, checks by people
    other than the founder this week, devnet pre-orders held and released, and the feedback answers. Zeros are zeros."""
    d = _doc()
    today = dt.datetime.now(dt.timezone.utc).date()
    live = d.get("live_days") or {}
    week = {(today - dt.timedelta(days=i)).isoformat() for i in range(7)}
    others, _ = week_counts(d.get("days") or {})
    o = orders or {}
    return {"checks_today": int(live.get(today.isoformat()) or 0), "checks_week": sum(int(v or 0) for k, v in live.items() if k in week),
            "checks_by_others": others, "preorders_held": o.get("held_n"), "preorders_released": o.get("released_n"),
            "released_on_proof": o.get("released_n"), **feedback_counts(),
            "day": today.isoformat(), "counted": "live: a check Qloo answered with at least one HTTP 200 during its request; others: no operator key, "
            "no automated client, no test session; pre-orders: the app's devnet orders, held and released on proof"}


def week_counts(days: dict, today: dt.date | None = None) -> tuple[int, int]:
    """Outside demand checks this week (today and the 6 days before) and the week before."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    this = {(today - dt.timedelta(days=i)).isoformat() for i in range(7)}
    last = {(today - dt.timedelta(days=i)).isoformat() for i in range(7, 14)}
    n = sum(int((v or {}).get("checks") or 0) for k, v in (days or {}).items() if k in this)
    m = sum(int((v or {}).get("checks") or 0) for k, v in (days or {}).items() if k in last)
    return n, m


def trend_line(n: int, m: int) -> str | None:
    """The one line the front door shows, only for real growth from at least 10: never a static small number."""
    return f"{n} ideas checked this week, up from {m} last week" if n > m and n >= 10 else None


def program() -> str:
    from knos.settle import v2
    return json.loads((Path(v2.__file__).parent / "program_ids.json").read_text(encoding="utf-8"))["knos_pay"]


def chain_count(url: str | None = None) -> int:
    """Every signature of the knos_pay program on devnet (getSignaturesForAddress, 1,000 a page, oldest last)."""
    from knos import chain

    from . import escrow
    url = url or escrow.ledger().url
    n, before = 0, None
    while True:
        opts: dict = {"limit": 1000, "commitment": "confirmed", **({"before": before} if before else {})}
        page = chain.call(url, "getSignaturesForAddress", [program(), opts]) or []
        n += len(page)
        if len(page) < 1000:
            return n
        before = page[-1]["signature"]


def counts() -> dict:
    d = _doc()
    if time.time() - _chain["at"] > CHAIN_S or _chain["n"] is None:
        try:
            _chain.update(n=chain_count(), at=time.time())
        except Exception:  # noqa: BLE001
            pass
    n, m = week_counts(d.get("days") or {})
    return {"trend": {"this_week": n, "last_week": m, "line": trend_line(n, m), "counts": "outside demand checks, test sessions and automated clients left out"},
            "checks": int(d.get("checks") or 0), "briefs": int(d.get("briefs") or 0), "since": d.get("since"),
            "payouts": _chain["n"], "program": program(), "cluster": "devnet",
            "payouts_counted": dt.datetime.fromtimestamp(_chain["at"], dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if _chain["at"] else None}
