"""The wired verifier: a job names a verifier at post time; `knos verify` re-runs the brief's checks and the buyer's
recalled preferences, commits the evidence to a Merkle root, and pays on pass or refunds on fail."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("solders.litesvm")

from solders.pubkey import Pubkey  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from knos.jobs import market, net as jnet, verify as V  # noqa: E402
from knos.proof import history  # noqa: E402
from _jobharness import Escrow, LocalLedger  # noqa: E402
from knos.jobs.relay import DirRelay  # noqa: E402

USDC = 1_000_000


@pytest.fixture
def chain(tmp_path):
    env = Escrow()
    return env, LocalLedger(env), DirRelay(tmp_path / "relay")


class _NoMemory:
    def __init__(self, *a, **k):
        pass

    def learn_from(self, text):
        return []

    def preferences(self):
        return []


def _wire(monkeypatch, ledger, relay, key):
    from knos.jobs import buyer_memory
    monkeypatch.setattr(jnet, "ledger", lambda: ledger)
    monkeypatch.setattr(jnet, "relay", lambda: relay)
    monkeypatch.setattr(jnet, "key", lambda: key)
    monkeypatch.setattr(jnet, "cluster", lambda: "localnet")
    monkeypatch.setattr(jnet, "remember_job", lambda *a, **k: None)
    monkeypatch.setattr(buyer_memory, "BuyerMemory", _NoMemory)


def _delivered(env, ledger, relay, brief, content: bytes, verifier):
    buyer, _ = env.party(10 * USDC)
    worker, worker_tok = env.party()
    jid = market.post(ledger, relay, buyer, brief, 2 * USDC, verifier=verifier.pubkey())
    market.claim(ledger, worker, jid)
    market.deliver(ledger, relay, worker, jid, verifier.pubkey(), content)   # a copy sealed to the verifier
    return jid, worker_tok


def test_reference_verifier_is_a_real_key():
    assert V.resolve("none") is None and V.resolve(None) is None
    if not V.KNOS_VERIFIER:
        with pytest.raises(ValueError):
            V.resolve("knos")
        pytest.skip("the reference verifier key is not filled in yet")
    assert Pubkey.from_string(V.KNOS_VERIFIER) == V.resolve("knos")


def test_post_verify_names_the_verifier(chain, monkeypatch):
    from knos.cli import app
    env, ledger, relay = chain
    buyer, _ = env.party(10 * USDC)
    custom, _ = env.party()
    _wire(monkeypatch, ledger, relay, buyer)
    ref, _ = env.party()
    monkeypatch.setattr(V, "KNOS_VERIFIER", V.KNOS_VERIFIER or str(ref.pubkey()))
    got = CliRunner().invoke(app, ["jobs", "post", "Ref", "--price", "2", "--verify", "knos", "--yes"])
    assert got.exit_code == 0, got.output
    got = CliRunner().invoke(app, ["jobs", "post", "Mine", "--price", "2", "--verify", str(custom.pubkey()), "--yes"])
    assert got.exit_code == 0, got.output
    named = {j.verifier for j in ledger.jobs()}
    assert named == {Pubkey.from_string(V.KNOS_VERIFIER), custom.pubkey()}


def test_pass_calls_verify_release_and_pays(chain, monkeypatch, tmp_path):
    from knos.cli import app
    env, ledger, relay = chain
    verifier, _ = env.party()
    jid, worker_tok = _delivered(env, ledger, relay, market.Brief("Hi", "say hello", checks={"must_include": ["hello"]}),
                                 b"hello there", verifier)
    called = []
    real = market.verify_release
    monkeypatch.setattr(market, "verify_release", lambda *a, **k: (called.append(a), real(*a, **k)))
    keyfile = tmp_path / "verifier.json"
    keyfile.write_text(json.dumps(list(bytes(verifier))))
    _wire(monkeypatch, ledger, relay, verifier)
    got = CliRunner().invoke(app, ["verify", jid.hex(), "--key", str(keyfile)])
    assert got.exit_code == 0, got.output
    assert "verdict PASS" in got.output and len(called) == 1
    j = market.job(ledger, jid)
    assert j.state == "released" and j.proof == called[0][3]
    assert called[0][3].hex() in got.output and env.balance(worker_tok) == 1_900_000


def test_fail_calls_verify_reject(chain, monkeypatch):
    env, ledger, relay = chain
    verifier, _ = env.party()
    jid, _ = _delivered(env, ledger, relay, market.Brief("Hi", "say hello", checks={"must_include": ["hello"]}),
                        b"goodbye", verifier)
    rejected, released = [], []
    monkeypatch.setattr(market, "verify_reject", lambda *a: rejected.append(a), raising=False)
    monkeypatch.setattr(market, "verify_release", lambda *a, **k: released.append(a))
    v = V.verify_job(ledger, relay, verifier, jid, preferences=[])
    assert not v.ok and v.settled == "rejected" and not released
    assert rejected == [(ledger, verifier, jid, v.root)]
    from solders.signature import Signature
    assert Signature.from_string(v.signature).verify(verifier.pubkey(), v.message())


def test_preference_lint_fails_and_cites_the_line(chain, monkeypatch):
    found = history.lint_preferences(["No emojis please", "British spelling", "no bullet points",
                                      "under 12 words"], "buyer",
                                     "Intro line\nOur color is bold \U0001F600\n- one\nfour five six seven eight")
    said = [str(f) for f in found]
    assert any("line 2" in s and "emoji" in s and "No emojis please" in s for s in said)
    assert any("line 2" in s and "'color'" in s and "colour" in s for s in said)
    assert any("line 3" in s and "'- one'" in s for s in said)
    assert any("line 4" in s and "under 12 words" in s for s in said)
    assert history.lint_preferences(["No emojis please"], "b", "plain text") == []

    env, ledger, relay = chain
    verifier, _ = env.party()
    jid, _ = _delivered(env, ledger, relay, market.Brief("Hi", "say hello", preferences=["no emojis"]),
                        "hello\nhello again \U0001F44B".encode(), verifier)
    rejected = []
    monkeypatch.setattr(market, "verify_reject", lambda *a: rejected.append(a), raising=False)
    monkeypatch.setattr(V, "recalled_preferences", lambda brief, buyer: list(brief.preferences or []))
    v = V.verify_job(ledger, relay, verifier, jid)
    assert not v.ok and rejected
    assert any(p.startswith("line 2:") and "no emojis" in p for p in v.problems)


def test_all_once_processes_every_pending_job(chain, monkeypatch, tmp_path):
    from knos.cli import app
    env, ledger, relay = chain
    verifier, _ = env.party()
    other, _ = env.party()
    a, _ = _delivered(env, ledger, relay, market.Brief("A", "x"), b"fine", verifier)
    b, _ = _delivered(env, ledger, relay, market.Brief("B", "x"), b"fine too", verifier)
    _delivered(env, ledger, relay, market.Brief("C", "x"), b"not ours", other)
    _wire(monkeypatch, ledger, relay, verifier)
    monkeypatch.setattr(V, "recalled_preferences", lambda brief, buyer: [])
    got = CliRunner().invoke(app, ["verify", "--all", "--once"])
    assert got.exit_code == 0, got.output
    assert got.output.count("verdict PASS") == 2
    assert market.job(ledger, a).state == market.job(ledger, b).state == "released"
    assert V.pending(ledger, relay, verifier.pubkey()) == []



def test_a_verified_delivery_is_one_envelope_both_sides_open_to_the_same_work():
    from solders.keypair import Keypair
    from knos.jobs import market
    buyer, verifier = Keypair(), Keypair()
    blob = market.envelope(buyer.pubkey(), verifier.pubkey(), b"the work")
    assert market.open_sealed(buyer, blob) == b"the work"
    from knos.team.registry import open_salt
    assert market.open_envelope(blob, "verifier", lambda b: open_salt(b, verifier)) == b"the work"
