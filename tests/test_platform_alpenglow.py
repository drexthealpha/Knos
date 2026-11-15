"""Alpenglow (knos.platform.finality): detected per cluster by getAgGenesisCert, never by a date or a version string;
`finalized` everywhere when it is active, today's `confirmed` when it is not; "paid and final in N ms"; and the
latency figures' parser. Nothing here asks a real cluster: every answer is a stand-in shaped like the documented one
(https://solana.com/docs/rpc/http/getaggenesiscert)."""
from __future__ import annotations

import json

import pytest

from knos import chain
from knos.platform import finality

# the shape of devnet's answer on 14 Oct 2026 (block id and bitmap shortened to what the parser reads; synthetic signature)
CERT = {"block": {"blockId": [19, 240, 158, 210] + [0] * 28, "slot": 504148999},
        "signature": {"bitmap": [0, 17, 0, 159, 198, 1], "signature": [6] * 192}}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("KNOS_COMMITMENT", raising=False)
    monkeypatch.delenv("KNOS_ALPENGLOW", raising=False)
    finality.forget()
    yield
    finality.forget()


def answering(result=None, code=None, seen=None):
    """ask(method, params) that answers getAgGenesisCert with `result`, or raises an RpcError with `code`."""
    def ask(method, params):
        if seen is not None:
            seen.append(method)
        assert method == "getAgGenesisCert" and params == []
        if code is not None:
            raise chain.RpcError("Method not found" if code == -32601 else "boom", None, code)
        return result
    return ask


# ---- detection ----------------------------------------------------------------------------------------------------
def test_a_certificate_means_alpenglow_null_means_towerbft_and_method_not_found_means_an_old_rpc():
    c = finality.ask_rpc("https://a.example", answering(CERT))
    assert c.active and c.why == "cert" and c.slot == 504148999 and c.block_id.startswith("13f09ed2")
    assert c.signers == sum(bin(b).count("1") for b in CERT["signature"]["bitmap"]) == 13
    n = finality.ask_rpc("https://a.example", answering(None))
    assert not n.active and n.why == "null"
    old = finality.ask_rpc("https://a.example", answering(code=-32601))
    assert not old.active and old.why == "method-not-found"
    # any other error, no answer, or a result that is no certificate: say nothing, keep TowerBFT's behaviour
    assert finality.ask_rpc("u", answering(code=-32000)).why == "no-answer"
    assert finality.ask_rpc("u", lambda m, p: (_ for _ in ()).throw(TimeoutError())).why == "no-answer"
    for junk in ({"block": {}}, {"value": 3}, [1, 2], "cert", {"block": {"slot": "1"}, "signature": {}}):
        assert not finality.ask_rpc("u", answering(junk)).active


def test_detection_is_kept_per_rpc_url_and_a_null_is_asked_again_later():
    seen: list = []
    assert finality.alpenglow("https://ag.example", answering(CERT, seen=seen))
    assert finality.alpenglow("https://ag.example", answering(None, seen=seen))      # a certificate is kept: not asked again
    assert seen == ["getAgGenesisCert"]
    tower: list = []
    assert not finality.detect("https://tower.example", answering(None, seen=tower), now=0.0).active
    assert not finality.detect("https://tower.example", answering(CERT, seen=tower), now=finality.TOWER_TTL_S - 1).active
    assert len(tower) == 1          # another URL has its own answer, and a null is kept for TOWER_TTL_S ...
    assert finality.detect("https://tower.example", answering(CERT, seen=tower), now=finality.TOWER_TTL_S + 1).active
    assert len(tower) == 2          # ... then asked again: a running relay notices the migration without a restart
    finality.forget("https://ag.example")
    assert not finality.alpenglow("https://ag.example", answering(code=-32601))


def test_never_a_date_or_a_version_string_only_the_answer_or_the_operators_override(monkeypatch):
    def nope(method, params):
        raise AssertionError("asked")
    assert not finality.alpenglow("file:///x", nope) and not finality.alpenglow(None, nope)     # not an RPC URL: nothing asked
    monkeypatch.setenv("KNOS_ALPENGLOW", "on")
    assert finality.alpenglow("https://x.example", nope) and finality.at("https://x.example", nope) == "finalized"
    monkeypatch.setenv("KNOS_ALPENGLOW", "off")
    assert not finality.alpenglow("https://x.example", nope) and finality.at("https://x.example", nope) == "confirmed"
    src = open(finality.__file__, encoding="utf-8").read()
    assert "getVersion" not in src and "solana-core" not in src and "epoch" not in src.split('"""', 2)[2]


def test_the_rpc_error_keeps_its_json_rpc_code(monkeypatch):
    class Resp:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.body
    monkeypatch.setattr(chain.urllib.request, "urlopen", lambda req, timeout=10.0: Resp(json.dumps(
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}).encode()))
    with pytest.raises(chain.RpcError) as e:
        chain.call("https://old.example", "getAgGenesisCert", [])
    assert e.value.code == -32601
    assert finality.detect("https://old.example").why == "method-not-found"     # through chain.call, as the Ledger asks


# ---- commitment choice --------------------------------------------------------------------------------------------
def test_finalized_on_alpenglow_confirmed_on_towerbft_and_knos_commitment_still_wins(monkeypatch):
    assert finality.commitment(None, "https://ag.example", answering(CERT)) == "finalized"
    assert finality.commitment(None, "https://tw.example", answering(None)) == "confirmed"
    assert finality.commitment(None, "https://old.example", answering(code=-32601)) == "confirmed"
    assert finality.commitment() == "confirmed"         # no cluster named: today's default
    monkeypatch.setenv("KNOS_COMMITMENT", "confirmed")
    assert finality.commitment(None, "https://ag.example") == "confirmed"
    monkeypatch.setenv("KNOS_COMMITMENT", "processed")
    assert finality.at("https://tw.example") == "processed"
    assert finality.commitment("finalized", "https://tw.example") == "finalized"     # an explicit value wins over both


def test_a_ledger_asks_nothing_when_made_and_chooses_on_first_use_through_its_own_transport(monkeypatch):
    asked: list = []

    def fake(url, method, params, timeout=10.0):
        asked.append((url, method))
        return CERT if url == "https://ag.example" else None
    monkeypatch.setattr(chain, "call", fake)
    ag, tw = chain.Ledger("https://ag.example"), chain.Ledger("https://tw.example")
    assert asked == []
    assert ag.commitment == "finalized" and tw.commitment == "confirmed"
    assert ag.commitment == "finalized" and asked == [("https://ag.example", "getAgGenesisCert"), ("https://tw.example", "getAgGenesisCert")]
    assert chain.Ledger("https://ag.example", commitment="confirmed").commitment == "confirmed"
    with pytest.raises(ValueError):
        chain.Ledger("https://ag.example", commitment="rooted")
    # reads, the blockhash and preflight follow the ledger's commitment
    monkeypatch.setattr(chain, "call", lambda url, method, params, timeout=10.0: (asked.append((method, params)),
                        {"value": {"blockhash": "11111111111111111111111111111111"}})[1])
    ag._blockhash()
    assert asked[-1] == ("getLatestBlockhash", [{"commitment": "finalized"}])


def test_a_ledger_that_only_reads_asks_nothing_more_and_reads_at_what_is_known(monkeypatch):
    asked: list = []
    monkeypatch.setattr(chain, "call", lambda url, method, params, timeout=10.0: (asked.append((method, params)), {"value": None})[1])
    led = chain.Ledger("https://ag.example")
    led.account(chain.CLOCK)
    assert [m for m, _p in asked] == ["getAccountInfo"] and asked[0][1][1]["commitment"] == "confirmed"
    finality.detect("https://ag.example", answering(CERT))        # a send or a wait elsewhere in the process learned it
    led.account(chain.CLOCK)
    assert asked[-1][1][1]["commitment"] == "finalized" and finality.cached("https://ag.example") == "finalized"
    assert finality.cached("https://unknown.example") == "confirmed"


def test_wait_waits_at_the_clusters_commitment_when_none_is_named(monkeypatch):
    statuses = {"s": {"confirmationStatus": "confirmed", "err": None}}

    def fake(url, method, params, timeout=10.0):
        if method == "getAgGenesisCert":
            return CERT if "ag" in url else None
        return {"value": [statuses[s] for s in params[0]]}
    monkeypatch.setattr(chain, "call", fake)
    monkeypatch.setattr(chain.time, "sleep", lambda s: None)
    assert chain.wait("https://tw.example", "s", 1.0)["confirmationStatus"] == "confirmed"     # TowerBFT: as today
    with pytest.raises(TimeoutError):
        chain.wait("https://ag.example", "s", 0.0)       # Alpenglow: confirmed is not enough, finalized is waited for
    statuses["s"] = {"confirmationStatus": "finalized", "err": None}
    assert chain.wait("https://ag.example", "s", 1.0)["confirmationStatus"] == "finalized"


def test_the_fan_out_ledger_asks_through_its_own_post_and_looks_sooner_on_alpenglow():
    from knos.settle.v2.fanout import POLL_S, FanLedger
    for cert, first in ((CERT, finality.FIRST_POLL_ALPENGLOW_S), (None, POLL_S)):
        finality.forget()
        slept: list = []
        posted: list = []

        def post(url, method, params, cert=cert):
            posted.append(method)
            if method == "getAgGenesisCert":
                return cert
            return {"value": [{"confirmationStatus": "finalized", "err": None} for _ in params[0]]}
        led = FanLedger("https://fan.example", seconds=(), sleep=slept.append)
        led._post = post
        led._confirm({"sig": "raw"})
        assert led.commitment == ("finalized" if cert else "confirmed") and slept[0] == first
        assert posted[0] == "getAgGenesisCert" and posted.count("getAgGenesisCert") == 1


def test_a_sent_transaction_keeps_its_time_to_finality_and_says_paid_and_final():
    row = finality.timed("sigA", 10.0, 10.412, "finalized", "https://ag.example")
    assert row["final_ms"] == 412 and row["final"] and finality.timing_of("sigA") == row
    assert finality.words(row) == "paid and final in 412 ms"
    conf = finality.timed("sigB", 0.0, 1.5, "confirmed")
    assert not conf["final"] and finality.words(conf).startswith("paid (confirmed in 1500 ms")
    assert finality.timing_of("nope") is None and finality.timing_of(None) is None and finality.words(None) == ""
    assert finality.final_wait("https://ag.example", answering(CERT)) == finality.FINAL_WAIT_ALPENGLOW_S < finality.FINAL_WAIT_TOWER_S
    assert finality.final_wait("https://tw.example", answering(None)) == finality.FINAL_WAIT_TOWER_S


def test_the_payment_comment_says_paid_and_final_in_n_ms():
    from knos import flow

    class Run:
        clock = staticmethod(lambda: 100.0)
    st = flow._Status(Run(), 12, 50.0, "the merge")
    st.reach("submitted", 60.0)
    st.reach("confirmed", 61.0)
    assert st.final_in() == "" and "Paid and final" not in st.block()
    st.sig = "sigC"
    finality.timed("sigC", 0.0, 0.873, "finalized")
    st.reach("finalized", 61.0)
    assert st.final_in() == "in 873 ms" and "<sub>Paid and final in 873 ms after it was sent to Solana.</sub>" in st.block()
    st2 = flow._Status(Run(), 12, 50.0, "the merge")      # no time of this process's own: the states' (TowerBFT: tens of seconds)
    st2.reach("submitted", 60.0)
    st2.reach("finalized", 73.4)
    assert st2.final_in() == "in 13 s"


# ---- the latency figures ---------------------------------------------------------------------------------------------
def test_the_latency_parser_gives_p50_and_p95_by_nearest_rank_and_skips_what_is_not_a_measure():
    rows = [json.dumps({"kind": "record_anchor", "finalized_ms": v, "err": None}) for v in range(1, 21)]      # 1..20 ms
    rows += [json.dumps({"kind": "vault_fund", "finalized_ms": 1000}), json.dumps({"kind": "vault_fund", "finalized_ms": 3000})]
    rows += ["", "not json", json.dumps({"kind": "vault_fund", "finalized_ms": None}), json.dumps({"kind": "x", "finalized_ms": 5, "err": "failed"}),
             json.dumps({"kind": "x", "finalized_ms": True}), json.dumps({"kind": "x", "finalized_ms": -1})]
    got = finality.parse(rows)
    assert got["skipped"] == 5
    assert got["by_kind"]["record_anchor"] == {"n": 20, "p50": 10, "p95": 19, "min": 1, "max": 20}
    assert got["by_kind"]["vault_fund"] == {"n": 2, "p50": 1000, "p95": 3000, "min": 1000, "max": 3000}
    assert got["all"]["n"] == 22 and got["all"]["p50"] == 11 and got["all"]["p95"] == 1000
    assert finality.parse([{"kind": "k", "knos_wait_ms": 7}], "knos_wait_ms")["all"]["p50"] == 7
    assert finality.summary([]) == {"n": 0, "p50": None, "p95": None, "min": None, "max": None}
    assert finality.percentile([5.0], 95) == 5.0 and finality.percentile([], 50) is None


def test_the_committed_measurement_is_labelled_and_has_at_least_thirty_runs():
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "docs" / "finality.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    assert "internal dogfooding" in m["label"] and "our own devnet test traffic" in m["label"]
    assert m["all"]["n"] >= 30 and m["all"]["p50"] <= m["all"]["p95"]
    assert set(m["by_kind"]) <= {"record_anchor", "vault_fund", "vault_refund"} and m["consensus"]["why"] == "cert"


def test_the_stats_page_carries_the_finality_block():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("network_stats", Path(__file__).resolve().parent.parent / "scripts" / "network_stats.py")
    ns = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ns)
    got = ns.finality_block("https://ag.example", answering(CERT))
    assert got["consensus"] == "alpenglow" and got["commitment"] == "finalized" and got["genesis_slot"] == 504148999
    assert got["measured"]["all"]["n"] >= 30
    finality.forget()
    tw = ns.finality_block("https://tw.example", answering(None))
    assert tw["consensus"] == "towerbft" and tw["commitment"] == "confirmed" and tw["detected_by"] == "null"
