"""Every latency or throughput figure in a document says its sample size, its program ids and its date.

    python scripts/rate_claims.py                       # the documents in CHECKED; exit 1 on a figure that does not
    python scripts/rate_claims.py docs/X.md README.md   # any others

A wait or a rate printed alone hides what it is of: a run on staging ids read as one on the public ids, 44 payments
that worked read as all of them, a reading of last week read as today's. So a block (a paragraph, a list item, or a
table with the paragraph just above it) that states a latency or a throughput must carry, in itself or in the headings
above it:

    a sample size    `n`, "N payments", "N of M", "N orders", "N tokens", "N decisions", "N transactions", ...
    its ids          "public program id(s)", "staging program id(s)", "program ids not recorded" (said, not left out),
                     or where it ran without a cluster: "local
                     simulator", "LiteSVM", "no network", "one machine"
    its date         2026-10-07, or 7 October 2026, or 7 Oct 2026

A latency is a time (s, ms, seconds) beside a percentile word (p50, p95, p99, median, worst, slowest, percentile)
or beside "merge to paid"; a throughput is a count per second ("a second", "per second", "/s"). A figure the block
marks as derived, a target or a limit is arithmetic or a promise, not a measurement, and is exempt: it has no sample.
Code (between backticks) and HTML comments are not read.

`check(text)` is the rule, for any checker that wants it (scripts/truth_check.py can call it on every page).
tests/test_rate_claims.py plants each failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKED = ("docs/LOAD.md", "docs/BENCH.md")
# Figures in a block another script writes, waiting for its owner: {document: {the figure as check() reports it: the
# hook}}. A figure leaves this list when its block says what it lacks; tests/test_rate_claims.py fails on one that is
# fixed and still listed.
PENDING: dict[str, dict[str, str]] = {}

TIME = r"\d[\d,.]*\s?(?:ms|s|seconds?)\b"
LATENCY = re.compile(rf"(?:\b(?:p50|p95|p99|median|worst|slowest|percentile)\b.{{0,120}}?{TIME}|{TIME}.{{0,80}}?\b(?:p50|p95|p99|median|worst|slowest)\b"
                     rf"|merge[- ]to[- ]paid.{{0,80}}?{TIME})", re.I)
RATE = re.compile(r"\d[\d,.]*(?!th\b)\s?(?:[a-z ]{0,40}?)\b(?:a|per) second\b(?! time)|\d[\d,.]*\s?(?:confirmed|orders|payments|transactions)?/s\b", re.I)
SAMPLE = re.compile(r"(?:\|\s*n\s*\||\bn\s*=\s*\d|\bn\b\)?\s*\||\b\d[\d,]*\s+of\s+\d[\d,]*\b|\b\d[\d,]*\s+(?:real\s+)?(?:payments?|orders?|tokens?|decisions?|"
                    r"transactions?|samples?|runs?|attempts?|relays?|processes)\b|\bover\s+\d[\d,]*\b)", re.I)
IDS = re.compile(r"\b(?:public|staging)\s+program\s+ids?\b|\bprogram ids not recorded\b|\blocal simulator\b|\bLiteSVM\b|\bno network\b|\b(?:one|this) machine\b", re.I)
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
DATE = re.compile(rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b|\b\d{{1,2}}\s+(?:{MONTHS})\.?\s+\d{{4}}\b")
EXEMPT = re.compile(r"\bderived\b|\btargets?\b|\bceilings?\b|\blimits?\b.{0,40}\bpublished\b", re.I)


OPEN, END = "\x01open", "\x01end"


def _plain(text: str) -> str:
    """The text a reader reads: code spans out, HTML comments out (a marker that opens a generated block becomes OPEN,
    one that closes it END; every other comment keeps only its line breaks, so line numbers hold)."""
    def comment(m: re.Match) -> str:
        body = m.group(1).strip()
        if "\n" not in body and re.fullmatch(r"/?[\w:.-]+", body):
            return END if body.startswith("/") or body.endswith(":end") else OPEN
        return "\n" * m.group(0).count("\n")
    text = re.sub(r"<!--(.*?)-->", comment, text, flags=re.S)
    return re.sub(r"`[^`\n]*`", " ", text)


def blocks(text: str) -> list[tuple[int, str, str, str]]:
    """[(first line number, the block, its context, its own heading)]: a paragraph, a list item or a table. Its context
    is the headings above it, the lead (the first paragraph after its heading, or after the marker that opens the
    generated block it is in: where a section says what run it reports), and for a table the paragraph just above it."""
    lines = _plain(text).split("\n")
    out: list[tuple[int, str, str, str]] = []
    heads: dict[int, str] = {}
    cur: list[str] = []
    start, before, lead, want_lead = 0, "", "", True

    def flush() -> None:
        nonlocal cur, before, lead, want_lead
        if cur:
            body = "\n".join(cur)
            table = cur[0].lstrip().startswith("|")
            out.append((start + 1, body, " ".join(heads[k] for k in sorted(heads)) + " " + lead + (" " + before if table else ""),
                        heads[max(heads)] if heads else ""))
            if want_lead and not table:
                lead, want_lead = body, False
            before = "" if table else body
        cur = []

    for i, line in enumerate(lines):
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if h or line.strip() in (OPEN, END):
            flush()
            if h:
                level = len(h.group(1))
                heads = {k: v for k, v in heads.items() if k < level}
                heads[level] = h.group(2)
            before, lead, want_lead = "", "", line.strip() != END
            continue
        if not line.strip():
            flush()
            continue
        starts_item = bool(re.match(r"^\s*(?:[-*]|\d+\.)\s", line))
        if cur and (starts_item or line.lstrip().startswith("|") != cur[0].lstrip().startswith("|")):
            flush()
        if not cur:
            start = i
        cur.append(line)
    flush()
    return out


def _units(block: str) -> list[str]:
    """A table is read row by row (the header row gives the columns' names to each); anything else as one unit."""
    rows = [r for r in block.split("\n") if r.lstrip().startswith("|")]
    if len(rows) >= 2 and len(rows) == len(block.split("\n")):
        head = rows[0]
        return [head + " " + r for r in rows[2:]] or [head]
    return [block]


def check(text: str) -> list[dict]:
    """Every latency or throughput figure whose block lacks its sample size, its ids or its date:
    [{line, figure, missing: [...]}]."""
    bad = []
    for line, block, context, own in blocks(text):
        for unit in _units(block):
            hit = LATENCY.search(unit) or RATE.search(unit)
            if not hit:
                continue
            whole = unit + " " + context + " " + (block if unit != block else "")
            if EXEMPT.search(unit) or re.search(r"\(derived\)", own):
                continue
            missing = [name for name, rx in (("sample size", SAMPLE), ("program ids", IDS), ("date", DATE)) if not rx.search(whole)]
            if missing:
                bad.append({"line": line, "figure": hit.group(0)[:80], "missing": missing})
    return bad


def main(argv: list[str] | None = None) -> int:
    paths = [Path(p) for p in (argv if argv is not None else sys.argv[1:])] or [ROOT / p for p in CHECKED]
    failed = 0
    for path in paths:
        seen = set()
        rel = path.resolve().relative_to(ROOT).as_posix() if path.resolve().is_relative_to(ROOT) else str(path)
        for b in check(path.read_text(encoding="utf-8")):
            if (b["line"], tuple(b["missing"])) in seen:
                continue
            if b["figure"] in PENDING.get(rel, {}):
                print(f"{path}:{b['line']}: pending: {PENDING[rel][b['figure']]}")
                continue
            seen.add((b["line"], tuple(b["missing"])))
            failed += 1
            print(f"{path}:{b['line']}: \"{b['figure']}\" has no {', no '.join(b['missing'])}")
    print(f"rate_claims: {failed} figure{'' if failed == 1 else 's'} without a sample size, ids or date" if failed else "rate_claims: every figure has its sample size, ids and date")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
