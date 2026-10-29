"""N1 test_new_idea_answered: a new idea is answered from its own taste, never refused for being new. The 4 shared test
inputs and the 20 of INPUTS.txt go through the hosted app as a person would: the "Which one do you mean?" step first
(no Qloo call), then the reading a person picks (the input itself; for a paper, the first product it enables), checked
to its verdict. Pass: all 24 Open or Not yet with at least 3 live Qloo calls each, 0 answers saying "no product in Qloo
matches this idea", the median time to a verdict under 15 s, and at most 400 Qloo calls (the server's day counter).

The server answers at most 10 live checks per visitor an hour (B1), so the checks go in bursts of 10, an hour apart.

    python scripts/test_new_idea_answered.py <INPUTS.txt> [result file] [app base URL]
"""
from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

INPUTS = Path(sys.argv[1])
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else None
APP = (sys.argv[3] if len(sys.argv) > 3 else "https://knos.onrender.com").rstrip("/")
SHARED = ("a vegan ramen food truck", "a late night ramen spot", "10.1038/nature14539", "10.1126/science.1225829")
BUDGET, PER_HOUR = 400, 10
UA = {"User-Agent": "knos-n1-test", "Content-Type": "application/json"}


def post(path: str, body: dict) -> dict:
    """One request to the app; a connection the app drops is sent once more after 30 s (the app, never Qloo, retried)."""
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(urllib.request.Request(APP + path, json.dumps(body).encode(), UA), timeout=300) as r:
                return json.loads(r.read())
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(30)
    return {}


def get(path: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(APP + path, headers=UA), timeout=120) as r:
        return json.loads(r.read())


def pick(text: str) -> str:
    """The reading a person picks: the input itself; for a paper, the first product it enables."""
    w = post("/api/check", {"idea": text})
    if w.get("kind") != "which_one":
        return text
    rs = w.get("readings") or []
    if w.get("of") == "paper":
        prod = [r["text"] for r in rs if r.get("kind") == "product"]
        return prod[0] if prod else text
    return next((r["text"] for r in rs if r.get("kind") == "exact"), text)


def main() -> int:
    ideas = list(SHARED) + [x.strip() for x in INPUTS.read_text(encoding="utf-8").splitlines() if x.strip()]
    lines, fails, times = [], [], []

    def ok(c, what):
        line = f"{'ok  ' if c else 'FAIL'} {what}"
        lines.append(line)
        print(line, flush=True)
        if OUT:                                               # each line kept at once: a crash loses nothing
            with OUT.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        if not c:
            fails.append(what)

    day0 = int(get("/api/qloo/status").get("calls_today") or 0)
    burst_at = time.time()
    for i, text in enumerate(ideas):
        if i and i % PER_HOUR == 0:                           # the visitor cap: 10 live checks an hour
            time.sleep(max(0.0, burst_at + 3_610 - time.time()))
            burst_at = time.time()
        try:
            chosen = pick(text)
            t = time.time()
            rep = post("/api/check", {"idea": chosen, "picked": True, "stage": "verdict"})
        except (OSError, ValueError) as e:
            ok(False, f"{text[:60]}: the app did not answer ({type(e).__name__})")
            time.sleep(30)
            continue
        secs = round(time.time() - t, 1)
        times.append(secs)
        d = rep.get("decision") or {}
        q = rep.get("qloo_calls") or {}
        reasons = " ".join(str(x) for x in d.get("reasons") or [])
        said_no_match = "no product in Qloo matches this idea" in json.dumps(rep)
        good = d.get("verdict") in ("OPEN", "REFUSE") and int(q.get("live") or 0) >= 3 and not said_no_match
        tags = ", ".join(t_["name"] for t_ in ((rep.get("taste_answer") or {}).get("tags") or rep.get("tags") or [])[:3])
        ok(good, f"{text[:60]}{' -> ' + chosen[:40] if chosen != text else ''}: "
                 f"{'Open' if d.get('verdict') == 'OPEN' else 'Not yet' if d.get('verdict') == 'REFUSE' else d.get('verdict')}; "
                 f"{q.get('live')} live, {q.get('recorded')} recorded, {q.get('failed')} failed; tags: {tags or 'none'}; {secs} s; "
                 f"{reasons[:140]}")
        time.sleep(30)                                        # the app's check limit: 30 per client per 10 minutes (2 requests each)
    spent = int(get("/api/qloo/status").get("calls_today") or 0) - day0
    med = statistics.median(times) if times else None
    ok(med is not None and med < 15, f"median time to a verdict: {med} s (under 15 wanted)")
    ok(0 <= spent <= BUDGET, f"Qloo calls spent by this run: {spent} (the server's day counter; at most {BUDGET})")
    lines.append(f"PASS test_new_idea_answered: 24 of 24 Open or Not yet with 3+ live Qloo calls, median {med} s, {spent} Qloo calls"
                 if not fails else f"FAIL test_new_idea_answered: {len(fails)} of {len(lines)} checks failed; {spent} Qloo calls; first: {fails[0][:150]}")
    print(lines[-1])
    if OUT:
        with OUT.open("a", encoding="utf-8") as f:
            f.write(lines[-1] + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
