"""The evidence bundle: one .tar that holds everything a payment's verdict was derived from, so the buyer and the
seller hold the same bytes and either can re-derive the verdict with no network.

    MANIFEST.json   {"type", "version", "order", "files": {name: sha256}}
    receipt.json    the acceptance receipt, version 4 (or 3, or 2), in canonical form (docs/RECEIPT.md)
    token.jwt       the raw token the issuer signed, as it was written to knos_oidc
    key.json        the issuer's public key that verified it: {issuer, kid, n, e, account}
    terms.json      the order's terms, the bytes that were hashed at funding
    checks.json     the check runs, commit statuses and changed files of the accepted commit, as fetched
    judge.json      {kind, version, inputs_sha256}: who judged, at which commit of its workflow, over which checks.json
    verdict.json    optional, tests mode: the judge's verdict as `knos proof judge --evidence` wrote it: the hashes of the
                    two trees it ran on, the acceptance checks' hash, its assurance, and the image digest when it ran in
                    one. The trees themselves are not in the bundle: the receipt names the commit, and whoever runs
                    `knos judge rerun <bundle> --base DIR --pr DIR` checks them out and is told when they are not the same.

    chain.json      optional (a bundle that has it or keys.json says version 2 in its manifest): the archived copy of
                    the chain record. The paying transaction, the funding transaction and the one that verified the
                    token, each as the cluster gave it (its logs and instructions) with its slot and blockhash, and the
                    verifier's key account. Devnet can be reset: `verify_offline` reads this copy and says so.
    keys.json       optional: the list of keys the issuer published (GitHub's JWKS), as fetched, with the time it was
                    fetched. The one file two builds of one order differ in, when they are made at different times.

`make` is deterministic (names in order, times zero, one mode, no owner), so two builds of one order are the same
bytes. `verify` reads the tar alone: every file against the manifest, the token's signature against the included key,
the key against the address the receipt names (a derivation, no network), the claims and the audience against the
receipt, the terms against their hash, and the verdict again from the terms and the checks. With an RPC URL it also
reads the key's account on chain and the paying transaction: the wallets paid and the amounts are in no signed token,
so offline they are the receipt's word, and `verify` says so. `gather` builds the files from the chain and the host's API.
`verify_offline` is the check for when the chain is gone (`--no-chain`): it sorts every statement into verified from
signatures, resting on an archived copy, or not checkable without a cluster.

The commands live here: `knos bundle make|verify`, and `knos receipt <file> | mirror | verify` (docs/RECEIPT.md).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path     # at module level: typer reads the commands' annotations here

from . import receipt as rc
from . import terms as tm

TYPE, VERSION = "knos.evidence-bundle", 1
FILES = ("receipt.json", "token.jwt", "key.json", "terms.json", "checks.json", "judge.json")
OPTIONAL = ("verdict.json", "chain.json", "keys.json")       # one layout, read by `verify` and by `knos judge rerun`
ARCHIVES = ("chain.json", "keys.json")     # a bundle that holds one of these is of version 2: a reader of version 1 refuses it by name, not by surprise
CHAIN_ARCHIVE, PUBLISHED_KEYS = "knos.chain-archive", "knos.published-keys"
KEY_LISTS = {"https://token.actions.githubusercontent.com": "https://token.actions.githubusercontent.com/.well-known/jwks",
             "https://gitlab.com": "https://gitlab.com/oauth/discovery/keys"}
_SHA256_INFO = bytes.fromhex("3031300d060960864801650304020105000420")      # DigestInfo of SHA-256 (RFC 8017, 9.2)
_RUN_KEYS, _STATUS_KEYS = ("id", "name", "status", "conclusion", "details_url"), ("id", "context", "state", "created_at", "updated_at")
GENESIS = {"EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG": "devnet", "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d": "mainnet-beta"}


class Unavailable(LookupError):
    """The chain does not have the record (a reset cluster, or a history older than what was read)."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _json(doc) -> bytes:
    return rc.canonical(doc) + b"\n"


# ---- the tar ------------------------------------------------------------------------------------------------------------------
def make(files: dict[str, bytes], order: str) -> bytes:
    """The bundle of these files (FILES, and verdict.json when there is one), as bytes. The same files give the same
    bytes on any machine."""
    if not set(FILES) <= set(files) <= set(FILES) | set(OPTIONAL):
        raise ValueError(f"a bundle holds exactly {', '.join(FILES)}, and {OPTIONAL[0]} when a judge ran; got {', '.join(sorted(files))}")
    manifest = _json({"type": TYPE, "version": 2 if set(files) & set(ARCHIVES) else VERSION, "order": order, "files": {name: _sha(files[name]) for name in sorted(files)}})
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, data in sorted({**files, "MANIFEST.json": manifest}.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode, info.uid, info.gid, info.uname, info.gname = len(data), 0, 0o644, 0, 0, "", ""
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def read(blob: bytes) -> dict[str, bytes]:
    """The files of a bundle, each checked against the manifest. Raises ValueError, in words, for anything else."""
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as tar:
            members = tar.getmembers()
            if any(not m.isfile() for m in members) or len({m.name for m in members}) != len(members):
                raise ValueError("the bundle holds something that is not a plain file, or a name twice")
            files = {}
            for m in members:
                f = tar.extractfile(m)
                if f is None:
                    raise ValueError(f"the bundle's {m.name} cannot be read as a file")
                files[m.name] = f.read()
    except tarfile.TarError as e:
        raise ValueError(f"this is not a bundle (not a tar: {e})") from None
    try:
        manifest = json.loads(files.pop("MANIFEST.json"))
        listed = manifest["files"]
        assert manifest["type"] == TYPE and manifest["version"] in (VERSION, 2) and isinstance(listed, dict)
    except Exception:  # noqa: BLE001 - missing, not JSON, or not a manifest: one sentence either way
        raise ValueError("the bundle has no MANIFEST.json of a Knos evidence bundle, version 1 or 2") from None
    known = set(FILES) | set(OPTIONAL)
    if not set(FILES) <= set(files) <= known or set(listed) != set(files):
        raise ValueError(f"the bundle's files are not the ones a bundle holds: {', '.join(sorted(set(files) ^ set(FILES)) or sorted(set(listed) ^ set(files)))}")
    for name in sorted(files):
        if _sha(files[name]) != listed[name]:
            raise ValueError(f"{name} is not the file the manifest lists (its sha256 differs): the bundle was changed after it was made")
    if blob != make(files, manifest.get("order", "")):
        raise ValueError("the bundle is not in the one form `knos bundle make` writes (order of files, times, modes): it was repacked")
    return files


# ---- the verdict, again, from the bundle alone -------------------------------------------------------------------------------
def rs256(token: str, n: int) -> bool:
    """Whether `token` (a JWT) carries the RS256 signature of the key with modulus `n` and exponent 65537."""
    try:
        signed, _, sig = token.rpartition(".")
        k = (n.bit_length() + 7) // 8
        raw = _unb64(sig)
        if len(raw) != k or json.loads(_unb64(signed.split(".")[0])).get("alg") != "RS256":
            return False
        want = b"\x00\x01" + b"\xff" * (k - 3 - len(_SHA256_INFO) - 32) + b"\x00" + _SHA256_INFO + hashlib.sha256(signed.encode()).digest()
        return pow(int.from_bytes(raw, "big"), 65537, n).to_bytes(k, "big") == want
    except Exception:  # noqa: BLE001 - not a token at all
        return False


def _issuer_number(issuer: str):
    from .settle.v2 import oidc
    return next((num for num, url in oidc.ISSUERS.items() if url == issuer), issuer)


def _assurance(files: dict[str, bytes], terms: dict) -> list[str]:
    """What the bundle says about how the acceptance checks were run: one "checked:" line when it holds a verdict, and
    the "assurance:" line. Raises ValueError when verdict.json is not a verdict under these terms."""
    raw = files.get("verdict.json")
    if raw is None:
        if terms["mode"] != "tests":
            return ["assurance: none is claimed. In merge mode a maintainer's merge is the acceptance, and no judge ran the pull request's code."]
        return ["assurance: not said by this bundle. It holds no verdict.json (`knos bundle make --verdict FILE` adds the judge's), so it does not "
                "say how the acceptance checks were run" + (f"; the terms name the image `{terms['image']}`, and a judge that kept to them ran "
                                                            "in it." if terms.get("image") else ".")]
    try:
        v = json.loads(raw)
        ev, level = v["evidence"], v.get("assurance")
        trees, image = ev["artifact"], ev.get("image") or {}
        shaped = v["passed"] is True and raw == _json(v) and level in tm.ASSURANCE and all(isinstance(trees.get(k), str) and len(trees[k]) == 64 for k in ("base", "pr"))
    except Exception:  # noqa: BLE001 - not JSON, or not a verdict's shape: one sentence either way
        shaped = False
    if not shaped:
        raise ValueError("verdict.json is not a passed verdict in canonical form with its assurance and the hashes of the two trees "
                         "(`knos proof judge --evidence FILE` writes one)")
    if terms["mode"] != "tests" or v.get("checks_hash") != terms["accept"]:
        raise ValueError("verdict.json is not a verdict under these terms: it was given on other acceptance checks than the ones hashed at funding")
    if (level == "hermetic") != bool(image) or image.get("ref", "") != terms.get("image", "") or (image and not str(image.get("digest", "")).startswith("sha256:")):
        raise ValueError("verdict.json does not name the image the terms name: a hermetic verdict ran in the terms' image, by its digest, and no other verdict names one")
    where = f", in `{image['ref']}`" if image else ""
    return [f"verdict.json is a passed verdict on the acceptance checks hashed at funding{', in the image the terms name' if image else ''} (it is the "
            f"judge's own account, signed by nobody: `knos judge rerun` runs the same judge again on the trees whose hashes it records, base "
            f"{trees['base'][:16]} and pull request {trees['pr'][:16]})",
            f"assurance: {level}{where}. {tm.ASSURANCE[level]}"]


def _paid_as_recorded(r: dict, call) -> str:
    """Compare the wallets and amounts of the receipt with what the escrow logged in the paying transaction on the
    cluster behind `call`. Raises ValueError when they differ, the transaction is gone, or the receipt names an escrow
    this knos does not read (a bundle made on another deployment: it is refused as that, not as a changed receipt)."""
    from . import records
    if r["program"] not in records.PROGRAMS:
        raise ValueError(f"the receipt names the escrow program {r['program']}, and this knos reads the escrow at {' and '.join(records.PROGRAMS)}: the "
                         "bundle was made on another deployment of the programs (or its receipt was edited to name one), so its wallets cannot be "
                         "compared with that program's lines here. For a staging deployment, verify with its ids: KNOS_PROGRAM_IDS=<its ids file>")
    sig = r["transaction"]["signature"]
    tx = call("getTransaction", [sig, {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 1}])
    if not tx:
        raise ValueError(f"the cluster no longer has the paying transaction {sig}, so the wallets paid cannot be compared with the chain's record; "
                         "give --mirror to compare the receipt with a mirror's copy")
    mine = [e for e in records.events_of(tx) if e.get("order") == r["order"]]
    paid = [(int(e["payee"]), str(e["amount"]), str(e["to"])) for e in mine if e["event"] == "order_paid"]
    settled = next((e for e in mine if e["event"] == "order_settled"), {})
    if paid != [(p["github_id"], p["amount"], p["to"]) for p in r["payees"]]:
        raise ValueError("the wallets or amounts in the receipt are not the ones the chain's record of the paying transaction shows: the receipt was changed")
    if {k: str(settled.get(k)) for k in ("paid", "of", "fee", "tip")} != {k: r["amounts"][k] for k in ("paid", "of", "fee", "tip")}:
        raise ValueError("the amounts in the receipt are not the ones the chain's record of the paying transaction shows: the receipt was changed")
    return "the chain's record of the paying transaction shows these wallets paid these amounts, this fee and this tip"


LIMIT = ("limit: the wallets paid and the amounts are the receipt's word here. No signed token carries them (the token names accounts and shares), "
         "so a bundle whose receipt names another wallet, with its manifest rebuilt, still passes offline. Give --rpc to compare them with the "
         "chain's record of the paying transaction, or --mirror to compare the receipt with a mirror's copy.")


def _key_on_record(r: dict, n: int, call, copy: str = "") -> str:
    """The verifier's key account, as the cluster behind `call` gives it, holds the key with modulus `n` and is not
    revoked. Raises ValueError otherwise. `copy`: said after "the chain's" when `call` reads an archived copy."""
    from .settle.v2 import oidc
    v = r["issuer_authenticated"]["verified"]
    got = (call("getAccountInfo", [v["key"], {"encoding": "base64"}]) or {}).get("value")
    data = base64.b64decode(got["data"][0]) if got else b""
    k = oidc.read_key(data)
    if not got or got.get("owner") != v["program"] or k is None or k.revoked or n.to_bytes(k.bits // 8, "big") not in (
            data[oidc.K_HDR:oidc.K_HDR + k.bits // 8], data[oidc.K_HDR:oidc.K_HDR + k.bits // 8][::-1]):
        raise ValueError(f"the chain's {copy}record of the key at {v['key']} is missing, revoked or holds another key")
    return "the chain's key account holds this key and it is not revoked"


SIGNED, COPY = "signatures", "archive"      # how a statement of `_core` was established: from a signature, or from an unsigned file of the bundle


def _core(blob: bytes) -> tuple[dict, dict[str, bytes], int, list[tuple[str, str]], list[str]]:
    """(the receipt, the files, the key's modulus, what was checked as (SIGNED or COPY, one line), the assurance lines)
    for a bundle that holds together with no network. Raises ValueError with the first thing that does not."""
    from solders.pubkey import Pubkey

    from .settle.v2 import oidc
    files = read(blob)
    done = [(COPY, f"every file is the one the manifest lists ({len(files)} files)")]
    try:
        r, key, judge, checks = (json.loads(files[name]) for name in ("receipt.json", "key.json", "judge.json", "checks.json"))
        token = files["token.jwt"].decode("ascii").strip()
        claims = json.loads(_unb64(token.split(".")[1]))
        n = int.from_bytes(_unb64(key["n"]), "big")
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"a file of the bundle cannot be read as what it is ({e})") from None
    why = rc.check(r)
    if why or r["version"] not in (2, 3, 4) or rc.as3(r) is None or files["receipt.json"] != _json(r):     # a version 4 one of a paid, accepted deliverable
        raise ValueError(f"receipt.json is not a valid version 2, 3 or 4 receipt of a payment in canonical form{': ' + why if why else ''}")
    a, o, p = r["issuer_authenticated"], r["evaluator_observed"], r["policy"]
    # 1. what the issuer authenticated
    if key.get("e") != "AQAB" or not rs256(token, n):
        raise ValueError("the token's signature is not the included key's: the token or the key was changed")
    done.append((SIGNED, "the token carries the RS256 signature of the included key"))
    pinned = str(oidc.key_pda(_issuer_number(a["issuer"]), n, Pubkey.from_string(a["verified"]["program"])))
    if pinned != a["verified"]["key"] or key.get("account") != pinned or key.get("issuer") != a["issuer"] or claims.get("iss") != a["issuer"]:
        raise ValueError("the included key is not the one at the knos_oidc key account the receipt names")
    done.append((SIGNED, f"that key is the one knos_oidc holds at {pinned} (the address is derived from the key)"))
    if _sha(_unb64(token.rsplit(".", 1)[1])) != a["token_sha256"]:
        raise ValueError("the token is not the one the receipt names (token_sha256 differs)")
    told = {k: int(claims[k]) if k in ("iat", "exp") else str(claims[k]).lower() if isinstance(claims[k], bool) else str(claims[k]) for k in a["claims"] if k in claims}
    if told != a["claims"]:
        raise ValueError("the claims in the receipt are not the ones the token carries")
    aud = str(claims.get("aud", "")).split(":")
    mode = str(rc.MODES.index(p["mode"]))
    if aud[:2] != ["knos3", "pay"] or len(aud) != 8 or aud[2:7] != [r["order"], o["artifact"]["commit"], p["terms_hash"], mode, str(o["artifact"]["pull_request"])]:
        raise ValueError("the token was not signed for this order, commit, terms and pull request (its audience says otherwise)")
    named = [(int(i), int(bps)) for i, bps, _ in (e.split(".") for e in aud[7].split(","))]
    if named != [(e["github_id"], e["bps"]) for e in r["payees"]]:
        raise ValueError("the payees in the receipt are not the ones the token names")
    done.append((SIGNED, "the token names this order, this commit, these terms and these payees"))
    # 3. which policy (before 2: the verdict is derived from it)
    if _sha(files["terms.json"]) != p["terms_hash"]:
        raise ValueError("terms.json is not what was hashed at funding (its sha256 is not the receipt's terms hash)")
    try:
        terms = tm.parse(files["terms.json"])
    except tm.Refused as e:
        raise ValueError(f"terms.json is not a set of terms: {e}") from None
    if terms["mode"] != p["mode"] or terms["paths"] != p["allowed_paths"] or terms["deny"] != p["denied_paths"] or terms["v"] != p["version"]:
        raise ValueError("the policy in the receipt is not what terms.json says")
    done.append((SIGNED, "terms.json is the terms fixed at funding (its sha256 is the terms hash)"))
    # 2. what the evaluator observed
    if judge != {"kind": o["judge"]["kind"], "version": o["judge"]["version"], "inputs_sha256": _sha(files["checks.json"])}:
        raise ValueError("judge.json does not name this judge, its version and these checks (inputs_sha256 is sha256 of checks.json)")
    if checks.get("commit") != o["artifact"]["commit"]:
        raise ValueError("checks.json is about another commit than the one accepted")
    seen = tm.evidence(terms, checks.get("check_runs"), checks.get("statuses"), run_id="")
    ok, reasons = tm.accepted(terms, seen, checks.get("changed_files"))
    if not ok:
        raise ValueError("the verdict does not follow from the bundle: " + "; ".join(reasons))
    if sorted(seen) != [e["name"] for e in o["checks"]]:
        raise ValueError("the checks in the receipt are not the ones the terms require")
    done.append((COPY, f"the verdict follows again: {len(seen)} named checks passed at the commit and every changed file is within the allowed paths"))
    return r, files, n, done, _assurance(files, terms)


def verify(blob: bytes, call=None, mirror: str = "") -> tuple[dict, list[str]]:
    """(the receipt, what was checked, one line each) for a bundle that holds together. Raises ValueError with the
    first thing that does not. Nothing is asked of any network unless `call(method, params)` (a cluster's JSON-RPC)
    is given: then the key's account and the paying transaction are read there too. `mirror` (a folder or URL): the
    receipt must be the one that mirror holds for the paying transaction. With neither, the last line is LIMIT."""
    r, _files, n, classed, said = _core(blob)
    done = [line for _, line in classed]
    if call is not None:
        done.append(_key_on_record(r, n, call))
        done.append(_paid_as_recorded(r, call))
    else:
        done.append("the chain was not asked (give --rpc to compare the key with its account on chain)")
    if mirror:
        # a mirror is written from the chain alone; a bundle made with the host may also say how the judge's run reached its verdict
        if rc.digest(rc.chain_only(r)) not in {rc.digest(rc.chain_only(h)) for h in rc.mirror_find(mirror, r["transaction"]["signature"])}:
            raise ValueError(f"the mirror at {mirror} does not hold this receipt for the paying transaction: the receipt was changed, or the mirror never had it")
        done.append(f"the mirror at {mirror} holds the same receipt for the paying transaction")
    return r, [*done, *said, *([] if call is not None or mirror else [LIMIT])]


# ---- with the chain gone ---------------------------------------------------------------------------------------------------------
NO_CLUSTER = ("that a cluster holds the paying transaction at that slot: the archived copy is what is left of it, and it is signed by nobody. Whoever rebuilds "
              "a bundle can rewrite the archive together with the receipt, so compare this bundle's sha256 with the other party's copy, or the receipt's "
              "digest with a mirror's (--mirror)",
              "that the verifier's key account holds this key today and has not been revoked since",
              "that the token's single-use marker is on chain (the same token cannot pay twice): only a cluster shows it")


def _utc(t: int) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def published_keys(issuer: str, fetch=None, now=None) -> dict | None:
    """The list of keys `issuer` publishes, as keys.json holds it: {type, version, issuer, url, retrieved_at, keys:
    [{kid, n, e}] in order of kid}. None when the issuer has no list known here or it could not be fetched: nothing
    here raises. `fetch(url) -> bytes` and `now() -> int` stand in for the network and the clock in tests."""
    import time
    url = KEY_LISTS.get(issuer)
    if not url:
        return None
    try:
        if fetch is None:
            import urllib.request
            fetch = lambda u: urllib.request.urlopen(u, timeout=10).read()  # noqa: E731, S310 - the issuer's own published list
        keys = sorted(({"kid": str(k.get("kid", "")), "n": str(k["n"]), "e": str(k.get("e", ""))} for k in json.loads(fetch(url))["keys"] if k.get("kty") == "RSA"),
                      key=lambda k: (k["kid"], k["n"]))
    except Exception:  # noqa: BLE001 - no network, or not a key list: the caller says which copy it used instead
        return None
    return {"type": PUBLISHED_KEYS, "version": 1, "issuer": issuer, "url": url, "retrieved_at": int((now or time.time)()), "keys": keys}


def _archived_call(arch: dict):
    """A cluster's `call` that answers from chain.json alone: its three transactions and the key account."""
    txs = {t["signature"]: t["transaction"] for t in (arch.get(k) for k in ("payment", "funding", "verified")) if t}
    def call(method: str, params: list):
        if method == "getTransaction":
            return txs.get(params[0])
        acct = arch.get("key_account") or {}
        return {"value": {"owner": acct["owner"], "data": [acct["data"], "base64"]} if method == "getAccountInfo" and params[0] == acct.get("address") else None}
    return call


def _key_identity(files: dict[str, bytes], issuer: str, live) -> tuple[list[str], list[str], list[str]]:
    """Whose key signed: (from signatures, from an archive, not checked). The key is looked for in the issuer's live
    list first (`live(issuer)` gives a `published_keys` document or None), then in the bundle's archived list. Raises
    ValueError when a list names this key's id with another key."""
    key = json.loads(files["key.json"])
    kid, n = key.get("kid", ""), int.from_bytes(_unb64(key["n"]), "big")
    def held(doc: dict, where: str) -> bool:
        same = [k for k in doc.get("keys") or [] if int.from_bytes(_unb64(k["n"]), "big") == n]
        if not same and kid and any(k.get("kid") == kid for k in doc.get("keys") or []):
            raise ValueError(f"{where} names the key id {kid} with another key than the one that signed the token: the key or the list was changed")
        return bool(same)
    signed, copy, unchecked = [], [], []
    now = live(issuer) if live is not None else None
    served = now is not None and held(now, f"the list {issuer} serves now")
    if now is not None and served:
        signed.append(f"the signing key (id {kid}) is in the list of keys {issuer} serves now at {now['url']}")
    elif now is not None:
        copy.append(f"{issuer} no longer serves the signing key (id {kid}): an issuer's keys rotate out. The archived list is used instead")
    raw = files.get("keys.json")
    if raw is None:
        if not served:
            unchecked.append(f"that the signing key is one {issuer} published: this bundle archives no list of its keys" + ("" if now is not None else
                             ", and the issuer was not asked or could not be reached"))
        return signed, copy, unchecked
    try:
        doc = json.loads(raw)
        shaped = doc["type"] == PUBLISHED_KEYS and doc["issuer"] == issuer and type(doc["retrieved_at"]) is int and raw == _json(doc)
        there = shaped and held(doc, "keys.json")
    except ValueError:
        raise
    except Exception:  # noqa: BLE001
        shaped = there = False
    if not shaped:
        raise ValueError("keys.json is not the archived list of this issuer's published keys in canonical form")
    if there:
        copy.append(f"the signing key (id {kid}) is in the list of keys {issuer} published at {doc['url']}, as archived in keys.json when it was "
                    f"retrieved on {_utc(doc['retrieved_at'])}" + ("" if now is not None else " (archived copy: the issuer was not asked or could not be reached)"))
    elif not served:
        unchecked.append(f"that the signing key is one {issuer} published: it is not in the list archived on {_utc(doc['retrieved_at'])} (the bundle was made after "
                         "the key rotated out) and the issuer does not serve it now. What says it is the issuer's is the verifier's key account, in the archived chain record")
    return signed, copy, unchecked


def _funding_as_archived(r: dict, arch: dict) -> str | None:
    """Compare the fifth part of a version 3 receipt with what the archived funding transaction logged. None when the
    archive has no funding transaction; raises ValueError when they differ."""
    from . import records
    c, f = r["commercial_authorisation"], arch.get("funding")
    if not f:
        return None
    ev = next((e for e in records.events_of(f["transaction"]) if e["event"] == "order_funded" and e.get("order") == r["order"]), None)
    if c["funded"] != f["signature"] or ev is None:
        raise ValueError("chain.json's funding transaction is not the one the receipt names, or it did not fund this order")
    by, source = int(ev.get("by") or 0), str(ev.get("source", ""))
    passkey = next((line.split("wallet=")[1].split()[0] for line in (f["transaction"].get("meta") or {}).get("logMessages") or []
                    if "knosp:funded " in line and f"order={r['order']}" in line), None)
    if (c["funder"]["github_id"] or 0) != by or c["source"]["address"] != (passkey or source) or (c["source"]["kind"] == "passkey") != bool(passkey):
        raise ValueError("the funder or the source of the money in the receipt is not what the archived funding transaction logged: the receipt or the archive was changed")
    return (f"the archived funding transaction {f['signature']} (slot {f['slot']}) logged this funder and this source of the money; the limit, the funder's "
            "role and billed_before are the receipt's word, from the escrow's history when the receipt was built")


def verify_offline(blob: bytes, live=None, mirror: str = "") -> tuple[dict, dict[str, list[str]], list[str]]:
    """The check for when the chain is gone: (the receipt, {"signatures": [...], "archive": [...], "unchecked": [...]},
    the assurance lines). No cluster is asked. "signatures": what a signature or a hash inside a signed token
    proves. "archive": what rests on an unsigned copy in the bundle (the check conclusions as fetched, the chain
    record as fetched, the issuer's published keys as fetched). "unchecked": what only a cluster can show.
    `live(issuer)`: the issuer's key list now (`published_keys`), or None for no network; `mirror`: as `verify`.
    Raises ValueError with the first thing that does not hold, naming the file."""
    from . import records
    r, files, n, classed, said = _core(blob)
    out: dict[str, list[str]] = {SIGNED: [line for c, line in classed if c == SIGNED], COPY: [line for c, line in classed if c == COPY], "unchecked": []}
    out[SIGNED].append("the verdict itself is the issuer's signature: the pinned workflow asks for this token only after it accepted, for this order and artifact")
    more = _key_identity(files, r["issuer_authenticated"]["issuer"], live)
    for name, lines in zip((SIGNED, COPY, "unchecked"), more):
        out[name] += lines
    raw = files.get("chain.json")
    if raw is None:
        out["unchecked"].append("the wallets paid, the amounts, the fee and the tip: they are the receipt's word, and this bundle holds no archived copy of the "
                                "chain record (it was made before bundles archived one)")
    else:
        try:
            arch = json.loads(raw)
            pay_tx, x = arch["payment"], r["transaction"]
            shaped = arch["type"] == CHAIN_ARCHIVE and raw == _json(arch) and isinstance(pay_tx["transaction"], dict)
        except Exception:  # noqa: BLE001
            shaped = False
        if not shaped:
            raise ValueError("chain.json is not an archived chain record in canonical form")
        inner = pay_tx["transaction"]
        if (pay_tx["signature"], pay_tx["slot"], pay_tx["block_time"]) != (x["signature"], x["slot"], x["time"]) or (inner.get("slot") or 0, inner.get("blockTime") or 0) != (
                x["slot"], x["time"]):
            raise ValueError("chain.json's paying transaction is not the one the receipt names (its signature, slot or time differs)")
        if arch.get("cluster") != r["cluster"]:
            raise ValueError("chain.json was fetched from another cluster than the receipt names")
        call = _archived_call(arch)
        try:
            _key_on_record(r, n, call, "archived ")
            _paid_as_recorded(r, call)
        except ValueError as why:
            raise ValueError(f"chain.json: {str(why).replace('the cluster no longer has', 'the archive does not hold').replace(chr(10), ' ')}") from None
        where = f"slot {pay_tx['slot']}, blockhash {pay_tx.get('blockhash') or 'not given by the cluster'}, fetched from {arch['cluster']}"
        out[COPY].append(f"the archived copy of the paying transaction {x['signature']} ({where}) logged these wallets paid these amounts, this fee and this tip")
        out[COPY].append("the archived copy of the verifier's key account held this key, not revoked, when it was fetched")
        v = arch.get("verified")
        if not v or v["signature"] != r["issuer_authenticated"]["verified"]["transaction"]:
            raise ValueError("chain.json's verifying transaction is not the one the receipt names")
        if r["version"] >= 3:
            line = _funding_as_archived(r, arch)
            (out[COPY] if line else out["unchecked"]).append(line or "who funded and from what: the archive holds no funding transaction (it was older than the history read)")
        # the escrow's lines of the archived payment, again: nothing in it may name another order as paid
        if not any(e["event"] == "order_settled" and e.get("order") == r["order"] for e in records.events_of(inner)):
            raise ValueError("chain.json's paying transaction did not settle this order")
    if r["version"] == 2:
        out["unchecked"].append("who authorised the money and who controls the judge: a version 2 receipt does not record them")
    out["unchecked"] += NO_CLUSTER
    if mirror:
        if rc.digest(r) not in {rc.digest(h) for h in rc.mirror_find(mirror, r["transaction"]["signature"])}:
            raise ValueError(f"the mirror at {mirror} does not hold this receipt for the paying transaction: the receipt was changed, or the mirror never had it")
        out[COPY].append(f"the mirror at {mirror} holds the same receipt for the paying transaction")
    return r, out, said


HEADS = {SIGNED: "Verified from signatures (the issuer's key, and hashes inside the token it signed):",
         COPY: "Rest on an archived copy in the bundle, signed by nobody (as fetched when the bundle was made):",
         "unchecked": "Could not be checked without a cluster:"}


def offline_lines(out: dict[str, list[str]], said: list[str]) -> list[str]:
    """What `--no-chain` prints under the receipt: the three lists under their headings, then the assurance."""
    lines: list[str] = []
    for name in (SIGNED, COPY, "unchecked"):
        lines += [HEADS[name], *(f"  - {line}" for line in out[name] or ["nothing"]), ""]
    return [*lines, *said]


# ---- from the chain and the host -----------------------------------------------------------------------------------------------
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _unb58(text: str) -> bytes:
    n = 0
    for ch in text:
        n = n * 58 + _B58.index(ch)
    return b"\0" * (len(text) - len(text.lstrip("1"))) + n.to_bytes((n.bit_length() + 7) // 8, "big")


def _ixs(tx: dict, program: str) -> list[tuple[bytes, list[str]]]:
    """(data, account addresses) of each top-level instruction of `tx` sent to `program`."""
    message, loaded = tx["transaction"]["message"], (tx.get("meta") or {}).get("loadedAddresses") or {}
    keys = [k if isinstance(k, str) else k.get("pubkey") for k in message["accountKeys"]] + list(loaded.get("writable") or []) + list(loaded.get("readonly") or [])
    return [(_unb58(ix["data"]), [keys[i] for i in ix["accounts"]]) for ix in message["instructions"] if keys[ix["programIdIndex"]] == program]


def _tx(call, sig: str) -> dict:
    tx = call("getTransaction", [sig, {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 1}])
    if not tx:
        raise Unavailable(f"the cluster no longer has transaction {sig}")
    return tx


def token_of(call, account: str, program: str) -> tuple[str, str]:
    """(the raw token, the transaction that finished verifying it) from the transactions that wrote and stepped the
    knos_oidc token account `account`: the token is in their instruction data even after the account is closed."""
    sigs = [s["signature"] for s in call("getSignaturesForAddress", [account, {"limit": 200}]) or [] if s.get("err") is None]
    buf, total, stepped = {}, 0, ""
    for sig in reversed(sigs):
        for data, _ in _ixs(_tx(call, sig), program):
            if data[:1] == b"\x00" and len(data) > 37:
                total = int.from_bytes(data[33:35], "little")
                buf[int.from_bytes(data[35:37], "little")] = data[37:]
            elif data[:1] == b"\x01":
                stepped = sig
    raw = b"".join(buf[off] for off in sorted(buf))
    if not raw or len(raw) != total or not stepped:
        raise Unavailable(f"the cluster no longer has the transactions that wrote the token at {account}")
    return raw.decode("ascii"), stepped


def _slim(rows, keys: tuple, by: str):
    """What of a listing decides a verdict, in one order: the same for whoever fetches it once the checks are done."""
    if rows is None:
        return None
    out = [{**{k: r.get(k) for k in keys}, **({"app": {"id": (r.get("app") or {}).get("id")}} if "name" in keys else {})} for r in rows if isinstance(r, dict)]
    return sorted(out, key=lambda r: (str(r.get(by)), r.get("id") or 0))


def _copy(call, sig: str | None, tx: dict | None = None) -> dict | None:
    """One transaction as chain.json keeps it: as the cluster gave it, with its slot, its block's time and blockhash
    (None when the cluster does not give the block) and the recent blockhash the transaction itself named."""
    if not sig:
        return None
    try:
        tx = tx or _tx(call, sig)
    except Exception:  # noqa: BLE001 - older than the cluster keeps: the archive says it has none
        return None
    try:
        block = call("getBlock", [tx.get("slot") or 0, {"transactionDetails": "none", "rewards": False, "commitment": "confirmed", "maxSupportedTransactionVersion": 1}])
    except Exception:  # noqa: BLE001 - a cluster that does not serve blocks: the slot is kept, the blockhash is not
        block = None
    return {"signature": sig, "slot": tx.get("slot") or 0, "block_time": tx.get("blockTime") or 0, "blockhash": (block or {}).get("blockhash"),
            "recent_blockhash": ((tx.get("transaction") or {}).get("message") or {}).get("recentBlockhash"), "transaction": tx}


def _u64s(data: bytes, at: int, count: int) -> list[int]:
    return [int.from_bytes(data[at + 8 * k:at + 8 * k + 8], "little") for k in range(count)]


def _authorised(call, events: list[dict], o: dict, sig: str, pr: int, funding: dict | None) -> dict:
    """The fifth part of the receipt of the payment `sig` of order `o`: who funded, from what, under which limit, in
    which role, and whether this order and milestone were paid before. From the escrow's history and the funding
    transaction; a Balance's limits are the ones its log shows at the funding (its opening's cap, and the side
    account's daily and total limits and allow-list as last set before it)."""
    from . import records
    from .settle.v2 import oidc
    from .settle.v2 import pay as pay2
    logs = ((funding or {}).get("meta") or {}).get("logMessages") or []
    passkey = next((line.split("wallet=")[1].split()[0] for line in logs if "knosp:funded " in line and f"order={o['order']}" in line), None)
    milestone = pr if o["standing"] else 0
    earlier = []
    for row in o["payments"]:
        if row["tx"] == sig:
            break
        if row["kind"] == "paid" and (not o["standing"] or row["pr"] == pr):
            earlier.append(row["tx"])
    common = dict(order=o["order"], milestone=milestone, funded_tx=o["tx"], billed_before=earlier[0] if earlier else None)
    if passkey or not o["from_balance"]:
        return rc.authorisation(source="passkey" if passkey else "wallet", address=passkey or o["source"], wallet=passkey or o["source"], **common)
    start = next(i for i, e in enumerate(events) if e.get("tx") == o["tx"])
    opened = side = None
    for e in events[:start]:
        if e["event"] == "balance" and e["v"] == 2 and records._address(lambda e=e: pay2.balance_pda(e["owner"], records._key(e["authority"]), records._key(e["mint"]))) == o["source"]:
            opened = e
        elif e["event"] == "balancex" and str(e.get("balance")) == o["source"]:
            side = e
    owner, cap, repos = o["owner"], 0, []
    try:
        if opened:      # OpenBalance: 0x00, the owner's id, the cap, four spenders
            cap = next(_u64s(d, 9, 1)[0] for d, _ in _ixs(_tx(call, opened["tx"]), str(pay2.PAY_ID)) if d[:1] == b"\x00" and len(d) >= 17)
        if side:        # SetBalanceX: 0x0d, the daily and total limits, eight repository ids
            repos = next([x for x in _u64s(d, 17, 8) if x] for d, _ in _ixs(_tx(call, side["tx"]), str(pay2.PAY_ID)) if d[:1] == b"\x0d" and len(d) >= 81)
    except (StopIteration, Unavailable):
        opened = None       # the transactions that set the limits are gone: the receipt says the records do not have them
    if not owner:           # the Balance was opened before the history read: its account still names its owner
        try:
            held = pay2.read_balance(base64.b64decode(((call("getAccountInfo", [o["source"], {"encoding": "base64"}]) or {}).get("value") or {})["data"][0]))
            owner = held.owner_id if held else 0
        except Exception:  # noqa: BLE001
            owner = 0
    if not owner or not o["by"]:
        raise ValueError(f"the Balance {o['source']} that funded this order was opened before the history read, and its account is gone: read more of the "
                         "history (--limit) to build the receipt's fifth part")
    login = None
    try:                    # the login is in the funding token, which the verifier's transactions still carry
        tok = next(keys[1] for d, keys in _ixs(funding or {}, str(pay2.PAY_ID)) if d[:1] == b"\x10")
        claims = json.loads(_unb64(token_of(call, tok, str(oidc.OIDC_ID))[0].split(".")[1]))
        login = str(claims["actor"]) if str(claims.get("actor_id")) == str(o["by"]) and claims.get("actor") else None
    except Exception:  # noqa: BLE001 - the token's transactions are gone: the id is what the chain logged, the login is left out
        login = None
    return rc.authorisation(source="balance", address=o["source"], owner_id=owner, funder_id=o["by"], login=login, cap=cap, daily=int((side or {}).get("day") or 0),
                            total=int((side or {}).get("total") or 0), repositories=repos, limits_known=opened is not None, **common)


def _quorum_before(call, events: list[dict], o: dict, sig: str, start: int, end: int, paying: str, buyers, sellers) -> list[dict]:
    """The judges of a quorum that passed before the one whose token paid, oldest first, each from its own token."""
    from .settle.v2 import oidc
    from .settle.v2 import pay as pay2
    out: dict[str, dict] = {}
    for e in events[start:end]:
        if e["event"] != "order_quorum" or e.get("order") != o["order"] or e.get("tx") == sig or e.get("judge") not in (0, 1, 2) or rc.JUDGES[e["judge"]] == paying:
            continue
        keys = next((keys for d, keys in _ixs(_tx(call, e["tx"]), str(pay2.PAY_ID)) if d[:1] == b"\x11"), None)
        if keys is None:
            continue
        claims = json.loads(_unb64(token_of(call, keys[1], str(oidc.OIDC_ID))[0].split(".")[1]))
        out.pop(rc.JUDGES[e["judge"]], None)        # a kind that spoke again: its last word, in its place
        out[rc.JUDGES[e["judge"]]] = rc.evaluator(rc.JUDGES[e["judge"]], claims, buyers, sellers)
    return list(out.values())


def reexecution_of(text: str, order: str, commit: str, pull: int) -> dict:
    """What a receipt records of the verdict a judge's run handed on (`receipt.reexecution`), from the comment that
    carries it (its `knos-verdict: ` line), the line's JSON, or the run's verdict.json. It is read as what it is,
    text from a job that ran a stranger's code (knos.flow._rerun_read), and a verdict of a suite that was run must be
    a passed one of this order, pull request and commit. Raises ValueError in words otherwise."""
    from . import flow
    line = next((ln[len(flow.VERDICT):] for ln in text.splitlines() if ln.startswith(flow.VERDICT)), text).strip()
    v = flow._rerun_read(line)
    if isinstance(v, str):
        raise ValueError(v)
    if v["reexecuted"] and (v["order"], v["head"], v["pull"]) != (order, commit, pull):
        raise ValueError("the re-execution's verdict is of another order, pull request or commit than this payment's")
    if v["reexecuted"] and not v["passed"]:
        raise ValueError("the re-execution's verdict says the suite did not pass: no payment follows from it")
    return rc.reexecution(v)


def _verdict_beside(get, claims: dict, order: str, commit: str, pull: int) -> dict | None:
    """The verdict the paying judge's run posted beside its token (a comment on the "knos tokens" issue of the
    repository the run was in), as `reexecution_of` reads it; None when the host does not show one for that run.
    Never raises: the comment is a record, not a condition, and anyone who can write that issue can delete it."""
    import time

    from . import flow
    try:
        here = str(claims["repository"])
        issue = next(i["number"] for i in get(f"repos/{here}/issues?state=open&per_page=100") if i.get("title") == flow.TOKENS and "pull_request" not in i)
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(claims["iat"]) - 3600))
        for c in get(f"repos/{here}/issues/{issue}/comments?since={since}&per_page=100"):
            if not str(c.get("body") or "").startswith(flow.VERDICT):
                continue
            try:
                got = reexecution_of(str(c["body"]), order, commit, pull)
            except ValueError:
                continue
            if got["environment"].get("github_run_id") == str(claims["run_id"]) and got["environment"].get("github_repository_id") == str(claims["repository_id"]):
                return got
    except Exception:  # noqa: BLE001 - no issue, no comment, a host that does not answer: the receipt says nothing of it
        return None
    return None


def gather(call, events: list[dict], target: str, get, published=None, verdict: str | None = None) -> tuple[dict, dict[str, bytes]]:
    """(the receipt, the bundle's files) for the order or paying transaction `target`. `call(method, params)` is the
    cluster, `events` the escrow's history (records.history), `get(path)` the host's API. `published(issuer)`: the
    issuer's key list as `published_keys` gives it, archived as keys.json (None: no list is archived). `verdict`: the
    verdict the paying judge's run handed on (its `knos-verdict:` comment or verdict.json), for a judge outside the
    order's repository; without it the host is asked for the comment that run posted beside its token, and with no
    host, or none found, the receipt says nothing of how the judge ran (it is then the chain's facts alone). Raises
    Unavailable when the chain no longer holds what is needed, ValueError (in words) for an order no receipt is
    built for here."""
    from . import records
    from .settle.v2 import oidc
    from .settle.v2 import pay as pay2
    orders, _ = records.orders_of(events)
    hit = next(((o, row["tx"]) for o in reversed(orders) for row in o["payments"]
                if row["kind"] == "paid" and (row["tx"] == target or (o["order"] == target and row["tx"] == o.get("paid_tx")))), None)
    if hit is None:
        bounty = next((j for j in records.jobs_of(events)[0] if j["state"] == "paid" and target in (j["paid_tx"], j["address"])), None)
        if bounty is not None:
            raise ValueError(f"{target} is the payment of an issue's bounty (repository id {bounty['repo']}, issue {bounty['issue']}), not of a "
                             "work order: a receipt and its bundle are built from a work order's payment, whose token names the order, its "
                             "terms and the commit (docs/RECEIPT.md)")
        raise Unavailable(f"the escrow's history on this cluster shows no payment of {target}")
    o, sig = hit
    if o["private"] or not o["terms"]:
        raise ValueError("this is a private order: its terms and repository are not public, so no public receipt is built for it")
    tx = _tx(call, sig)
    mine = [e for e in records.events_of(tx) if e.get("order") == o["order"]]
    settled = next((e for e in mine if e["event"] == "order_settled"), None)
    spent = next((keys for data, keys in _ixs(tx, str(pay2.PAY_ID)) if data[:1] == b"\x11"), None)
    if settled is None or spent is None or settled.get("judge") not in (0, 1, 2, 3):
        raise ValueError(f"transaction {sig} is not a payment a judge's token made (a release after a warranty has no token of its own)")
    token, verified_tx = token_of(call, spent[1], str(oidc.OIDC_ID))
    claims = json.loads(_unb64(token.split(".")[1]))
    aud = str(claims.get("aud", "")).split(":")
    if aud[:2] != ["knos3", "pay"] or len(aud) != 8:
        raise ValueError("this payment was made by a ruling, which names no commit: no receipt is built for it here")
    shares = {i: bps for i, bps, _ in pay2.payees_of(claims["aud"])}
    terms = tm.parse(o["terms"])
    start = next(i for i, e in enumerate(events) if e.get("tx") == o["tx"])
    end = next(i for i, e in enumerate(events) if e.get("tx") == sig)
    kinds = {"order_topup": "topup", "order_assigned": "assign", "order_reserved": "reserve", "order_cancelled": "cancel", "plan": "plan"}
    amend = [{"kind": kinds[e["event"]], "transaction": e["tx"], "time": e["at"],
              "detail": {k: v for k, v in e.items() if k not in ("event", "v", "at", "signer", "keys", "tx", "order")}}
             for e in events[start:end] if e["event"] in kinds and (e.get("order") == o["order"] or (e["event"] == "plan" and e.get("owner") == o["owner"]))]
    mint = o["mint"] or spent[9]        # the order's mint: pay_order_ix's tenth account
    info = (call("getAccountInfo", [mint, {"encoding": "base64"}]) or {}).get("value")
    if not info:
        raise Unavailable(f"the cluster no longer has the mint {mint}")
    key_info = (call("getAccountInfo", [spent[2], {"encoding": "base64"}]) or {}).get("value")
    if not key_info:
        raise Unavailable(f"the cluster no longer has the key account {spent[2]}")
    kdata = base64.b64decode(key_info["data"][0])
    key = oidc.read_key(kdata)
    if key is None:
        raise ValueError(f"the account {spent[2]} is not a key account of the verifier")
    size = key.bits // 8
    limbs, issuer = kdata[oidc.K_HDR:oidc.K_HDR + size], _issuer_number(claims["iss"])
    n = next((v for v in (int.from_bytes(limbs, "big"), int.from_bytes(limbs, "little")) if str(oidc.key_pda(issuer, v)) == spent[2]), None)
    if n is None:
        raise ValueError(f"the key account {spent[2]} is not this issuer's key by number or by URL (a private key): no public receipt is built for it")
    r = rc.build2(cluster=GENESIS.get(call("getGenesisHash", []), "localnet"), program=str(pay2.PAY_ID), order=o["order"],
                  scope=pay2.scope_of(o["repo"], o["issue"]).hex(), repository={"id": o["repo"], "issue": o["issue"]}, commit=aud[3], pull_request=int(aud[6]),
                  terms_hash=aud[4], mode=rc.MODES[int(aud[5])], judge_kind=rc.JUDGES[settled["judge"]], issuer=claims["iss"], claims=claims,
                  token_sha256=_sha(_unb64(token.rsplit(".", 1)[1])), key=spent[2], oidc_program=str(oidc.OIDC_ID), verified_tx=verified_tx,
                  checks=sorted({c["name"] for c in terms["checks"]}), allowed_paths=terms["paths"], denied_paths=terms["deny"], policy_version=terms["v"],
                  amendments=amend, payees=[{"github_id": e["payee"], "bps": shares[e["payee"]], "amount": e["amount"], "to": str(e["to"])}
                                            for e in mine if e["event"] == "order_paid"],
                  mint=mint, decimals=base64.b64decode(info["data"][0])[44], paid=settled["paid"], of=settled["of"], fee=settled["fee"], tip=settled["tip"],
                  signature=sig, slot=tx.get("slot") or 0, time=tx.get("blockTime") or 0)
    try:
        funding = _tx(call, o["tx"]) if o["tx"] else None
    except Unavailable:
        funding = None
    part = _authorised(call, events, o, sig, int(aud[6]), funding)
    rerun = None
    if settled["judge"] != 0 and rc.PROVIDERS.get(claims["iss"], "github") == "github":
        rerun = reexecution_of(verdict, o["order"], aud[3], int(aud[6])) if verdict is not None else \
            _verdict_beside(get, claims, o["order"], aud[3], int(aud[6])) if get is not None else None
    elif verdict is not None:
        raise ValueError("a re-execution is recorded for a judge outside the order's repository, run on GitHub: this payment's judge was not one")
    r = rc.build4(rc.build3(r, part, _quorum_before(call, events, o, sig, start, end, rc.JUDGES[settled["judge"]],
                                                    (part["funder"]["github_id"], part["source"]["owner_id"]), list(shares)), rerun))
    genesis = call("getGenesisHash", [])
    archive = {"type": CHAIN_ARCHIVE, "version": 1, "cluster": r["cluster"], "genesis": genesis, "payment": _copy(call, sig, tx),
               "funding": _copy(call, o["tx"], funding) if funding else None, "verified": _copy(call, verified_tx),
               "key_account": {"address": spent[2], "owner": key_info.get("owner"), "data": key_info["data"][0]}}
    files = {"chain.json": _json(archive),"receipt.json": _json(r), "token.jwt": token.encode() + b"\n", "terms.json": o["terms"].encode(),
             "key.json": _json({"issuer": claims["iss"], "kid": json.loads(_unb64(token.split(".")[0])).get("kid", ""), "n": _b64(n.to_bytes(size, "big")),
                                "e": "AQAB", "account": spent[2]})}
    listed = published(claims["iss"]) if published is not None else None
    if listed:
        files["keys.json"] = _json(listed)
    if get is not None:
        name = (get(f"repositories/{o['repo']}") or {}).get("full_name")
        runs, statuses = tm.head_checks(name, aud[3], get) if name else (None, None)
        files["checks.json"] = _json({"commit": aud[3], "check_runs": _slim(runs, _RUN_KEYS, "name"), "statuses": _slim(statuses, _STATUS_KEYS, "context"),
                                      "changed_files": tm.pull_files(name, int(aud[6]), get) if name else None})
        files["judge.json"] = _json({"kind": r["evaluator_observed"]["judge"]["kind"], "version": r["evaluator_observed"]["judge"]["version"],
                                     "inputs_sha256": _sha(files["checks.json"])})
    return r, files


def receipts_of(call, events: list[dict]) -> tuple[list[dict], list[str]]:
    """(every receipt the chain still gives, what was left out and why) for the payments in `events`: what
    `knos receipt mirror` writes. No host is asked: a receipt is chain facts only."""
    from . import records
    out, left = [], []
    for o in records.orders_of(events)[0]:
        for sig in dict.fromkeys(row["tx"] for row in o["payments"] if row["kind"] == "paid"):
            try:
                out.append(gather(call, events, sig, None)[0])
            except (Unavailable, ValueError) as why:
                left.append(f"{o['order']} ({sig}): {why}")
    return out, left


# ---- the commands -------------------------------------------------------------------------------------------------------------
def _caller(rpc: str):
    import os

    from . import chain
    url = rpc or os.environ.get("KNOS_RPC") or chain.CLUSTERS["devnet"]
    return url, lambda method, params: chain.call(url, method, params, timeout=30)


def _history(url: str, limit: int) -> list[dict]:
    from . import records
    from .settle.v2 import pay as pay2
    events, unread, _ = records.history(url, pay2.PAY_ID, limit)
    if unread:
        raise OSError(f"{unread} transactions could not be read (the public RPC throttled); try again, or give --rpc")
    return events


def _show(r: dict, echo) -> None:
    for line in rc.render(r):
        echo(line)


def register(app, help_lines: list | None = None) -> None:
    """Add `knos bundle make|verify`, and put `knos receipt` (check a file, `mirror`, `verify`) in place of the
    command that only checked a file: `knos receipt <file>` does what it did, and prints the five parts first.
    `help_lines`: the CLI's (name, panel, summary) list; `bundle` gets its line after `receipt`, in the same panel."""
    help_lines = help_lines if help_lines is not None else []
    at = next((i for i, row in enumerate(help_lines) if row[0] == "receipt"), None)
    if at is not None:
        help_lines[at] = ("receipt", help_lines[at][1], "Check an acceptance receipt and print its five parts; `mirror` and `verify` keep and read copies off chain.")
        help_lines.insert(at + 1, ("bundle", help_lines[at][1], "The evidence bundle of a payment: make it, and re-derive the verdict from it offline."))
        if not any(row[0] == "judge" for row in help_lines):       # `knos judge rerun <bundle>` reads what `knos bundle make --verdict` writes
            help_lines.insert(at + 2, ("judge", help_lines[at][1], "`judge rerun`: run a bounty's judge again on the same artifact, from a verdict file or a bundle."))
    import sys

    import importlib
    typer = importlib.import_module("typer")       # the command line's package, named here and not imported: the relay reaches this module on an install without it

    def stop(words: str, code: int = 1):
        typer.echo(words, err=True)
        raise typer.Exit(code)

    app.registered_commands[:] = [c for c in app.registered_commands if (c.name or getattr(c.callback, "__name__", "")) != "receipt"]

    @app.command("receipt")
    def receipt_cmd(what: str = typer.Argument(..., help="a receipt file (- reads standard input), or `mirror`, or `verify`"),
                    target: str = typer.Argument("", help="for verify: an order's address or a paying transaction's signature"),
                    out_dir: Path = typer.Option(None, "--out", help="for mirror: the folder to write (a GitHub Pages branch, a bucket)"),
                    mirror: str = typer.Option("", "--mirror", help="for verify: a mirror's folder or https URL, read when the chain has no record"),
                    rpc: str = typer.Option("", "--rpc", help="the cluster's JSON-RPC URL (default: KNOS_RPC, then devnet)"),
                    limit: int = typer.Option(1000, "--limit", help="how many of the escrow's newest transactions to read"),
                    no_attest: bool = typer.Option(False, "--no-attest", help="for mirror: do not write new receipts as Solana Attestation Service attestations"),
                    no_chain: bool = typer.Option(False, "--no-chain", help="for verify: ask no cluster. TARGET is a bundle file, or an order or transaction read from --mirror"),
                    no_network: bool = typer.Option(False, "--no-network", help="with --no-chain: do not ask the issuer for its key list either")) -> None:
        """Check an acceptance receipt file and print its five parts and digest; `knos receipt mirror --out DIR` writes every
        receipt the chain shows as files any static host can serve; `knos receipt verify ORDER --mirror DIR` rebuilds a receipt
        from the chain, or reads it from a mirror when the chain no longer has it."""
        if what == "mirror":
            if out_dir is None:
                stop("give the folder to write: knos receipt mirror --out DIR", 2)
            url, call = _caller(rpc)
            try:
                before = set(json.loads((out_dir / "index.json").read_text(encoding="utf-8"))["orders"]) if (out_dir / "index.json").is_file() else set()
                got, left = receipts_of(call, _history(url, limit))
                index = rc.mirror_write(got, out_dir)
            except (OSError, ValueError) as why:
                stop(f"the mirror was not written: {why}")
            for line in left:
                typer.echo(f"left out: {line}", err=True)
            typer.echo(f"{out_dir}: {sum(len(v) for v in index['orders'].values())} receipts of {len(index['orders'])} orders ({len(got)} from the chain now).")
            for r in (r for r in got if r["order"] not in before and not no_attest):        # after the files are written: nothing waits on it
                said = rc.attest(r, rpc=url)
                typer.echo(f"attestation of {r['order']}: {said['why']}", err=not said["attested"])
            return
        if what == "verify":
            if not target:
                stop("give the order's address or the paying transaction's signature: knos receipt verify ORDER [--mirror DIR]", 2)
            if no_chain:
                if Path(target).is_file():
                    return offline(Path(target), mirror, no_network)
                if not mirror:
                    stop("with --no-chain, give a bundle file (knos receipt verify --no-chain ORDER.bundle.tar), or --mirror DIR with the order's address.", 2)
                try:
                    held = rc.mirror_find(mirror, target)
                except ValueError as bad:
                    stop(str(bad))
                if not held:
                    stop(f"the mirror at {mirror} has no receipt for {target}, and no cluster was asked.")
                for r in held:
                    _show(r, typer.echo)
                    typer.echo(f"{rc.FROM_MIRROR}: no cluster was asked. The receipt keeps the rules of docs/RECEIPT.md and is the one the mirror's index lists; "
                               "its bundle (knos bundle verify --no-chain) is what proves the issuer's signature.")
                return
            url, call = _caller(rpc)
            try:
                r = gather(call, _history(url, limit), target, None)[0]
                held = rc.mirror_find(mirror, target) if mirror else []
                if held and rc.digest(r) not in {rc.digest(h) for h in held}:
                    stop("the mirror's receipt is not the one the chain gives: trust the chain's, printed by `knos receipt verify` without --mirror.")
                _show(r, typer.echo)
                typer.echo("from the chain" + (", and the mirror holds the same receipt" if held else ""))
            except ValueError as why:
                stop(str(why))
            except (Unavailable, OSError) as why:
                if not mirror:
                    stop(f"the chain record is unavailable ({why}). Give --mirror DIR or URL to read the receipt from a mirror.")
                try:
                    held = rc.mirror_find(mirror, target)
                except ValueError as bad:
                    stop(str(bad))
                if not held:
                    stop(f"neither the chain nor the mirror at {mirror} has a receipt for {target}.")
                for r in held:
                    _show(r, typer.echo)
                    typer.echo(rc.FROM_MIRROR)
            return
        try:
            doc = json.loads(sys.stdin.read() if what == "-" else open(what, encoding="utf-8").read())
        except (OSError, ValueError) as e:
            stop(f"not a receipt: {e}", 2)
        wrong = rc.check(doc)
        if wrong:
            stop(f"not a valid receipt: {wrong}")
        _show(doc, typer.echo)
        pays = "it authorises payment" if rc.authorises_payment(doc) else "it authorises no payment"
        typer.echo(f"valid. verdict: {rc.verdict_of(doc).replace('_', ' ')}; {pays}. digest sha256:{rc.digest(doc)}")

    def offline(path: Path, mirror: str, no_network: bool) -> None:
        """`--no-chain`: the bundle alone, and the issuer's key list when the network is there."""
        try:
            blob = path.read_bytes()
            r, out, said = verify_offline(blob, None if no_network else published_keys, mirror)
        except (OSError, ValueError) as why:
            stop(f"not verified: {why}")
        _show(r, typer.echo)
        typer.echo("")
        for line in offline_lines(out, said):
            typer.echo(line)
        typer.echo(f"verified with no cluster. bundle sha256:{_sha(blob)}")

    bundle = typer.Typer(help="The evidence bundle of a payment: one .tar the buyer and the seller both hold, checked with no network.", no_args_is_help=True)
    app.add_typer(bundle, name="bundle")

    @bundle.command("make")
    def make_cmd(target: str = typer.Argument(..., help="an order's address or a paying transaction's signature"),
                 out_file: Path = typer.Option(None, "--out", help="where to write the .tar (default: <order>.bundle.tar)"),
                 rpc: str = typer.Option("", "--rpc", help="the cluster's JSON-RPC URL (default: KNOS_RPC, then devnet)"),
                 limit: int = typer.Option(1000, "--limit", help="how many of the escrow's newest transactions to read"),
                 verdict: Path = typer.Option(None, "--verdict", help="tests mode: the judge's verdict file (knos proof judge --evidence), kept as verdict.json"),
                 rerun: Path = typer.Option(None, "--reexecution", help="a neutral judge's own verdict (the `knos-verdict:` line of its comment, or its run's verdict.json): "
                                                                        "recorded in the receipt's entry for that judge. Without it, the comment is looked for")) -> None:
        """Write the evidence bundle of one payment: the receipt, the signed token, the key that verified it, the terms, the
        judge's version and inputs digest, the check conclusions as fetched, the judge's verdict when --verdict gives it, and a
        manifest. The same order gives the same bytes."""
        judge = importlib.import_module("knos.judge")       # named, not imported: `gather` is reached by the relay, and the judge is the command's alone
        url, call = _caller(rpc)
        try:
            r, files = gather(call, _history(url, limit), target, judge.github, published_keys,
                              rerun.read_text(encoding="utf-8") if rerun is not None else None)
            if verdict is not None:
                files["verdict.json"] = _json(judge.load_verdict(verdict)[0])
            blob = make(files, r["order"])
            verify(blob)        # a bundle that would not verify is never handed out
        except (Unavailable, OSError, ValueError) as why:
            stop(f"no bundle was written: {why}")
        path = out_file or Path(f"{r['order']}.bundle.tar")
        path.write_bytes(blob)
        typer.echo(f"{path}: {len(blob)} bytes, sha256:{_sha(blob)}. Check it anywhere with: knos bundle verify {path}")

    @bundle.command("verify")
    def verify_cmd(path: Path = typer.Argument(..., help="a bundle written by `knos bundle make`"),
                   rpc: str = typer.Option("", "--rpc", help="also read the key's account and the paying transaction on this cluster (without it, no network is used)"),
                   mirror: str = typer.Option("", "--mirror", help="also compare the receipt with the one this mirror (a folder or https URL) holds"),
                   no_chain: bool = typer.Option(False, "--no-chain", help="the cluster is gone or reset: check what signatures prove, what rests on the bundle's archived "
                                                                           "copy of the chain record, and say what only a cluster could show"),
                   no_network: bool = typer.Option(False, "--no-network", help="with --no-chain: do not ask the issuer for its key list either")) -> None:
        """Re-derive a payment's verdict from the bundle alone and print the receipt's five parts, the judge's assurance, and
        what an offline check cannot show. With --no-chain it also reads the bundle's archived copy of the chain record and
        sorts every statement: verified from signatures, resting on an archived copy, or not checkable without a cluster."""
        if no_chain:
            if rpc:
                stop("--no-chain asks no cluster: leave --rpc out, or leave --no-chain out to compare with a cluster.", 2)
            return offline(path, mirror, no_network)
        try:
            r, done = verify(path.read_bytes(), _caller(rpc)[1] if rpc else None, mirror)
        except (OSError, ValueError) as why:
            stop(f"not verified: {why}")
        _show(r, typer.echo)
        typer.echo("")
        for line in done:
            typer.echo(line if line.startswith(("assurance: ", "limit: ")) else f"checked: {line}")
        typer.echo(f"verified. bundle sha256:{_sha(path.read_bytes())}")
