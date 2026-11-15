"""scripts/stale_check.py: no public file states a retired figure as current."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("stale_check", ROOT / "scripts" / "stale_check.py")
assert _spec and _spec.loader
stale = importlib.util.module_from_spec(_spec)
sys.modules["stale_check"] = stale
_spec.loader.exec_module(stale)

# Files this check was written with; they must stay clean.
CLEAN = (
    "docs/reference/COMPARE.md",
    "docs/reference/DISCLOSURE.md",
    "docs/reference/MARKET.md",
    "docs/reference/METER.md",
)


def test_the_whole_tree_states_no_retired_figure() -> None:
    """scripts/stale_check.py passes on every public file: nothing is left to fix later."""
    found = stale.check(ROOT)
    assert found == [], [(f.file, f.line, f.rule) for f in found]


MD = Path("x.md")


def rules(text: str, path: Path = MD) -> list[str]:
    return [f.rule for f in stale.check_text("x", path, text)]


def test_owned_files_are_clean() -> None:
    for name in CLEAN:
        p = ROOT / name
        assert stale.check_text(name, p, p.read_text(encoding="utf-8")) == [], name


def test_retired_lead_is_found_and_history_is_not() -> None:
    assert rules("Of 241 merged pull requests, 30 of 241 had a failed check.") == ["lead"]
    assert rules("The share is 12.4% today.") == ["lead"]
    assert rules("The scan had recorded 30 of 241 (12.4%); 11 were excluded on the second reading.") == []
    assert rules("Of 241 merged agent pull requests, 9 had a failed test (3.7%).") == []


def test_merge_to_paid() -> None:
    assert rules("From merge to paid takes 25 seconds.") == ["merge-to-paid"]
    assert rules("The median from merge to paid is 25 s.") == ["merge-to-paid"]
    assert rules("The 6 October reading: median 25 s over 42 payments.") == []
    assert rules("A median of 26 seconds over 51 payments.") == ["merge-to-paid"]
    assert rules("On 6 Oct 2026 the median was 26 seconds over 51 payments.") == []
    assert rules("A median of 28 seconds over 56 payments, measured 10 Oct 2026.") == []
    assert rules("A median of 28 seconds over 56 payments.") == []


def test_old_disclosure_counts() -> None:
    assert rules("Of its 209 commits up to Knos 0.3.11, 83 predate it.") == ["disclosure-0.3.11"]
    assert rules("(At Knos 0.3.11, commit `f3dfd3d`, the same count was 423 of 39,778 lines.)") == []


def test_meter_price_needs_the_program_beside_it() -> None:
    assert rules("The Meter costs 0.002 USD an evaluation.") == ["meter-price"]
    assert rules("The price book proposes 0.002 USD an evaluation; the program charges 0.05 after 10,000.") == []


def test_pending_upgrade_is_retired() -> None:
    assert rules("Until the upgrade to knos_pay 2.2 executes, the fee is tiered.") == ["fee-upgrade-pending"]


def test_table_rows_are_their_own_paragraph() -> None:
    text = "The scan was read on 1 Oct.\n| all | 241 | 30 (12.4%) |\n"
    assert rules(text) == ["lead"]
    assert [n for n, _ in stale.paragraphs(MD, text)] == [1, 2]


def test_non_markdown_is_read_by_line() -> None:
    assert rules("const a = 1;\n// 0.002 USD an evaluation\n", Path("x.js")) == ["meter-price"]


def test_meter_constants_match_what_the_documents_say() -> None:
    src = (ROOT / "programs-v2" / "knos_meter" / "src" / "lib.rs").read_text(encoding="utf-8")
    fee = re.search(r"pub const FEE: u64 = ([\d_]+);", src)
    free = re.search(r"pub const FREE_PER_MONTH: u64 = ([\d_]+);", src)
    assert fee and free
    assert (int(fee.group(1).replace("_", "")), int(free.group(1).replace("_", ""))) == (50_000, 10_000)
    for name in ("docs/reference/MARKET.md", "docs/reference/METER.md", "docs/reference/COMPARE.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "0.05" in text and "10,000" in text, name


def test_who_pays_matches_knos_pay() -> None:
    src = (ROOT / "programs-v2" / "knos_pay" / "src" / "pay.rs").read_text(encoding="utf-8")
    assert "let net = j.amount - fee;" in src  # a job's fee comes out of the amount
    order = (ROOT / "programs-v2" / "knos_pay" / "src" / "order.rs").read_text(encoding="utf-8")
    assert "n.amount.checked_add(fee)" in order  # an order's fee is paid on top
    for name in ("docs/reference/MARKET.md", "docs/reference/METER.md", "docs/reference/COMPARE.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "on top" in text and "out of" in text, name
