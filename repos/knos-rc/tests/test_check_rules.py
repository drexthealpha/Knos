"""web/check_rules.js is the Agent PR Index's rules in the browser: the same patterns as scripts/agent_pr_ci.py, and
the same answers on the recorded pull requests of docs/agent_pr_ci.json (the 30 that docs/index_review.json read again
among them).

Each recorded pull request is turned back into what GitHub's REST API answers for its head commit (check runs, commit
statuses, check suites) and its description's claim line; Python's find_claim, verdict and is_testish_failure and the
JavaScript port read the same input, and every field must agree. No node: the pattern tests still run."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "web" / "check_rules.js"
sys.path.insert(0, str(ROOT / "scripts"))
import agent_pr_ci as py  # noqa: E402

RECORDED = json.loads((ROOT / "docs" / "agent_pr_ci.json").read_text(encoding="utf-8"))
REVIEWED = json.loads((ROOT / "docs" / "index_review.json").read_text(encoding="utf-8"))["prs"]

# descriptions the recorded lines do not cover: comments, a pasted prompt, boxes, boilerplate, other scripts and spaces
EXTRA_BODIES = [
    "<!-- tests pass -->\nNothing here.",
    "<details><summary>Original prompt</summary>\nmake sure all tests pass\n</details>\nDone.",
    "- [ ] All tests pass\n- [x] CI is green",
    "  1) [ ] tests pass",
    "> - [ ] tests pass",
    "**Your PR cannot be merged unless tests pass**\n- [x] tests pass",
    "Tests pass except one flaky case",
    "All unit tests passed ✅",
    "١٢ passed",
    "Ünïcode tests passing",
    "tests pass CI passes",
    "testsé pass",
    "the fail-safe path: tests pass",
    "`pytest -q` — all passed",
    "12/12 tests passed",
    "Tests don't pass yet",
    "CI: build #12 passing",
    "✅ " + "x" * 39 + " tests",
    "﻿tests pass﻿",
    "\x1ctests pass\x85",
    "tests pass " + "é" * 300,
    "",
]


def _body_of(rec: dict) -> str:
    return rec.get("claim_line") or ""


def _github(rec: dict) -> dict:
    """What GitHub answers at the head commit that the record describes: the failed checks by name (check runs, then
    failed commit statuses when the record counts fewer runs than failures), the other conclusions it saw, passing runs
    up to its count, the agent's own runs, and a check suite awaiting approval where it counted one."""
    failed, n_runs, n_st = list(rec.get("failed_checks") or []), rec.get("n_check_runs") or 0, rec.get("n_statuses") or 0
    as_runs, as_st = failed[:n_runs], failed[n_runs:]
    runs = [{"name": n, "status": "completed", "conclusion": "failure"} for n in as_runs]
    for c in rec.get("other_conclusions") or []:
        if c != "failure" and len(runs) < n_runs:
            runs.append({"name": f"job {c}", "status": "completed", "conclusion": c})
    if rec.get("class") == "pending" and len(runs) < n_runs:
        runs.append({"name": "job running", "status": "in_progress", "conclusion": None})
    while len(runs) < n_runs:
        runs.append({"name": f"job {len(runs)}", "status": "completed", "conclusion": "success"})
    runs += [{"name": " Copilot ", "status": "completed", "conclusion": "success"}] * (rec.get("n_agent_runs_excluded") or 0)
    statuses = [{"context": n, "state": "failure"} for n in as_st]
    pending_status = rec.get("class") == "pending" and not any(r["status"] != "completed" for r in runs)
    while len(statuses) < n_st:
        statuses.append({"context": f"status {len(statuses)}", "state": "pending" if pending_status else "success"})
        pending_status = False
    suites = [{"conclusion": "action_required"}] * (rec.get("awaiting_approval_suites") or 0)
    return {"runs": runs, "statuses": statuses, "suites": suites}


def _cases() -> list[dict]:
    cases = [{"key": f"{r['repo']}#{r['number']}", "body": _body_of(r), "record": r, **_github(r)} for r in RECORDED["prs"]]
    cases += [{"key": f"extra {i}", "body": b, "runs": [], "statuses": [], "suites": []} for i, b in enumerate(EXTRA_BODIES)]
    return cases


def _python(case: dict) -> dict:
    phrase, line = py.find_claim(case["body"])
    v = py.verdict(case["runs"], case["statuses"], case["suites"])
    names = [r["name"] for r in case["runs"] if r["conclusion"] in py.FAIL_CONCL and not py.AGENT_RUN_RE.match(r["name"].strip())]
    names += [s["context"] for s in case["statuses"] if s["state"] in ("failure", "error")]
    return {"claim": {"phrase": phrase, "line": line} if phrase else None, "verdict": v,
            "testish": py.is_testish_failure(v), "split": [bool(py.TESTISH_RE.search(n) and not py.ANCILLARY_RE.search(n)) for n in names]}


NODE = """
import { readFileSync } from "node:fs";
const r = await import(process.argv[1]);
const cases = JSON.parse(readFileSync(0, "utf8"));
const out = cases.map((c) => {
  const v = r.verdict(c.runs, c.statuses, c.suites);
  const names = c.runs.filter((x) => ["failure", "timed_out", "startup_failure"].includes(x.conclusion) && !r.AGENT_RUN_RE.test(x.name.trim()))
    .map((x) => x.name).concat(c.statuses.filter((s) => s.state === "failure" || s.state === "error").map((s) => s.context));
  return { claim: r.findClaim(c.body), verdict: v, testish: v.failed_checks.some(r.isTestish), split: names.map(r.isTestish),
    sentence: r.sentence(r.findClaim(c.body), v.class, r.byClass(v.failed_checks)) };
});
process.stdout.write(JSON.stringify(out));
"""


def _javascript(cases: list[dict]) -> list[dict]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    run = subprocess.run([node, "--input-type=module", "-e", NODE, RULES.as_uri()], input=json.dumps(cases),
                         capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_the_patterns_are_pythons_character_for_character():
    src = RULES.read_text(encoding="utf-8")
    for name, rx in (("CLAIM", py.CLAIM_RE), ("NONCLAIM", py.NONCLAIM_RE), ("BOILER", py._BOILER_RE),
                     ("AGENT_RUN", py.AGENT_RUN_RE), ("TESTISH", py.TESTISH_RE), ("ANCILLARY", py.ANCILLARY_RE)):
        m = re.search(rf"^  {name}: (.+),$", src, re.M)
        assert m, name
        # the one pattern written in two pieces (a backtick cannot sit in a String.raw): joined as JavaScript joins it
        pieces = re.findall(r'String\.raw`((?:[^`]|``)*)`|"((?:[^"\\]|\\.)*)"', m.group(1))
        text = "".join(a if a else json.loads(f'"{b}"') for a, b in pieces)
        assert text == rx.pattern, name
        assert rx.flags & re.I, name


def test_python_and_the_browser_agree_on_every_recorded_pull_request():
    cases = _cases()
    js = _javascript(cases)
    assert len(js) == len(cases) == len(RECORDED["prs"]) + len(EXTRA_BODIES)
    for case, got in zip(cases, js):
        want = _python(case)
        for k in ("claim", "verdict", "testish", "split"):
            assert got[k] == want[k], (case["key"], k, got[k], want[k])
        assert got["sentence"].endswith(".") and len(got["sentence"].split()) <= 12, got["sentence"]


def test_the_rebuilt_answers_reproduce_the_recorded_classes():
    """The fixtures are faithful: Python's verdict on them gives back each record's class and failed checks."""
    for case in _cases()[: len(RECORDED["prs"])]:
        v, rec = py.verdict(case["runs"], case["statuses"], case["suites"]), case["record"]
        assert v["class"] == rec["class"], case["key"]
        assert sorted(v["failed_checks"]) == sorted(rec["failed_checks"] or []), case["key"]


def test_the_thirty_reviewed_pull_requests_are_classed_as_the_review_recorded():
    by_key = {f"{c['repo']}#{c['number']}".lower(): c for c in RECORDED["prs"]}
    cases = {c["key"].lower(): c for c in _cases()}
    assert len(REVIEWED) == 30
    picked = [cases[r["pr"].lower()] for r in REVIEWED]
    js = _javascript(picked)
    for r, case, got in zip(REVIEWED, picked, js):
        rec = by_key[r["pr"].lower()]
        assert rec["claim_line"] == r["recorded"]["claim_line"], r["pr"]
        assert got["claim"] and got["claim"]["line"] == rec["claim_line"], r["pr"]
        assert got["verdict"]["class"] == "failed", r["pr"]
        assert got["testish"] is r["recorded"]["test_or_build_check_failed"], r["pr"]
        assert got["sentence"].startswith("Claims tests pass;"), r["pr"]


def test_the_page_in_a_browser_on_recorded_answers():
    """tests/web/check.mjs: the first verdict from a #check= link under 10 s on the Android profile, the answer's three
    parts, paste with no press, the pending state at once, GitHub's hourly limit said, words and widths."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path("/opt/pw-browsers").is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/pw-browsers"
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "check.mjs")], env=env, capture_output=True, text=True,
                         encoding="utf-8", timeout=170)
    if run.returncode == 0 and "\nSKIP " in "\n" + run.stdout:
        pytest.skip(run.stdout.split("SKIP ", 1)[1].strip())
    assert run.returncode == 0 and "all passed" in run.stdout, "\n".join(
        ln for ln in (run.stdout + run.stderr).splitlines() if not ln.startswith("ok"))
    for said in ("android: first verdict in", "paste: checked with no press", "GitHub's hourly limit is said"):
        assert said in run.stdout, said
