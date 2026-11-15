"""One organisation's month for the finance tests: its work orders (test_audit.month), its bounties on issues, and both.

The bounties are the second escrow's jobs as `records.events_of` gives their lines: one paid from the organisation's
faucet Balance, one paid from its own Balance, one accepted and held for a payee with no wallet, one refunded, one
open, and another organisation's. `REFS` is a buyer's refs file for the mix; `write_golden` writes tests/data/finance.
"""
from __future__ import annotations

from pathlib import Path

from knos.settle.v2 import pay as pay2

DATA = Path(__file__).parent / "data" / "finance"
ACME, OTHER = 5001, 5002
DAY, T0, U = 86_400, 1_788_220_800, 1_000_000       # 2026-09-01T00:00:00Z
FAUCET = str(pay2.faucet_balance_pda(ACME))
JOB_TERMS = '{"checks":[{"app":15368,"name":"test"}],"mode":"tests","v":1}'
SEPT = dict(first="2026-09-01", last="2026-09-30")
REFS = ("order,ref,paid_outside,dispute\n"
        "OrdA,PO-4411 line 2,,\n"
        "OrdB:FB:12,PO-4412 line 1,2026-09-28 bank ref 77120,\n"
        "OrdD,PO-4413,,the second payee's share is contested\n")
OPTIONS = {"account": "6100 Contract engineering", "entity": "1000", "tax_code": "", "date_format": ""}


def line(event: str, at: int, tx: str, **fields) -> dict:
    return {"event": event, "v": 2, "at": at, "signer": "relayer", "keys": ["relayer"], "tx": tx, **fields}


def bounty(issue: int, at: int, tx: str, amount: int, source: str, by: int = 6001, faucet: int = 0, repo: int = 7001, mode: int = 1) -> list[dict]:
    return [line("funded", at, tx, repo=repo, issue=issue, amount=amount, mode=mode, by=by, source=source, faucet=faucet), line("terms", at, tx, json=JOB_TERMS)]


def bounty_paid(issue: int, at: int, tx: str, payee: int, net: int, fee: int, repo: int = 7001, pr: int = 0) -> dict:
    return line("paid", at, tx, repo=repo, issue=issue, payee=payee, amount=net, fee=fee, to=f"W{payee}", **({"pr": pr} if pr else {}))


def bounties() -> list[dict]:
    import test_audit as base
    d = lambda n: T0 + n * DAY       # noqa: E731
    ev = [line("balance", T0 - DAY, "B1", owner=ACME, authority=base.WALLET, mint=base.MINT),
          line("balance", T0 - DAY, "B2", owner=OTHER, authority=base.WALLET2, mint=base.MINT),
          line("balance", T0 - DAY, "B3", owner=ACME, authority=str(pay2.auth_pda()), mint=str(pay2.faucet_mint()))]
    ev += bounty(21, d(1) + 60, "JF1", 20 * U, FAUCET, by=9100, faucet=1) + [bounty_paid(21, d(2) + 60, "JP1", 8001, 19_500_000, 500_000, pr=31)]
    ev += bounty(22, d(3) + 60, "JF2", 40 * U, base.BAL) + [bounty_paid(22, d(4) + 60, "JP2", 8002, 39 * U, 1 * U)]
    ev += bounty(23, d(5) + 60, "JF3", 10 * U, base.BAL) + [line("held", d(6) + 60, "JH3", repo=7001, issue=23, payee=8006, until=d(186) + 60)]
    ev += bounty(24, d(7) + 60, "JF4", 12 * U, base.BAL) + [line("refunded", d(21) + 60, "JR4", repo=7001, issue=24, amount=12 * U)]
    ev += bounty(25, d(9) + 60, "JF5", 15 * U, base.BAL)
    ev += bounty(26, d(10) + 60, "JF6", 30 * U, base.BAL2, repo=7002) + [bounty_paid(26, d(11) + 60, "JP6", 8001, 29_250_000, 750_000, repo=7002)]
    return sorted(ev, key=lambda e: e["at"])


def mix() -> list[dict]:
    import test_audit as base
    balances = {e["tx"] for e in bounties() if e["event"] == "balance"}
    return sorted([*bounties(), *(e for e in base.month() if e["tx"] not in balances)], key=lambda e: e["at"])


def extras() -> dict:
    """What the log lines do not carry, for the records of the mix: the acceptance receipt of one payment (the parts a
    record reads, made by knos.receipt's own functions) and nothing else. {"receipts": {paying transaction: receipt}}."""
    from knos import receipt
    judge = receipt.evaluator("attestor", {"repository_id": 9900, "repository_owner_id": 9901, "actor_id": 9902, "runner_environment": "github-hosted"},
                              (6001, ACME), (8001,))
    same, said = receipt.independence_of([judge])
    authorised = receipt.authorisation(order="OrdC", milestone=0, funded_tx="FC", funder_id=6001, login="acme-bot", source="balance", address="Bal",
                                       owner_id=ACME, cap=250 * U, total=1000 * U, repositories=(7001,))
    return {"receipts": {"PC": {"version": 3, "commercial_authorisation": authorised,
                                "evaluator_observed": {"evaluators": [judge], "same_controller": same, "independence": said}}}}
