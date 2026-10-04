"""The gate with a bounty's terms: a description's words can be found false, and they never stand in for a check.
The cases a reviewer reproduced against 0.3.11 are the first two tests."""

from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path

import pytest

from _hub import BOT, Hub, comment, run, status, user
from knos import closing, judge, terms
from knos.cli import main
from knos.proof import claims, history

MONA, EVE, HUBOT = user("mona", 4242), user("eve", 666), user("hubot", 1)
DEVIN = user("devin-ai-integration[bot]", 158243242, "Bot")
BOUGHT = {"accept": "", "checks": [{"app": 15368, "name": "tests"}], "deny": [".github/**", ".knos/**"], "mode": "merge",
          "paths": [], "reserve": 7, "v": 1}
NONE = "claim: the description claims tests pass; GitHub has no check runs for this commit"
ROOT = Path(__file__).resolve().parents[1]


def cli(capsys, *args: str) -> tuple[int, str]:
    rc = main(list(args))
    got = capsys.readouterr()
    return rc, got.out + got.err


# ---- the description's claims ----------------------------------------------------------------------------------------

def test_a_claim_on_a_commit_with_no_check_runs_is_refused_at_the_merge():
    """0.3.11 let "All tests pass" through when the commit had no check runs at all: nothing failed, so nothing was
    held against it. At the merged commit that is a claim nothing bears out."""
    body = "Fixes #7. All tests pass."
    assert judge.claim_check(body, [], strict=True) == [NONE]
    assert judge.claim_check("CI is green.", [], strict=True) == ["claim: the description claims CI is green; GitHub has no check runs for this commit"]
    assert judge.claim_check("CI is green and the tests pass.", [], strict=True) == \
        ["claim: the description claims CI is green and tests pass; GitHub has no check runs for this commit"]
    # Knos's own jobs are not check runs about the code
    assert judge.claim_check(body, [run("prove / check"), run("knos / gate", "failure"), run("check / claims")], strict=True) == [NONE]
    # before a merge it is reported, and not held against the pull request (CI may not have started)
    assert judge.claim_check(body, []) == []
    report = judge.claim_report(body, [])
    assert report == {"said": "tests pass", "state": "unverified", "violations": [], "facts": [], "checks": {},
                      "unverified": ["the description claims tests pass; GitHub has no check runs for this commit"]}
    # a check that was skipped did not pass: nothing bears the claim out either
    skipped = [run("tests", "skipped"), run("lint", "neutral")]
    assert judge.claim_check(body, skipped, strict=True) == ["claim: the description claims tests pass; no check passed at this commit (skipped: lint, tests)"]
    assert judge.claim_check(body, skipped) == [] and judge.claim_report(body, skipped)["state"] == "unverified"
    assert judge.claim_check(body, [run("tests", "skipped"), run("lint")], strict=True) == []          # one passed, none failed


def test_a_ticked_template_box_is_held_to_the_record_and_an_unticked_one_is_not():
    """A ticked box is the author asserting its words; an unticked one, or a template's instruction in an HTML comment,
    asserts nothing. 0.3.13 had both backwards for a checklist: it did not read a ticked "My PR passes all CI/CD
    checks", and it held an unticked "- [ ] All tests pass" against a failed check."""
    failing = [run("All Other Providers / Run tests", "failure"), run("lint")]
    ticked = ("## Pre-Submission checklist\r\n\r\n- [x] I have added meaningful tests\r\n"
              "- [x] My PR passes all CI/CD checks (e.g., lint, format, unit tests)\r\n")
    assert judge.claim_check(ticked, failing) == \
        ["claim: the description says CI is green, but these checks failed at the head commit: All Other Providers / Run tests"]
    report = judge.claim_report(ticked.replace("- [x] My PR", "- [ ] My PR"), failing, strict=True)
    assert report["said"] == "" and report["state"] == "none" and report["violations"] == []
    assert report["facts"] == ["checks failing: All Other Providers / Run tests"]                   # still said, as a fact
    for silent in ("Fixes #7.\n- [ ] All tests pass", "Fixes #7.\n<!-- Make sure CI is green -->"):
        assert judge.claim_check(silent, failing, strict=True) == [], silent


def test_a_hedged_sentence_never_causes_a_refusal():
    """A sentence that hedges, negates or instructs claims nothing, so with every check failed it is never refused,
    before a merge or at it, and the report says nothing was claimed. The same words asserted are refused."""
    failing = [run("tests", "failure"), run("lint", "failure")]
    hedged = ["Fixes #7. All tests should pass.", "Fixes #7. Please make sure CI is green.", "Fixes #7. Please ensure the tests pass.",
              "Fixes #7. The tests do not pass yet.", "Fixes #7. Tests don't pass on Windows.", "TODO: make tests pass",
              "Fixes #7. Tests must pass before merging.", "Fixes #7. CI will be green once the cache is warm.",
              "Fixes #7. Unit tests pass, except the flaky e2e job.", "Fixes #7.\n- [ ] All tests pass\n* [ ] CI is green"]
    words = ("ensure", "make sure", "verify that", "should", "would", "will", "to confirm", "until", "once", "if", "before", "whether",
             "need", "needs", "must", "expect", "expected", "todo", "not", "can't", "fail", "fails", "failing", "failed", "failure",
             "failures", "error", "errors", "except", "unless", "pending", "flaky", "skip", "red", "broken")
    hedged += [f"Fixes #7. All tests pass and CI is green ({word})." for word in words]
    for body in hedged:
        for strict in (False, True):
            assert judge.claim_check(body, failing, strict) == [], (body, strict)
        report = judge.claim_report(body, failing, strict=True)
        assert report["said"] == "" and report["state"] == "none" and report["facts"] == ["checks failing: lint, tests"], body
    assert judge.claim_check("Fixes #7. All tests pass and CI is green.", failing) == \
        ["claim: the description says CI is green and tests pass, but these checks failed at the head commit: lint, tests"]


def test_the_sites_examples_are_judged_here_as_the_site_shows_them():
    """The first screen's two claims (web/config.js) are pull requests of docs/agent_pr_ci.json, recorded with the line
    the site quotes and the checks that failed in tests/web/recorded/example_prs.json. "A claim that is false" is
    BerriAI/litellm#34321, a ticked "My PR passes all CI/CD checks" whose head commit had a failed check: the site
    showed it FALSE while `knos check` answered that the description did not say tests pass. Both read it the same way."""
    config = (ROOT / "web" / "config.js").read_text(encoding="utf-8")
    shown = dict(re.findall(r'\{ id: "(\w+)", label: "A claim that is \w+", input: "([^"]+)"', config))
    assert set(shown) == {"true", "false"}
    recorded = json.loads((ROOT / "tests" / "web" / "recorded" / "example_prs.json").read_text(encoding="utf-8"))["prs"]
    by_url = {f"https://github.com/{p['repo']}/pull/{p['number']}": p for p in recorded}
    for verdict, url in shown.items():
        pr = by_url[url]
        assert {"passed": "true", "failed": "false"}[pr["class"]] == verdict
        assert claims.read(pr["claim_line"]).kinds & {"tests", "ci"}, pr["claim_line"]
        report = judge.claim_report(pr["claim_line"], [run("lint")] + [run(name, "failure") for name in pr["failed_checks"]])
        assert report["state"] == verdict, (url, report)


def test_no_claim_and_a_failing_check_is_not_a_false_claim_and_is_not_paid_on_terms(tmp_path):
    """0.3.11 paid a merged pull request whose checks failed as long as its description claimed nothing. A silent
    description is still not a false claim; whether the work is paid is the terms' verdict, the same for any words."""
    failing, passing = [run("tests", "failure"), run("lint")], [run("tests"), run("lint")]
    for strict in (False, True):
        assert judge.claim_check("Fixes #7.", failing, strict) == []
    report = judge.claim_report("Fixes #7.", failing, strict=True)
    assert report["state"] == "none" and report["said"] == "" and report["facts"] == ["checks failing: tests"]
    store = history.SibylStore.local(tmp_path / "mem")
    free = judge.gate(tmp_path, "", store, "o/r", "agent", "Fixes #7.", failing, strict=True)
    assert free["passed"] and free["evidence"]["facts"] == ["checks failing: tests"] and free["evidence"]["accepted"] is None
    assert free["evidence"]["learned"] == []                                               # nothing false was said: nothing to learn
    verdicts = {}
    for words in ("Fixes #7.", "Fixes #7. All tests pass.", "Fixes #7. CI is green, trust me."):
        for name, runs in (("failing", failing), ("passing", passing)):
            got = judge.gate(tmp_path, "", history.NullStore(), "o/r", "agent", words, runs, strict=True, terms=BOUGHT, statuses=[], changed=["a.py"])
            verdicts[words, name] = got["evidence"]["accepted"]
            assert ("terms: required check `tests` failed at this commit" in got["reasons"]) == (name == "failing")
            assert got["evidence"]["checks"] == {"tests": "failed" if name == "failing" else "passed"}
            assert got["evidence"]["terms_hash"] == terms.terms_hash(BOUGHT)
    assert verdicts == {(w, n): n == "passing" for w, n in verdicts}                       # the words changed nothing
    silent = judge.gate(tmp_path, "", history.NullStore(), "o/r", "agent", "Fixes #7.", failing, strict=True, terms=BOUGHT, statuses=[], changed=["a.py"])
    assert not silent["passed"] and silent["reasons"] == ["terms: required check `tests` failed at this commit"]
    assert silent["evidence"]["claims"] == [] and silent["evidence"]["facts"] == ["checks failing: tests"]


def test_a_claim_is_judged_on_githubs_record_in_the_states_the_terms_use(tmp_path):
    body = "All tests pass."
    mixed = [run("unit"), run("e2e", "timed_out"), run("docs", "skipped"), run("slow", None, status="in_progress"),
             run("stale", "stale"), run("prove / check", "failure")]
    report = judge.claim_report(body, mixed, statuses=[status("ci/x", "error"), status("ci/y")])
    assert report["checks"] == {"ci/x": "failed", "ci/y": "passed", "docs": "skipped", "e2e": "failed", "slow": "pending",
                                "stale": "failed", "unit": "passed"}
    assert report["state"] == "false" and report["facts"] == ["checks failing: ci/x, e2e, stale"]
    assert report["violations"] == ["claim: the description says tests pass, but these checks failed at the head commit: ci/x, e2e, stale"]
    assert judge.claim_check(body, mixed) == ["claim: the description says tests pass, but these checks failed at the head commit: e2e, stale"]
    assert judge.claim_report(body, [run("unit"), run("unit", "failure")])["checks"] == {"unit": "failed"}     # one name, the worse run
    ok = judge.claim_report(body, [run("unit"), run("docs", "skipped")], strict=True)
    assert ok["state"] == "true" and ok["violations"] == [] == ok["unverified"] == ok["facts"]
    # unfinished or unreadable: not held against it before a merge, refused at the merge until it can be checked
    running = [run("unit"), run("slow", None, status="queued")]
    assert judge.claim_report(body, running) == {
        "said": "tests pass", "state": "unverified", "violations": [], "facts": [], "checks": {"slow": "pending", "unit": "passed"},
        "unverified": ["the description says tests pass, and these checks have not finished at the head commit: slow"]}
    assert judge.claim_check(body, running, strict=True) == \
        ["claim: the description says tests pass, and these checks have not finished at the head commit: slow; run this job again when they have"]
    assert judge.claim_report(body, None)["unverified"] == ["the description says tests pass, and GitHub's record of the head commit could not be read"]
    assert judge.claim_check(body, None, strict=True) == \
        ["claim: the description says tests pass, and GitHub's record of the head commit could not be read; run this job again"]
    assert judge.claim_report("Refactors the parser.", None, strict=True) == {"said": "", "state": "none", "violations": [], "unverified": [],
                                                                               "facts": [], "checks": None}
    assert judge.claim_report(None, [run("unit")])["state"] == "none"
    # a failure is final, whatever else is still running; and only a false claim is learned, not an unverified one
    assert "failed at the head commit: e2e" in judge.claim_check(body, [run("e2e", "failure"), run("slow", None, status="queued")])[0]
    store = history.SibylStore.local(tmp_path / "mem")
    assert not judge.gate(tmp_path, "", store, "o/r", "agent", body, [], strict=True)["passed"]
    assert history.tamper_checks_required(store, "o/r", "agent") == set()
    lie = judge.gate(tmp_path, "", store, "o/r", "agent", body, mixed)
    assert not lie["passed"] and lie["evidence"]["learned"] == ["tamper:false-claim"] and lie["evidence"]["unverified"] == []
    unverified = judge.gate(tmp_path, "", history.NullStore(), "o/r", "agent", body, [])
    assert unverified["passed"] and unverified["evidence"]["unverified"] == ["the description claims tests pass; GitHub has no check runs for this commit"]


# ---- the gate with terms, who is paid, and a mention -----------------------------------------------------------------

def test_the_gate_holds_a_bountys_pull_request_to_the_terms_and_to_who_is_paid(tmp_path):
    runs, changed = [run("tests")], ["src/a.py"]
    pull = {"number": 12, "user": MONA, "body": "Fixes #7", "assignees": []}

    def gate(**kw):
        kw = {"body": "Fixes #7", "check_runs": runs, "issue": "7", "pull": pull, "paid": judge.payee(pull), "terms": BOUGHT,
              "statuses": [], "changed": changed, **kw}
        return judge.gate(tmp_path, "", history.NullStore(), "o/r", "mona", **kw)
    ok = gate()
    assert ok["passed"] and ok["reasons"] == [] and ok["evidence"]["accepted"] is True and ok["evidence"]["payee"]["id"] == 4242
    assert ok["evidence"]["payable"] is True
    # what a payment is decided on is the terms and who is paid: a false claim fails the check and leaves that as it is
    lie = gate(body="Fixes #7. CI is green.", check_runs=[run("tests"), run("lint", "failure")])
    assert not lie["passed"] and lie["reasons"][0].startswith("claim: ") and lie["evidence"]["payable"] is True
    rule = judge.gate(tmp_path, "", history.NullStore(), "o/r", "mona", "Fixes #7", runs, "7", pull, None, judge.payee(pull), terms=BOUGHT,
                      statuses=[], changed=None)
    assert rule["evidence"]["payable"] is False and rule["evidence"]["accepted"] is False
    assert judge.gate(tmp_path, "", history.NullStore(), terms=BOUGHT, check_runs=runs, statuses=[], changed=changed)["evidence"]["payable"] is None
    assert gate(changed=["src/a.py", ".github/workflows/ci.yml"])["reasons"] == \
        ["terms: changes `.github/workflows/ci.yml`, which this bounty does not allow (`.github/**`)"]
    assert gate(changed=None)["reasons"] == ["terms: the pull request's changed files could not be read from GitHub; try again"]
    assert gate(check_runs=None)["reasons"] == ["terms: required check `tests` could not be read from GitHub; try again"]
    assert gate(check_runs=[])["reasons"] == ["terms: required check `tests` did not run on this commit"]
    by_status = {**BOUGHT, "checks": [{"app": 0, "name": "ci/x"}]}
    assert gate(terms=by_status, statuses=[status("ci/x")])["passed"] and not gate(terms=by_status, statuses=None)["passed"]
    assert gate(terms={**BOUGHT, "checks": []}, check_runs=[])["evidence"]["accepted"] is True          # the merge alone is the acceptance
    # who is paid: nobody, with what would fix it; an issue someone else holds; a maintainer's reject
    bot = {**pull, "user": DEVIN}
    nobody = gate(pull=bot, paid=judge.payee(bot))
    assert nobody["reasons"] == ["payee: devin-ai-integration[bot] is a bot account, and nothing GitHub authenticates names the person "
                                 "who ran it. A maintainer comments `/knos pay @login` on this pull request."]
    assert nobody["evidence"]["accepted"] is True and not nobody["passed"]                 # the terms are met; nobody to pay
    assert nobody["evidence"]["payable"] is False
    held = {"number": 7, "assignees": [EVE]}
    assert gate(issue_data=held)["reasons"] == ["assigned: issue #7 is assigned to @eve; only an assignee's pull request is paid for it"]
    theirs = judge.payee(pull, held)
    assert gate(issue_data=held, paid=theirs)["reasons"] == \
        ["assigned: issue #7 is assigned to @eve; only an assignee's pull request is paid for it. A maintainer can change the "
         "issue's assignee; a `/knos take` lapses on the date shown."]
    no = judge.payee(pull, held, [], [comment(1, HUBOT, "/knos reject wrong approach")], [], lambda login: "admin")
    assert gate(paid=no)["reasons"] == ["rejected: @hubot rejected this pull request for the bounty (wrong approach). To undo, @hubot "
                                        "deletes that `/knos reject` comment."]
    assert gate(paid={"id": None, "why": "nothing names anyone"})["reasons"] == ["payee: nothing names anyone"]   # a payee from older code
    assert judge.gate(tmp_path, "", history.NullStore(), pull=pull)["passed"]              # no payee worked out: none demanded


def test_an_assignment_holds_until_it_is_changed_and_a_take_until_it_lapses(tmp_path):
    pull = {"number": 12, "user": EVE}
    issue = {"number": 7, "assignees": [MONA]}
    now = 1_790_000_000.0
    took = [{"event": "assigned", "assignee": MONA, "assigner": BOT, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 86_400))}]
    assert judge.assignment_check(issue, pull, {"id": 666}) == ["assigned: issue #7 is assigned to @mona; only an assignee's pull request is paid for it"]
    assert "until" in judge.assignment_check(issue, pull, {"id": 666}, took, BOUGHT, now)[0]
    assert judge.assignment_check(issue, pull, {"id": 666}, took, BOUGHT, now + 7 * 86_400) == []       # lapsed: open to anyone
    assert judge.assignment_check(issue, pull, {"id": 4242}) == [] == judge.assignment_check(None, pull, {"id": 666})
    assert judge.assignment_check({"number": 7, "assignees": []}, pull, {"id": 666}) == []
    # the gate reads the same events at the same time as payee did, so the two never disagree about a take that lapsed
    for at, held in ((now, True), (now + 7 * 86_400, False)):
        paid = judge.payee(pull, issue, took, [], [], None, BOUGHT, at)
        got = judge.gate(tmp_path, "", history.NullStore(), "o/r", "eve", "Fixes #7", [run("tests")], "7", pull, issue, paid, terms=BOUGHT,
                         statuses=[], changed=["a.py"], events=took, now=at)
        assert (paid["id"] is None) == held and got["passed"] == (not held) and got["evidence"]["payable"] == (not held), at
        assert [r.split(":")[0] for r in got["reasons"]] == (["assigned"] if held else [])


def test_a_description_that_mentions_a_funded_issue_without_closing_it_is_told_what_to_write(tmp_path):
    def notes(body, funded):
        return judge.gate(tmp_path, "", history.NullStore(), "o/r", "a", body, funded=funded)
    said = notes("This relates to #30.", [30, 31])
    assert said["passed"] and said["evidence"]["notes"] == ["This mentions funded issue #30 but does not close it. If this pull request "
                                                            "is for that bounty, write `Fixes #30` in its description."]
    assert notes("Fixes #30.", [30])["evidence"]["notes"] == [] == notes("This relates to #30.", [])["evidence"]["notes"]
    assert notes("See o/r#31 and x/y#30", [30, 31])["evidence"]["notes"][0].startswith("This mentions funded issue #31 ")


# ---- knos proof gate, knos proof payee -------------------------------------------------------------------------------

@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A pull request by a bot on a repository GitHub answers for, and the files `knos proof gate` is handed."""
    base = tmp_path / "base"
    base.mkdir()
    pull = {"number": 12, "user": DEVIN, "body": "Fixes #7\n\nRequested by: @mona", "assignees": [MONA], "head": {"sha": "a" * 40}}
    (tmp_path / "event.json").write_text(json.dumps({"action": "opened", "pull_request": pull}), encoding="utf-8")
    (tmp_path / "terms.json").write_bytes(terms.canonical(BOUGHT))
    (tmp_path / "changed.txt").write_text("src/a.py\n", encoding="utf-8")
    (tmp_path / "body.md").write_text(pull["body"] + "\n\nSee also #30. All tests pass.", encoding="utf-8")
    hub = Hub({"repos/o/r/issues/7": {"number": 7, "assignees": []}, "repos/o/r/issues/7/events": [], "repos/o/r/issues/7/comments": [],
               "repos/o/r/issues/12/comments": [comment(1, MONA, "/knos mine"), comment(2, MONA, "/knos address 4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo")],
               "repos/o/r/commits/" + "a" * 40: {"commit": {"message": "Fix\n\nCo-authored-by: m <4242+mona@users.noreply.github.com>"}},
               "repos/o/r/commits/" + "a" * 40 + "/check-runs": {"total_count": 2, "check_runs": [run("tests"), run("lint", "failure")]},
               "repos/o/r/commits/" + "a" * 40 + "/status": {"total_count": 0, "statuses": []},
               "repos/o/r/pulls/12": pull, "repos/o/r/collaborators/hubot/permission": {"permission": "admin"}})
    monkeypatch.setattr("knos.judge.github", hub)
    return tmp_path, hub


def test_knos_proof_gate_reads_what_decides_from_github_and_says_each_thing_it_found(repo, capsys):
    tmp, hub = repo
    args = ["proof", "gate", "--base", str(tmp / "base"), "--repo", "o/r", "--issue", "7", "--event", str(tmp / "event.json"),
            "--head", "a" * 40, "--body-file", str(tmp / "body.md"), "--terms", str(tmp / "terms.json"), "--changed", str(tmp / "changed.txt"),
            "--funded", "7, 30", "--evidence", str(tmp / "ev.json")]
    rc, out = cli(capsys, *args)
    assert rc == 1 and out.splitlines() == [
        "passed     tests",
        "NOTE checks failing: lint",
        "NOTE This mentions funded issue #30 but does not close it. If this pull request is for that bounty, write `Fixes #30` in its description.",
        "paid to @mona (GitHub user id 4242): named in the assignees of devin-ai-integration[bot]'s pull request, and claimed it with `/knos mine`",
        "NOTE its text names @mona, which is a hint and decides nothing",
        "NO  claim: the description says tests pass, but these checks failed at the head commit: lint",
        "not proven"]
    ev = json.loads((tmp / "ev.json").read_text())["evidence"]
    assert ev["accepted"] is True and ev["checks"] == {"tests": "passed"} and ev["payee"]["id"] == 4242 and ev["checks_seen"] == 2
    # without the claim the same commit passes: the failed check is not one the bounty bought
    (tmp / "body.md").write_text("Fixes #7", encoding="utf-8")
    rc, out = cli(capsys, *args, "--strict")
    assert rc == 0 and out.splitlines()[-1] == "proven" and "NOTE checks failing: lint" in out
    # no --changed: GitHub's own list of the pull request's files, where a renamed file counts where it came from too
    unlisted = [a for a in args if a not in ("--changed", str(tmp / "changed.txt"))]
    rc, out = cli(capsys, *unlisted)
    assert rc == 1 and "NO  terms: the pull request's changed files could not be read from GitHub; try again" in out
    hub.answers["repos/o/r/pulls/12/files"] = [{"filename": "docs/ci.yml", "previous_filename": ".github/workflows/ci.yml", "status": "renamed"}]
    rc, out = cli(capsys, *unlisted)
    assert rc == 1 and "NO  terms: changes `.github/workflows/ci.yml`, which this bounty does not allow (`.github/**`)" in out
    hub.answers["repos/o/r/pulls/12/files"] = [{"filename": "src/a.py"}]
    rc, out = cli(capsys, *unlisted)
    assert rc == 0 and out.splitlines()[-1] == "proven"
    (tmp / "quoted.txt").write_text('"src/\\303\\251.py"\n".knos/acceptance/7/t\\303\\251st.py"\n', encoding="utf-8")   # as git writes such names
    rc, out = cli(capsys, *unlisted, "--changed", str(tmp / "quoted.txt"))
    assert rc == 1 and "NO  terms: changes `.knos/acceptance/7/t\u00e9st.py`, which this bounty does not allow (`.knos/**`)" in out
    # no bounty: the free check alone, on the same record; and what the judge's memory holds against this repository is said first
    rc, out = cli(capsys, "proof", "gate", "--base", str(tmp / "base"), "--repo", "o/r", "--head", "a" * 40, "--body-file", str(tmp / "body.md"))
    assert rc == 0 and out.splitlines() == ["NOTE checks failing: lint", "proven"]
    history.learn_tamper(history.SibylStore.local(tmp / "mem"), "o/r", "someone", "false-claim", "said tests pass; lint failed")
    rc, out = cli(capsys, "proof", "gate", "--base", str(tmp / "base"), "--repo", "o/r", "--head", "a" * 40, "--store", str(tmp / "mem"))
    assert rc == 0 and out.splitlines()[0] == "REQUIRED by this repo's history: tamper:false-claim"
    # the pull request by its number instead of an event; the checks from files instead of GitHub
    (tmp / "runs.json").write_text(json.dumps([run("tests", "failure")]), encoding="utf-8")
    rc, out = cli(capsys, "proof", "gate", "--base", str(tmp / "base"), "--repo", "o/r", "--issue", "7", "--pull", "12",
                  "--checks-file", str(tmp / "runs.json"), "--terms", str(tmp / "terms.json"), "--changed", str(tmp / "changed.txt"))
    assert rc == 1 and "failed     tests" in out and "NO  terms: required check `tests` failed at this commit" in out
    (tmp / "statuses.json").write_text(json.dumps([status("tests")]), encoding="utf-8")
    (tmp / "terms.json").write_bytes(terms.canonical({**BOUGHT, "checks": [{"app": 0, "name": "tests"}]}))
    rc, out = cli(capsys, "proof", "gate", "--base", str(tmp / "base"), "--checks-file", str(tmp / "runs.json"), "--statuses-file",
                  str(tmp / "statuses.json"), "--terms", str(tmp / "terms.json"), "--changed", str(tmp / "changed.txt"))
    assert rc == 0 and "passed     tests" in out
    cut = {"total_count": 150, "check_runs": [run("tests")] * 100}                         # GitHub's own answer, one page of two
    (tmp / "runs.json").write_text(json.dumps(cut), encoding="utf-8")
    rc, out = cli(capsys, "proof", "gate", "--base", str(tmp / "base"), "--checks-file", str(tmp / "runs.json"), "--statuses-file",
                  str(tmp / "statuses.json"), "--terms", str(tmp / "terms.json"), "--changed", str(tmp / "changed.txt"), "--evidence", str(tmp / "ev.json"))
    assert rc == 0 and json.loads((tmp / "ev.json").read_text())["evidence"]["checks_seen"] is None      # read as unreadable, not as whole
    (tmp / "terms.json").write_bytes(terms.canonical(BOUGHT))
    rc, out = cli(capsys, "proof", "gate", "--base", str(tmp / "base"), "--checks-file", str(tmp / "runs.json"), "--terms", str(tmp / "terms.json"),
                  "--changed", str(tmp / "changed.txt"))
    assert rc == 1 and "unreadable tests" in out and "NO  terms: required check `tests` could not be read from GitHub; try again" in out
    rc, out = cli(capsys, "proof", "gate", "--base", str(tmp / "base"), "--repo", "o/r", "--pull", "404")
    assert rc == 1 and out.startswith("GitHub did not answer for o/r#404")
    (tmp / "terms.json").write_text("{}", encoding="utf-8")
    rc, out = cli(capsys, "proof", "gate", "--base", str(tmp / "base"), "--terms", str(tmp / "terms.json"))
    assert rc == 1 and "terms.json: a bounty's terms have exactly these fields" in out


def test_knos_proof_payee_prints_who_is_paid_or_what_would_fix_it(repo, capsys):
    tmp, hub = repo
    rc, out = cli(capsys, "proof", "payee", "--event", str(tmp / "event.json"), "--repo", "o/r", "--issue", "7")
    assert rc == 0 and out.strip() == "4242"
    rc, out = cli(capsys, "proof", "payee", "--repo", "o/r", "--pull", "12", "--issue", "7", "--json", "--terms", str(tmp / "terms.json"))
    got = json.loads(out)
    assert rc == 0 and got["id"] == 4242 and got["login"] == "mona" and got["hint"].startswith("its text names @mona")
    assert got["address"] == {"address": "4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo", "from": "comment", "comment": 2,
                              "why": "@mona's `/knos address` comment on this pull request"}
    rc, out = cli(capsys, "proof", "payee", "--repo", "o/r", "--pull", "12", "--json", "--bound", "AT1aKj1DpgaWerxmS4YjDkNpWPNUtCCKVDvxLhFxg5Jc")
    assert json.loads(out)["address"]["from"] == "bound"
    # the head commit's message is only ever a hint: when GitHub does not give it, or there is no head, nothing changes
    del hub.answers["repos/o/r/commits/" + "a" * 40]
    rc, out = cli(capsys, "proof", "payee", "--repo", "o/r", "--pull", "12", "--issue", "7")
    assert rc == 0 and out.strip() == "4242"
    headless = {"pull_request": {k: v for k, v in json.loads((tmp / "event.json").read_text())["pull_request"].items() if k != "head"}}
    (tmp / "headless.json").write_text(json.dumps(headless), encoding="utf-8")
    rc, out = cli(capsys, "proof", "payee", "--event", str(tmp / "headless.json"), "--repo", "o/r", "--issue", "7")
    assert rc == 0 and out.strip() == "4242"
    # a pull request handed over as a file, with nothing asked of GitHub: a bot's pays nobody, and says what to type
    (tmp / "pull.json").write_text(json.dumps(json.loads((tmp / "event.json").read_text())["pull_request"]), encoding="utf-8")
    hub.asked.clear()
    rc, out = cli(capsys, "proof", "payee", "--event", str(tmp / "pull.json"))
    assert rc == 1 and hub.asked == [] and out.splitlines() == [
        "devin-ai-integration[bot] is a bot account, and nothing GitHub authenticates names the person who ran it.",
        "A maintainer comments `/knos pay @mona` on this pull request, or @mona (named in its assignees) comments `/knos mine`."]
    rc, out = cli(capsys, "proof", "payee", "--event", str(tmp / "pull.json"), "--json")
    assert rc == 1 and json.loads(out)["id"] is None and json.loads(out)["address"] == {"address": None, "from": None, "why": "nobody is paid"}
    # the issue is someone else's
    hub.answers["repos/o/r/issues/7"] = {"number": 7, "assignees": [EVE]}
    rc, out = cli(capsys, "proof", "payee", "--repo", "o/r", "--pull", "12", "--issue", "7")
    assert rc == 1 and out.startswith("issue #7 is assigned to @eve; only an assignee's pull request is paid for it.")
    # at the merge, a failed read pays nobody yet; with no issue named there is no bounty to be strict about
    del hub.answers["repos/o/r/issues/12/comments"]
    rc, out = cli(capsys, "proof", "payee", "--repo", "o/r", "--pull", "12", "--issue", "9", "--strict")
    assert rc == 1 and out.splitlines() == ["GitHub did not give the issue, so who is paid cannot be decided yet.", "Run this again."]
    hub.answers["repos/o/r/issues/7"] = {"number": 7, "assignees": []}
    rc, out = cli(capsys, "proof", "payee", "--repo", "o/r", "--pull", "12", "--issue", "7", "--strict")
    assert rc == 1 and out.startswith("GitHub did not give this pull request's comments")
    rc, out = cli(capsys, "proof", "gate", "--base", str(tmp / "base"), "--repo", "o/r", "--pull", "12", "--issue", "7", "--strict")
    assert rc == 1 and "NO  unread: GitHub did not give this pull request's comments, so who is paid cannot be decided yet. Run this again." in out
    rc, out = cli(capsys, "proof", "gate", "--base", str(tmp / "base"), "--repo", "o/r", "--pull", "12", "--strict")
    assert rc == 1 and "NO  payee: devin-ai-integration[bot] is a bot account" in out      # not strict about a bounty nobody named
    hub.answers["repos/o/r/issues/12/comments"] = [comment(1, MONA, "/knos mine")]
    # at the merge it must close the issue: by GitHub's own list of what it closes, or by its description
    for n, name in ((8, "eight"), (9, "nine")):
        (tmp / f"{name}.json").write_text(json.dumps({"number": n, "assignees": []}), encoding="utf-8")
    rc, out = cli(capsys, "proof", "payee", "--repo", "o/r", "--pull", "12", "--issue", "7", "--strict")
    assert rc == 0 and out.strip() == "4242" and hub.posted[-1][0] == "graphql"            # asked, and GitHub said no: its description says Fixes #7

    def graphql(numbers):
        nodes = [{"number": n, "repository": {"nameWithOwner": "o/r"}} for n in numbers]
        return lambda path, data: {"data": {"repository": {"pullRequest": {"closingIssuesReferences": {"totalCount": len(nodes), "nodes": nodes}}}}}
    hub.answers["graphql"] = graphql([7])
    rc, out = cli(capsys, "proof", "payee", "--repo", "o/r", "--pull", "12", "--issue", "7", "--strict")
    assert rc == 0 and out.strip() == "4242"
    assert hub.posted[-1] == ("graphql", {"query": closing.QUERY, "variables": {"owner": "o", "name": "r", "number": 12}})
    hub.answers["graphql"] = graphql([8])
    rc, out = cli(capsys, "proof", "payee", "--repo", "o/r", "--pull", "12", "--issue", "8", "--strict", "--issue-file", str(tmp / "eight.json"))
    assert rc == 0 and out.strip() == "4242"                                               # linked by hand: no keyword in the description
    rc, out = cli(capsys, "proof", "payee", "--repo", "o/r", "--pull", "12", "--issue", "9", "--strict", "--issue-file", str(tmp / "nine.json"))
    assert rc == 1 and out.splitlines() == ["this pull request does not close issue #9.", "Its description must say `Fixes #9`."]
    posted = len(hub.posted)
    rc, out = cli(capsys, "proof", "payee", "--repo", "o/r", "--pull", "12", "--issue", "7")
    assert rc == 0 and len(hub.posted) == posted                                           # asked only where money moves
    # the issues a pull request closes, for the job that pays at the merge: GitHub's list, then its description's
    rc, out = cli(capsys, "proof", "closes", "--repo", "o/r", "--pull", "12")
    assert rc == 0 and out.split() == ["8", "7"]
    rc, out = cli(capsys, "proof", "closes", "--event", str(tmp / "event.json"))
    assert rc == 0 and out.split() == ["7"]                                                # nothing asked of GitHub: the description alone
    rc, out = cli(capsys, "proof", "closes")
    assert rc == 1 and out.strip() == "not a pull request: pass --event, or --repo and --pull"
    del hub.answers["graphql"]
    hub.answers["repos/o/r/issues/7"] = {"number": 7, "assignees": [EVE]}
    (tmp / "issue.json").write_text(json.dumps({"number": 7, "assignees": []}), encoding="utf-8")
    rc, out = cli(capsys, "proof", "payee", "--repo", "o/r", "--pull", "12", "--issue", "7", "--issue-file", str(tmp / "issue.json"))
    assert rc == 0 and out.strip() == "4242"
    # a tip: decided on the merged pull request alone, so the issue (someone else's here) is not even asked about
    hub.asked.clear()
    rc, out = cli(capsys, "proof", "payee", "--repo", "o/r", "--pull", "12", "--issue", "7", "--tip")
    assert rc == 1 and out.splitlines() == ["this pull request is not merged.", "A tip is for a merged pull request: merge it first."]
    hub.answers["repos/o/r/pulls/12"] = {**hub.answers["repos/o/r/pulls/12"], "merged_at": "2026-10-01T12:00:00Z"}
    rc, out = cli(capsys, "proof", "payee", "--repo", "o/r", "--pull", "12", "--issue", "7", "--tip", "--strict", "--json",
                  "--issue-file", str(tmp / "nine.json"))
    assert rc == 0 and json.loads(out)["id"] == 4242 and not [p for p in hub.asked if p.startswith("repos/o/r/issues/7")]
    (tmp / "other.json").write_text(json.dumps({"action": "created", "comment": {}}), encoding="utf-8")
    rc, out = cli(capsys, "proof", "payee", "--event", str(tmp / "other.json"))
    assert rc == 1 and "GitHub did not say who opened this pull request" in out
    rc, out = cli(capsys, "proof", "payee")
    assert rc == 1 and out.strip() == "not a pull request: pass --event, or --repo and --pull"


def test_knos_proof_comment_answers_one_comment_and_says_what_is_left_to_do(repo, capsys):
    tmp, hub = repo
    hub.answers["repos/o/r/collaborators/eve/permission"] = {"permission": "read"}

    def said(body, who_, number=12, on_pull=True, *more, **issue):
        on = {"number": number, **({"pull_request": {"url": "x"}} if on_pull else {}), **issue}
        (tmp / "comment.json").write_text(json.dumps({"action": "created", "issue": on, "comment": {"body": body, "user": who_}}), encoding="utf-8")
        hub.asked.clear()
        rc, out = cli(capsys, "proof", "comment", "--event", str(tmp / "comment.json"), "--repo", "o/r", *more)
        return rc, (json.loads(out) if out.strip().startswith("{") else out)
    # on the bot's pull request: its description closes #7, so that issue is read too
    rc, got = said("/knos mine", MONA)
    assert rc == 0 and got == {"command": "mine", "assign": [], "unassign": [], "then": "", "reply": (
        "Knos: noted. This pull request pays @mona: named in the assignees of devin-ai-integration[bot]'s pull request, and claimed it "
        "with `/knos mine`.")}
    assert "repos/o/r/issues/7" in hub.asked and "repos/o/r/pulls/12" in hub.asked
    rc, got = said("/knos pay @mona", EVE)
    assert rc == 0 and got["reply"].startswith("Knos: `/knos pay` is for people with write access to this repository.")
    rc, got = said("/knos pay @mona", user("stranger", 5))                                 # GitHub did not answer about them
    assert rc == 0 and got["reply"].startswith("Knos: GitHub did not answer whether @stranger can write to this repository")
    rc, got = said("/knos reject not this way", HUBOT)
    assert rc == 0 and got["command"] == "reject" and got["reply"].startswith("Knos: noted. This pull request does not take the bounty")
    rc, got = said("/knos tip 5", HUBOT)
    assert rc == 0 and got["then"] == "" and got["reply"].startswith("Knos: this pull request is not merged.") and hub.asked == ["repos/o/r/pulls/12"]
    hub.answers["repos/o/r/pulls/12"] = {**hub.answers["repos/o/r/pulls/12"], "merged_at": "2026-10-01T12:00:00Z"}
    for body, then in (("/knos tip 5", "tip"), ("/knos settle", "settle")):
        rc, got = said(body, HUBOT)
        assert rc == 0 and got["then"] == then and got["command"] == then
    rc, got = said("/knos mine", MONA, 404)
    assert rc == 1 and got.startswith("GitHub did not answer for o/r#404")
    # on an issue: take and release change its assignees; a bounty's terms say for how long
    rc, got = said("/knos take", EVE, 7, False, "--terms", str(tmp / "terms.json"), assignees=[], state="open")
    assert rc == 0 and got["assign"] == ["eve"] and got["unassign"] == [] and got["reply"].startswith("Knos: issue #7 is reserved for @eve until ")
    assert hub.asked == ["repos/o/r/issues/7/events?per_page=100&page=1"]
    rc, got = said("/knos take", EVE, 7, False, assignees=[], state="open")
    assert rc == 0 and got["assign"] == [] and got["reply"] == "Knos: issue #7 has no bounty, so there is nothing to reserve."
    rc, got = said("/knos release", EVE, 7, False, "--terms", str(tmp / "terms.json"), assignees=[EVE])
    assert rc == 0 and got["unassign"] == ["eve"]
    # what needs the chain is handed on, and what is not a command is answered, with nothing asked of GitHub
    for body, on_pull, want in (("Fund it.\n\n/knos fund 20 checks: tests", False, {"command": "fund", "then": "fund", "reply": ""}),
                                ("/knos status", True, {"command": "status", "then": "status", "reply": ""})):
        rc, got = said(body, HUBOT, 7, on_pull)
        assert rc == 0 and {k: got[k] for k in want} == want and hub.asked == [], body
    rc, got = said("/knos frobnicate", EVE)
    assert rc == 0 and got["command"] == "" and got["reply"].startswith("Knos: `frobnicate` is not a command.") and hub.asked == []
    rc, got = said("/knos take", EVE)
    assert rc == 0 and got["reply"] == "Knos: `/knos take` belongs on the issue, not on a pull request. Comment it there."
    rc, got = said("/knos help", EVE)
    assert rc == 0 and got["command"] == "help" and "`/knos fund <amount>" in got["reply"]
    rc, got = said("thanks, merging", HUBOT)
    assert rc == 0 and got == ""                                                           # no command: nothing to post
    # a new issue whose description holds the command: there is no comment in the event
    (tmp / "opened.json").write_text(json.dumps({"action": "opened", "issue": {"number": 9, "body": "Slugs break.\n\n/knos bounty 20", "user": HUBOT}}),
                                     encoding="utf-8")
    rc, out = cli(capsys, "proof", "comment", "--event", str(tmp / "opened.json"), "--repo", "o/r")
    assert rc == 0 and json.loads(out)["then"] == "fund"
    # the issue named by the caller, when the description closes none or several
    hub.answers["repos/o/r/pulls/12"] = {**hub.answers["repos/o/r/pulls/12"], "body": "Fixes #7, fixes #8"}
    rc, got = said("/knos mine", MONA)
    assert rc == 0 and "repos/o/r/issues/7" not in hub.asked and got["reply"].startswith("Knos: noted. This pull request pays @mona")
    hub.answers["repos/o/r/issues/8"] = {"number": 8, "assignees": [EVE]}
    hub.answers["repos/o/r/issues/8/events"] = []
    hub.answers["repos/o/r/issues/8/comments"] = []
    rc, got = said("/knos mine", MONA, 12, True, "--issue", "8")
    assert rc == 0 and got["reply"].startswith("Knos: nobody is paid for this pull request yet: issue #8 is assigned to @eve")


def test_knos_proof_judge_still_runs_the_acceptance_checks_and_says_who_is_paid(tmp_path, capsys):
    base, pr = tmp_path / "base", tmp_path / "pr"
    files = {"tests/test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
             ".knos/acceptance/1/test_accept.py": "import calc\n\n\ndef test_mul():\n    assert calc.mul(2, 3) == 6\n",
             "pytest.ini": "[pytest]\npythonpath = .\n", "calc.py": "def add(a, b):\n    return a + b\n"}
    for root, more in ((base, ""), (pr, "\n\ndef mul(a, b):\n    return a * b\n")):
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes((text + (more if name == "calc.py" else "")).encode())
    (tmp_path / "changed.txt").write_text("calc.py\n", encoding="utf-8")
    (tmp_path / "event.json").write_text(json.dumps({"pull_request": {"number": 12, "user": MONA, "body": "Fixes #1"}}), encoding="utf-8")
    rc, out = cli(capsys, "proof", "judge", "--base", str(base), "--pr", str(pr), "--issue", "1", "--sandbox", "off",
                  "--changed", str(tmp_path / "changed.txt"), "--event", str(tmp_path / "event.json"), "--evidence", str(tmp_path / "ev.json"))
    assert rc == 0 and "paid to @mona (GitHub user id 4242): the pull request's author" in out and "checks_hash " in out and "proven" in out
    ev = json.loads((tmp_path / "ev.json").read_text())
    assert ev["passed"] and ev["checks_hash"] == judge.checks_hash(base / ".knos" / "acceptance" / "1") and ev["evidence"]["mode"] == "tests"
    assert ev["evidence"]["payee"]["id"] == 4242 and ev["evidence"]["changed"] == ["calc.py"]
    rc, out = cli(capsys, "proof", "judge", "--base", str(base), "--pr", str(base), "--issue", "1", "--sandbox", "off")
    assert rc == 1 and "not proven" in out                                                 # the base itself does not pass its acceptance


def _trees(root, pr_adds: str = "\n\ndef mul(a, b):\n    return a * b\n"):
    """A base and a pull request head whose acceptance bundle for issue 1 wants calc.mul."""
    base, pr = root / "base", root / "pr"
    files = {"tests/test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
             ".knos/acceptance/1/test_accept.py": "import calc\n\n\ndef test_mul():\n    assert calc.mul(2, 3) == 6\n",
             "pytest.ini": "[pytest]\npythonpath = .\n", "calc.py": "def add(a, b):\n    return a + b\n"}
    for tree, more in ((base, ""), (pr, pr_adds)):
        for name, text in files.items():
            (tree / name).parent.mkdir(parents=True, exist_ok=True)
            (tree / name).write_bytes((text + (more if name == "calc.py" else "")).encode())
    return base, pr


def test_a_bounty_funded_with_acceptance_checks_is_judged_on_its_terms_and_those_checks(tmp_path):
    """Tests mode with terms: the funded checks at the commit, the scope, and the acceptance checks that were funded
    (their hash is in the terms). `accepted` and `payable` say what a payment is decided on; words enter neither."""
    base, pr = _trees(tmp_path)
    bundle = judge.checks_hash(base / ".knos" / "acceptance" / "1")
    bought = {**BOUGHT, "accept": bundle, "mode": "tests"}
    pull = {"number": 12, "user": MONA, "body": "Fixes #1", "assignees": []}

    def verdict(pr_dir=pr, **kw):
        kw = {"body": "Fixes #1", "check_runs": [run("tests")], "pull": pull, "paid": judge.payee(pull), "terms": bought, "statuses": [],
              "sandbox": "off", **kw}
        return judge.judge_with_rules(base, pr_dir, {"issue": kw.pop("issue", "1")}, kw.pop("changed", None), "", history.NullStore(),
                                      "o/r", "mona", **kw)
    ok = verdict()
    ev = ok["evidence"]
    assert ok["passed"] and ok["reasons"] == [] and ok["checks_hash"] == bundle and ev["mode"] == "tests"
    assert ev["accepted"] is True and ev["payable"] is True and ev["checks"] == {"tests": "passed"} and ev["terms_hash"] == terms.terms_hash(bought)
    assert ev["changed"] == ["calc.py"] and ev["payee"]["id"] == 4242 and ev["pr"]["acceptance"]       # the scope came from the two trees
    # a false claim fails the check; the acceptance checks are still run, and what a payment is decided on is unchanged
    lie = verdict(body="Fixes #1. All tests pass.", check_runs=[run("tests"), run("lint", "failure")])
    assert not lie["passed"] and lie["reasons"] == ["claim: the description says tests pass, but these checks failed at the head commit: lint"]
    assert lie["evidence"]["accepted"] is True and lie["evidence"]["payable"] is True and lie["evidence"]["claims"] == lie["reasons"]
    assert lie["evidence"]["facts"] == ["checks failing: lint"] and "pr" in lie["evidence"]
    # the terms not met: no pull request code is run, and nothing is payable
    for kw, why in (({"check_runs": [run("tests", "failure")]}, "terms: required check `tests` failed at this commit"),
                    ({"changed": ["calc.py", ".knos/acceptance/1/test_accept.py"]},
                     "terms: changes `.knos/acceptance/1/test_accept.py`, which this bounty does not allow (`.knos/**`)"),
                    ({"terms": {**bought, "accept": "0" * 64}},
                     "terms: the acceptance checks in .knos/acceptance/1 on the base are not the ones this bounty was funded with"),
                    ({"terms": BOUGHT}, "terms: this bounty is paid on the merge: it was not funded with acceptance checks"),
                    ({"issue": "2"}, "terms: the acceptance checks in .knos/acceptance/2 on the base are not the ones this bounty was funded with"),
                    ({"issue": "../1"}, "terms: the acceptance checks in .knos/acceptance/../1 on the base are not the ones this bounty was funded with")):
        got = verdict(**kw)
        assert not got["passed"] and got["reasons"] == [why], kw
        assert got["evidence"]["accepted"] is False and got["evidence"]["payable"] is False and "pr" not in got["evidence"], kw
    assert verdict(check_runs=[run("tests", "failure")])["checks_hash"] == bundle
    # the acceptance checks do not pass: not accepted, whatever GitHub's checks say
    same = verdict(pr_dir=base)
    assert not same["passed"] and same["evidence"]["accepted"] is False and same["evidence"]["payable"] is False
    assert same["evidence"]["checks"] == {"tests": "passed"}
    # nobody to pay: accepted, not payable; no payee worked out: payable is not said
    bot = {**pull, "user": DEVIN}
    nobody = verdict(pull=bot, paid=judge.payee(bot))
    assert not nobody["passed"] and nobody["evidence"]["accepted"] is True and nobody["evidence"]["payable"] is False
    assert nobody["reasons"][0].startswith("payee: devin-ai-integration[bot] is a bot account")
    unsaid = verdict(pull=None, paid=None)
    assert unsaid["passed"] and unsaid["evidence"]["accepted"] is True and unsaid["evidence"]["payable"] is None
    # the repository's own rule is broken: the check fails and says so, and the payment is still the terms' to decide
    for tree in (base, pr):
        (tree / "CONTRIBUTING.md").write_text("# Rules\n\n- Do not leave print() debug statements in code.\n", encoding="utf-8")
    diff = ("diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,5 @@\n def add(a, b):\n     return a + b\n"
            "+def mul(a, b):\n+    print(a, b)\n+    return a * b\n")
    ruled = judge.judge_with_rules(base, pr, {"issue": "1"}, None, diff, history.NullStore(), "o/r", "mona", "Fixes #1", [run("tests")],
                                   sandbox="off", pull=pull, paid=judge.payee(pull), terms=bought, statuses=[])
    assert not ruled["passed"] and len(ruled["reasons"]) == 1 and ruled["reasons"][0].startswith("repo rule: calc.py:4")
    assert ruled["evidence"]["repo_rules"] and ruled["evidence"]["accepted"] is True and ruled["evidence"]["payable"] is True
    for tree in (base, pr):
        (tree / "CONTRIBUTING.md").unlink()
    # without terms nothing changed: the gate first, and only a pull request that clears it has its code run
    plain = verdict(terms=None, body="All tests pass.", check_runs=[run("lint", "failure")], changed=["calc.py"])
    assert not plain["passed"] and "pr" not in plain["evidence"] and plain["evidence"]["accepted"] is None
    free = verdict(terms=None, changed=["calc.py"])
    assert free["passed"] and "accepted" not in free["evidence"] and free["evidence"]["facts"] == []


def test_knos_proof_judge_takes_the_terms_and_the_reservation_they_fix(tmp_path, capsys, monkeypatch):
    base, pr = _trees(tmp_path)
    bought = {**BOUGHT, "accept": judge.checks_hash(base / ".knos" / "acceptance" / "1"), "mode": "tests"}
    (tmp_path / "terms.json").write_bytes(terms.canonical(bought))
    (tmp_path / "runs.json").write_text(json.dumps([run("tests")]), encoding="utf-8")
    pull = {"number": 12, "user": EVE, "body": "Fixes #1", "assignees": [], "head": {"sha": "a" * 40}}
    took = {"event": "assigned", "assignee": MONA, "assigner": BOT,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 8 * 86_400))}
    hub = Hub({"repos/o/r/pulls/12": pull, "repos/o/r/issues/1": {"number": 1, "assignees": [MONA]}, "repos/o/r/issues/1/events": [took],
               "repos/o/r/issues/1/comments": [], "repos/o/r/issues/12/comments": []})
    monkeypatch.setattr("knos.judge.github", hub)
    args = ["proof", "judge", "--base", str(base), "--pr", str(pr), "--issue", "1", "--sandbox", "off", "--repo", "o/r", "--pull", "12",
            "--checks-file", str(tmp_path / "runs.json"), "--evidence", str(tmp_path / "ev.json")]
    # mona's take lapsed a day ago: with the terms that say how long a take lasts, eve's pull request is paid
    rc, out = cli(capsys, *args, "--terms", str(tmp_path / "terms.json"))
    assert rc == 0 and out.splitlines()[:2] == ["passed     tests", "paid to @eve (GitHub user id 666): the pull request's author"]
    ev = json.loads((tmp_path / "ev.json").read_text())["evidence"]
    assert ev["accepted"] is True and ev["payable"] is True and ev["mode"] == "tests"
    # the same through the gate; and without the terms nothing says the take has lapsed
    (tmp_path / "changed.txt").write_text("calc.py\n", encoding="utf-8")
    gate = ["proof", "gate", "--base", str(base), "--issue", "1", "--repo", "o/r", "--pull", "12", "--checks-file", str(tmp_path / "runs.json"),
            "--changed", str(tmp_path / "changed.txt")]
    (tmp_path / "merge.json").write_bytes(terms.canonical(BOUGHT))
    rc, out = cli(capsys, *gate, "--terms", str(tmp_path / "merge.json"))
    assert rc == 0 and "paid to @eve (GitHub user id 666)" in out
    for none in (gate, args):
        rc, out = cli(capsys, *none)
        assert rc == 1 and "NO  assigned: issue #1 is assigned to @mona; only an assignee's pull request is paid for it" in out
    # a reservation still running holds it, with the terms too
    took["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 86_400))
    rc, out = cli(capsys, *gate, "--terms", str(tmp_path / "merge.json"))
    assert rc == 1 and "NO  assigned: issue #1 is assigned to @mona until " in out


# ---- knos.judge.github: the one door to GitHub -----------------------------------------------------------------------

def test_github_gets_and_posts_json_and_says_no_as_an_oserror(monkeypatch):
    import urllib.request
    seen = []

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=0):
        seen.append((req.get_method(), req.full_url, req.data, dict(req.header_items())))
        if "gone" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", None, None)
        return Answer({"empty": b"", "html": b"<html>"}.get(req.full_url.rsplit("/", 1)[1], b'{"ok": true}'))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("GH_TOKEN", "t0ken")
    assert judge.github("repos/o/r") == {"ok": True}
    method, url, data, headers = seen[-1]
    assert (method, url, data) == ("GET", "https://api.github.com/repos/o/r", None) and headers["Authorization"] == "Bearer t0ken"
    assert judge.github("repos/o/r/issues/1/comments", {"body": "x"}) == {"ok": True}
    method, url, data, _ = seen[-1]
    assert method == "POST" and json.loads(data) == {"body": "x"} and seen[-1][3]["Content-type"] == "application/json"
    assert judge.github("repos/o/r/empty") is None                                         # 204: nothing to read
    monkeypatch.delenv("GH_TOKEN")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    for path in ("repos/o/gone", "repos/o/r/html"):
        with pytest.raises(OSError):
            judge.github(path)
    assert "Authorization" not in seen[-1][3]
