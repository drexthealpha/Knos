"""The relay's chain of runs: starting the next run so that one bad answer does not end it, and a watchdog.

The always-on worker (.github/workflows/worker.yml) is a chain: each run starts the next one 30 s before it stops.
Once, GitHub answered HTTP 500 to that start (release run of 0.3.19), and the worker stayed down until a person
restarted it. Two things here, both with nothing but the standard library (the watchdog job installs nothing):

    python -m knos.proof.chain start --after <this run>     the handover: asked again after a 5xx, a 429 or no answer,
                                                            waiting 2, 4, 8, ... s (or what Retry-After says)
    python -m knos.proof.chain watch                        the watchdog: starts a chain when none is alive, and
                                                            replaces a run with no heartbeat in time

GitHub may take a start and still answer with an error. So before a start is asked again the runs are listed, and a
run that already took over ends the asking. When the listing fails too the start is asked again all the same: of
two runs that take over from one run the worker's first step lets the older one go on, and of two runs nobody
handed over to (two watchdogs, or a watchdog and a person) the older one. Nothing here reads a key.

ALIVE MEANS A HEARTBEAT. Once (release run of 0.3.20) a run sat waiting on its PyPI install, the watchdog counted it
alive because it existed, and the worker stayed down until a person restarted it. So "a run exists" is no longer enough:

    the heartbeat     the relay job's step HEARTBEAT, run right after the relay showed it starts with what was
                      installed. GitHub lists each step of a job with its status and the time it completed
                      (`GET /repos/{repo}/actions/runs/{id}/jobs`), so the watchdog reads the beat with no secret.
    alive             queued for less than QUEUED_MOST; or in progress with a beat less than BEAT_MOST old; or in
                      progress with no beat yet, started less than INSTALL_MOST ago (it is installing).
    stuck             in progress and none of that: no beat INSTALL_MOST after it started (an install that hangs), or
                      a beat older than BEAT_MOST (a relay that hangs). The watchdog cancels it, waits until GitHub
                      lists it ended (force-cancel when a cancel is not enough), and starts one run in its place.
    unknown           GitHub did not list a run's jobs: that run counts as alive (two chains are worse than a late one).

After a start the watchdog waits until GitHub lists the new run, so the next watchdog (they run one at a time) sees it:
two watchdogs never start two chains.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Callable

API = "https://api.github.com"
WORKFLOW = "worker.yml"
ALIVE = ("queued", "in_progress", "requested", "waiting", "pending")     # every status of a run that has not ended
WAIT_MOST = 60                  # seconds: the longest wait between two tries, whatever Retry-After says
TRIES = 6                       # 2 + 4 + 8 + 16 + 32 s of waiting at most
AGAIN = (429, 500, 502, 503, 504)
HEARTBEAT = "heartbeat: the relay starts with what was installed"     # the relay job's step that is the beat (worker.yml)
INSTALL_MOST = 8 * 60           # seconds from a run's start to its beat: checkout, uv, the install (6 minutes at most), the smoke step
BEAT_MOST = 9 * 60              # seconds a run may go on after its beat: about 4.5 minutes of relay, the cache, the handover
QUEUED_MOST = 15 * 60           # seconds a run may wait for a runner before it is replaced
SEEN_TRIES = 5                  # listings after a start, 2 s apart, until GitHub lists the new run


class Refused(Exception):
    """GitHub's answer says asking again will not help (a 4xx that is no rate limit): said, never retried."""


def wait_for(tries: int, retry_after: str | None = None) -> float:
    """Seconds before try number `tries` + 1: 2, 4, 8, ... up to WAIT_MOST, or Retry-After when GitHub names it.
    Nothing random: under a fake clock the times are the same."""
    if retry_after and retry_after.isdigit():
        return float(min(WAIT_MOST, max(1, int(retry_after))))
    return float(min(WAIT_MOST, 2 ** max(1, tries)))


def call(path: str, data: dict | None = None, opener: Callable | None = None) -> Any:
    """One request. Returns the answer's JSON (None for an empty one). Raises urllib's errors as they are."""
    head = {"Accept": "application/vnd.github+json", "User-Agent": "knos", "X-GitHub-Api-Version": "2022-11-28"}
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        head["Authorization"] = f"Bearer {tok}"
    if data is not None:
        head["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=None if data is None else json.dumps(data).encode(), headers=head, method="POST" if data is not None else "GET")
    with (opener or urllib.request.urlopen)(req, timeout=20) as resp:
        return json.loads(resp.read() or b"null")


def when(text: Any) -> float | None:
    """GitHub's time ("2026-10-08T05:22:00Z") as seconds since 1970; None for anything else."""
    import datetime
    try:
        return datetime.datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return None


def runs(repo: str, request: Callable = call) -> list[dict]:
    """The newest 50 runs of the worker: id, status, title, and when it was made and started (None when not said)."""
    got = request(f"/repos/{repo}/actions/workflows/{WORKFLOW}/runs?per_page=50")
    return [{"id": int(r["id"]), "status": str(r.get("status")), "title": str(r.get("display_title") or ""), "created": when(r.get("created_at")),
             "started": when(r.get("run_started_at") or r.get("created_at"))} for r in (got or {}).get("workflow_runs", [])]


def beat(repo: str, run: int, request: Callable = call) -> float | None:
    """When the run's HEARTBEAT step completed well; None when it has not (yet). Raises what the request raises."""
    got = request(f"/repos/{repo}/actions/runs/{run}/jobs?filter=latest&per_page=100")
    for job in (got or {}).get("jobs", []):
        for step in job.get("steps") or []:
            if step.get("name") == HEARTBEAT and step.get("status") == "completed" and step.get("conclusion") == "success":
                return when(step.get("completed_at"))
    return None


def health(run: dict, beat_at: float | None, now: float) -> str:
    """`alive` or `stuck` for a run that holds the chain (the module's text, "alive means a heartbeat")."""
    if run["status"] != "in_progress":
        made = run.get("created")
        return "stuck" if made is not None and now - made > QUEUED_MOST else "alive"
    if beat_at is not None:
        return "alive" if now - beat_at <= BEAT_MOST else "stuck"
    began = run.get("started")
    return "alive" if began is None or now - began <= INSTALL_MOST else "stuck"


def holders(listed: list[dict], me: int = 0) -> list[int]:
    """The runs that hold or are about to hold the chain, other than `me`: alive, and either a run of the chain
    ("relay after N") or one a person or a watchdog started ("relay"). A run for one event ("relay for ...") and a
    watchdog's own run relay nothing for long and start nothing, so they hold nothing."""
    return sorted(r["id"] for r in listed if r["id"] != me and r["status"] in ALIVE and (r["title"] == "relay" or r["title"].startswith("relay after ")))


def taken_over(listed: list[dict], after: str) -> list[int]:
    """The runs that took over from run `after` (whatever their status), or, for a first run, the holders."""
    return sorted(r["id"] for r in listed if r["title"] == f"relay after {after}") if after else holders(listed)


def start(repo: str, after: str = "", ref: str = "main", tries: int = TRIES, request: Callable = call, sleep: Callable[[float], None] = time.sleep,
          say: Callable[[str], None] = print) -> bool:
    """Starts the next run of the worker (`after`: the run handing over; empty for a first run). True when GitHub took
    the start, or a run that took over is listed. False after `tries` answers that were all errors worth asking again.
    Raises Refused for an answer that asking again cannot change."""
    path, body = f"/repos/{repo}/actions/workflows/{WORKFLOW}/dispatches", {"ref": ref, "inputs": {"after": after}}
    for n in range(1, max(1, tries) + 1):
        retry_after = None
        try:
            request(path, body)
            say(f"started the next run (try {n})" + (f": it takes over from run {after}" if after else ""))
            return True
        except urllib.error.HTTPError as e:
            head: Any = e.headers or {}
            if e.code not in AGAIN and not (e.code == 403 and head.get("Retry-After")):
                raise Refused(f"GitHub answered {e.code} to the start: asking again would get the same answer") from None
            why, retry_after = f"GitHub answered {e.code}", head.get("Retry-After")
        except (OSError, ValueError) as e:
            why = f"GitHub did not answer ({type(e).__name__})"
        if n >= max(1, tries):
            say(f"{why} while starting the next run (try {n} of {tries}): given up. The watchdog starts a chain when none is alive.")
            return False
        nap = wait_for(n, retry_after)
        say(f"{why} while starting the next run (try {n} of {tries}): asking again in {nap:.0f} s")
        sleep(nap)
        try:        # GitHub may have taken the start it answered with an error
            there = taken_over(runs(repo, request), after)
        except (OSError, ValueError, KeyError, TypeError):
            there = []
        if there:
            say(f"run {there[0]} took over all the same: nothing more is asked")
            return True
    return False


def _ended(repo: str, ids: list[int], request: Callable, sleep: Callable[[float], None], tries: int = 6) -> bool:
    """Lists the runs until none of `ids` is alive any more, 10 s apart. False when they still are."""
    for n in range(tries):
        try:
            if not [r for r in runs(repo, request) if r["id"] in ids and r["status"] in ALIVE]:
                return True
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if n < tries - 1:
            sleep(10.0)
    return False


def replace(repo: str, stuck: list[int], request: Callable = call, sleep: Callable[[float], None] = time.sleep, say: Callable[[str], None] = print) -> bool:
    """Cancels the stuck runs and waits until GitHub lists them ended; asks a force-cancel for those a cancel did not end.
    True when none of them is alive any more. A run that was cancelled starts nothing (its last step needs a relay step
    that succeeded), so the chain it held is over."""
    for rid in stuck:
        try:
            request(f"/repos/{repo}/actions/runs/{rid}/cancel", {})
        except (OSError, ValueError) as e:
            say(f"GitHub did not take the cancel of run {rid} ({type(e).__name__})")
    if _ended(repo, stuck, request, sleep):
        return True
    for rid in stuck:
        try:
            request(f"/repos/{repo}/actions/runs/{rid}/force-cancel", {})
        except (OSError, ValueError) as e:
            say(f"GitHub did not take the force-cancel of run {rid} ({type(e).__name__})")
    return _ended(repo, stuck, request, sleep)


def watch(repo: str, me: int = 0, tries: int = TRIES, request: Callable = call, sleep: Callable[[float], None] = time.sleep,
          say: Callable[[str], None] = print, now: Callable[[], float] = time.time, successor: bool = False) -> str:
    """The watchdog. `alive`: a run holds the chain with a heartbeat (or is still installing within its time), nothing is
    started. `started`: none did (or the ones that held it were stuck and are cancelled), and one was started.
    `unknown`: GitHub did not list the runs, so nothing is started (two chains are worse than a late one; the next
    watchdog asks again). `stuck`: a stuck run would not end, so nothing is started. `failed`: GitHub took no start.

    `successor`: the watchdog runs inside run `me` of the chain, whose relay did not succeed (worker.yml, job
    `rewatch`). Run `me` is still in progress while this runs, and a first run ("relay") that finds a run of the chain
    going ends at its first step; so the run started here takes over from `me` ("relay after <me>"), which that step
    lets go on. A run that took over from `me` already holds the chain like any other: nothing is started then."""
    listed = None
    for n in range(1, 4):
        try:
            listed = runs(repo, request)
            break
        except (OSError, ValueError, KeyError, TypeError) as e:
            say(f"GitHub did not list the runs ({type(e).__name__}), try {n} of 3")
            if n < 3:
                sleep(wait_for(n))
    if listed is None:
        say("nothing is started: the next watchdog asks again")
        return "unknown"
    held = holders(listed, me)
    stuck: list[int] = []
    for run in [r for r in listed if r["id"] in held]:
        beat_at = None
        if run["status"] == "in_progress":
            try:
                beat_at = beat(repo, run["id"], request)
            except (OSError, ValueError, KeyError, TypeError) as e:
                say(f"the relay's run sequence is running as far as can be told (run {run['id']}: GitHub did not list its steps, {type(e).__name__}): nothing to do")
                return "alive"
        if health(run, beat_at, now()) == "alive":
            said = "its heartbeat" if beat_at is not None else "installing" if run["status"] == "in_progress" else run["status"]
            say(f"the relay's run sequence is running (run {run['id']}, {said}): nothing to do")
            return "alive"
        stuck.append(run["id"])
    if stuck:
        say(f"run {', '.join(map(str, stuck))} holds the chain with no heartbeat in time: cancelled, and one is started in its place")
        if not replace(repo, stuck, request, sleep, say):
            say("GitHub still lists the stuck run as going: nothing is started (it would end at its first step). The next watchdog asks again.")
            return "stuck"
    else:
        say("no run of the chain is queued or in progress: starting one")
    if not start(repo, str(me) if successor and me else "", tries=tries, request=request, sleep=sleep, say=say):
        return "failed"
    for n in range(SEEN_TRIES):     # so that the next watchdog, which runs after this one, finds the run this one started
        try:
            if holders(runs(repo, request), me):
                return "started"
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if n < SEEN_TRIES - 1:
            sleep(2.0)
    say("GitHub does not list the started run yet: a second start would end at its first step all the same")
    return "started"


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="The relay's sequence of GitHub Actions runs (each run starts the next): start the next one, or check that one is running.")
    ap.add_argument("command", choices=("start", "watch"))
    ap.add_argument("--after", default="", help="start: the run that hands over (empty: a first run)")
    ap.add_argument("--tries", type=int, default=TRIES)
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--ref", default="main")
    ap.add_argument("--successor", action="store_true",
                    help="watch: run inside a chain run whose relay did not succeed; a run it starts takes over from this one")
    a = ap.parse_args(argv)
    if not a.repo:
        ap.error("give --repo owner/name (or GITHUB_REPOSITORY)")
    try:
        if a.command == "start":
            return 0 if start(a.repo, a.after, a.ref, a.tries) else 1
        return 1 if watch(a.repo, int(os.environ.get("GITHUB_RUN_ID") or 0), a.tries, successor=a.successor) in ("failed", "stuck") else 0
    except Refused as no:
        print(f"stopped: {no}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
