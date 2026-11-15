"""GitHub's record of a pull request's head commit, for the agent pull requests whose description claims tests pass or
CI is green. Read-only: one GraphQL query (`gh api graphql`) per BATCH (20) pull requests, the same query and the same
verdict the Agent PR Index uses (scripts/agent_pr_ci.py: `rollup_query`, `verdict`), so "failed" here means what it
means there and at the gate: a project check (not the agent's own session run) concluded failure, timed_out or
startup_failure at the head commit.

Every answer is kept under the cache directory, one JSON file per pull request, so a run that stops (a rate limit, a
network outage) continues where it stopped and a second run asks GitHub nothing.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BATCH = 20


def _index():
    spec = importlib.util.spec_from_file_location("agent_pr_ci", ROOT / "scripts" / "agent_pr_ci.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _graphql(query: str, tries: int = 6) -> dict | None:
    """One query; waits and asks again on a rate limit or a server error; None when GitHub never answered."""
    wait = 30
    for _ in range(tries):
        p = subprocess.run(["gh", "api", "graphql", "-f", f"query={query}"], capture_output=True, text=True)
        try:
            body = json.loads(p.stdout or "null")
        except ValueError:
            body = None
        if isinstance(body, dict) and isinstance(body.get("data"), dict):
            return body
        time.sleep(wait)
        wait = min(wait * 2, 600)
    return None


def _parse(index, pr: dict | None) -> dict:
    """agent_pr_ci.read_rollup's reading of one answered pull request, except that one with more than 100 checks, or one
    GitHub did not return, is class error here (the index reads those over REST)."""
    nodes = ((pr or {}).get("commits") or {}).get("nodes") or []
    if not pr or not nodes:
        return {"class": "error", "detail": "the pull request or its repository is gone"}
    commit = nodes[0]["commit"]
    contexts = (commit.get("statusCheckRollup") or {}).get("contexts") or {}
    if (contexts.get("pageInfo") or {}).get("hasNextPage"):
        return {"class": "error", "detail": "more than 100 checks (not read)"}
    low = lambda v: str(v or "").lower() or None  # noqa: E731
    runs = [{"name": x.get("name") or "", "status": low(x.get("status")), "conclusion": low(x.get("conclusion"))}
            for x in contexts.get("nodes") or [] if x and x.get("__typename") == "CheckRun"]
    statuses = [{"context": x.get("context") or "", "state": {"expected": "pending"}.get(low(x.get("state")), low(x.get("state")))}
                for x in contexts.get("nodes") or [] if x and x.get("__typename") == "StatusContext"]
    suites = [{"conclusion": low(x.get("conclusion"))} for x in (commit.get("checkSuites") or {}).get("nodes") or [] if x]
    return {"sha": commit.get("oid"), **index.verdict(runs, statuses, suites), "merged": bool(pr.get("merged"))}


def read(cands: list[dict], cache: Path, max_seconds: float = 1e9, log=print) -> dict[int, dict]:
    """{pr id: verdict} for `cands` ({id, repo, number}); asks GitHub only for those not kept in `cache`."""
    index = _index()
    cache.mkdir(parents=True, exist_ok=True)
    out: dict[int, dict] = {}
    todo = []
    for c in cands:
        f = cache / f"{c['id']}.json"
        if f.exists():
            out[c["id"]] = json.loads(f.read_text())
        else:
            todo.append(c)
    log(f"ci: {len(out)} kept, {len(todo)} to read")
    start = time.monotonic()
    for i in range(0, len(todo), BATCH):
        if time.monotonic() - start > max_seconds:
            log("ci: stopped for time; run again to continue")
            break
        part = todo[i:i + BATCH]
        got = _graphql(index.rollup_query(part))
        if got is None:
            log("ci: GitHub did not answer; run again to continue")
            break
        for j, c in enumerate(part):
            pr = (got["data"].get(f"p{j}") or {}).get("pullRequest")
            v = _parse(index, pr)
            out[c["id"]] = v
            (cache / f"{c['id']}.json").write_text(json.dumps(v, sort_keys=True))
        if (i // BATCH) % 25 == 0:
            log(f"ci: {i + len(part)}/{len(todo)}")
    return out
