"""How deep a transaction must be before Knos counts it, chosen per cluster.

    KNOS_COMMITMENT   processed | confirmed | finalized: always wins when set
    KNOS_ALPENGLOW    auto (default) | on | off: an operator's override of the detection below (never a date or a version)

`processed`: the node that answered has executed it (it can still be dropped by a fork). `confirmed`: a
supermajority voted on its block. `finalized`: its block is rooted. These are the cluster's own words
(https://solana.com/docs/rpc#configuring-state-commitment); Knos only chooses which one it waits for.

Alpenglow. A cluster that runs Alpenglow consensus finalizes a block in about 150 ms (the target, "an expectation, not
a constant"), where TowerBFT roots it about 12.8 s after it is confirmed; under Alpenglow `confirmed` and `finalized`
"become the same thing", new code should point at `finalized`, and `confirmed` "will be deprecated and removed in a
later release" (https://solana.com/upgrades/alpenglow, read 14 Oct 2026). So with no KNOS_COMMITMENT, Knos reads and
waits at:

    finalized   on a cluster whose RPC answers getAgGenesisCert with a certificate (Alpenglow is active)
    confirmed   on one that answers null (still TowerBFT), or "Method not found" (-32601: a node older than Agave 4.3,
                which cannot run Alpenglow), or does not answer: today's behaviour, never a 12.8 s wait per payment

getAgGenesisCert takes no parameters, reads from the finalized bank and returns null or {block: {slot, blockId},
signature: {signature, bitmap}} (https://solana.com/docs/rpc/http/getaggenesiscert; Agave rpc/src/rpc.rs
`get_ag_genesis_cert`, commit 722c8f4b; @solana/kit packages/rpc-api/src/getAgGenesisCert.ts). The answer is kept per
RPC URL: a certificate for the life of the process (a cluster does not go back to TowerBFT), null for TOWER_TTL_S (so
a long-running relay notices a migration, such as mainnet's on 21 Oct 2026, within minutes and with no restart), and
no answer for UNKNOWN_TTL_S.

`timed` / `timing_of` keep, per signature this process sent, how long it took from the send to the commitment it
waited for: "final in N ms" in the receipts and the payment comment. `summary` and `parse` turn such rows into the
p50 / p95 the stats page shows (docs/finality.json).
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

COMMITMENTS = ("processed", "confirmed", "finalized")
DEFAULT = "confirmed"           # the commitment on a TowerBFT cluster (and on one that cannot say what it runs)
ALPENGLOW_DEFAULT = "finalized"  # the commitment on an Alpenglow cluster: the same state as confirmed there
ENV = "KNOS_COMMITMENT"
ALPENGLOW_ENV = "KNOS_ALPENGLOW"
METHOD = "getAgGenesisCert"
METHOD_NOT_FOUND = -32601       # JSON-RPC "Method not found": a node older than Agave 4.3
TOWER_TTL_S = 600.0             # how long a "still TowerBFT" answer is kept
UNKNOWN_TTL_S = 60.0            # and a "no answer"
DETECT_TIMEOUT_S = 5.0
# Waits that depend on how fast a cluster finalizes. TowerBFT: a block is rooted ~12.8 s (32 slots of 400 ms) after it
# is confirmed, so a job that has already reported a payment waits up to 40 s for `finalized`. Alpenglow: finality is
# the target ~150 ms; what Knos measured on devnet send -> finalized (docs/finality.json) is well under 10 s at p95.
FINAL_WAIT_TOWER_S = 40.0
FINAL_WAIT_ALPENGLOW_S = 10.0
FIRST_POLL_ALPENGLOW_S = 0.25   # the fan-out ledger's first status read on Alpenglow (0.5 s, its POLL_S, on TowerBFT)


@dataclass(frozen=True)
class Consensus:
    """What one RPC said about the cluster's consensus."""
    active: bool                # Alpenglow is active
    why: str                    # cert | null | method-not-found | no-answer | forced-on | forced-off
    slot: int | None = None     # the certified block: the first block produced under Alpenglow
    block_id: str | None = None  # its block id, hex
    signers: int | None = None  # validators in the aggregate signature (bits set in the bitmap)
    at: float = 0.0             # time.time() of the answer

    def to_dict(self) -> dict:
        return asdict(self)


_CACHE: dict[str, tuple[Consensus, float]] = {}
_LOCK = threading.Lock()


def classify(kind: str, value: Any = None, code: int | None = None, at: float | None = None) -> Consensus:
    """One answer to getAgGenesisCert as a Consensus. `kind`: "result" (value = the result) or "error" (code = the
    JSON-RPC error code) or "none" (no answer at all). Only a certificate turns Alpenglow on; anything else keeps
    TowerBFT's behaviour."""
    when = time.time() if at is None else at
    if kind == "result":
        if value is None:
            return Consensus(False, "null", at=when)
        block = value.get("block") if isinstance(value, dict) else None
        sig = value.get("signature") if isinstance(value, dict) else None
        if isinstance(block, dict) and isinstance(block.get("slot"), int) and isinstance(sig, dict):
            bid = block.get("blockId")
            hexid = bytes(bid).hex() if isinstance(bid, list) and all(isinstance(b, int) and 0 <= b < 256 for b in bid) else None
            bitmap = sig.get("bitmap")
            signers = sum(bin(b).count("1") for b in bitmap) if isinstance(bitmap, list) and all(isinstance(b, int) for b in bitmap) else None
            return Consensus(True, "cert", int(block["slot"]), hexid, signers, when)
        return Consensus(False, "no-answer", at=when)       # a result that is no certificate: say nothing
    if kind == "error" and code == METHOD_NOT_FOUND:
        return Consensus(False, "method-not-found", at=when)
    return Consensus(False, "no-answer", at=when)


def _ask_default(url: str) -> Callable[[str, list], Any]:
    from .. import chain
    return lambda method, params: chain.call(url, method, params, timeout=DETECT_TIMEOUT_S)


def ask_rpc(url: str, ask: Callable[[str, list], Any] | None = None, at: float | None = None) -> Consensus:
    """Ask `url` once (no cache). `ask(method, params)` returns the result or raises; an error with a `code` attribute
    (knos.chain.RpcError) carries the JSON-RPC code."""
    try:
        got = (ask or _ask_default(url))(METHOD, [])
    except Exception as why:  # noqa: BLE001 - an RpcError is an answer; anything else is none
        code = getattr(why, "code", None)
        return classify("error", code=code, at=at) if code is not None else classify("none", at=at)
    return classify("result", got, at=at)


def forced() -> bool | None:
    word = os.environ.get(ALPENGLOW_ENV, "").strip().lower()
    if word in ("1", "on", "yes", "true"):
        return True
    if word in ("0", "off", "no", "false"):
        return False
    return None


def detect(url: str | None, ask: Callable[[str, list], Any] | None = None, now: float | None = None) -> Consensus:
    """The consensus of the cluster behind `url`, from the cache when it is fresh, else asked (one request)."""
    f = forced()
    if f is not None:
        return Consensus(f, "forced-on" if f else "forced-off", at=time.time())
    if not url or not str(url).startswith(("http://", "https://")):
        return Consensus(False, "no-answer", at=time.time())
    t = time.monotonic() if now is None else now
    with _LOCK:
        kept = _CACHE.get(url)
    if kept is not None and t < kept[1]:
        return kept[0]
    got = ask_rpc(url, ask)
    ttl = float("inf") if got.active else TOWER_TTL_S if got.why in ("null", "method-not-found") else UNKNOWN_TTL_S
    with _LOCK:
        _CACHE[url] = (got, t + ttl)
    return got


def forget(url: str | None = None) -> None:
    """Drop the cached answer for `url` (every URL with None)."""
    with _LOCK:
        if url is None:
            _CACHE.clear()
        else:
            _CACHE.pop(url, None)


def alpenglow(url: str | None, ask: Callable[[str, list], Any] | None = None) -> bool:
    return detect(url, ask).active


def commitment(value: str | None = None, url: str | None = None, ask: Callable[[str, list], Any] | None = None) -> str:
    """The commitment to read and wait at: `value`, else KNOS_COMMITMENT, else finalized on an Alpenglow cluster (`url`
    given and detected), else confirmed. ValueError for any other word."""
    word = value if value is not None else os.environ.get(ENV, "")
    if not str(word).strip():
        word = ALPENGLOW_DEFAULT if url and alpenglow(url, ask) else DEFAULT
    word = str(word).strip().lower()
    if word not in COMMITMENTS:
        raise ValueError(f"{ENV} must be one of {', '.join(COMMITMENTS)}; got {word!r}")
    return word


def at(url: str | None, ask: Callable[[str, list], Any] | None = None) -> str:
    """The commitment for `url`: what every hard-coded "confirmed" of Knos now asks for."""
    return commitment(None, url, ask)


def cached(url: str | None) -> str:
    """The commitment for `url` from what this process already knows (KNOS_COMMITMENT, KNOS_ALPENGLOW, or an answer a
    Ledger or a wait got for that URL), with no request of its own: for read-only checks whose requests are counted
    (the vault history reader, the mainnet check). Unknown: confirmed, which on Alpenglow is the same state."""
    word = os.environ.get(ENV, "").strip()
    if word:
        return commitment(word)
    return ALPENGLOW_DEFAULT if url and _cached_active(url) else DEFAULT


def of_call(call: Callable[[str, list], Any]) -> str:
    """The commitment for a reader that has only `call(method, params)` (no URL): asked through it once and kept on
    the function itself, so one verification asks one getAgGenesisCert however many transactions it reads."""
    kept = getattr(call, "_knos_commitment", None)
    if kept:
        return kept
    word = os.environ.get(ENV, "").strip()
    if word:
        return commitment(word)
    f = forced()
    got = (ALPENGLOW_DEFAULT if f else DEFAULT) if f is not None else (ALPENGLOW_DEFAULT if ask_rpc("", call).active else DEFAULT)
    try:
        call._knos_commitment = got      # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        pass
    return got


def good(value: str | None = None) -> tuple[str, ...]:
    """The confirmation statuses that satisfy a commitment: a deeper status always satisfies a shallower one."""
    c = commitment(value)
    return COMMITMENTS[COMMITMENTS.index(c):]


def reached(status: dict | None, value: str | None = None) -> bool:
    """Whether one entry of getSignatureStatuses has reached the commitment."""
    if not status:
        return False
    return status.get("confirmationStatus") in good(value)


def final_wait(url: str | None, ask=None) -> float:
    """Seconds to wait for `finalized` after a payment was reported (knos.flow)."""
    return FINAL_WAIT_ALPENGLOW_S if alpenglow(url, ask) else FINAL_WAIT_TOWER_S


def is_final(commitment_word: str | None) -> bool:
    """Whether a wait at this commitment means the payment cannot be rolled back: `finalized` always; on Alpenglow
    Knos waits at finalized by default, so "paid" is "paid and final"."""
    return commitment_word == "finalized"


# ---- send -> commitment, per signature this process sent ---------------------------------------------------------------
_TIMES: dict[str, dict] = {}
_KEEP = 2048


def timed(signature: str, sent: float, done: float, commitment_word: str, url: str | None = None) -> dict:
    """Note that `signature`, sent at `sent` (time.monotonic), reached `commitment_word` at `done`."""
    row = {"final_ms": max(0, round((done - sent) * 1000)), "commitment": commitment_word,
           "final": is_final(commitment_word), "alpenglow": _cached_active(url) if url else False}
    with _LOCK:
        if len(_TIMES) >= _KEEP:
            _TIMES.pop(next(iter(_TIMES)))
        _TIMES[signature] = row
    return row


def _cached_active(url: str) -> bool:
    f = forced()
    if f is not None:
        return f
    with _LOCK:
        kept = _CACHE.get(url)
    return bool(kept and kept[0].active)


def timing_of(signature: str | None) -> dict | None:
    """{final_ms, commitment, final, alpenglow} of a signature this process sent and waited for, else None."""
    if not signature:
        return None
    with _LOCK:
        got = _TIMES.get(str(signature))
    return dict(got) if got else None


def words(row: dict | None) -> str:
    """The user-facing state of a payment: "paid and final in N ms" once it is finalized, else "paid (confirmed)"."""
    if not row:
        return ""
    if row.get("final"):
        return f"paid and final in {int(row['final_ms'])} ms"
    return f"paid ({row.get('commitment')} in {int(row['final_ms'])} ms; final once the cluster finalizes it)"


# ---- the latency figures (docs/finality.json, stats.json) --------------------------------------------------------------
def percentile(values: list[float], q: float) -> float | None:
    """The q-th percentile (0..100) by the nearest-rank method; None for no values."""
    xs = sorted(float(v) for v in values)
    if not xs:
        return None
    k = max(1, -(-len(xs) * q // 100))
    return xs[int(min(k, len(xs))) - 1]


def summary(values: list[float]) -> dict:
    """{n, p50, p95, min, max} (milliseconds, rounded) of some latencies."""
    xs = [float(v) for v in values]
    r = lambda v: None if v is None else round(v)  # noqa: E731
    return {"n": len(xs), "p50": r(percentile(xs, 50)), "p95": r(percentile(xs, 95)),
            "min": r(min(xs)) if xs else None, "max": r(max(xs)) if xs else None}


def parse(lines, field: str = "finalized_ms") -> dict:
    """Rows of a measurement (JSON lines, or dicts) to {"all": summary, "by_kind": {kind: summary}, "skipped": n}.
    A row counts when it has a number in `field` and no "err"; the others are skipped (and counted)."""
    rows, skipped = [], 0
    for line in lines:
        if isinstance(line, str):
            line = line.strip()
            if not line:
                continue
            try:
                line = json.loads(line)
            except ValueError:
                skipped += 1
                continue
        v = line.get(field) if isinstance(line, dict) else None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or line.get("err"):
            skipped += 1
            continue
        rows.append((str(line.get("kind") or "?"), float(v)))
    kinds: dict[str, list[float]] = {}
    for k, v in rows:
        kinds.setdefault(k, []).append(v)
    return {"all": summary([v for _, v in rows]), "by_kind": {k: summary(vs) for k, vs in sorted(kinds.items())}, "skipped": skipped}
