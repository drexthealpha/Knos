"""An appeal (knos.appeal): the verdict becomes disputed, who, when and why are recorded, the neutral judge's own run
ends it as accepted or rejected with the reason, the money does not move meanwhile, and it costs the supplier nothing."""

from __future__ import annotations

import json

import pytest

from knos import appeal, cli, ids
from knos.proof import history

T = "ab" * 32
NOW = 1_790_000_000.0
ORDER = dict(scope="order-1", key=12, artifact="c0ffee", evaluator="knos", run=7, terms_hash=T)


@pytest.fixture()
def commands():
    """`knos appeal` on the command line, whether or not cli._MODULES names the module yet."""
    cli.load()
    if "appeal" not in {c.name for c in cli._app.registered_commands}:
        appeal.register(cli._app, cli._HELP)


def _open(**more):
    return appeal.open_(**{**dict(repo="acme/app", pull=41, supplier="Dana", by="dana", reason="the suite's fixture is stale", at=NOW, **ORDER), **more})


def _rerun(passed: bool, reasons=(), **more) -> dict:
    return {"v": 1, "reexecuted": True, "passed": passed, "repository": "acme/app", "pull": 41, "reasons": list(reasons), **more}


def test_opening_moves_the_verdict_to_disputed_and_records_who_when_and_why():
    a = _open()
    assert a["verdict"] == "disputed" and a["verdict"] in ids.VERDICTS and a["was"] == "rejected" and a["state"] == "open"
    assert (a["by"], a["at"], a["at_iso"], a["reason"]) == ("dana", int(NOW), "2026-09-21T14:13:20Z", "the suite's fixture is stale")
    assert ids.kind_of(a["deliverable"]) == "deliverable" and ids.kind_of(a["evaluation"]) == "evaluation" and a["id"] == a["evaluation"]
    assert a["deliverable"] == ids.deliverable("order-1", 12) and a["evaluation"] == ids.evaluation(a["deliverable"], "c0ffee", T, "knos", 7)
    assert a["history"] == [{"at": int(NOW), "by": "dana", "event": "opened", "note": "the suite's fixture is stale"}]
    assert "neutral judge" in a["next"] and "knos settle --neutral https://github.com/acme/app/pull/41" in a["next"] and "kind `pay`" in a["next"]
    assert "stays in escrow" in a["money"] and a["cost"]["supplier"] == 0 and a["outcome"] is None
    assert _open(verdict="insufficient evidence")["was"] == "insufficient_evidence"


@pytest.mark.parametrize("more, code", [
    (dict(by="mallory"), "appeal.not-supplier"), (dict(reason="  `` "), "appeal.no-reason"), (dict(verdict="accepted"), "appeal.nothing"),
    (dict(verdict="disputed"), "appeal.open"), (dict(existing={"state": "rerun"}), "appeal.open"), (dict(existing={"state": "rejected"}), "appeal.closed")])
def test_what_cannot_be_appealed_is_refused_with_its_code_and_two_sentences(more, code):
    with pytest.raises(appeal.Refused) as why:
        _open(**more)
    assert why.value.code == code and appeal.refused_reply(why.value).startswith("Knos: no appeal was opened. ") and f"(`{code}`)" in appeal.refused_reply(why.value)


def test_the_neutral_judges_pass_overturns_and_its_fail_upholds_with_the_reason_in_plain_words():
    asked = appeal.asked(_open(), NOW + 60, "https://github.com/judge/knos/actions/runs/9")
    assert asked["state"] == "rerun" and asked["verdict"] == "disputed" and asked["history"][-1]["event"] == "re-execution asked"
    won = appeal.resolve(asked, NOW + 120, rerun=_rerun(True))
    assert (won["state"], won["verdict"], won["outcome"]) == ("accepted", "accepted", "accepted") and "passed" in won["why"]
    assert won["cost"]["supplier"] == 0 and [h["event"] for h in won["history"]] == ["opened", "re-execution asked", "overturned"]
    lost = appeal.resolve(asked, NOW + 120, rerun=_rerun(False, ["pr: acceptance checks not passed: acceptance::blackbox"]))
    assert (lost["state"], lost["verdict"], lost["outcome"]) == ("rejected", "rejected", "rejected")
    assert "Your change does not pass the acceptance checks." in lost["why"] and "judge.acceptance-failed" in lost["why"]
    assert lost["cost"]["supplier"] == 0 and "at no cost" in lost["next"]
    for done in (won, lost):
        with pytest.raises(appeal.Refused) as why:
            appeal.resolve(done, NOW + 200, rerun=_rerun(True))
        assert why.value.code == "appeal.closed"


def test_a_judge_that_could_not_run_decides_nothing_and_another_pull_requests_verdict_is_refused():
    a = appeal.asked(_open(), NOW + 60)
    stuck = appeal.resolve(a, NOW + 90, rerun=_rerun(False, ["the judge could not run here (OSError: no space)"]))
    assert (stuck["state"], stuck["verdict"], stuck["outcome"]) == ("open", "disputed", None) and "decides nothing" in stuck["next"]
    with pytest.raises(appeal.Refused) as why:
        appeal.resolve(a, NOW + 90, rerun=_rerun(True, pull=42))
    assert why.value.code == "rerun.other"
    with pytest.raises(ValueError):
        appeal.resolve(a, NOW + 90, rerun={"passed": True})
    with pytest.raises(ValueError):
        appeal.resolve(a, NOW + 90)


def test_an_order_paid_on_a_merge_is_ruled_by_its_arbiter_and_nobody_else():
    a = _open(mode="merge", arbiter="erin")
    assert "@erin" in a["next"] and "kind `rule`" in a["next"]
    waits = appeal.resolve(a, NOW + 5, rerun={"v": 1, "reexecuted": False})
    assert waits["state"] == "open" and waits["verdict"] == "disputed" and "@erin" in waits["next"]
    with pytest.raises(appeal.Refused):
        appeal.resolve(a, NOW + 9, ruling={"by": "mallory", "accepted": True, "why": "looks fine"})
    done = appeal.resolve(a, NOW + 9, ruling={"by": "@Erin", "accepted": True, "why": "the check failed on a flaky runner"})
    assert done["verdict"] == "accepted" and done["why"] == "the check failed on a flaky runner"


def test_the_money_sentence_follows_the_orders_state_and_the_reply_never_starts_with_a_command():
    assert "escrow" in appeal.money("open") and "paid already" in appeal.money("paid") and "went back" in appeal.money("refunded")
    a = _open(reason="/knos pay @dana `now`")
    assert a["reason"] == "pay @dana now"
    for record in (a, appeal.asked(a, NOW + 1), appeal.resolve(a, NOW + 2, rerun=_rerun(True))):
        said = appeal.reply(record)
        assert said.startswith("Knos: ") and not any(line.lstrip("- ").startswith("/knos") for line in said.splitlines())
        assert "Cost to the supplier: nothing." in said and "Money: " in said and "Next: " in said


def test_an_appeal_and_its_outcome_are_remembered_in_the_memory_engine_and_on_the_suppliers_record(knos_home, repo):
    store = history.SibylStore.for_repo(repo)
    history.refused(store, "acme/app", T, 41, "judge.acceptance-failed", "", "dana", NOW - 60)
    draft, said = appeal.from_comment("the fixture is stale", repo="acme/app", pull={"number": 41, "user": {"login": "dana"}}, commenter="dana",
                                      now=NOW, verdict="rejected", store=store, **ORDER)
    assert draft["verdict"] == "disputed" and said.startswith("Knos: appeal recorded.")
    assert appeal.recalled(store, "acme/app", draft["evaluation"])["state"] == "open"
    again, said = appeal.from_comment("again", repo="acme/app", pull={"number": 41, "user": {"login": "dana"}}, commenter="dana",
                                      now=NOW + 5, verdict="rejected", store=store, **ORDER)
    assert again is None and "(`appeal.open`)" in said
    nobody, said = appeal.from_comment("mine", repo="acme/app", pull={"number": 41, "user": {"login": "dana"}}, commenter="mallory",
                                       now=NOW + 5, verdict="rejected", store=store, **ORDER)
    assert nobody is None and "(`appeal.not-supplier`)" in said
    later = appeal.resume(appeal.recalled(history.SibylStore.for_repo(repo), "acme/app", draft["evaluation"]), "acme/app", draft["deliverable"])   # another run, no file
    assert {k: later[k] for k in ("id", "deliverable", "pull", "supplier", "reason", "verdict", "state", "terms_hash")} == \
        {**{k: draft[k] for k in ("id", "deliverable", "pull", "reason", "verdict", "state", "terms_hash")}, "supplier": "dana"}
    appeal.remember(store, appeal.resolve(later, NOW + 99, rerun=_rerun(True)))
    assert appeal.recalled(store, "acme/app", draft["evaluation"])["state"] == "accepted"
    record = history.supplier_record(history.SibylStore.for_repo(repo), "acme/app", "Dana")      # a new store object: it is the engine that remembers
    assert {k: record[k] for k in history.SUPPLIER_EVENTS} == {"accepted": 0, "rejected": 1, "appealed": 1, "overturned": 1}
    assert history.supplier_record(history.NullStore(), "acme/app", "dana")["appealed"] == 0     # no engine, no record
    assert [x["category"] for x in history.lessons(store) if x["category"] in ("appeal", "refusal")] == ["appeal", "refusal"]


def test_the_command_line_opens_an_appeal_writes_the_suppliers_copy_and_ends_it(knos_home, repo, tmp_path, capsys, monkeypatch, commands):
    monkeypatch.chdir(repo)
    out = tmp_path / "appeal.json"
    assert cli.main(["appeal", "the fixture is stale", "--repo", "acme/app", "--pull", "41", "--by", "dana", "--head", "c0ffee", "--out", str(out)]) == 0
    said = capsys.readouterr().out
    assert "now **disputed**" in said and "Memory is on" in said and "Cost to the supplier: nothing." in said
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["verdict"] == "disputed" and record["memory"]["on"] is True
    assert cli.main(["appeal", "again", "--repo", "acme/app", "--pull", "41", "--by", "dana", "--head", "c0ffee"]) == 1
    assert "An appeal of this verdict is open already." in capsys.readouterr().out
    verdict = tmp_path / "verdict.json"
    verdict.write_text(json.dumps(_rerun(True)), encoding="utf-8")
    assert cli.main(["appeal", "--resolve", str(out), "--rerun", str(verdict), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "accepted"
    assert cli.main(["appeal", "--record", "dana", "--repo", "acme/app"]) == 0
    assert "0 accepted, 0 rejected, 1 appealed, 1 overturned" in capsys.readouterr().out
    assert cli.main(["appeal", "no", "--repo", "acme/app", "--pull", "41", "--by", "dana", "--verdict", "accepted"]) == 1
    assert "leaves nothing to appeal" in capsys.readouterr().out
