"""A NEAR payout is marked paid only when it is final: send_tx waits for FINAL, every receipt must succeed, and two RPC
providers must each say so (near/agents/common.py confirm_final, near/agents/checker.py settled). A stubbed RPC, no
network."""
from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pytest

AGENTS = Path(__file__).resolve().parents[1] / "near" / "agents"
sys.path.insert(0, str(AGENTS))

import checker  # noqa: E402
import common  # noqa: E402

A, B = "https://rpc-a.test", "https://rpc-b.test"


def tx(*receipts: str, final: str = "FINAL") -> dict:
    ok = {"outcome": {"status": {"SuccessValue": ""}}}
    bad = {"outcome": {"status": {"Failure": {"ActionError": {"kind": "FunctionCallError"}}}}}
    return {"final_execution_status": final, "transaction_outcome": ok, "receipts_outcome": [bad if r == "fail" else ok for r in receipts],
            "status": {"SuccessValue": ""}, "transaction": {"hash": "H"}}


def stub(monkeypatch, answers: dict) -> list:
    asked = []

    def at(url, method, params):
        asked.append((url, method, params))
        got = answers[url]
        if isinstance(got, Exception):
            raise got
        return got
    monkeypatch.setattr(common, "_rpc_at", at)
    return asked


def test_two_providers_final_is_paid(monkeypatch):
    asked = stub(monkeypatch, {A: tx("ok", "ok"), B: tx("ok", "ok")})
    c = common.confirm_final("H", "relayer.testnet", [A, B], tries=1)
    assert c == {"state": "paid", "paid": True, "seen": {A: "final", B: "final"}}
    assert all(p["wait_until"] == "FINAL" and m == "tx" for _u, m, p in asked)


def test_a_failed_receipt_keeps_it_unpaid(monkeypatch):
    stub(monkeypatch, {A: tx("ok", "fail"), B: tx("ok", "fail")})
    c = common.confirm_final("H", "relayer.testnet", [A, B], tries=1)
    assert c["state"] == "failed" and c["paid"] is False


def test_a_timeout_holds_it_as_releasing(monkeypatch):
    stub(monkeypatch, {A: TimeoutError("slow"), B: urllib.error.URLError("down")})
    c = common.confirm_final("H", "relayer.testnet", [A, B], tries=2, wait_s=0)
    assert c["state"] == "releasing" and c["paid"] is False


def test_two_providers_that_disagree_hold_it(monkeypatch):
    stub(monkeypatch, {A: tx("ok"), B: tx("ok", final="EXECUTED_OPTIMISTIC")})
    c = common.confirm_final("H", "relayer.testnet", [A, B], tries=2, wait_s=0)
    assert c["state"] == "releasing" and c["paid"] is False and c["seen"] == {A: "final", B: "unknown"}


def test_one_provider_alone_never_pays(monkeypatch):
    stub(monkeypatch, {A: tx("ok")})
    assert common.confirm_final("H", "relayer.testnet", [A], tries=1)["paid"] is False


def test_outcome_with_a_failed_receipt_is_not_ok():
    assert common._outcome(tx("ok", "fail"))["ok"] is False
    assert common._outcome(tx("ok", "ok"))["ok"] is True


@pytest.mark.parametrize(("state", "ok", "word"), [("paid", True, ""), ("releasing", False, "releasing"), ("failed", False, "failed")])
def test_release_waits_for_final_and_two_providers(monkeypatch, state, ok, word):
    sent = {}

    def call(who, contract, method, args, deposit="0 NEAR", gas="100 Tgas", wait="FINAL"):
        sent.update(method=method, wait=wait)
        return {"ok": True, "tx": "H", "said": "ok", "url": common.EXPLORER + "H"}
    monkeypatch.setattr(checker, "call", call)
    monkeypatch.setattr(checker, "sign", lambda claims: "token")
    monkeypatch.setattr(checker, "confirm_final", lambda h, who: {"state": state, "paid": state == "paid", "seen": {}})
    r = checker.release_one("job-1", "agent-a2.knos-swarm-1105.testnet", "0" * 64, "1" * 64)
    assert sent == {"method": "release_job", "wait": "FINAL"}
    assert r["ok"] is ok and r["final"]["state"] == state
    assert word in r["said"]
    assert "paid" not in r["said"] or not ok and "not" in r["said"]
