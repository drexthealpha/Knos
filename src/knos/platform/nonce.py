"""Durable nonces: a vault transaction signed now, offline or by several people one after the other, sent later.

A transaction normally names a recent blockhash and dies with it, about 33 s on devnet today (knos.platform.blockhash).
That is too short for a funder whose approver signs on another machine, a financier who signs an assignment
a hardware or cold wallet, or an agent that prepares a funding while its owner approves it. A durable
nonce replaces the blockhash with a value stored in a nonce account; the transaction stays good until that value is
advanced, and the first instruction of the transaction advances it, so the same bytes can land once and never again
(https://solana.com/docs/advanced/confirmation, durable transaction nonces; SIMD-0242 "Static Nonce Account Only" is
active, so the nonce account must be one of the message's own keys, which a v1 message always has: it has no lookup tables).

Here:
    create_ixs(payer, nonce, authority, lamports)   the two instructions that make a nonce account (System program)
    read(data)                                      a nonce account's authority, current value and fee
    message(ixs, fee_payer, nonce, authority, value, v1)  the message: AdvanceNonceAccount first, the value as blockhash
    sign_part(msg, keypairs) / add(tx, keypair)     partial signatures: each party signs the same message bytes
    missing(tx)                                     who has not signed yet
    send(ledger, tx)                                hand the finished transaction to the cluster (no blockhash fetched)

`python -m knos.platform.nonce` does the same from a shell: `create`, `show`, `cosign` (add one signature to a
transaction file) and `send`. The relay never holds a funder's key: it signs as fee payer, or not at all. The devnet
run in scripts/capabilities_devnet.py funds a knos_pay order this way (docs/reference/PLATFORM.md).
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Iterable

from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import Message, MessageV1, TransactionConfig, to_bytes_versioned
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.system_program import advance_nonce_account, create_nonce_account
from solders.transaction import VersionedTransaction

NONCE_SIZE = 80                 # u32 version, u32 state, authority (32), the value (32), lamports per signature (u64)
SYSTEM = Pubkey.from_string("11111111111111111111111111111111")
LOADED = 64 * 1024 * 1024       # as knos.chain.V1_LOADED


@dataclass(frozen=True)
class NonceAccount:
    authority: Pubkey
    value: Hash                 # the "blockhash" a transaction using this nonce names
    lamports_per_signature: int


def create_ixs(payer: Pubkey, nonce: Pubkey, authority: Pubkey, lamports: int) -> list[Instruction]:
    """CreateAccount + InitializeNonceAccount. `lamports`: the rent of NONCE_SIZE bytes (ledger.rent(80)); the nonce
    keypair signs the CreateAccount, the payer pays."""
    return list(create_nonce_account(payer, nonce, authority, lamports))


def read(data: bytes | None) -> NonceAccount | None:
    """An initialized nonce account (version 1, state 1); None for anything else."""
    if data is None or len(data) != NONCE_SIZE:
        return None
    if int.from_bytes(data[0:4], "little") != 1 or int.from_bytes(data[4:8], "little") != 1:
        return None
    return NonceAccount(Pubkey.from_bytes(data[8:40]), Hash.from_bytes(data[40:72]), int.from_bytes(data[72:80], "little"))


def advance_ix(nonce: Pubkey, authority: Pubkey) -> Instruction:
    return advance_nonce_account({"nonce_pubkey": nonce, "authorized_pubkey": authority})


def message(ixs: Iterable[Instruction], fee_payer: Pubkey, nonce: Pubkey, authority: Pubkey, value: Hash, v1: bool = True,
            units: int = 1_400_000) -> MessageV1 | Message:
    """The message of a durable-nonce transaction: AdvanceNonceAccount first (the runtime looks for it there), then
    `ixs`, with the nonce's current value where a blockhash would be. v1 (default): the compute-unit limit in the message
    and 4,096 bytes; else a legacy message with the same instructions."""
    body = [advance_ix(nonce, authority), *[ix for ix in ixs if not _is_advance(ix)]]
    if v1:
        return MessageV1.try_compile(fee_payer, body, value, TransactionConfig(compute_unit_limit=units, loaded_accounts_data_size_limit=LOADED,
                                                                                priority_fee=None))
    return Message.new_with_blockhash(body, fee_payer, value)


def _is_advance(ix: Instruction) -> bool:
    return ix.program_id == SYSTEM and bytes(ix.data)[:4] == (4).to_bytes(4, "little")


def _signers(msg) -> list[Pubkey]:
    return list(msg.account_keys[:msg.header.num_required_signatures])


def _bytes(msg) -> bytes:
    return to_bytes_versioned(msg) if isinstance(msg, MessageV1) else bytes(msg)


def sign_part(msg, keypairs: Iterable[Keypair]) -> VersionedTransaction:
    """The transaction with the signatures of `keypairs` and a blank (all-zero) one for every other required signer."""
    have = {kp.pubkey(): kp for kp in keypairs}
    raw = _bytes(msg)
    sigs = [have[k].sign_message(raw) if k in have else Signature.default() for k in _signers(msg)]
    unknown = set(have) - set(_signers(msg))
    if unknown:
        raise ValueError(f"not a signer of this message: {', '.join(map(str, unknown))}")
    return VersionedTransaction.populate(msg, sigs)


def add(tx: VersionedTransaction, keypair: Keypair) -> VersionedTransaction:
    """`tx` with `keypair`'s signature put in its place: what a co-signer does on their own machine."""
    keys = _signers(tx.message)
    if keypair.pubkey() not in keys:
        raise ValueError(f"{keypair.pubkey()} is not a signer of this transaction")
    sigs = list(tx.signatures)
    sigs[keys.index(keypair.pubkey())] = keypair.sign_message(_bytes(tx.message))
    return VersionedTransaction.populate(tx.message, sigs)


def missing(tx: VersionedTransaction) -> list[Pubkey]:
    """The required signers whose signature is absent or does not verify."""
    keys = _signers(tx.message)
    return [k for k, ok in zip(keys, tx.verify_with_results()) if not ok]


def encode(tx: VersionedTransaction) -> str:
    return base64.b64encode(bytes(tx)).decode()


def decode(text: str) -> VersionedTransaction:
    return VersionedTransaction.from_bytes(base64.b64decode(text))


def send(ledger, tx: VersionedTransaction, within: float = 60.0) -> str:
    """Hand a fully signed durable-nonce transaction to the cluster and wait for the ledger's commitment. Refused,
    before anything is sent, when a signature is missing or the transaction does not advance a nonce first."""
    from .. import chain
    if missing(tx):
        raise ValueError("still unsigned by " + ", ".join(map(str, missing(tx))))
    if not tx.uses_durable_nonce():
        raise ValueError("this transaction does not advance a nonce first: it would expire with its blockhash")
    sig = ledger._submit(tx)
    chain.wait(ledger.url, sig, within, ledger.commitment)
    return sig


def still_good(ledger, tx: VersionedTransaction) -> bool:
    """Whether the nonce the transaction names still holds the value it signed over (else it can never land)."""
    msg = tx.message
    ix = msg.instructions[0]
    nonce = msg.account_keys[ix.accounts[0]]
    got = read(ledger.account(nonce))
    return got is not None and got.value == msg.recent_blockhash


def _load(path: str) -> Keypair:
    from .. import chain
    return chain.wallet(path)


def main(argv: list[str] | None = None) -> int:
    """create PAYER_KEY NONCE_KEY [AUTHORITY]  | show NONCE  | cosign TX_FILE KEY | send TX_FILE"""
    import sys

    from .. import chain
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in ("create", "show", "cosign", "send"):
        print("usage: python -m knos.platform.nonce create PAYER_KEY NONCE_KEY [AUTHORITY] | show NONCE | cosign TX_FILE KEY | send TX_FILE",
              file=sys.stderr)
        return 2
    ledger = chain.ledger()
    if args[0] == "create":
        payer, nonce = _load(args[1]), _load(args[2])
        authority = Pubkey.from_string(args[3]) if len(args) > 3 else payer.pubkey()
        sig = ledger.send(create_ixs(payer.pubkey(), nonce.pubkey(), authority, ledger.rent(NONCE_SIZE)), payer, [nonce])
        print(json.dumps({"nonce": str(nonce.pubkey()), "authority": str(authority), "signature": sig}))
    elif args[0] == "show":
        got = read(ledger.account(Pubkey.from_string(args[1])))
        print(json.dumps(None if got is None else {"authority": str(got.authority), "value": str(got.value)}))
    elif args[0] == "cosign":
        with open(args[1], encoding="utf-8") as f:
            tx = add(decode(f.read().strip()), _load(args[2]))
        with open(args[1], "w", encoding="utf-8") as f:
            f.write(encode(tx))
        print(json.dumps({"missing": [str(k) for k in missing(tx)]}))
    else:
        with open(args[1], encoding="utf-8") as f:
            print(json.dumps({"signature": send(ledger, decode(f.read().strip()))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
