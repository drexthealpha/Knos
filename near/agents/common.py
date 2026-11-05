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
import urllib.request
from pathlib import Path

NEAR = os.environ.get("NEAR_CLI", "near")
RPC = os.environ.get("NEAR_RPC", "https://rpc.testnet.near.org")
EXPLORER = "https://explorer.testnet.near.org/transactions/"
HERE = Path(__file__).resolve().parent
JOB_DIR = HERE / "job"
CONFIG = json.loads((HERE / "swarm.json").read_text(encoding="utf-8"))


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rpc(method: str, params) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    with urllib.request.urlopen(urllib.request.Request(RPC, body, {"Content-Type": "application/json"}), timeout=180) as r:
        out = json.loads(r.read())
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


def call(who: str, contract: str, method: str, args: dict, deposit: str = "0 NEAR", gas: str = "100 Tgas") -> dict:
    """One transaction signed by `who`; returns ok, the transaction hash, and the contract's answer or its refusal."""
    text = near("contract", "call-function", "as-transaction", contract, method, "json-args", json.dumps(args), "prepaid-gas", gas,
                "attached-deposit", deposit, "sign-as", who, "network-config", "testnet", "sign-with-legacy-keychain", "display")
    m = re.search(r"Signed transaction \(serialized as base64\):\s*([A-Za-z0-9+/=]{100,})", text)
    if not m:
        raise RuntimeError(f"near-cli did not sign {method} for {who}: {text[-300:]}")
    r = rpc("send_tx", {"signed_tx_base64": m.group(1), "wait_until": "FINAL"})
    outcomes = [r["transaction_outcome"]] + r["receipts_outcome"]
    fail = next((o["outcome"]["status"]["Failure"] for o in outcomes if "Failure" in o["outcome"]["status"]), None)
    val = r["status"].get("SuccessValue", "")
    said = json.dumps(fail) if fail else (base64.b64decode(val).decode(errors="replace") if val else "ok")
    m2 = re.search(r'"panic_msg":"Smart contract panicked: ([^"]+)"', said) or re.search(r"Smart contract panicked: ([^\"\\]+)", said)
    return {"ok": fail is None, "tx": r["transaction"]["hash"], "said": m2.group(1) if m2 else said[:300], "url": EXPLORER + r["transaction"]["hash"]}


def ft_balance(account: str) -> int:
    return int(view(CONFIG["token"], "ft_balance_of", {"account_id": account}) or 0)
