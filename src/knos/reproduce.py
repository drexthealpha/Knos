"""knos reproduce: re-run, from a clean install and against public things only, what Knos says it does, and write a report.

    knos reproduce [--only ID ...] [--rpc URL] [--out report.json] [--own-repo OWNER/NAME]

Five checks, each timed, each naming the capabilities of docs/capabilities.json it supports:

    payment    a named payment on devnet (the rehearsal's `order_pay` transaction, docs/CAPABILITIES.md) is read from the chain and
               its token re-verified here: GitHub's RS256 signature (against the key the chain holds at an address derived
               from the key, and against GitHub's published keys while GitHub still publishes that one), the audience (this
               order, these payees), and the terms hash (sha256 of the terms the order logged when it was funded)
    programs   every pinned program's bytes on devnet hash to what the release names (the upgrade feed), and the upgrade
               multisig's state is read from the chain: a pending upgrade's buffer hashes to the build the feed names and
               has an execution time; an executed one is what the program runs
    simulator  from a source checkout: the local simulator's money invariants (tests/test_double_pay.py and the state
               machine at its default budget). From an installed wheel there are no tests: skipped, and said
    claim      `knos check` on a named public pull request gives the verdict recorded in docs/agent_pr_ci.json
    own_repo   only with --own-repo and a GitHub token: one funded round in the reproducer's own repository (fund by
               comment from the faucet Balance, pull request, merge, paid). It opens and merges a pull request there, so it
               is never run unasked

Three more hold what the PUBLIC program ids and the published pages say to the public record, read-only, with no key:

    provenance every pinned program's bytes on devnet hash to a build docs/provenance.json records for it (the build it
               read there, or the one this release proposes), or to one the upgrade feed says has run since
    payments   up to three payments docs/capabilities.json records at the public program ids, each read from the chain
               and its token re-verified from GitHub's signature, exactly as `payment` does for the named one. Skipped,
               and said, while the manifest records none
    statement  the statement the site publishes is made again from its evidence (which the repository keeps beside the
               same statement), and is the same statement

A check ends `pass`, `fail` or `skipped` (it could not be asked: no network, no checkout, no token). Only `pass` counts.

A report is made self-proving by GitHub, not by its author: examples/knos-reproduce.yml runs this command in the
reproducer's repository and asks GitHub for an OIDC token whose audience is `knos-repro:<sha256 of the report>`. The token
says which repository and account ran it; the audience says for which bytes. `verified` checks such a pair with no
network, given GitHub's keys: scripts/capabilities.py and .github/workflows/reproductions.yml both call it.

What the token does not say: that the workflow file was the example unchanged. It names the workflow and its commit
(`workflow_ref`, `workflow_sha`), which anyone can read in that repository.

This module imports nothing outside the standard library until a check runs: the workflow that verifies a pull request's
reproduction runs it on a bare Python.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import platform
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable

FORMAT = "knos-reproduction/1"
AUDIENCE = "knos-repro:"
ISSUER = "https://token.actions.githubusercontent.com"
JWKS = ISSUER + "/.well-known/jwks"
FEED = "https://drexthealpha.github.io/Knos/upgrades.json"       # what the release names: written from the multisig's accounts
MAINTAINER = "drexthealpha"
RESULTS = ("pass", "fail", "skipped")
# The payment `payment` re-verifies: the `order_pay` transaction of the 0.3.14 rehearsal, made on its own deployment of
# the 2.1 build (the staging knos_pay and the verifier it accepts tokens from, named in docs/CAPABILITIES.md, "The 0.3.14
# rehearsal on devnet"; the signature is in the note of `order_pay` in docs/capabilities.json, which stays `tested`).
PAYMENT = {"signature": "63wT5rhYhEKbgmF5k8vEKdexzoCaXZCiDvRG2GQMGSMBBsc9avGfDw3izER9D6LHoe4ucJeinTBiWaWGWpnFWvfq",
           "pay": "FJJtqcRjQ9ATx37sBTCLUBxBqLUA9aQgSTLAsZynqtnH", "oidc": "iosu8ARUNvvruHPCcMWQ5rqsnJewzBxcPXajSpoHqXd"}
# The pull request `claim` checks: merged, so its head no longer moves; docs/agent_pr_ci.json records it as `failed`
# at this commit (its description says tests pass, and a check failed there), which `knos check` calls "false".
CLAIM = {"pr": "SciML/SciMLBase.jl#1574", "head": "2ee3d2b1e1be9ccef2631c5c1fa071b73fc9899b", "verdict": "false"}
SUITE = ("tests/test_double_pay.py", "tests/test_invariants_machine.py")
SUPPORTS = {"payment": ("order_pay",), "programs": ("upgrade_delay", "upgrade_feed"),
            "simulator": ("single_use_tokens", "invariants_state_machine"), "claim": ("check",),
            "own_repo": ("fund_by_comment", "pay_on_merge")}
ORDER = tuple(SUPPORTS)
# The checks of the public round, after the five: read-only, against the PUBLIC program ids and the published pages.
PUBLIC = {"provenance": ("provenance_chain",), "payments": ("order_pay",), "statement": ("statements",)}
EVERY = {**SUPPORTS, **PUBLIC}                  # a report's rows: these checks, in this order, each with these capabilities
RAW = "https://raw.githubusercontent.com/drexthealpha/Knos/main/"       # the public record, for an install that has no checkout
STATEMENT = "https://drexthealpha.github.io/Knos/statement_sample.json"  # the statement the site publishes
RECORDED = ("order_pay", "order_quorum", "x402_knos_order")              # capabilities whose public transaction is a PayOrder with a token
MOST = 3                                                                 # payments re-verified in one run


class Skip(Exception):
    """A check that could not be asked from here. Its text says why and what would let it run."""


class Fail(Exception):
    """A check that was asked and did not hold. `evidence` is what was read."""

    def __init__(self, why: str, evidence: dict | None = None) -> None:
        super().__init__(why)
        self.evidence = evidence or {}


# ---- the report ---------------------------------------------------------------------------------------------------------

def canonical(report: dict) -> bytes:
    """The one form of a report: what report.json holds, and what the token's audience is the sha256 of."""
    return json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def digest(report: dict) -> str:
    return hashlib.sha256(canonical(report)).hexdigest()


def _commit(root: Path | None) -> str:
    """The commit of the source checkout the command runs from; empty from an installed wheel."""
    if root is None:
        return ""
    try:
        got = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return got.stdout.strip() if got.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}\s*", got.stdout) else ""


def checkout() -> Path | None:
    """The source checkout this module is in (it has the tests and the programs' ids); None from an installed wheel."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / "programs-v2" / "program_ids.json").is_file() and (root / SUITE[0]).is_file() else None


def run_check(cid: str, fn: Callable[[], dict], clock: Callable[[], float] = time.monotonic) -> dict:
    """One check as a row of the report. `fn` returns its evidence, or raises Skip or Fail; anything else it raises is
    a failure too, said in one line."""
    began = clock()
    row: dict = {"id": cid, "capabilities": list(EVERY[cid])}
    try:
        row.update(result="pass", evidence=fn(), why="")
    except Skip as why:
        row.update(result="skipped", evidence={}, why=str(why))
    except Fail as why:
        row.update(result="fail", evidence=why.evidence, why=str(why))
    except Exception as why:  # noqa: BLE001 - a check never ends the report
        row.update(result="fail", evidence={}, why=f"{type(why).__name__}: {' '.join(str(why).split())[:300]}")
    row["seconds"] = round(clock() - began, 1)
    return row


def build(checks: dict[str, Callable[[], dict]], only: list[str] | tuple = (), *, version: str, commit: str = "", cluster: str = "devnet",
          now: Callable[[], float] = time.time, clock: Callable[[], float] = time.monotonic) -> dict:
    """The report: who ran (the knos version, platform, Python, commit), and each check in the fixed order."""
    unknown = sorted(set(only) - set(checks))
    if unknown:
        raise ValueError(f"no check is called {', '.join(unknown)}; the checks are {', '.join(c for c in EVERY if c in checks)}")
    rows = [run_check(cid, checks[cid], clock) for cid in EVERY if cid in checks and (not only or cid in only)]
    return {"format": FORMAT, "knos": version, "python": platform.python_version(), "platform": platform.platform(), "commit": commit,
            "cluster": cluster, "at": int(now()), "checks": rows, **{r: sum(row["result"] == r for row in rows) for r in RESULTS}}


def lines(report: dict) -> list[str]:
    """The report for a person: one line per check, then what to do with it."""
    out = [f"{row['result'].upper():7} {row['id']:10} {row['seconds']:6.1f} s  " + (row["why"] or ", ".join(row["capabilities"])) for row in report["checks"]]
    return [*out, f"{report['pass']} passed, {report['fail']} failed, {report['skipped']} skipped. knos {report['knos']}, Python {report['python']}, "
                  f"{report['platform']}" + (f", commit {report['commit'][:12]}" if report["commit"] else "")]


# ---- a signed reproduction: the report and GitHub's token ---------------------------------------------------------------

def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


_SHA256_INFO = bytes.fromhex("3031300d060960864801650304020105000420")       # DigestInfo of SHA-256 (RFC 8017, 9.2)


def rs256(token: str, n: int) -> bool:
    """Whether `token` carries the RS256 signature of the key with modulus `n` and exponent 65537 (as knos.bundle.rs256,
    written out here so that a bare Python can check a reproduction)."""
    try:
        signed, _, sig = token.rpartition(".")
        k, raw = (n.bit_length() + 7) // 8, _unb64(sig)
        if len(raw) != k or json.loads(_unb64(signed.split(".")[0])).get("alg") != "RS256":
            return False
        want = b"\x00\x01" + b"\xff" * (k - 3 - len(_SHA256_INFO) - 32) + b"\x00" + _SHA256_INFO + hashlib.sha256(signed.encode()).digest()
        return pow(int.from_bytes(raw, "big"), 65537, n).to_bytes(k, "big") == want
    except Exception:  # noqa: BLE001 - not a token at all
        return False


def keys_of(jwks: dict) -> dict[str, int]:
    """{kid: modulus} of a JWKS document's RSA keys with exponent 65537."""
    return {str(k["kid"]): int.from_bytes(_unb64(k["n"]), "big") for k in (jwks or {}).get("keys", [])
            if isinstance(k, dict) and k.get("kty") == "RSA" and k.get("e") == "AQAB" and k.get("kid") and k.get("n")}


def file_name(claims: dict) -> str:
    """`<owner>-<repo>-<run id>.json`: where a reproduction goes in reproductions/."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", f"{claims.get('repository', '')}-{claims.get('run_id', '')}") + ".json"


def verified(doc, keys: dict[str, int], own: dict, name: str = "") -> tuple[dict, list[str]]:
    """(what GitHub signed and which checks passed, everything wrong with the pair) for a reproduction: {"report", "token"}.
    `keys`: GitHub's keys, {kid: modulus}. `own`: scripts/own_github_ids.json, whose accounts are never an outside run.
    `name`: the file's name, held to the repository and run the token names. With anything wrong, nothing in it counts.
    The token's expiry is not asked: it lasts minutes, and what matters is that GitHub signed it for these bytes."""
    facts: dict = {"passed": [], "failed": [], "capabilities": []}
    if not isinstance(doc, dict) or not isinstance(doc.get("report"), dict) or not isinstance(doc.get("token"), str) or set(doc) != {"report", "token"}:
        return facts, ['a reproduction is {"report": the report, "token": GitHub\'s token} and nothing else']
    report, token = doc["report"], doc["token"].strip()
    try:
        head, claims = (json.loads(_unb64(part)) for part in token.split(".")[:2])
        assert isinstance(head, dict) and isinstance(claims, dict) and token.count(".") == 2
    except Exception:  # noqa: BLE001
        return facts, ["the token is not a signed token (three parts, the first two JSON)"]
    wrong = []
    n = keys.get(str(head.get("kid")))
    if n is None:
        wrong.append(f"the token names the key {str(head.get('kid'))[:40]!r}, which is not among GitHub's keys given here")
    elif not rs256(token, n):
        wrong.append("the token's signature is not GitHub's: the token was changed, or GitHub did not sign it")
    if claims.get("iss") != ISSUER:
        wrong.append(f"the token's issuer is not {ISSUER}")
    if claims.get("aud") != AUDIENCE + digest(report):
        wrong.append("the token was not signed for this report (its audience is not knos-repro:<sha256 of the report>): the report was edited after it was signed")
    ids = {int(i) for i in own.get("ids", [])}
    owner, owner_id, actor_id = str(claims.get("repository_owner", "")), str(claims.get("repository_owner_id", "")), str(claims.get("actor_id", ""))
    if not (owner and owner_id.isdigit() and actor_id.isdigit() and re.fullmatch(r"[^/\s]+/[^/\s]+", str(claims.get("repository", ""))) and str(claims.get("run_id", "")).isdigit()):
        wrong.append("the token does not name a repository, its owner, who started the run and the run")
    elif owner.lower() == MAINTAINER or int(owner_id) in ids or int(actor_id) in ids:
        wrong.append(f"the run is Knos's own (repository owner {owner}, id {owner_id}; started by id {actor_id}): an outside reproduction is someone else's")
    elif name and name != file_name(claims):
        wrong.append(f"the file is named {name}; this run's file is {file_name(claims)}")
    rows = report.get("checks")
    if report.get("format") != FORMAT or not isinstance(rows, list) or not all(
            isinstance(r, dict) and r.get("id") in EVERY and r.get("result") in RESULTS and r.get("capabilities") == list(EVERY[r["id"]]) for r in rows) or \
            len({r["id"] for r in rows}) != len(rows):
        wrong.append(f"the report is not a {FORMAT} report: its checks are not the ones `knos reproduce` writes, each once, with the capabilities it names")
    facts.update({k: claims.get(k) for k in ("repository", "repository_id", "repository_owner", "repository_owner_id", "actor", "actor_id", "run_id",
                                             "run_attempt", "sha", "workflow_ref", "workflow_sha", "job_workflow_ref", "event_name", "iat")},
                 kid=head.get("kid"), report_sha256=digest(report), knos=report.get("knos"),
                 run=f"https://github.com/{claims.get('repository')}/actions/runs/{claims.get('run_id')}")
    if not wrong:
        facts["passed"] = [r["id"] for r in rows if r["result"] == "pass"]
        facts["failed"] = [r["id"] for r in rows if r["result"] == "fail"]
        facts["capabilities"] = sorted({c for r in rows if r["result"] == "pass" for c in r["capabilities"]})      # a failed or skipped check counts for nothing
    return facts, wrong


def body(doc: dict, facts: dict) -> str:
    """The pull request's text for a reproduction (.github/PULL_REQUEST_TEMPLATE/reproduction.md filled in): what the
    signing job of examples/knos-reproduce.yml prints, kept here so a test holds the two to one text."""
    rows = "\n".join(f"| `{r['id']}` | {r['result']} | {r['seconds']} s | {', '.join(r['capabilities'])} |" for r in doc["report"]["checks"])
    return (f"Reproduction of Knos {doc['report'].get('knos')} by {facts.get('repository_owner')}\n\n"
            f"Adds `reproductions/{file_name(facts)}`: the report of `knos reproduce` and the token GitHub signed for it in "
            f"[this run]({facts.get('run')}) of {facts.get('repository')}.\n\n| check | result | time | capabilities |\n|---|---|---|---|\n{rows}\n\n"
            f"Report sha256 `{facts.get('report_sha256')}`. I am not the maintainer of Knos and I ran this in a repository of my own.\n")


# ---- the checks ---------------------------------------------------------------------------------------------------------

def _fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "knos-reproduce", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - the two fixed https URLs above
        return json.load(r)


# A host that could not be asked: no connection, a timeout, or an answer cut off before its end (http.client's
# IncompleteRead is not an OSError). None of these says anything about what was asked, so none of them is a failure.
UNASKED = (OSError, http.client.HTTPException)


def _asked(what: str, fn, *args):
    """`fn(*args)`, with a host that could not be asked turned into a Skip that says which."""
    try:
        return fn(*args)
    except UNASKED as why:
        raise Skip(f"{what} could not be asked ({' '.join(str(why).split())[:160]}). Run it again; --rpc names another Solana RPC.") from None


def payment(call, jwks: Callable[[], dict], target: dict = PAYMENT) -> dict:
    """Read the named payment from the chain and verify its token again, from signatures. `call(method, params)` is the
    cluster; `jwks()` GitHub's published keys."""
    from solders.pubkey import Pubkey

    from . import bundle, records
    from .settle.v2 import oidc
    sig, pay, verifier = target["signature"], target["pay"], target["oidc"]
    try:
        tx = _asked("devnet", bundle._tx, call, sig)
        spent = next((keys for data, keys in bundle._ixs(tx, pay) if data[:1] == b"\x11"), None)      # PayOrder: its token and key accounts
        events = records.events_of(tx, {pay: 2})
        settled = next((e for e in events if e["event"] == "order_settled"), None)
        if (tx.get("meta") or {}).get("err") is not None or spent is None or settled is None:
            raise Fail(f"transaction {sig[:12]}... is not a payment of an order by {pay} that succeeded")
        token, verified_tx = _asked("devnet", bundle.token_of, call, spent[1], verifier)
        head, claims = (json.loads(_unb64(part)) for part in token.split(".")[:2])
        # the key: the account the program verified against, at an address only that key and its issuer derive
        info = (_asked("devnet", call, "getAccountInfo", [spent[2], {"encoding": "base64"}]) or {}).get("value")
        kdata = base64.b64decode(info["data"][0]) if info else b""
        key = oidc.read_key(kdata) if info and info.get("owner") == verifier else None
        if key is None:
            raise Fail(f"the key account {spent[2]} is not a key of the verifier {verifier}")
        limbs = kdata[oidc.K_HDR:oidc.K_HDR + key.bits // 8]
        n = next((v for v in (int.from_bytes(limbs, "big"), int.from_bytes(limbs, "little"))
                  if str(oidc.key_pda(oidc.GITHUB, v, Pubkey.from_string(verifier))) == spent[2]), None)
        if n is None or claims.get("iss") != ISSUER:
            raise Fail(f"the key account {spent[2]} is not derived from a key of GitHub's")
        if not rs256(token, n):
            raise Fail("the token does not carry the RS256 signature of the key the chain holds")
        try:
            live = keys_of(jwks())
        except UNASKED:
            live = None
        kid = str(head.get("kid"))
        if live is not None and kid in live and live[kid] != n:
            raise Fail(f"GitHub publishes another key under {kid} than the one the chain holds")
        # the audience: this order, these payees, these terms
        aud = str(claims.get("aud", "")).split(":")
        order = settled["order"]
        if aud[:2] != ["knos3", "pay"] or len(aud) != 8 or aud[2] != order:
            raise Fail("the token was not signed to pay this order (its audience names another)", {"audience": claims.get("aud")})
        paid = [(int(e["payee"]), int(e["amount"])) for e in events if e["event"] == "order_paid" and e.get("order") == order]
        named = [int(part.split(".")[0]) for part in aud[7].split(",")]
        if [p for p, _ in paid] != named or sum(a for _, a in paid) != int(settled["paid"]):
            raise Fail("the accounts paid are not the ones the token names, or the amounts do not add up to what was settled")
        history = [s["signature"] for s in _asked("devnet", call, "getSignaturesForAddress", [order, {"limit": 200}]) or [] if s.get("err") is None]
        terms = next((e["json"] for s in reversed(history) for e in records.events_of(_asked("devnet", bundle._tx, call, s), {pay: 2})
                      if e["event"] == "order_terms"), None)
        if terms is None or hashlib.sha256(terms.encode()).hexdigest() != aud[4]:
            raise Fail("the terms the order logged when it was funded do not hash to the terms hash the token names")
    except bundle.Unavailable as why:
        raise Skip(f"{why}: public RPCs drop old transactions. Give --rpc a node that keeps history.") from None
    return {"transaction": sig, "program": pay, "verifier": verifier, "order": order, "verified_in": verified_tx, "key_account": spent[2], "kid": kid,
            "key": "the chain's key account" + ("; GitHub's key list could not be read" if live is None else ", and GitHub publishes the same key"
                                                if kid in live else "; GitHub no longer publishes it"),
            "token_sha256": hashlib.sha256(_unb64(token.rsplit(".", 1)[1])).hexdigest(), "audience": claims["aud"], "terms_sha256": aud[4],
            "signed_for": {k: str(claims.get(k)) for k in ("repository", "repository_id", "run_id", "sha", "workflow_ref", "iat")},
            "paid": int(settled["paid"]), "fee": int(settled["fee"]), "payees": named}


def programs(account, feed: Callable[[], dict], ids: dict | None = None) -> dict:
    """Every pinned program against the build the release names for it, and the upgrade multisig's state, from the chain.
    `account(address)`: knos.mainnet_check's reader; `feed()`: the published upgrade feed (web/upgrades.json)."""
    from . import mainnet_check as mc
    from .settle.v2 import gate, oidc
    ids = ids or oidc.IDS
    squads, vault = ids["squads_program"], ids["upgrade_authority"]

    def buffer_hash(address: str) -> str | None:
        got = account(address)
        if not got or str(got[0]) != str(mc.LOADER) or len(got[1]) < gate.BUFFER_HEADER or got[1][:4] != (1).to_bytes(4, "little"):
            return None
        return gate.executable_hash(got[1][gate.BUFFER_HEADER:]).hex()

    def read() -> tuple:
        ms, said = mc.multisig_at(account, ids["upgrade_multisig"], squads)
        waiting = mc.pending_proposals(account, ids["upgrade_multisig"], ms, squads) if ms else []
        state = {name: mc.program_data(account, ids[name]) for name in (*mc.PROGRAMS, *mc.NEW_PROGRAMS) if ids.get(name)}
        return ms, said, waiting, state, {p.index: buffer_hash(p.buffer) for p in waiting if p.kind == "upgrade" and p.buffer}

    ms, said, waiting, state, buffers = _asked("devnet", read)
    try:
        entries = [e for e in (feed() or {}).get("entries", []) if isinstance(e, dict)]
    except (*UNASKED, ValueError) as why:
        raise Skip(f"the upgrade feed at {FEED} could not be read ({' '.join(str(why).split())[:120]})") from None
    out, wrong = {"multisig": ids["upgrade_multisig"], "multisig_state": said, "programs": {}}, []
    if ms is None or ms.time_lock != mc.TIME_LOCK:
        wrong.append(f"the upgrade multisig does not hold upgrades for {mc.TIME_LOCK // 3600} hours ({said})")
    for name, (deployed, authority, elf) in state.items():
        row = out["programs"][name] = {"address": ids[name], "on_chain": gate.executable_hash(elf).hex() if elf else None, "upgrade_authority": authority}
        if not deployed or authority not in (vault, None):
            wrong.append(f"{name}: " + ("not deployed" if not deployed else f"upgradeable by {authority}, not only through the multisig's vault {vault}"))
            continue
        named = [e for e in entries if e.get("program_address") == ids[name] and e.get("status") in ("pending", "executed")]
        pending = next((p for p in waiting if p.program == ids[name] and p.kind == "upgrade"), None)
        if pending is not None:
            told = next((e for e in named if e.get("index") == pending.index), None)
            row.update(state="pending", proposal=pending.index, status=pending.status, executes_at=pending.executes_at, buffer=pending.buffer,
                       buffer_hash=buffers.get(pending.index), named=told and told.get("build_hash"))
            if told is None or not row["buffer_hash"] or told.get("build_hash") != row["buffer_hash"]:
                wrong.append(f"{name}: proposal {pending.index} would deploy {row['buffer_hash']}, and the release names {row['named']}")
        elif named:      # nothing waits on chain: the newest upgrade the feed names has run, or the feed is older than the chain
            told = max(named, key=lambda e: int(e.get("index") or 0))
            row.update(state="executed", proposal=told.get("index"), named=told.get("build_hash"))
            if told.get("build_hash") != row["on_chain"]:
                wrong.append(f"{name}: devnet runs {row['on_chain']}, and the release names {told.get('build_hash')} (proposal {told.get('index')})")
        else:
            row.update(state="no upgrade named", named=None)
    if not any(r.get("named") for r in out["programs"].values()):
        wrong.append("the release names no build for any pinned program, so there is nothing to compare")
    if wrong:
        raise Fail("; ".join(wrong), out)
    return out


def simulator(root: Path | None, run=subprocess.run) -> dict:
    """The money invariants on the local simulator, from a source checkout: no network, no chain."""
    if root is None:
        raise Skip("no source checkout: an installed wheel has no tests. Clone the repository and run `python -m knos reproduce --only simulator` in it.")
    env = {k: v for k, v in os.environ.items() if not k.startswith("KNOS_MACHINE_")}       # the default budget, whatever the shell says
    env["PYTHONPATH"] = str(root / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    try:
        got = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *SUITE], cwd=str(root), capture_output=True, text=True, env=env, timeout=3600)
    except (OSError, subprocess.TimeoutExpired) as why:
        raise Skip(f"pytest could not be run here ({type(why).__name__})") from None
    tail = next((ln.strip() for ln in reversed((got.stdout or "").splitlines()) if ln.strip()), "")
    if "No module named pytest" in (got.stderr or ""):
        raise Skip("pytest is not installed: pip install -e '.[dev]' in the checkout")
    evidence = {"tests": list(SUITE), "summary": tail[:200], "commit": _commit(root)}
    if got.returncode != 0 or " passed" not in tail or " failed" in tail or " error" in tail:
        raise Fail(f"the simulator suite did not pass: {tail[:200] or (got.stderr or '').strip()[-200:]}", evidence)
    return evidence


def claim(check_pr: Callable[[str], dict], target: dict = CLAIM) -> dict:
    """`knos check` on the named public pull request against the verdict recorded for it."""
    try:
        got = check_pr(target["pr"])
    except Exception as why:  # noqa: BLE001 - knos.mcp.Failed: GitHub did not answer, or refused
        raise Skip(" ".join(str(why).split())[:240]) from None
    evidence = {"pr": target["pr"], "head": got.get("head"), "verdict": got.get("verdict"), "recorded": target["verdict"], "failed_checks": got.get("failed")}
    if got.get("head") != target["head"]:
        raise Fail(f"{target['pr']} is at {str(got.get('head'))[:12]}, not at the recorded commit {target['head'][:12]}", evidence)
    if got.get("verdict") != target["verdict"]:
        raise Fail(f"`knos check` says {got.get('verdict')!r} of {target['pr']}; the recorded verdict is {target['verdict']!r}", evidence)
    return evidence


def own_repo(repo: str, env: dict, canary=None) -> dict:
    """One funded round in the reproducer's own repository: `knos canary`'s (fund by comment, pull request, merge, paid)."""
    if not repo:
        raise Skip("not asked for: --own-repo OWNER/NAME runs one funded round (test USDC) in a repository of yours that has Knos installed; "
                   "it opens and merges a pull request there")
    if not (env.get("GH_TOKEN") or env.get("GITHUB_TOKEN")):
        raise Skip("no GitHub token: set GH_TOKEN to a token of yours that can write issues, pull requests and contents in that one repository")
    if repo.count("/") != 1 or repo.split("/")[0].lower() == MAINTAINER:
        raise Skip("--own-repo is OWNER/NAME, a repository of your own")
    from . import flow
    run, said = flow.Run(repo, {}, env=env), []
    run.note = lambda text, *a, **k: said.append(str(text))       # type: ignore[method-assign]  # the round's one line, kept as evidence in place of a job summary
    code = (canary or flow.canary)(run)
    line = next((ln.split("knos-canary ", 1)[1] for text in said for ln in text.splitlines() if ln.startswith("knos-canary ")), "{}")
    evidence = {"repository": repo, "round": json.loads(line)}
    if code != 0:
        raise Fail(f"the round did not end in a payment: the `{evidence['round'].get('failed')}` leg ({evidence['round'].get('why')})", evidence)
    return evidence


def provenance(account, record: Callable[[], dict], feed: Callable[[], dict], ids: dict | None = None) -> dict:
    """Every pinned program's bytes on devnet against docs/provenance.json. `account(address)`: knos.mainnet_check's
    reader; `record()`: docs/provenance.json; `feed()`: the published upgrade feed, asked only for a program that runs
    a build the record does not name (an upgrade that executed after the record was written)."""
    from . import mainnet_check as mc
    from .settle.v2 import gate, oidc
    ids = ids or oidc.IDS
    try:
        doc = record() or {}
    except (*UNASKED, ValueError) as why:
        raise Skip(f"docs/provenance.json could not be read ({' '.join(str(why).split())[:120]})") from None
    names = [n for n in mc.PROGRAMS + mc.NEW_PROGRAMS if ids.get(n) and (doc.get("programs") or {}).get(n)]
    if not names:
        raise Fail("docs/provenance.json records no program, so there is nothing to hold the chain to")
    state = _asked("devnet", lambda: {n: mc.program_data(account, ids[n]) for n in names})
    out: dict = {"read": doc.get("read"), "programs": {}}
    wrong, later = [], None
    for name in names:
        deployed, _authority, elf = state[name]
        on_chain = gate.executable_hash(elf).hex() if deployed and elf else None
        held, nxt = doc["programs"][name], (doc.get("next") or {}).get(name) or {}
        row = out["programs"][name] = {"address": ids[name], "on_chain": on_chain, "recorded": held.get("on_chain_hash"), "next": nxt.get("build_hash")}
        if on_chain is None:
            wrong.append(f"{name}: not deployed at {ids[name]}")
        elif on_chain == held.get("on_chain_hash"):
            row["runs"] = "the build the record read there"
        elif on_chain == nxt.get("build_hash"):
            row["runs"] = "the build the record names as next"
        else:
            if later is None:
                try:
                    later = [e for e in (feed() or {}).get("entries", []) if isinstance(e, dict)]
                except (*UNASKED, ValueError):
                    later = []
            told = next((e for e in later if e.get("program_address") == ids[name] and e.get("build_hash") == on_chain and e.get("status") in ("pending", "executed")), None)
            if told is None:
                wrong.append(f"{name}: devnet runs {on_chain}, which neither docs/provenance.json nor the upgrade feed names")
            else:
                row["runs"] = f"a build newer than the record: the upgrade feed names it (proposal {told.get('index')})"
    if wrong:
        raise Fail("; ".join(wrong), out)
    return out


def recorded_payments(manifest: dict, ids: dict) -> list[tuple[str, str]]:
    """(capability, signature) of each payment docs/capabilities.json records at the PUBLIC knos_pay: order_pay first."""
    out = []
    for c in manifest.get("capabilities", []):
        ev = c.get("evidence") or {}
        dep, ex = ev.get("deployed") or {}, ev.get("exercised") or {}
        if c.get("id") in RECORDED and ex.get("ids") == "public" and dep.get("id") == ids.get("knos_pay") and isinstance(ex.get("signature"), str):
            out.append((str(c["id"]), ex["signature"]))
    return sorted(out, key=lambda row: RECORDED.index(row[0]))


def payments(call, jwks: Callable[[], dict], manifest: Callable[[], dict], ids: dict | None = None, most: int = MOST) -> dict:
    """Up to `most` payments the manifest records at the public program ids, each re-verified as `payment` verifies
    the named one. `manifest()`: docs/capabilities.json."""
    from .settle.v2 import oidc
    ids = ids or oidc.IDS
    try:
        found = recorded_payments(manifest() or {}, ids)
    except (*UNASKED, ValueError) as why:
        raise Skip(f"docs/capabilities.json could not be read ({' '.join(str(why).split())[:120]})") from None
    if not any(cap == "order_pay" for cap, _sig in found):
        raise Skip("docs/capabilities.json records no payment of an order at the public program ids yet: the release that exercises them there writes it")
    rows: list[dict] = []
    for cap, sig in found[:most]:
        try:
            got = payment(call, jwks, {"signature": sig, "pay": ids["knos_pay"], "oidc": ids["knos_oidc"]})
        except Fail as why:
            raise Fail(f"{cap}: {why}", {"verified": rows, "failed": {"capability": cap, "transaction": sig, **why.evidence}}) from None
        rows.append({"capability": cap, **{k: got[k] for k in ("transaction", "order", "paid", "fee", "payees", "token_sha256", "kid", "key", "signed_for")}})
    return {"program": ids["knos_pay"], "verifier": ids["knos_oidc"], "recorded": len(found), "verified": rows}


def statement(published: Callable[[], dict], kept: Callable[[], dict]) -> dict:
    """The statement the site publishes, made again from its evidence. `published()`: that statement, which names its
    evidence by sha256 and does not carry it; `kept()`: the same statement as the repository keeps it with the evidence
    inside (tests/data/statement/sept.json). Both are made again, and the published one from the evidence the kept one holds."""
    from . import statement as st
    try:
        doc = published()
        ev = doc.get("evidence") if isinstance(doc, dict) else None
        bundle, source = None, "the statement itself"
        if isinstance(ev, dict) and ev.get("embedded") is None:
            whole = kept()
            inside = whole.get("evidence") if isinstance(whole, dict) else None
            if not isinstance(inside, dict) or inside.get("embedded") is None or inside.get("sha256") != ev.get("sha256"):
                raise Fail("the statement the repository keeps does not hold the evidence the published one names",
                           {"published_evidence": ev.get("sha256"), "kept_evidence": (inside or {}).get("sha256")})
            again, said = st.verify(whole)
            if not again:
                raise Fail(f"the statement the repository keeps is not what its own evidence gives: {said}")
            bundle, source = st.canonical(inside["embedded"]), "the statement the repository keeps with its evidence inside (tests/data/statement/sept.json)"
    except (*UNASKED, ValueError) as why:
        raise Skip(f"the published statement or its evidence could not be read ({' '.join(str(why).split())[:120]})") from None
    try:
        same, said = st.verify(doc, bundle)
    except (st.Refused, KeyError, TypeError) as why:
        raise Fail(f"the published statement cannot be made again: {why}") from None
    evidence = {"sha256": doc.get("sha256"), "invoice": doc.get("invoice"), "source": doc.get("source"), "lines": len(doc.get("lines") or []),
                "evidence_sha256": (doc.get("evidence") or {}).get("sha256"), "evidence_from": source, "totals": doc.get("totals")}
    if not same:
        raise Fail(f"the published statement is not what its evidence gives: {said}", evidence)
    return evidence


def _record(root: Path | None, path: str, env: dict) -> Callable[[], dict]:
    """A file of the public record: from the checkout when there is one, else from the repository's main branch."""
    def read() -> dict:
        if root is not None and (root / path).is_file():
            return json.loads((root / path).read_text(encoding="utf-8"))
        return _fetch_json((env.get("KNOS_RECORD_URL") or RAW) + path)
    return read


def live(rpc: str = "", own: str = "", env: dict | None = None) -> dict[str, Callable[[], dict]]:
    """The checks against the real things: devnet (or `rpc`), GitHub's keys, the published feed, GitHub's API, and
    the public record (docs/provenance.json, docs/capabilities.json, the site's statement)."""
    env = dict(os.environ) if env is None else env

    def call(method: str, params: list):
        from . import chain
        return chain.call(rpc or env.get("KNOS_RPC") or chain.CLUSTERS["devnet"], method, params, timeout=30)

    def account(address: str):
        from . import chain, mainnet_check as mc
        try:
            return mc._rpc(rpc or env.get("KNOS_RPC") or chain.CLUSTERS["devnet"])(address)
        except chain.Refused as why:      # the RPC answered with an error: not an answer about the account
            raise OSError(str(why)) from None

    def check_pr(pr: str) -> dict:
        from . import mcp
        return mcp.Server()._check_pr({"pr": pr})

    root = checkout()

    def feed() -> dict:
        return _fetch_json(env.get("KNOS_UPGRADES_URL") or FEED)

    def published() -> dict:
        if root is not None and (root / "web" / "statement_sample.json").is_file() and not env.get("KNOS_STATEMENT_URL"):
            return json.loads((root / "web" / "statement_sample.json").read_text(encoding="utf-8"))
        return _fetch_json(env.get("KNOS_STATEMENT_URL") or STATEMENT)

    return {"payment": lambda: payment(call, lambda: _fetch_json(JWKS)), "programs": lambda: programs(account, feed),
            "simulator": lambda: simulator(root), "claim": lambda: claim(check_pr), "own_repo": lambda: own_repo(own, env),
            "provenance": lambda: provenance(account, _record(root, "docs/provenance.json", env), feed),
            "payments": lambda: payments(call, lambda: _fetch_json(JWKS), _record(root, "docs/capabilities.json", env)),
            "statement": lambda: statement(published, _record(root, "tests/data/statement/sept.json", env))}


# ---- the command line ---------------------------------------------------------------------------------------------------

def register(app, help_lines: list | None = None) -> None:
    """`knos reproduce`, on the main app. `help_lines`: cli._HELP, which gets its line."""
    import typer

    if help_lines is not None:
        help_lines.append(("reproduce", "For money", "Re-run what Knos says it does, against public things only, and write a report GitHub can sign."))

    @app.command("reproduce")
    def reproduce(only: list[str] = typer.Option([], "--only", help=f"run only this check, or the checks behind this capability id (repeat for several); the checks: {', '.join(EVERY)}"),
                  rpc: str = typer.Option("", "--rpc", help="the Solana JSON-RPC URL (default: KNOS_RPC, then devnet)"),
                  out_file: Path = typer.Option(Path("report.json"), "--out", help="where to write the report"),
                  own: str = typer.Option("", "--own-repo", help="OWNER/NAME of a repository of yours with Knos installed: also run one funded round there (test USDC; it opens and merges a pull request). Needs GH_TOKEN")) -> None:
        """Re-run, from this install and against public things only, what Knos says it does: a named devnet payment verified again from signatures, the on-chain programs against the hashes the release names, the local simulator's money invariants (from a source checkout), and the claim check on a public pull request. Writes a report; examples/knos-reproduce.yml has GitHub sign it in your repository. Exit 1 when a check fails. Devnet: test USDC."""
        from . import version
        checks = live(rpc, own)
        wanted = [cid for cid in EVERY if cid in checks and (cid in only or set(EVERY[cid]) & set(only))]
        unknown = [o for o in only if o not in EVERY and not any(o in caps for caps in EVERY.values())]
        if unknown:
            typer.echo(f"No check is called {', '.join(unknown)} and none supports a capability of that name. The checks: {', '.join(EVERY)}.", err=True)
            raise typer.Exit(2)
        report = build(checks, wanted, version=version(), commit=_commit(checkout()))
        out_file.write_bytes(canonical(report))
        for line in lines(report):
            typer.echo(line)
        sha = digest(report)
        typer.echo(f"{out_file}: sha256 {sha}. A token GitHub signs for the audience {AUDIENCE}{sha} proves where this ran (docs/REPRODUCE.md).")
        if os.environ.get("GITHUB_OUTPUT"):      # the workflow's next job asks GitHub for that token
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
                f.write(f"sha256={sha}\n")
        raise typer.Exit(1 if report["fail"] else 0)
