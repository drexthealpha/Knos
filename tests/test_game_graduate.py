"""Step 6 for a game: the winner's verdict + locked pre-orders + sourced quotes -> the referee's verdict; graduation's
vault and pre-orders paid to the contributor split (LiteSVM); Knos Record, the Zenodo sandbox DOI (fixture without a
token), SWHIDs and the anchor."""
from __future__ import annotations

import json

import pytest

from _game import TASK, FakeJudge, attempt

from knos.autoresearch import task as artask
from knos.game import graduate, ids
from knos.game.engine import Game

REPO = 31_415_926
QUOTE = [{"kind": "compute", "supplier": "Nebius Token Factory (MOCK usage)", "unit_cost": 0.9, "quantity": 1,
          "source": "Token Factory model catalog, read 14 Oct 2026 (knos.nebius.sources)"}]


def _played(tmp_path, final=0.8):
    t = artask.load(TASK)
    g = Game.create(tmp_path / "g", TASK, title="Graduating game", judge=FakeJudge(t))
    w = g.join("winner", kind="agent", github_id=501, payee="So11111111111111111111111111111111111111112")["player"]
    g.submit(w, {"train.py": attempt(g.baseline(), 0.8, final)})
    g.finish()
    return g


def _orders(g, n=2, amount=10_000_000):
    return [{"spec_hash": g.s["seal"]["spec_hash"], "buyer": f"buyer{i}", "amount": amount, "escrow_ref": f"order{i}", "status": "locked"}
            for i in range(n)]


def test_the_swhid_of_a_file_is_its_git_blob_hash():
    assert ids.swhid_content(b"hello\n") == "swh:1:cnt:ce013625030ba8dba906f756967f9e9ca394464a"


def test_zenodo_without_a_token_is_a_fixture_with_no_doi(monkeypatch):
    monkeypatch.delenv(ids.ZENODO_ENV, raising=False)
    got = ids.zenodo_deposit(ids.metadata("t", "d", ["Knos"]), {"a.py": b"x"})
    assert got["mode"] == "fixture" and got["doi"] is None and got["label"].startswith("FIXTURE")


def test_zenodo_with_a_token_follows_the_documented_calls():
    calls = []

    def http(method, url, headers=None, body=None, timeout=30.0):
        calls.append((method, url.replace(ids.ZENODO, "Z/"), (headers or {}).get("Authorization", "")))
        if url.endswith("deposit/depositions") and method == "POST":
            return 201, {"id": 7, "links": {"bucket": "https://sandbox.zenodo.org/api/files/b1"}}
        if url.endswith("/actions/publish"):
            return 202, {"doi": "10.5072/zenodo.7", "links": {"html": "https://sandbox.zenodo.org/records/7"}}
        return 200, {}
    got = ids.zenodo_deposit(ids.metadata("t", "d", ["Knos"]), {"a.py": b"x"}, token="t0k", http=http)
    assert got["doi"] == "10.5072/zenodo.7" and got["sandbox"] is True
    assert [c[:2] for c in calls] == [("POST", "Z/deposit/depositions"), ("PUT", "Z/files/b1/a.py"),
                                      ("PUT", "Z/deposit/depositions/7"), ("POST", "Z/deposit/depositions/7/actions/publish")]
    assert all(c[2] == "Bearer t0k" for c in calls) and "t0k" not in json.dumps(got)


def test_software_heritage_save_reads_the_documented_fields():
    def http(method, url, headers=None, body=None, timeout=30.0):
        assert url == ids.SWH + "origin/save/git/url/https://github.com/drexthealpha/Knos/" and method == "POST"
        return 200, {"id": 9, "save_request_status": "accepted", "save_task_status": "pending", "snapshot_swhid": None}
    got = ids.swh_save("https://github.com/drexthealpha/Knos", http=http)
    assert (got["mode"], got["save_request_status"], got["error"]) == ("live", "accepted", None)
    with pytest.raises(ids.IdError):
        ids.swh_save("http://insecure.example")


def test_a_winner_with_demand_and_a_margin_graduates_and_without_demand_does_not(tmp_path):
    g = _played(tmp_path)
    v = graduate.verdict(g, _orders(g), QUOTE, locked_price=20.0, min_buyers=2, min_locked=20_000_000, record=False)
    assert v["passed"] is True and v["failed"] == []
    no = graduate.verdict(g, _orders(g, 1), QUOTE, locked_price=20.0, min_buyers=2, min_locked=20_000_000, record=False)
    assert no["passed"] is False and no["failed"] == ["wanted"]


def test_nobody_passing_means_nothing_works(tmp_path):
    g = _played(tmp_path, final=0.5)
    w = graduate.works(g)
    assert w.passed is False
    assert graduate.permanent(g, {"passed": False}, None)["why"].startswith("the verdict did not pass")


def test_the_graduation_pays_the_split_from_the_escrow_and_the_preorders_in_litesvm(tmp_path):
    pytest.importorskip("solders.litesvm")
    from pathlib import Path

    from solders.keypair import Keypair
    g = _played(tmp_path)
    v = graduate.verdict(g, _orders(g), QUOTE, locked_price=20.0, min_buyers=2, min_locked=20_000_000, record=False)
    cs = graduate.contributors(g, researcher_id=601, referee_id=602)
    assert [c["role"] for c in cs] == ["researcher", "agent", "referee"] and cs[1]["github_id"] == 501
    p = graduate.plan(g, v, repo_id=REPO, amount=30_000_000, contributors_=cs)
    wallets = [str(Keypair().pubkey()) for _ in p["split"]]
    got = graduate.pay_litesvm(Path(__file__).resolve().parents[1], p, wallets, [10_000_000, 7_000_000])
    assert got["paid"], got.get("error")
    from knos.money import fees_config
    want = [a + b + c for a, b, c in zip(*(fees_config.amounts(x, [b for _, b, _ in p["payees"]]) for x in (30_000_000, 10_000_000, 7_000_000)))]
    assert [x["received"] for x in got["payees"]] == want and got["total_received"] == 47_000_000


def test_the_permanent_record_names_the_ids_and_anchors(tmp_path, monkeypatch):
    monkeypatch.delenv(ids.ZENODO_ENV, raising=False)
    g = _played(tmp_path)
    v = graduate.verdict(g, _orders(g), QUOTE, locked_price=20.0, min_buyers=2, min_locked=20_000_000, record=False)
    sent = []

    def fake_send(memo):
        sent.append(memo)
        return {"tx": "5" * 88, "signer": "So11111111111111111111111111111111111111112", "slot": 1}
    swh = lambda url: {"mode": "live", "save_request_status": "accepted", "snapshot_swhid": None}   # noqa: E731
    out = graduate.permanent(g, v, None, origin_url="https://github.com/drexthealpha/Knos", swh=swh, anchor_send=fake_send)
    assert out["swhid_content"].startswith("swh:1:cnt:") and out["zenodo"]["mode"] == "fixture"
    assert out["record"]["ok"] is True and out["anchor"]["anchored"] is True and sent
    kinds = [e["kind"] for e in g.rec.written]
    assert "graduation" in kinds and kinds.count("paper") >= 2       # the program, and the SWHID of the winning file
