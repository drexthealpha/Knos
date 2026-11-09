"""The plain contract of the Knos task (drexthealpha/knos-e2e#285): ADAPTERS, example specs, dict quotes, no order
without vault, settle(), public_view() and leitner.step()."""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

import pytest

from knos import labs, leitner
from knos.labs import base

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    for k in ("ADAPTYV_API_KEY", "MP_API_KEY", "B12_API_KEY", "PCBWAY_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_adapters_cover_every_field_with_one_interface():
    A = labs.ADAPTERS
    assert "adaptyv" in A and A["adaptyv"].field == "proteins"
    assert {a.field for a in A.values()} >= {"proteins", "chemistry", "materials", "electronics", "mechanical", "robotics"}
    for a in A.values():
        assert all(callable(getattr(a, m)) for m in ("quote", "order", "status", "results"))
        assert a() is a


def test_every_example_is_quoted_from_fixtures_with_a_positive_price():
    for name, a in labs.ADAPTERS.items():
        q = a.quote(a.example)
        assert isinstance(q, dict) and q["price"] > 0 and isinstance(q["turnaround_days"], int) and q["mode"] == "fixture", (name, q)
    assert labs.ADAPTERS["adaptyv"].quote(labs.ADAPTERS["adaptyv"].example)["price"] == 1060.0
    assert "x402_check" in labs.ADAPTERS["materials_project"].quote(None)["price_basis"]


@pytest.mark.parametrize("ref", [None, ""])
def test_no_order_without_money_in_escrow(ref):
    for a in labs.ADAPTERS.values():
        with pytest.raises(ValueError, match="no order without held money"):
            a.order(a.example, ref)


def test_order_status_results_carry_the_two_verdicts():
    a = labs.ADAPTERS["adaptyv"]
    o = a.order(a.example, "EscrowRef")
    assert o["escrow_ref"] == "EscrowRef" and a.status(o)["state"] == base.COMPLETED
    r = a.results(o)
    assert (r["lab_verdict"], r["outcome_verdict"]) == ("PASS", "FAIL")
    assert r["settle"] == {"lab_paid": True, "researcher_paid": False, "lab_verdict": "PASS", "outcome_verdict": "FAIL"}
    e = labs.ADAPTERS["pcbway"]
    assert e.results(e.order(e.example, "E"))["settle"]["lab_paid"] is True


@pytest.mark.parametrize("protocol_ok, qc_ok, outcome_ok, lab, researcher", [
    (True, True, False, True, False),     # the science failed: the lab is still paid
    (True, True, True, True, True),
    (True, False, True, False, False),    # QC failed: nobody is paid, the outcome is void
    (False, True, True, False, False),
])
def test_settle(protocol_ok, qc_ok, outcome_ok, lab, researcher):
    got = labs.settle(protocol_ok, qc_ok, outcome_ok)
    assert (got["lab_paid"], got["researcher_paid"]) == (lab, researcher)


def test_public_view_shows_only_hashes_timing_and_verdicts():
    a = labs.ADAPTERS["adaptyv"]
    r = a.results(a.order(a.example, "EscrowRef"))
    r.update({"buyer": "Example Pharma Ltd", "ordered_at": "2026-10-14T20:00:00Z", "results_at": "2026-10-14T21:00:00Z", "turnaround_s": 3600})
    v = labs.public_view(r)
    text = json.dumps(v)
    for private in ("Example Pharma", "knos_design_1", "pos_ctrl", ".zip", "2.1", "EscrowRef", "EVQLVESGGGLVQPGGSLRLSCAASGFTFS"):
        assert private not in text, private
    assert v["lab_verdict"] == "PASS" and v["outcome_verdict"] == "FAIL" and v["publish"] is False
    assert v["timing"] == {"ordered_at": "2026-10-14T20:00:00Z", "results_at": "2026-10-14T21:00:00Z", "turnaround_s": 3600}
    assert v["hashes"] and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in v["hashes"] + [v["result_sha256"]])
    assert "published" in labs.public_view({**r, "publish": True})


@pytest.mark.parametrize("days, passed, want", [(1, True, (3, False)), (3, True, (7, False)), (7, True, (30, False)),
                                                (30, True, (30, False)), (30, False, (1, True)), (3, False, (1, True))])
def test_leitner_step(days, passed, want):
    assert leitner.step(days, passed) == want


def test_the_robotics_example_runs_its_sealed_test_on_the_recorded_runs():
    a = labs.ADAPTERS["pylabrobot"]
    assert a.quote(a.example)["mode"] == "fixture"
    r = a.results(a.order(a.example, "E"))
    assert r["lab_verdict"] == "PASS" and r["outcome_verdict"] == "PASS"
