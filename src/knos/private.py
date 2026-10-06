"""The private-repository path: the agreed acceptance runs inside the customer's network, and three things leave it.

    the verdict             one of the four words (knos.ids.VERDICTS)
    hashes                  of the terms, of the two source trees, of the acceptance checks, of the list of attestors
                            both parties approved, and of the evidence that was sealed in the vault to both of them
    the issuer's token      the customer's own forge signs which workflow ran, in which repository, for this record

No source, no file name, no check name, no repository name and no log line is in the record: `record` builds it from
a fixed set of fields and `leaks` refuses anything else, so a workflow cannot put more in by accident.

The attestors file is what "mutually approved" means here. It is one JSON document both parties hold; its hash is in
every record, and the token's audience is the record's hash, so the issuer signs for the list as well:

    {"type": "knos.attestors", "version": 1, "parties": ["buyer", "supplier"],
     "attestors": [{"name": ..., "issuer": the token's `iss`, "issuer_run_by": "buyer" | "supplier" | "third party",
                    "repository_id": ..., "workflow": the workflow's path as the issuer signs it,
                    "administrator": who can change that repository and its runners, in the parties' own words,
                    "approved_by": ["buyer", "supplier"]}]}

`arrangement` reads that list and says which of five things it is. The difference that matters:

    independent organisations   two attestors, each approved by both parties, whose administrators differ, whose
                                issuers differ or are run by a third party, and neither issuer is run by a party.
                                To pass a false verdict, two organisations must both fail or collude.
    one administrator           two attestors one person or one organisation can change. That is one judge run twice.
    one issuer                  two attestors whose tokens one party's own server signs. Whoever administers that
                                server can sign any claim for either. That is one judge, and it is that party.

What a receipt (knos.receipt, read here and not changed) shows of each is in `receipt_shows`, with the limit that
matters across instances: a receipt compares account ids, and ids are numbered by each forge for itself.

`python -m knos.private record|check` are the two commands the workflow in examples/private runs. docs/PRIVATE.md
is the page. Nobody with a private repository has run this path: it is tested here with keys this repository holds.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any, Callable

from . import ids

ATTESTORS_TYPE, RECORD_TYPE = "knos.attestors", "knos.private-record"
AUDIENCE = "knos-private:"
RUN_BY = ("buyer", "supplier", "third party")
ARRANGEMENTS = ("no attestor both approved", "one attestor", "one administrator", "one issuer", "independent organisations")
_HEX64, _HEX40 = re.compile(r"[0-9a-f]{64}\Z"), re.compile(r"[0-9a-f]{40}\Z")
_ASSURANCES = ("black-box", "hermetic", "in-process")
# what a token of each kind of forge calls the repository and the workflow file (GitHub and GitHub Enterprise Server; GitLab)
_CLAIMS = (("repository_id", "job_workflow_ref"), ("project_id", "ci_config_ref_uri"))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(doc) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"


# ---- who both parties approved -------------------------------------------------------------------------------------------
def attestors_of(doc) -> dict:
    """An attestors file, checked. Raises ValueError in words."""
    fields = {"name", "issuer", "issuer_run_by", "repository_id", "workflow", "administrator", "approved_by"}
    try:
        assert doc["type"] == ATTESTORS_TYPE and doc["version"] == 1 and isinstance(doc["attestors"], list) and doc["attestors"]
        assert isinstance(doc["parties"], list) and len(doc["parties"]) == 2 and len(set(doc["parties"])) == 2
        for a in doc["attestors"]:
            assert set(a) == fields and a["issuer_run_by"] in RUN_BY and str(a["issuer"]).startswith("https://") and type(a["repository_id"]) is int
            assert all(isinstance(a[k], str) and a[k] for k in ("name", "workflow", "administrator")) and set(a["approved_by"]) <= set(doc["parties"])
        assert len({a["name"] for a in doc["attestors"]}) == len(doc["attestors"])
    except Exception:  # noqa: BLE001
        raise ValueError("an attestors file is {type: knos.attestors, version: 1, parties: [two names], attestors: [{name, issuer (https), issuer_run_by: "
                         "buyer, supplier or third party, repository_id, workflow, administrator, approved_by: [parties]}]} (docs/PRIVATE.md)") from None
    return doc


def approved(doc: dict) -> list[dict]:
    """The attestors BOTH parties approved. One a single party named is not in this list, whoever that party is."""
    return [a for a in attestors_of(doc)["attestors"] if set(a["approved_by"]) == set(doc["parties"])]


def arrangement(doc: dict) -> dict:
    """{arrangement, counts_as, says}: what the list of mutually approved attestors amounts to, and how many independent
    judges it should be counted as. The administrators and who runs each issuer are the parties' own statements: no
    token carries them, and this function compares what was written, not who is behind an account."""
    mine = approved(doc)
    if not mine:
        return {"arrangement": ARRANGEMENTS[0], "counts_as": 0,
                "says": "No attestor was approved by both parties. A verdict from an attestor one party chose alone protects only that party."}
    if len(mine) == 1:
        a = mine[0]
        risk = (f" Its issuer is run by the {a['issuer_run_by']}: whoever administers that server can sign any claim, so this rests on the {a['issuer_run_by']}'s "
                "administrators and on the sealed evidence the other side can open." if a["issuer_run_by"] != "third party" else "")
        return {"arrangement": ARRANGEMENTS[1], "counts_as": 1, "says": f"One attestor, approved by both parties: {a['name']}, administered by {a['administrator']}." + risk}
    # two attestors are one judge when one administrator can change both, or when one party's own server signs for both
    group = list(range(len(mine)))
    shared_admin = shared_issuer = False
    for i, a in enumerate(mine):
        for j in range(i):
            b = mine[j]
            admin = a["administrator"].strip().lower() == b["administrator"].strip().lower()
            issuer = a["issuer_run_by"] != "third party" and (a["issuer"] == b["issuer"] or a["issuer_run_by"] == b["issuer_run_by"])
            if admin or issuer:
                shared_admin, shared_issuer = shared_admin or admin, shared_issuer or issuer
                group = [group[j] if g == group[i] else g for g in group]
    judges = len(set(group))
    if judges == 1 and shared_admin:
        return {"arrangement": ARRANGEMENTS[2], "counts_as": 1,
                "says": f"{len(mine)} attestors that one administrator can change: that is one judge run more than once. Count them as one."}
    if judges == 1:
        who = next(a["issuer_run_by"] for a in mine if a["issuer_run_by"] != "third party")
        return {"arrangement": ARRANGEMENTS[3], "counts_as": 1,
                "says": f"{len(mine)} attestors whose tokens the {who}'s own server signs: whoever administers that server can sign any claim for either. "
                        f"Count them as one judge, the {who}'s."}
    own = sorted({a["issuer_run_by"] for a in mine} - {"third party"})
    note = (f" The issuer of at least one is run by a party ({', '.join(own)}): that attestor is that party's own word, and the other side's protection is the "
            "other attestor and the sealed evidence." if own else "")
    return {"arrangement": ARRANGEMENTS[4], "counts_as": judges,
            "says": f"{len(mine)} attestors, each approved by both parties, counted as {judges} independent judges: different administrators, and no one party's "
                    "server signs for two of them. A false verdict needs all of them to fail or to collude. That the administrators really are different "
                    "organisations is the parties' statement, not a signature." + note}


def receipt_shows(evaluators: list[dict]) -> str:
    """What knos.receipt says of these judges (its own function, unchanged), with the limit a private path adds."""
    from . import receipt
    same, said = receipt.independence_of(evaluators)
    return (f"same_controller: {str(same).lower()}. {said} Across two forges this comparison means less: each GitHub Enterprise Server or GitLab instance numbers "
            "its own accounts, so equal ids on two instances are two accounts, and one person holds different ids on each.")


def admits(doc: dict, claims: dict) -> dict | None:
    """The mutually approved attestor these signed claims are from, or None."""
    for a in approved(doc):
        for repo, workflow in _CLAIMS:
            ref = str(claims.get(workflow, ""))
            if claims.get("iss") == a["issuer"] and str(claims.get(repo, "")) == str(a["repository_id"]) and (ref == a["workflow"] or ref.startswith(a["workflow"] + "@")):
                return a
    return None


# ---- the record that leaves the network ----------------------------------------------------------------------------------
def record(verdict: dict, terms: bytes, attestors: bytes, evidence_sha256: str, commit: str = "") -> dict:
    """The public record of one evaluation, from the judge's verdict file (`knos proof judge --evidence`), the terms'
    bytes, the attestors file's bytes and the hash of the evidence that was sealed. A verdict that did not run to an
    answer is `insufficient_evidence`, never a rejection."""
    ev = verdict.get("evidence") if isinstance(verdict, dict) else None
    art = ev.get("artifact") if isinstance(ev, dict) else None
    ran = isinstance(verdict.get("passed"), bool) and isinstance(art, dict) and not verdict.get("error")
    word = ("accepted" if verdict["passed"] else "rejected") if ran else "insufficient_evidence"
    assert word in ids.VERDICTS
    digest = str(((ev or {}).get("image") or {}).get("digest") or "") if isinstance(ev, dict) else ""
    out = {"type": RECORD_TYPE, "version": 1, "verdict": word, "terms_sha256": _sha(terms), "attestors_sha256": _sha(attestors),
           "base_tree_sha256": (art or {}).get("base") if ran else None, "pr_tree_sha256": (art or {}).get("pr") if ran else None,
           "checks_sha256": verdict.get("checks_hash") if ran else None, "assurance": verdict.get("assurance") if ran and verdict.get("assurance") in _ASSURANCES else None,
           "image_digest": digest or None, "evidence_sha256": evidence_sha256, "commit": commit or None}
    why = leaks(out)
    if why:
        raise ValueError(f"no record was made: {why}")
    return out


def leaks(doc) -> str | None:
    """Why `doc` is not a record that may leave; None when it is. Every value is a verdict word, a hash or nothing."""
    shape: dict[str, Callable[[Any], Any]] = {"type": lambda v: v == RECORD_TYPE, "version": lambda v: v == 1, "verdict": lambda v: v in ids.VERDICTS,
             "terms_sha256": _HEX64.match, "attestors_sha256": _HEX64.match, "evidence_sha256": _HEX64.match,
             "base_tree_sha256": lambda v: v is None or _HEX64.match(v), "pr_tree_sha256": lambda v: v is None or _HEX64.match(v),
             "checks_sha256": lambda v: v is None or _HEX64.match(v), "assurance": lambda v: v is None or v in _ASSURANCES,
             "image_digest": lambda v: v is None or (v.startswith("sha256:") and _HEX64.match(v[7:])), "commit": lambda v: v is None or _HEX40.match(v) or _HEX64.match(v)}
    if not isinstance(doc, dict) or set(doc) != set(shape):
        return "a record holds exactly: " + ", ".join(sorted(shape))
    for k, ok in shape.items():
        v = doc[k]
        if not (v is None or isinstance(v, (str, int))) or isinstance(v, bool) or not ok(v):
            return f"{k} is not a verdict word, a hash or empty: a record carries nothing else"
    return None


def audience(doc: dict) -> str:
    """The audience the issuer is asked to sign: the record's hash, so the token is good for this record and no other."""
    return AUDIENCE + _sha(_json(doc))


def _claims(token: str) -> dict:
    try:
        body = token.strip().split(".")[1]
        return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:  # noqa: BLE001
        raise ValueError("the token is not a signed token (three parts, the second a JSON object)") from None


def check(doc: dict, token: str, attestors_raw: bytes, key_n: int | None = None, terms: bytes | None = None, evidence: bytes | None = None) -> list[str]:
    """What holds of a record and its token, as lines; raises ValueError for what does not. `key_n`: the modulus of the
    issuer's key, from its published key set or from the verifier's key account; without it the signature is not
    checked and the lines say so. Offline: no chain, no network."""
    from . import bundle
    attestors = attestors_of(json.loads(attestors_raw))
    why = leaks(doc)
    if why:
        raise ValueError(why)
    claims = _claims(token)
    if claims.get("aud") != audience(doc):
        raise ValueError("the token was signed for another record: its audience is not this record's hash")
    who = admits(attestors, claims)
    if who is None:
        raise ValueError("the token is not from an attestor both parties approved: its issuer, repository and workflow match none in the attestors file")
    if doc["attestors_sha256"] != _sha(attestors_raw):
        raise ValueError("the record names another attestors file than the one given (its hash differs)")
    said = [f"verdict: {ids.VERDICT_WORDS[doc['verdict']]}", f"the token's audience is this record's hash ({audience(doc)[len(AUDIENCE):][:16]}...)",
            f"signed for attestor {who['name']}: issuer {who['issuer']} (run by: {who['issuer_run_by']}), repository {who['repository_id']}, workflow {who['workflow']}"]
    if key_n is None:
        said.append("limit: no key was given, so the issuer's signature was NOT checked; the lines above are the token's own words")
    elif not bundle.rs256(token.strip(), key_n):
        raise ValueError("the issuer's signature does not hold under the key given")
    else:
        said.append("the issuer's RS256 signature holds under the key given")
    for name, data, field in (("terms", terms, "terms_sha256"), ("sealed evidence, opened", evidence, "evidence_sha256")):
        if data is not None:
            if _sha(data) != doc[field]:
                raise ValueError(f"the {name} given are not the ones the record names (sha256 differs)")
            said.append(f"the {name} are the bytes the record names")
    said.append(arrangement(attestors)["says"])
    return said


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(prog="python -m knos.private", description="The record a private evaluation may publish, and its check.")
    sub = ap.add_subparsers(dest="what", required=True)
    r = sub.add_parser("record", help="write the record: a verdict word and hashes, nothing else")
    r.add_argument("--verdict", type=Path, required=True)
    r.add_argument("--terms", type=Path, required=True)
    r.add_argument("--attestors", type=Path, required=True)
    r.add_argument("--evidence", type=Path, required=True, help="the file that is sealed in the vault (its hash goes in the record)")
    r.add_argument("--commit", default="")
    r.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("check", help="check a record and its token against the attestors both parties approved")
    c.add_argument("--record", type=Path, required=True)
    c.add_argument("--token", type=Path, required=True)
    c.add_argument("--attestors", type=Path, required=True)
    c.add_argument("--jwks", type=Path, help="the issuer's published key set, as a file: the signature is checked under the key the token names")
    c.add_argument("--terms", type=Path)
    c.add_argument("--evidence", type=Path, help="the evidence, opened from the vault")
    a = ap.parse_args(argv)
    try:
        if a.what == "record":
            raw = a.attestors.read_bytes()
            attestors_of(json.loads(raw))
            verdict = json.loads(a.verdict.read_text(encoding="utf-8"))
            doc = record(verdict.get("verdict", verdict) if isinstance(verdict.get("verdict"), dict) else verdict, a.terms.read_bytes(), raw, _sha(a.evidence.read_bytes()), a.commit)
            a.out.write_bytes(_json(doc))
            print(audience(doc))
            return 0
        attestors, token = a.attestors.read_bytes(), a.token.read_text(encoding="utf-8")
        n = None
        if a.jwks:
            head = token.strip().split(".")[0]
            kid = json.loads(base64.urlsafe_b64decode(head + "=" * (-len(head) % 4))).get("kid")
            keys = [k for k in json.loads(a.jwks.read_text(encoding="utf-8"))["keys"] if k.get("kid") == kid and k.get("kty") == "RSA"]
            if len(keys) != 1:
                raise ValueError(f"the key set holds {len(keys)} RSA keys with the token's kid {kid!r}")
            n = int.from_bytes(base64.urlsafe_b64decode(keys[0]["n"] + "=" * (-len(keys[0]["n"]) % 4)), "big")
        for line in check(json.loads(a.record.read_text(encoding="utf-8")), token, attestors, n,
                          a.terms.read_bytes() if a.terms else None, a.evidence.read_bytes() if a.evidence else None):
            print(line)
        return 0
    except (OSError, ValueError, KeyError) as why:
        print(f"not done: {why}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
