"""Priority fees and a right-sized compute budget for the transactions Knos sends (payouts, refunds, funding), and a
WebSocket wait for their confirmation. Off unless asked: KNOS_PRIORITY=auto (or a number of micro-lamports a compute
unit) and KNOS_WS=1.

    estimate(url, writable)      getRecentPrioritizationFees for the accounts the transaction writes: the 75th
                                 percentile of the recent slots' fees (zeros included), capped by KNOS_PRIORITY_MAX
    budget(ledger, ixs, payer)   [SetComputeUnitLimit(units the simulation used + 15%), SetComputeUnitPrice(estimate)]:
                                 a fee is paid on the LIMIT, so a limit of 1,400,000 where 40,000 are used would pay 35
                                 times the priority fee needed (https://solana.com/docs/core/fees/compute-budget)
    ws_url(url)                  the cluster's WebSocket endpoint (https -> wss; localnet 8899 -> 8900)
    wait_ws(url, signature)      signatureSubscribe: one notification when the transaction reaches the commitment,
                                 instead of a getSignatureStatuses request every 0.4 s (the public devnet endpoint
                                 allows 100 requests in 10 s per address: polling a slow payout spends that budget)

On a v1 transaction (Agave, SIMD-0385) the two instructions do nothing; knos.chain.message_v1 reads their values into
the message's own limit and priority fee, so the same `budget` serves both formats. RPC references read 14 Oct 2026:
https://solana.com/docs/rpc/http/getrecentprioritizationfees, /docs/rpc/http/simulatetransaction,
/docs/rpc/websocket/signaturesubscribe."""
from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import struct
import time
import urllib.parse

PERCENTILE = 75
DEFAULT_MAX = 200_000            # micro-lamports a unit: 0.2 lamports; a payout of 40,000 units then pays at most 8,000 lamports (0.000008 SOL) more
HEADROOM = 1.15
MIN_UNITS, MAX_UNITS = 5_000, 1_400_000


def mode() -> str | int | None:
    raw = (os.environ.get("KNOS_PRIORITY") or "").strip().lower()
    if not raw or raw in ("0", "off", "none"):
        return None
    if raw == "auto":
        return "auto"
    if raw.isdigit():
        return int(raw)
    raise ValueError(f"KNOS_PRIORITY is auto, a whole number of micro-lamports a compute unit, or unset; not {raw!r}")


def cap() -> int:
    raw = (os.environ.get("KNOS_PRIORITY_MAX") or "").strip()
    return int(raw) if raw.isdigit() else DEFAULT_MAX


def pick(fees: list[int], percentile: int = PERCENTILE) -> int:
    """The `percentile`-th of the recent fees (nearest rank), capped. [] (a node that keeps none): 0."""
    if not fees:
        return 0
    got = sorted(int(f) for f in fees)
    rank = max(1, -(-percentile * len(got) // 100))
    return min(got[rank - 1], cap())


def estimate(url: str, writable: list[str], call=None) -> int:
    from .. import chain
    rows = (call or chain.call)(url, "getRecentPrioritizationFees", [writable[:128]] if writable else [])
    return pick([r.get("prioritizationFee", 0) for r in rows or [] if isinstance(r, dict)])


def writable_of(ixs, payer) -> list[str]:
    seen: dict[str, None] = {str(payer): None}
    for ix in ixs:
        for a in ix.accounts:
            if a.is_writable:
                seen[str(a.pubkey)] = None
    return list(seen)


def units_used(ledger, ixs, payer, signers=None) -> int | None:
    """unitsConsumed of a simulation of these instructions (no fee, nothing changed), or None when it cannot say."""
    from solders.hash import Hash
    from .. import chain
    try:
        raw = base64.b64encode(bytes(chain.sign(ixs, payer, signers, Hash.default()))).decode()
        got = chain.call(ledger.url, "simulateTransaction", [raw, {"encoding": "base64", "sigVerify": False,
                                                                   "replaceRecentBlockhash": True, "commitment": getattr(ledger, "commitment", None) or "confirmed"}])["value"]
    except Exception:  # noqa: BLE001 - no estimate: the caller keeps its own limit
        return None
    if got.get("err") or not isinstance(got.get("unitsConsumed"), int):
        return None
    return int(got["unitsConsumed"])


def budget(ledger, ixs, payer, signers=None, call=None) -> list:
    """The two compute budget instructions to put first, or [] when KNOS_PRIORITY is unset or the instructions
    already bring a compute budget of their own."""
    from solders.compute_budget import ID as CB
    from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
    m = mode()
    if m is None or any(ix.program_id == CB for ix in ixs):
        return []
    price = m if isinstance(m, int) else estimate(ledger.url, writable_of(ixs, payer.pubkey()), call)
    used = units_used(ledger, [set_compute_unit_limit(MAX_UNITS), *ixs], payer, signers)
    limit = MAX_UNITS if used is None else max(MIN_UNITS, min(MAX_UNITS, int(used * HEADROOM) + 300))
    return [set_compute_unit_limit(limit), *([set_compute_unit_price(min(price, cap()))] if price else [])]


# -- WebSocket ------------------------------------------------------------------------------------------------------
def ws_url(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    scheme = "wss" if u.scheme == "https" else "ws"
    netloc = u.netloc
    if u.port == 8899:
        netloc = f"{u.hostname}:8900"
    return urllib.parse.urlunsplit((scheme, netloc, u.path or "/", u.query, ""))


class WS:
    """A minimal RFC 6455 client (text frames, masking, ping/pong, close): what one subscription needs, no package."""

    def __init__(self, url: str, timeout: float = 30.0):
        u = urllib.parse.urlsplit(url)
        port = u.port or (443 if u.scheme == "wss" else 80)
        raw = socket.create_connection((u.hostname, port), timeout=timeout)
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=u.hostname) if u.scheme == "wss" else raw
        key = base64.b64encode(os.urandom(16)).decode()
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {u.hostname}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nUser-Agent: knos\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("the WebSocket endpoint closed during the handshake")
            head += chunk
        line = head.split(b"\r\n", 1)[0]
        if b" 101 " not in line + b" ":
            raise ConnectionError(f"the WebSocket endpoint answered {line[:60]!r}")
        self.buf = head.split(b"\r\n\r\n", 1)[1]

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("the WebSocket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, obj, opcode: int = 1) -> None:
        data = json.dumps(obj).encode() if opcode == 1 else bytes(obj)
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x80 | opcode]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536
                                         else bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        """The next text message, as JSON; pings answered, close raised."""
        while True:
            b0, b1 = self._read(2)
            op, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b1 & 0x80 else b""
            data = self._read(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if op == 9:
                self.send(data, opcode=10)
            elif op == 8:
                raise ConnectionError("the WebSocket was closed by the endpoint")
            elif op in (1, 2):
                return json.loads(data)

    def close(self) -> None:
        try:
            self.send(b"", opcode=8)
        except OSError:
            pass
        self.sock.close()


def wait_ws(url: str, signature: str, within: float = 60.0, commitment: str | None = None, connect=None) -> dict:
    """signatureSubscribe and wait for its one notification: {"slot", "err"}. TimeoutError when none came in time,
    ValueError when the transaction failed on chain. `connect(ws_url)` gives a WS (tests give a fake)."""
    from . import finality
    commitment = commitment or finality.at(url)      # finalized on Alpenglow, else confirmed
    end = time.monotonic() + within
    ws = (connect or (lambda u: WS(u, timeout=min(within, 30.0))))(ws_url(url))
    try:
        ws.send({"jsonrpc": "2.0", "id": 1, "method": "signatureSubscribe", "params": [signature, {"commitment": commitment}]})
        while time.monotonic() < end:
            try:
                msg = ws.recv()
            except socket.timeout:
                continue
            if msg.get("method") == "signatureNotification":
                res = (msg.get("params") or {}).get("result") or {}
                value = res.get("value")
                if isinstance(value, dict):
                    if value.get("err") is not None:
                        raise ValueError(f"transaction failed: {value['err']}")
                    return {"slot": (res.get("context") or {}).get("slot"), "err": None}
            elif "error" in msg:
                raise ConnectionError(f"signatureSubscribe was refused: {msg['error']}")
        raise TimeoutError(f"{signature} not confirmed within {within:.0f}s")
    finally:
        ws.close()
