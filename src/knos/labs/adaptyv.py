"""Adaptyv Bio (proteins): the first lab, live-ready in bring-your-own-key mode.

Every endpoint and field below was read on 14 Oct 2026 from Adaptyv's own docs and OpenAPI document:
  docs   https://docs.adaptyvbio.com/llms-full.txt (every page, each with its Source URL)
  spec   https://devs.adaptyvbio.com/api/v1/openapi.json (OpenAPI, version 0.0.2); sandbox: devs.testing.adaptyvbio.com

  base       https://devs.adaptyvbio.com/api/v1 (sandbox https://devs.testing.adaptyvbio.com/api/v1: set KNOS_ADAPTYV_BASE)
  auth       Authorization: Bearer <token>; the token is made in the Foundry portal (Organization -> Settings -> Tokens),
             role Member for experiments, Billing or Member to accept quotes and pay invoices (docs: API introduction,
             payments overview). Knos reads it from $ADAPTYV_API_KEY and never prints, logs or records it.
  quote      POST /experiments/cost-estimate {"experiment_spec"} -> breakdown.total_cents (USD cents, excl. VAT)
  order      POST /experiments {"name", "experiment_spec", "skip_draft": true, "payment": {"method": "x402-exact"}}
             -> experiment_id; then GET /experiments/{id}/quote (404 until the quote exists: poll) and
             POST /experiments/{id}/quote/confirm {"purchase_order_number", "notes"} -> invoice_id + payment
             {kind: "machine", pay_url: /api/v1/invoices/{invoice_id}/pay}. Confirming never moves money.
  pay        POST /invoices/{invoice_id}/pay -> 402 with the challenge in the PAYMENT-REQUIRED header (x402 v2,
             `exact`, EIP-3009 USDC on Base); retry with PAYMENT-SIGNATURE (knos.labs.x402pay) -> settlement_reference.
  status     GET /experiments/{id} -> status: draft, waiting_for_confirmation, quote_sent, waiting_for_materials,
             in_queue, in_production, data_analysis, in_review, done, canceled (the prose docs write them in
             PascalCase: matched without case or underscores)
  results    GET /experiments/{id}/results -> {items: [ResultInfo {id, result_type, summary[], data_package_url}]};
             an affinity summary entry per sequence: kd_mean (M), kon_mean, koff_mean, binding ("true", "false",
             "unknown", "in_progress"), binding_strength, expression, fit_quality, positive_control, replicates[]

Terms that shape this adapter (docs.adaptyvbio.com/api-reference/integrator-partner-guide): BYOK is required, "you must
not 'bundle' user orders under your own key"; keys are not stored in plain text (Knos does not store them at all);
resellers and distributors must join the Partner Program (not joined).

What is Knos's and not Adaptyv's: the run mapping (one run per sequence, controls marked) and the QC rule (the positive
control bound, every sequence reported, results complete). Fixture mode replays fixtures/adaptyv.json: responses built
from the shapes and examples in Adaptyv's OpenAPI document, with made-up ids and values (labelled; never a real order).
"""
from __future__ import annotations

from .base import Adapter, LabError, Order, Quote, Results, Spec, Status

STATE = {"draft": "draft", "waitingforconfirmation": "quoted", "quotesent": "quoted", "waitingformaterials": "submitted",
         "inqueue": "submitted", "inproduction": "in_progress", "dataanalysis": "qc", "inreview": "qc", "done": "completed",
         "canceled": "cancelled", "cancelled": "cancelled"}
# turnaround from the FAQ (docs.adaptyvbio.com/docs/faq/overview): 2-3 weeks expression/thermostability, 3-4 binding
TURNAROUND_DAYS = {"affinity": 28, "screening": 28, "epitope_binning": 28, "thermostability": 21, "expression": 21}
M_TO_NM = 1e9


def norm_state(s: str) -> str:
    return STATE.get(str(s).replace("_", "").replace(" ", "").lower(), "in_progress")


class Adaptyv(Adapter):
    NAME = "adaptyv"
    FIELD = "proteins"
    KEY_ENV = "ADAPTYV_API_KEY"
    BASE = "https://devs.adaptyvbio.com/api/v1"
    DOCS = "https://docs.adaptyvbio.com/llms-full.txt"
    LIVE_READY = True

    def auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key()}"}

    @staticmethod
    def check_spec(spec: Spec) -> dict:
        """The experiment_spec, checked against the documented rules before anything is sent."""
        p = dict(spec.protocol)
        t = p.get("experiment_type")
        types = ("affinity", "screening", "thermostability", "fluorescence", "expression", "epitope_binning", "enzyme_activity")
        if t not in types:
            raise LabError(f"experiment_type: one of {', '.join(types)}")
        if t in ("affinity", "screening") and p.get("method") not in ("bli", "spr"):
            raise LabError("affinity and screening need method bli or spr")
        if t not in ("affinity", "screening") and "method" in p:
            raise LabError(f"{t} takes no method")
        if t in ("affinity", "screening", "epitope_binning") and not p.get("target_id"):
            raise LabError(f"{t} needs a target_id (GET /targets)")
        if not isinstance(p.get("sequences"), dict) or not p["sequences"]:
            raise LabError("sequences: a mapping of name to amino-acid string (or {aa_string, control, metadata})")
        n = p.get("n_replicates", 3)
        if t != "epitope_binning" and not (isinstance(n, int) and 1 <= n <= 5):
            raise LabError("n_replicates: 1 to 5")
        return p

    # -- quote ---------------------------------------------------------------------------------------------------------
    def quote(self, spec: Spec) -> Quote:
        p = self.check_spec(spec)
        _s, a, _h = self._call("POST", "/experiments/cost-estimate", {"experiment_spec": p})
        b = a.get("breakdown")
        if not b:
            why = (a.get("incomplete") or {}).get("materials_unavailable") or a.get("warnings")
            raise LabError(f"adaptyv gives no self-service price for this spec (a custom quote is needed): {why}")
        cents = int(b["total_cents"])
        lines = [{"what": "assay", **(b.get("assay") or {})}] + ([{"what": "materials", **b["materials"]}] if b.get("materials") else [])
        return Quote(self.NAME, f"{cents // 100}.{cents % 100:02d}", "USD", TURNAROUND_DAYS.get(p["experiment_type"]), None, None, lines,
                     ["x402-exact (USDC on Base)", "async_invoice (Stripe hosted invoice)", "mpp-spt"], self.is_fixture, self.label, a)

    # -- order ---------------------------------------------------------------------------------------------------------
    def order(self, spec: Spec, escrow_ref: str, quote: Quote | None = None, *, webhook_url: str | None = None) -> Order:
        p = self.check_spec(spec)
        body = {"name": spec.title or f"Knos order {spec.hash()[:12]}", "experiment_spec": p, "skip_draft": True,
                "payment": {"method": "x402-exact"}, **({"webhook_url": webhook_url} if webhook_url else {})}
        _s, a, _h = self._call("POST", "/experiments", body, spends=True)
        exp = a.get("experiment_id")
        if not exp:
            raise LabError(f"adaptyv created no experiment: {a.get('error')}")
        return Order(self.NAME, exp, escrow_ref, spec.hash(), "quoted", self.is_fixture, self.label, a)

    def lab_quote(self, order: Order) -> dict:
        """GET /experiments/{id}/quote: amount_total (cents), currency, status, expires_at. A 404 means 'not yet'."""
        status, a, _h = self._call("GET", f"/experiments/{order.order_id}/quote", ok=(200, 404))
        return {"ready": status == 200, **a}

    def confirm(self, order: Order) -> dict:
        """Accept the quote (never moves money): invoice_id and the machine payment link. The vault reference is sent
        as the purchase order number, so the lab's invoice names the Knos vault that pays it."""
        _s, a, _h = self._call("POST", f"/experiments/{order.order_id}/quote/confirm",
                               {"purchase_order_number": order.escrow_ref[:64], "notes": "paid from money Knos holds until the LAB verdict"},
                               spends=True)
        return a

    def challenge(self, invoice_id: str) -> tuple[int, dict, dict]:
        """POST /invoices/{id}/pay with no credential: the 402 and its PAYMENT-REQUIRED header (decode with
        knos.labs.x402pay.decode_challenge)."""
        return self._call("POST", f"/invoices/{invoice_id}/pay", {}, ok=(200, 402))

    # -- status / results ---------------------------------------------------------------------------------------------
    def status(self, order: Order) -> Status:
        _s, a, _h = self._call("GET", f"/experiments/{order.order_id}")
        return Status(self.NAME, order.order_id, norm_state(a.get("status", "")), str(a.get("status")), self.is_fixture, self.label, a)

    def results(self, order: Order) -> Results:
        st = self.status(order)
        _s, a, _h = self._call("GET", f"/experiments/{order.order_id}/results")
        items = a.get("items") or []
        runs, files, controls = [], [], set()
        for res in items:
            if res.get("data_package_url"):
                files.append({"name": f"{res.get('id')}.zip", "url": res["data_package_url"],
                              "sha256": self.file_hash(res["data_package_url"])})
            for s in res.get("summary") or []:
                if s.get("positive_control"):
                    controls.add(s["positive_control"])
                runs.append(_run(res.get("result_type") or s.get("result_type"), s))
        for r in runs:
            r["control"] = r["id"] in controls
        exp_spec = (st.raw or {}).get("experiment_spec") or {}
        executed = {k: exp_spec.get(k) for k in ("experiment_type", "method", "n_replicates")}
        tgt = exp_spec.get("target") or {}
        executed["target_id"] = tgt.get("id") if isinstance(tgt, dict) else exp_spec.get("target_id")
        executed["sequences"] = sorted((exp_spec.get("sequences") or {}).keys())
        qc = _qc(runs, controls, st.raw.get("results_status"))
        return Results(self.NAME, order.order_id, "completed" if st.state == "completed" else st.state, runs, qc, files, executed,
                       self.is_fixture, self.label, a)


def _num(v):
    return None if v is None else float(v)


def _run(kind: str, s: dict) -> dict:
    """One sequence's readout as a Knos run. A run is ok when the lab got a call (binding true/false, or a Tm);
    unknown or in-progress is a run that did not finish, with its reason."""
    rid = s.get("sequence") or s.get("sequence_name") or s.get("sequence_id")
    if kind == "thermostability":
        tm = _num(s.get("tm"))
        return {"id": rid, "ok": tm is not None, "why": None if tm is not None else "no melting temperature",
                "measurements": {"tm_c": tm}}
    binding = s.get("binding")
    ok = binding in ("true", "false")
    kd = _num(s.get("kd_mean"))
    m = {"binding": binding == "true" if ok else None, "binding_strength": s.get("binding_strength"), "expression": s.get("expression"),
         "fit_quality": s.get("fit_quality"), "kd_nm": None if kd is None else kd * M_TO_NM, "kon": _num(s.get("kon_mean")),
         "koff": _num(s.get("koff_mean")), "replicates": len(s.get("replicates") or [])}
    return {"id": rid, "ok": ok, "why": None if ok else f"binding call {binding!r}", "measurements": m}


def _qc(runs: list[dict], controls: set, results_status) -> dict:
    """Knos's QC rule on Adaptyv's results (Knos's, not Adaptyv's): every positive control bound with a fit that is not
    poor, and the results are complete (results_status "all")."""
    ctl = [r for r in runs if r["id"] in controls]
    bound = [r for r in ctl if r["measurements"].get("binding") is True and r["measurements"].get("fit_quality") != "poor"]
    why = []
    if not ctl:
        why.append("no positive control in the results")
    elif len(bound) != len(ctl):
        why.append("a positive control did not bind (or its fit was poor)")
    if results_status not in ("all", None):
        why.append(f"results_status is {results_status!r}, not all")
    kd = [r["measurements"]["kd_nm"] for r in bound if r["measurements"].get("kd_nm") is not None]
    return {"passed": not why, "why": "; ".join(why) or None, "controls": sorted(controls), "controls_bound": len(bound),
            "positive_control_kd_nm": min(kd) if kd else None, "results_status": results_status, "rule": "knos"}
