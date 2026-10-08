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


# ---- the whole path as one command, against a simulator (0.3.20) --------------------------------------------------------

def _run(tmp_path, *more) -> tuple[int, str, Path]:
    out = tmp_path / "out"
    done = subprocess.run([sys.executable, "-m", "knos.private", "run", "--repo", str(EX), "--attestors", str(EX / "attestors.json"), "--out", str(out),
                           "--seed", "knos private test", "--now", str(NOW), *more], capture_output=True, text=True, encoding="utf-8",
                          env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")}, check=False, timeout=120)
    return done.returncode, done.stdout + done.stderr, out


def test_one_command_runs_the_private_path_end_to_end_against_the_simulator(tmp_path):
    code, said, out = _run(tmp_path)
    assert code == 0, said
    lines = said.splitlines()
    assert lines[0] == private.SIMULATED and "No private customer has run this path." in lines[0]
    assert [n for n in "12345678" if any(line.startswith(n + ". ") for line in lines)] == list("12345678")           # every step spoke, in order
    assert "1. attestors: independent organisations, counted as 2." in said and "the simulator ran NO suite" in said
    assert "Today: keep. A day past 7 years: hashes (a dry run: nothing was removed)" in said                         # examples/private/retention.json, read from beside the attestors file
    assert "the buyer alone cannot resolve it" in said and "resolved by both parties (buyer and supplier) to: accepted" in said
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert [f for f in files if not f.startswith("sealed/")] == ["buyer.vault-key.json", "checkpoint.json", "dispute.json", "jwks.json", "record.json", "supplier.vault-key.json", "token.jwt"]
    # what may leave is a verdict word and hashes: the stand-in names no checks and no assurance, and nothing of the folder
    doc = json.loads((out / "record.json").read_text(encoding="utf-8"))
    assert private.leaks(doc) is None and (doc["verdict"], doc["checks_sha256"], doc["assurance"]) == ("accepted", None, None)
    assert "knos-private.yml" not in json.dumps(doc) and doc["attestors_sha256"] == hashlib.sha256(RAW).hexdigest()
    # the evidence is sealed to BOTH parties: each key opens it alone, a stranger's does not, and it is the archive the record names
    from knos import vault
    sealed = next((out / "sealed").glob("*.vault")).read_bytes()
    for who in ("buyer", "supplier"):
        plain, head = vault.open_(sealed, vault.private_of(json.loads((out / f"{who}.vault-key.json").read_text(encoding="utf-8"))))
        assert hashlib.sha256(plain).hexdigest() == doc["evidence_sha256"] and [r["label"] for r in head["recipients"]] == ["buyer", "supplier"]
    with pytest.raises(ValueError, match="was not sealed to that key"):
        vault.open_(sealed, vault.private_of(vault.new_key("stranger", lambda n: b"\x07" * n)))
    assert b"verdict.json" not in sealed and b"attestors.json" not in sealed                 # whoever stores the file reads its header only
    # the files it wrote pass the offline check a second person would run, signature included
    check = subprocess.run([sys.executable, "-m", "knos.private", "check", "--record", str(out / "record.json"), "--token", str(out / "token.jwt"),
                            "--attestors", str(EX / "attestors.json"), "--jwks", str(out / "jwks.json")], capture_output=True, text=True, encoding="utf-8",
                           env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")}, check=False, timeout=60)
    assert check.returncode == 0 and "the issuer's RS256 signature holds under the key given" in check.stdout and "signed for attestor acme-ghes" in check.stdout
    # the same seed gives the same record: nothing in the run reads a clock or a random source the test did not give it
    again = private.run(EX, EX / "attestors.json", tmp_path / "again", now=NOW, seed="knos private test", retention=json.loads((EX / "retention.json").read_text()), say=lambda _l: None)
    assert again["record"] == doc and again["dispute"] == json.loads((out / "dispute.json").read_text(encoding="utf-8"))


def test_a_dispute_is_opened_by_a_party_who_could_open_the_evidence_and_resolved_only_by_both(tmp_path):
    from solders.keypair import Keypair
    got = private.run(EX, EX / "attestors.json", tmp_path / "out", now=NOW, seed="dispute", outcome="rejected", say=lambda _l: None)
    doc, d, keys = got["record"], got["dispute"], got["keys"]
    assert private.dispute_check(d, doc, keys) == ["opened by the supplier; resolved by both parties (buyer and supplier) to: rejected", "the line counts as rejected: it is not billed"]
    from knos import vault
    sealed = next((tmp_path / "out" / "sealed").glob("*.vault")).read_bytes()
    opened, _ = vault.open_(sealed, vault.private_of(json.loads((tmp_path / "out" / "buyer.vault-key.json").read_text(encoding="utf-8"))))
    buyer, supplier, stranger = Keypair.from_seed(b"\x01" * 32), Keypair.from_seed(b"\x02" * 32), Keypair.from_seed(b"\x03" * 32)
    mine = {"buyer": str(buyer.pubkey()), "supplier": str(supplier.pubkey())}
    # opening: by a party, on the archive the record names. A party that cannot open the evidence opens no dispute
    with pytest.raises(ValueError, match="is neither"):
        private.dispute_open(doc, ["buyer", "supplier"], "auditor", opened, NOW)
    with pytest.raises(ValueError, match="its sha256 differs"):
        private.dispute_open(doc, ["buyer", "supplier"], "buyer", opened + b"x", NOW)
    unsigned = private.dispute_open(doc, ["buyer", "supplier"], "buyer", opened, NOW)
    with pytest.raises(ValueError, match="buyer's signature is missing"):
        private.dispute_check(unsigned, doc, mine)
    opened_by_buyer = private.dispute_sign(unsigned, "buyer", buyer)
    assert private.dispute_check(opened_by_buyer, doc, mine)[1] == private.DISPUTED_MEANS and "not billed" in private.DISPUTED_MEANS
    with pytest.raises(ValueError, match="buyer's signature is missing or does not hold"):          # the supplier's key under the buyer's name
        private.dispute_check(private.dispute_sign(unsigned, "buyer", supplier), doc, mine)
    # resolving: both sign the SAME outcome. One alone, a stranger, or two who signed different outcomes do not resolve it
    proposed = private.dispute_resolve(opened_by_buyer, "accepted", NOW + 60)
    one = private.dispute_sign(proposed, "buyer", buyer)
    with pytest.raises(ValueError, match="resolved by both parties, never by one"):
        private.dispute_check(one, doc, mine)
    with pytest.raises(ValueError, match="not a party"):
        private.dispute_sign(one, "knos", stranger)
    with pytest.raises(ValueError, match="supplier's signature is missing or does not hold"):
        private.dispute_check({**one, "signatures": {**one["signatures"], "supplier": private.dispute_sign(proposed, "supplier", stranger)["signatures"]["supplier"]}}, doc, mine)
    other = private.dispute_sign(private.dispute_resolve(opened_by_buyer, "rejected", NOW + 60), "supplier", supplier)
    with pytest.raises(ValueError, match="supplier's signature is missing or does not hold"):
        private.dispute_check({**one, "signatures": {**one["signatures"], "supplier": other["signatures"]["supplier"]}}, doc, mine)
    both = private.dispute_sign(one, "supplier", supplier)
    assert private.dispute_check(both, doc, mine)[1] == "the line counts as accepted on the invoice (a private record moves no money)"
    for bad, why in (({**both, "outcome": "paid"}, "a dispute is"), ({**both, "record_sha256": "0" * 64}, "another record"), ({**both, "extra": 1}, "a dispute is")):
        with pytest.raises(ValueError, match=why):
            private.dispute_check(bad, doc, mine)
    with pytest.raises(ValueError, match="resolved already"):
        private.dispute_resolve(both, "rejected", NOW)
    with pytest.raises(ValueError, match="public key of each party"):
        private.dispute_check(both, doc, {"buyer": mine["buyer"]})


def test_the_run_refuses_what_the_path_refuses_and_takes_a_real_verdict_and_a_gitlab_attestor(tmp_path, capsys):
    one_sided = {**AGREED, "attestors": [{**a, "approved_by": ["buyer"]} for a in AGREED["attestors"]]}
    (tmp_path / "one.json").write_text(json.dumps(one_sided), encoding="utf-8")
    assert private.main(["run", "--repo", str(EX), "--attestors", str(tmp_path / "one.json"), "--out", str(tmp_path / "o1"), "--seed", "s", "--now", str(NOW)]) == 1
    assert "not done: No attestor was approved by both parties." in capsys.readouterr().out and not (tmp_path / "o1").exists()
    assert private.main(["run", "--repo", str(tmp_path / "nowhere"), "--attestors", str(EX / "attestors.json"), "--out", str(tmp_path / "o2")]) == 1
    assert "is not a folder" in capsys.readouterr().out
    # the judge's own verdict file is used as it is: its checks and its assurance are then in the record
    gitlab_only = {**AGREED, "attestors": [AGREED["attestors"][1]]}
    (tmp_path / "gl.json").write_text(json.dumps(gitlab_only), encoding="utf-8")
    got = private.run(EX, tmp_path / "gl.json", tmp_path / "o3", verdict=VERDICT, terms=TERMS, now=NOW, seed="gl", say=lambda _l: None)
    assert (got["record"]["assurance"], got["record"]["checks_sha256"], got["arrangement"]["arrangement"]) == ("hermetic", "c" * 64, "one attestor")
    assert "project_id" in private._claims(got["token"]) and got["record"]["terms_sha256"] == hashlib.sha256(TERMS).hexdigest()
    page = (ROOT / "docs" / "PRIVATE.md").read_text(encoding="utf-8")
    assert "python -m knos.private run --repo" in page and "No private customer has run it" in page and "gh workflow run knos-private.yml" in page
