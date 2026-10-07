"""Netted settlement (knos.netting): the book's rules as pure functions, the command line, and one period end to end
in the Solana runtime (LiteSVM) on the programs as they are: 1,000 outcomes of 0.32, one disputed, one duplicate;
the batch anchored by both sides on knos_meter; one order funded from a capped Balance and paid by one token."""
from __future__ import annotations

import hashlib
import json

import pytest

from knos import ledger, netting
from knos.ledger import Bad

BUYER, SUPPLIER, MONTH = 424242, 7_777_001, 202610
ORDER, POLICY = "a1" * 32, "b2" * 32


def sha(*parts: object) -> str:
    return hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()


def one(i: int, amount: str = "0.32") -> dict:
    """Outcome i of the supplier: a deliverable of its own (the order's milestone i), its own artifact and evidence id."""
    return {"order": ORDER, "milestone": i, "artifact": sha("artifact", i)[:40], "policy": POLICY, "amount": amount, "evidence": sha("evidence", i)}


def opened(cap: str = "500", month: int = MONTH, text: str = "") -> str:
    return text + netting.open_line(netting.read(text), BUYER, SUPPLIER, month, cap) + "\n"


def added(text: str, items) -> tuple[str, list[dict]]:
    lines, refused = netting.add(netting.read(text), items)
    return text + "".join(line + "\n" for line in lines), refused


def closed(text: str, other: str | None = None) -> tuple[netting.Net, str]:
    n, line = netting.close(netting.read(text), netting.read(other) if other is not None else None)
    return n, text + line + "\n"


def test_amounts_are_millionths_and_the_fee_is_the_escrows_own():
    assert netting.units("0.32") == 320_000 and netting.units("20") == 20_000_000 and netting.units(7) == 7
    for bad in ("0.0000001", "-1", "a lot"):
        with pytest.raises(Bad):
            netting.units(bad)
    assert [netting.fee_of(a) for a in (5_000_000, 100_000_000, 319_680_000)] == [50_000, 300_000, 959_040]


def test_an_outcome_is_added_once_in_any_period_and_never_past_the_cap():
    text, refused = added(opened("6"), [one(i) for i in range(16)])
    assert not refused and netting.read(text).open.value == 5_120_000
    # the same deliverable under another artifact and evidence, the same evidence for another deliverable, an amount
    # that is not small, no evidence
    again = {**one(3), "artifact": "c" * 40, "evidence": sha("other")}
    reused = {**one(99), "evidence": one(4)["evidence"]}
    big = one(100, "20")
    text2, refused = added(text, [again, reused, big, {**one(101), "evidence": ""}, one(17)])
    assert [r["why"].split(":")[0] for r in refused[:2]] == ["duplicate", "duplicate"] and "not netted" in refused[2]["why"] and len(refused) == 4
    assert text2.count("\n") == text.count("\n") + 1                      # one bad outcome refuses itself only
    # the cap: 5.44 held, 6.00 allowed: one more of 0.32 fits, the next does not
    text3, refused = added(text2, [one(18), one(19)])
    assert len(refused) == 1 and refused[0]["why"].startswith("over the cap") and netting.read(text3).open.value == 5_760_000
    # closed, and a new period of the same book: what the first holds is refused in the second
    n, text4 = closed(text3)
    assert n.value == 5_760_000 and n.fee == 50_000 and netting.read(text4).open is None
    with pytest.raises(Bad, match="no period is open"):
        netting.add(netting.read(text4), [one(20)])
    text5, refused = added(opened("6", text=text4), [again, reused, one(20)])
    assert [r["why"] for r in refused] == [f"duplicate: this order and milestone was accepted in period {MONTH}.0 already, and an accepted deliverable is counted once",
                                           f"duplicate: evidence {one(4)['evidence'][:16]}... already carries a line of period {MONTH}.0"]
    assert [p.name for p in netting.read(text5).periods] == [f"{MONTH}.0", f"{MONTH}.1"]
    # another recording mode already counted it (the events log's id of the outcome)
    e = netting.outcome(netting.read(text5).open.terms, **one(21))
    _lines, refused = netting.add(netting.read(text5), [one(21)], counted=[netting._acc(e)])
    assert refused and "events log" in refused[0]["why"]


def test_a_dispute_takes_one_line_out_and_leaves_the_rest_payable():
    text, _ = added(opened(), [one(i) for i in range(20)])
    book = netting.read(text)
    line = netting.dispute_line(book, one(7)["evidence"], "the call returned nothing")
    n, done = closed(text + line + "\n")
    assert (n.count, n.accepted, n.disputed, n.value) == (20, 19, 1, 19 * 320_000)
    # the disputed line is still under the root, as disputed: a batch without it is another root
    assert [e.stands for e in n.batch.evals].count("disputed") == 1
    without, _ = added(opened(), [one(i) for i in range(20) if i != 7])
    assert netting.net_of(netting.read(without).open).root != n.root
    with pytest.raises(Bad, match="disputed already"):
        netting.dispute_line(book, one(7)["evidence"])
    with pytest.raises(Bad, match="no period is open"):
        netting.dispute_line(netting.read(done), one(8)["evidence"])
    # the period is a meter ledger file the meter's own commands read
    assert ledger.verify(ledger.load(netting.ledger_text(n))) == []
    st = netting.statement(netting.read(done))
    assert st["periods"][0]["state"] == "closed" and st["periods"][0]["disputed"] == [one(7)["evidence"]] and len(st["enforced"]) == len(netting.ENFORCED)


def test_both_sides_compute_the_same_net_or_nothing_closes():
    items = [one(i) for i in range(30)]
    buyer, _ = added(opened(), items)
    seller, _ = added(opened(), list(reversed(items)))            # each from what it received, in its own order
    n, _ = closed(buyer, seller)
    assert n.root == netting.net_of(netting.read(seller).open).root
    short, _ = added(opened(), items[:-1])
    with pytest.raises(Bad, match="is here and not there"):
        closed(buyer, short)
    other, _ = added(opened(), [*items[:-1], {**items[-1], "amount": "0.33"}])
    with pytest.raises(Bad, match="differs: accepted 0.32 here, accepted 0.33 there"):
        closed(buyer, other)
    # a net under the least order stays open
    small, _ = added(opened(), items[:5])
    with pytest.raises(Bad, match="under 5"):
        closed(small)


def test_a_later_period_is_appended_to_the_pairs_ledger_file_and_never_written_alone(tmp_path):
    # Found on devnet (0.3.19): the pair had anchored batch 0 of the month already, so the period was batch 1, and
    # `net close --ledger` wrote a file holding batch 1 alone, which `knos meter verify` and attest.yml refuse ("its
    # batches are numbered [1], not 0 to 0"): the period could not be anchored from the file close wrote.
    first, _ = added(opened(), [one(i) for i in range(20)])
    n0, first = closed(first)
    zero = netting.ledger_text(n0)
    second, _ = added(first + netting.open_line(netting.read(first), BUYER, SUPPLIER, MONTH, "500") + "\n", [one(i) for i in range(20, 40)])
    n1, _ = closed(second)
    assert n1.seq == 1
    with pytest.raises(Bad, match=r"batch 1 of the pair's month, so the file must hold batches 0 to 0 of 202610 before it \(no file was given\)"):
        netting.ledger_text(n1)
    both = netting.ledger_text(n1, zero)
    assert both.startswith(zero) and [(s.month, s.seq) for s in ledger.load(both)] == [(MONTH, 0), (MONTH, 1)] and ledger.verify(ledger.load(both)) == []
    with pytest.raises(Bad, match="numbered"):
        netting.ledger_text(n1, both)                                       # the period is in the file already
    stranger, _ = added(text=netting.open_line(netting.read(""), BUYER, SUPPLIER + 1, MONTH, "500") + "\n", items=[one(i) for i in range(20)])
    with pytest.raises(Bad, match=f"this period's pair is {BUYER} and {SUPPLIER}"):
        netting.ledger_text(n1, netting.ledger_text(closed(stranger)[0]))
    # the command line appends to the file it is given, and writes nothing when it cannot
    typer = pytest.importorskip("typer")
    from typer.testing import CliRunner
    app = typer.Typer()
    netting.register(app)
    book, out, log = tmp_path / "net.jsonl", tmp_path / "pair.jsonl", tmp_path / "events.jsonl"
    book.write_text(second, encoding="utf-8")
    r = CliRunner().invoke(app, ["net", "close", str(book), "--ledger", str(out), "--events", str(log)])
    assert r.exit_code == 1 and "batches 0 to 0" in r.output + str(r.exception) and not out.exists() and book.read_text(encoding="utf-8") == second
    out.write_text(zero, encoding="utf-8")
    r = CliRunner().invoke(app, ["net", "close", str(book), "--ledger", str(out), "--events", str(log)])
    assert r.exit_code == 0, r.output
    assert out.read_text(encoding="utf-8") == both and netting.read(book.read_text(encoding="utf-8")).open is None


def test_a_book_is_recomputed_never_trusted():
    text, _ = added(opened(), [one(i) for i in range(20)])
    _n, done = closed(text)
    assert netting.text_of(netting.read(done)) == done
    lines = done.splitlines()
    for bad in ("\n".join(lines[:5] + lines[6:]),                                       # a line removed after closing
                done.replace('"value":6400000', '"value":6399999'),                     # the summary edited
                done.replace('"rate":320000', '"rate":320001', 1)):                     # a line edited
        with pytest.raises(Bad):
            netting.read(bad + "\n")


def test_the_command_line_opens_adds_disputes_closes_and_states(tmp_path):
    typer = pytest.importorskip("typer")
    from typer.testing import CliRunner
    from knos import events
    app = typer.Typer()
    netting.register(app)
    book, log, items = tmp_path / "net.jsonl", tmp_path / "events.jsonl", tmp_path / "outcomes.jsonl"
    items.write_text("".join(json.dumps(one(i)) + "\n" for i in range(20)), encoding="utf-8")
    run = lambda *a: CliRunner().invoke(app, ["net", *map(str, a)])      # noqa: E731
    r = run("open", book, "--buyer", BUYER, "--seller", SUPPLIER, "--month", "2026-10", "--cap", "50")
    assert r.exit_code == 0, r.output
    r = run("add", book, items, "--events", log)
    assert r.exit_code == 0 and json.loads(r.output)["added"] == 20, r.output
    r = run("add", book, items, "--events", log)                         # the same file again: every line refused, nothing written
    assert r.exit_code == 1 and json.loads(r.output)["added"] == 0 and len(json.loads(r.output)["refused"]) == 20
    r = run("dispute", book, "--evidence", one(2)["evidence"], "--reason", "empty answer", "--events", log)
    assert r.exit_code == 0, r.output
    r = run("close", book, "--ledger", tmp_path / "ledger.jsonl", "--events", log)
    out = json.loads(r.output)
    assert r.exit_code == 0 and out["net"]["value"] == 19 * 320_000 and out["net"]["fee"] == 50_000 and out["compare"]["single_fees"] == 19 * 50_000
    assert ledger.verify(ledger.load(tmp_path / "ledger.jsonl")) == []
    r = run("statement", book)
    assert json.loads(r.output)["periods"][0]["root"] == out["net"]["root"]
    # the events log holds every outcome once, by both arrivals, and the dispute as a correction
    lg = events.load(log)
    e = netting.outcome(netting.read(book.read_text(encoding="utf-8")).periods[0].terms, **one(2))
    assert len(lg.dupes()) == 19 * 2 and lg.state(lg.events[lg.first[netting._evl(e)]])[0] == "disputed"


# -- end to end in the simulator ------------------------------------------------------------------------------------------
def test_a_thousand_outcomes_settle_as_one_release_on_the_programs_as_they_are():
    pytest.importorskip("solders.litesvm")
    import _meter
    from _order import MAINT, OWNER, REPO, USDC, OrderChain, code, issue, transfer
    from knos.settle.v2 import meter, pay

    class NetChain(_meter.Meter, OrderChain):
        sent = 0

        def send(self, ixs, payer=None, signers=(), tag=None) -> bool:
            ok = super().send(ixs, payer, signers, tag)
            self.sent += ok
            return ok

    assert OWNER == BUYER
    c = NetChain()
    month = meter.yyyymm(c.now())
    cap = 500 * USDC

    # the two books: 1,000 outcomes of 0.32 each side received, one sent twice, one disputed
    items = [one(i) for i in range(1000)]
    buyer, refused = added(opened("500", month), [*items, items[412]])
    assert len(refused) == 1 and refused[0]["why"].startswith("duplicate")
    seller, _ = added(opened("500", month), list(reversed(items)))
    why = netting.dispute_line(netting.read(buyer), items[77]["evidence"], "no answer")
    n, buyer = closed(buyer + why + "\n", seller + why + "\n")
    assert (n.count, n.accepted, n.disputed, n.value, n.fee) == (1000, 999, 1, 319_680_000, 959_040)
    assert n.fee == 319_680_000 * 30 // 10_000              # 0.30% of the net; the floor of 0.05 does not bind

    # the buyer's wallet opens a Balance whose cap is the period's
    w, wtok = c.wallet(c.usdc, 1_000 * USDC)
    assert c.send([pay.open_balance_ix(w.pubkey(), OWNER, c.usdc, cap=cap, spenders=[MAINT])], w), c.err
    bal = pay.balance_pda(OWNER, w.pubkey(), c.usdc)
    transfer(c, wtok, pay.baltok_pda(bal), 600 * USDC, w)
    _wallet, credits = c.open(c.usdc, BUYER, 10 * USDC)
    supplier = c.fund().pubkey()
    c.token_account(supplier, c.usdc)

    def fund(amount: int, raw: bytes, aud: str | None = None):
        k = issue()
        c.warp(1)
        aud = aud or pay.order_fund_audience(k, amount, netting.MODE, pay.terms_hash(raw), bal)
        tok = c.gh(aud, file="fund.yml", event_name="issue_comment", actor_id=MAINT, repository_id=REPO, repository_owner_id=OWNER)
        return k, c.fund_balance_ix(tok, k, bal, raw)

    def paid(order, net: netting.Net, o=None) -> bool:
        aud = netting.release(net, bal, 0, order, supplier)["pay_audience"]
        tok = c.gh(aud, repository_id=REPO)
        o = o or c.order(order)
        return c.send([pay.pay_order_ix(c.payer.pubkey(), tok, c.key, order, o, [(SUPPLIER, supplier)], pr=netting.number(net))], tag="net_pay")

    # the cap is the program's: a release above it is refused
    _k, ix = fund(cap + 1, pay.terms_json(netting.terms(n)))
    assert not c.send([ix]) and code(c) == 93

    start = c.sent
    # 1. both sides anchor the batch on knos_meter: the same root in both accounts
    aud = netting.audiences(n)
    sides = lambda: [meter.read_ledger(c.data(meter.ledger_pda(BUYER, SUPPLIER, month, claim))) for claim in (False, True)]     # noqa: E731
    assert netting.anchored(n, *sides()) == [f"the buyer has not anchored period {month}.0", f"the supplier has not anchored period {month}.0"]
    assert c.batch(credits, aud["buyer"]), c.err
    assert c.claim(aud["seller"], repository_owner_id=SUPPLIER), c.err
    mine, theirs = sides()
    assert netting.anchored(n, mine, theirs) == [] and mine.chain == theirs.chain and (mine.evaluations, mine.accepted, mine.value) == (1000, 999, n.value)
    assert mine.fees == 0                                   # 1,000 evaluations are inside the month's free 100,000

    # 2. one order of exactly the net, funded from the Balance on terms that carry the root; the fee on top
    fees, before = c.balance(c.fee), c.balance(pay.baltok_pda(bal))
    k = issue()
    r = netting.release(n, bal, k)
    assert json.loads(r["terms"])["accept"] == n.root.hex() and r["total"] == 320_639_040
    c.warp(1)
    tok = c.gh(r["fund_audience"], file="fund.yml", event_name="issue_comment", actor_id=MAINT, repository_id=REPO, repository_owner_id=OWNER)
    assert c.send([c.fund_balance_ix(tok, k, bal, r["terms"].encode())], tag="net_fund"), c.err
    order = pay.order_pda(pay.scope_of(REPO, k), bal)
    o = c.order(order)
    assert (o.amount, o.fee, o.terms.hex()) == (n.value, n.fee, r["terms_hash"]) and before - c.balance(pay.baltok_pda(bal)) == n.value + n.fee

    # a token for another batch (the disputed line counted) does not pay this order
    other = netting.net_of(netting.read(seller).open)
    extra = c.sent
    assert other.value == 320_000_000 and not paid(order, other, o) and code(c) == 87
    extra = c.sent - extra                                  # what verifying the refused token took: not part of the release

    # 3. one pay token that names the order, those terms and the supplier releases it
    assert paid(order, n, o), c.err
    netted = c.sent - start - extra
    assert c.balance(pay.ata(supplier, c.usdc)) == 319_680_000
    # the fee is 0.30% of the net, once: the relayer's tip is paid out of it, and the order is gone
    assert c.balance(c.fee) - fees + c.balance(c.tip) == n.fee and c.balance(c.tip) == pay.TIP and c.data(order) is None

    # against paying singly: the escrow takes no job under 1.00, so one 0.32 outcome cannot be paid alone at all;
    # the least order (5.00) shows what one single payment costs in transactions
    assert netting.JOB_MIN == pay.MIN_AMOUNT and netting.ORDER_MIN == pay.ORDER_MIN_AMOUNT and netting.MAX_CAP == pay.MAX_AMOUNT
    start = c.sent
    raw = pay.terms_json({"accept": "", "checks": [], "mode": "merge", "v": 2})
    k, ix = fund(5 * USDC, raw)
    assert c.send([ix]), c.err
    single = pay.order_pda(pay.scope_of(REPO, k), bal)
    so = c.order(single)
    tok = c.gh(pay.order_pay_audience(single, "a" * 40, so.terms, so.mode, 7, [(SUPPLIER, 10_000, supplier)]), repository_id=REPO)
    assert c.send([pay.pay_order_ix(c.payer.pubkey(), tok, c.key, single, so, [(SUPPLIER, supplier)], pr=7)]), c.err
    one_single = c.sent - start
    cmp = netting.compare(n, single_txs=one_single, netted_txs=netted)
    assert cmp["netted_fee"] == 959_040 and cmp["single_fees"] == 999 * 50_000 and cmp["payable_singly"] == 0
    assert cmp["single_txs"] == 999 * one_single and cmp["netted_txs"] == 2 * one_single == 24
    print("NETTING", json.dumps({**cmp, "one_single_txs": one_single}))
