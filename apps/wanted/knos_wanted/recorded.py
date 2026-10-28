"""When Qloo is not answering, the card says so. A failed Qloo call (HTTP 429, a 5xx, or no answer in time) marks the
report `qloo_down` with its code, and the card's first line says it; for the 8 sample chips the last real full card
is shown instead, marked `stale` with the time it was made. Each chip's card is its first real answer to a reader's
press (nothing is run at boot) and is kept with no expiry. They survive a redeploy in one private place: a Render secret
file (KNOS_RECORDED_FILE, by default /etc/secrets/knos-recorded.json), read at boot. Never the repository, the Pages
build, Sibyl, devnet or any public store. A new real card is written back to that file at most once in 10 minutes, and
only when this server was given the means to (KNOS_RECORDED_UPLOAD_KEY and RENDER_SERVICE_ID); without them it stays in
memory until the operator uploads the file from their own machine."""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
import urllib.request

# the front door's 8 sample chips (web/brand/hero.html): 7 ideas for the demand check and 1 paper for a crossing
CHIPS = ("an AI recipe planner for families", "a crypto podcast for beginners", "a quantum physics book for kids",
         "a solar powered music festival", "a probiotic kombucha brand", "a recycled ocean plastic swimwear brand",
         "a tiny home kit for first-time buyers", "10.1038/nature16521")
TIMEOUT_CODE = 504                       # no answer in time is said as a gateway timeout
DEFAULT_FILE = "/etc/secrets/knos-recorded.json"
WRITE_EVERY_S = 600
_lock = threading.Lock()
_last: dict[str, dict] = {}
_answered: dict[str, dict] = {}          # every other idea Qloo answered, kept the same private way (nearest.py reads them)
_model: dict[str, dict] = {}             # the model's own answer for an idea, with no Qloo (claude -p), kept the same way
_forecasts: dict = {}                    # the forecast ledger's rows (docs/reference/forecast_plan_v2.md): Knos's picks stay here
_index: list[dict] = []                  # more answered ideas, names only (idea, day, entities, tags): the file's "index" (which.py)
MODEL_KEYS = ("city", "who", "why", "model", "at")
_write = {"at": 0.0, "timer": None}


def key(text: str) -> str:
    return " ".join(str(text or "").split()).lower()


CHIP_KEYS = {key(c) for c in CHIPS}


def failure(rep: dict) -> int | None:
    """The HTTP code of the first Qloo call that failed for want of an answer (429, a 5xx, a timeout), or None."""
    for c in rep.get("calls") or []:
        err = str(c.get("error") or "")
        if not err:
            continue
        m = re.search(r"HTTP (\d{3})", err)
        if m and (m[1] == "429" or m[1].startswith("5")):
            return int(m[1])
        if "did not answer" in err or "had not answered" in err:
            return TIMEOUT_CODE
    return None


def real(rep: dict) -> bool:
    """A full card made of real Qloo answers: live, no failed call, the whole check (not the verdict card alone)."""
    return (str(rep.get("label") or "").startswith("LIVE") and rep.get("stage") != "verdict" and failure(rep) is None
            and not rep.get("qloo_down") and not rep.get("stale"))


def path() -> str:
    return os.environ.get("KNOS_RECORDED_FILE") or DEFAULT_FILE


def load(file: str | None = None) -> int:
    """The recorded cards of the private file into memory (at boot); how many chips have one."""
    try:
        doc = json.loads(open(file or path(), encoding="utf-8").read())
    except (OSError, ValueError):
        return 0
    from . import check                   # a card recorded before a segment's name was known to be sensitive is shown without it
    from . import metros                  # and its launch terms written in, by the rule every page draws (metros.launch_terms)
    from . import signals                 # and what each Qloo signal changes on it (the published table)
    cards = {k: metros.with_terms(check.retie(check.scrub(v))) for k, v in (doc.get("cards") or {}).items() if k in CHIP_KEYS and isinstance(v, dict) and real(v)}
    cards = {k: {**v, "signals": signals.for_card(v)} for k, v in cards.items()}
    answered = {key(k): metros.with_terms(check.retie(check.scrub(v))) for k, v in (doc.get("answered") or {}).items() if isinstance(v, dict) and real(v)}
    model = {key(k): v for k, v in (doc.get("model_alone") or {}).items() if isinstance(v, dict) and v.get("city")}
    alone = lambda v: {**v, "model_alone": {f: model[key(v.get("idea"))].get(f) for f in MODEL_KEYS}} if key(v.get("idea")) in model else v  # noqa: E731
    # a card recorded under an older cache line says what the cache does today (qloo_rest.LIVE_LABEL)
    from .qloo_rest import LIVE_LABEL
    relabel = lambda v: {**v, "label": LIVE_LABEL} if str(v.get("label") or "").startswith("LIVE Qloo data (Qloo REST API") else v  # noqa: E731
    cards = {k: relabel(alone(v)) for k, v in cards.items()}
    answered = {k: relabel(alone(v)) for k, v in answered.items()}
    cards = {k: {**v, "gap": signals.gap(v)} for k, v in cards.items()}          # the model's city beside Qloo's, the flip, what was rejected
    answered = {k: {**v, "gap": signals.gap(v)} for k, v in answered.items()}
    from . import qloo_rest                 # the recorded cards' Qloo calls open the request log (/api/calls), oldest first
    if not any(x.get("origin") == "recorded" for x in qloo_rest.RECENT):
        calls = sorted(((c, v) for v in [*cards.values(), *answered.values()] for c in v.get("calls") or [] if isinstance(c, dict)),
                       key=lambda cv: str(cv[0].get("at") or cv[1].get("made") or ""))
        for c, v in calls[-200:]:
            qloo_rest.note(str(c.get("call") or ""), c.get("params") if isinstance(c.get("params"), dict) else {}, "recorded", c.get("ms"),
                           bool(c.get("cached")), at=str(c.get("at") or v.get("made") or ""), origin="recorded")
    extra = [{"idea": str(r.get("idea")), "made": str(r.get("made") or ""), "entities": [str(e) for e in r.get("entities") or []][:12],
              "tags": [str(t) for t in r.get("tags") or []][:12], "source": str(r.get("source") or "")}
             for r in doc.get("index") or [] if isinstance(r, dict) and r.get("idea")]
    with _lock:
        _model.update(model)
        _answered.update(answered)
        _index[:] = extra
        fc = doc.get("forecasts")
        _forecasts.clear()
        if isinstance(fc, dict) and isinstance(fc.get("rows"), list):
            _forecasts.update({"rows": fc["rows"], "sha256": fc.get("sha256")})
        for k, v in cards.items():
            if k not in _last or (v.get("made") or "") > (_last[k].get("made") or ""):
                _last[k] = v
        return len(_last)


def _upload() -> None:
    """Write the recorded cards back to the Render secret file (only with KNOS_RECORDED_UPLOAD_KEY and RENDER_SERVICE_ID)."""
    k, sid = os.environ.get("KNOS_RECORDED_UPLOAD_KEY"), os.environ.get("RENDER_SERVICE_ID")
    with _lock:
        _write.update(at=time.time(), timer=None)
        doc = {"v": 1, "about": "the sample chips' last real full cards (private: a Render secret file, never public)", "cards": dict(_last), "answered": dict(_answered),
               "model_alone": dict(_model)}
    if not (k and sid):
        return
    body = json.dumps({"content": json.dumps(doc, separators=(",", ":"), ensure_ascii=False)}).encode()
    req = urllib.request.Request(f"https://api.render.com/v1/services/{sid}/secret-files/{os.path.basename(path())}", method="PUT", data=body,
                                 headers={"Authorization": "Bearer " + k, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=60).read()
    except Exception as why:  # noqa: BLE001 - a write that fails keeps the card in memory, said in the log
        print(f"knos recorded: write-back failed ({type(why).__name__})", flush=True)


def _write_soon() -> None:
    """At most one write-back in WRITE_EVERY_S, after a new real card."""
    with _lock:
        if _write["timer"] is not None:
            return
        wait = max(0.0, _write["at"] + WRITE_EVERY_S - time.time())
        _write["timer"] = threading.Timer(wait, _upload)
        _write["timer"].daemon = True
        _write["timer"].start()


def keep(text: str, rep: dict) -> None:
    k = key(text)
    if k in CHIP_KEYS and real(rep):
        with _lock:
            _last[k] = copy.deepcopy(rep)
        if os.environ.get("KNOS_RECORDED_UPLOAD_KEY"):
            _write_soon()


def by_hash(h: str) -> dict | None:
    """A recorded sample card by its report hash (a copy), or None."""
    with _lock:
        r = next((v for v in [*_last.values(), *_answered.values()] if v.get("hash") == h), None)
    return copy.deepcopy(r) if r else None


def recording(text: str) -> dict | None:
    with _lock:
        r = _last.get(key(text))
    return copy.deepcopy(r) if r else None


def honest(text: str, rep: dict, picked: bool = False) -> dict:
    """The report as the card should show it (_honest), with Qloo's month line on every limited answer, and each call
    said as it is (live_or_recorded). picked: the reader picked this exact reading (which.py), so no other idea's answer
    stands in for it: with Qloo out and nothing recorded for it, its check is queued (which.queued)."""
    if picked and failure(rep) is not None and not (recording(text) or answered(text)):
        from . import which
        out = which.queued(text, rep)
        from . import qloo_status
        line = qloo_status.limit_line()
        return live_or_recorded({**out, **({"qloo_limit": line, "qloo_reset": qloo_status.reset_day()} if line else {})})
    out = _honest(text, rep)
    if failure(rep) is not None:
        from . import qloo_status
        line = qloo_status.limit_line()
        if line:
            out = {**out, "qloo_limit": line, "qloo_reset": qloo_status.reset_day()}
    return live_or_recorded(out)


RECORDED_LABEL = "Recorded Qloo data (Qloo REST API, answered on {day}, kept privately on the server)"


def live_or_recorded(rep: dict) -> dict:
    """A Qloo call is live only when this request got HTTP 200 from Qloo: a call made now, not served from the cache and
    with no error. Every other answered call is "recorded <date>", the day Qloo answered it. A card served from a
    recording has no live call at all. The report carries the counts the card and the MCP both show."""
    served = bool(rep.get("stale"))
    calls, live, recorded_n, failed, ms = [], 0, 0, 0, 0
    for c in rep.get("calls") or []:
        if not isinstance(c, dict):
            continue
        c = dict(c)
        ok = not c.get("error")
        is_live = ok and not served and not c.get("cached")
        day = str(c.get("at") or rep.get("made") or "")[:10] or None
        c["live"] = is_live
        c["recorded"] = None if is_live or not ok else day
        live += is_live
        recorded_n += bool(ok and not is_live)
        failed += not ok
        ms += c.get("ms") if isinstance(c.get("ms"), (int, float)) else 0
        calls.append(c)
    days = sorted({c["recorded"] for c in calls if c.get("recorded")})
    label = rep.get("label")
    if not live and str(label or "").startswith("LIVE"):
        label = RECORDED_LABEL.format(day=days[-1] if days else str(rep.get("made") or "")[:10])
    return {**rep, "calls": calls, "label": label,
            "qloo_calls": {"total": len(calls), "live": live, "recorded": recorded_n, "failed": failed, "ms": round(ms), "days": days}}


def _honest(text: str, rep: dict) -> dict:
    """The report as the card should show it: kept when real; when Qloo failed, the chip's last real card marked stale,
    or the report itself marked qloo_down."""
    code = failure(rep)
    if code is None:
        keep(text, rep)
        return rep
    rec = recording(text) or answered(text)
    if rec:
        from . import qloo_rest                     # /status/qloo counts the answers served from recordings today
        qloo_rest._today()["recorded"] = qloo_rest._today().get("recorded", 0) + 1
        return {**rec, "stage": rep.get("stage") or rec.get("stage"), "qloo_down": {"code": code},
                "stale": {"code": code, "from": rec.get("made")}}
    near = closest(text)
    if near and near.get("report"):                 # the nearest idea Qloo has answered, with no Qloo call
        n = near["report"]
        from . import qloo_rest
        qloo_rest._today()["recorded"] = qloo_rest._today().get("recorded", 0) + 1
        return {**n, "stage": n.get("stage") or "full", "qloo_down": {"code": code}, "stale": {"code": code, "from": n.get("made")},
                "nearest": {"asked": text, "idea": n.get("idea"), "on": str(n.get("made") or "")[:10], "shared": near["count"]},
                "nearest_next": near.get("next") or []}
    if near:
        return {**rep, "qloo_down": {"code": code}, "nearest_options": near["options"], "nearest_shared": near["count"]}
    return {**rep, "qloo_down": {"code": code}}


def matched(text: str) -> list[str]:
    """The products Qloo matched to a recorded idea (a chip's card or an answered idea), leader first; [] for any other."""
    k = key(text)
    with _lock:
        r = _last.get(k) or _answered.get(k)
    if not r:
        return []
    lead = r.get("leader")
    lead = lead.get("name") if isinstance(lead, dict) else lead
    names = [m.get("name") for m in r.get("matches") or [] if isinstance(m, dict) and m.get("name")]
    return ([lead] if lead else []) + [n for n in names if n != lead]


def answered(text: str) -> dict | None:
    """An answered idea kept under its own words (a copy), or None."""
    with _lock:
        r = _answered.get(key(text))
    return copy.deepcopy(r) if r else None


def closest(text: str) -> dict | None:
    """The nearest idea Qloo has answered (nearest.find), over the chips' cards and every other answered idea."""
    from . import nearest
    with _lock:
        pool = {key(r.get("idea") or k): r for k, r in {**_answered, **_last}.items()}
    got = nearest.find(text, list(pool.values()))
    if got and got.get("report"):
        got["report"] = copy.deepcopy(got["report"])
    return got

