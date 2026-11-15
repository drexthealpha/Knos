"""Run one candidate file the way the referee does: in a fresh directory that holds only the candidate, the public
data and the hidden rows' FEATURES (never their labels), with an almost empty environment and Python's isolated mode.

    python -I _knos_run.py <editable> --train train.csv --val val.csv --predict predict.csv --out preds.json --seed S --budget T

`_knos_run.py` is the referee's runner: it puts a module `knos_io` in front of the candidate (the ONLY door to data:
knos_io.rows("train" | "val" | "predict") and knos_io.output(), the file the predictions go to) and runs the
candidate as __main__. The candidate itself may not open files at all (judge.py refuses open, io, os, pathlib, chr()/
bytes()-built strings, eval/exec/compile/__import__/getattr), and writes {"predictions": [0|1, ...]} through
knos_io.output(). It may print one JSON line with its own validation score; the referee never uses it to decide.

Isolation (after an outside judge read the sealed seed through a computed path):
  - where the OS allows it (Linux with unprivileged user namespaces: `unshare --user --map-root-user --mount --net`),
    the candidate runs in its own mount and network namespace, and every path in `mask` (the task's sealed file and
    its folder, the game's folder, the operator's key folders) is covered by an empty tmpfs (a file: /dev/null) before
    the candidate starts: it cannot read them by any path, computed or not, and has no network. RunResult.isolation
    says "namespace";
  - elsewhere (Windows, macOS, a kernel without user namespaces) it is "none": only the static rules stand between the
    candidate and the referee's files. KNOS_AR_REQUIRE_JAIL=1 refuses to run any candidate without the namespace
    (fail closed: set it on any machine that judges strangers' code).

The time budget is CPU time, not wall-clock time: the candidate gets `budget + GRACE_S` seconds of CPU (RLIMIT_CPU, so
a loaded host does not fail an honest run), and a wall-clock backstop of max(3 x budget, budget + 15) seconds stops a
candidate that only waits. Either one fails the run ("over the time budget"); neither is a cheat.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import synth

GRACE_S = 5.0
RUNNER = "_knos_run.py"
REQUIRE_ENV = "KNOS_AR_REQUIRE_JAIL"
MASK_ENV = "KNOS_AR_MASK"
_PROBE: dict = {}

# The referee's runner. It reads the box's three data files for the candidate, so the candidate never opens a file.
RUNNER_SRC = r'''import csv, json, runpy, sys, types


def _rows(name, labelled):
    with open(name, newline="") as f:
        r = csv.reader(f)
        head = next(r)
        out = []
        for row in r:
            if row:
                vals = [float(v) for v in (row[:-1] if labelled else row)]
                out.append((vals, int(row[-1]) if labelled else None))
        return out


_FILES = {"train": ("train.csv", True), "val": ("val.csv", True), "predict": ("predict.csv", False)}


def rows(which):
    """[(features, label)] of the public train or val rows, or [(features, None)] of the rows to predict."""
    if which not in _FILES:
        raise ValueError("rows: train, val or predict")
    return _rows(*_FILES[which])


def output():
    """The file the predictions go to, opened for writing: json.dump({"predictions": [...]}, f)."""
    return open("preds.json", "w")


m = types.ModuleType("knos_io")
m.rows, m.output = rows, output
sys.modules["knos_io"] = m
editable = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(editable, run_name="__main__")
'''


@dataclass
class RunResult:
    ok: bool
    predictions: list[int] = field(default_factory=list)
    reported: dict = field(default_factory=dict)
    wall_s: float = 0.0
    error: str = ""
    timed_out: bool = False
    isolation: str = "none"


def _env() -> dict[str, str]:
    env = {"PATH": os.defpath, "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    for k in ("SYSTEMROOT", "TEMP", "TMP"):       # Windows cannot start Python without SYSTEMROOT
        if k in os.environ:
            env[k] = os.environ[k]
    return env


def namespace_available() -> bool:
    """Whether this machine can give a candidate its own user, mount and network namespace (asked once)."""
    if "ok" not in _PROBE:
        ok = False
        if sys.platform.startswith("linux") and shutil.which("unshare"):
            try:
                ok = subprocess.run(["unshare", "--user", "--map-root-user", "--mount", "--net", "sh", "-c",
                                     "mount -t tmpfs knos-probe /tmp 2>/dev/null || mount -t tmpfs knos-probe /mnt"],
                                    capture_output=True, timeout=30).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                ok = False
        _PROBE["ok"] = ok
    return _PROBE["ok"]


def default_mask() -> list[str]:
    """Folders no candidate may read even by a computed path: the Solana CLI's keys, and KNOS_AR_MASK (':'-separated)."""
    out = [str(Path.home() / ".config" / "solana")]
    out += [p for p in os.environ.get(MASK_ENV, "").split(":") if p]
    return out


def _jail(argv: list[str], mask: list[str], box: Path) -> list[str]:
    q = shlex.quote
    steps = []
    keep = {Path("/"), Path.home().resolve()} | {q_.resolve() for q_ in (Path(sys.prefix), Path(sys.base_prefix), Path(sys.executable).parent)}
    for m in mask:
        p = Path(m).resolve()
        if p == box or box in p.parents or p in box.parents:     # never hide the box itself (or a folder holding it)
            continue
        if p in keep or any(p in k.parents for k in keep):     # nor Python itself, the home folder or the root
            continue
        steps.append(f"if [ -d {q(str(p))} ]; then mount -t tmpfs -o size=16k,mode=000 knos-mask {q(str(p))}; "
                     f"elif [ -e {q(str(p))} ]; then mount --bind /dev/null {q(str(p))}; fi")
    # then a second user + mount namespace: the masks are inherited into a less privileged namespace, so the kernel
    # locks them (umount refused), even for the namespace's own root
    script = "set -e; " + "; ".join(steps + ['exec unshare --user --map-root-user --mount -- "$@"'])
    return ["unshare", "--user", "--map-root-user", "--mount", "--net", "--", "sh", "-c", script, "knos-ar-jail"] + argv


def _limits(cpu_s: int):
    def set_them():          # runs in the child before exec: RLIMIT_CPU is inherited by everything it starts
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
    return set_them


def backstop(budget_s: float) -> float:
    return max(3.0 * budget_s, budget_s + 15.0)


def run(source: str, editable: str, public: dict[str, list], predict: list, seed: int, budget_s: float,
        python: str | None = None, mask=()) -> RunResult:
    """Run the candidate once. `mask`: paths hidden from it (with default_mask()) where namespaces exist."""
    jail = namespace_available()
    if not jail and os.environ.get(REQUIRE_ENV) == "1":
        return RunResult(False, error=f"no namespace jail on this machine and {REQUIRE_ENV}=1: no candidate code runs")
    with tempfile.TemporaryDirectory(prefix="knos-ar-") as d:
        box = Path(d).resolve()
        (box / editable).write_text(source, encoding="utf-8")
        (box / RUNNER).write_text(RUNNER_SRC, encoding="utf-8")
        synth.write(box / "train.csv", public["train"])
        synth.write(box / "val.csv", public["val"])
        synth.write(box / "predict.csv", predict, labels=False)
        cmd = [python or sys.executable, "-I", RUNNER, editable, "--train", "train.csv", "--val", "val.csv",
               "--predict", "predict.csv", "--out", "preds.json", "--seed", str(seed), "--budget", str(budget_s)]
        if jail:
            cmd = _jail(cmd, [*default_mask(), *[str(m) for m in mask]], box)
        posix = os.name == "posix"
        cpu = int(budget_s + GRACE_S + 0.999)
        wall = backstop(budget_s)
        t0 = time.monotonic()
        try:
            p = subprocess.run(cmd, cwd=box, env=_env(), capture_output=True, text=True, timeout=wall,
                               preexec_fn=_limits(cpu) if posix else None)
        except subprocess.TimeoutExpired:
            return RunResult(False, wall_s=time.monotonic() - t0, timed_out=True, isolation="namespace" if jail else "none",
                             error=f"over the time budget ({budget_s:g} s of CPU; stopped by the wall-clock backstop at {wall:g} s)")
        took = time.monotonic() - t0
        iso = "namespace" if jail else "none"
        if posix and p.returncode in (-signal.SIGXCPU, -signal.SIGKILL, 128 + signal.SIGXCPU, 128 + signal.SIGKILL):
            return RunResult(False, wall_s=took, timed_out=True, isolation=iso, error=f"over the time budget ({budget_s:g} s of CPU)")
        if p.returncode != 0:
            tail = (p.stderr or p.stdout).strip().splitlines()[-1:] or ["no output"]
            return RunResult(False, wall_s=took, isolation=iso, error=f"exit {p.returncode}: {tail[0][:200]}")
        reported = {}
        for line in reversed(p.stdout.strip().splitlines()):
            try:
                got = json.loads(line)
            except ValueError:
                continue
            if isinstance(got, dict):
                reported = {k: v for k, v in got.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
                break
        try:
            preds = json.loads((box / "preds.json").read_text(encoding="utf-8"))["predictions"]
        except (OSError, ValueError, KeyError, TypeError):
            return RunResult(False, reported=reported, wall_s=took, isolation=iso, error="no readable preds.json")
        if not isinstance(preds, list) or len(preds) != len(predict) or any(v not in (0, 1) or isinstance(v, bool) for v in preds):
            return RunResult(False, reported=reported, wall_s=took, isolation=iso,
                             error=f"preds.json must list {len(predict)} predictions, each 0 or 1")
        return RunResult(True, predictions=[int(v) for v in preds], reported=reported, wall_s=took, isolation=iso)
