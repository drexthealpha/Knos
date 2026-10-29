"""Ready to fund: whether a brief is clear enough to lock money on (docs: the IDT check). Deterministic, no AI scoring.

The one check the web app, /mcp, the HTTP API and the knos_pay client (knos.ideas.commit) all call. A brief is a list
of milestones; each milestone needs
  target    measurable: a number with its unit ("p95 under 300 ms", "12 samples") or a named test ("test_login",
            "tests/test_api.py::test_refund", check "build / lint")
  verifier  machine: the GitHub check or test name that decides it; or
            human (lab results, documents): what is measured, how, who measures it, where the record is published
            (the DOE SMART fields)
  deadline  seconds from funding (deadline_s, 60 s to 90 days) or whole days (deadline_days); a lab, field or clinical
            milestone (it names a standard, a registry, a trial or a lab) up to 1,095 days, held in tranches of at most
            90 days each (an order on chain holds money 90 days at most)
and no vague word (VAGUE) in its name, target or verifier. The answer is Ready, or Not ready with every missing field
by name and a one-tap rewrite template per milestone. The criteria hash is the sha256 of the canonical JSON of the
fields that decide payment (plus the kill fee and the challenge window); it is fixed at lock.
"""
from __future__ import annotations

import hashlib
import json
import re

VAGUE = ("better", "faster", "slower", "clean", "cleaner", "robust", "improve", "improved", "improves", "improvement",
         "progress", "modern", "modernize", "nice", "good", "great", "optimize", "optimise", "optimized", "scalable",
         "seamless", "efficient", "enhance", "enhanced", "polish", "polished", "appropriate", "adequate", "significant",
         "user-friendly", "intuitive", "high quality", "best", "etc", "asap", "soon", "some", "various", "reasonable")
UNITS = ("%", "ms", "s", "sec", "secs", "second", "seconds", "min", "mins", "minute", "minutes", "h", "hr", "hrs", "hour",
         "hours", "day", "days", "week", "weeks", "kb", "mb", "gb", "tb", "b", "bytes", "kib", "mib", "gib", "rps", "qps",
         "req/s", "fps", "x", "usd", "eur", "$", "units", "unit", "samples", "sample", "tests", "test", "runs", "run", "users",
         "user", "items", "rows", "files", "pages", "page", "errors", "error", "defects", "defect", "issues", "issue",
         "points", "point", "score", "c", "°c", "k", "mm", "cm", "m", "km", "g", "kg", "mg", "µg", "ug", "ml", "l", "µl",
         "ul", "nm", "µm", "um", "mol", "mmol", "µmol", "mm/s", "v", "mv", "a", "ma", "w", "mw", "kw", "hz", "khz", "mhz",
         "ghz", "db", "ppm", "ppb", "cells", "cell", "reads", "devices", "device", "units/day", "documents", "document",
         "sections", "section", "signatures", "signature", "customers", "customer", "weeks", "months", "month", "lines",
         "commits", "prs", "accuracy", "auc", "f1", "rmse", "mae", "iops", "ops", "cycles", "boards", "parts", "batches",
         "percent", "trials", "trial", "prototype", "prototypes", "features", "feature", "patches", "arrays", "copies",
         "reports", "screens", "endpoints", "steps", "participants", "patients", "litres", "liters", "mah", "wh",
         # physical work: pressure, force, mass, carbon, energy, area, volume, and what is built
         "pa", "kpa", "mpa", "gpa", "psi", "bar", "n", "kn", "n/mm2", "n/mm²", "t", "tonne", "tonnes", "co2e", "kgco2e",
         "kwh", "mwh", "gwh", "gw", "m2", "m²", "m3", "m³", "lux", "cubes", "blocks", "homes", "houses", "panels", "years")
MIN_DEADLINE_S, MAX_DEADLINE_S = 60, 90 * 86_400
MAX_SCIENCE_DEADLINE_S = 1_095 * 86_400       # lab, field and clinical work: seasons, damp-heat hours, accuracy studies
TRANCHE_S = MAX_DEADLINE_S                     # the most one order holds money on chain (knos_pay error 81)
DEFAULT_CHALLENGE_S = 72 * 3600
MAX_KILL_FEE_BPS = 5000
_UNIT_RE = "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True))
# a number with its unit right after it, or up to two words later ("90 Lighthouse score", "1 functional prototype")
_NUM_UNIT = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(?:[A-Za-z][\w-]*\s+){0,2}(" + _UNIT_RE + r")(?![\w])", re.I)
# a named test: test_x, file.py::case, tests/..., check "name", or a joined name with "test(s)" in it (e2e-login-tests)
_TEST = re.compile(r"(?:\btest_[A-Za-z0-9_]+|\b[\w./-]+\.(?:py|js|ts|mjs|rs|go)::[\w\[\]-]+|\b[\w./-]*tests?/[\w./-]+|"
                   r"check\s+[\"'`][^\"'`]{2,100}[\"'`]|\b[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*[-_]tests?(?:[-_][A-Za-z0-9]+)*\b)")
# what decides it, in its own words: normal punctuation allowed (, ; % < > ' "), control characters and backticks not
_CHECK_NAME = re.compile(r"^[^\x00-\x1f\x7f`]{2,300}$")
# a named standard or registry the result is judged on: a count of passes or exceedances on it is measurable
_STANDARD = re.compile(r"\b(?:ASTM|IEC|ISO(?:/IEC)?|EN|UN|UL|SAE|AASHTO|OECD|EPA|CLSI|USABC|RILEM|IEEE|ANSI|NIST|IS)\s?"
                       r"[A-Z]{0,2}\s?\d[\w.:-]*|\bWHO\s+(?:GDWQ|PQ|TPP|prequalification)\b|ClinicalTrials\.gov|\bAEA RCT Registry\b|"
                       r"\bISRCTN\b|\bPROSPERO\b|\bOSF\s+(?:registry|preregistration)\b|\bRIDIE\b|\bEGAP\b")
# an effect size in standard deviations ("0.20 SD gain")
_EFFECT = re.compile(r"(?<![\w.])\d+(?:\.\d+)?\s*SD\b")
# a lab, field or clinical milestone: it may run past 90 days, held in tranches
_SCIENCE = re.compile(r"\b(?:lab|laborator\w*|field|clinical|trial|RCT|preregist\w*|accredit\w*|certif\w*|season\w*|cohort|"
                      r"study|damp heat|qualification|registry)\b", re.I)
HUMAN_FIELDS = ("what", "how", "who", "where")


def _text(v, n: int = 300) -> str:
    return re.sub(r"\s+", " ", v).strip()[:n] if isinstance(v, str) else ""


def vague_words(text: str) -> list[str]:
    low = f" {text.lower()} "
    return sorted({w for w in VAGUE if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low)})


def measurable(target: str) -> bool:
    """A number with its unit, a named test, a count on a named standard or registry ("1 pass on ASTM C1157"), or an
    effect size in SD."""
    return bool(_NUM_UNIT.search(target) or _TEST.search(target) or _EFFECT.search(target)
                or (re.search(r"(?<![\w.])\d", target) and _STANDARD.search(target)))


def science(m: dict) -> bool:
    """Lab, field or clinical work: its name, target or verifier names a standard, a registry, a trial or a lab."""
    v = m.get("verifier")
    text = " ".join(x for x in (m.get("name"), m.get("target"), *(v.values() if isinstance(v, dict) else ())) if isinstance(x, str))
    return bool(_SCIENCE.search(text) or _STANDARD.search(text))


def science_brief(brief) -> bool:
    """A research brief: one of its milestones is lab, field or clinical work, so each of its milestones may run long
    (a costing sheet or an emissions log is paced by the trial around it)."""
    ms = brief.get("milestones") if isinstance(brief, dict) else None
    return any(isinstance(m, dict) and science(m) for m in ms) if isinstance(ms, list) else False


def deadline_s(m: dict, long: bool = False) -> int | None:
    d = m.get("deadline_s")
    if d is None and m.get("deadline_days") is not None:
        d = m.get("deadline_days")
        d = d * 86_400 if isinstance(d, int) and not isinstance(d, bool) else None
    top = MAX_SCIENCE_DEADLINE_S if long or science(m) else MAX_DEADLINE_S
    if isinstance(d, bool) or not isinstance(d, int) or not MIN_DEADLINE_S <= d <= top:
        return None
    return d


def tranches(deadline: int) -> list[int]:
    """A milestone's deadline as the orders that hold its money, each at most TRANCHE_S (90 days) long."""
    n = -(-deadline // TRANCHE_S)
    return [TRANCHE_S] * (n - 1) + [deadline - TRANCHE_S * (n - 1)]


def clean(brief) -> dict:
    """A brief in the shape every check reads: an object whose milestones are a list of objects, each verifier an
    object. Anything else (a list, a string, a number) is dropped here, so a malformed brief is answered Not ready,
    naming its fields, and never reaches code that would fail on it."""
    b = dict(brief) if isinstance(brief, dict) else {}
    ms = b.get("milestones")
    b["milestones"] = [{**m, "verifier": m["verifier"] if isinstance(m.get("verifier"), dict) else {}} if isinstance(m, dict) else {}
                       for m in ms] if isinstance(ms, list) else []
    return b


def normal(m: dict, i: int = 0, long: bool = False) -> dict:
    """One milestone's deciding fields, normalised (the form the hash and the order memo are made from). `long`: it
    belongs to a research brief (science_brief), so its deadline may run to 1,095 days."""
    m = m if isinstance(m, dict) else {}
    raw = m.get("verifier")
    v: dict = raw if isinstance(raw, dict) else {}
    kind = v.get("kind") if v.get("kind") in ("machine", "human") else ("machine" if v.get("check") else "human" if any(v.get(x) for x in HUMAN_FIELDS) else "")
    ver = {"kind": kind, "check": _text(v.get("check"), 300)} if kind == "machine" else \
        {"kind": kind, **{f: _text(v.get(f), 200) for f in HUMAN_FIELDS}} if kind == "human" else {"kind": ""}
    key = _text(m.get("key"), 40) or f"m{i + 1}"
    return {"key": re.sub(r"[^a-z0-9_]", "_", key.lower())[:40], "name": _text(m.get("name"), 160), "target": _text(m.get("target"), 300),
            "verifier": ver, "deadline_s": deadline_s(m, long)}


def check_milestone(m: dict, i: int = 0, long: bool = False) -> dict:
    n = normal(m, i, long)
    missing, vague = [], []
    if len(n["name"]) < 3:
        missing.append("name")
    if not n["target"]:
        missing.append("target")
    elif not measurable(n["target"]):
        missing.append("target: a number with its unit, or a named test")
    v = n["verifier"]
    if not v["kind"]:
        missing.append("verifier")
    elif v["kind"] == "machine":
        if not v["check"]:
            missing.append("verifier.check: the GitHub check or test name")
        elif not _CHECK_NAME.match(v["check"]):
            missing.append("verifier.check: 2 to 300 characters, no backticks or control characters")
    else:
        missing += [f"verifier.{f}" for f in HUMAN_FIELDS if len(v[f]) < 3]
    if n["deadline_s"] is None:
        missing.append("deadline: 60 seconds to 1,095 days for lab, field or clinical work" if long or science(m)
                       else "deadline: 60 seconds to 90 days")
    words = " ".join([n["name"], n["target"], *(x for k, x in v.items() if k != "kind")])
    vague = vague_words(words)
    ok = not missing and not vague
    return {"key": n["key"], "ready": ok, "missing": missing, "vague": vague, "milestone": n,
            "rewrite": None if ok else rewrite(n, vague)}


def rewrite(n: dict, vague: list[str]) -> dict:
    """The one-tap rewrite: the milestone with every missing or vague field turned into a slot to fill."""
    v = n["verifier"]
    name = n["name"]
    for w in vague:
        name = re.sub(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", "<number and unit>", name, flags=re.I)
    target = n["target"] if n["target"] and measurable(n["target"]) and not vague_words(n["target"]) else \
        "<number> <unit> on <named test or measurement>"
    if v.get("kind") == "human":
        ver = {"kind": "human", **{f: v[f] if len(v[f]) >= 3 and not vague_words(v[f]) else f"<{f}>" for f in HUMAN_FIELDS}}
    else:
        ver = {"kind": "machine", "check": v.get("check") if v.get("check") and not vague_words(v.get("check", "")) else
               "<GitHub check or test name>"}
    # the ambiguity-aware form (IDT I5): the interpretation assumed for the first vague word, and how sure the rewrite is
    # (high: only a field was missing; medium: one vague word to resolve; low: several, or nothing to go on)
    assumed = None
    if vague:
        from . import idt
        first = idt.interpretations(" ".join(vague))[0]
        assumed = {"word": first["word"], "reading": first["reading"], "target": first["target"]}
    confidence = "high" if not vague and n["target"] else "medium" if len(vague) == 1 else "low"
    return {"key": n["key"], "name": name or "<what is delivered>", "target": target, "verifier": ver,
            "deadline_days": (n["deadline_s"] // 86_400 or 1) if n["deadline_s"] else 14, "assumed": assumed, "confidence": confidence}


def terms(brief: dict) -> dict:
    kf = brief.get("kill_fee_bps", 0)
    ch = brief.get("challenge_s", DEFAULT_CHALLENGE_S)
    return {"kill_fee_bps": kf if isinstance(kf, int) and not isinstance(kf, bool) else None,
            "challenge_s": ch if isinstance(ch, int) and not isinstance(ch, bool) else None}


def launch(brief) -> dict | None:
    """The launch terms Qloo set (apps/wanted metros.py): city, metro code, mean affinity, the heatmap cells and
    population behind it, the pre-order target and the refund rule, with the ranking's lift and the taste persona's tags. Hashed with the milestones when a brief carries them; a brief without them hashes as before."""
    raw = brief.get("launch") if isinstance(brief, dict) else None
    if not isinstance(raw, dict):
        return None
    a = raw.get("affinity")
    whole = lambda k: raw.get(k) if isinstance(raw.get(k), int) and not isinstance(raw.get(k), bool) else None  # noqa: E731
    out = {"city": _text(raw.get("city"), 120), "cbsa": _text(raw.get("cbsa"), 5),
           "affinity": round(float(a), 4) if isinstance(a, (int, float)) and not isinstance(a, bool) else None,
           "cells": whole("cells"), "population": whole("population"), "target": whole("target"),
           "refund_rule": _text(raw.get("refund_rule"), 300)}
    lf = raw.get("lift")
    if isinstance(lf, (int, float)) and not isinstance(lf, bool):     # the ranking's number, when the brief carries it
        out["lift"] = round(float(lf), 4)
    if isinstance(raw.get("persona"), list):                       # the taste persona's tags: changing one changes the hash
        out["persona"] = [_text(x, 80) for x in raw["persona"][:8]]
    return out


NOT_A_BRIEF = "a brief is a JSON object with a list of milestones"


def criteria_hash(brief: dict) -> str:
    """The brief's criteria hash. A brief that is not an object (a list, a string, null) is refused in one plain sentence
    (ValueError, a 400 on every route), never an AttributeError."""
    if not isinstance(brief, dict):
        raise ValueError(NOT_A_BRIEF)
    b = clean(brief)
    long = science_brief(b)
    ms = [normal(m, i, long) for i, m in enumerate(b["milestones"])]
    body = {"v": 1, "milestones": ms, **terms(b)}
    lt = launch(b)
    if lt is not None:
        body["launch"] = lt
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def check(brief: dict) -> dict:
    """Ready, or Not ready with the exact missing fields and a rewrite template per milestone. Free, sends nothing."""
    raw = brief.get("milestones") if isinstance(brief, dict) else None
    brief = clean(brief)
    long = science_brief(brief)
    rows = [check_milestone(m, i, long) for i, m in enumerate(brief["milestones"])]
    problems = [] if rows else ["milestones: at least one"]
    if raw is not None and not isinstance(raw, list):
        problems.append("milestones: a list of milestone objects")
    elif isinstance(raw, list):
        problems += [f"milestones[{i}]: an object (key, name, target, verifier, deadline)" for i, m in enumerate(raw) if not isinstance(m, dict)]
    problems += [f"m{i + 1}.verifier: an object (kind machine with check, or kind human with what, how, who, where), not text"
                 for i, m in enumerate(raw if isinstance(raw, list) else []) if isinstance(m, dict) and isinstance(m.get("verifier"), str)]
    if len(rows) > 12:
        problems.append("milestones: at most 12")
    if len({r["key"] for r in rows}) != len(rows):
        problems.append("milestones: each key once")
    t = terms(brief)
    lt = launch(brief)
    if lt is not None:
        problems += [f"launch.{k}" for k, v in lt.items() if v in (None, "")]
    if t["kill_fee_bps"] is None or not 0 <= t["kill_fee_bps"] <= MAX_KILL_FEE_BPS:
        problems.append("kill_fee_bps: 0 to 5000 (what the maker keeps if the buyer cancels)")
    if t["challenge_s"] is None or not 60 <= t["challenge_s"] <= 30 * 86_400:
        problems.append("challenge_s: 60 seconds to 30 days (the dispute window after a referee verdict)")
    from . import refuse
    no = refuse.refused(refuse.brief_text(brief))          # the published refuse list (knos.refuse): never fundable
    missing = [f"refused: {r['why']} ('{r['word']}')" for r in no] + problems + [f"{r['key']}.{f}" for r in rows for f in r["missing"]] + \
        [f"{r['key']}: vague word '{w}', say a number and unit instead" for r in rows for w in r["vague"]]
    ok = not missing
    return {"ready": ok, "label": "Refused" if no else "Ready" if ok else "Not ready", "missing": missing, "milestones": rows,
            "refused": no,
            "criteria_hash": criteria_hash(brief) if ok else None, **t, **({"launch": lt} if lt is not None else {}),
            "rule": "each milestone: a measurable target, a verifier (a GitHub check, or what/how/who/where) and a deadline; no vague words"}


class NotReady(ValueError):
    def __init__(self, result: dict):
        self.result = result
        super().__init__("Not ready: " + "; ".join(result["missing"][:8]))


def require(brief: dict) -> dict:
    r = check(brief)
    if not r["ready"]:
        raise NotReady(r)
    return r
