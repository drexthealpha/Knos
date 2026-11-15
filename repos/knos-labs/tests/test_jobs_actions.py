"""The Solana Actions (Blink) endpoint over real HTTP, against the escrow in the Solana runtime: a wallet's view of
posting a job and accepting the work, with the transaction checked before it is signed."""

from __future__ import annotations

import base64
import json
import threading
import urllib.error
import urllib.request

import pytest

pytest.importorskip("solders.litesvm")

from solders.transaction import VersionedTransaction  # noqa: E402

from knos.jobs import market  # noqa: E402
from knos.jobs.actions import Actions, serve  # noqa: E402
from _jobharness import LocalLedger  # noqa: E402
from _jobharness import Escrow  # noqa: E402
from knos.jobs.relay import DirRelay  # noqa: E402

USDC = 1_000_000


@pytest.fixture
def site(tmp_path):
    env = Escrow()
    ledger, relay = LocalLedger(env), DirRelay(tmp_path / "relay")
    srv = serve(Actions(ledger, relay, "devnet", cap_units=500 * USDC), port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield env, ledger, relay, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _http(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), json.loads(e.read())


def _sign_and_send(env, payload, signer):
    tx = VersionedTransaction.from_bytes(base64.b64decode(payload["transaction"]))
    msg = tx.message
    assert msg.header.num_required_signatures == 1 and msg.account_keys[0] == signer.pubkey()   # only the wallet signs
    r = env.svm.send_transaction(VersionedTransaction(msg, [signer]))
    env.svm.expire_blockhash()
    return type(r).__name__ == "TransactionMetadata"


def test_a_wallet_posts_a_job_and_accepts_the_work(site):
    env, ledger, relay, url = site
    status, headers, rules = _http(url + "/actions.json")
    assert status == 200 and rules["rules"][0]["apiPath"] == "/api/jobs/**"
    assert headers["Access-Control-Allow-Origin"] == "*" and headers["X-Blockchain-Ids"].startswith("solana:")
    assert headers["X-Action-Version"]

    _, _, card = _http(url + "/api/jobs/post")
    assert card["type"] == "action" and card["icon"].startswith("http") and card["title"] and card["description"]
    act = card["links"]["actions"][0]
    assert act["type"] == "transaction" and {p["name"] for p in act["parameters"]} == {"task", "price"}

    buyer, buyer_tok = env.party(10 * USDC)
    _, _, got = _http(url + "/api/jobs/post?task=Write%20a%20haiku%20about%20escrow&price=2", {"account": str(buyer.pubkey())})
    assert got["type"] == "transaction" and "2 USDC" in got["message"]
    assert _sign_and_send(env, got, buyer)
    assert env.balance(buyer_tok) == 8 * USDC and env.balance(env.vault) == 2 * USDC

    jid_hex = got["message"].split()[1].rstrip(":")
    env.known_jobs.extend(bytes.fromhex(b.job_id) for b in
                          (market.Brief.decode((relay.root / "briefs" / f.name).read_bytes())
                           for f in (relay.root / "briefs").iterdir()))
    (j, brief), = market.open_jobs(ledger, relay)
    assert brief.task == "Write a haiku about escrow" and brief.job_id.startswith(jid_hex)
    jid = bytes.fromhex(brief.job_id)
    worker, worker_tok = env.party()
    market.claim(ledger, worker, jid)

    _, _, early = _http(url + f"/api/jobs/{brief.job_id}/review")
    assert early.get("disabled") is True
    market.deliver(ledger, relay, worker, jid, buyer.pubkey(), b"Funds wait in trust")
    _, _, review = _http(url + f"/api/jobs/{brief.job_id}/review")
    assert [a["label"] for a in review["links"]["actions"]] == ["Accept and pay", "Reject"]

    stranger, _ = env.party()
    code, _, refused = _http(url + f"/api/jobs/{brief.job_id}/accept", {"account": str(stranger.pubkey())})
    assert code == 400 and "buyer" in refused["message"]
    _, _, pay = _http(url + f"/api/jobs/{brief.job_id}/accept", {"account": str(buyer.pubkey())})
    assert _sign_and_send(env, pay, buyer)
    assert env.balance(worker_tok) == 1_900_000 and env.balance(env.fee_token) == 100_000


@pytest.mark.parametrize("query,why", [("task=x&price=600", "capped"), ("task=x&price=-1", "more than zero"),
                                       ("task=x&price=0.5", "minimum job"),
                                       ("task=&price=1", "Describe"), ("task=x&price=abc", "number")])
def test_bad_posts_are_refused_before_any_transaction(site, query, why):
    env, _, _, url = site
    buyer, _ = env.party(10 * USDC)
    code, _, got = _http(url + "/api/jobs/post?" + query, {"account": str(buyer.pubkey())})
    assert code == 400 and why in got["message"] and "transaction" not in got
    code, _, got = _http(url + "/api/jobs/post?task=x&price=1", {"account": "not-a-key"})
    assert code == 400


def test_the_static_actions_json_matches_the_server():
    from pathlib import Path
    static = json.loads((Path(__file__).resolve().parents[1] / "actions" / "actions.json").read_text(encoding="utf-8"))
    assert static == Actions(None, None).rules()
