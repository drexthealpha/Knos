"""The relay's chain of runs heals itself: a start GitHub answers with an error is asked again, and a watchdog that is
not part of the chain starts one when none is alive (src/knos/proof/chain.py; worker.yml, job `watchdog`)."""
from __future__ import annotations

import io
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from knos.proof import chain

ROOT = Path(__file__).resolve().parents[1]


def _err(code: int, **head) -> urllib.error.HTTPError:
    import email.message
    h = email.message.Message()
    for k, v in head.items():
        h[k.replace("_", "-")] = v
    return urllib.error.HTTPError("https://api.github.com/x", code, "no", h, io.BytesIO(b""))


class GitHub:
    """GitHub's answers to the two requests the chain makes: `answers` to the start, in turn (an exception is raised,
    anything else means taken); `listed` to the listing (an exception is raised). A fake clock: sleeping only adds."""

    def __init__(self, answers=(), listed=(), beats=None):
        self.answers, self.listed, self.starts, self.slept, self.said = list(answers), listed, [], [], []
        self.beats = beats or {}            # run id -> when its heartbeat step completed (GitHub's text); none: no beat yet

    def request(self, path: str, data: dict | None = None):
        if data is None and "/jobs?" in path:
            rid = int(path.split("/runs/")[1].split("/")[0])
            beat = self.beats.get(rid)
            steps = [{"name": "Set up job", "status": "completed", "conclusion": "success", "completed_at": "2026-10-08T00:00:01Z"}]
            if beat:
                steps.append({"name": chain.HEARTBEAT, "status": "completed", "conclusion": "success", "completed_at": beat})
            return {"jobs": [{"name": "relay", "steps": steps}]}
        if data is None:
            assert path == "/repos/o/r/actions/workflows/worker.yml/runs?per_page=50"
            if isinstance(self.listed, Exception):
                raise self.listed
            return {"workflow_runs": [{"id": i, "status": s, "display_title": t} for i, s, t in self.listed]}
        assert path == "/repos/o/r/actions/workflows/worker.yml/dispatches"
        self.starts.append(data)
        got = self.answers.pop(0) if self.answers else None
        if isinstance(got, Exception):
            raise got
        return None

    def kw(self) -> dict:
        return {"request": self.request, "sleep": self.slept.append, "say": self.said.append}


def test_a_500_on_the_start_no_longer_ends_the_chain():
    gh = GitHub([_err(500), _err(502), None])
    assert chain.start("o/r", "80", **gh.kw()) is True
    assert gh.starts == [{"ref": "main", "inputs": {"after": "80"}}] * 3 and gh.slept == [2.0, 4.0]       # the fake clock: nothing random
    assert "GitHub answered 500 while starting the next run (try 1 of 6): asking again in 2 s" in gh.said and gh.said[-1].startswith("started the next run (try 3)")


def test_the_waits_double_to_a_minute_and_a_rate_limit_names_its_own():
    assert [chain.wait_for(n) for n in range(1, 8)] == [2, 4, 8, 16, 32, 60, 60]
    assert chain.wait_for(1, "7") == 7 and chain.wait_for(1, "900") == chain.WAIT_MOST and chain.wait_for(3, "soon") == 8
    gh = GitHub([_err(429, Retry_After="5"), _err(403, Retry_After="3"), TimeoutError("slow"), None])
    assert chain.start("o/r", "80", **gh.kw()) is True and gh.slept == [5.0, 3.0, 8.0]


def test_a_start_github_took_but_answered_with_an_error_is_not_asked_twice():
    gh = GitHub([_err(500), None], listed=[(80, "in_progress", "relay after 79"), (85, "queued", "relay after 80")])
    assert chain.start("o/r", "80", **gh.kw()) is True
    assert len(gh.starts) == 1 and gh.said[-1] == "run 85 took over all the same: nothing more is asked"


def test_an_answer_that_asking_again_cannot_change_is_said_at_once_and_errors_to_the_end_give_up():
    gh = GitHub([_err(404)])
    with pytest.raises(chain.Refused, match="404"):
        chain.start("o/r", "80", **gh.kw())
    assert len(gh.starts) == 1 and gh.slept == []
    gh = GitHub([_err(403)])          # a 403 that names no wait is a refusal (the token may not start runs)
    with pytest.raises(chain.Refused):
        chain.start("o/r", "80", **gh.kw())
    gh = GitHub([_err(500)] * 3, listed=OSError("down"))
    assert chain.start("o/r", "80", tries=3, **gh.kw()) is False
    assert len(gh.starts) == 3 and gh.slept == [2.0, 4.0] and "given up" in gh.said[-1]


def test_the_watchdog_starts_a_chain_only_when_none_is_queued_or_in_progress():
    idle = [(70, "completed", "relay after 69"), (71, "in_progress", "relay for a run"), (72, "queued", "relay for the timer"), (90, "in_progress", "relay for the timer")]
    gh = GitHub(listed=idle)
    assert chain.watch("o/r", 90, **gh.kw()) == "started" and gh.starts == [{"ref": "main", "inputs": {"after": ""}}]
    for alive in ((73, "queued", "relay"), (73, "in_progress", "relay after 70"), (73, "waiting", "relay"), (73, "pending", "relay after 1")):
        gh = GitHub(listed=[*idle, alive])
        assert chain.watch("o/r", 90, **gh.kw()) == "alive" and gh.starts == []
    gh = GitHub(listed=OSError("down"))        # two chains are worse than a late one: no listing, no start
    assert chain.watch("o/r", 90, **gh.kw()) == "unknown" and gh.starts == [] and gh.slept == [2.0, 4.0]
    gh = GitHub([_err(503)] * 2, listed=idle)
    assert chain.watch("o/r", 90, tries=2, **gh.kw()) == "failed"



def test_the_watchdog_inside_a_chain_run_that_did_not_relay_starts_that_runs_successor():
    """worker.yml's job `rewatch` (`watch --successor`): run 90 is still in progress while its last job watches, so it is
    not counted, and the run started takes over from it ("relay after 90"): a first run would find run 90 going and end
    at its first step. A run that took over from 90 already holds the chain: nothing is started."""
    ending = [(90, "in_progress", "relay after 85"), (85, "completed", "relay after 80")]
    gh = GitHub(listed=ending)
    assert chain.watch("o/r", 90, successor=True, **gh.kw()) == "started" and gh.starts == [{"ref": "main", "inputs": {"after": "90"}}]
    gh = GitHub(listed=[*ending, (93, "queued", "relay after 90")])
    assert chain.watch("o/r", 90, successor=True, **gh.kw()) == "alive" and gh.starts == []
    gh = GitHub(listed=ending)          # without --successor (the timer's watchdog) a start is a first run, as before
    assert chain.watch("o/r", 77, **gh.kw()) == "alive" and gh.starts == []

def test_two_watchdogs_cannot_start_two_chains():
    """The second watchdog runs after the first (their concurrency group) and finds the run the first one started. And
    when its start got a 500 that GitHub took, the listing before the next try finds that run too."""
    world: list[tuple[int, str, str]] = []

    class Live(GitHub):
        def request(self, path, data=None):
            if data is None:
                return {"workflow_runs": [{"id": i, "status": s, "display_title": t} for i, s, t in world]}
            self.starts.append(data)
            world.append((100 + len(world), "queued", "relay"))        # GitHub takes every start it is sent
            if self.answers:
                raise self.answers.pop(0)
            return None
    one, two = Live([_err(500)]), Live()
    assert chain.watch("o/r", 90, **one.kw()) == "started" and chain.watch("o/r", 91, **two.kw()) == "alive"
    assert len(world) == 1 and len(one.starts) == 1 and two.starts == []


def test_the_watchdog_runs_as_one_file_with_nothing_installed():
    """The job runs `python3 -I src/knos/proof/chain.py watch` right after the checkout: the standard library alone."""
    out = subprocess.run([sys.executable, "-I", str(ROOT / "src" / "knos" / "proof" / "chain.py"), "watch"], capture_output=True, text=True, encoding="utf-8", env={})
    assert out.returncode == 2 and "GITHUB_REPOSITORY" in out.stderr


# ---- 0.3.21: alive means a heartbeat, not "a run exists" ----------------------------------------------------------------

T0 = chain.when("2026-10-08T01:00:00Z")


def _at(seconds: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(T0 + seconds, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class World(GitHub):
    """A worker's runs that change: a cancel ends a run after `cancel_takes` listings (None: only a force-cancel ends it),
    a start adds a run that GitHub lists only after `lag` listings. The clock is the test's (`now`)."""

    def __init__(self, runs, beats=None, lag=0, cancel_takes=0):
        super().__init__(beats=beats)
        self.world = [dict(r) for r in runs]
        self.lag, self.cancel_takes, self.cancels, self.forced, self.pending = lag, cancel_takes, [], [], []

    def request(self, path, data=None):
        if "/jobs?" in path:
            return super().request(path, data)
        if data is None:
            for p in list(self.pending):
                p["in"] -= 1
                if p["in"] < 0:
                    self.world.append(p["run"])
                    self.pending.remove(p)
            for r in self.world:
                if r.get("ends_in") is not None:
                    r["ends_in"] -= 1
                    if r["ends_in"] < 0:
                        r["status"], r["ends_in"] = "completed", None
            return {"workflow_runs": [{"id": r["id"], "status": r["status"], "display_title": r["title"], "created_at": r.get("created"),
                                       "run_started_at": r.get("started")} for r in self.world]}
        if path.endswith("/cancel") or path.endswith("/force-cancel"):
            rid = int(path.split("/runs/")[1].split("/")[0])
            (self.forced if path.endswith("/force-cancel") else self.cancels).append(rid)
            for r in self.world:
                if r["id"] == rid and (path.endswith("/force-cancel") or self.cancel_takes is not None):
                    r["ends_in"] = 0 if path.endswith("/force-cancel") else self.cancel_takes
            return None
        self.starts.append(data)
        run = {"id": 200 + len(self.starts), "status": "queued", "title": "relay", "created": _at(0)}
        self.pending.append({"in": self.lag, "run": run})
        return None


def test_a_run_stuck_in_its_install_wait_is_cancelled_and_replaced():
    """The 0.3.20 gap: a run in its PyPI wait counted as alive. Now a run with no heartbeat INSTALL_MOST after it started
    is cancelled, and one run is started once GitHub lists the stuck one ended."""
    stuck = {"id": 80, "status": "in_progress", "title": "relay after 79", "created": _at(-700), "started": _at(-690)}
    gh = World([stuck], cancel_takes=1)
    assert chain.watch("o/r", 90, now=lambda: T0, **gh.kw()) == "started"
    assert gh.cancels == [80] and gh.forced == [] and gh.starts == [{"ref": "main", "inputs": {"after": ""}}]
    assert any("no heartbeat in time" in line for line in gh.said)


def test_a_run_still_installing_within_its_time_or_with_a_fresh_beat_is_alive_and_an_old_beat_is_not():
    installing = {"id": 80, "status": "in_progress", "title": "relay after 79", "created": _at(-200), "started": _at(-190)}
    gh = World([installing])
    assert chain.watch("o/r", 90, now=lambda: T0, **gh.kw()) == "alive" and gh.cancels == [] and gh.starts == []
    relaying = {"id": 80, "status": "in_progress", "title": "relay after 79", "created": _at(-900), "started": _at(-890)}
    gh = World([relaying], beats={80: _at(-120)})
    assert chain.watch("o/r", 90, now=lambda: T0, **gh.kw()) == "alive" and gh.starts == []
    gh = World([relaying], beats={80: _at(-chain.BEAT_MOST - 1)})          # a relay that hangs after its beat
    assert chain.watch("o/r", 90, now=lambda: T0, **gh.kw()) == "started" and gh.cancels == [80]
    # a run that waits for a runner past QUEUED_MOST is replaced too; one that waits less is alive
    assert chain.health({"status": "queued", "created": T0 - 60}, None, T0) == "alive"
    assert chain.health({"status": "queued", "created": T0 - chain.QUEUED_MOST - 1}, None, T0) == "stuck"


def test_a_cancel_that_does_not_end_the_run_is_forced_and_one_that_never_ends_starts_nothing():
    stuck = {"id": 80, "status": "in_progress", "title": "relay after 79", "created": _at(-700), "started": _at(-690)}
    gh = World([stuck], cancel_takes=None)          # a cancel is ignored: only a force-cancel ends it
    assert chain.watch("o/r", 90, now=lambda: T0, **gh.kw()) == "started" and gh.cancels == [80] and gh.forced == [80]

    class Never(World):
        def request(self, path, data=None):
            if path.endswith("cancel"):
                return None                          # taken, and the run goes on all the same
            return super().request(path, data)
    gh = Never([stuck])
    assert chain.watch("o/r", 90, now=lambda: T0, **gh.kw()) == "stuck" and gh.starts == []


def test_when_github_does_not_list_a_runs_steps_the_run_counts_as_alive():
    class Blind(World):
        def request(self, path, data=None):
            if "/jobs?" in path:
                raise OSError("down")
            return super().request(path, data)
    stuck = {"id": 80, "status": "in_progress", "title": "relay after 79", "created": _at(-700), "started": _at(-690)}
    gh = Blind([stuck])
    assert chain.watch("o/r", 90, now=lambda: T0, **gh.kw()) == "alive" and gh.cancels == [] and gh.starts == []


def test_two_watchdogs_never_start_two_chains_even_when_github_lists_the_new_run_late():
    """The first watchdog replaces a stuck run and waits until GitHub lists the run it started (here: two listings
    late); the second, which runs after it (their concurrency group), finds that run queued and starts nothing."""
    stuck = {"id": 80, "status": "in_progress", "title": "relay after 79", "created": _at(-700), "started": _at(-690)}
    gh = World([stuck], lag=2)
    assert chain.watch("o/r", 90, now=lambda: T0, **gh.kw()) == "started"
    assert chain.watch("o/r", 91, now=lambda: T0 + 30, **gh.kw()) == "alive"
    assert len(gh.starts) == 1 and gh.cancels == [80]
    assert [r["id"] for r in gh.world if r["status"] in chain.ALIVE] == [201]


def test_github_times_read_as_seconds():
    assert chain.when("1970-01-01T00:01:00Z") == 60.0 and chain.when(None) is None and chain.when("soon") is None
