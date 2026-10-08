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


# -- the reserve and the supplier's exposure ------------------------------------------------------------------------------
RESERVE = {"order": "9" * 43, "funded": 10_000_000, "tranche": 2_000_000, "deadline": 1_900_000_000}


def conserved(text: str) -> dict:
    """The open (or last) period's reserve, after checking what must hold at every step."""
    b = netting.read(text)
    s = netting.reserve_state(b.periods[-1])
    assert s["funded"] == s["brought"] + s["consumed"] + s["free"] and s["free"] >= 0 and netting.exposure(b) == 0
    assert netting.text_of(b) == text                       # the book written again is the book: a line added after a dispute stays after it
    return s


def test_a_reserved_period_spends_no_more_than_its_reserve_holds_and_funded_is_consumed_plus_free_at_every_step():
    text = ""
    text += netting.open_line(netting.read(text), BUYER, SUPPLIER, MONTH, "500", reserve=RESERVE) + "\n"
    assert conserved(text) == {**RESERVE, "brought": 0, "consumed": 0, "free": 10_000_000}
    for i in range(31):                                                 # 31 outcomes of 0.32 are 9.92 of the 10.00 locked
        text, refused = added(text, [one(i)])
        assert not refused and conserved(text)["consumed"] == (i + 1) * 320_000
    over, refused = added(text, [one(31)])
    assert over == text and refused[0]["why"].startswith("past the reserve: period 202610.0 has consumed 9.92 of the 10 its order holds, and 0.08 is free")
    # a dispute frees what its line had consumed; nothing else moves
    text += netting.dispute_line(netting.read(text), one(3)["evidence"], "empty") + "\n"
    assert conserved(text)["free"] == 400_000
    text, refused = added(text, [one(31)])
    assert not refused and conserved(text) == {**RESERVE, "brought": 0, "consumed": 9_920_000, "free": 80_000}
    # the other side must name the same reserve, or nothing closes
    theirs = text.replace('"funded":10000000', '"funded":20000000')
    with pytest.raises(Bad, match="what secures period 202610.0"):
        closed(text, theirs)
    n, text = closed(text, text)
    s = conserved(text)
    assert (s["draws"], s["drawn"], s["undrawn"]) == (4, 8_000_000, 1_920_000) and n.value == 9_920_000
    # the next period on the same order starts from what the last left undrawn, and a header that says otherwise is refused
    left = {**RESERVE, "funded": 2_000_000}
    nxt = text + netting.open_line(netting.read(text), BUYER, SUPPLIER, MONTH, "500", reserve=left) + "\n"
    assert conserved(nxt) == {**left, "brought": 1_920_000, "consumed": 0, "free": 80_000}
    with pytest.raises(Bad, match="brings forward 0, and the periods before it left 1.92 undrawn"):
        netting.read(nxt.replace('"brought":1920000', '"brought":0'))
    same, refused = added(nxt, [one(40)])
    assert same == nxt and "and brought 1.92 forward of the 2 its order holds, and 0.08 is free" in refused[0]["why"]
    nxt, refused = added(nxt, [one(40, "0.08")])
    assert not refused and conserved(nxt)["free"] == 0
    # a reserved period closes whatever it comes to: no new order is funded, so the least order does not apply
    n2, nxt = closed(nxt)
    s = conserved(nxt)
    assert n2.value == 80_000 and (s["draws"], s["drawn"], s["undrawn"]) == (1, 2_000_000, 0)
    assert [d["pr"] for d in netting.draws(netting.read(nxt).periods[0])] == [2026100000_0001 + k for k in range(4)]
    assert [d["pr"] for d in netting.draws(netting.read(nxt).periods[1])] == [2026100001_0001]
    st = netting.statement(netting.read(nxt))
    assert st["exposure"] == 0 and st["undrawn"] == 0 and [r["secured"] for r in st["periods"]] == ["reserve", "reserve"]
    assert st["periods"][0]["reserve"]["undrawn"] == 1_920_000 and "RefundOrder (knos_pay instruction 22)" in st["reserve_returns"]
    # a period is reserved or bounded, never both, and a reserve holds at least one tranche
    for bad in ({"reserve": RESERVE, "max_exposure": "5"}, {"reserve": {**RESERVE, "tranche": 10_000_001}}):
        with pytest.raises(Bad):
            netting.open_line(netting.Book(), BUYER, SUPPLIER, MONTH, "500", **bad)


def test_an_unsecured_period_says_so_and_the_supplier_carries_no_more_than_the_exposure_limit_over_the_whole_book():
    text = netting.open_line(netting.Book(), BUYER, SUPPLIER, MONTH, "50", max_exposure="8") + "\n"
    text, _ = added(text, [one(i) for i in range(20)])
    _n, text = closed(text)
    st = netting.statement(netting.read(text))
    assert st["exposure"] == 6_400_000 and st["periods"][0]["secured"] == "unsecured" and st["periods"][0]["max_exposure"] == 8_000_000
    assert st["exposure_says"].startswith("The supplier has delivered 6.4 USDC that no locked money covers")
    # the closed period is not funded yet: the next one takes 1.60 more and then nothing
    text += netting.open_line(netting.read(text), BUYER, SUPPLIER, MONTH, "50", max_exposure="8") + "\n"
    text, refused = added(text, [one(i) for i in range(20, 26)])
    assert netting.exposure(netting.read(text)) == 8_000_000 and len(refused) == 1
    assert refused[0]["why"].startswith("past the exposure limit: the supplier already carries 8 with no money locked behind it, and this period allows 8")
    # only a closed period is settled, once; then its value is no longer carried and the next line is taken
    for period in ("202610.1", "202610.7"):
        with pytest.raises(Bad, match="only a closed period is settled"):
            netting.settled_line(netting.read(text), period, "x")
    text += netting.settled_line(netting.read(text), "202610.0", "order 4xyz") + "\n"
    with pytest.raises(Bad, match="settled already"):
        netting.settled_line(netting.read(text), "202610.0", "again")
    assert netting.exposure(netting.read(text)) == 1_600_000
    text, refused = added(text, [one(25)])
    assert not refused and netting.read(netting.text_of(netting.read(text))).periods[0].settled == "order 4xyz"
    # a header of version 1 has no limit but its cap, as before
    old, refused = added(opened("50"), [one(i) for i in range(100)])
    assert not refused and "max_exposure" not in old and netting.statement(netting.read(old))["exposure"] == 32_000_000


def test_the_command_line_binds_a_reserve_read_from_the_chain_and_says_what_is_unsecured(tmp_path, monkeypatch):
    typer = pytest.importorskip("typer")
    pytest.importorskip("solders")
    from types import SimpleNamespace
    from solders.pubkey import Pubkey
    from typer.testing import CliRunner
    from knos import cli
    from knos.settle.v2 import pay
    at, other = Pubkey.new_unique(), Pubkey.new_unique()
    order = SimpleNamespace(state="open", flags=pay.F_STANDING, holdback_bps=0, terms=netting.reserve_hash(BUYER, SUPPLIER), from_balance=True, owner_id=BUYER,
                            deadline=2_000, pay_until=2_000, amount=10_000_000, paid=0, rate=2_000_000, cancel_at=0, judge_repo_id=0, refund_to=other)
    held = {bytes(at): order}
    monkeypatch.setattr(pay, "read_order", lambda data: data)
    monkeypatch.setattr(cli, "_ledger", lambda: SimpleNamespace(account=lambda a: held.get(bytes(a)), now=lambda: 1_000))
    app = typer.Typer()
    netting.register(app)
    run = lambda *a: CliRunner().invoke(app, ["net", *map(str, a)])      # noqa: E731
    book, items = tmp_path / "net.jsonl", tmp_path / "outcomes.jsonl"
    pair = ("--buyer", BUYER, "--seller", SUPPLIER, "--month", "2026-10", "--cap", "50")
    # every order that secures nothing for this pair is refused, in words, and nothing is written
    for change, said in (({"flags": 0}, "an open standing order"), ({"terms": bytes(32)}, "not funded on the reserve terms of buyer 424242"),
                         ({"owner_id": 5}, "Balance of GitHub owner 5"), ({"deadline": 999}, "past its deadline"), ({"amount": 1_999_999}, "less than one tranche")):
        held[bytes(at)] = SimpleNamespace(**{**vars(order), **change})
        r = run("open", book, *pair, "--reserve", at)
        assert r.exit_code != 0 and said in str(r.exception) and not book.exists(), (r.output, r.exception)
    held[bytes(at)] = order
    assert "there is no order at" in str(run("open", book, *pair, "--reserve", other).exception)
    assert run("open", book, *pair, "--reserve", at, "--max-exposure", "5").exit_code != 0 and not book.exists()
    r = run("open", book, *pair, "--reserve", at)
    out = json.loads(r.output)
    assert r.exit_code == 0 and out["secured"] == "reserve" and out["period"]["reserve"] == {"order": str(at), "funded": 10_000_000, "tranche": 2_000_000,
                                                                                             "deadline": 2_000, "brought": 0}
    items.write_text("".join(json.dumps(one(i)) + "\n" for i in range(32)), encoding="utf-8")
    out = json.loads(run("add", book, items).output)
    assert out["added"] == 31 and out["exposure"] == 0 and out["reserve"]["free"] == 80_000 and out["refused"][0]["why"].startswith("past the reserve")
    out = json.loads(run("close", book).output)
    assert "terms" not in out and len(out["draws"]) == 4 and out["reserve"]["undrawn"] == 1_920_000 and out["secured"] == "reserve"
    assert all(d["pay_audience"].startswith(f"knos3:pay:{at}:{out['net']['root'][:40]}:{netting.reserve_hash(BUYER, SUPPLIER).hex()}:0:") for d in out["draws"])
    # the statement reads the order again: it holds, then the buyer gives notice, then it is gone
    says = lambda: json.loads(run("statement", book, "--chain").output)["periods"][0]["reserve"]["on_chain"]      # noqa: E731
    assert says() == ["holds"]
    held[bytes(at)] = SimpleNamespace(**{**vars(order), "cancel_at": 900, "deadline": 1_500, "amount": 7_000_000})
    assert says() == ["the order holds 7 and the period is owed 8 from it", "the buyer gave notice (Cancel): draws pay until 1500 and not after"]
    del held[bytes(at)]
    assert says() == [f"the reserve order {at} is gone: paid out or refunded"]
    assert json.loads(run("settled", book, "--period", "202610.0", "--by", at).output)["exposure"] == 0 and says() == ["holds"]
    # without a reserve the period is unsecured, every answer says so, and the limit is the cap unless one is given
    loose = tmp_path / "loose.jsonl"
    out = json.loads(run("open", loose, *pair).output)
    assert out["secured"] == "unsecured" and out["period"]["max_exposure"] == 50_000_000 and out["says"].startswith("Unsecured: the supplier carries")
    out = json.loads(run("add", loose, items).output)
    assert out["secured"] == "unsecured" and out["exposure"] == 32 * 320_000
    st = json.loads(run("statement", loose).output)
    assert st["exposure"] == 10_240_000 and st["periods"][0]["exposure"] == 10_240_000 and "Withdraw, instruction 2" in st["not_a_reserve"]
    out = json.loads(run("reserve", "--buyer", BUYER, "--seller", SUPPLIER, "--amount", "500", "--tranche", "50", "--balance", other, "--issue", 7).output)
    assert (out["amount"], out["tranche"], out["fee"], out["work_s"]) == (500_000_000, 50_000_000, 1_500_000, 90 * 86_400)
    assert out["fund_audience"].startswith(f"knos3:fund:7:500000000:0:{out['terms_hash']}:7776000:{other}:0:08")


def test_a_period_is_paid_from_a_reserve_locked_before_the_work_and_what_it_does_not_draw_returns_to_the_buyer_at_the_deadline():
    pytest.importorskip("solders.litesvm")
    from _order import DAY, OWNER, USDC, OrderChain, code
    from _reserve import draw, locked
    from knos.settle.v2 import pay

    assert OWNER == BUYER
    c = OrderChain()
    baltok = pay.baltok_pda(c.bal)
    start, fee0, tip0 = c.balance(baltok), c.balance(c.fee), c.balance(c.tip)
    supplier = c.fund().pubkey()
    stok = c.token_account(supplier, c.usdc)

    # 1. the buyer locks 10.00 for this supplier, drawn 2.00 at a time: the order holds it, and the fee on top
    order, f = locked(c, SUPPLIER, "10", "2")
    o = c.order(order)
    assert (f["amount"], f["fee"]) == (10 * USDC, 50_000) and c.held(order) == 10_050_000 == start - c.balance(baltok)
    facts = netting.reserve_of(o, order, BUYER, SUPPLIER, c.now())
    assert (facts["funded"], facts["tranche"], facts["deadline"], facts["returns_to"]) == (10 * USDC, 2 * USDC, o.deadline, str(baltok))
    # an order that locks nothing for this pair is not a reserve: another supplier's, and one that is not standing
    with pytest.raises(Bad, match="not funded on the reserve terms"):
        netting.reserve_of(o, order, BUYER, SUPPLIER + 1, c.now())
    with pytest.raises(Bad, match="an open standing order"):
        netting.reserve_of(c.order(c.fund_wallet()), order, BUYER, SUPPLIER, c.now())
    # nobody takes it back before the deadline: not the relayer, not anyone
    assert not c.refund(order) and code(c) == 83

    # 2. the period, in both books: 31 outcomes of 0.32 fit, the 32nd is past the reserve
    def book() -> str:
        text = netting.open_line(netting.Book(), BUYER, SUPPLIER, pay_month, "500", reserve=facts) + "\n"
        text, refused = added(text, [one(i) for i in range(32)])
        assert len(refused) == 1 and refused[0]["why"].startswith("past the reserve")
        return text
    from knos.settle.v2 import meter
    pay_month = meter.yyyymm(c.now())
    n, mine = closed(book(), book())
    p = netting.read(mine).periods[0]
    s = netting.reserve_state(p)
    assert (s["consumed"], s["free"], s["draws"], s["drawn"], s["undrawn"]) == (9_920_000, 80_000, 4, 8 * USDC, 1_920_000)
    assert netting.reserve_check(p, c.order(order), c.now()) == []

    # 3. the release: four draws the order's judge signs, 2.00 each, out of the order and nowhere else
    ds = netting.draws(p, supplier)
    for k, d in enumerate(ds, 1):
        assert draw(c, order, d, SUPPLIER, supplier), c.err
        left = c.order(order)
        assert c.balance(stok) == k * 2 * USDC and left.amount == 10 * USDC - k * 2 * USDC          # the chain's own conservation, draw by draw
        assert c.held(order) == left.amount + left.fee and left.fee == 50_000 - k * 10_000
    assert not draw(c, order, ds[0], SUPPLIER, supplier) and code(c) == 91          # a draw is paid once
    # the fee's share of each draw (0.01) is less than a tip, so the relayer takes it; nothing else left the order
    assert c.balance(baltok) == start - 10_050_000 and c.balance(c.fee) == fee0 and c.balance(c.tip) == tip0 + 4 * 10_000

    # 4. the next period on the same order starts from the 1.92 the first left undrawn, and one more line draws it
    mine += netting.settled_line(netting.read(mine), p.name, str(order)) + "\n"
    again = netting.reserve_of(c.order(order), order, BUYER, SUPPLIER, c.now())
    assert again["funded"] == 2 * USDC
    mine += netting.open_line(netting.read(mine), BUYER, SUPPLIER, pay_month, "500", reserve=again) + "\n"
    mine, refused = added(mine, [one(50, "0.08")])
    _n2, mine = closed(mine)
    p2 = netting.read(mine).periods[1]
    assert not refused and netting.reserve_state(p2)["brought"] == 1_920_000 and netting.reserve_state(p2)["undrawn"] == 0
    c.warp(1)

    # 5. the buyer leaves the second period's draw unsigned. Past the deadline anyone sends RefundOrder, and what no
    #    draw took goes back to the buyer's Balance with the fee's unspent share: to nobody else
    c.warp(14 * DAY + 1)
    assert netting.reserve_check(p2, c.order(order), c.now()) == ["the order is past its deadline: anyone can send RefundOrder and the buyer has it back"]
    assert not draw(c, order, netting.draws(p2, supplier)[0], SUPPLIER, supplier)
    assert not c.refund(order, stok) and code(c) == 88
    assert c.refund(order), c.err
    assert c.data(order) is None and c.balance(stok) == 8 * USDC
    assert start - c.balance(baltok) == 8 * USDC + 40_000                           # locked 10.05; drawn 8.00 and its 0.04 of fee; 2.01 came back
    print("RESERVE", json.dumps({"locked": 10_050_000, "drawn": 8 * USDC, "fee_on_draws": 40_000, "returned": 2_010_000}))
