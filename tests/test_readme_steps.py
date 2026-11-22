"""README.md is written for a machine reader (L27): every control a step names exists on the site, the eval's interval
is computed from the locked test, and the lines the NEAR HACKATHON rules ask for stay while judging is open."""
from __future__ import annotations

import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")

# where a control's label can come from: the site's pages, scripts and strings, the page builders and the app's pages
SOURCES = [*ROOT.glob("web/**/*.html"), *ROOT.glob("web/**/*.js"), *ROOT.glob("web/i18n/*.json"),
           *ROOT.glob("near/web/**/*.html"), *ROOT.glob("near/web/**/*.js"), *ROOT.glob("scripts/site_*.py"),
           *ROOT.glob("apps/wanted/knos_wanted/*.py")]


def steps() -> list[str]:
    """The numbered steps of every "Judge it" list, each joined into one line."""
    out: list[str] = []
    for part in README.split("### Judge it")[1:]:
        body = part.split("\n### ", 1)[0].split("\n## ", 1)[0]
        cur = ""
        for line in body.splitlines():
            if re.match(r"\d+\. ", line):
                if cur:
                    out.append(cur)
                cur = line
            elif cur and line.startswith("   "):
                cur += " " + line.strip()
            elif cur and not line.strip():
                continue
        if cur:
            out.append(cur)
    return out


def labels() -> list[str]:
    return sorted({m for s in steps() for m in re.findall(r"\*\*([^*]+)\*\*", s)})


def pattern(label: str) -> re.Pattern:
    """A label as its source writes it: a number in it may be a template slot (${n}, {amount})."""
    parts = re.split(r"(\d+)", label)
    rx = "".join(r"(?:\d+|\$\{[^}]*\}|\{[a-z_]+\})" if p.isdigit() else re.escape(p).replace("'", "['’]")
                 for p in parts)
    return re.compile(rx)


def test_the_steps_name_controls():
    found = labels()
    assert len(steps()) >= 6, steps()
    assert {"Sample question", "Run the check yourself", "Run the check with 10 test dollars", "Check"} <= set(found), found


def test_every_named_control_exists_on_the_site():
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in SOURCES)
    missing = [lab for lab in labels() if not pattern(lab).search(text)]
    assert not missing, f"README steps name controls no page has: {missing}"


def test_no_step_names_the_retired_controls():
    joined = "\n".join(steps())
    for gone in ("Prove the same claim again", "Run the check with 10 test USDC", "Prove it yourself"):
        assert gone not in joined


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    p = k / n
    mid = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return mid - half, mid + half


def test_the_eval_interval_comes_from_the_locked_test():
    src = (ROOT / "near/agents/job/test_limit3.py").read_text(encoding="utf-8")
    body = src.split("CASES = [", 1)[1]
    n = len(re.findall(r"(?m)^    \(\"", body.split("\n]", 1)[0]))
    assert n == 14
    lo, hi = wilson(n, n)
    line = f"{n} of {n} pass (95% Wilson interval {math.floor(lo * 100)}% to {round(hi * 100)}%)"
    assert line in README, line
    assert f"{n} known-answer cases" in README


def test_the_near_entry_keeps_what_the_rules_ask_for():
    entry = README.split("<!-- entry:near -->", 1)[1].split("<!-- /entry:near -->", 1)[0]
    for must in ("https://x.com/getknos/status/2121724184380182623",                 # the public post (rule 3)
                 "compare/pre-hackathon...hackathon-submission",                     # the diff (Q-003)
                 "**Libraries.**", "**AI-written code.**",                          # Q-005
                 "**Built before, on another chain.**",                              # Q-002
                 "### Judge it in 2 minutes"):                                       # do X - see Y steps
        assert must in entry, must
    head = README.split("<!-- entry:near -->", 1)[0]
    assert "near/web/knos-near.mp4" in head, "the video link sits above the entries"
    assert "Knos keeps 1 part in 10" in entry and "(10%)" in entry
