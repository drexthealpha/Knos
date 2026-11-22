"""A paper crossed on this server lately is answered from that crossing at once, said so in its steps; one whose report
is gone, or one too old, is crossed again. SYNTHETIC jobs only."""
import time

from knos_wanted import agent


class State:
    def __init__(self, reports):
        self.reports = reports

    def report(self, h):
        return self.reports.get(h)


def _job(i, report, started):
    return {"id": f"j{i}", "ref": "10.1038/x", "idea": None, "place": None, "product": None, "leader": None,
            "status": "done", "steps": [{"title": "read the paper"}], "started": started, "report": report, "card": None}


def test_a_paper_crossed_lately_is_answered_from_that_crossing(monkeypatch):
    monkeypatch.setattr(agent, "JOBS", {"j1": _job(1, "r1", time.time() - 60)})
    job = agent.start(State({"r1": {"hash": "r1"}}), ref="10.1038/x")
    assert job["status"] == "done" and job["report"] == "r1" and job["kept_from"] == "j1" and job["steps"][-1]["title"].startswith("kept from")


def test_a_crossing_whose_report_is_gone_is_crossed_again(monkeypatch):
    started = []
    monkeypatch.setattr(agent, "run", lambda job, state: started.append(job["id"]))
    monkeypatch.setattr(agent, "JOBS", {"j1": _job(1, "r1", time.time() - 60)})
    got = agent.start(State({}), ref="10.1038/x", wait=False)
    assert got["status"] == "running" and "kept_from" not in got


def test_an_old_crossing_is_not_kept(monkeypatch):
    monkeypatch.setattr(agent, "run", lambda job, state: None)
    monkeypatch.setattr(agent, "JOBS", {"j1": _job(1, "r1", time.time() - agent.KEEP_CROSSING_S - 1)})
    assert "kept_from" not in agent.start(State({"r1": {"hash": "r1"}}), ref="10.1038/x")
