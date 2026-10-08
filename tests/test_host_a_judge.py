"""Host a judge (src/knos/host_judge.py, examples/host_a_judge): an account that is neither the buyer nor the supplier
runs the neutral evaluator in a repository of its own, and the receipt reads `rerun`; with a second host of another
owner it reads `agreed`. The runs are tests/_flow.py's simulator (GitHub, its signature and the chain are fakes with
fixed ids); the levels are computed by knos.receipt on receipts that pass its own check. No outside account has
hosted a judge: these are tests."""
from __future__ import annotations

import base64
import copy
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml
from _assurance import base
from _flow import MONA, World
from knos import flow, host_judge, receipt
from test_attest_rerun import Judge, staged
from test_flow_orders import ORDER, Sellers

ROOT = Path(__file__).resolve().parents[1]
ADA = {"id": 9001, "login": "ada", "repo": "ada/knos-judge", "repo_id": 70_001}          # a host: neither the buyer nor a payee
GRACE = {"id": 9002, "login": "grace", "repo": "grace/knos-judge", "repo_id": 70_002}    # a second host, another owner
ADA_TOO = {**ADA, "repo": "ada/second-judge", "repo_id": 70_003}                          # a second repository of the first host


class Hosts(Sellers):
    """A host's repository on GitHub beside the order's: its "knos tokens" issue and the comments on it."""

    def __init__(self, w: World, here: str):
        super().__init__(w)
        self.HERE = here


def hosted(w: World, trees: Path, who: dict, passed: bool = True) -> tuple[dict, dict | None]:
    """One run of knos-attest.yml in `who`'s repository, started by `who`: the job that runs the suite, then the job
    that asks GitHub to sign. Returns (the claims GitHub signed, or {} when nothing was signed; the run's verdict)."""
    env = {"GITHUB_ACTOR_ID": str(who["id"]), "GITHUB_ACTOR": who["login"], "GITHUB_REPOSITORY_ID": str(who["repo_id"]), "GITHUB_REPOSITORY": who["repo"],
           "GITHUB_REPOSITORY_OWNER_ID": str(who["id"]), "RUNNER_OS": "Linux", "RUNNER_ENVIRONMENT": "github-hosted", "ImageOS": "ubuntu24", "GITHUB_RUN_ID": str(500 + who["repo_id"])}

    def step(name: str, **more) -> flow.Run:
        w.tmp.mkdir(parents=True, exist_ok=True)
        run = w.run({}, **{**env, "GITHUB_STEP_SUMMARY": str(w.tmp / f"{name}-{w.runs}.md"), **more})
        w.signer.actor, w.signer.repo_id, w.signer.more = who["id"], who["repo_id"], {"repository_owner_id": str(who["id"])}
        return run
    asked = len(w.signer.asked)
    plan = step("plan")
    assert flow.attest(plan, str(ORDER), "pay", 12, plan=str(trees)) == 0 and plan.outputs.get("rerun") == "1"
    ran = step("judge")
    code = flow.attest(ran, str(ORDER), "pay", 12, judge=str(trees), judge_fn=Judge(passed))
    assert len(w.signer.asked) == asked                              # the jobs that run a stranger's code can ask for no token: the host holds no secret either
    verdict = ran.outputs.get("verdict")
    sign = step("token", **({} if verdict is None else {"KNOS_RERUN": verdict}))
    sign._github = sign._ghrelay = Hosts(w, who["repo"])
    code = flow.attest(sign, str(ORDER), "pay", 12)
    if code != 0:
        return {}, None if verdict is None else json.loads(verdict)
    body = sign.outputs["token"].split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))), json.loads(sign.outputs["verdict"])


def with_hosts(entries: list[dict], declared=()) -> dict:
    """A version 5 receipt whose evaluators are these hosted judges, then the judge that paid (version 3's fourth vector:
    payees 111, 222, 333, 444). It passes the receipt's own check, which computes the level again."""
    r = base()
    o = r["evaluator_observed"]
    o["evaluators"] = [*copy.deepcopy(entries), *o["evaluators"]]
    o["same_controller"], o["independence"] = receipt.independence_of(o["evaluators"])
    five = receipt.build5(receipt.build4(r), declared)
    assert receipt.check(five) is None
    return five


def test_a_judge_hosted_by_an_outside_account_reads_rerun_and_two_hosts_of_two_owners_read_agreed(tmp_path):
    w, _head, trees = staged(tmp_path)
    w.env.pop("KNOS_RELAY_KEY")                                       # a host has no relay key: the token is posted for any relayer
    ada, ran_ada = hosted(w, trees, ADA)
    assert (ada["repository_owner_id"], ada["actor_id"], ada["repository_id"]) == ("9001", "9001", "70001") and ran_ada["reexecuted"] is True
    assert ran_ada["environment"]["github_repository"] == "ada/knos-judge" and "ran the acceptance suite itself" in ran_ada["sentence"]
    r = base()
    buyers = (r["commercial_authorisation"]["funder"]["github_id"], r["commercial_authorisation"]["source"]["owner_id"])
    sellers = [p["github_id"] for p in r["payees"]]
    one = host_judge.entry("neutral", ada, buyers, sellers, ran_ada)
    assert one["independent_of_seller"] is True and one["reexecution"]["reexecuted"] is True and one["owner_id"] == 9001
    # no host: reported. One outside host that ran the suite: rerun
    assert with_hosts([])["assurance"]["level"] == "reported"
    got = with_hosts([one])
    assert got["assurance"]["level"] == "rerun" and got["evaluator_observed"]["same_controller"] is False
    assert any("ran the pinned suite again" in line for line in receipt.render(got))
    # a second host with another owner, on the same pull request: agreed
    w2, _head, trees2 = staged(tmp_path / "second")
    w2.env.pop("KNOS_RELAY_KEY")
    grace, ran_grace = hosted(w2, trees2, GRACE)
    two = host_judge.entry("attestor", grace, buyers, sellers, ran_grace)
    both = with_hosts([one, two])
    assert both["assurance"]["level"] == "agreed" and both["evaluator_observed"]["same_controller"] is False
    assert host_judge.level([one, two], sellers)["level"] == "agreed" and host_judge.level([one], sellers)["level"] == "rerun"
    # two repositories of ONE owner are one evaluator: the level stays rerun and the receipt says SAME CONTROLLER
    w3, _head, trees3 = staged(tmp_path / "third")
    w3.env.pop("KNOS_RELAY_KEY")
    again, ran_again = hosted(w3, trees3, ADA_TOO)
    same = with_hosts([one, host_judge.entry("attestor", again, buyers, sellers, ran_again)])
    assert same["assurance"]["level"] == "rerun" and same["evaluator_observed"]["same_controller"] is True
    # a host the terms declare one party with a payee is the supplier: reported. So is a host who is a payee
    assert with_hosts([one], declared=[[9001, 111]])["assurance"]["level"] == "reported"
    mine = host_judge.entry("neutral", {**ada, "repository_owner_id": "111", "actor_id": "111"}, buyers, sellers, ran_ada)
    assert mine["independent_of_seller"] is False and with_hosts([mine])["assurance"]["level"] == "reported"
    # nobody types a level: one written by hand is refused
    forged = {**with_hosts([]), "assurance": {**with_hosts([])["assurance"], "level": "rerun", "trusted": list(receipt.TRUSTED["rerun"])}}
    assert "computed from the evidence" in (receipt.check(forged) or "")


def test_a_host_signs_nothing_for_a_suite_that_fails_and_the_payees_own_run_stays_reported(tmp_path):
    w, _head, trees = staged(tmp_path)
    w.env.pop("KNOS_RELAY_KEY")
    asked = len(w.signer.asked)
    claims, verdict = hosted(w, trees, ADA, passed=False)
    assert claims == {} and len(w.signer.asked) == asked and verdict is not None and verdict["passed"] is False        # a host cannot get a failing suite signed
    # the supplier's own run of the same file (the simulator's payee is mona): signed, and it raises nothing
    w2, _head, trees2 = staged(tmp_path / "own")
    w2.env.pop("KNOS_RELAY_KEY")
    mona, ran = hosted(w2, trees2, {"id": MONA["id"], "login": "mona", "repo": "mona/knos-attest", "repo_id": 999})
    entry = host_judge.entry("neutral", mona, (), [MONA["id"]], ran)
    assert entry["independent_of_seller"] is False and host_judge.level([entry], [MONA["id"]])["level"] == "reported"
    assert host_judge.level([host_judge.entry("neutral", {**mona, "repository_owner_id": "9001", "actor_id": "9001"}, (), [MONA["id"]], ran)], [MONA["id"]])["level"] == "rerun"


def test_the_level_from_account_ids_says_why_before_anyone_runs_anything(capsys):
    reads = host_judge.reads
    assert [reads([5], hosts)["level"] for hosts in ([], [9], [9, 10], [9, 9], [5], [9, 5])] == ["reported", "rerun", "agreed", "rerun", "reported", "rerun"]
    assert reads([5], [9], declared=[[9, 5]])["level"] == "reported" and reads([5], [9, 10], declared=[[9, 10]])["level"] == "rerun"
    assert reads([5], [9, 10], suite=False)["level"] == "reported" and "paid on the merge" in reads([5], [9], suite=False)["why"]
    assert reads([5], [9, 5])["hosts_paid_by_the_order"] == [5] and reads([5], [9, 9])["same_controller"] is True
    # the buyer's account as a host is not refused by the receipt (only the supplier's side is compared), which is why the
    # page says the order's own repository, kind `repository`, never raises the level: that is the buyer's judge an order has
    own = receipt.evaluator("repository", {"repository_id": 1, "repository_owner_id": 7, "actor_id": 7, "runner_environment": "github-hosted"}, [7], [5],
                            {"reexecuted": True, "assurance": "black-box", "environment": {}, "image_digest": None})
    assert host_judge.level([own], [5])["level"] == "reported"
    assert host_judge.main(["level", "--payee", "5", "--host", "9", "--host", "10"]) == 0 and capsys.readouterr().out.startswith("agreed: two evaluators with different owners")
    assert host_judge.main(["editor", "not a repository"]) == 1 and capsys.readouterr().out.startswith("not done: ")


def test_the_one_click_and_the_file_it_installs_need_no_secret(capsys):
    text = (ROOT / "examples" / "knos-attest.yml").read_text(encoding="utf-8")
    link = host_judge.template_link()
    q = parse_qs(urlsplit(link).query)
    assert link.startswith("https://github.com/new?") and q == {"template_owner": ["drexthealpha"], "template_name": ["knos-attest"], "name": ["knos-judge"],
                                                               "visibility": ["public"], "owner": ["@me"]}
    assert link in (ROOT / "examples" / "host_a_judge" / "README.md").read_text(encoding="utf-8")
    assert '"knos-attest": ("the template' in (ROOT / "scripts" / "small_repos.py").read_text(encoding="utf-8")      # the template repository is one Knos builds
    edit = host_judge.editor_link("https://github.com/ada/knos-judge", text)
    assert edit is not None and len(edit) <= host_judge.URL_LIMIT and edit.startswith("https://github.com/ada/knos-judge/new/main?filename=.github%2Fworkflows%2Fknos-attest.yml&value=")
    sent = parse_qs(urlsplit(edit).query)["value"][0]
    assert yaml.safe_load(sent) == yaml.safe_load(text) and "#" not in sent.split("\n")[0]             # the same workflow, without its comment lines
    doc = yaml.safe_load(text)
    job = doc["jobs"]["attest"]
    assert "secrets" not in text.replace("holds no secret", "").replace("needs no secret", "").replace("no secret of yours", "") and "secrets" not in job
    assert doc["permissions"] == {} and job["permissions"] == {"contents": "read", "issues": "write", "id-token": "write"}
    assert list(doc[True]) == ["workflow_dispatch"] and re.fullmatch(r"drexthealpha/knos-workflows/\.github/workflows/attest\.yml@([0-9a-f]{40}|KNOS_WORKFLOWS_SHA)", job["uses"])
    assert host_judge.editor_link("ada/knos-judge", text + "x" * 9000) is None and host_judge.editor_link("ada", text) is None
    assert host_judge.run_link("ada/knos-judge") == "https://github.com/ada/knos-judge/actions/workflows/knos-attest.yml"
    assert host_judge.fund_line("20", "ada/knos-judge") == "/knos fund 20 checks: unit quorum 2 judge: ada/knos-judge"
    with pytest.raises(ValueError, match="quorum 2\\|3"):
        host_judge.fund_line("20", "ada/knos-judge", quorum=4)
    assert host_judge.main(["link"]) == 0 and capsys.readouterr().out.strip() == link


def test_the_line_that_names_a_host_is_one_the_funding_comment_grammar_reads():
    from knos import commands
    got = commands.parse(host_judge.fund_line("20", "ada/knos-judge"), on_pull=False)
    assert (got.quorum, got.judge) == (2, "ada/knos-judge")


def test_the_page_says_what_a_host_is_paid_and_what_they_can_and_cannot_do():
    readme = (ROOT / "examples" / "host_a_judge" / "README.md").read_text(encoding="utf-8")
    lib = (ROOT / "programs-v2" / "knos_pay" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert len(readme.splitlines()) == 10
    assert "pub const TIP: u64 = 50_000;" in lib and "pub const TIP_FIRST: u64 = 300_000;" in lib            # the two figures the page and the module state
    for where in (readme, host_judge.PAID):
        assert "0.05 test USDC" in where and "0.30" in where and ("Nothing by the order" in where or "paid nothing by the order" in where)
    said = "\n".join(host_judge.says())
    assert "A host can:" in said and "A host cannot:" in said and "count twice" in said and "No outside account has hosted a judge yet" in readme
    for word in ("rerun", "agreed", "reported", "needs no secret"):
        assert word in readme
    for page in ("ATTESTOR.md", "OPERATOR.md"):
        assert "host_a_judge" in (ROOT / "docs" / page).read_text(encoding="utf-8")


def test_the_site_offers_the_same_one_click():
    page = (ROOT / "web" / "playground.js").read_text(encoding="utf-8")
    assert re.search(r'export const HOST_A_JUDGE = "([^"]+)";', page).group(1) == host_judge.template_link()
