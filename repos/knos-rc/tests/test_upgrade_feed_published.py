"""scripts/upgrade_feed.py --published: the feed the site serves, held to the multisig as it is now. The site's copy is
written when the site is built, so after a proposal is made or executed it is behind until the pages workflow runs."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("upgrade_feed_published", ROOT / "scripts" / "upgrade_feed.py")
feed = importlib.util.module_from_spec(spec)
sys.modules["upgrade_feed_published"] = feed
spec.loader.exec_module(feed)


def entry(index: int, program: str, status: str) -> feed.Entry:
    return feed.Entry(index=index, program=program, program_address="P", buffer="B", build_hash=None, hash_from=None, source_commit=None, gate_run=None,
                      status=status, squads_status="Approved" if status == "pending" else "Executed", approved=2, threshold=2, earliest_execution=None, since=0, proposal="A")


def test_a_site_built_before_the_proposals_is_behind_and_one_built_after_is_not():
    chain = [entry(8, "knos_pay", "pending"), entry(7, "knos_oidc", "pending"), entry(6, "knos_passkey", "executed")]
    # the site as it was the morning proposals 7 and 8 were approved: built before them
    old = {"generated": "2026-10-07T08:00:25Z", "pending": 0, "entries": [{"index": 6, "program": "knos_passkey", "status": "executed"}]}
    assert feed.behind(chain, old) == ["proposal 8 (knos_pay) is pending on chain, and the site's feed (generated 2026-10-07T08:00:25Z) does not have it",
                                       "proposal 7 (knos_oidc) is pending on chain, and the site's feed (generated 2026-10-07T08:00:25Z) does not have it"]
    now = {"generated": "g", "entries": [{"index": 8, "status": "pending"}, {"index": 7, "status": "pending"}, {"index": 6, "status": "executed"}]}
    assert feed.behind(chain, now) == []
    # after they execute, a site that still says pending is behind again
    ran = [entry(8, "knos_pay", "executed"), entry(7, "knos_oidc", "executed")]
    assert feed.behind(ran, now) == ["proposal 8 (knos_pay) is executed on chain, and the site's feed (generated g) says pending",
                                     "proposal 7 (knos_oidc) is executed on chain, and the site's feed (generated g) says pending"]
    # a site that does not answer, or answers something else, is not "current"
    assert feed.behind(ran, None) == feed.behind(ran, {"entries": "x"}) == ["the site's upgrades.json could not be read"]
    assert feed.fetch("http://example.invalid/upgrades.json") is None         # https only, and nothing is fetched
