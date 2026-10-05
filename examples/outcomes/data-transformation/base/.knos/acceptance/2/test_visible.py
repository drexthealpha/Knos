"""The naive check, kept beside the real one to show what it lets through: it runs inside the pull request's tree
(in-process) and compares transform.sql's output with the one worked example. A transform.sql that writes the example's
answer down passes it. Nobody should fund on this bundle; bundle 1 is the one that is paid."""
import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def rows(name: str) -> list[list[str]]:
    with open(ROOT / "examples" / name, encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))[1:]


def test_the_worked_example_comes_out_as_expected():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE charges (charge_id TEXT, customer_id TEXT, amount TEXT)")
    db.execute("CREATE TABLE refunds (refund_id TEXT, charge_id TEXT, amount TEXT)")
    db.executemany("INSERT INTO charges VALUES (?, ?, ?)", rows("charges.csv"))
    db.executemany("INSERT INTO refunds VALUES (?, ?, ?)", rows("refunds.csv"))
    db.executescript((ROOT / "transform.sql").read_text(encoding="utf-8"))
    got = db.execute("SELECT customer_id, charges, gross_cents, refund_cents, net_cents FROM ledger ORDER BY customer_id").fetchall()
    assert [[str(v) for v in r] for r in got] == rows("expected_ledger.csv")
