"""The plain contract over knos.labs (Knos task V34LABS, drexthealpha/knos-e2e#285): dicts in, dicts out.

    ADAPTERS["adaptyv"].quote(ADAPTERS["adaptyv"].example)  -> {"lab", "price", "currency", "turnaround_days", "mode", ...}
    ADAPTERS[name].order(spec, `escrow_ref`)                   ValueError without a vault reference: no order without
                                                             money in vault
    ADAPTERS[name].status(order) / .results(order)           dicts; results carry the two verdicts
    settle(protocol_ok, qc_ok, outcome_ok)                   {"lab_paid", "researcher_paid"}
    public_view(result)                                      what may be public: hashes, timing, the two verdicts

`mode` is "fixture" unless YOUR key for that lab is in the environment (bring your own key), then "live". A lab whose
service is free (computed data, simulation) is quoted at the Knos check price (config/fees.yaml `x402_check`), and the
quote says so in `price_basis`. Examples marked synthetic are made up for the example, never a lab's price.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import verdicts
from .base import Order, Results, Spec, canonical, sha256_hex

FIXTURES = Path(__file__).with_name("fixtures")
EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples" / "labs" / "robotics"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _fx(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _examples() -> dict[str, Spec]:
    a, p, b = _fx("adaptyv"), _fx("pcbway"), _fx("b12_selenium")
    out = {
        "adaptyv": Spec("proteins", a["spec"], qc={"protocol_keys": ["experiment_type", "method", "target_id"], "runs": 3},
                        claim={"metric": "kd_nm", "op": "<=", "value": 100, "agg": "min"}, title="example (fixture)"),
        "b12_selenium": Spec("chemistry", b["spec"], qc={"runs": 1}, claim={"metric": "all_likely_feasible", "op": "==", "value": True, "agg": "all"}),
        "b12_foundry": Spec("chemistry", {"quoted_usd": "4200.00", "turnaround_days": 21, "synthetic": True, "target": "example compound"},
                            qc={"runs": 1}, claim={"metric": "yield_pct", "op": ">=", "value": 30}, title="example (synthetic quote)"),
        "materials_project": Spec("materials", {"material_ids": ["mp-149"]}, qc={"runs": 1},
                                  claim={"metric": "energy_above_hull", "op": "<=", "value": 0.025, "agg": "max"}),
        "pcbway": Spec("electronics", p["spec"], qc=p["qc"], claim=p["claim"]),
        "xometry": Spec("mechanical", {"quoted_usd": "180.00", "turnaround_days": 10, "synthetic": True, "part": "example bracket"},
                        qc={"runs": 1}, claim={"metric": "within_tolerance", "op": "==", "value": True, "agg": "all"},
                        title="example (synthetic quote; Xometry is ordered on its website)"),
        "pylabrobot": Spec("robotics", {"protocol_file": str(EXAMPLES_DIR / "serial_dilution.py"),
                                        "sealed_test": str(EXAMPLES_DIR / "sealed_test.json"), "reruns": 2},
                           qc={"runs": 2}, claim={"metric": "max_abs_error_ul", "op": "<=", "value": 0.5, "agg": "max"}),
    }
    return out


def _d(x: Any) -> dict:
    return asdict(x) if is_dataclass(x) and not isinstance(x, type) else dict(x)


class Lab:
    """One lab behind the plain contract. Calling it returns itself, so ADAPTERS[name] and ADAPTERS[name]() both work."""

    def __init__(self, name: str, adapter_name: str | None = None):
        from . import REGISTRY
        self.name = name
        self.adapter_name = adapter_name or name
        _mod, _cls, self.field, self.what = REGISTRY[self.adapter_name] if self.adapter_name in REGISTRY else (None, None, "mechanical", "")
        self.example = _examples()[name]
        self._orders: dict[str, tuple[Order, Spec]] = {}

    def __call__(self, *a, **k) -> "Lab":
        return self

    def _adapter(self):
        from . import get, manual
        if self.name == "xometry":
            lab = manual.Manual()
            lab.NAME, lab.FIELD, lab.CONTACT = "xometry", "mechanical", "xometry.com (its API serves manufacturing partners, not buyers)"
            return lab
        cls = get(self.adapter_name)
        env = cls.KEY_ENV
        live = bool(env and os.environ.get(env)) and (self.name != "b12_selenium" or os.environ.get("KNOS_B12_SELENIUM_BASE"))
        return get(self.adapter_name, "live" if live else "fixture")

    @property
    def mode(self) -> str:
        return self._adapter().mode

    def quote(self, spec: Spec | dict | None = None) -> dict:
        spec = _spec(spec, self.example)
        a = self._adapter()
        q = a.quote(spec)
        basis = "the lab's price"
        if q.currency == "credits":
            price, currency, basis = Decimal(q.lines[0]["credits"]), "credits", "b12 credits (the USD price of a credit is not published)"
        else:
            price, currency = Decimal(q.amount_usd or "0"), q.currency
        if price <= 0:
            from ..money import fees_config
            price = Decimal(fees_config.load().doc["fees"]["x402_check"]["usd_each"])
            basis = "the Knos check price (config/fees.yaml x402_check): the lab's data or simulation is free"
        return {"lab": self.name, "field": self.field, "price": float(price), "price_text": str(price), "currency": currency,
                "price_basis": basis, "turnaround_days": q.turnaround_days if q.turnaround_days is not None else 0,
                "mode": a.mode, "fixture": a.mode == "fixture", "source": q.source}

    def order(self, spec: Spec | dict | None, escrow_ref: str | None) -> dict:
        if not escrow_ref or not isinstance(escrow_ref, str):
            raise ValueError("no order without held money: name the Knos order (escrow_ref) that holds the money for this lab")
        spec = _spec(spec, self.example)
        a = self._adapter()
        o = a.order(spec, escrow_ref)
        self._orders[o.order_id] = (o, spec)
        return {**_d(o), "mode": a.mode}

    def _find(self, order: dict | Order | str) -> tuple[Order, Spec]:
        oid = order if isinstance(order, str) else (order.order_id if isinstance(order, Order) else order.get("order_id"))
        if oid not in self._orders:
            raise ValueError(f"no order {oid!r} placed through this adapter")
        return self._orders[oid]

    def status(self, order: dict | Order | str) -> dict:
        o, _spec_ = self._find(order)
        a = self._adapter()
        st = "completed" if self.name in ("xometry", "b12_foundry") else a.status(o).state
        return {"lab": self.name, "order_id": o.order_id, "state": st, "mode": a.mode}

    def results(self, order: dict | Order | str, publish: bool = False) -> dict:
        o, spec = self._find(order)
        a = self._adapter()
        if self.name in ("xometry", "b12_foundry"):
            raise ValueError(f"{self.name} is ordered by a person: its results come back with knos.labs.manual.Manual.deliver")
        r: Results = a.results(o, spec) if self.name == "pylabrobot" else a.results(o)
        if self.name == "pcbway":
            r = a.with_bench(r, _fx("pcbway")["bench"])
        lab = verdicts.lab_verdict(spec, r)
        out = verdicts.outcome_verdict(spec, r, lab)
        return {**r.to_dict(), "spec_hash": spec.hash(), "lab_verdict": lab.verdict, "outcome_verdict": out.verdict,
                "settle": settle(lab.passed, lab.passed, out.passed), "publish": publish}


def _spec(spec, example: Spec) -> Spec:
    if spec is None:
        return example
    if isinstance(spec, Spec):
        return spec
    if isinstance(spec, dict) and "protocol" in spec:
        return Spec(spec.get("field", example.field), spec["protocol"], spec.get("qc", {}), spec.get("claim", {}), spec.get("title", ""))
    if isinstance(spec, dict):
        return Spec(example.field, spec, example.qc, example.claim)
    raise ValueError("a spec is a knos.labs.Spec or a dict")


def settle(protocol_ok: bool, qc_ok: bool, outcome_ok: bool) -> dict:
    """The two verdicts as payments: the lab is paid when the protocol ran as specified and QC passed, even when the
    science failed; the researcher only when the outcome also holds."""
    lab = bool(protocol_ok) and bool(qc_ok)
    return {"lab_paid": lab, "researcher_paid": lab and bool(outcome_ok),
            "lab_verdict": "PASS" if lab else "FAIL", "outcome_verdict": ("PASS" if outcome_ok else "FAIL") if lab else "VOID"}


TIMING = ("ordered_at", "results_at", "submitted_at", "completed_at", "created_at", "turnaround_s", "turnaround_days", "duration_s")
VERDICTS = ("lab_verdict", "outcome_verdict")


def _hashes(result: dict) -> list[str]:
    out = []

    def walk(v, key=""):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, str) and _HEX64.match(v) and any(t in key.lower() for t in ("hash", "sha256", "digest")):
            out.append(v)
    walk(result)
    return sorted(set(out))


def public_view(result: dict | Results) -> dict:
    """What a lab result may show in public. With publish False (the default): a sha256 of the whole result, the
    sha256 hashes it already carries (spec, evidence, files: hashes only, never names), timing and the two verdicts.
    No buyer data, no data values, no raw file names. With publish True (the buyer's opt-in), the result too."""
    d = result.to_dict() if isinstance(result, Results) else dict(result)
    view = {"result_sha256": sha256_hex(canonical(json.loads(json.dumps(d, default=str)))), "hashes": _hashes(d),
            "timing": {k: d[k] for k in TIMING if k in d and isinstance(d[k], (str, int, float)) and not isinstance(d[k], bool)},
            **{k: d.get(k) for k in VERDICTS}, "publish": bool(d.get("publish"))}
    if d.get("publish") is True:
        view["published"] = d
    return view


def adapters() -> dict[str, Lab]:
    return {n: Lab(n) for n in ("adaptyv", "b12_selenium", "b12_foundry", "materials_project", "pcbway", "xometry", "pylabrobot")}
