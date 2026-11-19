"""Round 13, the server's part (knos_wanted.tool_run, knos_wanted.tool_page): "Check a test file against a limit".

GET /api/tools, POST /api/run, POST /api/pay, GET /api/usage (its tool counts), /mcp tools "tools" and "run",
GET /t/<id>/, GET /r/<result-id>/, GET /og/<t|r>/<id>.png. The program is the one the job released,
near/agents/job/data/limit/released_solution.py; until that file exists, matches released.json and was released for
test_limit3.py, these tests run the stand-in written to that test's interface, tests/limit_standin.py, which is kept
only here (it is never served).

B's "Proved by": file 2 of A8 (near/agents/job/data/limit/case2.csv, or the same file built here: 100 rows, row 37 the
first below the limit) through /api/run and through the connector gives first_failing_row 37, one result sentence, and
a link that opens."""
import datetime as dt
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from knos_wanted import server, tool_page, tool_run, usage, valley
from knos_wanted.qloo_mcp import InProcess, Qloo

REPO = Path(__file__).resolve().parents[3]
JOB = REPO / "near" / "agents" / "job"
STANDIN = Path(__file__).parent / "limit_standin.py"
PLAIN = ("tx", "hash", "testnet", "devnet", "mainnet", "proof", "prove", "verify", "contract", "token", "wallet", "agent",
         "job", "oracle", "LMSR", "NEAR", "Solana", "IRIS", "MCP", "API", "JSON")
FRONT = "https://drexthealpha.github.io"
SMALL = "row,reading\n1,5\n2,6\n3,7"


def file2() -> tuple[str, str, float]:
    """File 2 of A8, with its column and limit: the job's case2.csv when it is there, else the same file built here."""
    f = JOB / "data" / "limit" / "case2.csv"
    if f.is_file():
        return f.read_text(encoding="utf-8"), "reading_v", 2.5
    rows = ["cycle,capacity_ah"] + [f"{i},{1.38 if i == 37 else round(1.9 - i * 0.004, 3) if i < 37 else 1.6}" for i in range(1, 101)]
    return "\n".join(rows) + "\n", "capacity_ah", 1.4


def released_for_the_test() -> bool:
    return tool_run.ready() and str(tool_run.released().get("test") or "").endswith("/" + tool_run.CONF["claim_test"])


@pytest.fixture(autouse=True)
def program(monkeypatch):
    """The released program when it is the one released for the claim's locked test (test_limit3.py), else the stand-in
    under tests."""
    if not released_for_the_test():
        rel = {**tool_run.released(), "sha256": hashlib.sha256(STANDIN.read_bytes()).hexdigest()}
        monkeypatch.setattr(tool_run, "program_path", lambda: STANDIN)
        monkeypatch.setattr(tool_run, "released", lambda: rel)      # ready() compares the program with released.json


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(usage, "chain_count", lambda url=None: (_ for _ in ()).throw(OSError("no network in tests")))
    monkeypatch.setattr(tool_run, "_mem", {})
    monkeypatch.setitem(tool_run._measured, "v", None)
    state = server.State(Qloo(InProcess(), mode="mock", sleep=lambda s: None))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def call(base, path, body=None, headers=None, raw=False):
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=60) as r:
            got = r.read()
            return r.status, (got if raw else json.loads(got)), r.headers
    except urllib.error.HTTPError as e:
        got = e.read()
        return e.code, (got if raw or not got.startswith(b"{") else json.loads(got)), e.headers


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def words(text: str) -> int:
    return len(text.split())


def first_person(msg: str) -> bool:
    return bool(re.search(r"\b(I|me|my)\b", msg))


def sample_body(**kw):
    return {"id": "limit-check", "table": tool_run.sample(), "column": "capacity_ah", "rule": "above", "limit": 1.4, **kw}


def own(base, table=SMALL, column="reading", rule="above", limit=4, browser="b-test-000001", **kw):
    return call(base, "/api/run", {"id": "limit-check", "table": table, "column": column, "rule": rule, "limit": limit,
                                   "mode": "own", "browser": browser, "test": True, **kw})


def sample_row() -> int:
    """The sample's first row at or below 1.4, by the job's separate script (limit_check10.py), not by the program."""
    return int(subprocess.run([sys.executable, str(JOB / "limit_check10.py")], capture_output=True, text=True, timeout=30).stdout.split()[-1])


# ---- the program and its limits ---------------------------------------------------------------------------------------
def test_the_program_comes_only_from_the_released_file():
    real = tool_run.root() / "near" / "agents" / "job" / "data" / "limit" / "released_solution.py"
    assert tool_run.CONF["program"] == "near/agents/job/data/limit/released_solution.py" and real.parent.is_dir()
    assert "limit_standin" not in (Path(tool_run.__file__)).read_text(encoding="utf-8")       # the stand-in is never served


def test_with_no_released_program_the_tool_says_it_is_not_ready(app, monkeypatch):
    monkeypatch.setattr(tool_run, "program_path", lambda: Path(tempfile.gettempdir()) / "no-such-program.py")
    st, r, _ = call(app, "/api/run", sample_body(test=True))
    assert st == 503 and words(r["error"]) >= 12 and first_person(r["error"]), r


def test_the_locked_test_passes_on_the_program():
    """A8: near/agents/job/test_limit3.py run against the program as the checker runs it (the released one when it exists)."""
    claim = next(c for c in json.loads((REPO / "near" / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"] if c["test"] == "test_limit3.py")
    with tempfile.TemporaryDirectory() as d:                          # as near/agents/checker.py run_test lays it out
        shutil.copy(JOB / "test_limit3.py", Path(d) / "test_limit3.py")
        (Path(d) / "solution.py").write_bytes(tool_run.program_path().read_bytes())
        for rel in claim.get("data") or []:
            (Path(d) / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(JOB / rel, Path(d) / rel)
        p = subprocess.run([sys.executable, "-E", "-s", "-B", "test_limit3.py"], cwd=d, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and p.stdout.strip().splitlines()[-1].startswith("Passed: all 14 cases"), p.stdout + p.stderr


def test_the_limits_come_from_the_sandbox_settings():
    checker = (REPO / "near" / "agents" / "checker.py").read_text(encoding="utf-8")
    default = int(re.search(r'c\.get\("timeout_s"\) or (\d+)', checker).group(1))
    claims = json.loads((REPO / "near" / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"]
    c = next((c for c in claims if c["test"] == "test_limit3.py"), {})
    assert tool_run.limits() == {"max_rows": 100_000, "max_seconds": int(c.get("timeout_s") or default)}
    assert tool_run.CONF["checker_default_seconds"] == default      # runner_conf.py follows the checker


def test_100000_rows_run_inside_the_time_limit():
    table = "cycle,v\n" + "\n".join(f"{i},{2 + (i % 7) / 10}" for i in range(1, 100_001))
    got = tool_run.run_program(table, "v", "above", 1.5)
    assert got["result"] == "Passed: all 100000 rows stay above 1.5."
    assert got["passed"] == 100_000


def test_the_sample_is_the_jobs_and_fails_where_the_separate_script_says():
    assert tool_run.sample() == (JOB / "data" / "limit" / "sample.csv").read_text(encoding="utf-8").replace("\r\n", "\n").strip("\n")
    r = sample_row()
    got = tool_run.run_program(tool_run.sample(), "capacity_ah", "above", 1.4)
    assert got["first_failing_row"] == r and got["result"].startswith(f"Failed at row {r}: ") and got["passed"] == r - 1


def test_the_sample_label_and_limit_are_the_jobs():
    meta = json.loads((JOB / "data" / "limit" / "sample.json").read_text(encoding="utf-8"))
    conf = tool_run.CONF
    assert (conf["sample_label"], conf["sample_column"], conf["sample_rule"], conf["sample_limit"]) == (meta["label"], meta["column"], meta["rule"], meta["limit"])
    assert conf["sample_made_up"] == ("generated" in meta["made"]) and meta["limit_from"].startswith(conf["limit_rule_url"])


def test_prices_match_the_site_file():
    text = (REPO / "docs" / "data" / "pricing.json").read_text(encoding="utf-8")
    for v in (tool_run.CONF["free_runs_a_day"], tool_run.CONF["pack_runs"]):
        assert re.search(rf"(?<![\d.]){v}(?![\d.])", text), v


# ---- GET /api/tools and POST /api/run -----------------------------------------------------------------------------------
def test_api_tools_lists_only_the_limit_check(app):
    st, body, h = call(app, "/api/tools", headers={"Origin": FRONT})
    assert st == 200 and body == {"tools": [{"id": "limit-check", "title": "Check a test file against a limit", "sample": tool_run.sample()}]}
    assert h["Access-Control-Allow-Origin"] == FRONT
    assert call(app, "/t/count-distinct/", raw=True)[0] == 404                   # the list counter is no tool
    assert call(app, "/api/run", {"id": "count-distinct", "input": "a\nb"})[0] == 404


def test_a_sample_run_gives_the_result_and_a_link_that_opens(app):
    st, r, h = call(app, "/api/run", sample_body(mode="sample", browser="", test=True), headers={"Origin": FRONT})
    row = sample_row()
    assert st == 200 and h["Access-Control-Allow-Origin"] == FRONT
    assert r["result"].startswith(f"Failed at row {row}: ") and r["first_failing_row"] == row and r["runs_left"] is None
    assert r["result"].endswith(f"is not above 1.4. {row - 1} rows passed.")
    assert r["shown_by"] == "Checked by a test of 14 cases with known answers." and r["unchecked"] == []
    assert r["limits"] == tool_run.limits() and r["chart"]["fail"][0] == row and r["chart"]["limit"] == 1.4
    m = re.fullmatch(r"https?://[^/]+/r/([A-Za-z0-9_-]{12})/", r["link"])     # knos.onrender.com when deployed
    assert m, r["link"]
    st, page, _ = call(app, f"/r/{m.group(1)}/", raw=True)
    text = page.decode()
    assert st == 200 and r["result"] in text and "cycle,capacity_ah\n1,1.86" in text
    assert "Only people with this link" not in outside_fold(text)


def test_file_2_through_the_site_and_the_connector_fails_at_row_37(app):
    """B's Proved by: first_failing_row 37 through /api/run and /mcp, the same result sentence, a link that opens."""
    table, column, limit = file2()
    args = {"id": "limit-check", "table": table, "column": column, "rule": "above", "limit": limit}
    st, site, _ = call(app, "/api/run", {**args, "browser": "b-file2-0001", "test": True})
    assert st == 200 and site["first_failing_row"] == 37 and site["result"].startswith("Failed at row 37: "), site
    assert site["passed"] == 36 and site["result"].endswith(" 36 rows passed.")   # rows checked before row 37 (the released program)
    got = mcp(app, "run", args)["structuredContent"]
    assert set(got) == {"result", "first_failing_row", "passed", "unchecked", "shown_by", "link"}
    assert got["first_failing_row"] == 37 and got["result"] == site["result"] and got["shown_by"] == site["shown_by"]
    for link in (site["link"], got["link"]):
        rid = link.rstrip("/").rsplit("/", 1)[1]
        st, page, _ = call(app, f"/r/{rid}/", raw=True)
        assert st == 200 and site["result"] in page.decode()


def test_the_connector_takes_a_limit_sent_as_text_as_the_site_does(app):
    """B5: `run` takes the same inputs /api/run takes. A limit sent as text ("1.4") is checked, not refused, and gives
    the same answer; text that is not a number is refused with the site's own sentence."""
    table, column, limit = file2()
    args = {"id": "limit-check", "table": table, "column": column, "rule": "above", "limit": str(limit)}
    st, site, _ = call(app, "/api/run", {**args, "browser": "b-textlim-0001", "test": True})
    assert st == 200 and site["first_failing_row"] == 37, site
    got = mcp(app, "run", args)
    assert not got.get("isError"), got
    got = got["structuredContent"]
    for k in ("result", "first_failing_row", "passed", "unchecked", "shown_by"):
        assert got[k] == site[k], k
    st, bad, _ = call(app, "/api/run", {**args, "limit": "one point four", "browser": "b-textlim-0002", "test": True})
    refused = mcp(app, "run", {**args, "limit": "one point four"})
    assert st == 400 and refused["isError"] and refused["content"][0]["text"] == bad["error"], refused


def test_the_sentences_follow_the_rule_and_name_unchecked_rows(app):
    st, r, _ = own(app, "a,b\n1,9\n2,x\n3,8\n4,7", column="b", rule="below", limit=10)
    assert st == 200 and r["result"] == "Passed: all 3 rows stay below 10. Row 2 has no number, so I did not check it." and r["unchecked"] == [2]
    st, r, _ = own(app, "1,2.5\n2,2.6", column="column 2", rule="above", limit=2.5)
    assert r["result"] == "Failed at row 1: 2.5 is not above 2.5. 0 rows passed." and r["first_failing_row"] == 1


def test_own_runs_use_the_free_allowance_then_ask_for_test_money(app):
    seen = []
    for i in range(5):
        st, r, _ = own(app)
        assert st == 200 and r["result"] == "Passed: all 3 rows stay above 4." and r["mode"] == "own", r
        seen.append(r["free_left"])
    assert seen == [4, 3, 2, 1, 0]
    st, r, _ = own(app)
    assert st == 402 and r == {"pay": {"headline": "20 more runs for $1 in test money", "line": "Today this is test money. Nothing is charged.",
                                       "runs": 20, "price": "$1"}}
    st, p, _ = call(app, "/api/pay", {"browser": "b-test-000001", "press": "press-0001", "test": True}, headers={"Origin": FRONT})
    assert st == 200 and p == {"runs_left": 20, "recorded": "test"}
    st, again, _ = call(app, "/api/pay", {"browser": "b-test-000001", "press": "press-0001", "test": True})
    assert st == 200 and again == p                                     # the same press never records twice
    st, r, _ = own(app)
    assert st == 200 and r["runs_left"] == 19 and r["paid_left"] == 19 and r["free_left"] == 0



def test_one_payment_record_per_press_id_and_a_different_payload_is_refused(app):
    """R3: one record per idempotency key and identical payload; a different payload on the same key is refused."""
    body = {"browser": "b-press-00001", "press": "press-idem-1", "test": True}
    st, first, _ = call(app, "/api/pay", body)
    assert st == 200 and first == {"runs_left": 25, "recorded": "test"}, first
    for _ in range(3):
        assert call(app, "/api/pay", body)[1:2] == (first,)            # the same press and payload: the same answer
    for other in ({**body, "browser": "b-press-00002"}, {**body, "test": False}, {**body, "pack": 40}):
        st, r, _ = call(app, "/api/pay", other)
        assert st == 409, (other, st, r)
        words = r["error"].split()
        assert len(words) >= 12 and words[0] == "I" and "press Pay with test money again" in r["error"], r
    st, r, _ = own(app, browser="b-press-00001")
    assert st == 200 and r["paid_left"] == 20 and r["free_left"] == 4, r   # one pack recorded, for the first payload only
    st, r, _ = own(app, browser="b-press-00002")
    assert st == 200 and r["paid_left"] == 0, r                           # the refused payload recorded nothing

def test_sample_runs_are_free_and_not_counted_against_the_allowance(app):
    for _ in range(7):
        assert call(app, "/api/run", sample_body(browser="b-sample-0001"))[0] == 200
    st, r, _ = own(app, browser="b-sample-0001")
    assert st == 200 and r["free_left"] == 4


def test_no_browser_id_keeps_the_allowance_in_memory_only(app):
    st, r, _ = own(app, browser="")
    assert st == 200 and r["free_left"] == 4
    assert not list(valley._dir(tool_run.BROWSERS).glob("*.json"))     # nothing written for a browser with no id


def test_over_the_row_limit_is_413_with_the_items_words(app, monkeypatch):
    monkeypatch.setitem(tool_run.CONF, "max_rows", 10)
    st, r, _ = own(app, "v\n" + "\n".join(str(i) for i in range(11)), column="v")
    assert st == 413 and r["error"].startswith("Your file is too big. The limit is 10 rows. ")
    assert words(r["error"]) >= 12 and first_person(r["error"])
    assert own(app)[1]["free_left"] == 4                                # a refused file used no run


def test_over_the_time_limit_is_408_and_the_run_goes_back(app, monkeypatch):
    real = tool_run.limits
    monkeypatch.setattr(tool_run, "limits", lambda: {"max_rows": 100_000, "max_seconds": 0.001})
    st, r, _ = own(app)
    assert st == 408 and r["error"].startswith("This took too long and was stopped. Try a smaller file.")
    assert words(r["error"]) >= 12 and first_person(r["error"])
    monkeypatch.setattr(tool_run, "limits", real)      # not undo(): that would also undo the test's own state folder
    assert own(app)[1]["free_left"] == 4


def test_a_body_over_the_byte_limit_is_413(app, monkeypatch):
    monkeypatch.setitem(tool_run.CONF, "max_body_bytes", 100)
    st, r, _ = own(app, "v\n" + "1\n" * 100, column="v")
    assert st == 413 and words(r["error"]) >= 12


def test_every_refusal_is_a_full_first_person_sentence(app):
    for path, body, code in (("/api/run", {"id": "limit-check", "table": "  \n ", "column": "v", "rule": "above", "limit": 1}, 400),
                             ("/api/run", {"id": "limit-check", "table": SMALL, "column": "nope", "rule": "above", "limit": 1}, 400),
                             ("/api/run", {"id": "limit-check", "table": SMALL, "column": "reading", "rule": "sideways", "limit": 1}, 400),
                             ("/api/run", {"id": "limit-check", "table": SMALL, "column": "reading", "rule": "above", "limit": "lots"}, 400),
                             ("/api/run", {"id": "limit-check", "table": "a,b", "column": "a", "rule": "above", "limit": 1}, 400),
                             ("/api/run", {"id": "nope", "table": SMALL}, 404),
                             ("/api/pay", {"browser": "b-x-00000001"}, 400)):
        st, r, _ = call(app, path, body)
        if body.get("column") == "nope":      # G2's sentence word for word, then its next step (U6 Rules 16 and 17)
            assert r["error"].startswith("I cannot find a column named nope. Columns: row, reading. "), r
        assert st == code and words(r["error"]) >= 12 and first_person(r["error"]), r


# ---- the pages and their images ----------------------------------------------------------------------------------------
def og(page: str) -> dict:
    return dict(re.findall(r'<meta property="og:(title|description|image)" content="([^"]*)"', page))


def outside_fold(page: str) -> str:
    body = re.sub(r"<details>.*?</details>|<script.*?</script>|<style>.*?</style>|<head>.*?</head>|<textarea.*?</textarea>", " ", page, flags=re.S)
    # what is not shown: the language names laid out unseen (aria-hidden) and the parts that are hidden until a press
    body = re.sub(r'<span class="klang-list kwarm" aria-hidden="true">.*?</span></span>', " ", body, flags=re.S)
    body = re.sub(r"<(p|span|div|section)\b[^>]*\shidden\b[^>]*>.*?</\1>", " ", body, flags=re.S)
    return re.sub(r"<[^>]+>", " ", body)


def test_the_tool_page_has_its_tags_one_h1_and_plain_words(app):
    st, raw, _ = call(app, "/t/limit-check/", raw=True)
    page = raw.decode()
    assert st == 200
    tags = og(page)
    assert tags["title"] == "Check a test file against a limit" and len(tags["title"]) <= 52
    assert tags["description"] == "For anyone who tests batteries, motors, parts or machines." and words(tool_run.LINE) <= 12
    assert tags["image"].endswith("/og/t/limit-check.png")
    assert page.count("<h1") == 1 and ">Sample: made-up battery test<" in page and ">Try it<" in page and "<summary>How it works</summary>" in page
    assert '<span id="colname" data-user-content><bdi>capacity_ah</bdi></span>' in page and 'value="1.4"' in page and '<option value="above" selected>must stay above</option>' in page
    shown = outside_fold(page) + " " + " ".join(tags.values()).replace(tags["image"], "")
    for w in PLAIN:
        assert not re.search(rf"\b{w}\b", shown, re.I), w
    assert words(outside_fold(page)) <= 40
    assert call(app, "/t/limit-check", raw=True)[0] == 301
    st, raw, _ = call(app, "/t/nope/", raw=True)
    assert st == 404 and words(re.sub(r"<[^>]+>", " ", raw.decode().split("<h1>")[1])) >= 12


def test_the_fold_keeps_the_items_order(app):
    fold = tool_run.fold()
    assert fold[0].startswith("The sample is made up: a straight line from 1.86 to 1.29 over 168 cycles")
    heads = [x.split(":")[0] for x in fold[1:]]
    assert heads == ["What it does not do", "What happens to your file", "The test that showed it works", "The price", "Limits", "Who built it"]
    assert "files longer than 168 rows" in fold[3]


def test_an_own_result_page_says_who_can_see_it_and_is_not_indexed(app):
    st, r, _ = own(app, "t,v\n1,9\n2,3\n3,8", column="v", limit=4)
    rid = r["link"].rstrip("/").rsplit("/", 1)[1]
    st, raw, _ = call(app, f"/r/{rid}/", raw=True)
    page = raw.decode()
    assert st == 200 and "Only people with this link can see it." in page and 'name="robots" content="noindex"' in page
    assert "t,v\n1,9\n2,3\n3,8" in page and og(page)["description"] == "Failed at row 2: 3 is not above 4."
    assert og(page)["image"].endswith(f"/og/r/{rid}.png")
    assert call(app, f"/r/{rid}", raw=True)[0] == 301 and call(app, "/r/AAAAAAAAAAAA/", raw=True)[0] == 404


def test_the_og_images_are_1200_by_630_pngs(app):
    st, r, _ = call(app, "/api/run", sample_body())
    rid = r["link"].rstrip("/").rsplit("/", 1)[1]
    for path in ("/og/t/limit-check.png", f"/og/r/{rid}.png"):
        st, img, h = call(app, path, raw=True)
        assert st == 200 and h["Content-Type"] == "image/png" and img[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", img[16:24]) == (1200, 630)
    assert call(app, "/og/r/AAAAAAAAAAAA.png", raw=True)[0] == 404


def test_the_font_draws_every_letter_the_pages_use():
    line = "Failed at row 37: 2.41 is not above 2.5."
    w, h, rgb = tool_page.decode_rgb(tool_page.og_png("Check a test file against a limit", line))
    assert (w, h) == (1200, 630) and len(rgb) == 1200 * 630 * 3
    assert all(c in tool_page.FONT for c in line + "Passed: all 100 rows stay below 3.9. Check a test file Knos")


# ---- /mcp: the same JSON -----------------------------------------------------------------------------------------------
def mcp(base, name, args):
    st, r, _ = call(base, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}},
                    headers={"X-Knos-Test": "1"})
    assert st == 200, r
    return r["result"]


def test_the_connector_has_tools_and_run_with_the_same_answers(app):
    st, listed, _ = call(app, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"]: t for t in listed["result"]["tools"]}
    assert names["tools"]["annotations"]["readOnlyHint"] is True and names["run"]["annotations"]["readOnlyHint"] is False
    assert set(names["run"]["inputSchema"]["properties"]) == {"id", "table", "column", "rule", "limit"}
    assert "count-distinct" not in json.dumps(listed)
    assert mcp(app, "tools", {})["structuredContent"] == call(app, "/api/tools")[1]
    got = mcp(app, "run", {k: v for k, v in sample_body().items()})["structuredContent"]
    site = call(app, "/api/run", sample_body(test=True))[1]
    assert got == {k: v for k, v in site.items() if k in got and k != "link"} | {"link": got["link"]}


def test_the_connector_has_the_same_limits(app, monkeypatch):
    monkeypatch.setitem(tool_run.CONF, "max_rows", 3)
    r = mcp(app, "run", {"id": "limit-check", "table": "v\n1\n2\n3\n4", "column": "v", "rule": "above", "limit": 0})
    assert r["isError"] is True and "The limit is 3 rows" in r["content"][0]["text"]
    monkeypatch.setitem(tool_run.CONF, "max_rows", 100_000)
    small = {"id": "limit-check", "table": SMALL, "column": "reading", "rule": "above", "limit": 4}
    for _ in range(5):
        assert not mcp(app, "run", small).get("isError")
    r = mcp(app, "run", small)
    assert r["isError"] is True and "20 more runs for $1 in test money" in r["content"][0]["text"]


# ---- the counts (D2) and the measures (D1) ------------------------------------------------------------------------------
def test_usage_counts_per_day_with_tests_apart(app):
    call(app, "/api/tools")
    call(app, "/t/limit-check/?test=1", raw=True)
    call(app, "/api/run", sample_body())
    st, r, _ = own(app, browser="b-count-0001", test=False)
    rid = r["link"].rstrip("/").rsplit("/", 1)[1]
    call(app, f"/r/{rid}/", raw=True, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://web.whatsapp.com/"})
    call(app, f"/r/{rid}/", raw=True, headers={"User-Agent": "Mozilla/5.0", "Referer": FRONT + "/Knos/"})
    call(app, f"/r/{rid}/", raw=True, headers={"User-Agent": "curl/8.4.0"})
    call(app, "/api/pay", {"browser": "b-count-0001", "press": "press-count-1"})
    st, u, h = call(app, "/api/usage", headers={"Origin": FRONT})
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    row, test_row = u["days"][today], u["test_days"][today]
    assert st == 200 and h["Access-Control-Allow-Origin"] == FRONT and "checks" in u          # the old counter is still there
    assert row["tools_opened"] == 1 and test_row["tools_opened"] == 1
    assert row["sample_runs"] == 1 and row["own_runs"] == 1 and row["test_payments"] == 1
    assert row["results_opened_elsewhere"] == 1 and row["link_previews"] == 1
    assert set(u["measures"]) == {"day7_return", "active_days", "paying_share"}
    assert u["measures"]["paying_share"] == {"used_up": 0, "paid": 0, "share": None}



def test_connector_runs_are_counted_apart_from_runs_on_the_site(app):
    """R2 (D08): a run through /mcp is on its own counter, never in sample_runs or own_runs."""
    st, r, _ = call(app, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "run", "arguments": sample_body()}})
    assert st == 200 and not r["result"].get("isError"), r
    st, r, _ = call(app, "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "run", "arguments":
                    {"id": "limit-check", "table": SMALL, "column": "reading", "rule": "above", "limit": 4}}})
    assert st == 200 and not r["result"].get("isError"), r
    call(app, "/api/run", sample_body())
    row = call(app, "/api/usage")[1]["days"][dt.datetime.now(dt.timezone.utc).date().isoformat()]
    assert (row["connector_runs"], row["sample_runs"], row["own_runs"]) == (2, 1, 0), row

def test_the_three_measures(tmp_path):
    day = dt.date(2026, 11, 20)
    d = lambda n: (day - dt.timedelta(days=n)).isoformat()   # noqa: E731
    rows = {"aaaaaaaa": {"first": d(8), "days": [d(8), d(5), d(1)], "exhausted": True, "paid": True},
            "bbbbbbbb": {"first": d(7), "days": [d(7)], "exhausted": True, "paid": False},
            "cccccccc": {"first": d(2), "days": [d(2)], "exhausted": False, "paid": False},
            "dddddddd": {"first": d(9), "days": [d(9), d(2)], "test": True, "exhausted": True, "paid": True}}
    for k, v in rows.items():
        valley._save(tool_run.BROWSERS, k, {"id": k, **v}, chain=False)
    m = tool_run.measures(day)
    assert m["day7_return"] == {"browsers": 2, "returned": 1, "share": 0.5}       # aaaaaaaa ran on its day 7
    assert m["active_days"]["browsers"] == 2 and m["active_days"]["mean"] == 1.5   # aaaaaaaa: days 0 and 3; bbbbbbbb: day 0
    assert m["paying_share"] == {"used_up": 2, "paid": 1, "share": 0.5}
