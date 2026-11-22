"""Why people stay or leave, first-party only (Round 8, T8). Each page sends small events with a random visit id that
its browser makes and resets every day; nothing else identifies anyone: no cookie, no IP address and no account is
stored, and a browser that sends Do Not Track sends nothing at all (the page checks before it sends).

Events: view, press (and how long its answer took), result, proof (a proof ran to its end), backed (test money put
behind a claim), download, share, rage (three presses within a second on one spot), slow (a press with no visible answer
within 400 ms), error (an error shown), notwhat ("Not what I need", with an optional word), leave (the last screen and
the seconds on it). A visit says whether its browser came before (`back`), never who it is. Its first view may add whole
days since that browser's first visit (`since`), the screen's language (`lang`), phone or desktop (`dev`) and its time
zone (`tz`, of which only the region before the first slash is kept); never an IP address (L36, L37).

The funnel (visits, first press, first result, proof finished, backed, came back) and the screen people leave from most
are kept per day in memory and in a ledger file a scheduled job saves (visits.json on the gh-pages branch); /status
shows them, 0 until real visits exist."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from collections import Counter
from pathlib import Path

EVENTS = {"view", "press", "result", "proof", "backed", "download", "share", "rage", "slow", "error", "notwhat", "leave"}
LEDGER = Path(os.environ.get("KNOS_VISITS_LEDGER") or (Path(os.environ.get("TMPDIR") or "/tmp") / "knos-visits.json"))
SAVED = os.environ.get("KNOS_VISITS_SAVED", "https://raw.githubusercontent.com/drexthealpha/Knos/gh-pages/visits.json")
_lock = threading.Lock()
_days: dict = {}          # "YYYY-MM-DD" -> {"visits": set, "press": set, ...; "leave": Counter, "words": Counter, "slow": int, ...}
_seeded = [False]


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _day(d: str) -> dict:
    return _days.setdefault(d, {k: set() for k in ("visits", "press", "result", "proof", "backed", "back", "new")} | {"leave": Counter(), "counts": Counter(), "notwhat": Counter(),
                                "groups": {g: {"visits": set(), "result": set()} for g in GROUPS},
                                "meta": {}, "by_language": Counter(), "by_device": Counter(), "by_region": Counter(), "minutes": []})


# L36, L37: what a first view may say of its browser, never who it is: whole days since its first visit, the screen's
# language, phone or desktop, and the region its time zone names (only the part before the first slash is kept)
DEVICES = ("phone", "desktop")
_burst: dict = {}          # (visit id, kind) -> the minute it was last counted: a burst of one kind in one minute counts once


def _meta(ev: dict) -> dict:
    since = ev.get("since")
    since = since if isinstance(since, int) and not isinstance(since, bool) and 0 <= since <= 3660 else None
    lang = str(ev.get("lang") or "").lower()
    lang = lang.split("-")[0] if re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})*", lang) else None
    dev = ev.get("dev") if ev.get("dev") in DEVICES else None
    tz = str(ev.get("tz") or "")
    region = tz.split("/")[0] if re.fullmatch(r"[A-Za-z_]{2,20}(/[A-Za-z0-9_+-]{1,30}){0,2}", tz) else None
    return {"since": since, "lang": lang, "dev": dev, "region": "UTC" if region in ("Etc", "UTC", "GMT") else region,
            "t": time.time()}


def _first_in_minute(vid: str, kind: str) -> bool:
    """The burst filter (L37): one browser's events of one kind within one minute are counted once."""
    minute = int(time.time() // 60)
    if len(_burst) > 200_000:
        _burst.clear()
    if _burst.get((vid, kind)) == minute:
        return False
    _burst[(vid, kind)] = minute
    return True


GROUPS = ("variant", "holdout")


def group_of(vid: str) -> str:
    """A visit's group for a change to the main screen (L39), from its daily random id alone: the last hex digit even
    is the holdout, odd the variant. Nothing is stored to choose it, and the page works it out the same way."""
    return "variant" if int(vid[-1], 16) % 2 else "holdout"


def _seed() -> None:
    if _seeded[0] or os.environ.get("KNOS_VISITS_OFF"):
        return
    _seeded[0] = True
    try:
        with urllib.request.urlopen(urllib.request.Request(SAVED, headers={"User-Agent": "knos-visits"}), timeout=10) as r:
            saved = json.loads(r.read())
        with _lock:
            for d, s in (saved.get("days") or {}).items():
                if d not in _days:
                    _days[d] = {"saved": s}
    except Exception:  # noqa: BLE001 - none saved yet
        pass


def record(ev: dict) -> bool:
    """One event from a page; False when it is not one this module keeps."""
    vid, kind = str(ev.get("v") or ""), str(ev.get("e") or "")
    if not re.fullmatch(r"[0-9a-f]{16}", vid) or kind not in EVENTS:
        return False
    page = re.sub(r"[^a-z0-9/_-]", "", str(ev.get("p") or "")[:40].lower()) or "/"
    with _lock:
        d = _day(_today())
        d["visits"].add(vid)
        if ev.get("back"):
            d["back"].add(vid)
        if _first_in_minute(vid, kind):
            d["counts"][kind] += 1
        meta = d.setdefault("meta", {})
        if kind == "view" and vid not in meta and len(meta) < 100_000:
            m = meta[vid] = _meta(ev)
            if m["since"] == 0:
                d.setdefault("new", set()).add(vid)
        if kind == "result" and vid not in d["result"] and vid in meta:
            m = meta[vid]
            for k, split in (("lang", "by_language"), ("dev", "by_device"), ("region", "by_region")):
                if m[k]:
                    d.setdefault(split, Counter())[m[k]] += 1
            if m["since"] == 0 and len(d.setdefault("minutes", [])) < 1000:
                d["minutes"].append(round((time.time() - m["t"]) / 60, 1))
        if kind in ("press", "result", "proof", "backed"):
            d[kind].add(vid)
        g = d.setdefault("groups", {x: {"visits": set(), "result": set()} for x in GROUPS})[group_of(vid)]
        g["visits"].add(vid)
        if kind == "result":
            g["result"].add(vid)
        if kind == "leave":
            d["leave"][page] += 1
        if kind == "notwhat" and ev.get("why"):
            d["notwhat"][re.sub(r"[^a-z ]", "", str(ev["why"]).lower())[:30]] += 1
    return True


def _plain(d: dict) -> dict:
    if "saved" in d:
        return d["saved"]
    return {"visits": len(d["visits"]), "first_press": len(d["press"]), "first_result": len(d["result"]), "proof_finished": len(d["proof"]),
            "backed": len(d["backed"]), "came_back": len(d["back"]), "events": dict(d["counts"]), "leave_from": dict(d["leave"].most_common(5)),
            "not_what": dict(d["notwhat"].most_common(5)),
            "groups": {g: {"visits": len(v["visits"]), "first_result": len(v["result"])} for g, v in (d.get("groups") or {}).items()},
            "new_visits": len(d.get("new") or ()), "by_language": dict(d.get("by_language") or {}), "by_device": dict(d.get("by_device") or {}),
            "by_region": dict(d.get("by_region") or {}), "minutes_to_result": list(d.get("minutes") or [])}


AFTER_PRESS = "2026-11-13"   # from this day an answer, a proof or a backing counts only when it appears after a press


def summary(days: int = 7) -> dict:
    """The funnel of the last `days` days and the screen people leave from most."""
    _seed()
    with _lock:
        out = {d: _plain(v) for d, v in sorted(_days.items())[-days:]}
    tot = Counter()
    leave = Counter()
    for day, v in out.items():
        for k in ("visits", "first_press", "first_result", "proof_finished", "backed", "came_back"):
            if day < AFTER_PRESS and k in ("first_result", "proof_finished", "backed"):
                continue   # before 13 Nov the page counted these from text a page showed as it loaded, with no press
            tot[k] += int(v.get(k) or 0)
        leave.update(v.get("leave_from") or {})
    groups = {g: {"visits": 0, "first_result": 0} for g in GROUPS}
    for v in out.values():
        for g, x in (v.get("groups") or {}).items():
            if g in groups:
                groups[g]["visits"] += int(x.get("visits") or 0)
                groups[g]["first_result"] += int(x.get("first_result") or 0)
    for x in groups.values():
        x["rate"] = round(x["first_result"] / x["visits"], 4) if x["visits"] else None
    return {"holdout": groups, "days": out, "funnel": {k: tot[k] for k in ("visits", "first_press", "first_result", "proof_finished", "backed", "came_back")},
            "leave_most": leave.most_common(1)[0][0] if leave else None, "results_counted_from": AFTER_PRESS, "read_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def median(xs: list) -> float | None:
    s = sorted(float(x) for x in xs if isinstance(x, (int, float)) and not isinstance(x, bool))
    if not s:
        return None
    m = len(s) // 2
    return round(s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2, 1)


def depth(days: int = 28) -> dict:
    """The visit side of L37 over the last `days` days: results by language, device and region (from the time zone the
    browser named, no address), and the median minutes from a new browser's first view to its first result. Each is
    None while no real result was counted with what it needs: never a made-up 0."""
    got = summary(days)["days"].values()
    out: dict = {}
    for k in ("by_language", "by_device", "by_region"):
        c: Counter = Counter()
        for v in got:
            c.update({a: int(n) for a, n in (v.get(k) or {}).items() if isinstance(n, int)})
        out[k] = dict(c) if c else None
    out["minutes_to_result"] = median([x for v in got for x in v.get("minutes_to_result") or []])
    return out


# ---- L38: the optional questions after a second result, counts only ---------------------------------------------------
SURVEY = {"again": ("yes", "no"), "without": ("yes", "no"), "disappointed": ("very", "somewhat", "not"),
          "rank": ("r_file", "r_paper", "r_pr")}     # web/door.html QS: each question and the answers it offers
SURVEY_KEY = "survey"


def survey_answer(body: dict) -> bool:
    """One answer (POST /api/survey {q, a, test}): one count on that question's answer. Nothing else of the request is
    kept: no id, no address, no time. Knos's own tests count apart. False when it is not a question and answer asked."""
    from . import valley
    q, a = body.get("q"), body.get("a")
    if q not in SURVEY or a not in SURVEY[q]:
        return False
    part = "test" if body.get("test") is True else "answers"
    with _lock:
        doc = valley._safe_load("pages", SURVEY_KEY) or {}
        row = doc.setdefault(part, {}).setdefault(q, {x: 0 for x in SURVEY[q]})
        row[a] = int(row.get(a) or 0) + 1
        valley._save("pages", SURVEY_KEY, doc, chain=False)
    return True


def survey_counts() -> dict:
    """The answers' counts by question, real visitors only; a question nobody answered yet is left out."""
    from . import valley
    doc = valley._safe_load("pages", SURVEY_KEY) or {}
    return {q: {a: int(n) for a, n in v.items()} for q, v in (doc.get("answers") or {}).items() if q in SURVEY and any(v.values())}
