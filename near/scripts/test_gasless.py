"""N5: the payee releases a milestone without holding NEAR for gas; the relayer refuses every other receiver.

    NEAR_CLI=<near> python near/scripts/test_gasless.py [result file]

Starts near/relayer/relay.py on 127.0.0.1:8789 (and stops it), with the relayer account's key from ~/.near-credentials.
near-cli signs each delegate action for the network testnet-relay (its meta_transaction_relayer_url is the relayer).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "relayer"))
import relay  # noqa: E402

NEAR = os.environ.get("NEAR_CLI", "near")
S = "1102"
KNOS, USDC, PAYER, PAYEE, RELAYER = f"knos-pay2-{S}.testnet", f"knos-usdc-{S}.testnet", f"knos-payer-{S}.testnet", f"knos-payee-{S}.testnet", f"knos-relay-{S}.testnet"
OWN = [f"knos-own{i}-{S}.testnet" for i in (1, 2, 3)]
REPO = "drexthealpha/knos"
WF = f"{REPO}/.github/workflows/near-proof.yml@refs/heads/main"
CREDS = Path.home() / ".near-credentials" / "testnet"
LOG: list[str] = []


def say(s: str) -> None:
    LOG.append(s)
    print(s, flush=True)


def near(args: list[str], network: str) -> str:
    p = subprocess.run([NEAR, *args, "network-config", network, "sign-with-legacy-keychain", "display"], capture_output=True, text=True, timeout=300)
    return re.sub(r"\x1b\[[0-9;]*m", "", p.stdout + p.stderr)


def delegate(args: list[str]) -> str:
    m = re.search(r"Signed delegate action \(serialized as base64\):\s*([A-Za-z0-9+/=]{40,})", near(args, "testnet-relay"))
    if not m:
        raise RuntimeError("near signed no delegate action")
    return m.group(1)


def post_relay(sda: str) -> tuple[int, dict]:
    req = urllib.request.Request("http://127.0.0.1:8789/relay", json.dumps({"signed_delegate_action": sda}).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def call(who: str, contract: str, method: str, args: dict, deposit: str = "0 NEAR") -> str:
    """An ordinary transaction, for setup (signed by near, sent through RPC)"""
    text = near(["contract", "call-function", "as-transaction", contract, method, "json-args", json.dumps(args), "prepaid-gas", "300 Tgas",
                 "attached-deposit", deposit, "sign-as", who], "testnet")
    m = re.search(r"Signed transaction \(serialized as base64\):\s*([A-Za-z0-9+/=]{100,})", text)
    return relay.rpc("send_tx", {"signed_tx_base64": m.group(1), "wait_until": "FINAL"})["transaction"]["hash"]


def balance(acct: str) -> int:
    return int(relay.rpc("query", {"request_type": "view_account", "finality": "final", "account_id": acct})["amount"])


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else None
    log = str(HERE / "relayer" / "relay.log")
    r = relay.Relayer(RELAYER, str(CREDS / f"{RELAYER}.json"), KNOS, log)
    server = relay.serve(r)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fails = 0
    try:
        # setup: a test signing key by two owners and a milestone paid to the payee on NEAR
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        n = format(key.public_key().public_numbers().n, "0512x")
        call(OWN[0], KNOS, "propose_key", {"kid": "knos-gasless", "n_hex": n})
        call(OWN[1], KNOS, "propose_key", {"kid": "knos-gasless", "n_hex": n})
        call(PAYER, USDC, "storage_deposit", {"account_id": PAYEE, "registration_only": True}, "0.01 NEAR")
        mid = f"gas-{time.strftime('%m%d%H%M', time.gmtime())}"
        crit = hashlib.sha256(b"knos gasless criteria").hexdigest()
        fmsg = {"id": mid, "payee_chain": "near", "payee_address": PAYEE, "criteria_hash": crit, "repository": REPO, "workflow": WF,
                "deadline_ns": str((int(time.time()) + 3600) * 1_000_000_000)}
        say(f"setup: milestone {mid} funded {call(PAYER, USDC, 'ft_transfer_call', {'receiver_id': KNOS, 'amount': '1000', 'msg': json.dumps(fmsg)}, '1 yoctoNEAR')}")
        claims = {"iss": "https://token.actions.githubusercontent.com", "aud": KNOS, "exp": int(time.time()) + 900, "jti": f"jti-{mid}",
                  "repository": REPO, "job_workflow_ref": WF, "sha": "4ead275f347ef4829dddf686da2b70af981afe58"}
        signed = b64u(json.dumps({"alg": "RS256", "kid": "knos-gasless", "typ": "JWT"}).encode()) + "." + b64u(json.dumps(claims).encode())
        tok = signed + "." + b64u(key.sign(signed.encode(), padding.PKCS1v15(), hashes.SHA256()))

        before = balance(PAYEE)
        sda = delegate(["contract", "call-function", "as-transaction", KNOS, "release", "json-args", json.dumps({"id": mid, "token": tok, "criteria_hash": crit}),
                        "prepaid-gas", "200 Tgas", "attached-deposit", "0 NEAR", "sign-as", PAYEE])
        code, res = post_relay(sda)
        after = balance(PAYEE)
        state = relay.rpc("query", {"request_type": "call_function", "finality": "final", "account_id": KNOS, "method_name": "get_milestone",
                                    "args_base64": base64.b64encode(json.dumps({"id": mid}).encode()).decode()})
        st = json.loads(bytes(state["result"]))["state"]
        ok = code == 200 and res.get("ok") and before == after and st == "Released"
        fails += not ok
        say(f"{'PASS' if ok else 'FAIL'} the payee's release, relayed: http {code}, tx {res.get('tx')}, milestone {st}, payee NEAR before {before} after {after} (unchanged: {before == after})")

        for name, args in [
            ("a call to another contract (the token's ft_transfer)", ["contract", "call-function", "as-transaction", USDC, "ft_transfer",
                                                                       "json-args", json.dumps({"receiver_id": PAYER, "amount": "1"}), "prepaid-gas", "30 Tgas", "attached-deposit", "1 yoctoNEAR", "sign-as", PAYEE]),
            ("a NEAR transfer to another account", ["tokens", PAYEE, "send-near", PAYER, "0.01 NEAR"]),
            ("a call to the Knos contract with a deposit", ["contract", "call-function", "as-transaction", KNOS, "get_rules", "json-args", "{}",
                                                           "prepaid-gas", "30 Tgas", "attached-deposit", "1 yoctoNEAR", "sign-as", PAYEE]),
        ]:
            code, res = post_relay(delegate(args))
            ok = code == 403 and not res.get("ok")
            fails += not ok
            say(f"{'PASS' if ok else 'FAIL'} refused {name}: http {code}, {res.get('why')}")
        say("relay.log: " + " | ".join(Path(log).read_text(encoding="utf-8").strip().splitlines()[-4:]))
    finally:
        server.shutdown()
    say(f"{'PASS' if not fails else 'FAIL'} test_gasless: {4 - fails} of 4")
    if out:
        open(out, "a", encoding="utf-8").write("\n".join(LOG) + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
