"""scripts/outcome_k8s.py: an outcome that is not code, signed by a Kubernetes cluster's service-account issuer.

Every token here is signed by a TEST key derived from a fixed seed and is shaped like a projected service-account token
(the payload of kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/: `aud` a list, a nested
`kubernetes.io`). No cluster signed any of them. What is shown: the offline rule takes such a token for the example's
evaluation and refuses the ways it can be wrong, the receipt says what it is, and the test build of the verifier
(LiteSVM) verifies the same token under a private key through the very instructions `chain` would send."""
from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_790_000_000


def _load():
    spec = importlib.util.spec_from_file_location("outcome_k8s", ROOT / "scripts" / "outcome_k8s.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["outcome_k8s"] = mod
    spec.loader.exec_module(mod)
    return mod


k8s = _load()
from _settle import SeedKey, modulus, sign_jwt  # noqa: E402

KEY = SeedKey(2048, seed="knos outcome k8s cluster key")      # stands in for the cluster's sa.key; nobody's real key
KID = "kind-test-kid"


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def jwks(key=KEY, kid=KID, **over) -> dict:
    n = modulus(key)
    return {"keys": [{"kty": "RSA", "alg": "RS256", "use": "sig", "kid": kid, "e": "AQAB", "n": b64(n.to_bytes((n.bit_length() + 7) // 8, "big")), **over}]}


def claims(aud: str, now: int = NOW, **over) -> dict:
    c = {"aud": [aud], "exp": now + k8s.TOKEN_SECONDS, "iat": now, "iss": k8s.ISSUER, "jti": "aed34954-b33a-4142-b1ec-389d6bbb4936",
         "kubernetes.io": {"namespace": k8s.NAMESPACE, "node": {"name": "knos-outcome-control-plane", "uid": "646e7c5e-32d6-4d42-9dbd-e504e6cbe6b1"},
                           "pod": {"name": "judge-x7k2p", "uid": "5e0bd49b-f040-43b0-99b7-22765a53f7f3"},
                           "serviceaccount": {"name": k8s.SERVICE_ACCOUNT, "uid": "14ee3fa4-a7e2-420f-9f9a-dbc4507c3798"}},
         "nbf": now, "sub": k8s.SUBJECT}
    c.update(over)
    return c


def token(c: dict, key=KEY, header: dict | None = None, raw: bytes | None = None) -> str:
    return sign_jwt(key, c, header or {"alg": "RS256", "kid": KID}, raw_payload=raw)


@pytest.fixture(scope="module")
def ev():
    return k8s.evaluation(True)


@pytest.fixture(scope="module")
def verdict(ev):
    return {"verdict": "accepted", "audience": ev.audience(), "artifact": ev.artifact, "assurance": "black-box", "suite": "ab" * 32,
            "files": {"transform.sql": "cd" * 32}}


def test_the_evaluation_is_the_examples_own_line(ev):
    line = (ROOT / "examples" / "outcomes" / "data-transformation" / "evaluations.jsonl").read_text(encoding="utf-8").splitlines()[0]
    assert json.loads(ev.line()) == json.loads(line) and ev.audience().startswith("knosm:eval:") and len(ev.audience().split(":")) == 10
    with pytest.raises(k8s.Refused):
        k8s.evaluation(True, "0" * 40)                 # other files are another evaluation


def test_a_cluster_token_for_the_evaluation_verifies_offline_and_the_receipt_says_what_it_is(ev, verdict):
    r = k8s.receipt(token(claims(ev.audience())), jwks(), k8s.ISSUER, verdict, NOW + 60)
    a = r["issuer_authenticated"]
    assert a["provider"] == "kubernetes" and a["forge"] is False and a["issuer"] == k8s.ISSUER and a["key_bits"] == 2048 and a["alg"] == "RS256"
    assert a["claims"]["sub"] == k8s.SUBJECT and a["claims"]["aud"] == [ev.audience()] and a["claims"]["pod"] == "judge-x7k2p"
    assert a["verified"] == {"where": "offline", "rule": a["verified"]["rule"], "at": NOW + 60, "onchain": None}
    assert r["evaluator_observed"]["verdict"] == "accepted" and r["evaluation"]["id"] == ev.id.hex() and r["policy"]["terms_hash"] == ev.policy
    assert r["ids"]["deliverable"].startswith("dlv_") and r["ids"]["evaluation"].startswith("evl_")
    said = " ".join(r["limitations"])
    assert "a runner that Knos started" in said and "self-hosted" in said and "not a forge" in said and "independent party" in said
    assert r["meter"]["counted_onchain"] is False


def test_the_command_writes_the_receipt_and_refuses_in_one_line(tmp_path, ev, verdict, capsys):
    for name, text in (("token", token(claims(ev.audience()))), ("jwks.json", json.dumps(jwks())), ("verdict.json", json.dumps(verdict))):
        (tmp_path / name).write_text(text, encoding="utf-8")
    args = ["verify", "--token", str(tmp_path / "token"), "--jwks", str(tmp_path / "jwks.json"), "--verdict", str(tmp_path / "verdict.json"),
            "--out", str(tmp_path / "receipt.json"), "--now", str(NOW)]
    assert k8s.main(args) == 0
    assert json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))["kind"] == "knos.outcome-receipt"
    assert "limitations:" in capsys.readouterr().out
    (tmp_path / "token").write_text(token(claims("knosm:eval:other")), encoding="utf-8")
    assert k8s.main(args) == 1 and "refused: the token's audience" in capsys.readouterr().err


def _es256(c: dict) -> str:
    head, body = b64(json.dumps({"alg": "ES256", "kid": KID}).encode()), b64(json.dumps(c).encode())
    return f"{head}.{body}.{b64(bytes(64))}"


@pytest.mark.parametrize("why, make", [
    ("signed ES256", lambda aud: (_es256(claims(aud)), jwks())),
    ("the signature is not the issuer's", lambda aud: (token(claims(aud), key=SeedKey(2048, seed="another cluster")), jwks())),
    ("the signature is not the issuer's", lambda aud: (token(claims(aud))[:-6] + "AAAAAA", jwks())),
    ("no RS256 key", lambda aud: (token(claims(aud), key=SeedKey(1024, seed="a small key")), jwks(SeedKey(1024, seed="a small key")))),
    ("no RS256 key", lambda aud: (token(claims(aud)), {"keys": [{"kty": "EC", "crv": "P-256", "alg": "ES256", "kid": KID, "x": "AA", "y": "AA"}]})),
    ("no RS256 key", lambda aud: (token(claims(aud)), jwks(kid="another-kid"))),
    ("issuer is not this issuer", lambda aud: (token(claims(aud, iss="https://kubernetes.default.svc.cluster.local")), jwks())),
    ("more than a day ahead", lambda aud: (token(claims(aud, exp=NOW + 86_401)), jwks())),
    ("exp is not a whole number", lambda aud: (token(claims(aud, exp=float(NOW + 300))), jwks())),
    ("exp is not a whole number", lambda aud: (token(claims(aud, exp=str(NOW + 300))), jwks())),
    ("expired more than an hour ago", lambda aud: (token(claims(aud, exp=NOW - 3600)), jwks())),
    ("audience is not this evaluation's", lambda aud: (token(claims(aud.replace(":1:150000000", ":1:990000000"))), jwks())),
    ("audience is not this evaluation's", lambda aud: (token({**claims(aud), "aud": [aud, "https://kubernetes.default.svc"]}), jwks())),
    ("is not system:serviceaccount", lambda aud: (token(claims(aud, sub="system:serviceaccount:default:default")), jwks())),
    ("has a name twice", lambda aud: (token({}, raw=json.dumps(claims(aud))[:-1].encode() + b',"aud":["x"]}'), jwks())),
    ("not strict JSON", lambda aud: (token({}, raw=json.dumps(claims(aud))[:-1].encode() + b',"x":tru}'), jwks())),
])
def test_what_is_refused(ev, verdict, why, make):
    jwt, keys = make(ev.audience())
    with pytest.raises(k8s.Refused, match=why):
        k8s.receipt(jwt, keys, k8s.ISSUER, verdict, NOW)


def test_a_run_that_could_not_tell_gets_no_receipt_and_a_rejection_gets_its_own(ev, verdict):
    with pytest.raises(k8s.Refused, match="insufficient evidence"):
        k8s.receipt(token(claims(ev.audience())), jwks(), k8s.ISSUER, {"verdict": "insufficient_evidence"}, NOW)
    no = k8s.evaluation(False)
    assert no.id != ev.id and no.audience().split(":")[8] == "0"
    r = k8s.receipt(token(claims(no.audience())), jwks(), k8s.ISSUER, {**verdict, "verdict": "rejected", "audience": no.audience(), "artifact": no.artifact}, NOW)
    assert r["evaluator_observed"]["verdict"] == "rejected" and r["evaluation"]["accepted"] == 0
    with pytest.raises(k8s.Refused):                    # the accepted evaluation's token does not receipt the rejection
        k8s.receipt(token(claims(ev.audience())), jwks(), k8s.ISSUER, {**verdict, "verdict": "rejected", "audience": no.audience(), "artifact": no.artifact}, NOW)


def test_a_key_set_is_described_as_the_table_describes_one():
    rows = k8s.describe_jwks({"keys": [*jwks()["keys"], {"kty": "EC", "crv": "P-384", "alg": "ES384", "kid": "e"}]})
    assert [(r["kty"], r["bits"], r["accepted"]) for r in rows] == [("RSA", 2048, True), ("EC", None, False)]


# -- the same token in the test build of the verifier ---------------------------------------------------------------------

def test_the_verifier_takes_the_token_under_a_private_key_through_the_instructions_chain_would_send(ev):
    pytest.importorskip("solders.litesvm")
    from _oidc2 import Chain2

    from knos.settle.v2 import oidc
    c = Chain2()
    wallet = c.fund()
    jwt = token(claims(ev.audience(), now=c.now()))
    got = k8s.verify_token(jwt, jwks(), k8s.ISSUER, c.now())            # the offline rule and the program agree on it
    groups, account, key = k8s.chain_groups(wallet.pubkey(), jwt, got["n"], k8s.ISSUER)
    assert [what for what, _ in groups][:2] == ["register the cluster's key as this wallet's private key", "its constants"]
    for what, ixs in groups:
        assert c.send(ixs, wallet), (what, c.err)
    t = oidc.read_token(c.data(account))
    assert t is not None and t.verified and t.issuer == oidc.PRIVATE and t.key == key == oidc.key_pda(k8s.ISSUER, got["n"], registrant=wallet.pubkey())
    assert oidc.token_issuer(c.data(account)) == (oidc.issuer_hash(k8s.ISSUER), wallet.pubkey())     # which cluster is this wallet's word
    said = t.claims()
    assert said["aud"] == [ev.audience()] and said["sub"] == k8s.SUBJECT and said["kubernetes.io"]["pod"]["name"] == "judge-x7k2p"
    # a second token of the cluster needs no second registration
    again = token(claims(k8s.evaluation(False).audience(), now=c.now(), jti="second"))
    more, account2, _ = k8s.chain_groups(wallet.pubkey(), again, got["n"], k8s.ISSUER, registered=True)
    assert all(c.send(ixs, wallet) for _what, ixs in more) and oidc.read_token(c.data(account2)).verified
    # and what the offline rule refuses, the program refuses: another cluster's signature under this key
    forged = token(claims(ev.audience(), now=c.now(), jti="forged"), key=SeedKey(2048, seed="another cluster"))
    sent = [c.send(ixs, wallet) for _what, ixs in k8s.chain_groups(wallet.pubkey(), forged, got["n"], k8s.ISSUER, registered=True)[0]]
    assert sent[-1] is False and "Custom(70)" in (c.err or "")


def test_the_workflow_runs_the_script_and_pins_what_it_uses():
    yaml = pytest.importorskip("yaml")
    text = (ROOT / ".github" / "workflows" / "outcome-k8s.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    pins = set(json.loads((ROOT / "scripts" / "action_pins.json").read_text(encoding="utf-8"))["pins"].values())
    import re
    uses = re.findall(r"uses:\s*(\S+)@(\S+)", text)
    assert uses and all(sha in pins and len(sha) == 40 for _name, sha in uses)          # every action at a pinned commit; none is new
    assert wf["permissions"] == {} and all(j["permissions"] == {"contents": "read"} for j in wf["jobs"].values())
    for needle in ("kind create cluster", "kubectl get --raw /openid/v1/jwks", "scripts/outcome_k8s.py collect", "scripts/outcome_k8s.py verify",
                   "- name: service-account-issuer", f"value: {k8s.ISSUER}", f"= {k8s.ISSUER} ] ||", "scripts/outcome_k8s_job.yaml"):
        assert needle in text, needle
    # kind's config: the node image pinned by digest, and the issuer flag in kubeadm v1beta4's form (a list of name and value)
    import textwrap
    kind_cfg = yaml.safe_load(textwrap.dedent(text.split("<<'EOF'\n", 1)[1].split("\n          EOF", 1)[0]))
    node = kind_cfg["nodes"][0]
    assert re.fullmatch(r"kindest/node:v1\.\d+\.\d+@sha256:[0-9a-f]{64}", node["image"])
    patch = yaml.safe_load(node["kubeadmConfigPatches"][0])
    assert patch["kind"] == "ClusterConfiguration" and patch["apiServer"]["extraArgs"] == [{"name": "service-account-issuer", "value": k8s.ISSUER}]
    docs = list(yaml.safe_load_all((ROOT / "scripts" / "outcome_k8s_job.yaml").read_text(encoding="utf-8")))
    by = {d["kind"]: d for d in docs}
    assert by["Namespace"]["metadata"]["name"] == by["ServiceAccount"]["metadata"]["namespace"] == k8s.NAMESPACE and by["ServiceAccount"]["metadata"]["name"] == k8s.SERVICE_ACCOUNT
    # the service account may ask for one thing: a token of its own
    assert by["Role"]["rules"] == [{"apiGroups": [""], "resources": ["serviceaccounts/token"], "resourceNames": [k8s.SERVICE_ACCOUNT], "verbs": ["create"]}]
    pod = by["Job"]["spec"]["template"]["spec"]
    assert pod["serviceAccountName"] == k8s.SERVICE_ACCOUNT and pod["containers"][0]["command"] == ["python", "scripts/outcome_k8s.py", "job"]
    # the Job's image is built FROM the base's digest, read from the pull before the build (BuildKit keeps no copy to inspect after)
    run = "\n".join(st.get("run", "") for st in wf["jobs"]["outcome"]["steps"])
    assert "docker pull -q python:3.12-slim" in run and "printf 'FROM %s" in run and '"$base" > "$RUNNER_TEMP/Dockerfile"' in run
    assert run.index("docker pull -q python:3.12-slim") < run.index("docker build") and "--format 'base " not in run
    assert "id-token" not in text and "secrets." not in text        # it asks GitHub for no token and holds no key: it cannot send a transaction
