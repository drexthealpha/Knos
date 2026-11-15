"""What a claim does *not* block.

Every other test asks whether the refusal fires. This asks whether it stays quiet, which is the more likely way this
product dies: under-refusing loses a collision somebody will probably notice, while over-refusing gets the hook
uninstalled on the first afternoon and never reported.

In 0.2.0 a claim is a set of path globs, so precision is glob semantics: `*` and `?` stay inside one directory, `**`
crosses them, `dir/` and a plain directory path mean everything under it, and matching is case-insensitive. Text
similarity never blocks.

Dropped from the 0.1 version of this file, because the behaviour is gone:
  - test_the_known_false_positive_is_still_only_this_one: 0.1 matched a claim's words against file names with
    stemming, so a claim on "the parser" refused src/parse_args_unrelated_cli/. Claims are globs now; that file is in
    UNTOUCHED below and must be allowed, as must every look-alike name.
"""

from __future__ import annotations

import subprocess

import pytest

from knos import guard
from knos.claims import Claims
from knos.identity import Agent

HOLDER = Agent(host="claude", session="holder01-parser")
ASKER = Agent(host="cursor", session="asker001-chat")

GLOBS = ["src/parser/**", "tests/test_parser.py"]

COVERED = [
    "src/parser/lexer.py",
    "src/parser/deep/nested/ast.py",
    "src/parser/__init__.py",
    "tests/test_parser.py",
    "SRC/Parser/Lexer.py",  # case-insensitive, as on the filesystems people actually use
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
    # look-alikes: similar words, different paths
    "src/parser.py",
    "src/parsers/json_parser.py",
    "src/parser_old/lexer.py",
    "src/parse_args_unrelated_cli/main.py",
    "tests/test_parser_extra.py",
    "tests/unit/test_parser.py",
    "docs/parsing.md",
    "docs/src/parser/lexer.md",
]


@pytest.fixture()
def tree(knos_home, repo):
    for rel in [*COVERED[:-1], *UNTOUCHED]:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {rel}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "tree"], cwd=repo, check=True, capture_output=True)
    with Claims(repo) as c:
        took, _, _ = c.take(HOLDER, "the parser rewrite", GLOBS)
    assert took
    return repo


@pytest.mark.critical
def test_a_claim_does_not_block_unrelated_work(tree) -> None:
    """The one that decides whether a maintainer keeps the hook installed."""
    refused = [rel for rel in UNTOUCHED if not guard.check(tree, str(tree / rel), ASKER).allow]
    assert not refused, "a claim on src/parser/** refused work that has nothing to do with it: " + ", ".join(refused)


@pytest.mark.critical
def test_a_claim_still_covers_what_it_is_about(tree) -> None:
    missed = [rel for rel in COVERED if guard.check(tree, str(tree / rel), ASKER).allow]
    assert not missed, "the claim did not reach: " + ", ".join(missed)


def test_the_description_words_never_block(tree) -> None:
    """"the parser rewrite" is prose; only the globs are enforced."""
    for rel in ("rewrite.py", "src/the.py", "parser", "docs/rewrite/parser.md"):
        assert guard.check(tree, str(tree / rel), ASKER).allow, rel


# (glob, covered, not covered)
SEMANTICS = [
    ("src/*.py", ["src/auth.py", "src/new.py"], ["src/sub/x.py", "src/auth.pyc", "auth.py", "src/a/b/c.py"]),
    ("src/**/*.py", ["src/auth.py", "src/a/x.py", "src/a/b/c.py"], ["src/a/notes.md", "lib/src/a.py", "src.py"]),
    ("src/**", ["src/auth.py", "src/a/b/c.md"], ["srcx/a.py", "README.md"]),
    ("**/*.md", ["README.md", "docs/a/b.md"], ["src/auth.py", "README.mdx"]),
    ("src/", ["src/auth.py", "src/a/b/c.md"], ["srcx/a.py", "README.md"]),
    ("src", ["src/auth.py", "src/a/b.py"], ["srcx/a.py", "src.py"]),
    ("src/auth.py", ["src/auth.py", "SRC/AUTH.PY"], ["src/auth.py.bak", "src/auth_test.py", "test/src/auth.py"]),
    ("src/a?.py", ["src/ab.py"], ["src/abc.py", "src/a/.py", "src/a.py"]),
]


@pytest.mark.parametrize("glob,covered,free", SEMANTICS, ids=[s[0] for s in SEMANTICS])
def test_glob_semantics(knos_home, repo, glob, covered, free) -> None:
    """`*` and `?` stay in one directory, `**` crosses them, `dir/` and a plain directory mean everything under it."""
    with Claims(repo) as c:
        assert c.take(HOLDER, f"claim {glob}", [glob])[0]
    wrong_way = [rel for rel in covered if guard.check(repo, str(repo / rel), ASKER).allow]
    wrong_way += [rel for rel in free if not guard.check(repo, str(repo / rel), ASKER).allow]
    assert not wrong_way, f"{glob}: got these wrong: {wrong_way}"


def test_a_leading_dot_slash_or_backslashes_in_a_claim_mean_the_same_path(knos_home, repo) -> None:
    with Claims(repo) as c:
        assert c.take(HOLDER, "auth", ["./src\\auth.py"])[0]
    assert not guard.check(repo, str(repo / "src" / "auth.py"), ASKER).allow
    assert guard.check(repo, str(repo / "README.md"), ASKER).allow
