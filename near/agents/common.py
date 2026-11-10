"""What the agents and the checker share: testnet calls through near-cli-rs, each signed with the caller's own key in
~/.near-credentials (a key never leaves that folder and is never printed), and the job's files.

An agent signs with a function-call key that may call only the jobs contract's take, submit and spend, with a gas
allowance (near/agents/setup_swarm.py adds it). It cannot send NEAR or add keys.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

NEAR = os.environ.get("NEAR_CLI", "near")
RPC = os.environ.get("NEAR_RPC", "https://rpc.testnet.near.org")
EXPLORER = "https://explorer.testnet.near.org/transactions/"
HERE = Path(__file__).resolve().parent
JOB_DIR = HERE / "job"
JOB_TEST = "test_hll.py"   # the locked check: HyperLogLog's promise (job/test_hll.py)
CONFIG = json.loads((HERE / "swarm.json").read_text(encoding="utf-8"))
# the hosted app posts and releases from its own capped account (live.knos-swarm-1105.testnet), not the maintainer's
CONFIG.update({k: os.environ[e] for k, e in (("payer", "KNOS_NEAR_PAYER"), ("relayer", "KNOS_NEAR_RELAYER")) if os.environ.get(e)})


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


RPC_SPARE = os.environ.get("NEAR_RPC_SPARE", "https://test.rpc.fastnear.com")   # asked when the first answers 429


def rpc(method: str, params) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for tries in range(5):   # a public RPC answers 429 when asked too fast: wait, then ask it or the spare again
        url = RPC if tries % 2 == 0 else RPC_SPARE
        try:
            with urllib.request.urlopen(urllib.request.Request(url, body, {"Content-Type": "application/json"}), timeout=180) as r:
                out = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or tries == 4:
                raise
            time.sleep(1.5 * (tries + 1))
    if "error" in out:
        raise RuntimeError(json.dumps(out["error"])[:300])
    return out["result"]


def view(contract: str, method: str, args: dict):
    r = rpc("query", {"request_type": "call_function", "finality": "final", "account_id": contract, "method_name": method,
                      "args_base64": base64.b64encode(json.dumps(args).encode()).decode()})
    return json.loads(bytes(r["result"]).decode() or "null")


def near(*args: str) -> str:
    p = subprocess.run([NEAR, *args], capture_output=True, text=True, timeout=300)
    return re.sub(r"\x1b\[[0-9;]*m", "", p.stdout + p.stderr)


B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58d(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(s) - len(s.lstrip("1"))) + raw


def _b58e(b: bytes) -> str:
    n, out = int.from_bytes(b, "big"), ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def _amount(text: str, unit: int) -> int:
    """'1 yoctoNEAR', '0 NEAR', '0.5 NEAR' or '100 Tgas' as an integer."""
    from decimal import Decimal
    num, _, name = text.strip().partition(" ")
    scale = {"yoctonear": 1, "near": 10**24, "tgas": 10**12, "gas": 1}.get(name.strip().lower(), unit)
    return int(Decimal(num) * scale)


def _keys() -> dict:
    """The signing keys of the hosted app: a JSON file {account: "ed25519:<secret>"} named by KNOS_NEAR_KEYS_FILE."""
    return json.loads(Path(os.environ["KNOS_NEAR_KEYS_FILE"]).read_text(encoding="utf-8"))


_PREFETCHED: dict = {}
_LAST_NONCE: dict = {}      # the last nonce this process signed with, per account
_SIGNING: dict = {}         # one lock per account: two threads never sign for one account at once


def prefetch(who: str) -> None:
    """Fetch `who`'s key nonce and a recent block hash now, for its next transaction (a block hash stays valid for
    about a day; the nonce is right while nothing else signs for `who` meanwhile)."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    secret = _b58d(_keys()[who].split(":", 1)[1])
    pub = secret[32:64] if len(secret) >= 64 else ed25519.Ed25519PrivateKey.from_private_bytes(secret[:32]).public_key().public_bytes_raw()
    ak = rpc("query", {"request_type": "view_access_key", "finality": "final", "account_id": who, "public_key": "ed25519:" + _b58e(pub)})
    _PREFETCHED[who] = (ak["nonce"], _b58d(rpc("block", {"finality": "final"})["header"]["hash"]), time.time())


def _py_signed(who: str, contract: str, method: str, args: dict, deposit: str, gas: str) -> str:
    """One FunctionCall transaction, borsh-encoded and signed here with ed25519 (the hosted app has no near-cli)."""
    import struct

    from cryptography.hazmat.primitives.asymmetric import ed25519
    secret = _b58d(_keys()[who].split(":", 1)[1])
    sk = ed25519.Ed25519PrivateKey.from_private_bytes(secret[:32])
    pub = secret[32:64] if len(secret) >= 64 else sk.public_key().public_bytes_raw()
    kept = _PREFETCHED.pop(who, None)
    if kept and time.time() - kept[2] < 3600:     # fetched while the job was readied: the click only signs and sends
        ak, block = {"nonce": kept[0]}, kept[1]
    else:
        ak = rpc("query", {"request_type": "view_access_key", "finality": "final", "account_id": who, "public_key": "ed25519:" + _b58e(pub)})
        block = _b58d(rpc("block", {"finality": "final"})["header"]["hash"])
    s = lambda t: struct.pack("<I", len(t.encode())) + t.encode()   # noqa: E731
    body = json.dumps(args).encode()
    action = bytes([2]) + s(method) + struct.pack("<I", len(body)) + body + struct.pack("<Q", _amount(gas, 10**12)) + _amount(deposit, 10**24).to_bytes(16, "little")
    nonce = max(int(ak["nonce"]), _LAST_NONCE.get(who, 0)) + 1   # a final read can lag this process's own last send
    _LAST_NONCE[who] = nonce
    tx = s(who) + b"\0" + pub + struct.pack("<Q", nonce) + s(contract) + block + struct.pack("<I", 1) + action
    return base64.b64encode(tx + b"\0" + sk.sign(hashlib.sha256(tx).digest())).decode()


def _send(who: str, signed: str, wait: str = "FINAL") -> dict:
    """send_tx, and when the RPC times out waiting (HTTP 408, or its TIMEOUT_ERROR), ask for the same transaction by its
    hash until it is final: a signed transaction's hash is the sha256 of its bytes without the 65-byte signature."""
    import time
    import urllib.error
    try:
        return rpc("send_tx", {"signed_tx_base64": signed, "wait_until": wait})
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, RuntimeError) as e:
        if isinstance(e, RuntimeError) and "TIMEOUT" not in str(e).upper():
            raise
        h = _b58e(hashlib.sha256(base64.b64decode(signed)[:-65]).digest())
        for _ in range(24):
            time.sleep(5)
            try:
                return rpc("tx", {"tx_hash": h, "sender_account_id": who, "wait_until": wait})
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, RuntimeError):
                continue
        raise RuntimeError(f"testnet did not finish transaction {h} in 2 minutes")


def call(who: str, contract: str, method: str, args: dict, deposit: str = "0 NEAR", gas: str = "100 Tgas", wait: str = "FINAL") -> dict:
    """One transaction signed by `who`; returns ok, the transaction hash, and the contract's answer or its refusal."""
    if os.environ.get("KNOS_NEAR_KEYS_FILE"):
        import threading
        with _SIGNING.setdefault(who, threading.Lock()):
            for n in range(3):   # a nonce another signer used meanwhile: read it afresh and sign again
                signed = _py_signed(who, contract, method, args, deposit, gas)
                try:
                    r = _send(who, signed, wait)
                    break
                except RuntimeError as e:
                    if "InvalidNonce" not in str(e) or n == 2:
                        raise
                    _PREFETCHED.pop(who, None)
                    _LAST_NONCE.pop(who, None)
                    time.sleep(1.5)
        return _outcome(r)
    else:
        text = near("contract", "call-function", "as-transaction", contract, method, "json-args", json.dumps(args), "prepaid-gas", gas,
                    "attached-deposit", deposit, "sign-as", who, "network-config", "testnet", "sign-with-legacy-keychain", "display")
        m = re.search(r"Signed transaction \(serialized as base64\):\s*([A-Za-z0-9+/=]{100,})", text)
        if not m:
            raise RuntimeError(f"near-cli did not sign {method} for {who}: {text[-300:]}")
        signed = m.group(1)
    return _outcome(_send(who, signed, wait))


def _outcome(r: dict) -> dict:
    outcomes = [r["transaction_outcome"]] + r["receipts_outcome"]
    fail = next((o["outcome"]["status"]["Failure"] for o in outcomes if "Failure" in o["outcome"]["status"]), None)
    val = r["status"].get("SuccessValue", "")
    said = json.dumps(fail) if fail else (base64.b64decode(val).decode(errors="replace") if val else "ok")
    m2 = re.search(r'"panic_msg":"Smart contract panicked: ([^"]+)"', said) or re.search(r"Smart contract panicked: ([^\"\\]+)", said)
    return {"ok": fail is None, "tx": r["transaction"]["hash"], "said": m2.group(1) if m2 else said[:300], "url": EXPLORER + r["transaction"]["hash"]}


def ft_balance(account: str) -> int:
    return int(view(CONFIG["token"], "ft_balance_of", {"account_id": account}) or 0)
