"""A Solana JSON-RPC endpoint in front of a LiteSVM chain (tests/_pay2.py's Chain): the eight methods a client needs
to read an account, send a signed transaction and read back what it logged. So code that talks to a cluster's URL
(examples/x402_attested/live.mjs with --rpc) runs here against the real program builds, signatures verified.

LiteSVM is used from one thread only, so nothing here starts a thread: `run` starts the client process and answers
its requests on the calling thread until it exits. Tests only."""
from __future__ import annotations

import base64
import json
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer

from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction


class RpcShim:
    def __init__(self, chain):
        self.chain = chain
        self.txs: dict[str, list[str]] = {}            # signature -> its log
        self.named: dict[str, list[str]] = {}          # address -> signatures of the transactions that named it, oldest first
        self.calls: list[str] = []
        self.versions: dict[str, int | str] = {}      # signature -> its transaction's version: "legacy", 0 or 1
        # the version the harness's own transactions are recorded with: a relay carries PayOrder in a version 1 transaction
        self.harness_version: int | str = "legacy"
        send = chain.send

        def recorded(ixs, payer=None, signers=(), tag=None):          # what the harness itself sends is history too
            ok = send(ixs, payer, signers, tag)
            if ok:
                self._record(f"harness{len(self.txs)}", {str(a.pubkey) for ix in ixs for a in ix.accounts}, self.harness_version)
            return ok
        chain.send = recorded
        shim = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["content-length"])))
                out = {"jsonrpc": "2.0", "id": req.get("id")}
                try:
                    out["result"] = shim.call(req["method"], req.get("params") or [])
                except Exception as e:  # noqa: BLE001  (a cluster answers an error object, whatever went wrong)
                    out["error"] = {"code": -32002, "message": str(e)}
                body = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.timeout = 0.05
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def _record(self, signature: str, keys: set[str], version: int | str = "legacy") -> None:
        self.txs[signature] = list(self.chain.logs)
        self.versions[signature] = version
        for k in keys:
            self.named.setdefault(k, []).append(signature)

    def call(self, method: str, params: list):
        self.calls.append(method)
        svm, ctx = self.chain.svm, {"slot": int(self.chain.svm.get_clock().slot)}
        if method == "getAccountInfo":
            a = svm.get_account(Pubkey.from_string(params[0]))
            live = a is not None and a.lamports > 0
            return {"context": ctx, "value": {"owner": str(a.owner), "lamports": a.lamports, "executable": a.executable, "rentEpoch": 0,
                                              "data": [base64.b64encode(bytes(a.data)).decode(), "base64"]} if live else None}
        if method == "getLatestBlockhash":
            return {"context": ctx, "value": {"blockhash": str(svm.latest_blockhash()), "lastValidBlockHeight": ctx["slot"] + 150}}
        if method == "sendTransaction":
            tx = VersionedTransaction.from_bytes(base64.b64decode(params[0]))
            r = svm.send_transaction(tx)
            svm.expire_blockhash()
            if "Failed" in type(r).__name__:
                raise RuntimeError(f"Transaction simulation failed: {r.err()}")
            self.chain.logs = list(r.logs())
            first = bytes(tx.message)[0]                # a versioned message starts with 0x80 | its version
            self._record(str(tx.signatures[0]), {str(k) for k in tx.message.account_keys}, first & 0x7F if first & 0x80 else "legacy")
            return str(tx.signatures[0])
        if method == "getSignatureStatuses":
            return {"context": ctx, "value": [{"slot": ctx["slot"], "err": None, "confirmationStatus": "confirmed"} if s in self.txs else None for s in params[0]]}
        if method == "getSlot":
            return ctx["slot"]
        if method == "getBlockTime":
            return self.chain.now()
        if method == "getSignaturesForAddress":
            return [{"signature": s, "err": None} for s in reversed(self.named.get(params[0], []))]      # newest first, as a cluster
        if method == "getTransaction":
            if params[0] not in self.txs:
                return None
            # as a cluster: a versioned transaction only to a reader whose maxSupportedTransactionVersion is at least its
            # version (a reader that names none takes legacy transactions only; a cluster answers -32015)
            version, most = self.versions[params[0]], (params[1] if len(params) > 1 else {}).get("maxSupportedTransactionVersion")
            if version != "legacy" and (most is None or most < version):
                raise RuntimeError(f"Transaction version ({version}) is not supported by the requesting client. Please try the request again with "
                                   f'the following configuration parameter: "maxSupportedTransactionVersion": {version}')
            return {"slot": ctx["slot"], "blockTime": self.chain.now(), "version": version, "meta": {"err": None, "logMessages": self.txs[params[0]]}}
        raise RuntimeError(f"Method not found: {method}")

    def run(self, cmd: list[str], cwd=None, timeout: float = 120) -> subprocess.CompletedProcess:
        """Runs `cmd` to its end while answering its RPC calls. stdout and stderr go to files: a pipe nobody reads fills."""
        import time
        with tempfile.TemporaryFile("w+") as out, tempfile.TemporaryFile("w+") as err:
            p = subprocess.Popen(cmd, cwd=cwd, stdout=out, stderr=err, text=True)
            end = time.monotonic() + timeout
            while p.poll() is None:
                if time.monotonic() > end:
                    p.kill()
                    raise TimeoutError(f"{cmd[1:3]} did not finish in {timeout} seconds")
                self.httpd.handle_request()
            out.seek(0), err.seek(0)
            return subprocess.CompletedProcess(cmd, p.returncode, out.read(), err.read())

    def close(self) -> None:
        self.httpd.server_close()
