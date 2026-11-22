"""Today's short list (L24): at most five claims Knos can check, each with its source and the day it is listed for, a
different set each day, taken in turn from near/claims/claims.json (read only). Never an endless feed: five at most.

    GET /api/today                       today's list (UTC)
    python -m knos_wanted.today --out F  the daily job writes today's list to F (JSON)
    python -m knos_wanted.today --plan 60 the next 60 days' lists, to read the content plan ahead
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("KNOS_NEAR_ROOT") or Path(__file__).resolve().parents[3])
MAX_ITEMS = 5


def claims() -> list[dict]:
    try:
        return json.loads((ROOT / "near" / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"]
    except (OSError, ValueError, KeyError):
        return []


def source_of(c: dict) -> str:
    """The claim's public source: its DOI as a link, else its own address."""
    doi = str(c.get("doi") or "").strip()
    if doi:
        return doi if doi.startswith("http") else "https://doi.org/" + doi
    return str(c.get("url") or c.get("limit_from") or "")


def today_list(day: dt.date | None = None) -> dict:
    """The list for one UTC day: the claims in turn, starting one further along each day, at most MAX_ITEMS."""
    day = day or dt.datetime.now(dt.timezone.utc).date()
    cs = [c for c in claims() if source_of(c) and c.get("name")]
    if not cs:
        return {"date": day.isoformat(), "items": []}
    start = day.toordinal() % len(cs)
    pick = [cs[(start + i) % len(cs)] for i in range(min(MAX_ITEMS, len(cs)))]
    items = [{"claim": c["name"], "line": str(c.get("plain") or c.get("question") or c.get("paper") or ""), "paper": c.get("paper"),
              "source": source_of(c), "date": day.isoformat()} for c in pick]
    return {"date": day.isoformat(), "items": items, "from": "near/claims/claims.json"}


def plan(start: dt.date, days: int = 60) -> list[dict]:
    return [today_list(start + dt.timedelta(days=i)) for i in range(days)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", help="write today's list here")
    ap.add_argument("--plan", type=int, default=0, help="print the next N days' lists")
    a = ap.parse_args(argv)
    if a.plan:
        print(json.dumps(plan(dt.datetime.now(dt.timezone.utc).date(), a.plan), indent=1, ensure_ascii=False))
        return 0
    doc = json.dumps(today_list(), indent=1, ensure_ascii=False)
    if a.out:
        Path(a.out).write_text(doc + "\n", encoding="utf-8")
    else:
        print(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
