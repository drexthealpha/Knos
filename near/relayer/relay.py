"""A self-hosted NEP-366 meta-transaction relayer that pays gas only for calls to the Knos contract.

    RELAYER_ACCOUNT=<account> RELAYER_KEY_FILE=<near credentials json> KNOS_CONTRACT=<contract> python near/relayer/relay.py

POST /relay with {"signed_delegate_action": "<base64>"} (what near-cli prints for a network with a relayer URL). The
relayer reads the delegate action and refuses it unless every action is a function call with no deposit to
KNOS_CONTRACT; otherwise it wraps it in a transaction it signs and pays for, and answers with the transaction hash.
Every decision is one line in relay.log. The sender needs no NEAR for gas.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography.hazmat.primitives.asymmetric import ed25519

RPC = os.environ.get("NEAR_RPC", "https://rpc.testnet.near.org")
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
ACTIONS = ["CreateAccount", "DeployContract", "FunctionCall", "Transfer", "Stake", "AddKey", "DeleteKey", "DeleteAccount", "Delegate"]


def b58d(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(s) - len(s.lstrip("1"))) + b


def b58e(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s


class Reader:
    def __init__(self, b: bytes):
        self.b, self.i = b, 0

    def take(self, n: int) -> bytes:
        if self.i + n > len(self.b):
            raise ValueError("delegate action is cut short")
        out = self.b[self.i:self.i + n]
        self.i += n
        return out

    def u8(self) -> int:
        return self.take(1)[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.take(8))[0]

    def string(self) -> str:
        return self.take(self.u32()).decode()


def read_delegate(raw: bytes) -> dict:
    """The parts of a SignedDelegateAction the relayer decides on"""
    r = Reader(raw)
    sender, receiver = r.string(), r.string()
    actions = []
    for _ in range(r.u32()):
        tag = r.u8()
        name = ACTIONS[tag] if tag < len(ACTIONS) else f"action {tag}"
        if tag != 2:
            actions.append({"type": name})
            break  # anything but a function call is refused; no need to read further
        method = r.string()
        r.take(r.u32())  # args
        gas = r.u64()
        deposit = int.from_bytes(r.take(16), "little")
        actions.append({"type": name, "method": method, "gas": gas, "deposit": deposit})
    return {"sender": sender, "receiver": receiver, "actions": actions}


def rpc(method: str, params) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    with urllib.request.urlopen(urllib.request.Request(RPC, body, {"Content-Type": "application/json"}), timeout=180) as r:
        out = json.loads(r.read())
    if "error" in out:
        raise RuntimeError(json.dumps(out["error"])[:300])
    return out["result"]


def borsh_str(s: str) -> bytes:
    return struct.pack("<I", len(s)) + s.encode()


class Relayer:
    def __init__(self, account: str, key_file: str, contract: str, log: str):
        k = json.load(open(key_file, encoding="utf-8"))
        self.sk = ed25519.Ed25519PrivateKey.from_private_bytes(b58d(k["private_key"].split(":")[1])[:32])
        self.pub = b58d(k["public_key"].split(":")[1])
        self.account, self.contract, self.log = account, contract, log

    def note(self, line: dict) -> None:
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **line}) + "\n")

    def decide(self, sda: bytes) -> tuple[bool, str, dict]:
        d = read_delegate(sda)
        if d["receiver"] != self.contract:
            return False, f"refused: the receiver is {d['receiver']}, this relayer pays only for {self.contract}", d
        bad = [a for a in d["actions"] if a["type"] != "FunctionCall" or a.get("deposit")]
        if bad or not d["actions"]:
            return False, f"refused: only function calls with no deposit ({bad[0]['type'] if bad else 'no action'})", d
        return True, "accepted", d

    def relay(self, sda_b64: str) -> dict:
        sda = base64.b64decode(sda_b64)
        try:
            ok, why, d = self.decide(sda)
        except Exception as e:  # noqa: BLE001 - an action it cannot read is refused
            self.note({"ok": False, "why": f"refused: unreadable ({e})"})
            return {"ok": False, "why": f"refused: unreadable ({e})"}
        if not ok:
            self.note({"ok": False, "why": why, "sender": d["sender"], "receiver": d["receiver"], "actions": d["actions"]})
            return {"ok": False, "why": why}
        ak = rpc("query", {"request_type": "view_access_key", "finality": "final", "account_id": self.account, "public_key": "ed25519:" + b58e(self.pub)})
        block = b58d(rpc("block", {"finality": "final"})["header"]["hash"])
        tx = (borsh_str(self.account) + b"\0" + self.pub + struct.pack("<Q", ak["nonce"] + 1) + borsh_str(d["sender"]) + block
              + struct.pack("<I", 1) + bytes([8]) + sda)
        signed = tx + b"\0" + self.sk.sign(hashlib.sha256(tx).digest())
        r = rpc("send_tx", {"signed_tx_base64": base64.b64encode(signed).decode(), "wait_until": "FINAL"})
        failed = [o["outcome"]["status"]["Failure"] for o in r["receipts_outcome"] if "Failure" in o["outcome"]["status"]]
        out = {"ok": not failed, "why": "relayed" if not failed else json.dumps(failed[0])[:200], "tx": r["transaction"]["hash"],
               "sender": d["sender"], "receiver": d["receiver"], "methods": [a["method"] for a in d["actions"]],
               "gas_burnt_by_relayer_tx": r["transaction_outcome"]["outcome"]["gas_burnt"]}
        self.note(out)
        return out


def serve(relayer: Relayer, port: int = 8789) -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - the http.server name
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            res = relayer.relay(body.get("signed_delegate_action", ""))
            data = json.dumps(res).encode()
            self.send_response(200 if res.get("ok") else 403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), H)


if __name__ == "__main__":
    r = Relayer(os.environ["RELAYER_ACCOUNT"], os.environ["RELAYER_KEY_FILE"], os.environ["KNOS_CONTRACT"], os.environ.get("RELAY_LOG", "relay.log"))
    print(f"relaying for {r.contract} as {r.account} on 127.0.0.1:8789")
    serve(r).serve_forever()
