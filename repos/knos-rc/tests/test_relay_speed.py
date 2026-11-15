"""What 0.3.18 adds to the relay's queue (knos.settle.v2.relayq) and its sweep (knos.proof.ghrelay): notes that two
runners merge by key and neither drains for the other, new comments read while a slow confirmation is pending, and
several fee payers. Every clock here is the test's; where two threads must meet they meet on an event, never on a
sleep; the chain is a stand-in that takes a token once."""
from __future__ import annotations

import itertools
import json
import threading
import time

import pytest
from solders.keypair import Keypair

from test_worker import fund_aud, jwt

from knos.proof import ghrelay
from knos.settle.v2 import relayq

T0 = 1_791_021_600.0
TERMS = '{"accept":"","checks":[{"app":15368,"name":"test"}],"deny":[".github/**",".knos/**"],"mode":"merge","paths":[],"reserve":7,"v":1}'
SOON = 10               # seconds a thread waits for another before the test fails (never reached when the code is right)


def _runner(tmp_path, name: str, clock, **kw) -> relayq.Queue:
    """One run of the relay: a journal of its own, and the notes folder both share."""
    return relayq.Queue(tmp_path / f"{name}.json", lambda: clock[0], notes=relayq.Notes(tmp_path / "notes", name, lambda: clock[0]), **kw)


# ---- the merge -------------------------------------------------------------------------------------------------------------

def test_notes_merge_by_key_with_one_precedence_and_a_runner_speaks_last_for_itself(tmp_path):
    clock = [T0]
    a, b = (relayq.Notes(tmp_path / "n", name, lambda: clock[0]) for name in ("sweep-1", "event-2"))
    assert a.merged() == {} and a.theirs("k") is None
    a.append("k", "waiting", id="ab")
    assert b.merged()["k"] == {"t": T0, "id": "ab", "state": "waiting", "by": "sweep-1"} and b.theirs("k")["by"] == "sweep-1" and a.theirs("k") is None
    # confirmed > refused > sending > waiting, whoever spoke first or last
    clock[0] += 1
    assert b.lease("k", until=clock[0] + 180) is True and a.merged()["k"]["state"] == "sending" and a.merged()["k"]["by"] == "event-2"
    clock[0] += 1
    a.append("k", "waiting")                                    # a later word of lower rank changes nothing
    assert a.merged()["k"]["by"] == "event-2" and a.theirs("k")["state"] == "sending"
    b.append("k", "refused", why="no open bounty for this issue")
    assert a.merged()["k"]["state"] == "refused" and a.merged()["k"]["why"] == "no open bounty for this issue"
    a.append("k", "confirmed")                                  # the chain has it: true whoever says it, and it stands over a refusal
    assert b.merged()["k"]["state"] == "confirmed" and b.merged()["k"]["by"] == "sweep-1"
    # within one runner its last line is its word: sending, then waiting again (a try that may clear)
    assert a.lease("j", until=clock[0] + 180) and a.merged()["j"]["state"] == "sending"
    a.append("j", "waiting")
    assert b.merged()["j"]["state"] == "waiting"
    # a lease past its time is read as waiting: its runner is gone, or late
    assert b.lease("m", until=clock[0] + 180) and a.theirs("m")["state"] == "sending"
    clock[0] += 181
    assert a.theirs("m")["state"] == "waiting"
    # only the runner that leased a token writes its refusal; and after its own answer a runner says nothing more of it
    with pytest.raises(relayq.NotMine, match="did not lease"):
        a.append("m", "refused", why="mine to say? no")
    with pytest.raises(ValueError):
        a.append("m", "paid")
    size = a.file.stat().st_size
    a.append("k", "waiting")
    assert a.file.stat().st_size == size and b.merged()["k"]["state"] == "confirmed"
    # a line a killed writer left half written is no line; what was whole before it still counts
    with open(b.file, "ab") as f:
        f.write(b'{"k":"m","s":"confir')
    fresh = relayq.Notes(tmp_path / "n", "reader", lambda: clock[0])
    assert fresh.merged()["m"]["state"] == "waiting" and fresh.merged()["k"]["state"] == "confirmed"
    # each runner has a file of its own, every line is JSON, and a repository an event run read is told to the sweep
    b2 = relayq.Notes(tmp_path / "n2", "event-9", lambda: clock[0])
    b2.repo("o/r")
    b2.repo("o/r")
    assert relayq.Notes(tmp_path / "n2", "sweep-1", lambda: clock[0]).repos() == {"o/r"} and len(b2.file.read_text(encoding="utf-8").splitlines()) == 1
    assert sorted(p.name for p in (tmp_path / "n").iterdir()) == ["event-2.jsonl", "sweep-1.jsonl"]
    assert all(json.loads(ln)["k"] for ln in a.file.read_text(encoding="utf-8").splitlines())


def test_two_runners_that_lease_in_the_same_instant_one_holds_and_the_other_yields(tmp_path):
    clock = [T0]
    a, b = (relayq.Notes(tmp_path / "n", name, lambda: clock[0]) for name in ("sweep-1", "event-2"))
    a.append("k", "sending", until=T0 + 180)                    # both lines are in before either reads back
    b.append("k", "sending", until=T0 + 180)
    assert [a.lease("k", T0 + 180), b.lease("k", T0 + 180)] == [False, True]     # the same instant: the name decides, the same for both
    assert a.merged()["k"]["by"] == "event-2" and a.mine("k")["s"] == "waiting" and a.mine("k")["yielded"] == "event-2"
    clock[0] += 5                                               # an earlier lease holds against a later one
    assert a.lease("j", T0 + 185) is True
    clock[0] += 1
    assert b.lease("j", T0 + 186) is False and b.merged()["j"]["by"] == "sweep-1"


def test_old_notes_of_runners_long_gone_are_dropped_and_never_this_runners_own(tmp_path):
    clock = [T0]
    a, b = (relayq.Notes(tmp_path / "n", name, lambda: clock[0]) for name in ("sweep-1", "event-2"))
    a.append("k", "waiting")
    b.append("k", "confirmed")
    clock[0] += relayq.NOTES_KEEP - 1
    assert a.prune() == 0
    clock[0] += 2
    assert b.prune() == 1 and not a.file.exists() and b.file.exists() and b.prune() == 0 and b.merged()["k"]["state"] == "confirmed"


# ---- two runners, every interleaving ------------------------------------------------------------------------------------------

def _play(tmp_path, order, answer: dict):
    """A sweep run and an event run each read the same comment, take what they may and answer what they took, their
    steps interleaved as `order` says ("s" or "e" for whose step is next). The chain takes the token once."""
    clock, sends = [T0], []
    sweep = _runner(tmp_path, "sweep-1", clock, max_tries=None, strict=False)
    event = _runner(tmp_path, "event-2", clock)
    held: dict[str, dict | None] = {}

    def steps(name: str, q: relayq.Queue):
        yield q.put("tok", "owner:77", {"jwt": "x"}, id="ab", kind="fund")
        held[name] = q.take(f"{name}:w1")
        yield held[name]
        if held[name] is not None:
            sends.append(name)
            yield q.finish("tok", f"{name}:w1", dict(answer) if len(sends) == 1 else {"ok": True, "already": True})
    runs = {"s": steps("sweep-1", sweep), "e": steps("event-2", event)}
    for who in order:
        clock[0] += 1
        next(runs[who], None)
    for run in runs.values():                                   # whatever a runner had not finished, it finishes
        for _ in run:
            pass
    for q, name in ((sweep, "sweep-1"), (event, "event-2")):   # and each makes one more pass: there is nothing left to send
        clock[0] += 1
        assert q.take(f"{name}:w2") is None
    return sweep, event, sends


@pytest.mark.parametrize("order", sorted({"".join(p) for p in itertools.permutations("ssseee")}))
def test_in_every_interleaving_of_two_runners_one_token_is_sent_once_and_both_end_with_its_answer(tmp_path, order):
    sweep, event, sends = _play(tmp_path, order, {"ok": True, "order": "O1"})
    assert len(sends) == 1, (order, sends)                      # never twice: the second runner found the first one's lease, or its answer
    merged = sweep.shared.merged()["tok"]
    assert merged["state"] == "confirmed" and merged["by"] == sends[0]
    mine, other = (sweep, event) if sends[0] == "sweep-1" else (event, sweep)
    assert mine.entries()["tok"]["state"] == "done"
    # the other runner never queued it (the answer was in the notes already), or closed its entry from the notes without a try
    theirs = other.entries().get("tok")
    assert theirs is None or (theirs["state"], theirs["by"], theirs["tries"]) == ("done", sends[0], 0)


@pytest.mark.parametrize("order", ["sseese", "eessse", "sesese", "esesse", "eeesss", "ssseee"])
def test_a_refusal_one_runner_got_closes_the_token_for_the_other_with_the_same_words(tmp_path, order):
    sweep, event, sends = _play(tmp_path, order, {"ok": False, "why": "no open bounty for this issue"})
    assert len(sends) == 1
    states = [q.entries().get("tok", {"state": "dead", "why": "no open bounty for this issue"}) for q in (sweep, event)]
    assert [e["state"] for e in states] == ["dead", "dead"] and {e["why"] for e in states} == {"no open bounty for this issue"}
    assert sweep.shared.merged()["tok"]["state"] == "refused" and sweep.shared.merged()["tok"]["by"] == sends[0]


def test_neither_runner_drains_or_gives_up_what_the_other_holds(tmp_path):
    """The 0.3.17 finding: an event run that shared the sweep's journal would carry the sweep's waiting tokens on
    its own count of tries and mark them dead. With a journal each and notes that merge, it cannot."""
    clock, sent = [T0], []
    sweep = _runner(tmp_path, "sweep-1", clock, max_tries=None, strict=False)
    event = _runner(tmp_path, "event-2", clock, max_tries=2)
    # the sweep holds two tokens: one it will try again in a minute, one in flight
    for key in ("later", "flying"):
        assert sweep.put(key, f"owner:{key}", {"jwt": key}, id=key, kind="fund")
    assert sweep.take("sweep-1:w1")["key"] == "later"
    assert sweep.finish("later", "sweep-1:w1", {"ok": False, "retry": True, "wait": 60, "why": "the cluster did not answer"}) == "queued"
    assert sweep.take("sweep-1:w1")["key"] == "flying"
    mine = sweep.shared.file.read_bytes()
    # an event run that knows nothing of them (its event named another comment) carries its own token and ends
    assert event.put("own", "owner:9", {"jwt": "own"}, id="own", kind="fund")
    out = relayq.work(event, lambda e: sent.append(e["key"]) or {"ok": True}, workers=2, idle=_bounded(event))
    assert sent == ["own"] and out["done"] == 1 and out["dead"] == 0 and out["stopped"] == 0
    assert set(event.entries()) == {"own"} and sweep.shared.file.read_bytes() == mine       # nothing of the sweep's was read into it, or written
    # an event that names the sweep's comments queues them in ITS journal; the one in flight is left alone, the waiting one it may try
    for key in ("later", "flying"):
        assert event.put(key, f"owner:{key}", {"jwt": key}, id=key, kind="fund")
    fails = []
    relayq.work(event, lambda e: fails.append(e["key"]) or {"ok": False, "retry": True, "wait": 0, "why": "the cluster did not answer"}, workers=1,
                drain=False, idle=lambda: None)
    assert fails == ["later"]                                   # `flying` is leased by the sweep: not taken, and no try counted
    assert event.entries()["flying"]["tries"] == 0 and event.entries()["flying"]["state"] == "queued"
    # the event run gives `later` up after its own two tries: that ends ITS tries, and closes nothing for the sweep
    relayq.work(event, lambda e: fails.append(e["key"]) or {"ok": False, "retry": True, "wait": 0, "why": "the cluster did not answer"}, workers=1,
                drain=False, idle=lambda: None)
    assert event.take("event-2:w9") is None and event.entries()["later"]["state"] == "dead" and event.entries()["later"]["gave_up"] is True
    assert sweep.shared.merged()["later"]["state"] == "waiting" and sweep.entries()["later"]["state"] == "queued"
    assert sweep.shared.file.read_bytes() == mine               # still not one byte of the sweep's notes changed
    clock[0] += 61
    took = sweep.take("sweep-1:w2")
    assert took["key"] == "later" and took["tries"] == 2        # the sweep's own second try, on the sweep's own time
    assert sweep.finish("later", "sweep-1:w2", {"ok": True}) == "done" and sweep.finish("flying", "sweep-1:w1", {"ok": True}) == "done"
    # and what the sweep confirmed, the event run closes from the notes without sending
    assert event.take("event-2:w9") is None and event.entries()["flying"]["state"] == "done" and event.entries()["flying"]["by"] == "sweep-1"


def test_a_runner_that_died_with_a_lease_leaves_it_to_the_other_once_the_lease_is_over(tmp_path):
    clock, chain = [T0], []
    sweep, event = _runner(tmp_path, "sweep-1", clock, max_tries=None, strict=False), _runner(tmp_path, "event-2", clock)
    for q in (sweep, event):
        assert q.put("tok", "owner:77", {"jwt": "x"}, id="ab", kind="fund")
    assert event.take("event-2:w1")["key"] == "tok"             # the event run sends, and is killed before its answer
    chain.append("event-2")
    clock[0] += relayq.LEASE - 1
    assert sweep.take("sweep-1:w1") is None                     # still the event run's
    clock[0] += 2
    assert sweep.take("sweep-1:w1")["key"] == "tok"             # the lease is over: the sweep takes it
    assert sweep.finish("tok", "sweep-1:w1", {"ok": True, "already": True}) == "done"       # the chain shows it done: sent twice, taken once
    assert sweep.shared.merged()["tok"]["state"] == "confirmed" and sweep.shared.merged()["tok"]["by"] == "sweep-1"
    # the dead run's late refusal (it comes back to life) is its own word and stands under the confirmation
    assert event.finish("tok", "event-2:w1", {"ok": False, "why": "late and wrong"}) == "dead"
    assert sweep.shared.merged()["tok"]["state"] == "confirmed"


def test_the_sweep_and_an_event_run_with_one_home_carry_one_token_once_and_the_sweep_learns_the_repository(tmp_path, monkeypatch):
    """The two as the worker runs them (`ghrelay.once`, `relayq.serve_event` with notes), on one home."""
    now = ghrelay._unix("2026-10-04T08:00:30Z")
    one = jwt(fund_aud(7), repository="o/r", repository_owner_id="77", run_id="1")
    two = jwt(fund_aud(8), repository="o/r", repository_owner_id="78", run_id="2")
    api = [{"issue_url": "https://api.github.com/repos/o/r/issues/12", "body": ghrelay.token_comment("fund", one, TERMS), "created_at": "2026-10-04T08:00:10Z",
            "user": {"login": "github-actions[bot]"}}]
    comments, sent, posted = [], [], []
    monkeypatch.setattr(ghrelay, "found", lambda repo, since: list(comments) if repo == "o/r" else [])
    monkeypatch.setattr(ghrelay, "discover", lambda since, state: set())
    monkeypatch.setattr(ghrelay, "watched", lambda ledger, state, now: set())
    monkeypatch.setattr(ghrelay, "logged", lambda since, get=None: set())
    monkeypatch.setattr(ghrelay, "post_log", posted.extend)
    monkeypatch.setattr(ghrelay, "relay_one", lambda ledger, payer, kind, token, terms=None: sent.append(ghrelay.token_id(token)) or {
        "ok": True, "kind": "fund", "sigs": ["s1"], "note": "funded"})
    monkeypatch.setattr(ghrelay, "stages", lambda *a, **k: {})
    monkeypatch.setattr(ghrelay, "_state_path", lambda: tmp_path / "ghrelay.json")
    monkeypatch.delenv("KNOS_RELAY_REPOS", raising=False)
    monkeypatch.delenv("KNOS_RELAY_KEYS", raising=False)
    monkeypatch.setenv("GITHUB_RUN_ID", "41")

    class Ledger:
        def send(self):
            return "sig"
    notes = relayq.Notes(tmp_path / "ghrelay-notes", "event-77", lambda: now)
    serve = lambda: relayq.serve_event("repository_dispatch", {"client_payload": {"repo": "o/r", "number": 12}}, Ledger(), None,  # noqa: E731
                                       tmp_path / "ghrelay.event-77.json", get=lambda path: api, post=posted.extend, clock=lambda: now,
                                       say=lambda line: None, notes=notes)
    assert ghrelay.once(Ledger(), None, now=now - 3, crank=False) == []         # the sweep is up, and has never heard of o/r
    assert serve() == 1 and sent == [ghrelay.token_id(one)] and len(posted) == 1
    comments += [ghrelay.Found("fund", 12, one, "octocat", TERMS.encode(), now - 20), ghrelay.Found("fund", 13, two, "octocat", TERMS.encode(), now - 5)]
    [line] = ghrelay.once(Ledger(), None, now=now + 3, crank=False)             # it reads o/r now (the event run said so), and carries only what is new
    assert f" {ghrelay.token_id(two)} ok " in line and sent == [ghrelay.token_id(one), ghrelay.token_id(two)]
    state = json.loads((tmp_path / "ghrelay.json").read_text(encoding="utf-8"))
    assert len(state["seen"]) == 2 and len(state["journal"]) == 1               # the event run's token: noted as answered, never queued here
    api.append({**api[0], "body": ghrelay.token_comment("fund", two, TERMS), "created_at": "2026-10-04T08:00:25Z"})
    assert serve() == 0 and len(sent) == 2 and len(posted) == 2                 # and the event that announces the sweep's token sends nothing
    assert sorted(p.name for p in (tmp_path / "ghrelay-notes").iterdir()) == ["event-77.jsonl", "sweep-41.jsonl"]


# ---- a pass does not keep new comments waiting behind its slowest token -----------------------------------------------------

def test_what_is_fed_while_a_worker_waits_is_carried_by_a_free_worker_before_the_slow_one_answers(tmp_path):
    clock, order = [T0], []
    queue = relayq.Queue(tmp_path / "q.json", lambda: clock[0], max_tries=None, strict=False)
    new_done, slow_started = threading.Event(), threading.Event()
    assert queue.put("slow", "owner:1", {"jwt": "slow"})

    def handle(entry):
        if entry["key"] == "slow":
            slow_started.set()
            assert new_done.wait(SOON), "the new entry was not carried while the slow one was pending"
        order.append(entry["key"])
        if entry["key"] == "new":
            new_done.set()
        return {"ok": True}
    fed = []

    def feed() -> int:
        assert slow_started.wait(SOON)
        if fed:
            return 0
        fed.append(queue.put("new", "owner:2", {"jwt": "new"}))
        return 1
    out = relayq.work(queue, handle, workers=2, drain=False, feed=feed, feed_every=0)
    assert order == ["new", "slow"] and out["done"] == 2 and out["stopped"] == 0 and fed == [True]
    # with no feed a pass is what it was: every entry that may leave, once, and it ends
    assert queue.put("x", "owner:3", {"jwt": "x"})
    assert relayq.work(queue, lambda e: {"ok": True}, workers=2, drain=False)["done"] == 3
    # a feed that fails is asked again and stops nobody
    assert queue.put("y", "owner:4", {"jwt": "y"})
    asked, go = [], threading.Event()

    def bad_feed() -> int:
        asked.append(1)
        if len(asked) >= 2:
            go.set()
        raise RuntimeError("GitHub did not answer")
    out = relayq.work(queue, lambda e: (go.wait(SOON), {"ok": True})[1], workers=1, drain=False, feed=bad_feed, feed_every=0)
    assert out["done"] == 4 and len(asked) >= 2


def test_a_pass_ends_when_its_workers_say_they_ended_though_their_threads_are_not_gone_yet(tmp_path, monkeypatch):
    """A worker's thread is still alive for a moment after its last word. A pass that asked Thread.is_alive() could
    see it alive then, wait out the whole feed_every for a word already said, and read again for nothing: on Python
    3.13 with four processes at once 4 to 7 passes of 200 did (tests/test_relay_failures.py took 76 s where 3.12 takes 2).
    Here every thread of the pass stays alive until it is joined, the moment made as long as it can be: the pass ends
    when its workers have said so, and never reads again."""
    class Lingering(threading.Thread):
        def is_alive(self) -> bool:
            return not getattr(self, "joined", False)

        def join(self, timeout=None) -> None:
            super().join(timeout)
            self.joined = True
    monkeypatch.setattr(threading, "Thread", Lingering)
    queue = relayq.Queue(tmp_path / "q.json", lambda: T0, max_tries=None, strict=False)
    assert queue.put("a", "owner:1", {"jwt": "a"}) and queue.put("b", "owner:2", {"jwt": "b"})
    asked = []

    def feed() -> int:                  # what a pass that waited out feed_every does next: reads again
        asked.append(1)
        return 0
    out = relayq.work(queue, lambda e: {"ok": True}, workers=4, drain=False, feed=feed, feed_every=SOON, stop=lambda: bool(asked))
    assert out["done"] == 2 and out["stopped"] == 0 and asked == []


def test_the_sweep_reads_new_comments_while_a_slow_confirmation_is_pending_and_carries_them_in_the_same_pass(tmp_path, monkeypatch):
    """0.3.17: "a pass still ends with its slowest token": a comment posted while one confirmation was awaited was
    read by the next pass, up to 60 s later. Now the pass reads again while it waits."""
    now = ghrelay._unix("2026-10-04T08:00:30Z")
    slow = jwt(fund_aud(7), repository="o/r", repository_owner_id="77", run_id="1")
    new = jwt(fund_aud(8), repository="o/r", repository_owner_id="78", run_id="2")
    comments = [ghrelay.Found("fund", 12, slow, "octocat", TERMS.encode(), now - 5)]
    sent, posted, reads, new_done = [], [], [], threading.Event()

    def relay_one(ledger, payer, kind, token, terms=None):
        if token == slow:
            comments.append(ghrelay.Found("fund", 13, new, "octocat", TERMS.encode(), now))        # posted while this confirmation is awaited
            assert new_done.wait(SOON), "the comment posted meanwhile was not read and carried in this pass"
        sent.append(ghrelay.token_id(token))
        if token == new:
            new_done.set()
        return {"ok": True, "kind": "fund", "sigs": ["s1"], "note": "funded"}
    monkeypatch.setattr(ghrelay, "found", lambda repo, since: reads.append(repo) or (list(comments) if repo == "o/r" else []))
    monkeypatch.setattr(ghrelay, "discover", lambda since, state: set())
    monkeypatch.setattr(ghrelay, "watched", lambda ledger, state, now: set())
    monkeypatch.setattr(ghrelay, "logged", lambda since, get=None: set())
    monkeypatch.setattr(ghrelay, "post_log", posted.extend)
    monkeypatch.setattr(ghrelay, "relay_one", relay_one)
    monkeypatch.setattr(ghrelay, "stages", lambda *a, **k: {})
    monkeypatch.setattr(ghrelay, "_state_path", lambda: tmp_path / "ghrelay.json")
    monkeypatch.setenv("KNOS_RELAY_REPOS", "o/r")
    monkeypatch.setenv("KNOS_RELAY_REREAD", "0")
    monkeypatch.delenv("KNOS_RELAY_KEYS", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)

    class Ledger:
        def send(self):
            return "sig"
    lines = ghrelay.once(Ledger(), None, now=now, crank=False)
    assert sent == [ghrelay.token_id(new), ghrelay.token_id(slow)]             # the new one was on the chain before the slow one confirmed
    assert len(lines) == 2 and posted == lines and reads.count("o/r") >= 2
    state = json.loads((tmp_path / "ghrelay.json").read_text(encoding="utf-8"))
    assert len(state["seen"]) == 2 and {e["state"] for e in state["journal"].values()} == {"confirmed"} and state["round"]["tokens"] == 2
    assert ghrelay.once(Ledger(), None, now=now + 3, crank=False) == [] and len(sent) == 2       # and nothing is carried twice by the pass after


# ---- several fee payers ------------------------------------------------------------------------------------------------------

class OnePerPayer:
    """A chain that refuses a second send from a fee payer that has one in flight. The first `together` sends are
    held until that many have arrived, so that they ARE in flight together; a token is taken once. A refused send
    hears its refusal when the send it ran into has landed (as a sender does: the refusal says nothing of when), so
    the try after it never meets that same send again, however the machine schedules the two threads."""

    def __init__(self, together: int):
        self.lock, self.flying, self.rejected, self.most, self.took = threading.Condition(), [], 0, 0, []
        self.meet: threading.Barrier | None = threading.Barrier(together, timeout=SOON) if together > 1 else None

    def send(self, payer, token: str) -> dict:
        with self.lock:
            clash = payer in self.flying
            self.flying.append(payer)
            self.most = max(self.most, len(self.flying))
            self.rejected += int(clash)
            meet = self.meet
        try:
            if meet is not None:
                meet.wait()
                self.meet = None
        finally:
            with self.lock:
                self.flying.remove(payer)
                self.lock.notify_all()
                landed = not clash or self.lock.wait_for(lambda: payer not in self.flying, timeout=SOON)
        assert landed, "the send this one ran into never landed"
        if clash:
            raise RuntimeError("this fee payer has a transaction in flight")
        with self.lock:
            self.took.append((token, payer))
        return {"ok": True, "kind": "fund", "sigs": ["s1"], "note": "funded"}


class Stuck(BaseException):
    """What `_bounded` raises in a worker: not an Exception, so `relayq.work` counts that worker as stopped and it ends."""


def _bounded(queue: relayq.Queue, seconds: float = 3 * SOON):
    """`idle` for `relayq.work` under a clock that stands still (the queue's): what a worker does when it may carry nothing
    yet. These tests' clock never moves, so an entry that waits for a LATER time (a third try's backoff) while
    nothing is in flight will wait for ever, and a worker with a no-op `idle` would ask the queue again without end.
    This one ends its worker instead, at once in that case and after `seconds` in any other, and `_carry` fails."""
    until = time.monotonic() + seconds

    def idle() -> None:
        waiting = [e for e in queue.entries().values() if e.get("state") in relayq.OPEN]
        if waiting and all(e["state"] == "queued" and float(e.get("not_before", 0)) > queue.clock() for e in waiting):
            raise Stuck(f"every open entry waits for a time after this clock's: {sorted((e['tries'], e.get('why')) for e in waiting)}")
        if time.monotonic() > until:
            raise Stuck(f"still waiting after {seconds} s: {queue.counts()}")
    return idle


def _lanes(pool: relayq.Payers, want: list[int]) -> list[str]:
    """Lanes (owners) whose fee payers are the ones of `want`, by index, in order."""
    found, n = [], 0
    for index in want:
        while pool.index(f"owner:{n}") != index or f"owner:{n}" in found:
            n += 1
        found.append(f"owner:{n}")
    return found


def _carry(tmp_path, monkeypatch, name: str, pool: relayq.Payers, lanes: list[str], chain: OnePerPayer, per_lane: int = 1) -> dict:
    monkeypatch.setattr(ghrelay, "relay_one", lambda ledger, payer, kind, token, terms=None: chain.send(payer, token))
    monkeypatch.setattr(ghrelay, "stages", lambda *a, **k: {})
    queue = relayq.Queue(tmp_path / f"{name}.json", lambda: T0)
    for i in range(per_lane):
        for lane in lanes:
            assert queue.put(f"{lane}/{i}", lane, {"kind": "fund", "repo": "o/r", "n": 1, "jwt": f"{lane}/{i}", "terms": None, "created": T0})
    out = relayq.work(queue, relayq.carrier(object(), pool, lambda: T0), workers=len(lanes), idle=_bounded(queue))
    assert out["stopped"] == 0, f"{name}: a worker waited for what could not come: {out} {queue.entries()}"
    return out


def test_two_sends_from_one_fee_payer_contend_and_one_payer_a_lane_removes_the_contention(tmp_path, monkeypatch):
    keys = [Keypair.from_seed(bytes([i + 1]) * 32) for i in range(4)]
    # one payer, two owners in flight together: the chain refuses the second send, and that token needs a second try
    one = relayq.Payers(keys[:1])
    chain = OnePerPayer(together=2)
    out = _carry(tmp_path, monkeypatch, "one", one, ["owner:1", "owner:2"], chain)
    assert chain.rejected == 1 and out["done"] == 2 and len(chain.took) == 2 and {p for _t, p in chain.took} == {keys[0]}
    # two payers, the two owners on one each: both in flight together, and nothing is refused
    two = relayq.Payers(keys[:2])
    lanes = _lanes(two, [0, 1])
    chain = OnePerPayer(together=2)
    out = _carry(tmp_path, monkeypatch, "two", two, lanes, chain)
    assert chain.rejected == 0 and chain.most == 2 and out["done"] == 2
    assert dict(chain.took) == {f"{lanes[0]}/0": keys[0], f"{lanes[1]}/0": keys[1]}
    # four payers, four owners, three tokens each: never a refusal, each owner always from its own payer, in the order they came
    four = relayq.Payers(keys)
    lanes = _lanes(four, [0, 1, 2, 3])
    chain = OnePerPayer(together=4)
    out = _carry(tmp_path, monkeypatch, "four", four, lanes, chain, per_lane=3)
    assert chain.rejected == 0 and out["done"] == 12 and chain.most == 4
    for i, lane in enumerate(lanes):
        mine = [(t, p) for t, p in chain.took if t.startswith(lane + "/")]
        assert [t for t, _p in mine] == [f"{lane}/{n}" for n in range(3)] and {p for _t, p in mine} == {keys[i]}
    # two owners that fall on ONE of several payers wait for each other: never two sends from one payer at once
    same = _lanes(two, [1, 1])
    chain = OnePerPayer(together=1)
    out = _carry(tmp_path, monkeypatch, "same", two, same, chain, per_lane=2)
    assert chain.rejected == 0 and out["done"] == 4 and {p for _t, p in chain.took} == {keys[1]}


def test_the_relays_fee_payers_are_read_from_the_environment_and_a_lane_keeps_its_payer(monkeypatch):
    keys = [Keypair.from_seed(bytes([i + 1]) * 32) for i in range(3)]
    assert relayq.payers(keys[0], {}).keys == [keys[0]] and len(relayq.payers(None, {})) == 1       # one today: KNOS_RELAY_KEY alone
    for text in (" ".join(str(k) for k in keys[1:]), ",\n".join(str(k) for k in keys[1:]), json.dumps([list(bytes(k)) for k in keys[1:]]),
                 json.dumps([str(k) for k in keys[1:]])):
        assert relayq.payers(keys[0], {"KNOS_RELAY_KEYS": text}).keys == keys
    assert relayq.payers(keys[0], {"KNOS_RELAY_KEYS": json.dumps(list(bytes(keys[1])))}).keys == keys[:2]      # a single key, as KNOS_RELAY_KEY writes one
    assert relayq.payers(keys[0], {"KNOS_RELAY_KEYS": f"{keys[0]} {keys[1]} {keys[1]}"}).keys == keys[:2]     # a key named twice counts once
    with pytest.raises(ValueError) as said:
        relayq.payers(keys[0], {"KNOS_RELAY_KEYS": "not-a-key"})
    assert "not-a-key" not in str(said.value) and said.value.__cause__ is None                                  # the text is never said back
    pool = relayq.Payers(keys)
    assert [pool.index("owner:77") for _ in range(3)] == [relayq.Payers(list(keys)).index("owner:77")] * 3      # the same in every run
    assert {pool.index(f"owner:{n}") for n in range(60)} == {0, 1, 2}                                           # and the owners are spread over all of them
    monkeypatch.setenv("KNOS_RELAY_KEYS", str(keys[2]))
    assert relayq.payers(keys[0]).keys == [keys[0], keys[2]]


def test_the_sweep_pays_each_lane_from_its_own_payer_and_takes_back_every_payers_rent(tmp_path, monkeypatch):
    keys = [Keypair.from_seed(bytes([i + 1]) * 32) for i in range(2)]
    pool = relayq.Payers(keys)
    owners = [lane.split(":")[1] for lane in _lanes(pool, [0, 1])]
    now = ghrelay._unix("2026-10-04T08:00:30Z")
    tokens = [jwt(fund_aud(7 + i), repository="o/r", repository_owner_id=owner, run_id=str(i)) for i, owner in enumerate(owners)]
    comments = [ghrelay.Found("fund", 12 + i, t, "octocat", TERMS.encode(), now - 5) for i, t in enumerate(tokens)]
    paid, swept = {}, []
    monkeypatch.setattr(ghrelay, "found", lambda repo, since: list(comments) if repo == "o/r" else [])
    monkeypatch.setattr(ghrelay, "discover", lambda since, state: set())
    monkeypatch.setattr(ghrelay, "watched", lambda ledger, state, now: set())
    monkeypatch.setattr(ghrelay, "logged", lambda since, get=None: set())
    monkeypatch.setattr(ghrelay, "post_log", lambda lines: None)
    monkeypatch.setattr(ghrelay, "relay_one", lambda ledger, payer, kind, token, terms=None: paid.update({token: payer}) or {
        "ok": True, "kind": "fund", "sigs": ["s1"], "note": "funded"})
    monkeypatch.setattr(ghrelay, "stages", lambda *a, **k: {})
    monkeypatch.setattr(ghrelay, "_cranks", lambda ledger, payer, others=(): swept.append((payer, list(others))) or [])
    monkeypatch.setattr(ghrelay, "_state_path", lambda: tmp_path / "ghrelay.json")
    monkeypatch.setenv("KNOS_RELAY_REPOS", "o/r")
    monkeypatch.setenv("KNOS_RELAY_KEYS", str(keys[1]))
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)

    class Ledger:
        def send(self):
            return "sig"
    assert len(ghrelay.once(Ledger(), keys[0], now=now)) == 2
    assert paid == {tokens[0]: keys[0], tokens[1]: keys[1]} and swept == [(keys[0], [keys[1]])]
