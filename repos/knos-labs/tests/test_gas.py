"""POST /gas: 0.01 devnet SOL for a passkey wallet's gas key, rate-limited per key and per IP, devnet only, and 503 on
a server without a gas key. Offline (a fake ledger behind the real HTTP server)."""
import json
import threading
import urllib.error
import urllib.request

from solders.keypair import Keypair

from knos.jobs import gas as G
from knos.jobs.actions import Actions, serve


class FakeLedger:
    def __init__(self):
        self.sent, self.bal = [], {}

    def lamports(self, who):
        return self.bal.get(str(who), 0)

    def send(self, ixs, payer, signers=None):
        self.sent.append((ixs, payer.pubkey()))
        return "sig"

    def blockhash(self):
        raise AssertionError("not used")


def _post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _server(gas):
    srv = serve(Actions(FakeLedger(), None), port=0, gas=gas)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/gas"


def test_gas_tops_up_once_per_key_and_limits_ips():
    led = FakeLedger()
    srv, url = _server(G.Gas(led, Keypair(), "devnet"))
    try:
        k = str(Keypair().pubkey())
        code, got = _post(url, {"pubkey": k})
        assert code == 200 and got["lamports"] == G.LAMPORTS and got["to"] == k and len(led.sent) == 1
        assert _post(url, {"pubkey": k})[0] == 429
        assert _post(url, {"pubkey": "not-a-key"})[0] == 400
        for _ in range(G.PER_IP - 1):
            assert _post(url, {"pubkey": str(Keypair().pubkey())})[0] == 200
        assert _post(url, {"pubkey": str(Keypair().pubkey())})[0] == 429, "per-IP limit"
        assert "secret" not in json.dumps(got) and len(led.sent) == G.PER_IP
    finally:
        srv.shutdown()


def test_gas_refuses_funded_keys_mainnet_and_no_key():
    led = FakeLedger()
    k = Keypair().pubkey()
    led.bal[str(k)] = G.LAMPORTS
    g = G.Gas(led, Keypair(), "devnet")
    try:
        g.top_up({"pubkey": str(k)}, "1.1.1.1")
        raise AssertionError("funded key topped up")
    except G.GasError as e:
        assert e.code == 409
    for gg, code in ((G.Gas(led, Keypair(), "mainnet"), 403), (G.Gas(led, None, "devnet"), 503)):
        try:
            gg.top_up({"pubkey": str(Keypair().pubkey())}, "1.1.1.1")
            raise AssertionError("should refuse")
        except G.GasError as e:
            assert e.code == code
    srv, url = _server(None)
    try:
        assert _post(url, {"pubkey": str(k)})[0] == 503
    finally:
        srv.shutdown()
