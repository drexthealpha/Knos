"""Shadow mode: `knos shadow <invoice.csv|.json>`. One question about an invoice that bills per merged change: which
of these billed changes had a failed check when they were merged?

It reads, and only reads. Nothing is written to GitHub, nothing is paid, nothing is held, and the supplier is asked
for nothing: for a public repository everything it needs is public, and for a private one the buyer's own read token
is enough (`--token-env`).

For each line of the invoice it asks GitHub for the pull request (merged or not, its merge commit, its last commit),
for every check run and commit status at that last commit, which is the code that was merged, and, when the
description claims nothing, for the commits' messages. The readers are the free claim check's (knos.terms.head_checks
and knos.terms.pages behind knos.proof.ghrelay.Hub, whose every GET is conditional); what counts as a claim of passing
tests and what counts as a failed check are the Agent PR Index's (scripts/agent_pr_ci.py: `find_claim`, FAIL_CONCL,
OK_CONCL and AGENT_RUN_RE are copied here word for word and tests/test_shadow.py holds the two together); which issue
a pull request closes is knos.closing's.

Each line ends in exactly one class:

    clean        merged; a check passed, none failed, none is unfinished
    failed       merged with a failed check; each is named with a link to its run
    unverified   merged, and GitHub's record gives no verdict: no check ran, one has not finished, or none passed
    not_merged   the pull request is not merged
    duplicate    the same pull request as an earlier line, or it closes an issue an earlier merged line closes
    unreadable   GitHub could not be read for it (rate limit, private without a token): counted apart, never guessed

The amount in dispute is what the failed, not merged and duplicate lines bill. The statement is one canonical JSON
(sorted keys, no spaces, a final newline) and one CSV, the same bytes for the same invoice and the same answers from
GitHub, and its sha256 lets both sides confirm they hold the same one. web/shadow.js writes the same bytes in a
browser (tests/web/shadow.mjs, against tests/data/shadow_cases.json, which this module wrote).

A failed check at merge is not proof the work is bad, and a green check is not proof it is good: NOTE says so in every
statement.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from . import closing, terms
from .proof import ghrelay

KIND, VERSION = "knos-shadow-statement", 1
NOTE = ("A failed check at merge is not proof the work is bad, and a green check is not proof it is good. "
        "Shadow mode changes nothing and holds no money.")
CLASSES = ("clean", "failed", "unverified", "not_merged", "duplicate", "unreadable")
DISPUTED = ("failed", "not_merged", "duplicate")
LABELS = {"clean": "verified clean", "failed": "failed check at merge", "unverified": "no verdict from checks",
          "not_merged": "not merged", "duplicate": "billed twice", "unreadable": "could not be read"}
ALIASES = {"pr": ("pr", "pull_request", "url", "change"), "amount": ("amount", "price", "total"), "supplier": ("supplier", "vendor")}
RESUME = "shadow.resume.json"
_BLANK = " \t\r\n\u00a0\ufeff"       # what is trimmed from a cell: the same characters in web/shadow.js
_URL = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/pull/(\d{1,10})", re.I | re.A)
_SHORT = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d{1,10})$", re.A)
_AMOUNT = re.compile(r"^(-?)([1-9]\d{0,2}(?:[.,]\d{3})+|\d+)(?:[.,](\d{1,2}))?$", re.A)

# ---- the Agent PR Index's reading of a description and of a commit's checks (scripts/agent_pr_ci.py, word for word) ----
_PASS = r"(?:pass(?:es|ed|ing)?|green)"
CLAIM_RE = re.compile(
    r"(?:\ball\s+(?:\w+\s+){0,2}tests?\s+(?:are\s+|now\s+)*" + _PASS +
    r"|\btests?\s+(?:are\s+|now\s+|still\s+)*" + _PASS + r"\b" +
    r"|\btests?\b[^\n.]{0,40}?\band\s+passing\b" +
    r"|\bCI\b(?:[\s:/,]+(?:is|are|now|run|runs|job|jobs|checks?|build|pipeline|workflows?|all|CD|#?\d+))*[\s:,]+"
    + _PASS + r"\b" +
    r"|\b(?:all\s+(?:CI\s+)?checks?|(?:CI\s+)?checks)\s+(?:are\s+|have\s+)?" + _PASS + r"\b" +
    r"|\bpass(?:es|ed|ing)?\s+all\s+(?:\w+\s+){0,2}(?:tests|checks|CI)\b" +
    r"|`[^`\n]*test[^`\n]*`\s*(?:[-:—]\s*)?(?:all\s+)?" + _PASS + r"\b" +
    r"|\b\d[\d,]*\s*(?:/\s*\d[\d,]*\s*)?(?:\w+\s+){0,2}passed\b" +
    r"|✅\s*[^\n]{0,40}?\btests?\b"
    r"|\btests?\b[^\n]{0,30}?✅)", re.I)
NONCLAIM_RE = re.compile(
    r"^[ \t]*(?:>[ \t]*)*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)+\[ \](?:[ \t]|$)|"
    r"\b(ensure|make sure|verify that|should|would|will|to confirm|until|"
    r"once|if|before|whether|need|needs|must|expect|expected|todo|not|"
    r"fail|fails|failing|failed|failure|failures|errors?|except|unless|pending|flaky|skip|"
    r"red|broken)\b|n't\b", re.I)
_BOILER_RE = re.compile(r"\*\*Your PR cannot be merged unless tests pass\*\*|"
                        r"\bfail[- ](?:closed|safe|fast|open)\b|\b0 failed\b", re.I)
AGENT_RUN_RE = re.compile(
    r"^(copilot|claude|claude[-_ ]?(code|review|code[-_ ]review|pr[-_ ]review)|codex|devin)$", re.I)
FAIL_CONCL = {"failure", "timed_out", "startup_failure"}
OK_CONCL = {"success", "neutral", "skipped"}


def strip_body(body) -> str:
    b = body or ""
    b = re.sub(r"<!--.*?-->", " ", b, flags=re.S)
    return re.sub(r"<details>\s*<summary>[^<]*(original prompt|original issue)[^<]*</summary>.*?</details>", " ", b, flags=re.S | re.I)


def find_claim(body) -> tuple[str | None, str | None]:
    """(the words that claim passing tests or green CI, their line), or (None, None): the Index's own reading."""
    for line in strip_body(body).splitlines():
        m = CLAIM_RE.search(line)
        if not m:
            continue
        if NONCLAIM_RE.search(_BOILER_RE.sub(" ", line)):
            continue
        return m.group(0).strip(), line.strip()[:200]
    return None, None


# ---- the invoice ---------------------------------------------------------------------------------------------------

def _cells(text: str) -> list[list[str]]:
    """A CSV's rows: a byte order mark is dropped, the separator is the first line's (semicolon or tab when it holds
    more of them than commas), a quoted cell may hold the separator, a line break and a doubled quote. Rows with
    nothing in them are left out, and so are rows that start with "#": a note to the reader, not a line."""
    text = text[1:] if text.startswith("\ufeff") else text
    first = next((line for line in text.split("\n") if not line.strip(_BLANK).startswith("#")), "")
    sep = ";" if first.count(";") > first.count(",") else "\t" if first.count("\t") > first.count(",") else ","
    rows, row, cell, quoted, i, n = [], [], "", False, 0, len(text)
    while i < n:
        c = text[i]
        if quoted:
            if c == '"' and text[i + 1:i + 2] == '"':
                cell += '"'
                i += 1
            elif c == '"':
                quoted = False
            else:
                cell += c
        elif c == '"' and not cell.strip(_BLANK):
            cell, quoted = "", True
        elif c == sep:
            row.append(cell)
            cell = ""
        elif c == "\n":
            row.append(cell)
            rows.append(row)
            row, cell = [], ""
        elif c != "\r":
            cell += c
        i += 1
    rows.append([*row, cell])
    trimmed = [[c.strip(_BLANK) for c in r] for r in rows]
    return [r for r in trimmed if any(r) and not r[0].startswith("#")]


def _column(name: str) -> str:
    """Which of pr, amount, supplier a header names ("" for none): any case, spaces and dashes as underscores."""
    key = re.sub(r"[ \t-]+", "_", name.strip(_BLANK).lower())
    return next((col for col, names in ALIASES.items() if key in names), "")


def pull_of(text: str) -> tuple[str, int] | None:
    """("owner/repo", number) from a pull request's address or owner/repo#number; None when it names none."""
    m = _URL.search(text or "") or _SHORT.match((text or "").strip(_BLANK))
    return (f"{m.group(1)}/{m.group(2)}", int(m.group(3))) if m else None


def cents(text: str) -> int | None:
    """An amount in hundredths: "1,200.50", "1.200,50", "$1200", "12,5". None for an empty cell. A comma or a point
    followed by one or two digits at the end is the decimal mark; groups of three are thousands. ValueError for
    anything else: an amount is never guessed."""
    t = re.sub(r"[^0-9.,-]", "", text or "")
    if not t:
        if (text or "").strip(_BLANK):
            raise ValueError(text)
        return None
    m = _AMOUNT.match(t)
    if not m:
        raise ValueError(text)
    whole = int(re.sub(r"[.,]", "", m.group(2)))
    value = whole * 100 + int(((m.group(3) or "") + "00")[:2])
    return -value if m.group(1) else value


def money(value: int) -> str:
    """Hundredths as text: 120050 is "1200.50"."""
    return f"{'-' if value < 0 else ''}{abs(value) // 100}.{abs(value) % 100:02d}"


def _text(value) -> str:
    """A JSON value as the cell it would be: a whole number without ".0", nothing for null."""
    if value is None or isinstance(value, (bool, dict, list)):
        return ""
    if isinstance(value, float) and value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return str(value)


def parse(text: str) -> dict:
    """An invoice: {"lines": [{"line", "pr", "repo", "number", "amount", "supplier"}]}. `text` is a CSV (a header with
    any of ALIASES, or none: pull request, amount, supplier in that order) or JSON (a list, or {"lines": [...]}, of
    objects with the same names, or of pull requests as text). A line that names no pull request stays in, with an
    empty `repo`: it is billed, and it cannot be read. ValueError names the line whose amount could not be read."""
    start = text.lstrip(_BLANK)[:1]
    table: list[dict] = []
    if start in ("[", "{"):
        got = json.loads(text.lstrip("\ufeff"))
        items = got.get("lines") if isinstance(got, dict) else got
        if not isinstance(items, list):
            raise ValueError("the invoice's JSON holds no list of lines")
        for item in items:
            row = {"pr": "", "amount": "", "supplier": ""}
            if isinstance(item, dict):
                for name, value in item.items():
                    if _column(str(name)) and not row[_column(str(name))]:
                        row[_column(str(name))] = _text(value).strip(_BLANK)
            else:
                row["pr"] = _text(item).strip(_BLANK)
            table.append(row)
    else:
        rows = _cells(text)
        head = [_column(c) for c in rows[0]] if rows else []
        if "pr" in head:
            rows = rows[1:]
        else:
            head = ["pr", "amount", "supplier"]
        for r in rows:
            row = {"pr": "", "amount": "", "supplier": ""}
            for col, value in zip(head, r):
                if col and not row[col]:
                    row[col] = value
            table.append(row)
    lines = []
    for i, row in enumerate(table, 1):
        named = pull_of(row["pr"])
        try:
            amount = cents(row["amount"])
        except ValueError:
            raise ValueError(f"line {i}: the amount {row['amount']!s} could not be read") from None
        lines.append({"line": i, "pr": f"{named[0]}#{named[1]}" if named else row["pr"], "repo": named[0] if named else "",
                      "number": named[1] if named else 0, "amount": amount, "supplier": row["supplier"]})
    if not lines:
        raise ValueError("the invoice names no line")
    return {"lines": lines}


# ---- GitHub, read only ---------------------------------------------------------------------------------------------

class Unread(Exception):
    """GitHub could not be read for one path. `reason` is one of: rate limit, not found or private, refused,
    no answer, not in the recording."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Reader(ghrelay.Hub):
    """GitHub as shadow mode reads it: the relay's conditional reader (an answer is kept with its ETag and asked for
    again with If-None-Match, and with a token GitHub's 304 costs nothing against the rate limit), with the token the
    caller names and nothing else, and no way to send anything. `settled`: paths whose kept answer is used without
    asking, the lines an earlier run finished (the resume file)."""

    def __init__(self, token: str = "", kept: dict | None = None, settled=(), urlopen=None, clock=time.time):
        super().__init__(urlopen, clock)
        self.token, self.settled, self.asked = token, set(settled), 0
        self.kept.update({path: (etag, answer) for path, (etag, answer) in (kept or {}).items()})

    def _request(self, path: str, data: dict | None = None, method: str | None = None, etag: str | None = None):
        if data is not None or method not in (None, "GET"):
            raise ValueError("shadow mode only reads GitHub")
        req = super()._request(path, etag=etag)
        req.remove_header("Authorization")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        return req

    def send(self, path: str, data: dict, method: str = "POST"):
        raise ValueError("shadow mode only reads GitHub")

    def get(self, path: str):
        if path in self.settled and path in self.kept:
            return self.kept[path][1]
        self.asked += 1
        try:
            return super().get(path)
        except RuntimeError as why:
            said = str(why)
            code = re.search(r"answered (\d{3}) ", said)
            limited = self.rest > self._clock()
            raise Unread("rate limit" if limited else "not found or private" if code and code.group(1) == "404"
                         else "refused" if code and code.group(1) in ("401", "403") else "no answer") from None


def recorded(book: dict):
    """A reader over answers written down earlier: {path: answer}, or {path: {"__unread": reason}} for one GitHub did
    not give. No network."""
    def get(path: str):
        if path not in book:
            raise Unread("not in the recording")
        got = book[path]
        if isinstance(got, dict) and "__unread" in got:
            raise Unread(str(got["__unread"]))
        return got
    return get


EVIDENCE = "evidence.json"


def keeping(get) -> tuple:
    """(a reader that asks `get` and writes down what it said, the book it writes in). The book is {path: answer}, with
    {"__unread": reason} for a path GitHub did not give: `recorded(book)` answers the same again with no network, which
    is what lets a statement be made again years later (knos.statement)."""
    book: dict = {}

    def kept(path: str):
        try:
            book[path] = get(path)
        except Unread as e:
            book[path] = {"__unread": e.reason}
            raise
        return book[path]
    return kept, book


def evidence(text: str, book: dict) -> bytes:
    """The evidence file of one run: the invoice as it was given and every answer that was read, in canonical JSON."""
    return (json.dumps({"answers": book, "invoice": text}, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8", "surrogatepass")


def read(repo: str, number: int, get) -> dict:
    """What GitHub says about one pull request: {"pull", "runs", "statuses", "commits", "unread", "paths"}. `runs` and
    `statuses` are those of its last commit and are read only when it is merged; `commits` only when its description
    claims nothing. `unread` is why any of it could not be read ("" when all of it was): then nothing of it is used."""
    facts: dict = {"pull": None, "runs": None, "statuses": None, "commits": None, "unread": "", "paths": []}
    why: list[str] = []

    def got(path: str):
        facts["paths"].append(path)
        try:
            return get(path)
        except Unread as e:
            why.append(e.reason)
            raise

    try:
        pull = got(f"repos/{repo}/pulls/{number}")
    except Unread:
        facts["unread"] = why[0]
        return facts
    if not isinstance(pull, dict):
        facts["unread"] = "no answer"
        return facts
    facts["pull"] = pull
    head = str((pull.get("head") or {}).get("sha") or "")
    if not pull.get("merged_at"):
        return facts
    if not head:
        facts["unread"] = "no answer"
        return facts
    facts["runs"], facts["statuses"] = terms.head_checks(repo, head, got)
    if facts["runs"] is not None and facts["statuses"] is not None and not find_claim(pull.get("body"))[0]:
        facts["commits"] = terms.pages(f"repos/{repo}/pulls/{number}/commits", got, cap=3)
        if facts["commits"] is None:
            facts["unread"] = why[0] if why else "cut short"
    if facts["runs"] is None or facts["statuses"] is None:
        facts["unread"] = why[0] if why else "cut short"
    return facts


def gather(invoice: dict, get, each=None) -> dict:
    """`read` for every pull request the invoice names, once each: {"owner/repo#n" in lower case: its facts}.
    `each(line, facts)` is called after every line, for a progress display or a resume file."""
    facts: dict = {}
    for ln in invoice["lines"]:
        key = ln["pr"].lower()
        if ln["repo"] and key not in facts:
            facts[key] = read(ln["repo"], ln["number"], get)
        if each:
            each(ln, facts.get(key))
    return facts


# ---- the statement -------------------------------------------------------------------------------------------------

def _units(text: str) -> bytes:
    return text.encode("utf-16-be", "surrogatepass")     # the order JavaScript sorts text in


def checks_of(runs: list, statuses: list) -> tuple[list[dict], int]:
    """(every check at a commit, how many of the agent's own session runs were left out). One row per check run and
    per commit status: {"name", "kind": run | status, "conclusion": GitHub's word, "state", "url"}, where state is
    failed (the Index's FAIL_CONCL; a status that says failure or error), pending, passed, skipped, or other (a run
    that was cancelled, went stale or waits for someone: no verdict). Sorted by name, then kind, then address."""
    out, own = [], 0
    for r in runs:
        name = str(r.get("name") or "?")
        if AGENT_RUN_RE.match(name.strip()):
            own += 1
            continue
        done, concl = r.get("status") == "completed", str(r.get("conclusion") or "")
        state = ("failed" if concl in FAIL_CONCL else "pending" if not done else "passed" if concl == "success"
                 else "skipped" if concl in OK_CONCL else "other")
        out.append({"name": name, "kind": "run", "conclusion": concl if done or concl else str(r.get("status") or ""), "state": state,
                    "url": str(r.get("html_url") or r.get("details_url") or "")})
    for s in statuses:
        said = str(s.get("state") or "")
        state = "failed" if said in ("failure", "error") else "pending" if said == "pending" else "passed" if said == "success" else "other"
        out.append({"name": str(s.get("context") or "?"), "kind": "status", "conclusion": said, "state": state, "url": str(s.get("target_url") or "")})
    return sorted(out, key=lambda c: (_units(c["name"]), c["kind"], _units(c["url"]))), own


def verdict(checks: list[dict]) -> tuple[str, str]:
    """(clean | failed | unverified, why) from a commit's checks, as the Index classes them."""
    states = [c["state"] for c in checks]
    if "failed" in states:
        return "failed", ""
    if not checks:
        return "unverified", "no check ran"
    if "pending" in states:
        return "unverified", "a check has not finished"
    if "other" in states:
        return "unverified", "a check ended without a verdict"
    if "passed" not in states:
        return "unverified", "no check passed"
    return "clean", ""


def statement(invoice: dict, facts: dict) -> dict:
    """The statement for an invoice (`parse`) and what GitHub said (`gather`). Pure: the same two give the same one."""
    rows: list[dict] = []
    first_pull: dict[str, int] = {}
    first_issue: dict[str, int] = {}
    for ln in invoice["lines"]:
        row = {"line": ln["line"], "pr": ln["pr"], "url": f"https://github.com/{ln['repo']}/pull/{ln['number']}" if ln["repo"] else "",
               "amount": None if ln["amount"] is None else money(ln["amount"]), "supplier": ln["supplier"], "class": "unreadable", "why": "",
               "merged": None, "merged_at": "", "merge_commit": "", "head": "", "claimed": "", "issues": [], "checks": [], "failed": [],
               "agent_runs": 0, "duplicate_of": None}
        rows.append(row)
        key = ln["pr"].lower()
        got = facts.get(key)
        if not ln["repo"]:
            row["why"] = "no pull request named"
        elif key in first_pull:
            row.update({"class": "duplicate", "duplicate_of": first_pull[key], "why": f"same pull request as line {first_pull[key]}"})
        elif got is None or got["unread"] or got["pull"] is None:
            first_pull[key] = ln["line"]
            row["why"] = (got or {}).get("unread") or "no answer"
        else:
            first_pull[key] = ln["line"]
            pull = got["pull"]
            row.update({"merged": bool(pull.get("merged_at")), "merged_at": str(pull.get("merged_at") or ""),
                        "head": str((pull.get("head") or {}).get("sha") or "")})
            if not row["merged"]:
                row["class"] = "not_merged"
                continue
            row["merge_commit"] = str(pull.get("merge_commit_sha") or "")
            home = str(((pull.get("base") or {}).get("repo") or {}).get("full_name") or ln["repo"])
            row["issues"] = [f"{home}#{n}" for n in closing.closed_by(pull)]
            messages = [str(((c or {}).get("commit") or {}).get("message") or "") for c in got["commits"] or []]
            row["claimed"] = "description" if find_claim(pull.get("body"))[0] else "commit" if any(find_claim(m)[0] for m in messages) else ""
            row["checks"], row["agent_runs"] = checks_of(got["runs"], got["statuses"])
            row["failed"] = [{"name": c["name"], "url": c["url"]} for c in row["checks"] if c["state"] == "failed"]
            twice = next((i for i in row["issues"] if i.lower() in first_issue), None)
            if twice:
                row.update({"class": "duplicate", "duplicate_of": first_issue[twice.lower()],
                            "why": f"closes {twice}, as line {first_issue[twice.lower()]} does"})
                continue
            for i in row["issues"]:
                first_issue[i.lower()] = ln["line"]
            row["class"], row["why"] = verdict(row["checks"])
    priced = all(ln["amount"] is not None for ln in invoice["lines"])
    billed = sum(ln["amount"] for ln in invoice["lines"]) if priced else 0
    by_amount = priced and billed > 0
    counts = {c: sum(1 for r in rows if r["class"] == c) for c in CLASSES}
    sums = {c: sum(ln["amount"] for ln, r in zip(invoice["lines"], rows) if r["class"] == c) for c in CLASSES} if by_amount else {}
    part = sum(sums[c] for c in DISPUTED) if by_amount else sum(counts[c] for c in DISPUTED)
    whole = billed if by_amount else len(rows)
    share = max(0, (2 * part * 10000 + whole) // (2 * whole))        # hundredths of a percent, halves up
    names = {r["supplier"] for r in rows if r["supplier"]}
    return {"kind": KIND, "version": VERSION, "note": NOTE, "supplier": names.pop() if len(names) == 1 else "",
            "basis": "amount" if by_amount else "lines", "lines_billed": len(rows), "counts": counts,
            "amounts": {"billed": money(billed), **{c: money(sums[c]) for c in CLASSES}} if by_amount else None,
            "disputed": {"lines": sum(counts[c] for c in DISPUTED), "amount": money(part) if by_amount else None,
                         "share_bp": share, "share": f"{share // 100}.{share % 100:02d}%"},
            "complete": counts["unreadable"] == 0, "lines": rows}


def canonical(st: dict) -> bytes:
    """The statement's bytes: JSON with sorted keys and no spaces, UTF-8, one final newline."""
    return (json.dumps(st, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8", "surrogatepass")


def digest(st: dict) -> str:
    """The sha256 of the statement's bytes: what `sha256sum statement.json` prints."""
    return hashlib.sha256(canonical(st)).hexdigest()


CSV_HEAD = ("line", "pull_request", "url", "supplier", "amount", "class", "why", "merged_at", "merge_commit", "last_commit",
            "claimed_passing", "failed_checks", "failed_check_links", "duplicate_of")


def _cell(value, words: bool = False) -> str:
    """One CSV cell. `words`: text from the invoice or from GitHub, which a spreadsheet must not read as a formula."""
    t = "" if value is None else str(value)
    if words and t[:1] in ("=", "+", "-", "@"):
        t = "'" + t
    return '"' + t.replace('"', '""') + '"' if any(c in t for c in ',"\r\n') else t


def as_csv(st: dict) -> str:
    """The statement as a CSV: one row a line, in the invoice's order."""
    out = [",".join(CSV_HEAD)]
    for r in st["lines"]:
        out.append(",".join([_cell(r["line"]), _cell(r["pr"], True), _cell(r["url"]), _cell(r["supplier"], True), _cell(r["amount"]),
                             _cell(r["class"]), _cell(r["why"], True), _cell(r["merged_at"]), _cell(r["merge_commit"]), _cell(r["head"]),
                             _cell(r["claimed"]), _cell(" | ".join(f["name"] for f in r["failed"]), True),
                             _cell(" | ".join(f["url"] for f in r["failed"]), True), _cell(r["duplicate_of"])]))
    return "\n".join(out) + "\n"


def as_text(st: dict) -> list[str]:
    """The statement in words, for a terminal."""
    by_amount = st["basis"] == "amount"
    out = [f"Shadow statement{' for ' + st['supplier'] if st['supplier'] else ''}: {st['lines_billed']} lines billed"
           + (f", {st['amounts']['billed']}" if by_amount else "")]
    for c in CLASSES:
        out.append(f"  {LABELS[c]:<24}{st['counts'][c]:>5}" + (f"{st['amounts'][c]:>14}" if by_amount else ""))
    d = st["disputed"]
    out.append(f"In dispute: {d['amount'] + ' of ' + st['amounts']['billed'] if by_amount else str(d['lines']) + ' of ' + str(st['lines_billed']) + ' lines'}"
               f" ({d['share']} of the invoice{'' if by_amount else ', by lines: not every line has an amount'})")
    for r in st["lines"]:
        if r["class"] == "failed":
            for f in r["failed"]:
                out.append(f"  line {r['line']} {r['pr']}: failed check {f['name']} {f['url']}".rstrip())
        elif r["class"] != "clean":
            out.append(f"  line {r['line']} {r['pr'] or '(no pull request)'}: {LABELS[r['class']]}{': ' + r['why'] if r['why'] else ''}")
    if not st["complete"]:
        n = st["counts"]["unreadable"]
        out.append(f"{n} {'line' if n == 1 else 'lines'} could not be read and {'is' if n == 1 else 'are'} not judged. Run again later, or with a token: --token-env.")
    out.append(st["note"])
    return out


def write(st: dict, out: Path) -> list[Path]:
    """statement.json (the canonical bytes), statement.csv and statement.sha256 in `out`."""
    out.mkdir(parents=True, exist_ok=True)
    files = [(out / "statement.json", canonical(st)), (out / "statement.csv", as_csv(st).encode("utf-8", "surrogatepass")),
             (out / "statement.sha256", f"{digest(st)}  statement.json\n".encode())]
    for path, data in files:
        path.write_bytes(data)
    return [path for path, _ in files]


def run(text: str, get, out: Path | None = None, reader: Reader | None = None, events: Path | None = None, named: str = "", month: int | str | None = None) -> dict:
    """Parse, read and state. With `out`, evidence.json is written beside the statement (the invoice and
    every answer read); with a live `reader` too, the resume file is written after every line: the kept answers with
    their ETags, and the paths of the lines that were read in full. With `events` (a log of `knos events`) the
    statement's invoice lines and evaluations are also taken into that log, best effort, as invoice `named` of
    `month` (YYYY-MM; this month when it is not given)."""
    invoice = parse(text)

    def each(_ln, facts) -> None:
        if reader is None or out is None:
            return
        if facts and not facts["unread"]:
            reader.settled.update(facts["paths"])
        out.mkdir(parents=True, exist_ok=True)
        kept = {path: [etag, answer] for path, (etag, answer) in sorted(reader.kept.items())}
        (out / RESUME).write_text(json.dumps({"kept": kept, "settled": sorted(reader.settled & set(kept))}, sort_keys=True), encoding="utf-8")

    get, book = keeping(get)
    st = statement(invoice, gather(invoice, get, each))
    if out is not None:
        write(st, out)
        (out / EVIDENCE).write_bytes(evidence(text, book))       # what `knos statement make` and `verify` read: no network needed again
    if events is not None:
        import time

        from . import events as log
        log.keep(events, lambda: log.from_shadow(st, named or "invoice", month or time.strftime("%Y-%m", time.gmtime())))
    return st


def register(app, help_lines: list | None = None) -> None:
    """`knos shadow`, on the main app. `help_lines`: cli._HELP, which gets the command's line."""
    import importlib
    typer = importlib.import_module("typer")       # the command line's package, named here and not imported: the relay reaches this module on an install without it

    if help_lines is not None:
        help_lines.append(("shadow", "For money", "Which lines of a per-change invoice had a failed check at merge? Reads GitHub; changes nothing."))

    @app.command("shadow", rich_help_panel="For money")
    def shadow_(invoice: Path = typer.Argument(..., help="the invoice: a CSV or JSON whose lines name pull requests (an address or owner/repo#number), with an amount and a supplier if it has them"),
                token_env: str = typer.Option("GH_TOKEN", "--token-env", help="the environment variable that holds a GitHub read token (needed for a private repository; without one GitHub answers 60 requests an hour)"),
                out: Path = typer.Option(None, "--out", help="write statement.json, statement.csv and statement.sha256 here, and keep a resume file so a second run asks GitHub only for what is missing"),
                recorded_file: Path = typer.Option(None, "--recorded", help="read GitHub's answers from this file ({path: answer}) and not from the network"),
                refresh: bool = typer.Option(False, "--refresh", help="with --out: ask GitHub again about lines an earlier run finished"),
                as_json: bool = typer.Option(False, "--json", help="print the statement's JSON"),
                events_log: Path = typer.Option(None, "--events", help="also take the invoice's lines and their evaluations into this log of events (`knos events`); default: the file KNOS_EVENTS names, else none"),
                invoice_name: str = typer.Option("", "--invoice", help="with a log of events: the invoice's own number or name (default: the file's name)"),
                month: str = typer.Option(None, "--month", help="with a log of events: the month the invoice belongs to, YYYY-MM (default: this month)")) -> None:
        """Shadow mode: take an invoice that bills per merged change and say which billed changes had a failed check when they were merged, which were not merged, which are billed twice, and which could not be read (those are counted apart, never guessed). Prints the amount in dispute, its share of the invoice and the statement's sha256, so both sides can confirm they hold the same one. It only reads GitHub: nothing is written there, nothing is paid and nothing is held. A failed check at merge is not proof the work is bad, and a green check is not proof it is good."""
        from . import cli
        try:
            text = invoice.read_text(encoding="utf-8-sig")
        except (OSError, ValueError) as why:
            raise cli.Stop(f"{invoice} could not be read: {why}", "Give a CSV or JSON file whose lines name pull requests.") from None
        reader = None
        try:
            if recorded_file:
                get = recorded(json.loads(recorded_file.read_text(encoding="utf-8")))
            else:
                kept: dict = {}
                if out and (out / RESUME).is_file():
                    kept = json.loads((out / RESUME).read_text(encoding="utf-8"))
                reader = Reader(os.environ.get(token_env, ""), kept.get("kept"), () if refresh else kept.get("settled") or ())
                get = reader.get
            from . import events
            st = run(text, get, out, reader, events.where(events_log), invoice_name or invoice.stem, month)
        except ValueError as why:
            raise cli.Stop(f"{invoice}: {why}", "Each line names a pull request; an amount is digits with a point or a comma.") from None
        except OSError as why:
            raise cli.Stop(str(why)) from None
        if as_json:
            typer.echo(canonical(st).decode("utf-8", "replace"), nl=False)
            return
        for line in as_text(st):
            typer.echo(line)
        typer.echo(f"sha256 {digest(st)}")
        if out:
            typer.echo(f"wrote {out / 'statement.json'}, statement.csv, statement.sha256 and {EVIDENCE}")
            typer.echo(f"For accounts payable (a CSV and a PDF with every line's state): knos statement make {out / EVIDENCE}")
        if reader is not None:
            typer.echo(f"GitHub was asked {reader.asked} times ({reader.same} answered unchanged)."
                       + ("" if reader.token else f" No token in ${token_env}: GitHub answers 60 requests an hour without one."))
