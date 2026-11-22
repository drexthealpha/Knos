"""L14: the cost per run the server measured (tool_run.cost(), in GET /api/usage "cost") written where the pricing page
reads it, docs/data/pricing.json "window" "cost_per_run", with one point a day on its "trend".

    python -m knos_wanted.run_cost --out docs/data/pricing.json [--from https://knos.onrender.com/api/usage]

A server that does not answer, or has no run recorded yet, changes nothing: the page keeps saying "not known yet".
Only window.cost_per_run and window.trend are written; every other number in the file stays as it is."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

URL = "https://knos.onrender.com/api/usage"
UNIT = "US dollars one run costs Knos, failed runs included, over the latest runs"


def merge(doc: dict, cost: dict, today: str) -> bool:
    """Write the measured cost into the pricing document; False (nothing written) while it is not measured."""
    usd = cost.get("usd_per_run") if isinstance(cost, dict) else None
    if not isinstance(usd, (int, float)) or isinstance(usd, bool) or usd < 0 or not cost.get("runs"):
        return False
    w = doc.setdefault("window", {})
    w["cost_per_run"] = {"value": usd, "unit": UNIT,
                         "source": f"{cost.get('source')}; host {cost.get('host_usd_per_month')} US dollars a month "
                                   f"({cost.get('host_source')}); read {today}",
                         "runs": int(cost["runs"]), "failed": int(cost.get("failed") or 0),
                         "seconds_per_run": cost.get("seconds_per_run"), "tokens_per_run": cost.get("tokens_per_run")}
    trend = [t for t in w.get("trend") or [] if t.get("date") != today]
    w["trend"] = (trend + [{"date": today, "value": usd}])[-365:]
    return True


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--from", dest="src", default=URL)
    a = ap.parse_args(argv)
    try:
        with urllib.request.urlopen(urllib.request.Request(a.src, headers={"user-agent": "knos-run-cost"}), timeout=60) as r:
            cost = json.loads(r.read().decode("utf-8")).get("cost")
    except Exception as e:  # noqa: BLE001 - any failure leaves the file
        print(f"pricing.json kept: {a.src} did not answer ({type(e).__name__})")
        return 0
    out = Path(a.out)
    doc = json.loads(out.read_text(encoding="utf-8"))
    if not merge(doc, cost or {}, dt.datetime.now(dt.timezone.utc).date().isoformat()):
        print("pricing.json kept: no run measured yet")
        return 0
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="")
    print(f"pricing.json: cost per run {doc['window']['cost_per_run']['value']} over {cost['runs']} runs")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
