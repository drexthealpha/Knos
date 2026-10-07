"""The judge's memory between runs, without the Actions cache: its lessons travel in the repository's `knos-memory`
issue, and Sibyl's store is still the only thing that remembers. Only what GitHub Actions wrote, and nobody edited,
is read back."""

from __future__ import annotations

import json
import re

import pytest

from _hub import BOT, Issues, user
from knos import judge
from knos.cli import main
from knos.proof import history, memory

DIFF = ("diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,4 @@\n def add(a, b):\n"
        "     return a + b\n+def mul(a, b):\n+    print(a, b)\n")
MONA = user("mona", 4242)


def learned(tmp_path, name: str = "a"):
    """A judge's store after one run that caught a debug print: Sibyl's local store, as on GitHub."""
    store = history.SibylStore.local(tmp_path / name)
    history.learn_tamper(store, "o/strict", "agent-x", "rule:no_debug", "calc.py:4: 'print(a, b)' breaks CONTRIBUTING.md:3", at=1.0)
    return store


# ---- export and import -----------------------------------------------------------------------------------------------

def test_what_the_judge_learned_is_exported_as_json_lines_and_loaded_once(tmp_path):
    a = learned(tmp_path)
    rows = history.lessons(a)
    assert sorted((x["category"], str(x["body"].get("scope"))) for x in rows) == [("proof_rule", "agent"), ("proof_rule", "repo"), ("tamper", "None")]
    assert rows == sorted(rows, key=lambda x: (x["category"], x["name"]))                  # in one order, whatever the store's
    text = history.export_lessons(a)
    assert text.endswith("\n") and [json.loads(line) for line in text.splitlines()] == rows and "\n\n" not in text
    assert history.export_lessons(rows) == text and history.export_lessons([]) == ""       # a store, or the rows themselves
    assert all(set(x) == {"category", "name", "body"} and re.fullmatch(r"[0-9a-f]{24}", x["name"]) for x in rows)
    b = history.SibylStore.local(tmp_path / "b")
    assert history.import_lessons(b, text) == 3
    assert history.tamper_checks_required(b, "o/other", "agent-x") == {"tamper:rule:no_debug"} == history.tamper_checks_required(a, "o/other", "agent-x")
    assert history.lessons(b) == rows
    for again in (text, rows, text.splitlines(), text + "\n\n" + text):                    # the same lessons, however often
        history.import_lessons(b, again)
        assert history.lessons(b) == rows and len(b.all("proof_rule")) == 2 and len(b.all("tamper")) == 1
    assert history.import_lessons(b, "") == 0 == history.import_lessons(b, None) == history.import_lessons(b, [])


def test_a_load_of_lessons_releases_sibyls_connection_once_and_not_after_each_lesson(tmp_path, monkeypatch):
    """Each release closes Sibyl's connection and the next call opens it again: seconds a call on a slow disk, so a
    knos-memory issue of a few dozen lessons took `knos preflight --issue` minutes. A load is one batch."""
    rows = history.lessons(learned(tmp_path))
    store = history.SibylStore.local(tmp_path / "b")
    storage, closed = store.client.storage, []
    close = storage.close
    monkeypatch.setattr(storage, "close", lambda: (closed.append(1), close())[1])
    assert history.import_lessons(store, rows * 4) == len(rows) * 4 and len(closed) == 1
    assert len(store.all("tamper")) == 1 and len(closed) == 2               # a call outside a batch releases at once
    with store.held():
        with store.held():
            store.all("tamper")
        store.put("proof_rule", "ef" * 12, {"when": "release", "require": "ci", "because": "x"})
        assert len(closed) == 2                                             # nested: open until the outer batch ends
    assert len(closed) == 3 and len(store.all("proof_rule")) == 3
    with history.NullStore().held() as none:
        assert history.import_lessons(none, rows) == len(rows) and none.all("tamper") == []


def test_a_contributing_rule_is_never_a_lesson_and_a_rule_a_rejection_taught_is(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "CONTRIBUTING.md").write_text("# Rules\n\n- Do not leave print() debug statements in code.\n", "utf-8")
    store = history.SibylStore.local(tmp_path / "s")
    first = judge.gate(base, DIFF, store, "o/strict", "agent-x")
    assert not first["passed"] and store.all("repo_rule")                                  # the file's rules are in Sibyl for this run
    assert {x["category"] for x in history.lessons(store)} == {"proof_rule", "tamper"}     # and are read from the file again next run
    flagged = history.lint_pr(store, base, DIFF)
    history.learn(store, flagged)                                                          # the Stop hook's way of learning a rule
    taught = [x for x in history.lessons(store) if x["category"] == "repo_rule"]
    assert len(taught) == 1 and taught[0]["body"]["origin"] == "learned" and taught[0]["body"]["id"] == taught[0]["name"]
    other = history.SibylStore.local(tmp_path / "t")
    assert history.import_lessons(other, history.export_lessons(store)) == len(history.lessons(store))
    assert [r["origin"] for r in other.all("repo_rule")] == ["learned"]
    assert {r["require"] for r in history.rules(other)} >= {"tamper:rule:no_debug", f"rule:{taught[0]['name']}"}


def test_a_line_that_is_not_a_lesson_is_skipped(tmp_path):
    good = history.lessons(learned(tmp_path))
    rule = next(x for x in good if x["category"] == "proof_rule" and x["body"]["scope"] == "repo")
    contributing = {"category": "repo_rule", "name": "ab" * 12, "body": {"id": "ab" * 12, "kind": "max_lines", "param": 1,
                                                                        "origin": "contributing", "contributing": "0" * 16}}
    junk = ["not json", "[]", "7", json.dumps({"category": "proof_claim", "name": "ab" * 12, "body": {}}),
            json.dumps({**rule, "name": "short"}), json.dumps({**rule, "name": "ZZ" * 12}), json.dumps({**rule, "name": 7}),
            json.dumps({**rule, "body": "x"}), json.dumps({"category": "proof_rule", "name": rule["name"]}),
            json.dumps({**rule, "name": "cd" * 12}),                                       # another rule's name on this rule
            json.dumps({**rule, "body": {**rule["body"], "repo": "everyone"}}),            # this rule's name on another rule
            json.dumps({**rule, "body": {**rule["body"], "scope": "world"}}), json.dumps({**rule, "body": {**rule["body"], "require": "ci"}}),
            json.dumps({**rule, "body": {**rule["body"], "repo": 7}}), json.dumps({**rule, "body": {"when": "tamper"}}),
            json.dumps({**rule, "body": {"when": 1, "require": "x"}}),
            json.dumps(contributing),                                                      # could stand in for the repository's own file
            json.dumps({**contributing, "body": {**contributing["body"], "origin": "learned", "id": "other"}}),
            json.dumps({**contributing, "body": {"origin": "learned", "id": "ab" * 12}}),
            json.dumps({"category": "tamper", "name": "ab" * 12, "body": {"repo": "o/r", "agent": "x"}}),
            json.dumps({"category": "tamper", "name": "ab" * 12, "body": {"repo": "o/r", "agent": "x", "pattern": "p", "evidence": "e" * 9000}}),
            {"category": "proof_rule"}, None, 7]
    store = history.SibylStore.local(tmp_path / "junk")
    assert history.import_lessons(store, junk) == 0 and history.lessons(store) == []
    assert all(history.lesson(json.loads(x)) is None for x in junk[:3] if x != "not json")
    assert history.import_lessons(store, [*junk, json.dumps(rule), *junk]) == 1 and history.lessons(store) == [rule]
    plain = {"category": "proof_rule", "name": "ef" * 12, "body": {"when": "release", "require": "ci", "because": "x"}}
    assert history.lesson(plain) == plain                                                  # a rule the Stop hook learned travels too


def test_without_sibyl_the_lines_are_not_a_memory(tmp_path):
    text = history.export_lessons(learned(tmp_path))
    nothing = history.NullStore()
    assert history.import_lessons(nothing, text) == 3                                      # read, and kept nowhere
    assert history.rules(nothing) == [] and history.lessons(nothing) == [] and history.export_lessons(nothing) == "" and nothing.rows("tamper") == []

    class NoRows:                                                                          # a store that cannot name what it keeps
        def all(self, category):
            return [{"when": "tamper"}]
    assert history.lessons(NoRows()) == []
    assert judge.gate(tmp_path, DIFF, nothing, "o/lax", "agent-x")["passed"]               # so the same pull request passes
    kept = history.SibylStore.local(tmp_path / "kept")
    history.import_lessons(kept, text)
    again = judge.gate(tmp_path, DIFF, kept, "o/lax", "agent-x")
    assert not again["passed"] and again["evidence"]["required_by_history"] == ["tamper:rule:no_debug"]


# ---- the knos-memory issue -------------------------------------------------------------------------------------------

def test_a_run_posts_what_it_learned_and_a_later_run_reads_it_back(tmp_path):
    hub = Issues()
    assert memory.read("o/r", hub) == (None, []) and memory.pull("o/r", history.SibylStore.local(tmp_path / "empty"), hub) == 0
    a = learned(tmp_path)
    assert memory.push("o/r", a, hub, hub, run="123") == 3
    (opened, issue), (said, post) = hub.posted
    assert opened == "repos/o/r/issues" and issue["labels"] == ["knos-memory"] and issue["title"] == "Knos memory"
    assert "Close this issue to make Knos forget." in issue["body"]
    assert said == "repos/o/r/issues/1/comments"
    lines = post["body"].splitlines()                                                      # one comment: the marker, then a fence
    assert lines[0] == memory.MARK == "<!-- knos-memory 1 -->" and "in run 123" in lines[1] and lines[3] == "```json" and lines[-1] == "```"
    assert [json.loads(x) for x in lines[4:-1]] == history.lessons(a) == memory.lessons_in(post["body"])
    assert memory.push("o/r", a, hub, hub, run="124") == 0 and len(hub.posted) == 2        # nothing new: nothing posted
    # a later run, on another runner: the lessons go into its own Sibyl store, once
    b = history.SibylStore.local(tmp_path / "b")
    assert memory.pull("o/r", b, hub) == 3 == memory.pull("o/r", b, hub)
    assert history.lessons(b) == history.lessons(a)
    assert memory.push("o/r", b, hub, hub) == 0 and len(hub.posted) == 2                   # it knows nothing the issue does not have
    refused = judge.gate(tmp_path, DIFF, b, "o/lax", "agent-x")
    assert not refused["passed"] and refused["evidence"]["required_by_history"] == ["tamper:rule:no_debug"]
    # that refusal is a lesson of its own (this repository now requires it too): only what is new is posted, in one more comment
    assert memory.push("o/r", b, hub, hub) == 2 and len(hub.posted) == 3
    new = memory.lessons_in(hub.posted[-1][1]["body"])
    assert sorted((x["category"], x["body"]["repo"]) for x in new) == [("proof_rule", "lax"), ("tamper", "o/lax")]
    assert "in run" not in hub.posted[-1][1]["body"]
    assert len(memory.read("o/r", hub)[1]) == 5 and memory.read("o/r", hub)[0] == 1


def test_only_what_github_actions_wrote_and_nobody_edited_is_read(tmp_path):
    block = memory.comment(history.lessons(learned(tmp_path)))
    hub = Issues()
    n = hub.open(BOT)
    hub.say(n, MONA, block)                                                                # anyone can comment on an issue
    hub.say(n, user("github-actions[bot]", 7, "Bot"), block)                               # the name alone is not the account
    hub.say(n, user("other[bot]", 41898282, "Bot"), block)
    hub.say(n, BOT, block, edited=True)                                                    # anyone with write access can edit a comment
    hub.say(n, BOT, "A note.\n" + block)                                                   # the marker is the first line or it is not one
    hub.say(n, BOT, block.replace(memory.MARK, "<!-- knos-memory 2 -->"))
    hub.say(n, BOT, "Knos: `x` is not a command.")
    hub.say(n, BOT, memory.MARK + "\nno fence here\n" + json.dumps(history.lessons(learned(tmp_path, "c"))[0]))
    assert memory.read("o/r", hub) == (n, [])
    store = history.SibylStore.local(tmp_path / "fresh")
    assert memory.pull("o/r", store, hub) == 0 and history.rules(store) == []
    hub.say(n, BOT, memory.MARK + "\n```json\nnot json\n{\"category\":\"proof_claim\"}\n" + block.split("```json\n")[1])
    assert len(memory.read("o/r", hub)[1]) == 3                                            # the bot's own, unedited: junk lines skipped
    assert memory.lessons_in(block + "\n```\n" + block.split("```json\n")[1]) == memory.lessons_in(block)   # one fence a comment
    assert memory.lessons_in("") == [] == memory.lessons_in(None) == memory.lessons_in(memory.MARK)


def test_only_an_issue_github_actions_opened_is_the_memory(tmp_path):
    hub = Issues()
    theirs = hub.open(MONA)                                                                # a person's issue with the label
    hub.say(theirs, BOT, memory.comment(history.lessons(learned(tmp_path))))               # (even with the bot's comment in it)
    hub.open(BOT, labels=("bug",))
    hub.open(BOT, pull_request={"url": "x"})                                               # a pull request is not an issue
    assert memory.issues("o/r", hub) == [] and memory.read("o/r", hub) == (None, [])
    a = learned(tmp_path, "mine")
    assert memory.push("o/r", a, hub, hub) == 3 and hub.posted[0][0] == "repos/o/r/issues" and hub.posted[1][0] == "repos/o/r/issues/4/comments"
    assert memory.issues("o/r", hub) == [4]
    # two runs opened one each at the same moment: both are read, and new lessons go to the older
    second = hub.open(BOT)
    b = learned(tmp_path, "second")
    history.learn_tamper(b, "o/r", "agent-z", "protected-path", "touches protected path .knos/x", at=3.0)
    hub.say(second, BOT, memory.comment([x for x in history.lessons(b) if x not in history.lessons(a)]))
    assert memory.issues("o/r", hub) == [4, 5] and len(memory.read("o/r", hub)[1]) == 6 and memory.read("o/r", hub)[0] == 4
    # closing the issue is how a maintainer makes Knos forget
    for issue in hub.issues:
        issue["state"] = "closed"
    assert memory.read("o/r", hub) == (None, []) and memory.pull("o/r", history.SibylStore.local(tmp_path / "forgot"), hub) == 0


def test_a_memory_that_cannot_be_read_is_not_guessed(tmp_path):
    hub = Issues()
    a = learned(tmp_path)
    assert memory.push("o/r", a, hub, hub) == 3
    hub.down = True
    assert memory.read("o/r", hub) == (None, None) and memory.pull("o/r", a, hub) is None
    posted = len(hub.posted)
    assert memory.push("o/r", a, hub, hub) is None and len(hub.posted) == posted           # nothing is posted blind
    hub.down = False
    hub.comments[1] = None                                                                 # the issue is there, its comments are not

    def comments_fail(path, data=None):
        if "/comments" in path:
            raise OSError("502")
        return hub(path, data)
    assert memory.read("o/r", comments_fail) == (1, None) and memory.push("o/r", a, comments_fail, comments_fail) is None


def test_lessons_that_do_not_fit_one_comment_go_in_several(tmp_path):
    store = history.SibylStore.local(tmp_path / "many")
    for i in range(60):
        history.learn_tamper(store, f"o/r{i}", f"agent-{i}", "false-claim", "x" * 1900, at=float(i))
    hub = Issues()
    assert memory.push("o/r", store, hub, hub, run="9") == 180
    bodies = [data["body"] for path, data in hub.posted if path.endswith("/comments")]
    assert len(bodies) > 1 and all(len(b) <= 65_536 and b.startswith(memory.MARK) for b in bodies)
    assert sum(len(memory.lessons_in(b)) for b in bodies) == 180
    other = history.SibylStore.local(tmp_path / "other")
    assert memory.pull("o/r", other, hub) == 180 and history.lessons(other) == history.lessons(store)
    assert memory.push("o/r", other, hub, hub) == 0
    hub.asked.clear()
    memory.read("o/r", hub)
    assert len([p for p in hub.asked if "/comments" in p]) == 1                            # few comments: one page


# ---- knos proof memory pull | push -----------------------------------------------------------------------------------

def cli(capsys, *args: str) -> tuple[int, str]:
    rc = main(list(args))
    got = capsys.readouterr()
    return rc, got.out + got.err


def test_knos_proof_memory_carries_the_lessons_between_runs(tmp_path, capsys, monkeypatch):
    hub = Issues()
    monkeypatch.setattr("knos.judge.github", hub)
    learned(tmp_path, "run1")
    rc, out = cli(capsys, "proof", "memory", "pull", "--repo", "o/r", "--store", str(tmp_path / "run1"))
    assert rc == 0 and out.strip() == "Loaded 0 lesson(s) from o/r's knos-memory issue."
    rc, out = cli(capsys, "proof", "memory", "push", "--repo", "o/r", "--store", str(tmp_path / "run1"), "--run", "55")
    assert rc == 0 and out.strip() == "Posted 3 new lesson(s) to o/r's knos-memory issue." and "in run 55" in hub.posted[-1][1]["body"]
    rc, out = cli(capsys, "proof", "memory", "push", "--repo", "o/r", "--store", str(tmp_path / "run1"))
    assert rc == 0 and out.strip() == "Nothing new to remember."
    rc, out = cli(capsys, "proof", "memory", "pull", "--repo", "o/r", "--store", str(tmp_path / "run2"))
    assert rc == 0 and out.strip() == "Loaded 3 lesson(s) from o/r's knos-memory issue." and (tmp_path / "run2" / "sibyl.db").is_file()
    assert history.tamper_checks_required(history.SibylStore.local(tmp_path / "run2"), "o/lax", "agent-x") == {"tamper:rule:no_debug"}
    hub.down = True
    rc, out = cli(capsys, "proof", "memory", "pull", "--repo", "o/r", "--store", str(tmp_path / "run3"))
    assert rc == 1 and "this run remembers nothing" in out
    rc, out = cli(capsys, "proof", "memory", "push", "--repo", "o/r", "--store", str(tmp_path / "run1"))
    assert rc == 1 and "nothing was posted" in out
    hub.down = False
    history.learn_tamper(history.SibylStore.local(tmp_path / "run1"), "o/r", "agent-q", "false-claim", "x")
    monkeypatch.setattr("knos.judge.github", lambda path, data=None: (_ for _ in ()).throw(OSError("403 Resource not accessible")) if data else hub(path))
    rc, out = cli(capsys, "proof", "memory", "push", "--repo", "o/r", "--store", str(tmp_path / "run1"))
    assert rc == 1 and out.startswith("GitHub did not take the lessons: 403")              # a read-only token: said, not hidden


def test_the_memory_is_written_only_through_sibyl(tmp_path, monkeypatch):
    import sys
    hub = Issues()
    assert memory.push("o/r", learned(tmp_path), hub, hub) == 3
    monkeypatch.setitem(sys.modules, "sibyl_memory_client", None)                          # as if Sibyl were not installed
    with pytest.raises(ImportError):
        history.SibylStore.local(tmp_path / "none")                                        # there is no other store to pull into
    assert memory.pull("o/r", history.NullStore(), hub) == 3
    assert judge.gate(tmp_path, DIFF, history.NullStore(), "o/lax", "agent-x")["passed"]   # the issue alone remembers nothing


# ---- a pull request that was paid stays paid --------------------------------------------------------------------------

SETTLED = history._id("settlement", "r", 12, "a" * 40)       # the lesson's name: the repository, the pull request, its head


def settled(tmp_path, name: str, paid: bool, hub=None):
    """A run that settled pull request 12 at the same commit, as flow._learn keeps it: the memory read from the issue
    (when `hub` is given), then what this settlement showed, under the same name whoever settled it."""
    store = history.SibylStore.local(tmp_path / name)
    if hub is not None:
        assert memory.pull("o/r", store, hub) is not None
    body = {"repo": "r", "pull": 12, "paid": paid, "failed": {} if paid else {"test": ["src"]}, "false": [],
            "met": ["test"] if paid else [], "paths": ["src"], "at": 1}
    assert history.import_lessons(store, [{"category": "settlement", "name": SETTLED, "body": body}]) == 1
    return store


def remembered(tmp_path, hub, name: str = "next") -> dict:
    """What the next run reads of pull request 12."""
    store = history.SibylStore.local(tmp_path / name)
    memory.pull("o/r", store, hub)
    [(got, body)] = store.rows("settlement")
    assert got == SETTLED
    return body


@pytest.mark.parametrize("posts_last", ["refused", "paid"])
def test_a_merge_settle_and_attest_racing_on_one_pull_request_leave_it_paid_whichever_posts_last(tmp_path, posts_last):
    """prove.yml's merged job and attest no longer share a concurrency line: both read the memory before either
    writes, both post their lesson under the same name, and the one posted last used to be what every later run read.
    A "not paid" posted after the "paid" took the payment back out of the judge's memory."""
    hub = Issues()
    paid, refused = settled(tmp_path, "attest", True, hub), settled(tmp_path, "merge", False, hub)
    first, last = (paid, refused) if posts_last == "refused" else (refused, paid)
    between = []

    def post(path, data):                                  # `last` read the issue; `first` posts before `last` does
        if not between:
            between.append(memory.push("o/r", first, hub, hub, run="1"))
        return hub(path, data)
    assert memory.push("o/r", last, hub, post, run="2") == 1 and between == [1]
    there = [x for x in memory.read("o/r", hub)[1] if x["category"] == "settlement"]
    assert [x["name"] for x in there] == [SETTLED, SETTLED] and {x["body"]["paid"] for x in there} == {True, False}
    got = remembered(tmp_path, hub)
    assert got["paid"] is True and got["met"] == ["test"] and got["failed"] == {}
    # every run after reads the same, however often it loads the issue, and has nothing of its own to post
    later = history.SibylStore.local(tmp_path / "later")
    assert memory.pull("o/r", later, hub) == 2 == memory.pull("o/r", later, hub)
    assert [b["paid"] for b in later.all("settlement")] == [True] and memory.push("o/r", later, hub, hub) == 0


def test_a_not_paid_written_after_paid_is_not_kept_and_a_paid_written_after_not_paid_is_posted(tmp_path):
    # the attestor paid first; the merge's settlement runs after it and refuses: its store keeps the payment, and it posts nothing
    hub = Issues()
    assert memory.push("o/r", settled(tmp_path, "attest", True, hub), hub, hub) == 1
    late = settled(tmp_path, "merge", False, hub)
    assert [b["paid"] for b in late.all("settlement")] == [True] and memory.push("o/r", late, hub, hub) == 0
    assert remembered(tmp_path, hub)["paid"] is True
    # the merge's settlement refused first; the attestor pays after it: the issue says "not paid" under that name, and
    # the payment is posted all the same (a lesson is never edited, only posted again), and read as final
    hub = Issues()
    assert memory.push("o/r", settled(tmp_path, "merge2", False, hub), hub, hub) == 1
    late = settled(tmp_path, "attest2", True, hub)
    assert [b["paid"] for b in late.all("settlement")] == [True] and memory.push("o/r", late, hub, hub) == 1
    assert remembered(tmp_path, hub, "next2")["paid"] is True and memory.push("o/r", late, hub, hub) == 0
    # a "not paid" for another commit of the same pull request is another lesson: nothing is taken from it
    other = history._id("settlement", "r", 12, "b" * 40)
    assert history.paid_settlements(memory.read("o/r", hub)[1]) == {SETTLED} and other != SETTLED
    assert history.paid_settlements([]) == set() == history.paid_settlements(history.NullStore()) == history.paid_settlements(object())


class Editable(Issues):
    """The same issues, on a forge that also reads one issue and takes an edit of its body (PATCH)."""

    def __init__(self):
        super().__init__()
        self.edits = []

    def __call__(self, path: str, data: dict | None = None, method: str | None = None):
        m = re.fullmatch(r"repos/o/r/issues/(\d+)", path)
        if m and method == "PATCH":
            self.edits.append((path, data))
            self.issues[int(m.group(1)) - 1].update(data)
            return {}
        if m and data is None:
            return dict(self.issues[int(m.group(1)) - 1])
        return super().__call__(path, data)


def test_the_memory_issue_says_it_is_a_log_and_one_opened_before_is_edited_once_to_say_so(tmp_path):
    said = "This is a log written by a workflow. It is not a task and carries no payment. "
    assert memory._ABOUT.startswith(said + "Knos keeps here what its judge learned")
    # opened now: the sentence is the first thing its body says, and nothing is ever edited
    hub = Editable()
    assert memory.push("o/r", settled(tmp_path, "new", True, hub), hub, hub) == 1 and hub.issues[0]["body"] == memory._ABOUT
    other = history.SibylStore.local(tmp_path / "other")
    history.import_lessons(other, [{"category": "settlement", "name": history._id("settlement", "r", 13, "b" * 40),
                                    "body": {**remembered(tmp_path, hub), "pull": 13}}])
    assert memory.push("o/r", other, hub, hub) == 1 and hub.edits == []
    # opened by an earlier release: edited once, when the next lesson is posted, and the lesson is posted all the same
    hub = Editable()
    n = hub.open(BOT, title="Knos memory", body="Knos keeps here what its judge learned.")
    assert memory.push("o/r", settled(tmp_path, "old", True, hub), hub, hub) == 1
    assert hub.edits == [(f"repos/o/r/issues/{n}", {"body": said + "Knos keeps here what its judge learned."})] and len(hub.comments[n]) == 1
    assert memory.push("o/r", other, hub, hub) == 1 and len(hub.edits) == 1 and len(hub.comments[n]) == 2
    # a forge that takes no edit: the lesson is posted, and nothing is lost
    plain = Issues()
    n = plain.open(BOT, title="Knos memory", body="")
    assert memory.push("o/r", settled(tmp_path, "plain", True, plain), plain, plain) == 1 and len(plain.comments[n]) == 1
