"""Release a milestone from GitHub Actions with the run's own OIDC token, then show the same token refused twice.

    python3 near/scripts/release_ci.py        (in .github/workflows/near-release.yml; the standard library only)

Env: NEAR_RELEASE_KEY (an "ed25519:..." function-call key of NEAR_RELEASE_ACCOUNT, limited to `release` on the contract,
from an Actions secret), NEAR_RELEASE_ACCOUNT, KNOS_CONTRACT, MILESTONE (funded for this workflow: it is paid),
REUSE_MILESTONE (also funded for this workflow: the same token must be refused as used), OTHER_MILESTONE (funded for
another workflow: this token must be refused), CRITERIA_HASH. The token is asked for with the contract as its audience
and is never printed. Each transaction is signed here (Ed25519 as in RFC 8032, NEAR's borsh transaction) and sent to
the testnet RPC; the hashes, results and gas go to stdout and the run's summary. Exit 1 unless all three are as expected.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import sys
import time
import urllib.request

RPC = "https://rpc.testnet.near.org"
GAS = 100 * 10**12

# ---- Ed25519 (RFC 8032, section 6) ---------------------------------------------------------------------------------
P = 2**255 - 19
Q = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _add(a, b):
    x = (a[1] - a[0]) * (b[1] - b[0]) % P
    y = (a[1] + a[0]) * (b[1] + b[0]) % P
    c, d = 2 * a[3] * b[3] * D % P, 2 * a[2] * b[2] % P
    e, f, g, h = y - x, d - c, d + c, y + x
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(s: int, pt):
    acc = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            acc = _add(acc, pt)
        pt = _add(pt, pt)
        s >>= 1
    return acc


def _x(y: int, sign: int) -> int:
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * SQRT_M1 % P
    return P - x if (x & 1) != sign else x


_GY = 4 * pow(5, P - 2, P) % P
_GX = _x(_GY, 0)
G = (_GX, _GY, 1, _GX * _GY % P)


def _compress(pt) -> bytes:
    zi = pow(pt[2], P - 2, P)
    x, y = pt[0] * zi % P, pt[1] * zi % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _expand(seed: bytes) -> tuple[int, bytes]:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little") & ((1 << 254) - 8) | (1 << 254)
    return a, h[32:]


def public_key(seed: bytes) -> bytes:
    return _compress(_mul(_expand(seed)[0], G))


def sign(seed: bytes, msg: bytes) -> bytes:
    a, prefix = _expand(seed)
    pub = _compress(_mul(a, G))
    r = int.from_bytes(hashlib.sha512(prefix + msg).digest(), "little") % Q
    big_r = _compress(_mul(r, G))
    h = int.from_bytes(hashlib.sha512(big_r + pub + msg).digest(), "little") % Q
    return big_r + ((r + h * a) % Q).to_bytes(32, "little")


# ---- NEAR -----------------------------------------------------------------------------------------------------------
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58d(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(s) - len(s.lstrip("1"))) + raw


def b58e(b: bytes) -> str:
    n, out = int.from_bytes(b, "big"), ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def _s(v: str) -> bytes:
    raw = v.encode()
    return struct.pack("<I", len(raw)) + raw


def transaction(signer: str, pub: bytes, nonce: int, receiver: str, block_hash: bytes, method: str, args: dict) -> bytes:
    """A v0 Transaction with one FunctionCall action (borsh), no deposit."""
    body = json.dumps(args, separators=(",", ":")).encode()
    action = b"\x02" + _s(method) + struct.pack("<I", len(body)) + body + struct.pack("<Q", GAS) + (0).to_bytes(16, "little")
    return (_s(signer) + b"\x00" + pub + struct.pack("<Q", nonce) + _s(receiver) + block_hash
            + struct.pack("<I", 1) + action)


def signed(tx: bytes, seed: bytes) -> bytes:
    return tx + b"\x00" + sign(seed, hashlib.sha256(tx).digest())


def rpc(method: str, params) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for _ in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(RPC, body, {"Content-Type": "application/json"}), timeout=90) as r:
                out = json.loads(r.read())
            if "result" in out:
                return out["result"]
            if "error" in out and method == "send_tx":
                return {"error": out["error"]}
        except OSError:
            pass
        time.sleep(3)
    raise RuntimeError(f"rpc {method} failed")


def view(contract: str, method: str, args: dict):
    r = rpc("query", {"request_type": "call_function", "finality": "final", "account_id": contract, "method_name": method,
                      "args_base64": base64.b64encode(json.dumps(args).encode()).decode()})
    return json.loads(bytes(r["result"]))


def outcome(r: dict) -> tuple[bool, str, float]:
    """(every receipt succeeded, the first panic or the returned value, Tgas burnt over the transaction and its receipts)"""
    outs = [r["transaction_outcome"]] + r["receipts_outcome"]
    tgas = sum(o["outcome"]["gas_burnt"] for o in outs) / 1e12
    for o in outs:
        st = o["outcome"]["status"]
        if "Failure" in st:
            msg = json.dumps(st["Failure"])
            i = msg.find("Smart contract panicked: ")
            return False, (msg[i + 25:].split('"')[0].split("\\")[0] if i >= 0 else msg[:160]), tgas
    val = r["status"].get("SuccessValue", "")
    return True, base64.b64decode(val).decode(errors="replace").strip('"') if val else "ok", tgas


def oidc(audience: str) -> str:
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=" + audience
    req = urllib.request.Request(url, headers={"Authorization": "bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["value"]


def main() -> int:
    contract, account = os.environ["KNOS_CONTRACT"], os.environ["NEAR_RELEASE_ACCOUNT"]
    raw = b58d(os.environ["NEAR_RELEASE_KEY"].split(":", 1)[1])
    seed, pub = raw[:32], public_key(raw[:32])
    if len(raw) == 64 and raw[32:] != pub:
        print("NEAR_RELEASE_KEY: its public half does not match its seed")
        return 1
    crit = os.environ["CRITERIA_HASH"]
    token = oidc(contract)
    usdc = view(contract, "get_rules", {})["usdc"]
    first = view(contract, "get_milestone", {"id": os.environ["MILESTONE"]}) or {}
    payee = first.get("payee_address", "")
    before = int(view(usdc, "ft_balance_of", {"account_id": payee})) if payee else 0
    plan = [("MILESTONE", True, "paid"), ("REUSE_MILESTONE", False, "this token was already used"),
            ("OTHER_MILESTONE", False, "the token comes from another workflow")]
    lines, bad = [f"signer {account}, key ed25519:{b58e(pub)}, contract {contract}"], 0
    for env, want_ok, want in plan:
        mid = os.environ[env]
        ak = rpc("query", {"request_type": "view_access_key", "finality": "final", "account_id": account,
                           "public_key": "ed25519:" + b58e(pub)})
        tx = transaction(account, pub, ak["nonce"] + 1, contract, b58d(ak["block_hash"]), "release",
                         {"id": mid, "token": token, "criteria_hash": crit})
        r = rpc("send_tx", {"signed_tx_base64": base64.b64encode(signed(tx, seed)).decode(), "wait_until": "FINAL"})
        if "error" in r:
            bad += 1
            lines.append(f"{env} {mid}: the RPC refused the transaction: {json.dumps(r['error'])[:200]}")
            continue
        ok, why, tgas = outcome(r)
        good = ok == want_ok and (want in why.lower() if not want_ok else True)
        bad += not good
        lines.append(f"{'PASS' if good else 'FAIL'} {env} {mid}: {'done' if ok else 'refused'}: {why}; tx {r['transaction']['hash']}; {tgas:.2f} Tgas")
    after = int(view(usdc, "ft_balance_of", {"account_id": payee})) if payee else 0
    state = (view(contract, "get_milestone", {"id": os.environ["MILESTONE"]}) or {}).get("state")
    paid = after - before == int(first.get("amount") or -1)
    bad += not paid
    lines.append(f"{'PASS' if paid else 'FAIL'} payee {payee}: {before} -> {after} test units (+{after - before}, the milestone's amount {first.get('amount')}); state {state}")
    text = "\n".join(lines)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("```\n" + text + "\n```\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
