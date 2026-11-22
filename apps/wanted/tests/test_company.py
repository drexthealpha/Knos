"""Every demand report and pre-order goes into the Knos Record (Sibyl WARM claim + COLD events), anchors on devnet
(here a fake send), and every fee comes from config/fees.yaml. Needs knos + Sibyl (skipped without them)."""
import pytest
from test_check import use_signals

from knos_wanted import check, company

record = pytest.importorskip("knos.record")
pytest.importorskip("sibyl_memory_client")
fees_config = pytest.importorskip("knos.money.fees_config")
from knos.settle.v2 import pay  # noqa: E402


@pytest.fixture
def report(monkeypatch):
    use_signals(monkeypatch)
    return check.demand_check("A late-night oat-milk coffee bar for students in London", "London")


def test_report_is_warm_claim_and_cold_event(report, tmp_path):
    rep = report
    got = company.record_check(rep)
    assert got["recorded"] is True and got["claim"] == "demand:" + rep["hash"][:40]
    lines = record.entries(tmp_path / "record")
    assert [(e["kind"], e["tier"]) for e in lines] == [("claim", "WARM"), ("experiment", "COLD")]
    warm = lines[0]["payload"]
    assert warm["report_hash"] == rep["hash"] and warm["verdict"] == "OPEN" and warm["live"] is True
    assert rep["idea"] not in str(lines)                         # only the idea's sha256 is public
    assert lines[1]["payload"]["endpoints"] == ["Hacker News", "Research papers", "Wikipedia"]   # the sources, never their answers
    assert "296" not in str(lines)
    st = record.sibyl(tmp_path / "record")
    assert record.claim_state(got["claim"], store=st)["report_hash"] == rep["hash"]
    v = record.verify(tmp_path / "record", offline=True)
    assert v["ok"] is True and v["lines"] == 2, v["problems"]


def test_preorder_is_cold_funding_and_updates_the_claim_then_anchors(report, tmp_path):
    rep = report
    company.record_check(rep)
    res = {"order": "Ord3r1111111111111111111111111111111111111", "signature": "5" * 88, "buyer": "Buy3r111111111111111111111111111111111111",
           "buyer_kind": "demo buyer", "amount_units": 5, "mint": "M1nt1111111111111111111111111111111111111"}
    got = company.record_preorder(rep["hash"], res, company.quote(5), synthetic_report=True)
    assert got["recorded"] is True
    lines = record.entries(tmp_path / "record")
    assert [e["kind"] for e in lines] == ["claim", "experiment", "funding", "claim"]
    assert lines[-1]["payload"]["preorders"] == {"orders": 1, "units": 5}
    sent = []
    a = company.anchor(send=lambda memo: (sent.append(memo), {"tx": "4" * 88, "signer": "S1gner11111111111111111111111111111111111", "slot": 1})[1])
    assert a["anchored"] is True and a["first"] == 0 and a["last"] == 3 and sent
    assert record.entries(tmp_path / "record")[-1]["kind"] == "anchor"
    assert company.anchor(send=lambda memo: {"tx": "x"})["anchored"] is False      # nothing pending


def test_fees_come_from_config():
    cfg = fees_config.load()
    qd = company.quote(5)
    assert qd["source"] == "config/fees.yaml"
    assert qd["at_lock"]["units"] == 0 and qd["at_lock"]["line"] == "funding"
    assert qd["at_release"]["units"] * 1e6 == cfg.fee("payout", 5_000_000) == pay.order_fee(5_000_000)
    assert qd["on_graduation"]["units"] * 1e6 == cfg.fee("graduation", 5_000_000)
    assert qd["at_release"]["status"] == "live" and qd["on_graduation"]["status"] == "decided"
    assert qd["demand_report"]["line"] == "demand_check" and qd["demand_report"]["units"] == 0
    assert qd["demand_report"]["free_a_month"] == 10 and qd["demand_report"]["status"] == "decided"


def test_record_never_hides_the_report(report, monkeypatch):
    rep = report
    monkeypatch.setattr(company, "_record", lambda: None)
    assert company.record_check(rep) == {"recorded": False, "why": "the knos package is not installed"}
