"""The NEAR pages on this machine, with real testnet calls: fund, proof (release), refund, status.

    NEAR_CLI=<near> python near/web/serve.py        then open http://127.0.0.1:8790/

Listens on 127.0.0.1 only. Each action is a testnet transaction near-cli signs with the test accounts in
~/.near-credentials (the page never holds a key). The proof is a GitHub-shaped OIDC token signed by a test RSA key
that two owners set at start, standing in for GitHub's key (see near/README.md, the attack table).
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
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

HERE = Path(__file__).resolve().parent
NEAR = os.environ.get("NEAR_CLI", "near")
RPC = "https://rpc.testnet.near.org"
S = "1102"
KNOS, USDC, PAYER, PAYEE = f"knos-pay2-{S}.testnet", f"knos-usdc-{S}.testnet", f"knos-payer-{S}.testnet", f"knos-payee-{S}.testnet"
OWN = [f"knos-own{i}-{S}.testnet" for i in (1, 2, 3)]
REPO = "drexthealpha/knos"
WF = f"{REPO}/.github/workflows/near-proof.yml@refs/heads/main"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KID = f"knos-web-{int(time.time())}"
IDS = HERE / "milestones.local.json"
SITE = HERE.parent.parent / "web"
CROSS = {"/api/job/quote", "/api/job/pay"}


def jobs():
    """The job routes (near/web/jobs_api.py), once near/agents/swarm.json exists (near/agents/setup_swarm.py writes it)"""
    import jobs_api
    return jobs_api


def rpc(method: str, params) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    with urllib.request.urlopen(urllib.request.Request(RPC, body, {"Content-Type": "application/json"}), timeout=180) as r:
        out = json.loads(r.read())
    if "error" in out:
        raise RuntimeError(json.dumps(out["error"])[:300])
    return out["result"]


def call(who: str, contract: str, method: str, args: dict, deposit: str) -> dict:
    cmd = [NEAR, "contract", "call-function", "as-transaction", contract, method, "json-args", json.dumps(args), "prepaid-gas", "300 Tgas",
           "attached-deposit", deposit, "sign-as", who, "network-config", "testnet", "sign-with-legacy-keychain", "display"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    m = re.search(r"Signed transaction \(serialized as base64\):\s*([A-Za-z0-9+/=]{100,})", re.sub(r"\x1b\[[0-9;]*m", "", p.stdout + p.stderr))
    if not m:
        return {"ok": False, "why": "near did not sign"}
    r = rpc("send_tx", {"signed_tx_base64": m.group(1), "wait_until": "FINAL"})
    fail = next((o["outcome"]["status"]["Failure"] for o in [r["transaction_outcome"]] + r["receipts_outcome"] if "Failure" in o["outcome"]["status"]), None)
    why = re.search(r"Smart contract panicked: ([^\"\\]+)", json.dumps(fail)) if fail else None
    return {"ok": not fail, "tx": r["transaction"]["hash"], "why": why.group(1) if why else ("refused" if fail else "done")}


def view(method: str, args: dict):
    r = rpc("query", {"request_type": "call_function", "finality": "final", "account_id": KNOS, "method_name": method,
                      "args_base64": base64.b64encode(json.dumps(args).encode()).decode()})
    return json.loads(bytes(r["result"]))


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def ledger() -> list[dict]:
    return json.loads(IDS.read_text(encoding="utf-8")) if IDS.exists() else []


def remember(mid: str, **kw) -> None:
    rows = ledger()
    row = next((r for r in rows if r["id"] == mid), None)
    if not row:
        row = {"id": mid, "txs": {}}
        rows.insert(0, row)
    row["txs"].update(kw)
    IDS.write_text(json.dumps(rows, indent=1), encoding="utf-8")


def fund(body: dict) -> dict:
    amount = int(body.get("amount") or 0)
    minutes = int(body.get("minutes") or 0)
    if not (0 < amount <= 10_000_000 and 1 <= minutes <= 1440):
        return {"ok": False, "why": "amount 1 to 10,000,000 test units, deadline 1 to 1,440 minutes"}
    mid = f"web-{time.strftime('%m%d%H%M%S', time.gmtime())}"
    crit = hashlib.sha256(f"knos web criteria {mid}".encode()).hexdigest()
    msg = {"id": mid, "payee_chain": "near", "payee_address": PAYEE, "criteria_hash": crit, "repository": REPO, "workflow": WF,
           "deadline_ns": str((int(time.time()) + minutes * 60) * 1_000_000_000)}
    r = call(PAYER, USDC, "ft_transfer_call", {"receiver_id": KNOS, "amount": str(amount), "msg": json.dumps(msg)}, "1 yoctoNEAR")
    if r["ok"]:
        remember(mid, fund=r["tx"], criteria=crit)
    return {**r, "id": mid}


def proof(body: dict) -> dict:
    mid = body.get("id", "")
    row = next((x for x in ledger() if x["id"] == mid), None)
    if not row:
        return {"ok": False, "why": "no such milestone on this page"}
    claims = {"iss": "https://token.actions.githubusercontent.com", "aud": KNOS, "exp": int(time.time()) + 600, "jti": f"jti-{mid}-{time.time_ns()}",
              "repository": REPO, "job_workflow_ref": WF, "sha": hashlib.sha1(mid.encode()).hexdigest()}
    signed = b64u(json.dumps({"alg": "RS256", "kid": KID, "typ": "JWT"}).encode()) + "." + b64u(json.dumps(claims).encode())
    tok = signed + "." + b64u(KEY.sign(signed.encode(), padding.PKCS1v15(), hashes.SHA256()))
    r = call(PAYEE, KNOS, "release", {"id": mid, "token": tok, "criteria_hash": row["txs"]["criteria"]}, "0 NEAR")
    if r["ok"]:
        remember(mid, release=r["tx"])
    return r


def refund(body: dict) -> dict:
    mid = body.get("id", "")
    r = call(PAYEE, KNOS, "refund", {"id": mid}, "0 NEAR")
    if r["ok"]:
        remember(mid, refund=r["tx"])
    return r


def status() -> list[dict]:
    out = []
    for row in ledger()[:5]:
        m = view("get_milestone", {"id": row["id"]}) or {}
        out.append({"id": row["id"], "state": m.get("state"), "amount": m.get("amount"), "payee": m.get("payee_address"),
                    "deadline_s": int(m.get("deadline_ns", "0")) // 1_000_000_000, "txs": {k: v for k, v in row["txs"].items() if k != "criteria"}})
    return out


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE), **kw)

    def send_json(self, code: int, obj) -> None:
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self):
        # the embeddable button (pay.js) calls the quote and the pay route from another page
        if self.path.split("?")[0] in CROSS:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204 if self.path in CROSS else 404)
        self.end_headers()

    def translate_path(self, path):
        # the shared tokens and fonts of the site (web/brand, web/fonts), as the Pages build has them next to /near/
        for d in ("/brand/", "/fonts/"):
            if path.startswith(d) and ".." not in path:
                return str(SITE / path.lstrip("/").split("?")[0])
        return super().translate_path(path)

    def do_GET(self):  # noqa: N802
        if self.path == "/api/status":
            return self.send_json(200, {"contract": KNOS, "token": USDC, "payee": PAYEE, "milestones": status(), "jobs": jobs().status()})
        if self.path.startswith("/api/") or self.path.endswith(".py") or "local" in self.path:
            return self.send_json(404, {"why": "not here"})
        return super().do_GET()

    def do_POST(self):  # noqa: N802
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.send_json(415, {"why": "send application/json"})
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        act = {"/api/fund": fund, "/api/proof": proof, "/api/refund": refund, **jobs().ROUTES}.get(self.path)
        if not act:
            return self.send_json(404, {"why": "not here"})
        res = act(body)
        return self.send_json(200 if res.get("ok") else 409, res)

    def log_message(self, *a):
        pass


def main() -> None:
    n = format(KEY.public_key().public_numbers().n, "0512x")
    call(OWN[0], KNOS, "propose_key", {"kid": KID, "n_hex": n}, "0 NEAR")
    r = call(OWN[1], KNOS, "propose_key", {"kid": KID, "n_hex": n}, "0 NEAR")
    print(f"test key {KID} set by 2 owners: {r.get('tx')}; open http://127.0.0.1:8790/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8790), Handler).serve_forever()


if __name__ == "__main__":
    main()
