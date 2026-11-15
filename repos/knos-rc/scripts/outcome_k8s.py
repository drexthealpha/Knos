"""An outcome that is not code, signed by a workload identity that is not a forge: the data-transformation example
(examples/outcomes/data-transformation) judged in a Kubernetes Job, and a service-account token of the cluster whose
audience is the evaluation. docs/reference/OUTCOMES.md, "A Kubernetes cluster signs an outcome", is the page.

    python scripts/outcome_k8s.py job                       IN THE POD: judge, then ask the cluster for the token
    python scripts/outcome_k8s.py collect --log LOG --out DIR   the Job's log -> DIR/token and DIR/verdict.json
    python scripts/outcome_k8s.py verify --token T --jwks J --issuer URL --verdict V --out receipt.json
                                                            offline: the verifier's rule, then the receipt
    python scripts/outcome_k8s.py chain --token T --jwks J --issuer URL --receipt R --keypair FILE [--send]
                                                            devnet: admit the cluster's key, relay the token

`verify` needs nothing but Python: the RSA arithmetic is RFC 8017's on integers. Its rule is the on-chain verifier's
(programs-v2/knos_oidc, Step): three parts of canonical base64url, at most 8,192 bytes; a PKCS#1 v1.5 SHA-256
signature under a 2048- or 4096-bit key with exponent 65537; a header and a payload that are strict JSON (RFC 8259,
no name twice at the top, at most 64 levels and 128 members); `alg` RS256; `iss` the issuer's URL; `exp` a whole
number at most a day ahead. Then what a program that spends the token would ask, which the verifier leaves to it:
the audience is exactly the evaluation's, the token has not expired, and `sub` is the service account that ran the Job.

What `chain` can and cannot do. The cluster's issuer is no public URL, so its key is a PRIVATE key: the wallet that
sends RegisterPrivateKey says the key is that cluster's, and nobody checks it. The token then verifies on chain and
its account carries the hash of the issuer's URL and that wallet. knos_meter does not count it: Record takes a token
of GitHub's from a pinned workflow and refuses a private key (error 122), and a Kubernetes token's `aud` is a list,
which no reader on chain reads. So the evaluation is a line for the seller's ledger (`knos meter batch --claim`),
with the verified token account named in the receipt beside it.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = "data-transformation"
NAMESPACE, SERVICE_ACCOUNT = "knos-outcome", "knos-judge"
SUBJECT = f"system:serviceaccount:{NAMESPACE}:{SERVICE_ACCOUNT}"
ISSUER = "https://kind.knos-outcome.invalid"    # the workflow's cluster: `.invalid` never resolves (RFC 2606), and says so
MAX_JWT, AHEAD, LATE, KEY_BITS = 8192, 86_400, 3600, (2048, 4096)     # the verifier's own numbers (examples/issuers/issuers.json)
TOKEN_SECONDS = 6 * 3600                       # asked of the cluster: long enough for a release run to carry it to devnet
MARK = "KNOS_OUTCOME "                         # the one line of the Job's log that the workflow reads
DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")       # SHA-256, RFC 8017 section 9.2
SA_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
LIMITATIONS = (
    "The cluster ran on a runner that Knos started: one party ran the cluster, the Job and the judge.",
    "The issuer is self-hosted. Its URL does not resolve and its key set was read from the cluster's own API server, so nobody "
    "outside that run can fetch the key and compare it.",
    "This shows that the path works for a workload identity that is not a forge. It does not show that an independent party ran it.",
    "The cluster signed which service account asked for this audience. It did not sign what the Job read or decided.",
    "The buyer, the seller and the work order are the example's sample values. Nobody bought this.",
)


class Refused(ValueError):
    """Why a token, a key set or a run is not taken, in one sentence."""


# -- the verifier's rule, offline -------------------------------------------------------------------------------------
def unb64(part: str) -> bytes:
    """Unpadded base64url in its one canonical spelling (RFC 7515 section 2)."""
    if not part or not re.fullmatch(r"[A-Za-z0-9_-]+", part) or len(part) % 4 == 1:
        raise Refused("a part of the token is not unpadded base64url")
    raw = base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != part:
        raise Refused("a part of the token is base64url with bits left over")
    return raw


class _Int(int):
    text = ""


def _whole(text: str) -> _Int:
    v = _Int(text)
    v.text = text
    return v


def _no(text: str):
    raise ValueError(text)


def _depth(v, level: int = 1) -> int:
    kids = v.values() if isinstance(v, dict) else v if isinstance(v, list) else ()
    return max([level, *(_depth(k, level + 1) for k in kids)])


def _strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for k, x in v.items():
            yield k
            yield from _strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _strings(x)


def strict_object(doc: bytes, what: str) -> dict:
    """One JSON object, RFC 8259 in every byte, as the verifier reads it since its strict build."""
    names: list[list[str]] = []

    def pairs(items):
        names.append([k for k, _ in items])
        return dict(items)
    try:
        v = json.loads(doc.decode("utf-8", "strict"), object_pairs_hook=pairs, parse_constant=_no, parse_int=_whole)
    except (ValueError, RecursionError):
        raise Refused(f"the token's {what} is not strict JSON") from None
    if not isinstance(v, dict):
        raise Refused(f"the token's {what} is not a JSON object")
    top = names[-1]
    if len(set(top)) != len(top):
        raise Refused(f"the token's {what} has a name twice")
    if len(top) > 128 or _depth(v) > 64:
        raise Refused(f"the token's {what} has more than 128 members or 64 levels")
    if any(0xD800 <= ord(c) <= 0xDFFF for s in _strings(v) for c in s):
        raise Refused(f"the token's {what} holds half a surrogate pair")
    return v


def jwks_rsa(jwks: dict) -> dict[str, int]:
    """{kid: modulus} of the RSA keys in a key set that the verifier can hold: exponent 65537, 2048 or 4096 bits, and
    not marked for another algorithm."""
    out = {}
    for k in jwks.get("keys", []) if isinstance(jwks, dict) else []:
        if not isinstance(k, dict) or k.get("kty") != "RSA" or k.get("alg", "RS256") != "RS256" or k.get("use", "sig") != "sig":
            continue
        try:
            n, e = int.from_bytes(unb64(k["n"]), "big"), int.from_bytes(unb64(k["e"]), "big")
        except (KeyError, TypeError, Refused):
            continue
        if e == 65537 and n.bit_length() in KEY_BITS:
            out[str(k.get("kid", ""))] = n
    return out


def describe_jwks(jwks: dict) -> list[dict]:
    """Every key of a key set as the table of docs/reference/VERIFIER.md names one: its type, its algorithm, its size."""
    rows = []
    for k in jwks.get("keys", []) if isinstance(jwks, dict) else []:
        bits = None
        if k.get("kty") == "RSA":
            try:
                bits = int.from_bytes(unb64(k["n"]), "big").bit_length()
            except (KeyError, TypeError, Refused):
                bits = None
        rows.append({"kid": k.get("kid"), "kty": k.get("kty"), "alg": k.get("alg"), "crv": k.get("crv"), "bits": bits,
                     "accepted": k.get("kty") == "RSA" and bits in KEY_BITS and k.get("alg", "RS256") == "RS256"})
    return rows


def rsa_ok(n: int, message: bytes, signature: bytes) -> bool:
    """RSASSA-PKCS1-v1_5 with SHA-256 (RFC 8017 section 8.2.2), by making the encoding again and comparing all of it."""
    k = (n.bit_length() + 7) // 8
    s = int.from_bytes(signature, "big")
    if len(signature) != k or s >= n:
        return False
    t = DIGEST_INFO + hashlib.sha256(message).digest()
    return pow(s, 65537, n).to_bytes(k, "big") == b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t


def verify_token(jwt: str, jwks: dict, issuer: str, now: int) -> dict:
    """The on-chain rule. Returns {"header", "claims", "kid", "n", "bits"}; Refused, with the reason, otherwise."""
    jwt = jwt.strip()
    if len(jwt.encode()) > MAX_JWT:
        raise Refused(f"the token is longer than {MAX_JWT} bytes")
    parts = jwt.split(".")
    if len(parts) != 3:
        raise Refused("the token is not three parts separated by two dots")
    head, body, sig = (unb64(p) for p in parts)
    header, claims = strict_object(head, "header"), strict_object(body, "payload")
    if header.get("alg") != "RS256":
        raise Refused(f"the token is signed {str(header.get('alg'))[:12]}: the verifier takes RS256 only")
    if not (issuer.startswith("https://") and 8 < len(issuer.encode()) <= 200):
        raise Refused("an issuer is an https URL of at most 200 bytes")
    if claims.get("iss") != issuer:
        raise Refused("the token's issuer is not this issuer")
    exp = claims.get("exp")
    if not isinstance(exp, _Int) or not exp.text.isdigit() or exp >= 10 ** 18:
        raise Refused("the token's exp is not a whole number in plain digits")
    if exp > now + AHEAD:
        raise Refused("the token expires more than a day ahead")
    keys = jwks_rsa(jwks)
    kid = str(header.get("kid", ""))
    if kid not in keys:
        raise Refused("the key set has no RS256 key of 2048 or 4096 bits with the token's kid")
    if not rsa_ok(keys[kid], f"{parts[0]}.{parts[1]}".encode(), sig):
        raise Refused("the signature is not the issuer's")
    return {"header": header, "claims": claims, "kid": kid, "n": keys[kid], "bits": keys[kid].bit_length()}


def spend_checks(claims: dict, audience: str, subject: str, now: int) -> None:
    """What the verifier leaves to whoever spends the token: the audience, the freshness and the workload."""
    aud = claims.get("aud")
    if aud != audience and aud != [audience]:
        raise Refused("the token's audience is not this evaluation's, alone")
    if now >= int(claims["exp"]) + LATE:
        raise Refused("the token expired more than an hour ago")
    if claims.get("sub") != subject:
        raise Refused(f"the token is not {subject}'s")


# -- the evaluation: the example's own line -----------------------------------------------------------------------------
def _knos():
    sys.path.insert(0, str(ROOT / "src"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("outcomes_evaluation", ROOT / "examples" / "outcomes" / "evaluation.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    kept, sys.dont_write_bytecode = sys.dont_write_bytecode, True       # a __pycache__ beside a bundle would change its hash
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = kept
    return mod


def evaluation(accepted: bool, artifact: str | None = None):
    """The example's evaluation with this verdict (examples/outcomes/data-transformation/evaluations.jsonl). `artifact`:
    what was judged; it must be the example's submission, or this is another evaluation and not ours to sign."""
    e = next(x for x in _knos().evaluations(EXAMPLE) if x.accepted == accepted)
    if artifact is not None and artifact != e.artifact:
        raise Refused("the files judged are not the example's submission")
    return e


def hashes(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


# -- in the pod ---------------------------------------------------------------------------------------------------------
def judge(submission: str, work: Path) -> dict:
    """`knos proof judge` on the example's base with `submission` laid over it, as tests/test_outcomes.py runs it."""
    import contextlib
    import io
    import shutil
    ev = _knos()
    from knos import judge as judge_mod
    from knos.cli import main as knos
    src = ROOT / "examples" / "outcomes" / EXAMPLE
    base, pr = work / "base", work / "pr"
    for tree in (base, pr):
        shutil.copytree(src / "base", tree)
    shutil.copytree(src / submission, pr, dirs_exist_ok=True)
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        rc = knos(["proof", "judge", "--base", str(base), "--pr", str(pr), "--issue", "1", "--evidence", str(work / "ev.json")])
    seen = json.loads((work / "ev.json").read_text(encoding="utf-8")) if (work / "ev.json").is_file() else {}
    return {"accepted": rc == 0, "assurance": seen.get("assurance"), "output": out.getvalue()[-2000:],
            "artifact": ev.artifact(src / submission), "suite": judge_mod.checks_hash(src / "base" / ".knos" / "acceptance" / "1"),
            "files": hashes(src / submission), "submission": submission}


def token_request(audience: str, seconds: int = TOKEN_SECONDS) -> str:
    """The pod asks its own cluster for a token of its own service account with this audience (the TokenRequest API),
    bound to this pod when the pod's name and uid are in POD_NAME and POD_UID."""
    host, port = os.environ["KUBERNETES_SERVICE_HOST"], os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    spec: dict = {"audiences": [audience], "expirationSeconds": seconds}
    if os.environ.get("POD_NAME") and os.environ.get("POD_UID"):
        spec["boundObjectRef"] = {"kind": "Pod", "apiVersion": "v1", "name": os.environ["POD_NAME"], "uid": os.environ["POD_UID"]}
    req = urllib.request.Request(
        f"https://{host}:{port}/api/v1/namespaces/{NAMESPACE}/serviceaccounts/{SERVICE_ACCOUNT}/token", method="POST",
        data=json.dumps({"apiVersion": "authentication.k8s.io/v1", "kind": "TokenRequest", "spec": spec}).encode(),
        headers={"Authorization": "Bearer " + (SA_DIR / "token").read_text(encoding="utf-8").strip(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, context=ssl.create_default_context(cafile=str(SA_DIR / "ca.crt")), timeout=30) as r:
        return json.load(r)["status"]["token"]


def job(args) -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        seen = judge(args.submission, Path(tmp))
    if seen["assurance"] != "black-box":
        # a run that could not tell is neither an acceptance nor the supplier's failure: nothing is signed
        print(MARK + json.dumps({"verdict": "insufficient_evidence", "why": "the suite did not run black-box here", **seen}, sort_keys=True))
        return 3
    e = evaluation(seen["accepted"], seen["artifact"])
    token = token_request(e.audience()) if not args.no_token else ""
    print(MARK + json.dumps({"verdict": "accepted" if seen["accepted"] else "rejected", "audience": e.audience(), "evaluation": json.loads(e.line()),
                             "token": token, **seen}, sort_keys=True))
    return 0


def collect(args) -> int:
    """The Job's one marked line, split into the token (a file of its own) and the verdict (everything else)."""
    lines = [ln[len(MARK):] for ln in _read(args.log).splitlines() if ln.startswith(MARK)]
    if len(lines) != 1:
        print(f"the Job's log has {len(lines)} lines that start with {MARK.strip()}; one is expected", file=sys.stderr)
        return 1
    seen = json.loads(lines[0])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    token = seen.pop("token", "")
    (out / "verdict.json").write_text(json.dumps(seen, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"verdict: {seen.get('verdict')}")
    if not token:
        print("no token: nothing was signed", file=sys.stderr)
        return 1
    (out / "token").write_text(token + "\n", encoding="utf-8", newline="\n")
    return 0


# -- offline: the receipt -----------------------------------------------------------------------------------------------
def receipt(jwt: str, jwks: dict, issuer: str, verdict: dict, now: int) -> dict:
    """Verifies and builds the receipt; Refused when anything does not hold."""
    if verdict.get("verdict") not in ("accepted", "rejected"):
        raise Refused("there is no verdict to receipt: the run could not tell (insufficient evidence)")
    e = evaluation(verdict["verdict"] == "accepted", verdict.get("artifact"))
    if verdict.get("audience") != e.audience():
        raise Refused("the verdict's audience is not the evaluation's")
    got = verify_token(jwt, jwks, issuer, now)
    claims = got["claims"]
    spend_checks(claims, e.audience(), SUBJECT, now)
    sys.path.insert(0, str(ROOT / "src"))
    from knos import ids
    deliverable = ids.deliverable(e.order, e.milestone)
    k8s = claims.get("kubernetes.io") if isinstance(claims.get("kubernetes.io"), dict) else {}
    return {
        "kind": "knos.outcome-receipt", "v": 1, "outcome": EXAMPLE,
        "issuer_authenticated": {
            "provider": "kubernetes", "issuer": issuer, "forge": False, "alg": "RS256", "key_bits": got["bits"], "kid": got["kid"],
            "key_sha256": hashlib.sha256(got["n"].to_bytes(got["bits"] // 8, "big")).hexdigest(),
            "token_sha256": hashlib.sha256(jwt.strip().encode()).hexdigest(),
            "claims": {"sub": claims["sub"], "aud": claims["aud"], "iat": claims.get("iat"), "exp": int(claims["exp"]), "jti": claims.get("jti"),
                       "pod": (k8s.get("pod") or {}).get("name"), "node": (k8s.get("node") or {}).get("name")},
            "verified": {"where": "offline", "rule": "the on-chain verifier's (scripts/outcome_k8s.py verify_token)", "at": now, "onchain": None},
        },
        "evaluator_observed": {"verdict": verdict["verdict"], "assurance": verdict.get("assurance"), "suite": verdict.get("suite"),
                               "artifact": e.artifact, "files": verdict.get("files", {})},
        "policy": {"terms_hash": e.policy, "mode": "tests"},
        "ids": {"deliverable": deliverable, "evaluation": ids.evaluation(deliverable, e.artifact, e.policy, issuer, str(claims.get("jti") or "")),
                "meter_evaluation": e.id.hex()},
        "evaluation": json.loads(e.line()), "audience": e.audience(),
        "meter": {"counted_onchain": False,
                  "why": "knos_meter records a token of GitHub's from a pinned workflow and refuses a private key; this evaluation is a line of the seller's ledger"},
        "limitations": list(LIMITATIONS),
    }


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def verify(args) -> int:
    now = args.now if args.now is not None else int(time.time())
    jwks = json.loads(_read(args.jwks))
    try:
        r = receipt(_read(args.token), jwks, args.issuer, json.loads(_read(args.verdict)), now)
    except Refused as why:
        print(f"refused: {why}", file=sys.stderr)
        for row in describe_jwks(jwks):
            print(f"  key {row['kid']}: {row['kty']} {row['alg'] or row['crv'] or ''} {row['bits'] or ''}", file=sys.stderr)
        return 1
    Path(args.out).write_text(json.dumps(r, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    a = r["issuer_authenticated"]
    print(f"verified offline: {a['issuer']} signed (RS256, a {a['key_bits']}-bit key) that {a['claims']['sub']} asked for\n"
          f"  {r['audience']}\nverdict: {r['evaluator_observed']['verdict']} ({r['evaluator_observed']['assurance']})\nlimitations:")
    for line in r["limitations"]:
        print(f"  - {line}")
    return 0


# -- devnet: admit the key, relay the token -----------------------------------------------------------------------------
def chain_groups(wallet, jwt: str, n: int, issuer: str, registered: bool = False):
    """The transactions, in order, as (what it is, instructions): the private key and its constants (left out when the
    wallet's key is already there), the token's bytes, the steps. And the token account that is VERIFIED after the last."""
    from knos.settle.v2 import oidc
    tid = oidc.token_id(jwt)
    key = oidc.key_pda(issuer, n, registrant=wallet)
    groups = [] if registered else [("register the cluster's key as this wallet's private key", [oidc.register_private_key_ix(wallet, issuer, n)]),
                                    ("its constants", [oidc.key_params_ix(wallet, issuer, n, registrant=wallet)])]
    groups += [(f"token bytes {i + 1}", [ix]) for i, ix in enumerate(oidc.write_ixs(wallet, tid, jwt))]
    groups += [(f"step {i + 1}", [oidc.step_ix(wallet, tid, key, sq)]) for i, sq in enumerate(oidc.step_plan(n.bit_length()))]
    return groups, oidc.token_pda(wallet, tid), key


def chain(args) -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from knos import chain as net
    from knos.settle.v2 import oidc
    jwt, jwks, r = _read(args.token).strip(), json.loads(_read(args.jwks)), json.loads(_read(args.receipt))
    ledger = net.ledger()                      # devnet or a localnet, never mainnet (knos.chain refuses any other)
    now = ledger.now() if args.send else int(time.time())
    try:
        got = verify_token(jwt, jwks, args.issuer, now)
        spend_checks(got["claims"], r["audience"], SUBJECT, now)
    except Refused as why:
        print(f"refused before any fee: {why}", file=sys.stderr)
        return 1
    wallet = net._keypair(_read(args.keypair))
    me = wallet.pubkey()
    key = oidc.key_pda(args.issuer, got["n"], registrant=me)
    held = oidc.read_key(ledger.account(key)) if args.send else None
    groups, account, key = chain_groups(me, jwt, got["n"], args.issuer, registered=held is not None and held.state == 1)
    print(f"verifier {oidc.OIDC_ID}\nwallet   {me} (the registrant: every reader of the token sees it)\nkey      {key}\ntoken    {account}")
    sigs = []
    for what, ixs in groups:
        if args.send:
            sigs.append(ledger.send(ixs, wallet))
            print(f"  sent {what}: {sigs[-1]}")
        else:
            print(f"  would send {what}")
    if not args.send:
        print("nothing was sent (add --send)")
        return 0
    t = oidc.read_token(ledger.account(account))
    seen = oidc.token_issuer(ledger.account(account))
    if t is None or not t.verified or seen != (oidc.issuer_hash(args.issuer), me):
        print("the token account is not VERIFIED under this issuer and wallet", file=sys.stderr)
        return 1
    r["issuer_authenticated"]["verified"]["onchain"] = {"program": str(oidc.OIDC_ID), "key": str(key), "token": str(account), "registrant": str(me),
                                                         "private_key": True, "transactions": sigs, "cluster": "devnet"}
    Path(args.receipt).write_text(json.dumps(r, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    line = Path(args.receipt).with_name("evaluation.jsonl")
    line.write_text(json.dumps(r["evaluation"], sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    print(f"VERIFIED on devnet. The evaluation's line is {line}: add it to the seller's ledger with\n"
          f"  knos meter batch {line} --ledger <ledger file> --month {time.strftime('%Y-%m', time.gmtime(now))} --claim")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("job", help="in the pod: judge the submission, then ask the cluster for the token")
    j.add_argument("--submission", default="solution")
    j.add_argument("--no-token", action="store_true", help="judge only (outside a cluster)")
    k = sub.add_parser("collect", help="the Job's log into a token file and a verdict file")
    k.add_argument("--log", required=True)
    k.add_argument("--out", required=True)
    v = sub.add_parser("verify", help="offline: the verifier's rule, then the receipt")
    c = sub.add_parser("chain", help="devnet: admit the cluster's key as a private key and relay the token")
    for s in (v, c):
        s.add_argument("--token", required=True)
        s.add_argument("--jwks", required=True)
        s.add_argument("--issuer", default=ISSUER)
    v.add_argument("--verdict", required=True)
    v.add_argument("--out", required=True)
    v.add_argument("--now", type=int, default=None)
    c.add_argument("--receipt", required=True)
    c.add_argument("--keypair", required=True, help="a file with the wallet's key (a devnet wallet)")
    c.add_argument("--send", action="store_true", help="send the transactions; without it they are only listed")
    args = p.parse_args(argv)
    return {"job": job, "collect": collect, "verify": verify, "chain": chain}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
