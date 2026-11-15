"""One polite reader for every research API Knos reads ideas from.

Each host gets the pace its own terms ask for (knos.ideas.sources.SOURCES says where each rule was read), one
request at a time, a User-Agent that names Knos, and a bounded retry on 429/503 that honours Retry-After. Nothing
here is cached on disk and no key is ever logged or returned: a key is read from the environment by the adapter that
needs it and sent only to its own host.

Fixture mode (offline tests, and sources whose key is missing): `Fetcher(fixtures={url: body})` answers from recorded
bodies and refuses any URL it has no body for; every answer then carries mode "fixture". `KNOS_IDEAS_FIXTURES=FILE`
makes every default Fetcher a fixture one (tests, offline demos). `KNOS_IDEAS_RECORD=DIR`
appends each live body to DIR/recorded.jsonl (for re-recording test fixtures by hand; never in CI; a URL that
carries a key is never written).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .. import version

USER_AGENT = f"Knos/{version()} (+https://github.com/drexthealpha/Knos)"
TIMEOUT_S = 30.0
RETRIES = 2

# seconds between two requests to one host (the slowest rule wins; sources.SOURCES cites each)
PACE = {
    "export.arxiv.org": 3.0,                 # arXiv API ToU: one request every three seconds, one connection
    "eutils.ncbi.nlm.nih.gov": 0.34,         # E-utilities: 3 requests/s without a key (10 with NCBI_API_KEY)
    "api.crossref.org": 0.2,                 # Crossref public pool: 5 requests/s, 1 at a time (polite: 10/s, 3)
    "api.openalex.org": 0.1,                 # OpenAlex: 10 requests/s without a key
    "www.ebi.ac.uk": 0.2,                    # Europe PMC: no published figure; Knos keeps 5/s
    "api.biorxiv.org": 0.5,                  # bioRxiv/medRxiv: no published figure; Knos keeps 2/s
    "clinicaltrials.gov": 0.2,               # ClinicalTrials.gov v2: no published figure; ~5/s observed without 429
    "pub.orcid.org": 0.1,                    # ORCID anonymous: 12 requests/s, burst 40, 25k reads/day per IP
    "api.github.com": 0.5,                   # GitHub REST: 60/hour without a token
    "api.uspto.gov": 0.3,                    # USPTO ODP: burst 1 (no parallel calls per key), 4-15 requests/s
}


class FetchError(RuntimeError):
    def __init__(self, url: str, status: int | None, said: str):
        super().__init__(f"{urllib.parse.urlsplit(url).netloc}: {said}")
        self.url, self.status = url, status


class NoFixture(FetchError):
    pass


def contact() -> str | None:
    """KNOS_CONTACT_EMAIL, when the operator set one: Crossref's polite pool and NCBI's `email` take it. Never a default."""
    v = (os.environ.get("KNOS_CONTACT_EMAIL") or "").strip()
    return v if "@" in v and " " not in v else None


def key(url: str) -> str:
    """The fixture key of a URL: its sha256 (so a key in a query string is never a file name)."""
    return hashlib.sha256(url.encode()).hexdigest()[:24]


def load_recorded(path: Path) -> dict:
    """A recorded.jsonl (one {"url", "read", "body"} per line), or a fixture .json ({"label", "responses": {url: body}}),
    as {url: body}."""
    if path.suffix == ".json":
        return dict(json.loads(path.read_text(encoding="utf-8"))["responses"])
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[row["url"]] = row["body"]
    return out


class Fetcher:
    """`get(url) -> (body text, mode)`. Live unless `fixtures` is given (a dict url -> body, or a directory of
    <key(url)>.txt files)."""

    def __init__(self, fixtures: dict | str | os.PathLike | None = None, opener=None):
        if fixtures is None and os.environ.get("KNOS_IDEAS_FIXTURES"):        # offline: every read from a fixture file
            fixtures = os.environ["KNOS_IDEAS_FIXTURES"]
        if fixtures is not None and not isinstance(fixtures, dict) and Path(fixtures).is_file():
            fixtures = load_recorded(Path(fixtures))
        self.fixtures = fixtures
        self.mode = "live" if fixtures is None else "fixture"
        self._open = opener or urllib.request.urlopen
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self.calls: list[str] = []

    def _fixture(self, url: str) -> str:
        f = self.fixtures
        if isinstance(f, dict):
            if url in f:
                v = f[url]
                return v if isinstance(v, str) else json.dumps(v)
            raise NoFixture(url, None, f"no recorded body for this request ({url})")
        p = Path(f) / f"{key(url)}.txt"            # type: ignore[arg-type]
        if not p.exists():
            raise NoFixture(url, None, f"no recorded body for this request ({url})")
        return p.read_text(encoding="utf-8")

    def get(self, url: str, headers: dict | None = None) -> tuple[str, str]:
        self.calls.append(url)
        if self.fixtures is not None:
            return self._fixture(url), "fixture"
        host = urllib.parse.urlsplit(url).netloc
        h = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
        for attempt in range(RETRIES + 1):
            with self._lock:                      # one request at a time, at the host's pace
                wait = self._last.get(host, 0.0) + PACE.get(host, 0.5) - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                try:
                    req = urllib.request.Request(url, headers=h)
                    with self._open(req, timeout=TIMEOUT_S) as r:   # noqa: S310 - https research APIs only
                        body = r.read().decode("utf-8", "replace")
                    self._last[host] = time.monotonic()
                    break
                except urllib.error.HTTPError as e:
                    self._last[host] = time.monotonic()
                    if e.code in (429, 503) and attempt < RETRIES:
                        retry = e.headers.get("Retry-After") if e.headers else None
                        delay = float(retry) if retry and retry.isdigit() else 5.0 * (attempt + 1)
                        time.sleep(min(delay, 30.0))
                        continue
                    raise FetchError(url, e.code, f"HTTP {e.code}") from None
                except (urllib.error.URLError, TimeoutError, OSError) as e:
                    raise FetchError(url, None, f"unreachable ({type(e).__name__})") from None
        rec = os.environ.get("KNOS_IDEAS_RECORD")
        if rec and "api_key=" not in url and "api-key=" not in url:
            Path(rec).mkdir(parents=True, exist_ok=True)
            with (Path(rec) / "recorded.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"url": url, "read": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "body": body}) + "\n")
        return body, "live"

    def json(self, url: str, headers: dict | None = None) -> tuple[dict, str]:
        body, mode = self.get(url, headers)
        try:
            return json.loads(body), mode
        except ValueError:
            raise FetchError(url, None, "the answer is not JSON") from None
