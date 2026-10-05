"""The acceptance receipt: one JSON document that says who signed what, about which artifact, under which terms, and
what was paid for it. It is derived from public facts only (the order, the judge's signed token, the program's
log lines of the paying transaction), so anyone can rebuild it and compare digests. docs/RECEIPT.md is the
specification; docs/receipt/acceptance-receipt.v2.schema.json (and v1) is the JSON Schema; docs/receipt/vectors.json
holds the conformance vectors.

Version 3 keeps five things apart, in this order: what the issuer authenticated, what the evaluator observed, which
policy produced the verdict, who authorised the money and under which limit, and what trust remains; it records who
controls each judge that spoke, and it lists every amendment of the order's terms with its transaction. Version 2 has
four of the parts (no commercial authorisation, no record of the judges' control) and version 1 none; both still
check (`check` reads all three), `upgrade` writes a version 1 receipt as version 2 and `build3` a version 2 one as 3.

`check` is the whole rule set (the schema's shape and the rules a schema cannot say: shares add up, amounts add up,
the judge matches the order). It needs no package. `render` is the receipt for a person, under the five headings.
`mirror_write` / `mirror_find` keep receipts off chain (devnet can be reset); `attest` writes one as a Solana
Attestation Service attestation and never raises."""
from __future__ import annotations

import hashlib
import json
import re

TYPE, VERSION = "knos.acceptance-receipt", 3          # `check` still reads versions 1 and 2
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
    r["version"] = 1            # this is the version 1 shape; `build2` and `upgrade` write version 2
    why = check(r)
    if why:
        raise ValueError(why)
    return r


def check(r) -> str | None:
    """None when `r` is a valid receipt of version 1, 2 or 3; otherwise the first reason it is not, in words."""
    if isinstance(r, dict) and r.get("type") == TYPE and (type(r.get("version")) is not int or r["version"] not in (1, 2, 3)):
        return f"not a {TYPE} of version 1, 2 or 3"
    if isinstance(r, dict) and r.get("type") == TYPE and r["version"] == 3:
        return _check3(r)
    return _check2(r) if isinstance(r, dict) and r.get("type") == TYPE and r["version"] == 2 else _check1(r)


def _check1(r) -> str | None:
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
    if r["type"] != TYPE or r["version"] != 1 or type(r["version"]) is not int:
        return f"not a {TYPE} of version 1, 2 or 3"
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


# ---- version 2: four parts, and the order's amendments ----------------------------------------------------------------
PROVIDERS = {"https://token.actions.githubusercontent.com": "github", "https://gitlab.com": "gitlab"}
# What GitLab signs for a pipeline (docs.gitlab.com/ci/secrets/id_token_authentication), as knos_pay reads it.
# `ref_type`, `ref_path` and `project_path` are read by the program (programs-v2/knos_pay/src/gl.rs): the pipeline ran on a
# branch, and `ci_config_ref_uri` is "gitlab.com/<project_path>//<file>@<ref_path>", a file of the token's own project.
GITLAB_CLAIMS = ("ci_config_ref_uri", "ci_config_sha", "exp", "iat", "namespace_id", "pipeline_id", "pipeline_source", "project_id", "project_path", "ref",
                 "ref_path", "ref_protected", "ref_type", "runner_environment", "sha", "user_id")
# gl.rs moves GitLab's three id spaces into ranges no GitHub id is read from: a project and a user are GL_ID + id, a
# namespace is GL_NS + id, and a raw id is 1..=GL_MAX. Those are the ids an order, its scope and its payees carry.
GL_NS, GL_ID, GL_MAX = 800_000_000_000_000_000, 900_000_000_000_000_000, 99_999_999_999_999_999
_GL_BASE = {"project_id": GL_ID, "user_id": GL_ID, "namespace_id": GL_NS}
_GL_RAW = re.compile(r"^[1-9][0-9]{0,16}$")
GITLAB_HOST = "gitlab.com/"


def gitlab_id(claim: str, raw) -> int | None:
    """The id the program reads from a GitLab token's `project_id`, `user_id` or `namespace_id` (gl.rs); None for a
    value it refuses."""
    return _GL_BASE[claim] + int(raw) if isinstance(raw, str) and _GL_RAW.match(raw) else None


# a GitLab claim -> the GitHub claim that says the same thing (the rules of version 1 are written in GitHub's words)
_AS_GITHUB = {"user_id": "actor_id", "pipeline_source": "event_name", "ci_config_ref_uri": "job_workflow_ref", "ci_config_sha": "job_workflow_sha",
              "project_id": "repository_id", "namespace_id": "repository_owner_id", "pipeline_id": "run_id"}
PARTS = ("issuer_authenticated", "evaluator_observed", "policy", "commercial_authorisation", "trust_remaining")       # in this order, everywhere
PARTS2 = tuple(k for k in PARTS if k != "commercial_authorisation")       # what a version 2 receipt has
HEADINGS = {"issuer_authenticated": "What the issuer authenticated", "evaluator_observed": "What the evaluator observed",
            "policy": "Which policy produced the verdict", "commercial_authorisation": "Who authorised the money, and under which limit",
            "trust_remaining": "What trust remains"}
AMENDMENTS = ("topup", "assign", "reserve", "cancel", "plan")
_KEYS2 = ("type", "version", "cluster", "program", "order", "scope", "repository", *PARTS2, "amendments", "payees", "amounts", "transaction")
_KEYS3 = ("type", "version", "cluster", "program", "order", "scope", "repository", *PARTS, "amendments", "payees", "amounts", "transaction")


def trust_of(provider: str, mode: str, kind: str) -> list[str]:
    """What a reader of this receipt still has to trust, in plain words. It follows from who signed, how the order
    was judged and by whom, so a receipt cannot leave one out: `check` compares."""
    host = {"github": "GitHub", "gitlab": "GitLab"}[provider]
    out = [f"{host}'s signing key and its hosted runner: whoever holds that key, or a runner that lies about which workflow ran, could forge the token.",
           "The code of the pinned workflow at the commit named above: it decides what counts as accepted. Read it at that commit."]
    if mode == "merge":
        out.append("The administrators of the repository: in merge mode the merge is the acceptance, and whoever may merge or change the branch rules can accept.")
    if kind in ("neutral", "arbiter", "attestor"):
        out.append("The account that ran the judge: the run was in a repository other than the one the work was merged in, started by its owner.")
    out.append("Knos's upgrade multisig: the programs are upgradeable only through a multisig with a public 48-hour delay, until an outside review.")
    return out


def trusted_line(provider: str, mode: str, kind: str, commit: str) -> str:
    """The parties `trust_of` lists, in one line: printed beside the verdict, so nobody reads "accepted" without them."""
    host = {"github": "GitHub", "gitlab": "GitLab"}[provider]
    who = [f"{host}'s signing key and runner", f"the pinned workflow at {commit}"]
    who += ["the repository's administrators (the merge is the acceptance)"] if mode == "merge" else []
    who += ["the account that ran the judge"] if kind in ("neutral", "arbiter", "attestor") else []
    return "trusted: " + "; ".join([*who, "Knos's upgrade multisig (public 48-hour delay)"]) + "."


def build2(*, cluster: str, program: str, order: str, scope: str, repository: dict | None, commit: str, pull_request: int, terms_hash: str, mode: str,
           judge_kind: str, issuer: str, claims: dict, token_sha256: str, key: str, oidc_program: str, verified_tx: str, checks: list[str],
           allowed_paths: list[str] | None, denied_paths: list[str] | None, policy_version: int | None, amendments: list[dict], payees: list[dict],
           mint: str, decimals: int, paid: int, of: int, fee: int, tip: int, signature: str, slot: int, time: int) -> dict:
    """A version 2 receipt from its facts. `checks`: the names the terms require (the judge signs only when each
    passed at `commit`). `allowed_paths`, `denied_paths`, `policy_version`: from the terms; None when the order's
    terms are not public (a private order). `amendments`: {kind, transaction, time, detail} oldest first."""
    provider = PROVIDERS.get(issuer, "github")
    names = GITLAB_CLAIMS if provider == "gitlab" else CLAIMS
    said = {k: int(claims[k]) if k in ("iat", "exp") else str(claims[k]).lower() if isinstance(claims[k], bool) else str(claims[k]) for k in names}
    r = {"type": TYPE, "version": 2, "cluster": cluster, "program": program, "order": order, "scope": scope, "repository": repository,
         "issuer_authenticated": {"provider": provider, "issuer": issuer, "claims": said, "token_sha256": token_sha256,
                                  "verified": {"program": oidc_program, "key": key, "transaction": verified_tx}},
         "evaluator_observed": {"judge": {"kind": judge_kind, "version": said["ci_config_sha" if provider == "gitlab" else "job_workflow_sha"]},
                                "verdict": "accepted", "checks": [{"name": n, "conclusion": "passed"} for n in checks],
                                "artifact": {"commit": commit, "pull_request": pull_request}},
         "policy": {"terms_hash": terms_hash, "mode": mode, "allowed_paths": allowed_paths, "denied_paths": denied_paths, "version": policy_version},
         "trust_remaining": trust_of(provider, mode, judge_kind),
         "amendments": [{"kind": a["kind"], "transaction": a["transaction"], "time": a["time"], "detail": {k: str(v) for k, v in sorted(a["detail"].items())}}
                        for a in amendments],
         "payees": [{"github_id": p["github_id"], "bps": p["bps"], "amount": str(p["amount"]), "to": p["to"]} for p in payees],
         "amounts": {"mint": mint, "decimals": decimals, "paid": str(paid), "of": str(of), "fee": str(fee), "tip": str(tip)},
         "transaction": {"signature": signature, "slot": slot, "time": time}}
    why = check(r)
    if why:
        raise ValueError(why)
    return r


def upgrade(r1: dict, *, oidc_program: str, verified_tx: str, terms: dict | None = None, amendments: list[dict] | None = None) -> dict:
    """A version 1 receipt as version 2. `terms`: the order's terms (their `checks`, `paths`, `deny` and `v` are what
    version 1 did not carry); None leaves them unknown. `verified_tx`: the transaction in which knos_oidc finished
    verifying the token."""
    why = check(r1)
    if why or r1["version"] != 1:
        raise ValueError(why or "this receipt is not of version 1")
    j, m, x = r1["judge"], r1["amounts"], r1["transaction"]
    return build2(cluster=r1["cluster"], program=r1["program"], order=r1["order"], scope=r1["scope"], repository=r1["repository"],
                  commit=r1["artifact"]["commit"], pull_request=r1["artifact"]["pull_request"], terms_hash=r1["terms"]["hash"], mode=r1["terms"]["mode"],
                  judge_kind=j["kind"], issuer=j["issuer"], claims=j["claims"], token_sha256=j["token_sha256"], key=j["key"], oidc_program=oidc_program,
                  verified_tx=verified_tx, checks=sorted({c["name"] for c in terms["checks"]}) if terms else [],
                  allowed_paths=list(terms["paths"]) if terms else None, denied_paths=list(terms["deny"]) if terms else None,
                  policy_version=terms["v"] if terms else None, amendments=amendments or [],
                  payees=[{**p, "amount": int(p["amount"])} for p in r1["payees"]], mint=m["mint"], decimals=m["decimals"], paid=int(m["paid"]),
                  of=int(m["of"]), fee=int(m["fee"]), tip=int(m["tip"]), signature=x["signature"], slot=x["slot"], time=x["time"])


def _as1(r: dict) -> dict:
    """The version 1 receipt a version 2 one holds, with a GitLab token's claims under the names GitHub gives the same
    facts: the rules both versions share are written once, in `_check1`."""
    a, o, p = r["issuer_authenticated"], r["evaluator_observed"], r["policy"]
    claims = dict(a["claims"])
    if a["provider"] == "gitlab":       # with its three ids as the program reads them: the order's repository id is 9e17 + the project's
        claims = {_AS_GITHUB[k]: str(gitlab_id(k, v)) if k in _GL_BASE else v for k, v in claims.items() if k in _AS_GITHUB} | {"iat": claims["iat"], "exp": claims["exp"], "run_attempt": "1",
                  "runner_environment": "github-hosted" if claims["runner_environment"] == "gitlab-hosted" else claims["runner_environment"]}
    return {"type": TYPE, "version": 1, **{k: r[k] for k in ("cluster", "program", "order", "scope", "repository", "payees", "amounts", "transaction")},
            "artifact": o["artifact"], "terms": {"hash": p["terms_hash"], "mode": p["mode"]},
            "judge": {"kind": o["judge"]["kind"], "issuer": a["issuer"], "claims": claims, "token_sha256": a["token_sha256"], "key": a["verified"]["key"]}}


def _check2(r) -> str | None:
    def keys(obj, want, where):
        if not isinstance(obj, dict):
            return f"{where} is not an object"
        return None if set(obj) == set(want) else f"{where} has fields {sorted(set(obj) ^ set(want))} missing or unknown"
    def globs(v):
        return v is None or (isinstance(v, list) and all(isinstance(g, str) for g in v) and v == sorted(set(v)))
    why = keys(r, _KEYS2, "the receipt")
    if why:
        return f"not a {TYPE} of version 1, 2 or 3: as version 2, {why}"
    a, o, p = r["issuer_authenticated"], r["evaluator_observed"], r["policy"]
    why = (keys(a, ("provider", "issuer", "claims", "token_sha256", "verified"), "issuer_authenticated")
           or keys(a["verified"], ("program", "key", "transaction"), "issuer_authenticated.verified")
           or keys(o, ("judge", "verdict", "checks", "artifact"), "evaluator_observed") or keys(o["judge"], ("kind", "version"), "evaluator_observed.judge")
           or keys(p, ("terms_hash", "mode", "allowed_paths", "denied_paths", "version"), "policy"))
    if why:
        return why
    if a["provider"] not in ("github", "gitlab") or PROVIDERS.get(a["issuer"], "github") != a["provider"]:
        return "issuer_authenticated.provider is github or gitlab, and gitlab only for https://gitlab.com"
    names = GITLAB_CLAIMS if a["provider"] == "gitlab" else CLAIMS
    why = keys(a["claims"], names, "issuer_authenticated.claims")
    if why:
        return why
    c, v = a["claims"], a["verified"]
    if not all(isinstance(c[k], str) for k in names if k not in ("iat", "exp")):
        return "judge.claims are strings as the issuer signed them, but iat and exp, which are numbers"
    if a["provider"] == "gitlab":       # what gl.rs asks of a token that pays, in its order
        if any(gitlab_id(k, c[k]) is None for k in _GL_BASE):
            return (f"a GitLab receipt's project_id, user_id and namespace_id are GitLab's own numbers, 1 to {GL_MAX}: the program reads a project and a user as "
                    f"{GL_ID} + id and a namespace as {GL_NS} + id")
        if c["ref_protected"] != "true" or c["ref_type"] != "branch" or o["judge"]["kind"] != "repository":
            return "a GitLab receipt is for a pipeline of the order's own project on a protected branch"
        head, tail = f"{GITLAB_HOST}{c['project_path']}//", f"@{c['ref_path']}"
        if not (len(c["ci_config_ref_uri"]) > len(head) + len(tail) and c["ci_config_ref_uri"].startswith(head) and c["ci_config_ref_uri"].endswith(tail)):
            return "ci_config_ref_uri is gitlab.com/<project_path>//<file>@<ref_path>: a file of the token's own project, on the ref the pipeline ran on"
        if c["pipeline_source"] != "pipeline":
            return "a GitLab order is paid from a pipeline that a pipeline of the project started (pipeline_source is pipeline)"
    if not (isinstance(v["program"], str) and _ADDR.match(v["program"]) and isinstance(v["transaction"], str) and _SIG.match(v["transaction"])):
        return "issuer_authenticated.verified is {program and key as base58 addresses, transaction as a base58 signature}"
    why = _check1(_as1(r))          # everything version 1 said, by the same rules
    if why:
        return why
    if o["judge"]["version"] != c["ci_config_sha" if a["provider"] == "gitlab" else "job_workflow_sha"]:
        return "evaluator_observed.judge.version is the commit of the workflow the issuer signed"
    ch = o["checks"]
    if o["verdict"] != "accepted" or not isinstance(ch, list) or any(keys(e, ("name", "conclusion"), "a check") or not isinstance(e["name"], str) or not e["name"]
                                                                     or e["conclusion"] != "passed" for e in ch):
        return "evaluator_observed is the verdict accepted, with every named check as {name, conclusion: passed}"
    if [e["name"] for e in ch] != sorted({e["name"] for e in ch}):
        return "evaluator_observed.checks are in order of name, each once"
    if not (globs(p["allowed_paths"]) and globs(p["denied_paths"])) or (p["version"] is not None and p["version"] != 1) or type(p["version"]) is bool:
        return "policy.allowed_paths and policy.denied_paths are sorted lists of globs and policy.version is 1; all three are null when the terms are not public"
    if len({p["allowed_paths"] is None, p["denied_paths"] is None, p["version"] is None}) != 1:
        return "policy.allowed_paths and policy.denied_paths are sorted lists of globs and policy.version is 1; all three are null when the terms are not public"
    if r["trust_remaining"] != trust_of(a["provider"], p["mode"], o["judge"]["kind"]):
        return "trust_remaining is the list this kind of order leaves (knos.receipt.trust_of): none may be left out"
    am, last = r["amendments"], 0
    if not isinstance(am, list):
        return "amendments is a list"
    for e in am:
        if (keys(e, ("kind", "transaction", "time", "detail"), "an amendment") or e["kind"] not in AMENDMENTS
                or not (isinstance(e["transaction"], str) and _SIG.match(e["transaction"])) or type(e["time"]) is not int or e["time"] < last
                or not isinstance(e["detail"], dict) or not all(isinstance(k, str) and isinstance(x, str) for k, x in e["detail"].items())):
            return "an amendment is {kind: topup, assign, reserve, cancel or plan, transaction, time, detail of strings}, oldest first"
        last = e["time"]
    return None


# ---- version 3: a fifth part (who authorised the money), and who controls each judge --------------------------------------
SOURCES = ("wallet", "balance", "passkey")      # what the money came from: a wallet, an organisation's Balance, a passkey wallet
ROLES = ("owner", "spender", "wallet", "passkey")     # in which capacity the funder acted
NO_LIMIT = "no limit set"
ONE_JUDGE = "One judge spoke."
SAME_CONTROLLER = ("These judges are not independent of each other: account {id} owns or started more than one of them. Two accounts run by one "
                   "person are one judge, and so are two runs of one account: count this quorum as one judge.")
APART = ("The {n} judges have different owners and starters, by account id. An id is all that is recorded: two accounts run by one person are one "
         "judge, and no receipt can show that they are not.")


REEXECUTION = ("reexecuted", "assurance", "environment", "image_digest")
_ASSURANCES = ("black-box", "hermetic", "in-process")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def reexecution(verdict: dict) -> dict:
    """What an evaluator's entry says about running the acceptance suite itself, from the verdict its run handed on
    (`knos.flow._rerun_read` gives it; the `knos-verdict:` line beside the token, or the run's verdict.json):

        reexecuted     true when this judge ran the suite on the artifact; false when it read the record of the order's
                       own repository (an order paid on the merge has no suite to run)
        assurance      black-box, hermetic or in-process when it ran; null when it did not
        environment    where it ran, as the runner said: knos's version, the repository and run, the machine's kind and image
        image_digest   the digest of the image the suite ran in (hermetic), else null

    These are the run's own words: the issuer signed which workflow ran, in which repository and run, not what the
    workflow read or printed. `check` holds the run and the repository they name to the ones the issuer signed."""
    ran = bool(verdict["reexecuted"])
    digest = str((verdict.get("image") or {}).get("digest") or "") if ran else ""
    return {"reexecuted": ran, "assurance": (str(verdict.get("assurance") or "") or None) if ran else None,
            "environment": {str(k): str(v) for k, v in sorted(verdict["environment"].items())}, "image_digest": digest or None}


def _reexecution_rule(x, claims: dict | None = None) -> str | None:
    """Why `x` is not an evaluator's `reexecution`; None when it is. `claims`: the paying judge's signed claims."""
    env = x.get("environment") if isinstance(x, dict) else None
    if not isinstance(x, dict) or set(x) != set(REEXECUTION) or type(x["reexecuted"]) is not bool \
            or not (isinstance(env, dict) and len(env) <= 16 and all(isinstance(k, str) and isinstance(v, str) and len(v) <= 200 for k, v in env.items())) \
            or not (x["assurance"] in _ASSURANCES if x["reexecuted"] else x["assurance"] is None) \
            or not (x["image_digest"] is None or (isinstance(x["image_digest"], str) and _DIGEST.match(x["image_digest"]))) \
            or (x["image_digest"] is not None) != (x["assurance"] == "hermetic"):
        return ("an evaluator's reexecution is {reexecuted, assurance: black-box, hermetic or in-process when it ran and null when not, environment: "
                "at most 16 short texts, image_digest: sha256:<hex> for a hermetic run and null otherwise}")
    if claims is not None and any(k in env and env[k] != str(claims.get(c, "")) for k, c in (("github_run_id", "run_id"), ("github_repository_id", "repository_id"),
                                                                                             ("github_run_attempt", "run_attempt"))):
        return "an evaluator's reexecution names the run the issuer signed for: its environment says another repository or run than the token"
    return None


def evaluator(kind: str, claims: dict, buyers, sellers, rerun: dict | None = None) -> dict:
    """What a receipt records of one judge that spoke, from the claims its issuer signed (GitHub's names): the
    repository its run was in, who owns that repository, who started the run, on which kind of runner, and whether
    owner and starter are both other accounts than the buyer's (`buyers`: the funder's and the Balance owner's ids)
    and the seller's (`sellers`: every payee's id). Recorded, not asserted: the two flags follow from the ids, and
    `check` computes them again. `independent_of_buyer` is false for the order's own repository whoever owns it (the
    buyer chose it, and its administrators can accept), and null when the buyer is a wallet and so has no account id
    to compare with. `rerun`: what `reexecution` made of the verdict this judge's run handed on; the entry then
    carries it as `reexecution`. An entry without it says nothing about how the judge reached its verdict."""
    owner, actor = int(claims["repository_owner_id"]), int(claims["actor_id"])
    buyers, sellers = {int(b) for b in buyers if b}, {int(x) for x in sellers if x}
    return {"kind": kind, "repository_id": int(claims["repository_id"]), "owner_id": owner, "actor_id": actor, "runner": str(claims["runner_environment"]),
            "independent_of_buyer": False if kind == "repository" else None if not buyers else not ({owner, actor} & buyers),
            "independent_of_seller": not ({owner, actor} & sellers), **({} if rerun is None else {"reexecution": rerun})}


def independence_of(evaluators: list[dict]) -> tuple[bool, str]:
    """(whether two of the judges share an owner or a starter, the sentence a receipt says about it)."""
    seen: dict[int, int] = {}
    for i, e in enumerate(evaluators):
        for who in {e["owner_id"], e["actor_id"]}:
            if seen.setdefault(who, i) != i:
                return True, SAME_CONTROLLER.format(id=who)
    return False, ONE_JUDGE if len(evaluators) == 1 else APART.format(n=len(evaluators))


def authorisation(*, order: str, milestone: int, funded_tx: str | None, funder_id: int = 0, login: str | None = None, wallet: str | None = None,
                  source: str = "wallet", address: str, owner_id: int = 0, cap: int = 0, daily: int = 0, total: int = 0, repositories=(),
                  limits_known: bool = True, billed_before: str | None = None) -> dict:
    """The fifth part, from the funding as the chain logged it. `funder_id`: the GitHub id of the account whose signed
    comment funded (0: a wallet signed, and `wallet` is it); `login`: its login as the funding token carried it, None
    when the records no longer have the token. `source`, `address`, `owner_id`: what the money came from, and for a
    Balance the id of its owner. `cap`, `daily`, `total`, `repositories`: the Balance's limits when it funded (0 and
    empty: none of that kind); a wallet has none. `limits_known` False: the records do not have them. `billed_before`:
    the transaction of an earlier payment of this order and milestone, or None."""
    limited = source == "balance" and limits_known and bool(cap or daily or total or repositories)
    return {"funder": {"github_id": funder_id or None, "login": login if funder_id else None, "wallet": None if funder_id else wallet},
            "source": {"kind": source, "address": address, "owner_id": owner_id or None},
            "limit": ({"cap_per_order": str(cap), "daily": str(daily), "total": str(total), "repositories": sorted(int(x) for x in repositories)} if limited
                      else NO_LIMIT if limits_known or source != "balance" else None),
            "role": (("owner" if funder_id == owner_id else "spender") if source == "balance" else source),
            "deliverable": {"order": order, "milestone": milestone}, "billed_before": billed_before or False, "funded": funded_tx}


def build3(r2: dict, authorised: dict, others: list[dict] | tuple = (), rerun: dict | None = None) -> dict:
    """A version 2 receipt as version 3. `authorised`: the fifth part (`authorisation`). `others`: the judges of a
    quorum that passed this artifact before the one whose token paid, as `evaluator` gives them, oldest first; the
    paying judge's own entry is made here from its claims and comes last. `rerun`: what `reexecution` made of the
    verdict the paying judge's run handed on, for a judge outside the order's repository (attest.yml's two jobs);
    None when no verdict is on hand, and the entry then says nothing of it."""
    why = check(r2)
    if why or r2["version"] != 2:
        raise ValueError(why or "this receipt is not of version 2")
    if rerun is not None and r2["evaluator_observed"]["judge"]["kind"] == "repository":
        raise ValueError("the order's own repository judged this payment: a re-execution is recorded for a judge outside it")
    f, src = authorised["funder"], authorised["source"]
    judges = [*others, {**_paying(r2, (f["github_id"], src["owner_id"])), **({} if rerun is None else {"reexecution": rerun})}]
    same, said = independence_of(judges)
    r = {}
    for k in _KEYS3:
        r[k] = (3 if k == "version" else authorised if k == "commercial_authorisation"
                else {**r2[k], "evaluators": judges, "same_controller": same, "independence": said} if k == "evaluator_observed" else r2[k])
    why = check(r)
    if why:
        raise ValueError(why)
    return r


def _paying(r2: dict, buyers) -> dict:
    """The entry of the judge whose token paid, from the claims of a version 2 receipt (a GitLab token's ids as the
    program reads them, its runner as GitLab named it)."""
    claims = {**_as1(r2)["judge"]["claims"], "runner_environment": r2["issuer_authenticated"]["claims"]["runner_environment"]}
    return evaluator(r2["evaluator_observed"]["judge"]["kind"], claims, buyers, [p["github_id"] for p in r2["payees"]])


def chain_only(r: dict) -> dict:
    """The receipt as the chain alone gives it: without what an evaluator's entry holds from its run's own words
    (`reexecution`). A mirror is written with no host asked, so two copies of one payment's receipt are the same
    receipt when these are equal."""
    o = r.get("evaluator_observed") if isinstance(r, dict) else None
    if r.get("version") != 3 or not isinstance(o, dict) or not isinstance(o.get("evaluators"), list):
        return r
    return {**r, "evaluator_observed": {**o, "evaluators": [{k: v for k, v in e.items() if k != "reexecution"} if isinstance(e, dict) else e
                                                            for e in o["evaluators"]]}}


def as2(r: dict) -> dict:
    """The version 2 receipt a version 3 one holds (the same payment, without the fifth part and the judges' control);
    a receipt of version 1 or 2 as it is. What a reader that knows version 2 only is given."""
    if r.get("version") != 3:
        return r
    out = {k: r[k] for k in _KEYS2}
    out["version"] = 2
    out["evaluator_observed"] = {k: v for k, v in r["evaluator_observed"].items() if k not in ("evaluators", "same_controller", "independence")}
    return out


_ROLE_RULE = "commercial_authorisation.role is owner or spender for a Balance (owner when the funder is its owner), wallet for a wallet, passkey for a passkey wallet"


def _check3(r) -> str | None:
    def keys(obj, want, where):
        if not isinstance(obj, dict):
            return f"{where} is not an object"
        return None if set(obj) == set(want) else f"{where} has fields {sorted(set(obj) ^ set(want))} missing or unknown"
    def ident(v):
        return type(v) is int and v > 0
    why = keys(r, _KEYS3, "the receipt")
    if why:
        return f"not a {TYPE} of version 1, 2 or 3: as version 3, {why}"
    o, c = r["evaluator_observed"], r["commercial_authorisation"]
    why = keys(o, ("judge", "verdict", "checks", "artifact", "evaluators", "same_controller", "independence"), "evaluator_observed")
    if why:
        return why
    why = _check2(as2(r))           # everything version 2 said, by the same rules
    if why:
        return why
    # 4. who authorised the money
    why = (keys(c, ("funder", "source", "limit", "role", "deliverable", "billed_before", "funded"), "commercial_authorisation")
           or keys(c["funder"], ("github_id", "login", "wallet"), "commercial_authorisation.funder")
           or keys(c["source"], ("kind", "address", "owner_id"), "commercial_authorisation.source")
           or keys(c["deliverable"], ("order", "milestone"), "commercial_authorisation.deliverable"))
    if why:
        return why
    f, s, lim = c["funder"], c["source"], c["limit"]
    if (f["github_id"] is None) == (f["wallet"] is None) or not (f["github_id"] is None or ident(f["github_id"])) \
            or not (f["wallet"] is None or (isinstance(f["wallet"], str) and _ADDR.match(f["wallet"]))) \
            or not (f["login"] is None or (isinstance(f["login"], str) and f["login"] and f["github_id"] is not None)):
        return "commercial_authorisation.funder is an account {github_id, login or null} or a wallet {wallet}, the other fields null"
    if s["kind"] not in SOURCES or not (isinstance(s["address"], str) and _ADDR.match(s["address"])) or (s["kind"] == "balance") != ident(s["owner_id"]) \
            or (s["kind"] != "balance" and s["owner_id"] is not None):
        return "commercial_authorisation.source is {kind: wallet, balance or passkey, address, owner_id: a Balance's owner, else null}"
    if (s["kind"] == "balance") != (f["github_id"] is not None) or (s["kind"] == "wallet" and f["wallet"] != s["address"]):
        return "a Balance is spent by an account's signed comment, and a wallet or a passkey wallet funds with its own signature: the funder and the source do not fit"
    if c["role"] != (("owner" if f["github_id"] == s["owner_id"] else "spender") if s["kind"] == "balance" else s["kind"]):
        return _ROLE_RULE
    if isinstance(lim, dict):
        if keys(lim, ("cap_per_order", "daily", "total", "repositories"), "commercial_authorisation.limit") \
                or not all(isinstance(lim[k], str) and _UNITS.match(lim[k]) for k in ("cap_per_order", "daily", "total")) \
                or not (isinstance(lim["repositories"], list) and all(ident(x) for x in lim["repositories"]) and lim["repositories"] == sorted(set(lim["repositories"]))) \
                or not (int(lim["cap_per_order"]) or int(lim["daily"]) or int(lim["total"]) or lim["repositories"]) or s["kind"] != "balance":
            return ("commercial_authorisation.limit is a Balance's {cap_per_order, daily, total as decimal strings (0: none of that kind), repositories as a sorted "
                    f"list of ids}} with at least one of them set, \"{NO_LIMIT}\", or null when the records do not have it")
        if lim["repositories"] and (r["repository"] is None or r["repository"]["id"] not in lim["repositories"]):
            return "the order's repository is not on the allow-list the funding is said to have passed under"
    elif lim != NO_LIMIT and not (lim is None and s["kind"] == "balance"):
        return ("commercial_authorisation.limit is a Balance's {cap_per_order, daily, total as decimal strings (0: none of that kind), repositories as a sorted "
                f"list of ids}} with at least one of them set, \"{NO_LIMIT}\", or null when the records do not have it")
    d, before = c["deliverable"], c["billed_before"]
    if d["order"] != r["order"] or type(d["milestone"]) is not int or d["milestone"] not in (0, r["evaluator_observed"]["artifact"]["pull_request"]):
        return "commercial_authorisation.deliverable is this order and its milestone: 0, or the pull request of a standing order's payment"
    if not (before is False or (isinstance(before, str) and _SIG.match(before) and before != r["transaction"]["signature"])):
        return "commercial_authorisation.billed_before is false, or the signature of the earlier transaction that paid this order and milestone"
    if not (c["funded"] is None or (isinstance(c["funded"], str) and _SIG.match(c["funded"]))):
        return "commercial_authorisation.funded is the funding transaction's signature, or null when the history read does not reach it"
    # 2. who controls each judge
    ev = o["evaluators"]
    if not isinstance(ev, list) or not 1 <= len(ev) <= 3:
        return "evaluator_observed.evaluators is a list of the one to three judges that spoke, the one whose token paid last"
    fields = ("kind", "repository_id", "owner_id", "actor_id", "runner", "independent_of_buyer", "independent_of_seller")
    sellers = [p["github_id"] for p in r["payees"]]
    for n, e in enumerate(ev):
        rerun = e.get("reexecution") if isinstance(e, dict) else None       # optional: the verdict the judge's run handed on, when one was on hand
        if rerun is not None:
            e = {k: v for k, v in e.items() if k != "reexecution"}
            why = "the order's own repository" if e.get("kind") == "repository" else \
                _reexecution_rule(rerun, r["issuer_authenticated"]["claims"] if n == len(ev) - 1 and r["issuer_authenticated"]["provider"] == "github" else None)
            if why:
                return ("a re-execution is recorded for a judge outside the order's repository: evaluator_observed.evaluators gives one to the order's own"
                        if why == "the order's own repository" else why)
        if keys(e, fields, "an evaluator") or e["kind"] not in JUDGES or not all(ident(e[k]) for k in ("repository_id", "owner_id", "actor_id")) \
                or not isinstance(e["runner"], str):
            return "an evaluator is {kind, repository_id, owner_id, actor_id, runner, independent_of_buyer, independent_of_seller}"
        want = evaluator(e["kind"], {"repository_id": e["repository_id"], "repository_owner_id": e["owner_id"], "actor_id": e["actor_id"],
                                     "runner_environment": e["runner"]}, (f["github_id"], s["owner_id"]), sellers)
        if e != want:
            return ("an evaluator's independent_of_buyer and independent_of_seller are computed, not chosen: its owner and its starter are both other "
                    "accounts than the funder and the Balance's owner, and than every payee (knos.receipt.evaluator)")
    if len({e["kind"] for e in ev}) != len(ev):
        return "each kind of judge speaks once in a quorum: evaluator_observed.evaluators names a kind twice"
    if {k: v for k, v in ev[-1].items() if k != "reexecution"} != _paying(as2(r), (f["github_id"], s["owner_id"])):
        return "the last of evaluator_observed.evaluators is the judge whose token paid, with the ids and the runner its issuer signed"
    if (o["same_controller"], o["independence"]) != independence_of(ev) or type(o["same_controller"]) is not bool:
        return ("evaluator_observed.same_controller is true when two judges share an owner or a starter, and independence is the sentence for it "
                "(knos.receipt.independence_of): two accounts run by one person are one judge")
    return None


# ---- the receipt for a person ---------------------------------------------------------------------------------------------
def _utc(t: int) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _money(units: str, decimals: int) -> str:
    whole, part = divmod(int(units), 10 ** decimals)
    return f"{whole}.{part:0{decimals}d}" if decimals else str(whole)


def _authorised(c: dict | None, version: int, m: dict) -> list[str]:
    """The fifth part in lines; for a receipt of version 1 or 2, what it does not carry."""
    if c is None:
        return [f"   Not recorded in a version {version} receipt: who funded, from what, under which limit, and whether this deliverable was paid before.",
                "   `knos bundle make` writes a version 3 receipt of the same payment while the chain's record is there."]
    f, s, lim, d = c["funder"], c["source"], c["limit"], c["deliverable"]
    who = (f"GitHub account {f['github_id']}" + (f" ({f['login']}, as its funding token named it)" if f["login"] else " (its login is not in the records read)")
           if f["github_id"] else f"the wallet {f['wallet']}")
    what = {"wallet": f"that wallet's own money ({s['address']})", "passkey": f"the passkey wallet {s['address']}",
            "balance": f"the Balance {s['address']} of the organisation account {s['owner_id']}"}[s["kind"]]
    role = {"owner": "The funder is the Balance's owner.", "spender": "The funder is not the Balance's owner: the Balance lists it as a spender.",
            "wallet": "The wallet signed the funding itself: nobody else's authority was used.",
            "passkey": "The holder of the passkey signed the funding: nobody else's authority was used."}[c["role"]]
    if isinstance(lim, dict):
        parts = [f"{name} {_money(lim[k], m['decimals'])}" if int(lim[k]) else f"{name} none" for k, name in (("cap_per_order", "cap for one order"),
                                                                                                       ("daily", "a day"), ("total", "in total"))]
        limit = "   Limit the funding passed under: " + ", ".join(parts) + "; repositories allowed: " + (", ".join(str(x) for x in lim["repositories"]) or "any") + "."
    else:
        limit = (f"   Limit the funding passed under: {NO_LIMIT}." if lim == NO_LIMIT
                 else "   Limit the funding passed under: not in the records read (the Balance's opening is older than the history).")
    return [f"   Funded by {who}, from {what}.", f"   {role}", limit,
            f"   Deliverable: order {d['order']}, milestone {d['milestone']}. Billed before: " + (f"yes, in transaction {c['billed_before']}." if c["billed_before"]
                                                                                             else "no, this is its first payment in the history read."),
            f"   Funding transaction: {c['funded'] or 'older than the history read'}."]


def _reran(x: dict | None) -> str:
    """One sentence about how a judge reached its verdict, when its entry says (the run's own words, not the issuer's)."""
    if x is None:
        return ""
    env = x["environment"]
    where = ", ".join(f"{name} {env[k]}" for k, name in (("knos", "knos"), ("runner_os", "on"), ("imageos", "image"), ("imageversion", "version")) if env.get(k))
    if not x["reexecuted"]:
        return f" By its own run's word, it did not run the acceptance suite: it read the record of the order's repository{' (' + where + ')' if where else ''}."
    return (f" By its own run's word, it ran the acceptance suite itself ({x['assurance']}"
            + (f", image {x['image_digest']}" if x["image_digest"] else "") + (f"; {where}" if where else "") + ").")


def _judges(o: dict) -> list[str]:
    """Who controls each judge that spoke (version 3), one line each, then the sentence about their independence."""
    def flag(v, of: str) -> str:
        return f"independence of the {of} cannot be computed (a wallet has no account id)" if v is None else f"{'independent' if v else 'NOT independent'} of the {of}"
    out = [f"   - {e['kind']}: repository {e['repository_id']} owned by account {e['owner_id']}, run started by account {e['actor_id']}, "
           f"{'GitHub-hosted' if e['runner'] == 'github-hosted' else e['runner']} runner; {flag(e['independent_of_buyer'], 'buyer')}, "
           f"{flag(e['independent_of_seller'], 'seller')}." + _reran(e.get("reexecution")) for e in o["evaluators"]]
    return ["   Judges that spoke, and who controls each:", *out, f"   {'SAME CONTROLLER. ' if o['same_controller'] else ''}{o['independence']}"]


def render(r: dict) -> list[str]:
    """The receipt in lines a person reads: the five parts under their headings, in order, then the amendments and the
    payment. The parties still trusted are named in one line beside the verdict. A receipt of version 1 or 2 is
    shown the same way, and says what it does not carry."""
    old = r["version"] == 1
    a = ({"provider": "github", "issuer": r["judge"]["issuer"], "claims": r["judge"]["claims"], "token_sha256": r["judge"]["token_sha256"],
          "verified": {"program": None, "key": r["judge"]["key"], "transaction": None}} if old else r["issuer_authenticated"])
    o = ({"judge": {"kind": r["judge"]["kind"], "version": r["judge"]["claims"]["job_workflow_sha"]}, "verdict": "accepted", "checks": None,
          "artifact": r["artifact"]} if old else r["evaluator_observed"])
    p = {"terms_hash": r["terms"]["hash"], "mode": r["terms"]["mode"], "allowed_paths": None, "denied_paths": None, "version": None} if old else r["policy"]
    c, gl = a["claims"], a["provider"] == "gitlab"
    host = "GitLab" if gl else "GitHub"
    file, at, repo, event = ((c["ci_config_ref_uri"], c["ci_config_sha"], f"{c['project_id']} ({c['project_path']}; on chain {gitlab_id('project_id', c['project_id'])})",
                              c["pipeline_source"]) if gl
                             else (c["job_workflow_ref"], c["job_workflow_sha"], c["repository_id"], c["event_name"]))
    v, m = a["verified"], r["amounts"]
    out = [f"Acceptance receipt, version {r['version']}: order {r['order']} on {r['cluster']}", "",
           f"1. {HEADINGS['issuer_authenticated']}",
           f"   {host} signed: the workflow file {file}", f"   at commit {at}", f"   ran in repository {repo} for the event {event}, at {_utc(c['iat'])}.",
           (f"   Verified on chain by knos_oidc ({v['program']}), key {v['key']}, in transaction {v['transaction']}." if v["transaction"]
            else f"   Verified on chain by the knos_oidc key {v['key']} (a version 1 receipt does not name the verifying transaction)."),
           f"   The token is recognised by sha256 of its signature: {a['token_sha256']}.", "",
           f"2. {HEADINGS['evaluator_observed']}",
           f"   The pinned judge ({o['judge']['kind']}, version {o['judge']['version']}) gave the verdict: {o['verdict']}.",
           f"   {trusted_line(a['provider'], p['mode'], o['judge']['kind'], o['judge']['version'])}",
           ("   Named checks: not recorded in a version 1 receipt." if o["checks"] is None else "   Named checks: none were required." if not o["checks"]
            else "   Named checks: " + "; ".join(f"{e['name']}: {e['conclusion']}" for e in o["checks"]) + "."),
           f"   Artifact: commit {o['artifact']['commit']}, pull request {o['artifact']['pull_request']}.",
           *(_judges(o) if r["version"] == 3 else [f"   Who controls the judge (its owner, its starter, its runner): not recorded in a version {r['version']} receipt."]), "",
           f"3. {HEADINGS['policy']}",
           f"   Terms hash, fixed at funding: {p['terms_hash']}. Mode: {p['mode']}.",
           ("   Allowed paths and policy version: not in this receipt (the terms are not public, or the receipt is of version 1)." if p["version"] is None
            else f"   Allowed paths: {', '.join(p['allowed_paths']) or 'any'}. Never allowed: {', '.join(p['denied_paths']) or 'none'}. Policy version: {p['version']}."),
           "", f"4. {HEADINGS['commercial_authorisation']}", *_authorised(r.get("commercial_authorisation"), r["version"], m),
           "", f"5. {HEADINGS['trust_remaining']}"]
    out += [f"   - {t}" for t in (trust_of("github", p["mode"], o["judge"]["kind"]) if old else r["trust_remaining"])]
    out += ["", "Amendments of the order's terms"]
    out += (["   Not recorded in a version 1 receipt."] if old else ["   None: the order was paid as it was funded."] if not r["amendments"] else
            [f"   - {_utc(e['time'])} {e['kind']} {' '.join(f'{k}={x}' for k, x in sorted(e['detail'].items()))} (transaction {e['transaction']})"
             for e in r["amendments"]])
    out += ["", "Payment", f"   Paid {_money(m['paid'], m['decimals'])} of {_money(m['of'], m['decimals'])} (mint {m['mint']}), fee {_money(m['fee'], m['decimals'])}, "
            f"relayer tip {_money(m['tip'], m['decimals'])}."]
    out += [f"   - account {e['github_id']}: {_money(e['amount'], m['decimals'])} to {e['to']}" for e in r["payees"]]
    out += [f"   Transaction {r['transaction']['signature']}, slot {r['transaction']['slot']}, {_utc(r['transaction']['time'])}.",
            "", f"Digest sha256:{digest(r)}"]
    return out


# ---- the mirror: every receipt, off chain -----------------------------------------------------------------------------------
MIRROR, MIRROR_VERSION = "knos.receipt-mirror", 1
FROM_MIRROR = "from mirror, chain record unavailable"


def mirror_write(receipts: list[dict], out_dir) -> dict:
    """Write `receipts` under `out_dir` as `<order>.json` (every receipt of that order, oldest first: a standing order
    is paid more than once) and `index.json`. What the folder already holds is kept, so a receipt outlives the chain
    that made it; the same receipts in any order give the same bytes, so any static host can serve the folder.
    Returns the index."""
    from pathlib import Path
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    held: dict[str, dict[str, dict]] = {}       # order -> digest -> receipt
    for f in sorted(out.glob("*.json")):
        if f.name != "index.json":
            for r in json.loads(f.read_text(encoding="utf-8"))["receipts"]:
                held.setdefault(r["order"], {})[digest(r)] = r
    for r in receipts:
        why = check(r)
        if why:
            raise ValueError(f"not written, a receipt of order {r.get('order') if isinstance(r, dict) else '?'} is not valid: {why}")
        held.setdefault(r["order"], {})[digest(r)] = r
    index: dict = {"type": MIRROR, "version": MIRROR_VERSION, "orders": {}}
    for order in sorted(held):
        rows = sorted(held[order].items(), key=lambda kv: (kv[1]["transaction"]["time"], kv[1]["transaction"]["slot"], kv[0]))
        doc = {"type": MIRROR, "version": MIRROR_VERSION, "order": order, "receipts": [r for _, r in rows]}
        (out / f"{order}.json").write_bytes(canonical(doc) + b"\n")
        index["orders"][order] = [{"sha256": d, "transaction": r["transaction"]["signature"], "time": r["transaction"]["time"], "cluster": r["cluster"]}
                                  for d, r in rows]
    (out / "index.json").write_bytes(canonical(index) + b"\n")
    return index


def mirror_find(where: str, target: str, get=None) -> list[dict]:
    """The receipts a mirror holds for `target` (an order's address, or a paying transaction's signature), each checked
    against the mirror's own index and against the rules. `where`: a folder, or the https URL a folder is served at.
    Raises ValueError, in words, when the mirror cannot be read or what it holds is not what its index says."""
    def read(name: str) -> dict:
        try:
            if where.startswith(("https://", "http://")):
                import urllib.request
                fetch = get or (lambda url: urllib.request.urlopen(url, timeout=20).read())  # noqa: S310 - the mirror the reader named
                return json.loads(fetch(f"{where.rstrip('/')}/{name}"))
            from pathlib import Path
            return json.loads((Path(where) / name).read_bytes())
        except Exception as e:  # noqa: BLE001 - whatever stopped the read, the reader is told which file
            raise ValueError(f"the mirror at {where} could not be read ({name}: {e})") from None
    index = read("index.json")
    if index.get("type") != MIRROR or not isinstance(index.get("orders"), dict):
        raise ValueError(f"{where} is not a Knos receipt mirror (its index.json is not one)")
    orders = [o for o, rows in sorted(index["orders"].items()) if o == target or any(row["transaction"] == target for row in rows)]
    out = []
    for order in orders:
        listed = {row["sha256"] for row in index["orders"][order]}
        for r in read(f"{order}.json").get("receipts", []):
            why = check(r)
            if why or digest(r) not in listed or r["order"] != order:
                raise ValueError(f"the mirror's receipt for order {order} is not the one its index lists" if not why else f"the mirror's receipt for order {order} is not valid: {why}")
            if target in (order, r["transaction"]["signature"]):
                out.append(r)
    return out


# ---- the Solana Attestation Service attestation, at settlement ---------------------------------------------------------------
def attest(r: dict, keypair: str | None = None, rpc: str | None = None, timeout: float = 60.0, run=None, call=None, sleep=None) -> dict:
    """Write `r` as an attestation (scripts/sas_receipt.mjs --send). On by default wherever a receipt is issued; the
    caller's opt-out is its own flag, or KNOS_NO_SAS=1. It fails soft: nothing here raises and a payment never waits
    on it, since it runs after the paying transaction is confirmed. Returns {"attested": bool, "why": words, ...}.
    `keypair`: the credential authority's devnet key file (default: KNOS_SAS_KEYPAIR). When the script fails after it
    may have sent (a public endpoint's 429 can crash its client after the transaction landed), the cluster is asked
    whether the attestation is there before a failure is reported, and the failure is the script's own error line.
    `call` and `sleep` stand in for knos.chain.call and time.sleep in tests."""
    import os
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path
    try:
        if os.environ.get("KNOS_NO_SAS") == "1":
            return {"attested": False, "why": "attestations are turned off (KNOS_NO_SAS=1)"}
        keypair = keypair or os.environ.get("KNOS_SAS_KEYPAIR")
        script = Path(os.environ.get("KNOS_SAS_SCRIPT") or Path(__file__).resolve().parents[2] / "scripts" / "sas_receipt.mjs")
        node = shutil.which("node")
        if not keypair:
            return {"attested": False, "why": "no key for the attestation: set KNOS_SAS_KEYPAIR to the credential authority's devnet key file"}
        if not node or not script.is_file() or (run is None and not (script.parent / "node_modules").is_dir()):
            return {"attested": False, "why": "the attestation script needs Node and scripts/sas_receipt.mjs (npm ci --prefix scripts)"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            path.write_bytes(canonical(r))          # as it is: the attestation's digest is this receipt's, whatever its version (the script reads 1, 2 and 3)
            done = (run or subprocess.run)([node, str(script), str(path), "--send", "--keypair", keypair, *(["--rpc", rpc] if rpc else [])],
                                           capture_output=True, text=True, timeout=timeout)
            if done.returncode != 0:
                why = _script_error(done)
                if why.startswith("refused:"):          # refused before anything was sent
                    return {"attested": False, "why": why}
                url = rpc or os.environ.get("KNOS_RPC") or "https://api.devnet.solana.com"
                there = _attestation_on_chain([node, str(script), str(path), "--keypair", keypair], url, run or subprocess.run, timeout, call, sleep)
                if there:
                    return {"attested": True, "why": f"attested: the attestation is on chain, though the script failed ({why})", "attestation": there}
                return {"attested": False, "why": why}
        said = json.loads(done.stdout)
        return {"attested": True, "why": "already attested" if said.get("already") else "attested", **{k: said[k] for k in ("attestation", "signature") if said.get(k)}}
    except Exception as e:  # noqa: BLE001 - failing soft is the point: the payment is done and the receipt is in the mirror
        return {"attested": False, "why": f"the attestation was not written: {e}"}


def _script_error(done) -> str:
    """The error a failed run of the script stated: its own `refused:` or `failed:` line, else the error Node printed for
    an exception nothing caught (not the stack under it, nor the `Node.js v...` line Node ends with)."""
    import re
    lines = [line.strip() for line in (done.stderr or done.stdout or "").splitlines() if line.strip()]
    lines = [line for line in lines if not re.match(r"Node\.js v\d", line) and not line.startswith("at ") and line != "^"]
    said = [line for line in lines if line.startswith(("refused:", "failed:"))]
    if said:
        return said[-1]
    errors = [line for line in lines if re.match(r"(\w*Error|Error)\b", line)]
    return errors[0] if errors else (lines[-1] if lines else "the script failed")


def _attestation_on_chain(dry: list[str], url: str, run, timeout: float, call=None, sleep=None, waits=(0, 2, 4, 8)) -> str | None:
    """The attestation's address when the cluster at `url` holds it (an account of the attestation program there), else
    None. Its address is the script's dry run with the same key: nothing is sent for it."""
    import time
    from . import chain
    plan = json.loads(run(dry, capture_output=True, text=True, timeout=timeout).stdout)
    address, program = plan["attestation"], plan["program"]
    ask = call or (lambda u, method, params: chain.call(u, method, params, timeout=30))
    for wait in waits:
        (sleep or time.sleep)(wait)
        try:
            got = (ask(url, "getAccountInfo", [address, {"encoding": "base64", "commitment": "confirmed"}]) or {}).get("value")
        except Exception:  # noqa: BLE001, S112 - not known yet: ask again
            continue
        if got and got.get("owner") == program:
            return address
    return None


def settled(ledger, result: dict, log=None, limit: int = 200) -> dict | None:
    """What a relay calls once a payment is confirmed (knos.settle.v2.relay.submit): the receipt of that payment, written
    as an attestation. On by default, and never in the payment's way: it runs after the paying transaction, nothing here
    raises, and the relay's answer does not wait on what it returns. A relay with no credential key or no
    scripts/node_modules (the public worker's lean install) says so in one line and asks nothing of the chain.
    KNOS_NO_SAS=1 turns it off without a word. Returns what `attest` said, or None when it was not asked."""
    import os
    import sys
    from pathlib import Path
    say = log or (lambda line: print(line, file=sys.stderr))
    try:
        if not result.get("ok") or result.get("kind") not in ("pay", "rule") or result.get("already") or not result.get("sigs"):
            return None
        if any(row.get("to") is None for row in result.get("paid") or [{}]):        # held for a payee with no wallet: nothing was paid yet
            return None
        if os.environ.get("KNOS_NO_SAS") == "1":
            return None
        script = Path(os.environ.get("KNOS_SAS_SCRIPT") or Path(__file__).resolve().parents[2] / "scripts" / "sas_receipt.mjs")
        url = getattr(ledger, "url", None)
        if not os.environ.get("KNOS_SAS_KEYPAIR") or not (script.parent / "node_modules").is_dir() or not url:
            say(f"no attestation of order {result.get('order')}: this relay has no KNOS_SAS_KEYPAIR or no scripts/node_modules "
                "(the payment is done; `knos receipt mirror` attests it later)")
            return None
        said = attest(_receipt_of(url, result["sigs"][-1], limit), rpc=url)
        say(f"attestation of order {result.get('order')}: {said['why']}")
        return said
    except Exception as e:  # noqa: BLE001 - failing soft is the point: the payment is confirmed whatever happens here
        try:
            say(f"no attestation of order {result.get('order') if isinstance(result, dict) else '?'}: {e}")
        except Exception:  # noqa: BLE001, S110 - not even the log line may stop a relay
            pass
        return {"attested": False, "why": f"the attestation was not written: {e}"}


def _receipt_of(url: str, signature: str, limit: int) -> dict:
    """The receipt of the payment in `signature`, rebuilt from the cluster at `url` (knos.bundle.gather): chain facts only."""
    from . import bundle, chain, records
    from .settle.v2 import pay
    events, _unread, _cut = records.history(url, pay.PAY_ID, limit)
    return bundle.gather(lambda method, params: chain.call(url, method, params, timeout=30), events, signature, None)[0]
