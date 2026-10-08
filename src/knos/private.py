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

`python -m knos.private run --repo FOLDER --attestors FILE` is the whole path as one command, against a simulator: the
issuer is a key made on the spot, and both parties are played on one machine. It approves, seals, records, signs,
checks, applies the retention rule, and opens and resolves a dispute (`dispute_open`, `dispute_sign`,
`dispute_check`: open by one party who could open the sealed evidence, resolved only by both).
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


# ---- a dispute both parties can use ----------------------------------------------------------------------------------------
DISPUTE_TYPE = "knos.private-dispute"
OUTCOMES = ("accepted", "rejected")           # what the two parties can agree a disputed record comes to
DISPUTED_MEANS = "the line is disputed: it is not billed and it is not paid until both parties sign what it comes to"
_DISPUTE = ("type", "version", "record_sha256", "evidence_sha256", "parties", "opened_by", "opened_at", "state", "outcome", "resolved_at", "signatures")


def _dispute_bytes(d: dict) -> bytes:
    """What a party signs: the dispute without its signatures."""
    return b"knos.private-dispute.v1\x00" + _json({k: d[k] for k in _DISPUTE if k != "signatures"})


def dispute_open(doc: dict, parties, by: str, opened: bytes, at: int) -> dict:
    """A dispute of the record `doc`, opened by the party `by`, who shows that it could open the sealed evidence:
    `opened` is the archive out of the vault, and its hash is the one the record names. Unsigned until `dispute_sign`."""
    why = leaks(doc)
    if why:
        raise ValueError(why)
    parties = [str(p) for p in parties]
    if len(set(parties)) != 2 or by not in parties:
        raise ValueError(f"a dispute is opened by one of the record's two parties ({', '.join(parties)}), and {by!r} is neither")
    if _sha(opened) != doc["evidence_sha256"]:
        raise ValueError("a dispute is opened on the evidence the record names: open the sealed file with your own key and give that archive (its sha256 differs)")
    return {"type": DISPUTE_TYPE, "version": 1, "record_sha256": _sha(_json(doc)), "evidence_sha256": doc["evidence_sha256"], "parties": sorted(parties),
            "opened_by": by, "opened_at": int(at), "state": "open", "outcome": None, "resolved_at": None, "signatures": {}}


def dispute_resolve(d: dict, outcome: str, at: int) -> dict:
    """The same dispute as resolved to `outcome`, with no signature yet: each party signs these bytes or does not."""
    if outcome not in OUTCOMES:
        raise ValueError(f"a dispute is resolved to one of: {', '.join(OUTCOMES)}")
    if d.get("state") != "open":
        raise ValueError("this dispute is resolved already")
    return {**d, "state": "resolved", "outcome": outcome, "resolved_at": int(at), "signatures": {}}


def dispute_sign(d: dict, party: str, keypair) -> dict:
    """`d` with `party`'s Ed25519 signature (a solders Keypair, the key of a Solana wallet file) over its bytes."""
    if party not in d["parties"]:
        raise ValueError(f"{party!r} is not a party to this dispute")
    return {**d, "signatures": {**d["signatures"], party: {"public": str(keypair.pubkey()), "value": str(keypair.sign_message(_dispute_bytes(d)))}}}


def dispute_check(d, doc: dict, keys: dict) -> list[str]:
    """What holds of a dispute of `doc`, as lines; raises ValueError for what does not. `keys`: each party's Ed25519
    public key, as the two exchanged them beforehand. An open dispute stands on its opener's signature. A resolved one
    stands only on BOTH parties' signatures over the same outcome: neither side resolves alone, and Knos signs nothing."""
    from solders.pubkey import Pubkey
    from solders.signature import Signature
    try:
        assert set(d) == set(_DISPUTE) and d["type"] == DISPUTE_TYPE and d["version"] == 1 and d["state"] in ("open", "resolved")
        assert sorted(d["parties"]) == d["parties"] and len(set(d["parties"])) == 2 and d["opened_by"] in d["parties"] and isinstance(d["signatures"], dict)
        assert (d["outcome"] in OUTCOMES and type(d["resolved_at"]) is int) if d["state"] == "resolved" else (d["outcome"] is None and d["resolved_at"] is None)
    except Exception:  # noqa: BLE001
        raise ValueError("a dispute is {type: knos.private-dispute, version: 1, record_sha256, evidence_sha256, parties: [two], opened_by, opened_at, "
                         "state: open or resolved, outcome, resolved_at, signatures: {party: {public, value}}}") from None
    if d["record_sha256"] != _sha(_json(doc)) or d["evidence_sha256"] != doc["evidence_sha256"]:
        raise ValueError("the dispute is about another record than the one given (its hash differs)")
    if sorted(keys) != d["parties"]:
        raise ValueError(f"give the public key of each party ({', '.join(d['parties'])}) and of nobody else")
    need = d["parties"] if d["state"] == "resolved" else [d["opened_by"]]
    for party in need:
        sig = d["signatures"].get(party)
        try:
            held = isinstance(sig, dict) and sig["public"] == str(keys[party]) and Signature.from_string(sig["value"]).verify(Pubkey.from_string(sig["public"]), _dispute_bytes(d))
        except Exception:  # noqa: BLE001 - not a signature at all
            held = False
        if not held:
            raise ValueError(f"the {party}'s signature is missing or does not hold" + (": a dispute is resolved by both parties, never by one" if d["state"] == "resolved" else ""))
    if d["state"] == "open":
        return [f"opened by the {d['opened_by']}, who opened the sealed evidence the record names", DISPUTED_MEANS]
    return [f"opened by the {d['opened_by']}; resolved by both parties ({' and '.join(d['parties'])}) to: {d['outcome']}",
            "the line counts as accepted on the invoice (a private record moves no money)" if d["outcome"] == "accepted" else "the line counts as rejected: it is not billed"]


# ---- the whole path as one command, against a simulator --------------------------------------------------------------------
SIMULATED = ("simulator: every key was made on this machine, the issuer is a key made here and not a forge, and one process played "
             "both parties. No private customer has run this path.")
_SHA256_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def _stream(seed: str | None) -> Callable[[int], bytes]:
    """`rand(n)`: the system's random bytes, or (with a seed, for a run that must repeat) a SHA-256 counter stream."""
    if seed is None:
        import os
        return os.urandom
    count = [0]

    def rand(n: int) -> bytes:
        out = b""
        while len(out) < n:
            out += hashlib.sha256(f"{seed}:{count[0]}".encode()).digest()
            count[0] += 1
        return out[:n]
    return rand


def _prime(bits: int, rand: Callable[[int], bytes]) -> int:
    def probable(n: int) -> bool:
        if any(n % p == 0 for p in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97)):
            return False
        d, r = n - 1, 0
        while d % 2 == 0:
            d, r = d // 2, r + 1
        for _ in range(24):          # Miller-Rabin
            x = pow(2 + int.from_bytes(rand(bits // 8), "big") % (n - 4), d, n)
            if x in (1, n - 1):
                continue
            for _ in range(r - 1):
                x = x * x % n
                if x == n - 1:
                    break
            else:
                return False
        return True
    while True:
        n = int.from_bytes(rand(bits // 8), "big") | (3 << (bits - 2)) | 1
        if n % 65537 != 1 and probable(n):
            return n


def simulator_issuer(rand: Callable[[int], bytes]) -> tuple[int, int]:
    """(n, d) of a 2048-bit RSA key made here, exponent 65537: the simulator's stand-in for a forge's signing key."""
    p, q = _prime(1024, rand), _prime(1024, rand)
    return p * q, pow(65537, -1, (p - 1) * (q - 1))


def simulator_token(key: tuple[int, int], claims: dict, kid: str = "simulator") -> str:
    """A token with these claims under the simulator's key, RS256 as a forge signs it (PKCS#1 v1.5, SHA-256)."""
    n, d = key
    enc = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
    signed = f"{enc(json.dumps({'alg': 'RS256', 'kid': kid, 'typ': 'JWT'}, separators=(',', ':')).encode())}.{enc(json.dumps(claims, separators=(',', ':'), sort_keys=True).encode())}"
    k = (n.bit_length() + 7) // 8
    padded = b"\x00\x01" + b"\xff" * (k - 3 - len(_SHA256_INFO) - 32) + b"\x00" + _SHA256_INFO + hashlib.sha256(signed.encode()).digest()
    return f"{signed}.{enc(pow(int.from_bytes(padded, 'big'), d, n).to_bytes(k, 'big'))}"


def _archive(files: dict[str, bytes]) -> bytes:
    """One plain tar of these files, the same bytes every time (sorted names, no dates, no owners)."""
    import io
    import tarfile
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name in sorted(files):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(files[name]), 0o644
            tar.addfile(info, io.BytesIO(files[name]))
    return out.getvalue()


def run(repo, attestors_file, out, *, terms: bytes | None = None, verdict: dict | None = None, retention: dict | None = None, now: int = 0,
        seed: str | None = None, outcome: str = "accepted", say: Callable[[str], Any] = print) -> dict:
    """The private path end to end on one machine, each step the function the real path uses, in the order it happens:

        1 the attestors both parties approved (`arrangement`)       5 the simulator's issuer signs for the record's hash
        2 a vault key for each party (knos.vault)                   6 `check`, with the evidence the SUPPLIER opened
        3 the evaluation: a verdict file, or a stand-in             7 the retention rule (knos.vault.retain, as a dry run)
        4 the evidence sealed to both; the record that may leave    8 a dispute opened by one party and resolved by both

    `repo`: the private work, a folder. `out`: a folder for what the run writes (nothing is written in `repo`).
    `verdict`: the judge's verdict (`knos proof judge --evidence`); without one the simulator hashes the folder and runs
    no suite, and says so. Returns {record, token, dispute, arrangement, files}. Raises ValueError in words."""
    from pathlib import Path

    from solders.keypair import Keypair

    from . import judge, vault
    repo, out, rand = Path(repo), Path(out), _stream(seed)
    if not repo.is_dir():
        raise ValueError(f"{repo} is not a folder: --repo is the private work as a checkout")
    raw = Path(attestors_file).read_bytes()
    agreed = attestors_of(json.loads(raw))
    how = arrangement(agreed)
    mine = approved(agreed)
    if not mine:
        raise ValueError(how["says"])
    out.mkdir(parents=True, exist_ok=True)
    buyer, supplier = agreed["parties"]
    say(SIMULATED)
    say(f"1. attestors: {how['arrangement']}, counted as {how['counts_as']}. {how['says']}")
    keys = {p: vault.new_key(re.sub(r"[^a-z0-9._-]", "-", p.lower())[:40] or "party", rand) for p in (buyer, supplier)}
    signers = {p: Keypair.from_seed(rand(32)) for p in (buyer, supplier)}
    for p in keys:
        (out / f"{keys[p]['label']}.vault-key.json").write_bytes(_json(keys[p]))
    say(f"2. keys: one vault key each for the {buyer} ({keys[buyer]['id']}) and the {supplier} ({keys[supplier]['id']}); each opens the evidence alone, and nobody else can")
    terms = terms if terms is not None else b'{"checks":[],"mode":"tests","v":1}\n'
    tree = judge.tree_hash(repo)
    stand_in = verdict is None
    verdict = {"passed": True, "evidence": {"artifact": {"base": tree, "pr": tree}}} if verdict is None else verdict
    say("3. evaluation: " + ("the simulator ran NO suite. It hashed the folder and stands in an accepted verdict, so the record names no checks and no assurance"
                             if stand_in else "the verdict file given (the judge's own)"))
    evidence = _archive({"verdict.json": _json(verdict), "terms.json": terms, "attestors.json": raw})
    sealed = vault.seal(evidence, [(keys[p]["label"], bytes.fromhex(keys[p]["public"])) for p in (buyer, supplier)], "evidence.tar", now, rand)
    held = vault.put(out / "sealed", sealed)
    doc = record(verdict, terms, raw, _sha(evidence))
    (out / "record.json").write_bytes(_json(doc))
    say(f"4. sealed to both parties: {held.name} ({len(sealed)} bytes; whoever stores it reads the header only). The record that may leave: verdict {doc['verdict']} and hashes")
    issuer = simulator_issuer(rand)
    a = mine[0]
    gitlab = "//" in a["workflow"]             # a GitLab pipeline file is named host/group/project//file
    claims = {"iss": a["issuer"], "aud": audience(doc), "iat": int(now), "exp": int(now) + 300, "runner_environment": "self-hosted",
              **({"project_id": str(a["repository_id"]), "ci_config_ref_uri": a["workflow"] + "@refs/heads/main"} if gitlab else
                 {"repository_id": str(a["repository_id"]), "job_workflow_ref": a["workflow"] + "@refs/heads/main"})}
    token = simulator_token(issuer, claims)
    (out / "token.jwt").write_text(token, encoding="utf-8")
    n64 = base64.urlsafe_b64encode(issuer[0].to_bytes(256, "big")).rstrip(b"=").decode()
    (out / "jwks.json").write_bytes(_json({"keys": [{"kty": "RSA", "kid": "simulator", "alg": "RS256", "e": "AQAB", "n": n64}]}))
    say(f"5. signed: the simulator's issuer, standing in for {a['issuer']}, signed for the audience {audience(doc)[:len(AUDIENCE) + 16]}...")
    opened, _head = vault.open_(held.read_bytes(), vault.private_of(keys[supplier]))       # the other side opens, with its own key
    for line in check(doc, token, raw, issuer[0], terms, opened):
        say("6. checked: " + line)
    policy = vault.policy_of(retention if retention is not None else {"type": vault.POLICY_TYPE, "version": 1, "keep_years": 7, "then": "hashes"})
    today = vault.retain(out / "sealed", policy, now)
    later = vault.retain(out / "sealed", policy, now + policy["keep_years"] * vault.YEAR + 86400)
    mark = vault.checkpoint([e["sha256"] for e in vault.entries(out / "sealed")], now)
    (out / "checkpoint.json").write_bytes(_json(mark))
    say(f"7. retention: keep {policy['keep_years']} years, then {policy['then']}. Today: {today[0]['action']}. A day past {policy['keep_years']} years: {later[0]['action']} "
        f"(a dry run: nothing was removed). Checkpoint root {mark['root'][:16]}...")
    public = {p: str(signers[p].pubkey()) for p in (buyer, supplier)}
    d = dispute_sign(dispute_open(doc, [buyer, supplier], supplier, opened, now + 3600), supplier, signers[supplier])
    for line in dispute_check(d, doc, public):
        say("8. dispute: " + line)
    half = dispute_sign(dispute_resolve(d, outcome, now + 7200), buyer, signers[buyer])
    try:
        dispute_check(half, doc, public)
        raise AssertionError("one party resolved a dispute alone")
    except ValueError as why:
        say(f"8. dispute: the {buyer} alone cannot resolve it ({why})")
    d = dispute_sign(half, supplier, signers[supplier])
    for line in dispute_check(d, doc, public):
        say("8. dispute: " + line)
    (out / "dispute.json").write_bytes(_json(d))
    say(f"Wrote {out}: record.json and token.jwt (what may leave), jwks.json, sealed/, checkpoint.json, dispute.json and the two vault keys.")
    return {"record": doc, "token": token, "dispute": d, "arrangement": how, "keys": public,
            "files": sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())}


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(prog="python -m knos.private", description="The record a private evaluation may publish, its check, and the whole path as one command.")
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
    e = sub.add_parser("run", help="the whole path on one machine, against a simulator: approve, seal, record, sign, check, retain, dispute")
    e.add_argument("--repo", type=Path, required=True, help="the private work, as a folder")
    e.add_argument("--attestors", type=Path, required=True)
    e.add_argument("--out", type=Path, default=Path("knos-private-run"), help="where the run writes (default: ./knos-private-run)")
    e.add_argument("--terms", type=Path)
    e.add_argument("--verdict", type=Path, help="the judge's verdict file; without it the simulator runs no suite and says so")
    e.add_argument("--retention", type=Path, help="a retention policy (default: retention.json beside the attestors file, else 7 years then hashes)")
    e.add_argument("--now", type=int, default=None, help="the time, in seconds (default: the clock)")
    e.add_argument("--seed", default=None, help="make every key from this text, so a run repeats (for tests)")
    a = ap.parse_args(argv)
    try:
        if a.what == "run":
            import time
            beside = a.attestors.parent / "retention.json"
            policy = a.retention or (beside if beside.is_file() else None)
            run(a.repo, a.attestors, a.out, terms=a.terms.read_bytes() if a.terms else None,
                verdict=json.loads(a.verdict.read_text(encoding="utf-8")) if a.verdict else None,
                retention=json.loads(policy.read_text(encoding="utf-8")) if policy else None, now=int(time.time()) if a.now is None else a.now, seed=a.seed)
            return 0
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
