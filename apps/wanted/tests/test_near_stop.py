"""L13: Stop on a job calls the jobs contract's own refund_job (no contract change), against a stubbed NEAR client: an
open job past its deadline is refunded with the transaction's link; before the deadline, or once the job is no longer
open, nothing is sent and the answer says why."""
import sys
import time
import types

import pytest

from knos_wanted import near_live


@pytest.fixture
def chain(monkeypatch):
    sent, jobs = [], {}
    common = types.SimpleNamespace(EXPLORER="https://testnet.nearblocks.io/txns/",
                                   view=lambda contract, method, args: jobs.get(args["id"]),
                                   call=lambda who, contract, method, args, deposit="0 NEAR", gas="", wait="FINAL": (
                                       sent.append((who, contract, method, args)) or {"ok": True, "tx": "TX1", "url": "https://testnet.nearblocks.io/txns/TX1", "said": "ok"}))
    monkeypatch.setitem(sys.modules, "common", common)
    monkeypatch.setattr(near_live, "_jobs", lambda: None)
    monkeypatch.setenv("KNOS_NEAR_LIVE", "on")
    monkeypatch.setenv("KNOS_NEAR_KEYS_FILE", "not-read-in-tests")
    return sent, jobs


def test_an_open_job_past_its_deadline_is_refunded_by_refund_job(chain):
    sent, jobs = chain
    jobs["job-1"] = {"state": "Open", "deadline_ns": str(int((time.time() - 60) * 1e9))}
    got = near_live.stop_job("job-1")
    assert got["ok"] is True and got["state"] == "Refunded" and got["url"].endswith("TX1")
    assert sent == [(near_live.LIVE, near_live.JOBS, "refund_job", {"id": "job-1"})]


def test_before_the_deadline_or_when_not_open_nothing_is_sent(chain):
    sent, jobs = chain
    jobs["job-2"] = {"state": "Open", "deadline_ns": str(int((time.time() + 3600) * 1e9))}
    jobs["job-3"] = {"state": "Paid", "deadline_ns": "0"}
    early, paid, none = near_live.stop_job("job-2"), near_live.stop_job("job-3"), near_live.stop_job("job-9")
    assert not early["ok"] and early["deadline"] and "after its deadline" in early["why"]
    assert not paid["ok"] and paid["state"] == "Paid" and not none["ok"] and none["state"] == "none"
    assert sent == []
    with pytest.raises(ValueError):
        near_live.stop_job("bad id; drop")
