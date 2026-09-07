"""What a claim does *not* block.

Every other test here asks whether the refusal fires. This asks whether it
stays quiet, which is the more likely way this product dies: under-refusing
loses a collision somebody will probably notice and fix, while over-refusing
gets the hook uninstalled on the first afternoon and never reported.

One ordinary claim - "the parser" - walked past an ordinary tree.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

import pytest

from knos import guard
from knos.memory import Memory

COVERED = [
    "src/parser/lexer.py",
    "src/parser.py",
    "src/parsers/json_parser.py",
    "tests/test_parser.py",
    "docs/parsing.md",
]

UNTOUCHED = [
    "src/renderer/html.py",
    "src/auth/login.py",
    "README.md",
    "package.json",
    "src/utils/strings.py",
    "tests/test_auth.py",
    "src/db/migrations/0004_add_index.py",
    ".github/workflows/ci.yml",
]

# Stemming folds `parse` and `parser` together, so a directory named for
# argument parsing collides with a claim on the language parser. It is a real
# false positive and it is written down here rather than left to be
# discovered: the alternative is exact-word matching, which would stop
# `src/parsers/` matching a claim on "the parser" and lose the collisions
# this exists for. Refusing an edit and naming the holder is recoverable in
# one message; missing the collision is not.
ARGUABLE = "src/parse_args_unrelated_cli/main.py"


@pytest.fixture()
def tree(knos_home, repo):
    for rel in [*COVERED, *UNTOUCHED, ARGUABLE]:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "tree"], cwd=repo, capture_output=True)

    with Memory(repo) as mem:
        mem.working_on("the parser", "Claude Code",
                       datetime.now(timezone.utc).isoformat())
    return repo


@pytest.mark.critical
def test_a_claim_does_not_block_unrelated_work(tree) -> None:
    """The one that decides whether a maintainer keeps the hook installed."""
    refused = [
        rel for rel in UNTOUCHED
        if not guard.check(tree, str(tree / rel), "Cursor").allow
    ]
    assert not refused, (
        "a claim on 'the parser' refused work that has nothing to do with it: "
        + ", ".join(refused)
    )


def test_a_claim_still_covers_what_it_is_about(tree) -> None:
    missed = [
        rel for rel in COVERED
        if guard.check(tree, str(tree / rel), "Cursor").allow
    ]
    assert not missed, "the claim did not reach: " + ", ".join(missed)


def test_the_known_false_positive_is_still_only_this_one(tree) -> None:
    """If stemming ever gets greedier, this is where it shows up first."""
    verdict = guard.check(tree, str(tree / ARGUABLE), "Cursor")
    assert not verdict.allow, (
        "stemming stopped folding parse/parser together — check that "
        "src/parsers/ is still covered by a claim on 'the parser'"
    )
