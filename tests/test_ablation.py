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


@pytest.mark.critical
def test_the_repo_carries_its_memory_to_a_fresh_machine(bare) -> None:
    """The keepsake arm: what comes back, and what must not."""
    lost, back, gone = ablation.arm_restore(bare)
    assert lost is True, "the decision survived deleting the store somehow"
    assert back is True, "knos restore did not recover it from the committed file"
    assert gone is True, "a claim was rebuilt on a machine where nobody holds it"


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
    assert arms["restore"]["lost_before"] == trials
    assert arms["restore"]["back_after"] == trials
    assert arms["restore"]["claims_stayed_gone"] == trials
    # The rule is answered while the file carries it, withdrawn the moment it
    # does not, and there is nothing to answer with at all once the store is
    # gone - which is a real dependence and a weaker one than the withhold.
    assert arms["stale_rule"]["answered"] == trials
    assert arms["stale_rule"]["withdrawn"] == trials
    assert arms["stale_rule"]["answered_without_store"] == 0


def test_the_script_runs_end_to_end() -> None:
    """A judge running the documented command gets the documented table."""
    said = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ablation.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=900,
    )
    assert said.returncode == 0, said.stderr[-800:]
    for line in ("Withhold", "Guard", "Action", "Paid", "Spend", "Reversed", "Fresh machine", "store deleted"):
        assert line in said.stdout, line


def test_the_page_knows_which_number_is_which_for_every_arm() -> None:
    """The evidence page used to guess, and got three of seven rows wrong.

    It took the first two keys of an arm and called them with-the-store and
    without-it. For `reversed` and `restore` - which measure three things that
    all happen while the store is present - that printed "12/12" under a
    column headed "without it", telling a reader that deleting the store
    changed nothing, on the page whose whole job is the deletion test. For
    `spend`, whose count is of the bad outcome, it printed the store scoring
    zero.

    So the page now carries an explicit spec per arm, and this fails when an
    arm is added without one rather than letting the table invent a number.
    """
    import json
    import re

    page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    spec = page[page.index("const ARMS = {"):]
    spec = spec[: spec.index("\n};")]
    got = json.loads(
        (ROOT / "docs" / "evidence" / "ablation.json").read_text(encoding="utf-8")
    )

    missing = [name for name in got["arms"] if f"{name}:" not in spec]
    assert not missing, (
        f"the page has no way to read these arms and would guess: {missing}"
    )

    # Every key the spec names has to be one the arm actually publishes.
    wrong = []
    for name, arm in got["arms"].items():
        block = spec[spec.index(f"{name}:") :]
        block = block[: block.index("}")]
        for key in re.findall(r"'(\w+)'", block):
            if key not in arm and key != "invert":
                wrong.append(f"{name}.{key}")
    assert not wrong, f"the page reads keys the ablation does not write: {wrong}"


def test_the_stale_rule_arm_is_honest_about_being_the_weak_one() -> None:
    """Its ablated value is zero for a duller reason than the others.

    Deleting the store does not make knos quote the rule wrongly - it leaves
    it with no rule to quote at all. That is still a dependence, and it is a
    smaller claim than the withhold arm, where deleting the store makes knos
    actively hand over work somebody else is holding.
    """
    said = (ROOT / "scripts" / "ablation.py").read_text(encoding="utf-8")
    body = said[said.index("def arm_stale_rule") :]
    body = body[: body.index("\ndef ")]

    assert "no rule to quote" in body, (
        "the arm has to say why its zero is a weaker result than the others'"
    )
