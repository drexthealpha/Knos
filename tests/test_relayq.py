"""The relay's queue (knos.settle.v2.relayq): the journal's four states, leases that expire, a token sent twice that
does one thing once, lanes that keep a payer's order, a full queue that says when to come back, GitHub's quota read
from its headers, an event carried start to end, and the drill of docs/LOAD.md (200 entries, 4 workers, a kill and a
slow confirmation). Every clock here is the test's; the chain is a stand-in that takes a token once."""
from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

import pytest
import yaml

from test_worker import HOME, Answer, fund_aud, jwt

from knos.proof import ghrelay
from knos.settle.v2 import relayq

ROOT = Path(__file__).resolve().parents[1]
T0 = 1_791_021_600.0        # a fixed time: nothing here reads this machine's clock


def _script(name: str):
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(f"knos_{name}_script", ROOT / "scripts" / f"{name}.py")
    mod = sys.modules[spec.name] = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


drill = _script("queue_drill")


@pytest.fixture
def q(tmp_path):
    clock = [T0]
    return relayq.Queue(tmp_path / "ghrelay.json", lambda: clock[0], limit=5), clock


def test_an_entry_is_queued_once_leased_to_one_worker_and_done_or_dead_with_its_reason(q):
    queue, clock = q
    assert queue.put("a", "payer1", {"jwt": "x"}, kind="fund") and not queue.put("a", "payer1", {"jwt": "x"})     # announced twice: one entry
    assert queue.put("b", "payer2", {"jwt": "y"})
    a = queue.take("w1")
    assert (a["key"], a["state"], a["worker"], a["tries"], a["lease_until"], a["kind"]) == ("a", "leased", "w1", 1, T0 + relayq.LEASE, "fund")
    b = queue.take("w2")
    assert b["key"] == "b" and queue.take("w3") is None and queue.counts() == {"queued": 0, "leased": 2, "done": 0, "dead": 0}
    clock[0] += 7
    assert queue.finish("a", "w1", {"ok": True, "order": "Ord1"}) == "done"
    assert queue.finish("b", "w2", {"ok": False, "why": "no open\n bounty for   this issue"}) == "dead"
    got = queue.entries()
    assert (got["a"]["state"], got["a"]["order"], got["a"]["took"], got["a"]["why"]) == ("done", "Ord1", 7, None)
    assert (got["b"]["state"], got["b"]["why"]) == ("dead", "no open bounty for this issue")                   # the reason, in the relay's words
    assert "worker" not in got["a"] and "lease_until" not in got["a"]
    assert queue.finish("b", "w2", {"ok": False, "retry": True, "why": "later"}) == "dead"                       # closed stays closed
    # the file is the queue: another process finds the same, and the notes' other keys are left as they were
    doc = json.loads(queue.path.read_text(encoding="utf-8"))
    assert set(doc["journal"]) == {"a", "b"} and relayq.Queue(queue.path, lambda: clock[0]).counts()["done"] == 1
    assert set(relayq.STATES) == {"queued", "leased", "done", "dead"}


def test_a_lease_nobody_answered_expires_and_the_entry_is_taken_again_then_given_up_with_the_reason(q):
    queue, clock = q
    queue.put("a", "payer1", {})
    assert queue.take("w1")["tries"] == 1
    clock[0] += relayq.LEASE - 1
    assert queue.take("w2") is None                                      # the lease still holds
    clock[0] += 1
    again = queue.take("w2")
    assert (again["key"], again["worker"], again["tries"], again["lost"]) == ("a", "w2", 2, 1)
    # the first worker was only slow: its late "it failed" changes nothing, its late "it is on the chain" is true whoever says it
    assert queue.finish("a", "w1", {"ok": False, "why": "refused"}) == "leased"
    assert queue.finish("a", "w1", {"ok": True}) == "done" and queue.finish("a", "w2", {"ok": True, "already": True}) == "done"
    # an entry no worker ever answers for is closed after MAX_TRIES takes, and says why
    queue.put("b", "payer1", {})
    for n in range(relayq.MAX_TRIES):
        assert queue.take(f"w{n}")["tries"] == n + 1
        clock[0] += relayq.LEASE
    assert queue.take("w") is None
    b = queue.entries()["b"]
    assert b["state"] == "dead" and b["why"] == f"given up after {relayq.MAX_TRIES} tries; the last one said: no worker answered for it"


def test_a_failure_that_may_clear_waits_its_time_and_keeps_its_place_in_its_lane(q):
    queue, clock = q
    for key, lane in (("a1", "A"), ("a2", "A"), ("b1", "B")):
        queue.put(key, lane, {})
    assert queue.take("w1")["key"] == "a1" and queue.take("w2")["key"] == "b1"      # a2 waits behind a1: one of a lane in flight
    assert queue.take("w3") is None
    assert queue.finish("a1", "w1", {"ok": False, "retry": True, "wait": 60, "why": "the faucet serves a repository once a minute"}) == "queued"
    assert queue.take("w3") is None                                      # a1 is not due, and a2 does not pass it
    clock[0] += 60
    assert queue.take("w3")["key"] == "a1" and queue.take("w1") is None
    assert queue.finish("a1", "w3", {"ok": True}) == "done" and queue.take("w1")["key"] == "a2"
    assert [relayq.backoff(n) for n in (1, 2, 3, 4, 9)] == [0, 0, 10, 20, 60]


def test_a_full_queue_refuses_the_next_token_and_says_when_to_come_back(q):
    queue, clock = q
    for i in range(5):
        queue.put(f"k{i}", f"p{i}", {})
    with pytest.raises(relayq.Full) as full:
        queue.put("k5", "p5", {})
    assert full.value.retry_after == 13 and str(full.value) == (            # 5 waiting, 10 s each, 4 workers
        "the relay's queue is full: 5 tokens are waiting and it holds 5, because Solana or GitHub is answering slowly. "
        "This token was not taken and nothing is lost: it is still in its comment. Try again in 13 seconds.")
    assert "k5" not in queue.entries() and not queue.put("k0", "p0", {})    # a token it holds already is not refused: it is there
    # the wait follows what entries took lately: a slow chain says a longer wait
    e = queue.take("w1")
    clock[0] += 100
    queue.finish(e["key"], "w1", {"ok": True})
    queue.put("k5", "p5", {})
    with pytest.raises(relayq.Full) as slow:
        queue.put("k6", "p6", {})
    assert slow.value.retry_after == 125                                 # 5 waiting x 100 s / 4 workers
    # room again once entries close
    queue.finish(queue.take("w1")["key"], "w1", {"ok": True})
    assert queue.put("k6", "p6", {})


def test_notes_written_before_the_queue_are_read_as_its_states_and_nothing_is_lost(tmp_path):
    old = {"journal": {"t1": {"state": "sending", "last": T0}, "t2": {"state": "waiting"}, "t3": {"state": "confirmed"},
                       "t4": {"state": "refused", "why": "no bounty"}, "t5": {"state": "expired"}}, "seen": ["t3"], "repos": {"o/r": T0}}
    (tmp_path / "ghrelay.json").write_text(json.dumps(old), encoding="utf-8")
    queue = relayq.Queue(tmp_path / "ghrelay.json", lambda: T0 + 1)
    assert {k: e["state"] for k, e in queue.entries().items()} == {"t1": "leased", "t2": "queued", "t3": "done", "t4": "dead", "t5": "dead"}
    # those notes kept no token, so nobody can carry t1 or t2 from them: each is taken up when its comment is read again
    assert queue.take("w1") is None and queue.pending() == 0
    assert queue.put("t3", "p", {"jwt": "x"}) is False and queue.put("t4", "p", {"jwt": "x"}) is False       # answered stays answered
    assert queue.put("t1", "p", {"jwt": "a"}, kind="fund") is True
    took = queue.take("w1")
    assert (took["key"], took["item"], took["tries"]) == ("t1", {"jwt": "a"}, 1)
    kept = json.loads(queue.path.read_text(encoding="utf-8"))
    assert kept["seen"] == ["t3"] and kept["repos"] == {"o/r": T0}        # the relay's other notes are as they were
    # and the file still says the five words it said before, so the release before this one reads what this one wrote
    assert {k: e["state"] for k, e in kept["journal"].items()} == {"t1": "sending", "t2": "waiting", "t3": "confirmed", "t4": "refused", "t5": "expired"}
    assert set(relayq.SPELLED.values()) | {"expired"} == set(relayq.EARLIER) and all(relayq.EARLIER[v] == k for k, v in relayq.SPELLED.items())


def test_a_lane_is_held_by_what_waits_only_when_the_queue_is_strict_and_one_pass_takes_an_entry_once(tmp_path):
    clock = [T0]
    strict, loose = relayq.Queue(tmp_path / "a.json", lambda: clock[0]), relayq.Queue(tmp_path / "b.json", lambda: clock[0], strict=False, max_tries=None)
    for queue in (strict, loose):
        for k in ("a1", "a2", "a3"):
            queue.put(k, "owner:a", {})
        assert queue.take("w1")["key"] == "a1" and queue.take("w2") is None          # in flight: its lane is held either way
        assert queue.finish("a1", "w1", {"ok": False, "retry": True, "wait": 0, "why": "dropped"}) == "queued"      # a wait of 0 is 0, not the backoff
    assert strict.take("w1")["key"] == "a1"                                           # strict: tried again before anything later of its lane
    assert loose.take("w1", skip={"a1"})["key"] == "a2" and loose.take("w2", skip={"a1"}) is None       # this pass had a1: the next one leaves, alone
    assert loose.finish("a2", "w1", {"ok": True}) == "done" and loose.take("w1")["key"] == "a1"         # and the oldest that may leave is first again
    # one pass (`drain=False`): each entry at most once, whatever it answers; the rest is the next pass's
    q3, calls = relayq.Queue(tmp_path / "c.json", lambda: clock[0], strict=False, max_tries=None), []
    for k in ("b1", "b2", "c1"):
        q3.put(k, f"owner:{k[0]}", {})
    end = relayq.work(q3, lambda e: calls.append(e["key"]) or {"ok": e["key"] == "c1", "retry": True, "wait": 0}, 4, drain=False, owner="sweep-1")
    assert sorted(calls) == ["b1", "b2", "c1"] and calls.index("b1") < calls.index("b2") and (end["queued"], end["done"]) == (2, 1)
    # a lease this process left behind (a killed pass) is ended by name, and nobody else's is
    q3.take("sweep-1:w1"), q3.put("d1", "owner:d", {}), q3.take("event:w1")
    assert q3.release("sweep-1") == 1
    again = q3.take("sweep-1:w2")
    assert (again["key"], again["lost"], again["tries"]) == ("b1", 1, 3)
    assert q3.take("sweep-1:w3") is None                # b2 is behind b1, which is in flight again; d1 is the event run's until its lease ends


def test_a_token_sent_twice_is_taken_once_a_worker_killed_after_its_send_pays_nobody_twice(tmp_path):
    """The queue does not try to learn whether a lost worker had sent. The entry is sent again, and the single-use rule
    answers the repeat: this is the property every expired lease relies on."""
    clock = [T0]
    queue, chain = drill.Steady(tmp_path / "q.json", lambda: clock[0]), drill.OnceChain()
    for i in range(6):
        queue.put(f"t{i}", "payer", {"i": i, "token": f"tok{i}"})
    killed = []

    def handle(entry):
        r = chain.submit(entry["item"]["token"], entry["lane"], entry["item"]["i"])
        if entry["key"] == "t2" and not killed:
            killed.append(entry["worker"])
            raise drill.Killed                      # after the send, before the answer
        return r

    def idle():                                 # time passes only while the one lease open is the killed worker's
        with queue.step:
            leased = [e for e in queue.entries().values() if e["state"] == "leased"]
            if len(leased) == 1 and leased[0]["worker"] in killed and leased[0]["item"]["i"] == 2 and leased[0]["tries"] == 1:
                clock[0] += relayq.LEASE + 1

    end = relayq.work(queue, handle, workers=3, idle=idle)
    assert end == {"queued": 0, "leased": 0, "done": 6, "dead": 0, "stopped": 1}
    assert chain.sends == {**{f"tok{i}": 1 for i in range(6)}, "tok2": 2}        # sent twice
    assert chain.took == {"payer": [0, 1, 2, 3, 4, 5]}                           # taken once, and the payer's order kept through the kill
    assert queue.entries()["t2"]["tries"] == 2 and queue.entries()["t2"]["lost"] == 1


def test_what_a_relay_raises_is_tried_again_and_a_refusal_is_dead_with_its_words(tmp_path):
    clock = [T0]
    queue = relayq.Queue(tmp_path / "q.json", lambda: clock[0])
    queue.put("a", "A", {})
    queue.put("b", "B", {})
    tries, heard = [], []

    def handle(entry):
        tries.append(entry["key"])
        if entry["key"] == "a" and tries.count("a") < 4:
            raise RuntimeError("the cluster did not answer")
        return {"ok": True} if entry["key"] == "a" else {"ok": False, "why": "the token is for the other deployment"}

    def idle():
        clock[0] += 10

    relayq.work(queue, handle, workers=1, idle=idle, after=lambda e, r, state: heard.append((e["key"], state)))       # one worker: its clock moves only while it holds nothing
    got = queue.entries()
    assert tries.count("a") == 4 and got["a"]["state"] == "done" and got["a"]["tries"] == 4
    assert (got["b"]["state"], got["b"]["why"]) == ("dead", "the token is for the other deployment")
    assert heard.count(("a", "queued")) == 3 and ("a", "done") in heard and ("b", "dead") in heard


def test_200_entries_4_workers_one_kill_one_slow_confirmation_each_handled_once_in_its_payers_order(tmp_path):
    got = drill.run(200, 4, 20, drill.SEED, tmp_path)
    assert got["ok"], got
    assert (got["done"], got["dead"], got["left_open"], got["sends"], got["sent_twice"], got["taken_by_chain"]) == (200, 0, 0, 200, 0, 200)
    assert got["out_of_order"] == 0 and got["workers_killed"] == 1 and got["taken_again"] == 1 and got["taken_again_was_the_killed_one"]
    assert got["others_went_on_while_the_slow_one_was_in_flight"] and got["lanes"] == 20
    # the page prints this run, and says what it is
    page = (ROOT / "docs" / "LOAD.md").read_text(encoding="utf-8")
    kept = json.loads((ROOT / "docs" / "load.json").read_text(encoding="utf-8"))["relay"]["queue"]
    assert kept == drill.run(200, 4, 20, drill.SEED, tmp_path / "again") == got
    assert "**This is a local test of the queue, not an end-to-end service benchmark**" in page
    assert "| Entries done | 200 of 200 |" in page and "| Entries sent twice | 0 |" in page


# ---- GitHub's quota ---------------------------------------------------------------------------------------------------

def test_the_quota_is_read_from_every_answer_and_reads_stop_before_the_hour_is_spent():
    quota = relayq.Quota()
    assert quota.wait(T0) == 0
    quota.note({"X-RateLimit-Remaining": "900", "X-RateLimit-Reset": str(int(T0) + 1800)}, T0)
    assert (quota.remaining, quota.reset, quota.wait(T0)) == (900, T0 + 1800, 0)
    quota.note({"x-ratelimit-remaining": str(relayq.RESERVE), "x-ratelimit-reset": str(int(T0) + 1800)}, T0)
    assert quota.wait(T0) == 1800 and quota.wait(T0, write=True) == 0          # the last requests are kept for verdicts
    quota.note({"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(T0) + 1800)}, T0, 403)
    assert quota.wait(T0, write=True) == 1800 and quota.wait(T0 + 1800) == 0
    after = relayq.Quota()
    after.note({"Retry-After": "75"}, T0, 403)                                  # the secondary limit names its own wait
    assert after.wait(T0) == after.wait(T0, write=True) == 75
    bare = relayq.Quota()
    bare.note({}, T0, 429)
    assert bare.wait(T0) == 60                                                  # a 429 that names nothing: a minute
    bare.note({"Retry-After": "999999"}, T0, 429)
    assert bare.wait(T0) == relayq.REST_MOST
    plain = relayq.Quota()
    plain.note({}, T0, 403)                                                     # a 403 that names no limit rests nothing
    assert plain.wait(T0) == 0


def test_the_forge_asks_nothing_while_github_said_to_stay_away_and_says_when_to_come_back():
    asked, clock, answers = [], [T0], []

    def urlopen(req, timeout=None):
        asked.append(req.full_url)
        got = answers.pop(0)
        if isinstance(got, Exception):
            raise got
        return got
    forge = relayq.Forge(urlopen, lambda: clock[0], token="t")
    ok = Answer([{"id": 1}], "e1")
    ok.headers = {"X-RateLimit-Remaining": "51", "X-RateLimit-Reset": str(int(T0) + 600)}
    last = Answer([], "e2")
    last.headers = {"X-RateLimit-Remaining": "50", "X-RateLimit-Reset": str(int(T0) + 600)}
    answers += [ok, last]
    assert forge.get("repos/o/r/issues/1/comments") == [{"id": 1}] and forge.get("repos/o/r/issues/2/comments") == []
    with pytest.raises(relayq.Slow) as slow:
        forge.get("repos/o/r/issues/3/comments")
    assert len(asked) == 2 and slow.value.retry_after == 600                    # not asked at all
    assert str(slow.value) == "GitHub's rate limit leaves no room to read repos/o/r/issues/3/comments now. Try again in 600 seconds."
    clock[0] += 600
    answers.append(urllib.error.HTTPError("u", 403, "slow down", {"Retry-After": "30"}, None))
    with pytest.raises(relayq.Slow) as again:
        forge.get("repos/o/r/issues/3/comments")
    assert again.value.retry_after == 30 and len(asked) == 3
    clock[0] += 30
    answers.append(urllib.error.HTTPError("u", 404, "gone", {}, None))
    with pytest.raises(RuntimeError, match="GitHub answered 404"):
        forge.get("repos/o/r/issues/3/comments")


# ---- an event ---------------------------------------------------------------------------------------------------------

def test_an_event_names_one_repository_and_what_it_cannot_name_is_refused():
    assert relayq.named("repository_dispatch", {"client_payload": {"repo": "o/r", "number": 12}}) == ("o/r", [12])
    assert relayq.named("repository_dispatch", {"repository": {"full_name": "me/home"}, "client_payload": {}}) == ("me/home", [])
    run = {"workflow_run": {"repository": {"full_name": "o/r"}, "pull_requests": [{"number": 9}, {"number": 7}, {"number": 9}]}}
    assert relayq.named("workflow_run", run) == ("o/r", [7, 9])
    assert relayq.named("workflow_run", {"repository": {"full_name": "o/r"}, "workflow_run": {"pull_requests": []}}) == ("o/r", [])
    for name, event in (("push", {}), ("repository_dispatch", {"client_payload": {"repo": "o/r/../x"}}), ("repository_dispatch", {"client_payload": {"repo": "$(id)"}})):
        with pytest.raises(ValueError):
            relayq.named(name, event)
    assert relayq.named("repository_dispatch", {"client_payload": {"repo": "o/r", "number": "12; rm"}}) == ("o/r", [])     # not a number: the repository's newest comments


def _comment(n: int, body: str, at: str = "2026-10-04T08:00:00Z") -> dict:
    return {"issue_url": f"https://api.github.com/repos/o/r/issues/{n}", "body": body, "created_at": at, "user": {"login": "github-actions[bot]"}}


def test_an_event_is_carried_start_to_end_exactly_what_it_names_several_at_a_time(tmp_path, monkeypatch):
    now = ghrelay._unix("2026-10-04T08:00:30Z")
    one = jwt(fund_aud(7), repository="o/r", repository_owner_id="77", run_id="1")
    two = jwt(fund_aud(8), repository="o/r", repository_owner_id="77", run_id="2")
    bad = jwt("knos2:pay:1:7:9:" + "a" * 40 + ":" + "0" * 64 + ":0:-", repository="o/r", repository_owner_id="77", run_id="3")
    terms = '{"accept":"","checks":[{"app":15368,"name":"test"}],"deny":[".github/**",".knos/**"],"mode":"merge","paths":[],"reserve":7,"v":1}'
    comments = [_comment(12, ghrelay.token_comment("fund", two, terms), "2026-10-04T08:00:20Z"),
                _comment(12, ghrelay.token_comment("fund", one, terms), "2026-10-04T08:00:10Z"),
                _comment(12, ghrelay.token_comment("proof", bad), "2026-10-04T08:00:25Z"),
                _comment(12, ghrelay.token_comment("verify", one), "2026-10-04T08:00:26Z"),            # limited per day in the sweep's notes: left to the sweep
                _comment(12, ghrelay.token_comment("fund", one, terms), "2026-10-04T05:00:00Z")]        # older than the chain would take
    asked, sent, posted, said = [], [], [], []

    def get(path):
        asked.append(path)
        if "/actions/runs/" in path:
            raise RuntimeError("not asked for here")
        return comments

    def relay_one(ledger, payer, kind, token, terms=None):
        sent.append((kind, ghrelay.token_id(token), terms))
        ledger.send()                                               # the first send and the confirmation, on this entry's own clock
        if token == bad:
            return {"ok": False, "kind": "pay", "why": "no open bounty for this issue"}
        return {"ok": True, "kind": "fund", "sigs": ["s1", "s2"], "note": "funded"}

    class Ledger:
        def send(self):
            return "sig"
    monkeypatch.setattr(ghrelay, "relay_one", relay_one)
    monkeypatch.setattr(ghrelay, "stages", lambda *a, **k: {})
    event = {"client_payload": {"repo": "o/r", "number": 12}}
    carried = relayq.serve_event("repository_dispatch", event, Ledger(), None, tmp_path / "ghrelay.json", workers=4,
                                 get=get, post=posted.extend, clock=lambda: now, say=said.append)
    assert asked == ["repos/o/r/issues/12/comments?per_page=100&since=2026-10-04T06:50:30Z"]            # exactly what the event names, once
    assert carried == 2
    # one lane (one owner): the two fundings left in the order they were posted, then the proof
    assert [s[:2] for s in sent] == [("fund", ghrelay.token_id(one)), ("fund", ghrelay.token_id(two)), ("proof", ghrelay.token_id(bad))]
    assert sent[0][2] == terms.encode()
    assert len(posted) == 3 and posted == said
    assert posted[0].startswith(f"knos-relay fund o/r#12 {ghrelay.token_id(one)} ok sig=s1,s2 queued_at=") and posted[0].endswith(" note=funded t=20")
    assert posted[2] == f"knos-relay proof o/r#12 {ghrelay.token_id(bad)} fail no open bounty for this issue"
    journal = json.loads((tmp_path / "ghrelay.json").read_text(encoding="utf-8"))["journal"]
    assert sorted((e["kind"], e["state"], e["where"]) for e in journal.values()) == [("fund", "confirmed", "o/r#12"), ("fund", "confirmed", "o/r#12"), ("proof", "refused", "o/r#12")]
    assert relayq.Queue(tmp_path / "ghrelay.json").counts() == {"queued": 0, "leased": 0, "done": 2, "dead": 1}
    # the same event again (GitHub delivered it twice, or the sweep announced the same comment): nothing is sent twice from here
    assert relayq.serve_event("repository_dispatch", event, Ledger(), None, tmp_path / "ghrelay.json", get=get, post=posted.extend, clock=lambda: now, say=said.append) == 0
    assert len(sent) == 3 and len(posted) == 3
    # a token the chain already showed done gets no line from an event run: whoever carried it writes its own
    monkeypatch.setattr(ghrelay, "relay_one", lambda *a, **k: {"ok": True, "kind": "fund", "already": True, "sigs": [], "note": "funded"})
    assert relayq.serve_event("repository_dispatch", event, Ledger(), None, tmp_path / "other.json", get=get, post=posted.extend, clock=lambda: now, say=said.append) == 0
    assert len(posted) == 3
    # an event that names nothing, a full queue, a quota that is spent: said in words, and the run ends well (the sweep carries it)
    assert relayq.serve_event("push", {}, Ledger(), None, tmp_path / "none.json", get=get, post=posted.extend, clock=lambda: now, say=said.append) == 0
    assert said[-1].startswith("relay: a push event names no token") and said[-1].endswith("The relay's next sweep of the comments carries what is posted there.")


@pytest.fixture
def sweep(monkeypatch, tmp_path):
    """The always-on pass over one repository's comments, with GitHub and the relays faked and notes of its own:
    (comments, sent, posted, pass)."""
    comments, sent, posted, answers = [], [], [], {}

    def relay_one(ledger, payer, kind, token, terms=None):
        sent.append((kind, ghrelay.token_id(token)))
        return dict(answers.get(ghrelay.token_id(token), {"ok": True, "kind": "fund", "sigs": ["s1"], "note": "funded"}))
    reads = []
    monkeypatch.setattr(ghrelay, "found", lambda repo, since: reads.append(repo) or (list(comments) if repo == "o/r" else []))
    monkeypatch.setattr(ghrelay, "discover", lambda since, state: set())
    monkeypatch.setattr(ghrelay, "watched", lambda ledger, state, now: set())
    monkeypatch.setattr(ghrelay, "logged", lambda since, get=None: set())
    monkeypatch.setattr(ghrelay, "post_log", posted.extend)
    monkeypatch.setattr(ghrelay, "relay_one", relay_one)
    monkeypatch.setattr(ghrelay, "stages", lambda *a, **k: {})
    monkeypatch.setattr(ghrelay, "_state_path", lambda: tmp_path / "ghrelay.json")
    monkeypatch.setenv("KNOS_RELAY_REPOS", "o/r")
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)

    class Ledger:
        def send(self):
            return "sig"
    return comments, sent, posted, answers, reads, lambda now: ghrelay.once(Ledger(), None, now=now, crank=False)


TERMS = '{"accept":"","checks":[{"app":15368,"name":"test"}],"deny":[".github/**",".knos/**"],"mode":"merge","paths":[],"reserve":7,"v":1}'


def test_an_event_run_and_the_sweep_that_share_their_notes_never_both_carry_one_token(sweep, tmp_path, monkeypatch):
    comments, sent, posted, _answers, _reads, once = sweep
    now = ghrelay._unix("2026-10-04T08:00:30Z")
    one = jwt(fund_aud(7), repository="o/r", repository_owner_id="77", run_id="1")
    two = jwt(fund_aud(8), repository="o/r", repository_owner_id="77", run_id="2")
    three = jwt(fund_aud(9), repository="o/r", repository_owner_id="78", run_id="3")
    api = [_comment(12, ghrelay.token_comment("fund", one, TERMS), "2026-10-04T08:00:10Z")]
    event = {"client_payload": {"repo": "o/r", "number": 12}}

    class Ledger:
        def send(self):
            return "sig"
    serve = lambda: relayq.serve_event("repository_dispatch", event, Ledger(), None, tmp_path / "ghrelay.json", get=lambda path: api,  # noqa: E731
                                       post=posted.extend, clock=lambda: now, say=lambda line: None)
    # 1. the event run carries it and its answer is in the notes the sweep reads: the sweep finds the comment and sends nothing
    assert serve() == 1 and sent == [("fund", ghrelay.token_id(one))] and len(posted) == 1
    notes = json.loads((tmp_path / "ghrelay.json").read_text(encoding="utf-8"))
    assert [e["state"] for e in notes["journal"].values()] == ["confirmed"] and notes["repos"] == {"o/r": now}      # and the sweep now knows the repository
    comments.append(ghrelay.Found("fund", 12, one, "octocat", TERMS.encode(), now - 20))
    assert once(now + 3) == [] and len(sent) == 1 and len(posted) == 1
    assert len(json.loads((tmp_path / "ghrelay.json").read_text(encoding="utf-8"))["seen"]) == 1                  # noted as answered: never looked up again
    # 2. the sweep carries one; the event that announces the same comment queues nothing and sends nothing
    comments.append(ghrelay.Found("fund", 12, two, "octocat", TERMS.encode(), now - 10))
    [line] = once(now + 6)
    assert f" {ghrelay.token_id(two)} ok " in line and len(sent) == 2
    api.append(_comment(12, ghrelay.token_comment("fund", two, TERMS), "2026-10-04T08:00:20Z"))
    assert serve() == 0 and len(sent) == 2 and len(posted) == 2
    # 3. an event run holds one in flight (leased, no answer yet): the sweep reads its comment and leaves it alone ...
    api.append(_comment(12, ghrelay.token_comment("fund", three, TERMS), "2026-10-04T08:00:25Z"))
    queue = relayq.Queue(tmp_path / "ghrelay.json", lambda: now + 7)
    [key] = relayq.ingest(queue, "repository_dispatch", event, lambda path: api, now + 7)
    assert queue.take("event:w1")["key"] == key
    comments.append(ghrelay.Found("fund", 12, three, "octocat", TERMS.encode(), now - 5))
    assert once(now + 9) == [] and once(now + 60) == [] and len(sent) == 2
    # ... until the lease has expired with no answer (that run is gone): then the sweep takes it, once, and says it was a second try
    [line] = once(now + 7 + relayq.LEASE)
    assert f" {ghrelay.token_id(three)} ok " in line and " tries=2 " in line and len(sent) == 3
    assert queue.finish(key, "event:w1", {"ok": False, "why": "late"}) == "done" and once(now + 400) == [] and len(sent) == 3


def test_a_full_queue_stops_the_sweep_reading_comments_and_says_when_it_reads_again(sweep, tmp_path, monkeypatch, capsys):
    comments, sent, _posted, answers, reads, once = sweep
    monkeypatch.setattr(relayq, "LIMIT", 3)
    toks = [jwt(fund_aud(i), iat=1000 + i, exp=int(T0) + 3000, repository_owner_id=str(50 + i)) for i in range(5)]
    for i, t in enumerate(toks):
        comments.append(ghrelay.Found("fund", i, t, "octocat", TERMS.encode(), T0 - 5))
        answers[ghrelay.token_id(t)] = {"ok": False, "kind": "fund", "why": "TimeoutError: not confirmed within 60s", "retry": True, "transient": True}
    assert once(T0) == [] and sorted(s[1] for s in sent) == sorted(ghrelay.token_id(t) for t in toks[:3])        # three are taken; the queue holds three
    said = capsys.readouterr().err
    notes = json.loads((tmp_path / "ghrelay.json").read_text(encoding="utf-8"))
    rest = notes["resting"] - T0
    assert 5 <= rest <= 60 and f"No comment is read for {int(rest)} seconds; reading starts again at {ghrelay._stamp(notes['resting'])}." in said
    assert "the queue is full (3 tokens wait and it holds 3)" in said and "Nothing is lost: a token that was not taken is still in its comment." in said
    assert len(notes["journal"]) == 3 and notes["seen"] == []                  # the two it did not take are nowhere but in their comments
    # until then no comment is read (what is queued is still carried, each on its own times)
    n = len(reads)
    for t in toks[:3]:
        del answers[ghrelay.token_id(t)]
    lines = once(T0 + 3)
    assert len(reads) == n and len(lines) == 3 and "comments are read again at" in capsys.readouterr().err
    # then it reads again, and the two that waited in their comments are carried
    assert len(once(T0 + rest + 1)) == 0 and len(reads) > n and len(sent) == 8
    for t in toks[3:]:
        del answers[ghrelay.token_id(t)]
    assert len(once(T0 + rest + 4)) == 2 and "resting" not in json.loads((tmp_path / "ghrelay.json").read_text(encoding="utf-8"))


def test_the_sweep_carries_12_tokens_of_6_owners_past_one_slow_confirmation_and_a_killed_pass(tmp_path):
    """`scripts/queue_drill.py`'s second part, which docs/LOAD.md prints: `ghrelay.once` itself, on the queue."""
    got = drill.sweep(tmp_path)
    assert got["ok"], got
    # one confirmation took 60 s of the clock: the other 11 were done before it, in the same pass, each sent once
    assert (got["done_in_the_first_pass"], got["sends_in_the_first_pass"], got["done_before_the_slow_one_confirmed"]) == (12, 12, 11)
    assert got["slow_one_took_s"] >= 60 > got["slowest_other_took_s"] and got["most_in_flight"] == relayq.WORKERS == 4
    assert got["two_of_one_owner_in_flight"] == 0 and got["out_of_order"] == 0 and got["sent_twice"] == 0
    # a pass killed between a send and the note of its answer: the lease is in the notes, the next pass sends again, and it
    # is the chain's single-use rule that answers ("already"): taken once, logged once, as a second try that sent nothing
    assert got["pass_killed"] and got["killed_token_in_the_notes_after_the_kill"] == ["sending"]
    assert (got["killed_token_sends"], got["killed_token_taken_by_chain"]) == (2, 1) and got["killed_token_answered_already_and_logged_once"]
    assert got["taken_by_chain"] == 14 == got["log_lines"] and got["lines_after_everything_was_done"] == 0 and got["states"] == ["confirmed"]
    kept = json.loads((ROOT / "docs" / "load.json").read_text(encoding="utf-8"))["relay"]["sweep"]
    assert kept == got == drill.sweep(tmp_path / "again")
    page = (ROOT / "docs" / "LOAD.md").read_text(encoding="utf-8")
    assert "| Tokens done before the slow one confirmed | 11 of the other 11 |" in page and "were made by the serial sweep" in page


def test_the_sweeps_lanes_one_owner_one_lane_and_what_names_no_owner_one_at_a_time():
    a, b, c = jwt(fund_aud(1), repository_owner_id="77"), jwt(fund_aud(2), repository_owner_id=77), jwt(fund_aud(3), repository_owner_id="78")
    assert ghrelay._lane("fund", a, "o/r") == ghrelay._lane("proof", b, "o/x") == "owner:77" != ghrelay._lane("fund", c, "o/r")
    assert ghrelay._lane("fund", jwt(fund_aud(4)), "o/r") == ghrelay._lane("fund", jwt(fund_aud(5)), "p/q") == "unowned"
    # the three kinds with a limit a day for one repository: a lane for each repository, so the count is taken one at a time
    assert ghrelay._lane("withdraw", "AAAA", "u/knos-claim") == "withdraw:u/knos-claim" and ghrelay._lane("passkey-fund", "AAAA", "o/r") == "passkey-fund:o/r"
    assert ghrelay._lane("verify", jwt("x", repository_id="9", repository_owner_id="77"), "o/r") == "verify:9" and set(relayq.LEFT_TO_SWEEP) == {"verify", "withdraw", "passkey-fund"}


def test_two_tokens_of_one_owner_share_a_lane_and_a_token_that_names_none_travels_alone():
    from knos.settle.v2 import relay
    a, b = jwt(fund_aud(1), repository_owner_id="77"), jwt(fund_aud(2), repository_owner_id=77)
    c = jwt(fund_aud(3), repository_owner_id="78")
    assert relay.lane(a) == relay.lane(b) == "owner:77" and relay.lane(c) == "owner:78"
    lone = jwt(fund_aud(4))
    assert relay.lane(lone).startswith("alone:") and relay.lane(lone) != relay.lane(jwt(fund_aud(5))) and relay.lane("not a token").startswith("alone:")


# ---- worker.yml: the event beside the timer -----------------------------------------------------------------------------

def test_the_worker_takes_the_event_in_a_job_of_its_own_that_keeps_no_notes_and_starts_no_run():
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "worker.yml").read_text(encoding="utf-8"))
    on = doc[True] if True in doc else doc["on"]                    # YAML reads a bare `on` as true
    assert on["repository_dispatch"] == {"types": [relayq.EVENT_TYPE]} and on["workflow_run"] == {"workflows": ["knos"], "types": ["completed"]}
    assert on["schedule"] == [{"cron": "*/5 * * * *"}]              # the sweep's timer is as it was
    relay, event = doc["jobs"]["relay"], doc["jobs"]["event"]
    assert relay["if"] == "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
    assert event["if"] == "github.event_name == 'repository_dispatch' || github.event_name == 'workflow_run'"
    text = json.dumps(event)
    assert "actions/cache" not in text and "gh workflow run" not in text and "knos-home" not in text.replace("knos-event-home", "")
    assert "github.event." not in text and "client_payload" not in text         # nothing of the event reaches a shell: the relay reads its file
    runs = [str(s.get("run") or "") for s in event["steps"]]
    install = next(i for i, r in enumerate(runs) if "requirements/sign.txt" in r)
    assert runs[install] == next(str(s["run"]) for s in relay["steps"] if "requirements/sign.txt" in str(s.get("run")))     # the chain's install, by hash
    assert runs[install + 1].strip() == "python -m knos.settle.v2.relayq --help" and "secrets." not in json.dumps(event["steps"][:install + 2])
    last = [ln.strip() for ln in runs[-1].splitlines()]
    assert last[-1] == 'python -m knos.settle.v2.relayq --event "$GITHUB_EVENT_PATH" --event-name "$GITHUB_EVENT_NAME"' and "||" not in last[-1]
    assert [s["with"]["enable-cache"] for s in event["steps"] if "setup-uv" in str(s.get("uses"))] == [False]
    assert event["steps"][-1]["env"]["KNOS_RELAY_WORKERS"] == str(relayq.WORKERS)
    # an event run's title is one the chain's first step does not count
    assert "'relay for a dispatch'" in doc["run-name"] and "'relay for a run'" in doc["run-name"]
    assert 'startswith("relay for ") | not' in relay["steps"][0]["run"]
    assert HOME == "drexthealpha/Knos"


# -- notes two runners both see: the relay-log issue as the store (0.3.19) ----------------------------------------------
class Log:
    """The relay-log issue of one repository: comments in the order GitHub took them, newest first when listed.
    `turns`: the order in which named runners' requests are let through (then anyone's)."""

    def __init__(self, turns: str = "") -> None:
        import threading
        self.comments: list[dict] = []
        self.down = False
        self.turns, self.cv = list(turns), threading.Condition()

    def _turn(self, who: str, do):
        with self.cv:
            assert self.cv.wait_for(lambda: not self.turns or self.turns[0] == who, timeout=20), f"{who} was never let through: {self.turns}"
            try:
                if self.down:
                    raise RuntimeError("GitHub answered 502")
                return do()
            finally:
                if self.turns:
                    self.turns.pop(0)
                self.cv.notify_all()

    def _post(self, body: str, login: str = relayq.LOG_BOT, issue: int = 1) -> dict:
        c = {"id": 9000 + len(self.comments), "user": {"login": login}, "issue_url": f"https://api.github.com/repos/{HOME}/issues/{issue}", "body": body}
        self.comments.append(c)
        return c

    def store(self, who: str, said: list | None = None) -> relayq.LogStore:
        return relayq.LogStore(HOME, lambda path: self._turn(who, lambda: list(reversed(self.comments))[:100]),
                               lambda path, data: self._turn(who, lambda: self._post(data["body"])), lambda: 1,
                               say=(said if said is not None else []).append)


def _runner(tmp_path, log: Log, who: str, clock: list, said: list | None = None) -> tuple[relayq.Queue, relayq.Notes]:
    """A runner with a disk of its own: its journal, its notes folder, and the one thing it shares, the log."""
    notes = relayq.Notes(tmp_path / who / "notes", f"{who}-run", lambda: clock[0], store=log.store(who, said))
    return relayq.Queue(tmp_path / who / "ghrelay.json", lambda: clock[0], notes=notes), notes


@pytest.mark.parametrize("skew", [0.0, -50.0, 50.0])
@pytest.mark.parametrize("turns", ["ABAB", "ABBA", "AABB", "BABA", "BAAB", "BBAA"])
def test_in_every_interleaving_of_two_runners_writes_and_reads_one_token_is_sent_once(tmp_path, turns, skew):
    """Each runner's lease is a write (its line) and a read (the log). Whatever order GitHub takes the four in, and
    whatever the two clocks say, exactly one runner is told the token is its to send; the other sends nothing, then or
    after it read the answer."""
    import threading
    log, ca, cb = Log(turns), [T0], [T0 + skew]
    (qa, na), (qb, nb) = _runner(tmp_path, log, "A", ca), _runner(tmp_path, log, "B", cb)
    for q_ in (qa, qb):
        assert q_.put("tok", "lane", {"jwt": "x"}, id="i")
    assert log.comments == []                                   # a token that waits is nobody's news: no comment
    took: dict[str, dict | None] = {}
    threads = [threading.Thread(target=lambda n=n, q_=q_: took.__setitem__(n, q_.take("w"))) for n, q_ in (("A", qa), ("B", qb))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not log.turns and sorted(took) == ["A", "B"]
    winners = [n for n, e in took.items() if e is not None]
    assert len(winners) == 1, (turns, took)
    first = relayq.NOTE_MARK + ("A-run" if log.comments[0]["body"].startswith(relayq.NOTE_MARK + "A-run ") else "B-run")
    assert log.comments[0]["body"].startswith(first) and winners == [first[-5]]         # the earlier comment holds, not the earlier clock
    win, lose = ((qa, qb) if winners == ["A"] else (qb, qa))
    loser = nb if winners == ["A"] else na
    assert lose.take("w") is None                               # in flight elsewhere: not this runner's to send
    assert win.finish("tok", "w", {"ok": True}) == "done"
    assert len(log.comments) == 3                               # two leases and one answer: one comment a change, and no other
    loser.store.take(list(reversed(log.comments)))             # the sweep's next fetch of the log's comments, handed in
    assert lose.take("w") is None and lose.entries()["tok"]["state"] == "done" and lose.entries()["tok"]["by"] == f"{winners[0]}-run"
    assert len(log.comments) == 3 and loser.store.asked == 1    # the loser wrote nothing more, and asked GitHub once: at its lease


def test_a_lease_whose_runner_died_is_taken_by_the_other_when_it_is_over_and_the_token_is_sent_once(tmp_path):
    log, clock = Log(), [T0]
    (qa, _na), (qb, nb) = _runner(tmp_path, log, "A", clock), _runner(tmp_path, log, "B", clock)
    for q_ in (qa, qb):
        q_.put("tok", "lane", {"jwt": "x"}, id="i")
    assert qa.take("w") is not None                             # A leases, and its runner is gone before any answer
    nb.store.read()
    for later in (1.0, relayq.LEASE - 1.0):
        clock[0] = T0 + later
        assert qb.take("w") is None
    clock[0] = T0 + relayq.LEASE
    got = qb.take("w")
    assert got is not None and got["tries"] == 1 and qb.finish("tok", "w", {"ok": True}) == "done"
    assert [json.loads(c["body"].split(" ", 3)[3])["s"] for c in log.comments] == ["sending", "sending", "confirmed"]
    assert [c["body"].split(" ")[2] for c in log.comments] == ["A-run", "B-run", "B-run"]


def test_when_github_fails_the_notes_are_local_and_the_run_says_so_once_and_again_when_they_are_shared(tmp_path):
    log, clock, said = Log(), [T0], []
    qa, na = _runner(tmp_path, log, "A", clock, said)
    log.down = True
    for key in ("one", "two"):
        qa.put(key, key, {"jwt": key}, id=key)
        assert qa.take("w")["key"] == key                       # carried all the same: the chain takes a token once
    assert log.comments == [] and na.store.failed == "GitHub answered 502"
    assert len(said) == 1 and said[0].startswith("relay notes: GitHub did not take or give this run's shared notes (GitHub answered 502). They are local")
    lines = [json.loads(ln) for ln in na.file.read_text(encoding="utf-8").splitlines()]
    assert [(ln["k"], ln["s"]) for ln in lines] == [("one", "waiting"), ("one", "sending"), ("two", "waiting"), ("two", "sending")]
    assert not any("at" in ln for ln in lines)
    log.down = False
    assert qa.finish("one", "w", {"ok": True}) == "done"
    assert said[1:] == ["relay notes: shared with the other runners again (the relay log took a line)."] and na.store.failed is None
    assert len(log.comments) == 1 and '"s":"confirmed"' in log.comments[0]["body"]


def test_only_the_logs_own_account_on_the_log_issue_writes_a_note_and_the_sweeps_fetch_is_the_read(tmp_path, monkeypatch):
    log = Log()
    store = log.store("A")
    line = relayq.NOTE_MARK + 'B-run {"k":"tok","s":"confirmed","t":5}'
    log._post(line, login="someone-outside")                    # anyone can comment on a public issue
    log._post(line, issue=2)                                    # the workflow's account, on another issue
    log._post(relayq.NOTE_MARK + 'B-run {"k":"tok","s":"waiting","t":5}')      # not a state the log carries
    assert store.take(list(reversed(log.comments))) == 0 and store.lines == {}
    log._post("knos-relay fund octo/widgets#7 0123456789abcdef ok sig=s note=funded t=3\n" + line)
    assert store.take(list(reversed(log.comments))) == 1 and store.lines["B-run"]["tok"]["s"] == "confirmed" and store.asked == 0
    notes = relayq.Notes(tmp_path / "notes", "A-run", lambda: T0, store=store)
    assert notes.theirs("tok")["state"] == "confirmed" and notes.theirs("tok")["by"] == "B-run"
    # the request a lease makes is the sweep's own for the log's repository, so its answer is one GitHub already gave
    assert store.path == f"repos/{HOME}/issues/comments?sort=created&direction=desc&per_page=100"
    for name in ("KNOS_RELAY_SHARED_NOTES", "GITHUB_REPOSITORY", "GITHUB_WORKFLOW_REF"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ghrelay, "_STORE", {})
    assert ghrelay.log_store() is None                          # a relay of someone else's writes no note anywhere
    worker = {"GITHUB_REPOSITORY": ghrelay.HOME_REPO, "GITHUB_WORKFLOW_REF": f"{ghrelay.HOME_REPO}/.github/workflows/worker.yml@refs/heads/main"}
    assert ghrelay.shares_notes(worker) and not ghrelay.shares_notes({**worker, "KNOS_RELAY_SHARED_NOTES": "0"})
    assert ghrelay.log_store(worker) is ghrelay.log_store(worker) and ghrelay.log_store(worker).path == f"repos/{ghrelay.HOME_REPO}/issues/comments?sort=created&direction=desc&per_page=100"


def test_an_event_run_and_the_sweep_on_two_runners_see_each_other_through_the_relay_log(sweep, tmp_path, monkeypatch):
    """Two disks, one log. What the event run answered the sweep does not send; what the event run holds in flight the
    sweep leaves alone until that lease is over; and the sweep reads the other's lines in the comments its pass
    fetches for the log's repository anyway."""
    comments, sent, posted, _answers, _reads, once = sweep
    now = ghrelay._unix("2026-10-04T08:00:30Z")
    log, fetched = Log(), []
    monkeypatch.setattr(ghrelay, "log_store", lambda env=None, store=log.store("S"): store)
    monkeypatch.setattr(ghrelay, "_api", lambda path: fetched.append(path) or list(reversed(log.comments)))
    monkeypatch.setattr(ghrelay, "found", lambda repo, since, getter=None: (getter(f"repos/{repo}/issues/comments") and []) if getter else
                        (list(comments) if repo == "o/r" else []))
    one = jwt(fund_aud(7), repository="o/r", repository_owner_id="77", run_id="1")
    three = jwt(fund_aud(9), repository="o/r", repository_owner_id="78", run_id="3")
    api = [_comment(12, ghrelay.token_comment("fund", one, TERMS), "2026-10-04T08:00:10Z")]
    event = {"client_payload": {"repo": "o/r", "number": 12}}
    theirs = relayq.Notes(tmp_path / "event-runner" / "notes", "event-1", lambda: now, store=log.store("E"))

    class Ledger:
        def send(self):
            return "sig"
    assert relayq.serve_event("repository_dispatch", event, Ledger(), None, tmp_path / "event-runner" / "ghrelay.json", get=lambda path: api,
                              post=posted.extend, clock=lambda: now, say=lambda line: None, notes=theirs) == 1
    assert sent == [("fund", ghrelay.token_id(one))] and [c["body"].split('"s":"')[1].split('"')[0] for c in log.comments] == ["sending", "confirmed"]
    assert not (tmp_path / "ghrelay-notes" / "event-1.jsonl").exists()          # the sweep's disk holds nothing of the event run's
    comments.append(ghrelay.Found("fund", 12, one, "octocat", TERMS.encode(), now - 20))
    assert once(now + 3) == [] and len(sent) == 1 and fetched == [f"repos/{ghrelay.HOME_REPO}/issues/comments"]
    assert len(log.comments) == 2                                               # the sweep wrote nothing about a token it did not carry
    # the event run holds the next one in flight: the sweep leaves it until that lease is over, then sends it once
    api.append(_comment(12, ghrelay.token_comment("fund", three, TERMS), "2026-10-04T08:00:25Z"))
    held = relayq.Queue(tmp_path / "event-runner" / "ghrelay.json", lambda: now + 7, notes=theirs)
    [key] = relayq.ingest(held, "repository_dispatch", event, lambda path: api, now + 7)
    assert held.take("event:w1")["key"] == key
    comments.append(ghrelay.Found("fund", 12, three, "octocat", TERMS.encode(), now - 5))
    assert once(now + 9) == [] and once(now + 60) == [] and len(sent) == 1
    [line] = once(now + 7 + relayq.LEASE)
    assert f" {ghrelay.token_id(three)} ok " in line and len(sent) == 2
    assert [(c["body"].split(" ")[2][:5], c["body"].split('"s":"')[1].split('"')[0]) for c in log.comments[2:]] == [("event", "sending"), ("sweep", "sending"), ("sweep", "confirmed")]


def test_an_event_run_that_sends_nothing_for_a_token_it_found_says_who_holds_it_and_where_the_log_says_so(tmp_path, monkeypatch):
    """0.3.19, live in staging: an event run found the token the sweep had carried a moment before and printed only
    "0 tokens carried". It now says, for each token it found and does not carry, which runner the notes name and
    the relay-log comment that carries their word; also when the other runner answered while this run waited."""
    import hashlib
    now = ghrelay._unix("2026-10-04T08:00:30Z")
    one = jwt(fund_aud(7), repository="o/r", repository_owner_id="77", run_id="1")
    two = jwt(fund_aud(8), repository="o/r", repository_owner_id="78", run_id="2")
    key = lambda t: hashlib.sha256(f"fund\n{t}\n".encode() + TERMS.encode()).hexdigest()[:16]  # noqa: E731
    api = [_comment(12, ghrelay.token_comment("fund", one, TERMS), "2026-10-04T08:00:10Z")]
    event = {"client_payload": {"repo": "o/r", "number": 12}}
    log, sent, said = Log(), [], []
    sweep_notes = relayq.Notes(tmp_path / "sweep" / "notes", "sweep-1", lambda: now, store=log.store("S"))
    assert sweep_notes.lease(key(one), now + relayq.LEASE)
    sweep_notes.append(key(one), "confirmed")
    monkeypatch.setattr(ghrelay, "relay_one", lambda *a, **k: sent.append(a) or {"ok": True, "kind": "fund", "sigs": ["s"], "note": "funded"})

    class Ledger:
        def send(self):
            return "sig"
    theirs = relayq.Notes(tmp_path / "event" / "notes", "event-1", lambda: now, store=log.store("E"))
    assert theirs.store.read()                  # what `main` does before anything is queued
    serve = lambda: relayq.serve_event("repository_dispatch", event, Ledger(), None, tmp_path / "event" / "ghrelay.json",  # noqa: E731
                                       get=lambda path: api, post=lambda lines: None, clock=lambda: now, say=said.append, notes=theirs)
    assert serve() == 0 and sent == []
    confirmed_at = log.comments[1]["id"]
    assert said == [f"relay: fund o/r#12 {ghrelay.token_id(one)}: not carried by this run: sweep-1 has it on chain "
                    f"(relay log comment {confirmed_at}), so nothing is sent from here"]
    assert len(log.comments) == 2               # nothing written by the run that sent nothing
    # the sweep holds the next one when the event run queues it, and answers while the event run waits for its lease
    api.append(_comment(12, ghrelay.token_comment("fund", two, TERMS), "2026-10-04T08:00:20Z"))
    assert sweep_notes.lease(key(two), now + relayq.LEASE)
    real = relayq.work

    def work(queue, *a, **k):
        sweep_notes.append(key(two), "confirmed")
        theirs.store.read()
        return real(queue, *a, **k)
    monkeypatch.setattr(relayq, "work", work)
    said.clear()
    assert serve() == 0 and sent == []
    assert said[-1] == (f"relay: fund o/r#12 {ghrelay.token_id(two)}: not carried by this run: sweep-1 has it on chain "
                        f"(relay log comment {log.comments[-1]['id']}), so nothing is sent from here")
