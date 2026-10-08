"""A neutral run that RE-EXECUTES. GitHub signs which workflow ran, not what it read: for a work order paid by its
acceptance checks (tests mode: a black-box bundle whose hash is in the terms) attest.yml's first job, which can ask
for no token, runs the suite itself on the two commits, and the job that signs takes only that job's verdict, read
as untrusted text and held to the order. A check in the buyer's repository that says "success" is then not repeated:
the suite is run again under another account, on another runner. An order paid on the merge has no suite to run:
its neutral run reads the check results, and says so.

The fakes are tests/_flow.py's (GitHub, the chain, GitHub's signature); the judge is a stand-in that records what it
was asked to run, and once the real one, on the sample tree the tamper benchmark uses. The last test carries what
each neutral run signed to the real program in LiteSVM (tests/_order.py), on an order that needs two judges."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from _flow import MONA, World, check
from knos import flow, judge, terms
from knos.settle.v2 import order_auto, pay
from test_flow import BY_TESTS, CHECKS, sha
from test_flow_orders import ORDER, Sellers, ordered, world

SAMPLE = Path(__file__).resolve().parent / "bench_tamper" / "sample"
D = "a" * 64
IMAGE = f"registry.example/team/judge@sha256:{D}"
READ = "this judge read the buyer repository's check results; it did not run them"
RAN = "this judge fetched the two commits and ran the acceptance suite itself"
ATTESTER = {"GITHUB_ACTOR_ID": str(MONA["id"]), "GITHUB_ACTOR": "mona", "GITHUB_REPOSITORY_ID": "999", "GITHUB_REPOSITORY": "mona/knos-attest",
            "RUNNER_OS": "Linux", "RUNNER_ENVIRONMENT": "github-hosted", "ImageOS": "ubuntu24", "GITHUB_RUN_ID": "501"}


def staged(tmp_path, bought: dict = BY_TESTS, flags: int = pay.F_NEUTRAL | pay.F_FAUCET) -> tuple[World, str, Path]:
    """Issue #7 with an order paid by its black-box acceptance checks, and pull request #12 MERGED, every check of the
    buyer's repository green at its head, the judge's own among them. Returns (the world, the head, the job's folder
    with base/ and pr/ in it as the workflow's fetch step leaves them)."""
    w = world(tmp_path)
    w.chain.order(7, 20_000_000, bought, mode=pay.TESTS, flags=flags)
    w.hub.bundles[7] = dict(CHECKS)
    w.clock.sleep(3600)
    head = w.hub.pull(12, MONA, "Fixes #7")["head"]["sha"]
    w.hub.checks[head] = [check("test"), check("build"), check("knos review / judge"), check("knos review / attest")]
    w.chain.bind(MONA)
    w.hub.merge(12)
    trees = tmp_path / "job"
    for side in ("base", "pr"):
        bundle = trees / side / ".knos" / "acceptance" / "7"
        bundle.mkdir(parents=True)
        for name, text in CHECKS.items():
            (bundle / name).write_bytes(text)
        (trees / side / "slug.py").write_text("def slug(s):\n    return s\n" if side == "base" else "def slug(s):\n    return s.replace(' ', '-')\n", encoding="utf-8")
    return w, head, trees


class Judge:
    """knos.judge.judge by its contract, with the verdict a test wants: what it was asked to run is kept."""

    def __init__(self, passed: bool = True, image: str = ""):
        self.passed, self.image, self.asked = passed, image, []

    def __call__(self, base, pr, cfg, changed=None, sandbox="auto") -> dict:
        self.asked.append((Path(base).name, Path(pr).name, dict(cfg), sandbox))
        self.changed = changed
        ev = {"issue": cfg["issue"], "runner": "blackbox", "artifact": {"base": judge.tree_hash(base), "pr": judge.tree_hash(pr)}}
        if self.image:
            ev["image"] = {"ref": self.image, "digest": self.image.rsplit("@", 1)[-1], "runtime": "docker", "limits": {"memory": "512m"}}
        return {"passed": self.passed, "checks_hash": BY_TESTS["accept"], "evidence": ev, "assurance": "hermetic" if self.image else "black-box",
                "reasons": [] if self.passed else ["pr: acceptance checks not passed: blackbox"]}


def step(w: World, name: str, **env) -> tuple[flow.Run, Path]:
    w.tmp.mkdir(parents=True, exist_ok=True)
    summary = w.tmp / f"{name}-{w.runs}.md"
    run = w.run({}, **{**ATTESTER, "GITHUB_STEP_SUMMARY": str(summary), **env})
    w.signer.actor = MONA["id"]
    return run, summary


def rerun(w: World, trees: Path, judged: Judge | None, kind: str = "pay") -> tuple[int, dict, str]:
    """attest.yml's first job: the plan, then (when there is a suite to run) the judge on the two trees. Returns
    (the job's exit status, its outputs, what its page says). It is given no way to sign: the test fails if it asks."""
    run, summary = step(w, "plan")
    asked = len(w.signer.asked)
    code = flow.attest(run, str(ORDER), kind, 12, plan=str(trees))
    outputs = dict(run.outputs)
    if code == 0 and outputs.get("rerun") == "1":
        read = len(w.hub.asked)
        run, more = step(w, "judge")
        code = flow.attest(run, str(ORDER), kind, 12, judge=str(trees), judge_fn=judged)
        assert len(w.hub.asked) == read                     # the step that runs the suite reads nothing of GitHub: it has no token for it
        outputs.update(run.outputs)
        summary.write_text(summary.read_text(encoding="utf-8") + more.read_text(encoding="utf-8"), encoding="utf-8")
    assert len(w.signer.asked) == asked and "token" not in outputs and "audience" not in outputs
    return code, outputs, summary.read_text(encoding="utf-8")


def signs(w: World, verdict: str | None, sellers: Sellers | None = None, **env) -> tuple[int, flow.Run, str]:
    """attest.yml's second job, the one that may ask for the token: `knos attest` with the first job's verdict in KNOS_RERUN."""
    run, summary = step(w, "token", **({} if verdict is None else {"KNOS_RERUN": verdict}), **env)
    if sellers is not None:
        run._github = run._ghrelay = sellers
    code = flow.attest(run, str(ORDER), "pay", 12)
    return code, run, summary.read_text(encoding="utf-8")


def test_the_buyers_checks_say_success_and_the_suite_fails_when_it_is_run_again_so_nothing_is_signed(tmp_path):
    w, head, trees = staged(tmp_path)
    assert all(c["conclusion"] == "success" for c in w.hub.checks[head])            # GitHub's record of the buyer's repository: all green
    judged = Judge(passed=False)
    code, out, text = rerun(w, trees, judged)
    # the plan named the two commits and the funded bundle; the suite was run on them, in the sandbox, and did not pass
    plan = json.loads((trees / "plan.json").read_text(encoding="utf-8"))
    assert plan == {"order": str(ORDER), "repository": "o/r", "pull": 12, "issue": 7, "head": head, "base": sha("main"),
                    "accept": BY_TESTS["accept"], "image": "", "changed": ["src/a.py"]} and (out["rerun"], out["base"], out["head"]) == ("1", sha("main"), head)
    assert judged.asked == [("base", "pr", {"issue": "7"}, "hermetic")] and judged.changed == ["src/a.py"]      # GitHub's list, not the trees' difference
    assert code == 1 and "was run again here and did not pass (black-box)" in text and "Nothing is signed: the job that asks GitHub for the token does not start." in text
    v = json.loads(out["verdict"])
    assert v == json.loads((trees / "verdict.json").read_text(encoding="utf-8"))
    assert (v["reexecuted"], v["passed"], v["assurance"], v["head"], v["base"], v["accept"]) == (True, False, "black-box", head, sha("main"), BY_TESTS["accept"])
    assert v["artifact"] == {"base": judge.tree_hash(trees / "base"), "pr": judge.tree_hash(trees / "pr")} and v["image"] == {}
    assert v["environment"]["github_repository"] == "mona/knos-attest" and v["environment"]["runner_environment"] == "github-hosted"
    assert v["reasons"] == ["pr: acceptance checks not passed: blackbox"] and v["sentence"].startswith(RAN)
    # the workflow does not start the token job after a failed job. Were it started all the same, with that verdict, it signs nothing
    code, run, text = signs(w, out["verdict"])
    assert code == 1 and w.signer.asked == [] and len(w.chain.orders(7)) == 1 and "token" not in run.outputs
    assert "nothing was signed" in text and "the acceptance suite did not pass when it was run again here: pr: acceptance checks not passed: blackbox" in text
    assert "Whatever the check results in the order's repository say, this judge signs only what it ran itself" in text
    assert "- `test`: passed" in text and "- `build`: passed" in text       # the record it read is green, and it is not what decided
    # and with no verdict at all (the first job never ran): the same
    code, run, text = signs(w, None)
    assert code == 1 and w.signer.asked == [] and "this order is paid by its acceptance checks, and they were not run again here" in text


def test_a_suite_that_fails_when_it_is_run_again_is_posted_as_a_verdict_that_says_why_nothing_was_signed(tmp_path):
    # attest.yml's job `refused`: after the first job failed with a verdict, the same command, with no id-token, posts
    # that verdict on the "knos tokens" issue with the reason, signs nothing and ends 1 (the first job of 0.3.15's
    # real run left the verdict only in its log and its artifact)
    w, head, trees = staged(tmp_path)
    code, out, _text = rerun(w, trees, Judge(passed=False))
    assert code == 1 and json.loads(out["verdict"])["passed"] is False
    sellers = Sellers(w)
    w.env.pop("KNOS_RELAY_KEY")
    code, run, text = signs(w, out["verdict"], sellers)
    assert code == 1 and w.signer.asked == [] and "token" not in run.outputs and len(w.chain.orders(7)) == 1
    [said] = sellers.comments
    first, *rest = said["body"].split("\n")
    assert said["issue"] == 1 and sellers.issues[0]["title"] == "knos tokens" and first.startswith(flow.VERDICT)
    assert json.loads(first.removeprefix(flow.VERDICT)) == json.loads(out["verdict"]) == json.loads(run.outputs["verdict"])
    assert f"How this run reached its verdict: {RAN}" in said["body"]
    assert said["body"].endswith("\n\nNothing was signed: the acceptance suite did not pass when it was run again here: pr: acceptance checks not "
                                 "passed: blackbox. Whatever the check results in the order's repository say, this judge signs only what it ran itself.")
    assert "nothing was signed" in text
    # the workflow: the job that posts it starts only after a failed first job that handed on a verdict, and cannot sign
    yaml = pytest.importorskip("yaml")
    jobs = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github" / "workflows" / "attest.yml").read_text(encoding="utf-8"))["jobs"]
    refused, attest = jobs["refused"], jobs["attest"]
    assert refused["needs"] == "rerun" and refused["if"] == "${{ failure() && needs.rerun.outputs.verdict != '' }}" and "if" not in attest
    assert refused["permissions"] == {"contents": "read", "issues": "write"}
    for key in ("uses", "with", "run", "env"):          # uv, the hash-locked install and the same command, with the same facts
        assert [s.get(key) for s in refused["steps"]] == [s.get(key) for s in attest["steps"]], key


def test_the_honest_case_is_signed_on_the_run_the_attester_made_and_the_verdict_is_posted_beside_the_token(tmp_path):
    w, head, trees = staged(tmp_path)
    code, out, text = rerun(w, trees, Judge())
    assert code == 0 and "was run again here and passed (black-box)" in text
    sellers = Sellers(w)
    w.env.pop("KNOS_RELAY_KEY")
    code, run, text = signs(w, out["verdict"], sellers)
    # the token and its audience are what the program takes today: knos3:pay, the order's own mode, the commit, the payees
    assert code == 0 and w.signer.asked == [pay.order_pay_audience(ORDER, head, pay.terms_hash(terms.canonical(BY_TESTS)), pay.TESTS, 12, [(MONA["id"], 10_000, None)])]
    assert w.chain.orders(7) == [] and f"- how this verdict was reached: {RAN}" in text
    assert f"repos/o/r/contents/.knos/acceptance?ref={sha('main')}" in w.hub.asked          # the bundle at the base, read again by the job that signs
    token, verdict = sellers.comments
    assert token["body"].startswith(f"knos-proof: {run.outputs['token']}\n") and verdict["body"].startswith("knos-verdict: {")
    assert json.loads(verdict["body"].splitlines()[0].removeprefix(flow.VERDICT)) == json.loads(out["verdict"]) == json.loads(run.outputs["verdict"])


def test_a_verdict_is_untrusted_text_held_to_this_order_this_commit_and_these_terms(tmp_path):
    w, head, trees = staged(tmp_path)
    code, out, _text = rerun(w, trees, Judge())
    good = json.loads(out["verdict"])
    assert code == 0 and flow._rerun_read(out["verdict"]) == good

    def refused(change, want: str) -> None:
        v = json.loads(out["verdict"])
        change(v)
        code, _run, text = signs(w, v if isinstance(v, str) else json.dumps(v))
        assert code == 1 and w.signer.asked == [] and want in text, text
    for key, other in (("head", "b" * 40), ("base", "c" * 40), ("accept", "d" * 64), ("pull", 13), ("issue", 8), ("repository", "o/other"),
                       ("order", str(pay.order_pda(pay.scope_of(1, 7), ORDER, 0)))):
        refused(lambda v, key=key, other=other: v.update({key: other}), f"the re-execution was of another {key}")
    refused(lambda v: v.update(passed=False), "did not pass when it was run again here")
    refused(lambda v: v.update(assurance="in-process"), "did not run the pull request's code black-box")
    refused(lambda v: v.update(artifact={}), "does not say which two trees it judged")
    for change in (lambda v: v.update(extra="x"), lambda v: v.pop("artifact"), lambda v: v.update(pull=True), lambda v: v.update(head="HEAD"),
                   lambda v: v.update(reasons=["x" * 300]), lambda v: v.update(environment={"a": 1}), lambda v: v.update(passed="yes")):
        refused(change, "does not have the fields a verdict has")
    refused(lambda v: v.update(v=2), "is not in a form this version reads")
    # a verdict that says nothing was run does not pay an order whose suite must be run, and neither does one that is no verdict
    for said, want in ((json.dumps({"v": 1, "reexecuted": False, "sentence": READ, "environment": {}}), "the verdict handed to this job says they were not run"),
                       ("{not json", "is not JSON"), ("[1]", "is not in a form this version reads"), (" " * 9000, "is larger than a verdict is")):
        code, _run, text = signs(w, said)
        assert code == 1 and w.signer.asked == [] and want in text, text
    # nothing above changed what the job itself reads: the untouched verdict still pays
    assert signs(w, out["verdict"])[0] == 0 and len(w.signer.asked) == 1


def test_terms_that_name_an_image_are_signed_only_for_a_run_in_that_image_and_the_verdict_records_the_digest(tmp_path):
    bought = {**BY_TESTS, "image": IMAGE}
    w, head, trees = staged(tmp_path, bought)
    judged = Judge(image=IMAGE)
    code, out, text = rerun(w, trees, judged)
    v = json.loads(out["verdict"])
    assert code == 0 and judged.asked[0][2] == {"issue": "7", "image": IMAGE} and f"(hermetic, image digest `sha256:{D}`)" in text
    assert (v["assurance"], v["image"]) == ("hermetic", {"ref": IMAGE, "digest": f"sha256:{D}"})
    assert signs(w, out["verdict"])[0] == 0 and w.signer.asked[0].split(":")[5] == "1"
    # the same suite run on the bare runner is not what these terms bought
    w, head, trees = staged(tmp_path / "bare", bought)
    code, out, _text = rerun(w, trees, Judge())
    code, _run, text = signs(w, out["verdict"])
    assert code == 1 and w.signer.asked == [] and f"the terms name the image `{IMAGE}`, and the re-execution did not run the suite in it" in text


def test_the_bundle_that_is_run_is_the_one_that_was_funded_and_a_judge_that_cannot_run_is_a_suite_that_did_not_pass(tmp_path):
    w, _head, trees = staged(tmp_path)
    (trees / "base" / ".knos" / "acceptance" / "7" / "blackbox.sh").write_bytes(b"exit 0\n")       # the base carries other checks than the funded ones
    judged = Judge()
    code, out, text = rerun(w, trees, judged)
    assert code == 1 and judged.asked == [] and "at the base commit are not the ones this order was funded with" in text
    assert json.loads(out["verdict"])["passed"] is False

    def broken(*_a, **_k):
        raise RuntimeError("no sandbox on this machine")
    w, _head, trees = staged(tmp_path / "broken")
    code, out, text = rerun(w, trees, broken)
    assert code == 1 and "the judge could not run here (RuntimeError: no sandbox on this machine)" in text


def test_an_order_paid_on_the_merge_has_no_suite_to_run_so_the_run_reads_the_check_results_and_says_so(tmp_path):
    w = ordered(tmp_path)
    w.chain.bind(MONA)
    w.hub.merge(12)
    head, trees = w.hub.pulls[12]["head"]["sha"], tmp_path / "job"
    code, out, text = rerun(w, trees, None)
    v = json.loads(out["verdict"])
    assert code == 0 and out["rerun"] == "" and not (trees / "plan.json").exists() and f"nothing is re-executed for this order: {READ}." in text
    assert (v["reexecuted"], v["sentence"]) == (False, READ) and set(v) == {"v", "reexecuted", "sentence", "environment"}
    assert v == json.loads((trees / "verdict.json").read_text(encoding="utf-8"))
    # the job that signs decides from GitHub's record, as before, and its own verdict says which kind of judgment that was
    w.hub.checks[head] = [check("test", "failure"), check("build")]
    code, run, text = signs(w, out["verdict"])
    assert code == 1 and w.signer.asked == [] and "- `test`: failed" in text and f"- how this verdict was reached: {READ}" in text
    w.hub.checks[head] = [check("test"), check("build")]
    # a verdict that claims a re-execution adds nothing to an order that has no suite: the record decides, and the output says "read"
    forged = json.dumps({**v, "reexecuted": True})
    code, run, text = signs(w, forged)
    assert code == 0 and len(w.signer.asked) == 1 and w.signer.asked[0].split(":")[5] == "0" and f"- how this verdict was reached: {READ}" in text
    assert json.loads(run.outputs["verdict"])["reexecuted"] is False
    # the other kinds sign no payment: their first job has nothing to run either
    code, out, text = rerun(ordered(tmp_path / "take"), tmp_path / "take-job", None, kind="take")
    assert code == 0 and out["rerun"] == "" and json.loads(out["verdict"])["reexecuted"] is False


def test_settle_neutral_starts_the_run_for_an_order_paid_by_its_checks_and_says_they_are_run_again(tmp_path, capsys):
    w, _head, _trees = staged(tmp_path)
    calls = []

    def gh(*args: str) -> str:
        calls.append(args)
        if args[:2] == ("api", "user"):
            return "mona\n"
        if args[0] == "api":
            raise OSError("not found")
        return ""
    run = flow.Run("o/r", {}, github=w.hub, ledger=w.chain, gh=gh, clock=w.clock, sleep=w.clock.sleep, env={}, version=lambda: 1)
    assert flow.neutral(run, "https://github.com/o/r/pull/12") == 0
    assert calls[1] == ("workflow", "run", "knos-attest.yml", "--repo", "mona/knos-attest", "-f", "repository=o/r", "-f", "pull=12", "-f",
                        f"order={ORDER}", "-f", "kind=pay")
    said = capsys.readouterr().out
    assert ("This order is paid by its acceptance checks, so the run does not take o/r's word for them: it fetches the two commits of pull "
            "request #12, runs the checks again in mona/knos-attest, and asks GitHub to sign only if they pass; its page says what it found") in said


def test_the_command_line_has_the_two_steps_and_they_are_two(capsys):
    assert flow.main(["attest", "--help"]) == 0
    said = capsys.readouterr().out
    assert "--plan DIR" in said and "--judge DIR" in said and "nothing is signed" in said
    assert flow.main(["attest", "--repository", "o/r", "--order", "x", "--kind", "pay", "--plan", "a", "--judge", "a"]) == 1
    assert "--plan and --judge are two steps: give one." in capsys.readouterr().out


@pytest.mark.skipif(os.name == "nt", reason="a black-box check is a shell script: the judge's machine is Linux or macOS")
def test_the_real_judge_run_again_passes_the_fix_and_fails_a_pull_request_that_changes_nothing(tmp_path):
    """No stand-in: knos.judge.judge on the tamper benchmark's sample tree, whose issue 2 has a black-box bundle."""
    for name, fixed in (("honest", True), ("nothing", False)):
        trees = tmp_path / name
        shutil.copytree(SAMPLE, trees / "base")
        shutil.copytree(SAMPLE, trees / "pr")
        if fixed:
            (trees / "pr" / "calc.py").write_text('import re\nKNOWN = [("Hello World", "hello-world"), ("a  b", "a-b"), ("x", "x")]\n'
                                                  'def slugify(s):\n    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")\n', encoding="utf-8")
        plan = {"order": str(ORDER), "repository": "o/r", "pull": 12, "issue": 2, "head": "a" * 40, "base": "b" * 40,
                "accept": judge.checks_hash(trees / "base" / ".knos" / "acceptance" / "2"), "image": ""}
        v = flow._rerun_judge(plan, trees, dict(ATTESTER), sandbox="auto")
        assert (v["passed"], v["assurance"], v["reexecuted"]) == (fixed, "black-box", True), v["reasons"]
        assert flow._rerun_read(json.dumps(v)) == v and (flow._rerun_holds(v, plan) == "") is fixed


def test_with_a_quorum_of_two_the_buyers_green_checks_alone_pay_nothing_when_the_second_run_fails(tmp_path):
    """The program, in LiteSVM: an order that asks for two judges, paid by its black-box suite. Judge a is the buyer's own
    repository, whose run says the suite passed. Judge b is the neutral run above: what it signed is carried to the
    program, and where it signed nothing there is nothing to carry."""
    pytest.importorskip("solders.litesvm")
    from _order import HEAD, SUITE, USDC, OrderChain, user
    from solders.keypair import Keypair
    c = OrderChain()
    fee = pay.order_fee(20 * USDC)

    def order() -> tuple:
        o = c.fund_wallet(mode=pay.TESTS, terms=SUITE, options=pay.opts(pay.F_NEUTRAL | order_auto.quorum_flags(2)))
        author, wallet = user(), Keypair().pubkey()
        payees = [(author, 10_000, wallet)]
        assert c.send([c.pay_ix(o, c.pay_token(o, payees), payees)]), c.err             # judge a: the buyer's own run passed it
        assert c.said("knos3:quorum") == [f"knos3:quorum order={o} judge=0 have=1 of=2"]
        return o, author, wallet, payees

    def carry(asked: list, o, author, payees) -> None:
        """Each audience the neutral run had GitHub sign, as the pinned attest.yml's token started by hand by the seller."""
        for aud in asked:
            word, kind, _order, _head, _terms, mode, pull, _payees = aud.split(":")
            assert (word, kind, mode, pull) == ("knos3", "pay", "1", "12")
            assert c.send([c.pay_ix(o, c.pay_token(o, payees, pr=7, head_sha=HEAD, **c.neutral(author)), payees)]), c.err

    # the suite fails when it is run again: the neutral run signs nothing, so the second judge never arrives and no money moves
    w, _head, trees = staged(tmp_path / "cheat", flags=pay.F_NEUTRAL | pay.F_FAUCET | order_auto.quorum_flags(2))
    code, out, _text = rerun(w, trees, Judge(passed=False))
    assert code == 1 and signs(w, out["verdict"])[0] == 1 and w.signer.asked == []
    o, author, wallet, payees = order()
    carry(w.signer.asked, o, author, payees)
    assert c.order(o).state == "open" and c.order(o).paid == 0 and c.held(o) == 20 * USDC + fee and c.balance(pay.ata(wallet, c.usdc)) == 0
    assert c.quorum(o)[1] is None
    # the honest case: the neutral run signs one pay token, and with it the two judges agree and the order pays
    w, _head, trees = staged(tmp_path / "honest", flags=pay.F_NEUTRAL | pay.F_FAUCET | order_auto.quorum_flags(2))
    code, out, _text = rerun(w, trees, Judge())
    assert code == 0 and signs(w, out["verdict"])[0] == 0 and len(w.signer.asked) == 1
    o, author, wallet, payees = order()
    carry(w.signer.asked, o, author, payees)
    assert c.order(o) is None and c.balance(pay.ata(wallet, c.usdc)) == 20 * USDC


@pytest.mark.skipif(os.name == "nt", reason="a black-box check is a shell script: the judge's machine is Linux or macOS")
def test_a_default_branch_that_moved_after_the_pull_request_left_it_is_not_charged_to_the_pull_request(tmp_path):
    """Found live in the 0.3.18 staging run (knos-e2e-202610020610 #24, attest.yml run 37570503437): the pull request
    changed calc.py only, but the default branch had changed .github/workflows/ after it branched, so the merge's first
    parent and the head differed there too, and the neutral judge refused the honest fix for a protected path. The
    judge is told what GitHub lists for the pull request; a path the pull request itself changes is still refused."""
    w, head, trees = staged(tmp_path)
    trees = tmp_path / "real"
    shutil.copytree(SAMPLE, trees / "base")
    shutil.copytree(SAMPLE, trees / "pr")
    (trees / "pr" / "calc.py").write_text('import re\nKNOWN = [("Hello World", "hello-world"), ("a  b", "a-b"), ("x", "x")]\n'
                                          'def slugify(s):\n    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")\n', encoding="utf-8")
    moved = trees / "base" / ".github" / "workflows" / "knos-attest.yml"          # on the default branch only, after the branch point
    moved.parent.mkdir(parents=True, exist_ok=True)
    moved.write_text("name: knos attest\n", encoding="utf-8")
    w.hub.files[12] = [{"filename": "calc.py", "patch": "@@ -1 +1 @@"}]
    run, _summary = step(w, "plan")
    assert flow.attest(run, str(ORDER), "pay", 12, plan=str(trees)) == 0
    plan = json.loads((trees / "plan.json").read_text(encoding="utf-8"))
    assert plan["changed"] == ["calc.py"]
    plan.update(issue=2, accept=judge.checks_hash(trees / "base" / ".knos" / "acceptance" / "2"))
    v = flow._rerun_judge(plan, trees, dict(ATTESTER), sandbox="auto")
    assert (v["passed"], v["reexecuted"], v["reasons"]) == (True, True, [])
    # what the trees' difference alone says: the workflow is charged to the pull request, and the fix is refused
    v = flow._rerun_judge({k: x for k, x in plan.items() if k != "changed"}, trees, dict(ATTESTER), sandbox="auto")
    assert v["passed"] is False and any(".github/workflows/knos-attest.yml" in r for r in v["reasons"])
    # a protected path the pull request itself changes is refused, as before
    v = flow._rerun_judge({**plan, "changed": ["calc.py", ".github/workflows/knos-attest.yml"]}, trees, dict(ATTESTER), sandbox="auto")
    assert v["passed"] is False and any(".github/workflows/knos-attest.yml" in r for r in v["reasons"])
    # and GitHub that does not list the files whole is a plan that cannot be made: run it again
    w.hub.files[12] = None
    run, _summary = step(w, "plan")
    run._files.clear()
    assert flow.attest(run, str(ORDER), "pay", 12, plan=str(tmp_path / "again")) == 1
