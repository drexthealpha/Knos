"""Take Sibyl away and Knos remembers nothing.

There is no second store, no cache and no fallback file. What the Stop hook learned from a past false "done", and
what the judge learned from a tampering pull request, live only in Sibyl's memory engine (sibyl-memory-client). These
tests break that on purpose and show the behaviour changing. Read this file first if you want to know whether the
memory is real.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest
from _host_events import EVENTS, NEEDS_CWD, deliver, reason

from knos import judge, store
from knos.proof import checks, engine, history, hook

FALSE_DONE = "Knos 9.9.9 is shipped: tagged, on PyPI, tests pass."


def _runners(ci_ok: bool = True) -> dict:
    ok = lambda name, good=True: (lambda repo, claim, cfg: checks.Result(name, good, name, {"sha": "abc"}))  # noqa: E731
    return {"tests": ok("tests"), "pypi": ok("pypi"), "author": ok("author"), "ci": ok("ci", ci_ok)}


def _teach(repo: Path) -> None:
    """A release was called done while its CI then failed: Sibyl learns that a release claim here needs CI."""
    st = history.SibylStore.for_repo(repo)
    engine.evaluate(repo, FALSE_DONE, st, _runners(), use_cache=False)
    history.observe(st, checks.head(repo), "ci", False, "CI failed after the release")
    assert {r["require"] for r in history.learn(st)} == {"ci"}


def test_the_stop_hook_blocks_because_of_what_sibyl_remembers(knos_home, repo):
    payload = {"cwd": str(repo), "session_id": "s", "last_assistant_message": FALSE_DONE}
    red_ci = _runners(ci_ok=False)                 # the message never mentions CI; only memory makes Knos look
    assert hook.stop(payload, history.NullStore(), red_ci)[0] == "allow"
    assert hook.stop(payload, history.SibylStore.for_repo(repo), red_ci)[0] == "allow"   # nothing learned yet
    _teach(repo)
    verdict, why = hook.stop(payload, history.SibylStore.for_repo(repo), red_ci)
    assert verdict == "block" and "required by this repo's history" in why
    assert hook.stop(payload, history.NullStore(), red_ci)[0] == "allow"                 # same hook, no Sibyl: lets it by


def test_what_was_learned_is_in_sibyls_own_store_and_nowhere_else(knos_home, repo):
    _teach(repo)
    db = store.shared_store()
    assert db.name == "memory.db" and db.parent.name == ".sibyl-memory"      # Sibyl's own store, under Sibyl's cap
    with contextlib.closing(sqlite3.connect(db)) as con:     # closed before the file is deleted: Windows locks an open one
        rows = con.execute("select count(*) from entities where tenant_id = ?", (store.tenant(repo),)).fetchone()
    assert rows[0] >= 3                                                      # the claim, the outcome, the rule
    assert not list(knos_home.rglob("*.db")) and not (repo / ".knos").exists()   # no copy anywhere else
    for f in db.parent.glob("memory.db*"):
        f.unlink()
    assert history.rules(history.SibylStore.for_repo(repo)) == []           # delete Sibyl's store: the rule is gone


def test_a_broken_store_is_not_papered_over(knos_home, repo):
    _teach(repo)
    db = store.shared_store()
    for f in db.parent.glob("memory.db-*"):
        f.unlink()
    db.write_bytes(b"this is not a database")
    with pytest.raises(sqlite3.DatabaseError):
        history.rules(history.SibylStore.for_repo(repo))


def test_without_the_sibyl_package_there_is_no_memory_at_all(knos_home, repo, monkeypatch):
    monkeypatch.setitem(sys.modules, "sibyl_memory_client", None)           # as if it were not installed
    with pytest.raises(ImportError):
        history.SibylStore.for_repo(repo)
    with pytest.raises(ImportError):
        history.SibylStore.local(knos_home / "judge")
    payload = {"cwd": str(repo), "session_id": "s2", "last_assistant_message": FALSE_DONE}
    assert hook.stop(payload, None, _runners(ci_ok=False))[0] == "allow"    # the hook still runs, and has learned nothing


def test_sibyls_free_tier_cap_is_sibyls_to_enforce(knos_home, repo, monkeypatch):
    """Knos hands Sibyl's own cap gate the size of the stores on this machine and does not route around it."""
    import sibyl_memory_client._capcheck as capcheck
    from sibyl_memory_client import FREE_TIER_CAP_BYTES, CapExceededError
    st = history.SibylStore.for_repo(repo)
    st.put("proof_rule", "a", {"when": "release", "require": "ci"})
    monkeypatch.setattr(capcheck, "aggregate_db_size", lambda *_a, **_k: FREE_TIER_CAP_BYTES + 1)
    full = history.SibylStore.for_repo(repo)
    with pytest.raises(CapExceededError):
        full.put("proof_rule", "b", {"when": "release", "require": "ci"})
    creds = knos_home / "credentials.json"
    creds.write_text(json.dumps({"account_id": "acct_test", "session_token": "tok_test"}), encoding="utf-8")
    monkeypatch.setenv("SIBYL_CREDENTIALS", str(creds))
    assert store.account() == {"account_id": "acct_test", "session_token": "tok_test"}   # handed to Sibyl's gate only


DIFF = ("diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,4 @@\n def add(a, b):\n"
        "     return a + b\n+def mul(a, b):\n+    print(a, b)\n")


def test_the_judge_on_github_refuses_a_second_pull_request_because_of_what_sibyl_kept(tmp_path):
    """The judge on GitHub keeps Sibyl's local store <dir>/sibyl.db. A pull request that broke the repository's rule
    teaches it; the same author's next pull request, to a repository with no such rule, is refused for it. With
    that store gone, nothing was learned."""
    strict = tmp_path / "strict"
    strict.mkdir()
    (strict / "CONTRIBUTING.md").write_text("# Rules\n\n- Do not leave print() debug statements in code.\n", "utf-8")
    lax = tmp_path / "lax"
    lax.mkdir()
    mem = history.SibylStore.local(tmp_path / "cache")
    first = judge.gate(strict, DIFF, mem, "o/strict", "agent-x")
    assert not first["passed"] and first["reasons"][0].startswith("repo rule:")
    again = judge.gate(lax, DIFF, history.SibylStore.local(tmp_path / "cache"), "o/lax", "agent-x")
    assert not again["passed"] and again["evidence"]["required_by_history"] == ["tamper:rule:no_debug"]
    assert judge.gate(lax, DIFF, history.NullStore(), "o/lax", "agent-x")["passed"]
    shutil.rmtree(tmp_path / "cache")
    assert judge.gate(lax, DIFF, history.SibylStore.local(tmp_path / "cache"), "o/lax", "agent-x")["passed"]
    assert (tmp_path / "cache" / "sibyl.db").exists()


def test_the_lessons_in_the_knos_memory_issue_are_nothing_without_sibyl(tmp_path, monkeypatch):
    """Between runs on GitHub the lessons travel as comments in the repository's knos-memory issue (the Actions cache
    can no longer be written from the runs that judge). A run loads them into Sibyl's store and judges from there.
    The same comments with no Sibyl behind them remember nothing: they are not a second store."""
    from _hub import Issues
    from knos.proof import memory
    strict = tmp_path / "strict"
    strict.mkdir()
    (strict / "CONTRIBUTING.md").write_text("# Rules\n\n- Do not leave print() debug statements in code.\n", "utf-8")
    lax = tmp_path / "lax"
    lax.mkdir()
    github = Issues()
    run1 = history.SibylStore.local(tmp_path / "run1")
    assert not judge.gate(strict, DIFF, run1, "o/strict", "agent-x")["passed"]
    assert memory.push("o/r", run1, github, github) == 3                    # the tamper, and the check it made required twice over
    shutil.rmtree(tmp_path / "run1")                                        # the runner is gone; only the issue is left
    assert judge.gate(lax, DIFF, history.SibylStore.local(tmp_path / "run2"), "o/lax", "agent-x")["passed"]   # nothing loaded: nothing known
    run3 = history.SibylStore.local(tmp_path / "run3")
    assert memory.pull("o/r", run3, github) == 3
    again = judge.gate(lax, DIFF, run3, "o/lax", "agent-x")
    assert not again["passed"] and again["evidence"]["required_by_history"] == ["tamper:rule:no_debug"]
    with contextlib.closing(sqlite3.connect(tmp_path / "run3" / "sibyl.db")) as con:     # what was pulled is in Sibyl's own store
        assert con.execute("select count(*) from entities where category = 'proof_rule'").fetchone()[0] >= 2
    assert memory.pull("o/r", history.NullStore(), github) == 3                           # the same comments, with no Sibyl
    assert judge.gate(lax, DIFF, history.NullStore(), "o/lax", "agent-x")["passed"]
    monkeypatch.setitem(sys.modules, "sibyl_memory_client", None)                         # as if it were not installed
    with pytest.raises(ImportError):
        history.SibylStore.local(tmp_path / "run4")


DONE = "The parser is finished and released."        # says nothing of tests: only what was refused before makes Knos run them


def _tests(good: bool) -> dict:
    return {**_runners(), "tests": lambda repo, claim, cfg: checks.Result("tests", good, "ok" if good else "3 failed in test_calc.py", {})}


def test_what_was_refused_last_session_is_owed_in_the_next_and_only_sibyl_knows_it(knos_home, repo):
    """Session one says "tests pass" and they fail: refused, and the refusal goes to Sibyl's journal with the running
    count in its state document. Session two says only "finished": the check that failed is run anyway and the stop is
    blocked with what failed last time. The same stop with no Sibyl, or with Sibyl's store deleted, is allowed."""
    one = {"cwd": str(repo), "session_id": "one", "last_assistant_message": "All tests pass."}
    two = {"cwd": str(repo), "session_id": "two", "last_assistant_message": DONE}
    assert hook.stop(two, history.SibylStore.for_repo(repo), _tests(False))[0] == "allow"      # nothing remembered yet
    assert hook.stop(one, history.SibylStore.for_repo(repo), _tests(False))[0] == "block"
    st = history.SibylStore.for_repo(repo)
    assert history.owed(st) == {"tests"} and history.track(st)["refused"] == 1
    assert history.recall(st, "test_calc") == ["refused: tests (3 failed in test_calc.py)"]   # Sibyl's FTS5, in the journal
    verdict, why = hook.stop(two, history.SibylStore.for_repo(repo), _tests(False))
    assert verdict == "block" and "3 failed in test_calc.py" in why and "an earlier claim here was refused on it" in why
    assert "Knos refused 1 of 2 claims of done" in why                      # the first stop was a claim too, and held
    assert hook.stop(two, history.NullStore(), _tests(False))[0] == "allow"                    # same hook, no Sibyl
    db = store.shared_store()
    with contextlib.closing(sqlite3.connect(db)) as con:
        assert con.execute("select count(*) from journal_events where tenant_id = ?", (store.tenant(repo),)).fetchone()[0] == 3   # one event per verdict
    for f in db.parent.glob("memory.db*"):
        f.unlink()
    assert hook.stop(two, history.SibylStore.for_repo(repo), _tests(False))[0] == "allow"      # Sibyl's store gone: nothing owed


def test_a_check_is_owed_until_it_is_seen_passing_and_an_edited_journal_changes_the_outcome(knos_home, repo):
    one = {"cwd": str(repo), "session_id": "one", "last_assistant_message": "All tests pass."}
    two = {"cwd": str(repo), "session_id": "two", "last_assistant_message": DONE}
    assert hook.stop(one, history.SibylStore.for_repo(repo), _tests(False))[0] == "block"
    assert hook.stop(two, history.SibylStore.for_repo(repo), _tests(True))[0] == "allow"       # run because owed, and it passes
    assert history.owed(history.SibylStore.for_repo(repo)) == set()                           # seen passing: no longer owed
    assert hook.stop(two, history.SibylStore.for_repo(repo), _tests(False))[0] == "allow"      # so a bare "finished" is not re-run
    assert hook.stop(one, history.SibylStore.for_repo(repo), _tests(False))[0] == "block"      # refused again: owed again
    with contextlib.closing(sqlite3.connect(store.shared_store())) as con:                     # someone edits Sibyl's journal by hand
        con.execute("update journal_events set extra = replace(extra, '\"failed\":[\"tests\"]', '\"failed\":[]')")
        con.commit()
    assert history.owed(history.SibylStore.for_repo(repo)) == set()
    assert hook.stop(two, history.SibylStore.for_repo(repo), _tests(False))[0] == "allow"      # the memory decided it, so the edit did too


def _hosts() -> list:
    """Every host the hook answers; `unconfirmed` where the host's page does not state all of its event (tests/_host_events.py)."""
    return [pytest.param(c, id=c if EVENTS[c][1] else f"{c}-unconfirmed") for c in sorted(EVENTS)]


def _edit_the_journal() -> None:
    with contextlib.closing(sqlite3.connect(store.shared_store())) as con:
        con.execute("update journal_events set extra = replace(extra, '\"failed\":[\"tests\"]', '\"failed\":[]')")
        con.commit()


@pytest.mark.parametrize("client", _hosts())
def test_in_every_host_the_answer_is_sibyls_memory_and_changes_when_it_is_gone_or_edited(client, knos_home, repo, monkeypatch):
    """The same two sessions as above, through each host's own event and read back as that host reads the answer.
    Session two's message says nothing of tests. What sends the agent back (or, in a host that cannot hold a turn,
    what the person is shown) is the check Sibyl remembers failing, with the record of it. The same event with no
    Sibyl, with the journal edited by hand, or with the store deleted, gets no answer at all."""
    if client in NEEDS_CWD:
        monkeypatch.chdir(repo)
    sibyl = lambda: history.SibylStore.for_repo(repo)  # noqa: E731
    two = lambda st: deliver(client, repo, DONE, st, _tests(False), "-two")  # noqa: E731
    assert two(sibyl()) == ("", 0)                                               # nothing remembered yet
    assert "3 failed in test_calc.py" in reason(client, deliver(client, repo, "All tests pass.", sibyl(), _tests(False), "-one")[0])
    out, code = two(sibyl())
    why = reason(client, out)
    assert code == 0 and "3 failed in test_calc.py" in why and "an earlier claim here was refused on it" in why
    assert "Knos refused 1 of 2 claims of done" in why and "The last refusal" in why   # the briefing, in this host's answer
    assert two(history.NullStore()) == ("", 0)                                   # same event, no Sibyl
    _edit_the_journal()
    assert two(sibyl()) == ("", 0)                                               # the edited memory decided it
    assert reason(client, deliver(client, repo, "All tests pass.", sibyl(), _tests(False), "-one")[0])    # refused again: owed again
    assert reason(client, two(sibyl())[0])
    for f in store.shared_store().parent.glob("memory.db*"):
        f.unlink()
    assert two(sibyl()) == ("", 0)                                               # Sibyl's store gone: nothing owed


def test_aiders_test_command_says_what_sibyl_remembers_and_not_a_word_of_it_without(knos_home, repo, monkeypatch):
    """aider has no message, so its test command always stands for "tests pass" and fails when they do, memory or
    not. What the memory adds is what the model is given with the failure: the record of refusals here."""
    monkeypatch.chdir(repo)
    sibyl = lambda: history.SibylStore.for_repo(repo)  # noqa: E731
    first, code = deliver("aider", repo, "", sibyl(), _tests(False))
    assert code == 1 and "3 failed in test_calc.py" in first and "Knos refused" not in first
    again, code = deliver("aider", repo, "", sibyl(), _tests(False))
    assert code == 1 and "Knos refused 1 of 1 claims of done" in again and "Still owed, whatever the message says: tests" in again
    bare, code = deliver("aider", repo, "", history.NullStore(), _tests(False))
    assert code == 1 and "Knos refused" not in bare and "Still owed" not in bare
    _edit_the_journal()
    edited, _ = deliver("aider", repo, "", sibyl(), _tests(False))
    assert "Knos refused" in edited and "Still owed" not in edited               # the edit took the debt out of the answer


# ---- which terms worked: the template a funding reply proposes is Sibyl's memory of how past orders here ended ----

def _three_orders(mem) -> None:
    """Three orders in o/r, each funded with the published `bugfix` template, version 1: two were refused on `lint`
    before a second pull request fixed it, one was accepted first time."""
    history.order_outcome(mem, "o/r", "7", "fixed", "bugfix", 1, failed=["lint"], seq=7)
    history.order_outcome(mem, "o/r", "9", "accepted", "bugfix", 1, seq=9)
    history.order_outcome(mem, "o/r", "12", "fixed", "bugfix", 1, failed=["lint", "unit"], seq=12)


def test_the_template_a_funding_reply_proposes_is_what_sibyl_remembers_of_past_orders(tmp_path):
    """The one line a funding reply adds about terms comes from how the last orders here ended, kept in Sibyl's
    store. With no memory there is no line; with the store deleted there is none; another repository gets none."""
    line = "last 3 orders here: 2 refused on `lint` first; `bugfix` v1 with `lint` named"
    assert history.terms_supported(history.SibylStore.local(tmp_path / "m"), "o/r") == ""      # nothing remembered: no claim
    _three_orders(history.SibylStore.local(tmp_path / "m"))
    assert history.terms_supported(history.SibylStore.local(tmp_path / "m"), "o/r") == line     # a new client, the same store
    assert history.terms_supported(history.SibylStore.local(tmp_path / "m"), "someone/else") == ""
    assert history.terms_supported(history.NullStore(), "o/r") == ""                           # the same question, no Sibyl
    with contextlib.closing(sqlite3.connect(tmp_path / "m" / "sibyl.db")) as con:              # it is in Sibyl's own store
        assert con.execute("select count(*) from entities where category = 'order'").fetchone()[0] == 3
    assert not [p for p in tmp_path.rglob("*") if p.is_file() and not p.name.startswith("sibyl.db")]   # and nowhere else
    shutil.rmtree(tmp_path / "m")
    assert history.terms_supported(history.SibylStore.local(tmp_path / "m"), "o/r") == ""      # Sibyl's store gone: no line


def test_the_proposal_follows_the_memory_when_an_order_ends_another_way(tmp_path):
    mem = history.SibylStore.local(tmp_path / "m")
    _three_orders(mem)
    history.order_outcome(mem, "o/r", "12", "reverted", "bugfix", 1, seq=12)    # the last one is reverted in its warranty
    history.order_outcome(mem, "o/r", "15", "reverted", "bugfix", 1, seq=15)
    assert [b["outcome"] for b in history.orders(mem, "o/r")] == ["fixed", "accepted", "reverted", "reverted"]   # an order counts once, as it ended last
    assert history.terms_supported(mem, "o/r") == "last 3 orders here: 2 reverted in warranty; `milestone` v1, holding a share back"
    assert history.terms_supported(mem, "o/r", versions={"milestone": 2}).endswith("`milestone` v2, holding a share back")
    history.order_outcome(mem, "o/r", "16", "disputed", "milestone", 1, policy="ab" * 32, seq=16)
    history.order_outcome(mem, "o/r", "17", "accepted", "milestone", 1, policy="ab" * 32, seq=17)
    assert history.terms_supported(mem, "o/r", policy="ab" * 32) == "last 2 orders here: 1 disputed; `feature-blackbox` v1, paying on a black-box suite"
    assert history.terms_supported(mem, "o/r", policy="cd" * 32) == ""          # no order was judged under that policy version
    clean = history.SibylStore.local(tmp_path / "clean")
    history.order_outcome(clean, "o/r", "1", "accepted", "milestone", 2)
    assert history.terms_supported(clean, "o/r") == "last 1 order here: 1 accepted first time; `milestone` v2 again"
    with pytest.raises(ValueError):
        history.order_outcome(clean, "o/r", "2", "paid twice", "milestone", 2)


def test_an_edited_order_memory_changes_the_proposal_and_a_row_that_lies_about_its_name_is_dropped(tmp_path):
    """Someone edits Sibyl's store by hand. Rewriting which check the orders were refused on changes the line:
    the memory decided it, so the edit did too. Rewriting an outcome makes the row say something its name does
    not, and such a row is no memory of an order: the line loses it."""
    mem = lambda: history.SibylStore.local(tmp_path / "m")  # noqa: E731
    _three_orders(mem())
    db = tmp_path / "m" / "sibyl.db"
    with contextlib.closing(sqlite3.connect(db)) as con:
        con.execute("update entities set body = replace(body, 'lint', 'types') where category = 'order'")
        con.commit()
    assert history.terms_supported(mem(), "o/r") == "last 3 orders here: 2 refused on `types` first; `bugfix` v1 with `types` named"
    with contextlib.closing(sqlite3.connect(db)) as con:
        con.execute("update entities set body = replace(body, '\"fixed\"', '\"accepted\"') where category = 'order'")
        con.commit()
    assert history.terms_supported(mem(), "o/r") == "last 1 order here: 1 accepted first time; `bugfix` v1 again"
    with contextlib.closing(sqlite3.connect(db)) as con:
        con.execute("delete from entities where category = 'order'")
        con.commit()
    assert history.terms_supported(mem(), "o/r") == ""


def test_order_outcomes_travel_in_the_knos_memory_issue_and_are_nothing_without_sibyl(tmp_path):
    from _hub import Issues
    from knos.proof import memory
    github = Issues()
    run1 = history.SibylStore.local(tmp_path / "run1")
    _three_orders(run1)
    assert memory.push("o/r", run1, github, github) == 3
    shutil.rmtree(tmp_path / "run1")
    run2 = history.SibylStore.local(tmp_path / "run2")
    assert history.terms_supported(run2, "o/r") == ""                           # nothing loaded: nothing claimed
    assert memory.pull("o/r", run2, github) == 3
    assert history.terms_supported(run2, "o/r") == "last 3 orders here: 2 refused on `lint` first; `bugfix` v1 with `lint` named"
    assert memory.pull("o/r", history.NullStore(), github) == 3                 # the same comments, with no Sibyl behind them
    assert history.terms_supported(history.NullStore(), "o/r") == ""
    forged = {"category": "order", "name": "0" * 24, "body": {**history.orders(run2, "o/r")[0], "outcome": "disputed"}}
    assert history.lesson(forged) is None                                       # a lesson whose name is not made of what it says
