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

SINCE 0.3.18, THREE MORE THINGS.

    notes that merge   `Notes`: a folder of append-only files, ONE PER RUNNER, a line per change, keyed by the
                       journal's key for a token. A runner appends only to its own file and keeps a journal of its
                       own, so nothing one run writes can replace, drain or close what another run holds. A reader
                       merges every file by key:
                           within one runner   its last line for a key is what it says now
                           across runners      confirmed > refused > sending > waiting
                           two `sending`       the earlier lease holds (then the runner's name): the other yields
                           a `sending` past its `until` is read as `waiting`: that lease is over
                       `confirmed` is true whoever says it (the chain has the token). `refused` is the program's or
                       the relay's final answer, and only the runner that leased the token may write it. A runner that
                       GAVE UP (its own count of tries ran out) writes `waiting` with `gave_up`: that ends its own
                       tries and nobody else's. `Queue(..., notes=...)` asks the merge before it queues or leases, and
                       appends as it goes. Two runners that share the folder never both carry one token; two that
                       cannot share one (two GitHub runners alive at once) are where they were: the chain takes it once.
    a feed             `work(..., feed=...)`: while a worker waits for a slow confirmation, the caller's `feed()` is
                       asked every `feed_every` seconds for new entries (the sweep reads the comments again), and a
                       free worker carries them. A pass no longer keeps new comments waiting behind its slowest token.
    several payers     `Payers`: N fee-paying keys (KNOS_RELAY_KEYS). A lane always pays from one key (sha256 of the
                       lane, modulo N: the same in every run, so a token tried again finds the account its first try
                       verified it in), and with more than one key a key signs for one token at a time. Two tokens in
                       flight then never pay from one fee account. With one key (the public worker today) nothing
                       changes: all workers pay from it.

SINCE 0.3.19, NOTES TWO RUNNERS BOTH SEE. An event run and the sweep are two GitHub runners: neither sees the other's
folder. `LogStore` makes the relay-log issue (the open issue labelled knos-relay, which both may write) the notes'
durable store, beside the folder:

    append             one machine line as a comment, `knos-note 1 <runner> <json>`, for the three changes another
                       runner must know (FORGE_STATES): `sending` (a lease, with its `until`), `confirmed`, `refused`.
                       Nothing is written for `waiting`, for a repository's name, or twice for one change.
    read               the comments the sweep's pass fetched anyway (the newest hundred of the log's repository,
                       a conditional request) are handed in (`take`); only a lease reads on its own, once, straight
                       after its own line, to see whether another runner's line is there first.
    the same merge     confirmed > refused > sending > waiting, and a `sending` past its `until` is `waiting`. Of two
                       `sending` the EARLIER COMMENT holds (GitHub's comment id, `at`), not the earlier clock: two
                       runners' clocks differ, the order of two comments on one issue does not. So of two runners
                       that lease one token, in any interleaving of their writes and reads, exactly one is told yes.
    when GitHub fails  the line is written to this run's folder as before and the run says, once, that its notes are
                       local until GitHub takes one again. The chain's single-use rule is then the guard, as in 0.3.18.
    said on the page   an event run that finds a token and sends nothing for it says so on its run's page, naming the
                       runner the notes say holds or answered it and the relay-log comment that says so (`passed_over`).
Only lines the log repository's own workflow account wrote on the log issue count: anyone can comment on a public issue.

SINCE 0.3.21, THE EVENT IS RECORDED FIRST, AND WORKERS ARE PARTITIONED BY ORDER.

    durable ingestion  an event run's first write, before it reads or carries anything, is one line in the relay log:
                       `knos-inbox 1 <runner> {"repo": ..., "n": [...], "t": ...}` (`LogStore.record`). The sweep reads
                       the log's comments on every pass anyway; a repository an inbox line names is read from that pass
                       on (`Notes.repos`). So an event run that dies after its first step loses nothing: the sweep's
                       polling is the backstop, not the transport. Before 0.3.21 the repository an event named was
                       written only to the event runner's own folder, which the sweep's runner never sees.
    partitions         `part_of(lane, n)`: sha256 of the lane, modulo n, the same in every process. A lane is the owner
                       of the repository a token was signed for (`relay.lane`), and every order has one owner.
                       `work(..., partition=True)`: worker i of n takes only the lanes of part i, so an order's tokens
                       always go to one worker. `Queue(..., part=(i, n))` (or KNOS_RELAY_PARTITION="i/n"): a whole
                       runner takes only part i, so runners that share no file never take the same order; the sweep,
                       which takes every part, is the backstop for a part whose runner is gone. Two workers never hold
                       one lane at once in any case (a lane leaves one entry at a time); a partition makes that hold
                       across runners and keeps an order on one worker for its whole life.
"""
from __future__ import annotations

import argparse
import contextlib
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
from typing import Any, Callable, Iterator, Mapping

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
RANK = {"waiting": 0, "sending": 1, "refused": 2, "confirmed": 3}      # the notes' precedence across runners: the highest wins
NOTES_KEEP = 3 * 3600   # a runner's notes file is dropped this long after its last line (a token is taken for at most 70 minutes)
FEED_EVERY = 3.0        # seconds between two reads for new entries while a worker is still carrying (the sweep's own pace)
_RUNNER = re.compile(r"[^A-Za-z0-9_.-]")
NOTE_MARK = "knos-note 1 "                              # a note's line in the relay log: the mark, the runner, one JSON object
INBOX_MARK = "knos-inbox 1 "                            # an event's line in the relay log, written before the event is read
FORGE_STATES = ("sending", "confirmed", "refused")      # the changes another runner must know: one comment each, and no other
LOG_LABEL, LOG_BOT = "knos-relay", "github-actions[bot]"    # knos.proof.ghrelay's: the log issue's label, and who writes in it


class NotMine(ValueError):
    """A runner tried to close a token it did not lease."""


class LogStore:
    """The relay-log issue as the notes' durable store (the module's text, "since 0.3.19"). `get(path)` and
    `send(path, data)` reach GitHub's API (the sweep hands in its conditional reader); `issue()` gives the log
    issue's number, None while there is none. `lines`: runner -> key -> its newest line read from the log, each with
    `at`, the id of the comment that carries it. `failed`: why the last write or read did not happen (None: shared)."""

    def __init__(self, repo: str, get: Callable[[str], Any], send: Callable[[str, dict[str, Any]], Any], issue: Callable[[], int | None],
                 bot: str = LOG_BOT, say: Callable[[str], None] | None = None) -> None:
        self.repo, self._get, self._send, self._issue, self.bot = repo, get, send, issue, bot
        self._say = say or (lambda words: print(words, file=sys.stderr))
        self.lines: dict[str, dict[str, dict[str, Any]]] = {}
        self.inbox: dict[str, dict[str, dict[str, Any]]] = {}   # runner -> repository -> its newest inbox line, with `at`
        self.failed: str | None = None
        self.wrote = self.asked = 0             # comments written, and reads this store made on its own
        self._lock = threading.Lock()

    @property
    def path(self) -> str:
        """The request the sweep makes on every pass for the log's repository (`ghrelay.found`): the same text, so its
        answer is reused and a read with nothing new is a 304."""
        return f"repos/{self.repo}/issues/comments?sort=created&direction=desc&per_page=100"

    def _fail(self, why: object) -> None:
        said = " ".join(str(why).split())[:200]
        if self.failed is None:
            self._say(f"relay notes: GitHub did not take or give this run's shared notes ({said}). They are local to this run until it does: "
                      "another runner does not see what this one holds, and the chain still takes a token once.")
        self.failed = said

    def _well(self) -> None:
        if self.failed is not None:
            self._say("relay notes: shared with the other runners again (the relay log took a line).")
        self.failed = None

    def take(self, comments: Any) -> int:
        """Reads notes out of comments someone fetched (the sweep's pass, or `read`). Returns how many lines were new."""
        try:
            number = self._issue()
        except Exception:  # noqa: BLE001 - which issue is the log is not known: nothing can be told to be a note
            number = None
        new = 0
        if number is None or not isinstance(comments, list):
            return 0
        with self._lock:
            for c in sorted((c for c in comments if isinstance(c, dict) and str(c.get("id", "")).isdigit()), key=lambda c: int(c["id"])):
                if (c.get("user") or {}).get("login") != self.bot or not str(c.get("issue_url") or "").endswith(f"/issues/{number}"):
                    continue
                for text in str(c.get("body") or "").splitlines():
                    if text.startswith(INBOX_MARK):
                        new += self._inbox(text[len(INBOX_MARK):], int(c["id"]))
                        continue
                    if not text.startswith(NOTE_MARK):
                        continue
                    runner, _, raw = text[len(NOTE_MARK):].partition(" ")
                    try:
                        ln = json.loads(raw)
                    except ValueError:
                        continue
                    if not (isinstance(ln, dict) and isinstance(ln.get("k"), str) and ln.get("s") in FORGE_STATES and _RUNNER.sub("-", runner) == runner and runner):
                        continue
                    had = self.lines.setdefault(runner, {}).get(ln["k"])
                    if had is None or int(had["at"]) < int(c["id"]):
                        self.lines[runner][ln["k"]] = {**ln, "at": int(c["id"])}
                        new += 1
        return new

    def _inbox(self, text: str, at: int) -> int:
        runner, _, raw = text.partition(" ")
        try:
            ln = json.loads(raw)
        except ValueError:
            return 0
        if not (isinstance(ln, dict) and isinstance(ln.get("repo"), str) and _REPO.fullmatch(ln["repo"]) and runner and _RUNNER.sub("-", runner) == runner):
            return 0
        had = self.inbox.setdefault(runner, {}).get(ln["repo"])
        if had is not None and int(had["at"]) >= at:
            return 0
        numbers = [int(n) for n in ln.get("n") or [] if isinstance(n, int) and n > 0][:50]
        self.inbox[runner][ln["repo"]] = {"repo": ln["repo"], "n": numbers, "t": ln.get("t"), "at": at}
        return 1

    def record(self, runner: str, repo: str, numbers: list[int], t: float) -> int | None:
        """The event, written down before it is read: one `knos-inbox` comment. Returns its id; None (and `failed`
        says why) when GitHub did not take it: the sweep then finds the token by polling, as before 0.3.21."""
        if not _REPO.fullmatch(repo):
            raise ValueError(f"no repository: {repo[:60]!r}")
        line = {"repo": repo, "n": sorted({int(n) for n in numbers if int(n) > 0})[:50], "t": t}
        try:
            number = self._issue()
            if number is None:
                raise RuntimeError("the relay log has no open issue yet")
            got = self._send(f"repos/{self.repo}/issues/{number}/comments", {"body": INBOX_MARK + runner + " " + json.dumps(line, separators=(",", ":"))})
            at = int(got["id"])
        except Exception as why:  # noqa: BLE001 - GitHub said no or did not answer: the sweep's polling still finds it
            self._fail(why)
            return None
        self.wrote += 1
        self._well()
        with self._lock:
            self.inbox.setdefault(runner, {})[repo] = {**line, "at": at}
        return at

    def read(self) -> bool:
        """Asks GitHub for the newest comments now (a lease does, after its own line). False when it did not answer."""
        self.asked += 1
        try:
            self.take(self._get(self.path))
        except Exception as why:  # noqa: BLE001 - GitHub did not answer: what was read before stands, and the run says so
            self._fail(why)
            return False
        return True

    def append(self, runner: str, line: Mapping[str, Any]) -> int | None:
        """One comment for one change. Returns the comment's id; None (and `failed` says why) when GitHub did not take it."""
        try:
            number = self._issue()
            if number is None:
                raise RuntimeError("the relay log has no open issue yet")
            got = self._send(f"repos/{self.repo}/issues/{number}/comments", {"body": NOTE_MARK + runner + " " + json.dumps(dict(line), separators=(",", ":"))})
            at = int(got["id"])
        except Exception as why:  # noqa: BLE001 - GitHub said no or did not answer: the line stays local
            self._fail(why)
            return None
        self.wrote += 1
        self._well()
        with self._lock:
            self.lines.setdefault(runner, {})[str(line["k"])] = {**line, "at": at}
        return at


class Notes:
    """The notes several runners share: a folder, one append-only file a runner (`<runner>.jsonl`), a JSON line a
    change. See the module's text for the merge. `runner`: this run's name, the same for all its passes. Nothing here
    replaces a file or writes to another runner's."""

    def __init__(self, folder: Path, runner: str, clock: Callable[[], float] = time.time, store: LogStore | None = None) -> None:
        """`store`: the relay-log issue, for runners that share no folder (`LogStore`). Its lines are merged with the
        folder's by the same rule; without it nothing changes."""
        self.folder, self.runner, self.clock, self.store = Path(folder), _RUNNER.sub("-", runner)[:80] or "runner", clock, store
        self._lock = threading.Lock()
        self._read: dict[str, tuple[int, dict[str, dict[str, Any]], set[str]]] = {}     # file name -> (bytes read, last line a key, repositories)

    @property
    def file(self) -> Path:
        return self.folder / f"{self.runner}.jsonl"

    def _line(self, line: dict[str, Any]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, (json.dumps(line, separators=(",", ":")) + "\n").encode())      # one write: a line is whole or absent
        finally:
            os.close(fd)

    def _all(self) -> dict[str, tuple[dict[str, dict[str, Any]], set[str]]]:
        """runner -> (its last line for each key, the repositories it named). Only what is new in a file is parsed;
        a last line with no newline yet (its writer is mid-write, or was killed) is left for the next read."""
        out: dict[str, tuple[dict[str, dict[str, Any]], set[str]]] = {}
        try:
            files = sorted(self.folder.glob("*.jsonl"))
        except OSError:
            files = []
        for f in files:
            done, last, repos = self._read.get(f.name, (0, {}, set()))
            try:
                with open(f, "rb") as fh:
                    fh.seek(done)
                    fresh = fh.read()
            except OSError:
                fresh = b""
            whole = fresh[:fresh.rfind(b"\n") + 1]
            for raw in whole.splitlines():
                try:
                    ln = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(ln, dict) and isinstance(ln.get("repo"), str):
                    repos.add(ln["repo"])
                elif isinstance(ln, dict) and isinstance(ln.get("k"), str) and ln.get("s") in RANK:
                    last[ln["k"]] = ln
            self._read[f.name] = (done + len(whole), last, repos)
            out[f.stem] = (last, repos)
        if self.store is not None:              # what the relay log holds: a runner's newer word for a key stands over its older one
            for runner, named in list(self.store.inbox.items()):       # where an event run was told to read: swept from now on
                last, repos = out.get(runner, ({}, set()))
                out[runner] = (last, repos | set(named))
            for runner, lines in list(self.store.lines.items()):
                last, repos = out.get(runner, ({}, set()))
                both = dict(last)
                for key, ln in list(lines.items()):
                    had = both.get(key)
                    if had is None or float(ln.get("t", 0)) >= float(had.get("t", 0)):
                        both[key] = ln
                out[runner] = (both, repos)
        return out

    def merged(self) -> dict[str, dict[str, Any]]:
        """key -> {state, by, t, ...}: every runner's last word for the key, merged by the precedence."""
        with self._lock:
            now = self.clock()
            best: dict[str, dict[str, Any]] = {}
            for runner, (last, _repos) in self._all().items():
                for key, ln in last.items():
                    state = str(ln["s"])
                    if state == "sending" and float(ln.get("until", 0)) <= now:
                        state = "waiting"                       # that lease is over
                    mine = {**{k: v for k, v in ln.items() if k not in ("k", "s")}, "state": state, "by": runner}
                    had = best.get(key)
                    if had is None or _beats(mine, had):
                        best[key] = mine
            return best

    def theirs(self, key: str) -> dict[str, Any] | None:
        """What the merge says of `key` when another runner said it; None when nobody did, or this runner's word stands."""
        got = self.merged().get(key)
        return got if got is not None and got["by"] != self.runner else None

    def mine(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._all().get(self.runner, ({}, set()))[0].get(key)

    def append(self, key: str, state: str, **about: Any) -> None:
        """This runner's next word for `key`. `refused` only for a token this runner leased (its last word is
        `sending`): NotMine otherwise. Nothing is appended after this runner's own `confirmed` or `refused`."""
        if state not in RANK:
            raise ValueError(f"a note's state is one of {', '.join(RANK)}")
        last = self.mine(key)
        if last is not None and last["s"] in ("confirmed", "refused"):
            return
        if state == "refused" and (last is None or last["s"] != "sending"):
            raise NotMine(f"{self.runner} did not lease {key}: only the run that holds a token may write its refusal")
        line = {"k": key, "s": state, "t": self.clock(), **{k: v for k, v in about.items() if v is not None}}
        if self.store is not None and state in FORGE_STATES:
            at = self.store.append(self.runner, {k: v for k, v in line.items() if k in ("k", "s", "t", "until", "why")})
            if at is not None:
                line["at"] = at                 # where its comment stands among the log's: what orders two leases
        self._line(line)

    def lease(self, key: str, until: float) -> bool:
        """Appends `sending` and reads back: False (and `waiting` appended) when the merge closed the key meanwhile or
        another runner's lease is earlier. Of two runners that lease in the same instant, exactly one is told True.
        With a `store` the line is a comment and the read is of the log: the earlier comment holds."""
        self.append(key, "sending", until=until)
        if self.store is not None and self.store.failed is None:
            self.store.read()
        got = self.merged().get(key)
        if got is None or got["by"] == self.runner:
            return True
        if got["state"] == "sending":
            self.append(key, "waiting", yielded=got["by"])
        return False

    def repo(self, name: str) -> None:
        """A repository a token was found in, for whoever sweeps (an event run says where it read)."""
        if name not in self.repos():
            self._line({"repo": name, "t": self.clock()})

    def repos(self) -> set[str]:
        with self._lock:
            return {r for _last, repos in self._all().values() for r in repos}

    def prune(self) -> int:
        """Drops the files of runners whose last line is older than NOTES_KEEP (never this runner's): by then every
        token they named is past the hour the chain takes it for. Returns how many."""
        gone = 0
        with self._lock:
            now = self.clock()
            for f in sorted(self.folder.glob("*.jsonl")) if self.folder.is_dir() else []:
                if f.stem == self.runner:
                    continue
                last = self._all().get(f.stem, ({}, set()))[0]
                try:
                    newest = max((float(ln.get("t", 0)) for ln in last.values()), default=f.stat().st_mtime)
                    if now - newest > NOTES_KEEP:
                        f.unlink()
                        self._read.pop(f.name, None)
                        gone += 1
                except OSError:
                    continue
        return gone


def _beats(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Whether word `a` stands over word `b` in the merge."""
    ra, rb = RANK[str(a["state"])], RANK[str(b["state"])]
    if ra != rb:
        return ra > rb
    if a["state"] == "sending" and a.get("at") is not None and b.get("at") is not None:
        return int(a["at"]) < int(b["at"])                       # two leases the relay log holds: the earlier comment, whatever the clocks say
    ta, tb = (float(a.get("t", 0)), str(a["by"])), (float(b.get("t", 0)), str(b["by"]))
    return ta < tb if a["state"] == "sending" else ta > tb       # the earlier lease holds; of anything else, the later word


class Payers:
    """The keys that pay fees. `hold(lane)` hands the lane's key for as long as one token is carried with it."""

    def __init__(self, keys: list[Any]) -> None:
        seen: dict[str, Any] = {}
        for k in keys:
            seen.setdefault(str(k.pubkey()) if hasattr(k, "pubkey") else f"id:{id(k)}", k)
        self.keys = list(seen.values()) or [None]
        self._locks = [threading.Lock() for _ in self.keys]

    def __len__(self) -> int:
        return len(self.keys)

    def index(self, lane: str) -> int:
        return int.from_bytes(hashlib.sha256(str(lane).encode()).digest()[:8], "big") % len(self.keys)

    @contextlib.contextmanager
    def hold(self, lane: str) -> Iterator[Any]:
        i = self.index(lane)
        if len(self.keys) == 1:
            yield self.keys[0]              # one key: every worker pays from it, as before
            return
        with self._locks[i]:                # several: a key signs for one token at a time
            yield self.keys[i]


def payers(first: Any = None, env: Mapping[str, str] | None = None) -> Payers:
    """The relay's fee payers: `first` (KNOS_RELAY_KEY, as `knos.chain.key` reads it), then the keys of
    KNOS_RELAY_KEYS: a JSON list of keys (each 64 numbers, or base58 text), or base58 keys separated by spaces,
    commas or new lines. A key named twice counts once. Raises ValueError for text that is neither."""
    text = ((os.environ if env is None else env).get("KNOS_RELAY_KEYS") or "").strip()
    keys = [] if first is None else [first]
    if text:
        from solders.keypair import Keypair
        try:
            if text.startswith("["):
                got = json.loads(text)
                rows = [got] if got and all(isinstance(x, int) for x in got) else got
                keys += [Keypair.from_bytes(bytes(r)) if isinstance(r, list) else Keypair.from_base58_string(str(r)) for r in rows]
            else:
                keys += [Keypair.from_base58_string(part) for part in re.split(r"[\s,;]+", text) if part]
        except Exception:  # noqa: BLE001 - whatever the text was, it is not said back: it is a key
            raise ValueError("KNOS_RELAY_KEYS is a JSON list of keys (each 64 numbers, or base58 text), or base58 keys separated by spaces or commas") from None
    return Payers(keys)


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


def part_of(lane: str, n: int) -> int:
    """The partition of `lane` (the owner an order belongs to: `relay.lane`) among `n`: sha256 of the lane, modulo n. The same in every process
    and every run, so an order's tokens always go to the same worker (and pay from the same key: `Payers.index`)."""
    return int.from_bytes(hashlib.sha256(str(lane).encode()).digest()[:8], "big") % max(1, n)


def partition(env: Mapping[str, str] | None = None) -> tuple[int, int] | None:
    """KNOS_RELAY_PARTITION="i/n": this runner takes only part i of n (0 <= i < n). None: every part (the sweep)."""
    text = ((os.environ if env is None else env).get("KNOS_RELAY_PARTITION") or "").strip()
    if not text:
        return None
    m = re.fullmatch(r"(\d+)/(\d+)", text)
    if not m or not 0 <= int(m[1]) < int(m[2]):
        raise ValueError(f"KNOS_RELAY_PARTITION is i/n with 0 <= i < n (got {text[:20]!r})")
    return int(m[1]), int(m[2])


def backoff(tries: int) -> int:
    """Seconds an entry is left alone after its `tries`-th failed try: 0, 0, 10, 20, ... up to BACKOFF_MOST."""
    return min(BACKOFF_MOST, max(0, tries - 2) * 10)


class Queue:
    """The journal as a queue. Every method reads the file, changes it and writes it back under one lock, so what a
    killed process leaves behind is what the next one finds."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time, limit: int = LIMIT, lease: float = LEASE,
                 workers: int = WORKERS, key: str = "journal", max_tries: int | None = MAX_TRIES, strict: bool = True,
                 notes: Notes | None = None, part: tuple[int, int] | None = None) -> None:
        """`max_tries`: takes after which an entry is given up here; None when whoever carries it decides that (the
        sweep does: it tries a token for as long as the chain would take it). `strict`: an entry that waits to be
        tried again holds its lane, so nothing later of it leaves first. Without it only an entry in flight holds its
        lane: two of one lane are still never in flight together and still start in the order they came, but one
        that waits (up to an hour, in the sweep) does not keep its owner's later tokens waiting with it. `notes`: what
        several runners share (`Notes`); this journal is then this runner's alone, and what another runner confirmed,
        refused or holds is read from the merge before a token is queued or leased. `part`: (i, n), this queue takes
        only the lanes of part i of n (`part_of`); None, every lane."""
        self.path, self.clock, self.limit, self.lease, self.workers, self.key = Path(path), clock, limit, lease, max(1, workers), key
        self.max_tries, self.strict, self.shared, self.part = max_tries, strict, notes, part
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
            mine = [(k, e) for k, e in state[self.key].items() if e.get("state") == "leased" and str(e.get("worker", "")).startswith(owner + ":")]
            for k, e in mine:
                e["lease_until"] = 0
                if self.shared is not None:
                    self.shared.append(k, "waiting")
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
            said = self.shared.theirs(key) if self.shared is not None else None
            if said is not None and said["state"] in ("confirmed", "refused"):
                return False                # another run has its answer: nothing to carry, and nothing of theirs is touched
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
                self._say(key, "waiting", id=about.get("id"))
                return True
            journal[key] = {**about, "state": "queued", "lane": lane, "item": dict(item), "tries": 0, "seen": now, "last": now,
                            "seq": 1 + max((int(e.get("seq", 0)) for e in journal.values()), default=0)}
            self._write(state)
            self._say(key, "waiting", id=about.get("id"))
            return True

    def _say(self, key: str, state: str, **about: Any) -> None:
        if self.shared is not None:
            self.shared.append(key, state, **about)

    # -- out ---------------------------------------------------------------------------------------------------------
    def _mine(self, lane: str, part: tuple[int, int] | None) -> bool:
        return all(p is None or part_of(lane, p[1]) == p[0] for p in (self.part, part))

    def take(self, worker: str, skip: Any = (), leave: Any = (), part: tuple[int, int] | None = None) -> dict[str, Any] | None:
        """The oldest entry a worker may carry now, leased to `worker`; None when there is none. An entry may be
        carried when it is the first open one of its lane and it is queued with its wait over, or leased with its
        lease expired (its worker stopped without an answer). One taken `max_tries` times already is closed as dead.
        `skip`: keys not to take now (they still hold their lane: nothing later of it leaves first). `leave`: kinds
        this caller does not carry (lanes of their own). An open entry with no token (older notes) is nobody's to
        carry until its comment is read again (`put`). `part`: (i, n), only lanes of part i of n (a worker's own, in
        `work(..., partition=True)`), beside the queue's own `part`."""
        with self._lock:
            state = self._read()
            journal: dict[str, dict[str, Any]] = state[self.key]
            now, heads, took = self.clock(), set(), None
            for key, e in sorted(journal.items(), key=lambda kv: int(kv[1].get("seq", 0))):
                if e.get("state") not in OPEN or "item" not in e or e.get("kind") in leave or e.get("lane", key) in heads:
                    continue
                if not self._mine(str(e.get("lane", key)), part):
                    continue                                # another worker's (or runner's) order: never taken here
                other = self.shared.theirs(key) if self.shared is not None else None
                if other is not None and other["state"] != "waiting":
                    if other["state"] == "sending":
                        heads.add(e.get("lane", key))       # in flight in another run: its lane waits, and this is no try of ours
                        continue
                    # another run has the answer: this runner's own entry is closed with it, and nothing is sent
                    e.update(state="done" if other["state"] == "confirmed" else "dead", last=now, by=other["by"],
                             why=None if other["state"] == "confirmed" else str(other.get("why") or "another run of the relay had it refused"))
                    for gone in ("worker", "lease_until", "taken"):
                        e.pop(gone, None)
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
                    self._say(key, "waiting", gave_up=True)   # this run's tries are over; that closes the token for nobody else
                    heads.discard(e.get("lane", key))       # closed: the next of its lane may leave on this same call
                    continue
                if self.shared is not None and not self.shared.lease(key, now + self.lease):
                    heads.add(e.get("lane", key))           # another run leased it in this instant, first: it is theirs
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
            if self.shared is not None:
                gave_up = e["state"] == "dead" and bool(e.get("gave_up"))
                word = "confirmed" if e["state"] == "done" else "waiting" if e["state"] == "queued" or gave_up else "refused"
                try:
                    self.shared.append(key, word, why=e.get("why") if word == "refused" else None, gave_up=True if gave_up else None)
                except NotMine:
                    pass                    # its lease was never noted here (notes of an older run): the journal has the answer
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

    def pending(self, leave: Any = (), part: tuple[int, int] | None = None) -> int:
        """Open entries a worker here could still carry: with their token, of a kind not in `leave`, of its part."""
        return sum(1 for k, e in self.entries().items() if e.get("state") in OPEN and "item" in e and e.get("kind") not in leave
                   and self._mine(str(e.get("lane", k)), part))


def work(queue: Queue, handle: Callable[[dict[str, Any]], Mapping[str, Any]], workers: int = WORKERS,
         idle: Callable[[], None] | None = None, after: Callable[[dict[str, Any], Mapping[str, Any], str], None] | None = None,
         drain: bool = True, owner: str = "", leave: Any = (), stop: Callable[[], bool] | None = None,
         note: Callable[[dict[str, Any]], None] | None = None, feed: Callable[[], int] | None = None,
         feed_every: float = FEED_EVERY, partition: bool = False) -> dict[str, int]:
    """`workers` threads carry the queue's entries until none is open. `handle(entry)` answers as a relay does; what
    it raises is a failure that may clear (the entry is tried again). A worker that stops without answering (the
    process is killed, or `handle` raises something that is not an Exception) leaves its lease to expire. `idle()` is
    what a worker does when nothing may be carried yet (default: a fifth of a second's sleep); `after(entry, result,
    state)` hears every answer. Returns the queue's counts, and `stopped`: workers that ended without an answer.

    `drain=False` is one pass (the sweep's): every entry that may leave now is taken, each at most once, and a worker
    ends when nothing more may; what is to be tried again, or leased to someone else, is left for the next pass.
    `owner`: a name before each worker's (`owner:w1`), so that a process can end its own lost leases (`Queue.release`).
    `leave`: kinds these workers do not carry. `stop()`: true when no worker should take another entry. `note`: see
    `Queue.finish`.

    `feed()`: asked every `feed_every` seconds for as long as a worker is still carrying; it queues what is new and
    returns how many entries it queued. Workers that have ended are started again for them, so what arrives while
    one confirmation is awaited is carried by a free worker and not after it. What `feed` raises is its own failure:
    it is asked again.

    `partition`: worker i of N takes only the lanes of part i (`part_of`), so an order's tokens always go to the same
    worker; a worker whose part holds nothing ends (drain) when its part is empty."""
    wait = idle or (lambda: time.sleep(0.2))
    stopped = 0
    guard = threading.Lock()
    tried: set[str] = set()             # one pass: the keys taken in it

    n = max(1, workers)

    def run(name: str, i: int) -> None:
        nonlocal stopped
        mine = (i, n) if partition else None
        try:
            while not (stop is not None and stop()):
                # (the set itself, not a copy: a key is in it before its entry is answered, so no take after the answer misses it)
                if mine is not None:
                    entry = queue.take(name, skip=() if drain else tried, leave=leave, part=mine)
                else:
                    entry = queue.take(name, skip=() if drain else tried, leave=leave) if leave or not drain else queue.take(name)
                if entry is None:
                    if not drain or not (queue.pending(leave, mine) if mine is not None else queue.pending(leave)):
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
    ended = threading.Condition()

    def start(i: int) -> threading.Thread:
        def body() -> None:
            try:
                run(f"{mark}w{i + 1}", i)
            finally:
                with ended:
                    ended.notify_all()
        t = threading.Thread(target=body, name=f"knos-relay-w{i + 1}")
        t.start()
        return t

    threads = [start(i) for i in range(n)]
    while feed is not None:
        until = time.monotonic() + max(0.0, feed_every)
        with ended:                         # until the time is up, or no worker is left (each says when it ends)
            while any(t.is_alive() for t in threads) and until - time.monotonic() > 0:
                ended.wait(until - time.monotonic())
        if not any(t.is_alive() for t in threads) or (stop is not None and stop()):
            break
        try:
            fresh = int(feed() or 0)
        except Exception:  # noqa: BLE001 - a read that failed is asked again; the workers carry on
            fresh = 0
        if fresh > 0:                       # a worker that had ended (nothing was left for it) is started again
            threads = [t if t.is_alive() else start(i) for i, t in enumerate(threads)]
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
           lane: Callable[[str], str] | None = None, passed: list | None = None) -> list[str]:
    """Reads what the event names and queues every token posted there in the last 70 minutes that the journal does
    not hold yet. Returns the keys queued. Raises Full (the queue), Slow (GitHub's quota) or ValueError (the event).
    `passed`: given a list, each token found and NOT queued is added to it as (key, kind, where, token id), so that
    the run can say why it sends nothing for it (`passed_over`)."""
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
        elif passed is not None:
            passed.append((key, kind, f"{repo}#{n}", ghrelay.token_id(jwt)))
    return queued


def passed_over(queue: Queue, notes: Notes | None, key: str, kind: str, where: str, tid: str) -> str:
    """The run page's line for a token this run found and does not carry: who answered it or holds it, as the
    merged notes say (another runner's word, and the relay-log comment that carries it), or this run's own journal.
    An event run that sends nothing for a token it found says so, and why: the log's `knos-note` lines are the reason."""
    head = f"relay: {kind} {where} {tid}: not carried by this run:"
    other = notes.theirs(key) if notes is not None else None
    if other is not None:
        state = {"confirmed": "has it on chain", "refused": "had it refused", "sending": "holds it (a lease)", "waiting": "waits for it"}[str(other["state"])]
        at = f" (relay log comment {other['at']})" if other.get("at") is not None else " (its notes)"
        return f"{head} {other['by']} {state}{at}, so nothing is sent from here"
    e = queue.entries().get(key) or {}
    if e.get("by"):
        return f"{head} {e['by']} answered it while this run waited, so nothing is sent from here"
    return f"{head} this run's journal has it already ({SPELLED.get(str(e.get('state')), e.get('state'))})"


def carrier(ledger: Any, payer: Any, clock: Callable[[], float] = time.time) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """`handle` for `work`: one entry to the chain through `ghrelay.relay_one`, with the times of its own send noted
    on a ledger of its own (several are in flight, each with its own first send and last confirmation). `payer`: one
    key, or `Payers` (each lane pays from its own)."""
    from ...proof import ghrelay
    pool = payer if isinstance(payer, Payers) else Payers([payer])

    def handle(entry: dict[str, Any]) -> dict[str, Any]:
        item = entry["item"]
        picked = clock()
        terms = str(item["terms"]).encode() if item.get("terms") else None
        with pool.hold(str(entry.get("lane") or entry["key"])) as key:
            timed = ghrelay.Timed(ledger, clock)
            sent = ghrelay.relay_one(timed, key, item["kind"], item["jwt"], terms=terms) if terms else ghrelay.relay_one(timed, key, item["kind"], item["jwt"])
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
                clock: Callable[[], float] = time.time, say: Callable[[str], None] = print, notes: Notes | None = None,
                part: tuple[int, int] | None = None) -> int:
    """One event, start to end: queue what it names, carry it with `workers` workers, write the log's lines. A token
    the chain already showed done gets no line from here (whoever carried it writes its own). Returns the number of
    tokens that reached the chain here. `notes`: the notes this run shares with others (`Notes`); `path` is then this
    run's own journal, and what the sweep holds or has answered is left to the sweep. `payer`: one key or `Payers`.
    With `notes` that have a relay log, the event is recorded there first (`LogStore.record`). Workers are partitioned
    by order (`work(..., partition=True)`); `part`: this runner's own part of the orders (KNOS_RELAY_PARTITION)."""
    from ...proof import ghrelay
    queue = Queue(path, clock, workers=workers, notes=notes, part=part)
    passed: list = []
    if notes is not None and notes.store is not None:     # written down before it is read: the sweep's backstop (module text, 0.3.21)
        try:
            where, numbers = named(event_name, event)
            if notes.store.record(notes.runner, where, numbers, clock()) is None:
                say("relay: the event was not recorded in the relay log; the sweep finds its token by reading the comments.")
        except ValueError:
            pass
    try:
        mine = ingest(queue, event_name, event, get or Forge(clock=clock).get, clock(), passed=passed)
    except (Full, Slow, ValueError) as why:
        mine = []
        say(f"relay: {why} The relay's next sweep of the comments carries what is posted there.")
    for p in passed:
        say(passed_over(queue, notes, *p))
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
        queue.note(lambda file: file.setdefault("repos", {}).update({repo: clock()}))      # the sweep reads this repository from now on
        if notes is not None:
            notes.repo(repo)
    except ValueError:
        pass
    work(queue, carrier(ledger, payer, clock), workers, after=after, leave=LEFT_TO_SWEEP, partition=True)
    entries = queue.entries()
    for key in mine:                    # queued here, then closed by another runner's answer (`Queue.take`): said, as above
        e = entries.get(key) or {}
        if e.get("by"):
            say(passed_over(queue, notes, key, str(e.get("kind")), str(e.get("where")), str(e.get("id"))))
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
    # a journal of this run's own, and the notes it shares: what a sweep with the same home (or the same
    # KNOS_RELAY_NOTES folder) holds or has answered is read from the merge, and nothing of the sweep's is written
    home, me = ghrelay._state_path(), f"event-{os.environ.get('GITHUB_RUN_ID') or os.getpid()}"
    store = ghrelay.log_store()         # the relay log, where this run may write it: what the sweep's runner sees of this one
    if store is not None:
        store.read()                    # one read: what the sweep holds or has answered, before anything is queued
    shared = Notes(Path(os.environ.get("KNOS_RELAY_NOTES") or home.with_name(f"{home.stem}-notes")), me, store=store)
    carried = serve_event(a.event_name, event, chain.ledger(), payers(chain.key()), home.with_name(f"ghrelay.{me}.json"), max(1, a.workers), notes=shared,
                          part=partition())
    print(f"relay: {carried} token{'' if carried == 1 else 's'} carried for this event", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
