"""Records what a cluster would answer about a small history, for the tests of sdk/settle/agent.js.

The history is run through the second deployment's test builds in LiteSVM (tests/_order.py and tests/_meter.py): a
repository's issue with a wallet's order, a Balance's order and a wallet's job on it, an order that has run out of time,
two evaluations of the meter and two payments of the escrow in September, and in October three evaluations for one buyer,
one for another, and two more payments. What is written is what a public RPC would give about it: the accounts of the
escrow, the meter and the token program, the transactions that named the escrow or the meter (their logs, as the
programs printed them) and the signatures that named each address. The expectations beside them come from the Python
client (the authority), the scenario's own numbers and the programs' own log lines, never from agent.js.

    PYTHONPATH=src python scripts/record_settle_agent.py            writes sdk/settle/agent.recorded.json
    PYTHONPATH=src python scripts/record_settle_agent.py --check    exits 1 unless the file is a recording of this scenario's shape
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "src")]

from _meter import BUYER, Meter  # noqa: E402
from _order import AUTHOR, OWNER, REPO, USDC, WF_REPO, WF_SHA, OrderChain, user  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.signature import Signature  # noqa: E402

from knos import fees  # noqa: E402
from knos import terms as terms_mod  # noqa: E402
from knos.settle.v2 import meter, pay  # noqa: E402

OUT = ROOT / "sdk" / "settle" / "agent.recorded.json"
ISSUE, EXPIRED_ISSUE, SEPT_ISSUE, OCT_ISSUE, SPLIT_ISSUE = 4242, 4343, 4444, 4545, 4646
BUYER2, SELLER = 777000, AUTHOR
DAY = 86_400


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


class World(Meter, OrderChain):
    """The escrow, the meter and the verifier on one chain, remembering each transaction that named the escrow or the meter."""

    def __init__(self):
        self.seen: list[dict] = []
        super().__init__()

    def send(self, ixs, payer=None, signers=(), tag=None) -> bool:
        ixs = list(ixs)
        ok = super().send(ixs, payer, signers, tag)
        programs = {pay.PAY_ID, meter.METER_ID}
        if ok and any(ix.program_id in programs for ix in ixs):
            keys = {(payer or self.payer).pubkey(), *(ix.program_id for ix in ixs), *(a.pubkey for ix in ixs for a in ix.accounts)}
            sig = str(Signature(hashlib.sha512(f"knos agent recording {len(self.seen)}".encode()).digest()))
            self.seen.append({"signature": sig, "blockTime": self.now(), "logs": list(self.logs), "keys": sorted(map(str, keys))})
        return ok

    def last_signature(self) -> str:
        return self.seen[-1]["signature"]


def canonical(**over) -> bytes:
    base = {"accept": "", "checks": [{"app": 15368, "name": "test"}], "deny": [".github/**", ".knos/**"], "mode": "merge", "paths": [], "reserve": 7, "v": 1}
    return terms_mod.canonical({**base, **over})


def scenario() -> tuple[World, dict]:
    c = World()
    plain, narrow = canonical(), canonical(checks=[{"app": 0, "name": "lint"}], paths=["src/**", "docs/*.md"], reserve=3)
    tests = canonical(mode="tests", accept="ab" * 32, checks=[])
    made: dict = {"terms": {"plain": plain.decode(), "narrow": narrow.decode(), "tests": tests.decode()}}

    # September: an issue with three kinds of money on it, an order that runs out, a payment, two evaluations
    made["wallet_order"] = c.fund_wallet(ISSUE, 20 * USDC, terms=plain)
    made["balance_order"] = c.fund_balance(ISSUE, 30 * USDC, terms=narrow)
    funder2, tok2 = c.wallet(c.usdc, 1000 * USDC)
    assert c.send([pay.fund_wallet_ix(funder2.pubkey(), tok2, c.usdc, REPO, ISSUE, 15 * USDC, WF_REPO, WF_SHA, tests, pay.TESTS, 20 * DAY)], funder2), c.err
    made["job"] = pay.job_pda(REPO, ISSUE, funder2.pubkey())
    made["expiring_order"] = c.fund_wallet(EXPIRED_ISSUE, 12 * USDC, terms=plain, work_s=3600)
    wallet = Keypair().pubkey()
    assert c.bind(SELLER, wallet), c.err
    paid_sept = c.fund_wallet(SEPT_ISSUE, 50 * USDC, terms=plain)
    assert c.pay(paid_sept, [(SELLER, 10_000, None)]), c.err
    made["sept_paid"] = c.said("knos3:paid")
    credits, other = c.open(c.usdc, BUYER, 5 * USDC)[1], c.open(c.usdc, BUYER2, 5 * USDC)[1]
    for n, (verdict, rate) in enumerate(((1, 2_000_000), (0, 0))):
        assert c.record(credits, c.aud(verdict=verdict, rate=rate, seller=SELLER, buyer=BUYER, order=bytes([n + 1]) * 32)), c.err
    # October: the Balance's order is still open, the short one has run out, and the seller is paid and bills more
    c.warp(12 * DAY)
    month = meter.yyyymm(c.now())
    made["month"] = month
    c.set_used(BUYER, 10_000)       # past the free evaluations: each one now costs
    for n, (verdict, rate) in enumerate(((1, 2_000_000), (1, 3_000_000), (0, 0))):
        assert c.record(credits, c.aud(verdict=verdict, rate=rate, seller=SELLER, buyer=BUYER, order=bytes([n + 10]) * 32)), c.err
    assert c.record(other, c.aud(verdict=1, rate=4_000_000, seller=SELLER, buyer=BUYER2, order=bytes([20]) * 32)), c.err
    made["oct_paid"] = []
    for issue, payees in ((OCT_ISSUE, [(SELLER, 10_000, None)]), (SPLIT_ISSUE, [(SELLER, 6000, None), (user(), 4000, None)])):
        order = c.fund_wallet(issue, 40 * USDC, terms=plain)
        if len(payees) == 2:
            assert c.bind(payees[1][0], Keypair().pubkey()), c.err
        assert c.pay(order, payees), c.err
        made["oct_paid"] += [{"signature": c.last_signature(), "lines": c.said("knos3:paid")}]
    return c, made


def record(c: World, made: dict) -> dict:
    accounts = {}
    for program in (pay.PAY_ID, meter.METER_ID, pay.TOKEN):
        for address, account in c.svm.get_program_accounts(program):
            if account.lamports > 0:
                accounts[str(address)] = {"owner": str(account.owner), "lamports": account.lamports, "data": b64(bytes(account.data))}
    transactions = {t["signature"]: {"blockTime": t["blockTime"], "logs": t["logs"], "keys": t["keys"]} for t in c.seen}
    signatures: dict[str, list[str]] = {}
    for t in reversed(c.seen):
        for key in t["keys"]:
            signatures.setdefault(key, []).append(t["signature"])
    now = c.now()
    out = {"note": "What a public RPC would answer about the history scenario() in scripts/record_settle_agent.py runs in LiteSVM; see the script.",
           "programs": {"knos_pay": str(pay.PAY_ID), "knos_meter": str(meter.METER_ID)}, "clock": {"slot": 7_000, "time": now},
           "mints": {"usdc": str(c.usdc), "faucet": str(pay.faucet_mint())}, "accounts": accounts, "signatures": signatures, "transactions": transactions}
    out["expect"] = expect(c, made, now)
    return out


def expect(c: World, made: dict, now: int) -> dict:
    """What the clients must say, from the Python client, the programs' log lines and the scenario's numbers."""
    def order_row(address, funder):
        o = pay.read_order(c.data(address))
        return {"kind": "order", "address": str(address), "state": o.state, "mode": o.mode, "amount": o.amount, "fee": o.fee, "paid": o.paid, "deadline": o.deadline,
                "mint": str(o.mint), "decimals": o.decimals, "terms": o.terms.hex(), "funder": funder}
    wallet = pay.read_order(c.data(made["wallet_order"]))
    job = pay.read_job(c.data(made["job"]))
    held = c.balance(pay.baltok_pda(c.bal))
    b = pay.read_balance(c.data(c.bal))
    bx = pay.read_balx(c.data(pay.balx_pda(c.bal))) if c.data(pay.balx_pda(c.bal)) else None
    describe = {name: terms_mod.describe(terms_mod.parse(made["terms"][name])) for name in ("plain", "narrow", "tests")}
    return {
        "issue": {"repo": REPO, "issue": ISSUE, "expired_issue": EXPIRED_ISSUE},
        "orders": [order_row(made["wallet_order"], {"kind": "wallet", "wallet": str(wallet.source)}),
                   order_row(made["balance_order"], {"kind": "balance", "ownerId": OWNER, "holds": held, "spent": b.spent, "capPerJob": b.cap_per_job,
                                                       "spenders": list(b.spenders), "faucet": b.faucet, "limits": bx is not None})],
        "job": {"address": str(made["job"]), "state": job.state, "mode": job.mode, "amount": job.amount, "deadline": job.deadline, "mint": str(job.mint), "terms": job.terms.hex(),
                "source": str(job.source), "net": job.amount - fees.live(c.ledger).job(job.amount)},
        # which knos_pay the recording was made on (knos.fees: 2 is 2.2 and the 0.3.18 fee): a job's fee is the one that build takes
        "fee_version": fees.version(c.ledger),
        "expiring": {"address": str(made["expiring_order"]), "deadline": pay.read_order(c.data(made["expiring_order"])).deadline},
        "terms_json": made["terms"], "terms_words": describe, "now": now, "month": made["month"],
        "statement": {
            "seller": SELLER,
            "meter": {str(buyer): vars(meter.statement(c.ledger, buyer, SELLER, made["month"])) for buyer in (BUYER, BUYER2)},
            "meter_accounts": {str(buyer): vars(c.month(buyer, SELLER, made["month"])) for buyer in (BUYER, BUYER2)},
            "september": vars(meter.statement(c.ledger, BUYER, SELLER, 202609)),
            "escrow": [{"signature": p["signature"], "line": line} for p in made["oct_paid"] for line in p["lines"] if f"payee={SELLER} " in line],
            "september_escrow": made["sept_paid"],
        },
    }


def main(argv: list[str]) -> int:
    c, made = scenario()
    out = record(c, made)
    if "--check" in argv:
        have = json.loads(OUT.read_text(encoding="utf-8"))
        same = (set(have["expect"]) == set(out["expect"]) and have["programs"] == out["programs"] and len(have["transactions"]) == len(out["transactions"]))
        print("agent.recorded.json is a recording of this scenario" if same else "agent.recorded.json is not a recording of this scenario: run the script")
        return 0 if same else 1
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out['accounts'])} accounts, {len(out['transactions'])} transactions, {OUT.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
