"""The submission's checklist and its one transaction: every link leads to a file, the invoice figures are what
`knos shadow` gives on the sample, and the witnessed links are the ones the README and the judges' page give."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB = ROOT / "docs" / "submission"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _relative(text: str) -> list[str]:
    return [t.split("#")[0] for t in re.findall(r"\]\(([^)\s]+)\)", text) if not re.match(r"[a-z]+:|#", t)]


def test_every_relative_link_of_the_checklist_and_the_transaction_leads_to_a_file():
    for name in ("CHECKLIST.md", "TRANSACTION.md", "SUBMISSION.md"):
        for target in _relative(_read(SUB / name)):
            assert (SUB / target).resolve().exists(), f"{name}: {target}"


def test_the_checklist_names_the_three_entries_and_cites_the_page():
    text = _read(SUB / "CHECKLIST.md")
    for heading in ("## Grand Prize", "## Solana track", "## Public Good"):
        assert heading in text
    assert "colosseum.com/worldsfair" in text and "colosseum.com/hackathon" in text
    assert "no program outside this repository reads a token yet" in text


def test_the_invoice_figures_are_what_shadow_gives_on_the_sample():
    done = subprocess.run([sys.executable, "-m", "knos", "shadow", "examples/shadow/invoice.csv", "--recorded",
                           "examples/shadow/recorded.json"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "NO_COLOR": "1"}, timeout=120)
    out = done.stdout
    sha = re.search(r"sha256 ([0-9a-f]{64})", out).group(1)
    text = _read(SUB / "TRANSACTION.md")
    assert sha in text
    assert "In dispute: 1750.00 of 2900.00" in out and "In dispute: 1,750.00 of 2,900.00" in text


def test_the_witnessed_links_agree_with_the_readme_and_the_judges_page():
    links = set(re.findall(r"https://(?:explorer\.solana\.com/tx|github\.com/drexthealpha/knos-witness)/[^)\s]+", _read(ROOT / "README.md")))
    assert links and links <= set(re.findall(r"https://[^)\s]+", _read(ROOT / "docs" / "JUDGES.md")))
    text = _read(SUB / "TRANSACTION.md")
    for link in links:
        assert link in text, link
    assert "pull/8" not in text and "pull/8" not in _read(ROOT / "README.md")


def test_the_transaction_page_and_the_changelog_say_which_build_runs_now_and_that_the_time_lock_is_not_applied():
    # once the manifest records knos_pay 2.2 on chain, no page may call 2.1 the build of today or proposal 8 pending,
    # and while docs/GOVERNANCE.md says the time lock is approved and not yet applied, the release's entry says the same
    def flat(rel: str) -> str:
        return " ".join((ROOT / rel).read_text(encoding="utf-8").split())

    on_chain = json.loads((ROOT / "docs" / "capabilities.json").read_text(encoding="utf-8"))["programs"]["knos_pay"]["on_chain"]
    page = flat("docs/submission/TRANSACTION.md")
    if on_chain == "2.2":
        assert "deployed today, knos_pay 2.1" not in page and "proposal 8, pending" not in page
        assert "the build deployed when the order was funded. Upgrade proposal 8 has since executed: knos_pay 2.2 charges 0.30%" in page
    entry = flat("CHANGELOG.md").split("## 0.3.23")[0]
    if "approved, not yet applied" in flat("docs/GOVERNANCE.md"):
        assert "The 8-day upgrade time lock is approved, not applied." in entry and "time lock is applied" not in entry

