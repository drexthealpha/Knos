"""The upgrade multisig's time lock, made longer than an order's notice: the plan, never the vote.

    python scripts/timelock_plan.py [--rpc URL | --state FILE] [--seconds N] [--creator ADDRESS] [--payer ADDRESS] [--json]

Why. An upgrade of a Knos program can execute once the upgrade multisig's time lock has run from the vote that
approves it (172,800 s, 48 hours, today). A funder who does not accept the upgrade cancels an open order, and the
program then holds it for the seller's notice (`knos.settle.v2.pay.NOTICE`, 7 days) and, for an order funded with the
presentation grace, `GRACE` (2 hours) more before `RefundOrder` takes it back. 48 hours are shorter than that. A time
lock of at least NOTICE + GRACE + 2 seconds lets every open order be cancelled and refunded before any upgrade that is
approved after the change can execute (`knos exit --before-upgrade` holds each exit to it). PLANNED is 8 days: about 22
hours above the minimum are for sending the Cancel, which for a Balance's order is a `/knos cancel` comment and a
workflow run. It does not cover an order held for a payee (180 days) or a holdback in its warranty (up to 90 days).

What it prints. The Squads v4 configuration transaction that sets the time lock (`config_transaction_create` with one
action, `SetTimeLock { new_time_lock: u32 }`, variant 3 of `ConfigAction`), its accounts and its bytes, and the three
steps that follow: a proposal for it, the members' approvals up to the threshold, and `config_transaction_execute`,
which itself waits out the PRESENT time lock from the approval. Facts from the Squads v4 source
(github.com/Squads-Protocol/v4, programs/squads_multisig_program/src): `time_lock` is "How many seconds must pass
between transaction voting settlement and execution" (state/multisig.rs); `MAX_TIME_LOCK` is 3 * 30 days and
`config_transaction_create` refuses more; executing `SetTimeLock` calls `invalidate_prior_transactions`, so every
proposal made before it becomes stale: one not yet approved can no longer be approved (proposal_vote.rs), a stale
configuration transaction can never execute (config_transaction_execute.rs), and an approved vault transaction can
still execute, once the NEW time lock has run from its approval (vault_transaction_execute.rs compares with
`multisig.time_lock` at execution).

What it refuses. While any proposal of the multisig is a draft, active, or approved and not executed (upgrades
proposed by a release first run their course: the change would make them stale, or hold them longer than their
announced time); a multisig with a config authority (a configuration transaction is for a multisig without one); a
time lock below the minimum or above Squads' maximum. When the time lock on chain is already at least the planned
one it says so and prints nothing to send.

It signs and sends nothing: `node scripts/governance.mjs` sends what the members approve. Reads the cluster with
`--rpc`; `--state FILE` reads {"now": unix seconds, "accounts": {address: {"owner": ..., "data": hex}}} instead
(the tests' fixtures). Exit 0 with a plan or when the time lock is already in force, 1 when it refuses, 2 on an
unreadable cluster or file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from solders.pubkey import Pubkey  # noqa: E402

from knos import mainnet_check as mc  # noqa: E402
from knos.settle.v2 import pay  # noqa: E402

KIND = "knos.timelock-plan/1"
MINIMUM = pay.NOTICE + pay.GRACE + 2          # knos.exit: a refund at notice + grace + 1 is out before approval + lock
PLANNED = mc.PLANNED_TIME_LOCK                 # 8 days: what knos status and governance.mjs show --check accept once it executed
MAX_TIME_LOCK = 3 * 30 * 24 * 60 * 60         # Squads v4 state/multisig.rs
SET_TIME_LOCK = 3                             # ConfigAction::SetTimeLock, the fourth variant
SYSTEM = "11111111111111111111111111111111"
CREATE = hashlib.sha256(b"global:config_transaction_create").digest()[:8]     # Anchor's instruction discriminator

Account = Callable[[str], "tuple | None"]


class Refused(Exception):
    """What stops the plan, in words."""


def span(seconds: int) -> str:
    d, rest = divmod(seconds, 86_400)
    return f"{d} days {rest // 3600} h" if rest % 3600 == 0 else f"{d} days {rest // 3600} h {rest % 3600 // 60} min"


def create_data(seconds: int, memo: str | None = None) -> bytes:
    """`config_transaction_create(ConfigTransactionCreateArgs { actions: vec![SetTimeLock { new_time_lock }], memo })`
    in borsh: the discriminator, a Vec of one action (u32 count, u8 variant, u32 seconds), an Option<String>."""
    out = CREATE + (1).to_bytes(4, "little") + bytes([SET_TIME_LOCK]) + seconds.to_bytes(4, "little")
    if memo is None:
        return out + b"\x00"
    raw = memo.encode("utf-8")
    return out + b"\x01" + len(raw).to_bytes(4, "little") + raw


def plan(account: Account, ids: dict, now: int, seconds: int = PLANNED, creator: str = "", payer: str = "") -> dict:
    """The plan as data (KIND). Raises Refused with the reasons when it must not be sent."""
    if not MINIMUM <= seconds <= MAX_TIME_LOCK:
        raise Refused(f"a time lock of {seconds} s is outside {MINIMUM} s (7 days of notice, 2 hours of grace, 2 s) to {MAX_TIME_LOCK} s (the Squads maximum).")
    address, squads = ids["upgrade_multisig"], ids["squads_program"]
    ms, said = mc.multisig_at(account, address, squads)
    if ms is None:
        raise Refused(f"the upgrade multisig cannot be read: {said}.")
    base = {"kind": KIND, "multisig": address, "squads": squads, "now": now, "time_lock_now": ms.time_lock, "time_lock_planned": seconds,
            "minimum": MINIMUM, "threshold": ms.threshold, "members": [str(m) for m in ms.members]}
    if ms.time_lock >= seconds:
        return {**base, "state": "in force", "steps": [],
                "words": [f"The time lock on chain is {span(ms.time_lock)} ({ms.time_lock} s): at least the planned {span(seconds)}. Nothing to send."]}
    if ms.config_authority is not None:
        raise Refused(f"the multisig has a config authority ({ms.config_authority}): it changes the time lock itself; a configuration transaction is for a multisig without one.")
    pending = mc.pending_proposals(account, address, ms, squads)
    if pending:
        raise Refused("proposals are still open: " + "; ".join(
            f"proposal {p.index} ({p.kind}{' of ' + str(p.program) if p.program else ''}, {p.status.lower()}"
            + (f", executable from {mc._at(p.executes_at)}" if p.executes_at else "") + ")" for p in pending)
            + ". Execute or cancel them first: a time lock change makes every earlier proposal stale.")
    index = ms.transaction_index + 1
    ms_key, sq = Pubkey.from_string(address), Pubkey.from_string(squads)
    who = creator or str(ms.members[0])
    pays = payer or who
    data = create_data(seconds)
    instruction = {"program": squads, "name": "config_transaction_create", "data": data.hex(), "accounts": [
        {"name": "multisig", "address": address, "signer": False, "writable": True},
        {"name": "transaction", "address": str(mc.transaction_address(ms_key, index, sq)), "signer": False, "writable": True},
        {"name": "creator", "address": who, "signer": True, "writable": False},
        {"name": "rent_payer", "address": pays, "signer": True, "writable": True},
        {"name": "system_program", "address": SYSTEM, "signer": False, "writable": False}]}
    steps = [f"1. config_transaction_create: transaction {index} of {address}, one action SetTimeLock {{ new_time_lock: {seconds} }} ({span(seconds)}); signed by member {who}",
             f"2. proposal_create for transaction {index} ({mc.proposal_address(ms_key, index, sq)})",
             f"3. proposal_approve by {ms.threshold} of the {len(ms.members)} members",
             f"4. config_transaction_execute, from {span(ms.time_lock)} after the last approval (the present time lock), by any member with execute permission",
             f"after 4: every upgrade approved from then on waits {span(seconds)}; an open order cancelled when it is approved is refunded {span(seconds - MINIMUM + 1)} before it can run"]
    return {**base, "state": "plan", "transaction_index": index, "instruction": instruction, "steps": steps,
            "words": [f"The time lock on chain is {span(ms.time_lock)} ({ms.time_lock} s); the plan sets {span(seconds)} ({seconds} s), above the "
                      f"{span(MINIMUM)} an open order needs to leave. No proposal is open. Nothing is sent from here."]}


def _state(file: Path) -> tuple[Account, int]:
    raw = json.loads(file.read_text(encoding="utf-8"))
    accounts = {a: (v["owner"], bytes.fromhex(v["data"])) for a, v in raw["accounts"].items()}
    return (lambda a: accounts.get(a)), int(raw["now"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Plan the Squads configuration transaction that sets the upgrade multisig's time lock above an order's notice.")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--rpc", default="", help="the cluster's JSON-RPC URL (default: devnet)")
    src.add_argument("--state", type=Path, help="read the accounts from this file instead of a cluster")
    ap.add_argument("--seconds", type=int, default=PLANNED, help=f"the time lock to set (default {PLANNED}, 8 days)")
    ap.add_argument("--creator", default="", help="the member who creates the transaction (default: the first member)")
    ap.add_argument("--payer", default="", help="who pays the transaction account's rent (default: the creator)")
    ap.add_argument("--json", action="store_true", help=f"print the plan as data ({KIND})")
    a = ap.parse_args(argv)
    try:
        if a.state:
            account, now = _state(a.state)
        else:
            from knos import chain
            url = a.rpc or chain.CLUSTERS["devnet"]
            account, now = mc._rpc(url), chain.Ledger(url).now()
    except Exception as why:  # noqa: BLE001 - nothing was read, nothing is planned
        print(f"cannot read the accounts ({type(why).__name__}: {why}). Nothing was planned.", file=sys.stderr)
        return 2
    try:
        got = plan(account, pay.IDS, now, a.seconds, a.creator, a.payer)
    except Refused as why:
        print(f"Refused: {why}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(got, indent=1))
    else:
        for line in [*got["words"], *got["steps"]]:
            print(line)
        if got.get("instruction"):
            ix = got["instruction"]
            print(f"instruction {ix['name']} to {ix['program']}, data {ix['data']}")
            for acc in ix["accounts"]:
                print(f"  {acc['name']:<15} {acc['address']}{'  signer' if acc['signer'] else ''}{'  writable' if acc['writable'] else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
