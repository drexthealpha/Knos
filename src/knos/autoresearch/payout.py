"""What happens after graduation: the outcome the referee measured, and who would be paid how much. A PLAN only:
nothing here signs or sends a transaction. Amounts are integers in micro-units of devnet test USDC.

    outcome(...)   the measured result in the shape an outcome check carries (metric, baseline, treated = the best,
                   lift per seed, the bar, passed, spec hash). knos.outcomes is not called: its spec is about a
                   treatment/control split over live data, this is a before/after on sealed data.
    split_plan(...) the bounty, divided by the roles' shares of THE one fee config (knos.money.fees_config,
                   config/fees.yaml; only the roles this task names and the config has) when it is installed, else by
                   task.json's shares. The payout fee is the funder's, ON TOP of the bounty (fees.yaml: "the funder pays
                   it on top of the amount"): the contributors receive the whole bounty. The agents' share is divided among the agents whose changes were kept, by count.
                   Paying it is graduation's job (knos.graduation: a vault order paying up to 4 payees, devnet).
"""
from __future__ import annotations


def outcome(task, seal: dict, final: dict) -> dict:
    return {"metric": task.spec["metric"], "direction": task.spec["direction"],
            "baseline": final["baseline"].get("scores"), "treated": final["best"].get("scores"),
            "lift_per_seed": final["lift_per_seed"], "lift": final["lift"], "min_lift": final["min_lift"],
            "passed": final["graduated"], "spec_hash": seal["spec_hash"], "seeds": task.spec["seeds"][:2],
            "data": "hidden_final (sealed; never used during the loop)", "synthetic": bool(task.spec.get("synthetic"))}


def _fees():
    try:
        from knos.money import fees_config  # type: ignore[attr-defined]
        return fees_config.load()
    except Exception:  # noqa: BLE001 - not installed, or no config file: the plan says so
        return None


def _divide(amount: int, weights: dict[str, int]) -> dict[str, int]:
    """Round down each share; the last one gets what is left, so the parts sum exactly to amount."""
    total = sum(weights.values())
    names = list(weights)
    out = {n: amount * weights[n] // total for n in names[:-1]} if total else {}
    if names:
        out[names[-1]] = amount - sum(out.values())
    return out


def split_plan(task, kept_by_agent: dict[str, int], graduated: bool) -> dict:
    b = task.spec.get("bounty") or {}
    amount = int(b.get("amount", 0))
    plan = {"status": "plan only: no transaction is built or sent", "cluster": "devnet", "currency": b.get("currency", ""),
            "amount": amount, "synthetic": bool(task.spec.get("synthetic"))}
    if not graduated or amount <= 0:
        return dict(plan, payable=False, why="not graduated" if not graduated else "no bounty", parts=[])
    cfg = _fees()
    wanted = {r: int(v) for r, v in (b.get("shares") or {}).items()}
    known = [r for r in wanted if r in (getattr(cfg, "roles", None) or {})] if cfg is not None else []
    if cfg is not None and known:
        fee = int(cfg.fee("payout", amount))
        roles = [(r, int(v)) for r, v in cfg.split(amount, known)]
        source = "knos.money.fees_config (config/fees.yaml)"
    else:
        fee = None
        roles = list(_divide(amount, wanted).items())
        source = "task.json bounty.shares (" + ("knos.money not installed" if cfg is None else "no role of this task is in the fee config") + "; fee not computed)"
    parts = []
    for role, micro in roles:
        if role == "agent" and kept_by_agent:
            for agent, part in _divide(micro, kept_by_agent).items():
                parts.append({"role": "agent", "who": agent, "amount": part})
        else:
            parts.append({"role": role, "who": task.spec.get("contributors", {}).get(role, f"<{role}>"), "amount": micro})
    return dict(plan, payable=True, fee=fee, fee_payer="funder, on top of the bounty",
                funder_pays=None if fee is None else amount + fee, shares_from=source, parts=parts)
