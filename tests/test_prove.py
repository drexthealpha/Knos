"""prove.yml keeps untrusted pull request code and the OIDC token apart, the judge refuses what it should, and
a token the chain would refuse before it costs a transaction, and `knos proof run` is the check job's verdict."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from knos.cli import main

ROOT = Path(__file__).resolve().parents[1]


def run(capsys, *args: str) -> tuple[int, str]:
    rc = main(list(args))
    got = capsys.readouterr()
    return rc, got.out + got.err


def _yaml(path: Path) -> dict:
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["on"] = doc.pop(True, doc.get("on"))   # YAML 1.1 reads the key `on` as True
    return doc


# ---- prove.yml ---------------------------------------------------------------------------------------------------
# What each job does is one command (knos settle, knos review, knos proof judge), tested with its own tests, and every
# rule of the second deployment's workflow files is in tests/test_workflows2.py: which job may ask GitHub for a token,
# which one runs pull request code, what each may read and write. What stays here: every action is a pinned commit,
# and the code those jobs run (who is paid, the claims at the merge, `knos proof run`).

EVENT = '--event "$GITHUB_EVENT_PATH" --repo "$GITHUB_REPOSITORY"'


def test_every_action_is_pinned_to_a_commit():
    """A tag can be moved to other code (the tj-actions compromise of 2025 did exactly that); a commit cannot."""
    import re
    pins = json.loads((ROOT / "scripts" / "action_pins.json").read_text(encoding="utf-8"))["pins"]
    ids = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
    seen = set()
    for f in sorted((ROOT / ".github" / "workflows").glob("*.yml")) + sorted((ROOT / "examples").glob("*.yml")):
        for name, ref in re.findall(r"uses:\s*([\w./-]+)@(\S+)", f.read_text(encoding="utf-8")):
            if name.startswith("./"):
                continue
            if name.startswith("drexthealpha/knos-workflows/"):
                assert ref == "KNOS_WORKFLOWS_SHA" or re.fullmatch(r"[0-9a-f]{40}", ref), (f.name, name, ref)
                continue
            if name == "drexthealpha/Knos/.github/workflows/supplier.yml":
                # the supplier's one line: Knos's own workflow at a release's tag, or the form its own header shows
                # (tests/test_workflows2.py and tests/test_record_page.py hold its shape)
                assert f.name in ("knos-supplier.yml", "supplier.yml") and (re.fullmatch(r"v\d+\.\d+\.\d+", ref) or ref.startswith("<")), (f.name, ref)
                continue
            assert not name.startswith("drexthealpha/Knos/"), f"{f.name} still calls a workflow of the first deployment"
            assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{f.name}: {name}@{ref} is not pinned to a commit"
            seen.add(ref)
    # the rotate and claim workflows are the commits the programs pin
    assert seen - {ids["rotate_sha"], ids["claim_sha"], ids["rotate_sha2"], ids["claim_sha_org"]} <= set(pins.values())


# ---- who is paid --------------------------------------------------------------------------------------------------

def _pull(login="mona", uid=4242, kind="User", body="Fixes #7", assignees=()):
    return {"number": 12, "body": body, "user": {"login": login, "id": uid, "type": kind},
            "assignees": [{"login": a, "id": i, "type": "User"} for a, i in assignees], "head": {"sha": "a" * 40}}


def _comment(cid, login, uid, body, edited=False):
    return {"id": cid, "user": {"login": login, "id": uid, "type": "User"}, "body": body, "author_association": "NONE",
            "created_at": "2026-10-01T10:00:00Z", "updated_at": "2026-10-01T10:09:00Z" if edited else "2026-10-01T10:00:00Z"}


def test_a_persons_pull_request_pays_that_person_and_an_agents_pays_whoever_github_authenticates():
    from knos import judge
    assert judge.payee(_pull()) == {"id": 4242, "login": "mona", "why": "the pull request's author"}
    assert judge.payee(_pull(body="Requested by: @other"))["id"] == 4242              # a person's own PR is never redirected
    bot = dict(login="devin-ai-integration[bot]", uid=158243242, kind="Bot")
    can_write = lambda login: "write" if login == "hubot" else "read"  # noqa: E731
    issue = {"number": 7, "assignees": []}
    # the agent's own word (it put a person in the pull request's assignees) pays nobody; that person's comment does
    named = _pull(**bot, assignees=[("mona", 4242)])
    assert judge.payee(named, issue, [], [], [], can_write)["id"] is None
    got = judge.payee(named, issue, [], [_comment(1, "mona", 4242, "/knos mine")], [], can_write)
    assert got["id"] == 4242 and "claimed it with `/knos mine`" in got["why"]
    # a maintainer names the person: write access as GitHub answers it, not a label on the comment
    pay = [_comment(1, "hubot", 1, "/knos pay @mona"), _comment(2, "mona", 4242, "thanks")]
    assert judge.payee(_pull(**bot), issue, [], pay, [], can_write) == \
        {"id": 4242, "login": "mona", "why": "maintainer @hubot named them with `/knos pay`"}
    assert judge.payee(_pull(**bot), issue, [], [_comment(1, "mallory", 66, "/knos pay @mallory")], [], can_write)["id"] is None
    # the issue is one person's, because a maintainer assigned it to them
    held = {"number": 7, "assignees": [{"login": "mona", "id": 4242, "type": "User"}]}
    by_hubot = [{"event": "assigned", "assignee": held["assignees"][0], "assigner": {"login": "hubot", "id": 1}, "created_at": "2026-09-01T10:00:00Z"}]
    assert judge.payee(_pull(**bot), held, by_hubot, [], [], can_write)["why"] == "issue #7 is theirs: maintainer @hubot assigned it to them"
    # an edited comment never counts: anyone with write access can edit anyone's comment
    for edited in ([_comment(1, "mona", 4242, "/knos mine", edited=True)], [_comment(1, "hubot", 1, "/knos pay @mona", edited=True)]):
        assert judge.payee(named, issue, [], edited, [], can_write)["id"] is None
    # nothing at all: nobody is paid, and it says exactly what to type
    got = judge.payee(_pull(**bot), issue, [], [], [], can_write)
    assert got["id"] is None and got["fix"] == "A maintainer comments `/knos pay @login` on this pull request."


def test_nobody_gets_paid_by_getting_a_line_into_a_bots_description():
    """An agent can be talked into echoing text. Whatever a description or a commit says about who ran the agent is
    shown as a hint; it pays nobody (0.3.11 paid the login such a line named)."""
    import time

    from knos import judge
    bot = dict(login="devin-ai-integration[bot]", uid=158243242, kind="Bot")
    msg = "Fix the slug\n\nCo-authored-by: mallory <66+mallory@users.noreply.github.com>"
    for line in ("Link to Devin session: https://x\nRequested by: @mallory", "PR created automatically by Jules for task 7 started by @mallory",
                 "Knos-Pay-To: @mallory", ""):
        got = judge.payee(_pull(**bot, body="Fixes #7\n\n" + line), {"number": 7, "assignees": []}, [], [], [], head_message=msg)
        assert got["id"] is None and got["hint"] == "its text names @mallory, which is a hint and decides nothing", line
        assert "`/knos pay @mallory`" in got["fix"]                                    # what a maintainer would type, if it is true
    for noise in ("Builds on the work started by @mallory.", "> Knos-Pay-To: @mallory", "```\nKnos-Pay-To: @mallory\n```",
                  "As requested by @mallory in the issue, this adds a flag.", "requested by\n\n@mallory"):
        assert "hint" not in judge.payee(_pull(**bot, body="Fixes #7\n\n" + noise)), noise    # prose, quotes and code are not even a hint
    # the hint changes nothing when GitHub's own facts name someone else
    claim = [_comment(1, "alice", 11, "/knos mine")]
    got = judge.payee(_pull(**bot, body="Knos-Pay-To: @mallory", assignees=[("alice", 11)]), None, None, claim)
    assert got["id"] == 11 and got["hint"].startswith("its text names @mallory")
    t = time.monotonic()
    judge.payee(_pull(**bot, body="requested by @a" + " " * 60_000 + "x\n" + "y" * 900_000))
    assert time.monotonic() - t < 1                                                   # no pattern that can be made slow


def test_at_the_merge_a_claim_that_cannot_be_checked_is_refused_and_knos_own_jobs_are_not_evidence():
    from knos import judge
    failed = lambda name: {"name": name, "status": "completed", "conclusion": "failure"}  # noqa: E731
    body = "Fixes #7. All tests pass."
    # Knos's own jobs from an earlier run on the same commit (a relay that timed out, a refusal) say nothing about the code:
    # they are never the check that failed, and they are not check runs that bear a claim out either
    for own in ("prove / check", "prove / merged", "prove-relay / relay", "prove-refused / refused", "fund-relay / relay", "check / claims"):
        assert judge.claim_check(body, [failed(own)]) == [], own
        assert judge.claim_check(body, [failed(own)], strict=True) == \
            ["claim: the description claims tests pass; GitHub has no check runs for this commit"], own
    assert "tests" in judge.claim_check(body, [failed("tests")], strict=True)[0]
    running = [{"name": "build", "status": "in_progress", "conclusion": None}]
    assert judge.claim_check(body, running) == [] and judge.claim_check(body, None) == []        # before a merge: not held against it
    assert "have not finished" in judge.claim_check(body, running, strict=True)[0]
    assert "could not be read" in judge.claim_check(body, None, strict=True)[0]
    assert judge.claim_check("Fixes #7.", None, strict=True) == []                               # no claim, nothing to check
    # more than 100 check runs on one commit are all read
    pages = {1: [{"name": f"job{i}", "status": "completed", "conclusion": "success"} for i in range(100)], 2: [failed("late")]}
    got = judge.check_runs("o/r", "a" * 40, get=lambda url: {"check_runs": pages.get(int(url.rsplit("page=", 1)[1]), [])})
    assert len(got) == 101 and "late" in judge.claim_check(body, got)[0]
    # at the merge the strict reading is the command's own: the job runs `knos settle` and passes it no flag to relax
    settle = _yaml(ROOT / ".github" / "workflows" / "prove.yml")["jobs"]["settle"]
    assert [s["run"] for s in settle["steps"] if "run" in s][-1] == f"knos settle {EVENT}"


def test_an_assigned_issue_pays_only_its_assignee(tmp_path, capsys):
    from knos import judge
    issue = {"number": 7, "assignees": [{"login": "hubot", "id": 1}, {"login": "mona", "id": 4242}]}
    mine, theirs = _pull(), _pull(login="eve", uid=666)
    assert judge.assignment_check(issue, mine, judge.payee(mine)) == []
    assert judge.assignment_check({"number": 7, "assignees": []}, theirs, judge.payee(theirs)) == []      # open to anyone
    assert judge.assignment_check(None, theirs, judge.payee(theirs)) == []                                # GitHub did not answer
    said = judge.assignment_check(issue, theirs, judge.payee(theirs))
    assert said == ["assigned: issue #7 is assigned to @hubot, @mona; only an assignee's pull request is paid for it"]
    assert judge.payee(mine, issue)["id"] == 4242 and judge.payee(theirs, issue)["kind"] == "assigned"   # payee, given the issue, says the same
    # an agent an assignee ran: the bot wrote the pull request, the assignee claimed it and is paid
    bot = _pull(login="copilot-swe-agent[bot]", uid=198982749, kind="Bot", assignees=[("mona", 4242)])
    assert judge.payee(bot, issue, None, [_comment(1, "mona", 4242, "/knos mine")])["id"] == 4242
    assert judge.payee(bot, issue, None, [_comment(1, "eve", 666, "/knos mine")])["id"] is None
    # through the command the workflow runs: the event file in, the refusal out, the payee in the evidence
    base = tmp_path / "base"
    base.mkdir()
    event, issue_file, ev = tmp_path / "event.json", tmp_path / "issue.json", tmp_path / "evidence.json"
    issue_file.write_text(json.dumps(issue), encoding="utf-8")
    event.write_text(json.dumps({"pull_request": theirs}), encoding="utf-8")
    rc, out = run(capsys, "proof", "gate", "--base", str(base), "--issue", "7", "--event", str(event),
                  "--issue-file", str(issue_file), "--evidence", str(ev))
    assert rc == 1 and "NO  assigned: issue #7 is assigned to @hubot, @mona" in out
    assert json.loads(ev.read_text(encoding="utf-8"))["evidence"]["payee"]["kind"] == "assigned"
    event.write_text(json.dumps({"pull_request": mine}), encoding="utf-8")
    rc, out = run(capsys, "proof", "gate", "--base", str(base), "--issue", "7", "--event", str(event),
                  "--issue-file", str(issue_file), "--evidence", str(ev))
    assert rc == 0 and "paid to @mona (GitHub user id 4242): the pull request's author" in out
    rc, out = run(capsys, "proof", "payee", "--event", str(event))
    assert rc == 0 and out.strip() == "4242"
    event.write_text(json.dumps({"pull_request": _pull(login="x[bot]", uid=5, kind="Bot")}), encoding="utf-8")
    rc, out = run(capsys, "proof", "payee", "--event", str(event))
    assert rc == 1 and "`/knos pay @login`" in out


# ---- knos proof run ----------------------------------------------------------------------------------------------

def _repo(tmp_path: Path, toml: str) -> Path:
    repo = tmp_path / "repo"
    (repo / ".knos").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".knos" / "proof.toml").write_text(toml, encoding="utf-8")
    return repo


def test_proof_run_passes_when_every_check_passes(knos_home, tmp_path, capsys):
    repo = _repo(tmp_path, '[[check]]\nname = "a"\nrun = "exit 0"\n[[check]]\nname = "b"\nrun = "exit 0"\n')
    rc, said = run(capsys, "proof", "run", "--in", str(repo))
    assert rc == 0, said
    assert "custom:a" in said and "custom:b" in said and "proven" in said


def test_proof_run_fails_when_one_check_fails(knos_home, tmp_path, capsys):
    repo = _repo(tmp_path, '[[check]]\nname = "a"\nrun = "exit 0"\n[[check]]\nname = "b"\nrun = "exit 3"\n')
    rc, said = run(capsys, "proof", "run", "--in", str(repo))
    assert rc == 1
    assert "NO  custom:b" in said and "not proven" in said


def test_proof_run_reads_the_toml_it_is_given(knos_home, tmp_path, capsys):
    repo = _repo(tmp_path, '[[check]]\nname = "pr"\nrun = "exit 0"\n')   # what the pull request says
    base = tmp_path / "base.toml"
    base.write_text('[[check]]\nname = "base"\nrun = "exit 1"\n', encoding="utf-8")   # what the base branch says
    rc, said = run(capsys, "proof", "run", "--in", str(repo), "--toml", str(base))
    assert rc == 1 and "custom:base" in said and "custom:pr" not in said


def test_proof_run_with_no_checks_proves_nothing(knos_home, tmp_path, capsys):
    repo = _repo(tmp_path, 'tests = "pytest"\n')
    rc, said = run(capsys, "proof", "run", "--in", str(repo))
    assert rc == 1 and "nothing to prove" in said
