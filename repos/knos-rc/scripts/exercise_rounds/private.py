"""The round `private`: the private path as one command (`python -m knos.private run`), from the attestors both parties
approved to a dispute both resolve. The command runs on one machine against a simulator and sends nothing to any
chain, so this round exercises no program and marks no capability.

    python scripts/exercise_public.py run --only private --simulate
    python scripts/exercise_public.py run --only private --rpc URL --keys DIR

On the simulator, and at the public ids alike, it runs the command on examples/private and keeps the record's hash.
At the public ids it then ends 3 until someone with a private repository has run examples/private/knos-private.yml
there and the operator has noted it (`note private --keys DIR record=<sha256 of that run's record.json> by=<who>`):
nobody has. `xp` is scripts/exercise_public.py, put here by its loader.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

ROUND = {"name": "private", "needs": (), "caps": (), "phase": "after"}
ROOT = Path(__file__).resolve().parents[2]
SEED = "knos exercise: the private path"


def _path(book, st: dict) -> None:
    from knos import private
    ex = ROOT / "examples" / "private"
    said: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        got = private.run(ex, ex / "attestors.json", Path(tmp) / "out", now=int(book.w.now()), seed=SEED, say=said.append,
                          retention=json.loads((ex / "retention.json").read_text(encoding="utf-8")))
        record = (Path(tmp) / "out" / "record.json").read_bytes()
    steps = [n for n in "12345678" if any(line.startswith(n + ". ") for line in said)]
    xp._check(steps == list("12345678"), f"the private path did not run its eight steps: {steps}")        # noqa: F821
    xp._check(private.leaks(got["record"]) is None, "the record that may leave holds more than a verdict word and hashes")        # noqa: F821
    st["path"] = {"record_sha256": hashlib.sha256(record).hexdigest(), "verdict": got["record"]["verdict"], "arrangement": got["arrangement"]["arrangement"],
                  "counts_as": got["arrangement"]["counts_as"], "files": got["files"], "simulated": True}
    book.say(f"  ok       the private path, eight steps, against the simulator: record {st['path']['record_sha256'][:16]}... ({got['record']['verdict']})")


def simulate(book, st: dict) -> None:
    """The private path as one command, against a simulator: approve, seal, record, sign, check, retain, dispute."""
    _path(book, st)


def run(book, st: dict) -> None:
    """The private path as one command; at the public ids it waits for a run in someone's private repository."""
    if "path" not in st:
        _path(book, st)
    noted = book.w.outside("private")
    if not noted:
        raise xp.Need("a private repository's own run",        # noqa: F821
                      "someone with a private repository installs examples/private/knos-private.yml and runs it; then `python scripts/exercise_public.py note "
                      "private --keys DIR record=<sha256 of that run's record.json> by=<who ran it>`. Nobody has: what ran here is the simulator's path only")
    st["outside"] = dict(noted)
