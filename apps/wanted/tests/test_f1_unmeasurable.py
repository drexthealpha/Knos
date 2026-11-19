"""F1 (a column with no numbers passes): the released program, run through the server's real run path (POST /api/run, and
the connector's run), never passes a column with no measurable row, counts NaN, inf and -inf apart, still fails the
sample at row 136, and a program file that is not byte for byte the one released.json records is refused.

These tests run near/agents/job/data/limit/released_solution.py as released (no stand-in): on the first release
(test_limit.py's contract) the first three fail, and they pass once the program released for test_limit2.py is in place."""
import json
import shutil
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from knos_wanted import server, tool_run, usage
from knos_wanted.qloo_mcp import InProcess, Qloo

MISMATCH = "This tool's program does not match its release."


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(usage, "chain_count", lambda url=None: (_ for _ in ()).throw(OSError("no network in tests")))
    monkeypatch.setattr(tool_run, "_mem", {})
    state = server.State(Qloo(InProcess(), mode="mock", sleep=lambda s: None))
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


def test_a_nan_only_column_cannot_be_checked(app):
    st, r = run(app, "cycle,capacity_ah\n1,NaN\n2,nan\n3,NAN", "capacity_ah", "b-f1-nan-0001")
    assert st == 200, r
    assert r["result"].startswith("Cannot check: no measurable rows"), r["result"]
    assert r["verdict"] == "unknown" and r["first_failing_row"] is None
    assert (r["passed"], r["failed"], r["unmeasurable"]) == (0, 0, 3)


def test_nan_inf_and_minus_inf_are_unmeasurable_and_counted_apart(app):
    table = "cycle,capacity_ah\n1,1.8\n2,NaN\n3,1.6\n4,inf\n5,1.3\n6,-inf"
    st, r = run(app, table, "capacity_ah", "b-f1-inf-0001")
    assert st == 200, r
    assert r["passed"] + r["failed"] == 3 and r["unmeasurable"] == 3, r
    assert r["result"] == "Failed at row 5: 1.3 is not above 1.4. Rows: 2 passed, 1 failed, 3 unmeasurable."


def test_the_nasa_sample_still_fails_at_row_136(app):
    st, r = run(app, tool_run.sample(), "capacity_ah", "")
    assert st == 200 and r["mode"] == "sample", r
    assert r["first_failing_row"] == 136
    assert r["result"] == "Failed at row 136: 1.399 is not above 1.4. Rows: 135 passed, 33 failed, 0 unmeasurable."


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
