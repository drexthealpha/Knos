"""The public numbers: a Knos team is counted only if its claim schema is Knos's byte for byte."""

from __future__ import annotations

import sys
from pathlib import Path

from _devchain import URL, devchain, funded, new_team
from knos.team import protocol, rpc, sas
from solders.keypair import Keypair
from solders.pubkey import Pubkey

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import network_stats  # noqa: E402


@devchain
def test_teams_are_counted_and_lookalikes_are_not():
    team, _, (a,) = new_team(1)
    protocol.claim(team, protocol.Holder(a, "codex", "m"), "x.py", within=30)
    fake = funded(1)
    name = "knos-" + "0" * 16
    cred = sas.credential_pda(fake.pubkey(), name)
    rpc.send(URL, [sas.create_credential(fake.pubkey(), fake.pubkey(), name, [fake.pubkey()])], fake)
    rpc.send(URL, [sas.create_schema(fake.pubkey(), fake.pubkey(), cred, "knos.claim.v1", "not ours", [sas.U8],
                                     ["x"])], fake)
    got = network_stats.cluster_stats("local", URL, with_history=False)
    assert got["teams"] >= 1 and got["claims_live"] >= 1 and got["rejected_lookalikes"] >= 1, got
    html = network_stats.render({"updated": "now", "clusters": [got], "github": {}})
    assert "counts are not proof of distinct teams" in html


def test_first_transaction_date_paginates(monkeypatch):
    """first_transaction_date follows pages until the last signature on the last page."""
    fake_cred = Keypair().pubkey()
    calls = []

    def mock_call(url, method, params, timeout=60):
        if method == "getSignaturesForAddress":
            p = params[1]
            calls.append(p)
            if "before" not in p:
                return [{"signature": f"sig-{i}", "blockTime": 1710000000 - i} for i in range(1000)]
            if p["before"] == "sig-999":
                return [
                    {"signature": "sig-1000", "blockTime": 1700000100},
                    {"signature": "sig-oldest", "blockTime": 1700000000},  # 2023-11-14 22:13:20 UTC
                ]
            return []
        return None

    monkeypatch.setattr(rpc, "call", mock_call)
    got = network_stats.first_transaction_date("http://fake", fake_cred)
    assert got == "2023-11-14"
    assert len(calls) == 2
    assert "before" not in calls[0]
    assert calls[1]["before"] == "sig-999"


def test_cluster_stats_first_seen_range(monkeypatch):
    """cluster_stats formats multiple team first-seen dates as a min..max range."""
    cred1 = Keypair().pubkey()
    cred2 = Keypair().pubkey()

    monkeypatch.setattr(network_stats, "credentials", lambda url: [(cred1, None), (cred2, None)])
    monkeypatch.setattr(network_stats, "is_knos_team", lambda url, addr: True)
    monkeypatch.setattr(network_stats, "attestations_by_schema", lambda url, addr: {})
    monkeypatch.setattr(network_stats, "closes", lambda url, addr: 0)

    dates = {str(cred1): "2024-02-01", str(cred2): "2024-08-15"}
    monkeypatch.setattr(network_stats, "first_transaction_date", lambda url, addr: dates.get(str(addr)))

    got = network_stats.cluster_stats("devnet", "http://fake", with_history=True)
    assert got["teams"] == 2
    assert got["first_seen"] == "2024-02-01 .. 2024-08-15"


def test_cluster_stats_first_seen_single_team(monkeypatch):
    """When a cluster has only one team, first_seen is that team's date alone."""
    cred1 = Keypair().pubkey()

    monkeypatch.setattr(network_stats, "credentials", lambda url: [(cred1, None)])
    monkeypatch.setattr(network_stats, "is_knos_team", lambda url, addr: True)
    monkeypatch.setattr(network_stats, "attestations_by_schema", lambda url, addr: {})
    monkeypatch.setattr(network_stats, "closes", lambda url, addr: 0)
    monkeypatch.setattr(network_stats, "first_transaction_date", lambda url, addr: "2024-05-10")

    got = network_stats.cluster_stats("devnet", "http://fake", with_history=True)
    assert got["teams"] == 1
    assert got["first_seen"] == "2024-05-10"


def test_render_includes_first_seen_header_and_data():
    """render includes the 'first seen' table header and cluster value."""
    sample = {
        "updated": "2026-10-01 12:00 UTC",
        "clusters": [{
            "cluster": "devnet", "teams": 3, "members": 5, "claims_live": 2, "renewals_live": 1,
            "records": 4, "closes_recent": 12, "first_seen": "2024-01-10 .. 2024-09-20", "error": ""
        }],
        "github": {"stars": 10, "forks": 2, "contributors": 3, "open_issues": 1},
    }
    html = network_stats.render(sample)
    assert "<th>first seen</th>" in html
    assert "<td>2024-01-10 .. 2024-09-20</td>" in html

