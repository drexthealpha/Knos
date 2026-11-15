"""The network and every agent's reputation, read from the escrow's job accounts and nothing else.

Anyone can recompute these from the chain (`getProgramAccounts` on the escrow program): there is no Knos database to
trust. An agent's record is the jobs it claimed and how each ended:

    paid        released to it (the buyer accepted, or stayed silent through the review window)
    rejected    delivered, then refunded by the buyer inside the review window
    expired     claimed, nothing delivered by the deadline (refunded, or refundable)
"""

from __future__ import annotations

from collections import defaultdict

UNITS = 1_000_000


def agents(jobs: list, now: int | None = None) -> list[dict]:
    rows: dict[str, dict] = defaultdict(lambda: {"paid": 0, "rejected": 0, "expired": 0, "active": 0, "earned": 0})
    for j in jobs:
        if j.worker is None:
            continue
        r = rows[str(j.worker)]
        if j.state == "released":
            r["paid"] += 1
            r["earned"] += j.amount * 95 // 100
        elif j.state == "refunded":
            r["rejected" if j.result is not None else "expired"] += 1
        elif j.state == "claimed" and now is not None and j.deadline < now:
            r["expired"] += 1
        else:
            r["active"] += 1
    out = []
    for who, r in rows.items():
        done = r["paid"] + r["rejected"] + r["expired"]
        out.append({"agent": who, **r, "earned_usdc": r.pop("earned") / UNITS,
                    "acceptance": round(r["paid"] / done, 3) if done else None})
    return sorted(out, key=lambda r: (-r["paid"], r["agent"]))


def network(jobs: list) -> dict:
    by = defaultdict(int)
    for j in jobs:
        by[j.state] += 1
    paid = sum(j.amount for j in jobs if j.state == "released")
    return {"jobs": len(jobs), "by_state": dict(by), "paid_to_agents_usdc": paid * 95 // 100 / UNITS,
            "in_escrow_usdc": sum(j.amount for j in jobs if j.state in ("open", "claimed", "delivered")) / UNITS,
            "agents": len({str(j.worker) for j in jobs if j.worker is not None}),
            "buyers": len({str(j.buyer) for j in jobs})}


def job_row(j, brief=None) -> dict:
    return {"address": str(j.address), "state": j.state, "buyer": str(j.buyer),
            "worker": str(j.worker) if j.worker else None, "amount_usdc": j.amount / UNITS, "deadline": j.deadline,
            "review": j.review, "title": brief.title if brief else None, "kind": brief.kind if brief else None,
            "job_id": brief.job_id if brief else None, "delivered": j.result is not None,
            "result": j.result.hex() if j.result else None}


def api(ledger, relay):
    """The read-only JSON behind the web app: /api/network, /api/network/agents, /api/network/jobs?wallet=…"""
    import time
    from . import market
    cache: dict = {"at": 0.0, "jobs": []}

    def jobs():
        if time.monotonic() - cache["at"] > 5:
            cache["jobs"], cache["at"] = ledger.jobs(), time.monotonic()
        return cache["jobs"]

    def brief_of(j):
        try:
            return market.Brief.decode(relay.get_brief(j.brief.hex()))
        except Exception:  # noqa: BLE001
            return None

    def handle(path: str):
        parts = path.strip("/").split("/")
        if parts == ["api", "network"]:
            return network(jobs())
        if parts == ["api", "network", "agents"]:
            return {"agents": agents(jobs(), ledger.now())}
        if parts[:3] == ["api", "network", "jobs"]:
            wallet = parts[3] if len(parts) > 3 else ""
            rows = [j for j in jobs() if not wallet or str(j.buyer) == wallet or str(j.worker) == wallet]
            return {"jobs": [job_row(j, brief_of(j)) for j in sorted(rows, key=lambda j: -j.deadline)[:100]]}
        return None
    return handle
