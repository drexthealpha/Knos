"""The contract floor of a Plan, which the program does not enforce, enforced by the only Knos tool that signs one.

knos_pay lets FEE_OWNER set a Plan (SetPlan, instruction 14) for one repository owner's orders at 10 to 30 basis points
(`PLAN_BPS_MIN` = 10 in programs-v2/knos_pay/src/lib.rs). The price book's floor is 0.20%: the earlier 0.10% tier is
withdrawn. So: the program allows 10 bps; Knos signs no Plan below 20 bps; the check proves which Plans exist.

    build(...)        the SetPlan instruction, refused below FLOOR_BPS: the one Knos builder of SetPlan for a cluster
    plans(call)       every Plan account of knos_pay on a cluster: one getProgramAccounts, filtered by the Plan's length
                      (24 bytes), each checked to be the ["plan", owner id] address it says it is
    below(found, now) the Plans in force below the floor
    `knos fees plans [--check]` prints them; with --check it exits 1 when one in force is below 20 bps.

A Plan account (fund.rs `set_plan`): byte 0 version (1), byte 1 bump, bytes 2..4 the rate (u16), 8..16 the owner id
(u64), 16..24 the expiry (i64, unix seconds); all little-endian. An expired Plan charges the standard rate."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Callable

FLOOR_BPS = 20             # the contract floor (price book 3.1); the program's own floor is PLAN_BPS_MIN = 10
DOC = "the program allows 10 bps; Knos signs no Plan below 20 bps; the check proves which Plans exist."     # pinned to docs/reference/ENFORCEMENT.md (knos.enforce)


class Refused(ValueError):
    pass


@dataclass(frozen=True)
class Found:
    address: str
    owner_id: int
    bps: int
    expires: int
    at_pda: bool            # the account is the ["plan", owner id] address of knos_pay: the program reads no other


def build(fee_owner, payer, owner_id: int, bps: int, expires: int, program=None):
    """The SetPlan instruction for `owner_id` at `bps` until `expires`, refused below the contract floor. Above the
    standard rate the program refuses it anyway; that is said here first."""
    from .settle.v2 import pay
    if isinstance(bps, bool) or not isinstance(bps, int) or bps < FLOOR_BPS:
        raise Refused(f"A plan below 0.20% ({FLOOR_BPS} basis points) is below Knos's minimum rate; {DOC}")
    if bps > pay.FEE_BPS:
        raise Refused(f"a Plan lowers the rate: at most {pay.FEE_BPS} basis points")
    return pay.set_plan_ix(fee_owner, payer, owner_id, bps, expires, program or pay.PAY_ID)


def read(address: str, data: bytes, program=None) -> Found | None:
    """A Plan account's fields, or None when the bytes are not a Plan."""
    from .settle.v2 import pay
    plan = pay.read_plan(data)
    if plan is None:
        return None
    pda = str(pay.plan_pda(plan.owner_id, program or pay.PAY_ID))
    return Found(address, plan.owner_id, plan.fee_bps, plan.expires, pda == address)


def plans(call: Callable[[str, list], Any], program=None) -> list[Found]:
    """Every Plan of knos_pay `program` (the public id by default) through `call(method, params)`, by address."""
    from .settle.v2 import pay
    prog = program or pay.PAY_ID
    got = call("getProgramAccounts", [str(prog), {"encoding": "base64", "commitment": "confirmed",
                                                   "filters": [{"dataSize": pay.PLAN_LEN}]}]) or []
    out = []
    for a in got:
        data = base64.b64decode(a["account"]["data"][0])
        f = read(a["pubkey"], data, prog)
        if f is not None:
            out.append(f)
    return sorted(out, key=lambda f: f.address)


def below(found: list[Found], now: int) -> list[Found]:
    """The Plans that would lower a fee now below the floor: in force, at their own ["plan", owner id] address."""
    return [f for f in found if f.at_pda and now < f.expires and f.bps < FLOOR_BPS]


def lines(found: list[Found], now: int) -> list[str]:
    out = [f"{len(found)} Plan account(s) of knos_pay. {DOC[0].upper()}{DOC[1:]}"]
    for f in found:
        state = "expired" if now >= f.expires else "in force"
        out.append(f"  owner {f.owner_id}: {f.bps} bps, {state} (expires {f.expires}) {f.address}" + ("" if f.at_pda else " (not at its Plan address: never read)"))
    bad = below(found, now)
    out.append(f"BELOW THE FLOOR: {len(bad)} Plan(s) in force under {FLOOR_BPS} bps." if bad else f"No Plan in force is below {FLOOR_BPS} bps.")
    return out


def register(app, help_lines: list | None = None) -> None:
    """`knos fees plans [--check]`, on the main app."""
    import importlib
    typer = importlib.import_module("typer")       # named here and not imported: this module is standard library only at import
    group = typer.Typer(add_completion=False, no_args_is_help=True, help="Fee plans (discounted fee rates for one repository owner), read from the chain.")
    app.add_typer(group, name="fees")
    if help_lines is not None:
        help_lines.append(("fees", "For money", "Every fee plan on the cluster, and whether one in force is below the 0.20% minimum."))

    @group.command("plans")
    def plans_(check: bool = typer.Option(False, "--check", help="exit 1 when a Plan in force is below 20 basis points")) -> None:
        """List every fee plan on the cluster (KNOS_CLUSTER) with its rate and expiry. The program allows rates down to
        0.10% (10 basis points); Knos signs no plan below 0.20%; this command shows which plans exist."""
        from . import chain
        led = chain.ledger()
        found = plans(lambda method, params: chain.call(led.url, method, params, timeout=30))
        now = led.now()                 # the cluster's clock: the one a Plan's expiry is measured by
        typer.echo("\n".join(lines(found, now)))
        if check and below(found, now):
            raise typer.Exit(1)
