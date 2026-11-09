"""The two verdicts on a lab order, kept apart because labs accept only this:

    LAB verdict       was the protocol executed as specified, was every run reported (failed runs included), and did
                      the QC pass (the lab's controls and the checks the order named)? PASS pays the LAB from vault,
                      EVEN IF THE SCIENCE FAILED: a lab is paid for doing the work right, never penalised because a design
                      did not bind, a reaction gave no product or a board missed its spec.
    OUTCOME verdict   did the result meet the researcher's claim? PASS pays the researcher and lets the product
                      graduate; FAIL refunds the reward to the funder. It is only given when the LAB verdict passed: with a
                      failed protocol there is no evidence about the claim, so the outcome is VOID and the reward goes back.

A claim, and a spec's QC checks, are conditions on the results:

    {"metric": "kd_nm", "op": "<=", "value": 100, "agg": "median", "over": "runs"}
    agg: median | min | max | mean | all | any | count   over: runs (each run's measurements, ok runs only unless
    "include_failed"; control runs never count) or qc (the lab's QC summary). Several conditions: {"all": [...]} or {"any": [...]}.

A verdict is signed by m of n referee keys (ed25519) over its canonical bytes: order, evidence hash, spec hash,
verdict, amount, recipient, mint, expiry, nonce. `check` refuses fewer than m distinct registered signers, a key not in
the set, an expired verdict, a replayed nonce, or a verdict whose amount or recipient differ from the vault's.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .base import Results, Spec, canonical, sha256_hex

PASS, FAIL, VOID = "PASS", "FAIL", "VOID"
DOMAIN = b"knos-lab-verdict:v1:"
OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
       "==": lambda a, b: a == b, "!=": lambda a, b: a != b}


class VerdictError(ValueError):
    pass


@dataclass
class Verdict:
    kind: str                    # "lab" or "outcome"
    verdict: str                 # PASS, FAIL or VOID
    reasons: list[str]
    evidence_hash: str
    spec_hash: str
    checks: list[dict] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.verdict == PASS

    def to_dict(self) -> dict:
        return {"kind": self.kind, "verdict": self.verdict, "reasons": self.reasons, "evidence_hash": self.evidence_hash,
                "spec_hash": self.spec_hash, "checks": self.checks}


# ---- conditions -------------------------------------------------------------------------------------------------------

def _values(results: Results, metric: str, over: str, include_failed: bool) -> list[Any]:
    if over == "qc":
        v = results.qc.get(metric)
        return [] if v is None else [v]
    if over != "runs":
        raise VerdictError(f"over: runs or qc, not {over!r}")
    out = []
    for r in results.runs:
        if r.get("control"):                # controls are the lab's QC, never the researcher's result
            continue
        if not r.get("ok") and not include_failed:
            continue
        v = (r.get("measurements") or {}).get(metric)
        if v is not None:
            out.append(v)
    return out


def _agg(values: list[Any], agg: str) -> Any:
    if agg == "count":
        return len(values)
    if not values:
        return None
    if agg in ("all", "any"):
        return values
    nums = [float(v) for v in values]
    pick: dict[str, Callable[[list[float]], float]] = {"median": statistics.median, "min": min, "max": max, "mean": statistics.fmean}
    return pick[agg](nums)


def condition(results: Results, cond: dict) -> tuple[bool, dict]:
    """(held?, a row saying what was compared). A metric the results do not have does not hold."""
    if "all" in cond or "any" in cond:
        key = "all" if "all" in cond else "any"
        rows = [condition(results, c) for c in cond[key]]
        held = all(h for h, _ in rows) if key == "all" else any(h for h, _ in rows)
        return held, {key: [r for _, r in rows], "held": held}
    metric, op, want = cond.get("metric"), cond.get("op", "=="), cond.get("value")
    if not isinstance(metric, str) or op not in OPS:
        raise VerdictError(f"a condition is {{metric, op (one of {' '.join(OPS)}), value, agg?, over?}}: {cond!r}")
    agg, over = cond.get("agg", "median" if cond.get("over", "runs") == "runs" else "value"), cond.get("over", "runs")
    values = _values(results, metric, over, bool(cond.get("include_failed")))
    if over == "qc":
        got: Any = values[0] if values else None
    else:
        got = _agg(values, agg)
    if got is None:
        return False, {"metric": metric, "op": op, "value": want, "got": None, "held": False, "why": "not in the results"}
    if agg == "all":
        held = all(OPS[op](v, want) for v in got)
    elif agg == "any":
        held = any(OPS[op](v, want) for v in got)
    else:
        try:
            held = bool(OPS[op](got, want))
        except TypeError:
            held = False
    return held, {"metric": metric, "op": op, "value": want, "agg": agg, "over": over, "got": got, "held": held}


# ---- the LAB verdict ----------------------------------------------------------------------------------------------------

def lab_verdict(spec: Spec, results: Results) -> Verdict:
    """Protocol executed as specified + every run reported + QC passed. The science (did the design work) is NOT
    looked at here. spec.qc keys:
        protocol_keys   the protocol fields the lab must report back unchanged in protocol_executed
        runs            how many runs (designs x replicates, boards, samples) the order asked for: all must be reported,
                        failed ones included
        lab_qc          True (default): the lab's own QC summary must say passed
        checks          more conditions on the results (controls, instrument checks), as `condition`
        files           True (default): at least one raw file with its sha256"""
    q = spec.qc or {}
    reasons, rows = [], []
    if results.state not in ("completed", "failed"):
        reasons.append(f"the order is {results.state}, not finished: no LAB verdict yet")
    for k in q.get("protocol_keys", []):
        want, got = spec.protocol.get(k), results.protocol_executed.get(k)
        rows.append({"protocol_key": k, "ordered": want, "executed": got, "held": want == got})
        if want != got:
            reasons.append(f"protocol: {k} was ordered as {want!r} and executed as {got!r}")
    runs = q.get("runs")
    if runs is not None and len(results.runs) != runs:
        reasons.append(f"{runs} runs were ordered and {len(results.runs)} reported (every run is reported, failed ones included)")
    for r in results.runs:
        if not r.get("ok") and not r.get("why"):
            reasons.append(f"run {r.get('id')} failed and the lab did not say why")
    if q.get("lab_qc", True) and results.qc.get("passed") is not True:
        reasons.append(f"the lab's QC did not pass: {results.qc.get('why') or results.qc}")
    for c in q.get("checks", []):
        held, row = condition(results, c)
        rows.append(row)
        if not held:
            reasons.append(f"QC check failed: {row}")
    if q.get("files", True) and not any(f.get("sha256") for f in results.files):
        reasons.append("no raw file with its sha256 came back")
    return Verdict("lab", PASS if not reasons else FAIL, reasons or ["protocol executed as specified, every run reported, QC passed"],
                   results.evidence_hash(), spec.hash(), rows)


# ---- the OUTCOME verdict ------------------------------------------------------------------------------------------------

def outcome_verdict(spec: Spec, results: Results, lab: Verdict) -> Verdict:
    """Did the result meet the researcher's claim (spec.claim, a condition)? VOID when the LAB verdict did not pass."""
    if lab.kind != "lab":
        raise VerdictError("outcome_verdict takes the LAB verdict of the same results")
    if lab.evidence_hash != results.evidence_hash():
        raise VerdictError("the LAB verdict was given on other evidence")
    if not lab.passed:
        return Verdict("outcome", VOID, ["the LAB verdict did not pass: the results say nothing about the claim; the reward goes back"],
                       results.evidence_hash(), spec.hash())
    if not spec.claim:
        raise VerdictError("the spec names no claim to hold the result to")
    held, row = condition(results, spec.claim)
    why = "the result met the claim" if held else "the result did not meet the claim (the science failed; the lab is still paid)"
    return Verdict("outcome", PASS if held else FAIL, [why], results.evidence_hash(), spec.hash(), [row])


# ---- m-of-n signed verdicts --------------------------------------------------------------------------------------------

def message(order: str, v: Verdict, *, amount: int, recipient: str, mint: str, expiry: int, nonce: str) -> dict:
    """The verdict as referees sign it: everything a release depends on, and nothing private (hashes, not results)."""
    return {"v": 1, "kind": v.kind, "order": order, "evidence_hash": v.evidence_hash, "spec_hash": v.spec_hash,
            "verdict": v.verdict, "amount": int(amount), "recipient": recipient, "mint": mint, "expiry": int(expiry),
            "nonce": nonce}


def signing_bytes(msg: dict) -> bytes:
    return DOMAIN + canonical(msg)


def digest(msg: dict) -> str:
    return sha256_hex(signing_bytes(msg))


def sign(msg: dict, keypairs: Iterable) -> list[dict]:
    """Each referee's ed25519 signature (solders Keypair) over the verdict."""
    data = signing_bytes(msg)
    return [{"referee": str(k.pubkey()), "signature": str(k.sign_message(data))} for k in keypairs]


class SpentStore:
    """Every lab verdict already accepted, kept on disk so a replay is refused across processes and restarts: one JSON
    line per spent (order, nonce) in <Knos home>/labs/verdicts-spent.jsonl (KNOS_LAB_VERDICTS_SPENT names another
    file). The same rule as knos.platform.verdict (V34PAY): a verdict that is ACCEPTED is spent; a refusal spends
    nothing; record=False is a dry run. Writes take an exclusive lock and are fsynced."""

    def __init__(self, path=None):
        from pathlib import Path
        if path is None:
            named = os.environ.get("KNOS_LAB_VERDICTS_SPENT")
            if named:
                path = Path(named)
            else:
                from .. import paths
                path = paths.home() / "labs" / "verdicts-spent.jsonl"
        self.path = Path(path)

    @staticmethod
    def key(msg: dict) -> str:
        return f"{msg.get('order')}:{msg.get('nonce')}"

    def __contains__(self, key: str) -> bool:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False
        return any(json.loads(line).get("key") == key for line in text.splitlines() if line.strip())

    def spend(self, msg: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            if sys.platform != "win32":
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(json.dumps({"key": self.key(msg), "digest": digest(msg), "at": int(time.time())}, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())


def check(msg: dict, sigs: list[dict], referees: Iterable[str], m: int, *, now: int | None = None,
          seen_nonces: set | None = None, amount: int | None = None, recipient: str | None = None,
          record: bool = True, spent: SpentStore | None = None) -> list[str]:
    """Why this signed verdict may NOT release money; [] when it may. A verdict it accepts is SPENT (record=True, the
    default): its (order, nonce) goes to the persistent store (SpentStore, or `spent`) and its nonce to `seen_nonces`
    when that set is given, so checking the same verdict again is refused as a replay. record=False is a dry run."""
    store = spent if spent is not None else SpentStore()
    from solders.pubkey import Pubkey
    from solders.signature import Signature
    problems = []
    allowed = set(referees)
    if m < 1 or m > len(allowed):
        problems.append(f"m={m} of {len(allowed)} referees is not a threshold")
    data = signing_bytes(msg)
    good = set()
    for s in sigs:
        who = s.get("referee")
        if who not in allowed:
            problems.append(f"{who} is not a registered referee")
            continue
        try:
            ok = Signature.from_string(s["signature"]).verify(Pubkey.from_string(who), data)
        except (ValueError, KeyError):
            ok = False
        if not ok:
            problems.append(f"the signature of {who} does not verify over this verdict")
            continue
        good.add(who)
    if len(good) < m:
        problems.append(f"{len(good)} valid distinct referee signatures; {m} needed")
    if (now if now is not None else int(time.time())) > int(msg.get("expiry", 0)):
        problems.append("the verdict has expired")
    if (seen_nonces is not None and msg.get("nonce") in seen_nonces) or SpentStore.key(msg) in store:
        problems.append("this verdict was already used (its nonce is spent)")
    if amount is not None and int(msg.get("amount", -1)) != int(amount):
        problems.append(f"the verdict releases {msg.get('amount')}, the held money is {amount}")
    if recipient is not None and msg.get("recipient") != recipient:
        problems.append("the verdict pays another recipient than the held money's")
    if not problems and record:
        store.spend(msg)
        if seen_nonces is not None and hasattr(seen_nonces, "add"):
            seen_nonces.add(msg.get("nonce"))
    return problems
