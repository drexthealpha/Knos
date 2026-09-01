"""One paid question, from someone on another team.

`knos share` covers people you know. This covers people you do not: they pay
a penny, they ask, they get whatever knos would have told a teammate with the
same access.

The payment rail is the official x402 middleware. There is nothing here that
verifies, settles, or talks to a facilitator; that is all the library's, and
none of it is reimplemented.

A question outside what was shared is answered honestly and still charged.
Finding out that a door is shut is worth what it costs to knock, and free
refusals are how you get probed all afternoon.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import answer, paths, private
from .memory import Memory

PRICE = os.environ.get("KNOS_PRICE", "$0.01")
# Base Sepolia, named the way the facilitator names it.
NETWORK = os.environ.get("KNOS_PAY_NETWORK", "eip155:84532")
FACILITATOR = os.environ.get("KNOS_FACILITATOR", "https://x402.org/facilitator")

NOTHING = "Nothing known about that."
NOT_POINTED = "This machine has not read a repo yet."


def _paid_to() -> str:
    """Where the pennies go. The key knos made, nothing else."""
    from . import team

    return team.identity().address


def answer_for(question: str, allowed: list[str]) -> dict[str, Any]:
    """What a paying stranger gets: the same passages, the same sources."""
    repo = paths.current_repo()
    if repo is None:
        return {"answer": NOT_POINTED, "sources": []}

    with Memory(repo) as mem:
        found = answer.ask(
            repo,
            mem,
            question,
            identity=private.GUEST,
            allowed=allowed,
            limit=6,
        )
    if not found:
        # Charged all the same. See the note at the top of this file.
        return {"answer": NOTHING, "sources": []}
    return {
        "answer": "\n\n".join(p.text.strip() for p in found),
        "sources": [p.where for p in found],
    }


def build(allowed: list[str] | None = None) -> Any:
    """A Flask app with one paid route, wrapped by the x402 middleware."""
    from flask import Flask, jsonify, request
    from x402.http.facilitator_client import (
        FacilitatorConfig,
        HTTPFacilitatorClientSync,
    )
    from x402.http.middleware.flask import payment_middleware_from_config
    from x402.http.types import PaymentOption, RouteConfig
    from x402.mechanisms.evm.exact import ExactEvmServerScheme

    app = Flask("knos")
    shared = list(allowed or [])

    @app.post("/ask")
    def ask_route() -> Any:
        question = str((request.get_json(silent=True) or {}).get("question", "")).strip()
        return jsonify(answer_for(question, shared))

    payment_middleware_from_config(
        app,
        routes={
            "POST /ask": RouteConfig(
                accepts=PaymentOption(
                    scheme="exact",
                    pay_to=_paid_to(),
                    price=PRICE,
                    network=NETWORK,
                ),
                description="One question, answered from this machine's memory.",
                mime_type="application/json",
            )
        },
        facilitator_client=HTTPFacilitatorClientSync(FacilitatorConfig(url=FACILITATOR)),
        schemes=[{"network": NETWORK, "server": ExactEvmServerScheme()}],
    )
    return app


def serve(allowed: list[str] | None = None, port: int = 4021) -> None:
    """Run it, for as long as the person who started it leaves it running."""
    build(allowed).run(port=port)
