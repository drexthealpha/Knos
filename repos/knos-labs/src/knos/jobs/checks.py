"""A brief's acceptance checks, run by the worker before delivering (and by `knos jobs get` for the buyer).

    python  {"tests": "<code that imports `solution` and asserts>"}   runs in a fresh interpreter, 30 s limit
    csv     {"expected": "<exact csv>"}                               compared line by line, trailing spaces ignored
    json    {"expected": {...}}                                       compared as parsed JSON
    copy    {"must_include": [...], "must_not_include": [...], "max_words": n}
    text    the same rules as copy

Preferences the buyer stated before (from Sibyl memory, with consent) are checked the same way: a preference such as
"never use exclamation marks" becomes a must_not_include rule. Passing checks is necessary, not sufficient: the buyer
still accepts or rejects.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def _lines(s: str) -> list[str]:
    return [ln.rstrip() for ln in s.strip().splitlines()]


def run(kind: str, checks: dict | None, deliverable: str, preferences: list[str] | None = None) -> tuple[bool, str]:
    checks = checks or {}
    ok, why = _kind(kind, checks, deliverable)
    if not ok:
        return ok, why
    for p in preferences or []:
        ok, why = preference_holds(p, deliverable)
        if not ok:
            return ok, why
    return True, "all checks passed"


def _kind(kind: str, checks: dict, d: str) -> tuple[bool, str]:
    if kind == "python" and checks.get("tests"):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "solution.py").write_text(d, encoding="utf-8")
            Path(tmp, "check_solution.py").write_text(checks["tests"], encoding="utf-8")
            try:
                got = subprocess.run([sys.executable, "-E", "-s", "check_solution.py"], cwd=tmp, capture_output=True,
                                     text=True, timeout=30)
            except subprocess.TimeoutExpired:
                return False, "tests timed out"
            return got.returncode == 0, (got.stderr or got.stdout)[-500:] or "tests passed"
    if kind == "csv" and "expected" in checks:
        return _lines(d) == _lines(checks["expected"]), "csv differs from the expected output"
    if kind == "json" and "expected" in checks:
        try:
            return json.loads(d) == checks["expected"], "json differs from the expected output"
        except ValueError:
            return False, "not valid json"
    for phrase in checks.get("must_include", []):
        if phrase.lower() not in d.lower():
            return False, f"missing: {phrase}"
    for phrase in checks.get("must_not_include", []):
        if phrase.lower() in d.lower():
            return False, f"must not include: {phrase}"
    if checks.get("max_words") and len(d.split()) > int(checks["max_words"]):
        return False, "too long"
    return True, "checks passed"


_SIGN_OFF = re.compile(r"sign (?:off|it) with\s*[\"'“]?(.+?)[\"'”]?\s*$", re.I)


def preference_holds(pref: str, d: str) -> tuple[bool, str]:
    """The machine-checkable standing preferences; anything else is left to the buyer."""
    p = pref.strip()
    low = p.lower()
    if "exclamation" in low and ("never" in low or "no " in low or "don't" in low):
        return ("!" not in d), "uses an exclamation mark"
    m = _SIGN_OFF.search(p)
    if m:
        return d.rstrip().endswith(m.group(1).strip().rstrip(".")), f"does not sign off with {m.group(1)}"
    if "camelcase" in low.replace(" ", "") and "key" in low:
        try:
            keys = _keys(json.loads(d))
        except ValueError:
            return True, ""
        bad = [k for k in keys if "_" in k or (k and k[0].isupper())]
        return (not bad), f"keys not camelCase: {bad[:3]}"
    if "snake_case" in low and "key" in low:
        try:
            keys = _keys(json.loads(d))
        except ValueError:
            return True, ""
        bad = [k for k in keys if k != k.lower() or "-" in k]
        return (not bad), f"keys not snake_case: {bad[:3]}"
    return True, ""


def _keys(obj) -> list[str]:
    if isinstance(obj, dict):
        return list(obj) + [k for v in obj.values() for k in _keys(v)]
    if isinstance(obj, list):
        return [k for v in obj for k in _keys(v)]
    return []
