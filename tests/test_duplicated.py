"""The break-even has to keep being measured, and has to keep being unflattering.

`spend.json` and `contention.json` are simulations, and their ratios follow
from numbers somebody chose. `duplicated.json` is the one piece of evidence
here whose figures are durations measured on the machine that wrote it, so the
thing worth protecting is not any value - it is that no value can be typed in,
and that the discouraging numbers stay in the file beside the encouraging one.

The first run of that script reported a ratio of nineteen to one *against* the
product. Keeping the cold-process number, and the two break-evens, is what
stops the file becoming a list of the measurements that came out well.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "duplicated.py"
EVIDENCE = ROOT / "docs" / "evidence" / "duplicated.json"


def _got() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_all_four_durations_are_published_not_just_the_good_one() -> None:
    """The cold-process figure is the one that makes knos look slow.

    Reporting only the compare-and-swap would be true and misleading: nobody
    runs a compare-and-swap, they run a command or a tool call.
    """
    seconds = _got()["seconds"]

    for name in (
        "one_file_read_and_parsed",
        "refusal_store_already_open",
        "refusal_including_opening_the_store",
        "refusal_from_a_cold_process",
    ):
        assert name in seconds, f"{name} is missing from the published measurements"
        assert seconds[name] > 0


def test_the_ratio_is_derivable_from_the_durations_beside_it() -> None:
    """A published ratio that its own numbers do not produce was typed in."""
    got = _got()
    seconds = got["seconds"]

    expected = seconds["one_file_read_and_parsed"] / seconds["refusal_store_already_open"]

    assert abs(got["times_cheaper_to_refuse_than_to_duplicate_one_file"] - expected) < 0.5


def test_both_break_evens_are_derivable_too() -> None:
    got = _got()
    seconds = got["seconds"]
    even = got["files_of_duplicated_work_to_break_even"]

    per_call = seconds["refusal_including_opening_the_store"] / seconds["one_file_read_and_parsed"]
    per_command = seconds["refusal_from_a_cold_process"] / seconds["one_file_read_and_parsed"]

    assert abs(even["per_mcp_tool_call"] - per_call) < 0.5
    assert abs(even["per_cold_command"] - per_command) < 0.5


def test_the_break_even_is_reported_at_all() -> None:
    """Where the product stops being worth it is part of measuring it.

    Below the break-even, coordinating costs more than colliding. A tool that
    cannot say where that point is has not been measured, and a judge is
    entitled to assume the worst.
    """
    even = _got()["files_of_duplicated_work_to_break_even"]

    assert even["per_cold_command"] > even["per_mcp_tool_call"], (
        "a cold command opens the store from nothing and must cost more than a "
        "tool call in a live session; if it does not, one of them is wrong"
    )


def test_no_duration_is_written_into_the_script() -> None:
    """Every figure in that file has to come from a clock.

    The check the waitlist number gets, for the same reason: this is the one
    place where an encouraging number would be worth points right up until it
    is a disqualification.
    """
    said = SCRIPT.read_text(encoding="utf-8")
    body = said[said.index("def main("):]
    # Digits that are not an index, a rounding precision, or a zero.
    typed = re.findall(r"(?<![\w.])(\d+\.\d+)(?![\w.])", body)

    assert not typed, f"a duration appears in the script rather than in the clock: {typed}"


def test_the_file_says_what_it_does_not_prove() -> None:
    """It measures the cost of preventing a collision, not the value of doing so.

    How often two agents collide is not something this machine can measure,
    and a script that quietly implied it had would be the same overclaim the
    simulations are already discounted for.
    """
    got = _got()

    assert "does not say" in " ".join(got).lower() or "what_this_does_not_say" in got
    said = got["what_this_does_not_say"].lower()
    assert "floor" in said, "the measured work is a floor and has to say so"


def test_the_guide_quotes_the_numbers_the_file_actually_holds() -> None:
    """A frozen figure beside a file CI regenerates every day goes stale.

    That is the same fault as a rule cited at a line its file no longer says,
    and it would be worse here: a judge reading the guide offline has no way
    to notice. So the block is fenced and held to the JSON it names, and the
    break-evens in the prose are held with it.
    """
    guide = (ROOT / "docs" / "JUDGE_GUIDE.md").read_text(encoding="utf-8")
    block = guide[
        guide.index("<!-- measured: docs/evidence/duplicated.json -->") :
        guide.index("<!-- /measured -->")
    ]
    got = _got()
    seconds = got["seconds"]

    wrong = []
    for key, decimals in (
        ("refusal_store_already_open", 2),
        ("refusal_including_opening_the_store", 1),
        ("refusal_from_a_cold_process", 0),
        ("one_file_read_and_parsed", 1),
    ):
        said = f"{seconds[key] * 1000:.{decimals}f} ms"
        if said not in block:
            wrong.append(f"{key}: the file says {said}")

    assert not wrong, (
        "the judge guide quotes durations duplicated.json no longer holds; "
        "regenerate it rather than editing the numbers:\n  " + "\n  ".join(wrong)
    )

    for key in ("per_mcp_tool_call", "per_cold_command"):
        said = str(got["files_of_duplicated_work_to_break_even"][key])
        assert said in guide, f"the break-even {key} in the guide is not {said}"
