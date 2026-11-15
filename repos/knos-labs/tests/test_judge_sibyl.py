"""prove.yml's judge remembers tampering in Sibyl's own local store (the cached .knos-memory/sibyl.db), offline.

Two tampering PRs by the same agent, in sequence. The first breaks repo A's CONTRIBUTING rule (a debug print) and is
refused by that rule. The second does the same thing in repo B, whose CONTRIBUTING says nothing about prints: by
default no check looks for it, so with no memory (NullStore) it gets through; with the Sibyl store the first refusal
taught `tamper:rule:no_debug` for that agent, and the second PR is refused citing it.
"""

from __future__ import annotations

import time
from pathlib import Path

from knos.jobs import prove
from knos.proof import history

PRINT_DIFF = ("diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,5 @@\n def add(a, b):\n"
              "     return a + b\n+def mul(a, b):\n+    print(a, b)\n+    return a * b\n")


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode())


def _pair(root: Path, contributing: str) -> tuple[Path, Path]:
    base, pr = root / "base", root / "pr"
    for d in (base, pr):
        _w(d / "tests" / "test_calc.py", "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n")
        _w(d / ".knos" / "acceptance" / "1" / "test_accept.py",
           "import calc\n\n\ndef test_mul():\n    assert calc.mul(2, 3) == 6\n")
        _w(d / "CONTRIBUTING.md", contributing)
        _w(d / "pytest.ini", "[pytest]\npythonpath = .\n")
    _w(base / "calc.py", "def add(a, b):\n    return a + b\n")
    _w(pr / "calc.py", "def add(a, b):\n    return a + b\ndef mul(a, b):\n    print(a, b)\n    return a * b\n")
    return base, pr


def _two_prs(tmp_path: Path, store) -> tuple[dict, dict]:
    a_base, a_pr = _pair(tmp_path / "a", "# Rules\n\n- Do not leave print() debug statements in code.\n")
    first = prove.judge_with_rules(a_base, a_pr, {"issue": "1"}, ["calc.py"], PRINT_DIFF, store, "o/a", "bot")
    b_base, b_pr = _pair(tmp_path / "b", "# Contributing\n\nBe kind.\n")
    second = prove.judge_with_rules(b_base, b_pr, {"issue": "1"}, ["calc.py"], PRINT_DIFF, store, "o/b", "bot")
    return first, second


def test_null_store_lets_the_second_tamper_through(tmp_path):
    first, second = _two_prs(tmp_path, history.NullStore())
    assert not first["passed"] and first["reasons"][0].startswith("repo rule: calc.py:4")
    assert second["passed"], second["reasons"]
    assert second["evidence"]["required_by_history"] == []


def test_sibyl_store_refuses_the_second_tamper_citing_the_learned_check(tmp_path):
    cache = tmp_path / ".knos-memory"   # what prove.yml restores from and saves to the Actions cache
    first, _ = _two_prs(tmp_path / "run1", history.SibylStore.local(cache))
    assert not first["passed"] and first["evidence"]["learned"] == ["tamper:rule:no_debug"]
    assert (cache / "sibyl.db").is_file()
    # a later run of the workflow: the store reopened from the restored cache directory
    b_base, b_pr = _pair(tmp_path / "run2" / "b", "# Contributing\n\nBe kind.\n")
    second = prove.judge_with_rules(b_base, b_pr, {"issue": "1"}, ["calc.py"], PRINT_DIFF,
                                    history.SibylStore.local(cache), "o/b", "bot")
    assert not second["passed"]
    assert second["evidence"]["required_by_history"] == ["tamper:rule:no_debug"]
    assert "tamper:rule:no_debug required by history" in second["reasons"][0]
    assert second["reasons"][0].startswith("repo rule: calc.py:4")


def test_sibyl_local_store_timing(tmp_path):
    t0 = time.perf_counter()
    s = history.SibylStore.local(tmp_path / ".knos-memory")
    t1 = time.perf_counter()
    history.learn_tamper(s, "o/a", "bot", "rule:no_debug", "calc.py:4: print(a, b)")
    t2 = time.perf_counter()
    got = history.tamper_checks_required(history.SibylStore.local(tmp_path / ".knos-memory"), "o/b", "bot")
    t3 = time.perf_counter()
    assert got == {"tamper:rule:no_debug"}
    print(f"\nsibyl local store: open {1000 * (t1 - t0):.1f} ms, write {1000 * (t2 - t1):.1f} ms, "
          f"reopen+read {1000 * (t3 - t2):.1f} ms")
