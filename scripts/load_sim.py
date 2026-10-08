"""A cluster's JSON-RPC as scripts/load.py asks it, answered by LiteSVM with the committed test builds.

`python scripts/load.py measure --relays N --orders M --simulate` runs the whole measurement here: every key, every
instruction and every check is the one the cluster run uses. What it does NOT give is a rate: the simulator has no
leader, no block limit and no other traffic, and its clock is the script's own (a `sleep` adds to it). So a simulated
run proves that the command works from its first transaction to its last, and measures nothing.
"""
from __future__ import annotations

import base64
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [p for p in (str(ROOT / "src"), str(ROOT / "tests")) if p not in sys.path]

from solders.pubkey import Pubkey  # noqa: E402
from solders.transaction import Transaction  # noqa: E402

from knos import chain  # noqa: E402
from knos.settle.v2 import pay  # noqa: E402


class SimRpc:
    """One transaction lands per slot, in the order the relays hand them in. `confirmed` when its status is first
    asked, `finalized` the third time. A transaction may be signed over any of the last 150 blockhashes, as on a
    cluster. `drop(k)`: the k-th submission is acknowledged and thrown away, as a cluster under load does."""

    def __init__(self, drop=lambda k: False):
        from _oidc2 import Chain2
        self.c = Chain2(programs={pay.PAY_ID: "knos_pay_v2_test.so"})
        self.c.svm = self.c.svm.with_blockhash_check(False)
        self.recent = [str(self.c.svm.latest_blockhash())]
        self.drop, self.lock = drop, threading.RLock()
        self.asked: dict[str, int] = {}
        self.slot_of: dict[str, int] = {}
        self.seen: set[str] = set()
        self.submissions, self.t, self.slot = 0, 0.0, 1
        # every method scripts/load.py calls, by its JSON-RPC name
        self.methods = {"getLatestBlockhash": self._getLatestBlockhash, "getMinimumBalanceForRentExemption": self._getMinimumBalanceForRentExemption, "getSlot": self._getSlot, "getBlockTime": self._getBlockTime, "getBalance": self._getBalance, "sendTransaction": self._sendTransaction, "getSignatureStatuses": self._getSignatureStatuses, "getMultipleAccounts": self._getMultipleAccounts}

    def clock(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        with self.lock:
            self.t += seconds
            self.c.warp(max(1, int(seconds)))

    def call(self, method: str, params: list):
        with self.lock:
            return self.methods[method](*params)

    def _getLatestBlockhash(self, _cfg):
        return {"value": {"blockhash": str(self.c.svm.latest_blockhash())}}

    def _getMinimumBalanceForRentExemption(self, space):
        return self.c.svm.minimum_balance_for_rent_exemption(space)

    def _getSlot(self, _cfg):
        return self.slot

    def _getBlockTime(self, _slot):
        return self.c.now()

    def _getBalance(self, address, _cfg=None):
        return {"value": int(self.c.svm.get_balance(Pubkey.from_string(address)) or 0)}

    def _sendTransaction(self, raw, _cfg):
        tx = Transaction.from_bytes(base64.b64decode(raw))
        sig = str(tx.signatures[0])
        self.submissions += 1
        if str(tx.message.recent_blockhash) not in self.recent[-150:]:
            raise chain.RpcError("Transaction simulation failed: Blockhash not found")
        if sig not in self.seen and self.drop(self.submissions):
            self.seen.add(sig)
            return sig
        self.seen.add(sig)
        r = self.c.svm.send_transaction(tx)
        if "Failed" in type(r).__name__:
            raise chain.RpcError(f"Transaction simulation failed: {r.err()}")
        self.c.svm.expire_blockhash()
        self.recent.append(str(self.c.svm.latest_blockhash()))
        self.slot += 1
        self.asked[sig], self.slot_of[sig] = 0, self.slot
        return sig

    def _getSignatureStatuses(self, sigs, _cfg):
        out: list[dict | None] = []
        for s in sigs:
            if s not in self.asked:
                out.append(None)
                continue
            self.asked[s] += 1
            out.append({"err": None, "slot": self.slot_of[s], "confirmationStatus": "finalized" if self.asked[s] >= 3 else "confirmed"})
        return {"value": out}

    def _getMultipleAccounts(self, addresses, _cfg):
        got = [self.c.data(Pubkey.from_string(a)) for a in addresses]
        return {"value": [None if d is None else {"data": [base64.b64encode(d).decode(), "base64"]} for d in got]}
