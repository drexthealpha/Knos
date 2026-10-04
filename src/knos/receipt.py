"""The acceptance receipt: one JSON document that says who signed what, about which artifact, under which terms, and
what was paid for it. It is derived from public facts only (the order, the judge's GitHub-signed token, the program's
log lines of the paying transaction), so anyone can rebuild it and compare digests. docs/RECEIPT.md is the
specification; docs/receipt/acceptance-receipt.v1.schema.json is the JSON Schema; docs/receipt/vectors.json holds the
conformance vectors.

`check` is the whole rule set (the schema's shape and the rules a schema cannot say: shares add up, amounts add up,
the judge matches the order). It needs no package."""
from __future__ import annotations

import hashlib
import json
import re

TYPE, VERSION = "knos.acceptance-receipt", 1
JUDGES = ("repository", "neutral", "attestor", "arbiter")     # the program's judge a, b, c, d (its log says 0, 1, 2, 3)
MODES = ("merge", "tests")
CLAIMS = ("actor_id", "event_name", "exp", "iat", "job_workflow_ref", "job_workflow_sha", "repository_id", "repository_owner_id", "run_attempt",
          "run_id", "runner_environment")
_HEX32, _HEX40, _ADDR, _SIG, _UNITS = (re.compile(p) for p in (r"^[0-9a-f]{64}$", r"^[0-9a-f]{40}$", r"^[1-9A-HJ-NP-Za-km-z]{32,44}$",
                                                              r"^[1-9A-HJ-NP-Za-km-z]{64,88}$", r"^(0|[1-9][0-9]{0,19})$"))


def canonical(receipt: dict) -> bytes:
    """The bytes a digest is taken over: keys sorted, no white space, UTF-8, no escaping of non-ASCII."""
    return json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(receipt: dict) -> str:
    return hashlib.sha256(canonical(receipt)).hexdigest()


def build(*, cluster: str, program: str, order: str, scope: str, repository: dict | None, commit: str, pull_request: int, terms_hash: str, mode: str,
          judge_kind: str, issuer: str, claims: dict, token_sha256: str, key: str, payees: list[dict], mint: str, decimals: int, paid: int, of: int,
          fee: int, tip: int, signature: str, slot: int, time: int) -> dict:
    """A receipt from its facts. `payees`: {github_id, bps, amount, to}; amounts are integers here and decimal strings in
    the document (a u64 does not fit a JSON number). `claims`: the judge's token's claims; only the ones a receipt keeps
    are copied."""
    r = {"type": TYPE, "version": VERSION, "cluster": cluster, "program": program, "order": order, "scope": scope, "repository": repository,
         "artifact": {"commit": commit, "pull_request": pull_request}, "terms": {"hash": terms_hash, "mode": mode},
         "judge": {"kind": judge_kind, "issuer": issuer, "claims": {k: str(claims[k]) if k not in ("iat", "exp") else int(claims[k]) for k in CLAIMS},
                   "token_sha256": token_sha256, "key": key},
         "payees": [{"github_id": p["github_id"], "bps": p["bps"], "amount": str(p["amount"]), "to": p["to"]} for p in payees],
         "amounts": {"mint": mint, "decimals": decimals, "paid": str(paid), "of": str(of), "fee": str(fee), "tip": str(tip)},
         "transaction": {"signature": signature, "slot": slot, "time": time}}
    why = check(r)
    if why:
        raise ValueError(why)
    return r


def check(r) -> str | None:
    """None when `r` is a valid version 1 receipt; otherwise the first reason it is not, in words."""
    def keys(obj, want, where):
        if not isinstance(obj, dict):
            return f"{where} is not an object"
        return None if set(obj) == set(want) else f"{where} has fields {sorted(set(obj) ^ set(want))} missing or unknown"
    def whole(v):
        return isinstance(v, int) and not isinstance(v, bool) and v >= 0
    why = keys(r, ("type", "version", "cluster", "program", "order", "scope", "repository", "artifact", "terms", "judge", "payees", "amounts",
                   "transaction"), "the receipt")
    if why:
        return why
    if r["type"] != TYPE or r["version"] != VERSION:
        return f"not a {TYPE} of version {VERSION}"
    if r["cluster"] not in ("devnet", "mainnet-beta", "localnet"):
        return "cluster is devnet, mainnet-beta or localnet"
    if not all(isinstance(r[k], str) and _ADDR.match(r[k]) for k in ("program", "order")) or not (isinstance(r["scope"], str) and _HEX32.match(r["scope"])):
        return "program and order are base58 addresses and scope is 64 lowercase hex characters"
    repo = r["repository"]
    if repo is not None and (keys(repo, ("id", "issue"), "repository") or not (whole(repo["id"]) and repo["id"] > 0 and whole(repo["issue"]))):
        return "repository is null (a private order) or {id, issue}, both whole numbers"
    if repo is not None and hashlib.sha256(b"knos3:scope" + repo["id"].to_bytes(8, "little") + repo["issue"].to_bytes(8, "little")).hexdigest() != r["scope"]:
        return "scope is not sha256(\"knos3:scope\" || repository id || issue) of the repository named"
    a, t, j, m, x = r["artifact"], r["terms"], r["judge"], r["amounts"], r["transaction"]
    why = (keys(a, ("commit", "pull_request"), "artifact") or keys(t, ("hash", "mode"), "terms")
           or keys(j, ("kind", "issuer", "claims", "token_sha256", "key"), "judge") or keys(j["claims"], CLAIMS, "judge.claims")
           or keys(m, ("mint", "decimals", "paid", "of", "fee", "tip"), "amounts") or keys(x, ("signature", "slot", "time"), "transaction"))
    if why:
        return why
    if not (isinstance(a["commit"], str) and _HEX40.match(a["commit"]) and whole(a["pull_request"])):
        return "artifact.commit is 40 lowercase hex characters and artifact.pull_request a whole number"
    if not (isinstance(t["hash"], str) and _HEX32.match(t["hash"])) or t["mode"] not in MODES:
        return "terms.hash is 64 lowercase hex characters and terms.mode is merge or tests"
    c = j["claims"]
    if j["kind"] not in JUDGES or not (isinstance(j["issuer"], str) and j["issuer"].startswith("https://")):
        return "judge.kind is repository, neutral, attestor or arbiter, and judge.issuer an https URL"
    if not all(isinstance(c[k], str) for k in CLAIMS if k not in ("iat", "exp")) or not (whole(c["iat"]) and whole(c["exp"]) and c["iat"] <= c["exp"]):
        return "judge.claims are strings as the issuer signed them, but iat and exp, which are numbers"
    if not (_HEX40.match(c["job_workflow_sha"]) and c["runner_environment"] == "github-hosted" and c["run_attempt"] == "1"):
        return "the judge's run is a first attempt on a GitHub-hosted runner of a workflow pinned by a 40-character commit"
    if not (isinstance(j["token_sha256"], str) and _HEX32.match(j["token_sha256"]) and isinstance(j["key"], str) and _ADDR.match(j["key"])):
        return "judge.token_sha256 is 64 lowercase hex characters and judge.key a base58 address"
    if j["kind"] == "repository" and (repo is None or c["repository_id"] != str(repo["id"])):
        return "a repository judge's run is in the order's own repository"
    if j["kind"] in ("neutral", "arbiter") and (c["repository_owner_id"] != c["actor_id"] or c["event_name"] != "workflow_dispatch"):
        return "a neutral judge's or an arbiter's run is started by hand in a repository its starter owns"
    if repo is None and j["kind"] != "attestor":
        return "a private order is judged by its attestor repository"
    p = r["payees"]
    if not isinstance(p, list) or not 1 <= len(p) <= 4:
        return "payees is a list of one to four"
    for e in p:
        if keys(e, ("github_id", "bps", "amount", "to"), "a payee") or not (whole(e["github_id"]) and e["github_id"] > 0 and whole(e["bps"]) and 1 <= e["bps"] <= 10_000
                                                                       and isinstance(e["amount"], str) and _UNITS.match(e["amount"])
                                                                       and isinstance(e["to"], str) and _ADDR.match(e["to"])):
            return "a payee is {github_id, bps 1..10000, amount as a decimal string, to as a base58 address}"
    if sum(e["bps"] for e in p) != 10_000:
        return "the payees' shares add up to 10000 basis points"
    if not (isinstance(m["mint"], str) and _ADDR.match(m["mint"]) and whole(m["decimals"]) and m["decimals"] <= 18
            and all(isinstance(m[k], str) and _UNITS.match(m[k]) for k in ("paid", "of", "fee", "tip"))):
        return "amounts are decimal strings in the mint's smallest units, with the mint's address and decimals"
    if sum(int(e["amount"]) for e in p) != int(m["paid"]) or int(m["paid"]) > int(m["of"]) or int(m["paid"]) == 0:
        return "what the payees received adds up to amounts.paid, which is more than zero and at most amounts.of"
    if not (isinstance(x["signature"], str) and _SIG.match(x["signature"]) and whole(x["slot"]) and whole(x["time"])):
        return "transaction is {signature in base58, slot, time}"
    if x["time"] < c["iat"]:
        return "the payment is not before the judge's token was issued"
    return None
