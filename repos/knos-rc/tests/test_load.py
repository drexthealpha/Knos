"""scripts/load.py: fifty orders through the test builds with duplicates and late replays injected, and the
invariants it must report; the arithmetic that turns compute units into cluster time; the cluster path against an RPC
that is LiteSVM behind the JSON-RPC methods the script calls (so the programs are the real test builds, and only the
network is simulated), with transactions dropped and refused on purpose; and that docs/reference/LOAD.md is what the script
renders from docs/load.json."""
from __future__ import annotations

import base64
import importlib.util
import json
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

from solders.transaction import Transaction  # noqa: E402

from _oidc2 import Chain2  # noqa: E402

from knos import chain  # noqa: E402
from knos.settle.v2 import oidc, pay  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("knos_load_script", ROOT / "scripts" / "load.py")
load = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = load          # dataclasses look their module up by name
_spec.loader.exec_module(load)


@pytest.fixture(scope="module")
def fifty():
    return load.run_local(50)


def test_fifty_orders_open_at_once_are_each_paid_once_and_nothing_is_lost(fifty):
    i = fifty["invariants"]
    assert i["ok"], i
    assert i["open_at_once"] == i["paid_exactly_once"] == 50 and i["paid_twice_or_short"] == 0
    assert i["paid"] + i["fees"] + i["refunds"] == i["funded"] > 0
    assert i["left_in_order_accounts_and_vault"] == 0 and i["orders_still_open"] == 0
    assert all(v == 50 for v in i["markers"].values()) and i["markers"]["fund"] == 50
    # every 10th fund token and every 10th pay token twice; order 0's tokens again once it has closed
    assert (i["sent_twice"], i["sent_after_close"], i["replays_accepted"]) == (10, 3, 0) and i["replays_refused"] == 13


def test_every_stage_is_measured_and_fits_a_transaction(fifty):
    s = fifty["stages"]
    for name in load.STAGES:
        x = s[name]
        assert x["orders"] == 50 and x["cu_per_order"]["p50"] <= x["cu_per_order"]["p95"] <= x["cu_per_order"]["max"]
        assert 0 < x["cu_per_tx_max"] <= load.LIMITS["tx_cu"] and 0 < x["bytes_per_tx_max"] <= load.LIMITS["tx_bytes"]
    assert s["fund"]["tx_per_order"] == s["pay"]["tx_per_order"] == {"p50": 1, "max": 1} and s["verify"]["tx_per_order"]["p50"] > 2
    # who every transaction of a stage writes: the fee account is in every payment, a Balance in every funding of its own
    assert any("fee account" in w for w in s["pay"]["written_by_every_tx"]) and not any("fee account" in w for w in s["fund"]["written_by_every_tx"])
    assert any("Balance" in w for w in s["fund"]["written_by_every_tx"]) and len(s["verify"]["written_by_every_tx"]) == 1


def test_the_orders_terms_are_the_canonical_form_a_judge_reads():
    from knos import terms
    assert terms.parse(load.TERMS) == {"accept": "", "checks": [{"app": 15368, "name": "test"}], "deny": [".github/**", ".knos/**"], "mode": "merge",
                                       "paths": [], "reserve": 0, "v": 1}


def test_a_sustained_rate_limit_is_waited_out_for_about_a_minute_and_then_is_the_error(monkeypatch):
    # rehearsed on devnet (0.3.14): K senders polling the public endpoint met HTTP 429 past chain.call's own backoff, and
    # the run ended there though nothing was wrong with its transactions
    import urllib.error
    slept, left = [], [4]

    def call(url, method, params, timeout=30.0):
        if left[0]:
            left[0] -= 1
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
        return {"method": method}
    monkeypatch.setattr(load.chain, "call", call)
    monkeypatch.setattr(load.time, "sleep", slept.append)
    assert load.Rpc("https://rpc.invalid").call("getSlot", []) == {"method": "getSlot"} and sum(slept) == 65
    left[0], slept[:] = 9, []
    with pytest.raises(urllib.error.HTTPError):
        load.Rpc("https://rpc.invalid").call("getSlot", [])
    assert sum(slept) == 65

    def refused(url, method, params, timeout=30.0):
        raise urllib.error.HTTPError(url, 500, "Internal Server Error", {}, None)
    monkeypatch.setattr(load.chain, "call", refused)
    slept[:] = []
    with pytest.raises(urllib.error.HTTPError):
        load.Rpc("https://rpc.invalid").call("getSlot", [])
    assert slept == []                  # any other error is the answer at once


def test_cluster_time_is_the_slowest_ceiling():
    stages = {"verify": {"cu_per_order": {"mean": 3_000_000}}, "fund": {"cu_per_order": {"mean": 120_000}}, "pay": {"cu_per_order": {"mean": 240_000}}}
    d = load.derive(stages, orders=1000, block_cu=100_000_000)
    assert d["cu_per_order"] == 3_360_000 and d["one_relayer_orders_per_second"] == round(12_000_000 / 3_360_000 / 0.4, 2)
    one, four, sixteen = (d["relayers"][k] for k in ("1", "4", "16"))
    assert (one["blocks"], one["bound_by"], one["under_a_minute"]) == (280, "the relayers' own accounts", False)      # 3.36e9 / 12M
    assert (four["blocks"], four["seconds"], four["under_a_minute"]) == (70, 28.0, True)
    assert (sixteen["blocks"], sixteen["bound_by"]) == (34, "the block")                                              # 3.36e9 / 100M, rounded up
    # verification free: the fee account caps payments whatever the relayers
    stages["verify"]["cu_per_order"]["mean"] = 0
    assert load.derive(stages)["relayers"]["16"] == {"blocks": 20, "seconds": 8.0, "bound_by": "the fee account", "orders_per_second": 125.0, "under_a_minute": True}
    assert load.pct([5, 1, 3, 2, 4], 50) == 3 and load.pct(range(1, 101), 95) == 95 and load.pct([], 50) is None and load.pct([7], 99) == 7


class FakeRpc:
    """The JSON-RPC methods scripts/load.py calls, answered by LiteSVM with the test builds of both programs. A
    transaction is `confirmed` the first time its status is asked and `finalized` the third. `drop(k)`: the k-th
    submission is acknowledged and thrown away, as a cluster under load does; `refuse(program, tag)`: preflight fails.
    A transaction may be signed over any of the last 150 blockhashes, as on a cluster: LiteSVM takes only its newest,
    and every landed transaction moves it on, so with three senders one of them could see its blockhash expire before
    it sent four times running. Its own check is off, and this one stands in for it."""
    def __init__(self, drop=lambda k: False, refuse=lambda program, tag: False):
        self.c = Chain2(programs={pay.PAY_ID: "knos_pay_v2_test.so"})
        self.c.svm = self.c.svm.with_blockhash_check(False)
        self.recent = [str(self.c.svm.latest_blockhash())]
        self.drop, self.refuse, self.lock = drop, refuse, threading.Lock()
        self.asked: dict[str, int] = {}
        self.seen: set[str] = set()
        self.submissions, self.t = 0, 0.0

    def clock(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        with self.lock:
            self.t += seconds
            self.c.warp(1)

    def call(self, method: str, params: list):
        with self.lock:
            return getattr(self, "_" + method)(*params)

    def _getLatestBlockhash(self, _cfg):
        return {"value": {"blockhash": str(self.c.svm.latest_blockhash())}}

    def _getMinimumBalanceForRentExemption(self, space):
        return self.c.svm.minimum_balance_for_rent_exemption(space)

    def _getSlot(self, _cfg):
        return 1

    def _getBlockTime(self, _slot):
        return self.c.now()

    def _sendTransaction(self, raw, _cfg):
        tx = Transaction.from_bytes(base64.b64decode(raw))
        sig = str(tx.signatures[0])
        self.submissions += 1
        keys = tx.message.account_keys
        ix = tx.message.instructions[-1]
        if self.refuse(keys[ix.program_id_index], bytes(ix.data)[0]):
            raise chain.RpcError("Transaction simulation failed: refused on purpose")
        if str(tx.message.recent_blockhash) not in self.recent[-150:]:
            raise chain.RpcError("Transaction simulation failed: Blockhash not found")
        if sig not in self.seen and self.drop(self.submissions):
            self.seen.add(sig)
            return sig
        self.seen.add(sig)
        r = self.c.svm.send_transaction(tx)
        if "Failed" in type(r).__name__:
            raise chain.RpcError(f"Transaction simulation failed: {r.err()}")
        self.c.svm.expire_blockhash()        # the next slot: a new recent blockhash
        self.recent.append(str(self.c.svm.latest_blockhash()))
        self.asked[sig] = 0
        return sig

    def _getSignatureStatuses(self, sigs, _cfg):
        out = []
        for s in sigs:
            if s not in self.asked:
                out.append(None)
                continue
            self.asked[s] += 1
            out.append({"err": None, "confirmationStatus": "finalized" if self.asked[s] >= 3 else "confirmed"})
        return {"value": out}

    def _getMultipleAccounts(self, addresses, _cfg):
        from solders.pubkey import Pubkey
        got = [self.c.data(Pubkey.from_string(a)) for a in addresses]
        return {"value": [None if d is None else {"data": [base64.b64encode(d).decode(), "base64"]} for d in got]}


def devnet(rpc: FakeRpc, n: int, **kw) -> dict:
    from cryptography.hazmat.primitives.asymmetric import rsa
    wallet = rpc.c.fund()
    sender = load.Sender(rpc, wallet, within=30.0, poll=1.0, clock=rpc.clock, sleep=rpc.sleep)     # the clock is shared by the three senders
    return load.run_devnet(rpc, wallet, rsa.generate_private_key(public_exponent=65537, key_size=2048), n, senders=3, sender=sender, name="fake", **kw)


def test_the_cluster_path_verifies_funds_and_refunds_with_a_test_issuer_and_counts_its_retries():
    rpc = FakeRpc(drop=lambda k: k % 9 == 0)
    r = devnet(rpc, 6)
    assert r["ok"], r
    v, f = r["stages"]["verify"], r["stages"]["fund"]
    # every token is on chain, VERIFIED under the wallet's private key for the issuer's URL; every order open, then gone
    assert v["verified_on_chain"] == v["units_finalized"] == 6 and v["failures"] == 0 and v["transactions"] >= 6 * 3
    assert f["open_on_chain"] == 6 and r["stages"]["refund"]["units_finalized"] == 6 and r["stages"]["close"]["units_finalized"] == 6
    assert r["checks"]["held_equals_funded"] and r["checks"]["nothing_lost"] and r["checks"]["orders_left"] == 0
    assert sum(s["retries"] for s in r["stages"].values()) > 0                       # the dropped ones were signed again and landed
    # a dropped transaction waited out its thirty seconds first: it shows in the tail, not in the median
    assert v["tx_submit_to_finalized_s"]["p50"] < v["tx_submit_to_finalized_s"]["max"] and v["unit_submit_to_finalized_s"]["p99"] is not None
    assert set(r["not_exercised"]) == {"pay", "fund from a Balance", "meter"} and r["cluster"] == "fake"
    # what the page says of a run comes out of the record
    text = load.render({"limits": load.LIMITS, "sources": load.SOURCES, "runs": [r]})
    assert "fake, " in text and "6 of 6" in text and "No cluster run is recorded yet" not in text


def test_a_refused_stage_is_reported_as_failures_and_the_run_is_not_ok():
    rpc = FakeRpc(refuse=lambda program, tag: program == pay.PAY_ID and tag == 0x0f)      # FundOrderWallet
    r = devnet(rpc, 3, refund=False)
    f = r["stages"]["fund"]
    assert not r["ok"] and (f["failures"], f["units_finalized"], f["open_on_chain"]) == (3, 0, 0) and "refused on purpose" in f["first_failures"][0]
    assert r["stages"]["verify"]["verified_on_chain"] == 3 and "refund" not in r["stages"]


def test_a_private_key_cannot_pay_an_order_a_wallet_funded():
    """Why the cluster tier stops before PayOrder: the escrow refuses a pay token under a test issuer's key."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    rpc = FakeRpc()
    c, wallet, key = rpc.c, rpc.c.fund(), rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sender = load.Sender(rpc, wallet, within=4.0, clock=rpc.clock, sleep=rpc.sleep)
    r = load.run_devnet(rpc, wallet, key, 1, senders=1, sender=sender, refund=False)
    assert r["stages"]["fund"]["open_on_chain"] == 1
    me, n = wallet.pubkey(), key.public_key().public_numbers().n
    order = next(a for a, acc in c.svm.get_program_accounts(pay.PAY_ID) if len(bytes(acc.data)) == pay.ORDER_LEN)
    o = pay.read_order(c.data(order))
    payee = (4242, 10_000, me)
    claims = dict(json.loads(base64.urlsafe_b64decode(load.issuer_token(key, load.ISSUER_URL, c.now(), 0, "x").split(".")[1] + "==")),
                  aud=pay.order_pay_audience(order, "a" * 40, o.terms, o.mode, 7, [payee]), repository_id=str(o.repo_id), repository_owner_id="1",
                  actor_id="1", run_attempt="1", runner_environment="github-hosted", event_name="pull_request_target", repository="o/r",
                  job_workflow_ref=f"{load.WF_REPO}/.github/workflows/prove.yml@refs/tags/v1", job_workflow_sha=load.WF_SHA)
    from _settle import sign_jwt
    tok = c.verify(sign_jwt(key, claims), load.ISSUER_URL, n, payer=wallet, registrant=me)
    assert tok is not None and oidc.token_issuer(c.data(tok))[1] == me                 # the verifier takes it
    c.send([pay.create_ata_ix(me, pay.FEE_OWNER, o.mint)], wallet)
    ix = pay.pay_order_ix(me, tok, oidc.key_pda(load.ISSUER_URL, n, registrant=me), order, o, [(4242, me)], pr=7)
    assert not c.send([ix], wallet) and "Custom(84)" in c.err, c.err                    # the escrow does not: E_TOKEN
    assert pay.read_order(c.data(order)).state == "open"


def test_the_page_is_what_the_script_renders_and_the_committed_run_is_a_thousand():
    doc = json.loads(load.JSON.read_text(encoding="utf-8"))
    assert load.DOC.read_text(encoding="utf-8") == load.render(doc)
    i = doc["local"]["invariants"]
    assert i["ok"] and i["orders"] == i["open_at_once"] == i["paid_exactly_once"] == 1000 and i["replays_accepted"] == 0
    assert doc["limits"] == load.LIMITS and all(r["cluster"] != "local" for r in doc["runs"])
    text = load.DOC.read_text(encoding="utf-8")
    assert "measured in the local simulator" in text and "Compute units are exact" in text and "is derived" in text
    # the builds the page reports are the ones in tests/fixtures: a number from another build is not a measurement of this one
    assert doc["local"]["fixtures"] == load.fixtures()
