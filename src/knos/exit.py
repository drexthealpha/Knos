"""`knos exit --before-upgrade`: every open order and Balance of one owner, the instruction that gets its money out of
knos_pay, and whether that can happen before a pending upgrade can execute.

    knos exit --before-upgrade --wallet ADDRESS        a wallet's Balances, its own orders and the orders of its Balances
    knos exit --before-upgrade --github-id N           the Balances a GitHub account owns, and their orders
              [--rpc URL] [--json] [--upgrade-at UNIX]

An upgrade of a Knos program can execute 48 hours after the multisig approves it (docs/GOVERNANCE.md). Whoever does
not accept it has those hours to take their money out. Not every holding can be left that fast, and this command
says which, from the program's own rules (programs-v2/knos_pay; the constants in knos.settle.v2.pay):

    Balance                    Withdraw, signed by the Balance's wallet, at once.
    open order, past deadline  RefundOrder, sent by anyone, at once.
    open order                 Cancel gives notice: the deadline becomes at most NOTICE (7 days) away, and RefundOrder
                               follows it. A wallet's order: the funding wallet signs Cancel. A Balance's order: a
                               `/knos cancel` comment, which needs GitHub and the pinned workflow. An order funded with
                               the presentation grace waits GRACE (2 hours) more.
    held order                 the money waits for its payee to bind a wallet; RefundOrder only after HOLD (180 days).
    order in warranty          the holdback goes to the seller (Release) when the warranty ends; the funder recovers
                               it only with a revert token from a judge of the order.

So an open order whose deadline is more than 48 hours away CANNOT be left before an upgrade approved now: the 7 days of
notice that protect the seller are longer than the upgrade's delay. A held order and a holdback in warranty cannot
either. This is the gap the command shows, with the hours that are missing.

The gap closes for open orders when the upgrade multisig's time lock is at least COVERS (NOTICE + GRACE + 2 seconds):
scripts/timelock_plan.py plans that change (docs/GOVERNANCE.md). With --before-upgrade the command reads the time lock
on chain and says which it is: every open order can leave before any upgrade approved from now on, or not.

    holdings(ledger, wallet, github_id)   what the owner holds in knos_pay, read through ledger.program_accounts/infos
    upgrade_deadline(account, ids, now)   the earliest time a pending upgrade of a Knos program can execute
    plan(items, now, upgrade)             one Way per holding: instruction, who sends it, when the money is out, and
                                          whether that is before the upgrade
    time_lock(account, ids)               the upgrade multisig's time lock on chain; lock_words(seconds) says what it covers
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from solders.pubkey import Pubkey

from .settle.v2 import pay

SCHEMA = "knos.exit/1"
PROGRAMS = ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey")
# an order cancelled when an upgrade is approved is refunded at notice + grace + 1; it is out first when the lock is longer
COVERS = pay.NOTICE + pay.GRACE + 2


@dataclass
class Holding:
    kind: str                   # "balance" or "order"
    address: str
    data: bytes                 # the account as the program wrote it
    held: int                   # what its token account holds now, in the mint's smallest units
    warranty_until: int = 0     # an order in warranty: the end of the warranty, from its holdback record


@dataclass
class Upgrade:
    index: int                  # the proposal
    program: str                # its name: knos_pay, ...
    executes_at: int            # the earliest time it can execute (unix seconds)
    approved: bool              # False: not approved yet; executes_at is then the earliest if it were approved now


@dataclass
class Way:
    kind: str                   # balance, order
    address: str
    state: str                  # balance, open, held, warranty
    held: int
    mint: str
    instruction: str            # what moves the money out
    who: str                    # who sends or signs it
    out_at: int                 # the first time the money can be out of the program (unix seconds)
    before: bool | None         # out before the upgrade can execute; None when no upgrade is pending
    short_s: int                # seconds the exit misses the upgrade by (0 when it does not)
    why: str                    # in plain words


def utc(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _amount(data: bytes | None) -> int:
    """The amount of an SPL token account (Token and Token-2022 alike: bytes 64..72)."""
    return int.from_bytes(data[64:72], "little") if data and len(data) >= 72 else 0


def holdings(ledger: Any, wallet: Pubkey | None = None, github_id: int | None = None, program: Pubkey = pay.PAY_ID) -> list[Holding]:
    """Every Balance and order of the owner. A wallet: the Balances it opened and the orders it funded; a GitHub id: the
    Balances that account owns. Both: the orders funded from those Balances."""
    balances: dict[str, bytes] = {}
    if wallet is not None:
        balances.update((str(a), d) for a, d in ledger.program_accounts(program, pay.BALANCE_LEN, {0: b"\x01", 16: bytes(wallet)}))
    if github_id is not None:
        balances.update((str(a), d) for a, d in ledger.program_accounts(program, pay.BALANCE_LEN, {0: b"\x01", 8: github_id.to_bytes(8, "little")}))
    sources = ([wallet] if wallet is not None else []) + [Pubkey.from_string(b) for b in sorted(balances)]
    orders: dict[str, bytes] = {}
    for s in sources:
        orders.update((str(a), d) for a, d in ledger.program_accounts(program, pay.ORDER_LEN, {0: b"\x02", 192: bytes(s)}))
    out: list[Holding] = []
    bal_keys = sorted(balances)
    tokens = ledger.infos([pay.baltok_pda(Pubkey.from_string(b), program) for b in bal_keys]) if bal_keys else []
    for b, tok in zip(bal_keys, tokens):
        out.append(Holding("balance", b, balances[b], _amount(tok[1] if tok else None)))
    ord_keys = sorted(orders)
    if ord_keys:
        vaults = ledger.infos([pay.ov_pda(Pubkey.from_string(o), program) for o in ord_keys])
        hbs = ledger.infos([pay.hb_pda(Pubkey.from_string(o), program) for o in ord_keys])
        for o, v, h in zip(ord_keys, vaults, hbs):
            hb = pay.read_holdback(h[1] if h else None)
            out.append(Holding("order", o, orders[o], _amount(v[1] if v else None), hb.until if hb else 0))
    return out


def upgrade_deadline(account: Callable, ids: dict, now: int) -> Upgrade | None:
    """The pending upgrade of a Knos program that can execute first. `account(address) -> (owner, data) | None`, as
    knos.mainnet_check reads the cluster. A proposal not yet approved counts as if it were approved now: that is the
    earliest it could run."""
    from . import mainnet_check as mc
    ms, _why = mc.multisig_at(account, ids["upgrade_multisig"], ids["squads_program"])
    if ms is None:
        return None
    names = {ids[n]: n for n in PROGRAMS if n in ids}
    best: Upgrade | None = None
    for p in mc.pending_proposals(account, ids["upgrade_multisig"], ms, ids["squads_program"]):
        if p.kind != "upgrade" or p.program not in names:
            continue
        at = p.executes_at if p.executes_at is not None else now + ms.time_lock
        if best is None or at < best.executes_at:
            best = Upgrade(p.index, names[p.program], at, p.executes_at is not None)
    return best


def time_lock(account: Callable, ids: dict) -> int | None:
    """The upgrade multisig's time lock in seconds, read from chain; None when the multisig cannot be read."""
    from . import mainnet_check as mc
    ms, _why = mc.multisig_at(account, ids["upgrade_multisig"], ids["squads_program"])
    return None if ms is None else ms.time_lock


def lock_words(seconds: int | None) -> str:
    """What the upgrade multisig's time lock means for leaving, in one sentence."""
    if seconds is None:
        return "The upgrade multisig's time lock could not be read."
    if seconds >= COVERS:
        return (f"The upgrade multisig's time lock is {hours(seconds)}: longer than 7 days of notice and 2 hours of grace, so every open order "
                "can be cancelled and refunded before any upgrade approved from now on can execute. Held orders and holdbacks in warranty still cannot.")
    return (f"The upgrade multisig's time lock is {hours(seconds)}: shorter than 7 days of notice and 2 hours of grace, so an open order whose "
            f"deadline is later than that cannot be left before an upgrade approved now ({hours(COVERS - seconds)} short).")


def _way(h: Holding, now: int) -> tuple[str, str, str, int, str, str]:
    """(state, mint, instruction, out_at, who, why) for one holding."""
    if h.kind == "balance":
        b = pay.read_balance(h.data)
        if b is None:
            return "unknown", "", "none", 0, "", "not a Balance this version reads"
        return ("balance", str(b.mint), "Withdraw", now, f"the Balance's wallet {b.authority}",
                "a Balance is withdrawn at once, for everything not in an order")
    o = pay.read_order(h.data)
    if o is None:
        return "unknown", "", "none", 0, "", "not an order this version reads"
    return order_way(o, h.warranty_until, now)


def order_way(o: pay.Order, warranty_until: int, now: int) -> tuple[str, str, str, int, str, str]:
    """(state, mint, instruction, out_at, who, why) for one order, from the program's rules."""
    mint = str(o.mint)
    if o.state == "open":
        refund_at = o.pay_until + 1                       # a refund is refused up to pay_until, taken after it
        if refund_at <= now:
            return "open", mint, "RefundOrder", now, "anyone (knos relay sends it)", "its deadline has passed: the refund can be sent now"
        canceller = ("the funding wallet signs Cancel (no token)" if not o.from_balance else
                     "a `/knos cancel` comment in the order's repository: the pinned workflow signs the cancel token, so it needs GitHub")
        if o.cancel_at:
            return ("open", mint, "RefundOrder", refund_at, "anyone, after the deadline the notice set",
                    f"notice was already given; the refund can be sent from {utc(refund_at)}")
        notice = min(o.deadline, now + pay.NOTICE)
        cancelled = (notice + pay.GRACE if o.grace else notice) + 1
        if cancelled < refund_at:
            return ("open", mint, "Cancel, then RefundOrder", cancelled, canceller,
                    f"Cancel moves the deadline to at most 7 days away; the refund follows from {utc(cancelled)}")
        return ("open", mint, "RefundOrder", refund_at, "anyone, after the deadline",
                f"its deadline is nearer than any notice; the refund can be sent from {utc(refund_at)}")
    if o.state == "held":
        return ("held", mint, "RefundOrder", o.hold_until + 1, "anyone, after the hold",
                "the money waits for its payee to bind a wallet (SettleOrder pays the payee); it returns to the funder only after the 180-day hold")
    if o.state == "warranty":
        until = warranty_until or o.hold_until
        return ("warranty", mint, "Release", until + 1, "anyone, after the warranty: the holdback goes to the seller",
                "the holdback is the seller's once the warranty ends; the funder gets it back only with a revert token from a judge of the order")
    return o.state, mint, "none", 0, "", "a state this version does not know"


def plan(items: list[Holding], now: int, upgrade: Upgrade | None) -> list[Way]:
    out = []
    for h in items:
        state, mint, ix, at, who, why = _way(h, now)
        before = None if upgrade is None else at < upgrade.executes_at
        short = 0 if upgrade is None or before else at - upgrade.executes_at + 1
        out.append(Way(h.kind, h.address, state, h.held, mint, ix, who, at, before, short, why))
    return out


def hours(seconds: int) -> str:
    return f"{seconds // 3600} h {seconds % 3600 // 60} min"


def words(ways: list[Way], now: int, upgrade: Upgrade | None, lock: int | None = None, read_lock: bool = False) -> list[str]:
    """The answer in lines. With `read_lock`, a last line says what the time lock `lock` covers."""
    lines = []
    if upgrade is None:
        lines.append("No upgrade of a Knos program is pending. Every holding below can be left on its own schedule.")
    else:
        left = max(0, upgrade.executes_at - now)
        lines.append(f"Proposal {upgrade.index} ({upgrade.program}) can execute from {utc(upgrade.executes_at)}"
                     + ("" if upgrade.approved else " if it were approved now") + f": {hours(left)} to leave.")
    if not ways:
        lines.append("This owner holds nothing in knos_pay.")
    for w in ways:
        when = "now" if w.out_at <= now else f"from {utc(w.out_at)}"
        verdict = ("" if w.before is None else " Out before the upgrade." if w.before else
                   f" CANNOT be out before the upgrade: {hours(w.short_s)} too late.")
        lines.append(f"{w.kind} {w.address} ({w.state}, {w.held / 1_000_000:,.2f} held): {w.instruction} {when}; {w.who}. {w.why}.{verdict}")
    if upgrade is not None:
        stuck = [w for w in ways if w.before is False]
        lines.append(f"{len(ways) - len(stuck)} of {len(ways)} holdings can be out before the upgrade; {len(stuck)} cannot.")
    if read_lock:
        lines.append(lock_words(lock))
    return lines


def as_json(ways: list[Way], now: int, upgrade: Upgrade | None, lock: int | None = None) -> dict:
    return {"kind": SCHEMA, "now": now, "upgrade": asdict(upgrade) if upgrade else None, "time_lock": lock,
            "open_orders_covered": None if lock is None else lock >= COVERS,
            "hours_to_leave": None if upgrade is None else max(0, upgrade.executes_at - now) // 3600,
            "ways": [asdict(w) for w in ways], "cannot_leave": sum(w.before is False for w in ways)}


def register(app: Any, help_lines: list | None = None) -> None:
    """`knos exit`. `help_lines`: cli._HELP, which gets the command's line."""
    import importlib
    typer = importlib.import_module("typer")
    if help_lines is not None:
        help_lines.append(("exit", "For money", "Every order and Balance you hold, and how to take the money out before an upgrade."))

    @app.command("exit", rich_help_panel="For money")
    def exit_(before_upgrade: bool = typer.Option(False, "--before-upgrade", help="hold each exit to the earliest pending upgrade of a Knos program"),
              wallet: str = typer.Option("", "--wallet", metavar="ADDRESS", help="a wallet: its Balances, its orders, and the orders of its Balances"),
              github_id: int = typer.Option(0, "--github-id", metavar="N", help="a GitHub account id: the Balances it owns, and their orders"),
              rpc: str = typer.Option("", "--rpc", help="the cluster's JSON-RPC URL (default: KNOS_RPC, then devnet)"),
              upgrade_at: int = typer.Option(0, "--upgrade-at", metavar="UNIX", help="hold the exits to this time instead of the chain's pending upgrade"),
              as_json_: bool = typer.Option(False, "--json", help=f"print the answer as data ({SCHEMA})")) -> None:
        """Every order and Balance of one owner and the instruction that gets its money out, with when. With --before-upgrade:
        whether that is before a pending upgrade can execute, and by how many hours it misses. Exit 1 when one cannot. Reads only."""
        from . import chain, cli, mainnet_check as mc
        if not wallet and not github_id:
            raise cli.Stop("Name whose holdings to read.", "knos exit --before-upgrade --wallet <address>   (or --github-id <n>)")
        url = rpc or os.environ.get("KNOS_RPC") or chain.CLUSTERS["devnet"]
        try:
            ledger = chain.Ledger(url)
            now = ledger.now()
            items = holdings(ledger, Pubkey.from_string(wallet) if wallet else None, github_id or None)
            upgrade, lock = None, None
            if before_upgrade:
                lock = time_lock(mc._rpc(url), pay.IDS)
            if upgrade_at:
                upgrade = Upgrade(0, "a given time", upgrade_at, True)
            elif before_upgrade:
                upgrade = upgrade_deadline(mc._rpc(url), pay.IDS, now)
        except Exception as why:  # noqa: BLE001 - no network is not "nothing held"
            raise cli.Stop(f"{url} could not be read ({type(why).__name__}: {why}). Nothing was decided.", "run it again when the cluster answers") from None
        ways = plan(items, now, upgrade)
        if as_json_:
            print(json.dumps(as_json(ways, now, upgrade, lock), indent=1))
        else:
            for line in words(ways, now, upgrade, lock, before_upgrade):
                print(line)
        if any(w.before is False for w in ways):
            raise typer.Exit(1)
