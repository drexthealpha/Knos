"""The job's locked check, second release: check a test file against a limit, never passing a column with no numbers.

NASA's page for its "Li-ion Battery Aging Datasets" (https://data.nasa.gov/dataset/li-ion-battery-aging-datasets) says,
word for word: "The experiments were stopped when the batteries reached the end-of-life (EOL) criteria of 30% fade in
rated capacity (from 2 Ah to 1.4 Ah)."

solution.py defines check(table, column, rule, limit) -> dict.
- table: the file as text, comma separated. If the first row has any cell that float() cannot read, it is the header;
  otherwise there is no header and the columns are named "column 1", "column 2" and so on.
- column: a column name as above. rule: "above" or "below". limit: a float.
- Rows are numbered from 1 over the data rows (the header is not a row).
- A row is unmeasurable when its cell is missing, cannot be read by float(), or reads as NaN, inf or -inf (any case).
  Every other row is measurable. A measurable value equal to the limit fails: with "above" a value fails when
  value <= limit, with "below" when value >= limit.
- passed, failed and unmeasurable count the rows of each kind over the whole file; each row is in exactly one.
- It returns {"result": sentence, "first_failing_row": int or None, "passed": int, "failed": int,
  "unmeasurable": int, "values": [float]}: values is every measurable value of the column, in file order.
- The sentences, exactly (the value as written in the file, the limit as given, 1.4 not 1.40), each ending with the
  counts " Rows: <p> passed, <f> failed, <u> unmeasurable.":
  Fail (any measurable row fails; r is the first): "Failed at row <r>: <value> is not above <limit>."
  Pass (measurable rows, none fails): "Passed: all <p> rows stay above <limit>."
  No measurable row at all: "Cannot check: no measurable rows." (never a pass)
  With "below", the same with "below".

Ten cases: generated files with known answers, and the sample, whose first failing row is worked out by a separate
script of a few lines (limit_check10.py), not by this test. The last line printed is the reason, in plain words.
"""
import csv
import hashlib
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SHA256 = {
    "data/limit/case1.csv": "04822649c0db2bff469c0b30909b766f33be443c72c83d23d674df2132c9fbf7",
    "data/limit/case2.csv": "eb7eec8ed1e32cd1a5d20b30fd287e6c4e54c10b2c9d529b25c0b6d5d861c45b",
    "data/limit/case3.csv": "7b7770437ddc095c6bd484ddbbc284299cfa665363c9de6acaa596ecff51a1da",
    "data/limit/case4.csv": "06feb2faa4f688a96da83bbb82e027ea2b1c61ccf968325b071b6f9c90a88519",
    "data/limit/case5.csv": "04822649c0db2bff469c0b30909b766f33be443c72c83d23d674df2132c9fbf7",
    "data/limit/case6.csv": "a770855199b0a4e55b1e4f03220ac6347899624d1476878f6995f68908a49a0f",
    "data/limit/case7.csv": "74fdac02e71292e3d3c47e1e680c00547d6351a4f55a6eabe73fbd18c092b37d",
    "data/limit/case8.csv": "dab0a43058ed3df7b09a3ceb34b8234047d368829b3cdb84fa0f450f14c05728",
    "data/limit/case9.csv": "18ac445179d7ec09039e9b57c87a77d350121a09796225ca6c7d21fa59ac1673",
    "data/limit/sample.csv": "9b0da3739c21cc9404faa4ed88cd950832f4261ce0298c4935bea9d830659482",
    "limit_check10.py": "97d194cf73445f8337fe620762f7b5e6770cd4c922506bd7b8645d1d1a328ba9",
}


def read(name):
    with open(os.path.join(HERE, name), "rb") as f:
        return f.read()


for name, want in SHA256.items():
    if hashlib.sha256(read(name)).hexdigest() != want:
        print(f"Failed: the test file {name} is not the one this test was locked with.")
        sys.exit(1)

said = subprocess.run([sys.executable, "-E", "-s", "-B", os.path.join(HERE, "limit_check10.py")],
                      capture_output=True, text=True, timeout=10, cwd=HERE).stdout.split()
r7 = int(said[-1])
v7 = list(csv.reader(io.StringIO(read("data/limit/sample.csv").decode())))[r7][1]


def n(p, f, u):
    return f" Rows: {p} passed, {f} failed, {u} unmeasurable."


# file, column, rule, limit, sentence, first failing row, passed, failed, unmeasurable, values
CASES = [
    ("case1.csv", "reading_v", "above", 2.5, "Passed: all 100 rows stay above 2.5." + n(100, 0, 0), None, 100, 0, 0, 1),
    ("case2.csv", "reading_v", "above", 2.5, "Failed at row 37: 2.41 is not above 2.5." + n(98, 2, 0), 37, 98, 2, 0, 1),
    ("case3.csv", "column 2", "above", 2.5, "Failed at row 1: 1.98 is not above 2.5." + n(99, 1, 0), 1, 99, 1, 0, 1),
    ("case4.csv", "reading_v", "above", 2.5, "Failed at row 50: 2.5 is not above 2.5." + n(99, 1, 0), 50, 99, 1, 0, 1),
    ("case5.csv", "reading_v", "below", 3.9, "Passed: all 100 rows stay below 3.9." + n(100, 0, 0), None, 100, 0, 0, 1),
    ("case6.csv", "reading_v", "above", 2.5, "Passed: all 97 rows stay above 2.5." + n(97, 0, 3), None, 97, 0, 3, 1),
    ("case7.csv", "capacity_ah", "above", 1.4, "Cannot check: no measurable rows." + n(0, 0, 3), None, 0, 0, 3, []),
    ("case8.csv", "capacity_ah", "above", 1.4, "Failed at row 6: 1.3 is not above 1.4." + n(2, 1, 3), 6, 2, 1, 3,
     [1.8, 1.6, 1.3]),
    ("case9.csv", "capacity_ah", "below", 3.9, "Cannot check: no measurable rows." + n(0, 0, 0), None, 0, 0, 0, []),
    ("sample.csv", "capacity_ah", "above", 1.4, f"Failed at row {r7}: {v7} is not above 1.4." + n(135, 33, 0),
     r7, 135, 33, 0, 1),
]

from solution import check  # noqa: E402

for k, (name, column, rule, limit, sentence, first, p, f, u, want_values) in enumerate(CASES, 1):
    text = read("data/limit/" + name).decode()
    if want_values == 1:          # every number in the column's second field, in file order (these files hold no NaN)
        want_values = []
        for row in csv.reader(io.StringIO(text)):
            try:
                want_values.append(float(row[1]))
            except (ValueError, IndexError):
                pass
    try:
        got = check(text, column, rule, limit)
    except Exception as e:  # noqa: BLE001 - any error is a fail, said plainly
        print(f"Failed: case {k} ({name}) stopped with an error: {type(e).__name__}: {e}")
        sys.exit(1)
    if not isinstance(got, dict) or got.get("result") != sentence:
        print(f"Failed: case {k} ({name}) said {(got or {}).get('result') if isinstance(got, dict) else got!r}, not {sentence!r}")
        sys.exit(1)
    for key, want in (("first_failing_row", first), ("passed", p), ("failed", f), ("unmeasurable", u)):
        if got.get(key) != want:
            print(f"Failed: case {k} ({name}) gave {key} {got.get(key)!r}, not {want!r}.")
            sys.exit(1)
    try:
        values = [float(v) for v in got.get("values")]
    except (TypeError, ValueError):
        values = None
    if values != want_values:
        print(f"Failed: case {k} ({name}) did not give every measurable number of the column {column!r}, in file order.")
        sys.exit(1)

print(f"Passed: all 10 cases, the sample failing at row {r7} as the separate script found, no column without numbers passing.")
