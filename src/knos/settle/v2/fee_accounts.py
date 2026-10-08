"""`knos relay fee-accounts --k N`: the K fee accounts of a mint, so payments of different orders write different ones.

knos_pay takes ANY token account of the order's mint that FEE_OWNER owns as the fee account of PayOrder, SettleOrder
and Release (`is_owned(fee_tok, token, mint, FEE_OWNER)`, order_pay.rs and order_terms.rs; Pay and Settle of a job
ask the same, pay.rs). Nothing in the program names the associated account. So spreading the fee's writes needs no
program change: account 0 stays FEE_OWNER's associated token account, and accounts 1..K-1 are plain token accounts
at `Pubkey.create_with_seed(base, pay.fee_seed(mint, i), TOKEN)`, initialised with FEE_OWNER as their owner. Making one
needs the base's signature and rent (2,039,280 lamports for 165 bytes), never FEE_OWNER's; only FEE_OWNER can move
or close what is in them.

With no --execute this prints the plan and sends nothing: the addresses, which exist (with --check), the rent, and
the two settings every relay then needs (KNOS_FEE_SHARDS, KNOS_FEE_BASE). --execute makes the missing ones, the
base paying, and is what the release run does.

THE SWEEP. The fees then sit in K accounts. They are FEE_OWNER's wherever they sit: counting revenue reads all K
(`pay.fee_accounts`); moving them into the associated account is one TransferChecked per account, signed by
FEE_OWNER (the Squads vault), proposed through the vault like any other movement of its money. Nothing here can
sign it, and nothing needs it to happen for a payment to work.
"""
from __future__ import annotations

import argparse
import json
import sys

from solders.keypair import Keypair
from solders.pubkey import Pubkey

from . import pay

RENT_165 = 2_039_280        # (165 + 128) bytes x 3,480 lamports a byte-year x 2 years: rent exemption of a token account


def plan(k: int, base: Pubkey, mints: list[Pubkey], exists=None) -> dict:
    """What `fee-accounts` would make. `exists(address) -> bool | None`: a read of the chain (None: not asked)."""
    rows = []
    for mint in mints:
        for i, address in enumerate(pay.fee_accounts(mint, pay.TOKEN, k, base)):
            there = exists(address) if exists else None
            rows.append({"mint": str(mint), "i": i, "address": str(address), "seed": None if i == 0 else pay.fee_seed(mint, i),
                         "kind": "associated (made by the relay the first time it is needed)" if i == 0 else "seeded",
                         "exists": there, "make": i > 0 and there is not True})
    make = sum(1 for r in rows if r["make"])
    return {"k": k, "base": str(base), "fee_owner": str(pay.FEE_OWNER), "accounts": rows, "to_make": make, "rent_lamports": make * RENT_165,
            "settings": {"KNOS_FEE_SHARDS": str(k), "KNOS_FEE_BASE": str(base)},
            "sweep": "fees stay FEE_OWNER's in every account; moving them to the associated one is a TransferChecked per account "
                     "that FEE_OWNER (the Squads vault) signs. Nothing here signs it."}


def make_ixs(payer: Pubkey, base: Pubkey, rows: list[dict], lamports: int = RENT_165) -> list[list]:
    """One transaction per account still to make: CreateAccountWithSeed, then InitializeAccount3 (owner FEE_OWNER)."""
    return [pay.create_fee_account_ixs(payer, base, Pubkey.from_string(r["mint"]), r["i"], lamports) for r in rows if r["make"]]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="knos relay fee-accounts", description="Plan, and with --execute make, K fee accounts of FEE_OWNER per mint.")
    ap.add_argument("--k", type=int, required=True, help=f"fee accounts per mint, 1..{pay.MAX_FEE_SHARDS} (account 0 is the associated one)")
    ap.add_argument("--base", default="", help="the base address the seeded accounts derive from (default: the relay key, KNOS_RELAY_KEY)")
    ap.add_argument("--mint", action="append", default=[], help="an SPL Token mint (repeat; default: Circle's devnet USDC and the faucet's test USDC)")
    ap.add_argument("--check", action="store_true", help="read the chain: which accounts exist already")
    ap.add_argument("--execute", action="store_true", help="make the missing accounts; the relay key is the base and pays the rent")
    a = ap.parse_args(argv)
    if not 1 <= a.k <= pay.MAX_FEE_SHARDS:
        ap.error(f"--k is 1..{pay.MAX_FEE_SHARDS}")
    payer: Keypair | None = None
    if a.execute or not a.base:
        from ... import chain
        payer = chain.key()
    base = payer.pubkey() if payer is not None else Pubkey.from_string(a.base)
    if a.execute and a.base and Pubkey.from_string(a.base) != base:
        ap.error("--execute signs with the relay key as the base: leave --base out, or set KNOS_RELAY_KEY to the base's key")
    mints = [Pubkey.from_string(m) for m in a.mint] or [pay.USDC_DEVNET, pay.faucet_mint()]
    ledger = None
    if a.check or a.execute:
        from ... import chain
        ledger = chain.ledger()
    got = plan(a.k, base, mints, (lambda addr: ledger.account(addr) is not None) if ledger is not None else None)
    if a.execute and payer is not None and ledger is not None:
        got["sent"] = [ledger.send(ixs, payer) for ixs in make_ixs(payer.pubkey(), base, got["accounts"])]
    print(json.dumps(got, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
