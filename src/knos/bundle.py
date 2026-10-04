"""The evidence bundle: one .tar that holds everything a payment's verdict was derived from, so the buyer and the
seller hold the same bytes and either can re-derive the verdict with no network.

    MANIFEST.json   {"type", "version", "order", "files": {name: sha256}}
    receipt.json    the acceptance receipt, version 2, in canonical form (docs/RECEIPT.md)
    token.jwt       the raw token the issuer signed, as it was written to knos_oidc
    key.json        the issuer's public key that verified it: {issuer, kid, n, e, account}
    terms.json      the order's terms, the bytes that were hashed at funding
    checks.json     the check runs, commit statuses and changed files of the accepted commit, as fetched
    judge.json      {kind, version, inputs_sha256}: who judged, at which commit of its workflow, over which checks.json
    verdict.json    optional, tests mode: the judge's verdict as `knos proof judge --evidence` wrote it: the hashes of the
                    two trees it ran on, the acceptance checks' hash, its assurance, and the image digest when it ran in
                    one. The trees themselves are not in the bundle: the receipt names the commit, and whoever runs
                    `knos judge rerun <bundle> --base DIR --pr DIR` checks them out and is told when they are not the same.

`make` is deterministic (names in order, times zero, one mode, no owner), so two builds of one order are the same
bytes. `verify` reads the tar alone: every file against the manifest, the token's signature against the included key,
the key against the address the receipt names (a derivation, no network), the claims and the audience against the
receipt, the terms against their hash, and the verdict again from the terms and the checks. With an RPC URL it also
reads the key's account on chain and the paying transaction: the wallets paid and the amounts are in no signed token,
so offline they are the receipt's word, and `verify` says so. `gather` builds the files from the chain and the host's API.

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
OPTIONAL = ("verdict.json",)       # a bundle of version 1 with or without it: one layout, read by `verify` and by `knos judge rerun`
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
    manifest = _json({"type": TYPE, "version": VERSION, "order": order, "files": {name: _sha(files[name]) for name in sorted(files)}})
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
        assert manifest["type"] == TYPE and manifest["version"] == VERSION and isinstance(listed, dict)
    except Exception:  # noqa: BLE001 - missing, not JSON, or not a manifest: one sentence either way
        raise ValueError("the bundle has no MANIFEST.json of a Knos evidence bundle, version 1") from None
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
    cluster behind `call`. Raises ValueError when they differ or the transaction is gone."""
    from . import records
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


def verify(blob: bytes, call=None, mirror: str = "") -> tuple[dict, list[str]]:
    """(the receipt, what was checked, one line each) for a bundle that holds together. Raises ValueError with the
    first thing that does not. Nothing is asked of any network unless `call(method, params)` (a cluster's JSON-RPC)
    is given: then the key's account and the paying transaction are read there too. `mirror` (a folder or URL): the
    receipt must be the one that mirror holds for the paying transaction. With neither, the last line is LIMIT."""
    from solders.pubkey import Pubkey

    from .settle.v2 import oidc
    files = read(blob)
    done = [f"every file is the one the manifest lists ({len(files)} files)"]
    try:
        r, key, judge, checks = (json.loads(files[name]) for name in ("receipt.json", "key.json", "judge.json", "checks.json"))
        token = files["token.jwt"].decode("ascii").strip()
        claims = json.loads(_unb64(token.split(".")[1]))
        n = int.from_bytes(_unb64(key["n"]), "big")
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"a file of the bundle cannot be read as what it is ({e})") from None
    why = rc.check(r)
    if why or r["version"] != 2 or files["receipt.json"] != _json(r):
        raise ValueError(f"receipt.json is not a valid version 2 receipt in canonical form{': ' + why if why else ''}")
    a, o, p = r["issuer_authenticated"], r["evaluator_observed"], r["policy"]
    # 1. what the issuer authenticated
    if key.get("e") != "AQAB" or not rs256(token, n):
        raise ValueError("the token's signature is not the included key's: the token or the key was changed")
    done.append("the token carries the RS256 signature of the included key")
    pinned = str(oidc.key_pda(_issuer_number(a["issuer"]), n, Pubkey.from_string(a["verified"]["program"])))
    if pinned != a["verified"]["key"] or key.get("account") != pinned or key.get("issuer") != a["issuer"] or claims.get("iss") != a["issuer"]:
        raise ValueError("the included key is not the one at the knos_oidc key account the receipt names")
    done.append(f"that key is the one knos_oidc holds at {pinned} (the address is derived from the key)")
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
    done.append("the token names this order, this commit, these terms and these payees")
    # 3. which policy (before 2: the verdict is derived from it)
    if _sha(files["terms.json"]) != p["terms_hash"]:
        raise ValueError("terms.json is not what was hashed at funding (its sha256 is not the receipt's terms hash)")
    try:
        terms = tm.parse(files["terms.json"])
    except tm.Refused as e:
        raise ValueError(f"terms.json is not a set of terms: {e}") from None
    if terms["mode"] != p["mode"] or terms["paths"] != p["allowed_paths"] or terms["deny"] != p["denied_paths"] or terms["v"] != p["version"]:
        raise ValueError("the policy in the receipt is not what terms.json says")
    done.append("terms.json is the terms fixed at funding (its sha256 is the terms hash)")
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
    done.append(f"the verdict follows again: {len(seen)} named checks passed at the commit and every changed file is within the allowed paths")
    said = _assurance(files, terms)
    if call is not None:
        got = (call("getAccountInfo", [pinned, {"encoding": "base64"}]) or {}).get("value")
        data = base64.b64decode(got["data"][0]) if got else b""
        k = oidc.read_key(data)
        if not got or got.get("owner") != a["verified"]["program"] or k is None or k.revoked or n.to_bytes(k.bits // 8, "big") not in (
                data[oidc.K_HDR:oidc.K_HDR + k.bits // 8], data[oidc.K_HDR:oidc.K_HDR + k.bits // 8][::-1]):
            raise ValueError(f"the chain's record of the key at {pinned} is missing, revoked or holds another key")
        done.append("the chain's key account holds this key and it is not revoked")
        done.append(_paid_as_recorded(r, call))
    else:
        done.append("the chain was not asked (give --rpc to compare the key with its account on chain)")
    if mirror:
        if rc.digest(r) not in {rc.digest(h) for h in rc.mirror_find(mirror, r["transaction"]["signature"])}:
            raise ValueError(f"the mirror at {mirror} does not hold this receipt for the paying transaction: the receipt was changed, or the mirror never had it")
        done.append(f"the mirror at {mirror} holds the same receipt for the paying transaction")
    return r, [*done, *said, *([] if call is not None or mirror else [LIMIT])]


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


def gather(call, events: list[dict], target: str, get) -> tuple[dict, dict[str, bytes]]:
    """(the receipt, the bundle's files) for the order or paying transaction `target`. `call(method, params)` is the
    cluster, `events` the escrow's history (records.history), `get(path)` the host's API. Raises Unavailable when the
    chain no longer holds what is needed, ValueError (in words) for an order no receipt is built for here."""
    from . import records
    from .settle.v2 import oidc
    from .settle.v2 import pay as pay2
    orders, _ = records.orders_of(events)
    hit = next(((o, row["tx"]) for o in reversed(orders) for row in o["payments"]
                if row["kind"] == "paid" and (row["tx"] == target or (o["order"] == target and row["tx"] == o.get("paid_tx")))), None)
    if hit is None:
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
    files = {"receipt.json": _json(r), "token.jwt": token.encode() + b"\n", "terms.json": o["terms"].encode(),
             "key.json": _json({"issuer": claims["iss"], "kid": json.loads(_unb64(token.split(".")[0])).get("kid", ""), "n": _b64(n.to_bytes(size, "big")),
                                "e": "AQAB", "account": spent[2]})}
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
    command that only checked a file: `knos receipt <file>` does what it did, and prints the four parts first.
    `help_lines`: the CLI's (name, panel, summary) list; `bundle` gets its line after `receipt`, in the same panel."""
    help_lines = help_lines if help_lines is not None else []
    at = next((i for i, row in enumerate(help_lines) if row[0] == "receipt"), None)
    if at is not None:
        help_lines[at] = ("receipt", help_lines[at][1], "Check an acceptance receipt and print its four parts; `mirror` and `verify` keep and read copies off chain.")
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
                    no_attest: bool = typer.Option(False, "--no-attest", help="for mirror: do not write new receipts as Solana Attestation Service attestations")) -> None:
        """Check an acceptance receipt file and print its four parts and digest; `knos receipt mirror --out DIR` writes every
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
        typer.echo(f"valid. digest sha256:{rc.digest(doc)}")

    bundle = typer.Typer(help="The evidence bundle of a payment: one .tar the buyer and the seller both hold, checked with no network.", no_args_is_help=True)
    app.add_typer(bundle, name="bundle")

    @bundle.command("make")
    def make_cmd(target: str = typer.Argument(..., help="an order's address or a paying transaction's signature"),
                 out_file: Path = typer.Option(None, "--out", help="where to write the .tar (default: <order>.bundle.tar)"),
                 rpc: str = typer.Option("", "--rpc", help="the cluster's JSON-RPC URL (default: KNOS_RPC, then devnet)"),
                 limit: int = typer.Option(1000, "--limit", help="how many of the escrow's newest transactions to read"),
                 verdict: Path = typer.Option(None, "--verdict", help="tests mode: the judge's verdict file (knos proof judge --evidence), kept as verdict.json")) -> None:
        """Write the evidence bundle of one payment: the receipt, the signed token, the key that verified it, the terms, the
        judge's version and inputs digest, the check conclusions as fetched, the judge's verdict when --verdict gives it, and a
        manifest. The same order gives the same bytes."""
        judge = importlib.import_module("knos.judge")       # named, not imported: `gather` is reached by the relay, and the judge is the command's alone
        url, call = _caller(rpc)
        try:
            r, files = gather(call, _history(url, limit), target, judge.github)
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
                   mirror: str = typer.Option("", "--mirror", help="also compare the receipt with the one this mirror (a folder or https URL) holds")) -> None:
        """Re-derive a payment's verdict from the bundle alone and print the receipt's four parts, the judge's assurance, and
        what an offline check cannot show."""
        try:
            r, done = verify(path.read_bytes(), _caller(rpc)[1] if rpc else None, mirror)
        except (OSError, ValueError) as why:
            stop(f"not verified: {why}")
        _show(r, typer.echo)
        typer.echo("")
        for line in done:
            typer.echo(line if line.startswith(("assurance: ", "limit: ")) else f"checked: {line}")
        typer.echo(f"verified. bundle sha256:{_sha(path.read_bytes())}")
