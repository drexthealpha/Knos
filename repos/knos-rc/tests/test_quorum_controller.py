"""Two judges started by one account are one judge (docs/reference/STANDARD.md, "Evaluators"; docs/reference/CHARTER.md).

knos_pay 2.2 counts a quorum's judges by the owner of the repository each ran in. A person who starts runs in a
repository he owns and in one his organisation owns is two owners to the program and one controller in fact. The
relay refuses to carry the word that would complete such a quorum (knos.settle.v2.order_auto.controllers): the
refusal is off chain, and a program upgrade would make it the rule. Under 2.1 a marker names no run, so nothing can
be compared; the 2.1 build is not exercised here."""
from __future__ import annotations

import pytest

from knos.settle.v2 import order_auto

ME, ORG, OTHER, ALICE, BOB = 101, 202, 303, 11, 22


def test_runs_that_share_an_owner_or_a_starter_are_one_controller():
    # own repository (owner ME, started by ALICE) and a judge repository of another owner started by ALICE
    assert order_auto.distinct(0, [(ME, ALICE), None, (ORG, ALICE)]) == 2       # what the program counts
    assert order_auto.controllers(0, [(ME, ALICE), None, (ORG, ALICE)]) == 1     # what the relay counts
    assert order_auto.controllers(0, [(ME, ALICE), None, (ORG, BOB)]) == 2
    # three owners: the program counts three, and two runs started by one account make two controllers
    assert order_auto.distinct(ME, [(ME, ALICE), (OTHER, BOB), (ORG, BOB)]) == 3
    assert order_auto.controllers(ME, [(ME, ALICE), (OTHER, BOB), (ORG, BOB)]) == 2
    assert order_auto.controllers(ME, [(ME, ALICE), (OTHER, BOB), (ORG, 33)]) == 3
    # one owner was never two judges: the relay never counts more than the program
    for who in ([(ME, ALICE), None, (ME, BOB)], [(ME, ALICE), (ME, BOB), None], [None, (OTHER, ALICE), (ORG, BOB)], [None, None, None]):
        assert order_auto.controllers(ME, who) <= order_auto.distinct(ME, who), who
    assert order_auto.counted(0, [(ME, ALICE), None, (ME, BOB)]) == [(ME, ALICE)]


def test_the_refusal_is_said_in_plain_words():
    said = order_auto.ONE_STARTER
    assert "one account is one judge" in said and "does not carry" in said


pytest.importorskip("solders.litesvm")

from solders.keypair import Keypair  # noqa: E402

from _pay21 import each_build, pay21_build  # noqa: E402, F401 - the fixtures `build` and `pay21`
from test_relay2 import USDC, order_pay_jwt, user  # noqa: E402
from test_relay_quorum import OTHER as STRANGER  # noqa: E402
from test_relay_quorum import JUDGE, carry, funded_by_the_comment, on_chain, order_of, own  # noqa: E402


def test_the_relay_does_not_carry_a_quorum_two_runs_of_one_starter_would_complete(tmp_path, build):
    if not build.new:
        pytest.skip("knos_pay 2.1 markers name no run: nothing to compare")
    raw, options = funded_by_the_comment(tmp_path, build.v)
    env = c, _net = on_chain(build)
    wallet = Keypair().pubkey()
    payees = [(user(), 10_000, wallet)]
    starter = 4_242
    order = order_of(env, raw, options)
    r = carry(env, own(c, order, payees, raw, actor_id=starter))
    assert r["ok"] and r["quorum"] == {"have": 1, "of": 2}, r
    # the judge repository belongs to someone else, and its run was started by the same account
    r = carry(env, _named_by(c, order, payees, raw, STRANGER, starter))
    assert not r["ok"] and r["why"] == order_auto.ONE_STARTER, r
    o = c.order(order)
    assert (o.state, o.paid) == ("open", 0)
    # a run started by another account pays
    r = carry(env, _named_by(c, order, payees, raw, STRANGER, starter + 1))
    assert r["ok"] and "quorum" not in r and [p["amount"] for p in r["paid"]] == [20 * USDC], r


def _named_by(c, order, payees, raw, owner: int, actor: int) -> str:
    return order_pay_jwt(c, order, payees, terms=raw, file="attest.yml", event_name="push", repository_id=JUDGE["id"],
                         repository_owner_id=owner, actor_id=actor)


def test_an_own_round_runs_and_an_outside_order_is_refused_by_default():
    runs = [(ME, ALICE), (ORG, ALICE)]
    assert order_auto.own_round(BOB, runs, frozenset({BOB, ALICE}))             # the funder and every starter are the operator's own
    assert not order_auto.own_round(OTHER, runs, frozenset({BOB, ALICE}))       # an outside funder: refused
    assert not order_auto.own_round(BOB, [(ME, ALICE), (ORG, 44)], frozenset({BOB, ALICE}))   # one outside starter: refused
    assert not order_auto.own_round(BOB, runs, frozenset()) and not order_auto.own_round(BOB, [], frozenset({BOB}))
    assert "own round" in order_auto.OWN_ROUND.lower() and "not independent" in order_auto.OWN_ROUND


def test_the_relays_own_accounts_are_the_ones_the_records_label_own(monkeypatch):
    import json
    from pathlib import Path
    ids = json.loads((Path(__file__).resolve().parent.parent / "scripts" / "own_github_ids.json").read_text(encoding="utf-8"))["ids"]
    monkeypatch.delenv("KNOS_OWN_IDS", raising=False)
    assert order_auto.own_ids() == order_auto.OWN_IDS == frozenset(ids)
    monkeypatch.setenv("KNOS_OWN_IDS", "7, 8")
    assert order_auto.own_ids() == frozenset({7, 8})


def test_the_relay_carries_an_own_round_and_says_so(tmp_path, build, monkeypatch):
    if not build.new:
        pytest.skip("knos_pay 2.1 markers name no run: nothing to compare")
    from test_relay2 import MAINT
    starter = 4_242
    monkeypatch.setenv("KNOS_OWN_IDS", f"{MAINT},{starter}")       # the funder (MAINT) and the one starter are the operator's own
    raw, options = funded_by_the_comment(tmp_path, build.v)
    env = c, _net = on_chain(build)
    payees = [(user(), 10_000, Keypair().pubkey())]
    order = order_of(env, raw, options)
    assert c.order(order).funder_id == MAINT
    r = carry(env, own(c, order, payees, raw, actor_id=starter))
    assert r["ok"] and r["quorum"] == {"have": 1, "of": 2}, r
    r = carry(env, _named_by(c, order, payees, raw, STRANGER, starter))
    assert r["ok"] and [p["amount"] for p in r["paid"]] == [20 * USDC] and r["own_quorum"] == order_auto.OWN_ROUND, r
