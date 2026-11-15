"""scripts/upstream_check.py: the gate in front of anything sent to, opened on or recommended for a repository Knos
does not own. It passes only a repository whose newest merged pull request is at most 30 days old; a repository it
cannot read is refused too. Fixtures stand in for GitHub's API; nothing here touches the network."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "upstream_check.py"
FIX = ROOT / "tests" / "data" / "upstream"
NOW = "2026-10-06T12:00:00Z"

_spec = importlib.util.spec_from_file_location("upstream_check", SCRIPT)
uc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(uc)


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args, "--fixture", str(FIX), "--now", NOW], capture_output=True, text=True,
                          encoding="utf-8", check=False)


def test_a_repository_that_merged_this_month_passes_and_the_date_is_printed():
    r = run("fresh/repo")
    assert r.returncode == 0 and r.stdout.strip() == "fresh/repo  last merged pull request #40 on 2026-10-01 (5 days ago)  ok"


def test_a_repository_whose_last_merge_is_older_than_30_days_is_refused():
    r = run("quiet/repo")
    assert r.returncode == 1 and "STALE" in r.stdout and "#7 on 2026-08-20 (47 days ago)" in r.stdout


@pytest.mark.parametrize("repo, why", [("gone/repo", "did not answer with a list"), ("closed/only", "no merged pull request"),
                                       ("nobody/nothing", "no fixture"), ("not-a-name", "not a repository name")])
def test_what_cannot_be_read_is_unknown_and_unknown_is_a_refusal(repo, why):
    r = run(repo)
    assert r.returncode == 2 and f"{repo}  unknown: " in r.stdout and why in r.stdout


def test_the_boundary_is_30_days_to_the_second():
    at = lambda text: datetime.fromisoformat(text).replace(tzinfo=timezone.utc)      # noqa: E731
    assert uc.check("edge/repo", at("2026-10-06T12:00:00"), fixture=FIX)["state"] == "ok"
    assert uc.check("edge/repo", at("2026-10-06T12:00:01"), fixture=FIX)["state"] == "stale"
    assert uc.check("edge/repo", at("2026-10-06T12:00:01"), days=31, fixture=FIX)["state"] == "ok"
    assert uc.check("edge/repo", at("2026-09-01T00:00:00"), fixture=FIX)["state"] == "unknown"       # a merge dated after now


def test_one_bad_repository_fails_the_whole_list_and_unknown_outranks_stale():
    assert run("fresh/repo", "quiet/repo").returncode == 1
    r = run("fresh/repo", "quiet/repo", "gone/repo", "--json")
    assert r.returncode == 2 and [g["state"] for g in json.loads(r.stdout)] == ["ok", "stale", "unknown"]


def test_no_network_is_unknown_not_a_pass(monkeypatch):
    def refused(*a, **k):
        raise OSError("no route")
    monkeypatch.setattr(uc.urllib.request, "urlopen", refused)
    got = uc.check("fresh/repo", uc.when(NOW))
    assert got["state"] == "unknown" and "could not read GitHub" in got["why"]


def test_the_token_goes_to_githubs_api_only(monkeypatch):
    seen = []

    class Answer:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return (FIX / "fresh__repo.json").read_bytes()

    def opened(req, timeout=0):
        seen.append((req.full_url, req.get_header("Authorization")))
        return Answer()
    monkeypatch.setattr(uc.urllib.request, "urlopen", opened)
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    assert uc.check("fresh/repo", uc.when(NOW))["state"] == "ok"
    assert seen == [("https://api.github.com/repos/fresh/repo/pulls?state=closed&sort=updated&direction=desc&per_page=100", "Bearer t0ken")]


def test_the_docs_this_gate_covers_name_outside_repositories_and_never_knos_itself(tmp_path):
    page = tmp_path / "page.md"
    page.write_text("[a](https://github.com/fresh/repo/blob/main/x.md) [b](https://github.com/drexthealpha/Knos) "
                    "[c](https://github.com/quiet/repo.git) [a again](https://github.com/fresh/repo)", encoding="utf-8")
    assert uc.repos_in([page]) == ["fresh/repo", "quiet/repo"]
    page.write_text("[a](https://github.com/fresh/repo)\n<!-- not-active -->\n[c](https://github.com/quiet/repo)\n<!-- /not-active -->\n", encoding="utf-8")
    assert uc.repos_in([page]) == ["fresh/repo"] and uc.repos_in([page], marked=True) == ["fresh/repo", "quiet/repo"]
    listed = run("--docs", str(ROOT / "docs" / "reference" / "INTEGRATIONS.md"), str(ROOT / "docs" / "reference" / "X402.md"), "--list")
    names = listed.stdout.split()
    assert listed.returncode == 0 and "x402-foundation/x402" in names and "codeswithroh/mergepay" in names
    assert not [n for n in names if n.startswith("drexthealpha/")] and len(names) == len(set(names))
    assert "gitcoinco/web" not in names         # the page marks it as not active already: nothing is sent there
    # and the pages say how the gate is run, with the same list
    text = (ROOT / "docs" / "reference" / "INTEGRATIONS.md").read_text(encoding="utf-8")
    assert "python scripts/upstream_check.py --docs docs/reference/INTEGRATIONS.md docs/reference/X402.md" in text


def test_the_x402_page_says_what_was_opened_upstream_and_that_nobody_answered():
    # the knos-order proposal: an issue and a draft pull request with the specification only, both linked; the page
    # no longer says nothing was opened, and the count of outside facilitators stays 0
    text = " ".join((ROOT / "docs" / "reference" / "X402.md").read_text(encoding="utf-8").split())
    assert "https://github.com/x402-foundation/x402/issues/3720" in text
    assert "https://github.com/x402-foundation/x402/pull/3731" in text
    assert "no issue and no pull request has been opened" not in text and "has not been run from a machine" not in text
    assert "No maintainer has answered either yet" in text and "the count of outside facilitators is 0" in text
