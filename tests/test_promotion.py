"""The promotion bench has to keep publishing the regime where it does not help.

Every number in `promotion.json` flatters knos except one, and that one is the
reason the file is worth reading: the window sweep shows the promoted record
beating the old journal ratio by seven times when the journal is forgetting
fast, and by three per cent when it is not. A judge who sees only the 7.4x has
been sold something.

So these tests spend their effort on the two things that could quietly turn
this into an advert: the sweep staying in the file, and the file continuing to
say out loud that it is a simulation with no model and no real money in it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "promotion_bench.py"
EVIDENCE = ROOT / "docs" / "evidence" / "promotion.json"


def _got() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_the_blind_arm_is_the_one_the_gate_is_decided_on() -> None:
    """Delete the store and every agent is a stranger. That is the baseline."""
    arms = _got()["arms"]

    assert set(arms) == {"blind", "journal", "promoted"}
    assert arms["blind"]["blocked_minutes"]["mean"] > arms["promoted"]["blocked_minutes"]["mean"]
    assert arms["blind"]["wasted_usd"]["mean"] > arms["promoted"]["wasted_usd"]["mean"]


def test_the_window_sweep_is_published_including_where_it_stops_mattering() -> None:
    """The parameter that decides the whole comparison.

    Make the journal's window large enough and it never forgets, so the
    promoted record has nothing to add. Publishing only the width that
    flatters it would be choosing the answer.
    """
    sweep = _got()["window_sweep"]

    assert len(sweep) >= 4, "one or two widths is a choice, not a sweep"

    widths = sorted(int(w) for w in sweep)
    tight, loose = str(widths[0]), str(widths[-1])
    gain_tight = sweep[tight]["journal_wasted_usd"] / sweep[tight]["promoted_wasted_usd"]
    gain_loose = sweep[loose]["journal_wasted_usd"] / sweep[loose]["promoted_wasted_usd"]

    assert gain_tight > gain_loose, (
        "promotion's whole advantage is surviving a window; if the gain does "
        "not shrink as the window grows, the bench is not measuring that"
    )
    assert gain_loose < 1.5, (
        "at a wide window the journal remembers everything and promotion "
        f"should add almost nothing, but the file claims {gain_loose:.1f}x"
    )


def test_the_promoted_arm_does_not_depend_on_the_window() -> None:
    """That is the property, stated as a number rather than a paragraph."""
    sweep = _got()["window_sweep"]
    values = [v["promoted_wasted_usd"] for v in sweep.values()]

    assert max(values) - min(values) < 0.05, (
        f"the promoted arm moved with the journal's window ({values}), which "
        "would mean it is reading the window after all"
    )


def test_it_says_it_is_a_simulation() -> None:
    """No model, no money. Anything else would be the overclaim."""
    got = _got()

    said = got["what_this_is_not"].lower()
    assert "no model" in said or "no real money" in said
    assert "simulation" in said
    assert "broken experiment" in said, (
        "the first version of this bench had no window and could not measure "
        "what it claimed to; that stays in the record"
    )


def test_the_agent_mix_is_stated_because_it_is_the_input_assumption() -> None:
    """The reliabilities are chosen. A reader has to be able to see them."""
    agents = _got()["agents"]

    assert len(agents) >= 3
    assert any(share < 0.2 for share in agents.values()), "no unreliable agent"
    assert any(share > 0.8 for share in agents.values()), "no reliable agent"


def test_no_result_is_written_into_the_script() -> None:
    said = SCRIPT.read_text(encoding="utf-8")
    body = said[said.index("def main("):]
    typed = re.findall(r"(?<![\w.])(\d+\.\d+)(?![\w.])", body)

    assert not typed, f"a result appears in the script rather than in the run: {typed}"


def test_every_seed_is_paired_between_the_arms() -> None:
    """Same day, same dice, one rule changed - or it is not a comparison."""
    got = _got()
    paired = got["promoted_vs_blind"]

    assert paired["seeds_with_less_waiting"] <= got["seeds"]
    assert paired["share_of_seeds"] == round(
        100 * paired["seeds_with_less_waiting"] / got["seeds"], 1
    )
