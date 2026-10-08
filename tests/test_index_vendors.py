"""scripts/vendor_pages.py and web/vendor.js: a page for each vendor the Agent PR Index rates, with its numbers and their
sample, a right of reply, its disputes and how to earn the supplier badge. Committed files only; no network."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import agent_pr_board  # noqa: E402
import vendor_pages as vp  # noqa: E402

SERIES = json.loads((ROOT / "docs" / "agent_weekly.json").read_text(encoding="utf-8"))
ISSUE = "https://github.com/drexthealpha/Knos/issues/9001"


def test_the_committed_pages_are_what_the_files_give():
    run = subprocess.run([sys.executable, "scripts/agent_pr_index.py", "vendors", "--check"], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", timeout=120)
    assert run.returncode == 0, run.stderr


def test_every_row_has_a_page_with_its_sample_reply_and_dispute():
    doc = vp.build(SERIES)
    top = agent_pr_board.board(SERIES)
    assert [v["agent"] for v in doc["vendors"]] == [r["agent"] for r in top["rows"]]
    for v, r in zip(doc["vendors"], top["rows"], strict=True):
        assert v["row"]["merged"] == r["merged"] and v["row"]["ci95"] == r["ci95"] and v["dispute"] == r["dispute"]
        assert v["reply"].startswith(f"{vp.REPO}/issues/new?template=vendor-reply.yml") and f"agent={v['agent']}" in v["reply"]
        assert len(v["weekly"]) == len(SERIES["agents"][v["agent"]]["weeks"])
        assert v["page"].endswith(f"#vendor={v['slug']}") and v["replies"] == [] and v["disputes"] == {"open": [], "closed": []}
    assert any("not a rating of defect-free work" in n for n in doc["not"])
    assert [s["step"] for s in doc["badge"]] == ["Run the free check on your own pull requests", "Deliver accepted work under a funded order"]
    page = vp.markdown(doc)
    assert page.count("[Dispute this row](") == len(doc["vendors"]) and page.count("No reply yet.") == len(doc["vendors"])


def test_a_reply_is_printed_word_for_word_and_a_dispute_with_its_outcome():
    agent = next(iter(SERIES["agents"]))
    disputes = [{"agent": agent, "week": None, "issue": ISSUE, "opened": "2026-10-01", "status": "rejected", "resolved": "2026-10-03",
                 "outcome": "the failed checks test the build", "changed": []}]
    replies = [{"agent": agent, "issue": ISSUE, "posted": "2026-10-02", "text": "Our checks include a preview deploy that fails often."}]
    doc = vp.build(SERIES, disputes, replies)
    mine = next(v for v in doc["vendors"] if v["agent"] == agent)
    assert mine["replies"] == replies and mine["disputes"]["closed"] == disputes and mine["disputes"]["open"] == []
    page = vp.markdown(doc)
    assert "> Our checks include a preview deploy that fails often." in page and "rejected 2026-10-03: the failed checks test the build" in page


@pytest.mark.parametrize("bad", [{"agent": "nobody", "issue": ISSUE, "text": "x"}, {"agent": "copilot", "issue": "http://x", "text": "x"},
                                 {"agent": "copilot", "issue": ISSUE, "text": ""}, {"agent": "copilot", "issue": ISSUE, "text": "x" * 1201}])
def test_a_wrong_reply_stops_the_run_in_words(tmp_path, bad):
    path = tmp_path / "replies.json"
    path.write_text(json.dumps({"schema": vp.REPLIES_SCHEMA, "replies": [bad]}), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        vp.load_replies(str(path), list(SERIES["agents"]))
    assert "reply 1" in str(e.value)


def test_the_reply_form_exists_and_asks_for_the_agent():
    form = (ROOT / ".github" / "ISSUE_TEMPLATE" / "vendor-reply.yml").read_text(encoding="utf-8")
    assert "id: agent" in form and "id: reply" in form and "1,200 characters" in form and "docs/index_replies.json" in form


def test_the_site_page_draws_one_vendor_with_its_reply_and_dispute_links():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    doc = vp.build(SERIES)
    script = ("import('" + (ROOT / "web" / "vendor.js").as_uri() + "').then((m) => { const d = JSON.parse(process.argv[1]);"
              " process.stdout.write(JSON.stringify([m.vendorHtml(d, 'copilot'), m.vendorHtml(d, 'nobody'), m.slugIn('#vendor=Copilot')])); })")
    run = subprocess.run([node, "--input-type=module", "-e", script, json.dumps(doc)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0, run.stderr
    html, none, slug = json.loads(run.stdout)
    row = next(v for v in doc["vendors"] if v["slug"] == "copilot")["row"]
    assert f"{row['failed_at_merge']} of {row['merged']}" in html and "95% interval" in html
    assert 'id="vp-reply"' in html and "vendor-reply.yml" in html and 'id="vp-dispute"' in html and "Earn the supplier badge" in html
    assert "not a rating of defect-free work" in html and 'id="vp-none"' in none and slug == "copilot"
    # each badge step is two sentences, the second one capitalised: "... pull requests.</strong> Gives a check receipt ..."
    assert html.count('<span class="fine">Gives ') == len(doc["badge"]) == 2 and '<span class="fine">a check receipt' not in html
