"""`knos receipt verify` answers in a time the reader is told (knos.receipt.from_chain).

It rebuilt a receipt by reading the escrow's newest 1,000 transactions one by one. devnet's public endpoint takes 40
requests of one method per 10 seconds, so that took minutes and printed nothing: the 0.3.25 run saw it "never answer".
Each request now waits at most what is left of one budget, and past it the command says so in one line. The cluster
and the clock here are stand-ins: no network, no waiting on the wall clock."""
from __future__ import annotations

import threading

import pytest

from knos import receipt
from knos.bundle import Unavailable
from knos.settle.v2 import pay


class Slow:
    """A cluster whose escrow lists `count` transactions and that takes `each` seconds (of a stand-in clock) a request."""

    def __init__(self, count: int = 1000, each: float = 0.25):
        self.now, self.each, self.asked, self.waits = 0.0, each, [], []
        self.sigs = [{"signature": f"sig{n}", "err": None} for n in range(count)]

    def clock(self) -> float:
        return self.now

    def call(self, method: str, params: list, timeout: float):
        self.asked.append((method, params[0]))
        self.waits.append(timeout)
        self.now += self.each
        if method == "getSignaturesForAddress":
            return self.sigs
        return {"slot": 1, "blockTime": 0, "meta": {"err": None, "logMessages": []}, "transaction": {"message": {"accountKeys": [], "instructions": []}}}


def test_a_slow_cluster_gets_one_line_in_the_time_given_and_no_request_after_it():
    c = Slow()
    with pytest.raises(receipt.NoAnswer) as got:
        receipt.from_chain("SomeOrder", "https://api.devnet.solana.com", seconds=120, call=c.call, clock=c.clock)
    said = str(got.value)
    assert "\n" not in said
    # this stand-in lists all 1,000 for the order too, so every one is read
    assert said.startswith("no answer from https://api.devnet.solana.com within 120 s (478 of 1,000 transactions read)")
    assert "--rpc URL" in said and "--limit N" in said
    assert len(c.asked) == 480 and c.now == 120.0       # the escrow's list and the order's, then 478 reads: none past the time
    assert max(c.waits) == 30.0 and min(c.waits) == 0.25        # no request may wait longer than what is left


def test_it_asks_for_every_transaction_version_the_relay_sends():
    c = Slow(count=3)
    with pytest.raises(Unavailable):
        receipt.from_chain("SomeOrder", "u", call=c.call, clock=c.clock)
    assert c.asked[0] == ("getSignaturesForAddress", str(pay.PAY_ID))
    assert receipt.TX_VERSION["maxSupportedTransactionVersion"] == 1


def test_a_request_cut_off_by_the_time_says_so_not_the_socket_words():
    c = Slow(count=10, each=0.0)

    def cut(method, params, timeout):
        if method == "getTransaction":
            c.now += timeout
            raise TimeoutError("timed out")
        return c.sigs

    with pytest.raises(receipt.NoAnswer, match=r"within 5 s \(0 of 10 transactions read\)"):
        receipt.from_chain("SomeOrder", "u", seconds=5, call=cut, clock=c.clock)


def test_a_cluster_that_does_not_give_its_list_is_named():
    c = Slow(count=0, each=10.0)

    def silent(method, params, timeout):
        c.call(method, params, timeout)
        raise TimeoutError("timed out")

    with pytest.raises(receipt.NoAnswer, match=r"within 5 s \(the list of transactions did not come\)"):
        receipt.from_chain("SomeOrder", "u", seconds=5, call=silent, clock=c.clock)


def test_a_request_that_never_returns_still_gets_an_answer():
    hold = threading.Event()

    def stuck(method, params, timeout):
        hold.wait()
        return []

    try:
        with pytest.raises(receipt.NoAnswer, match="the list of transactions did not come"):
            receipt.from_chain("SomeOrder", "u", seconds=0.05, call=stuck)
    finally:
        hold.set()


def test_what_the_chain_says_is_passed_on_as_it_was():
    c = Slow(count=2, each=0.0)
    with pytest.raises(Unavailable, match="shows no payment of SomeOrder"):
        receipt.from_chain("SomeOrder", "u", call=c.call, clock=c.clock)

    def throttled(method, params, timeout):
        if method == "getTransaction":
            raise OSError("HTTP Error 429: Too Many Requests")
        return c.sigs

    with pytest.raises(OSError, match="2 transactions could not be read") as got:
        receipt.from_chain("SomeOrder", "u", call=throttled, clock=c.clock)
    assert not isinstance(got.value, receipt.NoAnswer)


def test_it_rebuilds_the_receipt_gather_builds(tmp_path):
    pytest.importorskip("solders.litesvm")
    from _order import AUTHOR, MAINT, REPO, USDC, issue
    from test_receipt_offline import PR, TERMS, Recorded

    from knos import bundle

    c = Recorded()
    assert c.send([pay.set_balance_x_ix(c.owner.pubkey(), c.bal, 500 * USDC, 5_000 * USDC, [REPO])], c.owner), c.err
    order = c.fund_balance(issue(), terms=TERMS)
    wallet = c.fund().pubkey()
    c.warp(60)
    assert c.pay(order, [(AUTHOR, 10_000, wallet)], pr=PR, actor_id=MAINT), c.err
    asked: list[str] = []

    def cluster(method, params, timeout):
        asked.append(method)
        return c.call(method, params)

    got = receipt.from_chain(str(order), "harness", call=cluster)
    assert receipt.digest(got) == receipt.digest(bundle.gather(c.call, c.events(), str(order), None)[0])
    assert receipt.check(got) is None and asked[0] == "getSignaturesForAddress"


def test_it_reads_only_the_transactions_a_receipt_is_built_from():
    """On devnet's public endpoint (40 requests of one method per 10 s) the 0.3.26 tree read 72 of the escrow's newest
    996 transactions in its 120 s, and the witnessed order's own were 2 of them. Of the escrow's list it now reads the
    order's own, its Balance's opening and side account, and its owner's plan: the receipt is the one gather builds
    over every transaction, for the order and for its paying transaction, in a few seconds of that endpoint."""
    pytest.importorskip("solders.litesvm")
    from _order import AUTHOR, MAINT, REPO, USDC, issue
    from test_receipt_offline import PR, TERMS, Recorded

    from knos import bundle

    c = Recorded()
    assert c.send([pay.set_balance_x_ix(c.owner.pubkey(), c.bal, 500 * USDC, 5_000 * USDC, [REPO])], c.owner), c.err
    order = c.fund_balance(issue(), terms=TERMS)
    wallet = c.fund().pubkey()
    c.warp(60)
    assert c.pay(order, [(AUTHOR, 10_000, wallet)], pr=PR, actor_id=MAINT), c.err
    mine = list(c.named[str(pay.PAY_ID)])                 # every escrow transaction of the harness, oldest first
    other = [f"other{n:03}" for n in range(1000 - len(mine))]       # the rest of the escrow's newest 1,000: other orders'
    escrow = other[:500] + mine[:2] + other[500:700] + mine[2:] + other[700:]
    empty = {"slot": 1, "blockTime": 0, "meta": {"err": None, "logMessages": []}, "transaction": {"message": {"accountKeys": ["x"], "instructions": []}}}
    now, asked = [0.0], []

    def devnet(method, params, timeout):
        now[0] += 0.25
        asked.append((method, params[0] if params else None))
        if method == "getSignaturesForAddress" and params[0] == str(pay.PAY_ID):
            return [{"signature": s, "err": None} for s in reversed(escrow)]
        if method == "getTransaction" and params[0] in other:
            return empty
        return c.call(method, params)

    full = bundle.gather(c.call, c.events(), str(order), None)[0]
    paying = next(e["tx"] for e in c.events() if e["event"] == "order_paid")
    assert full["commercial_authorisation"]["limit"]["daily"] == str(500 * USDC)       # the Balance's side account is in it
    for target in (str(order), paying):
        now[0], asked[:] = 0.0, []
        got = receipt.from_chain(target, "https://api.devnet.solana.com", call=devnet, clock=lambda: now[0])
        assert receipt.digest(got) == receipt.digest(full) and receipt.check(got) is None
        read = [p for m, p in asked if m == "getTransaction" and p in escrow]
        assert read and set(read) <= set(mine) and not set(read) & set(other)
        assert now[0] < 15.0, now[0]          # under 60 requests in all, the receipt's own included


def test_an_auto_orders_payment_is_named_for_what_it_is():
    """The witnessed order of 0.3.24 was funded `auto` and paid by its own black-box checks before any merge: the
    program's judge e (Judge::Auto), which no receipt version names. It is said in those words, not as a payment no
    judge's token made."""
    def tx(*lines: str) -> dict:
        logs = [f"Program {pay.PAY_ID} invoke [1]", *(f"Program log: {line}" for line in lines), f"Program {pay.PAY_ID} success"]
        return {"slot": 1, "blockTime": 1, "meta": {"err": None, "logMessages": logs}, "transaction": {"message": {"accountKeys": ["Relayer"], "instructions": []}}}

    order = "AutoOrder"
    txs = {"funding": tx(f"knos3:funded order={order} repo=1 issue=11 seq=0 amount=5000000 fee=50000 mode=1 by=7 source=AutoBalance flags=36 deadline=9",
                         'knos3:terms {"v":1}'),
           "paying": tx(f"knos3:paid order={order} pr=12 payee=7 amount=5000000 to=Payee",
                        f"knos3:settled order={order} paid=5000000 of=5000000 fee=0 tip=50000 judge=4")}

    def cluster(method, params, timeout):
        if method == "getSignaturesForAddress":
            return [{"signature": s, "err": None} for s in ("paying", "funding")]
        return txs.get(params[0])

    with pytest.raises(ValueError, match=r"Transaction paying paid an open pull request of an auto order \(paid by the order's own black-box checks, with no merge\)") as got:
        receipt.from_chain(order, "u", call=cluster, clock=lambda: 0.0)
    assert "no token" not in str(got.value)


def test_the_answer_comes_at_the_time_given_not_after_it():
    """The 0.3.26 tree's first run on devnet answered 129 s after the command began, of its 120 s: the wait for the
    read allowed five seconds more than the time given."""
    import time
    hold = threading.Event()

    def stuck(method, params, timeout):
        hold.wait()
        return []

    try:
        began = time.monotonic()
        with pytest.raises(receipt.NoAnswer, match="within 1 s"):
            receipt.from_chain("SomeOrder", "u", seconds=1.0, call=stuck)
        assert time.monotonic() - began < 1.5
    finally:
        hold.set()


def test_the_command_reads_through_it_and_says_the_one_line(monkeypatch):
    """`knos receipt verify ORDER` reads the chain through from_chain: past the time, the reader gets its one line."""
    from typer.testing import CliRunner

    from knos import cli
    said = "no answer from https://api.devnet.solana.com within 120 s (12 of 1,000 transactions read): give your own endpoint (--rpc URL) or fewer transactions (--limit N)"

    def late(target, url, limit=1000):
        assert (target, limit) == ("SomeOrder", 1000)
        raise receipt.NoAnswer(said)

    monkeypatch.setattr(receipt, "from_chain", late)
    got = CliRunner().invoke(cli.app, ["receipt", "verify", "SomeOrder", "--rpc", "https://api.devnet.solana.com"])
    assert got.exit_code == 1 and said in got.output and "Give --mirror" in got.output
    assert len([line for line in got.output.splitlines() if line.strip()]) == 1, got.output
