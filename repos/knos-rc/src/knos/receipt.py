"""The acceptance receipt: one JSON document that says who signed what, about which artifact, under which terms, and
what was paid for it. It is derived from public facts only (the order, the judge's signed token, the program's
log lines of the paying transaction), so anyone can rebuild it and compare digests. docs/reference/RECEIPT.md is the
specification; docs/receipt/acceptance-receipt.v1 to v5.schema.json are the JSON Schemas; docs/receipt/vectors.json,
vectors.v4.json and vectors.v5.json hold the conformance vectors.

Version 3 keeps five things apart, in this order: what the issuer authenticated, what the evaluator observed, which
policy produced the verdict, who authorised the money and under which limit, and what trust remains; it records who
controls each judge that spoke, and it lists every amendment of the order's terms with its transaction. Version 2 has
four of the parts (no commercial authorisation, no record of the judges' control) and version 1 none; both still
check (`check` reads all three), `upgrade` writes a version 1 receipt as version 2 and `build3` a version 2 one as 3.

Version 4 says the verdict in one of four words (accepted, rejected, insufficient evidence, disputed), names the
deliverable, the evaluation, the invoice line and the settlement by ids of their own (knos.ids), names its evidence
source, and lists its `limitations`: what this evidence does not show. A receipt of a run that was rejected or could
not tell is a valid receipt and says so; only an accepted one authorises payment (`authorises_payment`). `build4`
writes a version 3 receipt as version 4, `unpaid4` a receipt of a run nothing was paid for, `dispute` a contested one.

Version 5 adds `assurance`: how much was verified, as one of four levels (reported, rerun, agreed, attested) that
`assurance_of` computes from the receipt's own evidence, the parties still trusted at that level, and the control
relationships the terms declare ("these accounts are one party"). `build5` writes a version 4 receipt as version 5;
`assurance_of` reads the level of a receipt of any version (an older one is `reported` unless its evidence shows more).

`parts` reads a receipt of version 4 or 5 in five parts, each one line: Identity, Execution, Acceptance, Consequence,
Assurance (the level, and what stayed trusted or outside the evaluation). It is a view, not a version: `explain`
prints it (`knos receipt explain FILE`), and an acceptance that stands on a weak test reads WEAK however valid its
signature.

`check` is the whole rule set (the schema's shape and the rules a schema cannot say: shares add up, amounts add up,
the judge matches the order). It needs no package. `render` is the receipt for a person, under the five headings.
`mirror_write` / `mirror_find` keep receipts off chain (devnet can be reset); `attest` writes one as a Solana
Attestation Service attestation and never raises."""
from __future__ import annotations

import hashlib
import json
import re

from . import ids as _ids

TYPE, VERSION = "knos.acceptance-receipt", 4          # `check` still reads versions 1, 2 and 3, and version 5 (`build5`)
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
    """None when `r` is a valid receipt of version 1, 2, 3, 4 or 5; otherwise the first reason it is not, in words."""
    if isinstance(r, dict) and r.get("type") == TYPE and (type(r.get("version")) is not int or r["version"] not in (1, 2, 3, 4, 5)):
        return f"not a {TYPE} of version 1, 2 or 3, or of version 4 or 5"
    if isinstance(r, dict) and r.get("type") == TYPE and r["version"] == 5:
        return _check5(r)
    if isinstance(r, dict) and r.get("type") == TYPE and r["version"] == 4:
        return _check4(r)
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
DECLARED_RELATED = ("These judges are not independent of each other: the terms declare accounts {a} and {b} to be one party. Count this quorum "
                    "as one judge.")
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


def independence_of(evaluators: list[dict], declared=()) -> tuple[bool, str]:
    """(whether two of the judges share an owner or a starter, the sentence a receipt says about it). `declared`: the
    groups of account ids the terms declare to be one party (`related`); two judges whose accounts fall in one group
    share a controller as surely as two that share an id, and the sentence names the two accounts and says who said so."""
    seen: dict[int, int] = {}
    for i, e in enumerate(evaluators):
        for who in sorted({e["owner_id"], e["actor_id"]}):
            if seen.setdefault(who, i) != i:
                return True, SAME_CONTROLLER.format(id=who)
    one = _party(declared)
    told: dict[int, tuple[int, int]] = {}
    for i, e in enumerate(evaluators):
        for who in sorted({e["owner_id"], e["actor_id"]}):
            first = told.setdefault(one(who), (i, who))
            if first[0] != i:
                return True, DECLARED_RELATED.format(a=first[1], b=who)
    return False, ONE_JUDGE if len(evaluators) == 1 else APART.format(n=len(evaluators))


def related(declared) -> list[list[int]]:
    """A declared list of control relationships in its one written form: groups of account ids that are one party,
    merged where they overlap, each group and the list in rising order. The terms declare them ("these accounts are
    one party"); nothing here can find a relationship nobody declared. ValueError for what is not such a list."""
    if not isinstance(declared, (list, tuple)) or not all(isinstance(g, (list, tuple)) and len(g) >= 2 and all(type(x) is int and x > 0 for x in g) for g in declared):
        raise ValueError("declared control relationships are lists of two or more account ids each: [[7001, 8002], ...]")
    groups: list[set[int]] = []
    for g in declared:
        mine = set(g)
        for other in [x for x in groups if x & mine]:
            mine |= other
            groups.remove(other)
        groups.append(mine)
    return sorted(sorted(g) for g in groups)


def _party(declared):
    """account id -> the party it belongs to (the smallest id of its declared group, or itself)."""
    of = {x: g[0] for g in related(declared) for x in g}
    return lambda who: of.get(who, who)


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
    if r.get("version") not in (3, 4, 5) or not isinstance(o, dict) or not isinstance(o.get("evaluators"), list):
        return r
    out = {**r, "evaluator_observed": {**o, "evaluators": [{k: v for k, v in e.items() if k != "reexecution"} if isinstance(e, dict) else e
                                                           for e in o["evaluators"]]}}
    if r["version"] == 5 and isinstance(r.get("assurance"), dict):     # the level follows from the evidence left: without the runs' words, reported
        out["assurance"] = assurance_of(out, r["assurance"].get("declared_related") or ())
    return out


def as2(r: dict) -> dict:
    """The version 2 receipt a version 3 one holds (the same payment, without the fifth part and the judges' control);
    a receipt of version 1 or 2 as it is. What a reader that knows version 2 only is given."""
    if r.get("version") in (4, 5):
        r3 = as3(r)
        return as2(r3) if r3 else r
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


# ---- version 4: four verdicts, four ids, the evidence source and what the evidence does not show ---------------------------
NEW4 = ("ids", "evidence_source", "limitations", "disputed")
_KEYS4 = (*_KEYS3, *NEW4)
CONCLUSIONS = ("passed", "failed", "missing")       # of one named check: it passed, it failed, or no run of it was found
EVIDENCE = ("issuer_token", "run_record")           # a token the issuer signed and knos_oidc verified; or the run's own record, signed by nobody
CONTESTERS = ("buyer", "supplier", "evaluator", "other")
NOT_SIGNED = "No issuer signed for this evaluator: who controls it is not recorded, and its independence of the buyer and the seller cannot be computed."
_L_TOKEN = "The issuer signs which workflow ran, in which repository and run, not what it read, ran or concluded."
_L_RECORD = "No issuer signed this: the verdict is the run's own record, and whoever controls the run or its record could have written another."
_L_POLICY = "The verdict is the pinned workflow's under the policy named here. It does not show that the policy asked for the right thing."
_L_MODE = {"merge": "In merge mode the merge is the acceptance: no test was run for this receipt, and it does not show that the code works.",
           "tests": "The named checks are what was looked at, at this commit and in the run's own environment. Nothing outside them was looked at."}
_L_VERDICT = {"accepted": "Accepted means the policy's conditions were met at this commit. It does not show that the work has no defect.",
              "rejected": "Rejected means the policy's conditions were not met at this commit, as this evaluator saw it. It does not show that the work is wrong. "
                          "It authorises no payment.",
              "insufficient_evidence": "The evaluation could not tell. This is not an acceptance and not a failure of the supplier. It authorises no payment.",
              "disputed": "This verdict is contested and not resolved. It does not show which side is right. It authorises no payment until it is resolved."}
_L_RERUN = "This receipt does not record whether the evaluator ran the acceptance suite itself or read another run's record."
_L_UNPAID = "No payment is recorded here: this receipt does not show that anything was paid, or that anything is owed."


def limitations_of(source: str, verdict: str, mode: str, reran: bool, paid: bool) -> list[str]:
    """What the evidence of a receipt does not show, in plain sentences. It follows from the evidence source, the
    verdict, how the order is judged, whether the evaluator's entry says how it reached its verdict (`reran`), and
    whether money moved, so a receipt cannot leave one out: `check` compares. A receipt may add its own after these."""
    return [_L_TOKEN if source == "issuer_token" else _L_RECORD, _L_POLICY, _L_MODE[mode], _L_VERDICT[verdict], *([] if reran else [_L_RERUN]),
            *([] if paid else [_L_UNPAID])]


def trust_unsigned(mode: str) -> list[str]:
    """What a reader of a receipt no issuer signed still has to trust."""
    return ["The run's own record and wherever it is kept: nothing here is signed by an issuer.",
            "The code of the workflow at the commit named above: it decides what counts as accepted. Read it at that commit.",
            *(["The administrators of the repository: in merge mode the merge is the acceptance, and whoever may merge or change the branch rules can accept."]
              if mode == "merge" else [])]


def ids_of(r: dict, milestone: int, invoice_line: str | None = None) -> dict:
    """The four ids of a receipt (knos.ids), from its own fields: the deliverable is the order and the milestone; the
    evaluation is that deliverable, the commit, the terms' hash, the evaluator as `<judge>@<version>` and the run (the
    run the issuer signed for; for a run's own record, the record's sha256, or nothing); the settlement is the paying
    transaction, null when nothing was paid. The invoice line is the supplier's and is passed in, or null."""
    o, a, src = r["evaluator_observed"], r["issuer_authenticated"], r.get("evidence_source") or {}
    dlv = _ids.deliverable(_ids.order_scope(r["order"]), milestone)
    run = (a["claims"]["pipeline_id" if a["provider"] == "gitlab" else "run_id"] if a else src.get("reference") or "")
    return {"deliverable": dlv,
            "evaluation": _ids.evaluation(dlv, o["artifact"]["commit"], r["policy"]["terms_hash"], f"{o['judge']['kind']}@{o['judge']['version']}", run),
            "invoice_line": invoice_line, "settlement": _ids.settlement(dlv, "chain", r["transaction"]["signature"]) if r["transaction"] else None}


def _finish4(r: dict, milestone: int, invoice_line: str | None, more) -> dict:
    o = r["evaluator_observed"]
    r["ids"] = ids_of(r, milestone, invoice_line)
    r["limitations"] = [*limitations_of(r["evidence_source"]["kind"], o["verdict"], r["policy"]["mode"],
                                        bool(o["evaluators"]) and "reexecution" in o["evaluators"][-1], r["transaction"] is not None), *more]
    r = {k: r[k] for k in _KEYS4}
    why = check(r)
    if why:
        raise ValueError(why)
    return r


def build4(r3: dict, *, invoice_line: str | None = None, limitations=()) -> dict:
    """A version 3 receipt (an accepted, paid deliverable) as version 4. `invoice_line`: the id of the supplier's
    invoice line for this deliverable (knos.ids.invoice_line), when one is known. `limitations`: sentences of the
    writer's own, after the ones that follow from the receipt."""
    why = check(r3)
    if why or r3["version"] != 3:
        raise ValueError(why or "this receipt is not of version 3")
    a = r3["issuer_authenticated"]
    r = {**r3, "version": 4, "evidence_source": {"kind": "issuer_token", "reference": a["token_sha256"], "signed_by": a["issuer"]}, "disputed": None}
    return _finish4(r, r3["commercial_authorisation"]["deliverable"]["milestone"], invoice_line, limitations)


def unpaid4(*, cluster: str, program: str, order: str, scope: str, repository: dict | None, commit: str, pull_request: int, terms_hash: str, mode: str,
            judge_kind: str, judge_version: str, verdict: str, checks: list[dict], allowed_paths: list[str] | None, denied_paths: list[str] | None,
            policy_version: int | None, mint: str, decimals: int, of: int, milestone: int = 0, payees=(), amendments=(), record_sha256: str | None = None,
            issuer_authenticated: dict | None = None, commercial_authorisation: dict | None = None, evaluators=(), invoice_line: str | None = None,
            limitations=()) -> dict:
    """A receipt of an evaluation nothing was paid for: `verdict` is rejected or insufficient_evidence. It is a valid
    receipt, it says so, and it never authorises payment. `checks`: {name, conclusion: passed, failed or missing}.
    `record_sha256`: the sha256 of the run's own verdict record, when one is kept. `issuer_authenticated`: the first
    part of a version 2 receipt, when the issuer signed for the run and knos_oidc verified the token; None when
    nothing was signed, and the evidence source is then the run's own record. `payees`: {github_id, bps, to}, who
    would have been paid; their amounts are 0. `of`: the order's price."""
    ia = issuer_authenticated
    r: dict = {"type": TYPE, "version": 4, "cluster": cluster, "program": program, "order": order, "scope": scope, "repository": repository,
         "issuer_authenticated": issuer_authenticated,
         "evaluator_observed": {"judge": {"kind": judge_kind, "version": judge_version}, "verdict": verdict,
                                "checks": sorted(({"name": c["name"], "conclusion": c["conclusion"]} for c in checks), key=lambda c: c["name"]),
                                "artifact": {"commit": commit, "pull_request": pull_request}, "evaluators": list(evaluators), "same_controller": False,
                                "independence": NOT_SIGNED},
         "policy": {"terms_hash": terms_hash, "mode": mode, "allowed_paths": allowed_paths, "denied_paths": denied_paths, "version": policy_version},
         "commercial_authorisation": commercial_authorisation, "trust_remaining": [],
         "amendments": [{"kind": a["kind"], "transaction": a["transaction"], "time": a["time"], "detail": {k: str(v) for k, v in sorted(a["detail"].items())}}
                        for a in amendments],
         "payees": [{"github_id": p["github_id"], "bps": p["bps"], "amount": "0", "to": p["to"]} for p in payees],
         "amounts": {"mint": mint, "decimals": decimals, "paid": "0", "of": str(of), "fee": "0", "tip": "0"}, "transaction": None,
         "evidence_source": ({"kind": "issuer_token", "reference": ia["token_sha256"], "signed_by": ia["issuer"]} if ia is not None
                             else {"kind": "run_record", "reference": record_sha256, "signed_by": None}), "disputed": None}
    if ia is not None:
        f, src = (commercial_authorisation or {}).get("funder") or {}, (commercial_authorisation or {}).get("source") or {}
        twin = _twin3({**r, "ids": None, "limitations": []})
        if not isinstance(twin, dict):
            raise ValueError(twin)
        paying = _paying(as2({**twin, "evaluator_observed": {**twin["evaluator_observed"], "evaluators": [], "same_controller": False, "independence": ""}}),
                         (f.get("github_id"), src.get("owner_id")))
        judges = [*evaluators, paying]
        same, said = independence_of(judges)
        r["evaluator_observed"].update(evaluators=judges, same_controller=same, independence=said)
        r["trust_remaining"] = trust_of(ia["provider"], mode, judge_kind)
    else:
        r["trust_remaining"] = trust_unsigned(mode)
    return _finish4(r, milestone, invoice_line, limitations)


def dispute(r4: dict, *, role: str, by: str, at: int, reason: str) -> dict:
    """A version 4 receipt, contested: the same receipt with the verdict `disputed`, who contested it (`role`: buyer,
    supplier, evaluator or other; `by`: their account or name), when (`at`, seconds), why, and the receipt it contests
    (its sha256 and the verdict it gave). A payment the contested receipt recorded stays recorded: the money moved.
    The disputed receipt authorises none."""
    why = check(r4)
    if why or r4["version"] not in (4, 5) or r4["disputed"] is not None:
        raise ValueError(why or "a receipt of version 4 or 5 that is not disputed already is contested (write an older one as version 4 first: build4)")
    o = r4["evaluator_observed"]
    r = {**r4, "evaluator_observed": {**o, "verdict": "disputed"},
         "disputed": {"by": {"role": role, "id": by}, "at": at, "reason": reason, "contests": {"sha256": digest(r4), "verdict": o["verdict"]}}}
    o = r["evaluator_observed"]
    args = (r["evidence_source"]["kind"], r["policy"]["mode"], bool(o["evaluators"]) and "reexecution" in o["evaluators"][-1], r["transaction"] is not None)
    own = r4["limitations"][len(limitations_of(args[0], r4["evaluator_observed"]["verdict"], *args[1:])):]
    r["limitations"] = [*limitations_of(args[0], o["verdict"], *args[1:]), *own]
    why = check(r)
    if why:
        raise ValueError(why)
    return r


def contested(r: dict) -> dict | None:
    """The receipt a disputed receipt contests, rebuilt from it (its digest is `disputed.contests.sha256`); None for a
    receipt that is not disputed."""
    if not isinstance(r, dict) or r.get("version") not in (4, 5) or not isinstance(r.get("disputed"), dict):
        return None
    o, was = r["evaluator_observed"], r["disputed"]["contests"]["verdict"]
    args = (r["evidence_source"]["kind"], r["policy"]["mode"], bool(o["evaluators"]) and "reexecution" in o["evaluators"][-1], r["transaction"] is not None)
    own = r["limitations"][len(limitations_of(args[0], "disputed", *args[1:])):]
    return {**r, "evaluator_observed": {**o, "verdict": was}, "disputed": None, "limitations": [*limitations_of(args[0], was, *args[1:]), *own]}


def verdict_of(r: dict) -> str:
    """The verdict of a valid receipt of any version, in one of the four words. Versions 1 to 3 are receipts of an
    accepted payment only."""
    return r["evaluator_observed"]["verdict"] if r["version"] >= 4 else "accepted"


def authorises_payment(r) -> bool:
    """Whether this receipt may stand behind a payment: it is valid and its verdict is accepted. A receipt that says
    rejected, insufficient evidence or disputed is a valid record and authorises nothing."""
    return check(r) is None and verdict_of(r) in _ids.BILLABLE


def exposed(r: dict) -> dict:
    """The six things every receipt answers, whatever its version: the artifact, the policy version, the evidence
    source, the evaluator, the verdict and the limitations. An older receipt did not write the last two in these
    words; they are what the same rules give for it."""
    two = as2(as3(r) or r) if r["version"] >= 3 else r
    if r["version"] == 1:
        j = r["judge"]
        art, pol, kind, ver, mode = r["artifact"], {"terms_hash": r["terms"]["hash"], "version": None}, j["kind"], j["claims"]["job_workflow_sha"], r["terms"]["mode"]
        src = {"kind": "issuer_token", "reference": j["token_sha256"], "signed_by": j["issuer"]}
    else:
        o, a = two["evaluator_observed"], two["issuer_authenticated"]
        art, pol, kind, ver, mode = o["artifact"], {"terms_hash": two["policy"]["terms_hash"], "version": two["policy"]["version"]}, o["judge"]["kind"], o["judge"]["version"], two["policy"]["mode"]
        src = r["evidence_source"] if r["version"] >= 4 else {"kind": "issuer_token", "reference": a["token_sha256"], "signed_by": a["issuer"]}
    judges = r["evaluator_observed"].get("evaluators", []) if r["version"] >= 3 else []
    return {"artifact": art, "policy": pol, "evidence_source": src, "evaluator": {"kind": kind, "version": ver, "controllers": judges},
            "verdict": verdict_of(r),
            "limitations": r["limitations"] if r["version"] >= 4 else limitations_of("issuer_token", "accepted", mode, bool(judges) and "reexecution" in judges[-1], True)}


def as3(r: dict) -> dict | None:
    """The version 3 receipt a version 4 one holds, when it holds one: an accepted, paid deliverable. None for a
    receipt of version 4 that is rejected, insufficient, disputed or unpaid (version 3 cannot say those), and the
    receipt itself for an older one."""
    if r.get("version") not in (4, 5):
        return r
    if r["evaluator_observed"]["verdict"] != "accepted" or r["transaction"] is None:
        return None
    return {**{k: r[k] for k in _KEYS3}, "version": 3}


def _twin3(r: dict):
    """The version 3 receipt whose rules a version 4 receipt of a signed run is held to: the same facts with the verdict
    and every check as version 3 can say them, and, when nothing was paid, a stand-in payment (never shown, never
    stored). A string instead, the reason, when the receipt is not shaped for one."""
    o, m, p, a = r["evaluator_observed"], r["amounts"], r["payees"], r["issuer_authenticated"]
    ch = o.get("checks") if isinstance(o, dict) else None
    if not isinstance(o, dict) or not isinstance(ch, list) or not all(isinstance(c, dict) for c in ch):
        return "evaluator_observed is an object, and its checks a list of {name, conclusion}"
    t = {**{k: r[k] for k in _KEYS3}, "version": 3, "evaluator_observed": {**o, "verdict": "accepted", "checks": [{**c, "conclusion": "passed"} for c in ch]}}
    if r["transaction"] is not None:
        return t
    if not isinstance(m, dict) or not isinstance(p, list) or not all(isinstance(e, dict) and e.get("amount") == "0" and type(e.get("bps")) is int for e in p) \
            or [m.get(k) for k in ("paid", "fee", "tip")] != ["0", "0", "0"] or not (isinstance(m.get("of"), str) and _UNITS.match(m["of"])):
        return "a receipt with no payment has transaction null, amounts.paid, fee and tip \"0\", and every payee's amount \"0\""
    exp = a["claims"].get("exp") if isinstance(a, dict) and isinstance(a.get("claims"), dict) else 0
    t["payees"] = [{**e, "amount": str(e["bps"])} for e in p] or [{"github_id": 1, "bps": 10_000, "amount": "10000", "to": r["program"]}]
    t["amounts"] = {**m, "paid": "10000", "of": str(max(int(m["of"]), 10_000))}
    t["transaction"] = {"signature": "1" * 64, "slot": 0, "time": exp if type(exp) is int else 0}
    if r["commercial_authorisation"] is None:
        d = r["ids"].get("deliverable") if isinstance(r.get("ids"), dict) else None
        pr = o["artifact"].get("pull_request") if isinstance(o.get("artifact"), dict) else 0
        ms = pr if isinstance(r["order"], str) and _ADDR.match(r["order"]) and type(pr) is int and pr and d == _ids.deliverable(_ids.order_scope(r["order"]), pr) else 0
        t["commercial_authorisation"] = authorisation(order=r["order"], milestone=ms, funded_tx=None, wallet=r["program"], address=r["program"])
    return t


def _check_unsigned(r: dict) -> str | None:
    """The rules of a version 4 receipt no issuer signed (its evidence is the run's own record)."""
    def keys(obj, want, where):
        if not isinstance(obj, dict):
            return f"{where} is not an object"
        return None if set(obj) == set(want) else f"{where} has fields {sorted(set(obj) ^ set(want))} missing or unknown"
    def whole(v):
        return type(v) is int and v >= 0
    def globs(v):
        return v is None or (isinstance(v, list) and all(isinstance(g, str) for g in v) and v == sorted(set(v)))
    if r["cluster"] not in ("devnet", "mainnet-beta", "localnet"):
        return "cluster is devnet, mainnet-beta or localnet"
    if not all(isinstance(r[k], str) and _ADDR.match(r[k]) for k in ("program", "order")) or not (isinstance(r["scope"], str) and _HEX32.match(r["scope"])):
        return "program and order are base58 addresses and scope is 64 lowercase hex characters"
    repo = r["repository"]
    if repo is not None and (keys(repo, ("id", "issue"), "repository") or not (whole(repo["id"]) and repo["id"] > 0 and whole(repo["issue"]))):
        return "repository is null (a private order) or {id, issue}, both whole numbers"
    if repo is not None and hashlib.sha256(b"knos3:scope" + repo["id"].to_bytes(8, "little") + repo["issue"].to_bytes(8, "little")).hexdigest() != r["scope"]:
        return "scope is not sha256(\"knos3:scope\" || repository id || issue) of the repository named"
    o, p, m = r["evaluator_observed"], r["policy"], r["amounts"]
    why = (keys(o, ("judge", "verdict", "checks", "artifact", "evaluators", "same_controller", "independence"), "evaluator_observed")
           or keys(o["judge"], ("kind", "version"), "evaluator_observed.judge") or keys(o["artifact"], ("commit", "pull_request"), "artifact")
           or keys(p, ("terms_hash", "mode", "allowed_paths", "denied_paths", "version"), "policy") or keys(m, ("mint", "decimals", "paid", "of", "fee", "tip"), "amounts"))
    if why:
        return why
    if not isinstance(o["checks"], list):
        return "evaluator_observed.checks are {name, conclusion: passed, failed or missing}, in order of name, each once"
    if o["judge"]["kind"] not in JUDGES or not (isinstance(o["judge"]["version"], str) and _HEX40.match(o["judge"]["version"])):
        return "evaluator_observed.judge is {kind: repository, neutral, attestor or arbiter, version: the workflow's commit, 40 lowercase hex characters}"
    if not (isinstance(o["artifact"]["commit"], str) and _HEX40.match(o["artifact"]["commit"]) and whole(o["artifact"]["pull_request"])):
        return "artifact.commit is 40 lowercase hex characters and artifact.pull_request a whole number"
    if not (isinstance(p["terms_hash"], str) and _HEX32.match(p["terms_hash"])) or p["mode"] not in MODES:
        return "terms.hash is 64 lowercase hex characters and terms.mode is merge or tests"
    if not (globs(p["allowed_paths"]) and globs(p["denied_paths"])) or (p["version"] is not None and p["version"] != 1) or type(p["version"]) is bool \
            or len({p["allowed_paths"] is None, p["denied_paths"] is None, p["version"] is None}) != 1:
        return "policy.allowed_paths and policy.denied_paths are sorted lists of globs and policy.version is 1; all three are null when the terms are not public"
    if o["evaluators"] != [] or o["same_controller"] is not False or o["independence"] != NOT_SIGNED or r["commercial_authorisation"] is not None:
        return ("a receipt no issuer signed names no controller of its evaluator and no funder: evaluator_observed.evaluators is empty, same_controller false, "
                "independence the sentence for it (knos.receipt.NOT_SIGNED), and commercial_authorisation null")
    if r["trust_remaining"] != trust_unsigned(p["mode"]):
        return "trust_remaining is the list this kind of receipt leaves (knos.receipt.trust_unsigned): none may be left out"
    am, last = r["amendments"], 0
    if not isinstance(am, list):
        return "amendments is a list"
    for e in am:
        if (keys(e, ("kind", "transaction", "time", "detail"), "an amendment") or e["kind"] not in AMENDMENTS
                or not (isinstance(e["transaction"], str) and _SIG.match(e["transaction"])) or type(e["time"]) is not int or e["time"] < last
                or not isinstance(e["detail"], dict) or not all(isinstance(k, str) and isinstance(x, str) for k, x in e["detail"].items())):
            return "an amendment is {kind: topup, assign, reserve, cancel or plan, transaction, time, detail of strings}, oldest first"
        last = e["time"]
    pay = r["payees"]
    if not isinstance(pay, list) or len(pay) > 4 or any(
            keys(e, ("github_id", "bps", "amount", "to"), "a payee") or not (whole(e["github_id"]) and e["github_id"] > 0 and whole(e["bps"]) and 1 <= e["bps"] <= 10_000
                                                                            and e["amount"] == "0" and isinstance(e["to"], str) and _ADDR.match(e["to"])) for e in pay) \
            or (pay and sum(e["bps"] for e in pay) != 10_000):
        return "the payees of a receipt with no payment are none, or up to four {github_id, bps, amount \"0\", to} whose shares add up to 10000"
    if not (isinstance(m["mint"], str) and _ADDR.match(m["mint"]) and whole(m["decimals"]) and m["decimals"] <= 18 and isinstance(m["of"], str) and _UNITS.match(m["of"])
            and [m["paid"], m["fee"], m["tip"]] == ["0", "0", "0"]):
        return "a receipt with no payment has transaction null, amounts.paid, fee and tip \"0\", and every payee's amount \"0\""
    return None


def _check4(r) -> str | None:
    def keys(obj, want, where):
        if not isinstance(obj, dict):
            return f"{where} is not an object"
        return None if set(obj) == set(want) else f"{where} has fields {sorted(set(obj) ^ set(want))} missing or unknown"
    why = keys(r, _KEYS4, "the receipt")
    if why:
        return f"not a {TYPE} of version 1, 2 or 3, or of version 4: as version 4, {why}"
    o, src, x, a = r["evaluator_observed"], r["evidence_source"], r["transaction"], r["issuer_authenticated"]
    verdict = o.get("verdict") if isinstance(o, dict) else None
    if not isinstance(verdict, str) or verdict not in _ids.VERDICTS:
        return "evaluator_observed.verdict is accepted, rejected, insufficient_evidence or disputed"
    paid = x is not None
    if keys(src, ("kind", "reference", "signed_by"), "evidence_source") or src["kind"] not in EVIDENCE:
        return "evidence_source is {kind: issuer_token or run_record, reference, signed_by}"
    if (src["kind"] == "issuer_token") != (a is not None):
        return "evidence_source.kind is issuer_token when issuer_authenticated is there, and run_record when it is null"
    if verdict == "accepted" and not (paid and a is not None):
        return "an accepted receipt records the token the issuer signed and the payment it authorised: a run's own record accepts nothing"
    if verdict in ("rejected", "insufficient_evidence") and paid:
        return "a receipt that says rejected or insufficient_evidence authorises no payment and records none: its transaction is null"
    # everything versions 1 to 3 said, by the same rules; or the rules of a receipt nobody signed
    if a is not None:
        twin = _twin3(r)
        why = twin if isinstance(twin, str) else _check3(twin)
    else:
        why = _check_unsigned(r)
    if why:
        return why
    # the checks, in the receipt's own words
    ch = o["checks"]
    if any(keys(e, ("name", "conclusion"), "a check") or not isinstance(e["name"], str) or not e["name"] or e["conclusion"] not in CONCLUSIONS for e in ch) \
            or [e["name"] for e in ch] != sorted({e["name"] for e in ch}):
        return "evaluator_observed.checks are {name, conclusion: passed, failed or missing}, in order of name, each once"
    if verdict == "accepted" and any(e["conclusion"] != "passed" for e in ch):
        return "an accepted receipt has every named check passed"
    # the evidence source
    hex_or_none = src["reference"] is None or (isinstance(src["reference"], str) and bool(_HEX32.match(src["reference"])))
    if (a is not None and (src["reference"], src["signed_by"]) != (a["token_sha256"], a["issuer"])) or (a is None and not (hex_or_none and src["signed_by"] is None)):
        return ("evidence_source names the token (reference: its sha256, signed_by: its issuer) for issuer_token; for run_record, reference is the sha256 of "
                "the run's record or null, and signed_by null")
    # the four ids
    got = r["ids"]
    why = keys(got, ("deliverable", "evaluation", "invoice_line", "settlement"), "ids")
    if why:
        return why
    for kind, value, may_be_null in (("deliverable", got["deliverable"], False), ("evaluation", got["evaluation"], False),
                                     ("invoice_line", got["invoice_line"], True), ("settlement", got["settlement"], True)):
        if not (value is None and may_be_null):
            try:
                _ids.expect(kind, value)
            except ValueError as said:
                return f"ids.{kind}: {said}"
    c, pr = r["commercial_authorisation"], o["artifact"]["pull_request"]
    try:
        want = [ids_of(r, ms, got["invoice_line"]) for ms in ([c["deliverable"]["milestone"]] if c is not None else sorted({0, pr}))]
    except ValueError:
        return "order is the address of an order account: 32 bytes in base58"
    if got not in want:
        return ("ids are the ones the receipt's own fields give (knos.receipt.ids_of): the deliverable of this order and milestone, the evaluation of this "
                "commit, terms, evaluator and run, and the settlement of this transaction, null when nothing was paid")
    # what the evidence does not show
    lim = r["limitations"]
    base = limitations_of(src["kind"], verdict, r["policy"]["mode"], bool(o["evaluators"]) and "reexecution" in o["evaluators"][-1], paid)
    if not isinstance(lim, list) or lim[:len(base)] != base or not all(isinstance(s, str) and 0 < len(s) <= 400 for s in lim) or len(lim) > len(base) + 8:
        return ("limitations begins with the sentences this evidence leaves (knos.receipt.limitations_of), none left out, then at most eight of the "
                "writer's own")
    # a dispute
    d = r["disputed"]
    if (verdict == "disputed") != (d is not None):
        return "disputed is null unless the verdict is disputed, and a disputed receipt says who contested it, when, why, and which receipt"
    if d is not None:
        if keys(d, ("by", "at", "reason", "contests"), "disputed") or keys(d["by"], ("role", "id"), "disputed.by") or keys(d["contests"], ("sha256", "verdict"), "disputed.contests") \
                or d["by"]["role"] not in CONTESTERS or not (isinstance(d["by"]["id"], str) and 0 < len(d["by"]["id"]) <= 100) or type(d["at"]) is not int or d["at"] < 0 \
                or not (isinstance(d["reason"], str) and 0 < len(d["reason"]) <= 500) or d["contests"]["verdict"] not in _ids.VERDICTS[:3]:
            return ("disputed is {by: {role: buyer, supplier, evaluator or other, id}, at: seconds, reason, contests: {sha256, verdict: the verdict "
                    "contested}}")
        was = contested(r) or {}
        if d["contests"]["sha256"] != digest(was) or _check4(was) is not None:
            return "disputed.contests.sha256 is the digest of the receipt contested: this receipt with that verdict, and no dispute"
        if paid and d["at"] < x["time"]:
            return "a payment is contested after it was made: disputed.at is before the transaction"
    return None


# ---- version 5: how much was verified (the assurance level), and the control relationships the terms declare --------------
NEW5 = ("assurance",)
_KEYS5 = (*_KEYS4, *NEW5)
LEVELS = ("reported", "rerun", "agreed", "attested")        # in rising order; each is computed from the evidence, never written by hand
LEVEL_WORDS = {"reported": "a workflow reported the result",
               "rerun": "an evaluator outside the supplier's control ran the pinned suite again",
               "agreed": "two evaluators with different owners each ran the suite and agree",
               "attested": "an attestation of the execution itself stands behind the result"}
UNREACHABLE = ("attested",)       # defined, and no evidence Knos records today reaches it: no receipt may say it until an attestation of execution exists
_T_ISSUER = "The issuer, for which workflow ran, in which repository and run. It did not sign what the run read, ran or concluded."
_T_POLICY = "Whoever wrote the terms: the level says how the result was checked, not that the terms asked for the right thing."
TRUSTED = {
    "reported": [_T_ISSUER, "The run that reported the result, and whoever controls its repository, its workflow and its runner: the result is that run's word.",
                 "The supplier, as far as the suite ran where the supplier's change could reach it.", _T_POLICY],
    "rerun": [_T_ISSUER, "The one evaluator that ran the suite again, its operator and its runner: nobody else repeated it.", _T_POLICY],
    "agreed": [_T_ISSUER, "That the evaluators which agree are not one party behind accounts nobody declared related: ids and declarations are all that is compared.",
               "The runners the evaluators ran on.", _T_POLICY],
    "attested": ["The root the attestation chains to, and the maker of the hardware or prover behind it.", _T_POLICY],
}
_T_UNSIGNED = "Whoever keeps the run's own record: no issuer signed it, so not even which workflow ran is authenticated."


def assurance_of(r: dict, declared=()) -> dict:
    """How much a valid receipt of any version shows was verified, from its own evidence: {level, trusted,
    declared_related}. Nothing here is typed by anyone:

        reported   a workflow reported the result. Every receipt reaches this, and a receipt of version 1 or 2, or one
                   whose evaluators' entries say nothing of how they reached the verdict, reaches no more.
        rerun      an evaluator outside the order's repository, whose owner and starter are neither a payee nor declared
                   one party with a payee, says by its run's word that it ran the pinned suite itself.
        agreed     two such evaluators, with different owners and starters and not declared one party, each ran it, and
                   the verdict they stand behind is accepted. Two that share an id, or that the terms declare related,
                   never agree: they are one evaluator.
        attested   an attestation of the execution itself. Defined and unreachable: no evidence recorded today is one.

    `declared`: the control relationships the terms declare (`related`); a version 5 receipt carries its own.
    `trusted`: the parties a reader still trusts at that level."""
    groups = related(declared)
    one = _party(groups)
    o = r["evaluator_observed"] if r["version"] >= 2 else {}
    judges = o.get("evaluators") or [] if r["version"] >= 3 else []
    sellers = {one(p["github_id"]) for p in r["payees"]}
    signed = r["version"] < 4 or r["issuer_authenticated"] is not None

    def party(e: dict) -> set[int]:
        return {one(e["owner_id"]), one(e["actor_id"])}
    ran = [e for e in judges if e["kind"] != "repository" and e["independent_of_seller"] and not (party(e) & sellers)
           and (e.get("reexecution") or {}).get("reexecuted") is True]
    was = (r["disputed"]["contests"]["verdict"] if r["disputed"] else o["verdict"]) if r["version"] >= 4 else "accepted"
    both = was == "accepted" and any(not (party(a) & party(b)) for n, a in enumerate(ran) for b in ran[n + 1:])
    level = "agreed" if both else "rerun" if ran else "reported"
    return {"level": level, "trusted": list(TRUSTED[level]) if signed else [_T_UNSIGNED, *TRUSTED[level][1:]], "declared_related": groups}


def build5(r4: dict, declared=()) -> dict:
    """A version 4 receipt as version 5: the same receipt with `assurance`, computed here from its evidence and the
    control relationships the terms declare (`declared`: groups of account ids that are one party). An older receipt
    goes through `build4` first. A disputed receipt then contests the version 5 form of the receipt it contested."""
    why = check(r4)
    if why or r4["version"] != 4:
        raise ValueError(why or "this receipt is not of version 4")
    r = {**r4, "version": 5, "assurance": assurance_of(r4, declared)}
    r = {k: r[k] for k in _KEYS5}
    if r["disputed"] is not None:           # a disputed receipt contests the same receipt in this version: `build5` of the one it contested
        r["disputed"] = {**r["disputed"], "contests": {**r["disputed"]["contests"], "sha256": digest(contested(r) or {})}}
    why = check(r)
    if why:
        raise ValueError(why)
    return r


def as4(r: dict) -> dict:
    """The version 4 receipt a version 5 one holds (the same facts without the assurance level); an older receipt as it
    is. A disputed one names the digest of the version 4 receipt it then contests."""
    if r.get("version") != 5:
        return r
    out = {**{k: r[k] for k in _KEYS4}, "version": 4}
    if isinstance(out["disputed"], dict):
        was = contested(out)
        out["disputed"] = {**out["disputed"], "contests": {**out["disputed"]["contests"], "sha256": digest(was) if was else ""}}
    return out


def _check5(r) -> str | None:
    if not isinstance(r, dict) or set(r) != set(_KEYS5):
        return f"not a {TYPE} of version 1 to 5: as version 5, the receipt has fields {sorted(set(r) ^ set(_KEYS5))} missing or unknown"
    try:
        four = as4(r)
    except (KeyError, TypeError, AttributeError):
        four = {**{k: r[k] for k in _KEYS4}, "version": 4}          # not shaped for a dispute: version 4's rules say what is wrong
    why = _check4(four)
    if why:
        return why
    if r["disputed"] is not None and r["disputed"]["contests"]["sha256"] != digest(contested(r) or {}):
        return "disputed.contests.sha256 is the digest of the receipt contested: this receipt with that verdict, and no dispute"
    a = r["assurance"]
    if not isinstance(a, dict) or set(a) != {"level", "trusted", "declared_related"}:
        return "assurance is {level: reported, rerun, agreed or attested, trusted: who is still trusted at that level, declared_related: groups of account ids}"
    try:
        groups = related(a["declared_related"])
    except ValueError as said:
        return f"assurance.declared_related: {said}"
    if groups != a["declared_related"] or len(groups) > 16 or any(len(g) > 16 for g in groups):
        return "assurance.declared_related is at most 16 groups of at most 16 account ids, each group and the list in rising order, no account in two groups"
    if a["level"] in UNREACHABLE:
        return "assurance.level attested is defined and nothing recorded today reaches it: no receipt says it until an attestation of execution exists"
    if a != assurance_of(r, groups):
        return ("assurance is computed from the evidence, not chosen (knos.receipt.assurance_of): reported unless an evaluator outside the supplier's "
                "control ran the suite itself (rerun), or two such with different owners, not declared related, agree (agreed)")
    return None


def _assured(a: dict, judges: list[dict]) -> list[str]:
    """The assurance of a version 5 receipt in lines."""
    said = "; ".join(" and ".join(str(x) for x in g) for g in a["declared_related"])
    same, why = independence_of(judges, a["declared_related"]) if judges else (False, "")
    return [f"   Assurance: {a['level']} ({LEVEL_WORDS[a['level']]}).",
            "   Accounts the terms declare to be one party: " + (said + "." if said else "none declared."),
            *([f"   DECLARED RELATED. {why}"] if same and why.startswith(DECLARED_RELATED[:40]) else []),
            "   Still trusted at this level:", *(f"   - {t}" for t in a["trusted"])]


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


def _render4(r: dict) -> list[str]:
    """A version 4 receipt in lines: the verdict and whether it authorises payment first, then the ids, the evidence
    source, the parts versions 1 to 3 print (as far as this receipt has them), and what the evidence does not show."""
    o, a, p, src, got, d, m = r["evaluator_observed"], r["issuer_authenticated"], r["policy"], r["evidence_source"], r["ids"], r["disputed"], r["amounts"]
    word = _ids.VERDICT_WORDS[o["verdict"]]
    out = [f"Acceptance receipt, version {r['version']}: order {r['order']} on {r['cluster']}", "",
           f"Verdict: {word}. " + ("This receipt authorises the payment it records." if o["verdict"] == "accepted" else "This receipt authorises no payment."),
           *(_assured(r["assurance"], o["evaluators"]) if r["version"] == 5 else []),
           f"   Deliverable {got['deliverable']}, evaluation {got['evaluation']}.",
           f"   Invoice line {got['invoice_line'] or 'not named'}; settlement {got['settlement'] or 'none: nothing was paid'}.",
           ("   Evidence: a token the issuer signed" + f" ({src['signed_by']}), recognised by sha256 {src['reference']}." if a is not None
            else "   Evidence: the run's own record, signed by nobody" + (f" (sha256 {src['reference']})." if src["reference"] else " (no copy of it is named).")),
           f"   Artifact: commit {o['artifact']['commit']}, pull request {o['artifact']['pull_request']}.",
           f"   Evaluator: {o['judge']['kind']}, workflow version {o['judge']['version']}.",
           f"   Policy: terms {p['terms_hash']}, mode {p['mode']}, version {p['version'] if p['version'] is not None else 'not public'}.",
           ("   Named checks: none were required." if not o["checks"] else "   Named checks: " + "; ".join(f"{e['name']}: {e['conclusion']}" for e in o["checks"]) + ".")]
    if d is not None:
        out += [f"   Contested by the {d['by']['role']} ({d['by']['id']}) at {_utc(d['at'])}: {d['reason']}",
                f"   It contests the receipt sha256:{d['contests']['sha256']}, whose verdict was {_ids.VERDICT_WORDS[d['contests']['verdict']]}."]
    out += ["", "What this evidence does not show", *(f"   - {s}" for s in r["limitations"])]
    if a is not None and r["transaction"] is not None:      # everything a version 3 receipt prints, under its five headings
        body = _render3({**{k: r[k] for k in _KEYS3}, "version": 3})
        out += ["", *body[2:-2]]
    else:
        out += ["", f"5. {HEADINGS['trust_remaining']}", *(f"   - {t}" for t in r["trust_remaining"]),
                "", "Payment", f"   None. The order's price is {_money(m['of'], m['decimals'])} (mint {m['mint']}); nothing was paid under this receipt."]
    return [*out, "", f"Digest sha256:{digest(r)}"]


def render(r: dict) -> list[str]:
    """The receipt in lines a person reads. A version 4 receipt says its verdict, its ids and what its evidence does
    not show first (`_render4`); versions 1 to 3 are printed as they always were."""
    return _render4(r) if r["version"] >= 4 else _render3(r)


def _render3(r: dict) -> list[str]:
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


# ---- the five parts: one view over a receipt of version 4 or 5 ------------------------------------------------------------
FIVE = ("identity", "execution", "acceptance", "consequence", "assurance")      # in this order, everywhere
FIVE_TITLES = {"identity": "Identity", "execution": "Execution", "acceptance": "Acceptance", "consequence": "Consequence", "assurance": "Assurance"}
FIVE_ASKS = {"identity": "Who produced the evidence?", "execution": "Which evaluator ran, on which inputs?", "acceptance": "Which agreed test passed?",
             "consequence": "What became payable, and to whom?", "assurance": "What stayed trusted or outside the evaluation?"}
PARTS_KIND, PARTS_V = "knos-receipt-parts", 1
O_WORKFLOW = "The workflow file decides what it reads: the issuer signed which workflow ran, not what it read, ran or concluded."
O_UNSIGNED = "No issuer signed anything: the evidence is the run's own record, and whoever keeps it could have written another."
O_REPORTED = "Nobody outside the supplier's reach ran the checks again: the result is one run's word."
O_MERGE = "No test decided: the terms name no check, the merge alone was the acceptance, and whoever may merge can accept."
O_MERGE_TOO = "A merge was required beside the named checks: whoever may merge decides when, and whether."
O_SELLER = "The evaluator's account is the payee's: account {id} owns or started the {kind} run, and is paid by it."
O_BUYER = "The evaluator's account is the buyer's: account {id} owns or started the {kind} run, and funded the order."
O_OWN_REPO = "The order's own repository judged: the buyer chose it, and its administrators can accept."
O_ONE_PARTY = "The evaluators are one party: {why}"
O_TERMS = "Whether the terms asked for the right thing is outside the evaluation: a passing weak test is a weak acceptance."
O_DISPUTED = "The verdict is contested and not resolved: which side is right is outside this receipt."


def _short(text: str, keep: int = 12) -> str:
    return text if len(text) <= keep else text[:keep] + "…"


def _amount(units: str, decimals: int) -> str:
    """Money for a line: at least two decimals, and no more than the amount needs."""
    whole, _, part = _money(units, decimals).partition(".")
    part = part.rstrip("0")
    return f"{whole}.{part:0<2}"


def outside_of(r: dict, level: str) -> tuple[list[str], list[str]]:
    """What stayed trusted or outside the evaluation of a version 4 or 5 receipt, in plain sentences, as two lists: the
    ones that make the acceptance WEAK (each alone is enough), then the ones every receipt carries. Computed from the
    receipt's own fields and the level `assurance_of` gave: nothing here is typed by anyone."""
    o, p, c = r["evaluator_observed"], r["policy"], r["commercial_authorisation"] or {}
    sellers = {x["github_id"] for x in r["payees"]}
    buyers = {x for x in ((c.get("funder") or {}).get("github_id"), (c.get("source") or {}).get("owner_id")) if x}
    weak = [O_UNSIGNED] if r["issuer_authenticated"] is None else []
    weak += [O_REPORTED] if level == "reported" else []
    weak += [O_MERGE] if p["mode"] == "merge" and not o["checks"] else []
    for e in o["evaluators"]:
        ids = (e["owner_id"], e["actor_id"])
        weak += [O_SELLER.format(id=i, kind=e["kind"]) for i in dict.fromkeys(ids) if i in sellers]
        weak += [O_BUYER.format(id=i, kind=e["kind"]) for i in dict.fromkeys(ids) if i in buyers and e["kind"] != "repository"]
    if o["same_controller"]:
        weak.append(O_ONE_PARTY.format(why=o["independence"]))
    always = [*([O_DISPUTED] if r["disputed"] is not None else []),
              *([O_WORKFLOW] if r["issuer_authenticated"] is not None else []),
              *([O_MERGE_TOO] if p["mode"] == "merge" and o["checks"] else []),
              *([O_OWN_REPO] if any(e["kind"] == "repository" for e in o["evaluators"]) else []), O_TERMS]
    return weak, always


def parts(r: dict, declared=()) -> dict:
    """A receipt of version 4 or 5 read in five parts, each one line and the facts behind it. A VIEW: nothing is added
    to the receipt, and no new version exists. A version 3 receipt is read as the version 4 receipt `build4` makes of
    it; versions 1 and 2 are refused (they do not say who funded).

        identity      who produced the evidence: the issuer, the repository, the workflow, the run
        execution     which evaluator ran, on which inputs, by hash
        acceptance    which agreed test passed, under which terms hash
        consequence   what amount became payable, to whom, in which order
        assurance     the level, and in plain words what stayed trusted or outside the evaluation

    {kind, v, receipt: its sha256, version, verdict, authorises_payment, weak, parts: [{id, title, asks, line, facts,
    more}]}. `weak` is true when the acceptance stands on less than an evaluator outside the supplier's control
    running a test again: the assurance line then starts with WEAK, however valid the signature. `declared`: the
    control relationships the terms declare, for a version 4 receipt (a version 5 one carries its own)."""
    why = check(r)
    if why:
        raise ValueError(why)
    if r["version"] == 3:
        r = build4(r)
    if r["version"] not in (4, 5):
        raise ValueError(f"a receipt of version {r['version']} does not say who funded or what was left unshown: `knos bundle make` writes the same payment as version 5")
    o, a, p, m, src, got, d = r["evaluator_observed"], r["issuer_authenticated"], r["policy"], r["amounts"], r["evidence_source"], r["ids"], r["disputed"]
    assured = r["assurance"] if r["version"] == 5 else assurance_of(r, declared)
    level, verdict = assured["level"], o["verdict"]
    # 1. identity
    if a is not None:
        gl, cl = a["provider"] == "gitlab", a["claims"]
        host = {"github": "GitHub", "gitlab": "GitLab"}[a["provider"]]
        ident = {"signed": True, "issuer": a["issuer"], "provider": a["provider"], "repository": cl["project_id" if gl else "repository_id"],
                 "repository_name": (r["repository"] or {}).get("full_name") if isinstance(r["repository"], dict) else None,
                 "workflow": cl["ci_config_ref_uri" if gl else "job_workflow_ref"], "workflow_sha": cl["ci_config_sha" if gl else "job_workflow_sha"],
                 "run": cl["pipeline_id" if gl else "run_id"], "attempt": None if gl else cl["run_attempt"], "started_by": cl["user_id" if gl else "actor_id"],
                 "runner": cl["runner_environment"], "token_sha256": a["token_sha256"], "verified_in": a["verified"]["transaction"]}
        one = f"{host} signed: workflow {ident['workflow']} ran in repository {ident['repository']}, run {ident['run']}."
        more1 = [f"Issuer {a['issuer']}; token sha256 {a['token_sha256']}.", f"Workflow file at commit {ident['workflow_sha']}; run started by account {ident['started_by']} on a {ident['runner']} runner.",
                 f"The signature was verified on chain in transaction {ident['verified_in']}."]
    else:
        ident = {"signed": False, "issuer": None, "provider": None, "repository": None, "repository_name": None, "workflow": None, "workflow_sha": None, "run": None,
                 "attempt": None, "started_by": None, "runner": None, "token_sha256": None, "verified_in": None, "record_sha256": src["reference"]}
        one = "Nobody signed: the evidence is the run's own record."
        more1 = ["The run's record has sha256 " + src["reference"] + "." if src["reference"] else "No copy of the run's record is named."]
    # 2. execution
    reran = [e for e in o["evaluators"] if (e.get("reexecution") or {}).get("reexecuted") is True]
    images = sorted({e["reexecution"]["image_digest"] for e in reran if e["reexecution"].get("image_digest")})
    execu = {"evaluator": o["judge"]["kind"], "evaluator_version": o["judge"]["version"], "commit": o["artifact"]["commit"], "pull_request": o["artifact"]["pull_request"],
             "checks": [dict(c) for c in o["checks"]], "evaluators": [{k: e[k] for k in ("kind", "repository_id", "owner_id", "actor_id", "runner")} | {
                 "reexecuted": (e.get("reexecution") or {}).get("reexecuted")} for e in o["evaluators"]], "images": images, "evaluation": got["evaluation"]}
    two = (f"Evaluator {o['judge']['kind']}, workflow {_short(o['judge']['version'])}, read commit {_short(o['artifact']['commit'])} of pull request {o['artifact']['pull_request']}; "
           + (f"{len(reran)} of {len(o['evaluators'])} ran the suite again." if o["evaluators"] else "who controls it is not recorded."))
    more2 = [f"Inputs by hash: commit {o['artifact']['commit']}; workflow {o['judge']['version']}; terms {p['terms_hash']}" + (f"; image {', '.join(images)}." if images else "."),
             *(f"{e['kind']}: repository {e['repository_id']}, owner account {e['owner_id']}, started by account {e['actor_id']};{_reran(e.get('reexecution')) or ' how it reached its verdict is not recorded.'}"
               for e in o["evaluators"]), f"Evaluation {got['evaluation']}."]
    # 3. acceptance
    names = ", ".join(f"{c['name']}: {c['conclusion']}" for c in o["checks"])
    test = ("the acceptance suite the terms pin" if p["mode"] == "tests" else "a merge") + (f", and the named checks ({names})" if names else "")
    accept = {"verdict": verdict, "predicate": {"mode": p["mode"], "checks": [dict(c) for c in o["checks"]]}, "terms_hash": p["terms_hash"], "policy_version": p["version"],
              "allowed_paths": p["allowed_paths"], "denied_paths": p["denied_paths"], "contested": None if d is None else {"by": d["by"]["role"], "was": d["contests"]["verdict"]}}
    said = {"accepted": "Accepted: {t} passed", "rejected": "Rejected: {t} did not pass", "insufficient_evidence": "Not decided: {t} could not be read",
            "disputed": "Disputed: {t} is contested"}[verdict].format(t=test)
    three = f"{said}, under terms {_short(p['terms_hash'])}."
    more3 = [f"Terms hash {p['terms_hash']}, fixed when the order was funded; policy version {p['version'] if p['version'] is not None else 'not public'}.",
             *([f"Contested by the {d['by']['role']}: {d['reason']} The verdict before was {_ids.VERDICT_WORDS[d['contests']['verdict']]}."] if d is not None else []),
             *([] if p["allowed_paths"] is None else [f"Paths allowed: {', '.join(p['allowed_paths']) or 'any'}; protected: {', '.join(p['denied_paths'] or []) or 'none'}."])]
    # 4. consequence
    paid = r["transaction"] is not None
    money = "test money on devnet" if r["cluster"] == "devnet" else f"mint {m['mint']}"
    conseq = {"payable": m["paid"] if paid and verdict in ("accepted", "disputed") else "0", "paid": m["paid"], "of": m["of"], "fee": m["fee"], "tip": m["tip"], "decimals": m["decimals"],
              "mint": m["mint"], "order": r["order"], "payees": [dict(x) for x in r["payees"]], "transaction": r["transaction"]["signature"] if paid else None,
              "deliverable": got["deliverable"], "settlement": got["settlement"], "invoice_line": got["invoice_line"]}
    to = ", ".join(f"account {x['github_id']}" if x["github_id"] else f"wallet {_short(x['to'])}" for x in r["payees"]) or "nobody named"
    four = (f"{_amount(m['paid'], m['decimals'])} of {_amount(m['of'], m['decimals'])} paid to {to} ({money}), order {_short(r['order'])}." if paid
            else f"Nothing became payable: order {_short(r['order'])} holds {_amount(m['of'], m['decimals'])} ({money}).")
    more4 = [f"Order {r['order']}; deliverable {got['deliverable']}.",
             *([f"Paying transaction {r['transaction']['signature']}; fee {_amount(m['fee'], m['decimals'])}, tip {_amount(m['tip'], m['decimals'])}, on top of the amount."] if paid else
               ["No payment is recorded: this receipt authorises none."]),
             *(f"{_amount(x['amount'], m['decimals'])} to {x['to']}" + (f" (account {x['github_id']}, {x['bps'] / 100:g}%)." if x["github_id"] else ".") for x in r["payees"] if paid),
             *(["A payment recorded before the dispute stays recorded: the money moved."] if paid and d is not None else [])]
    # 5. assurance
    weak, always = outside_of(r, level)
    assure = {"level": level, "level_says": LEVEL_WORDS[level], "weak": bool(weak), "weak_because": weak, "outside": [*weak, *always], "trusted": list(assured["trusted"]),
              "declared_related": assured["declared_related"], "limitations": list(r["limitations"])}
    five = (f"WEAK ({level}): {weak[0]}" + (f" And {len(weak) - 1} more." if len(weak) > 1 else "") if weak
            else f"{level.capitalize()}: {LEVEL_WORDS[level]}. {always[0]}")
    more5 = [*(f"Weak because: {s}" for s in weak), *(f"Outside the evaluation: {s}" for s in always), *(f"Still trusted: {s}" for s in assured["trusted"]),
             *(f"Not shown: {s}" for s in r["limitations"])]
    rows = zip(FIVE, (one, two, three, four, five), (ident, execu, accept, conseq, assure), (more1, more2, more3, more4, more5))
    return {"kind": PARTS_KIND, "v": PARTS_V, "receipt": digest(r), "version": r["version"], "verdict": verdict, "authorises_payment": verdict in _ids.BILLABLE, "weak": bool(weak),
            "parts": [{"id": k, "title": FIVE_TITLES[k], "asks": FIVE_ASKS[k], "line": line, "facts": facts, "more": list(more)} for k, line, facts, more in rows]}


def explain(r: dict, declared=()) -> list[str]:
    """`knos receipt explain FILE`: the five parts in lines, each its one line and then what stands behind it."""
    got = parts(r, declared)
    out = [f"Acceptance receipt sha256:{got['receipt']}, version {got['version']}: {_ids.VERDICT_WORDS[got['verdict']]}; "
           + ("it authorises payment." if got["authorises_payment"] else "it authorises no payment."), ""]
    for n, part in enumerate(got["parts"], 1):
        out += [f"{n}. {part['title']}. {part['asks']}", f"   {part['line']}", *(f"   - {s}" for s in part["more"]), ""]
    return out[:-1]


def five_cells(r: dict, declared=()) -> dict:
    """The five parts of a receipt as five cells, one line each, and the receipt's sha256: what every surface a receipt
    leaves Knos by carries beside its row (an export's parts file, a statement line, the record answer)."""
    got = parts(r, declared)
    return {"receipt_sha256": got["receipt"], **{p["id"]: p["line"] for p in got["parts"]}}


def five_missing(cells: dict) -> list[str]:
    """The parts a row leaves out or empty: [] when all five are said. A surface refuses a row this names."""
    return [k for k in FIVE if not isinstance(cells.get(k), str) or not cells[k].strip()]


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
        rows = sorted(held[order].items(), key=lambda kv: (*_when(kv[1]), kv[0]))
        doc = {"type": MIRROR, "version": MIRROR_VERSION, "order": order, "receipts": [r for _, r in rows]}
        (out / f"{order}.json").write_bytes(canonical(doc) + b"\n")
        index["orders"][order] = [{"sha256": d, "transaction": (r["transaction"] or {}).get("signature"), "time": _when(r)[0], "cluster": r["cluster"]}
                                  for d, r in rows]
    (out / "index.json").write_bytes(canonical(index) + b"\n")
    return index


def _when(r: dict) -> tuple[int, int]:
    """(time, slot) a receipt is ordered by in a mirror: its payment's; for a receipt with no payment, the time it
    was contested, else the time its token was issued, else 0."""
    x, a = r["transaction"], r.get("issuer_authenticated") or r.get("judge") or {}
    if x:
        return x["time"], x["slot"]
    return ((r.get("disputed") or {}).get("at") or (a.get("claims") or {}).get("iat") or 0), 0


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
            if target in (order, (r["transaction"] or {}).get("signature")):
                out.append(r)
    return out


# ---- `knos receipt verify`: the receipt rebuilt from the chain, with an answer in a time the reader is told -----------------
# It read the escrow's newest transactions one by one. devnet's public endpoint takes 40 requests of one method per 10 s
# (https://solana.com/docs/references/clusters), so 1,000 of them take over four minutes, and said nothing all that time.
# It now reads, of those, only the transactions a receipt is built from.
VERIFY_SECONDS = 120.0
TX_VERSION = {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 1}  # what the relay sends: version 1


class NoAnswer(OSError):
    """The cluster did not answer in time. Its text is one line: where, after how long, how far, and what to try."""


def from_chain(target: str, url: str, limit: int = 1000, seconds: float = VERIFY_SECONDS, call=None, clock=None) -> dict:
    """The receipt of `target` (an order's address, or its paying transaction) rebuilt from the cluster at `url`:
    knos.bundle.gather over the escrow's newest `limit` transactions. Of those it reads only the ones gather takes
    anything from, found in each account's own list: the order's; the first that names the Balance it was funded from
    (its opening: no Balance is closed); when that is among them, the last its side account set before the funding
    (the limits count only then); and the owner's plan set while the order was open. Every other transaction gives
    gather nothing it uses, so the receipt is the one gather builds over all of them. A paying
    transaction that names no work order and is an issue's bounty is read against all of them. Every request together
    gets `seconds`: each one waits at most what is left, and at that time NoAnswer says so in one line, whatever is
    still waiting. OSError when a transaction it needs could not be read; otherwise what gather raises.
    `call(method, params, timeout)` and `clock()` stand in for the cluster and the clock in tests."""
    import threading
    import time

    from . import bundle, chain, records
    from .settle.v2 import pay
    clock = clock or time.monotonic
    ask = call or (lambda method, params, timeout: chain.call(url, method, params, timeout=timeout))
    end, seen = clock() + seconds, {"read": 0, "of": -1}      # transactions read, of how many (-1: the list has not come)
    stop = time.monotonic() + seconds                          # the time the answer is given by, on the wall clock

    def late() -> NoAnswer:
        of = f"{seen['read']:,} of {seen['of']:,} transactions read" if seen["of"] >= 0 else "the list of transactions did not come"
        return NoAnswer(f"no answer from {url} within {seconds:g} s ({of}): give your own endpoint (--rpc URL) or fewer transactions (--limit N)")

    def timed(method: str, params: list):
        left = end - clock()
        if left <= 0:
            raise late()
        try:
            return ask(method, params, min(30.0, left))
        except Exception:
            if clock() >= end:      # the request ran out of the time that was left: say that, not the socket's words
                raise late() from None
            raise

    def work() -> dict:
        got = timed("getSignaturesForAddress", [str(pay.PAY_ID), {"limit": limit}]) or []
        window = [s["signature"] for s in reversed(got) if s.get("err") is None]      # oldest first, as records.history gives them
        at = {sig: n for n, sig in enumerate(window)}
        seen["of"] = 0
        logged: dict[str, list[dict]] = {}      # each transaction read: its escrow events
        unread: list[str] = []

        def read(sigs) -> None:
            new = [s for s in dict.fromkeys(sigs) if s in at and s not in logged and s not in unread]
            seen["of"] += len(new)
            for sig in new:
                try:
                    tx = timed("getTransaction", [sig, TX_VERSION])
                except NoAnswer:
                    raise
                except Exception:  # noqa: BLE001 - still throttled after the backoff: counted, never guessed
                    unread.append(sig)
                    continue
                seen["read"] += 1
                logged[sig] = [{**ev, "tx": sig} for ev in records.events_of(tx)]

        def own(address: str, upto: int) -> list[str]:
            """The transactions of the window that name `address`, oldest first, up to the window's `upto`-th."""
            listed = timed("getSignaturesForAddress", [address, {"limit": limit}]) or []
            return sorted((s["signature"] for s in listed if at.get(s.get("signature"), upto + 1) <= upto), key=at.__getitem__)

        def events() -> list[dict]:
            return [ev for sig in sorted(logged, key=at.__getitem__) for ev in logged[sig]]

        if len(target) > 44:        # a transaction's signature (an address has at most 44 characters)
            read([target])
            orders = sorted({str(ev["order"]) for ev in logged.get(target, []) if ev["event"].startswith("order_") and ev.get("order")})
            if not orders and any(ev["event"] in records.JOB_EVENTS for ev in logged.get(target, [])):
                read(window)        # an issue's bounty: gather tells it from the whole history, as it did
        else:
            orders = [target]
        for order in orders:
            read(own(order, len(window) - 1))
        for order in orders:
            mine = [ev for ev in events() if str(ev.get("order", "")) == order]
            last = max((at[ev["tx"]] for ev in mine), default=-1)
            for funded in [ev for ev in mine if ev["event"] == "order_funded"]:
                source, at_funding, known = str(funded.get("source", "")), at[funded["tx"]], None
                try:
                    side = str(pay.balx_pda(pay.Pubkey.from_string(source)))
                except Exception:  # noqa: BLE001 - not an address (a test's stand-in name): there is no Balance to read
                    side = None
                if side is not None:
                    read(own(source, at_funding)[:1])       # a Balance's opening is the first transaction that names it
                    known = records._balances(events()).get(source)
                if known and side is not None:      # the opening is in the window, so the limits count: the last its side account set before it
                    for sig in reversed(own(side, at_funding)):
                        read([sig])
                        if any(ev["event"] == "balancex" and str(ev.get("balance")) == source for ev in logged.get(sig, [])):
                            break
                # the plan of the order's owner (0 when the opening is not in the window) set while it was open
                read([s for s in own(str(pay.plan_pda(int((known or {}).get("owner") or 0))), last) if at[s] > at_funding])
        if unread:
            raise OSError(f"{len(unread)} transactions could not be read (the public RPC throttled); try again, or give --rpc")
        return bundle.gather(timed, events(), target, None)[0]

    # A request may run past its share (an endpoint that asks to wait and retry), so the whole read runs beside a clock
    # that answers at the time given, whatever is still waiting.
    box: dict = {}

    def run() -> None:
        try:
            box["receipt"] = work()
        except BaseException as e:  # noqa: BLE001 - handed to the caller as it was raised
            box["error"] = e

    worker = threading.Thread(target=run, name="knos-receipt-verify", daemon=True)
    worker.start()
    worker.join(max(0.0, stop - time.monotonic()))
    if worker.is_alive():
        raise late()
    if "error" in box:
        raise box["error"]
    return box["receipt"]


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
            path.write_bytes(canonical(r))          # as it is: the attestation's digest is this receipt's, whatever its version (the script reads 1 to 5)
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
