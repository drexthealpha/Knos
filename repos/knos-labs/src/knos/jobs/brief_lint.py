"""Brief lint: what to fix in a brief before money goes into escrow. Warnings, never blocks.

A worker can only be held to what the brief says. A brief with nothing checkable gets judged on taste; a brief that
contradicts the buyer's own standing preferences gets one of them broken. This says so before posting.
"""

from __future__ import annotations

import re

from .market import Brief

UNITS = 1_000_000


def lint(brief: Brief, price_units: int, preferences: list[str] | None = None) -> list[str]:
    out: list[str] = []
    task = (brief.task or "").strip()
    if len(task.split()) < 6:
        out.append("The task is very short: say what done looks like, so a worker can't miss it.")
    checks = brief.checks or {}
    if brief.kind == "python" and not checks.get("tests"):
        out.append("Python job with no tests (--tests FILE): acceptance can't be checked before delivery.")
    if brief.kind in ("csv", "json") and "expected" not in checks:
        out.append(f"{brief.kind.upper()} job with no expected output (--expect FILE): give one if you know it.")
    if brief.kind in ("copy", "text") and not any(k in checks for k in ("must_include", "must_not_include",
                                                                         "max_words")):
        out.append("Nothing checkable: add --must-include, --must-not-include or --max-words.")
    if price_units < 50_000:
        out.append(f"{price_units / UNITS:g} USDC is below what most workers take (0.05 USDC).")
    if re.search(r"\b(asap|urgent|quickly)\b", task, re.I):
        out.append("Urgency words don't change the deadline: set --work instead.")
    from ..sibyl import contradicts
    for p in preferences or []:
        for sentence in re.split(r"(?<=[.!?])\s+", task):
            if sentence and contradicts(p, sentence):
                out.append(f"This brief may contradict your standing preference: \"{p}\"")
    for phrase in checks.get("must_include", []):
        if phrase.lower() in [x.lower() for x in checks.get("must_not_include", [])]:
            out.append(f"\"{phrase}\" is both required and forbidden.")
    return out
