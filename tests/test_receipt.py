"""The acceptance receipt (docs/RECEIPT.md): the reference checker and the JSON Schema accept the five conformance
vectors of each version and give their digests, both refuse every invalid one for the reason it names, a version 2
receipt says its four parts in order, the page prints a vector of each version, and
scripts/sas_receipt.mjs computes the same digest and builds the attestation's instructions (when its package is there)."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from knos import receipt

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "docs" / "receipt" / "vectors.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "docs" / "receipt" / "acceptance-receipt.v1.schema.json").read_text(encoding="utf-8"))
SCHEMA2 = json.loads((ROOT / "docs" / "receipt" / "acceptance-receipt.v2.schema.json").read_text(encoding="utf-8"))
BEYOND_SCHEMA2 = {"a trust assumption left out", "a judge version that is not the signed workflow commit", "amendments out of order",
                  "allowed paths without a policy version", "shares that do not add up to 10000, in version 2"}
# the rules of an invalid vector that JSON Schema cannot express (sums, hashes, relations between fields)
BEYOND_SCHEMA = {"shares that do not add up to 10000", "payees who received more than was paid", "a repository judge in another repository",
                 "a scope that is not the repository's", "a private order with a public judge"}


def _changed(v: dict, of: str = "valid") -> dict:
    r = copy.deepcopy(VECTORS[of][v["of"]]["receipt"])
    for path, value in v["set"].items():
        at, *rest = path.split(".")
        node = r
        for step in [at, *rest][:-1]:
            node = node[int(step)] if isinstance(node, list) else node[step]
        last = [at, *rest][-1]
        node[int(last) if isinstance(node, list) else last] = value
    return r


def test_five_receipts_are_valid_and_have_the_digests_the_vectors_give():
    assert len(VECTORS["valid"]) == 5 and len({v["name"] for v in VECTORS["valid"]}) == 5
    for v in VECTORS["valid"]:
        assert receipt.check(v["receipt"]) is None, v["name"]
        assert receipt.digest(v["receipt"]) == v["sha256"], v["name"]
        assert json.loads(receipt.canonical(v["receipt"])) == v["receipt"] and b" " not in receipt.canonical(v["receipt"]).split(b'"job_workflow_ref"')[0]
    kinds = {v["receipt"]["judge"]["kind"] for v in VECTORS["valid"]}
    assert kinds == set(receipt.JUDGES) and any(v["receipt"]["repository"] is None for v in VECTORS["valid"])
    assert {len(v["receipt"]["payees"]) for v in VECTORS["valid"]} == {1, 2, 4}
    # the first one is a payment the test build of knos_pay made (the x402 example's fixture): the same order, amounts and wallet
    fx = json.loads((ROOT / "examples" / "x402_attested" / "fixtures.json").read_text(encoding="utf-8"))
    first = VECTORS["valid"][0]["receipt"]
    said = " ".join(fx["paid"]["logs"])
    assert first["order"] == fx["order"]["address"] and f"amount={first['payees'][0]['amount']} to={first['payees'][0]['to']}" in said
    assert f"paid={first['amounts']['paid']} of={first['amounts']['of']} fee={first['amounts']['fee']} tip={first['amounts']['tip']} judge=0" in said


def test_every_invalid_receipt_is_refused_for_its_reason():
    assert len(VECTORS["invalid"]) == 9 and BEYOND_SCHEMA <= {v["name"] for v in VECTORS["invalid"]}
    for v in VECTORS["invalid"]:
        why = receipt.check(_changed(v))
        assert why is not None and v["why"] in why, (v["name"], why)
    for junk in (None, [], "receipt", {}, {"type": receipt.TYPE}):
        assert receipt.check(junk) is not None


def test_the_json_schema_agrees_with_the_checker():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    ok = jsonschema.Draft202012Validator(SCHEMA)
    for v in VECTORS["valid"]:
        assert not list(ok.iter_errors(v["receipt"])), v["name"]
    for v in VECTORS["invalid"]:
        assert bool(list(ok.iter_errors(_changed(v)))) == (v["name"] not in BEYOND_SCHEMA), v["name"]
    assert SCHEMA["properties"]["judge"]["properties"]["kind"]["enum"] == list(receipt.JUDGES)
    assert set(SCHEMA["properties"]["judge"]["properties"]["claims"]["required"]) == set(receipt.CLAIMS)


def test_version_2_says_four_things_in_order_and_lists_amendments_and_version_1_still_checks():
    from knos.settle.v2 import oidc
    assert receipt.VERSION == 2 and len(VECTORS["valid_v2"]) == 5 and len(VECTORS["invalid_v2"]) == 8
    for v in VECTORS["valid_v2"]:
        r, old = v["receipt"], VECTORS["valid"][v["of"]]["receipt"]
        assert receipt.check(r) is None and receipt.digest(r) == v["sha256"] and receipt.check(old) is None, v["name"]
        keys = list(r)             # the four parts, in this order, in the document as it is written
        assert [k for k in keys if k in receipt.PARTS] == list(receipt.PARTS) and keys.index("amendments") == keys.index("trust_remaining") + 1
        assert receipt._as1(r) == old           # nothing version 1 said is lost
        a, o, p = r["issuer_authenticated"], r["evaluator_observed"], r["policy"]
        assert a["verified"]["program"] == str(oidc.OIDC_ID) and o["verdict"] == "accepted" and o["judge"]["version"] == a["claims"]["job_workflow_sha"]
        trust = " ".join(r["trust_remaining"])
        assert "GitHub's signing key and its hosted runner" in trust and "pinned workflow" in trust
        assert "upgradeable only through a multisig with a public 48-hour delay, until an outside review" in trust and "immutable" not in trust
        assert ("administrators of the repository" in trust) == (p["mode"] == "merge")
        assert ("account that ran the judge" in trust) == (o["judge"]["kind"] != "repository")
        lines = receipt.render(r)
        at = [lines.index(f"{i}. {receipt.HEADINGS[k]}") for i, k in enumerate(receipt.PARTS, 1)]
        assert at == sorted(at) and lines[-1] == f"Digest sha256:{v['sha256']}"
        assert [line for line in receipt.render(old) if line[:2] in ("1.", "2.", "3.", "4.")] == [lines[i] for i in at]      # an old receipt reads the same way
        terms = {"checks": [{"app": -1, "name": "build"}, {"app": 15368, "name": "test"}], "paths": ["src/**"], "deny": [".github/**", ".knos/**"], "v": 1}
        again = receipt.upgrade(old, oidc_program=a["verified"]["program"], verified_tx=a["verified"]["transaction"],
                                terms=terms if p["version"] else None, amendments=r["amendments"])
        assert again == r
    two = VECTORS["valid_v2"][1]["receipt"]
    assert [e["kind"] for e in two["amendments"]] == ["topup", "assign"] and all(e["transaction"] in "\n".join(receipt.render(two)) for e in two["amendments"])
    assert any(v["receipt"]["policy"]["allowed_paths"] is None for v in VECTORS["valid_v2"])
    for v in VECTORS["invalid_v2"]:
        why = receipt.check(_changed(v, "valid_v2"))
        assert why is not None and v["why"] in why, (v["name"], why)


GL_NS, GL_ID = 8 * 10 ** 17, 9 * 10 ** 17        # programs-v2/knos_pay/src/gl.rs: where namespace ids start, and project and user ids


def _gitlab(r: dict, **over) -> dict:
    """A valid GitHub receipt's facts as a GitLab pipeline would have signed them: project 20 of namespace 72, the pinned
    file on the protected branch `knos`, started by the merge's pipeline. The order, its scope and its payee carry the
    ids the program reads (9e17 + the project's and the user's)."""
    r = copy.deepcopy(r)
    a, issue = r["issuer_authenticated"], r["repository"]["issue"]
    a.update(provider="gitlab", issuer="https://gitlab.com", claims={
        "ci_config_ref_uri": "gitlab.com/my-group/my-project//.gitlab-ci.yml@refs/heads/knos", "ci_config_sha": a["claims"]["job_workflow_sha"],
        "exp": a["claims"]["exp"], "iat": a["claims"]["iat"], "namespace_id": "72", "pipeline_id": "991", "pipeline_source": "pipeline", "project_id": "20",
        "project_path": "my-group/my-project", "ref": "knos", "ref_path": "refs/heads/knos", "ref_protected": "true", "ref_type": "branch",
        "runner_environment": "gitlab-hosted", "sha": a["claims"]["job_workflow_sha"], "user_id": "31"} | over)
    r["repository"] = {"id": GL_ID + 20, "issue": issue}
    r["scope"] = hashlib.sha256(b"knos3:scope" + (GL_ID + 20).to_bytes(8, "little") + issue.to_bytes(8, "little")).hexdigest()
    r["trust_remaining"] = receipt.trust_of("gitlab", r["policy"]["mode"], "repository")
    return r


def test_a_gitlab_receipt_is_a_protected_branch_pipeline_of_the_order_s_own_project_with_the_ids_the_program_reads():
    """receipt.check follows gl.rs: the same thirteen claims the program reads are in the receipt, the order's repository
    id is 9e17 + the project's (so the scope is the one the order's address is derived from), and what the program
    refuses in a paying token (a ref that is not a protected branch, a file of another project or ref, a pipeline run
    by hand, an id outside GitLab's range) is no receipt."""
    read = {"project_id", "namespace_id", "user_id", "iat", "ci_config_ref_uri", "ci_config_sha", "runner_environment", "aud", "pipeline_source", "ref_type",
            "ref_path", "ref_protected", "project_path"}
    rs = (ROOT / "programs-v2" / "knos_pay" / "src" / "gl.rs").read_text(encoding="utf-8")
    assert read == set(re.findall(r'b"(\w+)"', rs[rs.index("pub fn read("):rs.index("let iat = number")]))
    assert read - {"aud"} <= set(receipt.GITLAB_CLAIMS) and (receipt.GL_NS, receipt.GL_ID, receipt.GL_MAX) == tuple(
        int(re.search(rf"pub const {name}: u64 = ([\d_]+);", rs).group(1)) for name in ("GL_NS", "GL_ID", "GL_MAX"))
    assert (receipt.gitlab_id("project_id", "20"), receipt.gitlab_id("user_id", "31"), receipt.gitlab_id("namespace_id", "72")) == (GL_ID + 20, GL_ID + 31, GL_NS + 72)
    assert [receipt.gitlab_id("project_id", v) for v in ("0", "020", "100000000000000000", "-1", "", 20)] == [None] * 6
    r = _gitlab(VECTORS["valid_v2"][0]["receipt"])
    assert receipt.check(r) is None and r["trust_remaining"][0].startswith("GitLab's signing key")
    shown = "\n".join(receipt.render(r))
    assert "GitLab signed" in shown and f"ran in repository 20 (my-group/my-project; on chain {GL_ID + 20}) for the event pipeline" in shown
    # the raw project id is not the order's repository: neither as the repository named, nor in the scope
    raw = copy.deepcopy(r)
    raw["repository"]["id"] = 20
    assert "scope is not sha256" in receipt.check(raw)
    raw["scope"] = hashlib.sha256(b"knos3:scope" + (20).to_bytes(8, "little") + raw["repository"]["issue"].to_bytes(8, "little")).hexdigest()
    assert "order's own repository" in receipt.check(raw)
    for claim, value, why in (("ref_protected", "false", "protected branch"), ("ref_type", "tag", "protected branch"), ("project_id", "5", "order's own repository"),
                              ("runner_environment", "self-hosted", "hosted runner"), ("pipeline_source", "web", "a pipeline of the project started"),
                              ("pipeline_source", "push", "a pipeline of the project started"), ("project_path", "my-group/other", "a file of the token's own project"),
                              ("ref_path", "refs/heads/main", "on the ref the pipeline ran on"),
                              ("ci_config_ref_uri", "gitlab.com/my-group/my-project//@refs/heads/knos", "gitlab.com/<project_path>//<file>@<ref_path>"),
                              ("ci_config_ref_uri", "gitlab.example.com/my-group/my-project//.gitlab-ci.yml@refs/heads/knos", "a file of the token's own project"),
                              ("project_id", "0", "GitLab's own numbers"), ("user_id", "100000000000000000", "GitLab's own numbers"),
                              ("namespace_id", "900000000000000001", "GitLab's own numbers")):
        assert why in receipt.check(_gitlab(VECTORS["valid_v2"][0]["receipt"], **{claim: value})), (claim, value)
    for missing in ("ref_type", "ref_path", "project_path"):
        bad = copy.deepcopy(r)
        del bad["issuer_authenticated"]["claims"][missing]
        assert f"issuer_authenticated.claims has fields ['{missing}'] missing or unknown" in receipt.check(bad)
    bad = copy.deepcopy(r)
    bad["issuer_authenticated"]["issuer"] = "https://token.actions.githubusercontent.com"
    assert "gitlab only for https://gitlab.com" in receipt.check(bad)
    jsonschema = pytest.importorskip("jsonschema")           # and the schema says the same of the claims
    ok = jsonschema.Draft202012Validator(SCHEMA2)
    assert ok.is_valid(r) and not ok.is_valid(_gitlab(VECTORS["valid_v2"][0]["receipt"], pipeline_source="web"))
    assert not ok.is_valid(_gitlab(VECTORS["valid_v2"][0]["receipt"], project_id="020")) and not ok.is_valid(_gitlab(VECTORS["valid_v2"][0]["receipt"], ref_type="tag"))


def test_a_receipt_built_from_a_gitlab_token_signed_by_the_test_key_and_paid_on_chain_is_valid():
    """The whole way: a GitLab-shaped token signed by the test key funds an order from a namespace's Balance and another
    pays it (knos_pay and knos_oidc as built, in LiteSVM: tests/test_gitlab_pay.py). The receipt is built from the
    paying token's own claims and the order as the chain holds it, and it is valid; with the project's raw id it is not."""
    pytest.importorskip("solders.litesvm")
    import base64

    from _order import HEAD, USDC, issue
    from _settle import gitlab_claims, sign_jwt, signing_key
    from test_gitlab_pay import AUTHOR, NAMESPACE, PROJECT, SHA, SPENDER, URI, GitLab
    from knos.settle.v2 import oidc, pay
    c = GitLab()
    n = issue()
    ok, order = c.gl_fund(n)
    assert ok, c.err
    o, wallet, payee = c.order(order), c.fund().pubkey(), GL_ID + AUTHOR
    c.warp(1)
    now = c.now()
    claims = gitlab_claims(aud=pay.order_pay_audience(order, HEAD, o.terms, o.mode, 7, [(payee, 10_000, wallet)]), iat=now, nbf=now - 5, exp=now + 300, jti="receipt",
                           pipeline_source="pipeline", ref="knos", ref_path="refs/heads/knos", ref_protected="true", ci_config_ref_uri=URI, ci_config_sha=SHA,
                           project_id=str(PROJECT), namespace_id=str(NAMESPACE), user_id=str(SPENDER + 1))
    jwt = sign_jwt(signing_key(4096), claims)
    tok = c.verify(jwt, oidc.GITLAB, c.gl_n)
    before = c.balance(pay.ata(wallet, c.usdc)) if c.data(pay.ata(wallet, c.usdc)) else 0
    assert c.send([pay.pay_order_ix(c.payer.pubkey(), tok, c.gl_key, order, o, [(payee, wallet)])]), c.err
    paid = c.balance(pay.ata(wallet, c.usdc)) - before
    assert paid == 20 * USDC and (o.repo_id, o.owner_id) == (GL_ID + PROJECT, GL_NS + NAMESPACE)
    sig58 = "5" * 87
    signed = json.loads(base64.urlsafe_b64decode(jwt.split(".")[1] + "=" * (-len(jwt.split(".")[1]) % 4)))
    facts = dict(cluster="localnet", program=str(pay.PAY_ID), order=str(order), repository={"id": o.repo_id, "issue": o.issue}, commit=HEAD, pull_request=7,
                 terms_hash=o.terms.hex(), mode=receipt.MODES[o.mode], judge_kind="repository", issuer=signed["iss"], claims=signed,
                 token_sha256=hashlib.sha256(base64.urlsafe_b64decode(jwt.rsplit(".", 1)[1] + "==")).hexdigest(), key=str(c.gl_key), oidc_program=str(oidc.OIDC_ID),
                 verified_tx=sig58, checks=["test"], allowed_paths=[], denied_paths=[".github/**", ".knos/**"], policy_version=1, amendments=[],
                 payees=[{"github_id": payee, "bps": 10_000, "amount": paid, "to": str(wallet)}], mint=str(c.usdc), decimals=6, paid=paid, of=o.amount, fee=o.fee,
                 tip=pay.TIP_FIRST, signature=sig58, slot=1, time=now)
    r = receipt.build2(scope=pay.scope_of(o.repo_id, o.issue).hex(), **facts)
    assert receipt.check(r) is None and str(order) == str(pay.order_pda(bytes.fromhex(r["scope"]), c.gl_bal))
    got = r["issuer_authenticated"]
    assert got["provider"] == "gitlab" and set(got["claims"]) == set(receipt.GITLAB_CLAIMS)
    assert (got["claims"]["project_id"], got["claims"]["ref_type"], got["claims"]["ref_path"], got["claims"]["project_path"]) == (str(PROJECT), "branch", "refs/heads/knos",
                                                                                                                       "my-group/my-project")
    # the scope of the raw project id is another order's address, and no receipt of this one
    with pytest.raises(ValueError, match="order's own repository"):
        receipt.build2(scope=pay.scope_of(PROJECT, o.issue).hex(), **(facts | {"repository": {"id": PROJECT, "issue": o.issue}}))
    assert pay.order_pda(pay.scope_of(PROJECT, o.issue), c.gl_bal) != order


def test_the_version_2_schema_agrees_with_the_checker():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(SCHEMA2)
    ok = jsonschema.Draft202012Validator(SCHEMA2)
    assert [k for k in SCHEMA2["properties"] if k in receipt.PARTS] == list(receipt.PARTS)
    assert [SCHEMA2["properties"][k]["description"][:2] for k in receipt.PARTS] == ["1.", "2.", "3.", "4."]
    for v in VECTORS["valid_v2"]:
        assert not list(ok.iter_errors(v["receipt"])), v["name"]
        assert list(ok.iter_errors(VECTORS["valid"][v["of"]]["receipt"]))          # each version has its own schema
    for v in VECTORS["invalid_v2"]:
        assert bool(list(ok.iter_errors(_changed(v, "valid_v2")))) == (v["name"] not in BEYOND_SCHEMA2), v["name"]


def test_the_attestation_is_on_by_default_and_fails_soft(monkeypatch, tmp_path):
    r = VECTORS["valid_v2"][0]["receipt"]
    for name in ("KNOS_NO_SAS", "KNOS_SAS_KEYPAIR", "KNOS_SAS_SCRIPT"):
        monkeypatch.delenv(name, raising=False)
    assert receipt.attest(r) == {"attested": False, "why": "no key for the attestation: set KNOS_SAS_KEYPAIR to the credential authority's devnet key file"}
    monkeypatch.setenv("KNOS_SAS_KEYPAIR", str(tmp_path / "key.json"))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/node")
    sent = []

    class Done:
        def __init__(self, code, out="", errs=""):
            self.returncode, self.stdout, self.stderr = code, out, errs

    def run(args, **kw):            # on by default: with a key, the script is run with --send and no flag asked for it
        sent.append(args)
        assert json.loads(open(args[2], encoding="utf-8").read()) == r and kw["timeout"] == 60.0
        return Done(0, json.dumps({"sent": True, "signature": "S", "attestation": "A"}))
    assert receipt.attest(r, run=run) == {"attested": True, "why": "attested", "attestation": "A", "signature": "S"}
    assert sent[0][1].replace("\\", "/").endswith("scripts/sas_receipt.mjs") and sent[0][3:] == ["--send", "--keypair", str(tmp_path / "key.json")]
    assert receipt.attest(r, run=lambda *a, **k: Done(0, json.dumps({"sent": False, "already": True, "attestation": "A"})))["why"] == "already attested"
    # soft, whatever goes wrong: the script refuses, hangs, or cannot be started
    assert receipt.attest(r, run=lambda *a, **k: Done(1, errs="refused: this script writes to devnet only")) == {
        "attested": False, "why": "refused: this script writes to devnet only"}
    for boom in (TimeoutError("timed out"), OSError("no such file"), RuntimeError("anything")):
        def fails(*a, _boom=boom, **k):
            raise _boom
        said = receipt.attest(r, run=fails)
        assert said["attested"] is False and str(boom) in said["why"]
    monkeypatch.setenv("KNOS_NO_SAS", "1")      # the opt-out
    assert receipt.attest(r, run=run)["why"] == "attestations are turned off (KNOS_NO_SAS=1)" and len(sent) == 1
    script = (ROOT / "scripts" / "sas_receipt.mjs").read_text(encoding="utf-8")
    assert "--init" in script and "[1, 2].includes(r.version)" in script and '"already": true' in script.replace("already: true", '"already": true')


def test_a_script_that_crashes_after_sending_is_checked_on_chain_and_its_own_error_is_said(monkeypatch, tmp_path):
    # rehearsed on devnet (0.3.14): web3.js crashed on a 429 after the attestation's transaction had landed; the relay
    # logged a failure, and the line it logged was the "Node.js v22..." Node ends a crash with
    r = VECTORS["valid_v2"][0]["receipt"]
    for name in ("KNOS_NO_SAS", "KNOS_SAS_SCRIPT", "KNOS_RPC"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KNOS_SAS_KEYPAIR", str(tmp_path / "key.json"))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/node")
    crash = ("file:///x/node_modules/@solana/web3.js/lib/index.cjs.js:1\n        throw err;\n        ^\n\n"
             "SolanaJSONRPCError: failed to get signature status: 429 Too Many Requests\n    at Connection.getSignatureStatuses (index.cjs.js:7)\n\nNode.js v22.23.3\n")
    asked = []

    class Done:
        def __init__(self, code, out="", errs=""):
            self.returncode, self.stdout, self.stderr = code, out, errs

    def run(args, **kw):
        if "--send" in args:
            return Done(1, errs=crash)
        assert args[3:] == ["--keypair", str(tmp_path / "key.json")]            # the dry run, with the same key: nothing is sent
        return Done(0, json.dumps({"dry_run": True, "program": "SAS1", "attestation": "ATT"}))

    def call(holds):
        def ask(url, method, params):
            asked.append((url, method, params[0]))
            return {"value": {"owner": "SAS1"} if len(asked) >= holds else None}
        return ask
    slept = []
    said = receipt.attest(r, run=run, call=call(2), sleep=slept.append)
    assert said == {"attested": True, "attestation": "ATT", "why": "attested: the attestation is on chain, though the script failed "
                    "(SolanaJSONRPCError: failed to get signature status: 429 Too Many Requests)"}, said
    assert asked == [("https://api.devnet.solana.com", "getAccountInfo", "ATT")] * 2 and slept == [0, 2]
    asked.clear()
    said = receipt.attest(r, rpc="http://cluster", run=run, call=call(99), sleep=lambda s: None)
    assert said == {"attested": False, "why": "SolanaJSONRPCError: failed to get signature status: 429 Too Many Requests"}, said
    assert len(asked) == 4 and {a[0] for a in asked} == {"http://cluster"}
    # the script's own words are kept as they are, and a refusal (nothing was sent) asks nothing of the chain
    asked.clear()
    failed = receipt.attest(r, run=lambda *a, **k: Done(1, errs="failed: Error: blockhash not found\n    at main (sas_receipt.mjs:1)")
                            if "--send" in a[0] else Done(0, json.dumps({"program": "SAS1", "attestation": "ATT"})), call=call(99), sleep=lambda s: None)
    assert failed == {"attested": False, "why": "failed: Error: blockhash not found"} and len(asked) == 4
    asked.clear()
    assert receipt.attest(r, run=lambda *a, **k: Done(1, errs="refused: the cluster at --rpc is not devnet"), call=call(1)) == {
        "attested": False, "why": "refused: the cluster at --rpc is not devnet"} and asked == []


def test_the_page_prints_the_first_vector_and_says_what_was_not_confirmed():
    page = (ROOT / "docs" / "RECEIPT.md").read_text(encoding="utf-8")
    shown = json.loads(re.search(r"## Version 1\n\n```json\n(.*?)\n```", page, re.S).group(1))
    assert shown == VECTORS["valid"][0]["receipt"] and VECTORS["valid"][0]["sha256"] in page
    shown2 = json.loads(re.search(r"## Version 2\n\n```json\n(.*?)\n```", page, re.S).group(1))
    assert shown2 == VECTORS["valid_v2"][0]["receipt"] and list(shown2) == list(VECTORS["valid_v2"][0]["receipt"]) and VECTORS["valid_v2"][0]["sha256"] in page
    at = [page.index(f"**{receipt.HEADINGS[k]}**") for k in receipt.PARTS]
    assert at == sorted(at) and receipt.FROM_MIRROR in page and "on by default" in page and "--init --send --keypair" in page
    assert page.index("## Version 2") < page.index("## The evidence bundle") < page.index("## The mirror") < page.index("## Version 1")
    assert "What was **not** confirmed" in page and "no attestation was sent to devnet from here" in page
    script = (ROOT / "scripts" / "sas_receipt.mjs").read_text(encoding="utf-8")
    sas = re.search(r'export const SAS = "(\w+)"', script).group(1)
    assert sas in page and "sas-lib" in json.loads((ROOT / "scripts" / "package.json").read_text(encoding="utf-8"))["optionalDependencies"]
    for name, code in re.findall(r'\["(\w+)", (\d+)\]', script.split("export const FIELDS")[1].split("];")[0]):
        assert f"`{name}`" in page, name


def test_the_script_builds_the_attestation_and_its_digest_is_the_python_one(tmp_path):
    node = shutil.which("node")
    if not node or not (ROOT / "scripts" / "node_modules" / "sas-lib").is_dir():
        pytest.skip("needs Node 20 and the packages: npm ci --prefix scripts")
    v = VECTORS["valid"][1]
    (tmp_path / "receipt.json").write_text(json.dumps(v["receipt"]), encoding="utf-8")
    authority = "4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo"
    done = subprocess.run([node, "scripts/sas_receipt.mjs", str(tmp_path / "receipt.json"), "--authority", authority], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["dry_run"] is True and out["receipt_sha256"] == v["sha256"] and out["program"] == "22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG"
    assert [i["name"] for i in out["instructions"]] == ["create credential", "create schema", "create attestation"]
    assert all(i["program"] == out["program"] and i["accounts"][0] == {"pubkey": authority, "signer": True, "writable": True} for i in out["instructions"])
    data = bytes.fromhex(out["instructions"][2]["data"])
    assert bytes.fromhex(v["sha256"]) in data and v["receipt"]["order"].encode() in data and v["receipt"]["transaction"]["signature"].encode() in data
    # --send without a key, and a file that is not a receipt, are refused before anything is asked of a cluster
    for args, said in ((["--send"], "--send needs --keypair"),):
        bad = subprocess.run([node, "scripts/sas_receipt.mjs", str(tmp_path / "receipt.json"), *args], cwd=ROOT, capture_output=True, text=True, timeout=120)
        assert bad.returncode == 1 and said in bad.stderr
    (tmp_path / "other.json").write_text("{}", encoding="utf-8")
    bad = subprocess.run([node, "scripts/sas_receipt.mjs", str(tmp_path / "other.json")], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert bad.returncode == 1 and "not a Knos acceptance receipt" in bad.stderr


def test_the_privacy_page_says_what_a_payment_reveals_and_what_a_hash_proves():
    page = (ROOT / "docs" / "PRIVACY.md").read_text(encoding="utf-8")
    for said in ("**Ids**", "**Amounts**", "**Timing**", "**The payee's wallet**", "**Counterparties**", "It does not hide:", "Merkle root", "## 4. Retention",
                 "**Not availability.**", "**Not confidentiality.**", "proves **correspondence**", "test USDC"):
        assert said in page, said
    assert "immutable" not in page and "audited" not in page


# ---- at settlement: the relay asks for the attestation after a confirmed payment, and the payment never depends on it ------
PAID = {"ok": True, "kind": "pay", "order": "Hp2aNaMFBYTHgutDEzzDnRqnSD7Y7RHqozYVsKrsJcNx", "sigs": ["v", "p"], "paid": [{"id": 5, "amount": 1, "to": "W"}]}


class _Ledger:
    url = "http://127.0.0.1:1"


def _ready(monkeypatch, tmp_path) -> list:
    """A relay that could attest: a key, and node_modules beside the script. Returns the log lines."""
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "sas_receipt.mjs").write_text("")
    monkeypatch.setenv("KNOS_SAS_KEYPAIR", str(tmp_path / "key.json"))
    monkeypatch.setenv("KNOS_SAS_SCRIPT", str(tmp_path / "sas_receipt.mjs"))
    monkeypatch.delenv("KNOS_NO_SAS", raising=False)
    monkeypatch.setattr(receipt, "_receipt_of", lambda url, sig, limit: {"order": PAID["order"], "sig": sig})
    return []


def test_a_relay_attests_a_confirmed_payment_by_default_and_only_a_payment(monkeypatch, tmp_path):
    lines = _ready(monkeypatch, tmp_path)
    asked = []
    monkeypatch.setattr(receipt, "attest", lambda r, rpc=None: asked.append((r, rpc)) or {"attested": True, "why": "attested"})
    assert receipt.settled(_Ledger(), PAID, lines.append) == {"attested": True, "why": "attested"}
    assert asked == [({"order": PAID["order"], "sig": "p"}, _Ledger.url)] and lines == [f"attestation of order {PAID['order']}: attested"]
    # not a payment, not confirmed, carried by another relayer already, or held for a payee with no wallet: nothing is asked
    for other in ({**PAID, "ok": False}, {**PAID, "kind": "fund"}, {**PAID, "already": True}, {**PAID, "sigs": []},
                  {**PAID, "paid": [{"id": 5, "amount": 1, "to": None}]}):
        assert receipt.settled(_Ledger(), other, lines.append) is None
    monkeypatch.setenv("KNOS_NO_SAS", "1")          # the opt-out, without a word
    assert receipt.settled(_Ledger(), PAID, lines.append) is None and len(asked) == 1 and len(lines) == 1


def test_a_lean_relay_says_one_line_and_asks_nothing_of_node_or_the_chain(monkeypatch, tmp_path):
    lines = _ready(monkeypatch, tmp_path)
    monkeypatch.setattr(receipt, "_receipt_of", lambda *a: (_ for _ in ()).throw(AssertionError("the chain was asked")))
    monkeypatch.setattr(receipt, "attest", lambda *a, **k: (_ for _ in ()).throw(AssertionError("node was asked")))
    (tmp_path / "node_modules").rmdir()             # the public worker installs no node package
    assert receipt.settled(_Ledger(), PAID, lines.append) is None
    (tmp_path / "node_modules").mkdir()
    monkeypatch.delenv("KNOS_SAS_KEYPAIR")          # and holds no credential key
    assert receipt.settled(_Ledger(), PAID, lines.append) is None
    assert len(lines) == 2 and all(line.startswith(f"no attestation of order {PAID['order']}: this relay has no KNOS_SAS_KEYPAIR or no scripts/node_modules") for line in lines)
    # the real `attest` asks for node_modules too before it starts node
    monkeypatch.undo()
    monkeypatch.setenv("KNOS_SAS_KEYPAIR", str(tmp_path / "key.json"))
    monkeypatch.setenv("KNOS_SAS_SCRIPT", str(tmp_path / "sas_receipt.mjs"))
    monkeypatch.delenv("KNOS_NO_SAS", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/node")
    (tmp_path / "node_modules").rmdir()
    assert receipt.attest(VECTORS["valid_v2"][0]["receipt"])["why"].startswith("the attestation script needs Node")


def test_the_payment_still_succeeds_when_the_attestation_raises(monkeypatch, tmp_path):
    from knos.settle.v2 import relay
    lines = _ready(monkeypatch, tmp_path)
    say = receipt.settled
    monkeypatch.setattr(receipt, "settled", lambda ledger, result: say(ledger, result, lines.append))

    def boom(*a, **k):
        raise RuntimeError("the attestation service is down")
    monkeypatch.setattr(receipt, "attest", boom)
    monkeypatch.setattr(relay, "_handler_of", lambda jwt: None)
    monkeypatch.setattr(relay, "_plan", lambda *a: "plan")
    monkeypatch.setattr(relay, "_carry", lambda ledger, payer, plan, again: dict(PAID))
    assert relay.submit(_Ledger(), None, "a.b.c") == PAID                       # the relay's answer is the payment's, whatever the attestation did
    assert lines == [f"no attestation of order {PAID['order']}: the attestation service is down"]
    monkeypatch.setattr(receipt, "_receipt_of", boom)                          # the chain no longer has the record: the same
    assert relay.submit(_Ledger(), None, "a.b.c") == PAID and len(lines) == 2


def test_the_document_names_the_bundles_options_and_states_the_offline_limit():
    """docs/RECEIPT.md says what `knos bundle` takes and what an offline check cannot show, in the command's own words."""
    import inspect

    from knos import bundle
    doc = " ".join((ROOT / "docs" / "RECEIPT.md").read_text(encoding="utf-8").split())
    for said in ("`knos bundle make ORDER [--verdict FILE]`", "`knos bundle verify FILE [--rpc URL] [--mirror DIR]`", "knos bundle verify FILE --mirror DIR",
                 "knos bundle make <order> --verdict FILE", "Offline, the paid wallet is not checked against the chain.", "a line that starts `limit:`",
                 "`ref_path`", "`ref_type`", "`project_path`", "900000000000000000 + id", "800000000000000000 + id"):
        assert said in doc, said
    code = inspect.getsource(bundle)
    assert '"--verdict"' in code and code.count('"--mirror"') == 2 and bundle.LIMIT.startswith("limit: the wallets paid and the amounts are the receipt's word here.")
    assert "still passes offline" in bundle.LIMIT and "No signed token carries" in doc and "still passes `knos bundle verify <tar>` with no option" in doc
