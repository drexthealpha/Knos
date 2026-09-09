"""The one measurement here taken from real agent behaviour rather than a model.

It is also the easiest one to overstate, which is what these tests are for.
The figure says two or more agent sessions were doing something in the same
window; it does not say they collided, and it is one developer's machine. A
reader who takes it for a collision rate has been misled, so the file has to
keep saying both things in its own words.

Nothing from a transcript may appear in it either. The transcripts are the
user's own work, and this publishes counts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "concurrency.py"
EVIDENCE = ROOT / "docs" / "evidence" / "concurrency.json"


def _got() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_it_says_what_it_does_not_measure() -> None:
    """The distinction the whole file rests on.

    Concurrency is necessary for a collision and does not imply one. A number
    presented without that sentence is a collision rate, and this is not one.
    """
    got = _got()

    assert "what_this_does_not_measure" in got
    said = got["what_this_does_not_measure"].lower()
    assert "collision" in said
    assert "one machine" in said or "one developer" in said, (
        "a sample of one has to say it is a sample of one"
    )


def test_more_than_one_window_size_is_published() -> None:
    """A share that only holds at one width is an artefact of that width."""
    windows = _got()["windows"]

    assert len(windows) >= 3, "one window size invites exactly the question it dodges"
    shares = [w["percent"] for w in windows.values()]
    assert max(shares) - min(shares) < 5, (
        f"the share swings with the window size ({shares}); if it does, the "
        "headline figure is a property of the bucketing rather than the day"
    )


def test_every_share_is_derivable_from_the_counts_beside_it() -> None:
    for name, window in _got()["windows"].items():
        working = window["windows_with_any_agent_working"]
        shared = window["windows_with_two_or_more"]
        assert working > 0, name
        assert abs(window["percent"] - 100 * shared / working) < 0.1, name
        assert shared <= working, f"{name}: more shared windows than windows"


def test_no_transcript_content_is_published() -> None:
    """It reads the user's own sessions. It publishes counts.

    Session identifiers are not in there either - they are not secret, but
    they are not a measurement, and a file that carries them invites the
    question of what else it carried.
    """
    raw = EVIDENCE.read_text(encoding="utf-8")

    # A session id is a uuid; a turn would bring prose with it.
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", raw), "a session id is published"
    got = _got()
    assert set(got["windows"]) and all(
        isinstance(v, dict) for v in got["windows"].values()
    )


def test_no_share_is_written_into_the_script() -> None:
    said = SCRIPT.read_text(encoding="utf-8")
    body = said[said.index("def main("):]
    typed = re.findall(r"(?<![\w.])(\d+\.\d+)(?![\w.])", body)

    assert not typed, f"a figure appears in the script rather than in the count: {typed}"


def test_it_reports_a_machine_with_no_sessions_rather_than_zero() -> None:
    """Zero windows is not zero concurrency, it is no data.

    A CI runner has no agent transcripts. Writing 0% from that would be the
    most quietly dishonest number this repo could produce, so the script says
    there is nothing to count and writes nothing at all.
    """
    said = SCRIPT.read_text(encoding="utf-8")

    assert "nothing to count" in said
    assert said.index("nothing to count") < said.index("windows = {"), (
        "the empty case has to return before anything is computed or written"
    )
    # The count itself is shared with `knos why` now, and its own empty case
    # is covered in test_why.py: no turns gives back no windows at all,
    # rather than a zero to divide by.



def test_the_guide_quotes_the_counts_the_file_actually_holds() -> None:
    """These grow every time anybody works on the machine.

    Which makes a frozen copy in the guide the fastest-staling number in the
    repository - the same fault as a rule cited at a line its file no longer
    says. The script that counts them rewrites the block that quotes them, and
    this is what notices when it has not.
    """
    guide = (ROOT / "docs" / "JUDGE_GUIDE.md").read_text(encoding="utf-8")
    block = guide[
        guide.index("<!-- counted: docs/evidence/concurrency.json -->") :
        guide.index("<!-- /counted -->")
    ]
    got = _got()

    wrong = []
    for width in (1, 5, 15, 30):
        one = got["windows"][f"{width}_minute"]
        said = f"{one['windows_with_two_or_more']:,} ({one['percent']}%)"
        if said not in block:
            wrong.append(f"{width}-minute: the file says {said}")

    assert not wrong, (
        "the judge guide quotes counts concurrency.json no longer holds; run "
        "`python scripts/concurrency.py` rather than editing them:\n  "
        + "\n  ".join(wrong)
    )
    assert f"{got['turns']:,} real turns across {got['sessions']} sessions" in guide
