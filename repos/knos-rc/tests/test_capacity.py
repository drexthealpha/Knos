"""scripts/capacity.py: what one word of the workflow asks of GitHub, counted against the tests' stand-in for it; the
model that names the limit a customer meets first, on fixed constants; and that docs/load.json's `workflow` section is
what the script computes from the committed measurements."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("knos_capacity_script", ROOT / "scripts" / "capacity.py")
cap = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cap
_spec.loader.exec_module(cap)

WORD = {"reads": 10, "writes": 1, "comments": 1, "tokens_signed": 1, "waits": 0, "jobs": 1}
FIXED = {
    "limits": {**cap.LIMITS, "github_token_requests_per_hour": 1_000, "content_per_hour": 500, "concurrent_jobs": {"Free": 20, "Team": 60}},
    "counted": {"own": {"command": {**WORD, "word": "command"}, "settle": {**WORD, "word": "settle"}, "attest_eval": {**WORD, "word": "eval"}},
                "public": {"command": {**WORD, "word": "command", "writes": 2, "comments": 2, "waits": 1},
                           "settle": {**WORD, "word": "settle", "writes": 2, "comments": 2, "waits": 1}}},
    "relay": {"polls_at_median": 12, "polls_at_p95": 52, "polls_at_timeout": 202, "log_comments_per_token": 1, "tokens_at_a_time": 4},
    "meter": {"statement_reads_at_most": 90_000, "evaluations_per_batch_at_most": 100_000},
    "chain": {"transactions_per_order": 12, "tokens_per_order": 2, "bytes_per_order": 8_000, "cu_per_order": 3_600_000,
              "one_relayer_orders_per_second": 8.0, "one_balance_orders_per_second": 200.0, "fee_account_orders_per_second": 150.0},
    "latency": {"merge_to_paid_s": {"count": 30, "median": 30, "p95": 150}},
}


def at(rows: list[dict]) -> dict:
    return {r["limit"]: r["at"] for r in rows}


def test_the_budget_of_a_deliverable_is_its_two_words_and_the_polling_only_the_public_worker_causes():
    own, pub = cap.budget(FIXED, cap.OWN), cap.budget(FIXED, cap.PUBLIC)
    assert (own["reads"], own["writes"], own["comments"], own["tokens_signed"], own["jobs"]) == (20, 2, 2, 2, 2)
    assert own["poll_requests"] == {"median": 0, "p95": 0, "timeout": 0} and own["token_requests"]["p95"] == 22 and own["relay_log_comments"] == 0
    assert pub["poll_requests"] == {"median": 24, "p95": 104, "timeout": 404} and pub["token_requests"] == {"median": 48, "p95": 128, "timeout": 428}
    assert (pub["comments"], pub["relay_log_comments"], pub["transactions"], pub["bytes"]) == (4, 2, 12, 8_000)


def test_a_wait_is_one_lookup_and_a_read_every_three_seconds():
    assert [cap.polls(s) for s in (0, 2, 3, 25, 600)] == [2, 2, 3, 10, 202]


def test_each_limit_binds_where_its_arithmetic_says():
    own = at(cap.bounds(FIXED, 1, 10))
    assert own == {"GITHUB_TOKEN requests an hour": 1_000 * 24 // 22, "comments made in one repository": 500 * 24 // 2,
                   "concurrent jobs (Free plan)": 20 * 86_400 // (2 * 150), "the meter's statement, recomputed from the logs": 3_000,
                   "the fee key's own account": 8 * 86_400, "the fee account of the mint": 150 * 86_400, "the Balance, one writable account": 200 * 86_400}
    pub = at(cap.bounds(FIXED, 1, 10, way=cap.PUBLIC))
    assert pub["GITHUB_TOKEN requests an hour"] == 1_000 * 24 // 128 and pub["comments made in one repository"] == 3_000
    assert pub["the public relay's log comments"] == 500 * 24 // 2 and pub[cap.SERIAL_PASS] == 86_400 // (2 * 30)
    assert "the fee key's own account" not in pub and cap.SERIAL_PASS not in own


def test_repositories_plan_peak_and_relayers_move_only_the_limits_they_own():
    one, ten = at(cap.bounds(FIXED, 1, 10, way=cap.PUBLIC)), at(cap.bounds(FIXED, 10, 10, way=cap.PUBLIC))
    per_repo = {"GITHUB_TOKEN requests an hour", "comments made in one repository"}
    assert {k for k in one if ten[k] != one[k]} == per_repo and all(one[k] * 10 <= ten[k] < one[k] * 10 + 10 for k in per_repo)
    team = at(cap.bounds(FIXED, 1, 10, plan="Team"))
    assert team["concurrent jobs (Team plan)"] == 3 * at(cap.bounds(FIXED, 1, 10))["concurrent jobs (Free plan)"]
    busy = at(cap.bounds(FIXED, 1, 10, peak=4.0))
    assert busy["GITHUB_TOKEN requests an hour"] == 1_000 * 6 // 22 and busy["the fee account of the mint"] == 150 * 86_400 // 4
    assert busy["the meter's statement, recomputed from the logs"] == 3_000      # a month's count does not care when in the day
    more = at(cap.bounds(FIXED, 1, 10, way=cap.PUBLIC, relayers=4))
    assert more[cap.SERIAL_PASS] == 4 * one[cap.SERIAL_PASS]
    assert more["the fee account of the mint"] == one["the fee account of the mint"]


def test_the_answer_names_the_first_limit_on_the_work_and_lists_what_the_volume_is_past():
    a = cap.answer(FIXED, 1, 10)
    assert (a["first"], a["at"], a["fits"], a["binding"]) == ("GITHUB_TOKEN requests an hour", 1_090, True, [])
    a = cap.answer(FIXED, 1, 1_440, way=cap.PUBLIC)
    assert (a["first"], a["at"], a["fits"]) == ("GITHUB_TOKEN requests an hour", 187, False)
    assert a["binding"] == ["GITHUB_TOKEN requests an hour", cap.SERIAL_PASS]
    assert [r["at"] for r in a["bounds"]] == sorted(r["at"] for r in a["bounds"]) and a["bounds"][1]["load"] == 1.0
    # many repositories: the requests are no longer first. Reading the count back is past its limit, and is never named as what stops the work
    a = cap.answer(FIXED, 100, 4_000)
    assert a["bounds"][0]["limit"] == "the meter's statement, recomputed from the logs" and a["bounds"][0]["binds"]
    assert (a["first"], a["at"], a["fits"]) == ("concurrent jobs (Free plan)", 5_760, True)
    assert a["binding"] == ["the meter's statement, recomputed from the logs"]
    without = copy.deepcopy(FIXED)
    del without["counted"]["own"]["attest_eval"]
    assert "the meter's statement, recomputed from the logs" not in at(cap.bounds(without, 1, 10))


def test_no_limit_needs_a_program_change_and_every_limit_says_what_lifts_it():
    """The fee account was the one that did, until 0.3.22: the program takes any token account of the mint that FEE_OWNER
    owns, so K of them spread its writes (tests/test_fee_shards.py)."""
    rows = cap.bounds(FIXED, 1, 10) + cap.bounds(FIXED, 1, 10, way=cap.PUBLIC)
    assert not [r["limit"] for r in rows if "NEEDS A PROGRAM CHANGE" in r["lift"].upper()]
    assert {r["limit"] for r in rows if "knos relay fee-accounts" in r["lift"]} == {"the fee account of the mint"}
    assert all(r["lift"] and r["from"] and r["scope"] for r in rows)
    lift = {r["limit"]: r["lift"] for r in rows}
    assert "one Balance per team" in lift["the Balance, one writable account"] and "batching the meter" in lift["the meter's statement, recomputed from the logs"]
    assert "several relayers" in lift[cap.SERIAL_PASS] and "KNOS_RELAY_KEY" in lift["the public relay's log comments"]


def test_a_statement_costs_a_request_a_transaction_and_a_page_a_hundred():
    assert [cap.statement_requests(n) for n in (0, 1, 99, 100, 300)] == [2, 3, 101, 103, 305]
    assert cap.statement_requests(30_000, 1_000) == 32


def test_the_words_are_counted_against_the_stand_in_for_github():
    pytest.importorskip("solders")
    got = cap.count()
    own, pub = got["own"], got["public"]
    assert set(own) == {"command", "settle", "attest_pay", "attest_eval"} and set(pub) == {"command", "settle"}
    for word in ("command", "settle"):          # the public worker costs a word one more write, a comment, and a wait; it reads the same
        o, p = own[word], pub[word]
        assert (p["reads"], p["writes"], p["comments"], p["waits"]) == (o["reads"], o["writes"] + 1, o["comments"] + 1, 1) and o["waits"] == 0
    assert all(x["tokens_signed"] == 1 and x["jobs"] == 1 and x["reads"] > 0 for way in got.values() for x in way.values())
    assert own["attest_eval"]["writes"] == own["attest_pay"]["writes"] == 0     # a seller's or a meter's run with a key writes nothing to GitHub
    assert cap.count() == got                                                    # the same every time


def test_the_committed_section_is_what_the_script_computes_and_is_about_the_committed_builds():
    pytest.importorskip("solders")
    doc = json.loads(cap.JSON.read_text(encoding="utf-8"))
    w = doc["workflow"]
    assert w == json.loads(json.dumps(cap.workflow()))
    assert w["chain"]["fixtures"] == doc["local"]["fixtures"] and w["limits"] == cap.LIMITS
    assert [(a["repositories"], a["per_day"], a["way"]) for a in w["customers"]] == [(r, n, way) for r, n in cap.SIZES for way in ("own", "public")]
    assert all(u.startswith("https://") for u in w["sources"].values())
    text = (ROOT / "docs" / "reference" / "LOAD.md").read_text(encoding="utf-8")
    assert "## 5. The whole workflow" in text and "NEEDS A PROGRAM CHANGE" not in text and "K fee accounts, no program change" in text and all(u in text for u in w["sources"].values())
