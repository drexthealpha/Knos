"""scripts/tidy_issues.py: every open item of the owner's repositories, what it is, and what to do with it.

`gh` is a stand-in that answers from a fixture and keeps what it is asked to write. No network."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from knos import claim_guard

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_791_331_200.0       # 2026-10-06T20:00:00Z
OWNER, STRANGER, BOT = {"login": "drexthealpha", "type": "User"}, {"login": "someone-outside", "type": "User"}, {"login": "github-actions[bot]", "type": "Bot"}
CLAIM = (ROOT / "tests" / "data" / "claims" / "pull_51_body.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def tidy():
    spec = importlib.util.spec_from_file_location("tidy_issues", ROOT / "scripts" / "tidy_issues.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tidy_issues"] = mod
    spec.loader.exec_module(mod)
    return mod


def _item(number: int, title: str, who: dict, association: str, created: str = "2026-10-01T20:00:00Z", **more) -> dict:
    return {"number": number, "title": title, "body": "", "user": who, "author_association": association, "created_at": created, "labels": [], **more}


KNOS = [
    _item(17, "Knos relay log", BOT, "NONE", "2026-07-08T20:00:00Z", labels=[{"name": "knos-relay"}]),
    _item(18, "knos tokens", BOT, "NONE"),
    _item(19, "Knos memory", BOT, "NONE", labels=[{"name": "knos-memory"}]),
    _item(40, "C7: fund, take, pay on staging", OWNER, "OWNER"),
    _item(41, "Track B rehearsal: quorum of two", OWNER, "OWNER"),
    _item(42, "Make the relay faster", OWNER, "OWNER"),
    _item(51, "fix: resolve #17", STRANGER, "NONE", "2026-10-06T08:00:00Z", body=CLAIM, pull_request={}),
    _item(52, "Typo in docs/RELAY.md", STRANGER, "NONE", pull_request={}),
    _item(53, "Does it work with GitLab?", STRANGER, "NONE"),
    _item(54, "A question that was answered", STRANGER, "NONE"),
]
COMMENTS = {53: [{"user": OWNER, "author_association": "OWNER", "body": "It does."}, {"user": STRANGER, "author_association": "NONE", "body": "And self-hosted?"}],
            54: [{"user": OWNER, "author_association": "OWNER", "body": "Yes."}]}


class Gh:
    def __init__(self) -> None:
        self.wrote: list[list[str]] = []
        self.asked: list[str] = []

    def __call__(self, args: list[str]) -> str:
        assert args[0] == "api"
        if "-X" in args:
            self.wrote.append(args[1:])
            return "{}"
        path = args[1]
        self.asked.append(path)
        if "page=1" not in path:
            return "[]"
        if path.startswith("users/drexthealpha/repos"):
            return json.dumps([{"name": n, "full_name": f"drexthealpha/{n}", "id": 100 + i} for i, n in enumerate(
                ["Knos", "knos-e2e", "knos-e2e-2", "knos-playground", "knos-task", "knos-attest", "knos-workflows", "MergePay", "dotfiles"])])
        if path.startswith("repos/drexthealpha/Knos/issues?"):
            return json.dumps(KNOS)
        if path.startswith("repos/drexthealpha/knos-e2e/issues?"):
            return json.dumps([_item(3, "C12b: order with a holdback", OWNER, "OWNER", pull_request={}), _item(4, "e2e smoke", OWNER, "OWNER")])
        if "/comments" in path:
            return json.dumps(COMMENTS.get(int(path.split("/")[4]), []))
        return "[]"


def _rows(tidy, chain=None) -> dict:
    return {f"{r['repo'].split('/')[1]}#{r['number']}": r for r in tidy.survey(Gh(), NOW, chain)}


def test_only_the_owners_named_repositories_are_read(tidy):
    gh = Gh()
    assert [r["full_name"] for r in tidy.repositories(gh)] == [f"drexthealpha/{n}" for n in (
        "Knos", "knos-attest", "knos-e2e", "knos-e2e-2", "knos-playground", "knos-task", "knos-workflows")]
    tidy.survey(gh, NOW)
    assert not any("MergePay" in p or "dotfiles" in p for p in gh.asked) and gh.wrote == []


def test_each_open_item_gets_its_category_its_action_and_its_exact_comment(tidy):
    rows = _rows(tidy)
    assert {k: (r["category"], r["action"]) for k, r in rows.items()} == {
        "Knos#17": ("machine", "leave open"), "Knos#18": ("machine", "leave open"), "Knos#19": ("machine", "leave open"),
        "Knos#40": ("rehearsal", "close"), "Knos#41": ("rehearsal", "close"), "Knos#42": ("own", "leave"),
        "Knos#51": ("claim", "answer, label no-order"), "Knos#52": ("outside", "answer"), "Knos#53": ("outside", "answer"),
        "Knos#54": ("outside", "nothing"), "knos-e2e#3": ("rehearsal", "close"), "knos-e2e#4": ("rehearsal", "close")}
    assert rows["Knos#17"]["age"] == 90 and rows["Knos#51"]["age"] == 0 and rows["Knos#40"]["age"] == 5 and rows["Knos#51"]["pull"] is True
    assert all(not rows[k]["comment"] and not rows[k]["close"] for k in ("Knos#17", "Knos#18", "Knos#19", "Knos#42", "Knos#54"))
    assert rows["Knos#40"]["comment"] == "This was a devnet rehearsal, and it is finished. Closing it; nothing is owed on it." and rows["Knos#40"]["close"] is True
    assert rows["Knos#51"]["comment"] == claim_guard.answer(True, [17], []) and rows["Knos#51"]["label"] == "no-order" and rows["Knos#51"]["close"] is False
    assert "Issue #17 is a log written by a workflow. It is not a task and carries no payment." in rows["Knos#51"]["comment"]
    assert rows["Knos#52"]["comment"] == rows["Knos#53"]["comment"] == tidy.THANKS and rows["Knos#52"]["close"] is False
    assert tidy.THANKS.splitlines()[1] == ("Thank you for this. A maintainer reads it and answers here. Contributions are welcome and unpaid unless the issue "
                                           "shows a funded order, and this one shows none.")
    for r in rows.values():         # no comment carries a word of the item it answers
        assert "someone-outside" not in r["comment"] and "0x00" not in r["comment"] and "RelayStats" not in r["comment"]


def test_another_services_bot_is_not_this_repositorys_word(tidy):
    """A review service's comment spoken last is not an answer: the outside item is still answered. Knos's own
    workflow account and the owner still are; an item a bot opened is left alone."""
    review = {"user": {"login": "coderabbitai[bot]", "type": "Bot"}, "author_association": "NONE", "body": "Review finished."}
    asked = [{"user": STRANGER, "author_association": "NONE", "body": "Could a maintainer approve the workflows?"}]
    pull = _item(38, "test: cover digits in slugs", STRANGER, "FIRST_TIME_CONTRIBUTOR", pull_request={})
    assert tidy.classify(pull, {}, NOW, False, asked + [review])["action"] == "answer"
    assert not claim_guard._ours(review["user"], "NONE") and claim_guard._ours(BOT, "NONE") and claim_guard._ours(OWNER, "OWNER")
    marked = {**review, "body": tidy.THANKS}
    assert tidy.classify(pull, {}, NOW, False, asked + [marked])["action"] == "answer"
    assert tidy.classify(pull, {}, NOW, False, asked + [{"user": BOT, "author_association": "NONE", "body": "Knos: noted."}])["action"] == "nothing"
    dependabot = _item(39, "Bump pytest", {"login": "dependabot[bot]", "type": "Bot"}, "NONE", pull_request={})
    assert (tidy.classify(dependabot, {}, NOW, False, [])["category"], tidy.classify(dependabot, {}, NOW, False, [])["comment"]) == ("bot", "")


@pytest.mark.parametrize("title,rehearsal", [
    ("C-b: initials.py: initials(name) (an auto order, judged black box)", True),
    ("C-d: an order funded from a passkey wallet on the Buy page", True), ("C-b2: a second try", True),
    ("C12b: order with a holdback", True), ("C2: titles.py: title_case", True),
    ("initials.py: initials(name)", False), ("C-section: notes", False), ("Make C-b: faster", False)])
def test_a_rehearsal_title_is_known_by_its_track_name(tidy, title, rehearsal):
    row = tidy.classify(_item(139, title, OWNER, "OWNER"), {}, NOW, False, [])
    assert (row["category"], row["close"]) == (("rehearsal", True) if rehearsal else ("own", False))


def test_the_chain_decides_whether_a_rehearsal_is_finished(tidy):
    rows = _rows(tidy, lambda repo_id, n: n == 41)
    assert (rows["Knos#41"]["action"], rows["Knos#41"]["note"], rows["Knos#41"]["close"]) == ("leave open", "its order still holds money on chain", False)
    assert rows["Knos#40"]["close"] is True and rows["Knos#40"]["note"] == ""
    assert _rows(tidy)["Knos#40"]["note"] == "the chain was not read (--rpc): --apply leaves it"
    funded = _rows(tidy, lambda repo_id, n: n == 51)["Knos#51"]
    assert funded["action"] == "nothing" and not funded["comment"]


def test_the_table_is_printed_and_nothing_is_written_without_apply(tidy, capsys):
    gh = Gh()
    assert tidy.main([], run=gh, now=NOW) == 0 and gh.wrote == []
    out = capsys.readouterr().out
    assert "drexthealpha/Knos#17     issue  90 d  machine    leave open" in out and "   3  machine: leave open" in out and "   4  rehearsal: close" in out
    assert "comment 1 (on drexthealpha/Knos#40, drexthealpha/Knos#41, drexthealpha/knos-e2e#3, drexthealpha/knos-e2e#4):" in out
    assert "    This was a devnet rehearsal, and it is finished. Closing it; nothing is owed on it." in out
    assert tidy.main(["--json"], run=gh, now=NOW) == 0 and len(json.loads(capsys.readouterr().out)) == 12


def test_apply_answers_and_closes_through_gh_and_closes_no_rehearsal_the_chain_was_not_read_for(tidy, capsys):
    gh = Gh()
    assert tidy.main(["--apply"], run=gh, now=NOW) == 0
    out = capsys.readouterr().out
    assert "drexthealpha/Knos#40: left (the chain was not read: give --rpc)" in out and not any("PATCH" in w for w in gh.wrote)
    assert sorted(w[2] for w in gh.wrote if w[2].endswith("/comments")) == [f"repos/drexthealpha/Knos/issues/{n}/comments" for n in (51, 52, 53)]
    gh = Gh()
    assert tidy.main(["--apply"], run=gh, now=NOW, chain=lambda repo_id, n: n == 41) == 0
    closed = sorted(w[2] for w in gh.wrote if w[1] == "PATCH")
    assert closed == ["repos/drexthealpha/Knos/issues/40", "repos/drexthealpha/knos-e2e/issues/3", "repos/drexthealpha/knos-e2e/issues/4"]
    assert ["-X", "POST", "repos/drexthealpha/Knos/issues/51/labels", "-f", "labels[]=no-order"] in gh.wrote
    assert not any("/issues/17" in w[2] or "/issues/42" in w[2] or "/issues/41" in w[2] for w in gh.wrote)      # logs, own work and a funded rehearsal are untouched
    body = next(w[4] for w in gh.wrote if w[2] == "repos/drexthealpha/Knos/issues/51/comments")
    assert body == "body=" + claim_guard.answer(True, [17], [])
    # what apply posted is found again: the guard's sweep and a second tidy both leave the item
    again = [{"user": OWNER, "author_association": "OWNER", "body": body[5:]}]
    assert claim_guard.answered(again) and tidy.classify(KNOS[6], {17: KNOS[0]}, NOW, None, again)["action"] == "nothing"
    assert tidy.classify(KNOS[7], {}, NOW, None, [{"user": OWNER, "author_association": "OWNER", "body": tidy.THANKS}])["action"] == "nothing"
