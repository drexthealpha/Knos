"""Qloo's REST API, called from this server only (the browser never sees the key or calls Qloo).

    c = Client()                      # key from env QLOO_API_KEY, base from env QLOO_BASE_URL
    got = c.get("/v2/insights", {"filter.type": "urn:demographics", "signal.interests.entities": "..."})
    got["body"]      the JSON Qloo answered
    got["source"]    {"call": "GET /v2/insights", "params": {...}, "cached": bool, "at": ...}: what every number cites

Rules this module keeps, all server side:
- the key comes from the environment (QLOO_API_KEY) only; it travels in the request header, never in a URL, a log line,
  an error message, the cache or a report;
- the base URL comes from QLOO_BASE_URL (the Dockerfile and README set Qloo's API server);
- answers are cached privately on the server's disk (KNOS_WANTED_CACHE/qloo-rest, one file per sha256 of method + path +
  sorted params, with no time limit), never in the repository (Qloo's rule: cache privately, never publish response bodies);
- at most 4 calls per second across the whole process (a token bucket);
- a persistent monthly call counter with a hard budget (QLOO_MONTHLY_BUDGET, default 9,000): past it, new uncached calls
  are refused with a clear error, cached answers are still served.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import qloo_guard, qloo_harness

TTL_S = None                  # a 2xx answer: kept with no time limit (Qloo's guide: private server-side caching, no time limit)
ERROR_TTL_S = 86_400          # a 4xx answer (Qloo refused the question) is remembered for a day
SLOW_TTL_S = 3_600           # a question Qloo did not answer within TIMEOUT_S is not asked again for an hour
RATE_PER_S = 4.0
DEFAULT_BUDGET = 9_000
TIMEOUT_S = 45.0
MAX_BYTES = 4_000_000
HEATMAP_KEEP = 50          # a heatmap answer's points kept: the app reads at most 8, Qloo sends thousands (6,999 seen)
LIVE_LABEL = "LIVE Qloo data (Qloo REST API, read for this report, cached privately on the server)"


RETRY_AFTER_DEFAULT_S = 300  # Qloo's 429 without a Retry-After: nothing is sent to Qloo for five minutes
_hold = {"until": 0.0}        # after a 429: no Qloo request at all before this time (time.time()), for the whole process
LAST: dict = {}               # the last answer Qloo itself gave this process (its time, HTTP status and path): /status/qloo


LIMITS: dict = {}             # Qloo's own limit headers, as its latest answer gave them (x-month-ratelimit-*, x-second-ratelimit-*)
MONTH_FLOOR = 2_000           # under this many calls left in Qloo's month, nothing is sent (the rest is kept for the reserved run)
DAY_CAP = 1_500               # this server sends at most this many calls to Qloo on one UTC day
TODAY: dict = {}              # this process's Qloo traffic on the current UTC day: calls sent, cache hits, last 200, last 429


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _today() -> dict:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    if TODAY.get("day") != day:
        TODAY.clear()
        TODAY.update(day=day, calls=0, hits=0)
    return TODAY


def _seen(status, path: str) -> None:
    LAST.update(at=_now(), status=status, path=path)
    t = _today()
    t["calls"] += 1
    if status == 200:
        t["last_ok"] = LAST["at"]
    elif status == 429:
        t["last_429"] = LAST["at"]


def _limits(headers) -> None:
    """Keep the limit headers of a Qloo answer (a success or a refusal), with when they were read."""
    if headers is None:
        return
    got = {k.lower(): v for k, v in headers.items() if k.lower().startswith(("x-month-ratelimit-", "x-second-ratelimit-"))}
    if got:
        LIMITS.clear()
        LIMITS.update(got, read=_now())
        try:
            secs = float(got.get("x-month-ratelimit-reset", ""))
            LIMITS["month_reset_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + secs))
        except ValueError:
            pass


def _int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def refusal() -> str | None:
    """Why nothing may be sent now, by Qloo's month (its own header) and this server's day; None when a call may go."""
    import os
    left = _int(LIMITS.get("x-month-ratelimit-remaining"))
    if left is not None and left < MONTH_FLOOR and os.environ.get("KNOS_QLOO_RESERVE") != "1":
        return f"Qloo's month has {left} calls left, under {MONTH_FLOOR:,}: they are kept for the reserved run"
    if _today()["calls"] >= DAY_CAP:
        return f"this server has sent {DAY_CAP:,} calls to Qloo today, its cap for a UTC day"
    return None


def today() -> dict:
    """Today's counts as /status/qloo shows them: calls sent, cache hits, the hit rate, the last success and last 429
    (this process's; the last 429 also when an earlier day's pause still holds)."""
    t = dict(_today())
    asked = t["calls"] + t["hits"]
    t["hit_rate"] = round(t["hits"] / asked, 3) if asked else None
    t["held_s"] = round(held())
    t["limited"] = t["held_s"] > 0 or (LAST.get("status") == 429)
    return t


def retry_after(value, now: float | None = None) -> float:
    """Seconds to wait from a Retry-After header: delay-seconds or an HTTP date; RETRY_AFTER_DEFAULT_S when absent or unreadable."""
    import email.utils
    now = time.time() if now is None else now
    v = str(value or "").strip()
    if v.isdigit():
        return float(v)
    try:
        when = email.utils.parsedate_to_datetime(v)
        return max(0.0, when.timestamp() - now)
    except (TypeError, ValueError, IndexError, OverflowError):
        return float(RETRY_AFTER_DEFAULT_S)


def held(now: float | None = None) -> float:
    """Seconds left before Qloo may be asked again after its last 429 (0 when it may)."""
    return max(0.0, _hold["until"] - (time.time() if now is None else now))


# the last 200 Qloo requests this server made or kept (GET /api/calls, the front door's /calls/): no body, no key
RECENT: collections.deque = collections.deque(maxlen=200)
_SECRET = re.compile(r"key|token|secret|auth", re.I)


def note(call: str, params: dict | None, status, ms: float | None, cached: bool, at: str | None = None, origin: str = "live") -> None:
    # "live" only when Qloo answered this call with HTTP 200 now; a cached answer, a 429 or a call not sent is said as such
    if origin == "live" and not (status == 200 and not cached):
        origin = "cached" if cached else "not sent" if status == "not sent" else "refused"
    RECENT.append({"at": at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "call": call,
                   "params": {k: v for k, v in (params or {}).items() if not _SECRET.search(str(k))},
                   "status": status, "ms": None if ms is None else round(ms), "cached": bool(cached), "origin": origin})


def _status(why: Exception) -> int | str:
    """A refused or failed call's status in the log: Qloo's HTTP code when it answered one, else "not sent" or "failed"."""
    text = str(why)
    if isinstance(why, (NoKey, BudgetExceeded)) or "not sent" in text or "no request sent" in text:
        return "not sent"
    code = re.search(r"HTTP (\d{3})", text)
    return int(code.group(1)) if code else "failed"


def recent() -> list[dict]:
    return list(reversed(RECENT))


class QlooError(RuntimeError):
    """Qloo could not answer (no key, network, HTTP error, budget). The message never contains the key."""


class NoKey(QlooError):
    pass


class BudgetExceeded(QlooError):
    pass


def trim(body):
    """A heatmap answer's first HEATMAP_KEEP points, with how many Qloo sent (heatmap_total): a 4 MB answer parsed on
    every read held tens of MB per check, and checks at once ran the free instance out of memory (24 Oct 2026)."""
    res = body.get("results") if isinstance(body, dict) else None
    pts = res.get("heatmap") if isinstance(res, dict) else None
    if isinstance(pts, list) and len(pts) > HEATMAP_KEEP:
        return {**body, "results": {**res, "heatmap": pts[:HEATMAP_KEEP], "heatmap_total": len(pts)}}
    return body


class _Bucket:
    """A process-wide token bucket: `rate` calls per second, bursts of at most `rate`."""

    def __init__(self, rate: float, clock=time.monotonic, sleep=time.sleep):
        self.rate, self.tokens, self.clock, self.sleep = rate, rate, clock, sleep
        self.last = clock()
        self.lock = threading.Lock()

    def take(self) -> None:
        while True:
            with self.lock:
                now = self.clock()
                self.tokens = min(self.rate, self.tokens + (now - self.last) * self.rate)
                self.last = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            self.sleep(wait)


BUCKET = _Bucket(RATE_PER_S)
_COUNT_LOCK = threading.Lock()


# the parameters Qloo takes only in a JSON body (docs.qloo.com: "can only be supplied when using POST HTTP method")
POST_ONLY = ("filter.exclude.entities.query", "signal.interests.entities.query")


def cache_dir() -> Path:
    base = os.environ.get("KNOS_WANTED_CACHE") or str(Path.home() / ".cache" / "knos-demand-check")
    return Path(base) / "qloo-rest"


def cache_key(method: str, path: str, params: dict) -> str:
    items = sorted((str(k), str(v)) for k, v in (params or {}).items())
    return hashlib.sha256(json.dumps([method.upper(), path, items]).encode()).hexdigest()


def _month(ts: float) -> str:
    return time.strftime("%Y-%m", time.gmtime(ts))



def forced() -> int | None:
    """Test mode only (KNOS_TEST_MODE=1): QLOO_FORCE_STATUS makes every Qloo call fail with that HTTP code. Both are
    unset in production, where this is always None."""
    if os.environ.get("KNOS_TEST_MODE") != "1":
        return None
    v = os.environ.get("QLOO_FORCE_STATUS", "")
    return int(v) if v.isdigit() else None


class Client:
    def __init__(self, key: str | None = None, base: str | None = None, folder: Path | None = None, budget: int | None = None,
                 opener=None, clock=time.time, bucket: _Bucket | None = None):
        self._key = key if key is not None else os.environ.get("QLOO_API_KEY", "")
        self.base = (base or os.environ.get("QLOO_BASE_URL", "")).rstrip("/")
        self.folder = folder or cache_dir()
        self.budget = budget if budget is not None else int(os.environ.get("QLOO_MONTHLY_BUDGET") or DEFAULT_BUDGET)
        self.opener = opener or urllib.request.urlopen
        self.harness = opener is None and key is None          # the real network only: Qloo's harness answers first
        self.clock = clock
        self.bucket = bucket or BUCKET
        self.live_calls = 0                   # uncached calls made by this client (for build/test accounting)

    # ---- state -------------------------------------------------------------------------------------------------------
    @property
    def has_key(self) -> bool:
        return bool(self._key)

    def ready(self) -> tuple[bool, str]:
        if forced():
            return True, f"test mode: every Qloo call answers HTTP {forced()}"
        if not self._key:
            return False, "no Qloo API key on this server"
        if not self.base.startswith("https://"):
            return False, "QLOO_BASE_URL is not set to Qloo's https API (see README)"
        return True, "ok"

    def _counter(self) -> Path:
        return self.folder / "calls.txt"

    def used(self) -> int:
        """Uncached calls this calendar month (UTC), read from the persistent counter."""
        try:
            month, n = self._counter().read_text(encoding="utf-8").split()
            return int(n) if month == _month(self.clock()) else 0
        except (OSError, ValueError):
            return 0

    def _count_one(self) -> None:
        with _COUNT_LOCK:
            n = self.used()
            if n >= self.budget:
                raise BudgetExceeded(f"Qloo monthly call budget reached ({n} of {self.budget}): new questions wait for next month; cached answers still work")
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self._counter().with_suffix(".tmp")
            tmp.write_text(f"{_month(self.clock())} {n + 1}\n", encoding="utf-8")
            os.replace(tmp, self._counter())

    def status(self) -> dict:
        ok, why = self.ready()
        return {"rest": ok, "reason": why, "calls_this_month": self.used(), "budget": self.budget, "rate_per_s": RATE_PER_S,
                "cache_ttl_days": None if TTL_S is None else TTL_S // 86_400}

    # ---- the call ----------------------------------------------------------------------------------------------------
    def _cached(self, k: str) -> dict | None:
        f = self.folder / k[:2] / f"{k}.qloo"
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        ttl = doc.get("ttl") or (ERROR_TTL_S if doc.get("error") else TTL_S)
        return doc if ttl is None or self.clock() - doc.get("t", 0) <= ttl else None

    def _store(self, k: str, body, error: str | None = None, surface: str | None = None, ttl: int | None = None) -> None:
        d = self.folder / k[:2]
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f"{k}.tmp"
        tmp.write_text(json.dumps({"t": self.clock(), "body": body, **({"error": error} if error else {}),
                                   **({"surface": surface} if surface else {}), **({"ttl": ttl} if ttl else {})}), encoding="utf-8")
        os.replace(tmp, d / f"{k}.qloo")

    def get(self, path: str, params: dict | None = None) -> dict:
        """One Qloo call, asked once: a question already in flight (a verdict's prefetch, the full card asking the same)
        is waited for and then read from the cache, never sent twice."""
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        key = cache_key("POST" if any(k in POST_ONLY for k in clean) else "GET", path, clean)
        lock = self.__dict__.setdefault("_flight_lock", threading.Lock())
        flight = self.__dict__.setdefault("_flight", {})
        with lock:
            waiting = flight.get(key)
            if waiting is None:
                flight[key] = threading.Event()
        if waiting is not None:
            waiting.wait(timeout=TIMEOUT_S + 5)
            return self._get(path, params)
        try:
            return self._get(path, params)
        finally:
            with lock:
                flight.pop(key).set()

    def _get(self, path: str, params: dict | None = None) -> dict:
        """One Qloo call, noted in RECENT whatever its end (answered, cached, refused, not sent)."""
        t0 = time.monotonic()
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        method = "POST" if any(k in POST_ONLY for k in clean) else "GET"
        try:
            got = self._ask(path, params)
        except QlooError as why:
            note(f"{method} {path}", clean, _status(why), (time.monotonic() - t0) * 1000, "cached refusal" in str(why))
            raise
        note(f"{method} {path}", clean, 200, (time.monotonic() - t0) * 1000, bool(got.get("source", {}).get("cached")))
        return got

    def _ask(self, path: str, params: dict | None = None) -> dict:
        """One Qloo call. GET, except when a parameter Qloo takes only in a JSON body is set (POST_ONLY): then POST."""
        params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        try:                                                # every parameter documented by Qloo for this endpoint and filter.type,
            qloo_guard.check(path, params)                  # or nothing is sent (knos_wanted.qloo_guard)
        except qloo_guard.InvalidParameter as why:
            raise QlooError(str(why)) from None
        method = "POST" if any(k in POST_ONLY for k in params) else "GET"
        if forced():
            raise QlooError(f"{method} {path}: HTTP {forced()} (test mode)")
        k = cache_key(method, path, params)
        src = {"call": f"{method} {path}", "params": params}
        hit = self._cached(k)
        if hit is not None and hit.get("error"):
            raise QlooError(hit["error"] + " (cached refusal)")
        if hit is not None:
            _today()["hits"] += 1
            return {"body": trim(hit["body"]), "source": {**src, "cached": True, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(hit["t"])),
                                                     **({"surface": hit["surface"]} if hit.get("surface") else {})}}
        ok, why = self.ready()
        if not ok:
            raise NoKey(why)
        if held():                                          # Qloo said 429: nothing is sent until its Retry-After has passed
            raise QlooError(f"{method} {path}: HTTP 429: Qloo asked for a pause; no request sent for {held():.0f} s more")
        why = refusal()                                     # Qloo's month (its own header) and this server's day
        if why:
            raise QlooError(f"{method} {path}: HTTP 429: not sent: {why}")
        self._count_one()
        self.bucket.take()
        m = qloo_harness.mapped(path, params) if self.harness and method == "GET" else None
        hb = qloo_harness.harness().call(*m) if m else None
        if hb is not None:                                  # Qloo's harness asked exactly this question (kit API_ACCESS)
            hb = trim(hb)
            self.live_calls += 1
            self._store(k, hb, surface=qloo_harness.SURFACE)
            return {"body": hb, "source": {**src, "surface": qloo_harness.SURFACE, "cached": False,
                                           "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock()))}}
        src["surface"] = "REST API"
        headers = {"x-api-key": self._key, "Accept": "application/json", "User-Agent": "knos-demand-check/0.3.34"}
        if method == "POST":
            req = urllib.request.Request(self.base + path, data=json.dumps(params).encode(), method="POST",
                                         headers={**headers, "Content-Type": "application/json"})
        else:
            req = urllib.request.Request(self.base + path + ("?" + urllib.parse.urlencode(params) if params else ""), headers=headers)
        body = None
        for attempt in range(2):
            try:
                with self.opener(req, timeout=TIMEOUT_S) as r:
                    raw = r.read(MAX_BYTES + 1)
                    _limits(getattr(r, "headers", None))
                if len(raw) > MAX_BYTES:
                    raise QlooError(f"{method} {path}: answer larger than {MAX_BYTES} bytes")
                body = json.loads(raw or b"{}")
                _seen(200, path)
                break
            except urllib.error.HTTPError as e:
                _seen(e.code, path)
                _limits(e.headers)
                if e.code == 429:                            # never asked again at once: wait what Qloo says (Retry-After)
                    wait = retry_after(e.headers.get("Retry-After") if e.headers else None)
                    _hold["until"] = max(_hold["until"], time.time() + wait)
                    print(f"knos qloo: HTTP 429 on {method} {path}; no Qloo request for {wait:.0f} s"
                          f" ({'Retry-After' if e.headers and e.headers.get('Retry-After') else 'no Retry-After: the default'})", flush=True)
                if e.code in (500, 502, 503, 504) and attempt == 0:
                    time.sleep(1.0)
                    continue
                self.live_calls += 1
                msg = f"{method} {path}: HTTP {e.code}"     # Qloo's own error text is not passed on to users
                if e.code in (401, 403):                     # said plainly, never a silent fallback (kit docs/API_ACCESS.md)
                    msg += ": Qloo refused this server's API key (missing, wrong or expired); no Qloo data was used"
                elif e.code == 429:
                    msg += f": Qloo's rate limit for this key was reached; nothing is sent to Qloo for {held():.0f} s"
                if 400 <= e.code < 500 and e.code != 429:
                    self._store(k, None, error=msg)  # a refused question is not asked again for a day
                raise QlooError(msg) from None
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                if isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):
                    # no answer within TIMEOUT_S: asking again at once only doubles the wait (24 Oct 2026: 2 x 2 x 45 s
                    # on one places question made a check take 183 s); the caller's lighter question goes next
                    self.live_calls += 1
                    msg = f"{method} {path}: Qloo did not answer within {TIMEOUT_S:g} s"
                    self._store(k, None, error=msg, ttl=SLOW_TTL_S)
                    raise QlooError(msg) from None
                if attempt == 0:
                    time.sleep(1.0)
                    continue
                raise QlooError(f"{method} {path}: {type(e).__name__}") from None
        self.live_calls += 1
        body = trim(body)
        self._store(k, body, surface="REST API")
        return {"body": body, "source": {**src, "cached": False, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock()))}}
