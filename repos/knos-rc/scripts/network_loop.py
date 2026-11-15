#!/usr/bin/env python3
"""The network loop, counted: does a new participant make Knos more useful to the ones already there?

    buyer adopts -> suppliers integrate -> a supplier reuses the integration with another buyer -> the acceptance
    format spreads -> the record improves decisions -> more buyers adopt

Each link has one counter here, and docs/reference/MARKET.md, section 7, prints them. Three are read from the same job records
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

Supplier reuse, the link a network effect needs (a supplier's second buyer costs less than its first), is counted
apart, under "reuse" (`reuse` below):

    suppliers_reused       outside suppliers whose record a second unrelated buyer read (a paid lookup, knos.record_api)
                           or whose work a second unrelated buyer paid
    onboarding_pairs       suppliers paid by two or more unrelated buyers whose first orders both say when they were
                           funded: the sample of the three times below
    onboarding_first_s     the median, over those suppliers, of the seconds from the first buyer's first funded order
                           to its first payment
    onboarding_second_s    the same for the second buyer
    onboarding_saved_s     the median of first minus second: what the second buyer saved. null with no pair

    python scripts/network_loop.py            prints the six and the reuse counts, as JSON, from an empty job list:
                                              the chain is not read here, and every count is 0 (times null)
    python scripts/network_loop.py --jobs jobs.json [--lookups lookups.json] [--own own.json]
                                              the same from job records (as scripts/outsiders.py reads them, with
                                              `funded_at` and `paid_at` in seconds) and from the record server's
                                              paid lookups ([{"reader": "wallet:<address>" | "gh:<id>",
                                              "supplier": "gh:<id>" | "wallet:<address>"}]): the script that moves them
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
REUSE = {
    "suppliers_reused": "outside suppliers whose record a second unrelated buyer read or whose work a second unrelated buyer paid",
    "onboarding_pairs": "suppliers paid by two unrelated buyers whose first orders both say when they were funded",
    "onboarding_first_s": "median seconds from the first buyer's first funded order to its first payment",
    "onboarding_second_s": "median seconds from the second buyer's first funded order to its first payment",
    "onboarding_saved_s": "median of first minus second, per supplier: what the second buyer saved",
}


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


def _median(xs: list[int]) -> float | None:
    xs = sorted(xs)
    if not xs:
        return None
    mid = len(xs) // 2
    return float(xs[mid]) if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2


def reuse(jobs: list[dict], lookups: list[dict] | None = None, own: frozenset = frozenset(), own_wallets: frozenset = frozenset(),
          own_repos: frozenset = frozenset(), own_balances: frozenset = frozenset()) -> dict:
    """Supplier reuse: does a supplier's second unrelated buyer cost less than its first? `jobs` as scripts/outsiders.py
    reads them, with `funded_at` and `paid_at` (seconds); `lookups` the record server's paid lookups, each
    {"reader", "supplier"} named as outsiders.py names accounts ("gh:<id>", "wallet:<address>")."""
    import outsiders as rules

    buyers: dict[str, set[str]] = {}
    first: dict[str, dict[str, tuple[int, int]]] = {}     # supplier -> buyer -> (paid_at, funded_at) of its first payment
    for j in jobs:
        f = rules.funder_of(j, own, own_wallets, own_repos, own_balances)
        if not f or f[1] != "outside":
            continue
        at, funded = int(j.get("paid_at") or 0), int(j.get("funded_at") or 0)
        for p in rules.payees_of(j, own, own_wallets):
            buyers.setdefault(p, set()).add(f[0])
            mine = first.setdefault(p, {})
            if f[0] not in mine or (at, funded) < mine[f[0]]:
                mine[f[0]] = (at, funded)
    for r in lookups or []:
        reader, supplier = str(r.get("reader") or ""), str(r.get("supplier") or "")
        ours = (reader.startswith("gh:") and reader[3:].isdigit() and int(reader[3:]) in own) or \
            (reader.startswith("wallet:") and reader[7:] in own_wallets)
        if reader and supplier and not ours and supplier != reader:
            buyers.setdefault(supplier, set()).add(reader)
    one, two, saved = [], [], []
    for by in first.values():
        order = sorted((at, funded, b) for b, (at, funded) in by.items() if at)
        if len(order) < 2 or not (order[0][1] and order[1][1]):
            continue
        a, b = order[0][0] - order[0][1], order[1][0] - order[1][1]
        one.append(a)
        two.append(b)
        saved.append(a - b)
    return {"suppliers_reused": sum(1 for b in buyers.values() if len(b) >= 2), "onboarding_pairs": len(saved),
            "onboarding_first_s": _median(one), "onboarding_second_s": _median(two), "onboarding_saved_s": _median(saved)}


def from_repository(root: Path = ROOT) -> dict:
    """The links no chain shows: counted from files of this repository. A key docs/facts.json does not hold is 0."""
    facts = root / "docs" / "facts.json"
    by_hand = json.loads(facts.read_text(encoding="utf-8")).get("by_hand", {}) if facts.is_file() else {}
    folder = root / "reproductions"
    out = {name: int(by_hand.get(name, 0)) for name in BY_HAND}
    out["reproductions_signed"] = len(list(folder.glob("*.json"))) if folder.is_dir() else 0
    return out


def rows(jobs: list[dict] | None = None, root: Path = ROOT, lookups: list[dict] | None = None, **who: frozenset) -> dict:
    """All six, with what each means and whether the chain was read, and the reuse counts under "reuse"."""
    return {**loop(jobs or [], measured=jobs is not None, **who), **from_repository(root), "definitions": DEFINITIONS,
            "reuse": {**reuse(jobs or [], lookups, **who), "definitions": REUSE}}


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="The network loop and supplier reuse, counted.")
    ap.add_argument("--jobs", help="job records, as scripts/outsiders.py reads them; none: nothing was read")
    ap.add_argument("--lookups", help="the record server's paid lookups: [{reader, supplier}]")
    ap.add_argument("--own", help='Knos\'s own accounts: {"ids": [...], "wallets": [...]} (scripts/own_github_ids.json)')
    ap.add_argument("--memory", metavar="DIR", help="a supplier's memory store (knos.proof.history): adds what its second buyer saved, as that memory has it")
    ap.add_argument("--supplier", metavar="ID", help="with --memory: the supplier whose memory is read")
    a = ap.parse_args(argv)

    def read(path: str | None) -> list | dict | None:
        return json.loads(Path(path).read_text(encoding="utf-8")) if path else None

    own = read(a.own) or {}
    who = {"own": frozenset(int(i) for i in own.get("ids", [])), "own_wallets": frozenset(own.get("wallets", []))} if isinstance(own, dict) else {}
    got = rows(read(a.jobs), ROOT, read(a.lookups), **who)  # type: ignore[arg-type]
    if a.memory and a.supplier:     # the supplier's own memory of its buyers (knos.recall order_funded / order_paid)
        from knos.proof import history
        got["reuse"]["memory_saved_s"] = history.reuse(history.SibylStore.for_supplier(a.supplier, Path(a.memory)))["saved_seconds"]
    print(json.dumps(got, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
