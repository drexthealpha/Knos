"""One paid question, from someone on another team."""

from __future__ import annotations

import base64
import json

import pytest

from knos import pay, paths
from knos.memory import Fact, Memory

pytest.importorskip("flask")


def _challenge(response) -> dict:
    header = response.headers.get("PAYMENT-REQUIRED")
    assert header, "no payment challenge"
    return json.loads(base64.b64decode(header + "=="))


@pytest.fixture()
def paid(knos_home, repo, monkeypatch):
    paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.record(
            Fact(
                text="we pinned pnpm because the image ships its own",
                source="session",
                where="Claude Code session aaaa1111 2026-08-20",
                when="2026-08-20",
                path="src/auth.py",
            )
        )
    monkeypatch.setattr(pay, "_paid_to", lambda: "0x" + "11" * 20)
    return pay.build(allowed=["src"]).test_client()


def test_asking_without_paying_gets_a_price_not_an_answer(paid):
    response = paid.post("/ask", json={"question": "why did we pin pnpm"})
    assert response.status_code == 402
    assert b"pnpm" not in response.data


def test_the_price_is_a_penny_of_usdc_on_the_free_network(paid):
    terms = _challenge(paid.post("/ask", json={"question": "anything"}))["accepts"][0]
    assert terms["scheme"] == "exact"
    assert terms["network"] == "eip155:84532"
    assert terms["amount"] == "10000"  # 0.01 USDC, six decimals
    assert terms["extra"]["name"] == "USDC"
    assert terms["payTo"] == "0x" + "11" * 20


def test_a_question_outside_the_share_is_charged_the_same(paid):
    """6.3: no free refusals. The paywall is in front of the answer, so
    finding out that a door is shut costs what knocking costs."""
    inside = paid.post("/ask", json={"question": "why did we pin pnpm"})
    outside = paid.post("/ask", json={"question": "what is in the payroll folder"})
    assert inside.status_code == outside.status_code == 402
    assert _challenge(inside)["accepts"] == _challenge(outside)["accepts"]


def test_a_question_outside_the_share_returns_nothing(paid):
    """And once paid, it is still nothing. Charged, and honest about it."""
    assert pay.answer_for("payroll salary bonuses", allowed=["src"])["answer"] == pay.NOTHING


def test_a_question_inside_the_share_returns_an_answer_with_its_source(paid):
    found = pay.answer_for("why did we pin pnpm", allowed=["src"])
    assert "pnpm" in found["answer"]
    assert found["sources"] and "session" in found["sources"][0]


def test_an_answer_never_carries_a_secret(knos_home, repo):
    paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.record(
            Fact(
                text="the stripe key is sk_live_quokka_9931",
                source="session",
                where="Claude Code session aaaa1111 2026-08-20",
                when="2026-08-20",
                path=".env",
            )
        )
    found = pay.answer_for("stripe key", allowed=["", "src", "docs"])
    assert "sk_live" not in found["answer"]
    assert found["answer"] == pay.NOTHING


# --- the receipt a person can follow -----------------------------------------


def _receipt(tx: str) -> str:
    """A settlement header shaped like the ones the facilitator returns."""
    return base64.b64encode(
        json.dumps(
            {
                "success": True,
                "payer": "0xEca35a0C0585E19EAa9Bfc5AF9751D2Ca7CC48C1",
                "transaction": tx,
                "network": "base",
            }
        ).encode()
    ).decode()


def test_a_receipt_carries_the_whole_transaction_hash():
    """The bug this pins: the header used to be stored cut to 160 characters.

    Truncated base64 still decodes. It decodes to a *shorter* hash, which
    looks exactly like a hash, sits in the store reading as evidence, and
    resolves to nothing on a block explorer. A receipt nobody can follow is
    worse than no receipt, so the hash is parsed here rather than kept as an
    opaque blob for something downstream to slice.
    """
    from knos.buy402 import _settlement

    full = "0x" + "ab" * 32
    assert len(full) == 66

    got = _settlement(_receipt(full))
    assert got["tx"] == full
    assert len(got["tx"]) == 66
    assert got["payer"].startswith("0x")

    # The old failure, stated as the test that would have caught it.
    cut = _settlement(_receipt(full)[:160])
    assert cut["tx"] != full


def test_an_unreadable_receipt_is_reported_as_missing_not_guessed():
    """A payment that settled with a receipt we cannot open is still a
    payment. Report it without a hash rather than inventing one, and never
    raise: the caller is a bot answering a person."""
    from knos.buy402 import _settlement

    for junk in ("", "not base64 at all!!", base64.b64encode(b"[]").decode()):
        assert _settlement(junk) == {"tx": "", "payer": "", "network": ""}


def test_padding_the_facilitator_stripped_is_not_a_decode_failure():
    from knos.buy402 import _settlement

    full = "0x" + "cd" * 32
    assert _settlement(_receipt(full).rstrip("="))["tx"] == full
