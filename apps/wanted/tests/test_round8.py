"""Round 8: one canonical evidence pin, the regulator flag, and the Buyer view's
crossing list. SYNTHETIC fixtures; no network, no chain."""
import io
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from test_check import IDEA, use_signals

from knos_wanted import agent, escrow, preorder, research, server


# ---- 1. the page's hash and the transaction's pin are one value -----------------------------------------------------
def test_the_displayed_evidence_pin_is_the_signed_one(monkeypatch, tmp_path):
    pytest.importorskip("solders")
    from knos import ideas
    from knos.ideas import commit as C
    claim = ideas.claim("Evidence pin test: one canonical hash for the page and the chain", field_name=preorder.FIELD, kind="person")
    order = "P" * 43
    preorder._save({"order": order, "report": "b" * 64, "status": "locked", "claim_id": claim["id"], "units": 5,
                    "buyer": "demo buyer, test money", "maker_wallet": "4dFAUoXNDbmPCJ1CPCFyaJqLW5WWY3i2TE3VKEdSbC31",
                    "deadline_days": 30, "signatures": {},
                    "doc": {"claim": claim, "panel": {"keys": [], "label": "UNLISTED PANEL"}, "program": "F" * 43, "mint": "M" * 43}})
    body = f"<p>{claim['id']}</p>".encode()
    monkeypatch.setattr(preorder, "_need", lambda: None)
    monkeypatch.setattr(escrow, "ledger", lambda: type("L", (), {"url": "devnet", "account": lambda self, a: b"open"})())
    signed = []

    def sign(doc, stage, r, led, passed=None, review=None):
        ev = C.review_evidence(doc, "referee_pass", passed, review)       # what knos.ideas.commit.sign really signs
        signed.append(ev["evidence_hash"])
        return {"evidence_hash": ev["evidence_hash"]}
    monkeypatch.setattr(C, "sign", sign)
    monkeypatch.setattr(C, "release", lambda doc, stage, recs, relayer, led: {"status": "released", "sent": [{"signature": "s1"}, {"signature": "s2"}]})
    monkeypatch.setattr(preorder, "referees", lambda: [object()] * 3)
    monkeypatch.setattr(preorder, "relayer", lambda: None)
    pins = {}
    monkeypatch.setattr(preorder.company, "record_release", lambda rep, o, sigs, pin: pins.setdefault("pin", pin) or {"recorded": True})
    rep = {"hash": "b" * 64, "decision": {"verdict": "OPEN", "reserve_units": 0}}
    got = preorder.milestone(rep, order, "https://maker.example/p", opener=lambda req, timeout=None: io.BytesIO(body), resolve=lambda h: None)
    v = got["verified"]
    assert v["chain_pin"] == signed[0] == signed[1] == pins["pin"], "the page's pin must be the one the verdicts carry"
    assert v["chain_pin"] != v["sha256"] and "review_evidence" in v["chain_pin_of"] and "release transaction" in v["chain_pin_of"]
    # the canonical function is knos.ideas.commit.review_evidence itself: the same evidence gives the same pin
    review = tmp_path / "e"
    review.write_bytes(body)
    assert preorder.evidence_pin({"claim": claim}, review)["evidence_hash"] == v["chain_pin"]


def test_a_changed_evidence_page_changes_the_pin(tmp_path):
    pytest.importorskip("solders")
    from knos import ideas
    claim = ideas.claim("Evidence pin test: a changed page changes the pin", field_name=preorder.FIELD, kind="person")
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"one")
    b.write_bytes(b"two")
    assert preorder.evidence_pin({"claim": claim}, a)["evidence_hash"] != preorder.evidence_pin({"claim": claim}, b)["evidence_hash"]


# ---- 3. the regulator behind the "no product yet" source ------------------------------------------------------------
def test_the_fda_source_sets_the_regulation_flag(monkeypatch):
    row = research.nobel_for("10.1038/nature16521")
    assert research.regulator_of(row) == "FDA (US)"                       # matched on the fda.gov source URL
    assert research.regulator_of({"url": "https://celiac.org/x", "said": "the only treatment is the gluten-free diet"}) is None
    assert research.regulator_of({"url": "https://example.org", "said": "The EMA has approved no such product."}) == "EMA (EU)"
    card = {"field": "Engineering", "topic": "Wearables", "topics": [], "product": "a fitness watch", "year": 2016,
            "cited_by_count": 5051, "nobel": None, "regulator": "FDA (US)",
            "no_product_evidence": {"url": row["url"], "said": row["said"]}}
    walls = research.why_never_crossed(card, {"hash": "a" * 64, "matches": [{"name": "Sweat", "popularity": 0.9}]})
    slow = next(w for w in walls if w["wall"] == "slow judges")
    assert slow["flag"] is True and "FDA (US)" in slow["evidence"] and "fda.gov" in slow["evidence"]
    none = research.why_never_crossed({**card, "regulator": None, "product": "a watch"}, {"matches": []})
    assert next(w for w in none if w["wall"] == "slow judges")["flag"] is False


# ---- 4. the Buyer view lists every crossing, newest first ------------------------------------------------------------
def test_the_server_lists_every_crossing_newest_first(monkeypatch):
    st = server.State()
    use_signals(monkeypatch)
    monkeypatch.setattr(research, "research_card", lambda ref, product=None, **k: {
        "hash": "c" * 64, "title": "Synthetic paper", "year": 2016, "cited_by_count": 5000, "retraction": {"retracted": False},
        "nobel": None, "regulator": None, "proven_result": {"quote": "We present a sensor.", "source": None}, "topics": [],
        "product": IDEA, "product_source": "synthetic", "field": "Engineering", "topic": "Wearables", "ids": {}})
    first = agent.start(st, ref="10.0/x", wait=True)
    second = agent.start(st, idea=IDEA, wait=True)
    rows = agent.crossings(st)
    assert [r["id"] for r in rows[:2]] == [second["id"], first["id"]]      # newest first
    assert rows[0]["verdict"] == "OPEN" and rows[0]["report"] and rows[0]["idea"]
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(st))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_address[1]}/api/crossings", timeout=30) as r:
        got = json.loads(r.read())
    httpd.shutdown()
    assert [x["id"] for x in got["crossings"][:2]] == [second["id"], first["id"]]
