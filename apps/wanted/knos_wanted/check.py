"""Knos's demand check: an idea in plain words -> free, keyless public signals -> a decision made by code.

    report = demand_check("A smart water bottle that reminds you to drink", place="Lagos")
    report["decision"]   {"verdict": "OPEN" | "REFUSE" | "CANNOT_DECIDE", "reasons": [...], "target_units", "reserve_units"}

The signals (knos_wanted.open_signals, each named with its link): how much people read about the idea's subject
(Wikimedia pageviews), how much the news writes about it (GDELT), how much builders post about it (Hacker News), how
much research there is (OpenAlex), and the money already put down on it here. The decision is the rule in
open_signals.fallback: people want it when 2 of those pass. No language model decides.

These sources say how much attention a subject gets; none says who buys it or in which city, so the report names no
audience, no launch city and no pre-order target. Directional demand evidence, not a sales forecast.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import threading

V = 3
KIND = "knos-demand-check"
FRAMING = "Directional demand evidence, not a sales forecast."
LABEL = "OPEN SIGNALS"
OFF = "the open sources are not asked on this server"
DEFAULT_PLACE = "United States"
# The market's country code: the World Bank row of the launch country.
COUNTRIES = {"united states": "US", "usa": "US", "us": "US", "united kingdom": "GB", "uk": "GB", "nigeria": "NG",
             "germany": "DE", "france": "FR", "japan": "JP", "canada": "CA", "australia": "AU", "india": "IN",
             "brazil": "BR", "south korea": "KR", "korea": "KR", "spain": "ES", "italy": "IT", "mexico": "MX"}


def market_country(place: str | None) -> str | None:
    return COUNTRIES.get((place or DEFAULT_PLACE).strip().lower())


# Words that carry no product meaning: grammar, pitch words, and the words of an instruction to this app.
STOP = set("""a an and or but the of for to in on at by with from into onto over under about above after before as is are
was were be been being it its this that these those there here which who whom whose what when where why how all any each
every some such no not nor only own same so than too very can could will would shall should may might must do does did
done have has had having i me my we our ours you your yours he she they them their his her him one two three new brand
like just really also get gets make makes made use uses using used way ways thing things people person someone anyone
everyone idea ideas product products service services startup company business app apps platform tool tools solution
solutions market markets customer customers user users buyer buyers seller sell sells buy buys selling buying
demand target reserve release funds fund money price prices order orders preorder preorders decision decide rules rule
ignore previous instruction instructions system prompt set open close verified overwhelming guaranteed exactly clone
copy version invented invent call called named name similar better best cheaper cheap first ever kind sort type lot built
lots great good amazing awesome cool nice perfect ultimate premium simple easy smart now today tomorrow please brand-new
let lets without within measure measures read reads
all-new""".split())
# Audience words in the idea: dropped from its content words (they say who, not what).
AUDIENCE = ("student", "students", "teen", "teens", "teenagers", "gen z", "young", "millennials", "parents", "moms", "mums",
            "dads", "kids", "children", "seniors", "retirees", "elderly", "older", "women", "woman", "female", "girls", "men",
            "male", "guys")
TIERS = {"budget": 1, "mid": 2, "premium": 4}       # test units per pre-ordered unit (devnet test money; a scale, not a price)


def _norm(w: str) -> str:
    w = w.lower()
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def tokens(text: str) -> list[str]:
    return re.findall(r"[^\W\d_][\w\-]{1,}", (text or "").lower())        # any alphabet: "cómics" stays one word


def content_words(idea: str, place: str | None = None) -> list[str]:
    drop = set(tokens(place or "")) | set(AUDIENCE)
    out: list[str] = []
    for w in tokens(idea):
        if len(w) < 3 or w in STOP or w in drop or _norm(w) in out:
            continue
        out.append(_norm(w))
    return out


def report_hash(rep: dict) -> str:
    keep = {k: v for k, v in rep.items() if k not in ("hash", "calls", "made", "fees")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()


CHECKS_AT_ONCE = 3               # demand checks run at the same time; the next waits
_checks = threading.BoundedSemaphore(CHECKS_AT_ONCE)
running = [0]
_running_lock = threading.Lock()


def demand_check(idea: str, place: str | None = None, leader: str | None = None, today: dt.date | None = None,
                 stage: str | None = None) -> dict:
    """One demand check, CHECKS_AT_ONCE at a time (the free instance has 512 MB)."""
    with _checks:
        with _running_lock:
            running[0] += 1
        try:
            rep = _demand_check(idea, place, leader, today, stage)
            if stage != "verdict":                    # the verdict card and its full card are one check
                from . import usage
                usage.bump(checks=1, briefs=0)
                usage.bump_live(sum(1 for r in (rep.get("open_demand") or {}).get("rows") or [] if r.get("link")))
            return rep
        finally:
            with _running_lock:
                running[0] -= 1


def _demand_check(idea: str, place: str | None = None, leader: str | None = None, today: dt.date | None = None,
                  stage: str | None = None) -> dict:
    from . import open_signals
    idea = " ".join(str(idea or "").split())
    if not 3 <= len(idea) <= 500:            # a one-word idea ("Phoenix") is a person's own input too
        raise ValueError("describe the idea in 3 to 500 characters")
    place = (" ".join(str(place).split())[:60] or None) if place else None
    leader = (" ".join(str(leader).split())[:80] or None) if leader else None
    today = today or dt.datetime.now(dt.timezone.utc).date()
    fb = open_signals.fallback(idea, market_country(place) or "US")
    reasons = [fb["line"]] + ([] if open_signals.online() else [OFF])
    rep = {"v": V, "kind": KIND, "idea": idea, "place": place, "leader_named": leader, "label": LABEL, "framing": FRAMING,
           "open_demand": fb, "matches": [],
           "decision": {"verdict": fb["verdict"], "reasons": reasons, "target_units": None, "reserve_units": None},
           "rules": {"verdict": fb["rule"], **{k: open_signals.RULES[k] for k in ("audience", "cities")}},
           "terms": None, "brief": None, "stage": "verdict" if stage == "verdict" else "full",
           "made": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "day": today.isoformat()}
    rep["hash"] = report_hash(rep)
    return rep
