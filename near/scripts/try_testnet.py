"""Try Knos on testnet from a fresh clone: your own copy of the contract, a release and a refund, in a few minutes.

    near account create-account sponsor-by-faucet-service <you>.testnet autogenerate-new-keypair save-to-legacy-keychain network-config testnet create
    NEAR_CLI=near python near/scripts/try_testnet.py <you>.testnet

From <you>.testnet it makes sub-accounts (each funded with a little of its test NEAR, no faucet): the contract, a test
token, a payee and three owners. It deploys near/wasm/ (built from this folder; sha256 in near/wasm/SHA256SUMS), sets a
test RSA key by two owners (standing in for GitHub's), then funds a milestone and releases it on a signed token, and
funds a second with a 1-minute deadline and refunds it. Every step prints its testnet transaction.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

NEAR = os.environ.get("NEAR_CLI", "near")
RPC = "https://rpc.testnet.near.org"
WASM = Path(__file__).resolve().parents[1] / "wasm"
REPO = "you/your-repo"
WF = f"{REPO}/.github/workflows/proof.yml@refs/heads/main"
EXPLORER = "https://explorer.testnet.near.org/transactions/"


def rpc(method: str, params) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    with urllib.request.urlopen(urllib.request.Request(RPC, body, {"Content-Type": "application/json"}), timeout=180) as r:
        out = json.loads(r.read())
    if "error" in out:
        raise RuntimeError(json.dumps(out["error"])[:300])
    return out["result"]


def near(*args: str) -> str:
    p = subprocess.run([NEAR, *args], capture_output=True, text=True, timeout=300)
    return re.sub(r"\x1b\[[0-9;]*m", "", p.stdout + p.stderr)


def tx_id(text: str) -> str:
    m = re.findall(r"Transaction ID: ([1-9A-HJ-NP-Za-km-z]{43,44})", text)
    return m[-1] if m else ""


def call(who: str, contract: str, method: str, args: dict, deposit: str) -> tuple[bool, str, str]:
    text = near("contract", "call-function", "as-transaction", contract, method, "json-args", json.dumps(args), "prepaid-gas", "100 Tgas",
                "attached-deposit", deposit, "sign-as", who, "network-config", "testnet", "sign-with-legacy-keychain", "display")
    m = re.search(r"Signed transaction \(serialized as base64\):\s*([A-Za-z0-9+/=]{100,})", text)
    if not m:
        raise RuntimeError(f"near did not sign {method} for {who}")
    r = rpc("send_tx", {"signed_tx_base64": m.group(1), "wait_until": "FINAL"})
    fail = next((o["outcome"]["status"]["Failure"] for o in [r["transaction_outcome"]] + r["receipts_outcome"] if "Failure" in o["outcome"]["status"]), None)
    val = r["status"].get("SuccessValue", "")
    return fail is None, r["transaction"]["hash"], json.dumps(fail)[:200] if fail else (base64.b64decode(val).decode(errors="replace") if val else "ok")


def step(n: int, what: str, ok: bool, tx: str, said: str = "") -> None:
    print(f"{n}. {what}: {'done' if ok else 'FAILED'} {EXPLORER + tx if tx else ''} {said}".rstrip(), flush=True)
    if not ok:
        sys.exit(1)


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    you = sys.argv[1]
    t0 = time.time()
    tag = time.strftime("%H%M%S", time.gmtime())
    names = {k: f"{k}{tag}.{you}" for k in ("knos", "usdc", "payee", "own1", "own2", "own3")}
    for i, (k, acct) in enumerate(names.items(), 1):
        amount = {"knos": "2.6 NEAR", "usdc": "1.7 NEAR"}.get(k, "0.2 NEAR")
        text = near("account", "create-account", "fund-myself", acct, amount, "autogenerate-new-keypair", "save-to-legacy-keychain",
                    "sign-as", you, "network-config", "testnet", "sign-with-legacy-keychain", "send")
        step(i, f"account {acct}", "created successfully" in text or "has been successfully created" in text, tx_id(text))
    for name, init in (("usdc", {"owner_id": you, "total_supply": "1000000000"}),
                       ("knos", {"usdc": names["usdc"], "owners": [names["own1"], names["own2"], names["own3"]]})):
        wasm = WASM / ("knos_mock_usdc.wasm" if name == "usdc" else "knos_near.wasm")
        text = near("contract", "deploy", names[name], "use-file", str(wasm), "with-init-call", "new", "json-args", json.dumps(init),
                    "prepaid-gas", "100 Tgas", "attached-deposit", "0 NEAR", "network-config", "testnet", "sign-with-legacy-keychain", "send")
        step(7 if name == "usdc" else 8, f"deploy {wasm.name} to {names[name]}", "successfully deployed" in text, tx_id(text))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    n = format(key.public_key().public_numbers().n, "0512x")
    call(names["own1"], names["knos"], "propose_key", {"kid": "try", "n_hex": n}, "0 NEAR")
    ok, tx, said = call(names["own2"], names["knos"], "propose_key", {"kid": "try", "n_hex": n}, "0 NEAR")
    step(9, "test key set by 2 of 3 owners", ok, tx, said)
    for acct in (names["knos"], names["payee"]):
        call(you, names["usdc"], "storage_deposit", {"account_id": acct, "registration_only": True}, "0.01 NEAR")
    crit = hashlib.sha256(b"your milestone's criteria").hexdigest()

    def fund(mid: str, seconds: int) -> tuple[bool, str, str]:
        msg = {"id": mid, "payee_chain": "near", "payee_address": names["payee"], "criteria_hash": crit, "repository": REPO, "workflow": WF,
               "deadline_ns": str((int(time.time()) + seconds) * 1_000_000_000)}
        return call(you, names["usdc"], "ft_transfer_call", {"receiver_id": names["knos"], "amount": "1000", "msg": json.dumps(msg)}, "1 yoctoNEAR")

    step(10, "fund milestone m1 with 1000 test units", *fund("m1", 3600))
    claims = {"iss": "https://token.actions.githubusercontent.com", "aud": names["knos"], "exp": int(time.time()) + 600, "jti": f"try-{tag}",
              "repository": REPO, "job_workflow_ref": WF, "sha": "0" * 40}
    signed = b64u(json.dumps({"alg": "RS256", "kid": "try", "typ": "JWT"}).encode()) + "." + b64u(json.dumps(claims).encode())
    tok = signed + "." + b64u(key.sign(signed.encode(), padding.PKCS1v15(), hashes.SHA256()))
    step(11, "release m1 on a signed token", *call(names["payee"], names["knos"], "release", {"id": "m1", "token": tok, "criteria_hash": crit}, "0 NEAR"))
    ok, tx, said = call(names["payee"], names["knos"], "release", {"id": "m1", "token": tok, "criteria_hash": crit}, "0 NEAR")
    step(12, "the same token again is refused", not ok, tx, "(refused, as it should be)")
    step(13, "fund milestone m2 with a 1-minute deadline", *fund("m2", 60))
    time.sleep(70)
    step(14, "refund m2 after its deadline", *call(names["payee"], names["knos"], "refund", {"id": "m2"}, "0 NEAR"))
    for mid in ("m1", "m2"):
        r = rpc("query", {"request_type": "call_function", "finality": "final", "account_id": names["knos"], "method_name": "get_milestone",
                          "args_base64": base64.b64encode(json.dumps({"id": mid}).encode()).decode()})
        print(f"   {mid}: {json.loads(bytes(r['result']))['state']}")
    print(f"done in {time.time() - t0:.0f} s; your contract: {names['knos']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
