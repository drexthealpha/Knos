"""The receipts page of the NEAR jobs contract (near/web/receipts.html, written from near/scripts/receipts.py): one CSV
row per job with its funding, proof, payout and refund and their testnet links, and totals equal to the contract's own
get_totals view read in the same run."""
from __future__ import annotations

import base64
import csv
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "near" / "web"
sys.path.insert(0, str(ROOT / "near" / "scripts"))

import receipts  # noqa: E402

NEED = {"job", "funded", "proof", "released", "refunded", "amount", "token", "funded_tx", "released_tx", "refunded_tx"}


def tx(h: str, t: int, signer: str, receipts_: list[tuple[str, str, str, dict]], fail: bool = False) -> dict:
    """A whole transaction as the index returns it: each receipt (receiver, predecessor, method, args)."""
    rs = [{"receipt": {"receiver_id": rc, "predecessor_id": pr, "receipt": {"Action": {"actions": [
        {"FunctionCall": {"method_name": m, "args": base64.b64encode(json.dumps(a).encode()).decode()}}]}}},
        "execution_outcome": {"outcome": {"status": {"Failure": {}} if fail else {"SuccessValue": ""}, "gas_burnt": 1}}}
        for rc, pr, m, a in receipts_]
    return {"transaction": {"hash": h, "signer_id": signer}, "execution_outcome": {"block_timestamp": str(t * 10**9)}, "receipts": rs}


def fund(h: str, t: int, jid: str, amount: str, msg: dict | None = None) -> dict:
    m = json.dumps(msg or {"open_job": {"id": jid}})
    return tx(h, t, "payer.testnet", [("knos-usdc-1102.testnet", "payer.testnet", "ft_transfer_call", {"receiver_id": J, "amount": amount, "msg": m}),
                                      (J, "knos-usdc-1102.testnet", "ft_on_transfer", {})])


J = receipts.JOBS


def test_build_one_record_per_job_from_its_transactions():
    txs = [fund("F1", 1_794_700_000, "job-1", "1000"),
           tx("P1", 1_794_700_060, "live.testnet", [(J, "live.testnet", "release_job", {"id": "job-1"}),
                                                    ("knos-usdc-1102.testnet", J, "ft_transfer", {"amount": "900", "memo": "knos job job-1"}),
                                                    ("knos-usdc-1102.testnet", J, "ft_transfer", {"amount": "100", "memo": "knos fee, job job-1"})]),
           fund("F2", 1_794_700_100, "job-2", "500"),
           tx("X2", 1_794_700_150, "live.testnet", [(J, "live.testnet", "release_job", {"id": "job-2"})], fail=True),   # refused
           tx("R2", 1_794_800_000, "payer.testnet", [(J, "payer.testnet", "refund_job", {"id": "job-2"})]),
           fund("B1", 1_794_700_200, "", "2", {"budget": {"agent": "b", "cap": "1"}}),
           fund("F3", 1_794_700_300, "job-3", "7")]                         # an open the contract refused: it has no job-3
    state = {"job-1": {"state": "Paid", "paid_to": "agent.testnet", "proof_jti": "jti-1"}, "job-2": {"state": "Refunded"}}
    jobs = {j["job"]: j for j in receipts.build(txs, state.get)}
    assert set(jobs) == {"job-1", "job-2"}                     # the budget funding is not a job; job-3 does not exist
    one, two = jobs["job-1"], jobs["job-2"]
    assert (one["amount"], one["fee"], one["proof"], one["paid_to"]) == ("1000", "100", "jti-1", "agent.testnet")
    assert one["released_tx"] == receipts.TX + "P1" and one["funded_tx"] == receipts.TX + "F1" and not one["refunded"]
    assert two["refunded_tx"] == receipts.TX + "R2" and not two["released"]
    assert receipts.sums(list(jobs.values())) == {"knos-usdc-1102.testnet": {"locked": 1500, "paid": 1000, "refunded": 500, "open": 0}}


def test_csv_has_every_column_and_one_row_per_job():
    text = (WEB / "receipts.csv").read_text(encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert NEED <= set(rows[0]) and list(rows[0]) == receipts.COLUMNS
    ids = [r["job"] for r in rows]
    assert len(ids) == len(set(ids)) > 0
    for r in rows:
        for k in ("funded_tx", "released_tx", "refunded_tx"):
            assert not r[k] or r[k].startswith("https://testnet.nearblocks.io/txns/")
        assert not (r["released_tx"] and r["refunded_tx"])          # a job is paid or refunded, never both


def test_csv_matches_the_json_the_page_reads():
    data = json.loads((WEB / "receipts.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader(io.StringIO((WEB / "receipts.csv").read_text(encoding="utf-8"))))
    assert [r["job"] for r in rows] == [j["job"] for j in data["jobs"]]


def test_totals_equal_the_contracts_totals_view():
    data = json.loads((WEB / "receipts.json").read_text(encoding="utf-8"))
    want = {t: {k: int(v[k]) for k in ("locked", "paid", "refunded", "open")} for t, v in data["totals"].items() if int(v["locked"])}
    assert data["counted_since"], "no cut in time makes the jobs add up to the contract's get_totals"
    assert receipts.sums(data["jobs"], data["counted_since"]) == want


def test_page_reads_the_record_and_offers_the_csv():
    page = (WEB / "receipts.html").read_text(encoding="utf-8")
    assert 'href="receipts.csv"' in page and "download" in page
    assert "receipts.json" in page and "paused" in page and "hold_over" in page
    for word in ("escrow", "marketplace", "pay on proof", "\u2014"):
        assert word not in page.lower()


def test_gas_is_read_from_the_release_receipt():
    sys.path.insert(0, str(ROOT / "near" / "scripts"))
    import near_gas
    t = tx("P1", 1_794_700_060, "live.testnet", [(J, "live.testnet", "release_job", {"id": "job-1"}),
                                                ("knos-usdc-1102.testnet", J, "ft_transfer", {"amount": "900"})])
    t["execution_outcome"]["outcome"] = {"gas_burnt": 2}
    t["receipts"][0]["execution_outcome"]["outcome"]["gas_burnt"] = 8_000_000_000_000
    assert near_gas.release_gas(t) == (8_000_000_000_000, 8_000_000_000_003)
    t["receipts"][1]["execution_outcome"]["outcome"]["status"] = {"Failure": {}}
    assert near_gas.release_gas(t) is None                       # a failed release is not a measure
    s = near_gas.summary([{"receipt_gas": 8e12, "tx_gas": 12e12}, {"receipt_gas": 6e12, "tx_gas": 10e12}])
    assert s["release_receipt_tgas"] == {"max": 8.0, "median": 7.0} and s["limit_tgas"] == 300
