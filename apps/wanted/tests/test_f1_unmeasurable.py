"""G1 (every limit-check result names its unchecked rows and has at most two counts): the released program, run through
the server's real run path (POST /api/run, and the connector's run), says "I cannot check" for a column with no number,
names the one row it did not check, names the first five of seven and then "and 2 more", still fails the sample at row
136, and a program file that is not byte for byte the one released.json records is refused (F1e).

These tests run near/agents/job/data/limit/released_solution.py as released (no stand-in): on the release for
test_limit2.py (counts "Rows: ... unmeasurable.") the first four fail, and they pass once the program released for
test_limit3.py is in place."""
import json
import shutil
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from knos_wanted import server, tool_run, usage

MISMATCH = "This tool's program does not match its release."


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(usage, "chain_count", lambda url=None: (_ for _ in ()).throw(OSError("no network in tests")))
    monkeypatch.setattr(tool_run, "_mem", {})
    state = server.State()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def call(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "X-Knos-Test": "1"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def run(base, table, column, browser, rule="above", limit=1.4):
    return call(base, "/api/run", {"id": "limit-check", "table": table, "column": column, "rule": rule, "limit": limit,
                                   "browser": browser, "test": True})


def mcp_run(base, args):
    st, r = call(base, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "run", "arguments": args}})
    assert st == 200, r
    return r["result"]


def test_a_column_of_only_nan_cannot_be_checked(app):
    st, r = run(app, "cycle,reading\n1,NaN\n2,nan\n3,NAN", "reading", "b-g1-nan-0001")
    assert st == 200, r
    assert r["result"] == "I cannot check: no row has a number."
    assert r["verdict"] == "unknown" and r["first_failing_row"] is None and r["passed"] == 0 and r["unchecked"] == [1, 2, 3], r


def test_three_numbers_and_one_nan_name_the_row_not_checked(app):
    table = "cycle,reading\n1,1.8\n2,NaN\n3,1.6\n4,1.3"
    want = "Failed at row 4: 1.3 is not above 1.4. 2 rows passed. Row 2 has no number, so I did not check it."
    st, r = run(app, table, "reading", "b-g1-one-0001")
    assert st == 200 and r["result"] == want, r
    assert (r["verdict"], r["first_failing_row"], r["passed"], r["unchecked"]) == ("fail", 4, 2, [2]), r
    got = mcp_run(app, {"id": "limit-check", "table": table, "column": "reading", "rule": "above", "limit": 1.4})
    assert not got.get("isError") and got["structuredContent"]["result"] == want, got
    assert got["structuredContent"]["unchecked"] == [2] and got["structuredContent"]["passed"] == 2


def test_seven_unchecked_rows_name_five_then_and_2_more(app):
    table = "cycle,reading\n1,1.9\n2,NaN\n3,x\n4,\n5,inf\n6,-inf\n7,nan\n8,n/a\n9,1.8"
    st, r = run(app, table, "reading", "b-g1-many-001")
    assert st == 200, r
    assert r["result"] == "Passed: all 2 rows stay above 1.4. Rows 2, 3, 4, 5, 6 and 2 more have no number, so I did not check them."
    assert (r["verdict"], r["first_failing_row"], r["passed"], r["unchecked"]) == ("pass", None, 2, [2, 3, 4, 5, 6, 7, 8]), r


def test_the_nasa_sample_fails_at_row_136_with_two_counts_at_most(app):
    st, r = run(app, tool_run.sample(), "capacity_ah", "")
    assert st == 200 and r["mode"] == "sample", r
    assert r["result"] == "Failed at row 136: 1.399 is not above 1.4. 135 rows passed."
    assert (r["first_failing_row"], r["passed"], r["unchecked"]) == (136, 135, [])


def test_a_program_with_one_byte_changed_is_refused(app, monkeypatch, tmp_path):
    """F1e: a copy of the repository's tool files with one byte of the program changed (the real file is not touched)."""
    real = tool_run.root()
    for rel in (tool_run.CONF["program"], tool_run.CONF["released"], tool_run.CONF["sample"], "near/claims/claims.json"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(real / rel, tmp_path / rel)
    monkeypatch.setattr(tool_run, "root", lambda: tmp_path)
    assert tool_run.ready()                                   # the copy as released runs
    prog = tmp_path / tool_run.CONF["program"]
    b = bytearray(prog.read_bytes())
    b[-1] = ord(" ") if b[-1] != ord(" ") else ord("\n")
    prog.write_bytes(bytes(b))
    assert not tool_run.ready()
    st, r = run(app, "cycle,v\n1,5\n2,6", "v", "b-f1-sha-0001", limit=4)
    assert st == 503 and r == {"error": MISMATCH}, r
    st, r = run(app, tool_run.sample(), "capacity_ah", "")
    assert st == 503 and r == {"error": MISMATCH}, r
    got = mcp_run(app, {"id": "limit-check", "table": "cycle,v\n1,5\n2,6", "column": "v", "rule": "above", "limit": 4})
    assert got["isError"] is True and got["content"][0]["text"] == MISMATCH, got
