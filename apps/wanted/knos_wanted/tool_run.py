"""Tools a stranger can run (Round 13, parts A to D): the first is "Check a test file against a limit".

The program is the one Knos's own job flow released for the claim whose locked test is near/agents/job/test_limit.py,
copied byte for byte to near/agents/job/data/limit/released_solution.py (released.json beside it names the job). Its
interface is fixed by that test: check(table, column, rule, limit) -> {result, first_failing_row, rows, skipped, values}.
Until that file exists the tool answers that it is not ready; nothing else stands in for it here.

It runs as the checker runs a locked test (near/agents/checker.py run_test): a temporary folder of its own,
`python -E -s -B`, a time limit. The two limits come from one place, runner_conf.py: the time limit is the one the
checker uses for this claim (near/claims/claims.json timeout_s, else the checker's default), the row limit is set there
because that sandbox has no input-size setting.

Routes (server.py calls handle_get and handle_post first):
    GET  /api/tools                      {"tools": [{"id", "title", "sample"}]}
    POST /api/run   {id, table, column, rule, limit, browser, test}   the result, its link, runs left and the limits
    POST /api/pay   {browser, press, test}             a test payment: 20 more runs, recorded once per press
    GET  /t/<id>/, /r/<result-id>/      server-written pages with their og tags; GET /og/<t|r>/<id>.png, their image
The usage counts (D2) and the three measures (D1) join GET /api/usage (usage()).

Store: the app's state folder (valley._save, never mirrored on chain). Render rebuilds that folder on every deploy, so
results, allowances, test payments and counts start again from empty after each deploy; each kind is capped.
A browser is known only by a random id its page makes after the person says yes to being counted; with no id, its
allowance is held in this process's memory under a keyed hash of its address, never written."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import tool_page, valley
from .runner_conf import CONF

HERE = Path(__file__).parent
TOOL_ID = CONF["tool"]
TITLE = "Check a test file against a limit"
LINE = "For anyone who tests batteries, motors, parts or machines."
SHOWN_BY = "Checked by a test of 7 files with known answers."
TEST_URL = "https://github.com/drexthealpha/Knos/blob/main/near/agents/job/test_limit.py"
PUBLIC = "https://knos.onrender.com"
FRONT = "https://drexthealpha.github.io/Knos/"
OWN_HOSTS = ("knos.onrender.com", "drexthealpha.github.io")
PREVIEW_UA = re.compile(r"bot|crawl|spider|facebookexternalhit|whatsapp|telegram|slack|discord|preview|embed|skype|"
                        r"linkedin|curl|wget|python-|go-http|okhttp|node-fetch|headless", re.I)
ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
RID = re.compile(r"[A-Za-z0-9_-]{12}")
RESULTS, BROWSERS, PRESSES, USAGE = "tool-results", "tool-browsers", "tool-presses", "tool-usage"
FIELDS = ("tools_opened", "sample_runs", "own_runs", "results_opened_elsewhere", "test_payments", "link_previews", "connector_runs")
RULES = ("above", "below")

READER = '''"""The reader in front of the released program: the run's four inputs in as JSON, its answer out."""
import json
import sys

from solution import check

a = json.loads(sys.stdin.buffer.read().decode("utf-8"))
print(json.dumps(check(a["table"], a["column"], a["rule"], a["limit"])))
'''


class Refusal(Exception):
    def __init__(self, code: int, body: dict):
        super().__init__(body.get("error") or str(body))
        self.code, self.body = code, body


def root() -> Path:
    return Path(os.environ.get("KNOS_NEAR_ROOT") or Path(__file__).resolve().parents[3])   # /app in the image


def program_path() -> Path:
    """The released program, byte for byte as the job released it (near/agents/job/data/limit/released_solution.py)."""
    return root() / CONF["program"]


def released() -> dict:
    """released.json beside the program: the job that built it. {} until the job is released."""
    try:
        got = json.loads((root() / CONF["released"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def ready() -> bool:
    return program_path().is_file()


def program() -> str:
    return program_path().read_text(encoding="utf-8")


def program_sha256() -> str:
    return hashlib.sha256(program_path().read_bytes()).hexdigest()


_sample: dict = {}


def sample() -> str:
    """The sample file the front door and the tool page open with (near/agents/job/data/limit/sample.csv), as text."""
    f = root() / CONF["sample"]
    try:
        key = (str(f), f.stat().st_mtime)
    except OSError:
        return ""
    if _sample.get("key") != key:
        _sample.update(key=key, text=f.read_text(encoding="utf-8").replace("\r\n", "\n").strip("\n"))
    return _sample["text"]


def max_seconds() -> int:
    """The checker's time limit for this claim: claims.json timeout_s, else run_test's default (runner_conf.py)."""
    try:
        claims = json.loads((root() / "near" / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"]
        c = next((c for c in claims if c.get("test") == CONF["claim_test"]), {})
    except (OSError, ValueError, KeyError):
        c = {}
    return int(float(c.get("timeout_s") or CONF["checker_default_seconds"]))


def limits() -> dict:
    return {"max_rows": int(CONF["max_rows"]), "max_seconds": max_seconds()}


def longest_test_file() -> int:
    """The most data rows in any file the locked test checks (near/agents/job/data/limit/*.csv)."""
    return max((columns(f.read_text(encoding="utf-8"))[1] for f in (root() / CONF["sample"]).parent.glob("*.csv")), default=0)


def job_link() -> str:
    r = released()
    return str(r.get("release_url") or r.get("url") or r.get("link") or "")


def fold() -> list[str]:
    """The "How it works" fold, in the item's order (A5): the sample's credit first, then what it does not do, what
    happens to your file, the test that showed it works, the price, and the job that built it."""
    lim = limits()
    out = []
    _, n = columns(sample())
    if CONF.get("sample_made_up") and n:
        vals = [r[1] for r in csv.reader(io.StringIO(sample()))][1:]
        out.append(f"The sample is made up: a straight line from {vals[0]} to {vals[-1]} over {n} cycles, because NASA's page "
                   f"offers no download from a nasa.gov address. Its limit, {tool_page.shown_limit(CONF['sample_limit'])}, is the "
                   f"end-of-life rule on <a href=\"{CONF['limit_rule_url']}\">NASA's battery data page</a>.")
    out += [
        "What it does not do: it checks one column against one limit. It does not judge whether the limit is the right "
        "one. A row whose value is not a number is skipped and counted.",
        f"What happens to your file: it is sent to the Knos server at knos.onrender.com and checked there. It is kept, up "
        f"to its first {CONF['input_kept_chars']:,} characters, so that its result link works, until the server is next "
        f"updated or {CONF['results_kept']:,} newer results replace it. A sample result can be seen by anyone with its link. "
        "A result from your own file is shown only to people who have its link and is never listed anywhere. Knos keeps "
        "nothing that says who you are.",
        f"The test that showed it works: six made-up files with known answers and the sample, each checked against a "
        f"limit. It did not cover files longer than {longest_test_file()} rows, or files separated by anything other than "
        f"commas. <a href=\"{TEST_URL}\">The test</a> is public.",
        f"The price: runs on the sample are free. {CONF['free_runs_a_day']} runs on your own files are free each day. "
        f"After that, {CONF['pack_runs']} more runs cost {CONF['pack_price']} in test money. Today nothing is charged.",
        f"Limits: up to {lim['max_rows']:,} rows, and a run is stopped after {lim['max_seconds']} seconds.",
    ]
    link = job_link()
    out.append(f'Who built it: AI helpers wrote the program through Knos, and it was released only when that test passed. '
               f'<a href="{link}">The public record</a>.' if link else
               "Who built it: AI helpers write the program through Knos, and it is released only when that test passes. "
               "It has not been released yet.")
    return out


def tool(tid: str) -> dict | None:
    if tid != TOOL_ID:
        return None
    return {"id": TOOL_ID, "title": TITLE, "line": LINE, "sample": sample(), "sample_label": CONF["sample_label"],
            "column": CONF["sample_column"], "rule": CONF["sample_rule"], "limit": CONF["sample_limit"],
            "limits": limits(), "fold": fold()}


def tools_doc() -> dict:
    return {"tools": [{"id": TOOL_ID, "title": TITLE, "sample": sample()}]}


first_sentence = tool_page.first_sentence    # "Failed at row 37: 1.38 is not above 1.4.": og:description and the link image


def lines_of(text: str) -> list[str]:
    return [x for x in (y.strip() for y in str(text).replace("\r\n", "\n").split("\n")) if x]


def is_sample(text: str) -> bool:
    s = sample()
    return bool(s) and lines_of(text) == lines_of(s)


def _num(cell: str) -> float | None:
    try:
        v = float(str(cell).strip())
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def columns(table: str) -> tuple[list[str], int]:
    """The file's column names and its number of data rows, by the program's own rule (SPEC2): a first row with any
    cell that is not a number is the header; otherwise the columns are "column 1", "column 2" and so on."""
    rows = [r for r in csv.reader(io.StringIO(table)) if any(c.strip() for c in r)]
    if not rows:
        return [], 0
    if any(_num(c) is None for c in rows[0]):
        return [c.strip() for c in rows[0]], len(rows) - 1
    return [f"column {i + 1}" for i in range(max(len(r) for r in rows))], len(rows)


# ---- the run -----------------------------------------------------------------------------------------------------------
_slots = threading.BoundedSemaphore(int(CONF["runs_at_once"]))
KEPT = "I kept your file in the box; try a shorter one."


def too_big() -> dict:
    return {"error": f"Your file is too big. The limit is {int(CONF['max_rows']):,} rows. {KEPT}"}


def not_ready() -> dict:
    return {"error": "I cannot check files yet, because the program for this tool has not passed the test that decides "
                     "it works. Please try again later."}


def inputs(body: dict) -> tuple[str, str, str, float]:
    """The four inputs, read and checked before anything runs: (table, column, rule, limit). Raises Refusal 400 or 413."""
    table, column, rule, limit = body.get("table"), body.get("column"), body.get("rule"), body.get("limit")
    if not isinstance(table, str) or not table.strip():
        raise Refusal(400, {"error": "Your file is empty, so I have nothing to check yet. Choose a file or paste a table, then press Try it."})
    if rule not in RULES:
        raise Refusal(400, {"error": "I need to know whether the values must stay above or below the limit. Please choose one, then press Try it."})
    try:
        lim = float(limit) if not isinstance(limit, bool) else math.nan
    except (TypeError, ValueError):
        lim = math.nan
    if not math.isfinite(lim):
        raise Refusal(400, {"error": "I need the limit as a number, such as 1.4, before I can check your file. Please type it, then press Try it."})
    names, n = columns(table)
    if n > int(CONF["max_rows"]):
        raise Refusal(413, too_big())
    if not isinstance(column, str) or column not in names:
        shown = ", ".join(names[:12])
        raise Refusal(400, {"error": f"I could not find a column called \"{str(column)[:40]}\" in your file. The columns I found are: {shown}. Please pick one."})
    if n == 0:
        raise Refusal(400, {"error": "Your file has a header but no rows under it, so I have nothing to check. Please add rows, then press Try it."})
    return table, column, rule, lim


def run_program(table: str, column: str, rule: str, limit: float) -> dict:
    """The reader and the released program in a folder of their own, as the checker runs a test: the program's answer."""
    if not ready():
        raise Refusal(503, not_ready())
    lim = limits()
    if not _slots.acquire(timeout=lim["max_seconds"]):
        raise Refusal(503, {"error": "I am checking other files right now and could not start yours. Your file is still in the box. Please try again in a moment."})
    try:
        with tempfile.TemporaryDirectory(prefix="knos-tool-") as d:
            (Path(d) / "solution.py").write_bytes(program_path().read_bytes())
            (Path(d) / "reader.py").write_text(READER, encoding="utf-8")
            args = json.dumps({"table": table, "column": column, "rule": rule, "limit": limit}).encode("utf-8")
            try:
                p = subprocess.run([sys.executable, "-E", "-s", "-B", "reader.py"], cwd=d, input=args,
                                   capture_output=True, timeout=lim["max_seconds"])
            except subprocess.TimeoutExpired:
                raise Refusal(408, {"error": f"This took too long and was stopped. Try a smaller file. I stopped it after "
                                             f"{lim['max_seconds']} seconds and kept your file in the box."}) from None
    finally:
        _slots.release()
    said = p.stdout.decode("utf-8", "replace").strip().splitlines()
    try:
        got = json.loads(said[-1]) if p.returncode == 0 and said else None
    except ValueError:
        got = None
    if not isinstance(got, dict) or not isinstance(got.get("result"), str):
        print(f"knos tool run failed: {p.stderr.decode('utf-8', 'replace')[-300:]}", file=sys.stderr, flush=True)
        raise Refusal(500, {"error": "The checking program stopped with an error, so I have no result for this file. Your file is still in the box. Please try again."})
    return got


def fails(v: float, rule: str, limit: float) -> bool:
    return v <= limit if rule == "above" else v >= limit


def chart(values: list, rule: str, limit: float) -> dict:
    """What the chart draws: the values as points (at most chart_points of them, the first failing one always kept),
    the limit, and the first failing point. x is the value's place among the numbers the program read."""
    vals = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)]
    bad = next((i for i, v in enumerate(vals) if fails(v, rule, limit)), None)
    step = max(1, math.ceil(len(vals) / int(CONF["chart_points"])))
    keep = sorted(set(range(0, len(vals), step)) | ({bad} if bad is not None else set()) | ({len(vals) - 1} if vals else set()))
    return {"points": [[i + 1, vals[i]] for i in keep], "fail": [bad + 1, vals[bad]] if bad is not None else None,
            "limit": limit, "rule": rule, "n": len(vals)}


# ---- the store ---------------------------------------------------------------------------------------------------------
_lock = threading.RLock()
_mem: dict = {}            # allowances of browsers with no id: keyed hash of the address -> record, this process only
_salt = secrets.token_bytes(16)


def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def _prune(kind: str, keep: int) -> None:
    files = list(valley._dir(kind).glob("*.json"))
    if len(files) > keep + 50:
        for f in sorted(files, key=lambda f: f.stat().st_mtime)[:len(files) - keep]:
            f.unlink(missing_ok=True)


def address_key(address: str) -> str:
    return "addr:" + hashlib.sha256(_salt + str(address).encode()).hexdigest()[:24]


def _key(browser, address: str) -> str:
    return browser if isinstance(browser, str) and ID.fullmatch(browser) else address_key(address)


def _rec(key: str) -> dict:
    if key.startswith("addr:"):
        if key not in _mem and len(_mem) > 50_000:
            _mem.clear()                             # a day's worth at most: the oldest go together
        return _mem.setdefault(key, {"day": _today(), "used": 0, "paid_left": 0})
    return valley._safe_load(BROWSERS, key) or {"id": key, "day": _today(), "used": 0, "paid_left": 0,
                                                 "first": None, "days": [], "exhausted": False, "paid": False}


def _keep(key: str, rec: dict) -> None:
    if key.startswith("addr:"):
        _mem[key] = rec
        return
    valley._save(BROWSERS, key, rec, chain=False)
    _prune(BROWSERS, int(CONF["browsers_kept"]))


def _fresh(rec: dict) -> dict:
    if rec.get("day") != _today():
        rec.update(day=_today(), used=0)
    return rec


def _left(rec: dict) -> tuple[int, int]:
    return max(0, int(CONF["free_runs_a_day"]) - int(rec.get("used") or 0)), max(0, int(rec.get("paid_left") or 0))


def pay_offer() -> dict:
    return {"pay": {"headline": f"{CONF['pack_runs']} more runs for {CONF['pack_price']} in test money",
                    "line": "Today this is test money. Nothing is charged.", "runs": int(CONF["pack_runs"]), "price": CONF["pack_price"]}}


def bump(field: str, test: bool = False) -> None:
    """One count on today's UTC row; Knos's own tests and WALK runs on a row of their own. Never fails a request."""
    try:
        with _lock:
            doc = valley._safe_load("pages", USAGE) or {"since": _today(), "days": {}, "test_days": {}}
            rows = doc.setdefault("test_days" if test else "days", {})
            row = rows.setdefault(_today(), {k: 0 for k in FIELDS})
            row[field] = int(row.get(field) or 0) + 1
            cut = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=120)).isoformat()
            for k in [k for k in rows if k < cut]:
                del rows[k]
            valley._save("pages", USAGE, doc, chain=False)
    except Exception as why:  # noqa: BLE001
        print(f"knos tool usage: not counted: {type(why).__name__}: {str(why)[:120]}", flush=True)


def save_result(table: str, column: str, rule: str, limit: float, got: dict, sample_run: bool) -> dict:
    rid = secrets.token_urlsafe(9)                     # 12 characters: never a 16-hex demand result's id
    while re.fullmatch(r"[0-9a-f]{12}", rid):          # nor a referral code (/r/<12 hex>, valley.make_referral)
        rid = secrets.token_urlsafe(9)
    ffr = got.get("first_failing_row")
    rec = {"id": rid, "tool": TOOL_ID, "mode": "sample" if sample_run else "own", "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "column": column, "rule": rule, "limit": limit, "result": str(got["result"]),
           "first_failing_row": int(ffr) if isinstance(ffr, int) and not isinstance(ffr, bool) else None,
           "rows": int(got.get("rows") or 0), "skipped": int(got.get("skipped") or 0),
           "chart": chart(got.get("values") or [], rule, limit)}
    if not sample_run:                                 # a sample result keeps no input: the sample is the tool's
        lines = table.replace("\r\n", "\n").split("\n")
        kept, size = [], 0
        for x in lines:
            size += len(x) + 1
            if size > int(CONF["input_kept_chars"]):
                break
            kept.append(x)
        rec.update(input="\n".join(kept), cut=len(kept) < len(lines), shown_lines=len(kept), lines=len(lines))
    with _lock:
        valley._save(RESULTS, rid, rec, chain=False)
        _prune(RESULTS, int(CONF["results_kept"]))
    return rec


def load_result(rid: str) -> dict | None:
    if not RID.fullmatch(rid or "") or re.fullmatch(r"[0-9a-f]{12}", rid):
        return None
    got = valley._safe_load(RESULTS, rid)
    return got if got and got.get("tool") == TOOL_ID else None


def shape(rec: dict, base: str = PUBLIC) -> dict:
    """A stored result as the pages and the run answer show it."""
    return {"id": rec["id"], "mode": rec["mode"], "result": rec["result"], "first_failing_row": rec.get("first_failing_row"),
            "rows": rec.get("rows"), "skipped": rec.get("skipped"), "shown_by": SHOWN_BY, "link": f"{base}/r/{rec['id']}/",
            "column": rec["column"], "rule": rec["rule"], "limit": rec["limit"], "chart": rec.get("chart"),
            "input": sample() if rec["mode"] == "sample" else rec.get("input", ""),
            "lines": rec.get("lines"), "cut": rec.get("cut", False), "shown_lines": rec.get("shown_lines")}


ANSWER = ("result", "first_failing_row", "rows", "skipped", "shown_by", "link")


def run(body: dict, address: str, base: str = PUBLIC, test: bool = False, connector: bool = False) -> dict:
    """One run of a tool: the answer /api/run and the connector's run give. Raises Refusal (400, 402, 408, 413, 500, 503)."""
    if str(body.get("id") or "") != TOOL_ID:
        raise Refusal(404, {"error": f"I do not have a tool called \"{str(body.get('id'))[:40]}\". The tool I have is {TOOL_ID}: ask for it by that name."})
    table, column, rule, limit = inputs(body)
    if not ready():
        raise Refusal(503, not_ready())
    sample_run = is_sample(table)
    key, rec, took = None, None, None
    if not sample_run:
        key = _key(body.get("browser"), address)
        with _lock:
            rec = _fresh(_rec(key))
            free, paid = _left(rec)
            if free == 0 and paid == 0:
                rec["exhausted"] = True
                _keep(key, rec)
                raise Refusal(402, pay_offer())
            took = "free" if free else "paid"
            if took == "free":
                rec["used"] = int(rec.get("used") or 0) + 1
            else:
                rec["paid_left"] = paid - 1
            _keep(key, rec)
    try:
        got = run_program(table, column, rule, limit)
    except Refusal:
        if key:                                          # nothing was checked: the run goes back
            with _lock:
                rec = _fresh(_rec(key))
                if took == "free":
                    rec["used"] = max(0, int(rec.get("used") or 0) - 1)
                else:
                    rec["paid_left"] = int(rec.get("paid_left") or 0) + 1
                _keep(key, rec)
        raise
    saved = save_result(table, column, rule, limit, got, sample_run)
    out = {k: v for k, v in shape(saved, base).items() if k in ANSWER + ("id", "mode", "chart", "column", "rule", "limit")}
    out["limits"] = limits()
    if sample_run:
        out.update(runs_left=None, free_left=None, paid_left=None)
    else:
        with _lock:
            rec = _fresh(_rec(key))
            free, paid = _left(rec)
            if not key.startswith("addr:"):
                today = _today()
                rec["test"] = bool(rec.get("test") or test)
                rec["first"] = rec.get("first") or today
                first = dt.date.fromisoformat(rec["first"])
                if (dt.date.fromisoformat(today) - first).days <= 7 and today not in rec["days"]:
                    rec["days"].append(today)
                if free == 0:
                    rec["exhausted"] = True
            _keep(key, rec)
        out.update(runs_left=free + paid, free_left=free, paid_left=paid)
    bump("sample_runs" if sample_run else "own_runs", test)
    if connector:
        bump("connector_runs", test)
    return out


def pay(body: dict, address: str, test: bool = False) -> dict:
    """A test payment for one browser: 20 more runs, recorded once per press id; a repeat of the press gets the same answer."""
    press = body.get("press")
    if not isinstance(press, str) or not ID.fullmatch(press):
        raise Refusal(400, {"error": "I could not record this test payment because the press had no id. Nothing was charged. Please press Pay with test money again."})
    key = _key(body.get("browser"), address)
    pid = hashlib.sha256(f"{key}|{press}".encode()).hexdigest()[:32]
    with _lock:
        seen = valley._safe_load(PRESSES, pid)
        if seen:
            return seen["answer"]
        rec = _fresh(_rec(key))
        rec["paid_left"] = int(rec.get("paid_left") or 0) + int(CONF["pack_runs"])
        rec["paid"] = True
        _keep(key, rec)
        free, paid = _left(rec)
        answer = {"runs_left": free + paid, "recorded": "test"}
        valley._save(PRESSES, pid, {"answer": answer, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, chain=False)
        _prune(PRESSES, 5_000)
    bump("test_payments", test)
    return answer


# ---- the counts (D2) and the measures (D1) -------------------------------------------------------------------------------
_measured: dict = {"at": 0.0, "v": None}


def measures(today: dt.date | None = None) -> dict:
    """The three D1 measures over browsers that said yes to being counted, own-data runs only (sample runs are a separate
    demo count), Knos's own test browsers left out."""
    if today is None and _measured["v"] is not None and time.time() - _measured["at"] < 60:
        return _measured["v"]
    day = today or dt.datetime.now(dt.timezone.utc).date()
    rows = [b for b in valley._all(BROWSERS) if b.get("first") and not b.get("test")]
    cohort = [b for b in rows if (day - dt.date.fromisoformat(b["first"])).days >= 7]
    back = [b for b in cohort if (dt.date.fromisoformat(b["first"]) + dt.timedelta(days=7)).isoformat() in b.get("days", [])]
    week = [b for b in rows if (day - dt.date.fromisoformat(b["first"])).days >= 6]
    active = [len({d for d in b.get("days", []) if 0 <= (dt.date.fromisoformat(d) - dt.date.fromisoformat(b["first"])).days <= 6}) for b in week]
    used = [b for b in rows if b.get("exhausted")]
    paid = [b for b in used if b.get("paid")]
    share = lambda a, b: round(a / b, 4) if b else None   # noqa: E731
    out = {"day7_return": {"browsers": len(cohort), "returned": len(back), "share": share(len(back), len(cohort))},
           "active_days": {"browsers": len(week), "mean": round(sum(active) / len(active), 2) if active else None,
                           "by_days": {str(k): active.count(k) for k in range(1, 8)}},
           "paying_share": {"used_up": len(used), "paid": len(paid), "share": share(len(paid), len(used))}}
    if today is None:
        _measured.update(at=time.time(), v=out)
    return out


def usage() -> dict:
    doc = valley._safe_load("pages", USAGE) or {"since": None, "days": {}, "test_days": {}}
    return {"days": doc.get("days") or {}, "test_days": doc.get("test_days") or {}, "measures": measures(),
            "tool_counts_since": doc.get("since"),
            "tool_counted": "per UTC day. tools_opened: GET /t/<id>/ and GET /api/tools; sample_runs and own_runs: runs that "
                            "returned a result; results_opened_elsewhere: GET /r/<id>/ with no referrer or one from another "
                            "site; link_previews: the same from a link-preview robot or a command-line client; test_payments: "
                            "test payments recorded; connector_runs: runs through /mcp (also in sample_runs or own_runs). "
                            "test_days: the same counts for requests marked as Knos's own tests or WALK runs. measures: "
                            "own-data runs of browsers that said yes to being counted, test browsers left out",
            "tool_store": "the server's disk, which Render empties on every deploy: counts restart from that day"}


# ---- routes --------------------------------------------------------------------------------------------------------------
def _marked(h, qs=None, body=None) -> bool:
    return h.headers.get("X-Knos-Test") == "1" or (qs or {}).get("test", [""])[0] == "1" or bool(isinstance(body, dict) and body.get("test") is True)


def _base(h) -> str:
    from . import tasks
    return tasks.public_base(h._base())


def _html(h, code: int, text: str, cache: str = "no-store") -> None:
    h._send(code, text.encode("utf-8"), "text/html; charset=utf-8", {"Cache-Control": cache})


def _elsewhere(h) -> str | None:
    """"results_opened_elsewhere", "link_previews", or None when the opener came from Knos's own pages."""
    if PREVIEW_UA.search(h.headers.get("User-Agent") or ""):
        return "link_previews"
    ref = h.headers.get("Referer") or ""
    host = re.sub(r"^https?://([^/:]+).*$", r"\1", ref).lower() if ref else ""
    own = OWN_HOSTS + ((h.headers.get("Host") or "").split(":")[0].lower(),)
    return None if host and host in own else "results_opened_elsewhere"


def handle_get(h, state, u, qs) -> bool:
    p = u.path
    if p == "/api/tools":
        bump("tools_opened", _marked(h, qs))
        return h._send(200, tools_doc(), headers={"Cache-Control": "no-store"}) or True
    m = re.fullmatch(r"/t/([a-z0-9-]{1,40})(/?)", p)
    if m:
        t = tool(m.group(1))
        if t is None:
            return _html(h, 404, tool_page.missing(FRONT)) or True
        if not m.group(2):
            return h._send(301, b"", "text/plain", {"Location": f"/t/{t['id']}/" + (f"?{u.query}" if u.query else "")}) or True
        bump("tools_opened", _marked(h, qs))
        return _html(h, 200, tool_page.page(t, _base(h), front=FRONT)) or True
    m = re.fullmatch(r"/r/([A-Za-z0-9_-]{12})(/?)", p)
    if m:
        rec = load_result(m.group(1))
        if rec is None and not m.group(2):
            return False                                 # /r/<code> with no slash: a referral link (product_routes)
        if rec is None:
            return _html(h, 404, tool_page.missing(FRONT)) or True
        if not m.group(2):
            return h._send(301, b"", "text/plain", {"Location": f"/r/{rec['id']}/" + (f"?{u.query}" if u.query else "")}) or True
        why = _elsewhere(h)
        if why:
            bump(why, _marked(h, qs))
        return _html(h, 200, tool_page.page(tool(rec["tool"]) or tool(TOOL_ID), _base(h), shape(rec, _base(h)), front=FRONT)) or True
    m = re.fullmatch(r"/og/(t|r)/([A-Za-z0-9_-]{1,40})\.png", p)
    if m:
        if m.group(1) == "t":
            t = tool(m.group(2))
            img = tool_page.og_png(t["title"]) if t else None
        else:
            rec = load_result(m.group(2))
            img = tool_page.og_png(TITLE, first_sentence(rec["result"])) if rec else None
        if img is None:
            return h._send(404, {"error": "I have no image at this address."}) or True
        return h._send(200, img, "image/png", {"Cache-Control": "public, max-age=86400"}) or True
    return False


def _body(h) -> dict:
    n = int(h.headers.get("Content-Length") or 0)
    if n > int(CONF["max_body_bytes"]):
        raise Refusal(413, {"error": f"Your file is too big for me to read here. The limit is {int(CONF['max_body_bytes']) // 1_000_000} megabytes of text. {KEPT}"})
    try:
        got = json.loads(h.rfile.read(n) or b"{}")
    except ValueError:
        raise Refusal(400, {"error": "I could not read what was sent, so nothing was checked. Please send your file again as text."}) from None
    if not isinstance(got, dict):
        raise Refusal(400, {"error": "I could not read what was sent, so nothing was checked. Please send your file again as text."})
    return got


def handle_post(h, state, path: str) -> bool:
    if path not in ("/api/run", "/api/pay"):
        return False
    if not state.allow(h._client(), "tool" if path == "/api/run" else "tool_pay"):
        return h._send(429, {"error": "I have had a great many requests from your network in the last few minutes. Please wait a minute and try again."}) or True
    try:
        body = _body(h)
        test = _marked(h, None, body)
        if path == "/api/run":
            return h._send(200, run(body, h._client(), _base(h), test)) or True
        return h._send(200, pay(body, h._client(), test)) or True
    except Refusal as r:
        return h._send(r.code, r.body) or True


# ---- the connector (/mcp): the same two answers as /api/tools and /api/run -----------------------------------------------
MCP_TOOLS = [
    {"name": "tools", "title": "Knos tools",
     "description": "Lists the tools a person can run on Knos: each one's id, title and sample file. No key and no account.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "run", "title": "Run a Knos tool",
     "description": "Runs one Knos tool on a file, as the Knos site does, with the same limits and the same free runs a day: "
                    "for limit-check, a comma separated table, the column to check, the rule (above or below) and the limit. "
                    "Returns the result sentence, the first failing row, the rows checked, the rows skipped, the test that "
                    "showed the program works, and the result's link.",
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string", "enum": [TOOL_ID], "description": "the tool's id"},
         "table": {"type": "string", "maxLength": int(CONF["max_body_bytes"]), "description": "the file as text, comma separated"},
         "column": {"type": "string", "description": "a column name from the file's header, or \"column 1\", \"column 2\" and so on when it has none"},
         "rule": {"type": "string", "enum": list(RULES), "description": "whether the values must stay above or below the limit"},
         "limit": {"type": "number", "description": "the limit; a value equal to it fails"}},
         "required": ["id", "table", "column", "rule", "limit"], "additionalProperties": False}},
]


def mcp_call(name: str, args: dict) -> dict:
    """The connector's answer, the same JSON as the site's routes. A refusal raises ValueError with its message."""
    from . import outside, qloo_rest
    if name == "tools":
        return tools_doc()
    headers = getattr(outside.CTX, "headers", None)
    test = bool(headers is not None and headers.get("X-Knos-Test") == "1")
    who = qloo_rest.current_visitor() or "connector"
    try:
        got = run({k: args.get(k) for k in ("id", "table", "column", "rule", "limit")}, "mcp:" + who, PUBLIC, test, connector=True)
    except Refusal as r:
        if r.code == 402:
            o = r.body["pay"]
            raise ValueError(f"Today's {CONF['free_runs_a_day']} free runs on your own files are used. {o['headline']}: "
                             f"{o['line']} Pay on the Knos site: {PUBLIC}/t/{TOOL_ID}/") from None
        raise ValueError(r.body.get("error") or "the run did not finish") from None
    return {k: got[k] for k in ANSWER}
