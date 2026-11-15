"""The playground: one public repository of Knos's where an account that cannot write to it may fund a test task.

Everywhere else `/knos fund` is for someone who can write to the repository (knos.flow._can_write). In the playground
the money is the devnet faucet's free test USDC, minted for the funding and withdrawn by nobody, so the only thing a
stranger can spend is Knos's patience. What bounds that is here, and knos.flow asks it before it asks GitHub to sign:

    where     only REPO, only while its owner is OWNER_ID (a repository of that name under another account is not it),
              only on devnet
    how       only in the description of an issue the account opens (`issues: opened`): one funding for one issue. A
              `/knos fund` comment from an account that cannot write is refused as it is everywhere
    how much  at most MOST for one task (the faucet itself gives at most pay.FAUCET_CAP for one funding)
    how often at most PER_DAY issues opened by one account in one UTC day, counted from GitHub's own list of that
              account's issues there; and the program's own rule, one faucet use per repository per minute
              (FUND_PERIOD), which holds whoever asks
    what      an issue numbered at most SLOTS: the repository holds the starter task's acceptance checks for those
              numbers (scripts/small_repos.py writes them), and a task with none could only be paid by a merge

`refuses` returns the reply to post, or "" when the funding may go on. It reads GitHub once and the chain never.
"""
from __future__ import annotations

import datetime

REPO = "drexthealpha/knos-playground"
OWNER_ID = 142920951                # the GitHub id of the account that owns it (scripts/own_github_ids.json)
MOST = 5_000_000                    # millionths of test USDC one playground task holds at most
PER_DAY = 3                         # issues one account may open and fund in one UTC day
SLOTS = 200                         # issue numbers that have the starter task's acceptance checks
FUND = "/knos fund 5 checks: none auto"      # the line the issue template carries
TASK = "words.py"                   # the one file a solution edits


def is_playground(repo: str, owner_id, devnet: bool) -> bool:
    """Whether this run is in the playground: the name, the owner's id and the cluster all say so."""
    return bool(devnet) and str(repo).lower() == REPO.lower() and owner_id == OWNER_ID


def _day(stamp) -> str:
    return str(stamp or "")[:10]


def opened_today(github, repo: str, login: str, now: float) -> int | None:
    """How many issues (not pull requests) this account opened in `repo` on the UTC day of `now`. None: GitHub did not say."""
    today = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y-%m-%d")
    try:
        got = github(f"repos/{repo}/issues?creator={login}&state=all&since={today}T00:00:00Z&per_page=100")
    except Exception:  # noqa: BLE001 - not knowing is not zero
        return None
    if not isinstance(got, list):
        return None
    return sum(1 for i in got if isinstance(i, dict) and "pull_request" not in i and _day(i.get("created_at")) == today)


def refuses(github, repo: str, event: dict, units: int, now: float) -> str:
    """Why an account that cannot write may not fund this in the playground ("" when it may). `event` is the run's event."""
    found = event.get("issue")
    issue: dict = found if isinstance(found, dict) else {}
    user = issue.get("user")
    author: dict = user if isinstance(user, dict) else {}
    login = str(author.get("login") or "")
    if "comment" in event or event.get("action") != "opened" or not login:
        return ("Knos: nothing was funded. In the playground a task is funded as it is opened, by the `/knos fund` line in its "
                f"description: open a new one at https://github.com/{REPO}/issues/new?template=fund-a-test-task.md")
    if units > MOST:
        return (f"Knos: nothing was funded. A playground task holds at most {MOST // 1_000_000} test USDC. Open a new one and leave "
                f"the line as it is: `{FUND}`.")
    if int(issue.get("number") or 0) > SLOTS:
        return (f"Knos: nothing was funded. The playground has acceptance checks for issues 1 to {SLOTS}, and this is issue "
                f"#{issue.get('number')}: the next release adds more. Knos works in your own repository today "
                "(https://github.com/drexthealpha/Knos/blob/main/docs/reference/INSTALL.md).")
    n = opened_today(github, repo, login, now)
    if n is None:
        return f"Knos: GitHub did not say how many tasks @{login} opened here today, so nothing was funded. Open the issue again."
    if n > PER_DAY:
        return (f"Knos: nothing was funded. One account funds at most {PER_DAY} playground tasks in a day (UTC), and this is "
                f"@{login}'s issue number {n} today. Take one of the open tasks instead, or come back tomorrow.")
    return ""
