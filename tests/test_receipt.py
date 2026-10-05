"""The acceptance receipt (docs/RECEIPT.md): the reference checker and the JSON Schema accept the five conformance
vectors of each version and give their digests, both refuse every invalid one for the reason it names, a version 2
receipt says its parts in order (five in version 3), the page prints a vector of each version, and
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
    assert receipt.VERSION == 3 and len(VECTORS["valid_v2"]) == 5 and len(VECTORS["invalid_v2"]) == 8
    for v in VECTORS["valid_v2"]:
        r, old = v["receipt"], VECTORS["valid"][v["of"]]["receipt"]
        assert receipt.check(r) is None and receipt.digest(r) == v["sha256"] and receipt.check(old) is None, v["name"]
        keys = list(r)             # the four parts, in this order, in the document as it is written
        assert [k for k in keys if k in receipt.PARTS] == list(receipt.PARTS2) and keys.index("amendments") == keys.index("trust_remaining") + 1
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
        assert [line for line in receipt.render(old) if line[:2] in ("1.", "2.", "3.", "4.", "5.")] == [lines[i] for i in at]      # an old receipt reads the same way
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
    assert [k for k in SCHEMA2["properties"] if k in receipt.PARTS] == list(receipt.PARTS2)
    assert [SCHEMA2["properties"][k]["description"][:2] for k in receipt.PARTS2] == ["1.", "2.", "3.", "4."]
    for v in VECTORS["valid_v2"]:
        assert not list(ok.iter_errors(v["receipt"])), v["name"]
        assert list(ok.iter_errors(VECTORS["valid"][v["of"]]["receipt"]))          # each version has its own schema
    for v in VECTORS["invalid_v2"]:
        assert bool(list(ok.iter_errors(_changed(v, "valid_v2")))) == (v["name"] not in BEYOND_SCHEMA2), v["name"]


# ---- version 3: the fifth part, and who controls each judge ------------------------------------------------------------------
SCHEMA3 = json.loads((ROOT / "docs" / "receipt" / "acceptance-receipt.v3.schema.json").read_text(encoding="utf-8"))
RUN = {"repository_id": "700700700", "repository_owner_id": "31", "actor_id": "32", "runner_environment": "github-hosted"}


def test_version_3_keeps_five_things_apart_in_order_and_versions_1_and_2_still_check():
    assert receipt.PARTS == ("issuer_authenticated", "evaluator_observed", "policy", "commercial_authorisation", "trust_remaining")
    assert len(VECTORS["valid_v3"]) == 5 and len(VECTORS["invalid_v3"]) == 12
    for v in VECTORS["valid_v3"]:
        r, two = v["receipt"], VECTORS["valid_v2"][v["of"]]["receipt"]
        assert receipt.check(r) is None and receipt.digest(r) == v["sha256"] and r["version"] == 3, v["name"]
        assert [k for k in r if k in receipt.PARTS] == list(receipt.PARTS)          # the five parts, in this order, in the document as it is written
        assert receipt.as2(r) == two and receipt.check(two) is None and receipt.check(VECTORS["valid"][two and VECTORS["valid_v2"][v["of"]]["of"]]["receipt"]) is None
        lines = receipt.render(r)
        at = [lines.index(f"{i}. {receipt.HEADINGS[k]}") for i, k in enumerate(receipt.PARTS, 1)]
        assert at == sorted(at) and lines[-1] == f"Digest sha256:{v['sha256']}"
        # the parties still trusted are on the line under the verdict itself, in one line
        verdict = next(i for i, line in enumerate(lines) if "gave the verdict: accepted." in line)
        trusted = lines[verdict + 1].strip()
        assert trusted.startswith("trusted: GitHub's signing key and runner; the pinned workflow at " + r["evaluator_observed"]["judge"]["version"])
        assert trusted.endswith("Knos's upgrade multisig (public 48-hour delay).") and "immutable" not in trusted
        assert ("the repository's administrators" in trusted) == (r["policy"]["mode"] == "merge")
        assert ("the account that ran the judge" in trusted) == (r["evaluator_observed"]["judge"]["kind"] != "repository")
    for v in VECTORS["valid_v2"] + VECTORS["valid"]:          # an older receipt prints the same five headings, and says what it does not carry
        lines = receipt.render(v["receipt"])
        assert [line[:2] for line in lines if line[:3] in ("1. ", "2. ", "3. ", "4. ", "5. ")] == ["1.", "2.", "3.", "4.", "5."]
        assert any(line.strip().startswith(f"Not recorded in a version {v['receipt']['version']} receipt: who funded") for line in lines)
        assert any(line.strip().startswith("trusted: ") for line in lines)
    for v in VECTORS["invalid_v3"]:
        why = receipt.check(_changed(v, "valid_v3"))
        assert why is not None and v["why"] in why, (v["name"], why)
    assert "version 1, 2 or 3" in receipt.check({"type": receipt.TYPE, "version": 4})


def test_the_version_3_schema_agrees_with_the_checker():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(SCHEMA3)
    ok = jsonschema.Draft202012Validator(SCHEMA3)
    assert [k for k in SCHEMA3["properties"] if k in receipt.PARTS] == list(receipt.PARTS)
    assert [SCHEMA3["properties"][k]["description"][:2] for k in receipt.PARTS] == ["1.", "2.", "3.", "4.", "5."]
    for v in VECTORS["valid_v3"]:
        assert not list(ok.iter_errors(v["receipt"])), v["name"]
        assert list(ok.iter_errors(VECTORS["valid_v2"][v["of"]]["receipt"]))          # each version has its own schema
    assert [v["name"] for v in VECTORS["invalid_v3"] if list(ok.iter_errors(_changed(v, "valid_v3")))] == ["the fifth part left out"]      # the rest are rules a schema cannot say


def test_the_fifth_part_says_who_funded_from_what_under_which_limit_in_which_role_and_whether_it_was_billed_before():
    owner, spender, wallet, passkey, unknown = (v["receipt"]["commercial_authorisation"] for v in VECTORS["valid_v3"])
    assert owner["funder"] == {"github_id": 424242, "login": "octo", "wallet": None} and owner["source"]["kind"] == "balance" and owner["role"] == "owner"
    assert owner["limit"] == {"cap_per_order": "50000000", "daily": "200000000", "total": "0", "repositories": [987654321]} and owner["billed_before"] is False
    assert spender["funder"]["wallet"] and spender["funder"]["github_id"] is None and spender["limit"] == receipt.NO_LIMIT == "no limit set" and spender["role"] == "wallet"
    assert passkey["source"]["kind"] == passkey["role"] == "passkey" and passkey["limit"] == receipt.NO_LIMIT
    assert unknown["limit"] is None and unknown["funded"] is None and unknown["billed_before"] not in (False, None)
    quorum = VECTORS["valid_v3"][2]["receipt"]
    part = quorum["commercial_authorisation"]
    assert part["role"] == "spender" and part["funder"]["github_id"] != part["source"]["owner_id"] and part["deliverable"] == {"order": quorum["order"], "milestone": 219}
    said = ["\n".join(receipt.render(v["receipt"])) for v in VECTORS["valid_v3"]]
    assert "Funded by GitHub account 424242 (octo, as its funding token named it), from the Balance" in said[0] and "The funder is the Balance's owner." in said[0]
    assert "cap for one order 50.000000, a day 200.000000, in total none; repositories allowed: 987654321." in said[0]
    assert "Limit the funding passed under: no limit set." in said[1] and "The wallet signed the funding itself" in said[1]
    assert "the Balance lists it as a spender" in said[2] and "milestone 219. Billed before: no" in said[2]
    assert "from the passkey wallet" in said[3] and "Limit the funding passed under: not in the records read" in said[4]
    assert f"Billed before: yes, in transaction {unknown['billed_before']}." in said[4] and "Funding transaction: older than the history read." in said[4]
    # a Balance with every limit at zero has no limit set; an account's login is kept only with its id
    none = receipt.authorisation(order=quorum["order"], milestone=0, funded_tx=None, funder_id=5, login="five", source="balance", address=quorum["program"], owner_id=6)
    assert none["limit"] == receipt.NO_LIMIT and none["role"] == "spender" and none["funder"]["login"] == "five"


def test_each_independence_flag_is_computed_from_the_ids_the_issuer_signed():
    ev = receipt.evaluator
    apart = ev("neutral", RUN, buyers=(10, 11), sellers=[20])
    assert apart == {"kind": "neutral", "repository_id": 700700700, "owner_id": 31, "actor_id": 32, "runner": "github-hosted",
                     "independent_of_buyer": True, "independent_of_seller": True}
    # of the buyer: the funder or the Balance's owner owns the judge's repository, or started its run
    assert ev("neutral", {**RUN, "repository_owner_id": "10"}, (10, 11), [20])["independent_of_buyer"] is False       # the funder owns it
    assert ev("neutral", {**RUN, "actor_id": "11"}, (10, 11), [20])["independent_of_buyer"] is False                    # the Balance's owner started it
    assert ev("attestor", {**RUN, "actor_id": "11"}, (10, 11), [20])["independent_of_seller"] is True
    assert ev("repository", RUN, (10, 11), [20])["independent_of_buyer"] is False        # the order's own repository is the buyer's choice, whoever owns it
    assert ev("neutral", RUN, (None, None), [20])["independent_of_buyer"] is None        # a wallet has no account id to compare with
    # of the seller: a payee owns the judge's repository, or started its run
    assert ev("neutral", {**RUN, "repository_owner_id": "20"}, (10, 11), [20, 21])["independent_of_seller"] is False
    assert ev("neutral", {**RUN, "actor_id": "21"}, (10, 11), [20, 21])["independent_of_seller"] is False
    assert ev("neutral", {**RUN, "actor_id": "21"}, (10, 11), [20, 21])["independent_of_buyer"] is True
    # the runner is the token's own word
    assert ev("neutral", {**RUN, "runner_environment": "self-hosted"}, (10,), [20])["runner"] == "self-hosted"
    # a quorum: two judges that share an owner or a starter are one judge
    a, b = ev("repository", {**RUN, "repository_owner_id": "40", "actor_id": "41"}, (10,), [20]), ev("neutral", {**RUN, "repository_owner_id": "50", "actor_id": "50"}, (10,), [20])
    assert receipt.independence_of([b]) == (False, receipt.ONE_JUDGE)
    assert receipt.independence_of([a, b]) == (False, receipt.APART.format(n=2)) and "two accounts run by one person are one judge" in receipt.APART
    for shared in ({"repository_owner_id": "40", "actor_id": "50"}, {"repository_owner_id": "51", "actor_id": "41"}, {"repository_owner_id": "41", "actor_id": "41"}):
        same, said = receipt.independence_of([a, ev("neutral", {**RUN, **shared}, (10,), [20])])          # one owner; one starter; the starter of one owns the other
        assert same is True and "Two accounts run by one person are one judge" in said and "count this quorum as one judge" in said
    third = ev("attestor", {**RUN, "repository_owner_id": "40", "actor_id": "60"}, (10,), [20])
    assert receipt.independence_of([a, b, third])[0] is True and receipt.independence_of([b, third])[0] is False
    # in a receipt: the flagged quorum prints the sentence, and the neutral judge a payee runs is not independent of the seller
    quorum = VECTORS["valid_v3"][2]["receipt"]["evaluator_observed"]
    assert quorum["same_controller"] is True and [e["kind"] for e in quorum["evaluators"]] == ["repository", "neutral"]
    assert [e["independent_of_seller"] for e in quorum["evaluators"]] == [False, False] and quorum["evaluators"][0]["independent_of_buyer"] is False
    text = "\n".join(receipt.render(VECTORS["valid_v3"][2]["receipt"]))
    assert "SAME CONTROLLER. These judges are not independent of each other: account 7001 owns or started more than one of them." in text
    assert "run started by account 7001, GitHub-hosted runner; independent of the buyer, NOT independent of the seller." in text
    alone = VECTORS["valid_v3"][1]["receipt"]["evaluator_observed"]
    assert alone["same_controller"] is False and alone["independence"] == receipt.ONE_JUDGE and alone["evaluators"][0]["independent_of_buyer"] is None
    assert "independence of the buyer cannot be computed (a wallet has no account id)" in "\n".join(receipt.render(VECTORS["valid_v3"][1]["receipt"]))


def test_the_attestation_is_of_the_receipt_as_issued_and_a_reader_of_version_2_can_still_be_given_version_2(monkeypatch, tmp_path):
    """The attestation script reads versions 1, 2 and 3, so a version 3 receipt is handed to it as it is: the digest
    attested is the digest of the receipt that was issued. `as2` still gives a reader of version 2 the same payment."""
    r3 = VECTORS["valid_v3"][0]["receipt"]
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "sas_receipt.mjs").write_text("", encoding="utf-8")
    monkeypatch.setenv("KNOS_SAS_SCRIPT", str(tmp_path / "sas_receipt.mjs"))
    monkeypatch.setenv("KNOS_SAS_KEYPAIR", str(tmp_path / "key.json"))
    monkeypatch.delenv("KNOS_NO_SAS", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "node")
    seen = []

    def run(args, **kw):
        seen.append(json.loads(open(args[2], encoding="utf-8").read()))
        return type("Done", (), {"returncode": 0, "stdout": json.dumps({"attestation": "A"}), "stderr": ""})()
    assert receipt.attest(r3, run=run)["attested"] is True
    assert seen == [r3] and seen[0]["version"] == 3
    assert receipt.as2(r3) == VECTORS["valid_v2"][0]["receipt"] and receipt.as2(receipt.as2(r3)) is not r3


def test_the_document_says_the_five_parts_the_independence_fields_and_what_survives_a_devnet_reset():
    page = (ROOT / "docs" / "RECEIPT.md").read_text(encoding="utf-8")
    doc = " ".join(page.split())
    at = [page.index(f"**{receipt.HEADINGS[k]}** (`{k}`)") for k in receipt.PARTS]
    assert at == sorted(at) and len(at) == 5 and "keeps five things apart" in doc
    heads = [page.index(h) for h in ("## Version 3", "### Evaluator independence", "## Version 2", "## The evidence bundle", "## Verifying with the chain gone",
                                     "## What survives a devnet reset", "## The mirror", "## Version 1")]
    assert heads == sorted(heads)
    shown = [json.loads(m) for m in re.findall(r"```json\n(.*?)\n```", page[heads[0]:heads[2]], re.S)]
    quorum = VECTORS["valid_v3"][2]["receipt"]["evaluator_observed"]
    assert shown == [VECTORS["valid_v3"][0]["receipt"]["commercial_authorisation"], {k: quorum[k] for k in ("evaluators", "same_controller", "independence")}]
    assert VECTORS["valid_v3"][0]["sha256"] in page
    for field in ("funder", "source", "limit", "role", "deliverable", "billed_before", "funded", "kind", "repository_id", "owner_id", "actor_id", "runner",
                  "independent_of_buyer", "independent_of_seller", "same_controller", "chain.json", "keys.json"):
        assert f"`{field}`" in page, field
    for said in ("Two accounts run by one person are one judge.", "It does not say two people differ.", f'`"{receipt.NO_LIMIT}"`', "prints no log line",
                 "knos bundle verify FILE --no-chain", "knos receipt verify FILE --no-chain", "**Verified from signatures.**",
                 "**Resting on an archived copy in the bundle, signed by nobody.**", "**Could not be checked without a cluster.**", "An issuer's keys rotate out.",
                 "**The chain record becomes an archived copy.**", "Nothing a customer is invoiced for depends on devnet staying up", "test USDC",
                 "trusted: GitHub's signing key and runner; the pinned workflow at"):
        assert said in doc, said
    assert "immutable" not in doc and "audited" not in doc


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
    assert "--init" in script and "[1, 2, 3].includes(r.version)" in script and "r.version >= 2" in script and '"already": true' in script.replace("already: true", '"already": true')


# ---- how a judge outside the order's repository reached its verdict: its run's own words, held to the signed run ------------

def _verdict(r: dict, **over) -> dict:
    """The verdict attest.yml's first job hands on (knos.flow._rerun_verdict) for the payment of receipt `r`."""
    c, o = r["issuer_authenticated"]["claims"], r["evaluator_observed"]
    v = {"v": 1, "reexecuted": True, "passed": True, "sentence": "ran it", "order": r["order"], "repository": "octo/widgets",
         "pull": o["artifact"]["pull_request"], "issue": r["repository"]["issue"], "head": o["artifact"]["commit"], "base": "b" * 40, "accept": "c" * 64,
         "assurance": "black-box", "image": {}, "artifact": {"base": "d" * 64, "pr": "e" * 64},
         "environment": {"knos": "0.0.0", "github_repository": "judge/neutral", "github_repository_id": str(c["repository_id"]), "github_run_id": str(c["run_id"]),
                         "github_run_attempt": "1", "runner_os": "Linux", "runner_environment": "github-hosted", "imageos": "ubuntu24"},
         "reasons": []}
    return {**v, **over}


def _with(r: dict, rerun, at: int = -1) -> dict:
    out = json.loads(json.dumps(r))
    out["evaluator_observed"]["evaluators"][at]["reexecution"] = rerun
    return out


def test_a_neutral_judges_entry_records_whether_it_ran_the_suite_itself_and_check_holds_it_to_the_signed_run():
    from knos import bundle, flow
    r = VECTORS["valid_v3"][1]["receipt"]                    # one neutral judge
    commit, pull = r["evaluator_observed"]["artifact"]["commit"], r["evaluator_observed"]["artifact"]["pull_request"]
    line = json.dumps(_verdict(r), sort_keys=True, separators=(",", ":"))
    assert isinstance(flow._rerun_read(line), dict)
    ran = bundle.reexecution_of(f"{flow.VERDICT}{line}\n\nHow this run reached its verdict: ran it.", r["order"], commit, pull)
    assert ran == bundle.reexecution_of(line, r["order"], commit, pull)         # the comment, or the run's verdict.json
    assert list(ran) == list(receipt.REEXECUTION) and (ran["reexecuted"], ran["assurance"], ran["image_digest"]) == (True, "black-box", None)
    assert ran["environment"]["github_run_id"] == str(r["issuer_authenticated"]["claims"]["run_id"]) and ran["environment"]["imageos"] == "ubuntu24"
    # built into the paying judge's entry, and nothing else of the receipt moves
    built = receipt.build3(receipt.as2(r), r["commercial_authorisation"], rerun=ran)
    assert built == _with(r, ran) and receipt.check(built) is None and receipt.chain_only(built) == r and receipt.chain_only(r) is not built
    assert receipt.digest(built) != receipt.digest(r) and receipt.digest(receipt.chain_only(built)) == receipt.digest(r)
    assert receipt.as2(built) == receipt.as2(r)
    said = "\n".join(receipt.render(built))
    assert "By its own run's word, it ran the acceptance suite itself (black-box; knos 0.0.0, on Linux, image ubuntu24)." in said
    # a hermetic run names the image by its digest; a run that read the record says it did not run the suite
    digest = "sha256:" + "a" * 64
    hermetic = bundle.reexecution_of(json.dumps(_verdict(r, assurance="hermetic", image={"ref": "ghcr.io/x/y@" + digest, "digest": digest})), r["order"], commit, pull)
    assert (hermetic["assurance"], hermetic["image_digest"]) == ("hermetic", digest) and receipt.check(_with(r, hermetic)) is None
    assert f"(hermetic, image {digest}; " in "\n".join(receipt.render(_with(r, hermetic)))
    read = bundle.reexecution_of(json.dumps({"v": 1, "reexecuted": False, "sentence": "read the record", "environment": _verdict(r)["environment"]}), r["order"], commit, pull)
    assert read == {"reexecuted": False, "assurance": None, "environment": ran["environment"], "image_digest": None} and receipt.check(_with(r, read)) is None
    assert "it did not run the acceptance suite: it read the record of the order's repository" in "\n".join(receipt.render(_with(r, read)))
    # a verdict of another payment, a failed one, or text that is not a verdict, is refused in words
    for text, why in ((json.dumps(_verdict(r, head="f" * 40)), "another order, pull request or commit"), (json.dumps(_verdict(r, pull=pull + 1)), "another order"),
                      (json.dumps(_verdict(r, passed=False, reasons=["pr: acceptance checks not passed: blackbox"])), "did not pass"),
                      ("not json", "is not JSON"), (json.dumps({**_verdict(r), "extra": 1}), "does not have the fields")):
        with pytest.raises(ValueError, match=why):
            bundle.reexecution_of(text, r["order"], commit, pull)
    # check: the words are the run's own, so they must at least name the run the issuer signed for, and keep their shape
    for name, bad, why in (
            ("another run", {**ran, "environment": {**ran["environment"], "github_run_id": "1"}}, "names the run the issuer signed for"),
            ("another repository", {**ran, "environment": {**ran["environment"], "github_repository_id": "1"}}, "names the run the issuer signed for"),
            ("an assurance nobody defines", {**ran, "assurance": "trust me"}, "an evaluator's reexecution is {reexecuted"),
            ("hermetic with no image", {**ran, "assurance": "hermetic"}, "an evaluator's reexecution is {reexecuted"),
            ("an image on a run that is not hermetic", {**ran, "image_digest": digest}, "an evaluator's reexecution is {reexecuted"),
            ("an assurance on a run that ran nothing", {**read, "assurance": "black-box"}, "an evaluator's reexecution is {reexecuted"),
            ("a field more", {**ran, "passed": True}, "an evaluator's reexecution is {reexecuted"),
            ("a long text", {**ran, "environment": {"knos": "x" * 201}}, "an evaluator's reexecution is {reexecuted"),
            ("not an object", "ran it", "an evaluator's reexecution is {reexecuted")):
        got = receipt.check(_with(r, bad))
        assert got is not None and why in got, (name, got)
    # the order's own repository runs the suite in prove.yml's judge job: no entry of that kind carries one, built or written
    own = VECTORS["valid_v3"][0]["receipt"]
    assert "a judge outside the order's repository" in receipt.check(_with(own, ran))
    with pytest.raises(ValueError, match="a judge outside it"):
        receipt.build3(receipt.as2(own), own["commercial_authorisation"], rerun=ran)
    # in a quorum the paying judge's entry is the last, and it is the one held to the token
    quorum = VECTORS["valid_v3"][2]["receipt"]
    mine = {**ran, "environment": {**ran["environment"], "github_run_id": str(quorum["issuer_authenticated"]["claims"]["run_id"]),
                                   "github_repository_id": str(quorum["issuer_authenticated"]["claims"]["repository_id"])}}
    assert receipt.check(_with(quorum, mine)) is None and "a judge outside the order's repository" in receipt.check(_with(quorum, mine, at=0))


def test_the_verdict_a_run_posted_beside_its_token_is_found_by_its_run_and_a_missing_one_is_not_an_error():
    from knos import bundle, flow
    r = VECTORS["valid_v3"][1]["receipt"]
    claims = {**r["issuer_authenticated"]["claims"], "repository": "judge/neutral"}
    commit, pull = r["evaluator_observed"]["artifact"]["commit"], r["evaluator_observed"]["artifact"]["pull_request"]
    line = lambda **over: flow.VERDICT + json.dumps(_verdict(r, **over), sort_keys=True, separators=(",", ":")) + "\n\nHow this run reached its verdict: ran it."  # noqa: E731
    other = {**_verdict(r)["environment"], "github_run_id": "5"}
    asked = []

    def get(path: str):
        asked.append(path)
        if path == "repos/judge/neutral/issues?state=open&per_page=100":
            return [{"number": 3, "title": "knos tokens", "pull_request": {}}, {"number": 9, "title": flow.TOKENS}]
        if path.startswith("repos/judge/neutral/issues/9/comments?since="):
            return [{"body": "a token"}, {"body": flow.VERDICT + "{}"}, {"body": line(environment=other)}, {"body": line(head="f" * 40)}, {"body": line()}]
        raise OSError(path)
    found = bundle._verdict_beside(get, claims, r["order"], commit, pull)
    assert found == bundle.reexecution_of(line(), r["order"], commit, pull) and receipt.check(_with(r, found)) is None
    since = asked[1].split("since=")[1].split("&")[0]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", since)                    # only comments from the hour before the token was signed
    # another run's verdict, no issue, no host: nothing is recorded, and nothing is raised
    assert bundle._verdict_beside(get, {**claims, "run_id": "6"}, r["order"], commit, pull) is None
    assert bundle._verdict_beside(get, {**claims, "repository": "nobody/nothing"}, r["order"], commit, pull) is None
    assert bundle._verdict_beside(lambda path: [], claims, r["order"], commit, pull) is None


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


def test_the_attestation_script_reads_a_version_3_receipt_and_attests_its_own_digest(tmp_path):
    """The fields of the attestation need no package of the script's: only Node. For a version 3 receipt they are the
    version 2 receipt's, and the digest is the version 3 receipt's own."""
    node = shutil.which("node")
    if not node:
        pytest.skip("needs Node")
    code = ("import fs from 'node:fs';\n"
            f"import {{ fields }} from {json.dumps((ROOT / 'scripts' / 'sas_receipt.mjs').as_uri())};\n"
            f"const v = JSON.parse(fs.readFileSync({json.dumps(str(ROOT / 'docs' / 'receipt' / 'vectors.json'))}, 'utf8'));\n"
            "const text = (f) => Object.fromEntries(Object.entries(f).map(([k, x]) => [k, k === 'receipt_sha256' ? Buffer.from(x).toString('hex') : String(x)]));\n"
            "let refused = ''; try { fields({ type: 'knos.acceptance-receipt', version: 4 }); } catch (e) { refused = e.message; }\n"
            "console.log(JSON.stringify({ three: v.valid_v3.map((x) => text(fields(x.receipt))), two: v.valid_v3.map((x) => text(fields(v.valid_v2[x.of].receipt))), refused }));\n")
    (tmp_path / "fields.mjs").write_text(code, encoding="utf-8")
    done = subprocess.run([node, str(tmp_path / "fields.mjs")], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    assert got["refused"] == "this is not a Knos acceptance receipt of version 1, 2 or 3 (docs/RECEIPT.md)."
    for v, three, two in zip(VECTORS["valid_v3"], got["three"], got["two"]):
        assert three["receipt_sha256"] == v["sha256"] != two["receipt_sha256"], v["name"]
        assert {k: x for k, x in three.items() if k != "receipt_sha256"} == {k: x for k, x in two.items() if k != "receipt_sha256"}, v["name"]
