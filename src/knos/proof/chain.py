"""The relay's chain of runs: starting the next run so that one bad answer does not end it, and a watchdog.

The always-on worker (.github/workflows/worker.yml) is a chain: each run starts the next one 30 s before it stops.
In the 0.3.19 release run GitHub answered HTTP 500 to that start, and the chain was down until a person started it
again. Two things here, both with nothing but the standard library (the watchdog job installs nothing):

    python -m knos.proof.chain start --after <this run>     the handover: asked again after a 5xx, a 429 or no answer,
                                                            waiting 2, 4, 8, ... s (or what Retry-After says)
    python -m knos.proof.chain watch                        the watchdog: starts a chain when none is alive

GitHub may take a start and still answer with an error. So before a start is asked again the runs are listed, and a
run that already took over ends the asking. When the listing fails too the start is asked again all the same: of
two runs that take over from one run the worker's first step lets the older one go on, and of two runs nobody
handed over to (two watchdogs, or a watchdog and a person) the older one. Nothing here reads a key.
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


def runs(repo: str, request: Callable = call) -> list[dict]:
    """The newest 50 runs of the worker: id, status, title."""
    got = request(f"/repos/{repo}/actions/workflows/{WORKFLOW}/runs?per_page=50")
    return [{"id": int(r["id"]), "status": str(r.get("status")), "title": str(r.get("display_title") or "")} for r in (got or {}).get("workflow_runs", [])]


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
            say(f"{why} to the start, try {n} of {tries}: given up. The watchdog starts a chain when none is alive.")
            return False
        nap = wait_for(n, retry_after)
        say(f"{why} to the start, try {n} of {tries}: asking again in {nap:.0f} s")
        sleep(nap)
        try:        # GitHub may have taken the start it answered with an error
            there = taken_over(runs(repo, request), after)
        except (OSError, ValueError, KeyError, TypeError):
            there = []
        if there:
            say(f"run {there[0]} took over all the same: nothing more is asked")
            return True
    return False


def watch(repo: str, me: int = 0, tries: int = TRIES, request: Callable = call, sleep: Callable[[float], None] = time.sleep,
          say: Callable[[str], None] = print) -> str:
    """The watchdog. `alive`: a run holds the chain, nothing is started. `started`: none did, and one was started.
    `unknown`: GitHub did not list the runs, so nothing is started (two chains are worse than a late one; the next
    watchdog asks again). `failed`: none is alive and GitHub took no start."""
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
    if held:
        say(f"the chain is alive (run {', '.join(map(str, held))}): nothing to do")
        return "alive"
    say("no run of the chain is queued or in progress: starting one")
    return "started" if start(repo, "", tries=tries, request=request, sleep=sleep, say=say) else "failed"


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="The relay's chain of runs: start the next one, or watch that one is alive.")
    ap.add_argument("command", choices=("start", "watch"))
    ap.add_argument("--after", default="", help="start: the run that hands over (empty: a first run)")
    ap.add_argument("--tries", type=int, default=TRIES)
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--ref", default="main")
    a = ap.parse_args(argv)
    if not a.repo:
        ap.error("give --repo owner/name (or GITHUB_REPOSITORY)")
    try:
        if a.command == "start":
            return 0 if start(a.repo, a.after, a.ref, a.tries) else 1
        return 1 if watch(a.repo, int(os.environ.get("GITHUB_RUN_ID") or 0), a.tries) == "failed" else 0
    except Refused as no:
        print(f"stopped: {no}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
