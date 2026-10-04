"""The public numbers (scripts/network_stats.py): counted from the escrows' own log lines of both deployments, the
public relay log and GitHub, with Knos's own activity, self-payment and faucet money kept out of "outside".

Recorded inputs (tests/web/recorded):

    devnet_first_deployment.json     every transaction of the first deployment's escrow on devnet, as the cluster
                                     returned them on 2 Oct 2026
    second_deployment_scenario.json  twelve jobs run through the second deployment's test build in LiteSVM (`scenario`
                                     below), as the program logged them; with the relay log lines a relay would have
                                     written for them and GitHub's answers about the comments and merges behind them
    stats_empty.json, stats_first_deployment.json, stats_with_data.json
                                     what the script writes for no history, for the first input alone and for both:
                                     the samples tests/web/site.mjs renders

    PYTHONPATH=src python tests/test_network_stats.py --record     runs the scenario again and rewrites the last four
    PYTHONPATH=src python tests/test_network_stats.py              rewrites the three samples from the recorded inputs
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest
from solders.pubkey import Pubkey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import network_stats  # noqa: E402

from knos import chain  # noqa: E402
from knos.settle import pay  # noqa: E402
from knos.settle.v2 import pay as pay2  # noqa: E402

RECORDED = ROOT / "tests" / "web" / "recorded"
PAY1, PAY2 = str(pay.PAY_ID), str(pay2.PAY_ID)
KNOS = 142920951                       # the one id in scripts/own_github_ids.json
OWN = frozenset({KNOS})
USDC, DAY = 1_000_000, 86_400
SAMPLED_AT = 1_791_000_000             # the "updated" time of the samples


def tx(at: int, signer: str, *lines: str, err=None, program: str = PAY1, keys=()) -> dict:
    """A confirmed transaction in which `program` logged these lines."""
    logs = [f"Program {program} invoke [1]", *[f"Program log: {x}" for x in lines], f"Program {program} success"]
    return {"blockTime": at, "meta": {"err": err, "logMessages": logs}, "transaction": {"message": {"accountKeys": [signer, *keys, program]}}}


def events(*txs: dict) -> list[dict]:
    out = []
    for n, t in enumerate(txs):
        out += [{**ev, "tx": t.get("signature", f"sig{n}")} for ev in network_stats.events_of(t)]
    return out


def recorded(name: str) -> dict:
    return json.loads((RECORDED / name).read_text(encoding="utf-8"))


# ---- reading the chain's log ---------------------------------------------------------------------------------------
def test_events_come_only_from_the_escrow_and_only_from_transactions_that_succeeded():
    good = tx(100, "relayer", "knos:funded repo=5 issue=7 amount=50000000 mode=0 by=900", "something else")
    assert network_stats.events_of(good) == [{"event": "funded", "v": 1, "at": 100, "signer": "relayer", "keys": ["relayer", PAY1], "repo": 5,
                                             "issue": 7, "amount": 50000000, "mode": 0, "by": 900}]
    assert network_stats.events_of(tx(100, "r", "knos:paid repo=5 issue=7 author=1 amount=1 fee=1", err={"x": 1})) == []
    assert network_stats.events_of(None) == []
    # the second deployment's lines, and the terms as they were logged
    second = tx(200, "r", "knos2:funded repo=5 issue=7 amount=5000000 mode=0 by=900 source=Bal1 faucet=0", 'knos2:terms {"checks":[],"v":1}', program=PAY2)
    assert [(e["event"], e["v"]) for e in network_stats.events_of(second)] == [("funded", 2), ("terms", 2)]
    assert network_stats.events_of(second)[1]["json"] == '{"checks":[],"v":1}' and network_stats.events_of(second)[0]["source"] == "Bal1"
    # a line is the escrow's only when the escrow printed it: another program in the same transaction can print anything
    forged = {"blockTime": 300, "meta": {"err": None, "logMessages": [
        f"Program {PAY2} invoke [1]", "Program log: knos2:balance owner=7 authority=A mint=M", f"Program {PAY2} success",
        "Program Evi1111111111111111111111111111111111111111 invoke [1]", "Program log: knos2:paid repo=1 issue=1 payee=7 amount=99 fee=1 to=W",
        f"Program {PAY2} invoke [2]", "Program log: knos2:paused until=0", f"Program {PAY2} success",
        "Program log: knos2:paid repo=1 issue=1 payee=7 amount=99 fee=1 to=W", "Program Evi1111111111111111111111111111111111111111 success"]},
        "transaction": {"message": {"accountKeys": ["r"]}}}
    assert [e["event"] for e in network_stats.events_of(forged)] == ["balance", "paused"]
    # each escrow speaks its own prefix: a `knos2:` line from the first deployment's program id is nothing
    assert network_stats.events_of(tx(1, "r", "knos2:paid repo=1 issue=1 payee=7 amount=99 fee=1 to=W", program=PAY1)) == []
    assert network_stats.events_of(tx(1, "r", "knos:paid repo=1 issue=1 author=7 amount=99 fee=1", program=PAY2)) == []
    # a versioned transaction's accounts include the ones it loaded from a table
    loaded = tx(1, "r", "knos2:paused until=5", program=PAY2)
    loaded["meta"]["loadedAddresses"] = {"writable": ["W1"], "readonly": ["R1"]}
    assert network_stats.events_of(loaded)[0]["keys"] == ["r", PAY2, "W1", "R1"]


def test_the_first_deployments_whole_history_on_devnet_is_knos_paying_itself():
    """The recorded devnet history: 11 jobs funded, 6 paid, one proven and vetoed back, two claims. Every one is Knos's
    own account funding and being paid, so outside use is zero, and a zero is what the numbers say."""
    got = events(*recorded("devnet_first_deployment.json")["transactions"])
    assert [e["event"] for e in got].count("funded") == 11 and {e["v"] for e in got} == {1}
    s = network_stats.summarize(got, OWN)
    assert s["outside"] == {"funded": 0, "completed": 0, "funders": 0, "payees": 0, "repeat_funders": 0, "repositories": 0, "funded_amount": 0,
                            "paid_amount": 0, "fees": 0}
    assert s["apart"]["own"] == {"funded": 11, "completed": 6, "funders": 1, "payees": 1, "repeat_funders": 1, "repositories": 2,
                                 "funded_amount": 124_000_000, "paid_amount": 62_400_000, "fees": 1_600_000}
    assert s["apart"]["self"]["completed"] == 0 and s["apart"]["test"]["funded"] == 0
    assert s["totals"] == {"funded": 11, "completed": 6, "open": 5, "held": 0, "funded_amount": 124_000_000, "paid_amount": 62_400_000, "refunded": 0,
                           "unmatched_paid": 0, "claimed": 2, "claimed_amount": 52_650_000, "vetoed": 1, "bound": 0, "balances": 0, "withdrawn": 0,
                           "paused": 0}
    assert s["by_deployment"] == {"first": {"funded": 11, "completed": 6}, "second": {"funded": 0, "completed": 0}}
    assert s["funnel"] == {"installed": None, "installed_note": "not measured", "funded": 0, "completed": 0, "funded_again": 0}
    # what docs/COMPARE.md reports of this history: the median from funding to payment over its 6 payments
    assert s["latency"]["funded_to_paid"] == {"count": 6, "median": 159, "p90": 386, "slowest": 386}
    assert len(s["recent"]) == 6 and s["recent"][0]["kind"] == "own" and s["recent"][0]["issue"] == 17 and s["recent"][0]["seconds"] == 95
    # each event found its job by the job's address among the transaction's accounts: the job that was proven and then
    # vetoed is open again, and it is the one on issue 2
    jobs, _ = network_stats.jobs_of(got)
    assert sorted(j["issue"] for j in jobs if j["state"] == "open") == [2, 15, 29, 30, 31]
    assert all(j["address"] == str(pay.job_pda(j["repo"], j["issue"])) for j in jobs)
    # were that account not Knos's, the same history would be self-payment and free faucet money: still not outside
    s = network_stats.summarize(got, frozenset())
    assert s["outside"]["funded"] == 0 and s["apart"]["own"]["funded"] == 0
    assert (s["apart"]["self"]["completed"], s["apart"]["test"]["funded"], s["apart"]["test"]["completed"]) == (6, 5, 0)


# ---- who is outside ------------------------------------------------------------------------------------------------
def funded2(at, repo, issue, amount, by, source, faucet=0, signer="relayer"):
    return tx(at, signer, f"knos2:funded repo={repo} issue={issue} amount={amount} mode=0 by={by} source={source} faucet={faucet}",
              'knos2:terms {"accept":"","checks":[],"deny":[],"mode":"merge","paths":[],"reserve":7,"v":1}', program=PAY2)


def paid2(at, repo, issue, payee, amount, to="Wallet1"):
    fee = pay2.fee_of(amount)
    return tx(at, "relayer", f"knos2:paid repo={repo} issue={issue} payee={payee} amount={amount - fee} fee={fee} to={to}", program=PAY2)


def test_a_job_is_outside_only_when_someone_else_put_their_own_money_in_and_did_not_pay_themselves():
    w = {name: str(Pubkey(bytes([n]) * 32)) for n, name in enumerate(["usdc", "a", "b", "c", "knos", "d"], 1)}
    bal = {name: str(pay2.balance_pda(owner, Pubkey.from_string(w[name]), Pubkey.from_string(w["usdc"])))
           for name, owner in (("a", 5001), ("c", 5003), ("knos", KNOS), ("d", 5004))}
    faucet = str(pay2.faucet_balance_pda(5005))
    opened = [tx(10 + n, w[name], f"knos2:balance owner={owner} authority={w[name]} mint={w['usdc']}", program=PAY2)
              for n, (name, owner) in enumerate((("a", 5001), ("c", 5003), ("knos", KNOS), ("d", 5004)))]
    history = [
        *opened,
        funded2(100, 7001, 1, 20 * USDC, 6001, bal["a"]),                 # an outside owner's Balance, a maintainer's comment
        paid2(400, 7001, 1, 8001, 20 * USDC),                             # ... paid to someone else: outside
        funded2(500, 7001, 2, 30 * USDC, 6001, bal["a"]),                 # the same funder again, after that payment
        funded2(600, 7003, 3, 15 * USDC, 0, w["b"], signer=w["b"]),       # a wallet funds
        paid2(900, 7003, 3, 8001, 15 * USDC),                             # ... the same payee, a second funder
        funded2(1000, 7004, 1, 8 * USDC, 5003, bal["c"]),                 # the owner funds
        paid2(1100, 7004, 1, 5003, 8 * USDC),                             # ... and is paid: self
        funded2(1200, 7100, 1, 25 * USDC, KNOS, bal["knos"]),             # Knos funds
        paid2(1300, 7100, 1, 8003, 25 * USDC),                            # ... someone else: own
        funded2(1400, 7005, 2, 9 * USDC, 5004, bal["d"]),                 # someone else funds
        paid2(1500, 7005, 2, KNOS, 9 * USDC),                             # ... Knos is paid: own
        tx(1600, "relayer", f"knos2:balance owner=5005 authority={pay2.auth_pda()} mint={pay2.faucet_mint()}", program=PAY2),
        funded2(1600, 7006, 1, 25 * USDC, 6005, faucet, faucet=1),        # the faucet's free test money
        paid2(1700, 7006, 1, 8004, 25 * USDC),                            # ... test
        funded2(1800, 7007, 1, 6 * USDC, 0, w["b"], signer=w["b"]),       # a wallet funds
        paid2(1900, 7007, 1, 8006, 6 * USDC, to=w["b"]),                  # ... and the money goes back to that wallet: self
        tx(2000, "relayer", "knos2:held repo=7001 issue=2 payee=8005 until=99999", program=PAY2),
        funded2(2100, 7002, 5, 5 * USDC, 6001, bal["a"]),
        tx(2200, "relayer", "knos2:refunded repo=7002 issue=5 amount=5000000", program=PAY2),
        tx(2300, "relayer", f"knos2:bound user=8005 wallet={w['d']}", program=PAY2),
        paid2(2400, 9999, 1, 8007, 5 * USDC),                             # a payment whose funding nobody read
    ]
    s = network_stats.summarize(events(*history), OWN)
    assert s["outside"] == {"funded": 4, "completed": 2, "funders": 2, "payees": 1, "repeat_funders": 1, "repositories": 3,
                            "funded_amount": 70 * USDC, "paid_amount": 35 * USDC - 875_000, "fees": 875_000}
    assert (s["apart"]["own"]["funded"], s["apart"]["own"]["completed"]) == (2, 2)
    assert (s["apart"]["self"]["funded"], s["apart"]["self"]["completed"], s["apart"]["self"]["funders"]) == (2, 2, 2)
    assert (s["apart"]["test"]["funded"], s["apart"]["test"]["completed"], s["apart"]["test"]["payees"]) == (1, 1, 1)
    assert s["totals"]["funded"] == 9 and s["totals"]["completed"] == 8 and s["totals"]["unmatched_paid"] == 1     # 7 of the 9, and the unread one
    assert (s["totals"]["held"], s["totals"]["refunded"], s["totals"]["open"], s["totals"]["bound"], s["totals"]["balances"]) == (1, 1, 0, 1, 4)
    assert s["funnel"] == {"installed": None, "installed_note": "not measured", "funded": 6, "completed": 2, "funded_again": 1}
    kinds = {(j["repo"], j["issue"]): network_stats.kind_of(j, OWN) for j in network_stats.jobs_of(events(*history))[0]}
    assert kinds == {(7001, 1): "outside", (7001, 2): "outside", (7003, 3): "outside", (7004, 1): "self", (7100, 1): "own", (7005, 2): "own",
                     (7006, 1): "test", (7007, 1): "self", (7002, 5): "outside"}
    # a wallet has no GitHub id: a Balance that one of Knos's wallets opened, and a job one of them funded, are Knos's
    mine = network_stats.summarize(events(*history), OWN, frozenset({w["a"], w["b"]}))
    assert mine["outside"]["funded"] == 0 and mine["apart"]["own"]["funded"] == 7 and mine["apart"]["self"]["funded"] == 1
    # the terms a funding logged stay with its job
    assert network_stats.jobs_of(events(*history))[0][0]["terms"].startswith('{"accept":""')


def test_a_payee_of_knos_is_never_outside_and_a_repeat_needs_a_payment_in_between():
    got = events(tx(1, "r", "knos:funded repo=1 issue=1 amount=1000000 mode=0 by=222"),
                 tx(2, "r", "knos:paid repo=1 issue=1 author=900 amount=950000 fee=50000"))
    s = network_stats.summarize(got, frozenset({900}))
    assert s["outside"]["completed"] == 0 and s["apart"]["own"]["completed"] == 1
    # two fundings by one funder with no payment between them are not a repeat; one after a payment is
    w = str(Pubkey(bytes([9]) * 32))
    two = [funded2(1, 5, 1, USDC, 0, w, signer=w), funded2(2, 5, 2, USDC, 0, w, signer=w)]
    assert network_stats.summarize(events(*two), OWN)["outside"]["repeat_funders"] == 0
    assert network_stats.summarize(events(*two, paid2(3, 5, 1, 77, USDC), funded2(4, 5, 3, USDC, 0, w, signer=w)), OWN)["outside"]["repeat_funders"] == 1
    # two jobs on one issue from two funders: each payment closes the job whose money it is
    v = str(Pubkey(bytes([8]) * 32))
    both = [funded2(1, 5, 1, 2 * USDC, 0, w, signer=w), funded2(2, 5, 1, 3 * USDC, 0, v, signer=v), paid2(3, 5, 1, 77, 3 * USDC)]
    jobs, _ = network_stats.jobs_of(events(*both))
    assert [(j["amount"], j["state"]) for j in jobs] == [(2 * USDC, "open"), (3 * USDC, "paid")]


def test_money_that_goes_back_to_its_own_wallet_or_to_knos_is_never_outside():
    w, other, usdc = (str(Pubkey(bytes([n]) * 32)) for n in (21, 22, 20))
    bal = str(pay2.balance_pda(5001, Pubkey.from_string(w), Pubkey.from_string(usdc)))
    opened = tx(1, w, f"knos2:balance owner=5001 authority={w} mint={usdc}", program=PAY2)
    kind = lambda *history, wallets=frozenset(): network_stats.kind_of(network_stats.jobs_of(events(*history))[0][0], OWN, wallets)  # noqa: E731
    def from_balance(to):
        return [opened, funded2(10, 1, 1, USDC, 6001, bal), paid2(20, 1, 1, 9001, USDC, to=to)]

    # a Balance's money paid to the wallet that opened it is self-payment, whoever the GitHub account is that was paid
    assert kind(*from_balance(w)) == "self"
    assert kind(*from_balance(other)) == "outside"
    assert kind(*from_balance(other), wallets=frozenset({other})) == "own"        # Knos's own wallet was paid
    assert kind(*from_balance(other), wallets=frozenset({w})) == "own"            # Knos's own wallet funded
    # an id of 0 is "a wallet, no account": a wallet's job paid to an address with no account is not the same person twice
    assert kind(funded2(10, 1, 1, USDC, 0, w, signer=w), paid2(20, 1, 1, 0, USDC, to=other)) == "outside"
    assert kind(funded2(10, 1, 1, USDC, 0, w, signer=w), paid2(20, 1, 1, 0, USDC, to=w)) == "self"


def _table(m: dict) -> dict:
    """What the Numbers table reads of a measurement."""
    return {k: m[k] for k in ("count", "median", "p90", "slowest")}


def test_the_spread_of_a_latency():
    assert network_stats._spread([]) == {"count": 0, "median": None, "p90": None, "slowest": None}
    assert network_stats._spread([40]) == {"count": 1, "median": 40, "p90": 40, "slowest": 40}
    assert network_stats._spread([30, 48, 75, 620]) == {"count": 4, "median": 61, "p90": 620, "slowest": 620}
    assert network_stats._spread(list(range(1, 101))) == {"count": 100, "median": 50, "p90": 90, "slowest": 100}
    assert network_stats._spread([5, None, -3]) == {"count": 1, "median": 5, "p90": 5, "slowest": 5}      # a start after its end is no measurement


# ---- the relay log and GitHub ----------------------------------------------------------------------------------------
def test_the_relay_log_gives_the_latency_a_person_saw():
    history = [{**funded2(1000, 7001, 1, 20 * USDC, 6001, "Bal1"), "signature": "FUND1"}, {**paid2(5000, 7001, 1, 8001, 20 * USDC), "signature": "PAY1"},
               {**funded2(6000, 7001, 2, 5 * USDC, 6001, "Bal1"), "signature": "FUND2"}, {**paid2(9000, 7001, 2, 8001, 5 * USDC), "signature": "PAY2"}]
    log = [{"created_at": "1970-01-01T00:16:50Z", "body": "knos-relay fund octo/widgets#1 0123456789abcdef ok sig=W1,S1,FUND1 note=20.00 test USDC is in escrow for issue #1. Job X. t=9"},
           {"created_at": "1970-01-01T01:23:30Z", "body": "knos-relay proof octo/widgets#12 1111111111111111 ok sig=PAY1 note=paid t=6.5\n"
                                                            "knos-relay fund octo/widgets#9 2222222222222222 fail this issue already has a bounty\n"
                                                            "knos-relay settle - - ok sig=CRANK note=a proven bounty's review window passed; paid"},
           {"created_at": "1970-01-01T01:40:10Z", "body": "knos-relay fund octo/widgets#2 3333333333333333 ok asked=5880 sig=FUND2 note=x t=11\n"
                                                            "knos-relay proof octo/widgets#13 4444444444444444 ok sig=none note=another relayer carried it first t=2\n"
                                                            "knos-relay proof octo/widgets#14 5555555555555555 ok sig=PAY2 note=y t=3 was the wait for review\nnot a line"}]
    lines = network_stats.relay_lines(log)
    assert [(r["kind"], r["repo"], r["number"], r["sigs"], r["asked"]) for r in lines] == [
        ("fund", "octo/widgets", 1, ["W1", "S1", "FUND1"], None), ("proof", "octo/widgets", 12, ["PAY1"], None),
        ("fund", "octo/widgets", 2, ["FUND2"], 5880), ("proof", "octo/widgets", 13, [], None), ("proof", "octo/widgets", 14, ["PAY2"], None)]
    assert lines[0]["posted"] == 1010 and lines[0]["token"] == "0123456789abcdef"
    # the relay's own seconds are the line's last word: a ` t=` inside the note is the note's, a line without one has none
    assert [r["t"] for r in lines] == [9.0, 6.5, 11.0, 2.0, None]
    # ... and a line that sent no transaction (another relayer carried it first) is not the relay's time
    assert network_stats.relay_seconds(lines) == {"fund": {"count": 2, "median": 10, "p90": 11, "slowest": 11},
                                                  "pay": {"count": 1, "median": 6, "p90": 6, "slowest": 6}}
    assert network_stats.relay_seconds([]) == {"fund": network_stats._spread([]), "pay": network_stats._spread([])}
    asked = []

    def get(path):
        asked.append(path)
        return {"repos/octo/widgets/issues/1": {"body": "Slugify keeps punctuation.", "created_at": "1970-01-01T00:01:00Z"},
                "repos/octo/widgets/issues/1/comments?per_page=100": [
                    {"body": "/knos fund 5", "created_at": "1970-01-01T00:10:00Z"},                 # an earlier try
                    {"body": "thanks!\n/knos bounty 20 checks: test", "created_at": "1970-01-01T00:12:54Z"},     # 774: the one that funded
                    {"body": "`/knos fund 20` is how", "created_at": "1970-01-01T00:13:00Z"},        # not a command: it does not start the line
                    {"body": "/knos fund 20", "created_at": "1970-01-01T00:30:00Z"}],                # after the funding landed
                "repos/octo/widgets/pulls/12": {"merged_at": "1970-01-01T01:22:32Z"},                # 4952
                "repos/octo/widgets/pulls/14": {"merged_at": None}}[path]                            # GitHub does not say
    ev = events(*history)
    whole = network_stats.latency(lines, ev, get)
    got = {k: _table(v) for k, v in whole.items()}
    # the one measurement says what it is over: the sample, the days, which escrow paid, and what gave no sample
    m = whole["merge_to_paid"]
    assert (m["n"], m["p50"], m["p95"], m["window"], m["deployment"]) == (1, 48, 48, {"from": "1970-01-01", "to": "1970-01-01"}, {"first": 0, "second": 1})
    assert (m["lines"], m["not_timed"]) == (3, 2) and "merged_at" in m["definition"] and "samples" not in m       # one sent nothing, one has no merge time
    assert network_stats.measure("merge_to_paid", lines, ev, get)["samples"] == [{"at": 5000, "seconds": 48, "t": 6.5, "sigs": ["PAY1"], "token": "1111111111111111", "v": 2}]
    assert got == {"comment_to_funded": {"count": 2, "median": 173, "p90": 226, "slowest": 226},         # 1000 - 774, and 6000 - 5880
                   "merge_to_paid": {"count": 1, "median": 48, "p90": 48, "slowest": 48}}                # 5000 - 4952
    assert "repos/octo/widgets/issues/2" not in asked            # that line carried its own start time
    # without GitHub only the lines that carry their start are measured, and nothing is guessed
    assert {k: _table(v) for k, v in network_stats.latency(lines, ev, None).items()} == {"comment_to_funded": {"count": 1, "median": 120, "p90": 120, "slowest": 120},
                                                      "merge_to_paid": {"count": 0, "median": None, "p90": None, "slowest": None}}

    def down(path):
        raise OSError("GitHub is down")
    assert network_stats.latency(lines, ev, down)["comment_to_funded"]["count"] == 1
    # an issue whose own description carried the command: the issue's time is the start
    assert network_stats.asked_at(lines[0], 1000, lambda p: [] if p.endswith("comments?per_page=100") else
                                  {"body": "Do this.\n\n/knos fund 20", "created_at": "1970-01-01T00:02:00Z"}) == 120


def test_the_relay_writes_its_log_in_the_form_this_reads():
    ghrelay = pytest.importorskip("knos.proof.ghrelay")
    if not hasattr(ghrelay, "log_line"):
        pytest.skip("the relay no longer has log_line: point this test at what writes the relay log now")
    jwt = "eyJhbGciOiJSUzI1NiJ9.e30.c2ln"
    line = ghrelay.log_line("fund", "octo/widgets", 7, jwt, {"ok": True, "sigs": ["a", "b", "c", "FUND"], "note": "20.00 test USDC is in escrow."})
    [got] = network_stats.relay_lines([{"created_at": "2026-10-02T09:37:20Z", "body": line}])
    assert (got["kind"], got["repo"], got["number"], got["sigs"][-1], got["token"]) == ("fund", "octo/widgets", 7, "FUND", ghrelay.token_id(jwt))
    assert got["posted"] == 1790933840
    refused = ghrelay.log_line("fund", "octo/widgets", 7, jwt, {"ok": False, "why": "this issue already has the repository's bounty"})
    assert network_stats.relay_lines([{"created_at": "2026-10-02T09:37:20Z", "body": refused}]) == []


def test_the_relay_log_is_every_comment_of_its_issues():
    pages = {"repos/drexthealpha/Knos/issues?labels=knos-relay&state=all&per_page=100": [{"number": 28}, {"number": 3}],
             "repos/drexthealpha/Knos/issues/28/comments?per_page=100&page=1": [{"body": f"c{n}"} for n in range(100)],
             "repos/drexthealpha/Knos/issues/28/comments?per_page=100&page=2": [{"body": "last"}],
             "repos/drexthealpha/Knos/issues/3/comments?per_page=100&page=1": []}
    got = network_stats.relay_log(pages.__getitem__)
    assert len(got) == 101 and got[-1] == {"body": "last"}


def test_installed_is_the_public_repositories_whose_workflows_call_knos_and_not_knos_own():
    def item(repo_id, name, owner, path=".github/workflows/knos.yml", **repo):
        return {"path": path, "repository": {"id": repo_id, "full_name": name, "owner": {"id": owner}, "private": False, "fork": False, **repo}}
    answers = {0: {"incomplete_results": False, "items": [item(7001, "octo/widgets", 5001), item(7001, "octo/widgets", 5001, ".github/workflows/knos-check.yml"),
                                                          item(1353152983, "drexthealpha/Knos", KNOS), item(7090, "copy/Knos", 5090, fork=True),
                                                          item(7091, "octo/notes", 5001, "docs/knos.md")]},
               1: {"incomplete_results": True, "items": [item(7003, "acme/gadgets", 5002)]},
               2: {"items": []}}
    asked = []

    def get(path):
        asked.append(path)
        return answers[len(asked) - 1]
    got = network_stats.installed(get, OWN)
    assert got == {"repositories": 2, "ids": [7001, 7003], "incomplete": True}
    assert len(asked) == 3 and all(p.startswith("search/code?q=") and "per_page=100&page=1" in p for p in asked)
    assert asked[0] == "search/code?q=%22drexthealpha/knos-workflows/.github/workflows%22%20path%3A.github/workflows&per_page=100&page=1"


# ---- stats.json, whole -----------------------------------------------------------------------------------------------
class Rpc:
    """chain.call, answered from recorded transactions and accounts."""

    def __init__(self, transactions: dict[str, list], accounts: dict[str, list] | None = None, throttled: frozenset = frozenset()):
        self.by_program, self.accounts, self.throttled = transactions, accounts or {}, throttled
        self.by_sig = {t["signature"]: t for txs in transactions.values() for t in txs}

    def __call__(self, url, method, params, timeout=10.0):
        if method == "getSignaturesForAddress":
            newest_first = list(reversed(self.by_program.get(params[0], [])))[:params[1]["limit"]]
            return [{"signature": t["signature"], "err": t["meta"]["err"]} for t in newest_first]
        if method == "getTransaction":
            if params[0] in self.throttled:
                raise OSError("429")
            return self.by_sig[params[0]]
        if method == "getProgramAccounts":
            size = params[1]["filters"][0]["dataSize"]
            return [a for a in self.accounts.get(params[0], []) if len(base64.b64decode(a["account"]["data"][0])) == size]
        raise AssertionError(method)


def github_of(scene: dict):
    answers = {**scene["github"], **{f"search/code?q={q}": a for q, a in scene["code_search"].items()}}

    def get(path):
        if path.startswith("search/code?q="):
            import urllib.parse
            return answers["search/code?q=" + urllib.parse.unquote(path.split("?q=", 1)[1].split("&", 1)[0])]
        if path not in answers:
            raise OSError(f"GitHub has no {path}")
        return answers[path]
    return get


def samples() -> dict[str, dict]:
    """What the script writes from the recorded inputs: no history at all; the first deployment's devnet history,
    chain only; and both deployments with the relay log, GitHub's times and a code search."""
    first, scene = recorded("devnet_first_deployment.json")["transactions"], recorded("second_deployment_scenario.json")
    real = chain.call
    try:
        chain.call = Rpc({})
        empty = network_stats.collect("rpc", None, None, now=SAMPLED_AT)
        chain.call = Rpc({PAY1: first})
        one = network_stats.collect("rpc", None, None, now=SAMPLED_AT)
        chain.call = Rpc({PAY1: first, PAY2: scene["transactions"]}, {PAY2: scene["accounts"]})
        both = network_stats.collect("rpc", github_of(scene), "a-token", now=SAMPLED_AT)
    finally:
        chain.call = real
    return {"stats_empty.json": empty, "stats_first_deployment.json": one, "stats_with_data.json": both}


def test_the_samples_the_site_renders_are_what_the_script_writes():
    for name, got in samples().items():
        assert json.loads((RECORDED / name).read_text(encoding="utf-8")) == got, f"{name} is stale: run python tests/test_network_stats.py"


def test_stats_json_with_no_history_is_zeros_and_says_what_was_not_measured():
    s = samples()["stats_empty.json"]
    assert s["updated"] == "2026-10-03 04:00 UTC" and s["cluster"] == "devnet" and "error" not in s
    assert s["programs"] == {"first": {"knos_oidc": str(network_stats.oidc.OIDC_ID), "knos_pay": PAY1},
                             "second": {"knos_oidc": str(network_stats.oidc2.OIDC_ID), "knos_pay": PAY2, "knos_meter": str(network_stats.meter.METER_ID)}}
    assert set(s["outside"].values()) == {0} and all(set(side.values()) == {0} for side in s["apart"].values())
    assert s["funnel"] == {"installed": None, "installed_note": "not measured", "funded": 0, "completed": 0, "funded_again": 0}
    zero = {"count": 0, "median": None, "p90": None, "slowest": None}
    assert {k: _table(v) if k in ("comment_to_funded", "merge_to_paid") else v for k, v in s["latency"].items()} == {
        "funded_to_paid": zero, "comment_to_funded": zero, "merge_to_paid": zero, "relay": {"fund": zero, "pay": zero}, "note": "not measured: GitHub was not asked"}
    assert s["latency"]["merge_to_paid"]["window"] is None and s["latency"]["merge_to_paid"]["n"] == 0
    no_orders = {"open": 0, "open_amount": 0, "held": 0, "held_amount": 0, "in_warranty": 0, "held_back": 0}
    assert s["recent"] == [] and s["live"]["second"] == {"open": 0, "open_amount": 0, "held": 0, "held_amount": 0, "orders": no_orders}
    assert set(s["orders"].values()) == {0} and s["meter"] == {"evaluations": 0, "accepted": 0, "rejected": 0, "fees": 0, "by_month": {}}


def test_stats_json_of_both_deployments_keeps_the_four_kinds_apart():
    s = samples()["stats_with_data.json"]
    # the second deployment's scenario: 12 jobs. Outside: A's five (two paid, one open, one held, one refunded) and B's
    assert s["by_deployment"] == {"first": {"funded": 11, "completed": 6}, "second": {"funded": 12, "completed": 8}}
    assert {k: s["outside"][k] for k in ("funded", "completed", "funders", "payees", "repeat_funders", "repositories")} == {
        "funded": 6, "completed": 3, "funders": 2, "payees": 2, "repeat_funders": 1, "repositories": 3}
    assert (s["apart"]["own"]["funded"], s["apart"]["own"]["completed"]) == (13, 8)          # the first deployment's 11 and 6, and two here
    assert (s["apart"]["self"]["funded"], s["apart"]["self"]["completed"]) == (2, 2)
    assert (s["apart"]["test"]["funded"], s["apart"]["test"]["completed"]) == (2, 1)
    assert sum(side["funded"] for side in (s["outside"], *s["apart"].values())) == s["totals"]["funded"] == 23       # each job in exactly one
    assert sum(side["completed"] for side in (s["outside"], *s["apart"].values())) == s["totals"]["completed"] == 14
    assert (s["totals"]["held"], s["totals"]["refunded"], s["totals"]["bound"], s["totals"]["balances"]) == (1, 1, 1, 4)
    assert s["funnel"] == {"installed": 3, "installed_note": "GitHub code search: public repositories whose workflow files call Knos's",
                           "funded": 6, "completed": 3, "funded_again": 1, "funded_of_installed": 2}
    assert _table(s["latency"]["comment_to_funded"]) == {"count": 3, "median": 226, "p90": 310, "slowest": 310}
    assert _table(s["latency"]["merge_to_paid"]) == {"count": 4, "median": 61, "p90": 620, "slowest": 620}
    assert s["latency"]["relay"] == {"fund": {"count": 3, "median": 9, "p90": 12, "slowest": 12}, "pay": {"count": 4, "median": 6, "p90": 14, "slowest": 14}}
    assert s["latency"]["note"] == "over the lines of the public relay log" and s["latency"]["funded_to_paid"]["count"] == 14
    assert {k: v for k, v in s["live"]["second"].items() if k != "orders"} == {"open": 2, "open_amount": 20 * USDC, "held": 1, "held_amount": 12 * USDC}
    assert s["orders"]["funded"] == 0 and set(s["live"]["second"]["orders"].values()) == {0}         # the recorded scenario is jobs alone
    assert len(s["recent"]) == 14 and [p["at"] for p in s["recent"]] == sorted((p["at"] for p in s["recent"]), reverse=True)      # newest first
    assert {p["kind"] for p in s["recent"]} == {"outside", "own", "self", "test"} and s["recent"][0]["deployment"] == 1


def test_what_could_not_be_read_is_said_and_never_guessed(monkeypatch):
    first = recorded("devnet_first_deployment.json")["transactions"]
    paying = next(t["signature"] for t in first if any("knos:paid" in line for line in t["meta"]["logMessages"]))
    monkeypatch.setattr(chain, "call", Rpc({PAY1: first}, throttled=frozenset({paying})))
    s = network_stats.collect("rpc", None, None)
    assert s["totals"]["completed"] == 5 and "1 transactions unread" in s["error"] and "lower bound" in s["error"]
    # more history than was read: said too
    monkeypatch.setattr(chain, "call", Rpc({PAY1: first}))
    s = network_stats.collect("rpc", None, None, limit=10)
    assert f"only the newest 10 transactions of {PAY1} were read" in s["error"] and s["totals"]["unmatched_paid"] > 0
    # the cluster does not answer at all: the file still ships, with the reason and no numbers
    def dead(*_a, **_k):
        raise OSError("no route")
    monkeypatch.setattr(chain, "call", dead)
    s = network_stats.collect("rpc", None, None)
    assert s["error"].startswith("OSError: no route") and "outside" not in s
    # GitHub answers the relay log but there is no token: the search is said to be not measured
    monkeypatch.setattr(chain, "call", Rpc({PAY1: first}))
    s = network_stats.collect("rpc", lambda path: [], None)
    assert s["funnel"]["installed"] is None and "needs a token" in s["funnel"]["installed_note"] and s["latency"]["note"].startswith("over the lines")

    def refuses(path):
        raise OSError("403")
    s = network_stats.collect("rpc", refuses, "a-token")
    assert s["latency"]["note"] == "not measured: the relay log could not be read (OSError)" and s["latency"]["comment_to_funded"]["count"] == 0
    assert s["latency"]["relay"]["fund"]["count"] == s["latency"]["relay"]["pay"]["count"] == 0
    assert s["funnel"]["installed"] is None and "did not answer" in s["funnel"]["installed_note"]


# ---- the second deployment's own log lines, from the program itself --------------------------------------------------
TERMS = pay2.terms_json({"accept": "", "checks": [{"app": 15368, "name": "test"}], "deny": [".github/**", ".knos/**"], "mode": "merge",
                         "paths": [], "reserve": 7, "v": 1})


def scenario() -> tuple[list[dict], list[dict], dict]:
    """Twelve jobs through the second deployment's test build in LiteSVM: (the escrow's transactions as a cluster
    would return them, the job accounts left at the end, {name: signature} of the ones the relay log names).

        A  an outside organisation (5001) whose wallet opened a Balance; a maintainer (6001) funds by comment:
             7001#1 paid to 8001 at the address they gave; 7001#2 funded after that and paid to 8002's bound wallet;
             7002#5 still open; 7001#3 held for 8005, who gave no address; 7001#4 refunded after its deadline
        B  an outside wallet funds 7003#3 itself; paid to 8001
        C  a person (5003) funds 7004#1 from their Balance and is paid for it themselves
        K  Knos (142920951) funds 7100#1, paid to 8003;  D (5004) funds 7005#2, paid to Knos
        E  an organisation (5005) with no Balance: the devnet faucet funds 7006#1 (paid to 8004) and 7006#2 (open)
        W  a wallet funds 7007#1 and the payment goes back to that same wallet
    """
    pytest.importorskip("solders.litesvm")
    sys.path.insert(0, str(ROOT / "tests"))
    from solders.instruction import AccountMeta, Instruction
    from solders.keypair import Keypair

    from _pay2 import TEST_CLAIM_SHA, WF_REPO, WF_SHA, Chain

    c, th = Chain(), pay2.terms_hash(TERMS)
    me, txs, named = c.payer.pubkey(), [], {}

    def send(ixs, payer=None, name=None) -> None:
        assert c.send(ixs, payer), c.err
        keys = list(dict.fromkeys([str((payer or c.payer).pubkey()), *[str(a.pubkey) for i in ixs for a in i.accounts], *[str(i.program_id) for i in ixs]]))
        sig = chain.b58(hashlib.sha512(f"knos scenario {len(txs)}".encode()).digest())      # a LiteSVM run has no cluster to sign for
        txs.append({"signature": sig, "blockTime": c.now(), "meta": {"err": None, "logMessages": c.logs}, "transaction": {"message": {"accountKeys": keys}}})
        if name:
            named[name] = sig

    usdc = c.new_mint()
    send([pay2.init_faucet_ix(me)])
    for mint in (usdc, pay2.faucet_mint()):
        c.token_account(pay2.FEE_OWNER, mint)

    def balance(owner: int, spenders=()) -> Pubkey:
        w, tok = c.wallet(usdc, 500 * USDC)
        bal = pay2.balance_pda(owner, w.pubkey(), usdc)
        move = Instruction(pay2.TOKEN, bytes([12]) + (200 * USDC).to_bytes(8, "little") + bytes([6]),
                           [AccountMeta(tok, False, True), AccountMeta(usdc, False, False), AccountMeta(pay2.baltok_pda(bal), False, True),
                            AccountMeta(w.pubkey(), True, False)])
        send([pay2.open_balance_ix(w.pubkey(), owner, usdc, spenders=list(spenders)), move], w)
        return bal

    def fund(bal, owner: int, repo: int, issue: int, amount: int, actor: int, work: int = 14 * DAY, name=None, faucet=False):
        c.warp(61 if faucet else 1)         # the faucet serves a repository once a minute; a Balance takes tokens in order
        mint = pay2.faucet_mint() if faucet else usdc
        tok = c.gh(pay2.fund_audience(issue, amount * USDC, pay2.MERGE, th, bal, work), file="fund.yml", event_name="issue_comment", actor_id=actor,
                   repository_owner_id=owner, repository_id=repo)
        assert tok is not None, c.err
        first = [pay2.faucet_open_ix(me, tok, c.key, owner, repo)] if faucet else []
        send([*first, pay2.fund_balance_ix(me, tok, c.key, bal, mint, repo, issue, TERMS)], name=name)
        return pay2.job_pda(repo, issue, bal)

    def fund_wallet(repo: int, issue: int, amount: int):
        w, tok = c.wallet(usdc, 100 * USDC)
        send([pay2.fund_wallet_ix(w.pubkey(), tok, usdc, repo, issue, amount * USDC, WF_REPO, WF_SHA, TERMS)], w)
        return pay2.job_pda(repo, issue, w.pubkey()), w.pubkey()

    def prove(job, payee: int, address=None, name=None) -> None:
        j = pay2.read_job(c.data(job))
        aud = pay2.pay_audience(j.repo_id, j.issue, payee, "a" * 40, j.terms, j.mode, address)
        tok = c.gh(aud, repository_id=j.repo_id)
        assert tok is not None, c.err
        wallet = pay2.destination(pay2.read_bind(c.data(pay2.bind_pda(payee))), aud)
        if wallet is not None:
            c.token_account(wallet, j.mint)
        send([pay2.pay_ix(me, tok, c.key, job, j, payee, wallet, used=c.data(tok))], name=name)     # 2.1: a pay token's single-use marker

    def bind(who: int, wallet) -> None:
        c.warp(1)
        tok = c.gh(pay2.bind_audience(wallet), file="claim.yml", wf_repo="drexthealpha/knos-oidc-rotate", wf_sha=TEST_CLAIM_SHA, event_name="workflow_dispatch",
                   actor_id=who, repository_owner_id=who, repository=f"user{who}/knos-claim", repository_id=70_000_000 + who)
        assert tok is not None, c.err
        send([pay2.bind_ix(me, tok, c.key, who)])

    a = balance(5001, [6001])
    p1 = Keypair().pubkey()
    a1 = fund(a, 5001, 7001, 1, 20, 6001, name="fund A1")
    c.warp(3000)
    prove(a1, 8001, p1, name="pay A1")
    c.warp(600)
    a2 = fund(a, 5001, 7001, 2, 30, 6001, name="fund A2")
    fund(a, 5001, 7002, 5, 10, 6001)
    a4 = fund(a, 5001, 7001, 3, 12, 6001)
    a5 = fund(a, 5001, 7001, 4, 5, 6001, work=60)
    b3, _wb = fund_wallet(7003, 3, 15)
    bind(8002, Keypair().pubkey())
    c.warp(7200)
    prove(a2, 8002, name="pay A2")                     # to the wallet 8002 bound
    prove(a4, 8005)                                    # no address, no bound wallet: held
    prove(b3, 8001, p1, name="pay B3")
    send([pay2.refund_ix(me, a5, pay2.read_job(c.data(a5)))])
    cbal = balance(5003)
    prove(fund(cbal, 5003, 7004, 1, 8, 5003), 5003, Keypair().pubkey())
    prove(fund(balance(KNOS), KNOS, 7100, 1, 25, KNOS), 8003, Keypair().pubkey())
    prove(fund(balance(5004), 5004, 7005, 2, 9, 5004), KNOS, Keypair().pubkey())
    e = pay2.faucet_balance_pda(5005)
    e1 = fund(e, 5005, 7006, 1, 25, 6005, name="fund E1", faucet=True)
    c.warp(900)
    prove(e1, 8004, Keypair().pubkey(), name="pay E1")
    fund(e, 5005, 7006, 2, 10, 6005, faucet=True)
    w7, wallet = fund_wallet(7007, 1, 6)
    prove(w7, 8006, wallet)
    accounts = [{"pubkey": str(addr), "account": {"data": [base64.b64encode(bytes(acc.data)).decode(), "base64"]}}
                for addr, acc in c.svm.get_program_accounts(pay2.PAY_ID) if acc.lamports > 0 and len(bytes(acc.data)) == pay2.JOB_LEN]
    return txs, sorted(accounts, key=lambda x: x["pubkey"]), named


def around(txs: list[dict], named: dict) -> dict:
    """The relay log a relay would have written for the scenario's named transactions, and what GitHub would answer
    about the comments and merges behind them: each start is put a stated number of seconds before its block time."""
    at = {t["signature"]: t["blockTime"] for t in txs}
    stamp = lambda unix: network_stats.datetime.datetime.fromtimestamp(unix, network_stats.datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    waits = {"fund A1": 226, "pay A1": 48, "fund A2": 180, "pay A2": 75, "pay B3": 30, "fund E1": 310, "pay E1": 620}
    took = {"fund A1": 9, "pay A1": 6, "fund A2": 12, "pay A2": 5, "pay B3": 7, "fund E1": 8, "pay E1": 14}       # the relay's own part of each wait
    where = {"fund A1": ("octo/widgets", 1), "pay A1": ("octo/widgets", 12), "fund A2": ("octo/widgets", 2), "pay A2": ("octo/widgets", 15),
             "pay B3": ("acme/gadgets", 4), "fund E1": ("free/test", 1), "pay E1": ("free/test", 2)}
    log, github = [], {}
    for n, (name, sig) in enumerate(named.items()):
        kind, (repo, number), start = name.split()[0], where[name], at[sig] - waits[name]
        carried = name == "pay B3"          # one line carries its own start, the others leave it to GitHub
        log.append({"created_at": stamp(at[sig] + 4), "body": f"knos-relay {'fund' if kind == 'fund' else 'proof'} {repo}#{number} {n:016x} ok "
                    + (f"asked={start} " if carried else "") + f"sig={sig} note=recorded for the tests t={took[name]}"})
        if carried:
            continue
        if kind == "fund":
            github[f"repos/{repo}/issues/{number}"] = {"body": "What should be done.", "created_at": stamp(start - 3600)}
            github[f"repos/{repo}/issues/{number}/comments?per_page=100"] = [{"body": "/knos fund 20 checks: test", "created_at": stamp(start)}]
        else:
            github[f"repos/{repo}/pulls/{number}"] = {"merged_at": stamp(start)}
    github["repos/drexthealpha/Knos/issues?labels=knos-relay&state=all&per_page=100"] = [{"number": 28}]
    github["repos/drexthealpha/Knos/issues/28/comments?per_page=100&page=1"] = log

    def found(*repos):
        return {"total_count": len(repos), "incomplete_results": False,
                "items": [{"path": ".github/workflows/knos.yml", "repository": {"id": i, "full_name": name, "owner": {"id": owner}, "private": False, "fork": False}}
                          for i, name, owner in repos]}
    search = {network_stats.INSTALLED_QUERIES[0]: found((7001, "octo/widgets", 5001), (7003, "acme/gadgets", 5002), (7900, "quiet/installed", 5900)),
              network_stats.INSTALLED_QUERIES[1]: found((1353152983, "drexthealpha/Knos", KNOS), (7001, "octo/widgets", 5001)),
              network_stats.INSTALLED_QUERIES[2]: found()}
    return {"github": github, "code_search": search}


EXPECTED = {"funded": 12, "completed": 8, "outside": (6, 3, 2, 2, 1, 3), "own": (2, 2), "self": (2, 2), "test": (2, 1), "held": 1, "refunded": 1,
            "bound": 1, "balances": 4, "funnel_funded": 6}


def check(s: dict) -> None:
    out = s["outside"]
    assert (s["totals"]["funded"], s["totals"]["completed"]) == (EXPECTED["funded"], EXPECTED["completed"])
    assert (out["funded"], out["completed"], out["funders"], out["payees"], out["repeat_funders"], out["repositories"]) == EXPECTED["outside"]
    for kind in ("own", "self", "test"):
        assert (s["apart"][kind]["funded"], s["apart"][kind]["completed"]) == EXPECTED[kind], kind
    assert (s["totals"]["held"], s["totals"]["refunded"], s["totals"]["bound"], s["totals"]["balances"]) == (1, 1, 1, 4)
    assert s["funnel"]["funded"] == EXPECTED["funnel_funded"] and s["totals"]["unmatched_paid"] == 0


def test_the_recorded_scenario_counts_as_it_was_played():
    scene = recorded("second_deployment_scenario.json")
    got = events(*scene["transactions"])
    check(network_stats.summarize(got, OWN))
    jobs, _ = network_stats.jobs_of(got)
    assert all(j["terms"] == TERMS.decode() for j in jobs)                    # each funding logged its terms
    assert {j["funder"] for j in jobs if network_stats.kind_of(j, OWN) == "outside"} == {"gh:5001", next(j["funder"] for j in jobs if j["repo"] == 7003)}
    assert next(j for j in jobs if j["repo"] == 7003)["funder"].startswith("wallet:")
    held = next(j for j in jobs if j["state"] == "held")
    assert (held["repo"], held["issue"], held["payee"]) == (7001, 3, 8005)
    assert len(scene["accounts"]) == 3                                         # the two open jobs and the held one


def test_the_second_deployments_program_logs_what_the_numbers_read():
    """The scenario again, through the program as it is built now: the same counts as the recording gives."""
    txs, accounts, named = scenario()
    check(network_stats.summarize(events(*txs), OWN))
    assert len(accounts) == 3 and set(named) == {"fund A1", "pay A1", "fund A2", "pay A2", "pay B3", "fund E1", "pay E1"}
    lines = [line for t in txs for line in t["meta"]["logMessages"] if "knos2:" in line]
    assert sum("knos2:funded " in x for x in lines) == sum("knos2:terms " in x for x in lines) == 12


if __name__ == "__main__":
    if "--record" in sys.argv:
        txs, accounts, named = scenario()
        scene = {"note": "Twelve jobs run through the second deployment's test build in LiteSVM by tests/test_network_stats.py (scenario): the "
                         "escrow's transactions with the log the program printed, the job accounts left at the end, the relay log lines a relay "
                         "would have written for seven of them, and GitHub's answers about those. The signatures are numbered stand-ins: a "
                         "LiteSVM run has no cluster. Recorded for the tests; do not edit.",
                 "transactions": txs, "accounts": accounts, **around(txs, named)}
        (RECORDED / "second_deployment_scenario.json").write_text(json.dumps(scene, indent=1) + "\n", encoding="utf-8")
    for name, data in samples().items():
        (RECORDED / name).write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        print(f"wrote tests/web/recorded/{name}")
