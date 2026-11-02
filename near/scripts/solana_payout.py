"""A Knos milestone paid on Solana devnet by NEAR Chain Signatures, end to end, each step a real transaction.

    NEAR_CLI=<near> SOL_FEE_KEY=<devnet key file> python near/scripts/solana_payout.py [result file]

On Solana devnet (fees from SOL_FEE_KEY, a JSON array of 64 bytes, never printed): a test SPL mint, a token account
owned by the contract's derived address (v1.signer-prod.testnet, path knos-solana-1, Ed25519) holding the payout,
and the payee's token account. On NEAR testnet: the milestone funded with payee_chain solana, released on a token,
then sign_payout with the unsigned transfer; the contract checks it and gets the MPC signature. This script adds that
signature and broadcasts the transfer. The relayer never holds the key that moves the payout.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import ssl
import struct
import subprocess
import sys
import time
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

NEAR = os.environ.get("NEAR_CLI", "near")
NRPC, SRPC = "https://rpc.testnet.near.org", "https://api.devnet.solana.com"
S = "1102"
KNOS, USDC, PAYER, PAYEE = f"knos-pay2-{S}.testnet", f"knos-usdc-{S}.testnet", f"knos-payer-{S}.testnet", f"knos-payee-{S}.testnet"
OWN = [f"knos-own{i}-{S}.testnet" for i in (1, 2, 3)]
SIGNER, PATH = "v1.signer-prod.testnet", "knos-solana-1"
PAYEE_SOL = "CVhqj6hcugFDKZxzSkiUG64cRbHn2kguZy9n6zv47FqL"  # the payee's Solana wallet (owner of its token account)
REPO = "drexthealpha/knos"
WF = f"{REPO}/.github/workflows/near-proof.yml@refs/heads/main"
AMOUNT = 1_000_000  # 1.000000 test units, decimals 6
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
SYSTEM = "11111111111111111111111111111111"
LOG: list[str] = []
try:  # some Windows Python builds lack the issuer of devnet's certificate; certifi carries it
    import certifi
    TLS = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    TLS = ssl.create_default_context()

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58e(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s


def b58d(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(s) - len(s.lstrip("1"))) + b


def say(line: str) -> None:
    LOG.append(line)
    print(line, flush=True)


def post(url: str, method: str, params) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for _ in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, body, {"Content-Type": "application/json"}), timeout=180, context=TLS) as r:
                out = json.loads(r.read())
            if "result" in out:
                return out["result"]
            if "error" in out and method != "getSignatureStatuses":
                raise RuntimeError(json.dumps(out["error"])[:400])
        except OSError:
            pass
        time.sleep(3)
    raise RuntimeError(f"{method} failed")


# ---- Solana: keys, messages, transactions ------------------------------------------------------------------------

class Key:
    def __init__(self, sk: ed25519.Ed25519PrivateKey):
        self.sk = sk
        self.pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def load_key(path: str) -> Key:
    raw = bytes(json.load(open(path, encoding="utf-8")))
    return Key(ed25519.Ed25519PrivateKey.from_private_bytes(raw[:32]))


def cu16(n: int) -> bytes:
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def compile_message(payer: bytes, ixs: list[tuple[bytes, list[tuple[bytes, bool, bool]], bytes]], blockhash: str) -> tuple[bytes, list[bytes]]:
    """A legacy message: keys ordered signer-writable (payer first), signer-readonly, writable, readonly"""
    meta: dict[bytes, list[bool]] = {payer: [True, True]}
    for prog, accts, _ in ixs:
        for k, s, w in accts:
            m = meta.setdefault(k, [False, False])
            m[0] |= s
            m[1] |= w
        meta.setdefault(prog, [False, False])
    order = sorted(meta, key=lambda k: (k != payer, not meta[k][0], not meta[k][1]))
    nsig = sum(meta[k][0] for k in order)
    ro_signed = sum(meta[k][0] and not meta[k][1] for k in order)
    ro_unsigned = sum(not meta[k][0] and not meta[k][1] for k in order)
    out = bytes([nsig, ro_signed, ro_unsigned]) + cu16(len(order)) + b"".join(order) + b58d(blockhash) + cu16(len(ixs))
    for prog, accts, data in ixs:
        out += bytes([order.index(prog)]) + cu16(len(accts)) + bytes(order.index(k) for k, _, _ in accts) + cu16(len(data)) + data
    return out, order[:nsig]


def send(ixs, payer: Key, extra: list[Key] = ()) -> str:
    bh = post(SRPC, "getLatestBlockhash", [{"commitment": "finalized"}])["value"]["blockhash"]
    msg, signers = compile_message(payer.pub, ixs, bh)
    keys = {k.pub: k for k in [payer, *extra]}
    tx = cu16(len(signers)) + b"".join(keys[s].sk.sign(msg) for s in signers) + msg
    return broadcast(tx)


def broadcast(tx: bytes) -> str:
    sig = post(SRPC, "sendTransaction", [base64.b64encode(tx).decode(), {"encoding": "base64", "preflightCommitment": "confirmed"}])
    for _ in range(40):
        st = post(SRPC, "getSignatureStatuses", [[sig]])["value"][0]
        if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
            if st.get("err"):
                raise RuntimeError(f"devnet transaction {sig} failed: {st['err']}")
            return sig
        time.sleep(2)
    raise RuntimeError(f"devnet transaction {sig} not confirmed")


def rent(size: int) -> int:
    return post(SRPC, "getMinimumBalanceForRentExemption", [size])


def create_account(payer: Key, new: Key, size: int, owner: str) -> tuple:
    data = struct.pack("<IQQ", 0, rent(size), size) + b58d(owner)
    return (b58d(SYSTEM), [(payer.pub, True, True), (new.pub, True, True)], data)


def token_account(payer: Key, mint: bytes, owner: bytes) -> tuple[Key, str]:
    acct = Key(ed25519.Ed25519PrivateKey.generate())
    init = (b58d(TOKEN), [(acct.pub, False, True), (mint, False, False)], bytes([18]) + owner)  # InitializeAccount3
    return acct, send([create_account(payer, acct, 165, TOKEN), init], payer, [acct])


# ---- NEAR: calls signed by near's keychain, sent through RPC ----------------------------------------------------

def ncall(who: str, contract: str, method: str, args: dict, deposit: str | None = None) -> tuple[str, bool, str, dict]:
    deposit = deposit or ("0 NEAR" if contract == KNOS else "1 yoctoNEAR")
    cmd = [NEAR, "contract", "call-function", "as-transaction", contract, method, "json-args", json.dumps(args), "prepaid-gas", "300 Tgas",
           "attached-deposit", deposit, "sign-as", who, "network-config", "testnet", "sign-with-legacy-keychain", "display"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    text = re.sub(r"\x1b\[[0-9;]*m", "", p.stdout + p.stderr)
    m = re.search(r"Signed transaction \(serialized as base64\):\s*([A-Za-z0-9+/=]{100,})", text)
    if not m:
        raise RuntimeError(f"near did not sign {method}")
    r = post(NRPC, "send_tx", {"signed_tx_base64": m.group(1), "wait_until": "FINAL"})
    for o in [r["transaction_outcome"]] + r["receipts_outcome"]:
        if "Failure" in o["outcome"]["status"]:
            return r["transaction"]["hash"], False, json.dumps(o["outcome"]["status"]["Failure"])[:300], r
    val = r["status"].get("SuccessValue", "")
    return r["transaction"]["hash"], True, base64.b64decode(val).decode(errors="replace") if val else "", r


def nview(contract: str, method: str, args: dict):
    r = post(NRPC, "query", {"request_type": "call_function", "finality": "final", "account_id": contract, "method_name": method,
                             "args_base64": base64.b64encode(json.dumps(args).encode()).decode()})
    return json.loads(bytes(r["result"]))


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else None
    fee = load_key(os.environ["SOL_FEE_KEY"])
    derived = b58d(nview(SIGNER, "derived_public_key", {"path": PATH, "predecessor": KNOS, "domain_id": 1}).split(":")[1])
    say(f"derived Solana address of {KNOS} for {PATH}: {b58e(derived)}")

    # devnet: the derived address needs SOL for its fee; a test mint; its token account with the payout; the payee's
    sig = send([(b58d(SYSTEM), [(fee.pub, True, True), (derived, False, True)], struct.pack("<IQ", 2, 20_000_000))], fee)
    say(f"devnet: 0.02 SOL to the derived address for its fee: {sig}")
    mint = Key(ed25519.Ed25519PrivateKey.generate())
    init_mint = (b58d(TOKEN), [(mint.pub, False, True)], bytes([20, 6]) + fee.pub + b"\0")  # InitializeMint2, decimals 6
    sig = send([create_account(fee, mint, 82, TOKEN), init_mint], fee, [mint])
    say(f"devnet: test mint {b58e(mint.pub)} (6 decimals): {sig}")
    src, sig = token_account(fee, mint.pub, derived)
    say(f"devnet: token account {b58e(src.pub)} owned by the derived address: {sig}")
    dst, sig = token_account(fee, mint.pub, b58d(PAYEE_SOL))
    say(f"devnet: payee token account {b58e(dst.pub)} owned by {PAYEE_SOL}: {sig}")
    sig = send([(b58d(TOKEN), [(mint.pub, False, True), (src.pub, False, True), (fee.pub, True, False)], bytes([7]) + struct.pack("<Q", AMOUNT))], fee)
    say(f"devnet: {AMOUNT} units minted to the derived address's account: {sig}")

    # NEAR: a test signing key set by two owners, the milestone funded for the payee on Solana, released on a token
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    n = format(key.public_key().public_numbers().n, "0512x")
    ncall(OWN[0], KNOS, "propose_key", {"kid": "knos-test", "n_hex": n})
    h, ok, why, _ = ncall(OWN[1], KNOS, "propose_key", {"kid": "knos-test", "n_hex": n})
    say(f"NEAR: test key set by 2 owners: {why} {h}")
    for acct in (KNOS,):
        ncall(PAYER, USDC, "storage_deposit", {"account_id": acct, "registration_only": True}, "0.01 NEAR")
    mid = f"sol-{time.strftime('%m%d%H%M', time.gmtime())}"
    crit = hashlib.sha256(b"knos solana payout criteria").hexdigest()
    msg = {"id": mid, "payee_chain": "solana", "payee_address": b58e(dst.pub), "payee_mint": b58e(mint.pub), "criteria_hash": crit,
           "repository": REPO, "workflow": WF, "deadline_ns": str((int(time.time()) + 3600) * 1_000_000_000)}
    h, ok, why, _ = ncall(PAYER, USDC, "ft_transfer_call", {"receiver_id": KNOS, "amount": str(AMOUNT), "msg": json.dumps(msg)})
    say(f"NEAR: milestone {mid} funded with {AMOUNT} test units for the Solana payee: ok={ok} {h}")
    claims = {"iss": "https://token.actions.githubusercontent.com", "aud": KNOS, "exp": int(time.time()) + 600, "jti": f"jti-{mid}",
              "repository": REPO, "job_workflow_ref": WF, "sha": "6413e890617b033c7cb89d385b45bc25c6acc4f3"}
    signed = b64u(json.dumps({"alg": "RS256", "kid": "knos-test", "typ": "JWT"}).encode()) + "." + b64u(json.dumps(claims).encode())
    tok = signed + "." + b64u(key.sign(signed.encode(), padding.PKCS1v15(), hashes.SHA256()))
    h, ok, why, _ = ncall(PAYEE, KNOS, "release", {"id": mid, "token": tok, "criteria_hash": crit})
    say(f"NEAR: release on the token: {why} ok={ok} {h}")

    # the unsigned transfer, checked and signed by the contract through Chain Signatures
    bh = post(SRPC, "getLatestBlockhash", [{"commitment": "finalized"}])["value"]["blockhash"]
    transfer = (b58d(TOKEN), [(src.pub, False, True), (mint.pub, False, False), (dst.pub, False, True), (derived, True, False)],
                bytes([12]) + struct.pack("<Q", AMOUNT) + bytes([6]))
    message, signers = compile_message(derived, [transfer], bh)
    assert signers == [derived]
    h, ok, why, r = ncall(PAYEE, KNOS, "sign_payout", {"id": mid, "message_b64": base64.b64encode(message).decode()})
    say(f"NEAR: sign_payout ({len(message)}-byte message): {why} ok={ok} {h}")
    p = nview(KNOS, "get_payout", {"id": mid})
    sig_json = json.loads(p["signature"]) if p and p.get("signature") else None
    if not sig_json:
        say(f"FAIL: no signature came back: {json.dumps(p)[:300]}")
        return 1
    raw = sig_json.get("signature")
    sig64 = bytes(raw) if isinstance(raw, list) else bytes.fromhex(raw) if isinstance(raw, str) and len(raw) == 128 else base64.b64decode(raw)
    ed25519.Ed25519PublicKey.from_public_bytes(derived).verify(sig64, message)
    say("the MPC signature (64 bytes) verifies against the derived key: yes")
    sol = broadcast(cu16(1) + sig64 + message)
    say(f"devnet: payout of {AMOUNT} units to {b58e(dst.pub)} signed by NEAR Chain Signatures: {sol}")
    say(f"https://explorer.solana.com/tx/{sol}?cluster=devnet")
    bal = post(SRPC, "getTokenAccountBalance", [b58e(dst.pub)])["value"]["amount"]
    say(f"payee token account balance now {bal}")
    if out:
        open(out, "a", encoding="utf-8").write("\n".join(LOG) + "\n")
    return 0 if int(bal) == AMOUNT else 1


if __name__ == "__main__":
    sys.exit(main())
