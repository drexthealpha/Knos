"""Has a repository Knos does not own merged a pull request lately? The gate in front of anything Knos sends to,
opens on or recommends for somebody else's repository: no merge in the last 30 days, or no answer, and it stops.

    python scripts/upstream_check.py x402-foundation/x402                   # one line, exit 0 only if merged in 30 days
    python scripts/upstream_check.py --docs docs/INTEGRATIONS.md docs/X402.md --list     # the outside repositories those pages name
    python scripts/upstream_check.py --docs docs/INTEGRATIONS.md docs/X402.md            # check each of them
    python scripts/upstream_check.py owner/repo --days 30 --json

`--docs` leaves out what a page has already marked as not active (between `<!-- not-active -->` and
`<!-- /not-active -->`); `--marked` puts those back, to see whether one of them woke up.

Exit 0: every repository merged a pull request within `--days`. Exit 1: at least one did not. Exit 2: at least one
could not be read (no network, a renamed or private repository, a rate limit, no merged pull request found): unknown
counts as a refusal, never as a pass.

It reads GitHub's public REST API (`GET /repos/<owner>/<repo>/pulls?state=closed&sort=updated&direction=desc`) and
takes the newest `merged_at` among the 100 most recently updated closed pull requests. That can only read too old,
never too new: a repository where over 100 closed pull requests were touched after its last merge would be refused.
GITHUB_TOKEN, when set, is sent to api.github.com and nowhere else (the anonymous limit is 60 requests an hour).
`--fixture DIR` reads DIR/<owner>__<repo>.json in place of the network, and `--now` fixes the clock: the tests use both.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.github.com"
DAYS = 30
OWN = ("drexthealpha",)                 # Knos's own account: never an outside repository
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")
LINK = re.compile(r"github\.com/([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9._-]+)")
MARKED = re.compile(r"<!-- not-active -->.*?<!-- /not-active -->", re.S)     # rows a page already marks as not active
NOT_REPOS = {"orgs", "sponsors", "features", "marketplace", "apps", "settings", "login", "about"}


class Unknown(Exception):
    """Why the repository's last merge could not be read."""


def when(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def fetch(repo: str, fixture: Path | None = None, timeout: float = 20) -> list:
    """The repository's closed pull requests, most recently updated first, as the API returns them."""
    if fixture is not None:
        path = fixture / (repo.replace("/", "__") + ".json")
        try:
            got = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            raise Unknown(f"no fixture {path.name}") from None
    else:
        req = urllib.request.Request(f"{API}/repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=100",
                                     headers={"Accept": "application/vnd.github+json", "User-Agent": "knos-upstream-check"})
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 (the URL is built from API above)
                got = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise Unknown(f"GitHub answered {e.code}") from None
        except (OSError, ValueError) as e:
            raise Unknown(f"could not read GitHub: {type(e).__name__}") from None
    if not isinstance(got, list):
        raise Unknown("GitHub did not answer with a list of pull requests")
    return got


def last_merged(pulls: list) -> tuple[datetime, int] | None:
    """(when, number) of the newest merged pull request in the list, or None when none of them was merged."""
    best: tuple[datetime, int] | None = None
    for p in pulls:
        if not isinstance(p, dict) or not p.get("merged_at"):
            continue
        try:
            at = when(str(p["merged_at"]))
        except ValueError:
            continue
        if best is None or at > best[0]:
            best = (at, int(p.get("number") or 0))
    return best


def check(repo: str, now: datetime, days: int = DAYS, fixture: Path | None = None) -> dict:
    """{repo, state: ok | stale | unknown, merged_at, pull, age_days, why}."""
    out: dict = {"repo": repo, "state": "unknown", "merged_at": None, "pull": None, "age_days": None, "why": ""}
    if not NAME.match(repo):
        out["why"] = "not a repository name: write owner/name"
        return out
    try:
        got = last_merged(fetch(repo, fixture))
    except Unknown as why:
        out["why"] = str(why)
        return out
    if got is None:
        out["why"] = "no merged pull request among the 100 most recently updated closed ones"
        return out
    at, number = got
    if at > now + timedelta(minutes=5):
        out["why"] = "the newest merge is dated after now: check this machine's clock"
        return out
    age = max(now - at, timedelta(0))
    out.update(merged_at=at.strftime("%Y-%m-%dT%H:%M:%SZ"), pull=number, age_days=age.days,
               state="ok" if age <= timedelta(days=days) else "stale")
    out["why"] = "" if out["state"] == "ok" else f"no pull request merged in the last {days} days"
    return out


def repos_in(paths: list[Path], marked: bool = False) -> list[str]:
    """Every github.com/<owner>/<name> those files link to that is not Knos's own, in order of first appearance.
    What a page puts between `<!-- not-active -->` and `<!-- /not-active -->` it has already marked as not active:
    those are left out unless `marked`, and nothing may be sent to them whatever this script says of the rest."""
    seen: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for owner, name in LINK.findall(text if marked else MARKED.sub("", text)):
            repo = f"{owner}/{name.removesuffix('.git').rstrip('.')}"
            if owner in OWN or owner in NOT_REPOS or repo in seen:
                continue
            seen.append(repo)
    return seen


def line(got: dict) -> str:
    if got["state"] == "unknown":
        return f"{got['repo']}  unknown: {got['why']}"
    said = f"{got['repo']}  last merged pull request #{got['pull']} on {got['merged_at'][:10]} ({got['age_days']} days ago)"
    return said + ("  ok" if got["state"] == "ok" else f"  STALE: {got['why']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Exit 0 only if every repository merged a pull request in the last 30 days.")
    ap.add_argument("repos", nargs="*", help="owner/name")
    ap.add_argument("--docs", nargs="+", type=Path, default=[], help="also every outside repository these files link to")
    ap.add_argument("--marked", action="store_true", help="with --docs: also the repositories a page already marks as not active")
    ap.add_argument("--list", action="store_true", help="print the repositories and stop: nothing is fetched")
    ap.add_argument("--days", type=int, default=DAYS)
    ap.add_argument("--now", default="", help="the time to measure from, ISO 8601 (default: this machine's clock)")
    ap.add_argument("--fixture", type=Path, default=None, help="a folder of <owner>__<repo>.json to read in place of the network")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    repos = list(dict.fromkeys([*a.repos, *repos_in(a.docs, a.marked)]))
    if not repos:
        ap.error("name a repository as owner/name, or --docs FILE")
    if a.list:
        print("\n".join(repos))
        return 0
    now = when(a.now) if a.now else datetime.now(timezone.utc)
    got = [check(r, now, a.days, a.fixture) for r in repos]
    print(json.dumps(got, indent=1) if a.json else "\n".join(line(g) for g in got))
    states = {g["state"] for g in got}
    return 2 if "unknown" in states else 1 if "stale" in states else 0


if __name__ == "__main__":
    sys.exit(main())
