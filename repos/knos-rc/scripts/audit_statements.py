"""The site's order statements: for each organisation, each month's audit lines, as web/statements.js reads them.

    files(events, owner_ids) -> {"audit/<owner id>.json": text}     for scripts/pages_data.py, beside statements/<login>.json
    python scripts/audit_statements.py --out _site --owner 5001 [--owner ...]     reads the escrow's history from the cluster

One file per organisation: {"type": "knos.audit-statement", "version": 1, "owner_id", "months": {"2026-09": {"scope", "lines"}}}.
`scope` is knos.audit.scope_of(owner, first day, last day) and `lines` is knos.audit.lines(events, owner, (), first day,
last day): exactly what `knos audit export --owner <id> --from <first day> --to <last day>` chains and writes. The
page chains and writes them itself (web/statements.js: auditExport), so its CSV and JSON are the bytes that command
prints, and the head is the one hash both parties compare. A month is listed when it has at least one line. A month
that is not over yet says what was true when the file was written; its head changes until the month ends.

From 0.3.16 the lines are those of version 2 of the audit export (`scope.version` says so): the organisation's bounties
on issues are among them (`record` is `bounty`), and every line has `source`, `terms_version`, `paid_each` and
`held_until`. web/finance_data.js chains and writes version 2 (and version 1 as it was), shapes each deliverable into
its four linked objects and writes the finance systems' import files; an owner whose money only ever funded bounties
has lines here too, so whoever lists the owners (scripts/pages_data.py) must count the funders of bounties.
"""
from __future__ import annotations

import argparse
import calendar
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from knos import audit  # noqa: E402

TYPE, VERSION = "knos.audit-statement", 1


def months_of(events: list[dict]) -> list[str]:
    """Every month from the first event to the last, as "2026-09"."""
    if not events:
        return []
    a, b = (time.gmtime(min(e["at"] for e in events)), time.gmtime(max(e["at"] for e in events)))
    return [f"{y:04d}-{m:02d}" for y in range(a.tm_year, b.tm_year + 1) for m in range(1, 13) if (a.tm_year, a.tm_mon) <= (y, m) <= (b.tm_year, b.tm_mon)]


def statement(events: list[dict], owner_id: int, partial: bool = False) -> dict:
    out = {}
    for month in months_of(events):
        y, m = int(month[:4]), int(month[5:])
        first, last = f"{month}-01", f"{month}-{calendar.monthrange(y, m)[1]:02d}"
        lines = audit.lines(events, owner_id, (), first, last)
        if lines:
            out[month] = {"scope": audit.scope_of(owner_id, first, last, (), partial), "lines": lines}
    return {"type": TYPE, "version": VERSION, "owner_id": int(owner_id), "months": out}


def files(events: list[dict], owner_ids, partial: bool = False) -> dict[str, str]:
    return {f"audit/{int(o)}.json": json.dumps(statement(events, int(o), partial), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
            for o in sorted({int(o) for o in owner_ids})}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--owner", action="append", type=int, default=[], help="a GitHub organisation or user id (repeat for several)")
    ap.add_argument("--limit", type=int, default=1000)
    args = ap.parse_args()
    from knos import cli
    got = cli._history(args.limit)
    for path, text in files(got.events, args.owner, bool(got.unread or 2 in got.cut)).items():
        (Path(args.out) / path).parent.mkdir(parents=True, exist_ok=True)
        (Path(args.out) / path).write_text(text, encoding="utf-8", newline="")
