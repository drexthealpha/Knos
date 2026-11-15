"""Recorded infrastructure proofs: what was run for real outside this server (a kind cluster with the Helm chart, a
self-hosted Keycloak test IdP through SAML Jackson, Odoo and ERPNext imports of the journal export, hledger), with where
it ran, what it returned, and the commands to run it yourself. The record (data/proofs.record, JSON; not *.json: apps/wanted keeps .json files only for its two data files) is signed
with cosign (proofs.record.sigstore, a Sigstore bundle; key proofs.cosign.pub); GET /api/proofs serves it, the Teams page shows it."""
from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent / "data"
FILES = {"/api/proofs": ("proofs.record", "application/json"),
         "/api/proofs/signature": ("proofs.record.sigstore", "application/json"),
         "/api/proofs/cosign.pub": ("proofs.cosign.pub", "text/plain; charset=utf-8")}


def record() -> dict:
    f = HERE / "proofs.record"
    if not f.exists():
        return {"proofs": [], "note": "no recorded proofs in this build"}
    return json.loads(f.read_text(encoding="utf-8"))


def raw(path: str) -> tuple[bytes, str] | None:
    name, ctype = FILES.get(path, (None, None))
    if name is None or not (HERE / name).exists():
        return None
    return (HERE / name).read_bytes(), ctype


def proof(key: str) -> dict | None:
    return next((p for p in record().get("proofs", []) if p.get("key") == key), None)
