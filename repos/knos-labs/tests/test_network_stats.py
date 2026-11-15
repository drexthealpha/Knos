"""The public numbers: a Knos team is counted only if its claim schema is Knos's byte for byte."""

from __future__ import annotations

import sys
from pathlib import Path

from _devchain import URL, devchain, funded, new_team
from knos.team import protocol, rpc, sas

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
