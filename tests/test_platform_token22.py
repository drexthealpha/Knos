"""Token-2022 extensions that would break a vault's promise (knos.platform.token22): read from synthetic account bytes
laid out as the Token-2022 program lays them out, and the refusal `knos fund-wallet` gives for such a mint. The devnet
mints these mirror are in docs/reference/PLATFORM.md."""
from __future__ import annotations

import pytest

from knos.platform import token22 as T

PK = bytes(range(1, 33))


def tlv(kind: int, body: bytes) -> bytes:
    return kind.to_bytes(2, "little") + len(body).to_bytes(2, "little") + body


def mint(*exts: bytes) -> bytes:
    base = bytearray(82)
    base[44], base[45] = 6, 1                                   # decimals, is_initialized
    return bytes(base) + bytes(165 - 82) + b"\x01" + b"".join(exts) if exts else bytes(base)


def account(state: int = 1, *exts: bytes) -> bytes:
    base = bytearray(165)
    base[108] = state
    return bytes(base) + (b"\x02" + b"".join(exts) if exts else b"")


def fee(older_bps: int, newer_bps: int) -> bytes:
    return (PK + PK + bytes(8) + bytes(8) + bytes(8) + older_bps.to_bytes(2, "little") + bytes(8) + bytes(8)
            + newer_bps.to_bytes(2, "little"))


def names(risks):
    return [(r["extension"], r["severity"]) for r in risks]


def test_a_classic_mint_and_a_plain_token_2022_mint_have_nothing_to_say():
    assert T.mint_risks(mint()) == [] and T.extensions(mint()) == {}
    plain = mint(tlv(18, PK + PK), tlv(19, b"metadata"))      # a metadata pointer and metadata change nothing a vault pays
    assert set(T.extensions(plain)) == {"MetadataPointer", "TokenMetadata"} and T.mint_risks(plain) == []


@pytest.mark.parametrize("ext, want", [
    (tlv(12, PK), [("PermanentDelegate", "refuse")]),
    (tlv(12, bytes(32)), []),                                       # no delegate set
    (tlv(26, PK + b"\x00"), [("Pausable", "refuse")]),
    (tlv(14, PK + PK), [("TransferHook", "refuse")]),
    (tlv(14, PK + bytes(32)), []),                                  # a hook extension naming no program runs nothing
    (tlv(9, b""), [("NonTransferable", "refuse")]),
    (tlv(1, fee(0, 50)), [("TransferFeeConfig", "refuse")]),
    (tlv(1, fee(25, 0)), [("TransferFeeConfig", "refuse")]),
    (tlv(1, fee(0, 0)), []),
    (tlv(6, b"\x02"), [("DefaultAccountState", "refuse")]),
    (tlv(6, b"\x01"), []),
    (tlv(4, bytes(65)), [("ConfidentialTransferMint", "warn")]),
    (tlv(3, PK), [("MintCloseAuthority", "warn")]),
    (tlv(25, bytes(56)), [("ScaledUiAmount", "warn")]),
])
def test_each_extension_that_moves_stops_or_shrinks_escrowed_money_is_named(ext, want):
    assert names(T.mint_risks(mint(ext))) == want
    assert T.refused(T.mint_risks(mint(ext))) is any(s == "refuse" for _, s in want)


def test_a_paused_mint_says_so():
    assert "paused now" in T.mint_risks(mint(tlv(26, PK + b"\x01")))[0]["why"]


def test_a_payee_account_that_requires_memos_or_is_frozen_cannot_receive_a_payout():
    assert T.account_risks(account()) == []
    assert names(T.account_risks(account(1, tlv(8, b"\x01")))) == [("MemoTransfer", "refuse")]
    assert T.account_risks(account(1, tlv(8, b"\x00"), tlv(7, b""))) == []       # memos turned off, immutable owner
    assert names(T.account_risks(account(2))) == [("frozen", "refuse")]


def test_check_tells_a_mint_from_an_account_and_from_anything_else():
    from knos.settle.v2 import pay
    t22 = str(pay.TOKEN_2022)
    assert T.check(t22, mint(tlv(12, PK)))["kind"] == "mint" and not T.check(t22, mint(tlv(12, PK)))["ok"]
    assert T.check(str(pay.TOKEN), mint())["ok"] and T.check(str(pay.TOKEN), mint())["token_2022"] is False
    assert T.check(t22, account(1, tlv(8, b"\x01")))["kind"] == "account"
    assert T.check("11111111111111111111111111111111", b"")["kind"] == "other"


def test_fund_wallet_refuses_a_mint_whose_delegate_could_take_the_escrow(monkeypatch):
    from solders.pubkey import Pubkey

    from knos import cli
    from knos.settle.v2 import pay
    m = Pubkey.from_bytes(PK)

    class L:
        def infos(self, keys):
            return [(pay.TOKEN_2022, mint(tlv(12, PK)))]
    with pytest.raises(cli.Stop, match="does not hold a bounty .*PermanentDelegate"):
        cli._mint(L(), str(m))

    class Ok:
        def infos(self, keys):
            return [(pay.TOKEN_2022, mint(tlv(18, PK + PK)))]
    assert cli._mint(Ok(), str(m)) == (m, pay.TOKEN_2022, 6)
