"""Both parties sign the final spec: an Ed25519 signature of its hash by each side's Solana wallet.

    message   b"knos-outcome:v1:" + spec hash (64 hex characters)
    file      outcome.signatures.json: {"spec_hash": ..., "signatures": [{"role", "github", "address", "signature"}]}
    comment   the line posted on the order's issue (`comment`), so the hash both signed sits beside the orders

The buyer signs with escrow.funder's wallet, the seller with parties.seller.address's. A signature by any other key,
or of another hash, does not verify (`verify`).
"""
from __future__ import annotations

import json
from pathlib import Path

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature

from .spec import spec_hash

PREFIX = b"knos-outcome:v1:"


def message(h: str) -> bytes:
    return PREFIX + h.encode()


def expected(spec: dict, role: str) -> str:
    return spec["escrow"]["funder"] if role == "buyer" else spec["parties"]["seller"]["address"]


def sign(spec: dict, role: str, wallet: Keypair) -> dict:
    if role not in ("buyer", "seller"):
        raise ValueError("role is buyer or seller")
    if str(wallet.pubkey()) != expected(spec, role):
        raise ValueError(f"the {role} signs with {expected(spec, role)}, the address the spec names; this wallet is {wallet.pubkey()}")
    h = spec_hash(spec)
    return {"role": role, "github": spec["parties"][role]["github"], "address": str(wallet.pubkey()), "signature": str(wallet.sign_message(message(h)))}


def verify(spec: dict, sigs: dict) -> list[str]:
    """Problems with a signatures file; [] when both parties signed this spec's hash with the named wallets."""
    h = spec_hash(spec)
    out = []
    if sigs.get("spec_hash") != h:
        out.append(f"the signatures are of {sigs.get('spec_hash')}, and this spec hashes to {h}")
    roles = {}
    for s in sigs.get("signatures", []):
        try:
            ok = Signature.from_string(s["signature"]).verify(Pubkey.from_string(s["address"]), message(h))
        except (ValueError, KeyError):
            ok = False
        if not ok or s.get("address") != expected(spec, s.get("role", "")):
            out.append(f"the {s.get('role')} signature does not verify for {expected(spec, s.get('role', 'buyer'))}")
        else:
            roles[s["role"]] = True
    for role in ("buyer", "seller"):
        if role not in roles:
            out.append(f"no valid {role} signature")
    return out


def add(path: Path, spec: dict, entry: dict) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"spec_hash": spec_hash(spec), "signatures": []}
    if doc.get("spec_hash") != spec_hash(spec):
        doc = {"spec_hash": spec_hash(spec), "signatures": []}
    doc["signatures"] = [s for s in doc["signatures"] if s.get("role") != entry["role"]] + [entry]
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return doc


def comment(spec: dict, sigs: dict, orders: list[dict] | None = None) -> str:
    """The comment for the order's issue: the hash both parties signed, their signatures, and the orders."""
    lines = [f"Knos outcome spec `{spec_hash(spec)}`" + (" (SYNTHETIC data)" if spec.get("synthetic") else ""),
             "", f"{spec['title']}", ""]
    for s in sigs.get("signatures", []):
        lines.append(f"- {s['role']} @{s['github']} ({s['address']}): `{s['signature']}`")
    for o in orders or []:
        lines.append(f"- tier {o['name']}: order `{o['address']}`, terms `{o['terms_hash']}`, {o['amount'] / 1e6:g} test units")
    lines += ["", f"Check: `knos outcome verify-signatures outcome.yaml` (message: knos-outcome:v1:<hash>)."]
    return "\n".join(lines)
