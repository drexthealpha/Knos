"""Budgets the chain enforces. Solana: an SPL delegate on a per-agent vault, live on the local validator; the agent's
key signing directly (no Knos code in the way) cannot move a token beyond its allowance. Tempo: the Keychain call
encoding and the remaining-allowance read, offline (the live Moderato run is a recorded measurement)."""

from __future__ import annotations

import pytest

from _devchain import URL, devchain, funded
from knos.pro import sol_budget as sb
from knos.team import rpc
from solders.keypair import Keypair


def _mint(owner: Keypair, decimals: int = 6):
    mint = Keypair()
    lamports = rpc.call(URL, "getMinimumBalanceForRentExemption", [sb.MINT_SIZE])
    from solders.system_program import CreateAccountParams, create_account
    rpc.send(URL, [create_account(CreateAccountParams(from_pubkey=owner.pubkey(), to_pubkey=mint.pubkey(),
                                                      lamports=lamports, space=sb.MINT_SIZE, owner=sb.TOKEN_PROGRAM)),
                   sb.initialize_mint2(mint.pubkey(), decimals, owner.pubkey())], owner, [mint])
    return mint.pubkey()


def test_token_account_layout():
    raw = bytearray(165)
    raw[0:32] = bytes([1]) * 32
    raw[32:64] = bytes([2]) * 32
    raw[64:72] = (7).to_bytes(8, "little")
    raw[72:76] = (1).to_bytes(4, "little")
    raw[76:108] = bytes([3]) * 32
    raw[121:129] = (5).to_bytes(8, "little")
    got = sb.parse_token_account(bytes(raw))
    assert got["amount"] == 7 and got["delegated_amount"] == 5 and bytes(got["delegate"]) == bytes([3]) * 32


def test_instruction_bytes():
    k = [Keypair().pubkey() for _ in range(4)]
    assert sb.approve_checked(k[0], k[1], k[2], k[3], 20_000_000, 6).data == bytes([13]) + (20_000_000).to_bytes(
        8, "little") + b"\x06"
    assert sb.transfer_checked(k[0], k[1], k[2], k[3], 1, 6).data == bytes([12, 1, 0, 0, 0, 0, 0, 0, 0, 6])
    assert sb.revoke(k[0], k[1]).data == b"\x05"
    ix = sb.transfer_checked(k[0], k[1], k[2], k[3], 1, 6)
    assert [(m.is_signer, m.is_writable) for m in ix.accounts] == [(False, True), (False, False), (False, True),
                                                                   (True, False)]


@devchain
def test_the_agent_key_cannot_spend_past_its_delegate_allowance():
    owner = funded(3)          # the team's vault key (encrypted at rest in the product)
    agent = funded(1)          # the agent's own key: it pays its own fees here, and holds no tokens
    mint = _mint(owner)
    vault = Keypair()
    rpc.send(URL, sb.new_vault_ixs(URL, owner.pubkey(), owner.pubkey(), vault, mint), owner, [vault])
    rpc.send(URL, [sb.mint_to_checked(mint, vault.pubkey(), owner.pubkey(), 100_000_000, 6),
                   sb.approve_checked(vault.pubkey(), mint, agent.pubkey(), owner.pubkey(), 20_000_000, 6)], owner)
    shop = Keypair().pubkey()
    rpc.send(URL, [sb.create_ata_idempotent(owner.pubkey(), shop, mint)], owner)
    dest = sb.ata(shop, mint)

    def pay(amount):  # signed by the agent's key alone: Knos is not involved at all
        return rpc.send(URL, [sb.transfer_checked(vault.pubkey(), mint, dest, agent.pubkey(), amount, 6)], agent)

    pay(15_000_000)
    assert sb.status(URL, vault.pubkey())["delegated_amount"] == 5_000_000
    refused = 0
    for _ in range(20):  # the bench runs 200
        try:
            pay(6_000_000)
        except rpc.RpcError:
            refused += 1
    assert refused == 20
    pay(5_000_000)  # exactly the rest is fine
    with pytest.raises(rpc.RpcError):
        pay(1)
    assert sb.status(URL, vault.pubkey())["amount"] == 80_000_000  # 20 moved, never more

    # the agent's key cannot re-approve itself: only the vault owner can
    with pytest.raises(rpc.RpcError):
        rpc.send(URL, [sb.approve_checked(vault.pubkey(), mint, agent.pubkey(), agent.pubkey(), 50_000_000, 6)],
                 agent)
    rpc.send(URL, [sb.approve_checked(vault.pubkey(), mint, agent.pubkey(), owner.pubkey(), 1_000_000, 6)], owner)
    rpc.send(URL, [sb.revoke(vault.pubkey(), owner.pubkey())], owner)
    with pytest.raises(rpc.RpcError):
        pay(1)


def test_tempo_remaining_is_read_with_the_documented_selector(monkeypatch):
    from knos.pro import tempo_keys as tk
    seen = {}

    def fake(url, method, params, timeout=20.0):
        seen["data"] = params[0]["data"]
        return "0x" + (399_640).to_bytes(32, "big").hex() + (1_790_845_473).to_bytes(32, "big").hex()

    monkeypatch.setattr(tk, "rpc", fake)
    root, agent, token = "0x" + "11" * 20, "0x" + "22" * 20, "0x20c0000000000000000000000000000000000001"
    assert tk.remaining("u", root, agent, token) == (399_640, 1_790_845_473)
    assert seen["data"].startswith("0xa7f72cab") and seen["data"].endswith(token[2:])


def test_tempo_authorize_encodes_a_periodic_limit_and_one_allowed_call():
    pytest.importorskip("pytempo")
    from pytempo import CallScope, KeyRestrictions, SignatureType, TokenLimit
    from pytempo.contracts import AccountKeychain
    token = "0x20c0000000000000000000000000000000000001"
    r = KeyRestrictions(expiry=2_000_000_000, limits=[TokenLimit(token=token, limit=5_000_000, period=86_400)],
                        allowed_calls=[CallScope.transfer_with_memo(target=token)])
    expiry, enforce, limits, any_calls, calls = r.to_abi_tuple()
    assert enforce is True and any_calls is False and limits[0][1:] == (5_000_000, 86_400)
    call = AccountKeychain.authorize_key(key_id="0x" + "22" * 20, signature_type=SignatureType.SECP256K1,
                                        restrictions=r)
    assert bytes(call.to).hex() == "aaaaaaaa00000000000000000000000000000000"


def test_budget_show_chain_tempo_watch_rereads_rpc(monkeypatch):
    """knos budget show --chain tempo --watch re-reads getRemainingLimitWithPeriod every N seconds."""
    from knos.cli import app
    from knos.pro import chainbudget as cb
    from knos.pro import tempo_keys as tk
    from typer.testing import CliRunner

    fake_entries = {
        "claude@tempo": {
            "chain": "tempo",
            "network": "moderato",
            "token": "0x20c0000000000000000000000000000000000001",
            "root": "0x" + "11" * 20,
            "key": "0x" + "22" * 20,
            "amount": 5.0,
            "period": 86400,
        },
        "sol_agent@solana": {
            "chain": "solana",
            "network": "devnet",
            "amount": 20.0,
        },
    }
    monkeypatch.setattr(cb, "entries", lambda: fake_entries)

    calls = []
    allowances = [5_000_000, 4_500_000, 3_000_000]

    def fake_rpc(url, method, params, timeout=20.0):
        calls.append((method, params))
        remaining_units = allowances[min(len(calls) - 1, len(allowances) - 1)]
        return "0x" + remaining_units.to_bytes(32, "big").hex() + (1_790_845_473).to_bytes(32, "big").hex()

    monkeypatch.setattr(tk, "rpc", fake_rpc)

    runner = CliRunner()
    res = runner.invoke(app, ["budget", "show", "--chain", "tempo", "--watch", "--count", "3", "--every", "0.01"])
    assert res.exit_code == 0, res.output
    assert len(calls) == 3
    # Check that selector a7f72cab (getRemainingLimitWithPeriod) was queried
    for _, params in calls:
        assert params[0]["data"].startswith("0xa7f72cab")
    # Solana entry must be filtered out
    assert "sol_agent@solana" not in res.output
    # Output displays changing remaining limits
    assert "claude@tempo" in res.output
    assert "5 left" in res.output
    assert "4.5 left" in res.output
    assert "3 left" in res.output


def test_budget_show_watch_stops_on_keyboard_interrupt(monkeypatch):
    """--watch loop sleeps every N seconds and terminates gracefully on KeyboardInterrupt."""
    import time
    from knos.cli import app
    from knos.pro import chainbudget as cb
    from knos.pro import tempo_keys as tk
    from typer.testing import CliRunner

    monkeypatch.setattr(cb, "entries", lambda: {
        "claude@tempo": {
            "chain": "tempo",
            "network": "moderato",
            "token": "0x20c0000000000000000000000000000000000001",
            "root": "0x" + "11" * 20,
            "key": "0x" + "22" * 20,
            "amount": 5.0,
            "period": 86400,
        }
    })

    monkeypatch.setattr(tk, "rpc", lambda url, method, params, timeout=20.0: (
        "0x" + (5_000_000).to_bytes(32, "big").hex() + (1_790_845_473).to_bytes(32, "big").hex()
    ))

    sleep_calls = []

    def fake_sleep(secs):
        sleep_calls.append(secs)
        if len(sleep_calls) >= 2:
            raise KeyboardInterrupt()

    monkeypatch.setattr(time, "sleep", fake_sleep)

    runner = CliRunner()
    res = runner.invoke(app, ["budget", "show", "--chain", "tempo", "--watch", "--every", "1.5"])
    assert res.exit_code == 0, res.output
    assert sleep_calls == [1.5, 1.5]


def test_budget_show_invalid_chain():
    """Invalid chain names are rejected with clear help."""
    from knos.cli import app
    from typer.testing import CliRunner

    runner = CliRunner()
    res = runner.invoke(app, ["budget", "show", "--chain", "invalidchain"])
    assert res.exit_code != 0
    assert "No chain called invalidchain" in (res.output + str(res.exception))
