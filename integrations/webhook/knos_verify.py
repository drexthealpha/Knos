"""Check a Knos acceptance receipt offline. One file, standard library only: copy it into a backend, or import it.

    from knos_verify import verify
    got = verify({"token": token, "receipt": receipt, "terms": terms}, jwks, expect={"repository_id": 987654321})
    if got["ok"]: ...            # got["facts"]: order, commit, pull_request, repository_id, terms_hash, mode, payees, workflow

`evidence` is the raw token GitHub signed (a string), or a mapping with `token` and, when you have them, `receipt`
(the acceptance receipt, version 2 or 3: a mapping or its JSON) and `terms` (the order's terms, the exact bytes that were
hashed at funding). Those are token.jwt, receipt.json and terms.json of a Knos evidence bundle. `jwks` is the
issuer's public keys as you trust them: GitHub's published set
(https://token.actions.githubusercontent.com/.well-known/jwks, fetched and kept by you), or the bundle's key.json.
This function opens no connection.

What is checked, in this order; the first thing that does not hold is `refused` (a word) and `why` (a sentence):

    token      it is an RS256 token, and its signature is the one of the key in `jwks` with its `kid`
    issuer     GitHub signed it (iss), for a run of the workflow you expect (job_workflow_ref starts with
               `expect["workflow"]`, by default Knos's own pinned workflows)
    audience   it was signed for a Knos payment: one order, commit, terms hash, mode, pull request and payees
    receipt    (when given) the receipt names this token (its sha256), carries its claims, and its order, commit,
               terms, pull request and payees are the ones in the token's audience
    terms      (when given) sha256 of the terms is the terms hash, and they say what the receipt's policy says
    expect     every fact you named in `expect` is the one found: repository_id, order, commit, pull_request,
               terms_hash, mode, payee (a GitHub account id that must be among the payees)

What is not checked here, and `limits` says so in every answer: the wallets paid and the amounts are in no signed
token, so they are the receipt's word; the key is the one you gave, not read from the chain; the checks are not
evaluated again; a token's expiry is not held against a receipt, which is a record of a past payment (iat and exp
are in `facts`). `knos bundle verify FILE --rpc URL` does all of that from the bundle and the chain.

The same function in TypeScript is knos-verify.ts beside this file; fixtures.json holds the cases both must answer
the same way.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re

GITHUB = "https://token.actions.githubusercontent.com"
WORKFLOW = "drexthealpha/Knos/.github/workflows/"
MODES = ("merge", "tests")
CLAIMS = ("actor_id", "event_name", "exp", "iat", "job_workflow_ref", "job_workflow_sha", "repository_id", "repository_owner_id",
          "run_attempt", "run_id", "runner_environment")
LIMITS = ("The wallets paid and the amounts are the receipt's word: no signed token carries them.",
          "The key is the one the caller gave; it was not compared with the key account on chain.",
          "The named checks were not evaluated again, and the token's expiry was not held against it: a receipt records a past payment.")
_SHA256_INFO = bytes.fromhex("3031300d060960864801650304020105000420")       # DigestInfo of SHA-256 (RFC 8017, 9.2)
_AUD = re.compile(r"knos3:pay:([1-9A-HJ-NP-Za-km-z]{32,44}):([0-9a-f]{40}):([0-9a-f]{64}):([01]):([1-9][0-9]{0,9}):([0-9.,\-A-Za-z]+)")
_PAYEE = re.compile(r"([1-9][0-9]{0,18})\.([0-9]{1,5})\.([\-1-9A-HJ-NP-Za-km-z]{1,44})")


class _No(Exception):
    def __init__(self, code: str, why: str):
        super().__init__(why)
        self.code, self.why = code, why


def _unb64(text: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]*", text):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _keys(jwks) -> dict[str, int]:
    """{kid: modulus} of every RS256 key with exponent 65537 and at least 2048 bits in a JWKS, a list of keys or one key."""
    doc = json.loads(jwks) if isinstance(jwks, (str, bytes)) else jwks
    rows = doc.get("keys") if isinstance(doc, dict) and "keys" in doc else doc if isinstance(doc, list) else [doc]
    out = {}
    for k in rows or []:
        if not isinstance(k, dict) or k.get("e") != "AQAB" or k.get("kty", "RSA") != "RSA" or k.get("alg", "RS256") != "RS256":
            continue
        try:
            n = int.from_bytes(_unb64(str(k.get("n", ""))), "big")
        except ValueError:
            continue
        if n.bit_length() >= 2048 and isinstance(k.get("kid"), str):
            out[k["kid"]] = n
    return out


def _signed(token: str, keys: dict[str, int]) -> dict:
    """The claims of `token` when it carries the RS256 signature of the key its header names; else refused."""
    parts = token.split(".")
    try:
        head, claims, sig = json.loads(_unb64(parts[0])), json.loads(_unb64(parts[1])), _unb64(parts[2])
        assert len(parts) == 3 and isinstance(head, dict) and isinstance(claims, dict)
    except Exception:  # noqa: BLE001 - not three base64url parts of JSON
        raise _No("token", "This is not a signed token (three base64url parts, the first two JSON).") from None
    if head.get("alg") != "RS256":
        raise _No("token", "The token is not signed with RS256, the only algorithm a Knos receipt uses.")
    n = keys.get(str(head.get("kid")))
    if n is None:
        raise _No("token", "No key with the token's kid is among the keys given. Give the issuer's keys of the day the token was signed.")
    k = (n.bit_length() + 7) // 8
    want = b"\x00\x01" + b"\xff" * (k - 3 - len(_SHA256_INFO) - 32) + b"\x00" + _SHA256_INFO + hashlib.sha256(f"{parts[0]}.{parts[1]}".encode()).digest()
    if len(sig) != k or pow(int.from_bytes(sig, "big"), 65537, n).to_bytes(k, "big") != want:
        raise _No("token", "The token's signature is not the one of the key with its kid: the token or the key was changed.")
    return claims


def _told(claims: dict) -> dict:
    """The token's claims as a receipt writes them: times as numbers, everything else as text."""
    def one(key: str):
        v = claims[key]
        return int(v) if key in ("iat", "exp") else str(v).lower() if isinstance(v, bool) else str(v)
    return {key: one(key) for key in CLAIMS if key in claims}


def _audience(claims: dict) -> dict:
    m = _AUD.fullmatch(str(claims.get("aud", "")))
    payees = [_PAYEE.fullmatch(p) for p in m.group(6).split(",")] if m else [None]
    if not m or not all(payees):
        raise _No("audience", "The token was not signed for a Knos payment (its audience is not knos3:pay:order:commit:terms:mode:pull:payees).")
    return {"order": m.group(1), "commit": m.group(2), "terms_hash": m.group(3), "mode": MODES[int(m.group(4))], "pull_request": int(m.group(5)),
            "payees": [{"github_id": int(p.group(1)), "bps": int(p.group(2))} for p in payees]}


def _receipt(r, token: str, claims: dict, facts: dict) -> None:
    try:
        a, o, p = r["issuer_authenticated"], r["evaluator_observed"], r["policy"]
        shaped = r["type"] == "knos.acceptance-receipt" and r["version"] in (2, 3) and type(r["version"]) is int and o["verdict"] == "accepted"
        named = {"order": r["order"], "commit": o["artifact"]["commit"], "terms_hash": p["terms_hash"], "mode": p["mode"],
                 "pull_request": o["artifact"]["pull_request"], "payees": [{"github_id": e["github_id"], "bps": e["bps"]} for e in r["payees"]]}
        repo, digest, told, issuer = r["repository"]["id"], a["token_sha256"], a["claims"], a["issuer"]
    except Exception:  # noqa: BLE001 - a missing field, or not a mapping at all
        shaped = False
    if not shaped:
        raise _No("receipt", "This is not an acceptance receipt of version 2 or 3 with an accepted verdict (docs/RECEIPT.md).")
    if hashlib.sha256(_unb64(token.rsplit(".", 1)[1])).hexdigest() != digest:
        raise _No("receipt", "The receipt names another token than the one given (token_sha256 differs).")
    if told != _told(claims) or issuer != claims.get("iss") or str(repo) != str(claims.get("repository_id")):
        raise _No("receipt", "The claims, the issuer or the repository in the receipt are not the ones the token carries.")
    if named != {k: facts[k] for k in named}:
        raise _No("receipt", "The order, commit, terms, pull request or payees in the receipt are not the ones the token was signed for.")


def _terms(raw, facts: dict, receipt) -> None:
    data = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
    if hashlib.sha256(data).hexdigest() != facts["terms_hash"]:
        raise _No("terms", "These are not the terms hashed at funding (their sha256 is not the terms hash the token names).")
    try:
        t = json.loads(data)
        same = t["mode"] == facts["mode"] and (receipt is None or (t["paths"], t["deny"], t["v"]) == tuple(receipt["policy"][k] for k in ("allowed_paths", "denied_paths", "version")))
    except Exception:  # noqa: BLE001
        same = False
    if not same:
        raise _No("terms", "The terms do not say what the token and the receipt's policy say (mode, allowed and denied paths, version).")


def _expect(expect: dict, facts: dict) -> None:
    for key, want in expect.items():
        if key == "workflow":
            continue
        if key == "payee":
            ok = str(want) in [str(p["github_id"]) for p in facts["payees"]]
        elif key in ("repository_id", "order", "commit", "pull_request", "terms_hash", "mode"):
            ok = str(facts[key]) == str(want)
        else:
            raise _No("expect", f"`{key}` is not a fact this function can hold a receipt to.")
        if not ok:
            raise _No("expect", f"The receipt is for another {key.replace('_', ' ')} than the one expected.")


def verify(evidence, jwks, expect: dict | None = None) -> dict:
    """{"ok", "refused", "why", "checked", "facts", "limits"} for `evidence` under the keys `jwks`. Never raises for
    evidence that is wrong: `ok` is False, `refused` is the step that failed and `why` says it in a sentence."""
    expect, checked, facts = dict(expect or {}), [], {}
    try:
        ev = evidence
        if isinstance(ev, (str, bytes)):
            text = (ev.decode("utf-8", "replace") if isinstance(ev, bytes) else ev).strip()
            ev = json.loads(text) if text.startswith("{") else {"token": text}
        if not isinstance(ev, dict) or not isinstance(ev.get("token"), str):
            raise _No("token", "Give the token GitHub signed, or a mapping with `token` and optionally `receipt` and `terms`.")
        token, receipt, terms = ev["token"].strip(), ev.get("receipt"), ev.get("terms")
        claims = _signed(token, _keys(jwks))
        checked.append("the token carries the RS256 signature of the key given for its kid")
        workflow = str(expect.get("workflow", WORKFLOW))
        if claims.get("iss") != GITHUB or not str(claims.get("job_workflow_ref", "")).startswith(workflow):
            raise _No("issuer", f"The token is not GitHub's for a run of {workflow}: another issuer or another workflow asked for it.")
        checked.append(f"GitHub signed it for a run of {claims['job_workflow_ref']}")
        facts = {**_audience(claims), "repository_id": str(claims.get("repository_id", "")), "workflow": claims["job_workflow_ref"],
                 "workflow_sha": str(claims.get("job_workflow_sha", "")), "iat": claims.get("iat"), "exp": claims.get("exp")}
        checked.append("it names one order, commit, terms hash, pull request and its payees")
        if receipt is not None:
            receipt = json.loads(receipt) if isinstance(receipt, (str, bytes)) else receipt
            _receipt(receipt, token, claims, facts)
            checked.append("the receipt names this token and says what the token says")
        if terms is not None:
            _terms(terms, facts, receipt)
            checked.append("the terms are the ones hashed at funding")
        _expect(expect, facts)
        if set(expect) - {"workflow"}:
            checked.append("it is for the " + ", ".join(sorted(k.replace("_", " ") for k in expect if k != "workflow")) + " expected")
    except _No as no:
        return {"ok": False, "refused": no.code, "why": no.why, "checked": checked, "facts": facts, "limits": list(LIMITS)}
    except (ValueError, TypeError):
        return {"ok": False, "refused": "token", "why": "The evidence could not be read as a token or as JSON.", "checked": checked, "facts": facts, "limits": list(LIMITS)}
    return {"ok": True, "refused": "", "why": "", "checked": checked, "facts": facts, "limits": list(LIMITS)}


if __name__ == "__main__":      # python knos_verify.py EVIDENCE.json JWKS.json: the answer as JSON, exit 1 when refused
    import sys
    from pathlib import Path
    answer = verify(Path(sys.argv[1]).read_text(encoding="utf-8"), Path(sys.argv[2]).read_text(encoding="utf-8"))
    print(json.dumps(answer, indent=1, sort_keys=True))
    sys.exit(0 if answer["ok"] else 1)
