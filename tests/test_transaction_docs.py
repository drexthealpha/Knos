"""The one transaction (docs/TRANSACTION.md): every link leads to a file, and the witnessed links are the ones the
README gives."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _relative(text: str) -> list[str]:
    return [t.split("#")[0] for t in re.findall(r"\]\(([^)\s]+)\)", text) if not re.match(r"[a-z]+:|#", t)]


def test_every_relative_link_of_the_transaction_leads_to_a_file():
    for name in ("TRANSACTION.md",):
        for target in _relative(_read(DOCS / name)):
            assert (DOCS / target).resolve().exists(), f"{name}: {target}"


def test_the_witnessed_links_agree_with_the_readme():
    links = set(re.findall(r"https://(?:explorer\.solana\.com/tx|github\.com/drexthealpha/knos-witness|github\.com/drexthealpha/Knos/blob/main/evidence)/[^)\s]+",
                            _read(ROOT / "README.md")))
    assert links
    text = _read(DOCS / "TRANSACTION.md")
    for link in links:
        assert link in text, link
    assert "pull/8" not in text and "pull/8" not in _read(ROOT / "README.md")


def test_the_transaction_page_and_the_changelog_say_which_build_runs_now_and_that_the_time_lock_is_not_applied():
    # once the manifest records knos_pay 2.2 on chain, no page may call 2.1 the build of today or proposal 8 pending,
    # and while docs/reference/GOVERNANCE.md says the time lock is approved and not yet applied, the release's entry says the same
    def flat(rel: str) -> str:
        return " ".join((ROOT / rel).read_text(encoding="utf-8").split())

    on_chain = json.loads((ROOT / "docs" / "capabilities.json").read_text(encoding="utf-8"))["programs"]["knos_pay"]["on_chain"]
    page = flat("docs/TRANSACTION.md")
    if on_chain == "2.2":
        assert "deployed today, knos_pay 2.1" not in page and "proposal 8, pending" not in page
        assert "the build deployed when the order was funded. Upgrade proposal 8 has since executed: knos_pay 2.2 charges 0.30%" in page
    entry = flat("CHANGELOG.md").split("## 0.3.23")[0]
    if "approved, not yet applied" in flat("docs/reference/GOVERNANCE.md"):
        assert "The 8-day upgrade time lock is approved, not applied." in entry and "time lock is applied" not in entry
    # once it says the time lock is in force, the newest entry says so in its first line, and no page says it is not yet
    if "**State: in force since 11 Oct 2026.**" in flat("docs/reference/GOVERNANCE.md"):
        top = flat("CHANGELOG.md").split("## 0.3.28 ")[1].split("## 0.3.27 ")[0]
        assert "**In short:** the 8-day time lock is in force: every program change now waits 8 days in public." in top
        for rel in ("docs/TRUST.md", "docs/reference/GOVERNANCE.md", "docs/reference/CHARTER.md", "CONTRIBUTING.md"):
            page = flat(rel)
            assert "not yet applied" not in page and "not yet in force" not in page and "approved, not applied" not in page, rel
            assert "691,200 s, in force since 11 Oct 2026" in page or "in force since 11 Oct 2026" in page, rel


def test_no_public_page_calls_48_hours_the_wait_of_today():
    # the 8-day time lock is in force since 11 Oct 2026: the security policy, the contributing guide, the consumer
    # example, the knos-oidc-interface README and programs-v2/README.md say 8 days, and 48 hours only as what came before (receipts, IDLs and
    # the programs' own comments keep their words: CHANGELOG 0.3.28 and docs/reference/RECEIPT.md say why)
    if "**State: in force since 11 Oct 2026.**" not in (ROOT / "docs" / "reference" / "GOVERNANCE.md").read_text(encoding="utf-8"):
        return
    for rel in ("SECURITY.md", "CONTRIBUTING.md", "examples/consumer/README.md", "crates/knos-oidc-interface/README.md",
                "programs-v2/README.md"):
        page = " ".join((ROOT / rel).read_text(encoding="utf-8").split())
        for stale in ("48 hours today", "not yet applied", "public 48-hour", "public 48 hours before", "two days after it is approved"):
            assert stale not in page, (rel, stale)
        assert re.search(r"8[- ]day", page) and "11 Oct 2026" in page, rel


def test_the_release_entry_says_what_ran_on_devnet_before_the_commit_and_calls_none_of_it_pending():
    # once docs/load.json holds a devnet burst with the fan-out, and the manifest has the rounds' capabilities
    # exercised, the release's entry says so and no longer calls them pending or not yet run
    entry = " ".join((ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("## 0.3.24")[0].split())
    load = json.loads((ROOT / "docs" / "load.json").read_text(encoding="utf-8"))
    fanned = [m for m in load["measured"] if m.get("cluster") == "devnet" and m.get("fanout")]
    if fanned:
        assert "the burst rerun with the fan-out is pending" not in entry
        assert f"the burst with the fan-out paid {fanned[-1]['paid']} of {fanned[-1]['attempted']}" in entry
    caps = json.loads((ROOT / "docs" / "capabilities.json").read_text(encoding="utf-8"))["capabilities"]
    stage = {c["id"]: c["stage"] for c in caps}
    rounds = ("meter_single", "passkey_payee_wallet", "upgrade_gate", "pause")
    if any(stage.get(r) == "exercised" for r in rounds):
        assert "are ready for the release to run at the public ids" not in entry
        exercised = sum(c["stage"] == "exercised" for c in caps)
        assert f"to exercised ({exercised} of {len(caps)})" in entry



def test_no_page_or_site_says_the_lock_in_force_is_two_days_once_it_is_8_days():
    # since 11 Oct 2026 a program change waits 8 days; only the receipt's trust line (checked word for word, with its
    # vectors and web/buyer_templates.json) keeps "public 48-hour delay", and dated history says "48 hours then"
    if "**State: in force since 11 Oct 2026.**" not in " ".join((ROOT / "docs" / "reference" / "GOVERNANCE.md").read_text(encoding="utf-8").split()):
        return
    kept = {"docs/reference/RECEIPT.md"}
    files = [ROOT / "README.md", ROOT / "README.pypi.md", *sorted((ROOT / "docs").rglob("*.md")),
             *sorted(p for p in (ROOT / "web").rglob("*") if p.suffix in (".html", ".js", ".md", ".txt") and "node_modules" not in p.parts)]
    said = []
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        text = " ".join(path.read_text(encoding="utf-8").split())
        for phrase in ("two days before it can run", "public two days", "waits 48 hours", "wait is 48 hours", "public 48-hour delay"):
            if phrase in text and not (phrase == "public 48-hour delay" and rel in kept):
                said.append((rel, phrase))
    assert not said, said
    # the check view spells its days out (it holds almost no digits): the word is the lock the site reads, in days
    lock = json.loads((ROOT / "web" / "upgrades.json").read_text(encoding="utf-8"))["time_lock"]
    assert lock == 691_200
    assert "shown in public eight days before it can run" in " ".join((ROOT / "web" / "index.html").read_text(encoding="utf-8").split())
