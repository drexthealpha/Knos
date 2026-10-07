"""Receipts of each assurance level, built from the conformance vectors with fixed ids, for tests/test_assurance.py and
tests/test_statement.py. Nothing here is random and nothing reads a clock."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from knos import receipt

ROOT = Path(__file__).resolve().parents[1]
V3 = json.loads((ROOT / "docs" / "receipt" / "vectors.json").read_text(encoding="utf-8"))["valid_v3"]
V4 = json.loads((ROOT / "docs" / "receipt" / "vectors.v4.json").read_text(encoding="utf-8"))["valid_v4"]
SECOND = {"repository_id": "990000002", "repository_owner_id": "9001", "actor_id": "9002", "runner_environment": "github-hosted"}   # a second evaluator's run


def ran(claims: dict, assurance: str = "black-box") -> dict:
    """An evaluator's `reexecution`, as its run would hand it on: it ran the suite itself, in the run these claims name."""
    return {"reexecuted": True, "assurance": assurance, "image_digest": None,
            "environment": {"github_repository_id": str(claims["repository_id"]), "github_run_attempt": "1", "github_run_id": str(claims.get("run_id", "37000000009")),
                            "knos": "0.3.19", "runner_os": "Linux"}}


def base(times: int = 1) -> dict:
    """Version 3's fourth vector (a passkey wallet funds; an arbiter outside the order's repository rules, owner 31337;
    payees 111, 222, 333, 444), with every amount multiplied by `times`."""
    r = copy.deepcopy(V3[3]["receipt"])
    r["amounts"] = {**r["amounts"], **{k: str(int(r["amounts"][k]) * times) for k in ("paid", "of", "fee", "tip")}}
    r["payees"] = [{**p, "amount": str(int(p["amount"]) * times)} for p in r["payees"]]
    assert receipt.check(r) is None, receipt.check(r)
    return r


def three(level: str, times: int = 1) -> dict:
    """A version 3 receipt whose evidence reaches `level`: reported (nobody says how the verdict was reached), rerun (the
    arbiter ran the suite itself), agreed (a neutral evaluator of another owner ran it too)."""
    r = base(times)
    o, c = r["evaluator_observed"], r["commercial_authorisation"]
    if level in ("rerun", "agreed"):
        o["evaluators"][-1]["reexecution"] = ran(r["issuer_authenticated"]["claims"])
    if level == "agreed":
        other = receipt.evaluator("neutral", SECOND, (c["funder"]["github_id"], c["source"]["owner_id"]), [p["github_id"] for p in r["payees"]], ran(SECOND))
        o["evaluators"].insert(0, other)
        o["same_controller"], o["independence"] = receipt.independence_of(o["evaluators"])
    assert receipt.check(r) is None, receipt.check(r)
    return r


def five(level: str, declared=(), invoice_line: str | None = None, times: int = 1) -> dict:
    return receipt.build5(receipt.build4(three(level, times), invoice_line=invoice_line), declared)
