"""The ablation numbers in the README are real, and stay real.

`scripts/ablation.py` is the thing a judge is invited to run. A number in a
README that nothing checks is a number that drifts, so this runs the same
arms and asserts the shape the README claims: every refusal is total with the
store present, and impossible without it.

One trial per arm here rather than twelve. The full run is the artifact; this
is the guard that stops it quietly becoming untrue.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ablation  # noqa: E402


@pytest.fixture()
def bare(tmp_path, monkeypatch):
    """A throwaway repo and knos home, the way the script makes them."""
    monkeypatch.setenv("KNOS_HOME", str(tmp_path / "home"))
    return ablation._repo(tmp_path)


@pytest.mark.critical
def test_the_withhold_needs_the_store(bare) -> None:
    """The claim the whole product rests on, as one measured pair."""
    ablation._seed_claim(bare, "the risk guard")
    on, off = ablation.arm_withhold(bare, "the risk guard")
    assert on is True, "a standing claim did not withhold"
    assert off is False, "the withhold survived deleting the store"


@pytest.mark.critical
def test_the_guard_needs_the_store(bare) -> None:
    ablation._seed_claim(bare, "the risk guard")
    on, off = ablation.arm_guard(bare, "the risk guard")
    assert on is True, "the guard allowed an edit to claimed work"
    assert off is False, "the guard still refused with no store"


def test_the_action_needs_the_exported_file(bare) -> None:
    ablation._seed_claim(bare, "the risk guard")
    on, off = ablation.arm_action(bare, "the risk guard")
    assert on is True, "the check did not match a claimed topic"
    assert off is False, "the check matched with no decisions file"


def test_a_bought_answer_needs_the_store_to_be_found_again(bare) -> None:
    on, off = ablation.arm_paid(bare)
    assert on is True, "the write-back was not readable by the next agent"
    assert off is False, "a bought answer survived deleting the store"


@pytest.mark.critical
def test_the_memory_gates_the_money(bare) -> None:
    """The arm that answers "what does remembering actually change"."""
    on, off, refused = ablation.arm_spend(bare)
    assert on is False, "it bought again with the answer already in the store"
    assert off is True, "it did not buy again after the store was deleted"
    assert refused is True, "a standing claim did not stop the spend"


@pytest.mark.critical
def test_a_reversed_decision_changes_outcomes(bare) -> None:
    """The arm that separates a memory that records from one that decides."""
    edit, spend, again = ablation.arm_reversed(bare)
    assert edit is True, "an edit resting on a reversed decision was allowed"
    assert spend is True, "a purchase resting on a reversed decision went through"
    assert again is True, "reconsidering did not release the work"


def test_the_published_numbers_match_the_arms() -> None:
    """docs/evidence/ablation.json is what the README quotes."""
    out = ROOT / "docs" / "evidence" / "ablation.json"
    assert out.exists(), "run scripts/ablation.py"
    got = json.loads(out.read_text(encoding="utf-8"))
    trials = got["trials"]
    arms = got["arms"]
    assert trials >= 12
    assert arms["withhold"]["on_refused"] == trials
    assert arms["withhold"]["off_refused"] == 0
    assert arms["guard"]["on_refused"] == trials
    assert arms["guard"]["off_refused"] == 0
    assert arms["action"]["on_commented"] == trials
    assert arms["action"]["off_commented"] == 0
    assert arms["paid"]["on_kept"] == trials
    assert arms["paid"]["off_kept"] == 0
    assert arms["spend"]["on_paid_again"] == 0
    assert arms["spend"]["off_paid_again"] == trials
    assert arms["spend"]["refused_when_claimed"] == trials
    assert arms["reversed"]["edit_refused"] == trials
    assert arms["reversed"]["spend_refused"] == trials
    assert arms["reversed"]["allowed_after_reconsider"] == trials


def test_the_script_runs_end_to_end() -> None:
    """A judge running the documented command gets the documented table."""
    said = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ablation.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=900,
    )
    assert said.returncode == 0, said.stderr[-800:]
    for line in ("Withhold", "Guard", "Action", "Paid", "Spend", "Reversed", "store deleted"):
        assert line in said.stdout, line
