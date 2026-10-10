"""The round `guardian`: the guardian multisig approves, at the public knos_oidc, a signing key an issuer published and
the rotate run registered (scripts/governance.mjs `guardian approve`).

    python scripts/exercise_public.py run --only guardian --rpc URL --keys DIR

Only a key that waits for it is approved: one GitHub or GitLab publishes now that knos_oidc holds registered and ready,
and that is neither a genesis key nor approved. When none waits the round ends `cannot` and says why. It never
revokes a live key: a revocation is for ever. The member keys: scripts/exercise_rounds/_guardian.py. Nothing to
simulate: the guardian is a Squads vault. `xp` is scripts/exercise_public.py, put here by its loader.
"""
from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable

ROUND = {"name": "guardian", "needs": ("knos_oidc", "public"), "caps": ("key_guardian",), "phase": "any"}
ISSUERS = (0, 1)            # GitHub, GitLab: the issuers governance.mjs approves keys of


def _xp() -> Any:
    return globals()["xp"]


def common() -> Any:
    """scripts/exercise_rounds/_guardian.py, loaded once."""
    name = "knos_exercise_guardian_common"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name("_guardian.py"))
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return sys.modules[name]


def published(issuer: int) -> list[int]:
    """The RSA moduli an issuer publishes now (its JWKS, fetched)."""
    from knos.settle import relay as first_relay
    return [int.from_bytes(base64.urlsafe_b64decode(k["n"] + "=" * (-len(k["n"]) % 4)), "big")
            for k in first_relay.fetch_jwks(issuer).get("keys", []) if k.get("kty") == "RSA" and k.get("n")]


PUBLISHED: Callable[[int], list[int]] = published      # a test gives the moduli in its place


def waiting(w: Any) -> list[tuple[int, int]]:
    """(issuer, modulus) of every published key the public knos_oidc holds registered and ready, and not approved,
    revoked or genesis: what the guardian may approve."""
    x = _xp()
    out = []
    for issuer in ISSUERS:
        for n in PUBLISHED(issuer):
            k = x.oidc.read_key(w.account(x.oidc.key_pda(issuer, n)))
            if k is not None and k.state == 1 and not (k.approved or k.revoked or k.genesis):
                out.append((issuer, n))
    return out


def run(book, st: dict) -> None:
    """The guardian multisig approves a signing key an issuer published and the rotate run registered."""
    from knos.settle import oidc as first
    x, w = _xp(), book.w
    if "approved" in st:
        return
    common().keys(x, w)
    todo = waiting(w)
    if not todo:
        raise x.Cannot("no signing key waits for the guardian at the public knos_oidc: every key GitHub and GitLab publish is a genesis key or "
                       "approved. An approval happens only after an issuer publishes a new key and the rotate run registers it; revoking a live "
                       "key to exercise the guardian would end it for ever")
    issuer, n = todo[0]
    h = first.key_hash(n).hex()
    at = x.oidc.key_pda(issuer, n)
    said = common().govern(x, w, ["guardian", "approve", str(issuer), h])
    k = x.oidc.read_key(w.account(at))
    x._check(k is not None and k.approved and not k.revoked, f"key {h} is not approved on chain after the guardian's proposal: {said.strip()[-200:]}")
    sig = next(iter(w.ledger.history(at, 5)), None)
    x._on_chain(w, sig, ("knos_oidc",), (str(at),))
    st["approved"] = {"issuer": issuer, "key": h, "account": str(at), "signature": sig}
    book.tx(st, f"the guardian multisig approves key {h[:12]}... of issuer {issuer}", str(sig), "knos_oidc")
    book.done(st, "key_guardian", "knos_oidc", str(sig),
              [f"the key account {at} reads approved, and not revoked, after the guardian's proposal executed",
               "the proposal carried knos_oidc's Approve and nothing else; the guardian has no instruction that moves money"])
