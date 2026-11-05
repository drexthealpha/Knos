"""Set up the swarm on testnet once: a parent account, the jobs contract under it, one sub-account per agent signing with
a function-call key scoped to that contract, a checker key set by 2 of the 3 owners, and the token registrations.
Writes near/agents/swarm.json. Every step prints its transaction. Keys stay in ~/.near-credentials and
~/.knos-checker; none is printed.

    NEAR_CLI=<near-cli-rs> python near/agents/setup_swarm.py <parent>.testnet

The parent must exist with test NEAR (near account create-account sponsor-by-faucet-service <parent>.testnet ...).
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
WASM = HERE.parent / "wasm" / "knos_near.wasm"
TOKEN = "knos-usdc-1102.testnet"
OWNERS = ["knos-own1-1102.testnet", "knos-own2-1102.testnet", "knos-own3-1102.testnet"]
PAYER = "knos-payer-1102.testnet"
RELAYER = "knos-relay-1102.testnet"
METHODS = "take, submit, spend"
CRED = Path.home() / ".near-credentials" / "testnet"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    parent = sys.argv[1]
    # common reads swarm.json; write a first one so it imports
    cfg_path = HERE / "swarm.json"
    names = {"contract": f"jobs.{parent}", "a": f"agent-a.{parent}", "b": f"agent-b.{parent}", "shop": f"shop.{parent}"}
    cfg = {"parent": parent, "contract": names["contract"], "token": TOKEN, "payer": PAYER, "relayer": RELAYER, "owners": OWNERS,
           "agents": {"a": names["a"], "b": names["b"]}, "shop": names["shop"], "checker_kid": "checker-1", "methods": METHODS}
    cfg_path.write_text(json.dumps(cfg, indent=1) + "\n", encoding="utf-8")
    from common import EXPLORER, call, near

    def tx(text: str) -> str:
        m = re.findall(r"Transaction ID: ([1-9A-HJ-NP-Za-km-z]{43,44})", text)
        return EXPLORER + m[-1] if m else ""

    out = {}
    for k, amount in (("contract", "3 NEAR"), ("a", "0.3 NEAR"), ("b", "0.3 NEAR"), ("shop", "0.1 NEAR")):
        acct = names[k]
        if (CRED / f"{acct}.json").exists():
            print(f"account {acct}: here already")
            continue
        t = near("account", "create-account", "fund-myself", acct, amount, "autogenerate-new-keypair", "save-to-legacy-keychain",
                 "sign-as", parent, "network-config", "testnet", "sign-with-legacy-keychain", "send")
        out[f"account {k}"] = tx(t)
        print(f"account {acct}:", "created" if ("created successfully" in t or "successfully created" in t) else t[-300:], tx(t))
    t = near("contract", "deploy", names["contract"], "use-file", str(WASM), "with-init-call", "new", "json-args",
             json.dumps({"usdc": TOKEN, "owners": OWNERS}), "prepaid-gas", "100 Tgas", "attached-deposit", "0 NEAR",
             "network-config", "testnet", "sign-with-legacy-keychain", "send")
    out["deploy"] = tx(t)
    print("deploy:", "done" if "successfully deployed" in t or "deployed" in t else t[-300:], tx(t))
    # each agent: a function-call key on the jobs contract (take, submit, spend), with a gas allowance; it signs with it
    for k in ("a", "b"):
        acct = names[k]
        t = near("account", "add-key", acct, "grant-function-call-access", "--allowance", "0.25 NEAR", "--contract-account-id",
                 names["contract"], "--function-names", METHODS, "autogenerate-new-keypair", "save-to-legacy-keychain",
                 "network-config", "testnet", "sign-with-legacy-keychain", "send")
        out[f"function-call key {k}"] = tx(t)
        print(f"function-call key for {acct}:", tx(t) or t[-300:])
    # the checker key, set by 2 of 3 owners
    kp = Path.home() / ".knos-checker" / "checker.pem"
    kp.parent.mkdir(exist_ok=True)
    if not kp.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        kp.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key = serialization.load_pem_private_key(kp.read_bytes(), password=None)
    n = format(key.public_key().public_numbers().n, "0512x")
    for o in OWNERS[:2]:
        r = call(o, names["contract"], "propose_checker_key", {"kid": cfg["checker_kid"], "n_hex": n})
        out[f"checker key by {o}"] = r["url"]
        print(f"checker key by {o}:", r["said"], r["url"])
    for acct in (names["contract"], names["a"], names["b"], names["shop"]):
        r = call(PAYER, TOKEN, "storage_deposit", {"account_id": acct, "registration_only": True}, "0.01 NEAR")
        print(f"token registration of {acct}:", r["ok"], r["url"])
    cfg["setup"] = out
    cfg["set_up_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cfg_path.write_text(json.dumps(cfg, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
