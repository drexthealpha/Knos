"""Qloo's state as this server has met it today, from its own traffic only (nothing here asks Qloo): the calls it sent,
the answers its cache gave, the hit rate, the last success and the last 429, and whether Qloo is limiting the key now.
GET /status/qloo draws it in the app's stylesheet; GET /api/qloo/status gives it to the front door, which shows one
line above the chips while Qloo is limiting requests."""
from __future__ import annotations

import html
import time

from . import qloo_rest, recorded


def _when(at: str | None) -> str | None:
    if not at:
        return None
    try:
        return time.strftime("%d %b %Y, %H:%M UTC", time.strptime(at[:19], "%Y-%m-%dT%H:%M:%S")).lstrip("0")
    except ValueError:
        return at


def reset_day() -> str | None:
    """The day Qloo's month resets, as the card says it ("20 Nov 2026"), from Qloo's own header; None before it is read."""
    at = str(qloo_rest.LIMITS.get("month_reset_at") or "")
    try:
        return time.strftime("%d %b %Y", time.strptime(at[:19], "%Y-%m-%dT%H:%M:%S")).lstrip("0")
    except ValueError:
        return None


def limit_line() -> str | None:
    """While Qloo's month is used up (its own header says 0 calls left): the sentence every limited answer says."""
    lim = qloo_rest.LIMITS
    if str(lim.get("x-month-ratelimit-remaining")) != "0":
        return None
    at = str(lim.get("month_reset_at") or "")
    try:
        day = time.strftime("%d %b %Y", time.strptime(at[:19], "%Y-%m-%dT%H:%M:%S")).lstrip("0")
    except ValueError:
        day = "the month's reset"
    return f"Qloo's monthly limit for Knos is reached until {day}. Cards show the last live answers."


def doc() -> dict:
    t = qloo_rest.today()
    with recorded._lock:
        made = max((str(r.get("made") or "") for r in recorded._last.values()), default="") or None
    live_at = t.get("last_ok") or made                 # the newest live answer a card can show: today's, else a recording's
    month = limit_line()
    line = month or (f"Qloo is limiting requests right now. Cards show the last live answer from {_when(live_at)}." if t["limited"] and live_at else (
        "Qloo is limiting requests right now." if t["limited"] else None))
    lim = dict(qloo_rest.LIMITS)
    return {"month_left": lim.get("x-month-ratelimit-remaining"), "month_limit": lim.get("x-month-ratelimit-limit"),
            "month_reset": lim.get("month_reset_at") or lim.get("x-month-ratelimit-reset"), "second_left": lim.get("x-second-ratelimit-remaining"),
            "limits_read": lim.get("read"), "day_cap": qloo_rest.DAY_CAP, "month_floor": qloo_rest.MONTH_FLOOR,
            "day": t["day"], "calls": t["calls"], "cache_hits": t["hits"], "recorded": t.get("recorded", 0), "hit_rate": t["hit_rate"], "last_ok": t.get("last_ok"),
            "last_429": t.get("last_429"), "held_s": t["held_s"], "limited": t["limited"] or bool(month), "live_at": live_at, "line": line,
            "from": "this server's own calls to Qloo since midnight UTC; this answer asks Qloo nothing", "answered": _answered()}


def _answered() -> dict:
    """What this server holds real Qloo answers for, privately (which.index): distinct ideas, the cards among them, the
    entities and tags Qloo confirmed. Counts only."""
    try:
        from . import which
        return which.counts()
    except Exception:  # noqa: BLE001 - the counts are said, or left out, never guessed
        return {}


def page() -> str:
    d, e = doc(), html.escape
    rate = f"{round(d['hit_rate'] * 100)}%" if d["hit_rate"] is not None else "none yet"
    rows = [("Calls sent today", str(d["calls"])), ("Answered from the cache", f"{d['cache_hits']} ({rate})"),
            ("Served from recordings", str(d["recorded"])),
            *([("Answered ideas held privately", f"{d['answered']['ideas']} ({d['answered']['cards']} full cards)"),
               ("Entities and tags Qloo confirmed", f"{d['answered']['entities']} entities, {d['answered']['tags']} tags")] if d.get("answered") else []),
            ("Qloo's month, calls left", f"{d['month_left']} of {d['month_limit']}, resets {_when(d['month_reset']) or d['month_reset']}" if d["month_left"] is not None else "not read yet"), ("Last success", _when(d["last_ok"]) or "none today"), ("Last 429", _when(d["last_429"]) or "none today")]
    now = (f'<p class="k-terms" data-limited>{e(d["line"])}</p>' if d["line"] else '<p class="k-terms" data-limited="no">Qloo is answering.</p>')
    hold = f'<p class="small">Nothing is sent to Qloo for {d["held_s"]} s more, as its Retry-After asks.</p>' if d["held_s"] else ""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Knos. Qloo status</title><meta name="description" content="What this server met calling Qloo today, from its own traffic.">'
            '<link rel="stylesheet" href="/static/brand/tokens.css"><link rel="stylesheet" href="/static/style.css"></head>'
            f'<body><main class="wrap"><p class="small"><a href="https://drexthealpha.github.io/Knos/">Knos</a></p><h1>Qloo status</h1>{now}{hold}'
            '<dl class="k-facts" data-not-prose>' + "".join(f"<dt>{k}</dt><dd>{e(v)}</dd>" for k, v in rows) + "</dl>"
            f'<p class="small">{e(d["day"])}, UTC. Read from this server\'s own calls. This page asks Qloo nothing.</p></main></body></html>')
