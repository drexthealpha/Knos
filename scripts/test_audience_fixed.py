"""A1 test_audience_fixed: the six front-door chips checked live on the hosted app after the deprecated audience call
was replaced (sweep 22 section 4). Pass: 0 calls with urn:entity:audience in the server's own call log for this run,
no chip ends CANNOT_DECIDE, each card shows at least 3 audience segments with lift numbers read live, and the run
spends at most 250 Qloo calls (the server's own day counter, before and after).

    python scripts/test_audience_fixed.py [result file] [app base URL]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else None
APP = (sys.argv[2] if len(sys.argv) > 2 else "https://knos.onrender.com").rstrip("/")
CHIPS = ("a solar powered music festival", "an AI recipe planner for families", "a crypto podcast for beginners",
         "a quantum physics book for kids", "a probiotic kombucha brand", "a recycled ocean plastic swimwear brand")
BUDGET = 250
UA = {"User-Agent": "knos-a1-test", "Content-Type": "application/json"}


def get(path: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(APP + path, headers=UA), timeout=120) as r:
        return json.loads(r.read())


def post(path: str, body: dict) -> dict:
    with urllib.request.urlopen(urllib.request.Request(APP + path, json.dumps(body).encode(), UA), timeout=300) as r:
        return json.loads(r.read())


def main() -> int:
    lines, fails = [], []

    def ok(c, what):
        lines.append(f"{'ok  ' if c else 'FAIL'} {what}")
        if not c:
            fails.append(what)

    day0 = int(get("/api/qloo/status").get("calls_today") or 0)
    deprecated = 0
    for chip in CHIPS:
        t = time.time()
        rep = post("/api/check", {"idea": chip, "picked": True})
        secs = round(time.time() - t, 1)
        req = (rep.get("qloo_request") or {}).get("req")
        log = [c for c in get("/api/calls").get("calls", []) if req and c.get("req") == req]
        bad = sum(1 for c in log if (c.get("params") or {}).get("filter.type") == "urn:entity:audience")
        deprecated += bad
        calls = rep.get("calls") or []
        segs = [a for a in rep.get("audiences") or [] if isinstance(a.get("lift"), (int, float))]
        live_segs = [a for a in segs if isinstance(a.get("src"), int) and 1 <= a["src"] <= len(calls) and calls[a["src"] - 1].get("live")]
        verdict = (rep.get("decision") or {}).get("verdict")
        q = rep.get("qloo_calls") or {}
        shown = ", ".join(f"{a['name']} {a['lift']:+.4f}" for a in segs[:3])
        ok(verdict not in (None, "CANNOT_DECIDE") and len(live_segs) >= 3 and bad == 0,
           f"{chip}: {verdict}; {len(segs)} segments with lift ({len(live_segs)} read live): {shown}; "
           f"calls {q.get('live')} live, {q.get('recorded')} recorded, {q.get('failed')} failed, {len(log)} in the server log "
           f"(req {req}), urn:entity:audience {bad}; {secs} s")
        time.sleep(22)                                        # the app's check limit: 30 per client per 10 minutes
    spent = int(get("/api/qloo/status").get("calls_today") or 0) - day0
    ok(deprecated == 0, f"calls with filter.type=urn:entity:audience in the server log for this run: {deprecated}")
    ok(0 <= spent <= BUDGET, f"Qloo calls spent by this run: {spent} (the server's day counter {day0} then {day0 + spent}; at most {BUDGET})")
    lines.append(f"PASS test_audience_fixed: 6 of 6 chips decided with 3+ live audience lifts, 0 deprecated calls, {spent} Qloo calls"
                 if not fails else f"FAIL test_audience_fixed: {len(fails)} of {len(lines)} checks failed: {fails[0][:160]}")
    print("\n".join(lines))
    if OUT:
        with OUT.open("a", encoding="utf-8") as f:
            f.write(f"\n{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n" + "\n".join(lines) + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
