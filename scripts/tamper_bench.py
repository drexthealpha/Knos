"""Tamper benchmark: test-weakening pull requests against three sample repositories, each judged three ways.

    python scripts/tamper_bench.py [--out docs/TAMPER.md] [--only python|node|ruby]
    python scripts/tamper_bench.py --real        # only the six real-behaviour tasks: rewrites their block of docs/TAMPER.md
    python scripts/tamper_bench.py --accept      # only the three non-code tasks (scripts/acceptance_examples.py), same
    python scripts/tamper_bench.py --escape      # only the five escapes from where the submission runs, same

The samples (tests/bench_tamper/) are the same small project with the same bug, in Python (pytest), JavaScript
(node:test) and Ruby (minitest), and each has its own 21 attacks: the same 21 ideas, each as that language's tools
would meet it (attacks.py, attacks_node.py, attacks_ruby.py).

"CI green" runs the PR's own CI test steps (the `run:` lines of its .github/workflows/ci.yml) in the PR's tree and
passes on exit 0, as a branch protection rule would. "Knos, tests" runs knos.judge.judge(base, pr, cfg) on the
acceptance bundle written in the repository's language (.knos/acceptance/1), the same function prove.yml's check job
runs. "Knos, black box" runs it on the black-box bundle (.knos/acceptance/2), whose check never loads the pull
request's code. An attack "fools" a judge when the judge passes it although slugify was not fixed.

Six more tasks (tests/bench_tamper/real_tasks.py) are taken from behaviour that real open-source code defines (Python's
urllib.parse.urljoin, packaging.version, csv.Sniffer, configparser, datetime.fromisoformat, fnmatch) and checked black
box against that code on generated inputs. Each has an honest fix, a constant-returning stub and the attacks above that
apply (attacks_real.py), judged by CI green and by Knos's black box. And three tasks that are not code
(examples/acceptance/) are run through `knos proof judge` by scripts/acceptance_examples.py. docs/TAMPER.md reports both.

Five escapes (ESCAPES) are not about the verdict: each is something a submission does to the machine that judges it,
tried in each place a submission can run (the judge's machine with no sandbox, its sandbox, a container of a pinned
image). A place that cannot be set up here is reported as "not run here", with no number.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "tests" / "bench_tamper"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(ROOT / "scripts"))

from knos import judge as prove  # noqa: E402


class Sample(NamedTuple):
    key: str
    title: str          # the language and its test runner
    folder: str         # under tests/bench_tamper
    attacks: str        # the module with CONTROL, ATTACKS and OUT_OF_SCOPE
    test_dirs: list     # what the base's .knos/proof.toml says
    needs: tuple        # the commands its CI and its runner use
    versions: tuple     # (name, argv that prints its version): what the report was measured with


SAMPLES = {s.key: s for s in (
    Sample("python", "Python, pytest", "sample", "attacks.py", ["tests"], (),
           (("Python", [sys.executable, "-c", "import platform; print(platform.python_version())"]),
            ("pytest", [sys.executable, "-c", "import pytest; print(pytest.__version__)"]))),
    Sample("node", "JavaScript, node:test", "sample_node", "attacks_node.py", ["test"], ("node", "npm"),
           (("Node", ["node", "-p", "process.versions.node"]), ("npm", ["npm", "--version"]))),
    Sample("ruby", "Ruby, minitest", "sample_ruby", "attacks_ruby.py", ["test"], ("ruby",),
           (("Ruby", ["ruby", "-e", "print RUBY_VERSION"]), ("minitest", ["ruby", "-e", 'require "minitest"; print Minitest::VERSION']))),
)}


def available(sample: Sample) -> bool:
    """Whether this machine can run that sample at all (its language is installed)."""
    return all(shutil.which(tool) for tool in sample.needs)


def measured_with(sample: Sample) -> str:
    """"Python 3.12.3 and pytest 8.4.2": the versions on this machine. What plain CI lets through depends on them."""
    def version(argv: list) -> str:
        try:
            return subprocess.run(argv, capture_output=True, text=True, timeout=60).stdout.strip() or "?"
        except (OSError, subprocess.SubprocessError):
            return "?"
    return " and ".join(f"{name} {version(argv)}" for name, argv in sample.versions)


def _attacks(sample: Sample):
    spec = importlib.util.spec_from_file_location(f"tamper_{sample.attacks[:-3]}", BENCH / sample.attacks)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ci_green(pr: Path) -> bool:
    wf = pr / ".github" / "workflows" / "ci.yml"
    if not wf.is_file():
        return True   # no CI step: nothing fails
    runs = re.findall(r"^\s*-\s*run:\s*(.+)$", wf.read_text(encoding="utf-8"), re.M)
    for cmd in runs:
        cmd = re.sub(r"^python\b", lambda _: f'"{sys.executable}"', cmd.strip())
        env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
               "NPM_CONFIG_UPDATE_NOTIFIER": "false", "NPM_CONFIG_FUND": "false", "NPM_CONFIG_AUDIT": "false"}
        r = subprocess.run(cmd, shell=True, cwd=pr, env=env, capture_output=True, timeout=300)
        if r.returncode != 0:
            return False
    return True


def one(sample: Sample, base: Path, tmp: Path, i: int, name: str, fn, cache: dict) -> dict:
    pr = tmp / f"pr{i}"
    shutil.copytree(base, pr)
    fn(pr)
    green = ci_green(pr)
    shutil.rmtree(pr / "__pycache__", ignore_errors=True)
    v = prove.judge(base, pr, {"issue": "1", "test_dirs": sample.test_dirs}, cache=cache)
    out = {"name": name, "ci": green, "knos": v["passed"], "why": "; ".join(v["reasons"]) or "-", "box": None}
    if BLACKBOX:
        b = prove.judge(base, pr, {"issue": "2", "test_dirs": sample.test_dirs}, cache=cache)
        out.update({"box": b["passed"], "box_why": "; ".join(b["reasons"]) or "-"})
    return out


BLACKBOX = os.name != "nt"   # the black-box check reaches the tree through a shell wrapper


def run(key: str = "python") -> tuple[dict, list[dict]]:
    """(the control's row, the attacks' rows) for one sample repository."""
    sample = SAMPLES[key]
    mod = _attacks(sample)
    with tempfile.TemporaryDirectory(prefix="knos-tamper-") as t:
        tmp = Path(t)
        base = tmp / "base"
        shutil.copytree(BENCH / sample.folder, base, ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
        jobs = [mod.CONTROL, *mod.ATTACKS]
        cache: dict = {}
        first = one(sample, base, tmp, 0, *jobs[0], cache)   # the control also runs the base side once, for every PR
        with ThreadPoolExecutor(max_workers=8) as ex:
            got = [first, *ex.map(lambda a: one(sample, base, tmp, a[0], *a[1], cache), list(enumerate(jobs))[1:])]
    for g in got:
        g["out_of_scope"] = g["name"] in mod.OUT_OF_SCOPE     # no in-process test run can stop it
        g["gap"] = g["name"] in getattr(mod, "GAP", ())        # this language's runner misses it; another catches it
    return got[0], got[1:]


def _fooled(rows: list[dict]) -> tuple[int, int, int]:
    return sum(r["ci"] for r in rows), sum(r["knos"] for r in rows), sum(bool(r["box"]) for r in rows)


_LISTS = re.compile(r"^(pr: acceptance checks[^:]*|pass-to-pass broken): (.+)$")


def _stable(why: str) -> str:
    """The judge lists checks in the order the runner ran them, and minitest runs them in a random order. Each list
    is sorted here, so the same verdict prints the same line every time."""
    def one(reason: str) -> str:
        m = _LISTS.match(reason)
        return f"{m.group(1)}: {', '.join(sorted(m.group(2).split(', ')))}" if m else reason
    return "; ".join(one(r) for r in why.split("; "))


def section(sample: Sample, control: dict, rows: list[dict]) -> list[str]:
    n = len(rows)
    ci, kn, bx = _fooled(rows)
    yes = lambda b: "n/a" if b is None else "PASS (fooled)" if b else "fail"  # noqa: E731
    out = [f"## {sample.title}", "",
           f"tests/bench_tamper/{sample.folder}, attacked by tests/bench_tamper/{sample.attacks}. "
           f"Measured with {measured_with(sample)}.", "",
           f"**CI green fooled {ci}/{n}. Knos, tests: fooled {kn}/{n}. Knos, black box: fooled {bx}/{n}.**", "",
           f"Control (the honest fix): CI green {'passes' if control['ci'] else 'fails'}, "
           f"Knos, tests {'passes' if control['knos'] else 'fails'}, "
           f"Knos, black box {'passes' if control['box'] else 'n/a' if control['box'] is None else 'fails'}.", "",
           "| # | attack | CI green | Knos, tests | Knos, black box | Knos's reason (tests) |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        why = _stable(r["why"]).replace("|", "\\|")
        if len(why) > 120:
            why = why[:117] + "..."
        out.append(f"| {i} | {r['name']} | {yes(r['ci'])} | {yes(r['knos'])} | {yes(r['box'])} | {why} |")
    note = getattr(_attacks(sample), "NOTE", "")
    return out + ["", *([note, ""] if note else [])]


def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def render(results: dict[str, tuple[dict, list[dict]]], extra: list[str] | None = None) -> str:
    """docs/TAMPER.md from {sample key: (control, rows)}, in SAMPLES' order, and `extra` (the blocks for the real-behaviour
    and the non-code tasks) after it."""
    done = [(SAMPLES[k], *results[k]) for k in SAMPLES if k in results]
    total = [r for _, _, rows in done for r in rows]
    ci, kn, bx = _fooled(total)
    count = {1: "One sample repository", 2: "Two sample repositories", 3: "Three sample repositories"}[len(done)]
    out = ["# Tamper benchmark", "",
           "Generated by `python scripts/tamper_bench.py`; checked by tests/test_tamper_bench.py.", "",
           f"{count} (tests/bench_tamper/): the same small project, in {_and([s.title.split(',')[0] for s, _, _ in done])},",
           "with one bug: `slugify` keeps punctuation. Each attack is a pull request that does NOT fix the bug and instead",
           "weakens what judges it: the same 21 ideas for each repository, each as that language's tools would meet it.",
           "Three judges see each one:", "",
           "- **CI green**: the PR's own CI test steps (its `.github/workflows/ci.yml`), run in the PR tree; pass on exit 0.",
           "- **Knos, tests**: `knos.judge.judge` on the funder's acceptance tests `.knos/acceptance/1/`, written in the",
           "  repository's language: protected paths, overlay of the base's tests and configuration, a random sentinel test",
           "  and a failing canary, fail-to-pass, pass-to-pass and test count. The code under test shares a process with",
           "  the test runner.",
           "- **Knos, black box**: `knos.judge.judge` on the funder's black-box bundle `.knos/acceptance/2/`: the check",
           "  runs as the judge and never loads the pull request's code; it asks that code for answers through the",
           "  sandbox and compares them with its own reference on generated inputs.", "",
           "| repository | attacks | CI green fooled | Knos, tests fooled | Knos, black box fooled |", "|---|---|---|---|---|"]
    for sample, _, rows in done:
        a, b, c = _fooled(rows)
        out.append(f"| {sample.title} | {len(rows)} | {a} | {b} | {c} |")
    out += [f"| **all** | **{len(total)}** | **{ci}** | **{kn}** | **{bx}** |", ""]
    for sample, control, rows in done:
        out += section(sample, control, rows)
    fooled = [r for r in total if r["knos"]]
    gaps = [r for r in fooled if r.get("gap")]
    out += [f"Of the {len(fooled)} that fool an in-process test run, {len(fooled) - len(gaps)} are limits of running tests "
            "at all, not bugs to patch:",
            "a stub that returns the expected constants passes any check made of fixed examples, and code that shares",
            "a process with the test runner can stop the acceptance bodies from running, or from asserting anything,",
            "while leaving every other test alone."
            + (f" The other {'one is a gap' if len(gaps) == 1 else f'{len(gaps)} are gaps'} in one runner that the "
               "others do not have: see the" if gaps else ""),
            *(["note under that repository's table."] if gaps else []),
            "The black-box check has none of these weaknesses, because the pull request's code is never in the process",
            "that decides.",
            "A bounty paid without a merge has no second look: when its check passes it is paid, with no review window",
            "and no veto. So payment without a merge (tests mode) is offered only when the acceptance bundle is black-box:",
            "the submission runs as a separate process and only its output is compared. Everything else is funded in merge",
            "mode, which pays on a maintainer's merge.", "", *(extra or [])]
    return "\n".join(out)

# ---- the six real-behaviour tasks ----------------------------------------------------------------------------------------

def _real_modules():
    import attacks_real
    import real_tasks
    return real_tasks, attacks_real


def one_real(task, base: Path, tmp: Path, i: int, name: str, fn, cache: dict) -> dict:
    """One attack on one task's repository, judged by CI green and by Knos's black box."""
    pr = tmp / f"pr{i}"
    shutil.copytree(base, pr)
    fn(pr, task, base)
    green = ci_green(pr)
    shutil.rmtree(pr / "__pycache__", ignore_errors=True)
    v = prove.judge(base, pr, {"issue": "1", "test_dirs": ["tests"]}, cache=cache)
    return {"name": name, "ci": green, "box": v["passed"], "why": "; ".join(v["reasons"]) or "-"}


def run_real(key: str, only: list[str] | None = None, delegate: bool = True) -> dict:
    """{"control", "rows", "delegate", "intact"} for one real task: the honest fix, each attack (all of attacks_real.ATTACKS,
    or the ones named in `only`), the submission that hands the work to the real code (unless `delegate` is False), and
    whether the judge's base checkout still holds the bundle it started with."""
    R, A = _real_modules()
    task = R.TASKS[key]
    with tempfile.TemporaryDirectory(prefix="knos-real-") as t:
        tmp = Path(t)
        base = tmp / "base"
        R.materialise(task, base)
        before = prove.checks_hash(base / ".knos" / "acceptance" / "1")
        jobs = [A.CONTROL, *[a for a in A.ATTACKS if only is None or a[0] in only], *([A.DELIVERS] if delegate else [])]
        cache: dict = {}
        first = one_real(task, base, tmp, 0, *jobs[0], cache)
        with ThreadPoolExecutor(max_workers=4) as ex:
            got = [first, *ex.map(lambda a: one_real(task, base, tmp, a[0], *a[1], cache), list(enumerate(jobs))[1:])]
        intact = prove.checks_hash(base / ".knos" / "acceptance" / "1") == before
    return {"task": task, "control": got[0], "rows": got[1:len(got) - delegate], "delegate": got[-1] if delegate else None,
            "intact": intact}


def real_section(results: dict[str, dict]) -> list[str]:
    """The block of docs/TAMPER.md for the six real-behaviour tasks, from {task key: run_real(...)}."""
    rows = [r for got in results.values() for r in got["rows"]]
    n_tasks, n_attacks = len(results), len(next(iter(results.values()))["rows"])
    ci, kn = sum(r["ci"] for r in rows), sum(r["box"] for r in rows)
    false_accepts = [f"{got['task'].key}: {r['name']}" for got in results.values() for r in got["rows"] if r["box"]]
    false_refusals = [got["task"].key for got in results.values() if not got["control"]["box"]]
    yes = lambda b: "passes" if b else "fails"  # noqa: E731
    out = ["<!-- real:begin -->", "## Real open-source behaviour, six tasks", "",
           f"Six tasks taken from behaviour that real open-source code defines, with none of that code copied: "
           f"{', '.join(g['task'].title.split('(')[1].rstrip(')') for g in results.values())}. The sample repository of each "
           "(tests/bench_tamper/real_tasks.py) has a function that is naive: it passes the easy examples and fails the rest, "
           "so its CI is red. The black-box check calls the pull request's code once through the judge's sandbox and compares "
           "every answer with the real code's, on a few fixed inputs and 150 to 250 generated ones (new on every run). "
           f"Each task is attacked with the {n_attacks} ideas below (the ideas of the first table that apply to a repository "
           "like this one, plus a constant-returning stub, a stub that returns the visible examples' answers, a timeout and "
           "a write into the judge's base checkout), judged by CI green and by Knos's black box. "
           f"Measured with Python {sys.version.split()[0]} and pytest {_pytest_version()}.", "",
           "A judge is *fooled* when it passes a submission that did not fix the issue. A *false refusal* is the honest fix "
           "refused.", "",
           "| task | checked against | honest fix: CI green | honest fix: Knos black box | attacks | CI green fooled | Knos black box fooled |",
           "|---|---|---|---|---|---|---|"]
    for key, got in results.items():
        t = got["task"]
        a, b = sum(r["ci"] for r in got["rows"]), sum(r["box"] for r in got["rows"])
        out.append(f"| {t.key} | {t.title.split('(')[1].rstrip(')')} | {yes(got['control']['ci'])} | "
                   f"{yes(got['control']['box'])} | {len(got['rows'])} | {a} | {b} |")
    out += [f"| **all** | | | | **{len(rows)}** | **{ci}** | **{kn}** |", "",
            f"**False accepts: {'none' if not false_accepts else '; '.join(false_accepts)}. "
            f"False refusals: {'none' if not false_refusals else ', '.join(false_refusals)}.** "
            f"CI green was fooled by {ci} of {len(rows)} attacks. "
            + ("After every task the judge's base checkout still held the bundle it started with, so the attack that writes "
               "over it did not get through the sandbox." if all(g["intact"] for g in results.values()) else
               "THE JUDGE'S BASE CHECKOUT WAS CHANGED during: " + ", ".join(k for k, g in results.items() if not g["intact"]) + "."), "",
            "| # | attack | CI green fooled | Knos black box fooled |", "|---|---|---|---|"]
    for i in range(n_attacks):
        name = next(iter(results.values()))["rows"][i]["name"]
        a = [g["rows"][i]["ci"] for g in results.values()]
        b = [g["rows"][i]["box"] for g in results.values()]
        out.append(f"| {i + 1} | {name} | {sum(a)} of {n_tasks} | {sum(b)} of {n_tasks} |")
    deleg = [g["task"].key for g in results.values() if g["delegate"]["box"]]
    out += ["", f"One more submission is not counted as an attack: it hands the work to the real code the check compares "
                f"with (`from urllib.parse import urljoin as join`, and the like). Knos's black box accepted it for "
                f"{len(deleg)} of {n_tasks} tasks, and so it should: it has the behaviour that was asked for. A black-box "
                "check measures behaviour, not how it was reached; a buyer who wants an implementation of their own says "
                "so in the task, and no check of outputs can enforce it.",
            "<!-- real:end -->"]
    return out


def _pytest_version() -> str:
    try:
        import pytest
        return pytest.__version__
    except ImportError:
        return "?"


# ---- the three tasks that are not code -------------------------------------------------------------------------------

HONEST_DRAWS = 20     # the honest solution is judged this many times: a false refusal is the failure that costs a seller


def run_accept(repeat: int = 5) -> dict:
    import acceptance_examples as ex
    out = {}
    for task in ex.tasks():
        out[task] = ex.run(task, repeat=repeat)
        out[task]["honest"] = ex.run(task, only="honest", repeat=HONEST_DRAWS)["honest"]
    return out


def accept_section(results: dict, repeat: int) -> list[str]:
    """The block of docs/TAMPER.md for the three tasks that are not code, from run_accept()."""
    cheats = [(t, r) for t, got in results.items() for r in got["cheats"]]
    honest = [(t, r) for t, got in results.items() for r in got["honest"]]
    false_accepts = [f"{t}: {r['name']}" for t, r in cheats if r["accepts"]]
    false_refusals = [t for t, r in honest if r["accepts"] < HONEST_DRAWS]
    out = ["<!-- accept:begin -->", "## Tasks that are not code", "",
           "examples/acceptance/ holds three tasks a buyer can write with no code to point at, each as a black-box bundle "
           "(scripts/acceptance_examples.py runs them; tests/test_acceptance_examples.py runs every submission once): "
           "**clean-csv** (turn messy customer exports into one clean file; every cell must equal the clean table the messy "
           "file was made from), **summarise** (a one-line summary of an incident report; unigram F1 against the reference "
           "written in the bundle, mean at least 0.85 and 90% of reports at 0.70 or more) and **classify** (hold risky "
           "payments; accuracy at least 0.85 on a hidden set and on a fresh one). Each has the text a buyer would write "
           "(TASK.md), an honest solution, cheating submissions and near misses, and every submission goes through "
           f"`knos proof judge`, the command prove.yml runs. Each cheat and near miss was judged {repeat} times and each honest "
           f"solution {HONEST_DRAWS} times, with new generated inputs each time. The cheats: a constant answer, reading the answer file (the held-out set, in the submission's own tree, in "
           "the judge's other trees and in the judge's private copy), special-casing the visible examples, never finishing, "
           "writing outside the sandbox (over the bundle in the judge's base checkout), asking a service on the network, "
           "answer bytes that are not text, too many answers, and editing the bundle in the pull request.", "",
           "| task | honest solution accepted | cheats | cheats accepted | near misses | near misses accepted |",
           "|---|---|---|---|---|---|"]
    for task, got in results.items():
        h, c, m = got["honest"][0], got["cheats"], got["near_misses"]
        out.append(f"| {task} | {h['accepts']} of {HONEST_DRAWS} | {len(c)} | {sum(r['accepts'] for r in c)} of {len(c) * repeat} | "
                   f"{len(m)} | {sum(r['accepts'] for r in m)} of {len(m) * repeat} |")
    out += ["", f"**False accepts: {'none' if not false_accepts else '; '.join(false_accepts)}. "
                f"False refusals: {'none' if not false_refusals else ', '.join(false_refusals)}.**", "",
            "| task | submission | kind | accepted |", "|---|---|---|---|"]
    for task, got in results.items():
        for kind in ("cheats", "near_misses"):
            for r in got[kind]:
                out.append(f"| {task} | {r['name']} | {'cheat' if kind == 'cheats' else 'near miss'} | {r['accepts']} of {repeat} |")
    runs = [r for _, r in cheats]
    intact = sum(r["bundle_intact"] and not r["wrote"] for r in runs)
    out += ["", f"After {intact} of {len(runs)} cheating submissions (each judged {repeat} times) the judge's base checkout held the "
                "bundle it started with and the marker file was not written."
                if intact == len(runs) else
                f"THE BASE CHECKOUT OR A MARKER FILE WAS CHANGED after {len(runs) - intact} of {len(runs)} cheating submissions.",
            "What these bundles rely on, measured and not assumed. The answers are not on disk in a form the submission can "
                "use: the messy files and the reports are generated from the answer (there is no cleaner or summariser to "
                "copy), and only the held-out parts are fixed data. The sandbox does the rest: no network (the cheat that "
                "sends the work to a service on 127.0.0.1 got `Network is unreachable`), a user that cannot write the "
                "judge's files or the base checkout (the sentence above), and, since this release, a tree with no copy of "
                "the bundle. The first run of the cheat that reads the answer file (in clean-csv) found the "
                "held-out set in `.knos/acceptance/1/` of its own tree and answered the held-out part right; it was stopped only "
                "by the freshly generated part, so a bundle made of fixed answers alone (a hidden set, a reference) was "
                "paid to it (tests/test_acceptance_examples.py::test_the_pull_request_cannot_read_the_bundle_it_is_judged_by "
                "fails on 0.3.12's judge and passes now). `knos.judge` now removes the repository's bundles from the tree "
                "before the submission runs. What no judge can do: a bundle committed to a public repository is public to the "
                "person who writes the submission, who can copy a fixed hidden set into it. A set that must stay hidden is "
                "drawn at judge time, as the fresh parts here are; a fixed part (the held-out file, the hidden labels) only "
                "keeps out code that reads it while it is judged. Near the bar the check is a threshold, not a proof: the "
                "near misses are refused because they score below it (the summarise one that leaves out the fix, about 0.82 "
                "against 0.85, is the closest), and a score near the bar can go either way.",
            "<!-- accept:end -->"]
    return out


# ---- escapes: what a submission can do to the machine that judges it -------------------------------------------------

# The image the hermetic column runs the probe in: python 3.12 on Alpine, as Docker Hub's registry named it on
# 2026-10-04 (https://hub.docker.com/_/python, tag 3.12-alpine).
ESCAPE_IMAGE = "docker.io/library/python@sha256:0687a6bc9716edc2a6ee0fbfb0f87e7ee358b262b67c9215de91bc9b2d38ba71"
PLACES = (("none", "host, no sandbox"), ("host", "host sandbox"), ("hermetic", "hermetic (image)"))
THREADS = 400     # more than the container's process limit (judge.Limits.pids) and few enough to be harmless anywhere


class Escape(NamedTuple):
    key: str
    title: str
    expect: dict        # place -> True (the escape works there) | False (it is stopped) | "root" (works when the judge is root)
    why: str


ESCAPES = (
    Escape("network", "open a connection out (how a hidden test set or a secret would leave)",
           {"none": True, "host": False, "hermetic": False},
           "the sandbox and the container both run the submission with no network"),
    Escape("write", "write a file outside the work directory",
           {"none": True, "host": True, "hermetic": False},
           "the sandbox user can write wherever any user of the machine can (/tmp and the like); the container has a "
           "read-only root and sees no host directory but the tree, read-only"),
    Escape("env", "read the judge's environment variables",
           {"none": True, "host": False, "hermetic": False},
           "without a sandbox the submission inherits the judge's environment, less CI's own variables; the sandbox "
           "starts it with an empty one and another user; the container starts with the image's"),
    Escape("procs", f"start {THREADS} threads at once (a fork bomb, held still)",
           {"none": True, "host": True, "hermetic": False},
           "the host puts no limit on the sandbox user's processes; the container has --pids-limit"),
    Escape("clock", "hold the right to set the machine's clock",
           {"none": "root", "host": False, "hermetic": False},
           "setting the clock needs CAP_SYS_TIME: the judge's own user has it only when that user is root, the sandbox "
           "user and the container never"),
)

PROBE = r"""import os, socket, sys, threading, time
what, args = sys.argv[1], sys.argv[2:]
if what == "network":
    for host in args[2:]:
        try:
            with socket.create_connection((host, int(args[1])), timeout=2) as s:
                s.sendall(args[0].encode())
            print("sent to", host)
        except OSError as why:
            print("no", host, why)
elif what == "write":
    try:
        with open(os.path.join(args[0], args[1]), "w") as f:
            f.write("was here")
        print("wrote")
    except OSError as why:
        print("no", why)
elif what == "env":
    seen = [v for v in os.environ.values()]
    for pid in os.listdir("/proc") if os.path.isdir("/proc") else []:
        try:
            with open("/proc/%s/environ" % pid, "rb") as f:
                seen.append(f.read().decode("utf-8", "replace"))
        except OSError:
            pass
    print("found " + args[0] if any(args[0] in v for v in seen) else "not found")
elif what == "procs":
    threading.stack_size(256 * 1024)
    stop, n = threading.Event(), 0
    for _ in range(int(args[0])):
        try:
            threading.Thread(target=stop.wait, daemon=True).start()
            n += 1
        except (RuntimeError, MemoryError):
            break
    stop.set()
    print("started", n)
elif what == "clock":
    cap = 0
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("CapEff:"):
                cap = int(line.split()[1], 16)
    if cap >> 25 & 1:
        print("may set the clock")          # it holds CAP_SYS_TIME; the probe does not use it
    else:
        try:
            time.clock_settime(time.CLOCK_REALTIME, time.time())
            print("may set the clock")
        except OSError as why:
            print("no", why)
"""


def _listener(nonce: str):
    """A TCP listener on every interface of this machine; (port, got) where got() says whether the nonce arrived."""
    import socket
    import threading
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", 0))
    srv.listen(8)
    srv.settimeout(0.2)
    seen, done = [], threading.Event()

    def serve():
        while not done.is_set():
            try:
                conn, _ = srv.accept()
            except OSError:
                continue
            with conn:
                conn.settimeout(2)
                try:
                    seen.append(conn.recv(200).decode("utf-8", "replace"))
                except OSError:
                    pass
    t = threading.Thread(target=serve, daemon=True)
    t.start()

    def got() -> bool:
        time.sleep(0.5)
        done.set()
        t.join(3)
        srv.close()
        return any(nonce in s for s in seen)
    return srv.getsockname()[1], got


def _host_addresses() -> list[str]:
    import socket
    out = ["127.0.0.1", "172.17.0.1"]          # this machine as it sees itself, and as docker's default bridge names it
    try:
        out.append(socket.gethostbyname(socket.gethostname()))
    except OSError:
        pass
    return list(dict.fromkeys(out))


def places() -> dict[str, str]:
    """place -> "" when a submission can be run there on this machine, else why not, in a few words."""
    linux = sys.platform.startswith("linux")
    rt = prove.container_runtime()
    return {"none": "" if linux else "the probes read /proc: Linux only",
            "host": "" if linux and prove.sandbox_available() else "no sandbox on this machine (Linux, setpriv, unshare, root or sudo)",
            "hermetic": "" if linux and prove.runtime_ready(rt) else ("no container runtime on this machine" if not rt
                                                                      else f"{Path(rt).name} is installed and its daemon does not answer")}


def _probe(place: str, work: Path, argv: list[str], box, held) -> str:
    """What the probe printed when run at `place` as a submission's command would be."""
    if place == "hermetic":
        cmd = [*prove.container_argv(held["runtime"], held["ref"], work, held["limits"], label=held["label"]), "python", *argv]
        got = subprocess.run(cmd, capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        return (got.stdout + got.stderr).decode("utf-8", "replace")
    return box.run([sys.executable, *argv], net=False, timeout=120)[1]


def run_escapes(only: tuple = ()) -> dict:
    """{"places": places(), "rows": {escape: {place: True escaped | False held | None not run}}}."""
    import secrets
    can = places()
    rows: dict = {e.key: {} for e in ESCAPES}
    for place, _ in PLACES:
        if can[place] or (only and place not in only):
            can[place] = can[place] or "left out of this run"
            for e in ESCAPES:
                rows[e.key][place] = None
            continue
        root = Path(tempfile.mkdtemp(prefix="knos-escape-")).resolve()
        drop = Path(tempfile.mkdtemp(prefix="knos-drop-")).resolve()
        os.chmod(drop, 0o1777)                 # a directory any user may write, as /tmp is
        box = prove.Box(root, place == "host")
        box.work.mkdir()
        (box.work / "probe.py").write_text(PROBE, encoding="utf-8")
        held = None
        try:
            if place == "hermetic":
                held = {"runtime": prove.container_runtime(), "ref": ESCAPE_IMAGE, "limits": prove.Limits(), "label": secrets.token_hex(6)}
                prove.pull(held["runtime"], ESCAPE_IMAGE)
                os.chmod(root, 0o755)
                (box.work / "probe.py").chmod(0o644)
                box.work.chmod(0o755)
            box.open_up()
            nonce = secrets.token_hex(12)
            os.environ["DEPLOY_TOKEN_OF_THE_JUDGE"] = nonce
            port, arrived = _listener(nonce)
            _probe(place, box.work, ["probe.py", "network", nonce, str(port), *_host_addresses()], box, held)
            rows["network"][place] = arrived()
            _probe(place, box.work, ["probe.py", "write", str(drop), nonce], box, held)
            rows["write"][place] = (drop / nonce).exists()
            rows["env"][place] = f"found {nonce}" in _probe(place, box.work, ["probe.py", "env", nonce], box, held)
            rows["procs"][place] = f"started {THREADS}" in _probe(place, box.work, ["probe.py", "procs", str(THREADS)], box, held)
            rows["clock"][place] = "may set the clock" in _probe(place, box.work, ["probe.py", "clock"], box, held)
        except (ValueError, OSError, subprocess.SubprocessError) as why:
            can[place] = f"could not be set up: {' '.join(str(why).split())[:160]}"
            for e in ESCAPES:
                rows[e.key][place] = None
        finally:
            os.environ.pop("DEPLOY_TOKEN_OF_THE_JUDGE", None)
            if held:
                prove._sweep(held["runtime"], held["label"])
            box.clean()
            shutil.rmtree(drop, ignore_errors=True)
    return {"places": can, "rows": rows}


def expected(e: Escape, place: str) -> bool:
    want = e.expect[place]
    return (hasattr(os, "geteuid") and os.geteuid() == 0) if want == "root" else bool(want)


def escape_section(results: dict) -> list[str]:
    word = {True: "ESCAPES", False: "held", None: "not run here"}
    exp = {True: "escapes", False: "held", "root": "escapes if the judge is root"}
    can, rows = results["places"], results["rows"]
    ran = [p for p, _ in PLACES if not can[p]]
    out = ["<!-- escape:begin -->", "## Escapes: what a submission can do to the machine that judges it", "",
           "These five are not ways to pass without doing the work, so they are not among the 63. Each is something a "
           "submission tries on the judge's machine while it runs; it is tried in each place a submission can run, by the "
           "same call the judge uses to run a submission's command (`python scripts/tamper_bench.py --escape`; "
           "tests/test_tamper_bench.py runs it). **host, no sandbox**: tests mode or black-box on a machine that has no "
           "sandbox and was not told `--sandbox require` (prove.yml passes `require`). **host sandbox**: tests mode and "
           "black-box as prove.yml runs them: another user, an empty environment, no network. **hermetic**: black-box with "
           f"an `image` in the terms; the probe ran in `{ESCAPE_IMAGE}`.", "",
           "What is expected, from how each place is built:", "",
           "| escape | " + " | ".join(t for _, t in PLACES) + " | why |", "|---|---|---|---|---|"]
    out += [f"| {e.title} | " + " | ".join(exp[e.expect[p]] for p, _ in PLACES) + f" | {e.why} |" for e in ESCAPES]
    out += ["", "What was measured on the machine that wrote this page:", "",
            "| escape | " + " | ".join(t for _, t in PLACES) + " |", "|---|---|---|---|"]
    out += [f"| {e.title} | " + " | ".join(word[rows[e.key][p]] for p, _ in PLACES) + " |" for e in ESCAPES]
    out.append("")
    for p, title in PLACES:
        if can[p]:
            out.append(f"**{title}: not run here** ({can[p]}). No number is claimed for it: its column above is what the "
                       "command line is built to do (tests/test_judge_hermetic.py checks that command line argument by "
                       "argument), not a measurement.")
            out.append("")
    if ran:
        hits = sum(rows[e.key][p] == expected(e, p) for e in ESCAPES for p in ran)
        out.append(f"In the places that were run ({_and([t for p, t in PLACES if p in ran])}), {hits} of {len(ESCAPES) * len(ran)} "
                   "outcomes were the expected one" + (f" (the judge ran as {'root' if expected(ESCAPES[-1], 'none') else 'an ordinary user'})." if "none" in ran else "."))
    out += ["", "What this says and does not: the host sandbox stops a submission from calling out and from reading the "
            "judge's environment, and leaves it able to write where any user can and to exhaust the machine. The "
            "container is built to close those too. Five probes are five probes: a kernel or runtime bug that lets a "
            "process out of a container is outside what this page measures.", "<!-- escape:end -->"]
    return out


def update_block(doc: str, name: str, lines: list[str]) -> str:
    """`doc` with the block between <!-- name:begin --> and <!-- name:end --> replaced (or appended when there is none)."""
    block = "\n".join(lines)
    pattern = re.compile(rf"<!-- {name}:begin -->.*?<!-- {name}:end -->", re.S)
    if pattern.search(doc):
        return pattern.sub(lambda _: block, doc)
    return doc.rstrip("\n") + "\n\n" + block + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "TAMPER.md"))
    ap.add_argument("--only", choices=list(SAMPLES), help="run one sample and print its section (docs/TAMPER.md is not written)")
    ap.add_argument("--real", action="store_true", help="run the six real-behaviour tasks and rewrite their block of --out")
    ap.add_argument("--accept", action="store_true", help="run the three non-code tasks and rewrite their block of --out")
    ap.add_argument("--repeat", type=int, default=5, help="with --accept: judgments of each submission (new inputs each time)")
    ap.add_argument("--escape", action="store_true", help="run the five escapes and rewrite their block of --out")
    a = ap.parse_args(argv)
    if a.real or a.accept or a.escape:
        path = Path(a.out)
        doc = path.read_text(encoding="utf-8")
        if a.real:
            doc = update_block(doc, "real", real_section({k: run_real(k) for k in _real_modules()[0].TASKS}))
        if a.accept:
            doc = update_block(doc, "accept", accept_section(run_accept(a.repeat), a.repeat))
        if a.escape:
            doc = update_block(doc, "escape", escape_section(run_escapes()))
        path.write_text(doc, encoding="utf-8")
        return 0
    if a.only:
        print("\n".join(section(SAMPLES[a.only], *run(a.only))))
        return 0
    missing = [s.title for s in SAMPLES.values() if not available(s)]
    if missing:
        print(f"not installed here: {', '.join(missing)}. docs/TAMPER.md reports every sample, so it is not written; "
              "run one sample with --only", file=sys.stderr)
        return 1
    extra = [*real_section({k: run_real(k) for k in _real_modules()[0].TASKS}), "",
             *accept_section(run_accept(a.repeat), a.repeat), "", *escape_section(run_escapes())]
    text = render({key: run(key) for key in SAMPLES}, extra) + "\n"
    Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
