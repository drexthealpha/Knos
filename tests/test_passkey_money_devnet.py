"""The passkey money flows on DEVNET, end to end, through the web app's own code (knos_wanted.wallets): opt-in, it
sends real devnet transactions. KNOS_DEVNET_E2E=1 and KNOS_E2E_RELAYER (a devnet relayer key file with ~0.1 SOL)
switch it on; KNOS_E2E_OUT names a JSON file for every signature. Programs: LazorKit FLb7fy... (the passkey wallet),
knos_pay 0.3.34 test program FaMHCjzy... (the vault). The passkeys are software P-256 authenticators
(tests/test_passkey_chain.py); the relayer pays fees, rents and mints test units, and signs nothing else.

What runs: three passkey wallets (buyer, maker, lender); the faucet; the maker claims; the buyer's passkey pre-orders
(a PANEL order); a lender quotes 90%, the maker's passkey sells the receivable's wallet (TransferOwnership), the
lender's passkey pays the advance; two referees release (PASS) to the receivable's wallet; the lender's passkey
collects. A second pre-order is refunded at once to the buyer's passkey wallet by two FAIL verdicts. The milestone's
evidence page is served to the verifier from memory (the page fetch is the one thing not on the network here)."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

if os.environ.get("KNOS_DEVNET_E2E") != "1":
    pytest.skip("devnet end to end: set KNOS_DEVNET_E2E=1 (sends real devnet transactions)", allow_module_level=True)

from solders.keypair import Keypair  # noqa: E402

from test_passkey_money_app import REPORT, Person, _Page  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "wanted"))
from knos_wanted import escrow, preorder, wallets  # noqa: E402

# read at import: the test harness (tests/conftest.py) clears every KNOS_* variable before each test
ENV = {k: os.environ.get(k) for k in ("KNOS_E2E_RELAYER", "KNOS_E2E_STATE", "KNOS_E2E_OUT")}
RP = "knos.dev"          # the software authenticator's site (tests/test_passkey_chain.py RP_ID); the program pins none


def test_devnet_passkey_preorder_factoring_release_and_refund(monkeypatch, tmp_path):
    import socket

    import conftest
    monkeypatch.setattr(socket.socket, "connect", conftest._real_connect)      # opted in: this test talks to devnet
    relayer = ENV["KNOS_E2E_RELAYER"]
    assert relayer, "KNOS_E2E_RELAYER: the devnet relayer key file (~0.1 SOL)"
    monkeypatch.setenv("KNOS_WANTED_DEVNET_KEYPAIR", relayer)
    state = Path(ENV["KNOS_E2E_STATE"] or tmp_path / "state")
    monkeypatch.setenv("KNOS_WANTED_STATE", str(state))
    monkeypatch.setenv("KNOS_WANTED_RECORD", str(state / "record"))
    refs = state / "referees.json"
    if not refs.exists():
        state.mkdir(parents=True, exist_ok=True)
        refs.write_text(json.dumps([list(bytes(Keypair())) for _ in range(3)]))
    monkeypatch.setenv("KNOS_WANTED_REFEREE_KEYS", str(refs))
    monkeypatch.delenv("KNOS_WANTED_PROGRAM", raising=False)                   # FaMHCjzy..., the 0.3.34 test program
    log: dict = {"cluster": "devnet", "program": str(preorder.program()), "lazorkit": str(wallets._ps().LAZOR_ID), "steps": []}
    out = Path(ENV["KNOS_E2E_OUT"] or tmp_path / "e2e.json")

    def note(what, got):
        sigs = got.get("signatures") or {}
        log["steps"].append({"step": what, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                             "signatures": sigs or {k: v for k, v in got.items() if k in ("signature", "created")}})
        out.write_text(json.dumps(log, indent=1))
        return got

    led = escrow.ledger()
    sf = state / "seed.txt"                       # the same three passkeys when a run is resumed
    if not sf.exists():
        sf.write_text(str(int(time.time())))
    seed = int(sf.read_text())
    buyer, maker, lender = Person(seed, "e2e buyer"), Person(seed + 1, "e2e maker"), Person(seed + 2, "e2e lender")
    for who in (buyer, maker, lender):
        w = wallets.public(led, wallets.holder(who.user), RP)
        log[who.user["label"]] = {"vault": w["vault"], "wallet": w["wallet"]}
        note(f"{who.user['label']}: passkey wallet made", w)
    note("buyer: faucet", wallets.faucet(led, wallets.holder(buyer.user), RP))
    note("lender: faucet", wallets.faucet(led, wallets.holder(lender.user), RP))
    rep = {**REPORT, "hash": f"{seed:064x}"[-64:]}
    wallets.claim_maker(led, maker.user, rep, RP)
    rec = note("buyer: pre-order signed by the buyer's passkey", buyer.approve(led, wallets.prepare_preorder(led, buyer.user, rep, 6, RP)))
    log["order"] = rec["commitment"]
    q = wallets.quote(led, lender.user, rec["commitment"], 9000, RP)
    note("maker: receivable sold to the lender (maker's passkey)", maker.approve(led, wallets.prepare_accept(led, maker.user, rec["commitment"], q["id"])))
    note("lender: advance paid (lender's passkey)", lender.approve(led, wallets.prepare_advance(led, lender.user, rec["commitment"], RP)))
    page = f"<html>milestone proof for {rec['claim_id']}</html>".encode()
    got = note("referees: release to the receivable's wallet", preorder.milestone(rep, rec["commitment"], "https://maker.example/proof", led=led,
                                                                                     opener=lambda req, timeout: _Page(page), resolve=lambda host: None))
    assert got["release"] == "released", got
    col = note("lender: repayment collected (lender's passkey)", lender.approve(led, wallets.prepare_collect(led, lender.user, rec["commitment"], RP)))
    assert col["factoring"]["status"] == "repaid"
    # a second pre-order, refunded at once to the buyer's passkey wallet by two FAIL verdicts
    rec2 = note("buyer: second pre-order (passkey)", buyer.approve(led, wallets.prepare_preorder(led, buyer.user, rep, 5, RP)))
    from knos.ideas import commit as C
    r2 = preorder.load(rec2["commitment"])
    review = state / "fail-review.txt"
    review.write_text("the milestone was not delivered (e2e FAIL verdict)")
    recs = [C.sign(r2["doc"], "stage1", k, led, passed=False, review=review) for k in preorder.referees()[:2]]
    got2 = C.refund(r2["doc"], "stage1", recs, preorder.relayer(), led)
    note("referees: second pre-order refunded to the buyer's passkey wallet", {"signatures": {f"fail_{i}": s["signature"] for i, s in enumerate(got2["sent"], 1)}})
    assert got2["status"] == "refunded", got2
    log["done"] = True
    out.write_text(json.dumps(log, indent=1))
