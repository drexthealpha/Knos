"""The use counts the status page shows (D2, D3): docs/data/usage.json, written from the hosted server's /api/usage.

    python scripts/site_usage.py            read https://knos.onrender.com/api/usage and write docs/data/usage.json
    python scripts/site_usage.py --check    the file has every count, each a whole number of 0 or more (or null for a
                                            measure with too few browsers yet)

A server that does not answer writes nothing: the committed file stays. Runs by Knos's own tests and by the WALK
agents carry a marker and are counted apart by the server; this file holds only the others. No name, email or network
address is in it: counts only.

The file's shape (the status page and tests/test_site_usage.py read it):
    {"source", "read_at", "days": [{"day": "YYYY-MM-DD", <COUNTS>}], "totals": {<COUNTS>}, "measures": {<MEASURES>}}
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "docs" / "data" / "usage.json"
URL = "https://knos.onrender.com/api/usage"
# each count per UTC day, with the label the status page shows (D2); short, because the status page's first screen holds
# at most 40 words (U3 R3); each label is also a key of web/i18n/en.json (status.<key>), shown in the browser's language
COUNTS = [("tools_opened", "Tool opened"), ("sample_runs", "Sample runs"), ("own_runs", "Own-file runs"),
          ("results_opened_elsewhere", "Results opened elsewhere"), ("test_payments", "Test payments"),
          ("connector_runs", "Runs from other apps")]   # web/i18n/en.json status.connector_runs (R13 WALK 1)
# the three measures of docs/NUMBERS.md (D1): a share in percent, or a number of days, or null with too few browsers
MEASURES = [("day7_return", "Came back on day 7, percent of browsers"), ("active_days", "Days with a run in the first 7, average"),
            ("paying_share", "Paid after the free runs ran out, percent of browsers")]


def empty() -> dict:
    return {"source": URL, "read_at": None, "days": [], "totals": {k: 0 for k, _ in COUNTS}, "measures": {k: None for k, _ in MEASURES}}


def shape(raw: dict) -> dict:
    """The server's answer in this file's shape: days as a list (or a map by day), totals summed from the days."""
    days = raw.get("days") or []
    if isinstance(days, dict):
        days = [{"day": d, **v} for d, v in days.items()]
    rows = [{"day": str(d["day"])[:10], **{k: int(d.get(k) or 0) for k, _ in COUNTS}} for d in days if d.get("day")]
    rows.sort(key=lambda r: r["day"])
    m = raw.get("measures") or {}

    def value(k: str):
        """The server's measure (apps/wanted/knos_wanted/tool_run.py measures()): a share from 0 to 1 for the two rates,
        shown in percent; the mean number of days for active days; null while no browser is old enough."""
        x = m.get(k)
        if isinstance(x, dict):
            x = x.get("mean") if k == "active_days" else (None if x.get("share") is None else float(x["share"]) * 100)
        return None if x is None else round(float(x), 1)
    return {"source": URL, "read_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "days": rows,
            "totals": {k: sum(r[k] for r in rows) for k, _ in COUNTS},
            "measures": {k: value(k) for k, _ in MEASURES}}


def check(doc: dict) -> list[str]:
    bad = [k for k, _ in COUNTS if not isinstance(doc.get("totals", {}).get(k), int) or doc["totals"][k] < 0]
    bad += [f"{d.get('day')}:{k}" for d in doc.get("days", []) for k, _ in COUNTS if not isinstance(d.get(k), int) or d[k] < 0]
    bad += [k for k, _ in MEASURES if k not in doc.get("measures", {})]
    bad += [k for k, _ in COUNTS if sum(d.get(k, 0) for d in doc.get("days", [])) != doc.get("totals", {}).get(k)]
    return bad


def main(argv: list[str]) -> int:
    if argv[:1] == ["--check"]:
        bad = check(json.loads(FILE.read_text(encoding="utf-8")))
        print("usage.json: every count is whole" if not bad else f"usage.json: not whole: {bad}")
        return 1 if bad else 0
    try:
        with urllib.request.urlopen(urllib.request.Request(URL, headers={"user-agent": "knos-site-build"}), timeout=60) as r:
            raw = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001 - any failure leaves the committed file
        print(f"usage.json kept: {URL} did not answer ({type(e).__name__})")
        return 0
    doc = shape(raw)
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="")
    print(f"usage.json written: {len(doc['days'])} days")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
