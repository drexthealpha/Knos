"""How long the event log takes: ingest, verify, and one month's statement from the index.

    python scripts/events_bench.py                    # 2,000 synthetic events: a quick look
    python scripts/events_bench.py --events 100000    # the figure docs/reference/EVENTS.md quotes

Synthetic and seeded: evaluations of 12 months and 20 suppliers, one in ten arriving a second time by another mode,
and one invoice line for every accepted deliverable. Nothing here opens the network. The times are this machine's;
the script prints them, and docs/reference/EVENTS.md says which machine wrote the ones it quotes.
"""
from __future__ import annotations

import argparse
import json
import platform
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from knos import events as E  # noqa: E402
from knos import ids  # noqa: E402


def synthetic(n: int, seed: int = 17):
    """About `n` arrivals: (evaluation [+ acceptance] [+ a repeat by batch] [+ an invoice line]) until there are n."""
    rng, made, k = random.Random(seed), 0, 0
    while made < n:
        k += 1
        month, supplier = 202601 + k % 12, str(1000 + k % 20)
        dlv = ids.deliverable(f"order-{k}", 0)
        ok = rng.random() < 0.8
        ev = E.evaluation(dlv, f"{k:040x}", "policy-1", "bench", 0, "accepted" if ok else "rejected", "record", supplier=supplier, month=month,
                          amount=2_000_000, unit="units", evidence=f"tx:{k}")
        out = [ev]
        if ok:
            out.append(E.acceptance(dlv, "record", supplier=supplier, month=month, amount=2_000_000, unit="units", evaluation=ev.id, evidence=f"tx:{k}"))
            out.append(E.invoice_line(supplier, f"INV-{month}", k, "import", deliverable=dlv, month=month, amount=2_000_000, unit="units"))
        if rng.random() < 0.1:
            out.append(E.replace(ev, source="batch", evidence=f"batch:{month}.0"))
        for e in out[:n - made]:
            made += 1
            yield e


def measure(n: int) -> dict:
    t = [time.perf_counter()]
    log = E.Log()
    report = E.ingest(log, synthetic(n))
    t.append(time.perf_counter())
    text = log.text()
    t.append(time.perf_counter())
    again, said = E.read(text)
    t.append(time.perf_counter())
    month = 202606
    st = E.statement(again, month)
    t.append(time.perf_counter())
    scanned = sum(1 for e in again.events if e.month == month)          # what a statement would cost with no index: every line, once
    t.append(time.perf_counter())
    assert not said and report.ok and scanned == len(again.by_month[month])
    return {"events": len(log.events), "counted": sum(1 for e in log.events if e.first is None), "repeats": len(report.duplicates),
            "log_bytes": len(text), "month": month, "month_events": scanned, "month_invoice_lines": len(st["invoice_lines"]),
            "seconds": {"ingest": round(t[1] - t[0], 3), "write": round(t[2] - t[1], 3), "read_and_verify": round(t[3] - t[2], 3),
                        "statement_one_month": round(t[4] - t[3], 4), "scan_all_lines_once": round(t[5] - t[4], 4)},
            "machine": f"{platform.machine()}, {platform.python_implementation()} {platform.python_version()}"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--events", type=int, default=2000, help="how many synthetic events (default 2000; 100000 is the documented run)")
    print(json.dumps(measure(ap.parse_args().events), indent=1))
