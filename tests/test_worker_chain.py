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

    def __init__(self, answers=(), listed=()):
        self.answers, self.listed, self.starts, self.slept, self.said = list(answers), listed, [], [], []

    def request(self, path: str, data: dict | None = None):
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
    assert "GitHub answered 500 to the start, try 1 of 6: asking again in 2 s" in gh.said and gh.said[-1].startswith("started the next run (try 3)")


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
