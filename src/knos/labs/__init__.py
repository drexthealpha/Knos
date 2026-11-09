"""Knos labs: the best designs go to cloud labs and fabs through ONE interface, and the two verdicts decide who is paid.

    from knos import labs
    lab = labs.get("adaptyv")                     fixture mode (recorded responses); labs.get("adaptyv", "live") uses
                                                  YOUR key ($ADAPTYV_API_KEY): bring your own key, Knos never resells
    q = lab.quote(spec)          price + turnaround
    o = lab.order(spec, vault)  bound to the Knos vault that pays it
    lab.status(o)                one of base.STATES
    r = lab.results(o)           data + QC + raw file hashes, failed runs included
    v1 = verdicts.lab_verdict(spec, r)                  protocol + QC: PASS pays the lab, even if the science failed
    v2 = verdicts.outcome_verdict(spec, r, v1)          the claim: PASS pays the researcher and lets it graduate
    `escrow`.settlement(plan, v1, v2)                     the transfers the two verdicts allow
    privacy.public_record(...)                          what Knos Record may hold: hashes, timing, the two verdicts

Every field of science plugs in the same way; the adapters below are examples, not the plan:
"""
from __future__ import annotations

from .base import STATES, Adapter, LabError, NoKey, Order, Quote, Results, Spec, Status

# name -> (module, class, field, what)
REGISTRY = {
    "adaptyv": ("adaptyv", "Adaptyv", "proteins", "Adaptyv Bio Foundry API: binding, expression, thermostability (BYOK, live-ready)"),
    "b12_selenium": ("chemistry", "B12Selenium", "chemistry", "b12 Selenium Route Search: retrosynthesis routes (BYOK, live-ready; base URL from b12)"),
    "b12_foundry": ("chemistry", "B12Foundry", "chemistry", "b12 Foundry: commissioned synthesis, ordered by e-mail (manual lab)"),
    "materials_project": ("materials", "MaterialsProject", "materials", "Materials Project: computed ground truth (key required, free account)"),
    "pcbway": ("electronics", "PCBWay", "electronics", "PCBWay partner API: PCB quote, order, fabrication status (partner key)"),
    "jlcpcb": ("electronics", "JLCPCB", "electronics", "JLCPCB open API: documented, access by application (stub)"),
    "xometry": ("mechanical", "Xometry", "mechanical", "Xometry: its API is for manufacturing partners, not buyers (stub; manual orders)"),
    "pylabrobot": ("robotics", "PyLabRobot", "robotics", "PyLabRobot: liquid-handling protocols re-run on its simulator as sealed tests"),
    "manual": ("manual", "Manual", "any", "any lab without an API: Knos holds the money until the proof passes, a person places the order"),
}


def get(name: str, mode: str = "fixture", **kw) -> Adapter:
    if name not in REGISTRY:
        raise LabError(f"no lab adapter {name!r}: one of {', '.join(REGISTRY)}")
    import importlib
    mod, cls, _f, _w = REGISTRY[name]
    return getattr(importlib.import_module(f"{__name__}.{mod}"), cls)(mode, **kw)


def catalogue() -> list[dict]:
    out = []
    for name in REGISTRY:
        a = get(name) if name != "manual" else None
        mod, cls, field, what = REGISTRY[name]
        out.append({"lab": name, "field": field, "what": what, **({k: v for k, v in a.describe().items() if k in ("live_ready", "key_env", "docs", "orders", "fixture_label")} if a else {})})
    return out


from .contract import Lab, public_view, settle  # noqa: E402 - the plain contract over the adapters above


def __getattr__(name: str):
    """ADAPTERS: name -> Lab (quote/order/status/results as dicts, each with its `example` spec), built on first use."""
    if name == "ADAPTERS":
        from .contract import adapters
        globals()["ADAPTERS"] = got = adapters()
        return got
    raise AttributeError(name)

__all__ = ["ADAPTERS", "REGISTRY", "STATES", "Adapter", "Lab", "LabError", "NoKey", "Order", "Quote", "Results", "Spec", "Status",
           "catalogue", "get", "public_view", "settle"]
