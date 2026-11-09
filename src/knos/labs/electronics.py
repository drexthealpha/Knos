"""Electronics: PCBWay's partner API (fabrication) + a sealed bench test of the boards (the science).

Read 14 Oct 2026 from PCBWay's own pages: https://api-partner.pcbway.com/Help (one page per endpoint), its API
example page, and "PCBWay API for Partners.pdf" (the workflow):
  base     https://api-partner.pcbway.com ("sandbox url" in PCBWay's own example code)
  auth     header `api-key: <your apikey>`; Knos reads it from $PCBWAY_API_KEY (a PARTNER key: the API is "for our
           distributors or partners")
  quote    POST /api/Pcb/PcbQuotation {Length, Width, Layers, Qty, Thickness, Material, FR4Tg, DesignInPanel, BoardType,
           MinTrackSpacing, MinHoleSize, SolderMask, Silkscreen, SilkSides, Goldfingers, SurfaceFinish, ViaProcess,
           FinishedCopper, ...} -> {priceList: [{BuildDays, BuildText, Express, Price, Standard}], Shipping: {ShipCost,
           ShipDays, Weight}, Status "ok"|"error", ErrorText, Code}
  order    POST /api/Pcb/PlaceOrder (the same parameters + PcbFileUrl or DataZipFile, PcbFileName, BuildDays, PONumber,
           Note) -> {OrderNo, DeliveryDate, Price, Status}   ("Add to Cart": nothing is paid yet)
           POST /api/Pcb/ConfirmOrder {OrderNo, PayType, ShipType, Country, ...} pays: from the partner's account
           balance (billed to the partner monthly) or on PCBWay's web page (PCBWayPayUrl)
  details  POST /api/Pcb/CheckOrderDetails {OrderNo} -> {PcbModel: {Layers, Thickness, Material, Qty, ..., IsPaid,
           Price, DeliveryDate, AuditResult}}
  status   POST /api/Pcb/QueryOrderProcess {OrderNo} -> {AllProcess: [names], List: [{Name, Time}] completed so far}
PCBWay bills in its own way (account balance or web page); it has no x402. Knos pays the partner account's monthly
bill from vault, or, in this repository's devnet demo, a lab stand-in that bills over x402 on Solana devnet.

The LAB verdict holds PCBWay to the fabrication: the board parameters ordered = the ones in CheckOrderDetails, every
process done, and the QC processes named in the spec (e.g. the electrical test) among them. The OUTCOME verdict holds
the BOARDS to the researcher's claim through a sealed bench test (each board measured by a referee's re-run): a board
that fails its spec is the science failing, and PCBWay is still paid.

Fixture mode replays fixtures/pcbway.json: PCBWay's documented response shapes with made-up values (labelled).
JLCPCB (api.jlcpcb.com) also has a documented ordering API, open by application: a stub until a key exists.
"""
from __future__ import annotations

from dataclasses import replace

from .base import Adapter, LabError, Order, Quote, Results, Spec, Status, canonical, sha256_hex

BOARD = ("Length", "Width", "Layers", "Qty", "Thickness", "Material", "SolderMask", "SurfaceFinish", "MinTrackSpacing", "MinHoleSize")
LAYERS = (1, 2, 4, 6, 8, 10, 12, 14)
QTY = (5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 125, 150, 200, 250, 300, 350, 400, 450, 500)


class PCBWay(Adapter):
    NAME = "pcbway"
    FIELD = "electronics"
    KEY_ENV = "PCBWAY_API_KEY"
    BASE = "https://api-partner.pcbway.com"
    DOCS = "https://api-partner.pcbway.com/Help"
    LIVE_READY = True

    def auth_headers(self) -> dict:
        return {"api-key": self.key()}

    @staticmethod
    def board(spec: Spec) -> dict:
        p = dict(spec.protocol)
        missing = [k for k in ("Length", "Width", "Layers", "Qty", "Thickness", "Material", "DesignInPanel", "BoardType") if k not in p]
        if missing:
            raise LabError(f"PCBWay requires {', '.join(missing)}")
        if p["Layers"] not in LAYERS:
            raise LabError(f"Layers: one of {LAYERS}")
        if p["Qty"] not in QTY and p["Qty"] < 500:
            raise LabError("Qty: one of PCBWay's quantities (5, 10, 15, 20, 25, 30, 40, 50, 75, 100, ...)")
        return p

    def _ok(self, a: dict, what: str) -> dict:
        if str(a.get("Status", "")).lower() != "ok":
            raise LabError(f"pcbway refused {what}: {a.get('ErrorText') or a.get('Code')}")
        return a

    def quote(self, spec: Spec) -> Quote:
        p = self.board(spec)
        body = {k: v for k, v in p.items() if k not in ("PcbFileUrl", "PcbFileName", "DataZipFile")}
        _s, a, _h = self._call("POST", "/api/Pcb/PcbQuotation", body)
        self._ok(a, "the quote")
        prices = a.get("priceList") or []
        std = next((x for x in prices if x.get("Standard")), prices[0] if prices else None)
        if std is None:
            raise LabError("pcbway returned no price")
        ship = a.get("Shipping") or {}
        total = round(float(std["Price"]) + float(ship.get("ShipCost") or 0), 2)
        return Quote(self.NAME, f"{total:.2f}", "USD", std.get("BuildDays"), None, None,
                     [{"what": "boards", "usd": std["Price"], "build_days": std.get("BuildDays")}, {"what": "shipping", "usd": ship.get("ShipCost"), "days": ship.get("ShipDays")}],
                     ["partner account balance (billed monthly)", "PCBWay web page"], self.is_fixture, self.label, a)

    def order(self, spec: Spec, escrow_ref: str, quote: Quote | None = None) -> Order:
        p = self.board(spec)
        if not (p.get("PcbFileUrl") or p.get("DataZipFile")) or not p.get("PcbFileName"):
            raise LabError("PlaceOrder needs the Gerber files: PcbFileUrl (or DataZipFile) and PcbFileName")
        body = {**p, "BuildDays": p.get("BuildDays") or (quote.turnaround_days if quote else None), "PONumber": escrow_ref[:50],
                "Note": "paid from money Knos holds until the LAB verdict"}
        _s, a, _h = self._call("POST", "/api/Pcb/PlaceOrder", body, spends=True)
        self._ok(a, "the order")
        return Order(self.NAME, a["OrderNo"], escrow_ref, spec.hash(), "submitted", self.is_fixture, self.label, a)

    def status(self, order: Order) -> Status:
        _s, a, _h = self._call("POST", "/api/Pcb/QueryOrderProcess", {"OrderNo": order.order_id})
        self._ok(a, "the fabrication status")
        done = [x.get("Name") for x in a.get("List") or []]
        allp = a.get("AllProcess") or []
        state = "completed" if allp and all(x in done for x in allp) else ("in_progress" if done else "submitted")
        return Status(self.NAME, order.order_id, state, f"{len(done)}/{len(allp)} processes", self.is_fixture, self.label, a)

    def results(self, order: Order) -> Results:
        st = self.status(order)
        _s, a, _h = self._call("POST", "/api/Pcb/CheckOrderDetails", {"OrderNo": order.order_id})
        self._ok(a, "the order details")
        m = a.get("PcbModel") or {}
        executed = {k: m.get(k) for k in BOARD}
        done = [x.get("Name") for x in st.raw.get("List") or []]
        qc = {"passed": st.state == "completed" and bool(m.get("IsPaid")), "why": None if st.state == "completed" else "fabrication not finished",
              "processes_done": done, "processes_all": st.raw.get("AllProcess"), "audit": m.get("AuditResult"), "rule": "knos"}
        return Results(self.NAME, order.order_id, st.state, [], qc,
                       [{"name": "fabrication.json", "sha256": sha256_hex(canonical({"status": st.raw, "details": a}))}],
                       executed, self.is_fixture, self.label, {"status": st.raw, "details": a})

    @staticmethod
    def with_bench(r: Results, bench: dict) -> Results:
        """The boards' sealed bench test (a referee's re-run measures each board): one run per board, and the bench
        file's hash among the evidence."""
        runs = [{"id": b["board"], "ok": b.get("ok", True), "why": b.get("why"), "measurements": b["measurements"]} for b in bench["boards"]]
        files = [*r.files, {"name": bench["file"], "sha256": bench["sha256"]}]
        return replace(r, runs=runs, files=files)


class JLCPCB(Adapter):
    """Documented ordering API, open by application: a stub until a key exists. Gateway https://open.jlcpcb.com (it
    answered `{"code":400,"message":"The request authorization cannot be empty."}` to an unsigned call, 14 Oct 2026);
    HMAC-SHA256 request signing in `Authorization: JOP appid=...,accesskey=...,nonce=...,timestamp=...,signature=...`
    (api.jlcpcb.com/docs/api-request-signature). The endpoint paths are shown only in the console after approval."""
    NAME = "jlcpcb"
    FIELD = "electronics"
    KEY_ENV = "JLCPCB_APP_KEY"
    BASE = "https://open.jlcpcb.com"
    DOCS = "https://api.jlcpcb.com"
    LIVE_READY = False

    def __init__(self, mode: str = "fixture", transport=None, key: str | None = None, base: str | None = None):
        self.mode, self.base, self._key, self.fixtures, self.transport = mode, self.BASE, key, None, transport

    def _stub(self, *a, **k):
        raise LabError("jlcpcb: a stub. JLCPCB's API is granted on application (api.jlcpcb.com)")

    quote = order = status = results = _stub
