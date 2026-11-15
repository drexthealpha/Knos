"""The repository is the shared object.

Knos is otherwise local on purpose. But two things exist nowhere a teammate
can reach — what somebody decided, and what somebody is working on now — and
those are exactly what a second clone needs.

So `knos export` writes one committed file, and this proves the loop: a
maintainer exports, a *second clean clone* reads the same decisions with no
import step, and the file parses back (share.read_decisions) into
exactly what was written, whatever a stranger commits to it.

0.2.0: claims come from claims.db (description, who, since, globs). The GitHub Action / CI pull-request warning is gone
from the product (no action/ folder). Dropped with it:
  - test_ci_warns_only_when_the_pull_request_touches_claimed_work
  - test_the_action_reports_decisions_as_well_as_claims
  - test_a_wall_of_claims_is_capped_the_way_decisions_are
  - test_the_action_never_returns_non_zero
The hostile-input test used to run the Action as a subprocess; it now feeds the same inputs to the parsers
(share.read_decisions) and to share.restore, and the round-trip test checks share's own parsers.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from knos import answer, paths, share
from knos.claims import Claims
from knos.cli import main
from knos.identity import Agent
from knos.memory import TOPIC, Fact, Memory

CLAUDE = Agent(host="claude", session="aaaa1111bbbb")
CURSOR = Agent(host="cursor", session="cccc2222dddd")


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


def _claim(repo: Path, agent: Agent, what: str, globs: list[str]) -> None:
    with Claims(repo) as c:
        took, _, _ = c.take(agent, what, globs)
    assert took


def test_export_writes_decisions_and_claims(knos_home, repo):
    _decide(repo, "we chose sqlite because a server is one more thing to run", "storage")
    _claim(repo, CLAUDE, "the auth refactor", ["src/auth.py"])
    with Memory(repo) as mem:
        target, decisions, claims = share.write(repo, mem)

    assert target == repo / ".knos" / "decisions.md"
    assert decisions == 1 and claims == 1
    text = target.read_text(encoding="utf-8")
    assert "we chose sqlite" in text
    line = next(x for x in text.splitlines() if x.startswith("- `the auth refactor`"))
    assert "held by **claude/aaaa1111**" in line, line
    assert "(src/auth.py)" in line, line
    assert " since 20" in line and " UTC " in line, line


def test_a_released_claim_is_not_exported(knos_home, repo):
    _claim(repo, CLAUDE, "the auth refactor", ["src/auth.py"])
    with Claims(repo) as c:
        c.release(CLAUDE)
    with Memory(repo) as mem:
        text, _, claims = share.export(repo, mem)
    assert claims == 0
    assert "_Nothing claimed._" in text
    assert "the auth refactor" not in text


def test_knos_export_says_what_it_wrote(knos_home, repo, capsys):
    _decide(repo, "we chose sqlite", "storage")
    _claim(repo, CLAUDE, "the auth refactor", ["src/auth.py"])
    capsys.readouterr()

    assert main(["export"]) == 0
    said = capsys.readouterr().out
    assert "Wrote .knos/decisions.md: 1 decisions, 1 claimed." in said, said
    assert (repo / ".knos" / "decisions.md").is_file()


@pytest.mark.critical
def test_a_bought_payload_does_not_take_over_the_shared_file(knos_home, repo):
    """What an agent pays for is a whole API response, kept in full.

    The store should have all of it. The file other people commit should
    not: a decision is a sentence, and a repo's decision record is not the
    place for a JSON body and a receipt.
    """
    bought = (
        "Bought over x402 on Base. Receipt: " + "e" * 200
        + "\n\n" + '{"symbol": "BTC", "price_usd": 81067.7, "why": ["'
        + "x" * 4000 + '"]}'
    )
    _decide(repo, bought, "market brief: BTC")
    with Memory(repo) as mem:
        target, decisions, claims = share.write(repo, mem)

    text = target.read_text(encoding="utf-8")
    assert "Bought over x402 on Base" in text
    assert "price_usd" not in text
    assert "x" * 100 not in text
    assert len(text) < 2000

    with Memory(repo) as mem:
        kept = [n["note"] for n in mem.notes()]
    assert any("price_usd" in note for note in kept)


def test_a_decision_someone_wrote_by_hand_is_never_truncated(knos_home, repo):
    written = (
        "Claims lapse after 30 minutes, or on knos done. The lapse is "
        "deliberate: a crashed agent must not be able to hold work forever, "
        "and nobody should have to know which process died to get on with a "
        "refactor that is already half finished on their disk."
    )
    _decide(repo, written, "claim lapse")
    with Memory(repo) as mem:
        target, _, _ = share.write(repo, mem)

    assert written in target.read_text(encoding="utf-8")


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


def test_the_exported_file_survives_a_round_trip(knos_home, repo):
    """The parsers read what export wrote. A format change on one side that the
    other does not follow makes restore silently recover nothing."""
    _decide(repo, "we chose sqlite because a server is one more thing to run", "storage")
    _claim(repo, CLAUDE, "the parser", ["src/auth.py"])
    _claim(repo, CURSOR, "the risk guard", ["README.md"])
    with Memory(repo) as mem:
        text, decisions, claims = share.export(repo, mem)

    assert (decisions, claims) == (1, 2)
    assert "the parser" in text and "the risk guard" in text
    assert share.read_decisions(text) == [
        ("storage", "we chose sqlite because a server is one more thing to run", _now()[:10])
    ]


def test_nothing_claimed_and_nothing_decided_means_nothing_parsed(knos_home, repo):
    with Memory(repo) as mem:
        text, decisions, claims = share.export(repo, mem)
    assert (decisions, claims) == (0, 0)
    assert share.read_decisions(text) == []


def test_export_can_write_where_the_repo_already_keeps_decisions(knos_home, repo):
    """`--to`, because insisting on `.knos/` was the objection maintainers had.

    A repo that already has `docs/decisions/` was being asked to carry a
    second convention at its root, named after this tool. It can write into
    the one it has instead, and that path is still read back because
    `rules.DECISIONS` already matches it.
    """
    with Memory(repo) as mem:
        mem.note_thing(TOPIC, "sqlite", {"note": "chosen over postgres", "when": "2026-08-20"})
        target, _, _ = share.write(repo, mem, "docs/decisions/0001-knos.md")

    assert target == repo / "docs" / "decisions" / "0001-knos.md"
    assert target.is_file()
    assert share.read_back(repo, target), "a path knos already reads must read back"
    assert not (repo / ".knos" / "decisions.md").exists()


def test_export_says_so_when_it_will_not_read_the_file_back(knos_home, repo, capsys):
    """A file knos cannot read back is still useful to people, and saying
    nothing is how somebody discovers weeks later that the loop never closed."""
    with Memory(repo) as mem:
        target, _, _ = share.write(repo, mem, "NOTES-for-humans.md")

    assert target.is_file()
    assert not share.read_back(repo, target)

    capsys.readouterr()
    assert main(["export", "--to", "NOTES-for-humans.md"]) == 0
    assert "knos will not read NOTES-for-humans.md back" in capsys.readouterr().out


def test_export_refuses_to_write_outside_the_repo(knos_home, repo):
    """Almost certainly a typo, and git would never carry the result."""
    with Memory(repo) as mem:
        with pytest.raises(ValueError):
            share.write(repo, mem, "../escaped.md")
    assert not (repo.parent / "escaped.md").exists()


# Named, because pytest puts the parameter in the test id and also exports
# that id in PYTEST_CURRENT_TEST - and a 200,000 character payload as a
# parameter overruns the limit on a Windows environment variable, failing in
# teardown after the test itself has passed.
#
# Each entry: (file body or None, the decisions the parser must find, the claims it must find).
HOSTILE = {
    "no file at all": (None, [], []),
    "empty": ("", [], []),
    "bytes, not markdown": ("\x00\x01\x02 binary-ish", [], []),
    "a very long single line": ("# " + "x" * 200_000, [], []),
    "a table that lies about its shape": ("|||\n|---|\n|" + "a|" * 3000, [], []),
    "control characters and emoji": ("# ‮ decisions \U0001f600\n- \u0007claim\n", [], []),
    "html that wants to be a comment": ("<script>x</script>\n<!-- knos-pr-check -->\n", [], []),
    "large, under no heading knos reads": ("# Decisions\n" + "- something claimed\n" * 20_000, [], []),
    "half-written lines among good ones": (
        "## Decisions\n"
        "- **storage** — we chose sqlite  _(recorded 2026-09-01)_\n"
        "- **broken line with no separator\n"
        "- ** — \n"
        "- **deploys** — on Tuesdays\n"
        "## Being worked on right now\n"
        "- `the parser` — held by **claude/aaaa1111** since 2026-09-06 10:00 UTC (src/parser/**)\n"
        "- `no holder here`\n"
        "- `` — held by **nobody**\n",
        [("storage", "we chose sqlite", "2026-09-01"), ("deploys", "on Tuesdays", "")],
        [("the parser", "claude/aaaa1111")],
    ),
    "a wall of claims": (
        "## Being worked on right now\n"
        + "".join(f"- `stage {n}` — held by **claude/aaaa1111** since 2026-09-06 10:00 UTC (src/{n}.py)\n"
                  for n in range(2000)),
        [],
        [(f"stage {n}", "claude/aaaa1111") for n in range(2000)],
    ),
}


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_the_parsers_survive_whatever_is_committed(knos_home, repo, name):
    """`.knos/decisions.md` is a file a stranger contributes, so it is exactly the input nobody controls.

    The parsers are tolerant by design: a line that does not parse is skipped, and what does parse comes back exactly.
    Restore goes through the same parser and must not raise either.
    """
    body, decisions, claims = HOSTILE[name]
    if body is not None:
        (repo / ".knos").mkdir(parents=True, exist_ok=True)
        (repo / ".knos" / "decisions.md").write_text(body, encoding="utf-8", errors="replace")

        assert share.read_decisions(body) == decisions

    with Memory(repo) as mem:
        kept, skipped = share.restore(repo, mem)
        assert kept == len(decisions)
        assert skipped == 0
        for about, note, _ in decisions:
            got = mem.thing(TOPIC, about)
            assert got is not None and got["body"]["note"] == note, got
