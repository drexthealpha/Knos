"""`/knos reserve <amount> for @supplier until <date> [tranche <amount>] [period YYYY-MM]`: a buyer locks money for one
supplier through the same workflow (fund.yml runs `knos command`) and the same checks as any funding comment. The fakes
are tests/_flow.py's; the order the comment funds is then read by knos.netting exactly as `knos net open --reserve`
reads it on the chain."""
from __future__ import annotations

import time

from _flow import EVE, HUBOT, MONA, REPO_ID, T0, World
from knos import commands, flow, netting
from knos.settle.v2 import pay

FAUCET = pay.faucet_balance_pda(HUBOT["id"])
ORDER = pay.order_pda(pay.scope_of(REPO_ID, 7), FAUCET, 0)


def world(tmp_path) -> World:
    w = World(tmp_path)
    w.version = 2
    w.hub.issue(7, "Agent calls for October, netted.")
    return w


def said(w: World, who_: dict, body: str, code: int = 0) -> str:
    assert flow.command(w.run(w.hub.commented(7, who_, body))) == code
    return w.hub.knos(7)[-1]


def test_the_grammar_reads_a_reserve_and_says_the_form_for_anything_else():
    got = commands.parse("/knos reserve 500 for @acme-agents until 2026-12-31 tranche 50 period 2026-11", False)
    assert got == commands.Reserve(500_000_000, "acme-agents", "2026-12-31", 50_000_000, 202611)
    assert commands.parse("/knos Reserve 20 FOR @mona until 2026-10-30", False) == commands.Reserve(20_000_000, "mona", "2026-10-30")
    for line, why in (("/knos reserve 20 for mona until 2026-10-30", "say the amount, the supplier and the last day"),
                      ("/knos reserve 20 for @mona until 2026-02-30", "a date written YYYY-MM-DD"),
                      ("/knos reserve 20 for @mona until 2026-10-30 tranche 21", "more than the reserve"),
                      ("/knos reserve 20 for @mona until 2026-10-30 period 2026-13", "a month written YYYY-MM"),
                      ("/knos reserve 20 for @mona until 2026-10-30 tranche 2 tranche 3", "written twice"),
                      ("/knos reserve 20 for @mona until 2026-10-30 warranty 3", "`warranty` is not something this command takes")):
        e = commands.parse(line, False)
        assert isinstance(e, commands.Error) and e.command == "reserve" and why in e.reply and commands.FORMS["reserve"] in e.reply, (line, e)
    assert commands.parse("/knos reserve 20 for @mona until 2026-10-30", True).kind == "misplaced"
    assert "/knos reserve <amount> for @supplier" in commands.reply("understood", commands.Help())


def test_a_reserve_comment_locks_a_standing_order_for_one_supplier_and_says_its_id_amount_deadline_and_how_the_supplier_checks_it(tmp_path):
    w = world(tmp_path)
    got = said(w, HUBOT, "/knos reserve 10 for @mona until 2026-09-30 tranche 2 period 2026-09")
    # GitHub was asked to sign exactly what knos.netting.reserve_fund says for this pair and period, through reserve_plan
    end = 1_790_812_800                          # 2026-10-01 00:00 UTC: the close of 2026-09-30
    want = netting.reserve_fund(HUBOT["id"], MONA["id"], 10_000_000, 2_000_000, FAUCET, 7, end - int(T0), seq=0, period=202609)
    assert w.signer.asked == [want["fund_audience"]]
    (address, o), = w.chain.orders(7)
    assert address == str(ORDER) and o.flags & pay.F_STANDING and (o.amount, o.rate, o.holdback_bps) == (10_000_000, 2_000_000, 0)
    assert w.chain.logs[address].decode() == want["terms"] and '"period":202609' in want["terms"]
    assert got.startswith("Knos: a reserve of 10.00 test USDC for @mona is locked on issue #7 ([order on Solana](")
    assert f"Reserve id: `{ORDER}`. Amount: 10.00. Deadline: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(o.deadline))}." in got
    assert "It secures period 2026-09 only, and pays @mona 2.00 for each draw this repository's workflow signs." in got
    assert (f"`knos net open BOOK --buyer {HUBOT['id']} --seller {MONA['id']} --month 2026-09 --cap 10 --reserve {ORDER}`" in got
            and not got.lstrip().startswith("/knos"))
    # the supplier's check: the order on the chain secures this pair for 2026-09, and for no other month
    facts = netting.reserve_of(o, address, HUBOT["id"], MONA["id"], w.chain.now(), month=202609)
    assert (facts["funded"], facts["tranche"], facts["period"]) == (10_000_000, 2_000_000, 202609)
    book = netting.read(netting.open_line(netting.Book(), HUBOT["id"], MONA["id"], 202609, "10", reserve=facts) + "\n")
    assert book.periods[0].reserve["period"] == 202609
    for month in (None, 202610):
        try:
            netting.reserve_of(o, address, HUBOT["id"], MONA["id"], w.chain.now(), month=month)
        except netting.Bad as why:
            assert "another month" in str(why)
        else:
            raise AssertionError(f"a reserve for 2026-09 was taken for {month}")
    # a draw of a period bound to it names the order's own terms hash (the one with the period), as the program asks
    text = netting.text_of(book) + "".join(line + "\n" for line in netting.add(book, [
        {"order": "a" * 64, "milestone": i, "artifact": "b" * 40, "policy": "c" * 64, "amount": "0.50", "evidence": f"{i:064x}"} for i in range(4)])[0])
    _n, line = netting.close(netting.read(text))
    (d,) = netting.draws(netting.read(text + line + "\n").periods[0])
    assert d["pay_audience"].split(":")[4] == o.terms.hex()


def test_a_reserve_asks_who_may_fund_and_the_procurement_gate_and_refuses_in_words_what_the_escrow_would(tmp_path, monkeypatch):
    from knos import approvals
    w = world(tmp_path)
    assert "is for people with write access to this repository" in said(w, EVE, "/knos reserve 10 for @mona until 2026-09-30")
    assert "GitHub gave no account named @nobody-here (the supplier)" in said(w, HUBOT, "/knos reserve 10 for @nobody-here until 2026-09-30")
    assert "@hubot owns this repository" in said(w, HUBOT, "/knos reserve 10 for @hubot until 2026-09-30")
    assert "2026-09-01 has passed" in said(w, HUBOT, "/knos reserve 10 for @mona until 2026-09-01")
    assert "at most 90 days" in said(w, HUBOT, "/knos reserve 10 for @mona until 2027-06-30")
    assert "before period 2026-11 begins" in said(w, HUBOT, "/knos reserve 10 for @mona until 2026-10-15 period 2026-11")
    assert "between 5.00 and 100,000.00" in said(w, HUBOT, "/knos reserve 2 for @mona until 2026-09-30")
    w.version = 0
    assert "does not hold work orders yet" in said(w, HUBOT, "/knos reserve 10 for @mona until 2026-09-30")
    w.version = 2
    assert w.signer.asked == [] and w.chain.orders(7) == []
    # the procurement gate is asked as for every funding comment: subject issue:7, this requester, this amount
    asked: list[dict] = []
    monkeypatch.setattr(flow, "_procurement", lambda run, rp: {".knos/procurement/policy.yaml": "x"})
    monkeypatch.setattr(approvals, "gate_order", lambda files, **kw: asked.append(kw) or (False, "Refused: issue:7 is not approved."))
    got = said(w, HUBOT, "/knos reserve 10 for @mona until 2026-09-30")
    assert got.startswith("Knos: nothing was reserved. Refused: issue:7 is not approved.") and w.chain.orders(7) == []
    assert [(a["subject"], a["requester"], a["amount"]) for a in asked] == [("issue:7", "hubot", 10_000_000)]
    monkeypatch.setattr(approvals, "gate_order", lambda files, **kw: (True, ""))
    assert said(w, HUBOT, "/knos reserve 10 for @mona until 2026-09-30").startswith("Knos: a reserve of 10.00 test USDC for @mona is locked")
    assert "It secures any netted period of @mona's until " in w.hub.knos(7)[-1] and len(w.chain.orders(7)) == 1


def test_where_the_buyer_keeps_approval_requests_a_reserve_is_funded_only_by_the_approval_bound_to_it(tmp_path, monkeypatch):
    from knos import approvals, boundary
    w = world(tmp_path)
    bound: list[dict] = []
    monkeypatch.setattr(approvals, "gate_order", lambda files, **kw: (True, ""))
    monkeypatch.setattr(boundary, "gate_bound", lambda files, **kw: bound.append(kw) or (False, "Refused: the approval is for a payment to @octocat, not to @mona."))
    # procurement files without approval requests: the bound approval is not asked
    monkeypatch.setattr(flow, "_procurement", lambda run, rp: {".knos/procurement/policy.yaml": "x"})
    assert said(w, HUBOT, "/knos reserve 10 for @mona until 2026-09-30").startswith("Knos: a reserve of 10.00 test USDC for @mona is locked")
    assert bound == []
    # with a request under requests/: the commitment of this reserve is what the approval must name
    monkeypatch.setattr(flow, "_procurement", lambda run, rp: {".knos/procurement/policy.yaml": "x", ".knos/procurement/requests/r.json": "{}"})
    w.hub.issue(8, "Another reserve.")
    assert flow.command(w.run(w.hub.commented(8, HUBOT, "/knos reserve 10 for @mona until 2026-09-30"))) == 0
    got = w.hub.knos(8)[-1]
    assert got.startswith("Knos: nothing was reserved. Refused: the approval is for a payment to @octocat, not to @mona.") and w.chain.orders(8) == []
    [kw] = bound
    order = kw["order"]
    assert (order["repo_id"], order["issue"], order["seq"], order["funder"], order["amount"], order["beneficiary"]) == (REPO_ID, 8, 0, "hubot", 10_000_000, "mona")
    assert len(order["terms_sha256"]) == 64 and kw["requester"] == "hubot"
