"""The Record line as a machine-priced API (src/knos/record_api.py, examples/record_api, docs/X402.md "Record"), in the
Solana runtime (LiteSVM), with two stand-in agents: pay, then the JSON. A replayed payment is refused, a call another
wallet signed is refused, the free file stays free, and the escrow pays the server on a signed acceptance or goes back."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _order import REPO, TERMS, USDC, OrderChain, code  # noqa: E402
from _pay2 import WF_REPO, WF_SHA, ChainLedger  # noqa: E402

from knos import fees, record_api, record_page  # noqa: E402
from knos.settle.v2 import pay  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "docs" / "records"
SELLER_ID, ISSUE = 5550123, 4242
PACK = 5 * USDC          # what one order costs: fifty lookups at 0.10


class Memory:
    """A store with the two calls the server uses (knos.proof.history's `state` and `set_state`)."""
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def state(self, key):
        return dict(self.docs.get(key, {}))

    def set_state(self, key, body):
        self.docs[key] = dict(body)


def world(store=None):
    c = OrderChain()
    seller = Keypair.from_seed(bytes([61]) * 32)
    off = record_api.offer(str(seller.pubkey()), SELLER_ID, str(c.usdc), REPO, ISSUE, WF_REPO, WF_SHA, TERMS.decode(), url="https://records.example")
    server = record_api.Server(off, ChainLedger(c), RECORDS, store)
    return c, seller, off, server


def agent(c, seed: int, money: int = 20 * USDC):
    key = Keypair.from_seed(bytes([seed]) * 32)
    c.svm.airdrop(key.pubkey(), 10 ** 9)
    tok = c.token_account(key.pubkey(), c.usdc)
    c.mint_to(c.usdc, tok, money)

    def fund(req, amount=None):
        x = req["extra"]
        ix = pay.fund_order_wallet_ix(key.pubkey(), tok, Pubkey.from_string(req["asset"]), int(x["repoId"]), int(x["issue"]), amount or int(req["amount"]),
                                      x["workflows"]["repository"], x["workflows"]["sha"], x["terms"].encode(), mode=x["mode"],
                                      work_s=req["maxTimeoutSeconds"], seq=x["seq"])
        assert c.send([ix], key), c.err
        return "funded"
    return key, tok, fund


def ask(c, server, key, fund, slug="codex", **kw):
    return record_api.lookup(server.handle, slug, key, fund, max_amount=PACK, mints=(str(c.usdc),), **kw)


def test_the_free_file_stays_free_and_a_lookup_without_payment_is_a_402_that_names_the_order_to_fund():
    c, seller, off, server = world()
    status, _h, body = server.handle("/records/codex.json", {})
    assert status == 200 and body == json.loads((RECORDS / "codex.json").read_text(encoding="utf-8")) and record_page.check(body) is None
    key, _tok, _fund = agent(c, 71)
    status, headers, body = server.handle("/lookup/codex", {"Attested-Payer": str(key.pubkey())})
    req = body["accepts"][0]
    assert status == 402 and record_api.decode(headers["PAYMENT-REQUIRED"]) == body and body["extensions"]["knos-order"]["info"]["proposal"] is True
    assert (req["scheme"], req["amount"], req["extra"]["record"]["price"], req["extra"]["record"]["lookups"]) == ("knos-order", "5000000", "100000", 50)
    assert req["extra"]["order"] == record_api.order_address(off, str(key.pubkey())) and req["extra"]["fee"] == str(fees.rule().order(PACK))
    assert server.handle("/lookup/nobody-here", {})[0] == 404 and server.handle("/lookup/../x", {})[0] == 400      # nothing is charged for nothing
    # the program takes no order under 5.00: one lookup cannot be one order, which is why an order buys fifty
    assert pay.ORDER_MIN_AMOUNT == record_api.PACK * record_api.PRICE == PACK
    key2, tok2, _ = agent(c, 72)
    small = pay.fund_order_wallet_ix(key2.pubkey(), tok2, c.usdc, REPO, ISSUE, record_api.PRICE, WF_REPO, WF_SHA, TERMS)
    assert not c.send([small], key2) and code(c) == 81
    under = pay.fund_order_wallet_ix(key2.pubkey(), tok2, c.usdc, REPO, ISSUE, PACK - 1, WF_REPO, WF_SHA, TERMS)
    assert not c.send([under], key2) and code(c) == 81 and c.balance(tok2) == 20 * USDC


def test_two_agents_pay_then_get_the_json_a_replay_is_refused_and_one_agent_cannot_spend_the_others_order():
    store = Memory()
    c, seller, off, server = world(store)
    a, a_tok, a_fund = agent(c, 71)
    b, b_tok, b_fund = agent(c, 72)
    got = ask(c, server, a, a_fund)
    fee = fees.live(ChainLedger(c)).order(PACK)
    assert got["status"] == 200 and got["body"]["record"]["supplier"] == "codex" and record_page.check(got["body"]["record"]) is None
    assert got["body"]["served"] == {"order": got["order"], "n": 0, "left": 49, "at": c.now(), "record_sha256": got["body"]["record"]["sha256"], "price": "100000"}
    assert c.balance(a_tok) == 20 * USDC - PACK - fee and c.held(Pubkey.from_string(got["order"])) == PACK + fee       # in escrow, not yet the seller's
    # the same payment again, byte for byte, from anyone who saw it: refused
    replay = server.handle("/lookup/codex", {"PAYMENT-SIGNATURE": record_api.encode(got["payment"])})
    assert replay[0] == 402 and "already used" in replay[2]["error"]
    # agent b knows a's order and signs a call on it with its own key: refused; it must fund its own
    stolen = ask(c, server, b, b_fund, order=got["order"], n=1)
    assert stolen["status"] == 402 and "not signed by the wallet that funded the order" in stolen["body"]["error"]
    assert c.balance(b_tok) == 20 * USDC
    # a's signed call for one record is not a call for another
    other = dict(got["payment"], payload=dict(got["payment"]["payload"], n=1))
    assert server.handle("/lookup/devin", {"PAYMENT-SIGNATURE": record_api.encode(other)})[0] == 402
    mine = ask(c, server, b, b_fund, slug="devin")
    assert mine["status"] == 200 and mine["body"]["record"]["supplier"] == "devin" and mine["order"] != got["order"]
    # a spends the rest of its fifty on the order it already funded, and the fifty-first is refused
    for n in range(1, 50):
        assert ask(c, server, a, a_fund, order=got["order"], n=n)["body"]["served"]["left"] == 49 - n
    over = ask(c, server, a, a_fund, order=got["order"], n=50)
    assert over["status"] == 402 and "all are used" in over["body"]["error"]
    assert ask(c, server, a, a_fund, order=got["order"], n=5)["status"] == 402
    # the count is kept in the store: a server started again does not sell a lookup twice
    again = record_api.Server(off, ChainLedger(c), RECORDS, store)
    assert again.used(got["order"]) == 50 and again.handle("/orders/" + mine["order"], {})[2]["used"] == 1
    assert again.handle("/lookup/codex", {"PAYMENT-SIGNATURE": record_api.encode(got["payment"])})[0] == 402
    # the acceptance: the order's pinned judge signs, and the escrow pays the seller the pack whole
    order = Pubkey.from_string(got["order"])
    c.warp(3600)
    assert c.pay(order, [(SELLER_ID, 10_000, seller.pubkey())], pr=12), c.err
    assert c.balance(pay.ata(seller.pubkey(), c.usdc)) == PACK and c.order(order) is None
    gone = server.handle("/lookup/codex", {"PAYMENT-SIGNATURE": record_api.encode(got["payment"])})
    assert gone[0] == 402 and "there is no order" in gone[2]["error"]
    # b's order is never accepted: after the deadline everything goes back to b
    c.warp(off["workSeconds"] + 1)
    assert c.refund(Pubkey.from_string(mine["order"])), c.err
    assert c.balance(b_tok) == 20 * USDC


def test_the_caller_checks_the_402_against_its_own_limits_and_the_server_checks_the_order_it_is_shown():
    c, seller, off, server = world()
    a, a_tok, a_fund = agent(c, 71)
    with pytest.raises(ValueError, match="over this caller's limit"):
        record_api.lookup(server.handle, "codex", a, a_fund, max_amount=PACK - 1, mints=(str(c.usdc),))
    with pytest.raises(ValueError, match="refusing to pay in mint"):
        record_api.lookup(server.handle, "codex", a, a_fund, max_amount=PACK, mints=())
    assert c.balance(a_tok) == 20 * USDC
    # an order for another issue, funded by the caller, is not this server's
    elsewhere = c.fund_wallet(amount=PACK)
    got = ask(c, server, c.funder, a_fund, order=str(elsewhere))
    assert got["status"] == 402 and "another resource" in got["body"]["error"]
    assert server.handle("/lookup/codex", {"PAYMENT-SIGNATURE": "not base64"})[0] == 400      # refused before the chain is read


def test_the_server_answers_on_a_socket():
    import threading
    import urllib.error
    import urllib.request
    c, seller, off, server = world()
    httpd = record_api.serve(server, port=0)
    t = threading.Thread(target=httpd.handle_request)        # one request: the free file reads no chain
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_address[1]}/records/copilot.json", timeout=10) as r:
            assert r.status == 200 and json.loads(r.read().decode("utf-8"))["supplier"] == "copilot"
    finally:
        t.join(10)
        httpd.server_close()


def test_knos_record_serve_is_the_servers_own_command(monkeypatch):
    """`knos record serve <offer file>` hands the offer to knos.record_api.main and does nothing else."""
    typer = pytest.importorskip("typer")
    from typer.testing import CliRunner

    from knos import badge, record_api
    app, got = typer.Typer(), []
    badge.register(app)
    monkeypatch.setattr(record_api, "main", lambda argv=None: got.append(argv) or 0)
    done = CliRunner().invoke(app, ["record", "serve", "offer.json"])
    assert done.exit_code == 0 and got == [["offer.json"]] and done.output == ""


def test_the_paid_answer_is_signed_expires_and_releases_history_only_on_the_suppliers_grant(tmp_path):
    """What the lookup adds to the free file (src/knos/record_answer.py): the operator's signature over the record's
    hash, the time and slot it read the chain and an expiry; a summary; and the supplier's history, field by field,
    only to the wallet the supplier granted."""
    from knos import record_answer as ra
    operator, supplier = Keypair.from_seed(bytes([62]) * 32), Keypair.from_seed(bytes([63]) * 32)
    past = ra.history("codex", times=[{"deliverable": "d", "delivered": 0, "accepted": 900}], as_of="2026-10-01")
    (tmp_path / "codex.history.json").write_text(json.dumps(past), encoding="utf-8")
    c = OrderChain()
    seller = Keypair.from_seed(bytes([61]) * 32)
    off = record_api.offer(str(seller.pubkey()), SELLER_ID, str(c.usdc), REPO, ISSUE, WF_REPO, WF_SHA, TERMS.decode(), url="https://records.example")
    server = record_api.Server(off, ChainLedger(c), RECORDS, key=operator, history=tmp_path, suppliers={"codex": str(supplier.pubkey())}, ttl=600)
    a, _tok, a_fund = agent(c, 71)
    b, _tok, b_fund = agent(c, 72)
    free = server.handle("/records/codex.json", {})[2]
    assert "answer" not in free and "signature" not in free and ra.verify(free, c.now())["state"] == "unsigned"      # the free file: no signature
    got = ask(c, server, a, a_fund)
    ans = got["body"]["answer"]
    assert got["status"] == 200 and got["body"]["record"] == free and ans["key"] == str(operator.pubkey()) and ans["reader"] == str(a.pubkey())
    assert ans["read"]["time"] == c.now() and ans["expires"] == ans["produced"] + 600 and ans["root"]["record_sha256"] == free["sha256"]
    assert ans["read"]["slot"] is None or ans["read"]["slot"] >= 0
    assert ra.verify(got["body"], c.now(), str(operator.pubkey()))["state"] == "fresh" and ra.verify(got["body"], c.now() + 601)["state"] == "stale"
    assert ans["summary"] == ra.summary(free) and ans["summary"]["public"]["failed_at_merge"]["ci95"] == free["public"]["ci95"]
    assert all(h["state"] == "not granted" and "data" not in h for h in ans["history"].values()) and ans["availability"]["uptime"] == "none"
    # the supplier grants a's wallet one field; b shows the same grant and gets nothing; a gets that field and no other
    g = ra.grant(supplier, "codex", str(a.pubkey()), ["time_to_accept"], c.now() - 1, c.now() + 86_400)

    def with_grant(key, fund, order=None, n=0):
        def asks(path, headers):
            return server.handle(path, {**headers, "Record-Grant": record_api.encode(g)})
        return record_api.lookup(asks, "codex", key, fund, max_amount=PACK, mints=(str(c.usdc),), order=order, n=n)
    mine = with_grant(a, a_fund, got["order"], 1)["body"]["answer"]
    assert mine["history"]["time_to_accept"] == {"granted": True, "state": "released", "what": ra.FIELD_WORDS["time_to_accept"], "data": past["fields"]["time_to_accept"]}
    assert mine["history"]["disputes"]["state"] == "not granted" and mine["root"]["history_sha256"] == past["sha256"]
    theirs = with_grant(b, b_fund)
    assert theirs["status"] == 200 and all(h["state"] == "not granted" for h in theirs["body"]["answer"]["history"].values())
    assert theirs["body"]["answer"]["grant"]["refused"] == "the grant names another reader" and "data" not in json.dumps(theirs["body"]["answer"]["history"])
    # a server with no key still answers, and says the answer is unsigned
    plain = record_api.Server(off, ChainLedger(c), RECORDS)
    unsigned = ask(c, plain, a, a_fund, order=got["order"], n=0)
    assert unsigned["status"] == 200 and ra.verify(unsigned["body"], c.now())["state"] == "unsigned"
    assert server.handle("/health", {})[2]["signing"] is True and plain.handle("/health", {})[2]["signing"] is False
