"""No personal data goes to Qloo (Qloo's docs/SAFE_USE.md: "Do not send names, email addresses, device
identifiers, account IDs, location histories, or other personal data to Qloo"). Every argument of every MCP call is
checked here BEFORE it leaves the server; a refused call never reaches Qloo.

What a buyer gives Knos is things they like (public cultural signals: a brand, a film, a cuisine), never who they
are. This guard refuses what looks like identity data: an e-mail address, a phone number, a social handle, a URL,
an IP address, a card or account number, a street address, or a sentence about the person ("my name is").
"""
from __future__ import annotations

import re

MAX_ITEMS = 10
MAX_LEN = 80
SAFE = re.compile(r"^(\d{4}-\d{2}-\d{2}|[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
                  r"|urn:[a-z0-9:_.-]+|mock-[a-z0-9_-]+)$")
# a WKT geometry (Qloo's filter.location: a launch area as POINT or POLYGON), numbers only: a place to sell in, not a person
WKT = re.compile(r"^(POINT|POLYGON|MULTIPOLYGON)\s*\([-0-9.,\s()]{3,400}\)$", re.I)
# a span of years ("2016-2018", "1990 to 2001") is a date range, not a phone number: taken out before the patterns run
YEARS = re.compile(r"\b(?:1[89]|20)\d\d\s*(?:[/\u2013\u2014-]|to)\s*(?:1[89]|20)\d\d\b")
PATTERNS = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "an e-mail address"),
    (re.compile(r"(?<![\w-])@[A-Za-z0-9_]{2,}"), "a social handle"),
    (re.compile(r"https?://|www\.", re.I), "a link"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "an IP address"),
    (re.compile(r"(?:\+|\b)\d(?:[\s().-]?\d){6,}\b"), "a phone, card or account number"),
    (re.compile(r"\b(my|our)\s+(name|email|e-mail|phone|number|address|account|id|birthday|age)\b", re.I), "a detail about a person"),
    (re.compile(r"\bi\s*(am|'m)\s+(a|an)?\s*\d{1,3}\b", re.I), "a person's age"),
    (re.compile(r"\b\d{1,5}\s+\w+(\s\w+)?\s+(street|st|road|rd|avenue|ave|lane|ln|drive|dr|close|crescent)\b", re.I), "a street address"),
    (re.compile(r"\b(device|advertising|account|user|customer)[\s_-]?id\b", re.I), "an identifier"),
]


# Asking Qloo to infer something about people: "Qloo results ... should not be used to infer a person's identity,
# sensitive traits, health, financial status, political views, or eligibility for housing, employment, credit, insurance"
# (kit docs/SAFE_USE.md). Refused when a text asks to infer (a verb) something sensitive (a topic) about people (a noun),
# or to decide someone's eligibility. A product for a health or money need is not refused: only inference about people.
INFER = re.compile(r"\b(infer\w*|predict\w*|guess\w*|identif\w+|determin\w+|find(?:ing)? out|figur\w* out|reveal\w*|profil\w+|deduc\w+|work out)\b", re.I)
PEOPLE = re.compile(r"\b(persons?|people|someone|somebody|individuals?|users?|customers?|employees?|applicants?|tenants?|voters?|neighbou?rs?|"
                    r"patients?|visitors?|followers?|students?|candidates?|my (?:friend|wife|husband|partner|boss|child)\w*|their|his|her|whose)\b", re.I)
SENSITIVE = re.compile(r"\b(health\w*|ill(?:ness)?|diseases?|diagnos\w*|diabet\w*|cancer|pregnan\w*|mental|depress\w*|disabilit\w*|hiv|"
                       r"financ\w*|income|salar\w*|debts?|credit ?scores?|default\w*|loans?|mortgages?|arrears|evict\w*|wealth\w*|poor|bankrupt\w*|politic\w*|votes?|voting|religio\w*|"
                       r"sexual\w*|gay|lesbian|transgender|ethnic\w*|race|racial|immigra\w*|citizenship|identity|identities|real names?)\b", re.I)
ELIGIBLE = re.compile(r"\b(eligib\w*|approve|reject|deny|screen\w*|decide who gets)\b.{0,60}\b(loans?|credit|housing|rent\w*|jobs?|hir\w+|"
                      r"employ\w*|insurance|mortgage\w*)\b", re.I)


def sensitive(text: str) -> str | None:
    """Why a text asks Qloo for what the kit forbids, or None."""
    if ELIGIBLE.search(text):
        return "it asks to decide someone's eligibility (housing, work, credit or insurance)"
    if INFER.search(text) and PEOPLE.search(text) and SENSITIVE.search(text):
        return "it asks to infer a person's health, finances, politics or identity"
    return None


class PersonalData(ValueError):
    """Refused before any Qloo call: the text looks like personal data."""


def problems(value, where: str = "input") -> list[str]:
    out: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            out += problems(v, f"{where}.{k}")
    elif isinstance(value, (list, tuple)):
        if len(value) > MAX_ITEMS:
            out.append(f"{where}: at most {MAX_ITEMS} items")
        for i, v in enumerate(value):
            out += problems(v, f"{where}[{i}]")
    elif isinstance(value, str):
        if SAFE.match(value) or WKT.match(value):      # a Qloo id or tag URN, an ISO date, a WKT area: not free text
            return out
        if len(value) > MAX_LEN and not where.endswith(("idea",)):
            out.append(f"{where}: at most {MAX_LEN} characters")
        scan = YEARS.sub(" ", value)
        for rx, what in PATTERNS:
            if rx.search(scan):
                out.append(f"{where} looks like {what}")
        why = sensitive(value)
        if why:
            out.append(f"{where}: {why}, which Knos refuses (Qloo describes aggregate taste, never a person)")
    return out


class Refused(ValueError):
    """Refused before any Qloo call: the idea is on Knos's published refuse list (knos.refuse, GET /api/refuse)."""


def _texts(value) -> list[str]:
    if isinstance(value, dict):
        return [t for v in value.values() for t in _texts(v)]
    if isinstance(value, (list, tuple)):
        return [t for v in value for t in _texts(v)]
    return [value] if isinstance(value, str) and not SAFE.match(value) else []


def check(value, where: str = "input") -> None:
    from knos import refuse
    no = refuse.refused(" ".join(_texts(value)))
    if no:
        raise Refused(f"Knos refuses this: {no[0]['why']} ('{no[0]['word']}'). The list is public: /api/refuse.")
    p = problems(value, where)
    if p:
        raise PersonalData("Knos sends no personal data to Qloo: " + "; ".join(p[:3])
                           + ". Name things you like (a brand, a film, a cuisine), not who you are.")


# ---- no email address in a stored record --------------------------------------------------------------------------------
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def scrub(value):
    """The value with every email address replaced by "Guest", and how many were replaced. Nothing else changes."""
    if isinstance(value, str):
        out, n = EMAIL.subn("Guest", value)
        return out, n
    if isinstance(value, dict):
        total, out = 0, {}
        for k, v in value.items():
            out[k], n = scrub(v)
            total += n
        return out, total
    if isinstance(value, list):
        total, out = 0, []
        for v in value:
            x, n = scrub(v)
            out.append(x)
            total += n
        return out, total
    return value, 0


def scrub_disk(root) -> int:
    """Every stored JSON record under the app's state folder, scrubbed in place. Returns the count of replacements
    (the values are never printed). A record of the valley store is saved through it, so its devnet copy is
    rewritten too."""
    import json
    from pathlib import Path

    from . import valley
    total = 0
    for f in Path(root).rglob("*.json"):
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        clean, n = scrub(obj)
        if not n:
            continue
        total += n
        rel = f.relative_to(root).parts
        if len(rel) == 3 and rel[0] == "valley" and isinstance(clean, dict):
            valley._save(rel[1], f.stem, clean)
        else:
            f.write_text(json.dumps(clean, indent=1, default=str), encoding="utf-8")
    return total
