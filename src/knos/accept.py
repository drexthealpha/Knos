"""`knos accept init`: a black-box acceptance bundle made from a reference implementation.

A bounty can be paid by its acceptance checks alone, with no merge, only when the bundle in `.knos/acceptance/<issue>/` is
black-box (`knos.judge.black_box`; docs/TAMPER.md measures why): the pull request's code runs as a separate process, only
what it prints is compared, and nothing it does can change the verdict except printing the right answer. Writing that
check by hand is the part people skip, so this makes it from what a funder already has: a command that answers right.

    knos accept init --issue 12 --from "python3 reference/slug.py" --cases 30

    1. Inputs are generated (`inputs`): one per case, from a seed, edge cases first. `--input` picks the kind (text, int or
       ints); `--inputs FILE` gives your own, one per line, for a command that wants some other shape.
    2. The reference command is run on each, twice, with the input on stdin: its output is the answer. A command that
       exits non-zero, times out, or answers differently the second time is refused (`record`): a check needs one answer.
    3. The bundle is written (`bundle`): `blackbox.py`, the judge that runs `$KNOS_RUN <command>` on every input and
       compares the output with the recorded one; `cases.json`, the cases; and a README that says what it can and cannot do.
    4. It is tried before it is trusted (`verify`): the reference must pass it, and a command that only echoes its input
       must fail it. A bundle that fails either is not left behind.

The command the pull request's code must answer to is `--run` (default: the same as `--from`), run in the pull request's
tree. Outputs are compared after trailing spaces and blank lines at the ends are dropped, and nothing else.

What this does not do, and the README in the bundle says so: the cases are in the repository, so an implementation can
answer exactly those from a table. Generated inputs, compared with a reference at the time the check runs, are what no
table survives (that is what a hand-written blackbox.py in docs/TAMPER.md does); recorded ones make a table a lot of work
for a bounty, not an impossible one. More cases make it more work.
"""

from __future__ import annotations

import importlib.util
import json
import random
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import judge

MAX_CASES = 200                 # one run of the command per case, each in the judge's sandbox
MAX_INPUT = 2000                # characters of one input line
TIMEOUT = 20                    # seconds the reference may take for one case
KINDS = ("text", "int", "ints")
_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789   ,.;:!?-_&'\"()/éüß中"
_EDGES = {"text": ["", " ", "a", "A", "Hello, World!", "  leading and trailing  ", "a  b", "x-y_z", "100%", "École"],
          "int": ["0", "1", "-1", "2", "7", "10", "255", "-100", "1000000", "-2147483648", "2147483647"],
          "ints": ["", "0", "5", "-5", "1 2 3", "3 2 1", "7 7 7", "-1 0 1", "1000000 -1000000"]}


class Refused(ValueError):
    """The bundle cannot be made. The message says why, in a sentence."""


@dataclass(frozen=True)
class Made:
    folder: Path
    files: tuple[str, ...]
    cases: int
    seed: int | None


def inputs(kind: str, n: int, seed: int) -> list[str]:
    """`n` distinct input lines of this kind, edge cases first, then random ones: the same for the same seed."""
    if kind not in KINDS:
        raise Refused(f"--input is one of {', '.join(KINDS)}; {kind!r} is none of them.")
    rng = random.Random(seed)
    seen: dict[str, None] = {}
    for edge in _EDGES[kind]:
        seen.setdefault(edge)
    tries = 0
    while len(seen) < n and tries < 50 * n + 500:      # a kind with few possible inputs may give fewer than n
        tries += 1
        if kind == "text":
            seen.setdefault("".join(rng.choice(_ALPHABET) for _ in range(rng.randint(1, 40))))
        elif kind == "int":
            seen.setdefault(str(rng.randint(-(10 ** rng.randint(1, 12)), 10 ** rng.randint(1, 12))))
        else:
            seen.setdefault(" ".join(str(rng.randint(-(10 ** rng.randint(0, 6)), 10 ** rng.randint(0, 6))) for _ in range(rng.randint(0, 8))))
    return list(seen)[:n]


def norm(text: str) -> str:
    """An answer as it is compared: line ends as \\n, trailing spaces and the blank lines at the end dropped."""
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").strip("\n").split("\n"))


def _argv(command: str, what: str) -> list[str]:
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as why:
        raise Refused(f"{what} is not a command line ({why}): {command!r}") from None
    if not argv:
        raise Refused(f"{what} is empty: name the command, like \"python3 reference.py\".")
    return argv


def _here(cwd: Path | None) -> str | None:
    """The folder to run in, or None for the current one: a folder that is not there yet must not read as a missing command."""
    return str(cwd) if cwd and cwd.is_dir() else None


def _once(argv: list[str], line: str, cwd: Path | None) -> tuple[int, str, str]:
    try:
        got = subprocess.run(argv, input=(line + "\n").encode("utf-8"), capture_output=True, timeout=TIMEOUT, cwd=_here(cwd))
    except FileNotFoundError:
        raise Refused(f"the reference command was not found: {argv[0]!r}") from None
    except subprocess.TimeoutExpired:
        raise Refused(f"the reference command took more than {TIMEOUT} seconds on the input {line[:60]!r}.") from None
    except OSError as why:
        raise Refused(f"the reference command could not be run: {str(why)[:100]}") from None
    return got.returncode, got.stdout.decode("utf-8", "replace"), got.stderr.decode("utf-8", "replace")


def record(argv: list[str], lines: list[str], cwd: Path | None = None) -> list[dict]:
    """[{"input", "output"}] for each line: what the reference command prints (stdin: the line). Raises Refused when it exits
    non-zero, answers differently the second time, or prints nothing for every input."""
    out = []
    for n, line in enumerate(lines, 1):
        code, first, err = _once(argv, line, cwd)
        if code != 0:
            raise Refused(f"the reference command exited {code} on case {n}, the input {line[:60]!r}: {' '.join(err.split())[-200:] or 'it said nothing'}")
        if norm(_once(argv, line, cwd)[1]) != norm(first):
            raise Refused(f"the reference command answered case {n}, the input {line[:60]!r}, differently the second time: a check needs one answer.")
        out.append({"input": line, "output": norm(first)})
    if not any(c["output"] for c in out):
        raise Refused("the reference command printed nothing for every input: there is nothing to compare.")
    return out


_JUDGE = '''"""Black-box acceptance for issue {issue}, made by `knos accept init`. Read README.md.

This file runs as the judge, outside the pull request's tree, and never loads the pull request's code. It runs
"$KNOS_RUN <command>" (which runs the command in the pull request's tree, inside the sandbox) on every input in
cases.json, and compares what it prints with the answer recorded from the reference. Exit 0 means every case agrees."""
import json
import os
import subprocess
import sys
from pathlib import Path

SPEC = json.loads((Path(__file__).resolve().parent / "cases.json").read_text(encoding="utf-8"))
SECONDS = 60


def norm(text):
    return "\\n".join(line.rstrip() for line in text.replace("\\r\\n", "\\n").strip("\\n").split("\\n"))


def ask(argv, stdin):
    got = subprocess.run([os.environ["KNOS_RUN"], *argv], input=stdin, capture_output=True, timeout=SECONDS)
    return got.returncode, got.stdout, got.stderr


def check(ask=ask):
    """None when every case agrees, else one sentence about the first that does not."""
    for n, case in enumerate(SPEC["cases"], 1):
        at = "case %d, the input %s" % (n, repr(case["input"][:60]))
        try:
            code, out, err = ask(SPEC["run"], (case["input"] + "\\n").encode("utf-8"))
        except subprocess.TimeoutExpired:
            return "%s: the command took more than %d seconds" % (at, SECONDS)
        if code != 0:
            return "%s: the command exited %d: %s" % (at, code, " ".join(err.decode("utf-8", "replace").split())[-200:] or "it said nothing")
        got = norm(out.decode("utf-8", "replace"))
        if got != case["output"]:
            return "%s: it printed %s, expected %s" % (at, repr(got[:80]), repr(case["output"][:80]))
    return None


if __name__ == "__main__":
    why = check()
    if why:
        sys.exit(why)
    print("all %d cases agree" % len(SPEC["cases"]))
'''

_README = """# Acceptance checks for issue {issue}

Made by `knos accept init` from a reference implementation: {n} inputs ({kind}, seed {seed}) and the answer the reference
gave to each, in `cases.json`. `blackbox.py` is the judge. It runs `{run}` in the pull request's tree for every input,
with the input on standard input, and compares what it prints with the recorded answer (trailing spaces and blank lines at
the end are ignored). Exit 0 means every case agrees.

It is black-box: the pull request's code runs as a separate process, and the judge never loads it, so nothing that code
does can change the verdict except printing the right answer. That is what lets Knos pay on this check alone, without a
merge, when this folder is on the default branch before the bounty is funded: `/knos fund <amount>` on issue {issue}.

What it does not do: the cases are in this repository, so an implementation can answer exactly them from a table. More
cases make that more work, not impossible. A check that generates its inputs when it runs and compares them with a
reference at that time cannot be answered from a table: write that as `blackbox.py` yourself if the bounty is worth it
(Knos's docs/TAMPER.md measures the difference).
"""


def bundle(issue: int, run: list[str], cases: list[dict], kind: str, seed: int | None) -> dict[str, bytes]:
    """The bundle's files as {name: content}: black-box by `judge.black_box`, or this raises."""
    spec = {"v": 1, "issue": issue, "run": run, "input": kind, "seed": seed, "cases": cases}
    text = json.dumps(spec, indent=1) + "\n"
    if "KNOS_TREE" in text:                       # a bundle that names the tree is not black-box: say so now, not at funding
        raise Refused("an input or an answer holds the text KNOS_TREE, which a black-box bundle may not name.")
    files = {"blackbox.py": _JUDGE.format(issue=issue).encode("utf-8"), "cases.json": text.encode("utf-8"),
             "README.md": _README.format(issue=issue, n=len(cases), kind=kind if seed is not None else "given", seed=seed if seed is not None else "none",
                                         run=shlex.join(run)).encode("utf-8")}
    why = judge.black_box(files)
    if why:                                       # a fault in this module, never in the person's input
        raise Refused(f"the bundle is not black-box (its checks {why}).")
    return files


def verify(files: dict[str, bytes], reference: list[str], cwd: Path | None, folder: Path) -> None:
    """The bundle as the judge would run it, with the reference standing in for the pull request's code: it must pass, and a
    command that only echoes its input must fail. Raises Refused otherwise. `folder` holds the files (cases.json is read
    from beside blackbox.py)."""
    spec = importlib.util.spec_from_file_location("knos_acceptance_try", folder / "blackbox.py")
    module = importlib.util.module_from_spec(spec)                                                    # type: ignore[arg-type]
    kept, sys.dont_write_bytecode = sys.dont_write_bytecode, True                                     # no __pycache__ in the bundle
    try:
        spec.loader.exec_module(module)                                                               # type: ignore[union-attr]
    finally:
        sys.dont_write_bytecode = kept

    def with_reference(_argv, stdin):
        got = subprocess.run(reference, input=stdin, capture_output=True, timeout=TIMEOUT, cwd=_here(cwd))
        return got.returncode, got.stdout, got.stderr
    why = module.check(with_reference)
    if why:
        raise Refused(f"the reference does not pass its own bundle: {why}")
    if module.check(lambda _argv, stdin: (0, stdin, b"")) is None:
        raise Refused("a command that only prints its input back passes this bundle: the inputs do not tell a right answer from an echo. Choose another --input or give --inputs.")


def scaffold(root: Path, issue: int, reference: str, run: str | None = None, cases: int = 30, kind: str = "text", seed: int | None = None,
             given: Path | None = None, force: bool = False) -> Made:
    """Make `.knos/acceptance/<issue>/` under `root` from the reference command. Raises Refused; leaves nothing behind then."""
    if not isinstance(issue, int) or isinstance(issue, bool) or not 1 <= issue <= 10 ** 9:
        raise Refused(f"--issue is the issue's number, like 12; {issue!r} is not one.")
    if given is None and not 1 <= cases <= MAX_CASES:
        raise Refused(f"--cases is from 1 to {MAX_CASES} (each is one run of the command in the judge's sandbox); {cases} is not.")
    argv, run_argv = _argv(reference, "--from"), _argv(run, "--run") if run else None
    run_argv = run_argv or argv
    folder = root / ".knos" / "acceptance" / str(issue)
    if folder.exists() and not force:
        raise Refused(f"{folder} exists already. Look at it, or give --force to replace it.")
    if given is not None:
        try:
            lines = given.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as why:
            raise Refused(f"--inputs {given} cannot be read as text: {str(why)[:80]}") from None
        lines = list(dict.fromkeys(lines))
        if not 1 <= len(lines) <= MAX_CASES or any(len(x) > MAX_INPUT for x in lines):
            raise Refused(f"--inputs holds {len(lines)} distinct lines; from 1 to {MAX_CASES}, each at most {MAX_INPUT} characters, are used.")
        kind, seed = "given", None
    else:
        seed = random.SystemRandom().randrange(1, 2 ** 31) if seed is None else seed
        lines = inputs(kind, cases, seed)
    made = record(argv, lines, root)
    files = bundle(issue, run_argv, made, kind, seed)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (folder / name).write_bytes(data)
        verify(files, argv, root, folder)
    except Refused:
        _clean(folder, files)
        raise
    except OSError as why:
        _clean(folder, files)
        raise Refused(f"could not write {folder}: {str(why)[:100]}") from None
    return Made(folder, tuple(files), len(made), seed)


def _clean(folder: Path, files: dict) -> None:
    for name in files:
        (folder / name).unlink(missing_ok=True)
    for dirs in (folder, folder.parent, folder.parent.parent):    # the issue's folder, then .knos/acceptance and .knos if now empty
        try:
            dirs.rmdir()
        except OSError:
            break
