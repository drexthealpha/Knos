"""Step 2, wanted? (wall 1): the demand check (Qloo MOCK, labelled), the pull-commitment plan locked in stages, the
milestone oracles, and the CLI door to both steps. Offline: recorded fixture bodies only. Keys, oracles and flags are
named through knos.ideas.K, knos.ideas.wanted.ORACLE and knos.ideas.cli's constants, never spelled here."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest
from solders.pubkey import Pubkey

from knos import cli, graduation, ideas
from knos.ideas import IdeaError, K, sources, wanted as W
from knos.ideas.cli import GROUP, OUT, PRICE, UNITS
from knos.ideas.http import Fetcher
from knos.settle.v2 import pay

FIXTURE = Path(__file__).parent / "fixtures" / "ideas" / "recorded-fixture.json"
O_ = W.ORACLE
TRIAL, PAPER = "NCT04718792", "arxiv:1606.00335"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for k in ideas.ENVS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no live API call in tests")))
    monkeypatch.setenv(ideas.FIXTURES_ENV, str(FIXTURE))


def trial() -> dict:
    return sources.get(TRIAL)


def paper() -> dict:
    return sources.get(PAPER)


def oracles(p: dict) -> list[str]:
    return [p[s][K.oracle] for s in p[K.stages]]


def test_the_plan_splits_n_times_p_over_the_stages_one_private_order_each():
    c = trial()
    p = W.plan(c, units=10, price=4)
    assert oracles(p) == [O_.trial_registered, O_.results_posted, O_.referee_pass]
    assert [p[s][K.amount] for s in p[K.stages]] == [8_000_000, 12_000_000, 20_000_000]
    assert p[K.commitment][K.total] == 40_000_000
    assert p[K.buyer_pays] == 40_000_000 + sum(pay.order_fee(p[s][K.amount]) for s in p[K.stages])
    # each stage is the claim's milestone k in graduation's scope, and its terms name the oracle and the commitment
    for k, s in enumerate(p[K.stages], 1):
        assert p[s][K.scope] == graduation.scope(c[K.id], W.DEFAULT_JUDGE_REPO, k).hex()
        t = json.loads(p[s][K.terms])
        assert t[K.oracle] == p[s][K.oracle] and t[K.commitment] == p[K.commitment_hash]
        assert t["spec_hash"] == c[K.hash]
        assert p[s][K.terms_hash] == pay.terms_hash(p[s][K.terms].encode()).hex()
    assert p[K.pool][K.scope] == graduation.scope(c[K.id], W.DEFAULT_JUDGE_REPO, 0).hex()
    # a literature claim gets the literature stages
    assert oracles(W.plan(paper(), units=10, price=4)) == [O_.preprint_posted, O_.referee_pass, O_.lab_qc]


def test_the_plan_refuses_what_cannot_be_locked():
    c = trial()
    for over in (dict(stages=[(O_.trial_registered, 5000)]), dict(stages=[("astrology", 10_000)]), dict(units=0),
                 dict(stages=[(O_.trial_registered, 5000), (O_.trial_registered, 5000)]), dict(units=1, price=4),
                 dict(stage_work_s=[10, 10, 10])):
        with pytest.raises(IdeaError):
            W.plan(c, **{"units": 10, "price": 4, **over})
    with pytest.raises(IdeaError):
        W.plan(dict(c, statement="tampered"), units=10, price=4)


def test_fund_instructions_go_to_the_stage_and_pool_orders():
    c = trial()
    p = W.plan(c, units=10, price=4)
    buyer = Pubkey.from_string("Hm36fQuLeD1vQAL4W8HiMTkCw5nhvohDQC9ycBRpzPsE")
    mint = Pubkey.from_string("GnQv5a8QAmWMhAcKreMkJaS2p9j2LZzrRdsNsdjQq22z")
    ix = W.fund_ix(p, K.stage2, buyer, pay.ata(buyer, mint), mint)
    assert ix.program_id == pay.PAY_ID and ix.accounts[1].pubkey == W.address(p, K.stage2, buyer)
    with pytest.raises(IdeaError):
        W.fund_ix(p, "stage9", buyer, pay.ata(buyer, mint), mint)
    with pytest.raises(IdeaError):
        W.fund_ix(p, K.pool, buyer, pay.ata(buyer, mint), mint, 1)
    rel = W.release_audience(p, K.stage1, W.address(p, K.stage1, buyer), "ab" * 32)
    assert rel[K.audience].startswith("knos3:pay:") and "m-of-n referee panel" in rel[K.next_route]


def test_the_oracles_read_the_public_sources():
    c, f = trial(), Fetcher()
    reg = W.check(c, O_.trial_registered, f)
    assert reg[K.met] is True and len(reg[K.evidence_hash]) == 64
    res = W.check(c, O_.results_posted, f)
    assert res[K.met] is False
    assert "hasResults False" in res[K.why]
    pp = paper()
    assert W.check(pp, O_.preprint_posted, f)[K.met] is True
    assert W.check(pp, O_.journal_published, f)[K.met] is True
    pre = sources.get("biorxiv:10.1101/2020.03.22.002386")
    assert W.check(pre, O_.journal_published, f)[K.published_doi] == "10.1038/s41586-020-2286-9"
    bad = sources.get("doi:10.1016/s0140-6736(97)11096-0")
    assert W.check(bad, O_.not_retracted, f)[K.met] is False
    assert W.check(c, O_.referee_pass)[K.met] is None                     # no verdict yet: pending
    with pytest.raises(IdeaError):
        W.check(c, "vibes")


def test_referee_and_lab_verdict_files(tmp_path):
    c = trial()
    v = tmp_path / "v.json"
    v.write_text(json.dumps({K.claim: c[K.id], K.passed: True}))
    assert W.check(c, O_.referee_pass, verdict=str(v))[K.met] is True
    v.write_text(json.dumps({K.claim: ideas.PREFIX + "other", K.passed: True}))
    assert W.check(c, O_.referee_pass, verdict=str(v))[K.met] is False
    v.write_text(json.dumps({K.claim: c[K.id], K.qc: "PASS"}))
    assert W.check(c, O_.lab_qc, verdict=str(v))[K.met] is True


def test_the_demand_check_runs_on_the_labelled_mock_without_a_qloo_key():
    d = W.demand(paper(), "longer-lasting perovskite solar panels")
    assert d[K.status] == "ok" and d[K.mode] == K.mock
    assert "MOCK" in d[K.label]
    assert len(d[K.hash]) == 64
    assert ideas.ENVS[3] in d["key"]
    assert "first candidate" in d[K.confirmed]


def test_the_cli_reads_an_idea_writes_it_and_plans_the_commitment(capsys, tmp_path):
    out = tmp_path / "idea.json"
    assert cli.main([GROUP, "get", TRIAL, OUT, str(out)]) == 0
    said = capsys.readouterr().out
    assert "FIXTURE" in said and TRIAL in said and out.exists()
    assert cli.main([GROUP, "wanted", str(out), UNITS, "10", PRICE, "4"]) == 0
    said = capsys.readouterr().out
    assert "MOCK" in said
    assert f"{K.stage2}: {O_.results_posted}" in said
    assert cli.main([GROUP, "check", str(out), O_.results_posted]) == 0
    assert "not met" in capsys.readouterr().out
    assert cli.main([GROUP, K.sources]) == 0
    assert K.uspto in capsys.readouterr().out
    assert cli.main([GROUP, "get", "myspace:1"]) == 1
