"""A transformation, judged black-box on inputs nobody outside this file has seen. The deliverable is transform.sql
(SQLite). The judge never runs it in its own process: "$KNOS_RUN python3 -c <driver>" loads one case's tables into an
in-memory database inside the sandbox, runs transform.sql there and prints the `ledger` table it leaves.

CASES inputs, each from a fixed seed (gen.py), so the verdict is the same on every run and on a rerun. On each one:
  schema            ledger has customer_id (text) and charges, gross_cents, refund_cents, net_cents (whole numbers)
  key uniqueness    one row per customer_id
  row conservation  every customer of the input is in the ledger and no other; the charges counted add up to the
                    distinct charges of the input (none lost, none counted twice)
  reconciliation    gross, refunds and net add up to the input's totals to the cent, net = gross - refunds on every
                    row, and each customer's row equals the reference's
The first case that fails is named with its seed, so the supplier can make the same tables and look."""
import json
import os
import subprocess
import sys

import gen

SEED, CASES, SECONDS = 20261005, 40, 20
COLUMNS = ("customer_id", "charges", "gross_cents", "refund_cents", "net_cents")
DRIVER = """
import json, sqlite3, sys
t = json.load(sys.stdin)
db = sqlite3.connect(":memory:")
db.execute("CREATE TABLE charges (charge_id TEXT, customer_id TEXT, amount TEXT)")
db.execute("CREATE TABLE refunds (refund_id TEXT, charge_id TEXT, amount TEXT)")
db.executemany("INSERT INTO charges VALUES (?, ?, ?)", t["charges"])
db.executemany("INSERT INTO refunds VALUES (?, ?, ?)", t["refunds"])
db.executescript(open("transform.sql", encoding="utf-8").read())
print(json.dumps(db.execute("SELECT customer_id, charges, gross_cents, refund_cents, net_cents FROM ledger").fetchall()))
"""


def transform(t: dict) -> list:
    """The rows of `ledger` after transform.sql ran on these tables, or a sentence (str) saying why there are none."""
    try:
        got = subprocess.run([os.environ["KNOS_RUN"], "python3", "-c", DRIVER], input=json.dumps(t).encode(),
                             capture_output=True, timeout=SECONDS)
    except subprocess.TimeoutExpired:
        return f"transform.sql took more than {SECONDS} seconds"
    if got.returncode:
        return "transform.sql did not run, or left no ledger table with the five columns: " + \
            (got.stderr.decode("utf-8", "replace").strip().splitlines() or ["no message"])[-1][:200]
    try:
        return json.loads(got.stdout.decode("utf-8"))
    except ValueError:
        return "the ledger could not be read back"


def whole(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def wrong(t: dict, rows) -> str:
    """Why these ledger rows are not the transformation of these tables; "" when they are."""
    if isinstance(rows, str):
        return rows
    if any(not isinstance(r[0], str) or not all(whole(v) for v in r[1:]) for r in rows):
        return "schema: customer_id must be text and the four other columns whole numbers (cents are integers, not 19.99 or 1999.0)"
    keys = [r[0] for r in rows]
    if len(set(keys)) != len(keys):
        return "key uniqueness: a customer_id has more than one row"
    want = gen.ledger(t)
    if set(keys) != set(want):
        return f"row conservation: {len(set(want) - set(keys))} customers of the input are missing and {len(set(keys) - set(want))} rows are for nobody"
    if sum(r[1] for r in rows) != len({c[0] for c in t["charges"]}):
        return (f"row conservation: the ledger counts {sum(r[1] for r in rows)} charges and the input holds "
                f"{len({c[0] for c in t['charges']})} distinct ones (a charge delivered twice is one charge)")
    for name, at in (("gross", 2), ("refund", 3), ("net", 4)):
        have, need = sum(r[at] for r in rows), sum(v[at - 1] for v in want.values())
        if have != need:
            return f"reconciliation: {name} adds up to {have} cents and the input to {need} cents, {abs(have - need)} apart"
    if any(r[4] != r[2] - r[3] for r in rows):
        return "reconciliation: a row's net_cents is not its gross_cents minus its refund_cents"
    if any(tuple(r[1:]) != want[r[0]] for r in rows):
        return "reconciliation: the totals add up, and a customer's row is not that customer's own charges and refunds"
    return ""


if __name__ == "__main__":
    for n in range(CASES):
        tables = gen.tables(SEED + n)
        why = wrong(tables, transform(tables))
        if why:
            sys.exit(f"case {n + 1} of {CASES} (seed {SEED + n}, {len(tables['charges'])} charge rows): {why}")
    print(f"all {CASES} cases hold: schema, key uniqueness, row conservation, reconciliation to the cent")
