"""scripts/doc_claims.py: the facts more than one document states are computed from one source each, and a document
that says otherwise fails here."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


dc = _script("doc_claims")
CRITERIA, DEMO, WHY = "docs/submission/CRITERIA.md", "docs/submission/demo_script.md", "docs/WHY.md"


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """Everything the check reads, copied, so a test can change a document or a source."""
    files = {*dc.documents(ROOT), *dc.SOURCES, *dc.OTHER, "docs/facts.json", *(f"web/{p.name}" for p in (ROOT / "web").glob("*.js"))}
    for rel in files:
        if (ROOT / rel).is_file():
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, tmp_path / rel)
    return tmp_path


def _add(root: Path, rel: str, text: str) -> None:
    (root / rel).write_text((root / rel).read_text(encoding="utf-8") + "\n" + text + "\n", encoding="utf-8")


def _swap(root: Path, rel: str, old: str, new: str) -> None:
    text = (root / rel).read_text(encoding="utf-8")
    assert old in text, (rel, old)
    (root / rel).write_text(text.replace(old, new), encoding="utf-8")


def _feed(root: Path, pending_from: int = 1791324000) -> dict:
    """An upgrade record as the chain has it after 0.3.14: every committed proposal withdrawn (`replaced`), and one
    new pending proposal that was approved 48 hours before `pending_from` (2026-10-06 22:00 UTC)."""
    feed = json.loads((root / dc.UPGRADES).read_text(encoding="utf-8"))
    for e in feed["entries"]:
        e["status"] = "replaced"
    old = feed["entries"][0]
    feed["entries"].insert(0, {**old, "index": 9, "status": "pending", "earliest_execution": pending_from,
                               "since": pending_from - feed["time_lock"]})
    feed["pending"] = 1
    (root / dc.UPGRADES).write_text(json.dumps(feed), encoding="utf-8")
    return feed


def _found(root: Path, *needles: str) -> list[str]:
    lines = dc.problems(root)
    assert any(all(n in line for n in needles) for line in lines), (needles, lines)
    return lines


def test_this_tree_states_every_registered_fact_once_and_as_its_source_has_it(tree):
    assert dc.problems(ROOT) == []
    assert dc.main([]) == 0 and dc.write(tree) == []            # nothing generated is out of date
    # each fact has one source, and the value is computed from it, not kept
    reg = dc._registry()
    assert {src for _what, src, _fn in reg.values()} <= set(dc.SOURCES)
    data = json.loads((ROOT / dc.MANIFEST).read_text(encoding="utf-8"))
    for stage in data["stages"]:
        assert dc.value(f"capabilities.{stage}") == sum(c["stage"] == stage for c in data["capabilities"])
    assert dc.value("capabilities.exercised") == sum(dc.value(f"capabilities.exercised.{w}") for w in ("public", "staging", "unknown"))
    # and every exercised one ran at a public program id: a staging run is no stage (scripts/capabilities.py refuses it)
    assert dc.value("capabilities.exercised") == dc.value("capabilities.exercised.public")
    assert dc.value("capabilities.exercised.staging") == dc.value("capabilities.exercised.unknown") == 0
    assert dc.value("programs") == 4 and dc.value("upgrades.pending") == len(dc.pending())
    assert dc.value("stat.payments_timed") == json.loads((ROOT / dc.BENCH).read_text(encoding="utf-8"))["devnet"]["stats"]["latency"]["merge_to_paid"]["count"]
    # the same documents hold whatever the chain says next: with every committed proposal withdrawn and a new one pending
    _feed(tree)
    assert dc.problems(tree) == []


def _exercise(root: Path, *cids: str, deployed: dict | None = None) -> dict:
    """The manifest of `root` with each of `cids` exercised by a transaction (made up here), on its own deployed program
    or on `deployed`."""
    data = json.loads((root / dc.MANIFEST).read_text(encoding="utf-8"))
    for k, c in enumerate(c for c in data["capabilities"] if c["id"] in cids):
        c["stage"] = "exercised"
        c["evidence"] = {**c["evidence"], **({"deployed": deployed} if deployed else {}), "exercised": {"signature": str(5 + k) * 87}}
    (root / dc.MANIFEST).write_text(json.dumps(data), encoding="utf-8")
    return data


def test_a_count_or_a_stage_that_is_not_the_manifests_fails(tree):
    # the committed pages state no count of capabilities (docs/CAPABILITIES.md is the count): one is written here, of a
    # manifest in which two deployed capabilities have been exercised at their public program ids
    assert not dc._COUNT.search((tree / CRITERIA).read_text(encoding="utf-8"))
    before = dc.value("capabilities.exercised.public", tree)     # what the committed manifest records as exercised already
    two = [c["id"] for c in json.loads((tree / dc.MANIFEST).read_text(encoding="utf-8"))["capabilities"] if c["stage"] == "deployed"][:2]
    assert len(two) == 2
    _exercise(tree, *two)
    n = dc.value("capabilities.exercised", tree)
    assert n == dc.value("capabilities.exercised.public", tree) == before + 2 and dc.value("capabilities.exercised.staging", tree) == 0
    dc.write(tree)          # the stage cells that name them follow the manifest
    assert dc.problems(tree) == []
    _add(tree, CRITERIA, f"{n} capabilities are exercised on devnet.")
    assert dc.problems(tree) == []
    _swap(tree, CRITERIA, f"{n} capabilities are exercised on devnet", f"{n + 1} capabilities are exercised on devnet")
    _found(tree, CRITERIA, f"says {n + 1} capabilities exercised", f"has {n}")
    _swap(tree, CRITERIA, f"{n + 1} capabilities are exercised on devnet", f"{n} capabilities are exercised on devnet")
    assert dc.problems(tree) == []
    # a contradiction between two pages: one lists the exercised ones, another says there are none
    _add(tree, WHY, "Nothing in the manifest is recorded as exercised or reproduced yet.")
    _found(tree, WHY, "says nothing is exercised")
    _add(tree, "docs/MARKET.md", "What this release adds is tested locally and is not on devnet yet.")
    _found(tree, "docs/MARKET.md", "gives a whole release one stage")
    # which ids they ran on is the manifest's too: a run is never said to be a staging one when it was public, nor the other way
    _add(tree, "docs/COMPARE.md", f"Of the {n} capabilities exercised on devnet, {n} ran on the public program ids.")
    assert not any("docs/COMPARE.md" in line for line in dc.problems(tree))
    _add(tree, "docs/COMPARE.md", f"Of the {n} capabilities exercised on devnet, {n} ran on the staging program ids.")
    _found(tree, "docs/COMPARE.md", f"says {n} exercised on staging ids", "has 0")
    _add(tree, "docs/COMPARE.md", f"Of the {n} capabilities exercised on devnet, {n - 1} ran on the public program ids.")
    _found(tree, "docs/COMPARE.md", f"says {n - 1} exercised on public ids", f"has {n}")
    _add(tree, "docs/METER.md", "Knos is seven programs on Solana devnet.")
    _found(tree, "docs/METER.md", "counts seven programs")


def test_a_stage_cell_is_the_manifests_words_and_follows_the_manifest(tree):
    text = (tree / DEMO).read_text(encoding="utf-8")
    # what the rehearsal ran on staging ids is tested locally on the public ids, and no stage cell says otherwise
    assert "| `ledger_dedup` | tested locally |" in text and "| `pay_on_merge` | exercised on devnet |" in text and "on staging program ids |" not in text
    _swap(tree, DEMO, "| `statements` | tested locally |", "| `statements` | deployed on devnet |")
    _found(tree, DEMO, "the stage of statements is 'deployed on devnet'", "'tested locally'")
    assert dc.write(tree) == [DEMO] and dc.problems(tree) == []
    # the manifest moves (a capability gets a devnet transaction at its public id): every document that states its stage or a count fails
    _add(tree, CRITERIA, f"{dc.value('capabilities.exercised')} capabilities are exercised on devnet.")
    public = next(c for c in json.loads((tree / dc.MANIFEST).read_text(encoding="utf-8"))["capabilities"] if c["id"] == "pay_on_merge")["evidence"]["deployed"]
    data = _exercise(tree, "statements", deployed=public)
    lines = _found(tree, DEMO, "the stage of statements", "'exercised on devnet'")
    assert any(CRITERIA in line and "capabilities exercised" in line for line in lines)
    assert dc.stage_words(["ledger_dedup", "statements"], tree) == "`ledger_dedup`: tested locally; `statements`: exercised on devnet"
    # a run at any other address than the public id is never said as a plain "exercised on devnet" (capabilities.py refuses it)
    staged = _exercise(tree, "ledger_dedup", deployed={"program": "knos_pay_staging", "id": "FJJtqcRjQ9ATx37sBTCLUBxBqLUA9aQgSTLAsZynqtnH", "version": "2.1"})
    assert dc.stage_words(["ledger_dedup"], tree) == "exercised on devnet, on staging program ids" and dc.value("capabilities.exercised.staging", tree) == 1
    _found(tree, DEMO, "the stage of ledger_dedup", "'exercised on devnet, on staging program ids'")
    data = json.loads(json.dumps(staged))
    # README.md's table of programs is the manifest's versions
    other = "2.0" if data["programs"]["knos_pay"]["on_chain"] != "2.0" else "2.1"      # a version the committed table does not give
    data["programs"]["knos_pay"]["on_chain"] = other
    (tree / dc.MANIFEST).write_text(json.dumps(data), encoding="utf-8")
    _found(tree, "README.md", "the table of programs is not what the manifest says")
    assert "README.md" in dc.write(tree) and f"`knos-pay`, the escrow | `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k` | runs `{other}`" in (tree / "README.md").read_text(encoding="utf-8")


def test_no_document_names_a_time_for_the_pending_upgrade_that_the_upgrade_record_does_not_have(tree):
    _feed(tree)                                                  # pending: approved 2026-10-04 22:00, can run from 2026-10-06 22:00
    now, past = dc.upgrade_times(tree)
    assert now == {"2026-10-04 22:00", "2026-10-06 22:00"} and "2026-10-06 07:17" in past and "2026-10-04 07:17" in past
    # the withdrawn proposals' time, said as if it were the pending upgrade: the sentence 0.3.14 shipped
    _add(tree, "README.md", "The upgrade was proposed and approved by the multisig on 2026-10-04 07:17 UTC and can execute from 2026-10-06 07:17 UTC.")
    lines = _found(tree, "README.md", "names 2026-10-06 07:17 UTC for an upgrade", "not pending")
    assert sum("README.md" in line for line in lines) == 2
    _swap(tree, "README.md", "\nThe upgrade was proposed and approved by the multisig on 2026-10-04 07:17 UTC and can execute from 2026-10-06 07:17 UTC.\n", "")
    assert dc.problems(tree) == []
    # a time the record does not have at all (the scheduled run, ten minutes later), a day, another way to write it
    _add(tree, "docs/SECURITY.md", "The four proposals execute on 2026-10-06 at 22:13 UTC.")
    _found(tree, "docs/SECURITY.md", "names 2026-10-06 22:13 UTC", "has no such time")
    _add(tree, "docs/submission/weekly_update.md", "The upgrade cannot execute until 5 Oct.")
    _found(tree, "docs/submission/weekly_update.md", "names 2026-10-05 as a day an upgrade runs")
    _add(tree, WHY, "The pending upgrade can run from 6 Oct 2026, 07:17 UTC.")
    _found(tree, WHY, "names 2026-10-06 07:17 UTC")
    # the history may keep the withdrawn times, in words that say they are history, and only there
    said = "That build was proposed on 2026-10-04 07:17 UTC and withdrawn before 2026-10-06 07:17 UTC."
    _add(tree, "CHANGELOG.md", said)
    _add(tree, "docs/GOVERNANCE.md", said)
    assert not [line for line in dc.problems(tree) if line.startswith(("CHANGELOG.md", "docs/GOVERNANCE.md"))]
    _add(tree, "CHANGELOG.md", "The upgrade can execute from 2026-10-06 07:17 UTC.")
    _found(tree, "CHANGELOG.md", "names 2026-10-06 07:17 UTC", "in a sentence that says it was withdrawn")
    _add(tree, "docs/COMPARE.md", said)
    _found(tree, "docs/COMPARE.md", "names 2026-10-06 07:17 UTC")
    # the pending proposal's own time is the record's, so a document that gives it agrees with the record
    _add(tree, "docs/METER.md", "The pending upgrade can execute from 2026-10-06 22:00 UTC.")
    assert not [line for line in dc.problems(tree) if line.startswith("docs/METER.md")]


def test_the_release_needs_no_time_that_exists_only_after_the_push():
    bd = _script("bench_docs")
    assert not [name for name in bd.SLOTS if "upgrade" in name] and not hasattr(bd, "WHEN")
    release = " ".join((ROOT / "docs" / "RELEASE.md").read_text(encoding="utf-8").split())
    assert "## Nothing after the push goes into a commit" in (ROOT / "docs" / "RELEASE.md").read_text(encoding="utf-8")
    assert "never by a second commit" in release and "upgrade_proposed" not in release and "--set upgrade" not in release
    for doc in ("README.md", "docs/SECURITY.md"):                # where the time used to be stamped: they point at the record
        text = " ".join((ROOT / doc).read_text(encoding="utf-8").split())
        assert "names no time for" in text and "upgrades.json" in text and "knos status" in text
    assert not [f for f in json.loads((ROOT / "docs" / "facts.json").read_text(encoding="utf-8"))["facts"] if "text" in f]


def test_a_fee_maximum_or_the_old_limit_said_as_current_fails(tree):
    _add(tree, WHY, "The fee is 2.5%, at least 0.40 and at most 25 USDC.")
    _found(tree, WHY, "gives the fee a maximum")
    _add(tree, "docs/MARKET.md", "Knos's fee is already 2.5% (capped).")
    _found(tree, "docs/MARKET.md", "gives the fee a maximum")
    _add(tree, "docs/METER.md", "An order holds between 5 and 500 USDC.")
    _found(tree, "docs/METER.md", "gives the old limit of 500 as current")
    _add(tree, "docs/COMPARE.md", "The fee is at least 0.40 and has no maximum. An order holds at most 100,000 on devnet (it was 500 before 0.3.14).")
    assert not [line for line in dc.problems(tree) if line.startswith("docs/COMPARE.md")]
    # a rate is not an order's limit: GitHub's "500 an hour" stands
    _add(tree, "docs/LOAD.md", "GitHub's secondary limits: 80 content-generating requests a minute and 500 an hour; at most 500 requests in a burst.")
    assert not [line for line in dc.problems(tree) if line.startswith("docs/LOAD.md")]
    # under an older release the changelog may keep what was true then only with what replaced it
    assert "at most 25 USDC (replaced" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    _add(tree, "CHANGELOG.md", "## 0.3.1\n\n- The fee is at most 25 USDC.")
    _found(tree, "CHANGELOG.md", "gives the fee a maximum")


def test_an_unfilled_slot_two_values_for_one_fact_and_an_undated_total_fail(tree):
    _add(tree, "docs/submission/SUBMISSION.md", "[[stat: tests_passing]] tests pass.")
    _found(tree, "docs/submission/SUBMISSION.md", "the slot [[stat: tests_passing]] is not filled")
    _found(tree, "one fact, one value", "tests_passing has 2 values")
    _swap(tree, "docs/submission/SUBMISSION.md", "\n[[stat: tests_passing]] tests pass.\n", "")
    _add(tree, WHY, "From merge to paid took 57 seconds at the median.")
    _found(tree, "one fact, one value", "seconds_from_merge_to_paid has 2 values", "57 in docs/WHY.md")
    _swap(tree, WHY, "\nFrom merge to paid took 57 seconds at the median.\n", "")
    _add(tree, WHY, "9 tasks had been paid on the second deployment.")
    _found(tree, "one fact, one value", "tasks_paid_on_the_second_deployment has 2 values")
    _swap(tree, WHY, "\n9 tasks had been paid on the second deployment.\n", "")
    assert dc.problems(tree) == []
    # a total of payments is a reading of one day: it says the day, and two documents do not give two totals
    _add(tree, "docs/MARKET.md", "Knos's two deployments show 15 payments on devnet.")
    _found(tree, "docs/MARKET.md", "gives a total of 15 payments on devnet without the day it was read")
    _add(tree, "docs/METER.md", "By 5 Oct 2026 the two deployments had made 52 payments.")
    _found(tree, "the total of payments on devnet has 2 values")


def test_a_number_in_the_pitch_can_rest_on_a_registered_fact(tree, monkeypatch, capsys):
    cc = _script("claims_check")
    n = dc.value("capabilities.exercised")
    assert cc.check({"say": [str(n)], "what": "exercised", "claim": "capabilities.exercised"}, True)[0] is True
    assert cc.check({"say": [str(n + 1)], "what": "exercised", "claim": "capabilities.exercised"}, True)[0] is False
