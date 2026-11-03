"""Set GitHub's live OIDC signing keys on the contract: two owners send the same propose_key for each key GitHub
publishes, then the contract's key set is read back. Prints kid, the two transaction hashes and what the contract said.

    NEAR_CLI=<path to near> python near/scripts/github_keys.py [result file]

The owners sign with near-cli's legacy keychain (~/.near-credentials, never read here). Keys the contract already holds
with the same modulus are skipped. Nothing else changes: keys GitHub no longer publishes stay until owners remove them.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

NEAR = os.environ.get("NEAR_CLI", "near")
RPC = "https://rpc.testnet.near.org"
JWKS = "https://token.actions.githubusercontent.com/.well-known/jwks"
KNOS = os.environ.get("KNOS_CONTRACT", "knos-pay-1103.testnet")
OWNERS = ("knos-own1-1102.testnet", "knos-own2-1102.testnet")


def rpc(method: str, params) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for _ in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(RPC, body, {"Content-Type": "application/json"}), timeout=60) as r:
                out = json.loads(r.read())
            if "result" in out:
                return out["result"]
        except OSError:
            pass
        time.sleep(3)
    raise RuntimeError(f"rpc {method} failed")


def rules() -> dict:
    r = rpc("query", {"request_type": "call_function", "finality": "final", "account_id": KNOS, "method_name": "get_rules",
                      "args_base64": base64.b64encode(b"{}").decode()})
    return json.loads(bytes(r["result"]))


def call(who: str, args: dict) -> tuple[str, bool, str]:
    cmd = [NEAR, "contract", "call-function", "as-transaction", KNOS, "propose_key", "json-args", json.dumps(args),
           "prepaid-gas", "100 Tgas", "attached-deposit", "0 NEAR", "sign-as", who, "network-config", "testnet",
           "sign-with-legacy-keychain", "display"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    text = re.sub(r"\x1b\[[0-9;]*m", "", p.stdout + p.stderr)
    m = re.search(r"Signed transaction \(serialized as base64\):\s*([A-Za-z0-9+/=]{100,})", text)
    if not m:
        return "", False, "not signed: " + (text.strip().splitlines() or ["?"])[-1][:120]
    r = rpc("send_tx", {"signed_tx_base64": m.group(1), "wait_until": "FINAL"})
    for o in [r["transaction_outcome"]] + r["receipts_outcome"]:
        if "Failure" in o["outcome"]["status"]:
            return r["transaction"]["hash"], False, json.dumps(o["outcome"]["status"]["Failure"])[:160]
    val = r["status"].get("SuccessValue", "")
    return r["transaction"]["hash"], True, base64.b64decode(val).decode(errors="replace").strip('"') if val else "ok"


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else None
    with urllib.request.urlopen(JWKS, timeout=60) as r:
        keys = [k for k in json.loads(r.read())["keys"] if k.get("kty") == "RSA"]
    have = {k["kid"]: k["n"] for k in rules()["keys"]}
    lines, bad = [], 0
    for k in keys:
        n_hex = base64.urlsafe_b64decode(k["n"] + "=" * (-len(k["n"]) % 4)).hex()
        if have.get(k["kid"]) == n_hex:
            lines.append(f"{k['kid']}: already set, skipped")
            continue
        sent = [call(who, {"kid": k["kid"], "n_hex": n_hex}) for who in OWNERS]
        ok = all(s[1] for s in sent) and "set by 2 owners" in sent[1][2]
        bad += not ok
        lines.append(f"{k['kid']}: {'set' if ok else 'NOT SET'}; {OWNERS[0]} {sent[0][0]} ({sent[0][2]}); {OWNERS[1]} {sent[1][0]} ({sent[1][2]})")
    after = {k["kid"]: k["n"] for k in rules()["keys"]}
    for k in keys:
        n_hex = base64.urlsafe_b64decode(k["n"] + "=" * (-len(k["n"]) % 4)).hex()
        held = after.get(k["kid"]) == n_hex
        bad += not held
        lines.append(f"read back {k['kid']}: {'held, same modulus' if held else 'MISSING'}")
    lines.append(f"contract {KNOS} holds {len(after)} keys: {', '.join(after)}")
    text = "\n".join(lines)
    print(text)
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
