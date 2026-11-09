"""x402 `upto` on Solana: an agent authorizes a ceiling once, Knos charges what its checks actually used, the rest goes back.

The x402 `upto` scheme (github.com/coinbase/x402 specs/schemes/upto/scheme_upto.md, read 14 Oct 2026): "transfers up to
a maximum amount, with final charges determined at settlement based on actual resource consumption"; each
authorization settles at most once, is time bound, binds the recipient, and the settled amount is at most the
authorized maximum. The repository's only network document for it is scheme_upto_evm.md (Permit2); there is no
scheme_upto_svm.md in coinbase/x402 main on 14 Oct 2026. The x402 docs (docs.x402.org/schemes/upto, same day) say the
SVM implementation uses "the payment-channels program" (github.com/solana-foundation/payment-channels): "the client
locks the ceiling amount in an onchain channel (`open`)" and the server settles "with a signed voucher
(`settle_and_seal` + `distribute`)". The public facilitator https://x402.org/facilitator/supported lists `upto` only for
eip155:84532 on that day, so Knos runs the SVM side itself in the docs' "self-managed mode": Knos holds the receiver
authorizer key that signs vouchers and submits the settlement, with no facilitator.

The program (CHNLxYvVA28MJP9PrFuDXccuoGXAx7jBacfLEkahyGsX, the same id on devnet; audited by Cantina, July 2026, per its
README) is read from its source (program/payment_channels/src, docs/003-program-instructions.md):
    open (1)          payer locks `deposit` in the channel PDA's associated token account, commits the payout splits'
                      sha256; PDA seeds ["channel", payer, payee, mint, authorized_signer, salt u64, open_slot u64]
    settleAndSeal (4) payee-signed; with has_voucher=1 it reads the Ed25519 precompile instruction right before it: the
                      50-byte voucher [0x56,0x01] || channel || cumulative u64 || expires_at i64, signed by
                      `authorized_signer`; then the channel is SEALED
    distribute (7)    permissionless; pays the splits and the payee's remainder of `settled`, refunds deposit - settled
                      to the payer, sweeps rounding dust to ATA(TREASURY_OWNER, mint) and closes the vault
    withdrawPayer (8) the payer's own refund of deposit - settled once SEALED (an escape route)
Knos sends Ed25519 + settleAndSeal + distribute as ONE v1 transaction (4,096 bytes, no lookup table), where the
program's own notes ask for a v0 transaction and a lookup table for many recipients.

What Knos charges is decided by Knos's meter (`used` below), never by the payer's word; what the program guarantees
the payer is that no more than the ceiling can be taken, only to the payee and splits fixed at `open`, and that the
remainder comes back.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

PROGRAM = Pubkey.from_string("CHNLxYvVA28MJP9PrFuDXccuoGXAx7jBacfLEkahyGsX")
ED25519 = Pubkey.from_string("Ed25519SigVerify111111111111111111111111111")
SYSTEM = Pubkey.from_string("11111111111111111111111111111111")
RENT = Pubkey.from_string("SysvarRent111111111111111111111111111111111")
INSTRUCTIONS = Pubkey.from_string("Sysvar1nstructions1111111111111111111111111")
ATA_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
TOKEN = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
# The owner of the treasury token account `distribute` sweeps dust to is compiled into each deployment
# (program/payment_channels/src/constants.rs). Mainnet: the source's value. Devnet: read from the deployed program's own
# distribute transactions on 14 Oct 2026 (account 6 of two distributes is ATA BSMX9adN..., owner 4zTeC5mV...).
TREASURY_OWNER = {"mainnet": Pubkey.from_string("Cs2zdfUNonRdRGsiZUQQLdTxzxVvJZmgiX2mpLYKuEqP"),
                  "devnet": Pubkey.from_string("4zTeC5mVqWLruDexgU2mV66p9t5vCA9JyiZqdGDUspap")}
NETWORK = {"devnet": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1", "mainnet": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"}
MAGIC = bytes([0x56, 0x01])
OPEN_SLOT_WINDOW = 1_500        # slots: `open` must land within this of its open_slot (constants.rs)
MAX_RECIPIENTS = 32
STATUS = {0: "open", 1: "sealed", 2: "closing", 3: "distributed"}


def ata(owner: Pubkey, mint: Pubkey, token_program: Pubkey = TOKEN) -> Pubkey:
    return Pubkey.find_program_address([bytes(owner), bytes(token_program), bytes(mint)], ATA_PROGRAM)[0]


def channel_pda(payer: Pubkey, payee: Pubkey, mint: Pubkey, signer: Pubkey, salt: int, open_slot: int) -> Pubkey:
    return Pubkey.find_program_address([b"channel", bytes(payer), bytes(payee), bytes(mint), bytes(signer),
                                        salt.to_bytes(8, "little"), open_slot.to_bytes(8, "little")], PROGRAM)[0]


def event_authority() -> Pubkey:
    return Pubkey.find_program_address([b"event_authority"], PROGRAM)[0]


def splits_bytes(splits: list[tuple[Pubkey, int]]) -> bytes:
    """The distribution preimage: count u32 || (recipient 32 || bps u16)*. Every bps > 0, total <= 10,000, no repeats;
    the payee gets the remainder."""
    if len(splits) > MAX_RECIPIENTS or any(b <= 0 for _r, b in splits) or sum(b for _r, b in splits) > 10_000 \
            or len({bytes(r) for r, _b in splits}) != len(splits):
        raise ValueError("splits: at most 32 recipients, each a share of 1 to 10,000 basis points, 10,000 in all, no repeats")
    return len(splits).to_bytes(4, "little") + b"".join(bytes(r) + b.to_bytes(2, "little") for r, b in splits)


def open_ix(payer: Pubkey, rent_payer: Pubkey, payee: Pubkey, mint: Pubkey, signer: Pubkey, salt: int, deposit: int, grace_s: int,
            open_slot: int, splits: list[tuple[Pubkey, int]], token_program: Pubkey = TOKEN) -> Instruction:
    if deposit <= 0 or grace_s <= 0:
        raise ValueError("the deposit and the grace period must be positive")
    ch = channel_pda(payer, payee, mint, signer, salt, open_slot)
    data = (bytes([1]) + salt.to_bytes(8, "little") + deposit.to_bytes(8, "little") + grace_s.to_bytes(4, "little")
            + open_slot.to_bytes(8, "little") + splits_bytes(splits))
    return Instruction(PROGRAM, data, [
        AccountMeta(payer, True, True), AccountMeta(rent_payer, True, True), AccountMeta(payee, False, False), AccountMeta(mint, False, False),
        AccountMeta(signer, False, False), AccountMeta(ch, False, True), AccountMeta(ata(payer, mint, token_program), False, True),
        AccountMeta(ata(ch, mint, token_program), False, True), AccountMeta(token_program, False, False), AccountMeta(SYSTEM, False, False),
        AccountMeta(RENT, False, False), AccountMeta(ATA_PROGRAM, False, False), AccountMeta(event_authority(), False, False),
        AccountMeta(PROGRAM, False, False)])


@dataclass(frozen=True)
class Opened:
    payer: Pubkey
    rent_payer: Pubkey
    payee: Pubkey
    mint: Pubkey
    signer: Pubkey
    channel: Pubkey
    salt: int
    deposit: int
    grace_s: int
    open_slot: int
    splits: list
    token_program: Pubkey


def read_open(ix_data: bytes, keys: list[Pubkey]) -> Opened:
    """An `open` instruction taken apart (data and its account keys in order), so the server checks what the payer
    signed rather than what a JSON envelope claims (the program's ADR-002, server requirement 2)."""
    d = bytes(ix_data)
    if d[:1] != b"\x01" or len(d) < 33:
        raise ValueError("not an open instruction")
    salt, deposit = int.from_bytes(d[1:9], "little"), int.from_bytes(d[9:17], "little")
    grace, slot, n = int.from_bytes(d[17:21], "little"), int.from_bytes(d[21:29], "little"), int.from_bytes(d[29:33], "little")
    if len(d) != 33 + 34 * n:
        raise ValueError("the splits do not fill the instruction")
    splits = [(Pubkey.from_bytes(d[33 + 34 * i:65 + 34 * i]), int.from_bytes(d[65 + 34 * i:67 + 34 * i], "little")) for i in range(n)]
    return Opened(keys[0], keys[1], keys[2], keys[3], keys[4], keys[5], salt, deposit, grace, slot, splits, keys[8])


def voucher(channel: Pubkey, cumulative: int, expires_at: int = 0) -> bytes:
    """The 50 bytes the authorized signer signs."""
    return MAGIC + bytes(channel) + cumulative.to_bytes(8, "little") + expires_at.to_bytes(8, "little", signed=True)


def ed25519_ix(signer: Keypair, message: bytes) -> Instruction:
    """The one-signature Ed25519 precompile instruction in the canonical layout the program insists on (pubkey at 16,
    signature at 48, message at 112, every instruction index 0xFFFF: all inside this instruction)."""
    sig = bytes(signer.sign_message(message))
    pk = bytes(signer.pubkey())
    head = bytes([1, 0]) + b"".join(v.to_bytes(2, "little") for v in (48, 0xFFFF, 16, 0xFFFF, 112, len(message), 0xFFFF))
    return Instruction(ED25519, head + pk + sig + message, [])


def settle_and_seal_ix(payee: Pubkey, channel: Pubkey, with_voucher: bool = True) -> Instruction:
    return Instruction(PROGRAM, bytes([4, 1 if with_voucher else 0]),
                       [AccountMeta(payee, True, False), AccountMeta(channel, False, True), AccountMeta(INSTRUCTIONS, False, False)])


def distribute_ix(channel: Pubkey, payer: Pubkey, rent_payer: Pubkey, payee: Pubkey, mint: Pubkey, splits: list[tuple[Pubkey, int]],
                  cluster: str = "devnet", token_program: Pubkey = TOKEN) -> Instruction:
    metas = [AccountMeta(channel, False, True), AccountMeta(payer, False, True), AccountMeta(rent_payer, False, True),
             AccountMeta(ata(channel, mint, token_program), False, True), AccountMeta(ata(payer, mint, token_program), False, True),
             AccountMeta(ata(payee, mint, token_program), False, True), AccountMeta(ata(TREASURY_OWNER[cluster], mint, token_program), False, True),
             AccountMeta(mint, False, False), AccountMeta(token_program, False, False), AccountMeta(event_authority(), False, False),
             AccountMeta(PROGRAM, False, False)]
    metas += [AccountMeta(ata(r, mint, token_program), False, True) for r, _b in splits]
    return Instruction(PROGRAM, bytes([7]) + splits_bytes(splits), metas)


def withdraw_payer_ix(payer: Pubkey, channel: Pubkey, mint: Pubkey, token_program: Pubkey = TOKEN) -> Instruction:
    return Instruction(PROGRAM, bytes([8]), [AccountMeta(payer, True, False), AccountMeta(channel, False, True),
                                             AccountMeta(ata(channel, mint, token_program), False, True),
                                             AccountMeta(ata(payer, mint, token_program), False, True), AccountMeta(mint, False, False),
                                             AccountMeta(token_program, False, False)])


@dataclass(frozen=True)
class Channel:
    status: str
    salt: int
    deposit: int
    settled: int
    payout_watermark: int
    grace_s: int
    distribution_hash: bytes
    payer: Pubkey
    payee: Pubkey
    signer: Pubkey
    mint: Pubkey
    rent_payer: Pubkey
    open_slot: int


def read_channel(data: bytes | None) -> Channel | None:
    """The 256-byte Channel account (state/channel.rs)."""
    if data is None or len(data) != 256:
        return None
    d, u = bytes(data), (lambda a, b: int.from_bytes(bytes(data)[a:b], "little"))

    def k(a: int) -> Pubkey:
        return Pubkey.from_bytes(d[a:a + 32])
    return Channel(STATUS.get(d[3], f"unknown {d[3]}"), u(4, 12), u(12, 20), u(20, 28), u(28, 36), u(52, 56), d[56:88],
                   k(88), k(120), k(152), k(184), k(216), u(248, 256))


# -- x402 v2 framing --------------------------------------------------------------------------------------------------
def requirements(*, ceiling: int, mint: Pubkey, pay_to: Pubkey, receiver_authorizer: Pubkey, decimals: int, resource: str,
                 cluster: str = "devnet", grace_s: int = 900, splits: list[tuple[Pubkey, int]] | None = None, timeout_s: int = 600,
                 token_program: Pubkey = TOKEN) -> dict:
    """One PaymentRequirements entry of a 402 for the `upto` scheme on Solana. `amount` is the ceiling here, at
    verification; the settled amount is what was used (scheme_upto.md, "Phase-Dependent amount Semantics"). The
    `extra` fields are what an SVM client needs to build `open`; their names follow the program's own HTTP notes
    (docs/002-http-protocol.md: channelProgram, gracePeriodSeconds, distributionSplits) because no SVM payload for
    x402 `upto` is published."""
    return {"scheme": "upto", "network": NETWORK[cluster], "amount": str(ceiling), "asset": str(mint), "payTo": str(pay_to),
            "maxTimeoutSeconds": timeout_s, "resource": resource,
            "extra": {"channelProgram": str(PROGRAM), "receiverAuthorizer": str(receiver_authorizer), "decimals": decimals,
                      "gracePeriodSeconds": grace_s, "tokenProgram": str(token_program),
                      "distributionSplits": [{"recipient": str(r), "shareBps": b} for r, b in (splits or [])]}}


def check_open(opened: Opened, req: dict) -> list[str]:
    """Why an `open` does not match the 402 it answers; empty when it does. The server checks this before it signs
    or pays for anything (ADR-002 requirement 2): payee, mint, authorized signer, grace, splits and the deposit."""
    ex, out = req["extra"], []
    if str(opened.payee) != req["payTo"]:
        out.append(f"payee {opened.payee} is not {req['payTo']}")
    if str(opened.mint) != req["asset"]:
        out.append(f"mint {opened.mint} is not {req['asset']}")
    if str(opened.signer) != ex["receiverAuthorizer"]:
        out.append("the voucher signer is not Knos's receiver authorizer")
    if opened.grace_s != ex["gracePeriodSeconds"]:
        out.append(f"grace period {opened.grace_s} s is not {ex['gracePeriodSeconds']} s")
    want = [(s["recipient"], s["shareBps"]) for s in ex["distributionSplits"]]
    if [(str(r), b) for r, b in opened.splits] != want:
        out.append("the splits are not the ones asked for")
    if opened.deposit != int(req["amount"]):
        out.append(f"deposit {opened.deposit} is not the ceiling {req['amount']}")
    if str(opened.token_program) != ex["tokenProgram"]:
        out.append("another token program")
    if opened.channel != channel_pda(opened.payer, opened.payee, opened.mint, opened.signer, opened.salt, opened.open_slot):
        out.append("the channel is not the address its seeds give")
    return out


def settle_ixs(authorizer: Keypair, payee: Pubkey, ch: Channel, channel: Pubkey, used: int, splits: list[tuple[Pubkey, int]],
               cluster: str = "devnet", token_program: Pubkey = TOKEN, expires_at: int = 0) -> list[Instruction]:
    """The settlement as one transaction's instructions: the voucher for `used` (Ed25519), settleAndSeal, distribute.
    `used` must be more than what is settled already and at most the deposit; `used` == 0 seals with no voucher and
    refunds everything."""
    if used < 0 or used > ch.deposit:
        raise ValueError(f"used {used} is outside 0..{ch.deposit} (the ceiling the payer holds in the channel)")
    if hashlib.sha256(splits_bytes(splits)).digest() != ch.distribution_hash:
        raise ValueError("these splits are not the ones the channel was opened with")
    head = [ed25519_ix(authorizer, voucher(channel, used, expires_at)), settle_and_seal_ix(payee, channel, True)] if used > ch.settled \
        else [settle_and_seal_ix(payee, channel, False)]
    return head + [distribute_ix(channel, ch.payer, ch.rent_payer, payee, ch.mint, splits, cluster, token_program)]


def response(signature: str, cluster: str, used: int, ceiling: int, payer: Pubkey) -> dict:
    """The PAYMENT-RESPONSE body: what was settled and refunded, and where."""
    return {"success": True, "transaction": signature, "network": NETWORK[cluster], "payer": str(payer),
            "amount": str(used), "refunded": str(ceiling - used), "scheme": "upto"}
