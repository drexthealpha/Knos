"""Task packages as rows for a training environment (an Atropos BaseEnv) and as
a sealed spec for the referee (knos.referee). A row carries only what the solver may see: the statement, the
repository and base commit, the scope, and the hashes that bind the hidden tests. The reward comes from `score`,
which grades a candidate patch against the sealed tests (knos.taskpack.grade) on the grader's side: a row holds no path to
the package, so a solver given the rows cannot open the hidden tests. Grading runs the candidate's code unsandboxed
(see knos.taskpack.grade): run the grader in a disposable container. Devnet / demo use only.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import export as ex
from . import grade as gr


def row(pack: Path | str) -> dict:
    m = ex.load(pack)
    return {"id": m["task_id"], "spec_sha256": m["spec_sha256"], "prompt": ex.statement(m), "repo": m["source"]["repo"],
            "base_commit": m["source"]["base_commit"], "scope": m["scope"], "sealed_tests_sha256": m["sealed"]["tests_sha256"],
            "hidden_tests": m["sealed"]["tests_count"], "judge": {"kind": ex.FORMAT, "reward": m["judge"]["reward"]},
            "licence": m["licence"]["spdx"]}      # no path to the package: the solver must not be able to reach the sealed files


def rows(packs) -> list[dict]:
    return [row(p) for p in packs]


def write_jsonl(packs, out: Path | str) -> int:
    got = rows(packs)
    Path(out).write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in got), encoding="utf-8")
    return len(got)


def score(r: dict, pack: Path | str, repo: Path | str, patch: str, key: bytes | None = None) -> float:
    """The reward of one candidate patch for one row. `pack`: the package folder, held by the grader only (never put it
    where the solver runs). The row's id must be the package's."""
    if ex.load(pack)["task_id"] != r["id"]:
        raise ex.Refused("the row is not this package's")
    return float(gr.grade(pack, repo, patch, key=key)["reward"])


def referee_spec(pack: Path | str) -> dict:
    """What the referee seals for this task: the spec hash, the hidden tests' hash, the locked judge command and the cheat
    rules. REFEREE's `referee.seal` works on a judge bundle folder; this is the package's side of that binding."""
    m = ex.load(pack)
    return {"spec_hash": m["spec_sha256"], "sealed_tests_sha256": m["sealed"]["tests_sha256"], "judge": m["judge"],
            "cheat_rules": m["cheat_rules"], "scope": m["scope"]["allowed"], "issue": m["source"]["issue"]}
