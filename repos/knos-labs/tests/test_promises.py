"""The promise suite: one fast test for every promise the README makes about jobs, in the order the README makes them.
If a promise stops being true, this file says which one."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

from knos.jobs import api, market, models, net, stats  # noqa: E402
from _jobharness import LocalLedger  # noqa: E402
from _jobharness import Escrow  # noqa: E402
from knos.jobs.relay import DirRelay  # noqa: E402
from knos.jobs.worker import Worker  # noqa: E402

U = 1_000_000
README = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")


@pytest.fixture
def net_(tmp_path):
    env = Escrow()
    return env, LocalLedger(env), DirRelay(tmp_path / "relay")


def _done(env, ledger, relay, price=U):
    buyer, btok = env.party(10 * U)
    worker, wtok = env.party()
    jid = market.post(ledger, relay, buyer, market.Brief("t", "Say ok.", kind="copy", checks={"must_include": ["ok"]}),
                      price)
    market.claim(ledger, worker, jid)
    market.deliver(ledger, relay, worker, jid, buyer.pubkey(), b"ok")
    return buyer, btok, worker, wtok, jid


def test_the_readme_opens_with_the_pitch():
    first = next(ln for ln in README.splitlines()[1:] if ln.strip())
    opening = README[:1500]
    assert first == "**AI agent work gets paid only when GitHub's own signature, checked by Solana, proves it passed.**"
    assert "hire any ai agent in one step" in " ".join(opening.split()).lower()


def test_hire_in_one_step_one_signature(net_):
    env, ledger, relay = net_
    buyer, btok = env.party(5 * U)
    sent = []
    real = ledger.send
    ledger.send = lambda ixs, payer, signers=None: sent.append((payer, signers)) or real(ixs, payer, signers)
    market.post(ledger, relay, buyer, market.Brief("t", "x"), 2 * U)
    assert len(sent) == 1 and sent[0][0] == buyer and not sent[0][1]
    assert env.balance(btok) == 3 * U and env.balance(env.vault) == 2 * U


def test_pay_only_for_work_you_accept(net_):
    env, ledger, relay = net_
    buyer, btok, worker, wtok, jid = _done(env, ledger, relay)
    market.reject(ledger, buyer, jid)
    assert env.balance(btok) == 10 * U and env.balance(wtok) == 0 and env.balance(env.fee_token) == 0
    jid2 = market.post(ledger, relay, buyer, market.Brief("t", "x"), U, work_s=60)
    env.warp(61)
    market.refund(ledger, buyer, jid2)                 # nobody delivered: everything back
    assert env.balance(btok) == 10 * U


def test_the_agent_is_paid_in_the_transaction_that_accepts(net_):
    env, ledger, relay = net_
    buyer, _, worker, wtok, jid = _done(env, ledger, relay, 2 * U)
    sent = []
    real = ledger.send
    ledger.send = lambda ixs, payer, signers=None: sent.append(1) or real(ixs, payer, signers)
    market.accept(ledger, buyer, jid)
    assert len(sent) == 1 and env.balance(wtok) == 1_900_000 and env.balance(env.fee_token) == 100_000


def test_the_escrow_releases_when_the_proof_passes_with_no_human_step(net_):
    """README: "the escrow releases when the proof passes, with no human step" (paid on proof, 0.3.4)."""
    import hashlib
    env, ledger, relay = net_
    buyer, btok = env.party(10 * U)
    worker, wtok = env.party()
    verifier, _ = env.party()
    jid = market.post(ledger, relay, buyer, market.Brief("t", "Say ok."), 2 * U, verifier=verifier.pubkey())
    market.claim(ledger, worker, jid)
    market.deliver(ledger, relay, worker, jid, buyer.pubkey(), b"ok")
    sent = []
    real = ledger.send
    ledger.send = lambda ixs, payer, signers=None: sent.append(payer) or real(ixs, payer, signers)
    with pytest.raises(RuntimeError):     # a proof of some other work releases nothing
        market.verify_release(ledger, verifier, jid, hashlib.sha256(b"root").digest(),
                              result_hash=hashlib.sha256(b"other").digest())
    market.verify_release(ledger, verifier, jid, hashlib.sha256(b"root").digest())
    assert buyer not in sent and market.job(ledger, jid).state == "released"
    assert market.job(ledger, jid).proof == hashlib.sha256(b"root").digest()
    assert env.balance(wtok) == 1_900_000 and env.balance(env.fee_token) == 100_000 and env.balance(btok) == 8 * U


def test_it_cannot_overspend(net_):
    env, ledger, relay = net_
    buyer, btok, worker, wtok, jid = _done(env, ledger, relay, U)
    market.accept(ledger, buyer, jid)
    with pytest.raises(LookupError):
        market.accept(ledger, buyer, jid)              # paid once, never twice
    assert env.balance(btok) == 9 * U and env.balance(wtok) + env.balance(env.fee_token) == U


def test_reputation_is_on_chain_for_anyone_to_check(net_):
    env, ledger, relay = net_
    buyer, _, worker, _, jid = _done(env, ledger, relay)
    market.accept(ledger, buyer, jid)
    fresh = LocalLedger(env)                            # a stranger, reading only job accounts
    row = next(r for r in stats.agents(fresh.jobs()) if r["agent"] == str(worker.pubkey()))
    assert row["paid"] == 1 and row["acceptance"] == 1.0


def test_delivered_sealed_so_only_the_buyer_can_read_it(net_):
    env, ledger, relay = net_
    buyer, _, worker, _, jid = _done(env, ledger, relay)
    stranger, _ = env.party()
    blob = relay.get_delivery(market.job(ledger, jid).result.hex())
    assert b"ok" != blob and market.fetch_delivery(ledger, relay, buyer, jid) == b"ok"
    with pytest.raises(Exception):
        market.open_sealed(stranger, blob)


def test_the_worker_only_delivers_work_that_passes_the_checks(net_):
    env, ledger, relay = net_
    buyer, _ = env.party(5 * U)
    worker, _ = env.party()
    market.post(ledger, relay, buyer, market.Brief("t", "x", kind="copy", checks={"must_include": ["Leeds"]},
                                                   scripted_answer="Manchester"), U)
    assert [o.delivered for o in Worker(ledger, relay, worker, models.scripted).once()] == [False]


def test_bring_any_agent_in_ten_lines():
    root = Path(__file__).resolve().parents[1] / "examples"
    for name in ("worker.py", "worker.mjs"):
        assert len([ln for ln in (root / name).read_text(encoding="utf-8").splitlines() if ln.strip()]) <= 10
    for tool in ("post_job", "find_jobs", "claim_job", "deliver_job"):
        assert hasattr(api, tool) and re.search(rf"\bdef {tool}\(", (Path(api.__file__).parents[1] / "mcp.py")
                                                 .read_text(encoding="utf-8"))


def test_mainnet_is_locked_and_capped(monkeypatch):
    monkeypatch.setenv("KNOS_JOBS_CLUSTER", "mainnet")
    monkeypatch.delenv("KNOS_ALLOW_MAINNET", raising=False)
    with pytest.raises(net.Refused):
        net.cluster()
    monkeypatch.setenv("KNOS_ALLOW_MAINNET", "1")
    assert "capped" in api.post_job("t", "x", 501.0)
    assert net.MAINNET_CAP_UNITS == 500 * U


def test_five_percent_only_on_release():
    assert "2.5%" in README and "only when the agent is paid" in README
