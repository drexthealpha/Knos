"""Tools a stranger can run (Round 13, parts A to D): the first is "Check a test file against a limit".

The program is the one Knos's own job flow released for the claim whose locked test is near/agents/job/test_limit3.py,
copied byte for byte to near/agents/job/data/limit/released_solution.py (released.json beside it names the job and the
program's sha256). Its interface is fixed by that test: check(table, column, rule, limit) -> {result, first_failing_row,
passed, unchecked, values}, unchecked being the row numbers that hold no number. Until that file exists, and whenever its sha256 is not the one released.json
records, the tool refuses to run; nothing else stands in for it here.

It runs as the checker runs a locked test (near/agents/checker.py run_test): a temporary folder of its own,
`python -E -s -B`, a time limit. The two limits come from one place, runner_conf.py: the time limit is the one the
checker uses for this claim (near/claims/claims.json timeout_s, else the checker's default), the row limit is set there
because that sandbox has no input-size setting.

Routes (server.py calls handle_get and handle_post first):
    GET  /api/tools                      {"tools": [{"id", "title", "sample"}]}
    POST /api/run   {id, table, column, rule, limit, browser, runs, test}   the result, its link, runs left and the limits
    POST /api/pay   {browser, runs, press, test}       a test payment: 20 more runs, recorded once per press
    GET  /t/<id>/, /r/<result-id>/      server-written pages with their og tags; GET /og/<t|r>/<id>.png, their image
The usage counts (D2) and the three measures (D1) join GET /api/usage (usage()).

Store: the app's state folder (valley._save, never mirrored on chain). Render rebuilds that folder on every deploy, so
results, allowances, test payments and counts start again from empty after each deploy; each kind is capped.
A browser is known only by a random id its page makes after the person says yes to being counted. The free runs are
per browser, as the pricing page says: a browser not counted sends another random id (runs) that its page keeps for the
allowance alone, held in this process's memory under a keyed hash, never written; a caller with neither id (the
connector, a form sent with no script) is held the same way under a keyed hash of its address."""
from __future__ import annotations

import base64
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
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

from . import tool_page, valley
from .runner_conf import CONF

HERE = Path(__file__).parent
TOOL_ID = CONF["tool"]
TITLE = "Check a test file against a limit"
LINE = "For anyone who tests batteries, motors, parts or machines."
SHOWN_BY = "Checked by a test of 14 cases with known answers."   # test_limit3.py's CASES: 14
TEST_URL = tool_page.TEST_URL
PUBLIC = "https://knos.onrender.com"
FRONT = "https://drexthealpha.github.io/Knos/"
OWN_HOSTS = ("knos.onrender.com", "drexthealpha.github.io")
PREVIEW_UA = re.compile(r"bot|crawl|spider|facebookexternalhit|whatsapp|telegram|slack|discord|preview|embed|skype|"
                        r"linkedin|curl|wget|python-|go-http|okhttp|node-fetch|headless", re.I)
ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
RID = re.compile(r"[A-Za-z0-9_-]{12}")
RESULTS, BROWSERS, PRESSES, USAGE = "tool-results", "tool-browsers", "tool-presses", "tool-usage"
CHALLENGES, INVITES = "tool-challenges", "tool-invites"
KEY = re.compile(r"[A-Za-z0-9_-]{16,64}")      # a result's own key (L17, L42): only the browser that ran it holds it
FIELDS = ("tools_opened", "sample_runs", "own_runs", "results_opened_elsewhere", "test_payments", "link_previews", "connector_runs",
          "test_payments_undone", "first_starter", "first_typed", "first_pasted")
FIRST = ("starter", "typed", "pasted")     # where a browser's first action came from (first_action, U3 Rule 11)
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
    """The program file exists and is, byte for byte, the one released.json records (its sha256), F1e."""
    try:
        return program_sha256() == str(released().get("sha256") or "").lower()
    except OSError:
        return False


def program() -> str:
    return program_path().read_text(encoding="utf-8")


def program_sha256() -> str:
    return hashlib.sha256(program_path().read_bytes()).hexdigest()


def tool_version() -> str:
    """The version a result was checked with (L19): the released job and the first 12 hex of the released program's sha256
    (released.json), so a result names the exact program that answered it."""
    r = released()
    sha = str(r.get("sha256") or "")[:12]
    return f"{r.get('job_id') or 'unreleased'}/{sha or 'none'}"


def test_sha256() -> str:
    """The sha256 of the locked test that decided the program works (released.json's "test", near/agents/job/test_limit3.py)."""
    rel = str(released().get("test") or f"near/agents/job/{CONF['claim_test']}")
    try:
        return hashlib.sha256((root() / rel).read_bytes()).hexdigest()
    except OSError:
        return ""


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
    """The most data rows in any file the locked test checks (its claim's "data" list in near/claims/claims.json)."""
    try:
        claims = json.loads((root() / "near" / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"]
        data = next((c.get("data") or [] for c in claims if c.get("test") == CONF["claim_test"]), [])
    except (OSError, ValueError, KeyError):
        data = []
    job = root() / "near" / "agents" / "job"
    return max((columns((job / rel).read_text(encoding="utf-8"))[1] for rel in data if (job / rel).is_file()), default=0)


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
        "one. A row with no number is not checked, and the result names it.",
        f"What happens to your file: it is sent to the Knos server at knos.onrender.com and checked there. It is kept, up "
        f"to its first {CONF['input_kept_chars']:,} characters, so that its result link works, until the server is next "
        f"updated or {CONF['results_kept']:,} newer results replace it. A sample result can be seen by anyone with its link. "
        "A result from your own file is shown only to people who have its link and is never listed anywhere. Knos keeps "
        "nothing that says who you are.",
        f"The test that showed it works: eleven made-up files with known answers and the sample, each checked against a "
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


REPO = Path(os.environ.get("KNOS_NEAR_ROOT") or HERE.parents[2])   # /app in the image (Dockerfile copies tools/ there)
_listed: dict = {}
_listed_lock = threading.Lock()


def manifest_ids() -> list[str]:
    """The ids scripts/tool_manifest.py listed() lists (IQ L49): a check whose locked test passed in an empty folder.
    Run once per process (the locked test takes about 2 s); a missing manifest runner lists nothing."""
    with _listed_lock:
        if "ids" not in _listed:
            ids: list[str] = []
            path = REPO / "scripts" / "tool_manifest.py"
            if path.is_file():
                import importlib.util
                spec = importlib.util.spec_from_file_location("knos_tool_manifest", path)
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)
                ok, _refused = m.listed(REPO)
                ids = [t["id"] for t in ok]
            _listed["ids"] = ids
        return _listed["ids"]


def tools_doc() -> dict:
    """The listed checks this app can run: publicly only the limit check, and only while its manifest lists it."""
    return {"tools": [{"id": TOOL_ID, "title": TITLE, "sample": sample()}] if TOOL_ID in manifest_ids() else []}


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


def is_data(cell: str) -> bool:
    """A cell float() can read is a data cell, NaN, inf and -inf included in any case (G2): never a header's."""
    try:
        float(str(cell).strip())
    except ValueError:
        return False
    return True


def header_row(row: list[str]) -> bool:
    """The program's rule (SPEC2, G2): a first row with any cell float() cannot read is the header."""
    return any(not is_data(c) for c in row)


def no_column(column, names: list[str]) -> str:
    """The program's own words for an unknown column (G2), answered before it runs, then one next step (UX/U6.md
    Rules 16 and 17: a refusal names what to do, in at least 12 words)."""
    return f"I cannot find a column named {column}. Columns: {', '.join(names)}. Choose one of them and check again."


def columns(table: str) -> tuple[list[str], int]:
    """The file's column names and its number of data rows, by the program's own rule (SPEC2): a first row with any
    cell float() cannot read is the header; otherwise the columns are "column 1", "column 2" and so on."""
    rows = [r for r in csv.reader(io.StringIO(table)) if any(c.strip() for c in r)]
    if not rows:
        return [], 0
    if header_row(rows[0]):
        return [c.strip() for c in rows[0]], len(rows) - 1
    return [f"column {i + 1}" for i in range(max(len(r) for r in rows))], len(rows)


DEC_COMMA = re.compile(r"^\s*[+-]?\d+,\d+\s*$")


def normalize(table: str) -> str:
    """A tab file or a semicolon file as the comma file the program reads (L26): the separator is read from the first
    line that holds any text, and only when that line has no comma; in a semicolon file a number written with a decimal
    comma (1,4) is read as 1.4. A comma file comes back unchanged."""
    first = next((x for x in str(table).replace("\r\n", "\n").split("\n") if x.strip()), "")
    sep = "\t" if "\t" in first and "," not in first else ";" if ";" in first and "," not in first else None
    if sep is None:
        return table
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    for row in csv.reader(io.StringIO(str(table).replace("\r\n", "\n")), delimiter=sep):
        w.writerow([c.strip().replace(",", ".") if sep == ";" and DEC_COMMA.match(c) else c for c in row])
    return out.getvalue().rstrip("\n")


XLSX_MAX = 40_000_000     # the most bytes a workbook may unpack to: a small file that unpacks without end is refused


def xlsx_to_csv(data: bytes) -> str:
    """The first sheet of a spreadsheet workbook (.xlsx) as comma text (L26: a one-step import), read with the standard
    library: shared strings, inline strings and numbers, each cell put in its own column by its reference (B3)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        if sum(i.file_size for i in z.infolist()) > XLSX_MAX:
            raise Refusal(413, too_big())
        names = z.namelist()
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ElementTree.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
        sheets = sorted((n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)), key=lambda n: int(re.sub(r"\D", "", n)))
        if not sheets:
            raise ValueError("no sheet")
        rows: list[list[str]] = []
        for r in ElementTree.fromstring(z.read(sheets[0])).iter("{%s}row" % ns["m"]):
            row: list[str] = []
            for c in r.findall("m:c", ns):
                ref = re.match(r"([A-Z]+)", c.get("r") or "")
                col = 0
                for ch in (ref.group(1) if ref else ""):
                    col = col * 26 + ord(ch) - 64
                col = col - 1 if col else len(row)
                kind, v = c.get("t"), c.find("m:v", ns)
                text = ("".join(t.text or "" for t in c.iter("{%s}t" % ns["m"])) if kind == "inlineStr"
                        else shared[int(v.text)] if kind == "s" and v is not None and (v.text or "").isdigit() and int(v.text) < len(shared)
                        else (v.text or "") if v is not None else "")
                row += [""] * (col + 1 - len(row))
                row[col] = text
            rows.append(row)
    except Refusal:
        raise
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError, ValueError):
        raise Refusal(400, {"error": "I could not read this spreadsheet. Please save it as a comma separated file and choose it again."}) from None
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(r for r in rows if any(x.strip() for x in r))
    return out.getvalue().rstrip("\n")


# ---- the run -----------------------------------------------------------------------------------------------------------
_slots = threading.BoundedSemaphore(int(CONF["runs_at_once"]))
KEPT = "I kept your file in the box; try a shorter one."


def too_big() -> dict:
    return {"error": f"Your file is too big. The limit is {int(CONF['max_rows']):,} rows. {KEPT}"}


MISMATCH = "This tool's program does not match its release."


def mismatch() -> dict:
    return {"error": MISMATCH}


def refuse_unless_ready() -> None:
    """Before every run (F1e): no program file is the not-ready answer; a file whose sha256 is not released.json's is
    refused with MISMATCH. Both are 503."""
    if not program_path().is_file():
        raise Refusal(503, not_ready())
    if not ready():
        raise Refusal(503, mismatch())


def not_ready() -> dict:
    return {"error": "I cannot check files yet, because the program for this tool has not passed the test that decides "
                     "it works. Please try again later."}


def inputs(body: dict) -> tuple[str, str, str, float]:
    """The four inputs, read and checked before anything runs: (table, column, rule, limit). Raises Refusal 400 or 413."""
    table, column, rule, limit = body.get("table"), body.get("column"), body.get("rule"), body.get("limit")
    if not isinstance(table, str) or not table.strip():
        raise Refusal(400, {"error": "Your file is empty, so I have nothing to check yet. Choose a file or paste a table, then press Check my data."})
    table = normalize(table)                       # a tab or semicolon file is read as the comma file it holds (L26)
    if not isinstance(rule, str) or rule not in RULES:   # a crafted rule is data, never code: only the two words pass (L42)
        raise Refusal(400, {"error": "I need to know whether the values must stay above or below the limit. Please choose one, then press Check my data."})
    try:
        lim = float(limit) if not isinstance(limit, bool) else math.nan
    except (TypeError, ValueError):
        lim = math.nan
    if not math.isfinite(lim):
        raise Refusal(400, {"error": "I need the limit as a number, such as 1.4, before I can check your file. Please type it, then press Check my data."})
    names, n = columns(table)
    if n > int(CONF["max_rows"]):
        raise Refusal(413, too_big())
    if not isinstance(column, str) or column not in names:
        raise Refusal(400, {"error": no_column(column, names)})
    if n == 0:
        raise Refusal(400, {"error": "Your file has a header but no rows under it, so I have nothing to check. Please add rows, then press Check my data."})
    # a whole limit goes to the program as a whole number, so its sentence prints it as given: 3, not 3.0 (SPEC2)
    return table, column, rule, (int(lim) if lim.is_integer() and abs(lim) < 2**53 else lim)


def run_program(table: str, column: str, rule: str, limit: float) -> dict:
    """The reader and the released program in a folder of their own, as the checker runs a test: the program's answer."""
    refuse_unless_ready()
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
_mem: dict = {}            # allowances not written: keyed hash of the runs id (or of the address) -> record, this process only
_salt = secrets.token_bytes(16)
MEM = ("run:", "addr:")    # the keys held only in _mem


def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def _prune(kind: str, keep: int) -> None:
    files = list(valley._dir(kind).glob("*.json"))
    if len(files) > keep + 50:
        for f in sorted(files, key=lambda f: f.stat().st_mtime)[:len(files) - keep]:
            f.unlink(missing_ok=True)


def address_key(address: str) -> str:
    return "addr:" + hashlib.sha256(_salt + str(address).encode()).hexdigest()[:24]


def runs_key(runs: str) -> str:
    return "run:" + hashlib.sha256(_salt + b"runs|" + str(runs).encode()).hexdigest()[:24]


def _key(browser, address: str, runs=None) -> str:
    """Whose free runs these are: a browser that said yes to being counted, by its id; else the browser by the random runs
    id its page keeps for the allowance alone (pricing: "5 free a day, in each browser"), held only in memory; else (a
    caller that sends neither, such as the connector or a form with no script) the address."""
    if isinstance(browser, str) and ID.fullmatch(browser):
        return browser
    if isinstance(runs, str) and ID.fullmatch(runs):
        return runs_key(runs)
    return address_key(address)


def _rec(key: str) -> dict:
    if key.startswith(MEM):
        if key not in _mem and len(_mem) > 50_000:
            _mem.clear()                             # a day's worth at most: the oldest go together
        return _mem.setdefault(key, {"day": _today(), "used": 0, "paid_left": 0})
    return valley._safe_load(BROWSERS, key) or {"id": key, "day": _today(), "used": 0, "paid_left": 0,
                                                 "first": None, "days": [], "exhausted": False, "paid": False}


def _keep(key: str, rec: dict) -> None:
    if key.startswith(MEM):
        _mem[key] = rec
        return
    valley._save(BROWSERS, key, rec, chain=False)
    _prune(BROWSERS, int(CONF["browsers_kept"]))


def _fresh(rec: dict) -> dict:
    if rec.get("day") != _today():
        rec.update(day=_today(), used=0)
    return rec


def _left(rec: dict) -> tuple[int, int]:
    """(free, paid): free is today's free runs left plus the extra free runs an invite or a return gave (L23, L25)."""
    return (max(0, int(CONF["free_runs_a_day"]) - int(rec.get("used") or 0)) + max(0, int(rec.get("bonus") or 0)),
            max(0, int(rec.get("paid_left") or 0)))


def _daily_left(rec: dict) -> int:
    return max(0, int(CONF["free_runs_a_day"]) - int(rec.get("used") or 0))


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


def _count(x) -> int:
    return int(x) if isinstance(x, int) and not isinstance(x, bool) and x >= 0 else 0


def _rows(x) -> list[int]:
    """The program's "unchecked": the row numbers with no number (test_limit3.py), each a whole number from 1."""
    return [int(r) for r in x if isinstance(r, int) and not isinstance(r, bool) and r >= 1] if isinstance(x, list) else []


def failing(got: dict, rule: str, limit: float) -> list[list[int]] | None:
    """Every row that fails, as [first, last] runs of row numbers, worked out on the server from the program's own answer
    (the program is never changed): the data rows numbered from 1, its "unchecked" rows skipped, its "values" in file
    order, each held to the rule and the limit as the program holds them. None when the answer cannot be read so, or
    when the first run does not start at the program's first failing row (F1B)."""
    vals, skip, ffr = got.get("values"), set(_rows(got.get("unchecked"))), got.get("first_failing_row")
    if not isinstance(vals, list) or not isinstance(ffr, int) or isinstance(ffr, bool):
        return None
    out: list[list[int]] = []
    row = 0
    for v in vals:
        row += 1
        while row in skip:
            row += 1
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
            return None
        if fails(float(v), rule, limit):
            if out and out[-1][1] == row - 1:
                out[-1][1] = row
            else:
                out.append([row, row])
    return out if out and out[0][0] == ffr else None


def _hash_key(k: str) -> str:
    return hashlib.sha256(b"knos-result-key|" + str(k).encode()).hexdigest()


def owns(rec: dict, k) -> bool:
    """Whether k is the result's own key (L17, L42): a result's key goes only to the browser whose run made it."""
    return bool(isinstance(k, str) and KEY.fullmatch(k) and rec.get("owner") and secrets.compare_digest(rec["owner"], _hash_key(k)))


def save_result(table: str, column: str, rule: str, limit: float, got: dict, sample_run: bool, owner: str = "") -> dict:
    rid = secrets.token_urlsafe(9)                     # 12 characters: never a 16-hex demand result's id
    while re.fullmatch(r"[0-9a-f]{12}", rid):          # nor a referral code (/r/<12 hex>, valley.make_referral)
        rid = secrets.token_urlsafe(9)
    ffr = got.get("first_failing_row")
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rec = {"id": rid, "tool": TOOL_ID, "mode": "sample" if sample_run else "own", "at": at, "created_at": at,
           "tool_version": tool_version(), "test_sha256": test_sha256(), "owner": owner, "opens": 0,
           "column": column, "rule": rule, "limit": limit, "result": str(got["result"]),
           "first_failing_row": int(ffr) if isinstance(ffr, int) and not isinstance(ffr, bool) else None,
           "passed": _count(got.get("passed")), "unchecked": _rows(got.get("unchecked")),
           "chart": chart(got.get("values") or [], rule, limit), "failing": failing(got, rule, limit)}
    rec["verdict"] = tool_page.verdict_of(rec)         # fail at a failing row, pass when a row passed, else unknown
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
            "passed": rec.get("passed"), "unchecked": rec.get("unchecked", []), "failing": rec.get("failing"), "verdict": tool_page.verdict_of(rec),
            "program_result": rec.get("program_result") or rec["result"], "shown_by": SHOWN_BY, "link": f"{base}/r/{rec['id']}/",
            "column": rec["column"], "rule": rec["rule"], "limit": rec["limit"], "chart": rec.get("chart"),
            "input": sample() if rec["mode"] == "sample" else rec.get("input", ""),
            "lines": rec.get("lines"), "cut": rec.get("cut", False), "shown_lines": rec.get("shown_lines"),
            # the exact version that answered (L19): a result from another version says so on its page
            "tool_version": rec.get("tool_version") or "", "test_sha256": rec.get("test_sha256") or "",
            "created_at": rec.get("created_at") or rec.get("at"), "older": (rec.get("tool_version") or "") != tool_version(),
            "opens": int(rec.get("opens") or 0)}


ANSWER = ("result", "first_failing_row", "passed", "unchecked", "shown_by", "link")


def run(body: dict, address: str, base: str = PUBLIC, test: bool = False, connector: bool = False) -> dict:
    """One run of a tool: the answer /api/run and the connector's run give. Raises Refusal (400, 402, 408, 413, 500, 503)."""
    if str(body.get("id") or "") != TOOL_ID:
        raise Refusal(404, {"error": f"I do not have a tool called \"{str(body.get('id'))[:40]}\". The tool I have is {TOOL_ID}: ask for it by that name."})
    table, column, rule, limit = inputs(body)
    refuse_unless_ready()
    sample_run = is_sample(table)
    key, rec, took = None, None, None
    if not sample_run:
        key = _key(body.get("browser"), address, body.get("runs"))
        with _lock:
            rec = _fresh(_rec(key))
            free, paid = _left(rec)
            if free == 0 and paid == 0:
                rec["exhausted"] = True
                _keep(key, rec)
                raise Refusal(402, pay_offer())
            took = "free" if _daily_left(rec) else "bonus" if free else "paid"
            if took == "free":
                rec["used"] = int(rec.get("used") or 0) + 1
            elif took == "bonus":
                rec["bonus"] = int(rec.get("bonus") or 0) - 1
            else:
                rec["paid_left"] = paid - 1
            _keep(key, rec)
    t0 = time.monotonic()
    try:
        got = run_program(table, column, rule, limit)
        cost_record(time.monotonic() - t0, True, test)
    except Refusal:
        cost_record(time.monotonic() - t0, False, test)
        bump("runs_failed", test)
        if key:                                          # nothing was checked: the run goes back
            with _lock:
                rec = _fresh(_rec(key))
                if took == "free":
                    rec["used"] = max(0, int(rec.get("used") or 0) - 1)
                elif took == "bonus":
                    rec["bonus"] = int(rec.get("bonus") or 0) + 1
                else:
                    rec["paid_left"] = int(rec.get("paid_left") or 0) + 1
                _keep(key, rec)
        raise
    own_key = secrets.token_urlsafe(18)                 # the result's own key, given to this caller alone (L17, L42)
    saved = save_result(table, column, rule, limit, got, sample_run, owner=_hash_key(own_key))
    out = {k: v for k, v in shape(saved, base).items() if k in ANSWER + ("failing", "id", "mode", "chart", "column", "rule", "limit", "verdict",
                                                                          "tool_version", "test_sha256", "created_at")}
    out["key"] = own_key
    out["limits"] = limits()
    if key and not sample_run and isinstance(body.get("invite"), str):
        invited(body["invite"], key)
    if sample_run:
        out.update(runs_left=None, free_left=None, paid_left=None)
    else:
        with _lock:
            rec = _fresh(_rec(key))
            free, paid = _left(rec)
            if not key.startswith(MEM):
                today = _today()
                rec["test"] = bool(rec.get("test") or test)
                rec["first"] = rec.get("first") or today
                first = dt.date.fromisoformat(rec["first"])
                if (dt.date.fromisoformat(today) - first).days <= 7 and today not in rec["days"]:
                    rec["days"].append(today)
                seen = rec.setdefault("seen", [])          # every day with an own run, the last 120 (L36, L37)
                if today not in seen:
                    rec["seen"] = (seen + [today])[-120:]
                if free == 0:
                    rec["exhausted"] = True
            _keep(key, rec)
        out.update(runs_left=free + paid, free_left=free, paid_left=paid)
    bump("connector_runs" if connector else "sample_runs" if sample_run else "own_runs", test)   # R2: the connector apart
    return out


def pay(body: dict, address: str, test: bool = False) -> dict:
    """A test payment for one browser: 20 more runs, one record per press id (R3: one record per key and payload). A repeat
    of the press with the same payload gets the same answer and records nothing; a different payload on the same press id
    is refused with 409 and records nothing."""
    press = body.get("press")
    if not isinstance(press, str) or not ID.fullmatch(press):
        raise Refusal(400, {"error": "I could not record this test payment because the press had no id. Nothing was charged. Please press Pay with test money again."})
    key = _key(body.get("browser"), address, body.get("runs"))
    pid = hashlib.sha256(f"press|{press}".encode()).hexdigest()[:32]
    if body.get("check") is True:                       # an unclear outcome is read before any retry (L12): never a payment
        seen = valley._safe_load(PRESSES, pid)
        return {"status": "recorded" if seen and not seen.get("undone") else "undone" if seen else "none",
                **({"runs_left": seen["answer"].get("runs_left")} if seen and not seen.get("undone") else {})}
    # a payment asking for more than the one pack is refused before anything is recorded (L42: no spend past the cap)
    if ("amount" in body and str(body["amount"]).lstrip("US$ ") != str(CONF["pack_price"]).lstrip("US$ ")) or \
            ("pack_runs" in body and body["pack_runs"] != int(CONF["pack_runs"])):
        raise Refusal(400, {"error": f"I record only one pack of {CONF['pack_runs']} runs for {CONF['pack_price']} in test money, so I "
                                     "recorded nothing. Nothing was charged."})
    payload = hashlib.sha256(json.dumps({"who": key, "body": {k: v for k, v in body.items() if k not in ("press", "undo", "check")}},
                                        sort_keys=True, default=str).encode()).hexdigest()
    if body.get("undo") is True:
        return undo(pid, key, payload, test)
    with _lock:
        seen = valley._safe_load(PRESSES, pid)
        if seen:
            if seen.get("payload", payload) != payload:
                raise Refusal(409, {"error": "I already recorded a different test payment under this press, so I did not record "
                                             "this one. Nothing was charged. Please press Pay with test money again to start a new one."})
            return seen["answer"]
        rec = _fresh(_rec(key))
        rec["paid_left"] = int(rec.get("paid_left") or 0) + int(CONF["pack_runs"])
        rec["payments"] = int(rec.get("payments") or (1 if rec.get("paid") else 0)) + 1
        rec["paid"] = True
        _keep(key, rec)
        free, paid = _left(rec)
        answer = {"runs_left": free + paid, "recorded": "test"}
        valley._save(PRESSES, pid, {"answer": answer, "payload": payload, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, chain=False)
        _prune(PRESSES, 5_000)
    bump("test_payments", test)
    return answer


def undo(pid: str, key: str, payload: str, test: bool = False) -> dict:
    """Undo of one test payment (U6 Rule 22): its runs are taken back while none of them is used; the same browser and
    body as the payment are required (the payload hash), and a second undo gets the first answer."""
    with _lock:
        seen = valley._safe_load(PRESSES, pid)
        if not seen or seen.get("payload") != payload:
            raise Refusal(404, {"error": "I have no test payment from this browser under this press, so there is nothing to undo. Nothing was charged."})
        if seen.get("undone"):
            return seen["undone"]
        rec = _fresh(_rec(key))
        runs = int(CONF["pack_runs"])
        if int(rec.get("paid_left") or 0) < runs:
            raise Refusal(409, {"error": "I could not undo the test payment, because some of its runs are already used. Nothing was charged."})
        rec["paid_left"] = int(rec["paid_left"]) - runs
        rec["payments"] = max(0, int(rec.get("payments") or 1) - 1)
        rec["paid"] = rec["payments"] > 0
        _keep(key, rec)
        free, paid = _left(rec)
        answer = {"runs_left": free + paid, "undone": True}
        seen["undone"] = answer
        valley._save(PRESSES, pid, seen, chain=False)
    bump("test_payments_undone", test)
    return answer


VITALS = ("lcp", "inp", "cls")
SCREENS = ("door", "tool", "result", "price", "status")     # the five screens that send their speed
DEVICES = ("phone", "desktop")


def first_action(body: dict, test: bool = False) -> dict:
    """The analytics event first_action (U3 Rule 11): whether a browser's first press of Check my data ran the sample as it
    stood (starter), a table typed into the box (typed), or one pasted or chosen from a file (pasted). The browser keeps it
    and sends it once, only after its person said yes to being counted (its random id is required and not kept); it is
    one count on the day's row, first_<source>."""
    if body.get("event") != "first_action" or body.get("source") not in FIRST:
        raise Refusal(400, {"error": "I count a first action only as starter, typed or pasted, so I counted nothing."})
    if not (isinstance(body.get("browser"), str) and ID.fullmatch(body["browser"])):
        raise Refusal(400, {"error": "I count first actions only from browsers whose person said yes to being counted, so I counted nothing."})
    bump("first_" + body["source"], test)
    return {"counted": True}


def vitals(body: dict, test: bool = False) -> dict:
    """One page's speed as a visitor's browser measured it (U1 R13), sent only from a browser that said yes to being
    counted (its random id is required and not kept): per UTC day and screen, the count and up to 500 values of each."""
    if not (isinstance(body.get("browser"), str) and ID.fullmatch(body["browser"])):
        raise Refusal(400, {"error": "I keep speed measures only from browsers whose person said yes to being counted, so I kept nothing."})
    screen = body.get("screen")
    if screen not in SCREENS:
        raise Refusal(400, {"error": "I keep speed measures only for the front door, the tool, result, price and status pages, so I kept nothing."})
    got = {}
    for k, top in (("lcp", 120_000), ("inp", 60_000), ("cls", 100)):
        x = body.get(k)
        if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and 0 <= x <= top:
            got[k] = round(float(x), 3)
    try:
        with _lock:
            doc = valley._safe_load("pages", USAGE) or {"since": _today(), "days": {}, "test_days": {}}
            days = doc.setdefault("test_vitals" if test else "vitals", {})
            row = days.setdefault(_today(), {}).setdefault(screen, {"n": 0, **{k: [] for k in VITALS}})
            row["n"] += 1
            for k, x in got.items():
                if len(row[k]) < 500:
                    row[k].append(x)
            # phones and desktops apart (L40): the page says which it is from its own screen and pointer, never from an id
            dev = body.get("device") if body.get("device") in DEVICES else None
            if dev:
                d = row.setdefault("by_device", {}).setdefault(dev, {"n": 0, **{k: [] for k in VITALS}})
                d["n"] += 1
                for k, x in got.items():
                    if len(d[k]) < 500:
                        d[k].append(x)
            cut = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=120)).isoformat()
            for d in [d for d in days if d < cut]:
                del days[d]
            valley._save("pages", USAGE, doc, chain=False)
    except Exception as why:  # noqa: BLE001
        print(f"knos tool vitals: not kept: {type(why).__name__}: {str(why)[:120]}", flush=True)
    return {"kept": True}


def _p75(xs: list) -> float | None:
    return sorted(xs)[max(0, math.ceil(0.75 * len(xs)) - 1)] if xs else None


def percentile(xs: list, q: float = 75) -> float | None:
    """The q-th percentile by linear interpolation between ranks (numpy.percentile's default), None for no values."""
    s = sorted(float(x) for x in xs)
    if not s:
        return None
    pos = (len(s) - 1) * q / 100
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (pos - lo), 4)


GOOD = {"lcp": 2500, "inp": 200, "cls": 0.1}     # good at the 75th percentile: LCP 2.5 s, INP 200 ms, CLS 0.1 (L40)


def field_speed(days: int = 28, doc: dict | None = None) -> dict:
    """Real visitors' speed at the 75th percentile over the last `days` UTC days, phones and desktops apart (L40), with
    whether each is inside good; "no field data yet" for a class with no values."""
    doc = doc if doc is not None else (valley._safe_load("pages", USAGE) or {})
    cut = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=days - 1)).isoformat()
    vals: dict = {d: {k: [] for k in VITALS} for d in DEVICES}
    for day, screens in (doc.get("vitals") or {}).items():
        if day < cut:
            continue
        for row in screens.values():
            for dev, r in (row.get("by_device") or {}).items():
                if dev in vals:
                    for k in VITALS:
                        vals[dev][k] += [x for x in r.get(k) or [] if isinstance(x, (int, float))]
    out = {}
    for dev, v in vals.items():
        if not any(v.values()):
            out[dev] = {"status": "no field data yet"}
            continue
        p = {k: percentile(v[k]) for k in VITALS}
        out[dev] = {**{f"{k}_p75": p[k] for k in VITALS}, **{f"{k}_n": len(v[k]) for k in VITALS},
                    "good": all(p[k] is None or p[k] <= GOOD[k] for k in VITALS)}
    return {"days": days, "by_device": out, "good_at_p75": GOOD}


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


# ---- L36, L37: the status page's lead and depth, from real records only ----------------------------------------------------
LEAD_DEFINED = {
    "source": "own-data runs of browsers that said yes to being counted, Knos's own test browsers left out (tool-browsers "
              "records: the first day and every day with a run); the visit beacon's first views for the splits and minutes",
    "first_result_7d": "browsers whose first own run with a result was in the last 7 UTC days, today included",
    "activation_7d": "not measured: a visit id resets every day and a counted browser's id is not sent with its visits, so "
                     "no record links a new visit to a result days later",
    "dau": "browsers with an own run yesterday (the last whole UTC day)",
    "dau_mau": "yesterday's browsers over those with a run in the 30 days to yesterday, browsers first seen 14 or more days "
               "before yesterday, percent",
    "dau_wau": "yesterday's browsers over those with a run in the 7 days to yesterday, percent",
    "return_dN": "of browsers whose first run was N or more days ago, the share with a run on exactly day N, percent",
    "week2_use": "of browsers first seen 14 or more days ago, the share with a run on days 7 to 13, percent",
    "zero": "every value is null (not known) while no real record exists; a share is null while its group is empty",
}
DEPTH_DEFINED = {
    "core_users": "browsers with 7 or more days with a run in the last 30",
    "resurrected": "browsers first seen 14 or more days ago with a run in the last 7 days and none in the 7 before",
    "active_days_28": "browsers with a run in the last 28 days on fewer than 4 of them",
    "week4_active": "of browsers first seen 28 or more days ago, the share with a run on days 21 to 27, percent",
    "minutes_to_result": "median minutes from a new browser's first view (0 days since its first visit) to its first result that day",
    "run_success": "runs that gave a verdict over every run the program started, last 28 days, percent",
    "by_language": "results by the screen's language, last 28 days", "by_device": "results by phone or desktop, last 28 days",
    "by_region": "results by the region the browser's time zone names, last 28 days (no IP address is read)",
    "invites": "invite links made, and new browsers that ran a check from one",
    "arrival_source": "not measured: the beacon sends no referrer",
    "shared_opens": "results by how many times another browser opened them",
    "l7": "browsers with a run in the last 7 days, by how many of the 7 days had one",
}


def _days_of(b: dict) -> set:
    return {dt.date.fromisoformat(d) for d in set(b.get("seen") or []) | set(b.get("days") or [])}


def _pct(a: int, b: int) -> float | None:
    return round(100 * a / b, 1) if b else None


def lead_depth(today: dt.date | None = None, rows: list | None = None) -> tuple[dict, dict]:
    """The L36 lead and the browser half of the L37 depth from the counted browsers' records."""
    day = today or dt.datetime.now(dt.timezone.utc).date()
    if rows is None:
        rows = [b for b in valley._all(BROWSERS) if b.get("first") and not b.get("test")]
    lead = {k: None for k in ("first_result_7d", "activation_7d", "dau", "dau_mau", "dau_wau", "return_d1", "return_d3",
                              "return_d7", "return_d14", "return_d30", "week2_use")}
    depth = {k: None for k in ("core_users", "resurrected", "active_days_28", "week4_active", "invites", "shared_opens", "l7", "run_success")}
    if not rows:
        return lead, depth
    br = [(dt.date.fromisoformat(b["first"]), _days_of(b)) for b in rows]
    yday = day - dt.timedelta(days=1)
    within = lambda ds, lo, hi: {d for d in ds if lo <= d <= hi}   # noqa: E731
    lead["first_result_7d"] = sum(1 for f, _ in br if 0 <= (day - f).days <= 6)
    lead["dau"] = sum(1 for _, ds in br if yday in ds)
    old = [(f, ds) for f, ds in br if (yday - f).days >= 14]
    lead["dau_mau"] = _pct(sum(1 for _, ds in old if yday in ds), sum(1 for _, ds in old if within(ds, yday - dt.timedelta(days=29), yday)))
    lead["dau_wau"] = _pct(lead["dau"], sum(1 for _, ds in br if within(ds, yday - dt.timedelta(days=6), yday)))
    for n in (1, 3, 7, 14, 30):
        cohort = [(f, ds) for f, ds in br if (day - f).days >= n]
        lead[f"return_d{n}"] = _pct(sum(1 for f, ds in cohort if f + dt.timedelta(days=n) in ds), len(cohort))
    c14 = [(f, ds) for f, ds in br if (day - f).days >= 14]
    lead["week2_use"] = _pct(sum(1 for f, ds in c14 if within(ds, f + dt.timedelta(days=7), f + dt.timedelta(days=13))), len(c14))
    last = lambda ds, n: within(ds, day - dt.timedelta(days=n - 1), day)   # noqa: E731
    depth["core_users"] = sum(1 for _, ds in br if len(last(ds, 30)) >= 7)
    depth["resurrected"] = sum(1 for f, ds in br if (day - f).days >= 14 and last(ds, 7)
                               and not within(ds, day - dt.timedelta(days=13), day - dt.timedelta(days=7)))
    depth["active_days_28"] = sum(1 for _, ds in br if 0 < len(last(ds, 28)) < 4)
    c28 = [(f, ds) for f, ds in br if (day - f).days >= 28]
    depth["week4_active"] = _pct(sum(1 for f, ds in c28 if within(ds, f + dt.timedelta(days=21), f + dt.timedelta(days=27))), len(c28))
    l7 = Counter(len(last(ds, 7)) for _, ds in br if last(ds, 7))
    depth["l7"] = {str(k): l7[k] for k in range(1, 8)} if l7 else None
    return lead, depth


def _depth_records(doc: dict) -> dict:
    """The parts of the L37 depth read from the tool's own store: run success, invites, shared results' openings."""
    cut = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=27)).isoformat()
    rows = [r for d, r in (doc.get("days") or {}).items() if d >= cut]
    ok = sum(int(r.get(k) or 0) for r in rows for k in ("sample_runs", "own_runs", "connector_runs"))
    failed = sum(int(r.get("runs_failed") or 0) for r in rows)
    invites = valley._all(INVITES)
    opens = Counter(min(int(r.get("opens") or 0), 3) for r in valley._all(RESULTS) if int(r.get("opens") or 0) > 0)
    return {"run_success": _pct(ok, ok + failed),
            "invites": {"made": len(invites), "joined": sum(int(i.get("joined") or 0) for i in invites)} if invites else None,
            "shared_opens": {("3 or more" if k == 3 else str(k)): n for k, n in sorted(opens.items())} if opens else None}


# ---- L14: what one run costs Knos, from the server's own run records --------------------------------------------------------
COSTS = "tool-costs"
COSTS_KEPT = 1000


def cost_record(seconds: float, ok: bool, test: bool) -> None:
    """One run's record for the cost per run: its program time, its model tokens (this tool calls no model: 0) and
    whether it gave a verdict; the latest COSTS_KEPT runs, failed runs included. Never fails a request."""
    try:
        with _lock:
            doc = valley._safe_load("pages", COSTS) or {"runs": []}
            doc["runs"] = (doc.get("runs") or [])[-(COSTS_KEPT - 1):] + [
                {"s": round(max(0.0, seconds), 4), "tokens_in": 0, "tokens_out": 0, "ok": bool(ok), "test": bool(test), "day": _today()}]
            valley._save("pages", COSTS, doc, chain=False)
    except Exception as why:  # noqa: BLE001
        print(f"knos tool cost: not kept: {type(why).__name__}: {str(why)[:120]}", flush=True)


def cost(doc: dict | None = None) -> dict:
    """The cost per run over the latest runs (failed included): the host's share of each run's program seconds at
    CONF["host_usd_per_month"] plus its model tokens at near_ai.PRICE's dearest model. Null while no run is recorded."""
    runs = (doc if doc is not None else (valley._safe_load("pages", COSTS) or {})).get("runs") or []
    host = CONF.get("host_usd_per_month")
    base = {"runs": len(runs), "host_usd_per_month": host, "host_source": CONF.get("host_usd_per_month_source"),
            "failed": sum(1 for r in runs if not r.get("ok")), "kept": COSTS_KEPT}
    if not runs:
        return {**base, "seconds_per_run": None, "tokens_per_run": None, "usd_per_run": None, "source": "not measured yet: no run recorded"}
    from .near_ai import PRICE
    pin, pout = max(PRICE.values(), key=lambda p: p[0] + p[1])
    secs = sum(float(r.get("s") or 0) for r in runs) / len(runs)
    tin = sum(int(r.get("tokens_in") or 0) for r in runs) / len(runs)
    tout = sum(int(r.get("tokens_out") or 0) for r in runs) / len(runs)
    usd = None if host is None else secs * float(host) / (30 * 86400) + tin * pin + tout * pout
    return {**base, "seconds_per_run": round(secs, 4), "tokens_per_run": round(tin + tout, 1),
            "usd_per_run": None if usd is None else round(usd, 8),
            "source": f"apps/wanted tool_run.py: the latest {len(runs)} runs' program time and model tokens, failed runs included"}


def usage() -> dict:
    doc = valley._safe_load("pages", USAGE) or {"since": None, "days": {}, "test_days": {}}
    speed = {d: {s: {"n": r.get("n", 0), **{f"{k}_p75": _p75(r.get(k) or []) for k in VITALS}} for s, r in row.items()}
             for d, row in (doc.get("vitals") or {}).items()}
    from . import visits
    lead, depth = lead_depth()
    depth.update(_depth_records(doc))
    try:
        depth.update(visits.depth())
    except Exception:  # noqa: BLE001 - the visit side unread: its parts stay not known
        depth.update({k: None for k in ("by_language", "by_device", "by_region", "minutes_to_result")})
    depth["arrival_source"] = None
    return {"days": doc.get("days") or {}, "test_days": doc.get("test_days") or {}, "measures": measures(), "vitals": speed,
            "field_speed": field_speed(doc=doc),
            "lead": lead, "depth": depth, "survey": visits.survey_counts(), "cost": cost(),
            "lead_defined": LEAD_DEFINED, "depth_defined": DEPTH_DEFINED,
            "tool_counts_since": doc.get("since"),
            "tool_counted": "per UTC day. tools_opened: GET /t/<id>/ and GET /api/tools; sample_runs and own_runs: runs not through /mcp that "
                            "returned a result; results_opened_elsewhere: GET /r/<id>/ with no referrer or one from another "
                            "site; link_previews: the same from a link-preview robot or a command-line client; test_payments: "
                            "test payments recorded; connector_runs: runs through /mcp, sample or own file (never in sample_runs or own_runs). "
                            "test_days: the same counts for requests marked as Knos's own tests or WALK runs. measures: "
                            "own-data runs of browsers that said yes to being counted, test browsers left out. "
                            "test_payments_undone: test payments taken back with Undo. first_starter, first_typed, first_pasted: the "
                            "first press of Check my data of browsers that said yes to being counted, by where the table came from "
                            "(the sample as it stood, typed, or pasted or chosen from a file). vitals: per UTC day and screen, how "
                            "many pages browsers that said yes to being counted measured, and the 75th percentile of their "
                            "largest paint (lcp, ms), slowest press (inp, ms) and layout shift (cls)",
            "tool_store": "the server's disk, which Render empties on every deploy: counts restart from that day"}


# ---- a result's owner: download, delete; anyone with its link: challenge (L06, L13, L17, L42) ------------------------------
def export(rid: str, ext: str, k) -> tuple[int, bytes, str]:
    """A result's download: (status, body, type). A sample's result is open to anyone with its link, as its page is; a
    result from a person's own file only to the browser that ran it, by the result's own key (X-Knos-Key)."""
    from . import exports
    rec = load_result(rid)
    if rec is None:
        return 404, json.dumps({"error": "I have no result at this address. It may have been deleted, or replaced after the server was updated."}).encode(), "application/json"
    if rec["mode"] == "own" and not owns(rec, k):
        return 403, json.dumps({"error": "I give a result from someone's own file only to the browser that checked it, so I sent nothing."}).encode(), "application/json"
    r = {**shape(rec), "tool": rec["tool"]}
    if ext == "csv":
        return 200, exports.tool_csv(r).encode("utf-8"), "text/csv; charset=utf-8"
    return 200, json.dumps(exports.tool_json(r), indent=1, ensure_ascii=False).encode("utf-8"), "application/json"


def delete(rid: str, k) -> dict:
    """The result and its kept table removed from the server now (L17), by the browser that ran it (its key)."""
    rec = load_result(rid)
    if rec is None:
        raise Refusal(404, {"error": "I have no result at this address, so there was nothing to delete."})
    if not owns(rec, k):
        raise Refusal(403, {"error": "Only the browser that checked this file can delete its result, so I deleted nothing."})
    with _lock:
        (valley._dir(RESULTS) / f"{rid}.json").unlink(missing_ok=True)
    return {"deleted": True, "id": rid}


def opened(rid: str) -> None:
    """One more opening of a result by someone else (L25): its maker sees the count on the result's page."""
    with _lock:
        rec = load_result(rid)
        if rec is not None:
            rec["opens"] = int(rec.get("opens") or 0) + 1
            valley._save(RESULTS, rid, rec, chain=False)


CHALLENGE_STATES = ("open", "upheld", "rejected")


def challenge(body: dict) -> dict:
    """A challenge of a result, recorded inside Knos (L13): what the person says is wrong, kept with the result's id;
    its status starts open and is read back at GET /api/challenge/<id>. Nothing that says who sent it is kept."""
    rid = str(body.get("id") or "")
    if load_result(rid) is None:
        raise Refusal(404, {"error": "I have no result at this address, so there is nothing to challenge."})
    why = str(body.get("why") or "").strip()[:500]
    if len(why) < 3:
        raise Refusal(400, {"error": "Please say in a few words what you think is wrong with this result, then send it again."})
    cid = secrets.token_urlsafe(9)
    rec = {"id": cid, "result": rid, "why": why, "status": "open", "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with _lock:
        valley._save(CHALLENGES, cid, rec, chain=False)
        _prune(CHALLENGES, int(CONF["challenges_kept"]))
    return {"challenge": cid, "status": "open", "result": rid}


def challenge_status(cid: str) -> dict | None:
    if not RID.fullmatch(cid or ""):
        return None
    rec = valley._safe_load(CHALLENGES, cid)
    return {k: rec.get(k) for k in ("id", "result", "status", "at")} if rec else None


def invite(body: dict, address: str) -> dict:
    """An invite code for this browser (L25): when a new browser that opened the invite link runs its first check on its
    own file, both browsers get CONF["invite_runs"] more free runs."""
    key = _key(body.get("browser"), address, body.get("runs"))
    code = hashlib.sha256(b"invite|" + key.encode()).hexdigest()[:12]
    with _lock:
        if not valley._safe_load(INVITES, code):
            valley._save(INVITES, code, {"by": key, "joined": 0}, chain=False)
            _prune(INVITES, int(CONF["browsers_kept"]))
    return {"invite": code, "runs_each": int(CONF["invite_runs"])}


def invited(code: str, key: str) -> bool:
    """A new browser's first own run with an invite code: both get the extra free runs, once per new browser, never for
    an invite of one's own."""
    if not re.fullmatch(r"[0-9a-f]{12}", code or ""):
        return False
    with _lock:
        inv = valley._safe_load(INVITES, code)
        rec = _fresh(_rec(key))
        if not inv or inv.get("by") == key or rec.get("invited_by"):
            return False
        n = int(CONF["invite_runs"])
        rec["invited_by"], rec["bonus"] = code, int(rec.get("bonus") or 0) + n
        _keep(key, rec)
        them = _fresh(_rec(inv["by"]))
        them["bonus"] = int(them.get("bonus") or 0) + n
        _keep(inv["by"], them)
        inv["joined"] = int(inv.get("joined") or 0) + 1
        valley._save(INVITES, code, inv, chain=False)
    return True


def bonus(body: dict, address: str) -> dict:
    """A small return bonus after a missed day (L23): CONF["return_bonus_runs"] more free runs, at most once a UTC day
    for one browser; never a guilt message, never a notification."""
    if body.get("why") != "return":
        raise Refusal(400, {"error": "I give extra runs only for coming back after a missed day, so I gave none."})
    key = _key(body.get("browser"), address, body.get("runs"))
    with _lock:
        rec = _fresh(_rec(key))
        if rec.get("bonus_day") != _today():
            rec["bonus_day"] = _today()
            rec["bonus"] = int(rec.get("bonus") or 0) + int(CONF["return_bonus_runs"])
            _keep(key, rec)
        free, paid = _left(rec)
    return {"runs_left": free + paid, "free_left": free, "bonus": int(CONF["return_bonus_runs"])}


def convert(body: dict) -> dict:
    """A spreadsheet (.xlsx, sent as base64) as the comma text the box takes (L26)."""
    try:
        data = base64.b64decode(str(body.get("xlsx") or ""), validate=True)
    except ValueError:
        raise Refusal(400, {"error": "I could not read this spreadsheet. Please save it as a comma separated file and choose it again."}) from None
    table = xlsx_to_csv(data)
    if columns(table)[1] > int(CONF["max_rows"]):
        raise Refusal(413, too_big())
    return {"table": table}


# ---- routes --------------------------------------------------------------------------------------------------------------
def _marked(h, qs=None, body=None) -> bool:
    return h.headers.get("X-Knos-Test") == "1" or (qs or {}).get("test", [""])[0] == "1" or bool(isinstance(body, dict) and body.get("test") is True)


def _base(h) -> str:
    from . import tasks
    return tasks.public_base(h._base())


def _lite(h) -> bool:
    """The browser asks to save data (Save-Data: on): the tool and result pages come without their script (U7 R25)."""
    return (h.headers.get("Save-Data") or "").strip().lower() == "on"


def _html(h, code: int, text: str, cache: str = "no-store", lang: str = "en", keep: bool = False) -> None:
    # the page's language follows ?lang= or Accept-Language (U7 R17) and its weight Save-Data (U7 R25), so a cache keeps
    # one copy per language and per mode; `keep` marks a page the offline worker (OFFLINE_SW) may keep for a visit with no
    # network: a tool page or a sample's result, never a result from a person's own file, never the lighter copy
    h._send(code, text.encode("utf-8"), "text/html; charset=utf-8", {"Cache-Control": cache, "Vary": "Accept-Language, Save-Data", "Content-Language": lang,
                                                                     **({"X-Knos-Offline": "keep"} if keep and not _lite(h) else {})})


# The tool and result pages with no network (LAWS UX U7.md R24): after one visit, a tool page or a sample's result opened
# offline shows the page kept from that visit, not the browser's error page. The pages register it with the scope /t/ or
# /r/. Network first; a page is kept only when the server marks it (X-Knos-Offline: keep), so a result from a person's
# own file, an answer of /api/ and every other address are never kept. The copy of the page being opened is fetched
# once at install with X-Knos-Offline-Copy, which no count takes.
OFFLINE_SW = r"""const KEPT = "knos-tool-v1";
const keep = (req, got) => got && got.ok && got.headers.get("X-Knos-Offline") === "keep" ? caches.open(KEPT).then((c) => c.put(req, got.clone())) : null;
self.addEventListener("install", (e) => {
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((cs) => Promise.all(cs.map((c) => c.url)
    .filter((u) => u.startsWith(self.registration.scope)).map((u) => fetch(u, { headers: { "X-Knos-Offline-Copy": "1" }, credentials: "same-origin" })
      .then((got) => keep(new Request(u), got)).catch(() => null)))).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(Promise.all([
    caches.keys().then((ks) => Promise.all(ks.filter((k) => k.startsWith("knos-tool-") && k !== KEPT).map((k) => caches.delete(k)))),
  ]).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const r = e.request;
  if (r.method !== "GET" || r.mode !== "navigate" || new URL(r.url).origin !== self.location.origin) return;
  e.respondWith((async () => {
    try {
      const got = await fetch(r);
      const k = keep(r, got); if (k) e.waitUntil(k);
      return got;
    } catch (err) {
      const kept = await caches.match(r, { ignoreVary: true });   // the copy is in the language it was opened in
      if (kept) return kept;
      throw err;
    }
  })());
});
"""


def _lang(h, qs) -> str:
    """The language of a tool or result page: ?lang=, else the browser's Accept-Language, else English (H3 a)."""
    return tool_page.pick((qs or {}).get("lang", [""])[0], h.headers.get("Accept-Language"))


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
    if p == "/tool-sw.js":
        return h._send(200, OFFLINE_SW.encode("utf-8"), "text/javascript; charset=utf-8", {"Cache-Control": "no-cache"}) or True
    if p == "/api/tools":
        bump("tools_opened", _marked(h, qs))
        return h._send(200, tools_doc(), headers={"Cache-Control": "no-store"}) or True
    m = re.fullmatch(r"/api/run/([A-Za-z0-9_-]{12})\.(csv|json)", p)
    if m:                                                 # L06: the result, its inputs and its evidence, no account
        code, data, ctype = export(m.group(1), m.group(2), h.headers.get("X-Knos-Key"))
        extra = {"Content-Disposition": f'attachment; filename="knos-{m.group(1)}.{m.group(2)}"'} if code == 200 else {}
        return h._send(code, data, ctype, extra) or True
    m = re.fullmatch(r"/api/challenge/([A-Za-z0-9_-]{12})", p)
    if m:
        got = challenge_status(m.group(1))
        return h._send(200 if got else 404, got or {"error": "I have no challenge at this address."}) or True
    if p == "/api/remind.ics":                            # L23: the daily reminder, built from the person's own answer
        from . import remind
        try:
            body = remind.ics(qs.get("at", [""])[0], qs.get("cue", [""])[0], _base(h) + f"/t/{TOOL_ID}/")
        except ValueError as why:
            return h._send(400, {"error": str(why)}) or True
        return h._send(200, body.encode("utf-8"), "text/calendar; charset=utf-8",
                       {"Content-Disposition": 'attachment; filename="knos-daily-check.ics"'}) or True
    if p == "/api/today":                                 # L24: today's short list, never more than five
        from . import today
        return h._send(200, today.today_list(), headers={"Cache-Control": "public, max-age=600"}) or True
    if p == "/api/sources":                               # L10: each source with its checked passage and date
        from . import sources
        return h._send(200, sources.summary(), headers={"Cache-Control": "public, max-age=600"}) or True
    m = re.fullmatch(r"/t/([a-z0-9-]{1,40})(/?)", p)
    if m:
        t = tool(m.group(1))
        if t is None:
            return _html(h, 404, tool_page.missing(FRONT, _lang(h, qs)), lang=_lang(h, qs)) or True
        if not m.group(2):
            return h._send(301, b"", "text/plain", {"Location": f"/t/{t['id']}/" + (f"?{u.query}" if u.query else "")}) or True
        if not h.headers.get("X-Knos-Offline-Copy"):                 # the offline worker's copy is not a visit
            bump("tools_opened", _marked(h, qs))
        return _html(h, 200, tool_page.page(t, _base(h), front=FRONT, lang=_lang(h, qs), test=_marked(h, qs), lite=_lite(h),
                                          sample=(qs.get("sample") or [""])[0] == "1"), lang=_lang(h, qs), keep=True) or True
    m = re.fullmatch(r"/r/([A-Za-z0-9_-]{12})/(mark|qr\.png|print)", p)
    if m:                                                # H3 c and d: knos_wanted.result_extras
        from . import result_extras as rx
        rec = load_result(m.group(1))
        if rec is None:
            return _html(h, 404, tool_page.missing(FRONT)) or True
        url, title, line = rx.address(_base(h), rec["id"]), (tool(rec["tool"]) or {}).get("title", TITLE), first_sentence(rec["result"])
        if m.group(2) == "mark":
            return h._send(200, rx.mark(title, line, url).encode("utf-8"), "text/html; charset=utf-8", rx.MARK_HEADERS) or True
        if m.group(2) == "print":
            return h._send(200, rx.print_page(title, line, url, f"/r/{rec['id']}/qr.png").encode("utf-8"),
                           "text/html; charset=utf-8", rx.PRINT_HEADERS) or True
        return h._send(200, rx.qr_png(url), "image/png", rx.QR_HEADERS) or True
    m = re.fullmatch(r"/r/([A-Za-z0-9_-]{12})(/?)", p)
    if m:
        rec = load_result(m.group(1))
        if rec is None and not m.group(2) and _referral(m.group(1)):
            return False                                 # /r/<code> with no slash: a referral link (product_routes)
        if rec is None:
            return _html(h, 404, tool_page.missing(FRONT, _lang(h, qs)), lang=_lang(h, qs)) or True
        if not m.group(2):
            return h._send(301, b"", "text/plain", {"Location": f"/r/{rec['id']}/" + (f"?{u.query}" if u.query else "")}) or True
        why = _elsewhere(h)
        if why and not h.headers.get("X-Knos-Offline-Copy"):          # the offline worker's copy is not an opening
            bump(why, _marked(h, qs))
        return _html(h, 200, tool_page.page(tool(rec["tool"]) or tool(TOOL_ID), _base(h), shape(rec, _base(h)), front=FRONT,
                                            lang=_lang(h, qs), test=_marked(h, qs), lite=_lite(h)), lang=_lang(h, qs), keep=rec["mode"] == "sample") or True
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
    # every other /r/ address: a demand result's page or download (16 hex, server.py) or a referral link that exists
    # (product_routes) is served there; anything else is the same plain Not found page, never a raw error
    if p.startswith("/r/") and not re.fullmatch(r"/r/[0-9a-f]{16}(?:\.(?:pdf|csv|json))?", p) and not _referral(p[3:]):
        return _html(h, 404, tool_page.missing(FRONT, _lang(h, qs)), lang=_lang(h, qs)) or True
    return False


def _referral(code: str) -> bool:
    """Whether code is a referral link's code this server holds (valley.make_referral: 12 hex)."""
    return bool(re.fullmatch(r"[0-9a-f]{12}", code or "")) and valley._safe_load("referrals", code) is not None


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


def _form_limit(s) -> str:
    """The limit as typed into the form, read as the page's script reads it: spaces dropped, one comma a decimal mark."""
    x = str(s or "").strip().replace(" ", "")
    return x.replace(",", ".") if "." not in x and x.count(",") == 1 else x


def _refused_html(lang: str, code: int, body: dict, sent: dict) -> str:
    """Why a form run was not run, in the page's language (the same lines the page's script shows), as a cannot-tell
    answer; the person's table, column, rule and limit stay in the form."""
    T = tool_page.t
    names = columns(sent.get("table") or "")[0]
    if code == 400:
        msg = (T(lang, "err.empty") if not str(sent.get("table") or "").strip()
               else T(lang, "err.column", column=tool_page.column_shown(lang, sent.get("column") or ""), names=", ".join(names)) if sent.get("column") not in names
               else T(lang, "err.limit") if _num(_form_limit(sent.get("limit"))) is None else T(lang, "err.bad"))
    elif code == 402:
        f = tool_page.facts()
        msg = T(lang, "pay.headline", n=f["runs"], price=f["price"]) + " " + T(lang, "pay.line")
    else:
        msg = {413: T(lang, "err.too_big", n=int(CONF["max_rows"])), 408: T(lang, "err.too_long", n=max_seconds()),
               503: MISMATCH if body.get("error") == MISMATCH else T(lang, "err.not_ready")}.get(code) or T(lang, "err.none")
    return (f'<div class="answer" data-verdict data-state="unknown">{tool_page.icon(lang, "unknown")}'
            f'<p class="bad" role="alert" data-answer data-reason>{tool_page._e(msg)}</p></div>')


def form_run(h, state, tid: str) -> bool:
    """POST /t/<id>/run: the tool's form sent by a browser with no script. A result: 303 to its page. Not run: the tool
    page again with what was sent and why. Runs on your own file count against the same free runs as the site's."""
    from urllib.parse import parse_qs, urlencode
    t = tool(tid)
    if t is None:
        return _html(h, 404, tool_page.missing(FRONT, _lang(h, {})), lang=_lang(h, {})) or True
    n = int(h.headers.get("Content-Length") or 0)
    raw = h.rfile.read(min(n, int(CONF["max_body_bytes"]) + 1)) if n > 0 else b""
    f = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True).items()}
    lang = tool_page.pick(f.get("lang"), h.headers.get("Accept-Language"))
    test = f.get("test") == "1" or h.headers.get("X-Knos-Test") == "1"
    lim = _form_limit(f.get("limit"))
    # a result page's box is offered empty (U6 Rule 2); sent empty from there, Check my data checks that result's table again
    rid = str(f.get("again") or "")
    again = load_result(rid) if re.fullmatch(r"[A-Za-z0-9_-]{12}", rid) and not str(f.get("table") or "").strip() else None
    if again:
        f["table"], f["column"] = shape(again)["input"], again["column"]
    # the tool page's box is offered empty, the sample shown in it as an example (G5); sent empty from there, untouched,
    # Check my data checks that example, as the page's script does
    elif f.get("sample") == "1" and not str(f.get("table") or "").strip():
        f["table"], f["column"] = t["sample"], t["column"]
    # the sample as the box shows it, its header in plain words (tool_page.sample_shown, F1B), is the sample as the file has it
    elif t["sample"] and lines_of(str(f.get("table") or "")) == lines_of(tool_page.sample_shown(lang, t["sample"])):
        f["table"] = t["sample"]
        if f.get("column") in ("", tool_page.column_shown(lang, t["column"])):
            f["column"] = t["column"]
    sent = {"table": str(f.get("table") or "").replace("\r\n", "\n"), "column": str(f.get("column") or ""),
            "rule": f.get("rule") if f.get("rule") in RULES else "", "limit": str(f.get("limit") or "")}
    try:
        if n > int(CONF["max_body_bytes"]):
            raise Refusal(413, too_big())
        if not state.allow(h._client(), "tool"):
            raise Refusal(429, {})
        got = run({"id": tid, "table": sent["table"], "column": sent["column"], "rule": sent["rule"], "limit": lim, "browser": ""},
                  h._client(), _base(h), test)
    except Refusal as r:
        sent["error_html"] = _refused_html(lang, r.code, r.body, sent)
        return _html(h, r.code, tool_page.page(t, _base(h), front=FRONT, lang=lang, test=test, sent=sent, lite=_lite(h)), lang=lang) or True
    q = urlencode([(k, v) for k, v in (("lang", f.get("lang") or ""), ("test", "1" if test else "")) if v])
    return h._send(303, b"", "text/plain", {"Location": f"/r/{got['id']}/" + (f"?{q}" if q else "")}) or True


def handle_post(h, state, path: str) -> bool:
    m = re.fullmatch(r"/t/([a-z0-9-]{1,40})/run", path)
    if m:
        return form_run(h, state, m.group(1))
    if path not in ("/api/run", "/api/pay", "/api/vitals", "/api/first_action", "/api/challenge", "/api/invite", "/api/bonus",
                    "/api/convert", "/api/opened"):
        return False
    if not state.allow(h._client(), "tool" if path in ("/api/run", "/api/convert") else "tool_pay"):
        return h._send(429, {"error": "I have had a great many requests from your network in the last few minutes. Please wait a minute and try again."}) or True
    try:
        body = _body(h)
        test = _marked(h, None, body)
        if path == "/api/run":
            return h._send(200, run(body, h._client(), _base(h), test)) or True
        if path == "/api/vitals":
            return h._send(200, vitals(body, test)) or True
        if path == "/api/first_action":
            return h._send(200, first_action(body, test)) or True
        if path == "/api/challenge":
            return h._send(200, challenge(body)) or True
        if path == "/api/invite":
            return h._send(200, invite(body, h._client())) or True
        if path == "/api/bonus":
            return h._send(200, bonus(body, h._client())) or True
        if path == "/api/convert":
            return h._send(200, convert(body)) or True
        if path == "/api/opened":                         # L25: another browser opened a shared result (its page sends it once)
            rid = str(body.get("id") or "")
            if load_result(rid) is None:
                raise Refusal(404, {"error": "I have no result at this address."})
            if not test:
                opened(rid)
            return h._send(200, {"counted": not test}) or True
        return h._send(200, pay(body, h._client(), test)) or True
    except Refusal as r:
        return h._send(r.code, r.body) or True


def handle_delete(h, state, path: str) -> bool:
    """DELETE /api/run/<id> with the result's own key (X-Knos-Key): the result is gone from the server at once (L17)."""
    m = re.fullmatch(r"/api/run/([A-Za-z0-9_-]{12})", path)
    if not m:
        return False
    if not state.allow(h._client(), "tool_pay"):
        return h._send(429, {"error": "I have had a great many requests from your network in the last few minutes. Please wait a minute and try again."}) or True
    try:
        return h._send(200, delete(m.group(1), h.headers.get("X-Knos-Key"))) or True
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
                    "Returns the result sentence, the first failing row, the rows passed, the rows not checked, the test that "
                    "showed the program works, and the result's link.",
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string", "enum": [TOOL_ID], "description": "the tool's id"},
         "table": {"type": "string", "maxLength": int(CONF["max_body_bytes"]), "description": "the file as text, comma separated"},
         "column": {"type": "string", "description": "a column name from the file's header, or \"column 1\", \"column 2\" and so on when it has none"},
         "rule": {"type": "string", "enum": list(RULES), "description": "whether the values must stay above or below the limit"},
         # a number, or the number as text ("1.4"), exactly as POST /api/run takes it (Round 13 item B5)
         "limit": {"type": ["number", "string"], "description": "the limit, such as 1.4 or \"1.4\"; a value equal to it fails"}},
         "required": ["id", "table", "column", "rule", "limit"], "additionalProperties": False}},
]


def mcp_call(name: str, args: dict) -> dict:
    """The connector's answer, the same JSON as the site's routes. A refusal raises ValueError with its message."""
    from . import outside, usage
    if name == "tools":
        return tools_doc()
    headers = getattr(outside.CTX, "headers", None)
    test = bool(headers is not None and headers.get("X-Knos-Test") == "1")
    who = usage.current_visitor() or "connector"
    try:
        got = run({k: args.get(k) for k in ("id", "table", "column", "rule", "limit")}, "mcp:" + who, PUBLIC, test, connector=True)
    except Refusal as r:
        if r.code == 402:
            o = r.body["pay"]
            raise ValueError(f"Today's {CONF['free_runs_a_day']} free runs on your own files are used. {o['headline']}: "
                             f"{o['line']} Pay on the Knos site: {PUBLIC}/t/{TOOL_ID}/") from None
        raise ValueError(r.body.get("error") or "the run did not finish") from None
    return {k: got[k] for k in ANSWER}
