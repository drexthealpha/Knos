"""The two-minute pitch (docs/submission/pitch_script_120.md) and the links the submission gives a judge.

The cut is said at the script's own pace, WORDS_A_SECOND, with the render's own quiet between sentences and around each
scene, and ends before its limit, 120 seconds: the form's help text says the presentation runs up to two minutes. It
opens on the lead number, tells one transaction, speaks the founder's record, and every number in it is a fact in
docs/facts.json. `scripts/video/render.py --script` renders it. Every link the submission and the checklist give a
judge is the release tag, a file at that tag, or the site: never the repository's bare front page, which a cache can
hold as an older release. Everything here reads files; no voice, browser or network is used.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "scripts" / "video"
sys.path.insert(0, str(VIDEO))
sys.path.insert(0, str(ROOT / "scripts"))

import claims_check  # noqa: E402
import record  # noqa: E402
import render  # noqa: E402
import storyboard as sb  # noqa: E402
import voice  # noqa: E402

CUT = "docs/submission/pitch_script_120.md"
WORDS_A_SECOND = 2.5                   # the pace the cut is held to (150 words a minute, the render's estimate)
LIMIT = 120                            # seconds: the form's "Up to 2 minutes"
NUMBER = "Of 241 merged agent pull requests claiming passing tests, 9 failed a test, build, lint or type check."
WHY_SOLANA = "Money is released with no custodian, and the count is anchored where neither side can alter it."
SITE = "https://drexthealpha.github.io/Knos/"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def board() -> sb.Storyboard:
    return sb.from_script(read(CUT), ROOT / CUT)


def clock(text: str) -> int:
    minutes, secs = text.split(":")
    return int(minutes) * 60 + int(secs)


def at_pace(scene: sb.Scene, pad: tuple[float, float]) -> voice.SceneAudio:
    """The scene as the render assembles it, every sentence lasting its words at WORDS_A_SECOND."""
    sentences = voice.split_sentences(scene.say)
    pcms = [bytes(2 * round(len(s.split()) / WORDS_A_SECOND * voice.RATE)) for s in sentences]
    return voice.scene_audio(sentences, pcms, pad[0], pad[1], hold=scene.hold)


def version() -> str:
    return re.search(r'(?m)^version = "([^"]+)"', read("pyproject.toml")).group(1)


# ---- the cut ----------------------------------------------------------------------------------------------------------

def test_the_cut_is_said_in_under_two_minutes_at_its_pace_and_each_part_fits_before_the_next():
    cut = board()
    assert cut.limit == LIMIT and f"`limit: {LIMIT}`" in read(CUT)
    heads = re.findall(r"(?m)^## (\d)\. (.+) \((\d:\d\d)\)$", read(CUT))
    assert [h[1] for h in heads] == ["The finding", "One transaction, seven steps", "The founder", "The business", "Where it stands", "The ask"]
    assert [s.id for s in cut.scenes] == ["the-finding", "one-transaction-seven-steps", "the-founder", "the-business", "where-it-stands", "the-ask"]
    starts = [clock(h[2]) for h in heads] + [LIMIT]
    lengths = [at_pace(scene, cut.pad).seconds for scene in cut.scenes]
    assert starts[0] == 0
    for (_n, name, _c), start, end, seconds in zip(heads, starts, starts[1:], lengths):
        assert start + seconds <= end, f"{name}: {seconds:.1f} s from {start} s runs past {end} s"
    total = sum(lengths)
    assert total <= LIMIT - 5, f"{total:.1f} s at {WORDS_A_SECOND} words a second"         # five seconds to spare for the voice
    assert sb.estimate(cut) <= LIMIT - 5
    words = sum(sb.words(s.say) for s in cut.scenes)
    stated = int(re.search(r"about (\d+) words", read(CUT)).group(1))
    assert abs(stated - words) <= 10, (stated, words)


def test_the_cut_opens_on_the_number_tells_one_transaction_and_speaks_the_founders_record():
    said = {s.id: " ".join(s.say.split()) for s in board().scenes}
    assert said["the-finding"].startswith(NUMBER) and "GitHub's own record" in said["the-finding"]
    merged = json.loads(read("docs/backtest.json"))["reviewed"]["overall"]
    assert (merged["prs"], merged["test_or_build_check_failed"]["prs"]) == (241, 9)
    story = said["one-transaction-seven-steps"]
    assert story.startswith("Knos is the neutral meter for AI agent work: neither side keeps the count.")
    at = [story.find(f"{step}: ") for step in ("Agree", "Fails", "Passes", "Statement", "Replay", "Pay", "Verify")]
    assert -1 not in at and at == sorted(at)
    assert f"Why Solana? {WHY_SOLANA}" in story and "checks that signature itself" in story
    record_ = [s for s in voice.split_sentences(said["the-founder"]) if "first place" in s]
    assert len(record_) == 1 and "first place of 92 teams at the Sibyl Labs hackathon" in record_[0]
    facts = json.loads(read("docs/facts.json"))["facts"]
    assert any(f["say"] == ["92", "126.9"] and "Sibyl Labs" in f["what"] for f in facts)
    assert "first place of 92 teams in the Sibyl Labs" in " ".join(read("docs/TEAM.md").split())
    business = said["the-business"]
    assert "The check is free." in business and "released against a signed acceptance" in business and "The supplier never pays." in business
    stands = said["where-it-stands"]
    assert stands.startswith("Where it stands, in one sentence: Solana devnet, test money") and stands.count(". ") == 0
    numbers = read("docs/submission/NUMBERS.md")
    value = {what.split(":")[0].strip(): int(n) for what, n in re.findall(r"(?m)^\| \d \| ([^|]+) \| (\d+) \|", numbers)}
    assert f"paid {value['Payments between unrelated accounts']} times" in stands and "nobody has paid" in stands
    assert ("one other GitHub account" in stands) == (value["Outside payees"] == 1)
    assert said["the-ask"].startswith("The ask:") and "first buyer" in said["the-ask"]


def test_every_number_in_the_cut_is_a_fact_and_no_fee_or_zero_is_spoken():
    facts = json.loads(read("docs/facts.json"))["facts"]
    allowed = {s for f in facts for s in f["say"]}
    found = claims_check.numbers(CUT)
    assert found and [(tok, line) for tok, line in found if tok not in allowed] == []
    everything = " ".join(s.say for s in board().scenes).lower()
    assert not re.search(r"\d+(\.\d+)?\s*(%|percent|bps|basis points)", everything) and "cents" not in everything
    assert not re.search(r"\b0\b", everything)
    assert "**No fee is spoken as a number**" in " ".join(read(CUT).split())
    for sorry in ("sorry", "unfortunately", "admit", "only a", "just a"):
        assert sorry not in everything, sorry


def test_every_scene_shows_the_site_or_the_leaderboard():
    for scene in board().scenes:
        assert scene.kind == "url" and (scene.target.startswith(SITE) or scene.target == "https://hack.sibyllabs.org/leaderboard"), scene.id
    assert board().scenes[2].target == "https://hack.sibyllabs.org/leaderboard"


def test_each_page_has_drawn_before_it_is_photographed_and_the_business_part_shows_the_fee_the_program_answers():
    """The render photographs a page `wait:` seconds after it loads (1 by default). The Agent PR Index draws its table
    from its data seconds after the load (a render of 9 Oct opened on its empty frame for 6.8 s), the Numbers view its
    counts, and the price view asks knos_pay for the fee it charges: each of them waits, and the business part scrolls the
    price view down to the row that the program's answer fills (web/pricing.js drawLive, #bill-live), which the first
    screen of the view does not reach."""
    scenes = {s.id: s for s in board().scenes}
    assert scenes["the-finding"].target.endswith("#index") and scenes["the-finding"].wait >= 10
    assert scenes["where-it-stands"].target.endswith("#network") and scenes["where-it-stands"].wait >= 3
    business = scenes["the-business"]
    assert business.target.endswith("#pricing") and business.wait >= 15 and 400 <= business.scroll <= 700
    pricing = read("web/pricing.js")
    assert 'id="bill-live"' in pricing and "Fee on devnet today" in pricing and 'dl.dataset.source' in pricing
    assert all(s.scroll == 0 for s in board().scenes if s.id not in ("one-transaction-seven-steps", "the-business"))


# ---- the render takes the script ----------------------------------------------------------------------------------------

def test_the_render_estimates_the_script_under_its_own_limit(capsys):
    assert render.main(["--script", str(ROOT / CUT), "--estimate"]) == 0
    out = capsys.readouterr().out
    assert "6 scenes" in out and "the limit is 120 s" in out and "OVER" not in out


def test_a_script_is_a_storyboard_with_its_own_line_numbers():
    text = "# T\n\nprose\n<!-- `limit: 30` -->\n\n## 1. One (0:00)\n\n<!-- `show: url https://x.example/` -->\n> First words.\n> More: words.\n"
    got = sb.from_script(text)
    assert got.limit == 30 and [(s.id, s.say, s.kind, s.target) for s in got.scenes] == [("one", "First words. More: words.", "url", "https://x.example/")]
    try:
        sb.from_script(text + "\n## 2. Two (0:10)\n\n> Said, with nothing shown.\n")
    except sb.StoryboardError as why:
        assert str(why).startswith("line 12: scene two shows nothing"), why
    else:
        raise AssertionError("a scene that shows nothing is refused")
    try:
        sb.from_script("<!-- `limit: 200` -->\n## 1. A (0:00)\n> x\n<!-- show: still a.png -->\n")
    except sb.StoryboardError as why:
        assert "line 1: limit is between 1 and 180, not 200" in str(why)
    else:
        raise AssertionError("a limit over 180 seconds is refused")


def test_a_storyboard_and_a_script_together_or_neither_is_exit_2(capsys):
    assert render.main(["--script", str(ROOT / CUT), str(VIDEO / "sample.storyboard"), "--estimate"]) == 2
    assert render.main(["--estimate"]) == 2
    assert "give a storyboard or --script SCRIPT, one of the two" in capsys.readouterr().err


def test_the_render_holds_the_script_to_its_limit_and_records_nothing_past_it(tmp_path, monkeypatch, capsys):
    cut = board()
    calls: list[str] = []
    monkeypatch.setattr(render, "check_tools", lambda: None)
    monkeypatch.setattr(render.record, "record", lambda *a, **k: calls.append("record") or [])
    slow = [voice.scene_audio(["x"], [bytes(2 * 21 * voice.RATE)], 0.4, 0.6) for _ in cut.scenes]      # 22 s a scene: 132 s
    monkeypatch.setattr(render.voice, "speak", lambda *a, **k: ("piper:test", slow))
    assert render.main(["--script", str(ROOT / CUT), "--out", str(tmp_path)]) == 3
    assert "the limit is 120 s" in capsys.readouterr().err and calls == []

    paced = [at_pace(scene, cut.pad) for scene in cut.scenes]                                      # at the script's pace it passes
    monkeypatch.setattr(render.voice, "speak", lambda *a, **k: ("piper:test", paced))

    def recorded(*a, **k):
        calls.append("record")
        raise record.RecordError("stop here: the length was accepted")
    monkeypatch.setattr(render.record, "record", recorded)
    assert render.main(["--script", str(ROOT / CUT), "--out", str(tmp_path)]) == 1
    assert calls == ["record"] and "the length was accepted" in capsys.readouterr().err


# ---- the links a judge is given -----------------------------------------------------------------------------------------

def test_every_link_the_submission_gives_a_judge_is_the_tag_a_file_at_it_or_the_site():
    tag = f"https://github.com/drexthealpha/Knos/tree/v{version()}"
    judges = f"https://github.com/drexthealpha/Knos/blob/v{version()}/docs/JUDGES.md"
    assert (ROOT / "docs" / "JUDGES.md").is_file()
    for rel in ("docs/submission/SUBMISSION.md", "docs/submission/CHECKLIST.md", CUT):
        text = read(rel)
        bare = re.findall(r"https?://(?:www\.)?github\.com/drexthealpha/Knos(?![\w/-])", text)
        assert bare == [], f"{rel}: the bare repository address, which a cache can hold as an older release"
        for kind, ref in re.findall(r"github\.com/drexthealpha/Knos/(tree|blob)/([^/)\]\s`>]+)", text):
            assert ref == f"v{version()}", f"{rel}: {kind}/{ref} is not the release tag v{version()}"
    sub, checklist = read("docs/submission/SUBMISSION.md"), read("docs/submission/CHECKLIST.md")
    table = sub.split("## Which link goes in which field")[1].split("\n## ")[0]
    rows = dict(re.findall(r"(?m)^\| ([^|]+?) \| (.+) \|$", table))
    assert tag in rows["GitHub repository"] and judges in rows["any other place the form takes a link"]
    for video in ("Presentation video", "Product-demo video"):
        assert "YouTube, Loom or Vimeo" in rows[video]
    assert "pitch_script_120.md" in rows["Presentation video"] and "demo_script.md" in rows["Product-demo video"]
    live = sub.split("## liveProductLink")[1].split("\n## ")[0]
    assert live.strip().startswith(SITE) and tag in live and judges in live
    assert tag in checklist and judges in checklist and "YouTube, Loom or Vimeo" in checklist
    for founder in ("**Country**", "**Telegram**", "**Accelerator**"):
        assert founder in checklist, founder
    assert sub.index("## Which link goes in which field") < sub.index("## whatBuilding")
