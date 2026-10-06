"""The private-repository path (src/knos/private.py, examples/private, docs/PRIVATE.md): what may leave a customer's
network, who both parties approved, what two attestors amount to, and the rules of the workflow a customer installs.
Tokens are signed with the tests' key, not by any forge: no private-repository customer has run this."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from _settle import NOW, modulus, sign_jwt, signing_key
from knos import ids, private, receipt

ROOT = Path(__file__).parents[1]
EX = ROOT / "examples" / "private"
RAW = (EX / "attestors.json").read_bytes()
AGREED = json.loads(RAW)
TERMS = b'{"checks":["unit"]}\n'
VERDICT = {"passed": True, "checks_hash": "c" * 64, "assurance": "hermetic", "reasons": ["tests/test_pay.py::test_refund passed"],
           "evidence": {"issue": "77", "runner": "blackbox", "artifact": {"base": "1" * 64, "pr": "2" * 64}, "image": {"ref": "ghcr.io/x/y", "digest": "sha256:" + "ab" * 32}}}
EVIDENCE = hashlib.sha256(b"sealed evidence").hexdigest()


def _with(*attestors, parties=("buyer", "supplier")) -> dict:
    return {"type": "knos.attestors", "version": 1, "parties": list(parties), "attestors": list(attestors)}


def _one(name, issuer, run_by, admin, approved=("buyer", "supplier"), repo=1) -> dict:
    return {"name": name, "issuer": issuer, "issuer_run_by": run_by, "repository_id": repo, "workflow": f"{name}/wf.yml", "administrator": admin, "approved_by": list(approved)}


def _token(doc: dict, **over) -> str:
    a = AGREED["attestors"][0]
    claims = {"iss": a["issuer"], "aud": private.audience(doc), "repository_id": str(a["repository_id"]), "repository_owner_id": "12", "actor_id": "900",
              "job_workflow_ref": a["workflow"] + "@refs/heads/main", "runner_environment": "self-hosted", "iat": NOW, "exp": NOW + 300, **over}
    return sign_jwt(signing_key(), claims)


def test_the_record_that_leaves_holds_a_verdict_word_and_hashes_and_nothing_else():
    doc = private.record(VERDICT, TERMS, RAW, EVIDENCE, "a" * 40)
    assert doc["verdict"] == "accepted" and doc["terms_sha256"] == hashlib.sha256(TERMS).hexdigest() and doc["attestors_sha256"] == hashlib.sha256(RAW).hexdigest()
    assert private.leaks(doc) is None and "test_pay" not in json.dumps(doc) and "ghcr.io" not in json.dumps(doc) and "77" not in [doc.get("issue")]
    assert all(v is None or v == 1 or re.fullmatch(r"[a-z_.-]{1,40}|(sha256:)?[0-9a-f]{40}([0-9a-f]{24})?", v) for v in doc.values()) and len(doc) == 12
    assert private.record({**VERDICT, "passed": False}, TERMS, RAW, EVIDENCE)["verdict"] == "rejected"
    for unsure in ({"error": "the judge wrote no verdict"}, {**VERDICT, "passed": None}, {"passed": True}):       # no answer is its own verdict, never a rejection
        got = private.record(unsure, TERMS, RAW, EVIDENCE)
        assert got["verdict"] == "insufficient_evidence" and got["pr_tree_sha256"] is None and got["verdict"] in ids.VERDICTS
    for leak in ({**doc, "repository": "acme/app"}, {**doc, "commit": "refs/heads/secret-project"}, {**doc, "assurance": "src/billing/core.py"},
                 {**doc, "verdict": "passed"}, {**doc, "checks_sha256": ["unit"]}, {k: v for k, v in doc.items() if k != "commit"}):
        assert private.leaks(leak)
    with pytest.raises(ValueError, match="no record was made"):
        private.record({**VERDICT, "checks_hash": "the unit tests"}, TERMS, RAW, EVIDENCE)


def test_a_token_counts_only_from_an_attestor_both_parties_approved_and_only_for_its_own_record():
    doc, n = private.record(VERDICT, TERMS, RAW, EVIDENCE), modulus(signing_key())
    said = private.check(doc, _token(doc), RAW, n, TERMS, b"sealed evidence")
    assert said[0] == "verdict: accepted" and "acme-ghes" in said[2] and "run by: buyer" in said[2] and "RS256 signature holds" in said[3]
    assert "the terms are the bytes the record names" in said and said[-1] == private.arrangement(AGREED)["says"]
    assert any(line.startswith("limit: no key was given") for line in private.check(doc, _token(doc), RAW))
    other = private.record({**VERDICT, "passed": False}, TERMS, RAW, EVIDENCE)
    refusals = [(other, _token(doc), RAW, n, "signed for another record"),
                (doc, _token(doc, repository_id="4712"), RAW, n, "not from an attestor both parties approved"),
                (doc, _token(doc, iss="https://token.actions.githubusercontent.com"), RAW, n, "not from an attestor both parties approved"),
                (doc, _token(doc, job_workflow_ref="acme/knos-private/.github/workflows/other.yml@refs/heads/main"), RAW, n, "not from an attestor both parties approved"),
                (doc, _token(doc), RAW, n + 2, "signature does not hold"),
                (doc, _token(doc), RAW + b" ", n, "another attestors file")]
    for d, token, raw, key, why in refusals:
        with pytest.raises(ValueError, match=why):
            private.check(d, token, raw, key)
    one_sided = {**AGREED, "attestors": [{**AGREED["attestors"][0], "approved_by": ["buyer"]}, AGREED["attestors"][1]]}       # the buyer's choice alone
    raw = json.dumps(one_sided).encode()
    mine = private.record(VERDICT, TERMS, raw, EVIDENCE)
    with pytest.raises(ValueError, match="not from an attestor both parties approved"):
        private.check(mine, _token(mine), raw, n)
    with pytest.raises(ValueError, match="terms given are not the ones"):
        private.check(doc, _token(doc), RAW, n, b"other terms")
    gitlab = AGREED["attestors"][1]                                 # a self-managed GitLab names the project and the pipeline file otherwise
    claims = {"iss": gitlab["issuer"], "aud": private.audience(doc), "project_id": "88", "ci_config_ref_uri": gitlab["workflow"] + "@refs/heads/main"}
    assert "supplier-gitlab" in private.check(doc, sign_jwt(signing_key(), claims), RAW, n)[2]


def test_two_organisations_agreeing_is_told_apart_from_two_evaluators_under_one_administrator_or_one_issuer():
    ghes, public = "https://github.acme.example/_services/token", "https://token.actions.githubusercontent.com"
    kind = lambda *a: (private.arrangement(_with(*a))["arrangement"], private.arrangement(_with(*a))["counts_as"])  # noqa: E731
    assert kind(_one("a", ghes, "buyer", "Acme", approved=["buyer"])) == ("no attestor both approved", 0)
    assert kind(_one("a", ghes, "buyer", "Acme")) == ("one attestor", 1) and "can sign any claim" in private.arrangement(_with(_one("a", ghes, "buyer", "Acme")))["says"]
    assert "can sign any claim" not in private.arrangement(_with(_one("a", public, "third party", "Assessor Ltd")))["says"]
    # two evaluators one administrator can change: one judge, whatever their issuers
    assert kind(_one("a", public, "third party", "Acme platform team"), _one("b", "https://gitlab.com", "third party", "acme platform team ")) == ("one administrator", 1)
    # two repositories on the buyer's own server, with two team names: its administrators sign for both
    assert kind(_one("a", ghes, "buyer", "Acme team one"), _one("b", ghes, "buyer", "Acme team two", repo=2)) == ("one issuer", 1)
    # two servers, both the buyer's
    assert kind(_one("a", ghes, "buyer", "Acme team one"), _one("b", "https://gitlab.acme.example", "buyer", "Acme team two")) == ("one issuer", 1)
    # each party attests on its own server: two organisations agreeing, each one's word its own
    both = private.arrangement(AGREED)
    assert (both["arrangement"], both["counts_as"]) == ("independent organisations", 2) and "that party's own word" in both["says"]
    # two outside assessors on a public forge neither party runs
    out = private.arrangement(_with(_one("a", public, "third party", "Assessor One Ltd"), _one("b", public, "third party", "Assessor Two GmbH", repo=2)))
    assert (out["arrangement"], out["counts_as"]) == ("independent organisations", 2) and "the parties' statement, not a signature" in out["says"]
    # an attestor only one side approved does not count towards the two
    assert kind(_one("a", public, "third party", "Assessor One Ltd"), _one("b", public, "third party", "Assessor Two GmbH", approved=["supplier"])) == ("one attestor", 1)
    assert set(private.ARRANGEMENTS) >= {kind(a)[0] for a in (_one("a", ghes, "buyer", "x"),)}
    for bad in ({}, _with(), _with(_one("a", "http://plain", "buyer", "x")), _with(_one("a", ghes, "the buyer", "x")), _with(_one("a", ghes, "buyer", "x"), _one("a", ghes, "buyer", "y")),
                _with(_one("a", ghes, "buyer", "x", approved=["auditor"])), _with(_one("a", ghes, "buyer", "x"), parties=("buyer", "buyer"))):
        with pytest.raises(ValueError, match="an attestors file is"):
            private.attestors_of(bad)


def test_what_the_receipt_records_of_each_arrangement_and_where_its_comparison_stops():
    """knos.receipt compares account ids (read here, not changed). It sees one account behind two judges; it cannot see
    one organisation behind two accounts, and across two instances the ids are not comparable at all."""
    judge = lambda kind, repo, owner, actor: receipt.evaluator(kind, {"repository_id": repo, "repository_owner_id": owner, "actor_id": actor,  # noqa: E731
                                                                      "runner_environment": "self-hosted"}, [500], [700])
    two_orgs = [judge("attestor", 1, 11, 21), judge("neutral", 2, 12, 22)]
    assert receipt.independence_of(two_orgs) == (False, receipt.APART.format(n=2)) and "same_controller: false" in private.receipt_shows(two_orgs)
    one_admin_one_account = [judge("attestor", 1, 11, 21), judge("neutral", 2, 11, 22)]
    assert receipt.independence_of(one_admin_one_account)[0] is True and "count this quorum as one judge" in private.receipt_shows(one_admin_one_account)
    one_admin_two_accounts = [judge("attestor", 1, 11, 21), judge("neutral", 2, 12, 22)]          # the same person, two accounts: the receipt cannot tell
    assert receipt.independence_of(one_admin_two_accounts)[0] is False and "no receipt can show that they are not" in receipt.APART
    two_instances_equal_ids = [judge("attestor", 1, 5, 9), judge("neutral", 1, 5, 9)]            # owner 5 on one server and owner 5 on another are two accounts
    assert receipt.independence_of(two_instances_equal_ids)[0] is True and "numbers its own accounts" in private.receipt_shows(two_instances_equal_ids)
    assert judge("attestor", 1, 500, 21)["independent_of_buyer"] is False and judge("attestor", 1, 11, 700)["independent_of_seller"] is False
    page = (ROOT / "docs" / "PRIVATE.md").read_text(encoding="utf-8")
    assert all(a in page for a in private.ARRANGEMENTS) and "same_controller" in page and "numbers its own accounts" in page


def test_the_workflow_signs_in_a_job_that_runs_no_pull_request_code_and_uploads_only_the_record_and_the_token():
    text = (EX / "knos-private.yml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    judge, sign = doc["jobs"]["judge"], doc["jobs"]["sign"]
    assert doc["permissions"] == {} and judge["permissions"] == {"contents": "read"} and sign["permissions"] == {"id-token": "write"}
    assert "self-hosted" in judge["runs-on"] and "self-hosted" in sign["runs-on"] and set(doc[True]) == {"workflow_dispatch"}      # yaml reads `on` as True
    uses = [s["uses"] for job in (judge, sign) for s in job["steps"] if "uses" in s]
    assert uses and all(re.fullmatch(r"[\w-]+/[\w-]+@[0-9a-f]{40}", u) for u in uses)                # every action by a full commit
    assert not any("checkout" in s.get("uses", "") for s in sign["steps"]) and "secrets." not in json.dumps(sign) and "knos proof judge" not in json.dumps(sign)
    assert all(s.get("with", {}).get("persist-credentials") is False for s in judge["steps"] if "checkout" in s.get("uses", ""))
    runs = [s["run"] for job in (judge, sign) for s in job["steps"] if "run" in s]
    assert not any("${{" in r for r in runs)                                                         # what a person types reaches a step as data, never as script
    assert not any("secrets." in json.dumps(s) for s in judge["steps"] if "run" in s)                # the step that runs the code is not given the token
    uploads = {s["with"]["name"]: s["with"]["path"] for job in (judge, sign) for s in job["steps"] if "upload-artifact" in s.get("uses", "")}
    assert uploads == {"knos-record": "out/record.json", "knos-sealed-evidence": "sealed/*.vault", "knos-private-verdict": "out/"}
    assert "audience=$AUDIENCE" in runs[-1] and "knos vault seal evidence.tar" in "".join(runs) and "python -m knos.private record" in text
    for words in ("Nobody with a private repository has run this file", "This record is not a payment", "can sign any claim"):
        assert words in text


def test_the_two_commands_the_workflow_runs_write_a_record_and_check_it(tmp_path):
    (tmp_path / "verdict.json").write_text(json.dumps(VERDICT), encoding="utf-8")
    (tmp_path / "terms.json").write_bytes(TERMS)
    (tmp_path / "evidence.tar").write_bytes(b"sealed evidence")
    run = lambda *a: subprocess.run([sys.executable, "-m", "knos.private", *a], capture_output=True, encoding="utf-8", cwd=tmp_path,  # noqa: E731
                                    env={"PYTHONPATH": str(ROOT / "src"), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
    made = run("record", "--verdict", "verdict.json", "--terms", "terms.json", "--attestors", str(EX / "attestors.json"), "--evidence", "evidence.tar", "--out", "record.json")
    doc = json.loads((tmp_path / "record.json").read_text(encoding="utf-8"))
    assert made.returncode == 0 and made.stdout.strip() == private.audience(doc) == "knos-private:" + hashlib.sha256((tmp_path / "record.json").read_bytes()).hexdigest()
    (tmp_path / "token.jwt").write_text(_token(doc), encoding="utf-8")
    n = modulus(signing_key())
    jwk = {"kty": "RSA", "kid": "k", "alg": "RS256", "e": "AQAB", "n": __import__("base64").urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()}
    (tmp_path / "jwks.json").write_text(json.dumps({"keys": [jwk]}), encoding="utf-8")
    ok = run("check", "--record", "record.json", "--token", "token.jwt", "--attestors", str(EX / "attestors.json"), "--jwks", "jwks.json", "--terms", "terms.json", "--evidence", "evidence.tar")
    assert ok.returncode == 0 and "the issuer's RS256 signature holds" in ok.stdout and "verdict: accepted" in ok.stdout, ok.stdout + ok.stderr
    (tmp_path / "terms.json").write_bytes(b"other")
    bad = run("check", "--record", "record.json", "--token", "token.jwt", "--attestors", str(EX / "attestors.json"), "--terms", "terms.json")
    assert bad.returncode == 1 and bad.stdout.startswith("not done: the terms given are not the ones")


def test_the_page_says_how_an_enterprise_issuer_is_admitted_who_opens_sealed_evidence_and_that_nobody_has_run_it():
    page = (ROOT / "docs" / "PRIVATE.md").read_text(encoding="utf-8")
    for words in ("https://HOSTNAME/_services/token", "/.well-known/openid-configuration", "oauth/discovery/keys", "jwks_uri", "register_private_key_ix",
                  "[VERIFIER.md](VERIFIER.md)", "../examples/issuers", "No private-repository customer has run this", "not legal advice",
                  "examples/private/knos-private.yml", "knos vault open", "test USDC", "ci_id_tokens_issuer_url"):
        assert words in page, words
    assert not re.search(r"\b(trustless|bulletproof|immutable)\b", page)
