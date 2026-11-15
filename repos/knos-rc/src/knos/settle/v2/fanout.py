"""One signed transaction sent to more than one endpoint, sent again until an endpoint takes it, and confirmed by its
signature, in ONE status request for every transaction the process waits on.

In a load test on devnet (Knos 0.3.24, 9 October 2026) 22 of 40 payments were paid: the other 18 were turned away by
the public endpoint (dropped connections,
timeouts, HTTP 408), each a payment whose ONE send's answer never came. A transaction's signature is its identity: the
same signed bytes land at most once, however often and wherever they are sent. So `FanLedger` (a `knos.chain.Ledger`)

  * sends each signed transaction to the configured endpoint and to every second endpoint it is given, the first with
    preflight (a failing program still answers with its logs, and costs no fee), the others without;
  * takes a dropped connection, a timeout, HTTP 408, 429 or 5xx as no answer, never as a refusal;
  * sends the same bytes again every RESEND_EVERY polls (2 s) while NO endpoint has taken them (every send so far had
    no answer). An endpoint that took them forwards them to the leaders itself, "every two seconds until either the
    transaction is finalized or the transaction's blockhash expires" (https://solana.com/docs/advanced/retry: no
    maxRetries is given), so they are not sent to it again;
  * reads the status of every signature the process waits on at these endpoints in ONE getSignatureStatuses (BATCH a
    request), at most once a poll round whoever waits (`_Board`): forty payments at once ask one request a poll, not forty;
  * raises TimeoutError("... not confirmed ...") after POLLS polls (60 s: a blockhash is taken for about 60 to 90
    seconds, https://solana.com/docs/core/transactions/confirmation#how-does-transaction-expiration-work), or once that
    time and WAIT_SLACK_S more have passed on the clock whatever the polls, so the caller may sign again over a fresh
    blockhash.

Why the last three are so: the first load test of 0.3.25 on devnet (10 October 2026) asked each transaction's status every
0.5 s and sent its bytes again every 2 s whatever an endpoint had answered. Forty payments at once asked about 80 status
requests a second of an endpoint that takes 40 of one method per 10 seconds; it answered every one with 429, each poll
waited out `chain.call`'s back-off (up to 15 s) while the wait was counted in polls, and 11 of 40 were paid in 23
minutes before the run was stopped.

Solana publishes ONE public devnet endpoint, https://api.devnet.solana.com, rate limited to 40 requests per 10 seconds
per IP for one RPC method (https://solana.com/docs/references/clusters). No second public one is named there, so by
default there is none and the fan-out is the resend to the one endpoint; KNOS_RPC_SECOND (comma-separated URLs) names
more, e.g. a provider's devnet endpoint of the operator's own. Counted by poll, so a test's stand-in clock and
endpoints give the same answer every run; the clock only cuts short a wait whose polls the endpoint slowed down."""
from __future__ import annotations

import base64
import os
import threading
import time
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Callable

from solders.hash import Hash
from solders.keypair import Keypair

from ... import chain

POLL_S = 0.5            # between two looks at the signatures' status
RESEND_EVERY = 4        # polls: bytes no endpoint has taken are sent again every 2 s
POLLS = 120             # 60 s in all, then TimeoutError
WAIT_SLACK_S = 30.0     # and whatever the polls, at most POLLS x POLL_S + this on the clock
BATCH = 256             # signatures in one getSignatureStatuses (the method takes up to 256)
NO_ANSWER = (TimeoutError, ConnectionError, urllib.error.URLError, OSError)
NO_ANSWER_HTTP = {408, 425, 429, 500, 502, 503, 504}
LANDED_ALREADY = ("already been processed", "alreadyprocessed")


def seconds_from_env() -> tuple[str, ...]:
    """The second endpoints KNOS_RPC_SECOND names (comma-separated https URLs), in order, none twice."""
    raw = os.environ.get("KNOS_RPC_SECOND", "")
    return tuple(dict.fromkeys(u.strip() for u in raw.split(",") if u.strip().startswith("https://")))


def no_answer(why: BaseException) -> bool:
    """An error that says nothing of the transaction: the request or its answer was lost on the way."""
    if isinstance(why, urllib.error.HTTPError):
        return why.code in NO_ANSWER_HTTP
    if isinstance(why, chain.RpcError):
        text = str(why).lower()
        return "blockhash not found" in text or "node is behind" in text or "rate limit" in text
    return isinstance(why, NO_ANSWER)


class _Board:
    """Every signature this process waits on at one set of endpoints, and what they last said of each. A waiter looks
    with the round it saw last: when no round began since, it asks the endpoints itself for EVERY signature waited on
    (BATCH a request) and a round begins; when one did, or another waiter is asking right now, it reads what was heard.
    So however many wait, the endpoints are asked about once a poll round. A signature nobody waits on is forgotten."""

    def __init__(self) -> None:
        self.lock, self.asking = threading.Lock(), threading.Lock()
        self.waiting: dict[str, int] = {}
        self.said: dict[str, dict | None] = {}
        self.round = 0

    def join(self, sigs) -> int:
        with self.lock:
            for s in sigs:
                self.waiting[s] = self.waiting.get(s, 0) + 1
            return self.round

    def leave(self, sigs) -> None:
        with self.lock:
            for s in sigs:
                left = self.waiting.get(s, 0) - 1
                if left > 0:
                    self.waiting[s] = left
                else:
                    self.waiting.pop(s, None)
                    self.said.pop(s, None)

    def look(self, ask: Callable[[list[str]], list | None], seen: int) -> tuple[int, dict[str, dict | None]]:
        """(the round now, what was heard of each signature). `ask(sigs)`: their statuses, or None when no endpoint answered."""
        if self.round == seen and self.asking.acquire(blocking=False):
            try:
                with self.lock:
                    sigs = list(self.waiting)
                for i in range(0, len(sigs), BATCH):
                    part = sigs[i:i + BATCH]
                    got = ask(part)
                    if got is not None:
                        with self.lock:
                            self.said.update((s, st) for s, st in zip(part, got) if s in self.waiting)
                with self.lock:
                    self.round += 1
            finally:
                self.asking.release()
        with self.lock:
            return self.round, dict(self.said)


_BOARDS: dict[tuple[str, ...], _Board] = {}
_BOARDS_LOCK = threading.Lock()


def board(endpoints) -> _Board:
    """The one board of this process for these endpoints."""
    with _BOARDS_LOCK:
        return _BOARDS.setdefault(tuple(endpoints), _Board())


@dataclass
class FanLedger(chain.Ledger):
    """A `chain.Ledger` whose sends reach every endpoint of `seconds` too, are sent again until an endpoint takes them,
    and are confirmed by signature status on the process's one board. `sleep`: how a poll waits (a test's stand-in);
    `clock`: the seconds that bound a wait besides its polls."""
    seconds: tuple[str, ...] = field(default_factory=seconds_from_env)
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    polls: int = POLLS
    resend_every: int = RESEND_EVERY
    asked: dict = field(default_factory=lambda: {"sends": 0, "resends": 0, "no_answer": 0, "status_polls": 0})
    taken: set = field(default_factory=set)         # signatures an endpoint answered for: it forwards them itself

    def endpoints(self) -> list[str]:
        return list(dict.fromkeys([self.url, *self.seconds]))

    def _post(self, url: str, method: str, params: list) -> Any:
        return chain.call(url, method, params)

    def _send_raw(self, raw: str, first: bool) -> bool:
        """The same bytes to every endpoint; only a program's refusal at the first endpoint's preflight is raised.
        Whether an endpoint took them (answered, or said they had landed)."""
        took = False
        for n, url in enumerate(self.endpoints()):
            preflight = first and n == 0
            opts = {"encoding": "base64", "preflightCommitment": "confirmed"} if preflight else {"encoding": "base64", "skipPreflight": True}
            try:
                self._post(url, "sendTransaction", [raw, opts])
            except Exception as why:  # noqa: BLE001 - sorted below: no answer, landed already, or the program's own refusal
                text = str(why).lower()
                if any(m in text or m in text.replace(" ", "") for m in LANDED_ALREADY):
                    took = True     # these bytes landed: an earlier send, or another endpoint's
                    continue
                if no_answer(why):
                    self.asked["no_answer"] += 1
                    continue
                if preflight:
                    raise
            took = True
            self.asked["sends" if first else "resends"] += 1
        return took

    def _statuses(self, sigs: list[str]) -> list[dict | None] | None:
        """Each signature's status from the first endpoint that answers; None when none did."""
        for url in self.endpoints():
            try:
                self.asked["status_polls"] += 1
                return list(self._post(url, "getSignatureStatuses", [sigs])["value"])
            except Exception as why:  # noqa: BLE001
                if not no_answer(why):
                    raise
                self.asked["no_answer"] += 1
        return None

    def _confirm(self, raws: dict[str, str]) -> None:
        """Polls the board until every signature of `raws` is at this ledger's commitment, sending again every
        `resend_every` polls the ones no endpoint has taken. RpcError for one that failed on chain; TimeoutError for
        one never confirmed."""
        good = ("finalized",) if self.commitment == "finalized" else ("confirmed", "finalized")
        shared = board(self.endpoints())
        seen = shared.join(raws)
        began = self.clock()
        end = began + self.polls * POLL_S + WAIT_SLACK_S
        done: dict[str, dict] = {}
        n = 0
        try:
            for n in range(1, self.polls + 1):
                # a poll waits first: a waiter asks only when no round began while it slept, so one that has just
                # joined starts no round of its own and rounds come at most once a poll, however many wait
                self.sleep(POLL_S)
                seen, said = shared.look(self._statuses, seen)
                for sig in raws:
                    status = said.get(sig)
                    if sig not in done and status and status.get("confirmationStatus") in good:
                        done[sig] = status
                failed = next((done[s] for s in raws if s in done and done[s].get("err")), None)
                if failed is not None:
                    raise chain.RpcError(f"transaction failed: {failed['err']}", failed)
                if len(done) == len(raws) or self.clock() > end:
                    break
                if n % self.resend_every == 0:
                    for sig in raws:
                        if sig not in done and sig not in self.taken and self._send_raw(raws[sig], first=False):
                            self.taken.add(sig)
        finally:
            shared.leave(raws)
            self.taken.difference_update(raws)
        if len(done) < len(raws):
            lost = next(s for s in raws if s not in done)
            raise TimeoutError(f"{lost} not confirmed after {n} polls ({self.clock() - began:.0f} s on the clock), sent to {len(self.endpoints())} endpoint(s)")

    def _blockhash(self):
        last: BaseException | None = None
        for url in self.endpoints():
            try:
                return Hash.from_string(self._post(url, "getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"])
            except Exception as why:  # noqa: BLE001
                if not no_answer(why):
                    raise
                last = why
        raise TimeoutError(f"no endpoint gave a blockhash: {last}")

    def _submit(self, tx) -> str:
        raw = base64.b64encode(bytes(tx)).decode()
        sig = str(tx.signatures[0])
        if self._send_raw(raw, first=True):
            self.taken.add(sig)
        return sig

    def send(self, ixs, payer: Keypair, signers: list[Keypair] | None = None, v1: bool = False) -> str:
        tx = chain.sign(ixs, payer, signers, self._blockhash(), v1)
        sig = self._submit(tx)
        self._confirm({sig: base64.b64encode(bytes(tx)).decode()})
        return sig

    def send_all(self, groups, payer: Keypair, signers: list[Keypair] | None = None, v1: bool = False) -> list[str]:
        groups = [list(g) for g in groups]
        if len(groups) < 2:
            return [self.send(g, payer, signers, v1) for g in groups]
        blockhash = self._blockhash()
        txs = [chain.sign(ixs, payer, signers, blockhash, v1) for ixs in groups]
        raws = {str(tx.signatures[0]): base64.b64encode(bytes(tx)).decode() for tx in txs}
        refused: BaseException | None = None
        for tx in txs:
            try:
                self._submit(tx)
            except Exception as why:  # noqa: BLE001 - raised once the others are confirmed, as chain.Ledger.send_all does
                refused = refused or why
                raws.pop(str(tx.signatures[0]), None)
        if raws:
            self._confirm(raws)
        if refused is not None:
            raise refused
        return [str(tx.signatures[0]) for tx in txs]
