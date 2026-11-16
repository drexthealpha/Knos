"""The build check of LAWS UX U7.md R31 (line 365) on web/i18n/: every English message carries, for its translator, a
description of where it appears and what it does and a max_length; every placeholder of the English message appears
exactly once in each translation; no translation is longer than max_length, which is IBM's allowance for the English
length (U7 R5). Plural forms are held to CLDR by apps/wanted/tests/test_h3_pages.py."""

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
I18N = ROOT / "web" / "i18n"
CATS = ("zero", "one", "two", "few", "many", "other")
EN = json.loads((I18N / "en.json").read_text(encoding="utf-8"))["strings"]
OTHERS = {p.stem: json.loads(p.read_text(encoding="utf-8"))["strings"] for p in sorted(I18N.glob("*.json")) if p.stem != "en"}


def forms(v) -> list[str]:
    if isinstance(v, dict):
        return [v["text"]] if "text" in v else [v[c] for c in CATS if c in v]
    return [v]


def ibm(n: int) -> float:
    return 3 if n <= 10 else 2 if n <= 20 else 1.8 if n <= 30 else 1.6 if n <= 50 else 1.4 if n <= 70 else 1.3


def test_every_english_message_has_a_description_and_a_max_length():
    bad = [k for k, v in EN.items() if not (isinstance(v, dict) and isinstance(v.get("description"), str) and len(v["description"].split()) >= 5
                                            and isinstance(v.get("max_length"), int))]
    assert bad == []


def test_max_length_is_ibms_allowance_for_the_longest_english_form():
    want = {k: math.ceil(max(map(len, forms(v))) * ibm(max(map(len, forms(v))))) for k, v in EN.items()}
    assert {k: v["max_length"] for k, v in EN.items() if v["max_length"] != want[k]} == {}


def test_every_placeholder_once_and_no_translation_over_max_length():
    assert len(OTHERS) >= 9
    bad = []
    for lang, s in OTHERS.items():
        for k, v in EN.items():
            if k not in s:
                continue
            ph = re.findall(r"\{\w+\}", forms(v)[-1])
            for f in forms(s[k]):
                if any(f.count(p) != 1 for p in set(ph)):
                    bad.append(f"{lang} {k}: placeholders")
                if len(f) > v["max_length"]:
                    bad.append(f"{lang} {k}: {len(f)} > {v['max_length']}")
    assert bad == []
