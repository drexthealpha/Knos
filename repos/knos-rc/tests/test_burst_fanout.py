"""The burst on a public endpoint, as 9 October 2026 met it: 22 of 40 paid, the other 18 lost to dropped connections,
timeouts and HTTP 408, each payment after ONE send whose answer never came. A stand-in devnet (every request answered,
dropped, timed out or refused with 408 by a seeded draw, per endpoint, per signature, per ask: no draw depends on which
thread asks first) runs `scripts/load_pay.py`'s cluster path twice: with 0.3.24's sending (one endpoint, one send, its
answer awaited; 408 and timeouts not taken as transient) it pays 22 of 40; through knos.settle.v2.fanout.FanLedger
(the same bytes again every 2 s, confirmed by signature status, a wider retry budget) 40 of 40, each once, alone or with
a second endpoint. No wall clock: every wait is the stand-in's."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import re
import sys
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from knos import chain
from knos.settle.v2 import fanout

ROOT = Path(__file__).resolve().parent.parent
if "knos_load_pay" in sys.modules:
    load_pay = sys.modules["knos_load_pay"]
else:
    _spec = importlib.util.spec_from_file_location("knos_load_pay", ROOT / "scripts" / "load_pay.py")
    assert _spec is not None and _spec.loader is not None
    load_pay = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = load_pay
    _spec.loader.exec_module(load_pay)

URL, SECOND = "https://api.devnet.solana.com", "https://second.devnet.invalid"
MEMO = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")
BLOCKHASH = "4sGjMW1sUnHzSxGspuhpqLDx6wiyjNtZAMdL4VZHirAn"
SEED, DROP = 20, 0.26            # the draw that gives 0.3.24's 22 of 40 with 0.3.24's sending
OLD_TRANSIENT = re.compile(r"\b429\b|too many requests|blockhash not found|block ?height exceeded|blockhash (?:has )?expired", re.I)


class Devnet:
    """Every request is answered, or (with probability DROP, by a draw on url, method, what it asks and how often it
    was asked) dropped, timed out or refused with HTTP 408. A dropped or timed-out send lands half the time: the
    answer is lost, not the transaction. Signed bytes land once; sent again, the cluster says so."""

    def __init__(self, drop: float = DROP, seed: int = SEED):
        self.lock, self.drop, self.seed = threading.Lock(), drop, seed
        self.landed: dict[str, bytes] = {}          # signature -> the memo it carried
        self.asked: dict[tuple, int] = {}
        self.failures = {"timeout": 0, "dropped": 0, "408": 0}
        self.clock = 0.0

    def draw(self, *key) -> float:
        n = self.asked[key] = self.asked.get(key, 0) + 1
        h = hashlib.sha256(repr((self.seed, n, *key)).encode()).digest()
        return int.from_bytes(h[:8], "big") / 2 ** 64

    def fail(self, roll: float, url: str) -> None:
        kind = ("timeout", "dropped", "408")[int(roll / self.drop * 3) % 3]
        self.failures[kind] += 1
        if kind == "timeout":
            raise TimeoutError("The read operation timed out")
        if kind == "dropped":
            raise urllib.error.URLError("Remote end closed connection without response")
        raise urllib.error.HTTPError(url, 408, "Request Timeout", None, None)  # type: ignore[arg-type]

    def call(self, url: str, method: str, params: list, timeout: float = 10.0):
        with self.lock:
            if method == "getLatestBlockhash":
                return {"value": {"blockhash": BLOCKHASH, "lastValidBlockHeight": 1}}
            if method == "sendTransaction":
                tx = Transaction.from_bytes(base64.b64decode(params[0]))
                sig = str(tx.signatures[0])
                roll = self.draw(url, method, sig)
                if roll < self.drop:
                    if self.draw(url, "lands", sig) < 0.5:
                        self.landed.setdefault(sig, bytes(tx.message.instructions[-1].data))
                    self.fail(roll, url)
                if sig in self.landed:
                    raise chain.RpcError("Transaction simulation failed: This transaction has already been processed")
                self.landed[sig] = bytes(tx.message.instructions[-1].data)
                return sig
            if method == "getSignatureStatuses":
                sigs = list(params[0])
                roll = self.draw(url, method, ",".join(sigs))
                if roll < self.drop:
                    self.fail(roll, url)
                return {"value": [{"confirmationStatus": "confirmed", "err": None} if s in self.landed else None for s in sigs]}
        raise AssertionError(method)

    # chain.wait_all's clock, for 0.3.24's sending: a poll's sleep moves it, nothing waits
    def monotonic(self) -> float:
        return self.clock

    def sleep(self, s: float) -> None:
        with self.lock:
            self.clock += s


def relay_one(ledger, key, kind, jwt):
    """A relay's PayOrder, as the stand-in sees it: one transaction carrying the token's digest."""
    ledger.send([Instruction(MEMO, hashlib.sha256(jwt.encode()).hexdigest().encode(), [])], key)
    return {"ok": True}


def burst(monkeypatch, ledger, seconds=(), drop: float = DROP) -> tuple[dict, Devnet]:
    from knos.settle.v2 import relay
    net = Devnet(drop)
    monkeypatch.setattr(chain, "call", net.call)
    monkeypatch.setattr(chain, "time", net)
    monkeypatch.setattr(relay, "lane", lambda jwt: jwt)
    tokens = [{"kind": "pay", "jwt": f"t{i}"} for i in range(40)]
    got = load_pay.on_cluster(None, Keypair.from_seed(bytes(32)), 4, tokens, ledger=ledger, relay_one=relay_one, lend=lambda k: True,
                              sweep=lambda k: None, scenario="burst", pause=lambda s: None, seconds=seconds)
    return got, net


class Old(chain.Ledger):
    """0.3.24's ledger: one endpoint, one send, its answer awaited (chain.Ledger itself, under another name so that
    on_cluster leaves it as it is)."""


def test_0_3_24_sending_pays_22_of_40_and_loses_the_rest_to_drops_timeouts_and_408(monkeypatch):
    monkeypatch.setattr(load_pay, "TRANSIENT", OLD_TRANSIENT)
    monkeypatch.setattr(load_pay, "BURST_ATTEMPTS", 8)
    got, net = burst(monkeypatch, Old(URL))
    assert (got["attempted"], got["paid"], got["failures"]) == (40, 22, 18) and got["ok"] is False
    assert all(n > 0 for n in net.failures.values()) and "fanout" not in got
    assert all(re.search(r"timed out|Remote end closed|HTTP Error 408|already been processed|not confirmed", w) for w in got["first_refusals"]), got["first_refusals"]


@pytest.mark.parametrize("seconds", [(), (SECOND,)])
def test_fanned_out_resent_and_confirmed_by_signature_the_burst_pays_40_of_40_once_each(monkeypatch, seconds):
    got, net = burst(monkeypatch, chain.Ledger(URL), seconds)
    assert (got["attempted"], got["paid"], got["failures"], got["ok"]) == (40, 40, 0, True), got.get("first_refusals")
    memos = list(net.landed.values())
    assert len(memos) == len(set(memos)) == 40                         # each payment landed once: one signature a payment
    fan = got["fanout"]
    assert (fan["endpoints"], fan["second_endpoints"], fan["resend_every_s"], fan["confirm_by"]) == (1 + len(seconds), len(seconds), 2.0, "getSignatureStatuses")
    assert fan["no_answer"] > 0 and fan["gives_up_after_s"] == 60.0
    assert got["backoff"]["sends_at_most"] == load_pay.BURST_ATTEMPTS == 12
    if seconds:
        assert any(k[0] == SECOND and k[1] == "sendTransaction" for k in net.asked)


def test_what_is_no_answer_and_what_is_a_refusal():
    assert fanout.no_answer(TimeoutError()) and fanout.no_answer(urllib.error.URLError("Remote end closed connection without response"))
    assert fanout.no_answer(urllib.error.HTTPError(URL, 408, "Request Timeout", None, None))  # type: ignore[arg-type]
    assert not fanout.no_answer(urllib.error.HTTPError(URL, 400, "Bad Request", None, None))  # type: ignore[arg-type]
    assert not fanout.no_answer(chain.RpcError("Transaction simulation failed: custom program error: 0x54"))
    for said in ("TimeoutError: The read operation timed out", "URLError: <urlopen error Remote end closed connection without response>",
                 "HTTPError: HTTP Error 408: Request Timeout", "HTTPError: HTTP Error 503: Service Unavailable", "TimeoutError: x not confirmed after 120 polls"):
        assert load_pay.transient(said), said
    for said in ("custom program error: 0x1771", "transaction failed: {'InstructionError': [0, {'Custom': 502}]}", "HTTPError: HTTP Error 400: Bad Request"):
        assert not load_pay.transient(said), said


def test_a_program_refusal_at_preflight_is_raised_at_once_and_never_resent(monkeypatch):
    sent = []

    def call(url, method, params, timeout=10.0):
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": BLOCKHASH}}
        sent.append((url, method))
        raise chain.RpcError("Transaction simulation failed: custom program error: 0x54")
    monkeypatch.setattr(chain, "call", call)
    led = fanout.FanLedger(URL, seconds=(SECOND,), sleep=lambda s: None)
    with pytest.raises(chain.RpcError, match="0x54"):
        led.send([Instruction(MEMO, b"x", [])], Keypair.from_seed(bytes([3]) * 32))
    assert sent == [(URL, "sendTransaction")]


def test_second_endpoints_come_from_the_environment_https_only_once_each(monkeypatch):
    monkeypatch.setenv("KNOS_RPC_SECOND", f" {SECOND}, http://plain.invalid,{SECOND},https://third.invalid ")
    assert fanout.seconds_from_env() == (SECOND, "https://third.invalid")
    monkeypatch.delenv("KNOS_RPC_SECOND")
    assert fanout.seconds_from_env() == () and fanout.FanLedger(URL).endpoints() == [URL]


def test_the_ledger_a_cluster_run_is_handed_is_a_fan_ledger_and_the_run_records_its_fan_out(monkeypatch):
    """`load.py measure --pay` hands on_cluster `chain.ledger()`, which is a FanLedger since 0.3.25, not a plain
    chain.Ledger: the burst on devnet then went out through chain.ledger()'s own fan-out with --second-rpc ignored and
    nothing of the fan-out in its record. It is made again with the run's second endpoints and its pause, and counted."""
    for name in ("KNOS_RPC", "KNOS_RPC_SECOND", "KNOS_CLUSTER"):
        monkeypatch.delenv(name, raising=False)
    handed = chain.ledger()
    assert type(handed) is fanout.FanLedger and handed.url == URL and handed.seconds == ()
    got, net = burst(monkeypatch, handed, (SECOND,))
    assert (got["attempted"], got["paid"], got["failures"], got["ok"]) == (40, 40, 0, True), got.get("first_refusals")
    fan = got["fanout"]
    assert (fan["endpoints"], fan["second_endpoints"], fan["resend_every_s"], fan["confirm_by"]) == (2, 1, 2.0, "getSignatureStatuses")
    assert fan["sends"] > 0 and fan["no_answer"] > 0 and fan["status_polls"] > 0
    assert any(k[0] == SECOND and k[1] == "sendTransaction" for k in net.asked)     # --second-rpc reached the endpoint


class Throttled:
    """An endpoint that takes every transaction at once and confirms a signature from the third time it is asked
    about, counting each request by method. `together`: the sends wait for each other, so every waiter polls at once."""

    def __init__(self, together: int = 1):
        self.lock, self.gate = threading.Lock(), threading.Barrier(together)
        self.calls: dict[str, int] = {}
        self.asked: dict[str, int] = {}
        self.largest = 0

    def call(self, url: str, method: str, params: list, timeout: float = 10.0):
        with self.lock:
            self.calls[method] = self.calls.get(method, 0) + 1
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": BLOCKHASH, "lastValidBlockHeight": 1}}
        if method == "sendTransaction":
            sig = str(Transaction.from_bytes(base64.b64decode(params[0])).signatures[0])
            self.gate.wait(timeout=30)
            return sig
        if method == "getSignatureStatuses":
            with self.lock:
                self.largest = max(self.largest, len(params[0]))
                for s in params[0]:
                    self.asked[s] = self.asked.get(s, 0) + 1
                return {"value": [{"confirmationStatus": "confirmed", "err": None} if self.asked[s] >= 3 else None for s in params[0]]}
        raise AssertionError(method)


def test_forty_waiters_share_one_status_request_a_poll_and_bytes_an_endpoint_took_are_not_sent_again(monkeypatch):
    """The first 0.3.25 burst on devnet (10 Oct 2026): each of 40 waiters asked its own status every 0.5 s and sent its
    bytes again every 2 s, about 80 requests a second of an endpoint that takes 40 of one method per 10 s; every one was
    answered 429. Now the process's waiters share one getSignatureStatuses a poll round, every signature in it, and
    bytes an endpoint took are left to that endpoint, which forwards them itself."""
    net = Throttled(together=40)
    monkeypatch.setattr(chain, "call", net.call)
    led = fanout.FanLedger(URL, sleep=lambda s: time.sleep(0.01))
    keys = [Keypair.from_seed(bytes([i + 1]) * 32) for i in range(40)]
    with ThreadPoolExecutor(max_workers=40) as pool:
        sigs = list(pool.map(lambda k: led.send([Instruction(MEMO, bytes(k.pubkey()), [])], k), keys))
    assert len(set(sigs)) == 40 and net.calls["sendTransaction"] == 40 and led.asked["resends"] == 0
    assert net.calls["getSignatureStatuses"] <= 12 and net.largest > 20, (net.calls, net.largest)      # 40 waiting each poll: 120 at least
    assert fanout.board([URL]).waiting == {} and led.taken == set()                                     # nothing kept once confirmed


def test_bytes_no_endpoint_took_are_sent_again_and_a_wait_slowed_down_ends_on_the_clock(monkeypatch):
    """A send whose answer was lost is sent again every 2 s; a status request the endpoint holds up (a 429 back-off
    inside chain.call) no longer stretches the 60 s wait: the clock ends it."""
    sent, clock = [], [0.0]

    def call(url, method, params, timeout=10.0):
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": BLOCKHASH}}
        if method == "sendTransaction":
            sent.append(url)
            raise urllib.error.URLError("Remote end closed connection without response")
        clock[0] += 15.0            # chain.call waited out 1 + 2 + 4 + 8 s of 429 before it gave up
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)  # type: ignore[arg-type]
    monkeypatch.setattr(chain, "call", call)
    led = fanout.FanLedger(URL, sleep=lambda s: None, clock=lambda: clock[0])
    with pytest.raises(TimeoutError, match="not confirmed"):
        led.send([Instruction(MEMO, b"lost", [])], Keypair.from_seed(bytes([9]) * 32))
    assert clock[0] <= fanout.POLLS * fanout.POLL_S + fanout.WAIT_SLACK_S + 15.0 and led.asked["status_polls"] < 10
    assert len(sent) >= 2 and led.asked["resends"] == 0 and led.asked["no_answer"] >= len(sent)        # sent again, never taken
