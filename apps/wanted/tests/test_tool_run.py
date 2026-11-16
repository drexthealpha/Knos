"""Round 13, the server's part (knos_wanted.tool_run, knos_wanted.tool_page): every route the tool adds.

GET /api/tools, POST /api/run, POST /api/pay, GET /api/usage (its tool counts), /mcp tools "tools" and "run",
GET /t/<id>/, GET /r/<result-id>/, GET /og/<t|r>/<id>.png. The program is pass_agent.py's SOLUTION, unchanged."""
import ast
import datetime as dt
import hashlib
import json
import re
import struct
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from knos_wanted import server, tool_page, tool_run, usage, valley
from knos_wanted.qloo_mcp import InProcess, Qloo

REPO = Path(__file__).resolve().parents[3]
PLAIN = ("tx", "hash", "testnet", "devnet", "mainnet", "proof", "prove", "verify", "contract", "token", "wallet", "agent",
         "job", "oracle", "LMSR", "NEAR", "Solana", "IRIS", "MCP", "API", "JSON")
FRONT = "https://drexthealpha.github.io"


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


def own(base, text, browser="b-test-000001", **kw):
    return call(base, "/api/run", {"id": "count-distinct", "input": text, "mode": "own", "browser": browser, "test": True, **kw})


# ---- the program and its limits ---------------------------------------------------------------------------------------
def test_the_program_is_pass_agent_solution_unchanged():
    src = (REPO / "near" / "agents" / "pass_agent.py").read_text(encoding="utf-8")
    sol = next(ast.literal_eval(n.value) for n in ast.parse(src).body if isinstance(n, ast.Assign) and n.targets[0].id == "SOLUTION")
    assert tool_run.solution() == sol
    assert tool_run.solution_sha256() == hashlib.sha256(sol.encode()).hexdigest()
    assert "solution.py" in tool_run.run_program.__doc__ or "folder" in tool_run.run_program.__doc__


def test_the_sample_is_20_lines_with_12_different_and_the_estimate_is_12():
    lines = tool_run.SAMPLE.splitlines()
    assert len(lines) == 20 and len(set(lines)) == 12
    got = tool_run.run_program(tool_run.SAMPLE)
    assert got == {"estimate": 12, "lines": 20, "exact": 12}


def test_the_limits_come_from_the_sandbox_settings():
    checker = (REPO / "near" / "agents" / "checker.py").read_text(encoding="utf-8")
    default = int(re.search(r'c\.get\("timeout_s"\) or (\d+)', checker).group(1))
    claims = json.loads((REPO / "near" / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"]
    hll = next(c for c in claims if c["test"] == "test_hll.py")
    assert tool_run.limits() == {"max_lines": 100_000, "max_seconds": int(hll.get("timeout_s") or default)}
    assert tool_run.CONF["checker_default_seconds"] == default      # runner_conf.py follows the checker


def test_the_exact_count_is_given_up_to_100000_lines():
    got = tool_run.run_program("\n".join(f"v{i % 70_000}" for i in range(100_000)))
    assert got["exact"] == 70_000 and abs(got["estimate"] - 70_000) / 70_000 < 0.10


def test_prices_match_the_site_file_when_it_exists():
    f = REPO / "docs" / "data" / "pricing.json"
    if not f.exists():
        pytest.skip("docs/data/pricing.json is the site builder's file; not written yet")
    text = f.read_text(encoding="utf-8")
    for v in (tool_run.CONF["free_runs_a_day"], tool_run.CONF["pack_runs"]):
        assert re.search(rf"(?<![\d.]){v}(?![\d.])", text), v


# ---- GET /api/tools and POST /api/run -----------------------------------------------------------------------------------
def test_api_tools(app):
    st, body, h = call(app, "/api/tools", headers={"Origin": FRONT})
    assert st == 200 and body == {"tools": [{"id": "count-distinct", "title": "Count the different items in a list", "sample": tool_run.SAMPLE}]}
    assert h["Access-Control-Allow-Origin"] == FRONT


def test_a_sample_run_gives_the_result_and_a_link_that_opens(app):
    st, r, h = call(app, "/api/run", {"id": "count-distinct", "input": tool_run.SAMPLE, "mode": "sample", "browser": "", "test": True},
                    headers={"Origin": FRONT})
    assert st == 200 and h["Access-Control-Allow-Origin"] == FRONT
    assert r["result"] == "About 12 different items" and r["exact"] == 12 and r["runs_left"] is None
    assert r["shown_by"] == "Checked by a test that counted 30,000 different visitors to within 10%."
    assert r["limits"] == {"max_lines": 100_000, "max_seconds": 20}
    m = re.fullmatch(r"https?://[^/]+/r/([A-Za-z0-9_-]{12})/", r["link"])     # knos.onrender.com when deployed
    assert m, r["link"]
    st, page, _ = call(app, f"/r/{m.group(1)}/", raw=True)
    text = page.decode()
    assert st == 200 and "About 12 different items" in text and "Exact count: 12" in text and "banana\ncherry" in text
    assert "Only people with this link" not in outside_fold(text)


def test_own_runs_use_the_free_allowance_then_ask_for_test_money(app):
    seen = []
    for i in range(5):
        st, r, _ = own(app, "a\nb\nb\nc\na")
        assert st == 200 and r["exact"] == 3 and r["result"] == "About 3 different items", r
        seen.append(r["free_left"])
    assert seen == [4, 3, 2, 1, 0]
    st, r, _ = own(app, "a\nb")
    assert st == 402 and r == {"pay": {"headline": "20 more runs for $1 in test money", "line": "Today this is test money. Nothing is charged.",
                                       "runs": 20, "price": "$1"}}
    st, p, _ = call(app, "/api/pay", {"browser": "b-test-000001", "press": "press-0001", "test": True}, headers={"Origin": FRONT})
    assert st == 200 and p == {"runs_left": 20, "recorded": "test"}
    st, again, _ = call(app, "/api/pay", {"browser": "b-test-000001", "press": "press-0001", "test": True})
    assert st == 200 and again == p                                     # the same press never records twice
    st, r, _ = own(app, "x\ny")
    assert st == 200 and r["runs_left"] == 19 and r["paid_left"] == 19 and r["free_left"] == 0


def test_sample_runs_are_free_and_not_counted_against_the_allowance(app):
    for _ in range(7):
        assert call(app, "/api/run", {"id": "count-distinct", "input": tool_run.SAMPLE, "browser": "b-sample-0001"})[0] == 200
    st, r, _ = own(app, "q\nr", browser="b-sample-0001")
    assert st == 200 and r["free_left"] == 4


def test_no_browser_id_keeps_the_allowance_in_memory_only(app):
    st, r, _ = own(app, "a\nb", browser="")
    assert st == 200 and r["free_left"] == 4
    assert not list(valley._dir(tool_run.BROWSERS).glob("*.json"))     # nothing written for a browser with no id


def test_over_the_line_limit_is_413_with_a_full_message(app, monkeypatch):
    monkeypatch.setitem(tool_run.CONF, "max_lines", 10)
    st, r, _ = own(app, "\n".join(str(i) for i in range(11)))
    assert st == 413 and r["error"] == "Your list is too long for me to count here. The limit is 10 lines. Try a shorter list."
    assert words(r["error"]) >= 12 and first_person(r["error"])
    assert own(app, "a")[1]["free_left"] == 4                           # a refused list used no run


def test_over_the_time_limit_is_408_and_the_run_goes_back(app, monkeypatch):
    real = tool_run.limits
    monkeypatch.setattr(tool_run, "limits", lambda: {"max_lines": 100_000, "max_seconds": 0.001})
    st, r, _ = own(app, "a\nb\nc")
    assert st == 408 and "took too long" in r["error"] and "Try a shorter list" in r["error"]
    assert words(r["error"]) >= 12 and first_person(r["error"])
    monkeypatch.setattr(tool_run, "limits", real)      # not undo(): that would also undo the test's own state folder
    assert own(app, "a")[1]["free_left"] == 4


def test_a_body_over_the_byte_limit_is_413(app, monkeypatch):
    monkeypatch.setitem(tool_run.CONF, "max_body_bytes", 100)
    st, r, _ = own(app, "x" * 200)
    assert st == 413 and words(r["error"]) >= 12


def test_empty_list_unknown_tool_and_missing_press_are_full_sentences(app):
    for path, body, code in (("/api/run", {"id": "count-distinct", "input": "  \n "}, 400),
                             ("/api/run", {"id": "nope", "input": "a"}, 404),
                             ("/api/pay", {"browser": "b-x-00000001"}, 400)):
        st, r, _ = call(app, path, body)
        assert st == code and words(r["error"]) >= 12 and first_person(r["error"]), r


# ---- the pages and their images ----------------------------------------------------------------------------------------
def og(page: str) -> dict:
    return dict(re.findall(r'<meta property="og:(title|description|image)" content="([^"]*)"', page))


def outside_fold(page: str) -> str:
    body = re.sub(r"<details>.*?</details>|<script.*?</script>|<style>.*?</style>|<head>.*?</head>", " ", page, flags=re.S)
    return re.sub(r"<[^>]+>", " ", body)


def test_the_tool_page_has_its_tags_one_h1_and_plain_words(app):
    st, raw, _ = call(app, "/t/count-distinct/", raw=True)
    page = raw.decode()
    assert st == 200
    tags = og(page)
    assert tags["title"] == "Count the different items in a list" and len(tags["title"]) <= 52
    assert tags["description"] == tool_run.LINE and words(tool_run.LINE) <= 12
    assert tags["image"].endswith("/og/t/count-distinct.png")
    assert page.count("<h1") == 1 and "Sample list" in page and ">Try it<" in page and "<summary>How it works</summary>" in page
    shown = outside_fold(page) + " " + " ".join(tags.values()).replace(tags["image"], "")
    for w in PLAIN:
        assert not re.search(rf"\b{w}\b", shown, re.I), w
    assert words(re.sub(re.escape(tool_run.SAMPLE.replace("\n", " ")), "", " ".join(outside_fold(page).split()))) <= 40
    assert call(app, "/t/count-distinct", raw=True)[0] == 301
    st, raw, _ = call(app, "/t/nope/", raw=True)
    assert st == 404 and words(re.sub(r"<[^>]+>", " ", raw.decode().split("<h1>")[1])) >= 12


def test_an_own_result_page_says_who_can_see_it_and_is_not_indexed(app):
    st, r, _ = own(app, "red\nblue\nred")
    rid = r["link"].rstrip("/").rsplit("/", 1)[1]
    st, raw, _ = call(app, f"/r/{rid}/", raw=True)
    page = raw.decode()
    assert st == 200 and "Only people with this link can see it." in page and 'name="robots" content="noindex"' in page
    assert "red\nblue\nred" in page and og(page)["description"] == "About 2 different items"
    assert og(page)["image"].endswith(f"/og/r/{rid}.png")
    assert call(app, f"/r/{rid}", raw=True)[0] == 301 and call(app, "/r/AAAAAAAAAAAA/", raw=True)[0] == 404


def test_the_og_images_are_1200_by_630_pngs(app):
    st, r, _ = call(app, "/api/run", {"id": "count-distinct", "input": tool_run.SAMPLE})
    rid = r["link"].rstrip("/").rsplit("/", 1)[1]
    for path in ("/og/t/count-distinct.png", f"/og/r/{rid}.png"):
        st, img, h = call(app, path, raw=True)
        assert st == 200 and h["Content-Type"] == "image/png" and img[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", img[16:24]) == (1200, 630)
    assert call(app, "/og/r/AAAAAAAAAAAA.png", raw=True)[0] == 404


def test_the_font_draws_every_letter_the_pages_use():
    w, h, rgb = tool_page.decode_rgb(tool_page.og_png("Count the different items in a list", "About 12 different items"))
    assert (w, h) == (1200, 630) and len(rgb) == 1200 * 630 * 3
    assert all(c in tool_page.FONT for c in "About 1,234,567 different items Count the list Knos")


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
    assert mcp(app, "tools", {})["structuredContent"] == call(app, "/api/tools")[1]
    got = mcp(app, "run", {"id": "count-distinct", "input": tool_run.SAMPLE})["structuredContent"]
    site = call(app, "/api/run", {"id": "count-distinct", "input": tool_run.SAMPLE, "test": True})[1]
    assert set(got) == {"result", "exact", "shown_by", "link"}
    assert got["exact"] == 12 and got["result"] == site["result"] and got["shown_by"] == site["shown_by"]
    rid = got["link"].rstrip("/").rsplit("/", 1)[1]
    assert call(app, f"/r/{rid}/", raw=True)[0] == 200


def test_the_connector_has_the_same_limits(app, monkeypatch):
    monkeypatch.setitem(tool_run.CONF, "max_lines", 3)
    r = mcp(app, "run", {"id": "count-distinct", "input": "a\nb\nc\nd"})
    assert r["isError"] is True and "The limit is 3 lines" in r["content"][0]["text"]
    monkeypatch.setitem(tool_run.CONF, "max_lines", 100_000)
    for _ in range(5):
        assert not mcp(app, "run", {"id": "count-distinct", "input": "a\nb"}).get("isError")
    r = mcp(app, "run", {"id": "count-distinct", "input": "a\nb"})
    assert r["isError"] is True and "20 more runs for $1 in test money" in r["content"][0]["text"]


# ---- the counts (D2) and the measures (D1) ------------------------------------------------------------------------------
def test_usage_counts_per_day_with_tests_apart(app):
    call(app, "/api/tools")
    call(app, "/t/count-distinct/?test=1", raw=True)
    call(app, "/api/run", {"id": "count-distinct", "input": tool_run.SAMPLE})
    st, r, _ = call(app, "/api/run", {"id": "count-distinct", "input": "a\nb", "browser": "b-count-0001"})
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
