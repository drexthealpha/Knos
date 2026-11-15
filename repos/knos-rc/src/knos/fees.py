"""The fee knos_pay charges, in one place, and which of its two rules the cluster's program applies now.

    0.3.18 (knos_pay 2.2)   jobs and orders alike: 0.30% of the amount, at least 0.05 of a whole unit; one rate, no
                            tiers; a Plan lowers the rate to no less than 0.10%. The numbers are knos.settle.v2.pay's
                            (FEE_BPS, FEE_MIN, fee_of): nothing here types them again.
    0.3.14 (knos_pay 2.1)   an order: 2.5% of the first 1,000, 1% from there to 50,000, 0.5% above, at least 0.40; a
                            Plan lowers the first rate to no less than 0.5%. A job: 2.5%, at least 0.05.

knos_pay 2.2 has run at the public program id on devnet since 9 October 2026 (upgrade proposal 8, executed). An order
funded before then keeps the fee fixed at its funding. `version` still asks the program, so a cluster on an older build
gets the right answer. So a fee shown to a person follows the build that is LIVE:

    version(ledger)   asks the program (Version, by simulation: `knos2:version 2` is 2.2), as knos.settle.v2.relay does
    feed_version(f)   the same answer from the upgrade feed (web/upgrades.json) for a page or a command that asks no chain
    rule(v)           NEW from 2 up, OLD below
    words(v)          the fee in one sentence; with v None (nobody was asked) it says the live 2.2 fee and its date

An order's fee is taken when it is funded and held with it, so an order funded before the upgrade keeps the rate fixed
at its funding (KEEPS says so wherever the fee is stated).
"""
from __future__ import annotations

from dataclasses import dataclass

from .settle.v2 import pay

NEW_VERSION = 2                    # what Version logs from knos_pay 2.2 on
OLD_PAY_PROPOSALS = 4              # the upgrade multisig's proposals of knos_pay up to this index carry the 0.3.14 fee
KEEPS = "Orders funded before the upgrade keep the rate fixed at their funding."


@dataclass(frozen=True)
class Rule:
    release: str            # the release whose fee this is
    build: str              # the knos_pay build that charges it
    bps: int                # the standard rate (an order's first tier under 0.3.14)
    floor: int              # the least fee of an order, in millionths of a whole unit
    plan_min: int           # the lowest rate a Plan may set
    job_bps: int
    job_floor: int
    tiers: tuple[tuple[int, int], ...] = ()     # (up to this many millionths, the rate of what lies above the last edge)

    def order(self, amount: int, bps: int | None = None, decimals: int = 6) -> int:
        """What the funder of an order of `amount` pays on top, in the mint's units, at `bps` (the standard rate or a Plan's)."""
        left, at, fee, rate = amount, 0, 0, self.bps if bps is None else bps
        for edge, after in self.tiers:
            part = min(left, pay.units(edge, decimals) - at)
            fee, left, at, rate = fee + part * rate // 10_000, left - part, at + part, after
        return max(fee + left * rate // 10_000, pay.units(self.floor, decimals))

    def job(self, amount: int, decimals: int = 6) -> int:
        """The fee of a job, taken out of its amount."""
        return min(max(amount * self.job_bps // 10_000, pay.units(self.job_floor, decimals)), amount)

    def plan_bps(self, plan, now: int) -> int:
        """The rate of an owner's orders now: its Plan's while it lasts, within what this rule allows."""
        return min(max(plan.fee_bps, self.plan_min), self.bps) if plan is not None and now < plan.expires else self.bps

    def rate(self, bps: int | None = None) -> str:
        """The rule as a rate: "0.3% of the amount, at least 0.05"."""
        first = pct(self.bps if bps is None else bps)
        if not self.tiers:
            return f"{first} of the amount, at least {_money(self.floor)}"
        (e1, r1), (e2, r2) = self.tiers
        return f"{first} of the first {e1 // 1_000_000:,}, {pct(r1)} to {e2 // 1_000_000:,}, {pct(r2)} above, at least {_money(self.floor)}"


def pct(bps: int) -> str:
    """30 -> "0.30%", 50 -> "0.5%", 250 -> "2.5%", 100 -> "1%": under half a percent is written with two decimals."""
    return f"{bps / 100:.2f}%" if bps < 50 else f"{bps / 100:g}%"


def _money(micro: int) -> str:
    whole, frac = divmod(micro, 1_000_000)
    return f"{whole:,}." + str(frac).rjust(6, "0").rstrip("0").ljust(2, "0")


NEW = Rule("0.3.18", "2.2", pay.FEE_BPS, pay.FEE_MIN, 10, pay.FEE_BPS, pay.FEE_MIN)
OLD = Rule("0.3.14", "2.1", 250, 400_000, 50, 250, 50_000, ((1_000_000_000, 100), (50_000_000_000, 50)))


def rule(version: int | None = NEW_VERSION) -> Rule:
    """The rule the program of `version` applies. None (nobody was asked) is the tree's own: NEW."""
    return NEW if version is None or version >= NEW_VERSION else OLD


def version(ledger, payer=None) -> int:
    """Which knos_pay the cluster runs (relay.version): 2 from the build with the 0.3.18 fee, 1 or 0 before."""
    from .settle.v2 import relay
    return relay.version(ledger, payer)


def live(ledger, payer=None) -> Rule:
    """The rule the cluster's program applies now."""
    return rule(version(ledger, payer))


def feed_version(feed: dict | None) -> int | None:
    """The same answer from the upgrade feed (web/upgrades.json): 2 once a proposal of knos_pay newer than the 2.1 one
    has executed, 1 while none has, None when the feed could not be read. The feed is as old as its `generated`."""
    entries = feed.get("entries") if isinstance(feed, dict) else None
    if not isinstance(entries, list):
        return None
    ran = any(isinstance(e, dict) and e.get("program") == "knos_pay" and e.get("status") == "executed"
              and isinstance(e.get("index"), int) and e["index"] > OLD_PAY_PROPOSALS for e in entries)
    return NEW_VERSION if ran else 1


def words(version: int | None = None) -> str:
    """The fee in plain words, true whichever build is live. `version`: what the program or the feed answered; None
    (nobody was asked) says the 2.2 fee, live on devnet since 9 October 2026."""
    if version is None:
        return (f"Fee: {NEW.rate()} test USDC, paid by the funder on top (knos_pay {NEW.build}, live on devnet since 9 October 2026; "
                f"`knos status` says which build runs). {KEEPS}")
    if version >= NEW_VERSION:
        return f"Fee: {NEW.rate()} test USDC, paid by the funder on top (knos_pay {NEW.build} is live). {KEEPS}"
    return (f"Fee today: {OLD.rate()} test USDC, paid by the funder on top (the fee it charges before the upgrade: knos_pay {NEW.build} is not live yet). "
            f"From knos_pay {NEW.build}: {NEW.rate()}. {KEEPS}")


def table(amounts=(5, 20, 1_000, 5_000, 50_000), r: Rule = NEW, bps: int | None = None, decimals: int = 6) -> list[tuple[int, int]]:
    """(amount, fee) in the mint's units for whole amounts, under `r`."""
    unit = 10 ** decimals
    return [(a * unit, r.order(a * unit, bps, decimals)) for a in amounts]
