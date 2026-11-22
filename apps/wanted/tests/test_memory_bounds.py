"""What keeps the free instance (512 MB) inside its memory under load: at most CHECKS_AT_ONCE demand checks at a time, and the operator's /api/ops/memory to measure it (24 Oct 2026:
three out-of-memory kills, two in champion runs)."""
from __future__ import annotations

import threading
import time

from knos_wanted import check


def test_no_more_than_checks_at_once_run_together(monkeypatch):
    seen, lock = [], threading.Lock()

    def slow(*a, **k):
        with lock:
            seen.append(check.running[0])
        time.sleep(0.05)
        return {}

    monkeypatch.setattr(check, "_demand_check", slow)
    threads = [threading.Thread(target=check.demand_check, args=("a smart water bottle",)) for _ in range(9)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(seen) == 9 and max(seen) <= check.CHECKS_AT_ONCE and check.running[0] == 0


def test_the_memory_answer_names_what_a_load_test_reads():
    from knos_wanted import server

    class S:
        reports = {"a": 1, "b": 2}
    got = server.memory_now(S())
    assert set(got) == {"rss_mb", "peak_mb", "threads", "checks_running", "checks_at_once", "reports_in_memory", "processes", "all_processes_mb"}
    assert got["reports_in_memory"] == 2 and got["checks_at_once"] == check.CHECKS_AT_ONCE and got["threads"] >= 1
