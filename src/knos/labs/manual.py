"""A lab with no ordering API (ordered by e-mail, a web form or a desktop application): Knos still holds the vault and
gives the two verdicts; a person places the order and brings the files back.

    lab = Manual()                                    (or a named one: chemistry.B12Foundry, Ginkgo Cloud Lab, ...)
    q = lab.quote(spec)                               the price the lab quoted to the buyer (spec.protocol["quoted_usd"])
    o = lab.order(spec, `escrow_ref`)                   the request text for the buyer to send (Knos sends nothing)
    r = lab.deliver(o, files, runs, qc, executed)     the files the lab sent back, hashed; the runs and QC as reported

The verdicts then bind the files' hashes exactly as for a lab with an API. Nothing here contacts the lab.
"""
from __future__ import annotations

from pathlib import Path

from .base import Adapter, LabError, Order, Quote, Results, Spec, Status, sha256_hex


class Manual(Adapter):
    NAME = "manual"
    FIELD = "any"
    CONTACT = "the lab's own ordering channel"
    LIVE_READY = True              # nothing to call: the buyer is the transport

    def __init__(self, mode: str = "fixture", transport=None, key: str | None = None, base: str | None = None):
        if mode not in ("fixture", "live"):
            raise LabError("mode: fixture or live")
        self.mode, self.base, self._key, self.fixtures, self.transport = mode, "", None, None, None
        self.states: dict[str, str] = {}

    @property
    def label(self) -> str:
        return f"manual: ordered through {self.CONTACT}; files brought back by the buyer"

    def quote(self, spec: Spec) -> Quote:
        q = spec.protocol.get("quoted_usd")
        if not isinstance(q, str) or not q.replace(".", "", 1).isdigit():
            raise LabError(f"{self.NAME}: put the price the lab quoted in protocol.quoted_usd (a decimal string)")
        return Quote(self.NAME, q, "USD", spec.protocol.get("turnaround_days"), spec.protocol.get("lab_quote_ref"), None,
                     [{"what": spec.title or "as agreed with the lab"}], ["as agreed with the lab"], self.is_fixture, self.label)

    def order(self, spec: Spec, escrow_ref: str, quote: Quote | None = None) -> Order:
        oid = spec.protocol.get("lab_quote_ref") or "manual-" + spec.hash()[:16]
        text = (f"Order request (send it yourself through {self.CONTACT}):\n"
                f"  work: {spec.title or 'as in the attached protocol'}\n"
                f"  protocol sha256: {sha256_hex(repr(sorted(spec.protocol.items())))}\n"
                f"  payment: held by Knos until the proof passes ({escrow_ref}); released to the lab when the protocol was executed as\n"
                f"  specified and QC passed, whatever the scientific outcome.\n"
                f"  please return: every run's raw files (failed runs included) and the QC record.")
        self.states[oid] = "submitted"
        return Order(self.NAME, oid, escrow_ref, spec.hash(), "submitted", self.is_fixture, self.label, {"request": text})

    def status(self, order: Order) -> Status:
        s = self.states.get(order.order_id, order.state)
        return Status(self.NAME, order.order_id, s, s, self.is_fixture, self.label)

    def deliver(self, order: Order, files: list[Path], runs: list[dict], qc: dict, executed: dict, state: str = "completed") -> Results:
        """What the lab sent back: each file hashed (the verdicts bind the hashes), runs and QC as the lab reported them."""
        hashed = []
        for f in files:
            p = Path(f)
            hashed.append({"name": p.name, "sha256": sha256_hex(p.read_bytes()), "bytes": p.stat().st_size})
        self.states[order.order_id] = state
        return Results(self.NAME, order.order_id, state, runs, qc, hashed, executed, self.is_fixture, self.label)

    def results(self, order: Order) -> Results:
        raise LabError(f"{self.NAME}: a manual lab's results come in with deliver(order, files, runs, qc, executed)")
