"""Agent budget wallets and paying APIs over HTTP 402.

A local server on 127.0.0.1 answers 402 in each protocol's own format. Knos must refuse, before anything is signed,
any payment that would pass the agent's cap, is in the wrong asset, or is on the wrong chain or network. No test here
reaches a chain."""

from __future__ import annotations

import base64
import json
import os
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from knos.pro import agentpay, budget, licence, solana, tempo, wallets

RECIPIENT = "0x742d35Cc6634c0532925a3b844bC9e7595F8fE00"


def _b64url(obj: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode().rstrip("=")


def _mpp_header(units: int, currency: str = tempo.TOKENS["testnet"]["pathUSD"], chain: int = 42431) -> str:
    req = {"amount": str(units), "currency": currency, "recipient": RECIPIENT, "methodDetails": {"chainId": chain}}
    return f'Payment id="chal1", realm="test", method="tempo", intent="charge", request="{_b64url(req)}"'


def _x402_header(units: int, network: str = agentpay.SOLANA_CAIP2["devnet"],
                 asset: str = solana.USDC["devnet"]) -> str:
    body = {"x402Version": 2, "resource": {"url": "http://127.0.0.1/paid"},
            "accepts": [{"scheme": "exact", "network": network, "asset": asset, "amount": str(units),
                         "payTo": solana.MERCHANT, "maxTimeoutSeconds": 60,
                         "extra": {"feePayer": solana.MERCHANT}}]}
    return base64.b64encode(json.dumps(body).encode()).decode()


@pytest.fixture()
def server():
    state = {"headers": {}, "seen_auth": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802
            state["seen_auth"].append(self.headers.get("Authorization") or self.headers.get("PAYMENT-SIGNATURE") or "")
            self.send_response(402)
            for k, v in state["headers"].items():
                self.send_header(k, v)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"payment required"}')

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{srv.server_address[1]}/paid"
    yield state
    srv.shutdown()


def _agent(name: str, chain: str, network: str, cap: float) -> str:
    addr = wallets.create(name, chain)
    budget.set_agent(name, chain, network, cap, addr)
    return addr


# ---- the wallet ------------------------------------------------------------------------------


def test_a_solana_wallet_is_owner_only_and_its_key_is_never_returned() -> None:
    addr = wallets.create("scout", "solana")
    f = wallets.key_file("scout", "solana")
    assert solana.is_address(addr) and addr == wallets.address("scout", "solana")
    if os.name == "posix":
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert wallets.create("scout", "solana") == addr  # idempotent: never a second key
    assert all("keypair" not in json.dumps(w) for w in wallets.listed())


def test_a_tempo_wallet_is_an_evm_address() -> None:
    pytest.importorskip("eth_account")
    assert tempo.is_address(wallets.create("buyer", "tempo"))


def test_agent_ids_are_names_not_paths() -> None:
    with pytest.raises(ValueError):
        wallets.key_file("../escape", "solana")


def test_the_fund_link_pays_the_agent_wallet_not_knos() -> None:
    addr = wallets.create("scout", "solana")
    url = wallets.fund_link("scout", "solana", 5, "devnet")
    assert url.startswith(f"solana:{addr}?") and "amount=5" in url and solana.USDC["devnet"] in url


# ---- the gate -------------------------------------------------------------------------------


def test_the_gate_holds_the_cap_across_many_attempts() -> None:
    _agent("scout", "solana", "devnet", cap=1.0)
    signed = 0.0
    for _ in range(200):
        try:
            agentpay.gate("scout", "solana", "devnet", solana.USDC["devnet"], 0.07, "http://x")
            signed += 0.07
        except agentpay.Refused:
            pass
    assert signed <= 1.0 + 1e-9 and agentpay.spent("scout") <= 1.0 + 1e-9
    assert round(signed, 2) == 0.98  # 14 payments fit; the 15th would pass the cap


@pytest.mark.parametrize("chain,network,asset,why", [
    ("tempo", "devnet", solana.USDC["devnet"], "budget wallet is on solana"),
    ("solana", "mainnet", solana.USDC["mainnet"], "is on devnet"),
    ("solana", "devnet", "So11111111111111111111111111111111111111112", "not the stablecoin"),
])
def test_the_gate_refuses_the_wrong_chain_network_or_asset(chain, network, asset, why) -> None:
    _agent("scout", "solana", "devnet", cap=10)
    with pytest.raises(agentpay.Refused, match=why):
        agentpay.gate("scout", chain, network, asset, 0.01, "http://x")
    assert agentpay.spent("scout") == 0


def test_an_agent_without_a_wallet_is_refused() -> None:
    with pytest.raises(agentpay.Refused, match="no budget wallet"):
        agentpay.gate("ghost", "tempo", "testnet", tempo.TOKENS["testnet"]["pathUSD"], 0.01, "http://x")


def test_agent_payments_count_toward_the_one_budget(repo) -> None:
    licence.status(start_trial=True)
    _agent("scout", "solana", "devnet", cap=100)
    budget.set_cap(1, "day")
    agentpay.gate("scout", "solana", "devnet", solana.USDC["devnet"], 1.5, "http://x")
    s = budget.state()
    assert s["paid_usd"] == 1.5 and s["over"]
    with pytest.raises(agentpay.Refused, match="spend cap"):
        agentpay.gate("scout", "solana", "devnet", solana.USDC["devnet"], 0.01, "http://x")


# ---- the protocols, over a real local 402 --------------------------------------------------------


def test_an_mpp_402_over_the_cap_is_refused_before_signing(server) -> None:
    pytest.importorskip("mpp")
    _agent("buyer", "tempo", "testnet", cap=0.5)
    server["headers"] = {"WWW-Authenticate": _mpp_header(units=1_000_000)}
    with pytest.raises(agentpay.Refused, match="cap"):
        agentpay.pay("buyer", server["url"])
    assert agentpay.spent("buyer") == 0
    assert all(not a for a in server["seen_auth"])  # no credential ever reached the server


def test_an_x402_402_over_the_cap_is_refused_before_signing(server) -> None:
    _agent("scout", "solana", "devnet", cap=0.5)
    server["headers"] = {"PAYMENT-REQUIRED": _x402_header(units=1_000_000)}
    with pytest.raises(agentpay.Refused, match="cap"):
        agentpay.pay("scout", server["url"])
    assert agentpay.spent("scout") == 0 and all(not a for a in server["seen_auth"])


def test_an_x402_payment_is_the_reference_exact_transaction_signed_by_the_agent() -> None:
    """A 402 with x402 v2 requirements, then 200 for a PAYMENT-SIGNATURE whose transaction is a TransferChecked of
    exactly the asked amount, from the agent's token account, signed by the agent, fee payer left to the facilitator."""
    from solders.hash import Hash
    from solders.pubkey import Pubkey
    from solders.signature import Signature
    from solders.transaction import VersionedTransaction
    from knos.pro import sol_budget as sb
    addr = _agent("scout", "solana", "devnet", cap=5)
    seen = {}
    req = {"x402Version": 2, "resource": {"url": "http://127.0.0.1/paid"},
           "accepts": [{"scheme": "exact", "network": agentpay.SOLANA_CAIP2["devnet"], "asset": solana.USDC["devnet"],
                        "amount": "250000", "payTo": solana.MERCHANT, "maxTimeoutSeconds": 60,
                        "extra": {"feePayer": solana.MERCHANT, "recentBlockhash": str(Hash.default())}}]}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802
            sig = self.headers.get("PAYMENT-SIGNATURE")
            if not sig:
                self.send_response(402)
                self.send_header("PAYMENT-REQUIRED", base64.b64encode(json.dumps(req).encode()).decode())
                self.end_headers()
                return
            seen["payload"] = json.loads(base64.b64decode(sig))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"paid content")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        got = agentpay.pay("scout", f"http://127.0.0.1:{srv.server_address[1]}/paid")
    finally:
        srv.shutdown()
    assert got.status == 200 and got.paid == 0.25 and got.body == "paid content"
    p = seen["payload"]
    assert p["x402Version"] == 2 and p["accepted"] == req["accepts"][0]
    tx = VersionedTransaction.from_bytes(base64.b64decode(p["payload"]["transaction"]))
    keys = tx.message.account_keys
    assert keys[0] == Pubkey.from_string(solana.MERCHANT) and tx.signatures[0] == Signature.default()
    assert keys[1] == Pubkey.from_string(addr)
    assert tx.signatures[1].verify(Pubkey.from_string(addr), bytes([0x80]) + bytes(tx.message))
    transfer = next(ix for ix in tx.message.instructions if keys[ix.program_id_index] == sb.TOKEN_PROGRAM)
    assert bytes(transfer.data) == bytes([12]) + (250_000).to_bytes(8, "little") + bytes([6])
    assert keys[transfer.accounts[0]] == sb.ata(Pubkey.from_string(addr), Pubkey.from_string(solana.USDC["devnet"]))
    assert agentpay.spent("scout") == 0.25


def test_the_protocol_must_match_the_wallet(server) -> None:
    _agent("scout", "solana", "devnet", cap=5)
    server["headers"] = {"WWW-Authenticate": _mpp_header(units=10)}
    with pytest.raises(agentpay.Refused, match="MPP"):
        agentpay.pay("scout", server["url"])


def test_a_402_that_is_not_a_payment_request_is_just_returned(server) -> None:
    _agent("scout", "solana", "devnet", cap=5)
    server["headers"] = {}
    got = agentpay.pay("scout", server["url"])
    assert got.status == 402 and got.paid == 0


def test_the_solana_program_ids_the_sweep_uses_are_real() -> None:
    """A mistyped program id once got as far as a devnet run. Parse every one the code names."""
    solders = pytest.importorskip("solders.pubkey")
    import inspect

    src = inspect.getsource(wallets._sweep_solana)
    import re

    ids = set(re.findall(r'"([1-9A-HJ-NP-Za-km-z]{32,44})"', src))
    assert "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA" in ids and "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL" in ids
    for i in ids:
        solders.Pubkey.from_string(i)
