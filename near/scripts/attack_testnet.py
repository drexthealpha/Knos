"""Attacks on the deployed testnet contract, each one a real transaction: what was tried, what the contract should do,
what it did, the reason it gave, and the transaction hash. Prints a Markdown table.

    NEAR_CLI=<path to near> python near/scripts/attack_testnet.py [table.md]

Accounts (testnet, keys in ~/.near-credentials, never read here): the contract, its NEP-141 test token, a payer, a
payee, three owners and a second token for the wrong-token case. Tokens are signed with an RSA-2048 test key that two
owners set as kid "knos-test": it stands in for GitHub's key so each attack changes one thing at a time. The key is
made fresh for each run and kept only in memory.
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

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

NEAR = os.environ.get("NEAR_CLI", "near")
RPC = "https://rpc.testnet.near.org"
S = "1102"
# the contract runs near/wasm/ (knos-pay-1103: knos-pay-1102's older state does not load in this code); the token,
# payer, payee and owners are the 1102 accounts
KNOS, USDC, FAKE = os.environ.get("KNOS_CONTRACT", "knos-pay-1103.testnet"), f"knos-usdc-{S}.testnet", f"knos-fake-{S}.testnet"
PAYER, PAYEE = f"knos-payer-{S}.testnet", f"knos-payee-{S}.testnet"
OWN = [f"knos-own{i}-{S}.testnet" for i in (1, 2, 3)]
REPO = "drexthealpha/knos"
WF = f"{REPO}/.github/workflows/near-proof.yml@refs/heads/main"
HASH = hashlib.sha256(b"knos attack table criteria").hexdigest()
SHA = "6413e890617b033c7cb89d385b45bc25c6acc4f3"
RUN = time.strftime("%m%d%H%M", time.gmtime())
ROWS: list[tuple[str, str, str, str, str]] = []


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KEY2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def n_hex(k: rsa.RSAPrivateKey) -> str:
    return format(k.public_key().public_numbers().n, "0512x")


def token(over: dict | None = None, kid: str = "knos-test", key: rsa.RSAPrivateKey = KEY, alg: str = "RS256", tamper: dict | None = None, cut: int = 0) -> str:
    c = {"iss": "https://token.actions.githubusercontent.com", "aud": KNOS, "exp": int(time.time()) + 600,
         "jti": f"jti-{RUN}-{len(ROWS)}-{time.time_ns()}", "repository": REPO, "job_workflow_ref": WF, "sha": SHA}
    c.update(over or {})
    signed = b64(json.dumps({"alg": alg, "kid": kid, "typ": "JWT"}).encode()) + "." + b64(json.dumps(c).encode())
    sig = key.sign(signed.encode(), padding.PKCS1v15(), hashes.SHA256())
    if tamper:
        c.update(tamper)
        signed = signed.split(".")[0] + "." + b64(json.dumps(c).encode())
    return signed + "." + b64(sig[: len(sig) - cut])


def rpc(method: str, params: dict) -> dict:
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


def outcome(r: dict) -> tuple[bool, str]:
    """(every receipt succeeded, the first panic message or the returned value) of a final transaction result"""
    for o in [r["transaction_outcome"]] + r["receipts_outcome"]:
        st = o["outcome"]["status"]
        if "Failure" in st:
            msg = json.dumps(st["Failure"])
            m = re.search(r"Smart contract panicked: ([^\"\\]+)", msg) or re.search(r'"(Method [^"]+)"', msg)
            return False, (m.group(1) if m else msg[:120])
    val = r["status"].get("SuccessValue", "")
    return True, base64.b64decode(val).decode(errors="replace").strip('"') if val else "ok"


def call(who: str, contract: str, method: str, args: dict, deposit: str | None = None) -> tuple[str, bool, str]:
    """near signs (its keychain), the RPC sends: a refused call still has its hash and its reason"""
    deposit = deposit or ("0 NEAR" if contract == KNOS else "1 yoctoNEAR")
    cmd = [NEAR, "contract", "call-function", "as-transaction", contract, method, "json-args", json.dumps(args),
           "prepaid-gas", "300 Tgas", "attached-deposit", deposit, "sign-as", who, "network-config", "testnet",
           "sign-with-legacy-keychain", "display"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    text = re.sub(r"\x1b\[[0-9;]*m", "", p.stdout + p.stderr)
    m = re.search(r"Signed transaction \(serialized as base64\):\s*([A-Za-z0-9+/=]{100,})", text)
    if not m:
        return "", False, "not signed: " + (text.strip().splitlines() or ["?"])[-1][:120]
    r = rpc("send_tx", {"signed_tx_base64": m.group(1), "wait_until": "FINAL"})
    ok, why = outcome(r)
    return r["transaction"]["hash"], ok, why


def row(attack: str, expected: str, res: tuple[str, bool, str], want_ok: bool = False, why_has: str = "") -> bool:
    tx, ok, why = res
    passed = ok == want_ok and (why_has.lower() in why.lower())
    ROWS.append((attack, expected, ("done" if ok else "refused") + ("" if passed else " (UNEXPECTED)"), why, tx))
    print(f"{'PASS' if passed else 'FAIL'} {attack}: {why} {tx}", flush=True)
    return passed


def fund(mid: str, deadline_s: int = 3600, contract_token: str = USDC, **over) -> tuple[str, bool, str]:
    msg = {"id": mid, "payee_chain": "near", "payee_address": PAYEE, "criteria_hash": HASH, "repository": REPO,
           "workflow": WF, "deadline_ns": str((int(time.time()) + deadline_s) * 1_000_000_000)}
    msg.update(over)
    return call(PAYER, contract_token, "ft_transfer_call", {"receiver_id": KNOS, "amount": "1000", "msg": json.dumps(msg)})


def fund_refused(mid: str, **kw) -> tuple[str, bool, str]:
    """A refused funding panics in ft_on_transfer and the token refunds itself: the transaction's receipts show it"""
    return fund(mid, **kw)


def milestone(mid: str) -> dict | None:
    r = rpc("query", {"request_type": "call_function", "finality": "final", "account_id": KNOS, "method_name": "get_milestone",
                      "args_base64": base64.b64encode(json.dumps({"id": mid}).encode()).decode()})
    return json.loads(bytes(r["result"]))


def release(mid: str, tok: str, crit: str = HASH, who: str = PAYEE) -> tuple[str, bool, str]:
    return call(who, KNOS, "release", {"id": mid, "token": tok, "criteria_hash": crit})


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else None
    i = iter(range(1, 1000))
    mid = lambda: f"a{RUN}-{next(i)}"  # noqa: E731
    # setup: storage on both tokens, the test key by two owners
    for acct in (KNOS, PAYEE):
        call(PAYER, USDC, "storage_deposit", {"account_id": acct, "registration_only": True}, "0.01 NEAR")
    call(PAYER, FAKE, "storage_deposit", {"account_id": KNOS, "registration_only": True}, "0.01 NEAR")
    row("one owner alone sets a key", "not applied", call(OWN[0], KNOS, "propose_key", {"kid": "knos-test", "n_hex": n_hex(KEY)}), True, "waiting for a second owner")
    row("the same owner twice", "not applied", call(OWN[0], KNOS, "propose_key", {"kid": "knos-test", "n_hex": n_hex(KEY)}), True, "waiting for a second owner")
    row("a second owner, same key (control)", "key set", call(OWN[1], KNOS, "propose_key", {"kid": "knos-test", "n_hex": n_hex(KEY)}), True, "set by 2 owners")
    row("a key change by a non-owner", "refused", call(PAYER, KNOS, "propose_key", {"kid": "evil", "n_hex": n_hex(OTHER)}), False, "only an owner")
    row("a 1024-bit key", "refused", call(OWN[0], KNOS, "propose_key", {"kid": "weak", "n_hex": format(rsa.generate_private_key(public_exponent=65537, key_size=1024).public_key().public_numbers().n, "0256x")}), False, "2048-bit")

    m1 = mid()
    fund(m1)
    good = token()
    row("an honest release (control)", "paid", release(m1, good), True, "")
    row("the same token again (replay)", "refused", (lambda m: (fund(m), release(m, good))[1])(mid()), False, "already used")
    row("a second payment of a paid milestone", "refused", release(m1, token()), False, "not funded and open")
    m = mid(); fund(m)
    row("a token from another repository", "refused", release(m, token({"repository": "evil/knos"})), False, "another repository")
    row("a token from another workflow", "refused", release(m, token({"job_workflow_ref": f"{REPO}/.github/workflows/other.yml@refs/heads/main"})), False, "another workflow")
    row("a workflow on another branch", "refused", release(m, token({"job_workflow_ref": f"{REPO}/.github/workflows/near-proof.yml@refs/heads/evil"})), False, "another workflow")
    row("altered criteria", "refused", release(m, token(), crit=hashlib.sha256(b"other criteria").hexdigest()), False, "criteria are not the ones locked")
    row("a forged token (unknown key)", "refused", release(m, token(kid="github-lookalike", key=OTHER)), False, "not in the key set")
    row("a re-signed token (known kid, other key)", "refused", release(m, token(key=OTHER)), False, "does not verify")
    row("claims changed after signing", "refused", release(m, token(tamper={"repository": REPO, "sha": "f" * 40})), False, "does not verify")
    row("a truncated signature", "refused", release(m, token(cut=8)), False, "")
    row("an expired token", "refused", release(m, token({"exp": int(time.time()) - 60})), False, "expired")
    row("another audience", "refused", release(m, token({"aud": "someone-else.testnet"})), False, "audience")
    row("another issuer", "refused", release(m, token({"iss": "https://evil.example"})), False, "not GitHub's")
    row("alg HS256", "refused", release(m, token(alg="HS256")), False, "not RS256")
    row("alg none, no signature", "refused", release(m, token(alg="none", cut=256)), False, "")
    row("a token naming no commit", "refused", release(m, token({"sha": "main"})), False, "names no commit")
    row("not a JWT", "refused", release(m, "eyJhbGciOiJSUzI1NiJ9.e30"), False, "")
    row("a milestone that does not exist", "refused", release("no-such-milestone", token()), False, "no such milestone")
    row("an early refund", "refused", call(PAYEE, KNOS, "refund", {"id": m}), False, "has not passed")
    row("the private callback called from outside", "refused", call(PAYER, KNOS, "on_paid", {"id": m, "refund": True}), False, "private")

    # funding refusals: the token returns the whole amount
    row("funding the same id twice", "refused", fund_refused(m1), False, "id exists")
    row("funding with a past deadline", "refused", fund_refused(mid(), deadline_s=-60), False, "in the past")
    row("funding without a criteria hash", "refused", fund_refused(mid(), criteria_hash="abc"), False, "64 hex")
    row("funding for an unknown chain", "refused", fund_refused(mid(), payee_chain="dogecoin"), False, "payee_chain")
    row("a workflow outside the repository", "refused", fund_refused(mid(), workflow="evil/knos/.github/workflows/x.yml@refs/heads/main"), False, "repository and workflow")
    row("funding in another token", "refused", fund_refused(mid(), contract_token=FAKE), False, "only the configured")

    # a removed key stops verifying
    call(OWN[0], KNOS, "propose_key", {"kid": "knos-test2", "n_hex": n_hex(KEY2)}); call(OWN[2], KNOS, "propose_key", {"kid": "knos-test2", "n_hex": n_hex(KEY2)})
    call(OWN[0], KNOS, "propose_key", {"kid": "knos-test2", "n_hex": None}); call(OWN[1], KNOS, "propose_key", {"kid": "knos-test2", "n_hex": None})
    row("a token under a removed key", "refused", release(m, token(kid="knos-test2", key=KEY2)), False, "not in the key set")

    # the deadline: release after it is refused, the refund goes to the payer, a release after the refund is refused
    md = mid(); fund(md, deadline_s=45); late = token()
    time.sleep(70)
    row("a release after the deadline", "refused", release(md, late), False, "deadline has passed")
    row("a refund after the deadline, sent by anyone (control)", "refunded", call(PAYEE, KNOS, "refund", {"id": md}), True, "")
    row("a release after the refund", "refused", release(md, token()), False, "not funded and open")
    row("a second refund", "refused", call(PAYEE, KNOS, "refund", {"id": md}), False, "not funded and open")

    lines = ["| Attack | Expected | Actual | Reason | Testnet tx |", "|---|---|---|---|---|"]
    for a, e, res, why, tx in ROWS:
        link = f"[`{tx[:8]}…`](https://testnet.nearblocks.io/txns/{tx})" if tx else "none"
        lines.append(f"| {a} | {e} | {res} | {why.replace('|', '/')} | {link} |")
    table = "\n".join(lines)
    if out:
        open(out, "w", encoding="utf-8").write(table + "\n")
    print(table)
    bad = [r for r in ROWS if "UNEXPECTED" in r[2]]
    print(f"{len(ROWS)} rows, {len(ROWS) - len(bad)} as expected, {len(bad)} unexpected")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
