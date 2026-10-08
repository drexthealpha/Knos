#!/usr/bin/env python3
"""The network loop, counted: does a new participant make Knos more useful to the ones already there?

    buyer adopts -> suppliers integrate -> a supplier reuses the integration with another buyer -> the acceptance
    format spreads -> the record improves decisions -> more buyers adopt

Each link has one counter here, and docs/MARKET.md, section 7, prints them. Three are read from the same job records
scripts/outsiders.py counts (its rules decide who is outside: `funder_of`, `payees_of`); the others are read from this
repository: the report files of reproductions/, and the counts a person keeps by hand in docs/facts.json.

    suppliers_two_buyers      outside payees paid by jobs of two or more different outside funders
    buyers_through_supplier   outside funders whose first paid job paid a supplier that a different outside funder
                              had already paid: the buyer arrived where a supplier already was
    repeat_buyers             outside funders with paid jobs in two or more different months
    receipt_implementations   software that is not Knos's and reads or writes the receipt format (by hand, with a link)
    decisions_from_record     buyers who say they chose or dropped a supplier on its record (by hand)
    reproductions_signed      report files in reproductions/ from a run in someone else's repository

A funder is unrelated to another when they are different accounts or wallets and neither is Knos's: nothing here can
see common ownership, so two accounts of one company would count as two. A larger log of events is not a network
effect, and none of these counts events.

    python scripts/network_loop.py            prints the six, as JSON, from an empty job list: the chain is not read here
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFINITIONS = {
    "suppliers_two_buyers": "outside payees paid by jobs of two or more different outside funders",
    "buyers_through_supplier": "outside funders whose first paid job paid a supplier a different outside funder had already paid",
    "repeat_buyers": "outside funders with paid jobs in two or more different months",
    "receipt_implementations": "software that is not Knos's and reads or writes the receipt format",
    "decisions_from_record": "buyers who say they chose or dropped a supplier on its record",
    "reproductions_signed": "report files in reproductions/ from a run in someone else's repository",
}
BY_HAND = ("receipt_implementations", "decisions_from_record")


def loop(jobs: list[dict], own: frozenset = frozenset(), own_wallets: frozenset = frozenset(), own_repos: frozenset = frozenset(),
         own_balances: frozenset = frozenset(), measured: bool = True) -> dict:
    """The three links a job record can show. `jobs` as scripts/outsiders.py reads them; `paid_at` (seconds) orders them
    and names the month. `measured` False: nothing was read, and the zeros are not a count."""
    import outsiders as rules

    paid = []
    for j in jobs:
        f = rules.funder_of(j, own, own_wallets, own_repos, own_balances)
        who = rules.payees_of(j, own, own_wallets)
        if f and f[1] == "outside" and who:
            paid.append((int(j.get("paid_at") or 0), f[0], who))
    paid.sort(key=lambda row: (row[0], row[1]))
    buyers_of: dict[str, set[str]] = {}
    months: dict[str, set[int]] = {}
    seen: set[str] = set()
    through: set[str] = set()
    for at, funder, who in paid:
        if funder not in seen and any(buyers_of.get(p, set()) - {funder} for p in who):
            through.add(funder)
        seen.add(funder)
        months.setdefault(funder, set()).add(at // (30 * 86_400) if at else -1)
        for p in who:
            buyers_of.setdefault(p, set()).add(funder)
    return {"measured": bool(measured), "suppliers_two_buyers": sum(1 for b in buyers_of.values() if len(b) >= 2),
            "buyers_through_supplier": len(through), "repeat_buyers": sum(1 for m in months.values() if len(m - {-1}) >= 2)}


def from_repository(root: Path = ROOT) -> dict:
    """The links no chain shows: counted from files of this repository. A key docs/facts.json does not hold is 0."""
    facts = root / "docs" / "facts.json"
    by_hand = json.loads(facts.read_text(encoding="utf-8")).get("by_hand", {}) if facts.is_file() else {}
    folder = root / "reproductions"
    out = {name: int(by_hand.get(name, 0)) for name in BY_HAND}
    out["reproductions_signed"] = len(list(folder.glob("*.json"))) if folder.is_dir() else 0
    return out


def rows(jobs: list[dict] | None = None, root: Path = ROOT, **who: frozenset) -> dict:
    """All six, with what each means and whether the chain was read."""
    return {**loop(jobs or [], measured=jobs is not None, **who), **from_repository(root), "definitions": DEFINITIONS}


if __name__ == "__main__":
    print(json.dumps(rows(), indent=2))
