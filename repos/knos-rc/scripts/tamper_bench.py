"""Tamper benchmark: test-weakening pull requests against three sample repositories, each judged three ways.

    python scripts/tamper_bench.py [--out docs/reference/TAMPER.md] [--only python|node|ruby]
    python scripts/tamper_bench.py --real        # only the six real-behaviour tasks: rewrites their block of docs/reference/TAMPER.md
    python scripts/tamper_bench.py --accept      # only the three non-code tasks (scripts/acceptance_examples.py), same
    python scripts/tamper_bench.py --escape      # only the five escapes from where the submission runs, same
    python scripts/tamper_bench.py --honest      # only the honest submissions (tests/bench_tamper/honest.py), same
    python scripts/tamper_bench.py --honest --group slug|real|plain|rules [--task KEY]
                                                 # one part of them (each under three minutes on a shared machine): its
                                                 # rows are kept in docs/tamper_honest.json and the block is written from
                                                 # that file, which a full --honest run replaces
    python scripts/tamper_bench.py --slug        # only the 63 attacks on the three slugify repositories: rewrites their tables
    python scripts/tamper_bench.py --allowed     # only the cheats aimed at what a pull request may add (attacks_allowed.py), same
    python scripts/tamper_bench.py --authors     # who wrote the cheats: Knos's authors, or outsiders through the `tamper` task
                                                 # (tests/bench_tamper/outside/cases.py, judged again here); rewrites that block

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
(examples/acceptance/) are run through `knos proof judge` by scripts/acceptance_examples.py. docs/reference/TAMPER.md reports both.

The honest set (tests/bench_tamper/honest.py) asks the opposite question of every task above: correct work written
in other ways (another algorithm, another layout, slower, with checks of its own) goes through the same judges, and
the report says how many each accepted and why each refused one was refused. A refused honest submission is a finding.

A pull request may now add test files beside the protected tests (allowed since release 0.3.17): they are not counted. The
cheats of tests/bench_tamper/attacks_allowed.py attack exactly that (a test, a conftest.py, a plugin, a fixture, a
start-up file that would decide if it were loaded), and the report says how many each judge accepted.

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
    ran = tmp / f"ci{i}"                 # CI runs the pull request's code, which may write to its own tree (one cheat
    shutil.copytree(pr, ran)             # rewrites the acceptance tests while they run): the judges get the tree as sent
    green = ci_green(ran)
    shutil.rmtree(ran, ignore_errors=True)
    v = prove.judge(base, pr, {"issue": "1", "test_dirs": sample.test_dirs}, cache=cache)
    out = {"name": name, "ci": green, "knos": v["passed"], "why": "; ".join(v["reasons"]) or "-", "box": None,
           "word": v["verdict"], "notes": v["notes"]}
    if BLACKBOX:
        b = prove.judge(base, pr, {"issue": "2", "test_dirs": sample.test_dirs}, cache=cache)
        out.update({"box": b["passed"], "box_why": "; ".join(b["reasons"]) or "-", "box_word": b["verdict"], "notes": b["notes"]})
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
    """docs/reference/TAMPER.md from {sample key: (control, rows)}, in SAMPLES' order, and `extra` (the blocks for the real-behaviour
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
    return {"name": name, "ci": green, "box": v["passed"], "why": "; ".join(v["reasons"]) or "-", "box_word": v["verdict"],
            "notes": v["notes"]}


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
    """The block of docs/reference/TAMPER.md for the six real-behaviour tasks, from {task key: run_real(...)}."""
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
    """The block of docs/reference/TAMPER.md for the three tasks that are not code, from run_accept()."""
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


# ---- honest work: does a judge refuse a submission that did what the task asked? ------------------------------------

def _honest():
    import honest
    return honest


def run_honest(only: tuple = (), tasks: tuple = ()) -> list[dict]:
    """One row for each honest submission: {"group", "task", "name", "ci", "knos", "box", "why"}. A judge that does not
    apply to a group is None (the real tasks and the tasks that are not code have a black-box bundle only; the tasks
    that are not code have no CI). `only` keeps some groups ("slug", "real", "plain") and `tasks` some tasks (a sample's key, a real task's,
    a folder of examples/acceptance)."""
    H = _honest()
    rows: list[dict] = []
    for key, sample in SAMPLES.items() if not only or "slug" in only else ():
        if tasks and key not in tasks:
            continue
        if not available(sample):
            rows += [{"group": "slug", "task": sample.title, "name": name, "ci": None, "knos": None, "box": None,
                      "why": "not run here: the language is not installed"} for name, _ in H.SLUG[key]]
            continue
        with tempfile.TemporaryDirectory(prefix="knos-honest-") as t:
            tmp = Path(t)
            base = tmp / "base"
            shutil.copytree(BENCH / sample.folder, base, ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
            cache: dict = {}
            for i, (name, fn) in enumerate(H.SLUG[key]):
                got = one(sample, base, tmp, i, name, fn, cache)
                why = "; ".join(x for x in (None if got["knos"] else f"tests: {_stable(got['why'])}",
                                            None if got["box"] in (True, None) else f"black box: {got['box_why']}") if x)
                rows.append({"group": "slug", "task": sample.title, "name": name, "ci": got["ci"], "knos": got["knos"],
                             "box": got["box"], "why": why or "-", "notes": got["notes"]})
    if not only or "real" in only:
        R, _ = _real_modules()
        for key, task in R.TASKS.items():
            if tasks and key not in tasks:
                continue
            with tempfile.TemporaryDirectory(prefix="knos-honest-") as t:
                tmp = Path(t)
                base = tmp / "base"
                R.materialise(task, base)
                cache = {}
                for i, (name, fn) in enumerate(H.REAL):
                    got = one_real(task, base, tmp, i, name, fn, cache)
                    rows.append({"group": "real", "task": key, "name": name, "ci": got["ci"], "knos": None,
                                 "box": got["box"], "why": "-" if got["box"] else f"black box: {got['why']}",
                                 "notes": got["notes"]})
    if not only or "plain" in only:
        import acceptance_examples as ex
        for task, subs in H.PLAIN.items():
            for name, source in subs if not tasks or task in tasks else ():
                with tempfile.TemporaryDirectory(prefix="knos-honest-") as t:
                    folder = source
                    if callable(source):
                        folder = Path(t) / "submission"
                        for rel, text in source().items():
                            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
                            (folder / rel).write_text(text, encoding="utf-8", newline="\n")
                    got = ex.judged(task, name, folder)
                rows.append({"group": "plain", "task": task, "name": name, "ci": None, "knos": None, "box": got["accepted"],
                             "why": "-" if got["accepted"] else "black box: " + ("; ".join(got["reasons"]) or got["output"][-200:])})
    return rows


def run_rule_refused() -> list[dict]:
    """Honest work that changes the authoritative suite itself (honest.RULE_REFUSED), on the Python sample: one row
    each, as run_honest gives. They are refused by rule and are not in the honest count."""
    H, sample = _honest(), SAMPLES["python"]
    rows = []
    with tempfile.TemporaryDirectory(prefix="knos-honest-") as t:
        tmp = Path(t)
        base = tmp / "base"
        shutil.copytree(BENCH / sample.folder, base, ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
        cache: dict = {}
        for i, (name, fn) in enumerate(H.RULE_REFUSED):
            got = one(sample, base, tmp, i, name, fn, cache)
            rows.append({"name": name, "ci": got["ci"], "knos": got["knos"], "box": got["box"],
                         "why": got["box_why"] if got["box"] is False else _stable(got["why"])})
    return rows


ROWS = "tamper_honest.json"       # beside --out: the honest rows of the last runs, part by part


def rows_file(out: Path) -> Path:
    """The rows file of a page: beside it, or in docs/ for a page in docs/reference/ (the data files stay in docs/)."""
    return (out.parent.parent if out.parent.name == "reference" else out.parent) / ROWS


HONEST_PARTS = ("slug", "real", "plain", "rules")


def honest_rows(out: Path, group: str | None = None, tasks: tuple = ()) -> tuple[list[dict], list[dict], bool]:
    """(rows, the rule-refused rows, whether every row is from this one run). With no `group` everything is run and
    the rows file is replaced; with one, only that part (and `tasks` of it) is run and the rest is read from the file."""
    import json
    path = rows_file(out)
    if group is None:
        rows, ruled = run_honest(), run_rule_refused()
    else:
        kept = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"rows": [], "ruled": []}
        rows, ruled = kept["rows"], kept["ruled"]
        if group == "rules":
            ruled = run_rule_refused()
        else:
            new = run_honest((group,), tasks)
            ran = {(r["group"], r["task"]) for r in new}
            rows = [r for r in rows if (r["group"], r["task"]) not in ran] + new
        order = {g: i for i, g in enumerate(HONEST_PARTS)}
        rows.sort(key=lambda r: order[r["group"]])            # stable: the order inside a group is the run's own
    was = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    path.write_text(json.dumps({**was, "rows": rows, "ruled": ruled}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return rows, ruled, group is None


BLOCKS = (("slug", "the 63 attacks on slugify"), ("real", "the attacks on the six real tasks"),
          ("accept", "the tasks that are not code"), ("allowed", "the cheats aimed at what a pull request may add"),
          ("honest", "the honest submissions"), ("escape", "the escapes"))


def judge_id() -> str:
    """Which judge a block was measured with: the first 12 hex digits of the SHA-256 of src/knos/judge.py."""
    import hashlib
    return hashlib.sha256((ROOT / "src" / "knos" / "judge.py").read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]


def measured(out: Path, ran: list[str]) -> list[str]:
    """The block that says which parts of the page were measured with the judge as it is now: `ran` are recorded as
    measured now (in the rows file), and every other part keeps the judge it was last measured with."""
    import json
    path = rows_file(out)
    state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    now = judge_id()
    state["measured"] = {**state.get("measured", {}), **{name: now for name in ran}}
    path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    fresh = [title for name, title in BLOCKS if state["measured"].get(name) == now]
    stale = [title for name, title in BLOCKS if state["measured"].get(name) != now]
    return ["<!-- measured:begin -->",
            f"Measured with the judge as it is in this tree (src/knos/judge.py, SHA-256 {now}...): {_and(fresh) if fresh else 'nothing'}. "
            + (f"Carried over from a run with an earlier judge, and to be measured again before a release: {_and(stale)}. "
               if stale else "Nothing on this page is carried over from an earlier judge. ")
            + "The whole page in one run: `python scripts/tamper_bench.py` (longer than three minutes on a shared machine); "
            "part by part: `--slug`, `--real`, `--accept`, `--allowed`, `--honest`, `--escape`.",
            "<!-- measured:end -->"]


def place_measured(doc: str, lines: list[str]) -> str:
    if "<!-- measured:begin -->" in doc:
        return update_block(doc, "measured", lines)
    head, sep, tail = doc.partition("<!-- honest:begin -->")
    return head + "\n".join(lines) + "\n\n" + sep + tail


def honest_counts(rows: list[dict]) -> dict:
    """{judge: (accepted, judged)} over the rows a judge saw."""
    return {j: (sum(bool(r[j]) for r in rows if r[j] is not None), sum(r[j] is not None for r in rows))
            for j in ("ci", "knos", "box")}


def cheat_totals(doc: str) -> list[tuple[int, int]]:
    """(accepted by Knos's black box, cheating submissions) for the three groups, read from the tables of docs/reference/TAMPER.md:
    the 63 attacks on slugify, the attacks on the six real tasks, and the cheats on the tasks that are not code."""
    slug = re.search(r"^\| \*\*all\*\* \| \*\*(\d+)\*\* \| \*\*\d+\*\* \| \*\*\d+\*\* \| \*\*(\d+)\*\* \|$", doc, re.M)
    real = re.search(r"^\| \*\*all\*\* \| \| \| \| \*\*(\d+)\*\* \| \*\*\d+\*\* \| \*\*(\d+)\*\* \|$", doc, re.M)
    plain = re.findall(r"^\| [\w-]+ \| \d+ of \d+ \| (\d+) \| (\d+) of \d+ \| \d+ \| \d+ of \d+ \|$", doc, re.M)
    out = [(int(m.group(2)), int(m.group(1))) if m else (0, 0) for m in (slug, real)]
    out.append((sum(int(b) for _, b in plain), sum(int(a) for a, _ in plain)))
    added = re.search(r"^\*\*Of (\d+) such cheats, CI green accepted \d+, Knos, tests \d+ and Knos, black box (\d+)\.\*\*", doc, re.M)
    return [*out, *([(int(added.group(2)), int(added.group(1)))] if added else [])]


# ---- cheats aimed at what a pull request may add ---------------------------------------------------------------------

def run_allowed() -> tuple[dict, list[dict]]:
    """(the control's row, the cheats' rows) for tests/bench_tamper/attacks_allowed.py on the Python sample."""
    sample = SAMPLES["python"]._replace(attacks="attacks_allowed.py")
    mod = _attacks(sample)
    with tempfile.TemporaryDirectory(prefix="knos-allowed-") as t:
        tmp = Path(t)
        base = tmp / "base"
        shutil.copytree(BENCH / sample.folder, base, ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
        jobs = [mod.CONTROL, *mod.ATTACKS]
        cache: dict = {}
        first = one(sample, base, tmp, 0, *jobs[0], cache)
        with ThreadPoolExecutor(max_workers=4) as ex:
            got = [first, *ex.map(lambda a: one(sample, base, tmp, a[0], *a[1], cache), list(enumerate(jobs))[1:])]
    return got[0], got[1:]


def allowed_section(control: dict, rows: list[dict]) -> list[str]:
    """The block of docs/reference/TAMPER.md for the cheats aimed at what a pull request may add."""
    n = len(rows)
    ci, kn, bx = _fooled(rows)
    yes = lambda b: "n/a" if b is None else "PASS (fooled)" if b else "fail"  # noqa: E731
    ok = lambda b: "n/a" if b is None else "accepted" if b else "REFUSED"  # noqa: E731
    out = ["<!-- allowed:begin -->", "## Cheats aimed at what a pull request may add", "",
           "The suite that decides is the one fixed at funding: the base's acceptance bundle, tests and test configuration. "
           "A pull request may add files beside them, and the judge sorts what it did to a protected path into three "
           "kinds, named in the verdict (`knos.judge.classify_path(path, terms, status)` says which, for one path, before "
           "any run):", "",
           "| what the pull request did | the judge |", "|---|---|",
           "| a new file in a test directory | allowed, not counted: `contributor tests: N files, not counted` |",
           "| an existing protected test edited or deleted | refused |",
           "| test discovery or execution configuration changed (conftest.py, pytest.ini, tox.ini, the pytest section of "
           "setup.cfg or pyproject.toml, .npmrc, Rakefile, .rspec) | allowed and not counted where the run takes the file "
           "from the base; refused anywhere else |",
           "| anything under `.knos/` (the terms and the bundle) or `.github/` (GitHub runs the pull request's copy of a "
           "workflow, which the judge cannot replace) | refused |",
           "| the `scripts` of package.json | not read where the judge starts the runner itself (`python -m pytest`, "
           "`node --test`, `go test`): allowed. Refused where the funder's own command decides (`[judge] run`, a "
           "black-box bundle), since that command may be `npm test` |", "",
           "Allowed is safe only if an added file cannot decide. The run is built from the pull request's source with "
           "every protected path taken from the base (`knos.judge.overlay`), so an added test, conftest.py or plugin is "
           "not in the tree the suite runs in; tests/test_tamper_bench.py lists that tree file by file and checks that "
           "a conftest.py which raises when it is imported changes nothing. The submissions below "
           "(tests/bench_tamper/attacks_allowed.py; `python scripts/tamper_bench.py --allowed`) test it from the other "
           "side: each leaves slugify broken in the Python sample and adds a file that would make the tests pass if it "
           "were loaded.", "",
           f"**Of {n} such cheats, CI green accepted {ci}, Knos, tests {kn} and Knos, black box {bx}.**", "",
           f"Control (the honest fix, with a regression test in the test directory): CI green {ok(control['ci'])}, "
           f"Knos, tests {ok(control['knos'])}, Knos, black box {ok(control['box'])}"
           + (f" (`{'; '.join(control['notes'])}`)." if control["notes"] else "."), "",
           "| # | cheat | CI green | Knos, tests | Knos, black box | what the judge said of the added files |",
           "|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        said = "; ".join(r["notes"]) or next((x for x in r["why"].split("; ") if x.startswith("touches protected path")),
                                             "nothing: the files are outside every protected path")
        out.append(f"| {i} | {r['name']} | {yes(r['ci'])} | {yes(r['knos'])} | {yes(r['box'])} | {said.replace('|', chr(92) + '|')} |")
    words = sorted({r[k] for r in rows for k in ("word", "box_word") if r.get(k)})
    out += ["", f"The verdict words these runs gave: {', '.join(words)}. A run that cannot decide (the suite did not start, "
                "ran out of time, or the machine could not run it) is `insufficient_evidence`: never accepted, never "
                "rejected.",
            "A file outside every protected path is the pull request's source and is in the tree: what keeps it from "
            "deciding is the runner (plugin autoload is off, the acceptance checks are the base's, and Python reads "
            "start-up and .pth files only from its own site directories), and for the black box that no test runner "
            "shares a process with the submission at all.",
            "<!-- allowed:end -->"]
    return out


HONEST_GROUPS = (("slug", "slugify, three repositories"), ("real", "real open-source behaviour, six tasks"),
                 ("plain", "tasks that are not code, three"))


def honest_section(rows: list[dict], cheats: list[tuple[int, int]], ruled: list[dict] | None = None, whole: bool = True) -> list[str]:
    """The block of docs/reference/TAMPER.md for the honest submissions, from run_honest(), cheat_totals() and run_rule_refused()."""
    H = _honest()
    n = honest_counts(rows)
    of = lambda pair: f"{pair[0]} of {pair[1]}" if pair[1] else "n/a"  # noqa: E731
    refused = [r for r in rows if False in (r["knos"], r["box"])]
    expected = [r for r in refused if r["name"] in H.EXPECTED_REFUSED]
    other = [r for r in refused if r["name"] not in H.EXPECTED_REFUSED]
    out = ["<!-- honest:begin -->", "## Honest work: is a correct submission refused?", "",
           "A judge that refuses every cheat and every honest submission is worth nothing, so the same judges see "
           f"{len(rows)} honest submissions (tests/bench_tamper/honest.py; `python scripts/tamper_bench.py --honest`): for "
           "every task on this page, correct work written in other ways than the benchmark's own fix: another "
           "algorithm, another style, the code moved to new files, a slower way that is still right, checks of its "
           "own, and regression tests added where the repository keeps its tests. The submissions are fixed text. The black-box checks draw new inputs on every run, so a count below "
           "can differ between runs only if a submission is wrong on a rare input or a check asks for something the task "
           "does not define (one such fault was found, below).", "",
           f"**Honest submissions accepted: Knos, black box {of(n['box'])}; Knos, tests {of(n['knos'])}; CI green {of(n['ci'])}.** "
           f"**Cheating submissions accepted by Knos, black box: {', '.join(f'{a} of {b}' for a, b in cheats)}** "
           "(the attacks on slugify, on the six real tasks, the cheats on the tasks that are not code, and the cheats "
           "aimed at what a pull request may add; the tables of each follow on this page).", "",
           "| tasks | honest submissions | CI green accepted | Knos, tests accepted | Knos, black box accepted |",
           "|---|---|---|---|---|"]
    for group, title in HONEST_GROUPS:
        g = honest_counts([r for r in rows if r["group"] == group])
        out.append(f"| {title} | {sum(r['group'] == group for r in rows)} | {of(g['ci'])} | {of(g['knos'])} | {of(g['box'])} |")
    out += [f"| **all** | **{len(rows)}** | **{of(n['ci'])}** | **{of(n['knos'])}** | **{of(n['box'])}** |", "",
            "Both rates are measured on Knos's own tasks, with submissions written by Knos's author: "
            f"{sum(b for _, b in cheats)} cheating submissions and {len(rows)} honest ones. Neither is a rate for other "
            "people's repositories or for attacks and solutions somebody else wrote; nobody outside has run either set.", ""]
    if refused:
        out += [f"Every honest submission a Knos judge refused ({len(refused)}), with the judge's reason:", "",
                "| task | submission | refused by | reason |", "|---|---|---|---|"]
        for r in refused:
            by = " and ".join(t for j, t in (("knos", "Knos, tests"), ("box", "Knos, black box")) if r[j] is False)
            why = r["why"].replace("|", "\\|")
            out.append(f"| {r['task']} | {r['name']} | {by} | {why if len(why) <= 160 else why[:157] + '...'} |")
        out.append("")
    if expected:
        out += [f"{len(expected)} of them are of a kind that is expected to be refused (honest.EXPECTED_REFUSED).", ""]
    out += [("No other honest submission was refused." if refused and not other else
             f"None of the {len(rows)} was refused by a Knos judge." if not refused else
             f"{len(other)} refused for another reason: each is a false refusal that is not explained above."), ""]
    before = [r for r in rows if r["name"] not in H.ADDED]
    if len(before) < len(rows):
        out += [f"{len(before)} of these submissions made up the whole set until release 0.3.17. Back then the black-box judge accepted 39 of them; "
                f"it now accepts {honest_counts(before)['box'][0]} of {len(before)}. The other {len(rows) - len(before)} are new: "
                "more ways to write a regression test in a protected place.", ""]
    with_tests = [r for r in rows if r["name"] in H.WITH_TESTS]
    took = [r for r in with_tests if False not in (r["knos"], r["box"])]
    noted = [r for r in took if any(n.startswith(("contributor tests:", "test configuration:")) for n in r.get("notes", ()))]
    out += [f"{len(with_tests)} of the {len(rows)} fix the issue and add tests where the repository keeps them: a test "
            "file, a parametrised test, a unittest class, a package of tests with a data file, a fixture in a new "
            f"conftest.py, a seeded property test, describe/it, a spec. Knos accepted {len(took)} of {len(with_tests)}, "
            f"and the verdict of {len(noted)} says what was added and that it was not counted (`contributor tests: N "
            "files, not counted`). Before release 0.3.17 the judge refused every pull request that touched a protected path, and "
            "the nine of this kind in the set then were the whole of its refusals. The added tests "
            "do not help a submission either: the suite that decides is the base's, and the next section measures what "
            "a cheat gains from adding one.", ""]
    if ruled is not None:
        still = [r for r in ruled if False in (r["knos"], r["box"])]
        out += [f"What is still refused, and honest: {len(still)} of {len(ruled)} further submissions that are correct and "
                "change the authoritative suite itself or a path the judge cannot take from the base (honest.RULE_REFUSED, "
                "on the Python repository). They are refused by rule, whatever the change says, and they are NOT in the "
                "count above: a judge that let a pull request rewrite the test it is judged by could not tell this from "
                "a weakened test. A contributor sends such a change in a pull request of its own, which a maintainer "
                "merges.", "",
                "| submission | CI green | Knos | reason |", "|---|---|---|---|"]
        for r in ruled:
            why = r["why"].replace("|", "\\|")
            out.append(f"| {r['name']} | {'passes' if r['ci'] else 'fails'} | "
                       f"{'refused' if False in (r['knos'], r['box']) else 'accepted'} | {why if len(why) <= 200 else why[:197] + '...'} |")
        out.append("")
    H_total = H.count()
    out += [("Every row of this section is from one run of `python scripts/tamper_bench.py --honest`." if whole else
             f"The rows of this section were measured part by part (`--honest --group slug`, `real`, `plain`, `rules`; "
             f"{len(rows)} of the set's {H_total} submissions have a row), each part in a run of its own, and are kept in "
             f"docs/{ROWS}; one run of `python scripts/tamper_bench.py --honest` measures them all at once."), ""]
    out += ["One fault was found in the suite itself while this set was written, and fixed there, not in a submission. "
            "The csv.Sniffer task says \"the delimiter every line has the same, highest number of times\", and its "
            "generator sometimes drew a sample in which two delimiters are in every line equally often (`a,b|c` on every "
            "line). The task does not say which of the two wins; csv.Sniffer picks one by rules of its own, and the check "
            "took that pick as the answer. The benchmark's own honest fix disagreed on 22 of 200,000 generated samples, "
            "which is about one refused run in sixty at 150 samples a run. The generator now leaves such samples out "
            "(tests/bench_tamper/real_tasks.py, `accept`); on 150,000 samples drawn after the change the honest fix and "
            "the other algorithm of this set both agreed with csv.Sniffer on every one.",
            "<!-- honest:end -->"]
    return out


def place_honest(doc: str, lines: list[str]) -> str:
    """`doc` with the honest block replaced, or put in before the first repository's section when there is none."""
    if "<!-- honest:begin -->" in doc:
        return update_block(doc, "honest", lines)
    head, sep, tail = doc.partition("\n## ")
    return head.rstrip("\n") + "\n\n" + "\n".join(lines) + "\n" + sep + tail


def place_allowed(doc: str, lines: list[str]) -> str:
    """`doc` with the block of the cheats aimed at what a pull request may add replaced, or put in before the first
    repository's section (after the honest block) when there is none."""
    if "<!-- allowed:begin -->" in doc:
        return update_block(doc, "allowed", lines)
    head, sep, tail = doc.partition("\n## Python, pytest")
    return head.rstrip("\n") + "\n\n" + "\n".join(lines) + "\n" + sep + tail


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
           {"none": True, "host": False, "hermetic": False},
           "the sandbox runs in a mount namespace where every mount but its own folder is read-only (/tmp and the "
           "like included); the container has a read-only root and sees no host directory but the tree, read-only"),
    Escape("env", "read the judge's environment variables",
           {"none": True, "host": False, "hermetic": False},
           "without a sandbox the submission inherits the judge's environment, less CI's own variables; the sandbox "
           "starts it with an empty one and another user; the container starts with the image's"),
    Escape("procs", f"start {THREADS} threads at once (a fork bomb, held still)",
           {"none": True, "host": False, "hermetic": False},
           "the sandbox user may run 256 processes and threads (RLIMIT_NPROC, judge.HostLimits); the container has "
           "--pids-limit"),
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
           "black-box as prove.yml runs them: another user, an empty environment, no network, the machine read-only but for "
           "the run's folder, and process, CPU, memory and file size limits (docs/reference/ATTESTOR.md). **hermetic**: black-box "
           f"with an `image` in the terms, or with none under `--sandbox hermetic` on a machine that runs containers; the "
           f"probe ran in `{ESCAPE_IMAGE}` (judge.DEFAULT_IMAGE).", "",
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
    out += ["", "What this says and does not: the host sandbox stops a submission from calling out, from reading the "
            "judge's environment, from writing outside its folder and from starting more processes than its limit; its "
            "memory limit is per process, where a container's is per container. Five probes are five probes: a kernel "
            "or runtime bug that lets a process out of a namespace or a container is outside what this page measures.",
            "<!-- escape:end -->"]
    return out


# ---- who wrote the cheats -------------------------------------------------------------------------------------------

def outside_cases() -> list:
    """The cheats outsiders wrote that the judge accepted (tests/bench_tamper/outside/cases.py CASES)."""
    spec = importlib.util.spec_from_file_location("tamper_outside_cases", BENCH / "outside" / "cases.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.CASES)


def run_outside(cases: list | None = None) -> list[dict]:
    """Each outside case judged again by this tree's judge on its sample, as `one` judges the authors' attacks."""
    rows = []
    for i, (name, author, pull, key, fn) in enumerate(outside_cases() if cases is None else cases):
        sample = SAMPLES[key]
        with tempfile.TemporaryDirectory(prefix="knos-outside-") as t:
            tmp = Path(t)
            base = tmp / "base"
            shutil.copytree(BENCH / sample.folder, base, ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
            rows.append({**one(sample, base, tmp, i, name, fn, {}), "author": int(author), "pull": pull, "sample": key})
    return rows


def authors_section(cheats: list[tuple[int, int]], rows: list[dict]) -> list[str]:
    """The block of docs/reference/TAMPER.md that says who wrote the cheats: `cheats` from cheat_totals (the authors'), `rows`
    from run_outside (the outsiders')."""
    mine, took = sum(b for _, b in cheats), sum(a for a, _ in cheats)
    now = sum(bool(r["box"]) or bool(r["knos"]) for r in rows)
    out = ["<!-- authors:begin -->", "## Who wrote the cheats", "",
           "| written by | cheating submissions | accepted by Knos, black box (the tables on this page) |",
           "|---|---|---|",
           f"| Knos's author | {mine} | {took} |",
           f"| outsiders, through the `tamper` task | {len(rows)} | {now} |", "",
           "Every cheat counted in the first row was written by Knos's author. An outsider can change that: "
           "the `tamper` task (tasks/outside/tamper.json) pays 5 test USDC for a submission the judge ACCEPTS on a funded "
           "task although it does not do what the task asks; a refused one pays nothing. So every outside cheat was "
           "accepted by the judge it was written against; the second row says how many this tree's judge still accepts. "
           "An accepted cheat joins "
           "tests/bench_tamper/outside/cases.py with its author's account id and pull request, is judged again by every "
           "later judge (`python scripts/tamper_bench.py --authors`), and is counted by scripts/outsiders.py as "
           "`outside_cheats` only when the account is not one of Knos's own."]
    if rows:
        out += ["", "| case | author (GitHub id) | pull request | sample | Knos, tests | Knos, black box |", "|---|---|---|---|---|---|"]
        out += [f"| {r['name']} | {r['author']} | {r['pull']} | {r['sample']} | {'accepted' if r['knos'] else 'refused'} | "
                f"{'n/a' if r['box'] is None else 'accepted' if r['box'] else 'refused'} |" for r in rows]
    else:
        out += ["", "No outsider has submitted a cheat yet: the outside row is 0 of 0, not a rate."]
    return [*out, "<!-- authors:end -->"]


def place_authors(doc: str, lines: list[str]) -> str:
    if "<!-- authors:begin -->" in doc:
        return update_block(doc, "authors", lines)
    head, sep, tail = doc.partition("<!-- honest:begin -->")
    return head + "\n".join(lines) + "\n\n" + sep + tail


def update_block(doc: str, name: str, lines: list[str]) -> str:
    """`doc` with the block between <!-- name:begin --> and <!-- name:end --> replaced (or appended when there is none)."""
    block = "\n".join(lines)
    pattern = re.compile(rf"<!-- {name}:begin -->.*?<!-- {name}:end -->", re.S)
    if pattern.search(doc):
        return pattern.sub(lambda _: block, doc)
    return doc.rstrip("\n") + "\n\n" + block + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "reference" / "TAMPER.md"))
    ap.add_argument("--only", choices=list(SAMPLES), help="run one sample and print its section (docs/reference/TAMPER.md is not written)")
    ap.add_argument("--real", action="store_true", help="run the six real-behaviour tasks and rewrite their block of --out")
    ap.add_argument("--accept", action="store_true", help="run the three non-code tasks and rewrite their block of --out")
    ap.add_argument("--repeat", type=int, default=5, help="with --accept: judgments of each submission (new inputs each time)")
    ap.add_argument("--escape", action="store_true", help="run the five escapes and rewrite their block of --out")
    ap.add_argument("--honest", action="store_true", help="run the honest submissions and rewrite their block of --out")
    ap.add_argument("--group", choices=HONEST_PARTS, help="with --honest: run one part and keep the other parts' rows")
    ap.add_argument("--task", action="append", default=[], help="with --honest --group: only this task of the part (repeatable)")
    ap.add_argument("--allowed", action="store_true", help="run the cheats aimed at what a pull request may add and rewrite their block of --out")
    ap.add_argument("--slug", action="store_true", help="run the attacks on the three slugify repositories and rewrite their tables of --out")
    ap.add_argument("--authors", action="store_true", help="judge the outsiders' cheats again and rewrite the block that says who wrote the cheats")
    a = ap.parse_args(argv)
    if a.real or a.accept or a.escape or a.honest or a.allowed or a.slug or a.authors:
        path = Path(a.out)
        doc = path.read_text(encoding="utf-8")
        if a.slug:
            missing = [s.title for s in SAMPLES.values() if not available(s)]
            if missing:
                print(f"not installed here: {', '.join(missing)}", file=sys.stderr)
                return 1
            kept = {name: re.search(rf"<!-- {name}:begin -->.*?<!-- {name}:end -->", doc, re.S) for name in ("honest", "allowed")}
            doc = render({key: run(key) for key in SAMPLES}).rstrip("\n") + "\n\n" + doc[doc.index("<!-- real:begin -->"):]
            if kept["honest"]:
                doc = place_honest(doc, kept["honest"].group(0).split("\n"))
            if kept["allowed"]:
                doc = place_allowed(doc, kept["allowed"].group(0).split("\n"))
        if a.real:
            doc = update_block(doc, "real", real_section({k: run_real(k) for k in _real_modules()[0].TASKS}))
        if a.accept:
            doc = update_block(doc, "accept", accept_section(run_accept(a.repeat), a.repeat))
        if a.escape:
            doc = update_block(doc, "escape", escape_section(run_escapes()))
        if a.allowed:
            doc = place_allowed(doc, allowed_section(*run_allowed()))
        if a.honest:
            rows, ruled, whole = honest_rows(path, a.group, tuple(a.task))
            doc = place_honest(doc, honest_section(rows, cheat_totals(doc), ruled, whole))
        if a.authors or a.slug or a.real or a.accept or a.allowed:     # the totals it reads may have changed
            doc = place_authors(doc, authors_section(cheat_totals(doc), run_outside()))
        whole_part = not (a.honest and a.group)         # one part of the honest set is not the honest set
        ran = [n for n, _ in BLOCKS if getattr(a, n) and (n != "honest" or whole_part)]
        doc = place_measured(doc, measured(path, ran))
        path.write_text(doc, encoding="utf-8")
        return 0
    if a.only:
        print("\n".join(section(SAMPLES[a.only], *run(a.only))))
        return 0
    missing = [s.title for s in SAMPLES.values() if not available(s)]
    if missing:
        print(f"not installed here: {', '.join(missing)}. docs/reference/TAMPER.md reports every sample, so it is not written; "
              "run one sample with --only", file=sys.stderr)
        return 1
    extra = [*real_section({k: run_real(k) for k in _real_modules()[0].TASKS}), "",
             *accept_section(run_accept(a.repeat), a.repeat), "", *escape_section(run_escapes())]
    text = render({key: run(key) for key in SAMPLES}, extra) + "\n"
    added = allowed_section(*run_allowed())
    rows, ruled, whole = honest_rows(Path(a.out))
    text = place_honest(text, honest_section(rows, cheat_totals(text + "\n".join(added)), ruled, whole))
    text = place_allowed(text, added)
    text = place_authors(text, authors_section(cheat_totals(text), run_outside()))
    text = place_measured(text, measured(Path(a.out), [n for n, _ in BLOCKS]))
    Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
