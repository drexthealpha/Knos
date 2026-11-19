"""Locked test for the limit-check claim (G3): solution.py defines check(table, column, rule, limit) and returns
{"result", "first_failing_row", "passed", "unchecked", "values"}. Each case's data file is pinned by sha256."""
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PINS = {
    "data/limit3/example.csv": "0b6c873f26fb7c8bae9cf641888e6487b6668ed09e2219e3f01f33cfd51e0ad7",
    "data/limit3/clean.csv": "c7ecf9d27fdd10f97144014837d05bf54c222f2d6df19648e36315f3a29da586",
    "data/limit3/gaps.csv": "823a9def69b80b5d8b6baf14105bb1c62d88a259ebd33b1e11edd564c258df0a",
    "data/limit3/many.csv": "15cd743bf083776bcfdf1cfff699928534f57e6d9bc453cf95f8a8fcd21e4863",
    "data/limit3/nan.csv": "c92bddbc300ea57c16a5802e8b33f772f1d24216b2d7a868ae6bfcc10469ab7e",
    "data/limit3/header.csv": "580ef7e49440527793e2423a8dc9f8e5c64ac63028b9127686e22a56a3c978de",
    "data/limit3/nohead.csv": "c6c01fac6d87670a60a06ab764403cb375e12485ed66d2b3fc8a8b65f0810164",
    "data/limit3/below.csv": "02405b6a63498431c6521fe3d1d8c4f2f6f57ca79295f905f8b39c64f36cd175",
    "data/limit3/equal.csv": "bf3084d601a6fb39b87aa40bc687e8b108687af2d9dec81df52eadc26deba973",
    "data/limit3/one.csv": "9a6f8b8cbfe81ba894185833b9aec735ff5ff06e775043036eaba0547a63fa42",
    "data/limit3/zero.csv": "326605044940af9523f4a4fa71879730f23555dba71206b48d36e9ca31976433",
    "data/limit/sample.csv": "9b0da3739c21cc9404faa4ed88cd950832f4261ce0298c4935bea9d830659482",
}


def fail(why):
    print(f"Failed: {why}")
    sys.exit(1)


for rel, want in PINS.items():
    p = HERE / rel
    if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != want:
        fail(f"the data file {rel} is missing or not the locked one")

# the NASA sample's capacities, read straight from the file
_lines = (HERE / "data/limit/sample.csv").read_text(encoding="ascii").splitlines()
SAMPLE_VALUES = [float(x.split(",")[1]) for x in _lines[1:]]

# (name, file, column, rule, limit, result, first_failing_row, passed, unchecked, values)
CASES = [
    ("the brief's example", "example.csv", "reading", "above", 1.4,
     "Failed at row 4: 1.3 is not above 1.4. 2 rows passed. Row 2 has no number, so I did not check it.",
     4, 2, [2], [1.8, 1.6, 1.3]),
    ("a pass with no unchecked rows", "clean.csv", "reading", "above", 1.4,
     "Passed: all 3 rows stay above 1.4.", None, 3, [], [1.9, 1.8, 1.7]),
    ("a pass with unchecked rows (empty, text, missing cell)", "gaps.csv", "reading", "above", 1.4,
     "Passed: all 2 rows stay above 1.4. Rows 2, 3 and 5 have no number, so I did not check them.",
     None, 2, [2, 3, 5], [1.9, 1.7]),
    ("more than 5 unchecked rows", "many.csv", "reading", "above", 1.4,
     "Failed at row 10: 1.2 is not above 1.4. 1 row passed. "
     "Rows 2, 3, 4, 5, 6 and 3 more have no number, so I did not check them.",
     10, 1, [2, 3, 4, 5, 6, 7, 8, 9], [2.0, 1.2]),
    ("a column of only NaN, inf and -inf", "nan.csv", "reading", "above", 1.4,
     "I cannot check: no row has a number.", None, 0, [1, 2, 3, 4, 5], []),
    ("a header-only file", "header.csv", "reading", "above", 1.4,
     "I cannot check: no row has a number.", None, 0, [], []),
    ("a headerless file whose first row holds NaN", "nohead.csv", "column 2", "below", 2.0,
     "Passed: all 2 rows stay below 2.0. Row 1 has no number, so I did not check it.",
     None, 2, [1], [1.6, 1.7]),
    ("the rule below, a value equal to the limit, the cell as written", "below.csv", "temp_c", "below", 45.25,
     "Failed at row 3: 45.250 is not below 45.25. 2 rows passed.", 3, 2, [], [20.5, 30.0, 45.25, 60.0]),
    ("a value equal to the limit with above", "equal.csv", "reading", "above", 1.4,
     "Failed at row 2: 1.4 is not above 1.4. 1 row passed.", 2, 1, [], [1.5, 1.4]),
    ("one row passing", "one.csv", "reading", "above", 1.4,
     "Passed: all 1 row stays above 1.4.", None, 1, [], [1.9]),
    ("no row passing", "zero.csv", "reading", "above", 1.4,
     "Failed at row 1: 1.0 is not above 1.4. 0 rows passed.", 1, 0, [], [1.0]),
    ("an unknown column", "example.csv", "voltage", "above", 1.4,
     "I cannot find a column named voltage. Columns: cycle, reading.", None, 0, [], []),
    ("an unknown column in a headerless file", "nohead.csv", "reading", "above", 1.4,
     "I cannot find a column named reading. Columns: column 1, column 2.", None, 0, [], []),
    ("the NASA sample", "../limit/sample.csv", "capacity_ah", "above", 1.4,
     "Failed at row 136: 1.399 is not above 1.4. 135 rows passed.", 136, 135, [], SAMPLE_VALUES),
]

try:
    sys.path.insert(0, str(HERE))
    from solution import check
except Exception as e:  # noqa: BLE001
    fail(f"solution.py has no usable check(): {type(e).__name__}: {e}")

if not callable(check):
    fail("solution.py's check is not a function")

KEYS = {"result", "first_failing_row", "passed", "unchecked", "values"}

for name, f, column, rule, limit, result, first, passed, unchecked, values in CASES:
    table = (HERE / "data/limit3" / f).resolve().read_text(encoding="ascii")
    try:
        got = check(table, column, rule, limit)
    except Exception as e:  # noqa: BLE001
        fail(f"{name}: check() raised {type(e).__name__}: {e}")
    if not isinstance(got, dict) or set(got) != KEYS:
        fail(f"{name}: check() must return a dict with exactly the keys {sorted(KEYS)}, got {got!r:.200}")
    if got["result"] != result:
        fail(f"{name}: result {got['result']!r}, expected {result!r}")
    ff = got["first_failing_row"]
    if (first is None and ff is not None) or (first is not None and (type(ff) is not int or ff != first)):
        fail(f"{name}: first_failing_row {ff!r}, expected {first!r}")
    if type(got["passed"]) is not int or got["passed"] != passed:
        fail(f"{name}: passed {got['passed']!r}, expected {passed}")
    u = got["unchecked"]
    if not isinstance(u, list) or any(type(x) is not int for x in u) or u != unchecked:
        fail(f"{name}: unchecked {u!r:.200}, expected {unchecked!r}")
    v = got["values"]
    if not isinstance(v, list) or any(type(x) is not float for x in v) or v != values:
        fail(f"{name}: values {v!r:.200}, expected {values!r:.200}")

print(f"Passed: all {len(CASES)} cases match, the NASA sample failing first at row 136.")
