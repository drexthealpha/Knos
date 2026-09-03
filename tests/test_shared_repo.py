"""The repository is the shared object.

Knos is otherwise local on purpose. But two things exist nowhere a teammate
can reach — what somebody decided, and what somebody is working on now — and
those are exactly what a second clone, or CI, needs.

So `knos export` writes one committed file, and this proves the whole loop:
a maintainer exports, a *second clean clone* reads the same evidence with no
import step, and the CI check fires on a pull request that touches claimed
work. Three sides, one file, no server.
"""

from __future__ import annotations

import pytest

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from knos import answer, paths, share
from knos.memory import TOPIC, Fact, Memory


def _git(where: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(where), check=True, capture_output=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decide(repo: Path, note: str, about: str) -> None:
    with Memory(repo) as mem:
        mem.record(
            Fact(text=note, source="note", where="you said so", when=_now(), about=about)
        )
        mem.note_thing(TOPIC, about, {"note": note, "when": _now()[:10]})


def test_export_writes_decisions_and_claims(knos_home, repo):
    _decide(repo, "we chose sqlite because a server is one more thing to run", "storage")
    with Memory(repo) as mem:
        mem.working_on("the auth refactor", "Claude Code", _now())
        target, decisions, claims = share.write(repo, mem)

    assert target == repo / ".knos" / "decisions.md"
    assert decisions == 1 and claims == 1
    text = target.read_text(encoding="utf-8")
    assert "we chose sqlite" in text
    assert "the auth refactor" in text and "Claude Code" in text


def test_a_second_clean_clone_reads_it_with_no_import_step(knos_home, repo, tmp_path):
    """The whole point. A teammate clones and asks — nothing to install,
    nothing to sync, no shared server."""
    _decide(repo, "we dropped redis because it was one dependency for one counter", "storage")
    with Memory(repo) as mem:
        share.write(repo, mem)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-qm", "share decisions")

    clone = tmp_path / "teammate"
    subprocess.run(
        ["git", "clone", "-q", str(repo), str(clone)], check=True, capture_output=True
    )
    paths.shared_root.cache_clear()
    paths.work_root.cache_clear()

    # A completely separate store, as a different machine would have.
    assert not paths.has_store(clone)
    with Memory(clone) as mem:
        answer.point(clone, mem, index_code=False)
        found = answer.ask(clone, mem, "why did we drop redis")

    assert found, "the clone learned nothing from the committed file"
    assert any(".knos/decisions.md" in p.where for p in found), [p.where for p in found]


def test_a_private_note_never_reaches_the_shared_file(knos_home, repo):
    """The file goes in the repository, so it is only as safe as the check
    that fills it."""
    _decide(repo, "the staging key lives in .env, rotate it monthly", ".env")
    _decide(repo, "we chose sqlite", "storage")
    with Memory(repo) as mem:
        text, decisions, _ = share.export(repo, mem)

    assert "sqlite" in text
    assert ".env" not in text and "staging key" not in text, text
    assert decisions == 1


def test_ci_warns_only_when_the_pull_request_touches_claimed_work(knos_home, repo):
    """The CI half reads the same file, with no knos installed."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "action"))
    import knos_pr_check as check

    with Memory(repo) as mem:
        mem.working_on("the auth refactor", "Cursor", _now())
        text, _, _ = share.export(repo, mem)

    claims = check.read_claims(text)
    assert claims == [("the auth refactor", "Cursor")]

    touching = check.words("Rewrite auth refactoring  src/auth.py")
    assert [t for t, _ in claims if check.words(t) & touching] == ["the auth refactor"]

    unrelated = check.words("Bump pytest in CI  .github/workflows/tests.yml")
    assert [t for t, _ in claims if check.words(t) & unrelated] == []


def test_the_exported_file_survives_a_round_trip(knos_home, repo):
    """CI parses what export wrote. A format change on one side that the
    other does not follow makes the check silently stop firing."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "action"))
    import knos_pr_check as check

    with Memory(repo) as mem:
        mem.working_on("the parser", "Claude Code", _now())
        mem.working_on("the risk guard", "you", _now())
        text, _, claims = share.export(repo, mem)

    assert claims == 2
    assert sorted(check.read_claims(text)) == sorted(
        [("the parser", "Claude Code"), ("the risk guard", "you")]
    )
    assert sorted(share.read_claims(text)) == sorted(check.read_claims(text))


def test_nothing_claimed_means_nothing_to_say(knos_home, repo):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "action"))
    import knos_pr_check as check

    with Memory(repo) as mem:
        text, _, claims = share.export(repo, mem)
    assert claims == 0
    assert check.read_claims(text) == []


def test_the_action_reports_decisions_as_well_as_claims(knos_home, repo):
    """The Action reads both halves of the exported file. A branch that
    reopens a settled decision is worth a line, quieter than a collision."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "action"))
    import knos_pr_check as check

    _decide(repo, "we chose sqlite because a server is one more thing to run", "storage")
    with Memory(repo) as mem:
        text, _, _ = share.export(repo, mem)

    found = check.read_decisions(text)
    assert found == [("storage", "we chose sqlite because a server is one more thing to run")]

    touching = check.words("rework the storage layer  src/storage.py")
    assert [a for a, _ in found if check.words(a) & touching] == ["storage"]

    unrelated = check.words("Bump pytest in CI  .github/workflows/tests.yml")
    assert [a for a, _ in found if check.words(a) & unrelated] == []


def test_the_action_never_returns_non_zero(knos_home, repo):
    """It comments; it does not judge. Every path returns 0, so a memory
    tool can never be the reason a build is red."""
    import re

    source = (Path(__file__).resolve().parents[1] / "action" / "knos_pr_check.py").read_text(
        encoding="utf-8"
    )
    in_main = source.split("def main()", 1)[1].split("__main__", 1)[0]
    returns = set(re.findall(r"^\s+return (\S+)$", in_main, re.M))
    assert returns == {"0"}, returns
    assert "sys.exit(main())" in source
