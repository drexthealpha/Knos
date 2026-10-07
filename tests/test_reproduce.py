"""knos reproduce: the report, and what makes someone else's report count: GitHub's token for exactly those bytes, from a
repository that is not Knos's own. No network: the chain, GitHub and the suite are fakes, and the key is the tests' own."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from knos import reproduce as rp

from _settle import NOW, github_claims, sign_jwt, signing_key

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("capabilities_for_reproduce", ROOT / "scripts" / "capabilities.py")
cap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cap)
OWN = json.loads((ROOT / "scripts" / "own_github_ids.json").read_text(encoding="utf-8"))
KEY = signing_key()
KEYS = {"k": KEY.n}        # sign_jwt's header names the key "k"
MANIFEST = json.loads((ROOT / "docs" / "capabilities.json").read_text(encoding="utf-8"))


def _clock(step: float = 1.5):
    t = [0.0]

    def clock() -> float:
        t[0] += step
        return t[0]
    return clock


def _fail():
    raise rp.Fail("devnet runs another build", {"on_chain": "ab"})


def _skip():
    raise rp.Skip("no source checkout")


def _report(**checks) -> dict:
    fakes = {"payment": lambda: {"transaction": "sig"}, "programs": lambda: {"programs": {}}, "simulator": _skip, "claim": lambda: {"verdict": "false"}}
    return rp.build({**fakes, **checks}, version="0.3.15", commit="c" * 40, now=lambda: NOW, clock=_clock())


def _signed(report: dict, **claims) -> dict:
    """The file a run of examples/knos-reproduce.yml makes: the report and the token for its hash."""
    return {"report": report, "token": sign_jwt(KEY, github_claims(aud=rp.AUDIENCE + rp.digest(report), event_name="workflow_dispatch", **claims))}


# ---- the report ---------------------------------------------------------------------------------------------------------

def test_the_report_says_who_ran_and_gives_each_check_its_result_evidence_and_seconds():
    report = _report(programs=_fail, claim=lambda: 1 // 0)
    assert {k: report[k] for k in ("format", "knos", "commit", "cluster", "at")} == {
        "format": "knos-reproduction/1", "knos": "0.3.15", "commit": "c" * 40, "cluster": "devnet", "at": NOW}
    assert report["python"] and report["platform"]
    assert [(c["id"], c["result"], c["seconds"]) for c in report["checks"]] == [
        ("payment", "pass", 1.5), ("programs", "fail", 1.5), ("simulator", "skipped", 1.5), ("claim", "fail", 1.5)]
    by = {c["id"]: c for c in report["checks"]}
    assert by["payment"] == {"id": "payment", "capabilities": ["order_pay"], "result": "pass", "evidence": {"transaction": "sig"}, "why": "", "seconds": 1.5}
    assert by["programs"]["evidence"] == {"on_chain": "ab"} and by["programs"]["why"] == "devnet runs another build"
    assert by["simulator"]["why"] == "no source checkout" and by["claim"]["why"].startswith("ZeroDivisionError")     # a check that breaks is a failure, in one line
    assert (report["pass"], report["fail"], report["skipped"]) == (1, 2, 1)
    # one form, so one hash: whoever writes it, and whatever order the keys came in
    assert rp.canonical(report) == rp.canonical(json.loads(json.dumps(dict(reversed(list(report.items()))))))
    assert rp.digest(report) != rp.digest({**report, "knos": "0.3.16"})
    said = rp.lines(report)
    assert said[0].startswith("PASS    payment") and "devnet runs another build" in said[1] and said[-1].startswith("1 passed, 2 failed, 1 skipped. knos 0.3.15")


def test_only_runs_the_named_checks_in_the_fixed_order_and_refuses_a_name_it_does_not_know():
    assert [c["id"] for c in rp.build({"claim": dict, "payment": dict}, ["claim", "payment"], version="x")["checks"]] == ["payment", "claim"]
    assert [c["id"] for c in rp.build({"claim": dict, "payment": dict}, ["claim"], version="x")["checks"]] == ["claim"]
    with pytest.raises(ValueError, match="no check is called audit"):
        rp.build({"claim": dict}, ["audit"], version="x")


def test_every_check_supports_capabilities_the_manifest_lists_and_the_named_things_are_the_recorded_ones():
    listed = {c["id"]: c for c in MANIFEST["capabilities"]}
    assert set(rp.ORDER) == set(rp.SUPPORTS) and all(set(caps) <= set(listed) for caps in rp.SUPPORTS.values())
    # the payment is the rehearsal's, on the staging deployment docs/CAPABILITIES.md names: the manifest's note of order_pay
    # gives its signature, and because those addresses are not the public program ids, it is no evidence of a stage
    rehearsal = (ROOT / "docs" / "CAPABILITIES.md").read_text(encoding="utf-8").split("## The 0.3.14 rehearsal on devnet", 1)[1]
    assert rp.PAYMENT["signature"] in listed["order_pay"]["note"] and rp.PAYMENT["signature"] in rehearsal
    assert rp.PAYMENT["pay"] in rehearsal and rp.PAYMENT["oidc"] in rehearsal
    assert (listed["order_pay"]["evidence"].get("exercised") or {}).get("signature") != rp.PAYMENT["signature"]
    assert {rp.PAYMENT["pay"], rp.PAYMENT["oidc"]}.isdisjoint(p["id"] for p in MANIFEST["programs"].values())
    # the pull request is one docs/agent_pr_ci.json records: merged, a claim of passing tests, a failed check at that commit
    repo, number = rp.CLAIM["pr"].split("#")
    [recorded] = [p for p in json.loads((ROOT / "docs" / "agent_pr_ci.json").read_text(encoding="utf-8"))["prs"] if p["repo"] == repo and p["number"] == int(number)]
    assert (recorded["sha"], recorded["class"], recorded["merged"]) == (rp.CLAIM["head"], "failed", True) and rp.CLAIM["verdict"] == "false"
    assert all((ROOT / t).is_file() for t in rp.SUITE)


# ---- the checks that need no chain ----------------------------------------------------------------------------------------

def test_the_claim_check_passes_only_on_the_recorded_verdict_at_the_recorded_commit():
    said = {"pr": rp.CLAIM["pr"], "head": rp.CLAIM["head"], "verdict": "false", "failed": 2}
    assert rp.claim(lambda pr: said) == {"pr": rp.CLAIM["pr"], "head": rp.CLAIM["head"], "verdict": "false", "recorded": "false", "failed_checks": 2}
    with pytest.raises(rp.Fail, match="the recorded verdict is 'false'"):
        rp.claim(lambda pr: {**said, "verdict": "true"})
    with pytest.raises(rp.Fail, match="not at the recorded commit"):
        rp.claim(lambda pr: {**said, "head": "d" * 40})

    def refused(pr):
        raise RuntimeError("GitHub refused repos/x (HTTP 403); set GH_TOKEN to lift its rate limit.")
    with pytest.raises(rp.Skip, match="set GH_TOKEN"):       # not asked is not failed
        rp.claim(refused)


def test_the_simulator_runs_the_two_suites_at_the_default_budget_from_a_checkout_and_is_skipped_without_one(tmp_path, monkeypatch):
    with pytest.raises(rp.Skip, match="no source checkout"):
        rp.simulator(None)
    seen = {}

    def run(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return subprocess.CompletedProcess(cmd, seen.get("code", 0), stdout=seen.get("out", "........\n8 passed in 10.70s\n"), stderr="")
    monkeypatch.setenv("KNOS_MACHINE_STEPS", "1")   # a smaller budget in the shell is not the suite that is claimed (and the shell's own setting comes back after)
    got = rp.simulator(tmp_path, run)
    assert got["tests"] == ["tests/test_double_pay.py", "tests/test_invariants_machine.py"] and got["summary"] == "8 passed in 10.70s"
    assert seen["cmd"][:3] == [sys.executable, "-m", "pytest"] and seen["cmd"][-2:] == list(rp.SUITE) and seen["cwd"] == str(tmp_path)
    assert "KNOS_MACHINE_STEPS" not in seen["env"] and seen["env"]["PYTHONPATH"].split(os.pathsep)[0] == str(tmp_path / "src")
    seen.update(code=1, out="1 failed, 7 passed in 9.00s\n")
    with pytest.raises(rp.Fail, match="1 failed, 7 passed"):
        rp.simulator(tmp_path, run)


def test_the_funded_round_is_never_run_unasked_or_without_a_token_or_in_knos_own_repository():
    def never(run):
        raise AssertionError("a round was started")
    for repo, env, why in (("", {"GH_TOKEN": "t"}, "not asked for"), ("octo/widgets", {}, "no GitHub token"), ("drexthealpha/Knos", {"GH_TOKEN": "t"}, "a repository of your own")):
        with pytest.raises(rp.Skip, match=why):
            rp.own_repo(repo, env, never)

    def paid(run):
        run.note('Knos canary: paid. fund 20 s.\n\nknos-canary {"repo":"octo/widgets","ok":true,"fund":20,"pay":41}')
        return 0
    assert rp.own_repo("octo/widgets", {"GH_TOKEN": "t"}, paid) == {"repository": "octo/widgets", "round": {"repo": "octo/widgets", "ok": True, "fund": 20, "pay": 41}}

    def stuck(run):
        run.note('Knos canary: the `pay` leg failed.\n\nknos-canary {"ok":false,"failed":"pay","why":"no payment within 5 minutes"}')
        return 1
    with pytest.raises(rp.Fail, match="the `pay` leg"):
        rp.own_repo("octo/widgets", {"GH_TOKEN": "t"}, stuck)


# ---- a reproduction: the report and GitHub's token for it ---------------------------------------------------------------

def test_a_token_signed_for_the_reports_hash_in_someone_elses_repository_is_accepted():
    doc = _signed(_report())
    facts, wrong = rp.verified(doc, KEYS, OWN, "octo-widgets-36905461215.json")
    assert wrong == []
    assert facts["passed"] == ["payment", "programs", "claim"] and facts["failed"] == []
    assert facts["capabilities"] == ["check", "order_pay", "upgrade_delay", "upgrade_feed"]      # the skipped simulator supports nothing
    assert (facts["repository"], facts["repository_owner_id"], facts["actor_id"], facts["run_id"]) == ("octo/widgets", "424242", "1234567", "36905461215")
    assert facts["run"] == "https://github.com/octo/widgets/actions/runs/36905461215" and facts["report_sha256"] == rp.digest(doc["report"])
    assert rp.file_name(facts) == "octo-widgets-36905461215.json"
    text = rp.body(doc, facts)
    assert "reproductions/octo-widgets-36905461215.json" in text and "| `payment` | pass | 1.5 s | order_pay |" in text and "I am not the maintainer" in text


def test_a_run_of_knos_own_is_refused_by_owner_id_by_who_started_it_and_by_name():
    report, own_id = _report(), str(OWN["ids"][0])
    for claims in ({"repository_owner_id": own_id, "repository_owner": "someone"}, {"actor_id": own_id},
                   {"repository_owner": "DrexTheAlpha", "repository": "DrexTheAlpha/knos-e2e"}):
        facts, wrong = rp.verified(_signed(report, **claims), KEYS, OWN)
        assert len(wrong) == 1 and "the run is Knos's own" in wrong[0], claims
        assert facts["capabilities"] == [] and facts["passed"] == []        # and nothing in it counts


def test_an_own_run_completes_is_filed_apart_and_counts_for_nothing(tmp_path):
    """reproductions/own/: the same signed pair, accepted only when the run IS Knos's own, with no capability; the
    counts read reproductions/*.json and never that folder; an outsider's file there is refused."""
    report, own_id = _report(), str(OWN["ids"][0])
    mine = _signed(report, repository_owner="DrexTheAlpha", repository="DrexTheAlpha/Knos", repository_owner_id=own_id, actor_id=own_id)
    name = "DrexTheAlpha-Knos-36905461215.json"
    facts, wrong = rp.verified(mine, KEYS, OWN, name, ours=True)
    assert wrong == [] and facts["own"] is True and facts["counted"] is False and facts["capabilities"] == []
    assert facts["passed"] == ["payment", "programs", "claim"] and rp.file_name(facts) == name       # what ran is on record; it supports nothing
    assert "the run is Knos's own" in rp.verified(mine, KEYS, OWN, name)[1][0]                      # as a reproduction it is refused, as before
    theirs, bad = rp.verified(_signed(report), KEYS, OWN, "octo-widgets-36905461215.json", ours=True)
    assert len(bad) == 1 and "the run is not Knos's own" in bad[0] and theirs["capabilities"] == [] and theirs["counted"] is False
    edited = {"report": {**mine["report"], "knos": "9.9.9"}, "token": mine["token"]}
    assert any("edited after it was signed" in line for line in rp.verified(edited, KEYS, OWN, name, ours=True)[1])
    assert any("the file is named" in line for line in rp.verified(mine, KEYS, OWN, "other.json", ours=True)[1])
    outside, _ = rp.verified(_signed(report), KEYS, OWN, "octo-widgets-36905461215.json")
    assert outside["counted"] is True and outside["own"] is False
    # on disk: the file under own/ is held by `own_runs`, and the folder every count reads is as empty as before
    folder = tmp_path / "reproductions" / "own"
    folder.mkdir(parents=True)
    (folder / name).write_text(json.dumps(mine), encoding="utf-8")
    (folder / "octo-widgets-36905461215.json").write_text(json.dumps(_signed(report)), encoding="utf-8")
    held, wrong = rp.own_runs(tmp_path, KEYS, OWN)
    assert list(held) == [f"reproductions/own/{name}"] and len(wrong) == 1 and wrong[0].startswith("reproductions/own/octo-widgets-36905461215.json: the run is not Knos's own")
    assert list((tmp_path / "reproductions").glob("*.json")) == []                                    # bench_docs.py and capabilities.py count this glob
    for script in ("bench_docs.py", "capabilities.py"):
        text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
        assert '.glob("*.json")' in text and "rglob" not in text and "**/*.json" not in text, script
    # the pull request's check takes own/ files apart and holds them as Knos's own; the page says so, and no longer
    # that the check is red for them (it said that after the workflow had learned it: seen in the 0.3.19 staging run)
    flow = (ROOT / ".github" / "workflows" / "reproductions.yml").read_text(encoding="utf-8")
    assert 'into="$RUNNER_TEMP/sent/own"' in flow and '--own "${own[@]}"' in flow
    page = (ROOT / "docs" / "REPRODUCE.md").read_text(encoding="utf-8")
    assert "does not yet check" not in page and "checked by `reproductions.yml`" in page


def test_a_report_edited_after_it_was_signed_is_refused_and_so_is_a_token_github_did_not_sign():
    doc = _signed(_report(simulator=_fail))
    edited = copy.deepcopy(doc)
    row = next(c for c in edited["report"]["checks"] if c["id"] == "simulator")
    row.update(result="pass", why="")                 # the failed check, typed over
    facts, wrong = rp.verified(edited, KEYS, OWN)
    assert any("the report was edited after it was signed" in w for w in wrong) and facts["capabilities"] == []
    # the token changed: another audience under the old signature
    head, body, sig = doc["token"].split(".")
    forged = sign_jwt(KEY, github_claims(aud=rp.AUDIENCE + rp.digest(edited["report"]))).split(".")[1]
    assert any("signature is not GitHub's" in w for w in rp.verified({"report": edited["report"], "token": f"{head}.{forged}.{sig}"}, KEYS, OWN)[1])
    # another key than GitHub's, another issuer, a file named for another run, a field too many, not a token
    assert any("not among GitHub's keys" in w for w in rp.verified(doc, {"other": KEY.n}, OWN)[1])
    assert any("signature is not GitHub's" in w for w in rp.verified(doc, {"k": KEY.n + 2}, OWN)[1])
    assert any("issuer is not" in w for w in rp.verified(_signed(doc["report"], iss="https://gitlab.com"), KEYS, OWN)[1])
    assert any("this run's file is octo-widgets-36905461215.json" in w for w in rp.verified(doc, KEYS, OWN, "octo-widgets-1.json")[1])
    assert rp.verified({**doc, "note": "trust me"}, KEYS, OWN)[1] and rp.verified({"report": doc["report"], "token": "abc"}, KEYS, OWN)[1]
    made_up = {**doc["report"], "checks": [{"id": "payment", "capabilities": ["order_pay", "refund"], "result": "pass", "evidence": {}, "why": "", "seconds": 1}]}
    assert any("with the capabilities it names" in w for w in rp.verified(_signed(made_up), KEYS, OWN)[1])     # a check cannot claim more than it supports


def test_a_failing_check_does_not_count_and_the_others_still_do():
    facts, wrong = rp.verified(_signed(_report(programs=_fail)), KEYS, OWN)
    assert wrong == [] and facts["failed"] == ["programs"] and facts["passed"] == ["payment", "claim"]
    assert facts["capabilities"] == ["check", "order_pay"] and "upgrade_delay" not in facts["capabilities"]


def test_an_answer_cut_off_before_its_end_is_a_host_not_asked_and_never_a_failed_check():
    """A first real run (0.3.15) read a program's account over a connection that dropped: http.client.IncompleteRead,
    which is not an OSError, came out as a failed check, and a failed check is a bug report. It is a skip: run it again."""
    import http.client

    def cut(_address):
        raise http.client.IncompleteRead(b"x" * 418574, 112465)
    row = rp.run_check("programs", lambda: rp.programs(cut, lambda: {"entries": []}))
    assert row["result"] == "skipped" and "devnet could not be asked" in row["why"] and "Run it again" in row["why"]

    def dropped(*_):
        raise http.client.RemoteDisconnected("closed")
    with pytest.raises(rp.Skip, match="devnet could not be asked"):
        rp._asked("devnet", dropped, "getTransaction", [])


# ---- scripts/capabilities.py: `reproduced` needs such a file ------------------------------------------------------------

def _stage(cid: str, evidence: dict) -> dict:
    data = copy.deepcopy(MANIFEST)
    c = next(c for c in data["capabilities"] if c["id"] == cid)
    # the stages below `reproduced` as they would be once it runs at the public knos_pay: a staging run is no evidence
    public = {"program": "knos_pay", "id": data["programs"]["knos_pay"]["id"], "version": data["programs"]["knos_pay"]["on_chain"]}
    below = {"deployed": c["evidence"].get("deployed", public), "exercised": c["evidence"].get("exercised", {"signature": "5" * 87})}
    c["stage"], c["evidence"] = "reproduced", {**c["evidence"], **below, "reproduced": evidence}
    return data


def test_a_capability_is_reproduced_only_by_a_valid_outside_file_in_which_a_check_for_it_passed(tmp_path, monkeypatch):
    sent = tmp_path / "reproductions"
    sent.mkdir()
    good, failed = _signed(_report()), _signed(_report(payment=_fail), run_id="2")
    (sent / "octo-widgets-36905461215.json").write_text(json.dumps(good), encoding="utf-8")
    (sent / "octo-widgets-2.json").write_text(json.dumps(failed), encoding="utf-8")
    held, invalid = cap.reproductions(tmp_path, KEYS)
    assert sorted(held) == ["reproductions/octo-widgets-2.json", "reproductions/octo-widgets-36905461215.json"] and invalid == []
    monkeypatch.setattr(cap, "reproductions", lambda root=None, keys=None: (held, []))
    file = "reproductions/octo-widgets-36905461215.json"
    assert cap.problems(_stage("order_pay", {"file": file})) == []
    assert cap.problems(_stage("order_pay", {"file": file, "url": held[file]["run"]})) == []
    # ... and never above a run at a staging address: an outside reproduction does not lift a staging deployment into evidence
    staged = _stage("order_pay", {"file": file})
    next(c for c in staged["capabilities"] if c["id"] == "order_pay")["evidence"]["deployed"] = {"program": "knos_pay", "id": rp.PAYMENT["pay"], "version": "2.1"}
    assert any("is not a public program id" in line for line in cap.problems(staged))
    assert "[outside run](https://github.com/octo/widgets/actions/runs/36905461215)" in cap.table(_stage("order_pay", {"file": file, "url": held[file]["run"]}))
    for evidence, said in (({"url": "https://example.com/a-run"}, "a link to someone else's run is not evidence"),
                           ({"file": "reproductions/nobody.json"}, "is not evidence"),
                           ({"file": "reproductions/octo-widgets-2.json"}, "no check that supports it passed"),       # there, the payment check failed
                           ({"file": file, "url": "https://github.com/octo/widgets/actions/runs/1"}, "the run of")):
        assert any(said in line for line in cap.problems(_stage("order_pay", evidence))), evidence
    assert any("no check that supports it passed" in line for line in cap.problems(_stage("fee_tiers", {"file": file})))     # no check supports it at all
    # a file that does not hold is a problem by being there: Knos's own run, and a report edited after signing
    (sent / "drexthealpha-Knos-3.json").write_text(json.dumps(_signed(_report(), repository="drexthealpha/Knos", repository_owner="drexthealpha", run_id="3")), encoding="utf-8")
    edited = copy.deepcopy(good)
    edited["report"]["knos"] = "9.9.9"
    (sent / "octo-widgets-4.json").write_text(json.dumps(edited), encoding="utf-8")
    monkeypatch.undo()
    held, invalid = cap.reproductions(tmp_path, KEYS)
    assert len(held) == 2 and len(invalid) >= 2 and any("Knos's own" in line for line in invalid) and any("edited after it was signed" in line for line in invalid)


def test_what_a_pull_request_sends_is_accepted_or_refused_in_words_and_a_failed_check_is_a_bug_report(tmp_path, monkeypatch):
    monkeypatch.setattr(cap, "archived_keys", lambda root=None: dict(KEYS))
    said: list[str] = []
    good = tmp_path / "octo-widgets-36905461215.json"
    good.write_text(json.dumps(_signed(_report())), encoding="utf-8")
    assert cap.sent([good], say=said.append) == 0
    assert "a valid outside reproduction" in said[-1] and "Passed: payment, programs, claim" in said[-1] and "`octo/widgets`" in said[-1]
    bad = tmp_path / "octo-widgets-7.json"
    bad.write_text(json.dumps(_signed(_report(programs=_fail), run_id="7")), encoding="utf-8")
    assert cap.sent([good, bad], say=said.append) == 1 and "not accepted" in said[-1] and "the check `programs` failed" in said[-1]
    nothing = tmp_path / "octo-widgets-8.json"
    nothing.write_text(json.dumps(_signed(_report(payment=_skip, programs=_skip, claim=_skip), run_id="8")), encoding="utf-8")
    assert cap.sent([nothing], say=said.append) == 1 and "no check passed" in said[-1]
    (tmp_path / "x.json").write_text("{not json", encoding="utf-8")
    assert cap.sent([tmp_path / "x.json"], say=said.append) == 1 and cap.sent([], say=said.append) == 1
    # a run of Knos's own, sent under reproductions/own/ (--own): accepted as that and as nothing more; an outsider's file there is refused
    own_id = str(OWN["ids"][0])
    mine = tmp_path / "DrexTheAlpha-Knos-36905461215.json"
    mine.write_text(json.dumps(_signed(_report(), repository_owner="DrexTheAlpha", repository="DrexTheAlpha/Knos", repository_owner_id=own_id, actor_id=own_id)), encoding="utf-8")
    assert cap.sent([], say=said.append, own=[mine]) == 0
    assert "own/DrexTheAlpha-Knos-36905461215.json: a valid run of Knos's own" in said[-1] and "is not counted and supports no capability" in said[-1]
    assert cap.sent([mine], say=said.append) == 1 and "the run is Knos's own" in said[-1]
    assert cap.sent([], say=said.append, own=[good]) == 1 and "the run is not Knos's own" in said[-1]
    assert cap.sent([good], say=said.append, own=[mine]) == 0
    monkeypatch.setattr(cap, "sent", lambda paths, live=False, **kw: (paths, live, kw))
    assert cap.main(["reproduction", "--live", "a.json", "--own", "b.json"]) == ([Path("a.json")], True, {"own": [Path("b.json")]})
    assert cap.main(["reproduction", "a.json"]) == ([Path("a.json")], False, {"own": []})
    monkeypatch.undo()
    monkeypatch.setattr(cap, "archived_keys", lambda root=None: dict(KEYS))
    # --live: a key GitHub publishes now and the archive lacks is used, and the maintainer is told to archive it
    monkeypatch.setattr(cap, "archived_keys", lambda root=None: {})
    jwks = {"keys": [{"kty": "RSA", "e": "AQAB", "kid": "k", "n": rp.base64.urlsafe_b64encode(KEY.n.to_bytes(256, "big")).decode().rstrip("=")}]}
    assert cap.sent([good], say=said.append) == 1
    assert cap.sent([good], live=True, say=said.append, fetch=lambda url: jwks) == 0 and "run `python scripts/capabilities.py keys` when merging" in said[-1]


def test_nothing_is_reproduced_yet_and_the_folder_holds_no_file_of_ours():
    assert sorted(p.name for p in (ROOT / "reproductions").iterdir()) == [".gitkeep", "README.md", "own"]
    assert sorted(p.name for p in (ROOT / "reproductions" / "own").iterdir()) == ["README.md"]      # Knos's own runs: none filed yet, and never counted
    assert rp.own_runs(ROOT, cap.archived_keys(), OWN) == ({}, [])
    assert cap.reproductions() == ({}, []) and cap.key_problems() == []
    assert not [c["id"] for c in MANIFEST["capabilities"] if c["stage"] == "reproduced"]
    readme, doc = ((ROOT / p).read_text(encoding="utf-8") for p in ("reproductions/README.md", "docs/REPRODUCE.md"))
    assert "Nobody outside has sent a reproduction yet" in readme and "Nobody outside has done this yet" in doc
    # the archived keys are GitHub's as the tests' own fixture recorded them
    fixture = rp.keys_of(json.loads((ROOT / "tests" / "fixtures" / "github_jwks_2026-10-02.json").read_text(encoding="utf-8")))
    assert fixture and all(cap.archived_keys().get(kid) == n for kid, n in fixture.items())


# ---- the two workflows ----------------------------------------------------------------------------------------------------

def _doc(path: Path) -> dict:
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["on"] = doc.pop(True, doc.get("on"))
    return doc


def test_the_workflow_that_checks_a_pull_request_only_reads_and_runs_nothing_from_it():
    doc = _doc(ROOT / ".github" / "workflows" / "reproductions.yml")
    assert doc["on"] == {"pull_request": {"paths": ["reproductions/**"]}} and doc["permissions"] == {}
    [job] = doc["jobs"].values()
    assert job["permissions"] == {"contents": "read", "pull-requests": "read"} and "secrets" not in json.dumps(job)
    [checkout] = [s for s in job["steps"] if "uses" in s]
    assert checkout["with"] == {"ref": "${{ github.event.pull_request.base.sha }}", "persist-credentials": False}
    fetch, verify = [s["run"] for s in job["steps"] if "run" in s]
    assert "${{" not in fetch + verify and "git " not in fetch + verify       # no expression in a script, and nothing of the head is checked out
    assert 'into="$RUNNER_TEMP/sent"' in fetch and '> "$into/$base"' in fetch and "application/vnd.github.raw" in fetch and '[ "$status" != added ]' in fetch
    # a file of reproductions/own/ goes to a folder of its own and is verified as a run of Knos's own (--own), never as a reproduction
    assert 'case "$base" in own/*) base="${base#own/}"; into="$RUNNER_TEMP/sent/own" ;; esac' in fetch
    assert fetch.index('own/*)') < fetch.index('case "$base" in -*|*[!A-Za-z0-9._-]*)')         # the name is held to the same letters after the folder is cut
    assert 'python3 scripts/capabilities.py reproduction --live "${files[@]}" --own "${own[@]}"' in verify and "install" not in fetch + verify
    assert 'own=("$RUNNER_TEMP"/sent/own/*.json)' in verify


def test_the_example_signs_in_a_job_that_installs_nothing_and_its_file_is_one_the_check_accepts(tmp_path):
    doc = _doc(ROOT / "examples" / "knos-reproduce.yml")
    assert set(doc["on"]) == {"workflow_dispatch"} and doc["permissions"] == {}
    # a fork has it under Actions already: Knos's own copy is the example, byte for byte
    assert (ROOT / ".github" / "workflows" / "knos-reproduce.yml").read_bytes() == (ROOT / "examples" / "knos-reproduce.yml").read_bytes()
    run, sign = doc["jobs"]["run"], doc["jobs"]["sign"]
    assert run["permissions"] == {"contents": "read"} and sign["permissions"] == {"id-token": "write"} and sign["needs"] == "run"
    assert [s["run"] for s in run["steps"] if "run" in s][-1] == "knos reproduce --out report.json"
    [script] = [s["run"] for s in sign["steps"] if "run" in s]
    assert "${{" not in script and "install" not in script and "knos " not in script.replace("knos reproduce`", "")
    assert [s["uses"].split("@")[0] for s in sign["steps"] if "uses" in s] == ["actions/download-artifact", "actions/upload-artifact"]
    assert "audience=knos-repro:$SHA" in script and 'sha256sum report.json' in script
    # the part that packs, run here as the job runs it: what it writes is a reproduction `verified` accepts
    pack = script.split("python3 - <<'PACK'\n")[1].split("\nPACK")[0]
    report = _report()
    (tmp_path / "report.json").write_bytes(rp.canonical(report))
    (tmp_path / "token.json").write_text(json.dumps({"value": _signed(report)["token"]}), encoding="utf-8")
    env = {**os.environ, "GITHUB_REPOSITORY": "octo/widgets", "GITHUB_RUN_ID": "36905461215", "SHA": rp.digest(report), "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
           "PYTHONIOENCODING": "utf-8"}
    got = subprocess.run([sys.executable, "-c", pack], cwd=str(tmp_path), env=env, capture_output=True, text=True, encoding="utf-8")
    assert got.returncode == 0, got.stderr
    [made] = (tmp_path / "out").iterdir()
    facts, wrong = rp.verified(json.loads(made.read_text(encoding="utf-8")), KEYS, OWN, made.name)
    assert wrong == [] and made.name == "octo-widgets-36905461215.json" and facts["passed"] == ["payment", "programs", "claim"]
    # and the text it prints is the one `knos reproduce --pack` prints
    assert rp.body(json.loads(made.read_text(encoding="utf-8")), facts) in (tmp_path / "summary.md").read_text(encoding="utf-8")
    # in Knos's own account it says that the run is not a reproduction, and never "I am not the maintainer" (the first
    # real run, in drexthealpha/knos-e2e, printed that sentence)
    own = {**env, "GITHUB_REPOSITORY": "drexthealpha/knos-e2e", "GITHUB_STEP_SUMMARY": str(tmp_path / "own.md")}
    got = subprocess.run([sys.executable, "-c", pack], cwd=str(tmp_path), env=own, capture_output=True, text=True, encoding="utf-8")
    said = (tmp_path / "own.md").read_text(encoding="utf-8")
    assert got.returncode == 0 and (tmp_path / "out" / "drexthealpha-knos-e2e-36905461215.json").is_file()
    assert "an account of Knos's own, so it is not a reproduction" in said and "I am not the maintainer" not in said and "use this as its text" not in said
    assert "I am not the maintainer" in (tmp_path / "summary.md").read_text(encoding="utf-8")


# ---- the command ----------------------------------------------------------------------------------------------------------

def test_the_command_writes_the_report_in_its_one_form_names_the_audience_and_exits_1_when_a_check_fails(tmp_path, monkeypatch):
    typer = pytest.importorskip("typer")
    from typer.testing import CliRunner
    app = typer.Typer()
    app.command("other")(lambda: None)
    rows: list = []
    rp.register(app, rows)
    assert rows[0][0] == "reproduce"
    fakes = {"payment": lambda: {"transaction": "sig"}, "programs": lambda: {}, "simulator": _skip, "claim": lambda: {}, "own_repo": _skip}
    monkeypatch.setattr(rp, "live", lambda rpc="", own="", env=None: fakes)
    out, outputs = tmp_path / "report.json", tmp_path / "outputs"
    got = CliRunner().invoke(app, ["reproduce", "--out", str(out)], env={"GITHUB_OUTPUT": str(outputs)})
    assert got.exit_code == 0, got.output
    report = json.loads(out.read_bytes())
    assert out.read_bytes() == rp.canonical(report) and [c["id"] for c in report["checks"]] == list(rp.ORDER)
    sha = rp.digest(report)
    assert f"knos-repro:{sha}" in got.output and outputs.read_text(encoding="utf-8") == f"sha256={sha}\n"
    assert __import__("hashlib").sha256(out.read_bytes()).hexdigest() == sha        # what `sha256sum report.json` gives in the signing job
    # --only takes a check's name or a capability's id
    got = CliRunner().invoke(app, ["reproduce", "--out", str(out), "--only", "upgrade_feed", "--only", "claim"])
    assert got.exit_code == 0 and [c["id"] for c in json.loads(out.read_bytes())["checks"]] == ["programs", "claim"]
    assert CliRunner().invoke(app, ["reproduce", "--out", str(out), "--only", "nothing"]).exit_code == 2
    fakes["programs"] = _fail
    assert CliRunner().invoke(app, ["reproduce", "--out", str(out)]).exit_code == 1
