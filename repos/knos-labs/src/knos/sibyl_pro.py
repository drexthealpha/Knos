"""Sibyl Pro, bought by Knos: every wallet that pays Knos anything has Sibyl Pro for the 30 days after that payment.

A payment is Knos Pro, a Knos Team seat, or the 5% fee the escrow takes when a buyer's job is accepted. Knos buys Sibyl
Pro from that one payment; there is no second checkout and no threshold. The grant runs 30 days from the payment and a
later payment extends it.

The purchase goes through a checkout:
  SimulatedCheckout   devnet, testnet, localnet: records the grant on this machine and says `simulated: true`.
  MainnetCheckout     built and locked: it refuses until Sibyl Labs confirms resale in writing and the founder
                      unlocks mainnet (KNOS_ALLOW_MAINNET=1 plus a partner endpoint). Nothing is bought blind.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import paths

DAYS = 30
TEST_NETWORKS = {"devnet", "testnet", "localnet", "moderato", "anvil"}


class Locked(Exception):
    """Mainnet purchase refused: built, not switched on."""


@dataclass
class Grant:
    wallet: str
    source: str          # pro-month, pro-year, team-seat or job-fee
    ref: str             # the payment: a transaction signature or a job id; one grant per payment
    paid_at: str
    until: str
    network: str
    seats: int = 1
    simulated: bool = True


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SimulatedCheckout:
    """Moves no money and calls no one: the grant is written to ~/.knos/sibyl-pro.json, labelled simulated."""
    simulated = True

    def __init__(self, path: Path | None = None):
        self.path = path or (paths.home() / "sibyl-pro.json")

    def _book(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def grants(self, wallet: str) -> list[Grant]:
        return [Grant(**g) for g in self._book().get(wallet, [])]

    def buy(self, grant: Grant) -> Grant:
        book = self._book()
        mine = book.setdefault(grant.wallet, [])
        if any(g["ref"] == grant.ref for g in mine):
            return Grant(**next(g for g in mine if g["ref"] == grant.ref))
        mine.append(asdict(grant))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(book, indent=1), encoding="utf-8")
        return grant


class MainnetCheckout(SimulatedCheckout):
    simulated = False

    def buy(self, grant: Grant) -> Grant:
        if os.environ.get("KNOS_ALLOW_MAINNET") != "1" or not os.environ.get("KNOS_SIBYL_PARTNER_URL"):
            raise Locked("Sibyl Pro purchases on mainnet are built and locked until Sibyl Labs confirms resale.")
        raise Locked("The Sibyl partner checkout is not live yet.")


def checkout_for(network: str, path: Path | None = None):
    return SimulatedCheckout(path) if network in TEST_NETWORKS else MainnetCheckout(path)


def grant(wallet: str, source: str, ref: str, network: str, paid_at: datetime | None = None, seats: int = 1,
          checkout=None) -> Grant:
    """Buy Sibyl Pro for `wallet` for the 30 days after this payment (later payments extend it). Idempotent by `ref`."""
    checkout = checkout or checkout_for(network)
    paid = paid_at or _now()
    begins = paid
    for g in checkout.grants(wallet):
        ends = datetime.fromisoformat(g.until)
        if g.ref != ref and ends > begins:
            begins = ends
    until = begins + timedelta(days=DAYS)
    return checkout.buy(Grant(wallet, source, ref, paid.isoformat(), until.isoformat(), network, seats,
                              checkout.simulated))


def active(wallet: str, network: str = "devnet", now: datetime | None = None, checkout=None) -> Grant | None:
    """The grant that covers `now` for this wallet, if any."""
    now = now or _now()
    checkout = checkout or checkout_for(network)
    live = [g for g in checkout.grants(wallet) if datetime.fromisoformat(g.paid_at) <= now
            < datetime.fromisoformat(g.until)]
    return max(live, key=lambda g: g.until) if live else None


def from_licence(body: dict, checkout=None) -> Grant | None:
    """Knos Pro or Team was paid (a licence from a verified payment): Sibyl Pro for the payer, for every seat."""
    if not body.get("payer") or not body.get("via"):
        return None
    paid = datetime.fromisoformat(str(body.get("verified_at") or body.get("issued")))
    return grant(body["payer"], body.get("plan", "pro-month"), body["via"], body.get("network", "mainnet"), paid,
                 int(body.get("seats", 1)), checkout)


def from_job(buyer: str, job_id: str, network: str, paid_at: datetime | None = None, checkout=None) -> Grant:
    """A buyer's job was accepted or released: the escrow took Knos's 5% fee from their price."""
    return grant(buyer, "job-fee", f"job:{job_id}", network, paid_at, 1, checkout)


def from_chain(jobs: list, wallet: str, network: str, now: datetime | None = None, checkout=None) -> list[Grant]:
    """Catch up from the escrow's job accounts: every released job this wallet paid for. The release happened no later
    than the job's review deadline, so that (or now, if earlier) is taken as the payment time."""
    now = now or _now()
    out = []
    for j in jobs:
        if j.state == "released" and str(j.buyer) == wallet:
            paid = min(now, datetime.fromtimestamp(j.deadline, timezone.utc))
            out.append(from_job(wallet, str(j.address), network, paid, checkout))
    return out
