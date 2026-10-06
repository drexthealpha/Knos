"""The relay's queue: the journal a relay already keeps (KNOS_HOME/ghrelay.json, `journal`), worked by several
workers at once, and the entry an event takes into it.

    python -m knos.settle.v2.relayq --event "$GITHUB_EVENT_PATH" --event-name "$GITHUB_EVENT_NAME" [--workers 4]

WHY. `knos.proof.ghrelay.once` finds tokens by reading comments on a timer. Until 0.3.16 it carried them one after
another: one token whose transaction was not confirmed for 60 s held every token behind it. This module is the
queue it carries them through now, and the entry an event takes into the same queue:

    an event        `repository_dispatch` (type knos-token) or `workflow_run` (completed) names one repository and,
                    when it can, one issue or pull request. `ingest` reads exactly that and queues what it finds.
                    The timer's pass stays as the sweep that carries what no event announced.
    a queue         every token is an entry of the journal with one of four states:
                        queued   waiting for a worker (or to be tried again, not before `not_before`)
                        leased   a worker holds it until `lease_until`; a lease nobody answered by then has expired,
                                 and the entry is taken again by whoever asks next
                        done     the chain has it (sent here, or found there already)
                        dead     it will not be sent again; `why` says the reason in plain words
                    The file is written whole or not at all, after every change. IN THE FILE the four are spelled
                    as the journal spelled them before 0.3.17 (waiting, sending, confirmed, refused or expired:
                    `SPELLED`), so the release before this one, the status comment and anything else that reads the
                    notes read them as they always did; read back, both spellings mean the same four.
    idempotent      a token sent twice does one thing once: the program takes a token a single time, and the second
                    send is answered "already". So an expired lease is simply taken again; nothing here tries to find
                    out whether the first worker had sent.
    N workers       `work` keeps N entries in flight (WORKERS, or --workers, or KNOS_RELAY_WORKERS). Two entries of
                    one lane (`knos.settle.v2.relay.lane`: the account both write) are never in flight together and
                    leave in the order they came.
    backpressure    the queue holds LIMIT open entries. `put` refuses the next one (`Full`) and says when to come
                    back; the token is still in its comment, so nothing is lost by the refusal.
    GitHub's quota  `Quota` reads `x-ratelimit-remaining`, `x-ratelimit-reset` and `retry-after` from every answer;
                    `Forge.get` asks nothing while GitHub said to stay away, and stops reading before the hour's last
                    RESERVE requests so that a verdict can still be written.

THE SWEEP IS ON THE QUEUE TOO. `knos.proof.ghrelay.once` queues what it reads and carries it with `work(...,
drain=False)`: one pass takes every entry that may leave now, each at most once, and ends; an entry to be tried again
waits for a later pass. An event run and the sweep that share a notes file therefore never both carry one token: the
second `put` of its key is refused, and a leased entry is nobody else's until its lease expires.

Two processes that write one file at the same moment can still lose each other's change (the file is replaced whole);
and two runners that each have a file of their own (the worker's event job today) know nothing of each other. In both
cases the chain's single-use rule is what keeps a second send harmless, as it does for two overlapping runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

STATES = ("queued", "leased", "done", "dead")
OPEN = ("queued", "leased")
# what the journal called its states before 0.3.17: read as these, so a relay that starts on older notes loses nothing
# (an entry in flight when the notes were written is a lease that has expired)
EARLIER = {"sending": "leased", "waiting": "queued", "confirmed": "done", "refused": "dead", "expired": "dead"}
# and what the file still calls them (a dead entry that was given up, not refused, is "expired": `gave_up`)
SPELLED = {"leased": "sending", "queued": "waiting", "done": "confirmed", "dead": "refused"}
WORKERS = 4             # entries in flight at once
LIMIT = 500             # open entries the queue holds; the next one is refused
LEASE = 180             # seconds a worker has to answer for an entry (a relay waits 60 s for one confirmation)
MAX_TRIES = 12          # times an entry is taken before it is given up (the journal's number before this module)
BACKOFF_MOST = 60       # the longest an entry is left alone between two tries, in seconds
KEEP = 2000             # entries the file keeps; the oldest closed ones go first, an open one never
PACE = 10.0             # seconds one entry is taken to need before any was timed (the relay's side of a payment: docs/RELAY.md)
RESERVE = 50            # of GitHub's hourly requests, the last ones kept for writing verdicts: nothing is read with them
REST_MOST = 3600        # the longest to stay away from GitHub because it asked (its hourly limit resets within the hour)
EVENT_TYPE = "knos-token"                           # the `repository_dispatch` type the worker listens for
LEFT_TO_SWEEP = ("verify", "withdraw", "passkey-fund")    # limited per repository per day in the sweep's notes: only the sweep queues and carries them
_REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
API = "https://api.github.com/"


class Full(RuntimeError):
    """The queue holds as many open entries as it takes. `retry_after`: seconds until it is worth asking again."""

    def __init__(self, waiting: int, limit: int, retry_after: int) -> None:
        super().__init__(f"the relay's queue is full: {waiting} tokens are waiting and it holds {limit}, because Solana or GitHub is answering "
                         f"slowly. This token was not taken and nothing is lost: it is still in its comment. Try again in {retry_after} seconds.")
        self.retry_after = retry_after


class Slow(RuntimeError):
    """GitHub is not to be asked now. `retry_after`: seconds until it may be."""

    def __init__(self, what: str, retry_after: float) -> None:
        wait = max(1, math.ceil(retry_after))
        super().__init__(f"GitHub's rate limit leaves no room to read {what} now. Try again in {wait} seconds.")
        self.retry_after = wait


def backoff(tries: int) -> int:
    """Seconds an entry is left alone after its `tries`-th failed try: 0, 0, 10, 20, ... up to BACKOFF_MOST."""
    return min(BACKOFF_MOST, max(0, tries - 2) * 10)


class Queue:
    """The journal as a queue. Every method reads the file, changes it and writes it back under one lock, so what a
    killed process leaves behind is what the next one finds."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time, limit: int = LIMIT, lease: float = LEASE,
                 workers: int = WORKERS, key: str = "journal", max_tries: int | None = MAX_TRIES, strict: bool = True) -> None:
        """`max_tries`: takes after which an entry is given up here; None when whoever carries it decides that (the
        sweep does: it tries a token for as long as the chain would take it). `strict`: an entry that waits to be
        tried again holds its lane, so nothing later of it leaves first. Without it only an entry in flight holds its
        lane: two of one lane are still never in flight together and still start in the order they came, but one
        that waits (up to an hour, in the sweep) does not keep its owner's later tokens waiting with it."""
        self.path, self.clock, self.limit, self.lease, self.workers, self.key = Path(path), clock, limit, lease, max(1, workers), key
        self.max_tries, self.strict = max_tries, strict
        self._lock = threading.Lock()

    # -- the file ----------------------------------------------------------------------------------------------------
    def _read(self) -> dict[str, Any]:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        state = state if isinstance(state, dict) else {}
        journal = state.get(self.key)
        state[self.key] = journal = journal if isinstance(journal, dict) else {}
        seq = 0
        for entry in journal.values():
            if entry.get("state") in EARLIER:
                if entry["state"] == "expired":
                    entry["gave_up"] = True
                entry["state"] = EARLIER[str(entry["state"])]
            seq = max(seq + 1, int(entry.get("seq", 0)))
            entry.setdefault("seq", seq)        # older notes have no number: the file's order is the order they came in
        return state

    def _write(self, state: dict[str, Any]) -> None:
        journal: dict[str, dict[str, Any]] = state[self.key]
        spare = len(journal) - KEEP
        if spare > 0:
            closed = [k for k, e in sorted(journal.items(), key=lambda kv: int(kv[1].get("seq", 0))) if e.get("state") not in OPEN]
            for k in closed[:spare]:
                del journal[k]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        spelled = {k: {**e, "state": "expired" if e.get("state") == "dead" and e.get("gave_up") else SPELLED.get(str(e.get("state")), e.get("state"))}
                   for k, e in journal.items()}
        tmp.write_text(json.dumps({**state, self.key: spelled}), encoding="utf-8")
        os.replace(tmp, self.path)

    # -- the notes beside the journal --------------------------------------------------------------------------------
    def notes(self) -> dict[str, Any]:
        """Everything the file holds beside the journal and the queue's own numbers (the sweep's notes)."""
        with self._lock:
            return {k: v for k, v in self._read().items() if k not in (self.key, "queue")}

    def note(self, change: Callable[[dict[str, Any]], None]) -> None:
        """`change(file)` under the queue's lock, then the file is written: how anything but the queue changes it."""
        with self._lock:
            state = self._read()
            journal, meta = state[self.key], state.get("queue")
            change(state)
            state[self.key] = journal                   # the journal and the queue's numbers are the queue's alone
            if meta is not None:
                state["queue"] = meta
            self._write(state)

    def release(self, owner: str) -> int:
        """Ends the leases of workers named `owner:...`: for a process that knows those workers are gone (its own,
        of a pass that was killed). Their entries are taken again by whoever asks next. Returns how many."""
        with self._lock:
            state = self._read()
            mine = [e for e in state[self.key].values() if e.get("state") == "leased" and str(e.get("worker", "")).startswith(owner + ":")]
            for e in mine:
                e["lease_until"] = 0
            if mine:
                self._write(state)
            return len(mine)

    # -- in ----------------------------------------------------------------------------------------------------------
    def put(self, key: str, lane: str, item: Mapping[str, Any], **about: Any) -> bool:
        """Queues one entry under `key`; False when the journal has that key already, whatever its state (a token is
        one entry however often it is announced). `lane`: entries of one lane leave one at a time, in the order they
        came. `item`: what a worker needs to carry it (JSON). Raises Full when the queue holds its limit."""
        with self._lock:
            state = self._read()
            journal: dict[str, dict[str, Any]] = state[self.key]
            had = journal.get(key)
            if had is not None and (had.get("state") not in OPEN or "item" in had):
                return False
            waiting = sum(1 for e in journal.values() if e.get("state") in OPEN and "item" in e)
            if waiting >= self.limit:
                pace = float((state.get("queue") or {}).get("pace") or PACE)
                raise Full(waiting, self.limit, max(5, math.ceil(pace * waiting / self.workers)))
            now = self.clock()
            if had is not None:     # open in notes an earlier release wrote, which kept no token: this is its token, found again
                had.update({**about, "state": "queued", "lane": lane, "item": dict(item), "last": now})
                for gone in ("worker", "lease_until", "taken"):
                    had.pop(gone, None)
                self._write(state)
                return True
            journal[key] = {**about, "state": "queued", "lane": lane, "item": dict(item), "tries": 0, "seen": now, "last": now,
                            "seq": 1 + max((int(e.get("seq", 0)) for e in journal.values()), default=0)}
            self._write(state)
            return True

    # -- out ---------------------------------------------------------------------------------------------------------
    def take(self, worker: str, skip: Any = (), leave: Any = ()) -> dict[str, Any] | None:
        """The oldest entry a worker may carry now, leased to `worker`; None when there is none. An entry may be
        carried when it is the first open one of its lane and it is queued with its wait over, or leased with its
        lease expired (its worker stopped without an answer). One taken `max_tries` times already is closed as dead.
        `skip`: keys not to take now (they still hold their lane: nothing later of it leaves first). `leave`: kinds
        this caller does not carry (lanes of their own). An open entry with no token (older notes) is nobody's to
        carry until its comment is read again (`put`)."""
        with self._lock:
            state = self._read()
            journal: dict[str, dict[str, Any]] = state[self.key]
            now, heads, took = self.clock(), set(), None
            for key, e in sorted(journal.items(), key=lambda kv: int(kv[1].get("seq", 0))):
                if e.get("state") not in OPEN or "item" not in e or e.get("kind") in leave or e.get("lane", key) in heads:
                    continue
                lost = e["state"] == "leased" and float(e.get("lease_until", 0)) <= now
                ready = key not in skip and (lost or (e["state"] == "queued" and float(e.get("not_before", 0)) <= now))
                if self.strict or ready or e["state"] == "leased":
                    heads.add(e.get("lane", key))           # nothing later of its lane leaves before it (strict), or while it is in flight
                if not ready:
                    continue
                if self.max_tries is not None and int(e.get("tries", 0)) >= self.max_tries:
                    said = e.get("why") or "no worker answered for it"
                    e.update(state="dead", gave_up=True, last=now, why=f"given up after {e['tries']} tries; the last one said: {said}")
                    heads.discard(e.get("lane", key))       # closed: the next of its lane may leave on this same call
                    continue
                if lost:
                    e["lost"] = int(e.get("lost", 0)) + 1   # times a worker took it and never answered
                e.update(state="leased", worker=worker, lease_until=now + self.lease, tries=int(e.get("tries", 0)) + 1, last=now, taken=now)
                took = {"key": key, **e}
                break
            self._write(state)
            return took

    def finish(self, key: str, worker: str, result: Mapping[str, Any], note: Callable[[dict[str, Any]], None] | None = None) -> str:
        """A worker's answer for an entry: `result` is a relay's ({ok, retry, wait, why, ...}). ok: done. `retry`:
        queued again, not before `wait` seconds (or `backoff`, when it names none). Anything else: dead, with the
        relay's reason (`gave_up`: it was tried until it could not be; the file calls that "expired").
        Returns the entry's state. An answer from a worker whose lease someone else now holds counts only when it
        says the token is on the chain: that is true whoever says it. `note(file)`: what else changes in the file with
        this answer, written in the same write (the sweep's own notes: an answer and its token's place in them are
        never apart). `took` (seconds from the token's comment to this answer) and `took_s` (seconds this try was in
        flight) are the worker's own measure, when its clock is not the queue's."""
        with self._lock:
            state = self._read()
            e = state[self.key].get(key)
            if e is None:
                return "dead"
            now, ok = self.clock(), bool(result.get("ok"))
            mine = e.get("state") == "leased" and e.get("worker") == worker
            if e.get("state") not in OPEN or not (mine or ok):
                return str(e.get("state"))
            why = " ".join(str(result.get("why") or "").split())[:300] or None
            if ok:
                e.update(state="done", why=None, order=str(result.get("order") or result.get("job") or "") or None)
            elif result.get("retry"):
                wait = float(backoff(int(e.get("tries", 0))) if result.get("wait") is None else result["wait"])
                e.update(state="queued", why=why, not_before=now + wait)
            else:
                e.update(state="dead", why=why or "the relay refused it and gave no reason")
                if result.get("gave_up"):
                    e["gave_up"] = True
            took = max(0.0, float(result["took_s"]) if result.get("took_s") is not None else now - float(e.get("taken", now)))
            meta = state.setdefault("queue", {})        # how long one entry takes, lately: what `Full` reckons its wait from
            meta["pace"] = round(0.8 * float(meta.get("pace") or took) + 0.2 * took, 3)
            e.update(last=now, took=round(float(result["took"]) if result.get("took") is not None else now - float(e.get("seen", now))))
            for gone in ("worker", "lease_until", "taken"):
                e.pop(gone, None)
            if note is not None:
                journal, meta = state[self.key], state["queue"]
                note(state)
                state[self.key], state["queue"] = journal, meta
            self._write(state)
            return str(e["state"])

    # -- seen --------------------------------------------------------------------------------------------------------
    def entries(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._read()[self.key])

    def counts(self) -> dict[str, int]:
        got = {s: 0 for s in STATES}
        for e in self.entries().values():
            got[str(e.get("state"))] = got.get(str(e.get("state")), 0) + 1
        return got

    def pending(self, leave: Any = ()) -> int:
        """Open entries a worker here could still carry: with their token, and of a kind not in `leave`."""
        return sum(1 for e in self.entries().values() if e.get("state") in OPEN and "item" in e and e.get("kind") not in leave)


def work(queue: Queue, handle: Callable[[dict[str, Any]], Mapping[str, Any]], workers: int = WORKERS,
         idle: Callable[[], None] | None = None, after: Callable[[dict[str, Any], Mapping[str, Any], str], None] | None = None,
         drain: bool = True, owner: str = "", leave: Any = (), stop: Callable[[], bool] | None = None,
         note: Callable[[dict[str, Any]], None] | None = None) -> dict[str, int]:
    """`workers` threads carry the queue's entries until none is open. `handle(entry)` answers as a relay does; what
    it raises is a failure that may clear (the entry is tried again). A worker that stops without answering (the
    process is killed, or `handle` raises something that is not an Exception) leaves its lease to expire. `idle()` is
    what a worker does when nothing may be carried yet (default: a fifth of a second's sleep); `after(entry, result,
    state)` hears every answer. Returns the queue's counts, and `stopped`: workers that ended without an answer.

    `drain=False` is one pass (the sweep's): every entry that may leave now is taken, each at most once, and a worker
    ends when nothing more may; what is to be tried again, or leased to someone else, is left for the next pass.
    `owner`: a name before each worker's (`owner:w1`), so that a process can end its own lost leases (`Queue.release`).
    `leave`: kinds these workers do not carry. `stop()`: true when no worker should take another entry. `note`: see
    `Queue.finish`."""
    wait = idle or (lambda: time.sleep(0.2))
    stopped = 0
    guard = threading.Lock()
    tried: set[str] = set()             # one pass: the keys taken in it

    def run(name: str) -> None:
        nonlocal stopped
        try:
            while not (stop is not None and stop()):
                # (the set itself, not a copy: a key is in it before its entry is answered, so no take after the answer misses it)
                entry = queue.take(name, skip=() if drain else tried, leave=leave) if leave or not drain else queue.take(name)
                if entry is None:
                    if not drain or not queue.pending(leave):
                        return
                    wait()
                    continue
                with guard:
                    tried.add(entry["key"])
                try:
                    result: Mapping[str, Any] = handle(entry)
                except Exception as why:  # noqa: BLE001 - whatever a relay raises says nothing about the token: tried again
                    result = {"ok": False, "retry": True, "transient": True, "why": f"{type(why).__name__}: {why}"}
                state = queue.finish(entry["key"], name, result, note) if note is not None else queue.finish(entry["key"], name, result)
                if after is not None:
                    after(entry, result, state)
        except BaseException:  # noqa: BLE001 - this worker is gone (a kill): its entry's lease expires and another takes it
            with guard:
                stopped += 1

    mark = f"{owner}:" if owner else ""
    threads = [threading.Thread(target=run, args=(f"{mark}w{i + 1}",), name=f"knos-relay-w{i + 1}") for i in range(max(1, workers))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return {**queue.counts(), "stopped": stopped}


# ---- GitHub's quota ---------------------------------------------------------------------------------------------------

class Quota:
    """What GitHub's last answer said is left of the hour: `x-ratelimit-remaining` and `x-ratelimit-reset` (on every
    answer), `retry-after` (on a 403 or 429 of its secondary limit)."""

    def __init__(self) -> None:
        self.remaining: int | None = None
        self.reset: float | None = None
        self.rest = 0.0                         # GitHub asked not to be asked again before this time

    def note(self, headers: Any, now: float, status: int = 200) -> None:
        """`headers`: an answer's, as urllib gives them or as a mapping; names are read in any case."""
        low = {str(k).lower(): str(v) for k, v in (headers.items() if headers is not None else ())}
        left, reset, after = low.get("x-ratelimit-remaining", ""), low.get("x-ratelimit-reset", ""), low.get("retry-after", "")
        if left.isdigit():
            self.remaining = int(left)
        if reset.isdigit():
            self.reset = float(reset)
        if status in (403, 429):
            wait = float(after) if after.isdigit() else (self.reset or now) - now if self.remaining == 0 else 60.0 if status == 429 else 0.0
            if wait > 0:
                self.rest = max(self.rest, now + min(wait, REST_MOST))

    def wait(self, now: float, write: bool = False) -> float:
        """Seconds to stay away before the next request; 0 when it may be made now. A read stops RESERVE requests
        before the hour is spent; a write (a verdict someone waits for) only when nothing is left."""
        rest = max(0.0, self.rest - now)
        floor = 0 if write else RESERVE
        if self.remaining is not None and self.remaining <= floor and self.reset is not None and self.reset > now:
            rest = max(rest, min(self.reset - now, REST_MOST))
        return rest


class Forge:
    """GitHub's API for the one read an event needs, with the quota read from every answer."""

    def __init__(self, urlopen: Callable[..., Any] | None = None, clock: Callable[[], float] = time.time, token: str | None = None) -> None:
        self.quota, self._open, self._clock = Quota(), urlopen or urllib.request.urlopen, clock
        self._token = token if token is not None else os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""

    def get(self, path: str) -> Any:
        left = self.quota.wait(self._clock())
        if left > 0:
            raise Slow(path, left)
        head = {"Accept": "application/vnd.github+json", "User-Agent": "knos"}
        if self._token:
            head["Authorization"] = f"Bearer {self._token}"
        try:
            with self._open(urllib.request.Request(API + path, headers=head), timeout=10) as resp:
                self.quota.note(resp.headers, self._clock())
                return json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            self.quota.note(e.headers, self._clock(), e.code)
            left = self.quota.wait(self._clock())
            if left > 0:
                raise Slow(path, left) from None
            raise RuntimeError(f"GitHub answered {e.code} for {path}") from None
        except (OSError, ValueError) as why:
            raise RuntimeError(f"GitHub did not answer for {path}: {why}") from None


# ---- an event, into the queue -----------------------------------------------------------------------------------------

def named(event_name: str, event: Mapping[str, Any]) -> tuple[str, list[int]]:
    """Where an event says a token was posted: (owner/repo, issue or pull request numbers; none: the repository's
    newest comments). `repository_dispatch` carries it in `client_payload` ({"repo": ..., "number": ...}; without
    `repo`, the repository the event is of); `workflow_run` names its repository and the pull requests of its run.
    Raises ValueError for an event that names nothing readable."""
    here = str((event.get("repository") or {}).get("full_name") or "")
    if event_name == "repository_dispatch":
        payload = event.get("client_payload") or {}
        repo, number = str(payload.get("repo") or here), str(payload.get("number") or "")
        numbers = [int(number)] if number.isdigit() and int(number) > 0 else []
    elif event_name == "workflow_run":
        run = event.get("workflow_run") or {}
        repo = str((run.get("repository") or {}).get("full_name") or here)
        numbers = sorted({int(p["number"]) for p in run.get("pull_requests") or [] if str(p.get("number", "")).isdigit()})
    else:
        raise ValueError(f"a {event_name or 'nameless'} event names no token: the worker takes repository_dispatch and workflow_run")
    if not _REPO.fullmatch(repo):
        raise ValueError(f"the event names no repository (got {repo[:60]!r})")
    return repo, numbers


def ingest(queue: Queue, event_name: str, event: Mapping[str, Any], get: Callable[[str], Any], now: float,
           lane: Callable[[str], str] | None = None) -> list[str]:
    """Reads what the event names and queues every token posted there in the last 70 minutes that the journal does
    not hold yet. Returns the keys queued. Raises Full (the queue), Slow (GitHub's quota) or ValueError (the event)."""
    from ...proof import ghrelay
    if lane is None:
        from . import relay
        lane = relay.lane
    repo, numbers = named(event_name, event)
    since = ghrelay._stamp(now - ghrelay.HORIZON)
    if numbers:
        found = [f for n in numbers for f in ghrelay.tokens(get(f"repos/{repo}/issues/{n}/comments?per_page=100&since={since}"), since)]
    else:
        found = ghrelay.found(repo, since, get)
    queued = []
    for f in sorted(found, key=lambda f: (f.created or 0.0, f[1])):
        kind, n, jwt, _who = f
        if kind in LEFT_TO_SWEEP:
            continue
        item = {"kind": kind, "repo": repo, "n": n, "jwt": jwt, "terms": f.terms.decode() if f.terms else None, "created": f.created}
        key = hashlib.sha256(f"{kind}\n{jwt}\n".encode() + (f.terms or b"")).hexdigest()[:16]      # the journal's key for a token as posted
        if queue.put(key, lane(jwt), item, id=ghrelay.token_id(jwt), kind=kind, where=f"{repo}#{n}"):
            queued.append(key)
    return queued


def carrier(ledger: Any, payer: Any, clock: Callable[[], float] = time.time) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """`handle` for `work`: one entry to the chain through `ghrelay.relay_one`, with the times of its own send noted
    on a ledger of its own (several are in flight, each with its own first send and last confirmation)."""
    from ...proof import ghrelay

    def handle(entry: dict[str, Any]) -> dict[str, Any]:
        item = entry["item"]
        timed, picked = ghrelay.Timed(ledger, clock), clock()
        terms = str(item["terms"]).encode() if item.get("terms") else None
        sent = ghrelay.relay_one(timed, payer, item["kind"], item["jwt"], terms=terms) if terms else ghrelay.relay_one(timed, payer, item["kind"], item["jwt"])
        r = dict(sent)
        done, created = clock(), item.get("created")
        if r.get("ok") and (r.get("sigs") or r.get("already")):
            parts = ghrelay.stages(item["jwt"], created, picked, done)
            if int(entry.get("tries", 1)) > 1:
                parts["tries"] = int(entry["tries"])
            r["line"] = ghrelay.log_line(item["kind"], item["repo"], int(item["n"]), item["jwt"], r,
                                         max(0, round(done - created)) if created is not None else None, parts,
                                         ghrelay.times(r, created, picked, done, timed))
        return r
    return handle


def serve_event(event_name: str, event: Mapping[str, Any], ledger: Any, payer: Any, path: Path, workers: int = WORKERS,
                get: Callable[[str], Any] | None = None, post: Callable[[list[str]], None] | None = None,
                clock: Callable[[], float] = time.time, say: Callable[[str], None] = print) -> int:
    """One event, start to end: queue what it names, carry it with `workers` workers, write the log's lines. A token
    the chain already showed done gets no line from here (whoever carried it writes its own). Returns the number of
    tokens that reached the chain here."""
    from ...proof import ghrelay
    queue = Queue(path, clock, workers=workers)
    try:
        ingest(queue, event_name, event, get or Forge(clock=clock).get, clock())
    except (Full, Slow, ValueError) as why:
        say(f"relay: {why} The relay's next sweep of the comments carries what is posted there.")
    carried = 0

    def after(entry: dict[str, Any], r: Mapping[str, Any], state: str) -> None:
        nonlocal carried
        item, line = entry["item"], None
        if state == "done" and not r.get("already") and r.get("line"):
            carried, line = carried + 1, str(r["line"])
        elif state == "dead":
            why = queue.entries().get(entry["key"], {}).get("why") or r.get("why")
            line = ghrelay.log_line(item["kind"], item["repo"], int(item["n"]), item["jwt"], {"ok": False, "why": why})
        if line:
            say(line)
            try:
                (post or ghrelay.post_log)([line])
            except Exception as why:  # noqa: BLE001 - the chain has the answer; the sweep's own line follows
                say(f"relay: the log line was not written ({why})")
    try:
        repo = named(event_name, event)[0]
        queue.note(lambda notes: notes.setdefault("repos", {}).update({repo: clock()}))      # the sweep reads this repository from now on
    except ValueError:
        pass
    work(queue, carrier(ledger, payer, clock), workers, after=after, leave=LEFT_TO_SWEEP)
    return carried


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Carry the tokens one GitHub event names, several at a time.")
    ap.add_argument("--event", type=Path, required=True, help="the event's JSON, as GitHub hands it to a job (GITHUB_EVENT_PATH)")
    ap.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", ""), help="repository_dispatch or workflow_run")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("KNOS_RELAY_WORKERS") or WORKERS), help=f"tokens in flight at once (default {WORKERS})")
    from ... import chain               # before the options are read: `--help` fails where an install lacks what a relay imports
    from ...proof import ghrelay
    from . import relay
    a = ap.parse_args(argv)
    assert callable(relay.lane)
    event = json.loads(a.event.read_text(encoding="utf-8"))
    carried = serve_event(a.event_name, event, chain.ledger(), chain.key(), ghrelay._state_path(), max(1, a.workers))
    print(f"relay: {carried} token{'' if carried == 1 else 's'} carried for this event", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
