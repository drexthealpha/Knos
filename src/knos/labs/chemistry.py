"""Chemistry: b12 labs (b12-labs.com), the best documented option found on 14 Oct 2026.

Two services, two adapters:

  b12_selenium   Selenium Route Search: computational retrosynthesis (how to make a molecule), with a documented API
                 (OpenAPI https://b12-labs.com/docs/selenium-route-search/openapi.json, v0.1.0; docs
                 https://b12-labs.com/docs/selenium-route-search/). Live-ready in bring-your-own-key mode:
                   auth     Authorization: Bearer $B12_API_KEY (the key comes from app.b12-labs.com)
                   base     not published (the docs use $SELENIUM_API_URL): set KNOS_B12_SELENIUM_BASE
                   quote    POST /v1/route-searches/quote {"smiles", "tier", ...} -> credits_required, params, version
                   order    POST /v1/route-searches (+ Idempotency-Key) -> 202 {id, status, credits_charged, links}
                   status   GET /v1/route-searches/{id} -> queued | running | completed | partial | failed | cancelled
                   results  GET /v1/route-searches/{id}/routes -> families[] {status solved|incomplete, best_route
                            {molecules, reactions[assessment.band likely_feasible|uncertain|high_risk], stats}}
                 Priced in credits; the price of a credit is not published, so a quote carries credits, not USD.
  b12_foundry    the b12 Foundry: commissioned synthesis and experimental chemistry in a partner lab at the University
                 of Zurich, run on Chemspeed workflows "from solid dispensing to LC-MS analysis" (b12-labs.com/foundry).
                 Ordered by e-mail; scope and deliverables are agreed before work starts; no public price, no API. So
                 it is a MANUAL lab (knos.labs.manual): Knos holds the vault and gives the verdicts on the files the
                 buyer brings back (LC-MS traces, NMR, yield).

Compound sourcing with a full documented quote/order/status API also exists (Molport, api.molport.com/openapi.json;
Mcule, doc.mcule.com): the next chemistry rail. IBM RXN for Chemistry is not used:
its README says the hosted service reaches end of service on 28 Oct 2026.
"""
from __future__ import annotations

import uuid

from .base import Adapter, LabError, Order, Quote, Results, Spec, Status
from .manual import Manual

STATE = {"queued": "submitted", "running": "in_progress", "completed": "completed", "partial": "completed", "failed": "failed",
         "cancelled": "cancelled"}


class B12Selenium(Adapter):
    NAME = "b12_selenium"
    FIELD = "chemistry"
    KEY_ENV = "B12_API_KEY"
    BASE = "https://selenium.b12-labs.invalid"       # not published: KNOS_B12_SELENIUM_BASE names it in live mode
    DOCS = "https://b12-labs.com/docs/selenium-route-search/"
    LIVE_READY = True

    def __init__(self, mode: str = "fixture", transport=None, key: str | None = None, base: str | None = None):
        super().__init__(mode, transport, key, base)
        if mode == "live" and self.base == self.BASE:
            raise LabError("b12_selenium: its base URL is not published; set KNOS_B12_SELENIUM_BASE to the one b12 gives you")

    def auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key()}"}

    @staticmethod
    def body(spec: Spec) -> dict:
        p = dict(spec.protocol)
        if not isinstance(p.get("smiles"), str) or not p["smiles"]:
            raise LabError("protocol.smiles: the target molecule as SMILES")
        allowed = {"smiles", "name", "tier", "max_route_families", "researcher_runs", "target_ready_routes", "timeout_minutes",
                   "chemistry_mode", "researcher_model", "route_developer_mode", "route_developer_model", "version"}
        extra = set(p) - allowed
        if extra:
            raise LabError(f"b12 refuses unknown fields (additionalProperties: false): {', '.join(sorted(extra))}")
        return p

    def quote(self, spec: Spec) -> Quote:
        _s, a, _h = self._call("POST", "/v1/route-searches/quote", self.body(spec))
        credits = int(a["credits_required"])
        return Quote(self.NAME, "", "credits", None, None, None, [{"what": "route search", "credits": credits, "params": a.get("params")}],
                     ["b12 credits"], self.is_fixture, self.label, a)

    def order(self, spec: Spec, escrow_ref: str, quote: Quote | None = None) -> Order:
        # one idempotency key per (spec, vault): a retried order is the same order, never a second charge
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"knos:{spec.hash()}:{escrow_ref}"))
        _s, a, _h = self._call("POST", "/v1/route-searches", self.body(spec), spends=True, headers={"Idempotency-Key": key})
        return Order(self.NAME, a["id"], escrow_ref, spec.hash(), STATE.get(str(a.get("status")), "submitted"), self.is_fixture, self.label, a)

    def status(self, order: Order) -> Status:
        _s, a, _h = self._call("GET", f"/v1/route-searches/{order.order_id}")
        return Status(self.NAME, order.order_id, STATE.get(str(a.get("status")), "in_progress"), str(a.get("status")), self.is_fixture, self.label, a)

    def results(self, order: Order) -> Results:
        st = self.status(order)
        _s, a, _h = self._call("GET", f"/v1/route-searches/{order.order_id}/routes")
        runs = []
        for f in a.get("families") or []:
            best = f.get("best_route") or {}
            bands = [((r.get("assessment") or {}).get("band")) for r in best.get("reactions") or []]
            stats = best.get("stats") or {}
            runs.append({"id": f.get("id"), "ok": f.get("status") == "solved", "why": None if f.get("status") == "solved" else "family incomplete",
                         "measurements": {"solved": f.get("status") == "solved", "reaction_count": stats.get("reaction_count"),
                                          "commercially_solved": stats.get("commercially_solved"),
                                          "all_likely_feasible": bool(bands) and all(b == "likely_feasible" for b in bands)}})
        why = [] if st.state == "completed" else [f"job {st.lab_state}"]
        qc = {"passed": not why and a.get("stats") is not None, "why": "; ".join(why) or None, "stats": a.get("stats"),
              "dropped": a.get("dropped"), "rule": "knos"}
        from .base import canonical, sha256_hex
        return Results(self.NAME, order.order_id, st.state, runs, qc, [{"name": "routes.json", "sha256": sha256_hex(canonical(a))}],
                       {"smiles": (a.get("target") or {}).get("smiles")}, self.is_fixture, self.label, a)


class B12Foundry(Manual):
    NAME = "b12_foundry"
    FIELD = "chemistry"
    CONTACT = "founders@b12-labs.com (b12-labs.com/foundry, read 14 Oct 2026)"
    DOCS = "https://b12-labs.com/foundry/"
