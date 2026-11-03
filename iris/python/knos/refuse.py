"""What Knos will not fund (the published refuse list, inside the Ready check).

A brief is refused, never "Not ready but fixable", when its words name one of these. The list is public
(docs/reference/REFUSE.md is generated from it) so a refusal is automatic and anyone can audit it.

    weapons                 arms, munitions, explosives for harm
    military_first          a product whose first customer or use is military
    dangerous_pathogens     biological or chemical agents of mass harm, or work that makes a pathogen more dangerous
    sanctioned_places       places under comprehensive US sanctions (OFAC country programs, read 23 Oct 2026):
                            Cuba, Iran, North Korea, and the Crimea, so-called Donetsk and Luhansk regions of Ukraine

Matching is on whole words and phrases; a few harmless phrases that share a word are allowed ("bath bomb", "glue gun").
This is a first gate, not a legal review: every real payment still screens its parties against OFAC's lists.
"""
from __future__ import annotations

import re

AS_OF = "2026-10-23"
SOURCE = "https://ofac.treasury.gov/sanctions-programs-and-country-information"

REFUSE: dict[str, tuple[str, ...]] = {
    "weapons": ("weapon", "weapons", "weaponize", "weaponized", "firearm", "firearms", "gun", "guns", "rifle", "rifles",
                "pistol", "ammunition", "munition", "munitions", "explosives", "warhead", "warheads", "bomb", "bombs",
                "grenade", "grenades", "landmine", "landmines", "silencer", "suppressor for rifles"),
    "military_first": ("military", "militaries", "defense contractor", "defence contractor", "battlefield", "warfighter",
                       "warfighters", "combat", "soldier", "soldiers", "army", "armed forces", "missile", "missiles",
                       "kill chain", "targeting system", "drone strike", "drone strikes", "loitering munition"),
    "dangerous_pathogens": ("bioweapon", "bioweapons", "biological weapon", "biological weapons", "chemical weapon",
                            "chemical weapons", "gain of function", "gain-of-function", "enhanced pathogen",
                            "enhance a pathogen", "pandemic pathogen", "select agent", "anthrax", "smallpox", "ebola",
                            "marburg", "botulinum toxin", "ricin", "yersinia pestis", "nerve agent", "sarin", "vx gas",
                            "novichok", "pathogen transmissibility", "increase transmissibility"),
    "sanctioned_places": ("cuba", "iran", "north korea", "dprk", "pyongyang", "tehran", "havana", "crimea", "sevastopol",
                          "donetsk", "luhansk", "lugansk"),
}
# harmless phrases that contain a refused word
ALLOWED = ("bath bomb", "bath bombs", "photo bomb", "glue gun", "heat gun", "spray gun", "nail gun", "staple gun",
           "caulk gun", "massage gun", "water gun", "military-grade encryption", "combat sports", "combat sport",
           "salvation army", "army green", "smoke bomb", "army knife")

WHY = {"weapons": "Knos does not fund weapons",
       "military_first": "Knos does not fund products whose first customer or use is military",
       "dangerous_pathogens": "Knos does not fund dangerous pathogens or chemical agents, or work that makes them more harmful",
       "sanctioned_places": "Knos does not fund work in places under comprehensive US sanctions (OFAC)"}

_PATTERNS = {cat: re.compile(r"(?<![\w-])(" + "|".join(sorted((re.escape(w) for w in words), key=len, reverse=True)) + r")(?![\w-])", re.I)
             for cat, words in REFUSE.items()}
_ALLOWED = re.compile(r"(?<![\w-])(" + "|".join(re.escape(w) for w in ALLOWED) + r")(?![\w-])", re.I)


def refused(text: str) -> list[dict]:
    """Each refused category the text names: [{category, word, why}], empty when nothing is refused."""
    t = _ALLOWED.sub(" ", str(text or ""))
    out = []
    for cat, pat in _PATTERNS.items():
        m = pat.search(t)
        if m:
            out.append({"category": cat, "word": m.group(1).lower(), "why": WHY[cat]})
    return out


def brief_text(brief: dict) -> str:
    """Every word a brief says: its title, summary and place, and each milestone's name, target and verifier."""
    if not isinstance(brief, dict):
        return ""
    parts = [str(brief.get(k) or "") for k in ("title", "summary", "about", "idea", "place", "market", "country")]
    for m in brief.get("milestones") or []:
        if isinstance(m, dict):
            parts += [str(m.get(k) or "") for k in ("name", "target", "key")]
            v = m.get("verifier")
            if isinstance(v, dict):
                parts += [str(x) for x in v.values() if isinstance(x, str)]
    return " \n ".join(parts)


def public() -> dict:
    """The list as published (GET /api/refuse and docs/reference/REFUSE.md)."""
    return {"as_of": AS_OF, "categories": {c: {"why": WHY[c], "words": list(w)} for c, w in REFUSE.items()},
            "allowed_phrases": list(ALLOWED), "sanctions_source": SOURCE,
            "rule": "a brief that names any of these is refused by the Ready check; every real payment still screens its parties"}
