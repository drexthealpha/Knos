"""Tools a stranger can run (Round 13, parts A to D): the first is "Count the different items in a list".

The program is near/agents/pass_agent.py's SOLUTION, unchanged: the HyperLogLog Counter that passed the locked test
near/agents/job/test_hll.py on NEAR testnet. It counts a stream given to Counter.add, so a small reader (READER, below)
sits in front of it: one item per line in, Counter.count() out, and the exact count of different lines when the list has
100,000 lines or fewer.

It runs as the checker runs a locked test (near/agents/checker.py run_test): a temporary folder of its own,
`python -E -s -B`, a time limit. The two limits come from one place, data/runner.json: the time limit is the one the
checker uses for this claim (near/claims/claims.json timeout_s, else the checker's default), the line limit is set there
because that sandbox had no input-size setting.

Routes (server.py calls handle_get and handle_post first):
    GET  /api/tools                      {"tools": [{"id", "title", "sample"}]}
    POST /api/run   {id, input, mode, browser, test}   the result, its link, runs left and the limits; 402 / 413 / 408
    POST /api/pay   {browser, press, test}             a test payment: 20 more runs, recorded once per press
    GET  /t/<id>/, /r/<result-id>/      server-written pages with their og tags; GET /og/<t|r>/<id>.png, their image
The usage counts (D2) and the three measures (D1) join GET /api/usage (usage()).

Store: the app's state folder (valley._save, never mirrored on chain). Render rebuilds that folder on every deploy, so
results, allowances, test payments and counts start again from empty after each deploy; each kind is capped.
A browser is known only by a random id its page makes after the person says yes to being counted; with no id, its
allowance is held in this process's memory under a keyed hash of its address, never written."""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
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

HERE = Path(__file__).parent
CONF = json.loads((HERE / "data" / "runner.json").read_text(encoding="utf-8"))
TOOL_ID = CONF["tool"]
TITLE = "Count the different items in a list"
LINE = "For anyone with a long list who wants one quick count."
# 20 lines, 12 different items: the program's estimate on them is 12 (tests/test_tool_run.py runs it)
SAMPLE = "\n".join(["apple", "banana", "cherry", "apple", "grape", "lemon", "banana", "mango", "orange", "apple",
                    "peach", "pear", "mango", "plum", "kiwi", "pear", "lime", "kiwi", "lemon", "apple"])
SHOWN_BY = "Checked by a test that counted 30,000 different visitors to within 10%."
PAPER = "https://doi.org/10.46298/dmtcs.3545"
EXACT_UP_TO = 100_000
PUBLIC = "https://knos.onrender.com"
FRONT = "https://drexthealpha.github.io/Knos/"
OWN_HOSTS = ("knos.onrender.com", "drexthealpha.github.io")
PREVIEW_UA = re.compile(r"bot|crawl|spider|facebookexternalhit|whatsapp|telegram|slack|discord|preview|embed|skype|"
                        r"linkedin|curl|wget|python-|go-http|okhttp|node-fetch|headless", re.I)
ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
RID = re.compile(r"[A-Za-z0-9_-]{12}")
RESULTS, BROWSERS, PRESSES, USAGE = "tool-results", "tool-browsers", "tool-presses", "tool-usage"
FIELDS = ("tools_opened", "sample_runs", "own_runs", "results_opened_elsewhere", "test_payments", "link_previews", "connector_runs")

READER = f'''"""The reader in front of the program that passed the locked test: one item per line in, its count out."""
import json
import sys

from solution import Counter

lines = [x.strip() for x in sys.stdin.buffer.read().decode("utf-8", "replace").splitlines()]
lines = [x for x in lines if x]
c = Counter()
for x in lines:
    c.add(x)
print(json.dumps({{"estimate": c.count(), "lines": len(lines), "exact": len(set(lines)) if len(lines) <= {EXACT_UP_TO} else None}}))
'''


class Refusal(Exception):
    def __init__(self, code: int, body: dict):
        super().__init__(body.get("error") or str(body))
        self.code, self.body = code, body


def root() -> Path:
    return Path(os.environ.get("KNOS_NEAR_ROOT") or Path(__file__).resolve().parents[3])   # /app in the image


_sol: dict = {}


def solution() -> str:
    """pass_agent.py's SOLUTION string, read from its source (importing it would import the agent's runner)."""
    if "src" not in _sol:
        tree = ast.parse((root() / "near" / "agents" / "pass_agent.py").read_text(encoding="utf-8"))
        _sol["src"] = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                           and any(getattr(t, "id", "") == "SOLUTION" for t in n.targets))
    return _sol["src"]


def solution_sha256() -> str:
    return hashlib.sha256(solution().encode("utf-8")).hexdigest()


def max_seconds() -> int:
    """The checker's time limit for this claim: claims.json timeout_s, else run_test's default (data/runner.json)."""
    try:
        claims = json.loads((root() / "near" / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"]
        c = next((c for c in claims if c.get("test") == CONF["claim_test"]), {})
    except (OSError, ValueError, KeyError):
        c = {}
    return int(float(c.get("timeout_s") or CONF["checker_default_seconds"]))


def limits() -> dict:
    return {"max_lines": int(CONF["max_lines"]), "max_seconds": max_seconds()}


def fold() -> list[str]:
    """The "How it works" fold, in the item's order (A5), plus what it depends on (Daily design)."""
    lim = limits()
    return [
        "What it does not do: it does not say which items repeat, and it does not fix spelling, so \"Apple\" and "
        "\"apple\" count as two. Blank lines and spaces at the ends of a line are left out. On a long list the "
        "\"About\" number can be a few percent off; the exact count is the true one.",
        f"What happens to your list: it is sent to the Knos server at knos.onrender.com and counted there. It is kept so "
        f"that its result link works, until the server is next updated or {CONF['results_kept']:,} newer results replace it. "
        "A sample result can be seen by anyone with its link. A result from your own list is shown only to people who "
        "have its link and is never listed anywhere. Knos keeps no name, email or network address.",
        f"The test that showed it works: the same program counted two streams of 30,000 different visitors, each seen "
        f"twice, to within 10%, using at most 1.5 kilobytes. That test did not cover lists of more than 30,000 different "
        f"items, or the paper's figure of 2% for very large lists. <a href=\"{PUBLIC}/api/near/claim/code\">The program</a> "
        f"and <a href=\"https://github.com/drexthealpha/Knos/blob/main/near/agents/job/test_hll.py\">its test</a> are public.",
        f"The price: runs on the sample are free. {CONF['free_runs_a_day']} runs on your own lists are free each day. "
        f"After that, {CONF['pack_runs']} more runs cost {CONF['pack_price']} in test money. Today nothing is charged.",
        f"Limits: up to {lim['max_lines']:,} lines, and a run is stopped after {lim['max_seconds']} seconds.",
        "What it depends on: the Knos server being up. After a quiet spell it can take a while to wake.",
        f"The paper it came from: <a href=\"{PAPER}\">HyperLogLog (2007), by Flajolet, Fusy, Gandouet and Meunier</a>.",
    ]


def tool(tid: str) -> dict | None:
    if tid != TOOL_ID:
        return None
    return {"id": TOOL_ID, "title": TITLE, "line": LINE, "sample": SAMPLE, "limits": limits(), "fold": fold()}


def tools_doc() -> dict:
    return {"tools": [{"id": TOOL_ID, "title": TITLE, "sample": SAMPLE}]}


def result_line(n: int) -> str:
    return f"About {n:,} different item{'' if n == 1 else 's'}"


def lines_of(text: str) -> list[str]:
    return [x for x in (y.strip() for y in str(text).splitlines()) if x]


def is_sample(text: str) -> bool:
    return lines_of(text) == lines_of(SAMPLE)


# ---- the run -----------------------------------------------------------------------------------------------------------
_slots = threading.BoundedSemaphore(int(CONF["runs_at_once"]))


def too_long(n: int | None = None) -> dict:
    return {"error": f"Your list is too long for me to count here. The limit is {CONF['max_lines']:,} lines. Try a shorter list."}


def run_program(text: str) -> dict:
    """The reader and the program in a folder of their own, as the checker runs a test: {estimate, lines, exact}."""
    n = len(lines_of(text))
    if n == 0:
        raise Refusal(400, {"error": "Your list is empty, so I have nothing to count yet. Type one item on each line, then press Try it."})
    lim = limits()
    if n > lim["max_lines"]:
        raise Refusal(413, too_long(n))
    if not _slots.acquire(timeout=lim["max_seconds"]):
        raise Refusal(503, {"error": "I am counting other lists right now and could not start yours. Your list is still in the box. Please try again in a moment."})
    try:
        with tempfile.TemporaryDirectory(prefix="knos-tool-") as d:
            (Path(d) / "solution.py").write_text(solution(), encoding="utf-8")
            (Path(d) / "reader.py").write_text(READER, encoding="utf-8")
            try:
                p = subprocess.run([sys.executable, "-E", "-s", "-B", "reader.py"], cwd=d, input=text.encode("utf-8"),
                                   capture_output=True, timeout=lim["max_seconds"])
            except subprocess.TimeoutExpired:
                raise Refusal(408, {"error": f"This took too long, so I stopped it after {lim['max_seconds']} seconds. "
                                             "Your list is still in the box. Try a shorter list."}) from None
    finally:
        _slots.release()
    said = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if p.returncode != 0 or not said:
        print(f"knos tool run failed: {p.stderr.decode('utf-8', 'replace')[-300:]}", file=sys.stderr, flush=True)
        raise Refusal(500, {"error": "The counting program stopped with an error, so I have no count for this list. Your list is still in the box. Please try again."})
    return json.loads(said[-1])


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


def save_result(text: str, got: dict, sample: bool) -> dict:
    rid = secrets.token_urlsafe(9)                     # 12 characters: never a 16-hex demand result's id
    while re.fullmatch(r"[0-9a-f]{12}", rid):          # nor a referral code (/r/<12 hex>, valley.make_referral)
        rid = secrets.token_urlsafe(9)
    rec = {"id": rid, "tool": TOOL_ID, "mode": "sample" if sample else "own", "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "estimate": int(got["estimate"]), "exact": got.get("exact"), "lines": int(got["lines"])}
    if not sample:                                     # a sample result keeps no input: the sample is the tool's
        kept, size = [], 0
        for x in lines_of(text):
            size += len(x) + 1
            if size > int(CONF["input_kept_chars"]):
                break
            kept.append(x)
        rec.update(input="\n".join(kept), cut=len(kept) < rec["lines"], shown_lines=len(kept))
    with _lock:
        valley._save(RESULTS, rid, rec, chain=False)
        _prune(RESULTS, int(CONF["results_kept"]))
    return rec


def load_result(rid: str) -> dict | None:
    if not RID.fullmatch(rid or "") or re.fullmatch(r"[0-9a-f]{12}", rid):
        return None
    return valley._safe_load(RESULTS, rid)


def shape(rec: dict, base: str = PUBLIC) -> dict:
    """A stored result as the pages and the run answer show it."""
    return {"id": rec["id"], "mode": rec["mode"], "result": result_line(rec["estimate"]), "exact": rec.get("exact"),
            "shown_by": SHOWN_BY, "link": f"{base}/r/{rec['id']}/", "input": SAMPLE if rec["mode"] == "sample" else rec.get("input", ""),
            "lines": rec.get("lines"), "cut": rec.get("cut", False), "shown_lines": rec.get("shown_lines")}


def run(body: dict, address: str, base: str = PUBLIC, test: bool = False, connector: bool = False) -> dict:
    """One run of a tool: the answer /api/run and the connector's run give. Raises Refusal (400, 402, 408, 413, 500, 503)."""
    if str(body.get("id") or "") != TOOL_ID:
        raise Refusal(404, {"error": f"I do not have a tool called \"{str(body.get('id'))[:40]}\". The tool I have is {TOOL_ID}: ask for it by that name."})
    text = body.get("input")
    if not isinstance(text, str):
        raise Refusal(400, {"error": "I need your list as text, with one item on each line, before I can count anything."})
    sample = is_sample(text)
    key, rec, took = None, None, None
    if not sample:
        n = len(lines_of(text))
        if n == 0 or n > int(CONF["max_lines"]):
            run_program(text)                            # the same refusal the program's runner gives (400 or 413)
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
        got = run_program(text)
    except Refusal:
        if key:                                          # nothing was counted: the run goes back
            with _lock:
                rec = _fresh(_rec(key))
                if took == "free":
                    rec["used"] = max(0, int(rec.get("used") or 0) - 1)
                else:
                    rec["paid_left"] = int(rec.get("paid_left") or 0) + 1
                _keep(key, rec)
        raise
    saved = save_result(text, got, sample)
    out = {k: v for k, v in shape(saved, base).items() if k in ("id", "mode", "result", "exact", "shown_by", "link", "lines")}
    out["limits"] = limits()
    if sample:
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
    bump("sample_runs" if sample else "own_runs", test)
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
    """The three D1 measures over browsers that said yes to being counted, own-list runs only (sample runs are a separate
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
                            "own-list runs of browsers that said yes to being counted, test browsers left out",
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
            img = tool_page.og_png(TITLE, result_line(rec["estimate"])) if rec else None
        if img is None:
            return h._send(404, {"error": "I have no image at this address."}) or True
        return h._send(200, img, "image/png", {"Cache-Control": "public, max-age=86400"}) or True
    return False


def _body(h) -> dict:
    n = int(h.headers.get("Content-Length") or 0)
    if n > int(CONF["max_body_bytes"]):
        raise Refusal(413, {"error": f"Your list is too large for me to read here. The limit is {int(CONF['max_body_bytes']) // 1_000_000} megabytes of text. Try a shorter list."})
    try:
        got = json.loads(h.rfile.read(n) or b"{}")
    except ValueError:
        raise Refusal(400, {"error": "I could not read what was sent, so nothing was counted. Please send your list again as text."}) from None
    if not isinstance(got, dict):
        raise Refusal(400, {"error": "I could not read what was sent, so nothing was counted. Please send your list again as text."})
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
     "description": "Lists the tools a person can run on Knos: each one's id, title and sample input. No key and no account.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "run", "title": "Run a Knos tool",
     "description": "Runs one Knos tool on an input, as the Knos site does, with the same limits and the same free runs a day: "
                    "for count-distinct, a list with one item per line. Returns the result line, the exact count, the "
                    "test that showed the program works, and the result's link.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string", "enum": [TOOL_ID], "description": "the tool's id"},
                                                      "input": {"type": "string", "maxLength": int(CONF["max_body_bytes"]),
                                                                "description": "one item per line"}},
                     "required": ["id", "input"], "additionalProperties": False}},
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
        got = run({"id": args.get("id"), "input": args.get("input")}, "mcp:" + who, PUBLIC, test, connector=True)
    except Refusal as r:
        if r.code == 402:
            o = r.body["pay"]
            raise ValueError(f"Today's {CONF['free_runs_a_day']} free runs on your own lists are used. {o['headline']}: "
                             f"{o['line']} Pay on the Knos site: {PUBLIC}/t/{TOOL_ID}/") from None
        raise ValueError(r.body.get("error") or "the run did not finish") from None
    return {k: got[k] for k in ("result", "exact", "shown_by", "link")}
