"""Contributor splits: who receives which share of a payout, as the payees of one knos_pay order.

The researcher, the agents, the lab and the referee each get a fixed share of every payout. The shares are in
config/fees.yaml (`splits.roles`, read through knos.money.fees_config: 60/25/10/5, decided by the founder on 14 Oct 2026).
On chain a share is a payee of the order: an order pays one to four payees (pay.MAX_PAYEES), each `(GitHub id,
basis points, address or None)`, named by the pay token the order's pinned judge workflow asks GitHub to sign
(pay.order_pay_audience). The program divides the amount itself: each share rounded down, the last payee the rest
(`amounts`). So a split is paid automatically, by the vault, in the transaction that pays the order; nobody
forwards money afterwards.

    contributors = [{"role": "researcher", "github_id": 1, "address": "..."}, {"role": "agent", "github_id": 2}]
    payees(contributors)            [(1, 7059, Pubkey), (2, 2941, None)]  (roles absent leave their share to the rest)
    amounts(amount, contributors)   [(role, github_id, base units)], summing to `amount`
"""
from __future__ import annotations

from typing import Any

from ..money import fees_config


class SplitError(ValueError):
    pass


def _contributors(contributors: Any, cfg: fees_config.FeeConfig) -> list[dict]:
    if not isinstance(contributors, (list, tuple)) or not contributors:
        raise SplitError("contributors: a list of {role, github_id, address?}")
    out, seen_roles, seen_ids = [], set(), set()
    for c in contributors:
        if not isinstance(c, dict):
            raise SplitError("each contributor is {role, github_id, address?}")
        role, gid, addr = c.get("role"), c.get("github_id"), c.get("address")
        if role not in cfg.roles:
            raise SplitError(f"role {role!r}: one of {', '.join(cfg.roles)}")
        if role in seen_roles:
            raise SplitError(f"role {role} twice: one payee per role")
        if isinstance(gid, bool) or not isinstance(gid, int) or not 0 < gid < 2 ** 64:
            raise SplitError(f"{role}: github_id is the account's number (above 0)")
        if gid in seen_ids:
            raise SplitError(f"GitHub id {gid} twice: the program refuses a payee named twice")
        if addr is not None:
            from solders.pubkey import Pubkey
            try:
                addr = Pubkey.from_string(str(addr))
            except ValueError:
                raise SplitError(f"{role}: address is not a Solana address") from None
        seen_roles.add(role)
        seen_ids.add(gid)
        out.append({"role": role, "github_id": gid, "address": addr})
    order = list(cfg.roles)
    return sorted(out, key=lambda c: order.index(c["role"]))


def payees(contributors: Any, cfg: fees_config.FeeConfig | None = None) -> list[tuple[int, int, Any]]:
    """The payees of a pay token for these contributors: (GitHub id, bps, address or None), bps adding up to 10000,
    in the config's role order. An address left out: the payee is paid at the wallet it bound, else held for it."""
    cfg = cfg or fees_config.load()
    cs = _contributors(contributors, cfg)
    shares = dict(cfg.shares([c["role"] for c in cs]))
    return [(c["github_id"], shares[c["role"]], c["address"]) for c in cs]


def amounts(amount: int, contributors: Any, cfg: fees_config.FeeConfig | None = None) -> list[tuple[str, int, int]]:
    """(role, GitHub id, base units) each contributor receives of `amount`, exactly as the program divides it."""
    cfg = cfg or fees_config.load()
    cs = _contributors(contributors, cfg)
    ps = payees(contributors, cfg)
    return [(c["role"], c["github_id"], a) for c, a in zip(cs, fees_config.amounts(amount, [b for _, b, _ in ps]))]
