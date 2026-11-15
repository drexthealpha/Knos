"""The playground's own rules (src/knos/playground.py): where a stranger may fund a test task, how, how much and how often."""
from __future__ import annotations

import calendar
import json
from pathlib import Path

from knos import commands, playground
from knos.settle.v2 import pay

ROOT = Path(__file__).resolve().parents[1]
NOW = calendar.timegm((2026, 10, 7, 12, 0, 0))


def opened(number=7, login="stranger", action="opened"):
    return {"action": action, "issue": {"number": number, "user": {"login": login, "id": 4242}, "body": playground.FUND}}


def listing(*stamps, pulls=()):
    return lambda path: [{"created_at": s} for s in stamps] + [{"created_at": s, "pull_request": {}} for s in pulls]


def test_the_playground_is_one_repository_of_one_owner_on_devnet():
    own = json.loads((ROOT / "scripts" / "own_github_ids.json").read_text(encoding="utf-8"))
    assert playground.OWNER_ID in own["ids"]
    assert playground.is_playground("drexthealpha/knos-playground", playground.OWNER_ID, True)
    assert playground.is_playground("DrexTheAlpha/Knos-Playground", playground.OWNER_ID, True)          # GitHub's names ignore case
    assert not playground.is_playground("drexthealpha/knos-playground", playground.OWNER_ID, False)     # never off devnet
    assert not playground.is_playground("drexthealpha/knos-playground", 99, True)                       # the name under another owner
    assert not playground.is_playground("octo/knos-playground", playground.OWNER_ID, True)
    assert not playground.is_playground("drexthealpha/Knos", playground.OWNER_ID, True)


def test_the_line_the_template_carries_is_a_fund_command_within_the_playground_and_the_faucet():
    cmd = commands.parse(f"Two lines of explanation.\n\n{playground.FUND}\n")
    assert isinstance(cmd, commands.Fund) and cmd.units == playground.MOST and cmd.checks == () and cmd.auto is True
    assert pay.ORDER_MIN_AMOUNT <= playground.MOST <= pay.FAUCET_CAP


def test_a_stranger_funds_only_by_opening_an_issue_within_the_amount_the_slots_and_the_day():
    day = "2026-10-07T0{}:00:00Z"
    ok = lambda ev, units=playground.MOST, n=1: playground.refuses(listing(*[day.format(i) for i in range(n)]), playground.REPO, ev, units, NOW)  # noqa: E731
    assert ok(opened()) == ""
    assert ok(opened(), n=playground.PER_DAY) == ""                                   # the third of the day, this one included
    assert "at most 3 playground tasks in a day" in ok(opened(), n=playground.PER_DAY + 1)
    assert "at most 5 test USDC" in ok(opened(), units=playground.MOST + 1)
    assert ok(opened(number=playground.SLOTS)) == "" and f"issues 1 to {playground.SLOTS}" in ok(opened(number=playground.SLOTS + 1))
    assert "funded as it is opened" in ok({**opened(), "comment": {"body": playground.FUND}, "action": "created"})    # never by a comment
    assert "funded as it is opened" in ok(opened(action="edited"))                                                    # nor by an edit
    # pull requests and other days are not counted; no answer from GitHub is not zero
    count = playground.opened_today(listing("2026-10-07T01:00:00Z", "2026-10-06T23:59:59Z", pulls=["2026-10-07T02:00:00Z"]), playground.REPO, "stranger", NOW)
    assert count == 1

    def down(path):
        raise OSError("503")
    assert playground.opened_today(down, playground.REPO, "stranger", NOW) is None
    assert "GitHub did not say" in playground.refuses(down, playground.REPO, opened(), playground.MOST, NOW)
    assert playground.opened_today(lambda path: {"message": "no"}, playground.REPO, "stranger", NOW) is None
    asked = []
    playground.opened_today(lambda path: asked.append(path) or [], playground.REPO, "stranger", NOW)
    assert asked == [f"repos/{playground.REPO}/issues?creator=stranger&state=all&since=2026-10-07T00:00:00Z&per_page=100"]
    assert not any(r.startswith("/knos") for r in (ok(opened(), n=9), ok(opened(), units=10**9)))      # a reply never starts a command


def test_the_document_says_the_limits_the_code_holds_and_claims_nobody():
    import importlib.util
    spec = importlib.util.spec_from_file_location("small_repos_playground", ROOT / "scripts" / "small_repos.py")
    small = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(small)
    doc = (ROOT / "docs" / "reference" / "PLAYGROUND.md").read_text(encoding="utf-8")
    lib = (ROOT / "programs-v2" / "knos_pay" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "pub const FAUCET_CAP: u64 = 100_000_000;" in lib and "pub const FUND_PERIOD: i64 = 60;" in lib and pay.FAUCET_CAP == 100_000_000
    assert "| One funding | at most 100 test USDC | the program (`FAUCET_CAP`) |" in doc and "one faucet funding a minute | the program (`FUND_PERIOD`, error 90)" in doc
    assert f"| One playground task | {playground.MOST // 10**6} test USDC, funded only as the issue is opened, once |" in doc
    assert f"| One account | {playground.PER_DAY} funded issues in a day (UTC) |" in doc and f"| Issues with checks | numbers 1 to {playground.SLOTS} |" in doc
    assert f"`{playground.FUND}`" in doc and f"`{playground.TASK}`" in doc and f"on {len(small.starter_cases())} recorded lines" in doc
    assert f"for up to {pay.HOLD // 86_400} days" in doc and f"https://github.com/{playground.REPO}/issues/new?template=fund-a-test-task.md" in doc
    assert "Nobody outside has used it" not in doc and "never claimed" in doc         # strangers came: the count says how many, the page does not
    assert any(line.startswith("Test USDC, no monetary value.") for line in doc.splitlines()[:7])
    assert "outside funder, Knos repository, faucet money" in doc and "never added to each other" in doc
    assert "an outside payee, never an outside funder" in doc
    # the stranger's path, in the order he walks it, and the board's limits as the code holds them
    path = [doc.index(w) for w in ("**Fork.**", "**`Closes #N`.**", "**The check.**", "**The merge pays.**")]
    assert path == sorted(path) and "`/knos address <address>`" in doc and "passkey wallet" in doc and "python3 check.py <task>" in doc
    spec = importlib.util.spec_from_file_location("task_board_playground", ROOT / "scripts" / "task_board.py")
    board = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(board)
    tasks = board.catalogue()
    assert f"The {len(tasks)} tasks are" in doc and f"keeps {board.TARGET} of them" in doc and {t["amount"] for t in tasks} == {pay.ORDER_MIN_AMOUNT}
    assert f"| A funded task of the board | {pay.ORDER_MIN_AMOUNT // 10**6} test USDC, {tasks[0]['deadline_days']} days, {board.TARGET} open at once |" in doc
    assert "three examples, 5 test USDC" in doc and all(len(t["public"]) == 3 and t["deadline_days"] == 14 for t in tasks)
    assert len(doc.splitlines()) <= 90
    low = doc.lower()
    assert not any(w in low for w in ("immutable", "audited", "customers")) and "## How it is counted" in doc
    # the site links the same place and the same repository
    site = (ROOT / "web" / "playground.js").read_text(encoding="utf-8")
    assert f'export const REPO = "{playground.REPO}";' in site and "docs/reference/PLAYGROUND.md" in site and "#how-it-is-counted" in site


def test_the_site_draws_the_playground_from_mocked_data_and_asks_only_github_and_itself():
    """tests/web/playground.mjs: the links, the rows, the three counts and the word budget with no browser, then in
    headless Chromium when the `playwright` package and a browser are there (it says so when they are not)."""
    import os
    import shutil
    import subprocess

    import pytest
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path("/opt/pw-browsers").is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/pw-browsers"
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "playground.mjs")], capture_output=True, text=True, encoding="utf-8", env=env, timeout=300)
    assert run.returncode == 0 and "all passed" in run.stdout, "\n".join(x for x in (run.stdout + run.stderr).splitlines() if not x.startswith("ok"))
    assert "ok   zeros that were counted are shown as zeros" in run.stdout and "ok   no statement on it is longer than 12 words" in run.stdout
