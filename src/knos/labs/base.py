"""The lab adapter interface: one shape for every cloud lab, fab and ground-truth service Knos sends work to.

    quote(spec)                 -> Quote      price, currency, turnaround, what the quote is valid for
    order(spec, `escrow_ref`)     -> Order      the lab's order id, bound to the Knos vault that will pay it
    status(order)               -> Status     one of STATES, with the lab's own word kept beside it
    results(order)              -> Results    data + QC + raw files, INCLUDING failed runs (a failed run is a result)

Every adapter runs in one of two modes:

    fixture   recorded or documented responses from the repository (labelled in every file and every answer:
              `fixture: true` and the label of where the response came from). Tests and CI use only this mode.
    live      the user's OWN key for that lab (bring your own key, BYOK), read from one environment variable and
              never printed, logged, recorded or sent anywhere but the lab's own documented host. Knos never resells a
              lab's service: the order is the user's, at the lab's price; Knos holds the vault and gives the verdicts.

A live call that would spend money (an order, accepting a quote) also needs KNOS_LABS_LIVE_ORDERS=1, so a stray key in
an environment can quote but never order by accident.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

FIXTURES = Path(__file__).with_name("fixtures")
# the states every lab's own words map to; "failed" is a run that finished and did not work (it still has results)
STATES = ("draft", "quoted", "submitted", "in_progress", "qc", "completed", "failed", "cancelled")
DRAFT, QUOTED, SUBMITTED, IN_PROGRESS, QC, COMPLETED, FAILED, CANCELLED = STATES
SPEC_FIELDS = ("field", "protocol", "qc", "claim", "title")      # the names of a Spec's fields (dataclass order)
FX_STATUS, FX_BODY, FX_HEADERS = "status", "body", "headers"     # the keys of one recorded response in a fixture file
ERROR_KEYS = ("detail", "message", "error", "Message", "msg", "text")   # where labs put the reason of a refusal
LIVE_ORDERS = "KNOS_LABS_LIVE_ORDERS"


class LabError(Exception):
    """The lab, or the adapter, refused: one sentence saying why."""


class NoKey(LabError):
    """Live mode needs the user's own key for this lab; the message names the environment variable (never a value)."""


def sha256_hex(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


@dataclass
class Spec:
    """What is to be made or measured. `field`: proteins, chemistry, materials, electronics, mechanical, robotics,
    or any other science. `protocol`: the lab-specific body (the adapter checks it). `qc`: the QC the LAB verdict holds
    the lab to (protocol executed + these checks). `claim`: what the researcher says the result will show; the
    OUTCOME verdict holds the result to it. The lab sees `protocol`; `claim` never goes to the lab."""
    field: str
    protocol: dict
    qc: dict = dataclasses.field(default_factory=dict)       # dataclasses.field: in this class `field` names the str above
    claim: dict = dataclasses.field(default_factory=dict)
    title: str = ""

    def hash(self) -> str:
        return sha256_hex(canonical({"field": self.field, "protocol": self.protocol, "qc": self.qc, "claim": self.claim}))


@dataclass
class Quote:
    lab: str
    amount_usd: str              # decimal string, never a float
    currency: str = "USD"
    turnaround_days: int | None = None
    quote_id: str | None = None
    valid_until: str | None = None
    lines: list[dict] = field(default_factory=list)
    payment_methods: list[str] = field(default_factory=list)
    fixture: bool = False
    source: str = ""             # the label of a fixture, or the lab's endpoint for a live answer
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Order:
    lab: str
    order_id: str
    escrow_ref: str              # the Knos vault that pays this order (an address on devnet)
    spec_hash: str
    state: str = "submitted"
    fixture: bool = False
    source: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Status:
    lab: str
    order_id: str
    state: str                   # one of STATES
    lab_state: str               # the lab's own word, kept
    fixture: bool = False
    source: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Results:
    """What came back. `runs`: one entry per run or replicate, each {"id", "ok", "measurements", "qc", "why"} where a
    failed run has ok False and says why (no expression, open circuit, failed reaction...). `qc`: the lab's own QC
    summary. `files`: raw files as {"name", "sha256", "bytes", "url"?}: the hashes are what the verdict binds."""
    lab: str
    order_id: str
    state: str
    runs: list[dict]
    qc: dict
    files: list[dict] = field(default_factory=list)
    protocol_executed: dict = field(default_factory=dict)
    fixture: bool = False
    source: str = ""
    raw: dict = field(default_factory=dict)

    def evidence_hash(self) -> str:
        """sha256 of everything the verdicts read: runs, QC, the protocol as executed, and every file's hash."""
        return sha256_hex(canonical({"lab": self.lab, "order_id": self.order_id, "state": self.state, "runs": self.runs,
                                     "qc": self.qc, "files": sorted(f.get("sha256", "") for f in self.files),
                                     "protocol_executed": self.protocol_executed}))

    def to_dict(self) -> dict:
        return {**asdict(self), "evidence_hash": self.evidence_hash()}


# ---- transports ------------------------------------------------------------------------------------------------------

Transport = Callable[[str, str, dict | None, dict], tuple[int, dict, dict]]
"""(method, url, json body or None, headers) -> (http status, json answer, response headers)."""


def http(method: str, url: str, body: dict | None, headers: dict, timeout: float = 30.0) -> tuple[int, dict, dict]:
    """A plain HTTPS call (urllib). Only an adapter's own documented host is ever called."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Accept": "application/json", "User-Agent": "knos-labs", **headers,
                                          **({"Content-Type": "application/json"} if data is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - the lab's https URL
            raw = r.read() or b"{}"
            return r.status, _json(raw), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, _json(e.read() or b"{}"), dict(e.headers or {})
    except (OSError, ValueError) as why:
        raise LabError(f"{urllib.parse.urlsplit(url).netloc} did not answer ({type(why).__name__})") from None


def _json(raw: bytes) -> dict:
    try:
        got = json.loads(raw)
    except ValueError:
        return {"text": raw[:2000].decode("utf-8", "replace")}
    return got if isinstance(got, dict) else {"data": got}


class Fixtures:
    """Recorded responses for one lab: fixtures/<lab>.json = {"label": ..., "source": ..., "responses": {"METHOD path":
    {"status", "body", "headers"?}}}. A request with no recorded response is refused, never invented."""

    def __init__(self, lab: str, path: Path | None = None):
        self.path = path or FIXTURES / f"{lab}.json"
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        self.label = doc["label"]
        self.source = doc.get("source", "")
        self.responses = doc["responses"]
        self.files = doc.get("files", {})          # url -> sha256 of a recorded raw file (made up in a mock)
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method: str, url: str, body: dict | None, headers: dict) -> tuple[int, dict, dict]:
        path = urllib.parse.urlsplit(url).path
        query = urllib.parse.urlsplit(url).query
        self.calls.append((method, path + (f"?{query}" if query else ""), body))
        for key in (f"{method} {path}?{query}" if query else None, f"{method} {path}"):
            if key and key in self.responses:
                r = self.responses[key]
                return int(r.get(FX_STATUS, 200)), r.get(FX_BODY, {}), r.get(FX_HEADERS, {})
        raise LabError(f"no recorded response for {method} {path} in {self.path.name} (fixture mode never invents one)")


class Adapter:
    """One lab. Subclasses set NAME, FIELD, KEY_ENV (None: no key needed), BASE (the documented API root), DOCS (the
    page every endpoint was read from) and implement the four calls with `_call`."""
    NAME = ""
    FIELD = ""
    KEY_ENV: str | None = None
    BASE = ""
    DOCS = ""
    LIVE_READY = False           # True only when every endpoint and field was checked against the lab's own docs
    ORDERS = True                # False: a ground-truth service (nothing is bought, the "order" is a query)

    def __init__(self, mode: str = "fixture", transport: Transport | None = None, key: str | None = None,
                 base: str | None = None):
        if mode not in ("fixture", "live"):
            raise LabError("mode: fixture or live")
        self.mode = mode
        self.base = (base or os.environ.get(f"KNOS_{self.NAME.upper()}_BASE") or self.BASE).rstrip("/")
        self._key = key
        self.fixtures: Fixtures | None             # None: live, or an adapter with no recorded responses
        self.transport: Transport | None           # None: an adapter that never calls a lab (manual, robotics)
        if mode == "fixture":
            fixtures = Fixtures(self.NAME)
            self.fixtures = fixtures
            self.transport = transport or fixtures
        else:
            self.fixtures = None
            self.transport = transport or http

    # -- the key, never shown -----------------------------------------------------------------------------------------
    def key(self) -> str | None:
        if self.KEY_ENV is None:
            return None
        if self.mode == "fixture":
            return "fixture-key-not-real"
        got = self._key or os.environ.get(self.KEY_ENV)
        if not got:
            raise NoKey(f"{self.NAME}: live mode needs your own key in ${self.KEY_ENV} (bring your own key; Knos never holds or resells one)")
        return got

    def auth_headers(self) -> dict:
        return {}

    def __repr__(self) -> str:          # never the key
        return f"<knos.labs {self.NAME} {self.mode}>"

    @property
    def is_fixture(self) -> bool:
        return self.mode == "fixture"

    @property
    def label(self) -> str:
        return self.fixtures.label if self.fixtures else f"live: {self.base}"

    def _call(self, method: str, path: str, body: dict | None = None, *, spends: bool = False,
              ok: tuple[int, ...] = (200, 201, 202), headers: dict | None = None) -> tuple[int, dict, dict]:
        if spends and self.mode == "live" and os.environ.get(LIVE_ORDERS) != "1":
            raise LabError(f"{self.NAME}: a live order spends money; set {LIVE_ORDERS}=1 to allow it (Knos CI never does)")
        if self.transport is None:
            raise LabError(f"{self.NAME}: this adapter calls no lab")
        status, answer, got = self.transport(method, self.base + path, body, {**self.auth_headers(), **(headers or {})})
        if status not in ok:
            raise LabError(f"{self.NAME} answered {status} to {method} {path}: {_why(answer)}")
        return status, answer, got

    def file_hash(self, url: str, limit: int = 2 * 1024 ** 3) -> str | None:
        """sha256 of a raw file the lab returned: the verdicts bind these hashes. Fixture mode: the recorded hash.
        Live mode: the file is downloaded (it costs nothing) and hashed as it streams; None when it cannot be read."""
        if self.fixtures is not None:
            return self.fixtures.files.get(url)
        h, seen = hashlib.sha256(), 0
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "knos-labs"}), timeout=120) as r:  # noqa: S310
                while chunk := r.read(1 << 20):
                    seen += len(chunk)
                    if seen > limit:
                        return None
                    h.update(chunk)
        except (OSError, ValueError):
            return None
        return h.hexdigest()

    # -- the interface ------------------------------------------------------------------------------------------------
    def quote(self, spec: Spec) -> Quote:
        raise NotImplementedError

    def order(self, spec: Spec, escrow_ref: str, quote: Quote | None = None) -> Order:
        raise NotImplementedError

    def status(self, order: Order) -> Status:
        raise NotImplementedError

    def results(self, order: Order) -> Results:
        raise NotImplementedError

    def describe(self) -> dict:
        return {"lab": self.NAME, "field": self.FIELD, "mode": self.mode, "live_ready": self.LIVE_READY, "key_env": self.KEY_ENV,
                "base": self.BASE, "docs": self.DOCS, "orders": self.ORDERS,
                "fixture_label": self.fixtures.label if self.fixtures else None}


def _why(answer: dict) -> str:
    for k in ERROR_KEYS:
        v = answer.get(k) if isinstance(answer, dict) else None
        if v:
            return str(v)[:200]
    return json.dumps(answer)[:200]
