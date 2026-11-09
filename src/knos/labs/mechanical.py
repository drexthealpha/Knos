"""Mechanical parts: Xometry, as a stub.

Xometry's Developer API (https://developer.xometry.com/llms.txt; api.developer.xometry.com, header X-API-Key, 2 reads/s
plus 2 writes/s per partner) is a SUPPLIER / manufacturing-partner API: jobs, milestones and offers "available only to
partners with Approved or PIP status", and webhooks. It is not a buyer's ordering API (CAPABILITIES-GAP.md, 2f,
resolved 14 Oct 2026; re-read 14 Oct: no quote or order-creation endpoint). Buyers order through Xometry's CAD
add-ins or enterprise PunchOut. Craftcloud (3D printing) publishes a buyer API (api.craftcloud3d.com/api-docs.json:
price, offer, cart, order, order status) with no declared auth scheme: the next mechanical rail to check. So a Knos buyer orders Xometry parts on its website (knos.labs.manual: Knos holds the vault,
the buyer brings back the inspection report), and the adapter below names what is missing instead of guessing.
"""
from __future__ import annotations

from .base import Adapter, LabError


class Xometry(Adapter):
    NAME = "xometry"
    FIELD = "mechanical"
    KEY_ENV = "XOMETRY_API_KEY"
    BASE = "https://api.developer.xometry.com"
    DOCS = "https://developer.xometry.com/llms.txt"
    LIVE_READY = False

    def __init__(self, mode: str = "fixture", transport=None, key: str | None = None, base: str | None = None):
        self.mode, self.base, self._key, self.fixtures, self.transport = mode, self.BASE, key, None, transport

    def _stub(self, *a, **k):
        raise LabError("xometry: its API serves manufacturing partners, not buyers; order on xometry.com and use "
                       "knos.labs.manual (Knos holds the money until the proof passes and judges the inspection report)")

    quote = order = status = results = _stub
