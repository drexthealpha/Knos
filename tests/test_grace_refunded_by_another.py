"""The grace after-round of scripts/exercise_public.py when someone else refunded the order first.

In the 0.3.24 release run the public relay refunded the grace order 41 s after its grace ended, before the round did,
and the round failed with "the order is not there". RefundOrder is anyone's once the grace is over: the round now reads
knos_pay's own line of that refund (the amount and the fee as funded), notes who sent it, and passes; a refund of any
other sum, or none, is still a failure."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
if "exercise_public" in sys.modules:           # tests/test_exercise_public.py loaded it: the same module, once
    ex = sys.modules["exercise_public"]
else:
    spec = importlib.util.spec_from_file_location("exercise_public", ROOT / "scripts" / "exercise_public.py")
    assert spec is not None and spec.loader is not None
    ex = importlib.util.module_from_spec(spec)
    sys.modules["exercise_public"] = ex
    spec.loader.exec_module(ex)

RELAY = "5zGQCyrtK4gv61EYpUvoKApWAxvbPucpHABA1vdhAJ9V"
FUNDER = ex.Keypair.from_seed(bytes([71]) * 32)
REPO, ISSUE = 1_234_567, 99
ORDER = ex.pay.order_pda(ex.pay.scope_of(REPO, ISSUE), FUNDER.pubkey(), 8)
BACK = ex.AMOUNT + 50_000


def lines(amount: int, program=ex.pay.PAY_ID) -> list[str]:
    return [f"Program {program} invoke [1]", f"Program log: knos3:refunded order={ORDER} amount={amount}", f"Program {program} success"]


class Ledger:
    def __init__(self, logs: dict[str, list[str]]):
        self.said = logs

    def history(self, address, most=500):
        return [s for s in self.said if s.endswith(str(address))][:most]

    def logs(self, sig):
        return self.said[sig]

    def payer_of(self, sig):
        return RELAY


class Late(ex.World):
    """The order was there when the round read it; the relay's refund lands before the round's own (`raced`), or had
    landed before the round started again (`gone`)."""

    def __init__(self, logs: dict[str, list[str]], raced: bool):
        self.ledger, self.raced, self.funder, self.sent = Ledger(logs), raced, FUNDER, []
        self.funder_token = ex.pay.ata(FUNDER.pubkey(), ex.pay.USDC_DEVNET)
        self.relayer = ex.Keypair.from_seed(bytes([72]) * 32)

    def pin(self):
        return "o/r", "0" * 40, REPO

    def wait_until(self, t, what):
        pass

    def account(self, address):
        return b"\x00" * 300 if self.raced and not self.sent else None

    def send(self, ixs, payer=None, signers=None):
        self.sent.append(ixs)
        raise ex.chain.RpcError("Transaction simulation failed: the order account is closed")


def run(logs: dict[str, list[str]], raced: bool = False) -> dict:
    st = {"round": "grace", "issue": ISSUE, "fund": {"signature": "f", "order": str(ORDER), "amount": ex.AMOUNT, "fee": 50_000, "deadline": 1, "pay_until": 7201},
          "early": {"signature": "e", "error": 83, "means": "x"}}
    w = Late(logs, raced)
    ex.after_grace(ex.Book({"rounds": {}, "exercises": {}}, w, lambda _s: None), st)
    return st


def test_a_refund_the_relay_sent_first_is_read_and_noted_and_the_round_passes():
    st = run({f"sig-{ORDER}": lines(BACK)})
    assert st["refund"] == {"signature": f"sig-{ORDER}", "refunded": True, "sent_by": RELAY}
    [row] = st["transactions"]
    assert row["signature"] == f"sig-{ORDER}" and RELAY in row["what"] and "went back to the wallet whole (5.05)" in row["what"], row


def test_a_refund_that_lands_between_the_read_and_the_rounds_own_is_read_too(monkeypatch):
    monkeypatch.setattr(ex.pay, "read_order", lambda data: object())             # the order as read the moment before the relay's refund
    monkeypatch.setattr(ex.pay, "refund_order_ix", lambda *a, **k: "refund")
    st = run({f"sig-{ORDER}": lines(BACK)}, raced=True)
    assert st["refund"]["signature"] == f"sig-{ORDER}" and st["refund"]["sent_by"] == RELAY


@pytest.mark.parametrize("logs", [{f"sig-{ORDER}": lines(BACK - 1)},                                                  # another sum
                                  {f"sig-{ORDER}": lines(BACK, program=ex.Keypair.from_seed(bytes([9]) * 32).pubkey())},  # another program
                                  {}])                                                                                # nothing
def test_an_order_gone_with_no_refund_of_its_amount_and_fee_is_still_a_failure(logs):
    with pytest.raises(ex.Failed, match=r"the order is not there, and no transaction of knos_pay refunded it with its amount and its fee \(5.05\)"):
        run(logs)
