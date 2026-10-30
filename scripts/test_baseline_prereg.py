"""Q7 test_baseline_prereg: Knos's Qloo launch-city ranking against two baselines with no model, Qloo popularity alone
and population, on the held-out Census key of the where-demand test. The plan is docs/reference/baseline_prereg_plan.md,
committed with its sha256 in the commit message before any Qloo call. Run once.

    python scripts/test_baseline_prereg.py --run <world>/where-truth.json <world>/baseline-cards.json
    python scripts/test_baseline_prereg.py --score <world>/where-truth.json <world>/baseline-cards.json <world result file>
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "reference" / "baseline_prereg_plan.md"
PUBLIC = ROOT / "docs" / "reference" / "baseline_prereg.json"
APP = "https://knos.onrender.com"
K, MIN_CELLS, BOOT, SEED = 5, 3, 2000, 1
CAP, STOP_AT = 600, 560


def check(title: str) -> dict:
    """One live demand check of the title as typed; a dropped connection is asked once more (the server's cache keeps
    what Qloo already answered), never a third time."""
    body = json.dumps({"idea": title, "picked": True}).encode()
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(APP + "/api/check", body, {"Content-Type": "application/json", "User-Agent": "knos-q7-test"})
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read())
        except (OSError, ValueError) as e:
            if attempt == 2:
                return {"error": f"{type(e).__name__}: {str(e)[:160]}"}
            time.sleep(30)
    return {}


def run(truth_file: str, out: str) -> int:
    t = json.loads(Path(truth_file).read_text(encoding="utf-8"))
    done = json.loads(Path(out).read_text(encoding="utf-8")) if Path(out).exists() else {"rows": []}
    seen = {r["naics"] for r in done["rows"]}
    spent = sum(r.get("live", 0) for r in done["rows"])
    for c in t["codes"]:
        if c["naics"] in seen:
            continue
        if spent >= STOP_AT:
            done["rows"].append({"naics": c["naics"], "title": c["title"], "not_reached": True, "live": 0, "metros": []})
            print(c["naics"], "not reached: the budget stop", flush=True)
        else:
            rep = check(c["title"])
            live = int((rep.get("qloo_calls") or {}).get("live") or 0)
            spent += live
            metros = (rep.get("terms") or {}).get("metros") or []
            done["rows"].append({"naics": c["naics"], "title": c["title"], "live": live, "verdict": (rep.get("decision") or {}).get("verdict"),
                                 "hash": rep.get("hash"), "error": rep.get("error"),
                                 "metros": [{k: m.get(k) for k in ("cbsa", "cells", "lift", "affinity", "qloo_popularity")} for m in metros]})
            print(c["naics"], live, "live calls,", len(metros), "metros, spent", spent, flush=True)
        Path(out).write_text(json.dumps(done, indent=1), encoding="utf-8")          # written as it goes
    return 0


def knos_top(metros: list[dict], cands: set[str]) -> list[str]:
    rows = [m for m in metros if m["cbsa"] in cands]
    key = lambda m: (-(m.get("lift") or 0), -m["cells"], m["cbsa"])  # noqa: E731
    return [m["cbsa"] for m in sorted((m for m in rows if m["cells"] >= MIN_CELLS), key=key) +
            sorted((m for m in rows if m["cells"] < MIN_CELLS), key=key)][:K]


def popularity_top(metros: list[dict], cands: set[str]) -> list[str]:
    rows = [m for m in metros if m["cbsa"] in cands and m.get("qloo_popularity") is not None]
    return [m["cbsa"] for m in sorted(rows, key=lambda m: (-m["qloo_popularity"], -m["cells"], m["cbsa"]))][:K]


def interval(diffs_by_code: list[float]) -> tuple[float, float]:
    rng, n, means = random.Random(SEED), len(diffs_by_code), []
    for _ in range(BOOT):
        means.append(sum(diffs_by_code[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return means[int(0.025 * BOOT)], means[int(0.975 * BOOT) - 1]


def score(truth_file: str, cards_file: str, result: str) -> int:
    t = json.loads(Path(truth_file).read_text(encoding="utf-8"))
    cards = {r["naics"]: r for r in json.loads(Path(cards_file).read_text(encoding="utf-8"))["rows"]}
    cands = {c["cbsa"] for c in t["candidates"]}
    population = [c["cbsa"] for c in sorted(t["candidates"], key=lambda c: (-c["pop"], c["cbsa"]))][:K]
    per = []
    for c in t["codes"]:
        top10, r = set(c["top10"]), cards.get(c["naics"]) or {"metros": []}
        kn, po = knos_top(r["metros"], cands), popularity_top(r["metros"], cands)
        per.append({"naics": c["naics"], "title": c["title"], "truth_top10": sorted(top10), "knos_top5": kn, "popularity_top5": po,
                    "population_top5": population, "knos": len(set(kn) & top10) / K, "popularity": len(set(po) & top10) / K,
                    "population": len(set(population) & top10) / K, "live": r.get("live", 0), "not_reached": bool(r.get("not_reached"))})
    n = len(per)
    mean = {a: round(sum(p[a] for p in per) / n, 4) for a in ("knos", "popularity", "population")}
    out = {}
    for base in ("popularity", "population"):
        lo, hi = interval([p["knos"] - p[base] for p in per])
        reading = "Knos is ahead" if lo > 0 else "the baseline is ahead" if hi < 0 else "the test cannot tell them apart"
        out[base] = {"difference": round(mean["knos"] - mean[base], 4), "interval_95": [round(lo, 4), round(hi, 4)], "reading": reading}
    calls = sum(p["live"] for p in per)
    sha = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    doc = {"made": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "plan": "docs/reference/baseline_prereg_plan.md",
           "plan_sha256": sha, "n": n, "qloo_calls": calls, "metric": "overlap at 5 with the Census top 10, divided by 5",
           "mean_overlap": {"knos_with_qloo": mean["knos"], "qloo_popularity_alone": mean["popularity"], "population": mean["population"]},
           "knos_minus_popularity": out["popularity"], "knos_minus_population": out["population"],
           "bootstrap": {"resamples": BOOT, "seed": SEED}, "types_with_metros": sum(1 for p in per if p["knos_top5"]),
           "not_reached": sum(1 for p in per if p["not_reached"]), "per_code": per,
           "answer_key": "docs/reference/where_truth.json (the where-demand test's Census key, unchanged)"}
    PUBLIC.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    lines = [f"plan {doc['plan']} sha256 {sha}",
             f"n {n}; mean overlap at 5: Knos with Qloo {mean['knos']:.3f}, Qloo popularity alone {mean['popularity']:.3f}, population {mean['population']:.3f}; {calls} Qloo calls",
             f"Knos minus popularity {out['popularity']['difference']:+.3f} [{out['popularity']['interval_95'][0]:+.3f}, {out['popularity']['interval_95'][1]:+.3f}]: {out['popularity']['reading']}",
             f"Knos minus population {out['population']['difference']:+.3f} [{out['population']['interval_95'][0]:+.3f}, {out['population']['interval_95'][1]:+.3f}]: {out['population']['reading']}"]
    ran = calls <= CAP and n == 30
    lines.append(f"scored{'' if ran else ' (outside the plan)'}: run once to its result by the plan on {n} business types with {calls} Qloo calls; "
                 f"Knos {mean['knos']:.3f}, popularity alone {mean['popularity']:.3f}, population {mean['population']:.3f}; "
                 f"against popularity: {out['popularity']['reading']}; against population: {out['population']['reading']}")
    with open(result, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if ran else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit({"--run": run, "--score": score}[a[0]](*a[1:]))
