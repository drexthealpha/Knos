"""Client for knos-passkey's Fund (1.1): a funder with only a passkey funds a knos_pay work order. Pure builders and
the reader of the one line a relay picks up; no network. The browser side is web/passkey_fund.js, and
tests/test_passkey_fund.py sends what this module builds to both programs.

The passkey signs a WebAuthn assertion whose challenge is `fund_challenge(mint, data, expiry_slot, nonce)`: `data`
is the whole instruction data of knos_pay's FundOrderWallet (`pay.fund_order_wallet_ix(wallet, ...).data`, which
names the issue, the amount, the pinned workflows and the terms), `nonce` is the wallet's nonce plus one. One
transaction then carries, with anyone paying its fee:

    passkey.open_ix(payer, key)       only while the wallet account does not exist
    *rent_ixs(payer, order, ov, ...)  the rent of the order and of its token account: the wallet cannot pay it
    *fund_ixs(...)                    the secp256r1 check, then Fund: keep the two adjacent, in this order

The fee on top of the amount is knos_pay's: Fund computes none and logs what left the wallet beyond the amount.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer

from knos.settle.v2 import passkey as pk
from knos.settle.v2 import pay

FUND_DOMAIN = b"knos-passkey:fund"
FUND_ORDER_WALLET = 15          # knos_pay's instruction tag
FUND_MIN = 158                  # the tag and the 157 bytes FundOrderWallet requires before the terms
ORDER_LEN = 512
SALTED = 1 + 37 + 32            # where a private order says so in the data (opts byte 32); its scope then follows at 158
ERRORS = {123: "the slot is past the expiry slot the passkey signed for; sign again",
          124: "the instruction to fund with is not a FundOrderWallet of the knos_pay this program is pinned to"}
COMMENT = "/knos passkey-fund"
LINE = re.compile(r"/knos passkey-fund\s+([A-Za-z0-9_-]{300,6000})")


def fund_challenge(mint: Pubkey, data: bytes, expiry_slot: int, nonce: int, pay_program: Pubkey = pay.PAY_ID) -> bytes:
    """The 32 bytes the passkey signs to fund the order `data` describes, in `mint`, as the wallet's number `nonce`,
    in no slot after `expiry_slot`."""
    return hashlib.sha256(FUND_DOMAIN + bytes(pay_program) + bytes(mint) + bytes(data) + expiry_slot.to_bytes(8, "little")
                          + nonce.to_bytes(8, "little")).digest()


def order_of(wallet: Pubkey, data: bytes, pay_program: Pubkey = pay.PAY_ID) -> Pubkey:
    """The address of the order a FundOrderWallet with this data creates when `wallet` is its funder."""
    data = bytes(data)
    if len(data) < FUND_MIN or data[0] != FUND_ORDER_WALLET:
        raise ValueError("not the instruction data of FundOrderWallet")
    issue, repo, seq = int.from_bytes(data[1:9], "little"), int.from_bytes(data[9:17], "little"), int.from_bytes(data[34:38], "little")
    scope = data[FUND_MIN:FUND_MIN + 32] if data[SALTED] == 1 else pay.scope_of(repo, issue)
    return pay.order_pda(scope, wallet, seq, pay_program)


def fund_ix(key: bytes, mint: Pubkey, data: bytes, expiry_slot: int, nonce: int, client_data_json: bytes, token_program: Pubkey = pay.TOKEN,
            from_token: Pubkey | None = None, program: Pubkey = pk.PASSKEY_ID, pay_program: Pubkey = pay.PAY_ID) -> Instruction:
    """Fund alone; it is refused unless the instruction right before it is `secp256r1_ix` for the same assertion.
    `from_token`: the wallet's token account to spend (default: its associated one)."""
    w, cdj = pk.wallet(key, program), bytes(client_data_json)
    order = order_of(w, data, pay_program)
    body = expiry_slot.to_bytes(8, "little") + nonce.to_bytes(8, "little") + len(cdj).to_bytes(2, "little") + cdj + bytes(data)
    return Instruction(program, b"\x02" + body,
                       [AccountMeta(w, False, True), AccountMeta(from_token or pay.ata(w, mint, token_program), False, True), AccountMeta(mint, False, False),
                        AccountMeta(order, False, True), AccountMeta(pay.ov_pda(order, pay_program), False, True),
                        AccountMeta(pay.auth_pda(pay_program), False, False), AccountMeta(token_program, False, False), AccountMeta(pay.SYSTEM, False, False),
                        AccountMeta(pay.pause_pda(pay_program), False, False), AccountMeta(pay_program, False, False), AccountMeta(pk.INSTRUCTIONS, False, False)])


def fund_ixs(key: bytes, mint: Pubkey, data: bytes, expiry_slot: int, nonce: int, authenticator_data: bytes, client_data_json: bytes, signature: bytes,
             **kw) -> list[Instruction]:
    """The two instructions of a funding, from a WebAuthn assertion: the precompile, then Fund. Keep them adjacent."""
    message = bytes(authenticator_data) + hashlib.sha256(bytes(client_data_json)).digest()
    return [pk.secp256r1_ix(key, signature, message), fund_ix(key, mint, data, expiry_slot, nonce, client_data_json, **kw)]


def rent_ixs(payer: Pubkey, order: Pubkey, ov: Pubkey, order_rent: int, ov_rent: int, order_has: int = 0, ov_has: int = 0) -> list[Instruction]:
    """The sender's lamports for the order and its token account, before Fund: `order_rent` and `ov_rent` are the
    cluster's rent for ORDER_LEN bytes and for a token account of the mint; `*_has` is what the address holds already."""
    return [transfer(TransferParams(from_pubkey=payer, to_pubkey=to, lamports=need - has))
            for to, need, has in ((order, order_rent, order_has), (ov, ov_rent, ov_has)) if need > has]


# -- the intent: the one object a relay needs, and the one line it travels in -----------------------------------------
@dataclass(frozen=True)
class Intent:
    key: bytes
    mint: Pubkey
    token_program: Pubkey
    data: bytes
    expiry_slot: int
    nonce: int
    authenticator_data: bytes
    client_data_json: bytes
    signature: bytes

    @property
    def wallet(self) -> Pubkey:
        return pk.wallet(self.key)

    @property
    def order(self) -> Pubkey:
        return order_of(self.wallet, self.data)

    @property
    def amount(self) -> int:
        return int.from_bytes(self.data[17:25], "little")

    def ixs(self) -> list[Instruction]:
        return fund_ixs(self.key, self.mint, self.data, self.expiry_slot, self.nonce, self.authenticator_data, self.client_data_json, self.signature,
                        token_program=self.token_program)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def intent(i: Intent) -> dict:
    """The JSON object web/passkey_fund.js's passkeyFundIntent returns. `wallet`, `order` and `amount` are for a
    reader's eyes: `read_intent` derives them again and refuses an object in which they differ."""
    return {"v": 1, "program": str(pk.PASSKEY_ID), "pay": str(pay.PAY_ID), "key": i.key.hex(), "wallet": str(i.wallet), "mint": str(i.mint),
            "tokenProgram": str(i.token_program), "order": str(i.order), "amount": i.amount, "data": _b64(i.data), "expirySlot": i.expiry_slot,
            "nonce": i.nonce, "authenticatorData": _b64(i.authenticator_data), "clientDataJSON": _b64(i.client_data_json),
            "signature": _b64(pk.raw_signature(i.signature))}


def intent_comment(i: Intent | dict) -> str:
    """`/knos passkey-fund <base64url of the JSON>`: the one line a relay picks up."""
    obj = intent(i) if isinstance(i, Intent) else i
    return f"{COMMENT} {_b64(json.dumps(obj, separators=(',', ':')).encode())}"


def read_intent(text: str | dict) -> Intent:
    """An intent read back from its object, its base64url text or the whole comment. ValueError says what is wrong.
    Nothing here says the assertion is good: the chain does, when the two instructions are simulated or sent."""
    try:
        if isinstance(text, dict):
            o = text
        else:
            m = LINE.search(str(text))
            o = json.loads(_unb64(m.group(1) if m else str(text).strip()))
        if o.get("v") != 1 or o.get("program") != str(pk.PASSKEY_ID) or o.get("pay") != str(pay.PAY_ID):
            raise ValueError("it is for another version or another deployment")
        i = Intent(key=pk.compressed(bytes.fromhex(o["key"])), mint=Pubkey.from_string(o["mint"]), token_program=Pubkey.from_string(o["tokenProgram"]),
                   data=_unb64(o["data"]), expiry_slot=int(o["expirySlot"]), nonce=int(o["nonce"]), authenticator_data=_unb64(o["authenticatorData"]),
                   client_data_json=_unb64(o["clientDataJSON"]), signature=pk.raw_signature(_unb64(o["signature"])))
        if (str(i.wallet), str(i.order), i.amount) != (o.get("wallet"), o.get("order"), o.get("amount")):
            raise ValueError("its wallet, order or amount is not what its own data gives")
        if i.token_program not in (pay.TOKEN, pay.TOKEN_2022):
            raise ValueError("its token program is neither SPL Token nor Token-2022")
        return i
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"not a passkey funding intent: {e}") from None
    except ValueError as e:
        raise ValueError(f"not a passkey funding intent: {e}") from None
