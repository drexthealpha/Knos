"""The default terms a newcomer gets (knos.terms, "The defaults a newcomer gets"): a pull request that edits the files
that judge it is refused, the buyer's acceptance checks decide when the issue has them and are pinned by their hash,
and `terms.window` gives a work order a share kept back for a warranty window unless someone says otherwise (written
and tested here; knos.flow does not call it yet). Nothing here opens the network."""

from __future__ import annotations

import pytest

from knos import commands, policy, terms, terms3
from knos.settle.v2 import pay

UNIT = [{"name": "unit", "app": {"id": 15368}, "status": "completed", "conclusion": "success"}]
BUNDLE, OTHER = "ab" * 32, "cd" * 32


def funded(comment: str = "/knos fund 50", accept: str = "") -> dict:
    """The terms a comment buys in a repository with one passing check and no branch rule, as flow builds them."""
    return terms.build(commands.parse(comment, on_pull=False), [], UNIT, [], accept).terms


@pytest.mark.parametrize("path,glob", [(".github/workflows/ci.yml", ".github/**"), (".knos/acceptance/7/blackbox.sh", ".knos/**"),
                                       (".knos/policy.yml", ".knos/**")])
def test_a_pull_request_that_edits_the_files_that_judge_it_is_refused_by_default(path, glob):
    tm = funded()
    assert tm["deny"] == sorted(terms.DENY) == [".github/**", ".knos/**"]
    seen = terms.evidence(tm, UNIT, [])
    assert terms.accepted(tm, seen, ["src/fix.py"]) == (True, [])                # every check passed, nothing judged was touched
    assert terms.accepted(tm, seen, ["src/fix.py", path]) == (False, [f"changes `{path}`, which this bounty does not allow (`{glob}`)"])


def test_a_rename_out_of_the_judged_files_is_refused_and_the_funders_paths_cannot_open_them():
    tm = funded("/knos fund 50 paths: .github/**, src/**")
    assert tm["paths"] == [".github/**", "src/**"] and tm["deny"] == [".github/**", ".knos/**"]
    seen = terms.evidence(tm, UNIT, [])
    ok, why = terms.accepted(tm, seen, [".github/workflows/ci.yml"])
    assert not ok and "does not allow (`.github/**`)" in why[0]
    moved = [{"filename": "src/ci.yml", "previous_filename": ".github/workflows/ci.yml"}]          # a rename counts under both names
    assert not terms.accepted(tm, seen, moved)[0]


def test_the_buyers_acceptance_checks_decide_when_the_issue_has_them_and_their_hash_is_fixed_at_funding():
    merge, tests = funded(), funded(accept=BUNDLE)
    assert (merge["mode"], merge["accept"]) == ("merge", "")
    assert (tests["mode"], tests["accept"], tests["deny"]) == ("tests", BUNDLE, [".github/**", ".knos/**"])
    assert terms.terms_hash(tests) != terms.terms_hash(funded(accept=OTHER))      # other checks are other terms: the order refuses them


def test_terms_3_orders_keep_the_judged_files_protected_even_when_the_document_protects_nothing():
    doc = terms3.template("bug-fix")
    bare = terms3.validate({**doc, "changes": {**doc["changes"], "protected": []}}, strict=False)
    assert set(terms.DENY) <= set(terms3.order_terms(bare)["deny"])


def test_only_a_tip_asks_nothing_because_the_one_who_tips_has_seen_the_merged_work():
    assert terms.tip()["deny"] == [] and terms.tip()["checks"] == []


def test_a_work_order_keeps_ten_percent_back_for_fourteen_days_unless_the_comment_or_the_policy_says_otherwise():
    assert terms.window() == (1_000, 14) == (terms.HOLDBACK_PERCENT * 100, terms.WARRANTY_DAYS)
    assert terms.window(orders=False) == (0, 0)                                          # no work orders on that escrow: nothing held on chain
    assert terms.window(holdback=0) == (0, 0)                                            # `holdback 0` turns it off
    assert terms.window(holdback=20, warranty=30) == (2_000, 30)
    assert terms.window(warranty=30) == (0, 30)                                          # the funder's words decide, as before
    assert terms.window(holdback=15, policy_holdback_bps=500, policy_warranty_days=7) == (1_500, 7)
    assert terms.window(policy_holdback_bps=0, policy_warranty_days=0) == (0, 0)         # the policy turned it off
    assert terms.window(policy_holdback_bps=500, policy_warranty_days=7) == (500, 7)


def test_the_default_window_is_inside_what_the_comment_the_policy_and_the_program_allow():
    assert 0 < terms.HOLDBACK_PERCENT <= policy.MAX_HOLDBACK_PERCENT and 0 < terms.WARRANTY_DAYS <= policy.MAX_WARRANTY_DAYS
    said = commands.parse(f"/knos fund 50 holdback {terms.HOLDBACK_PERCENT} warranty {terms.WARRANTY_DAYS}", on_pull=False)
    assert terms.window(said.holdback, said.warranty) == terms.window()                  # writing the default out funds the same
    held, days = terms.window()
    got = pay.opts(pay.F_NEUTRAL, held, days)
    assert len(got) == 48 and int.from_bytes(got[1:3], "little") == 1_000 and int.from_bytes(got[3:5], "little") == 14
