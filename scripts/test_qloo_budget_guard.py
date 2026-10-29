"""B1 test_qloo_budget_guard: the server's Qloo caps hold before any network call, its limiters stay bounded, and
/status/qloo shows calls left this month, today's count and the day cap. Spends 0 Qloo calls: every Qloo answer here
comes from a fake opener that counts what would have gone out.

    python scripts/test_qloo_budget_guard.py [result file] [app base URL]
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "wanted"))

from knos_wanted import qloo_rest, server  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else None
APP = (sys.argv[2] if len(sys.argv) > 2 else "https://knos.onrender.com").rstrip("/")
SALT = b"test salt, never the server's"


class Net:
    """A stand-in for the network: counts every request that would have reached Qloo."""

    def __init__(self):
        self.n = 0

    def __call__(self, req, timeout=None):
        self.n += 1
        body = json.dumps({"success": True, "results": {"entities": [{"name": f"answer {self.n}"}]}}).encode()

        class R:
            headers = {"x-month-ratelimit-remaining": "99000"}

            def read(self, n=-1):
                return body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return R()


def client(folder: Path, net: Net) -> qloo_rest.Client:
    return qloo_rest.Client(key="test-key-not-real", base="https://hackathon.api.qloo.com", folder=folder, opener=net,
                            bucket=qloo_rest._Bucket(1000.0))


def tags(i: int) -> dict:
    return {"filter.query": f"ramen {i}", "take": 5}


def refused(fn) -> str:
    try:
        fn()
    except qloo_rest.QlooError as e:
        return str(e)
    return ""


def main() -> int:
    lines, fails = [], []

    def ok(c, what):
        lines.append(f"{'ok  ' if c else 'FAIL'} {what}")
        if not c:
            fails.append(what)

    qloo_rest.LIMITS.clear()
    with tempfile.TemporaryDirectory() as d:
        net = Net()
        c = client(Path(d), net)
        # 1. call 3,001 of a simulated UTC day: the counter on disk says 3,000 sent today
        (Path(d) / "day.txt").write_text(f"{time.strftime('%Y-%m-%d', time.gmtime())} {qloo_rest.DAY_CAP}\n", encoding="utf-8")
        why = refused(lambda: qloo_rest.CheckBudget(c).get("/v2/tags", tags(0)))
        ok(net.n == 0 and qloo_rest.LIMIT_LINE in why, f"call {qloo_rest.DAY_CAP + 1:,} of a simulated day: not sent ({why[:90]}), network calls {net.n}")
        (Path(d) / "day.txt").unlink()
        # 2. call 41 of one check
        b = qloo_rest.CheckBudget(c)
        for i in range(1, qloo_rest.PER_CHECK + 1):
            b.get("/v2/tags", tags(i))
        sent = net.n
        why = refused(lambda: b.get("/v2/tags", tags(qloo_rest.PER_CHECK + 1)))
        ok(sent == qloo_rest.PER_CHECK and net.n == sent and "live Qloo calls are used" in why,
           f"call {qloo_rest.PER_CHECK + 1} of one check: not sent ({why[:80]}); network calls {net.n} for {qloo_rest.PER_CHECK} asked")
        # 3. the same question again within 24 hours: the private cache, labelled with its time
        n0 = net.n
        again = qloo_rest.CheckBudget(c).get("/v2/tags", tags(1))
        ok(net.n == n0 and again["source"]["cached"] and again["source"].get("at"),
           f"a repeat within 24 hours: from the cache, labelled {again['source'].get('at')}, network calls added {net.n - n0}")
        # 4. under the 20,000 reserve: anything that is not a demand check answers from the cache only
        qloo_rest.LIMITS["x-month-ratelimit-remaining"] = str(qloo_rest.RESERVE - 1)
        n0 = net.n
        why = refused(lambda: c.get("/v2/tags", tags(900), purpose="other"))
        ok(net.n == n0 and "kept for demand checks" in why, f"a non-check call under the {qloo_rest.RESERVE:,} reserve: not sent ({why[:90]})")
        # and a visitor past the hourly cap is answered from the cache only
        why = refused(lambda: qloo_rest.CheckBudget(c, only_cache="10 live checks an hour from one visitor").get("/v2/tags", tags(901)))
        ok(net.n == n0 and "not sent" in why, f"a check past the visitor cap: not sent, network calls added {net.n - n0}")
        qloo_rest.LIMITS.clear()
        # the visitor key is a salted SHA-256, never the address
        vh = qloo_rest.visitor_hash("203.0.113.7", SALT)
        ok(re.fullmatch(r"[0-9a-f]{64}", vh) and "203.0.113.7" not in vh, f"visitor key: HMAC-SHA256 {vh[:12]}..., the address not kept")
        caps = [qloo_rest.visitor_take(vh, now=1000.0 + i) for i in range(qloo_rest.VISITOR_CAP[0] + 1)]
        ok(caps[:-1] == [None] * qloo_rest.VISITOR_CAP[0] and caps[-1], f"visitor cap: checks 1 to {qloo_rest.VISITOR_CAP[0]} live, check {qloo_rest.VISITOR_CAP[0] + 1} from the cache")
        ok(net.n == qloo_rest.PER_CHECK, f"network calls in all of the above: {net.n}, all {qloo_rest.PER_CHECK} from case 2")
    # 5. the limiters stay bounded: 10,000 simulated visitors, then an hour later one more
    qloo_rest._VISITORS.clear()
    for i in range(10_000):
        qloo_rest.visitor_take(qloo_rest.visitor_hash(f"198.51.{i // 256}.{i % 256}", SALT), now=5000.0 + i * 0.01)
    held_before = qloo_rest.visitor_keys(now=5100.0)[0]
    qloo_rest.visitor_take(qloo_rest.visitor_hash("192.0.2.1", SALT), now=5100.0 + 3601)
    held, old = qloo_rest.visitor_keys(now=5100.0 + 3601)
    ok(old == 0 and held == 1, f"visitor map: {held_before:,} keys after 10,000 visitors, {held} held and {old} older than 1 hour an hour later")
    st = server.State(rest=qloo_rest.Client(key=""))
    real = server.time.monotonic
    try:
        server.time.monotonic = lambda: 10_000.0
        for i in range(10_000):
            st.allow(f"198.51.{i // 256}.{i % 256}", "check")
        before = len(st.hits)
        server.time.monotonic = lambda: 10_000.0 + 3601
        st.allow("192.0.2.1", "check")
        now = 10_000.0 + 3601
        old = sum(1 for dq in st.hits.values() if not dq or now - dq[-1] > 3600)
    finally:
        server.time.monotonic = real
    ok(old == 0 and len(st.hits) == 1, f"rate limiter: {before:,} keys after 10,000 visitors, {len(st.hits)} held and {old} older than 1 hour an hour later")
    # 6. /status/qloo shows the 3 numbers, and this test spent 0 Qloo calls (the server's own count, before and after)
    def status():
        with urllib.request.urlopen(urllib.request.Request(APP + "/api/qloo/status", headers={"User-Agent": "knos-b1"}), timeout=60) as r:
            return json.loads(r.read())
    try:
        s0 = status()
        with urllib.request.urlopen(urllib.request.Request(APP + "/status/qloo", headers={"User-Agent": "knos-b1"}), timeout=60) as r:
            page = r.read().decode("utf-8", "replace")
        s1 = status()
        rows = {k: v for k, v in re.findall(r"<dt>([^<]+)</dt><dd>([^<]+)</dd>", page)}
        three = [rows.get(k) for k in ("Calls left this month", "Calls today", "Day cap")]
        ok(all(three) and (rows.get("Day cap") or "").replace(",", "") == str(qloo_rest.DAY_CAP),
           f"/status/qloo: calls left this month {three[0]}, calls today {three[1]}, day cap {three[2]}")
        spent = int(s1.get("calls_today") or 0) - int(s0.get("calls_today") or 0)
        ok(spent == 0, f"Qloo calls spent by this test: {spent} (server count {s0.get('calls_today')} then {s1.get('calls_today')})")
    except Exception as e:  # noqa: BLE001 - the live part is reported, never skipped silently
        ok(False, f"/status/qloo could not be read: {type(e).__name__}: {e}")
    lines.append(f"PASS test_qloo_budget_guard: {len(lines)} of {len(lines)} checks, 0 Qloo calls spent" if not fails
                 else f"FAIL test_qloo_budget_guard: {len(fails)} of {len(lines)} checks failed: {fails[0][:120]}")
    print("\n".join(lines))
    if OUT:
        with OUT.open("a", encoding="utf-8") as f:
            f.write(f"\n{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n" + "\n".join(lines) + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
