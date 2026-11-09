"""Paying a variable result with today's fixed-amount orders: one knos_pay order per tier.

Tier k is a work order funded from the buyer's wallet (FundOrderWallet) for the spec's repository and issue, with
seq = escrow.seq_start + k, the tier's amount, the tier's terms (`knos.outcomes.spec.terms`: the spec's hash, the
tier, its bar) and the pin: the repository's prove.yml at the commit that holds the spec, the lock and the measuring
code. So:

    - the most the buyer can pay is the sum of the tiers' amounts, which the spec requires to equal its cap;
    - a tier pays only on a token from that prove.yml at that commit whose audience names that order and that
      tier's terms hash (knos_pay checks both; no new program, no oracle);
    - a tier whose bar was not reached is never signed for, and its money goes back to the funder after the
      deadline with RefundOrder, which needs no token.

Nothing here talks to the network: instruction builders and plans. `knos.outcomes.demo` sends them on devnet.
"""
from __future__ import annotations

from solders.pubkey import Pubkey

from ..settle.v2 import pay
from .spec import micro, spec_hash, terms_bytes, terms_hash


def order_address(spec: dict, k: int) -> Pubkey:
    e = spec["escrow"]
    return pay.order_pda(pay.scope_of(int(e["repository_id"]), int(e["issue"])), Pubkey.from_string(e["funder"]), int(e["seq_start"]) + k)


def orders(spec: dict) -> list[dict]:
    """Each tier's order as the lock lists it."""
    out = []
    for k, t in enumerate(spec["tiers"]):
        out.append({"tier": k, "name": t["name"], "seq": int(spec["escrow"]["seq_start"]) + k, "address": str(order_address(spec, k)),
                    "terms_hash": terms_hash(spec, k).hex(), "amount": micro(t["amount"]), "fee": pay.order_fee(micro(t["amount"]))})
    return out


def fund_ixs(spec: dict, wf_sha: str, funder: Pubkey, funder_token: Pubkey, mint: Pubkey, decimals: int = 6) -> list:
    """FundOrderWallet for every tier, pinned to the spec's repository's prove.yml at `wf_sha`."""
    e = spec["escrow"]
    if str(funder) != e["funder"] or str(mint) != e["mint"]:
        raise ValueError("the funding wallet and the mint must be the spec's escrow.funder and escrow.mint")
    if e["cluster"] not in ("devnet", "localnet"):
        raise ValueError("devnet or localnet only")
    ixs = []
    for k, t in enumerate(spec["tiers"]):
        ixs.append(pay.fund_order_wallet_ix(funder, funder_token, mint, int(e["repository_id"]), int(e["issue"]), pay.units(micro(t["amount"]), decimals),
                                            e["repository"], wf_sha, terms_bytes(spec, k), pay.MERGE, int(e["work_seconds"]), int(e["seq_start"]) + k))
    return ixs


def escrowed(spec: dict) -> dict:
    """What the buyer puts in: the tiers' amounts (= the cap) and the fees on top, in millionths."""
    amounts = [micro(t["amount"]) for t in spec["tiers"]]
    fees = [pay.order_fee(a) for a in amounts]
    return {"amounts": amounts, "fees": fees, "cap": micro(spec["price"]["cap"]), "total": sum(amounts) + sum(fees), "spec_hash": spec_hash(spec)}


def outcome_of(o: pay.Order | None, closed_by: str | None) -> str:
    """open / paid / refunded, from the order account (None once closed) and how it closed."""
    if o is not None:
        return o.state
    return closed_by or "closed"
