"""The relay's queue under load, on this machine: N entries, W workers, one worker killed and one slow confirmation.

    python scripts/queue_drill.py [--items 200] [--workers 4] [--lanes 20] [--seed 314] [--write]

This is a LOCAL TEST OF THE QUEUE (knos.settle.v2.relayq), not a benchmark of the service: nothing is signed, no
transaction is built and no cluster is asked. The chain is a stand-in that keeps the one rule the queue relies on, the
programs' single-use rule: a token is taken once, and a second send of it is answered "already" and moves nothing.
(That rule itself is tested on the programs as built: tests/test_relay_failures.py, on LiteSVM.) The clock is the
drill's own, so a lease expires when the drill says so and the result is the same on every run.

What is injected:

    a kill              one worker takes an entry and stops before it sends (the thread ends without an answer). The
                        entry stays leased until its lease expires; then another worker takes it.
    a slow confirmation one entry is held in flight, 60 s on the drill's clock, while twenty others are carried. The
                        entries behind it in its lane wait for it; the other lanes do not.

THE SWEEP ON THE QUEUE (`sweep`). The second part runs the relay's always-on pass itself, `knos.proof.ghrelay.once`,
which queues what it reads and carries it with the queue's workers: 12 tokens of 6 owners (two each) are posted, the
confirmation of one takes 60 s of the drill's clock, and one pass is killed after a token was sent and before
anything was noted. GitHub and the chain are stand-ins here too; the relay, its notes and the queue are the real ones.

What is counted: entries done and dead, sends per entry (every one must be 1), entries the chain took (each once),
entries that left out of order within their lane, and the entry taken again after the kill. `--write` puts the
result in docs/load.json (`relay.queue`) and renders docs/reference/LOAD.md (scripts/load.py).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import random
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "src", ROOT / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from knos.settle.v2 import relayq  # noqa: E402

SEED = 314
HELD_FOR = 20           # entries carried while the slow one is in flight
SLOW = 60.0             # seconds the slow confirmation takes, on the drill's clock


class Killed(BaseException):
    """A worker that is gone: not an Exception, so nothing answers for the entry it held."""


class OnceChain:
    """The stand-in chain: it takes a token once. `sends`: how often each token was handed to it; `took`: the tokens
    in the order it took them, per lane."""

    def __init__(self) -> None:
        self.sends: dict[str, int] = {}
        self.took: dict[str, list[int]] = {}
        self._lock = threading.Lock()

    def submit(self, token: str, lane: str, i: int) -> dict[str, Any]:
        with self._lock:
            self.sends[token] = self.sends.get(token, 0) + 1
            if self.sends[token] > 1:
                return {"ok": True, "already": True, "sigs": []}
            self.took.setdefault(lane, []).append(i)
            return {"ok": True, "sigs": [f"sig{i}"]}


class Steady(relayq.Queue):
    """The queue with its takes in step with the drill's clock: the clock jumps past a lease only between two takes."""

    step = threading.Lock()

    def take(self, worker: str, skip: Any = (), leave: Any = ()) -> dict[str, Any] | None:
        with self.step:
            return super().take(worker, skip, leave)


def run(items: int = 200, workers: int = 4, lanes: int = 20, seed: int = SEED, home: Path | None = None) -> dict[str, Any]:
    """The drill. `home`: where the queue's file goes (default: a folder of its own, removed afterwards)."""
    if home is None:
        with tempfile.TemporaryDirectory() as tmp:
            return run(items, workers, lanes, seed, Path(tmp))
    rng = random.Random(seed)
    clock = [1_791_021_600.0]
    queue = Steady(home / "ghrelay.json", lambda: clock[0], limit=max(relayq.LIMIT, items), workers=workers)
    lane_of = [f"payer{rng.randrange(lanes)}" for _ in range(items)]
    killed_at, slow_at = rng.sample(range(items // 4, items // 2), 2)
    for i in range(items):
        queue.put(f"t{i:04d}", lane_of[i], {"i": i, "token": f"token-{seed}-{i}"})
    chain, tally = OnceChain(), threading.Lock()
    seen = {"done": 0, "kills": 0, "flying": 0, "while_slow": 0, "until": 0}
    held = threading.Event()

    def handle(entry: dict[str, Any]) -> dict[str, Any]:
        i = int(entry["item"]["i"])
        if i == killed_at and int(entry["tries"]) == 1:
            with tally:
                seen["kills"] += 1
            raise Killed
        with tally:
            seen["flying"] += 1
        r = chain.submit(str(entry["item"]["token"]), str(entry["lane"]), i)
        if i == slow_at:
            with tally:
                before = seen["done"]
                seen["until"] = before + HELD_FOR
            held.wait(timeout=60)           # until HELD_FOR others are done (the time-out only ends a drill that went wrong)
            with queue.step:
                clock[0] += SLOW
            seen["while_slow"] = seen["done"] - before
        with tally:
            seen["flying"] -= 1
            seen["done"] += 1
            if seen["until"] and seen["done"] >= seen["until"]:
                held.set()
        return r

    def idle() -> None:
        # nothing may be carried now. When the one lease still open is the killed worker's, time passes until it expires.
        # (Checked between two takes: a lease a living worker holds is never made to expire.)
        with queue.step:
            leased = [e for e in queue.entries().values() if e.get("state") == "leased"]
            if len(leased) == 1 and int(leased[0]["item"]["i"]) == killed_at and int(leased[0]["tries"]) == 1:
                clock[0] += relayq.LEASE + 1

    end = relayq.work(queue, handle, workers, idle=idle)
    entries = queue.entries()
    again = [k for k, e in entries.items() if int(e.get("tries", 0)) > 1]
    out = {"items": items, "workers": workers, "lanes": len(set(lane_of)), "seed": seed, "lease_s": relayq.LEASE,
           "done": end["done"], "dead": end["dead"], "left_open": end["queued"] + end["leased"],
           "sends": sum(chain.sends.values()), "sent_twice": sum(1 for n in chain.sends.values() if n > 1),
           "taken_by_chain": sum(len(v) for v in chain.took.values()),
           "out_of_order": sum(1 for v in chain.took.values() for a, b in zip(v, v[1:]) if a > b),
           "workers_killed": end["stopped"], "taken_again": len(again), "taken_again_was_the_killed_one": again == [f"t{killed_at:04d}"],
           "others_went_on_while_the_slow_one_was_in_flight": seen["while_slow"] >= HELD_FOR, "slow_s": SLOW}
    out["ok"] = (out["done"] == items == out["sends"] == out["taken_by_chain"] and not out["dead"] and not out["left_open"]
                 and not out["sent_twice"] and not out["out_of_order"] and out["workers_killed"] == 1 and out["taken_again_was_the_killed_one"]
                 and out["others_went_on_while_the_slow_one_was_in_flight"])
    return out


SWEEP_T0 = 1_791_021_600.0
PAY_AUD = "knos2:pay:1:7:9:" + "a" * 40 + ":" + "0" * 64 + ":0:-"


def sweep_token(i: int, owner: int) -> str:
    """A token's shape (unsigned: the chain is a stand-in): owner `owner`'s, issued `i` seconds after SWEEP_T0."""
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    body = {"aud": PAY_AUD, "iat": int(SWEEP_T0) + i, "exp": int(SWEEP_T0) + 300, "jti": f"drill-{i}", "repository_owner_id": str(7000 + owner)}
    return f"{enc({'alg': 'RS256', 'kid': 'k1'})}.{enc(body)}.c2ln"


class _Clock:
    """The `time` module with the drill's own `time()`: what the relay stamps its lines with."""

    def __init__(self, now: list[float]) -> None:
        self._now = now

    def time(self) -> float:
        return self._now[0]

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)


def sweep(home: Path | None = None, tokens: int = 12, owners: int = 6, slow: float = SLOW) -> dict[str, Any]:
    """The always-on pass on the queue: `tokens` tokens of `owners` owners in one repository, read by
    `ghrelay.once` and carried by the queue's workers. The confirmation of the last token of one owner is held until
    every other token is done, then takes `slow` seconds of the drill's clock. Then two more tokens are posted and
    the pass that carries them is killed after the first was sent and before anything was noted; the pass after it
    sends that token again and the chain answers "already"."""
    if home is None:
        with tempfile.TemporaryDirectory() as tmp:
            return sweep(Path(tmp), tokens, owners, slow)
    from knos.proof import ghrelay
    repo, clock = "octo/widgets", [SWEEP_T0 + tokens + 3]
    toks = [sweep_token(i, i % owners) for i in range(tokens + 2)]
    owner_of = {t: i % owners for i, t in enumerate(toks)}
    index = {t: i for i, t in enumerate(toks)}
    slow_one, killed_one = toks[tokens - 1], toks[tokens]       # the slow one is the last of its owner; the killed one comes after
    posted = [ghrelay.Found("proof", 10 + i, t, "octocat", None, SWEEP_T0 + i) for i, t in enumerate(toks[:tokens])]
    chain, guard, others, log = OnceChain(), threading.Lock(), threading.Event(), []
    together = threading.Barrier(min(relayq.WORKERS, owners))   # the first tokens (one an owner) confirm only once this many are in flight
    seen = {"flying": 0, "most": 0, "pairs": 0, "done_before_slow": 0, "kill": True, "answers": {}}
    flying: dict[int, int] = {}

    def relay_one(ledger: Any, payer: Any, kind: str, jwt: str, terms: bytes | None = None) -> dict[str, Any]:
        own = owner_of[jwt]
        with guard:
            flying[own] = flying.get(own, 0) + 1
            seen["pairs"] += flying[own] > 1                    # two of one owner in flight together: must stay 0
            seen["flying"] += 1
            seen["most"] = max(seen["most"], seen["flying"])
        try:
            ledger.send()                                       # the first send, on this token's own clock
            r = chain.submit(jwt, f"owner{own}", index[jwt])
            if index[jwt] < together.parties:
                try:
                    together.wait(timeout=60)                   # (the time-out only ends a drill that went wrong)
                except threading.BrokenBarrierError:
                    pass
            if jwt == killed_one and seen["kill"]:
                seen["kill"] = False
                raise KeyboardInterrupt("the runner was stopped")       # sent, and nothing noted: the process ends here
            if jwt == slow_one and not r.get("already"):
                others.wait(timeout=60)                         # until every other token is done (the time-out only ends a drill that went wrong)
                with guard:
                    seen["done_before_slow"] = sum(1 for t in toks[:tokens] if t != slow_one and seen["answers"].get(t))
                    clock[0] += slow
            ledger.send()                                       # the last confirmation
            with guard:
                seen["answers"][jwt] = seen["answers"].get(jwt, 0) + 1
                if all(seen["answers"].get(t) for t in toks[:tokens] if t != slow_one):
                    others.set()
            return {**r, "kind": "pay", "note": "paid"}
        finally:
            with guard:
                flying[own] -= 1
                seen["flying"] -= 1

    class Ledger:
        def send(self) -> str:
            return "sig"

    was = {k: getattr(ghrelay, k) for k in ("found", "discover", "watched", "post_log", "logged", "relay_one", "stages", "_state_path", "time")}
    env = {k: os.environ.get(k) for k in ("KNOS_RELAY_REPOS", "GITHUB_RUN_ID", "KNOS_RELAY_WORKERS")}
    try:
        os.environ["KNOS_RELAY_REPOS"] = repo
        os.environ.pop("GITHUB_RUN_ID", None)
        os.environ.pop("KNOS_RELAY_WORKERS", None)
        ghrelay.found = lambda r, since, getter=None: list(posted) if r == repo else []       # type: ignore[assignment]
        ghrelay.discover = lambda since, state, getter=None: set()                            # type: ignore[assignment]
        ghrelay.watched = lambda ledger, state, now, getter=None: set()                       # type: ignore[assignment]
        ghrelay.post_log = log.extend                                                         # type: ignore[assignment]
        ghrelay.logged = lambda since, get=None: set()                                        # type: ignore[assignment]
        ghrelay.relay_one = relay_one                                                         # type: ignore[assignment]
        ghrelay.stages = lambda *a, **k: {}                                                   # type: ignore[assignment]
        ghrelay._state_path = lambda: home / "ghrelay.json"                                   # type: ignore[assignment]
        ghrelay.time = _Clock(clock)                                                          # type: ignore[assignment]
        first = ghrelay.once(Ledger(), None, now=clock[0], crank=False)
        after_first = dict(chain.sends)
        posted += [ghrelay.Found("proof", 10 + i, toks[i], "octocat", None, clock[0]) for i in (tokens, tokens + 1)]
        clock[0] += 3
        try:
            ghrelay.once(Ledger(), None, now=clock[0], crank=False)
            killed = False
        except KeyboardInterrupt:
            killed = True
        left = json.loads((home / "ghrelay.json").read_text(encoding="utf-8"))
        clock[0] += 3
        again = ghrelay.once(Ledger(), None, now=clock[0], crank=False)
        clock[0] += 3
        quiet = ghrelay.once(Ledger(), None, now=clock[0], crank=False)
    finally:
        for k, v in was.items():
            setattr(ghrelay, k, v)
        for k, v in env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    notes = json.loads((home / "ghrelay.json").read_text(encoding="utf-8"))
    kid, slow_id = ghrelay.token_id(killed_one), ghrelay.token_id(slow_one)
    line_of = {ln.split()[3]: ln for ln in log}
    t_of = {tid: int(ln.rsplit(" t=", 1)[1]) for tid, ln in line_of.items() if " ok " in ln and " t=" in ln}
    out = {"tokens": tokens, "owners": owners, "workers": relayq.WORKERS, "slow_s": slow,
           "done_in_the_first_pass": sum(1 for ln in first if " ok sig=" in ln), "sends_in_the_first_pass": sum(after_first.values()),
           "done_before_the_slow_one_confirmed": seen["done_before_slow"],
           "slow_one_took_s": t_of.get(slow_id), "slowest_other_took_s": max(t for tid, t in t_of.items() if tid not in (slow_id, kid)),
           "most_in_flight": seen["most"], "two_of_one_owner_in_flight": seen["pairs"],
           "out_of_order": sum(1 for v in chain.took.values() for a, b in zip(v, v[1:]) if a > b),
           "pass_killed": killed,
           "killed_token_in_the_notes_after_the_kill": [e["state"] for e in left["journal"].values() if e.get("id") == kid],
           "killed_token_sends": chain.sends.get(killed_one, 0), "killed_token_taken_by_chain": sum(v.count(index[killed_one]) for v in chain.took.values()),
           "killed_token_answered_already_and_logged_once": sum(1 for ln in log if f" {kid} ok " in ln) == 1 and sum(1 for ln in again if f" {kid} ok " in ln and " tries=2 " in ln and " sent_at=- " in ln) == 1,
           "taken_by_chain": sum(len(v) for v in chain.took.values()), "sent_twice": sum(1 for t, n in chain.sends.items() if n > 1 and t != killed_one),
           "log_lines": len(log), "lines_after_everything_was_done": len(quiet),
           "states": sorted({str(e["state"]) for e in notes["journal"].values()})}
    out["ok"] = (out["done_in_the_first_pass"] == tokens == out["sends_in_the_first_pass"] and out["done_before_the_slow_one_confirmed"] == tokens - 1
                 and (out["slow_one_took_s"] or 0) >= slow > out["slowest_other_took_s"] and out["most_in_flight"] == min(relayq.WORKERS, owners)
                 and not out["two_of_one_owner_in_flight"] and not out["out_of_order"] and killed
                 and out["killed_token_in_the_notes_after_the_kill"] == ["sending"] and out["killed_token_sends"] == 2
                 and out["killed_token_taken_by_chain"] == 1 and out["killed_token_answered_already_and_logged_once"]
                 and out["taken_by_chain"] == tokens + 2 == out["log_lines"] and not out["sent_twice"] and not out["lines_after_everything_was_done"]
                 and out["states"] == ["confirmed"])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--items", type=int, default=200)
    ap.add_argument("--workers", type=int, default=relayq.WORKERS)
    ap.add_argument("--lanes", type=int, default=20, help="payers the entries are spread over")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--write", action="store_true", help="put the result in docs/load.json and render docs/reference/LOAD.md")
    a = ap.parse_args(argv)
    got = run(a.items, a.workers, a.lanes, a.seed)
    swept = sweep()
    print(json.dumps({**got, "sweep": swept}, indent=1))
    if a.write:
        import load
        doc = load.load()
        doc.setdefault("relay", {})["queue"] = got
        doc["relay"]["sweep"] = swept
        load.write(doc)
    return 0 if got["ok"] and swept["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
