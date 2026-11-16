"""The job's locked check: check a test file against a limit, the job hardware-testing companies charge for.

NASA's page for its "Li-ion Battery Aging Datasets" (https://data.nasa.gov/dataset/li-ion-battery-aging-datasets) says,
word for word: "The experiments were stopped when the batteries reached the end-of-life (EOL) criteria of 30% fade in
rated capacity (from 2 Ah to 1.4 Ah)."

solution.py defines check(table, column, rule, limit) -> dict.
- table: the file as text, comma separated. If the first row has any cell that is not a number, it is the header;
  otherwise there is no header and the columns are named "column 1", "column 2" and so on.
- column: a column name as above. rule: "above" or "below". limit: a float.
- Rows are numbered from 1 over the data rows (the header is not a row), skipped rows included. A row whose value in
  that column is not a number is skipped and counted.
- A value equal to the limit fails: with "above" a value fails when value <= limit, with "below" when value >= limit.
- It returns {"result": sentence, "first_failing_row": int or None, "rows": int, "skipped": int, "values": [float]}:
  rows is the number of numeric rows for a pass, r - 1 for a fail; values is every numeric value of the column, in
  file order.
- The sentences, exactly (the value as written in the file, the limit as given, 1.4 not 1.40):
  Fail: "Failed at row <r>: <value> is not above <limit>. It passed for the <r-1> rows before that."
  Pass: "Passed: all <n> rows stay above <limit>."
  With "below", the same with "below". When rows were skipped, add " <k> rows were skipped because they are not numbers."

Seven cases: six generated files with known answers, and the sample, whose first failing row is worked out by a
separate script of a few lines (limit_check10.py), not by this test. The last line printed is the reason, in plain words.
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

# case, file, column, its index in the file, rule, limit, sentence, first failing row, rows, skipped
CASES = [
    (1, "case1.csv", "reading_v", 1, "above", 2.5, "Passed: all 100 rows stay above 2.5.", None, 100, 0),
    (2, "case2.csv", "reading_v", 1, "above", 2.5,
     "Failed at row 37: 2.41 is not above 2.5. It passed for the 36 rows before that.", 37, 36, 0),
    (3, "case3.csv", "column 2", 1, "above", 2.5,
     "Failed at row 1: 1.98 is not above 2.5. It passed for the 0 rows before that.", 1, 0, 0),
    (4, "case4.csv", "reading_v", 1, "above", 2.5,
     "Failed at row 50: 2.5 is not above 2.5. It passed for the 49 rows before that.", 50, 49, 0),
    (5, "case5.csv", "reading_v", 1, "below", 3.9, "Passed: all 100 rows stay below 3.9.", None, 100, 0),
    (6, "case6.csv", "reading_v", 1, "above", 2.5,
     "Passed: all 97 rows stay above 2.5. 3 rows were skipped because they are not numbers.", None, 97, 3),
    (7, "sample.csv", "capacity_ah", 1, "above", 1.4,
     f"Failed at row {r7}: {v7} is not above 1.4. It passed for the {r7 - 1} rows before that.", r7, r7 - 1, 0),
]

from solution import check  # noqa: E402

for n, name, column, idx, rule, limit, sentence, first, rows, skipped in CASES:
    text = read("data/limit/" + name).decode()
    want_values = []
    for row in csv.reader(io.StringIO(text)):
        try:
            want_values.append(float(row[idx]))
        except ValueError:
            pass
    try:
        got = check(text, column, rule, limit)
    except Exception as e:  # noqa: BLE001 - any error is a fail, said plainly
        print(f"Failed: case {n} ({name}) stopped with an error: {type(e).__name__}: {e}")
        sys.exit(1)
    if not isinstance(got, dict) or got.get("result") != sentence:
        print(f"Failed: case {n} ({name}) said {(got or {}).get('result') if isinstance(got, dict) else got!r}, not {sentence!r}")
        sys.exit(1)
    for key, want in (("first_failing_row", first), ("rows", rows), ("skipped", skipped)):
        if got.get(key) != want:
            print(f"Failed: case {n} ({name}) gave {key} {got.get(key)!r}, not {want!r}.")
            sys.exit(1)
    try:
        values = [float(v) for v in got.get("values")]
    except (TypeError, ValueError):
        values = None
    if values != want_values:
        print(f"Failed: case {n} ({name}) did not give every number of the column {column!r}, in file order.")
        sys.exit(1)

print(f"Passed: all 7 cases, the sample failing at row {r7} as the separate script found.")
