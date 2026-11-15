"""Kept for its record: a tool of the earlier demand-check work, not of Knos's locked-test flow.
test_outside_truth, live: 200 past DoD SBIR/STTR Phase I awards (2005-2014) whose outcome is known, 100 commercialized
(a granted US patent linked to the award in the Zenodo SBIR patent web data, 10.5281/zenodo.17018422) and 100 not (no
linked patent, no Phase II from the same firm on that topic or title, per sbir.gov award data). The hosted app reads one
short phrase from each (the title, or the abstract's first sentence) through POST /api/open-signals; prediction =
verdict OPEN. Pass: every row got a prediction and the stats were computed. The result is published as measured,
whatever it shows: accuracy, the majority-class base rate, precision/recall, an exact binomial test against that base
rate and Fisher's exact test on the 2x2.

    KNOS_ADMIN_KEY=... python scripts/outside_truth.py T3-sample.json [--limit N] [--out file] [--public]

Resumable: rows already in the result file (default T3-result.json next to the sample) are not asked again. With
--public the summary (numbers, method, sources; no abstracts) is written to docs/reference/outside_truth.json.
"""
from __future__ import annotations

import datetime
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("KNOS_WANTED_URL", "https://knos.onrender.com")
PUBLIC = os.path.join(os.path.dirname(__file__), "..", "docs", "reference", "outside_truth.json")
SOURCES = [{"name": "Zenodo: Data for 'A new approach to measuring invention commercialization: An application to the SBIR "
                    "program' (Bottai, de Rassenfosse, Raiteri; Research Policy 10.1016/j.respol.2025.105302)",
            "url": "https://doi.org/10.5281/zenodo.17018422"},
           {"name": "sbir.gov award data (with abstracts)", "url": "https://data.www.sbir.gov/awarddatapublic/award_data.csv"}]
METHOD = ("Population: DoD SBIR/STTR Phase I awards 2005-2014 on sbir.gov with an abstract of at least 200 characters. "
          "Commercialized = the Zenodo data links at least one granted US patent to the award's contract (a few also have a "
          "product or marking web page). Not = no linked patent and no Phase II from the same firm on the same topic code or "
          "title. 100 of each, drawn per award year in equal counts (seed 328). Knos sees one phrase: the title, or the "
          "abstract's first sentence, at most 120 characters. Prediction = OPEN from /api/open-signals (REFUSE and "
          "CANNOT_DECIDE count as not). p-values: exact binomial (one-sided, accuracy above the majority-class rate) and "
          "Fisher's exact (two-sided) on prediction x outcome.")


def post(path, body, headers=None, timeout=300):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read() or b"{}"
        try:
            return e.code, json.loads(raw)
        except ValueError:                                  # a proxy's HTML page (the app restarting): not an answer
            return e.code, {"message": raw[:120].decode("utf-8", "replace")}
    except (TimeoutError, urllib.error.URLError) as e:      # no answer at all: retried like a 5xx
        return 599, {"message": str(e)[:120]}


def phrase(row: dict) -> str:
    t = " ".join(row["title"].split())
    if 3 <= len(t.split()) and len(t) <= 120:
        return t
    s = re.split(r"(?<=[.!?])\s", row["abstract"], maxsplit=1)[0]
    return s if len(s) <= 120 else s[:120].rsplit(" ", 1)[0]


def binom_ge(k: int, n: int, p: float) -> float:
    """P(X >= k), X ~ Binomial(n, p)."""
    return min(1.0, sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1)))


def fisher(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher's exact p for [[a, b], [c, d]]: the tables with these margins no likelier than the one seen."""
    r1, c1, n = a + b, a + c, a + b + c + d
    pr = lambda x: math.comb(c1, x) * math.comb(n - c1, r1 - x) / math.comb(n, r1)  # noqa: E731
    p0 = pr(a)
    return min(1.0, sum(pr(x) for x in range(max(0, r1 + c1 - n), min(r1, c1) + 1) if pr(x) <= p0 * (1 + 1e-9)))


def stats(done: list[dict]) -> dict:
    n = len(done)
    tp = sum(1 for r in done if r["pred"] and r["truth"])
    fp = sum(1 for r in done if r["pred"] and not r["truth"])
    fn = sum(1 for r in done if not r["pred"] and r["truth"])
    tn = n - tp - fp - fn
    pos = tp + fn
    base = max(pos, n - pos) / n if n else 0.0
    return {"rows": n, "commercialized": pos, "not": n - pos, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "accuracy": round((tp + tn) / n, 4) if n else None, "base_rate": round(base, 4),
            "precision": round(tp / (tp + fp), 4) if tp + fp else None, "recall": round(tp / pos, 4) if pos else None,
            "p_binomial_vs_base": round(binom_ge(tp + tn, n, base), 6) if n else None,
            "p_fisher": round(fisher(tp, fp, fn, tn), 6) if n else None,
            "verdicts": {v: sum(1 for r in done if r["verdict"] == v) for v in sorted({r["verdict"] for r in done})}}


def main(sample_path: str, limit: int | None, out: str | None, public: bool) -> int:
    sample = json.loads(open(sample_path, encoding="utf-8").read())
    rows = sample["rows"][:limit] if limit else sample["rows"]
    out = out or os.path.join(os.path.dirname(os.path.abspath(sample_path)), "T3-result.json")
    res = json.loads(open(out, encoding="utf-8").read()) if os.path.exists(out) else {"rows": {}}
    op = {"X-Knos-Admin": os.environ.get("KNOS_ADMIN_KEY", "")}           # the operator's run: past the per-address limits
    for i, row in enumerate(rows, 1):
        if row["id"] in res["rows"]:
            continue
        idea = phrase(row)
        for _ in range(10):                                                  # a 429 waits out the public window
            st, got = post("/api/open-signals", {"idea": idea}, op)
            if st != 429 and st < 500:
                break
            time.sleep(70 if st == 429 else 20)                              # a 5xx: the app is restarting
        if st != 200 or not got.get("verdict"):
            print(f"FAIL {row['id']}: HTTP {st} {got.get('message') or got.get('error')}")
            continue
        res["rows"][row["id"]] = {"idea": idea, "verdict": got["verdict"], "counted": got.get("attention_counted"),
                                  "pred": got["verdict"] == "OPEN", "truth": row["outcome"] == "commercialized", "year": row["year"]}
        with open(out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)
        print(f"{i:3} {row['outcome'][:5]:5} {got['verdict']:13} {idea[:70]}", flush=True)
        time.sleep(1)
    done = [res["rows"][r["id"]] for r in rows if r["id"] in res["rows"]]
    s = stats(done)
    res.update({"made": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "summary": s,
                "method": METHOD, "sources": SOURCES, "population_base_rate": sample.get("meta", {}).get("base_rate_population")})
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    full = len(done) == len(rows) == len(sample["rows"])
    if public and full:
        with open(PUBLIC, "w", encoding="utf-8") as f:
            json.dump({k: res[k] for k in ("made", "summary", "method", "sources", "population_base_rate")}, f, indent=1)
    line = (f"accuracy {s['accuracy']} vs base rate {s['base_rate']} (n={s['rows']}), precision {s['precision']}, recall "
            f"{s['recall']}, p binomial {s['p_binomial_vs_base']}, p Fisher {s['p_fisher']}, verdicts {s['verdicts']}")
    if full:
        print("PASS test_outside_truth: " + line)
        return 0
    print(f"{'PARTIAL' if limit else 'FAIL'} test_outside_truth ({len(done)} of {len(rows)} rows predicted"
          f"{'' if limit is None else f', limit {limit} of ' + str(len(sample['rows']))}): " + line)
    return 0 if limit and len(done) == len(rows) else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(main(a[0], int(a[a.index("--limit") + 1]) if "--limit" in a else None,
                  a[a.index("--out") + 1] if "--out" in a else None, "--public" in a))
