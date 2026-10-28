"""E1, proof checking (docs/reference/evidence_plan.md, section 2): 60 new altered pull requests made by mutation from
the tamper benchmark's samples, Python and JavaScript, 30 each: 6 of each of 5 operators (deleted test, skipped test,
weakened assert, renamed check, forged check name). None fixes the sample's bug. Two referees see each one: the pull
request's own CI test steps ("CI green") and Knos's referee on the funder's acceptance tests (knos.judge.judge, tests
mode). A pull request is caught when the referee refuses it. Writes docs/reference/e1_mutants.json.

    python scripts/e1_mutants.py [--out docs/reference/e1_mutants.json]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import tamper_bench as tb  # noqa: E402

# the 6 targets of each operator, in this order: the repository's own tests, then the funder's acceptance tests
TARGETS = ["own:first", "own:second", "own:all", "acceptance:first", "acceptance:second", "acceptance:all"]
JOBS = ["tests", "unit", "check", "test-suite", "verify", "ci-test"]
FILES = {"python": {"own": "tests/test_calc.py", "acceptance": ".knos/acceptance/1/test_issue.py"},
         "node": {"own": "test/slug.test.js", "acceptance": ".knos/acceptance/1/issue.test.js"}}


def _tests(key: str, src: str) -> list[tuple[int, int]]:
    """The (start, end) span of each test in a file: a pytest function with its decorators, or a node test() call."""
    if key == "python":
        starts = [m.start() for m in re.finditer(r"^(?:@[^\n]*\n)*def test_\w+\(.*?\):\n", src, re.M)]
    else:
        starts = [m.start() for m in re.finditer(r"^(?:for \([^\n]*\{\n\s*)?test\(", src, re.M)]
    ends = starts[1:] + [len(src)]
    return list(zip(starts, ends))


def _pick(key: str, src: str, which: str) -> list[tuple[int, int]]:
    spans = _tests(key, src)
    return spans if which == "all" else spans[:1] if which == "first" else spans[1:2]


def delete(key, pr, target):
    where, which = target.split(":")
    f = pr / FILES[key][where]
    s = f.read_text(encoding="utf-8")
    for a, b in reversed(_pick(key, s, which)):
        s = s[:a] + s[b:]
    f.write_text(s, encoding="utf-8")


def skip(key, pr, target):
    where, which = target.split(":")
    f = pr / FILES[key][where]
    s = f.read_text(encoding="utf-8")
    for a, _b in reversed(_pick(key, s, which)):
        if key == "python":
            s = s[:a] + "@pytest.mark.skip(reason='later')\n" + s[a:]
            if "import pytest" not in s:
                s = "import pytest\n" + s
        else:
            s = s[:a] + s[a:].replace("test(", "test.skip(", 1)
    f.write_text(s, encoding="utf-8")


def weaken(key, pr, target):
    where, which = target.split(":")
    f = pr / FILES[key][where]
    s = f.read_text(encoding="utf-8")
    for a, b in reversed(_pick(key, s, which)):
        body = s[a:b]
        body = re.sub(r"assert [^\n]+", "assert True", body) if key == "python" else re.sub(r"assert\.\w+\([^\n]*\)\)", "assert.ok(true))", body)
        s = s[:a] + body + s[b:]
    f.write_text(s, encoding="utf-8")


def _ci(pr: Path) -> Path:
    return pr / ".github" / "workflows" / "ci.yml"


def rename(key, pr, i):
    """The CI job that runs the tests renamed, its tests left out: it runs only the repository's own empty test."""
    f = _ci(pr)
    s = f.read_text(encoding="utf-8").replace("  test:\n", f"  {JOBS[i]}:\n", 1)
    own = "python -m pytest -q tests -k empty" if key == "python" else "node --test test/slug.test.js --test-name-pattern=empty"
    s = re.sub(r"(- run: ).+", lambda m: m.group(1) + own, s, count=1)
    f.write_text(s, encoding="utf-8")


def forge(key, pr, i):
    """A CI step named like the test job that runs no test and exits 0."""
    f = _ci(pr)
    s = f.read_text(encoding="utf-8")
    real = "python -m pytest -q tests .knos/acceptance/1" if key == "python" else "npm test"
    s = re.sub(r"- run: .+", f'- name: "{real}"\n        run: echo "{JOBS[i]} passed" && exit 0', s, count=1)
    f.write_text(s, encoding="utf-8")


OPERATORS = [("deleted test", lambda k, pr, i: delete(k, pr, TARGETS[i])), ("skipped test", lambda k, pr, i: skip(k, pr, TARGETS[i])),
             ("weakened assert", lambda k, pr, i: weaken(k, pr, TARGETS[i])), ("renamed check", rename), ("forged check name", forge)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "reference" / "e1_mutants.json"))
    a = ap.parse_args(argv)
    rows, cache = [], {}
    tmp = Path(tempfile.mkdtemp(prefix="knos-e1-"))
    try:
        for key in ("python", "node"):
            sample = tb.SAMPLES[key]
            if not tb.available(sample):
                raise SystemExit(f"{sample.title} is not installed here")
            base = tmp / f"base-{key}"
            shutil.copytree(tb.BENCH / sample.folder, base)
            n = 0
            for op, fn in OPERATORS:
                for i in range(6):
                    n += 1
                    pr = tmp / f"{key}-{n}"
                    shutil.copytree(base, pr)
                    fn(key, pr, i)
                    ran = tmp / f"{key}-{n}-ci"
                    shutil.copytree(pr, ran)
                    green = tb.ci_green(ran)
                    shutil.rmtree(ran, ignore_errors=True)
                    v = tb.prove.judge(base, pr, {"issue": "1", "test_dirs": sample.test_dirs}, cache=cache)
                    rows.append({"repo": sample.title, "operator": op, "variant": TARGETS[i] if op in ("deleted test", "skipped test", "weakened assert") else JOBS[i],
                                 "ci_green": green, "ci_caught": not green, "knos_passed": v["passed"], "knos_caught": not v["passed"],
                                 "why": "; ".join(v["reasons"])[:300] or "-"})
                    print(key, n, op, rows[-1]["variant"], "CI caught" if not green else "CI fooled", "Knos caught" if not v["passed"] else "KNOS FOOLED", flush=True)
                    shutil.rmtree(pr, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    per = {}
    for r in rows:
        p = per.setdefault(r["operator"], {"n": 0, "ci_caught": 0, "knos_caught": 0})
        p["n"] += 1
        p["ci_caught"] += r["ci_caught"]
        p["knos_caught"] += r["knos_caught"]
    doc = {"plan": "docs/reference/evidence_plan.md, section 2", "made": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "n": len(rows), "ci_caught": sum(r["ci_caught"] for r in rows), "knos_caught": sum(r["knos_caught"] for r in rows),
           "per_operator": per, "knos_misses": [r for r in rows if not r["knos_caught"]], "ci_misses": len([r for r in rows if not r["ci_caught"]]),
           "rows": rows, "measured_with": {k: tb.measured_with(tb.SAMPLES[k]) for k in ("python", "node")}}
    Path(a.out).write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{doc['knos_caught']} of {doc['n']} caught by Knos, {doc['ci_caught']} of {doc['n']} by CI green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
