"""The two scripts and the shot list, as 0.3.19 shapes them (docs/submission/demo_script.md, pitch_script.md,
scripts/video/demo.shots.json, docs/STORY.md).

The demonstration is one task in six steps and opens on the refusal: the first thing on screen after the title. The
presentation is seven beats: buyer, problem, insight, evidence, team, business, and the limits in one sentence; no
count is read out as a list of zeros. Everything here reads files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NUMBER = "Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check."
OUTCOME = "Buyers and suppliers close invoices on evidence both can verify."
LIMITS = "Solana devnet, test money, one person holds every key, no outside review, and nobody has paid."
STEPS = ["one", "two", "three", "four", "five", "six"]
WORDS_A_SECOND = 2.5


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def seconds(clock: str) -> int:
    minutes, secs = clock.strip("()").split(":")
    return int(minutes) * 60 + int(secs)


def said_in(rel: str) -> list[tuple[str, str]]:
    """Each numbered section of a script with the words it has someone say."""
    out = []
    for part in read(rel).split("\n## ")[1:]:
        head = part.splitlines()[0]
        if re.match(r"\d\. ", head):
            out.append((head, " ".join(" ".join(line[1:].strip() for line in part.splitlines() if line.startswith(">")).split())))
    return out


def test_the_demo_is_six_steps_that_end_at_three_minutes_and_fit_their_time():
    demo = read("docs/submission/demo_script.md")
    assert "three minutes" in demo.splitlines()[0] and "six steps" in demo.splitlines()[0]
    rows = re.findall(r"(?m)^\| (\w+) \| \((\d:\d\d)\) \| \((\d:\d\d)\) \| (.+) \|$", demo)
    assert [r[0] for r in rows] == STEPS
    assert seconds(rows[0][1]) == 0 and seconds(rows[-1][2]) == 180
    assert all(a[2] == b[1] for a, b in zip(rows, rows[1:]))                    # no gap, no overlap
    parts = said_in("docs/submission/demo_script.md")
    assert len(parts) == 6
    for (head, words), (_step, a, b, _what) in zip(parts, rows):
        assert f"({a}, {seconds(b) - seconds(a)} seconds)" in head, head
        assert len(words.split()) <= (seconds(b) - seconds(a)) * WORDS_A_SECOND + 5, (head, len(words.split()))
    total = sum(len(words.split()) for _h, words in parts)
    assert 390 <= total <= 450, total
    for part in demo.split("\n## ")[-6:]:
        assert "**On screen.**" in part and "\n> " in part and "**Must be visible.**" in part


def test_the_demo_leads_with_the_refusal_and_tells_the_six_steps_in_order():
    demo = read("docs/submission/demo_script.md")
    flat = " ".join(demo.split())
    parts = demo.split("\n## ")[-6:]
    said = [words for _h, words in said_in("docs/submission/demo_script.md")]
    # the refusal is the first thing on screen after the title, and the first words are the number
    screen = " ".join(parts[0].split("**On screen.**")[1].split(">")[0].split())
    assert screen.startswith("The title. Then, first, the judge's comment on a pull request: payment withheld, and the reason.")
    assert "**The refusal leads.**" in demo and said[0].startswith(NUMBER) and "it was not paid" in said[0]
    assert "price and the acceptance terms" in said[0] and "hashed into the order" in said[0]
    from_table = (ROOT / "src" / "knos" / "ghwords.py").read_text(encoding="utf-8")
    refusal = "The change edits a test that already existed."
    # the words and the code are what the judge's refusal of an edited existing test gives, not a neighbouring row's
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from knos import ghwords, judge
    assert ghwords.code_of_reason(judge.REFUSALS["protected_test_edited"]) == "judge.protected-test-edited"
    assert ghwords.refusal("judge.protected-test-edited")[0] == refusal
    assert refusal in from_table and f'"{refusal}"' in " ".join(parts[1].split()) and "`judge.protected-test-edited`" in parts[1]
    assert "payment is withheld, with the reason" in said[1] and refusal[0].lower() + refusal[1:].rstrip(".") in said[1]
    assert "the condition passes" in said[2] and "two independent records" in said[2] and "They reconcile." in said[2]
    assert said[3].startswith("The payment executes.") and "a receipt it can carry anywhere" in said[3] and "the network off" in said[3]
    assert "a token works once" in said[4] and said[4].endswith("No second payment.") and "`E_REPLAY`" in parts[4]
    assert "exports as a file" in said[5] and "the deployment identity" in said[5] and "](../MANIFEST.md)" in parts[5]
    assert f"The limits, in one line: {LIMITS}" in said[5] and said[5].endswith("Neither side keeps the count.")
    assert len(re.findall(r"\b0\b", " ".join(said))) == 0                       # no zero is read out
    # where a step ran is said, and nobody outside is claimed
    for caption in ("Public program ids on Solana devnet", "Staging program ids on Solana devnet", "Local simulator: not devnet",
                    "Replay of a run recorded earlier", "Recorded at N times speed", "Solana devnet. Test USDC."):
        assert f'"{caption}"' in flat, caption
    assert "no buyer and no supplier outside Knos has run one" in flat


def test_the_shot_list_follows_the_script():
    shots = json.loads(read("scripts/video/demo.shots.json"))
    demo = read("docs/submission/demo_script.md")
    rows = re.findall(r"(?m)^\| (\w+) \| \((\d:\d\d)\) \| \((\d:\d\d)\) \|", demo)
    assert [(s["moment"], s["start"], s["end"]) for s in shots["shots"]] == rows
    assert shots["limit_seconds"] == 180 == seconds(shots["shots"][-1]["end"])
    round_ = json.loads(read("web/demo_data.json"))
    assert shots["program_ids"] == round_["ids"]                                # the label is the data file's, public or staging
    flat = " ".join(demo.split())
    for name, words in shots["captions"].items():
        if name not in ("offline",):
            assert words in flat, name
    for shot in shots["shots"]:
        assert set(shot) == {"moment", "start", "end", "kind", "faster", "captions", "shows"} and set(shot["captions"]) <= set(shots["captions"])
        assert ("replay" in shot["captions"]) == (shot["kind"] == "replay") and ("faster" in shot["captions"]) == shot["faster"], shot["moment"]
    by = {s["moment"]: s for s in shots["shots"]}
    assert "FIRST the judge's refusal" in by["one"]["shows"] and by["one"]["shows"].index("refusal") < by["one"]["shows"].index("issue")
    assert "steps two and three are replays at higher speed" in flat and [s["moment"] for s in shots["shots"] if s["faster"]] == ["two", "three"]
    assert "money" in by["four"]["captions"] and "offline" in by["four"]["captions"] and "no second payment" in by["five"]["shows"]
    assert "docs/MANIFEST.md" in by["six"]["shows"] and "limits as one line" in by["six"]["shows"]


def test_the_pitch_is_buyer_problem_insight_evidence_team_business_and_one_sentence_of_limits():
    pitch = read("docs/submission/pitch_script.md")
    parts = said_in("docs/submission/pitch_script.md")
    heads = re.findall(r"(?m)^## (\d)\. (.+) \((\d:\d\d)\)$", pitch)
    assert [h[1] for h in heads] == ["The buyer", "The problem", "The insight", "The evidence", "The team", "The business", "The limits"]
    starts = [seconds(h[2]) for h in heads]
    assert starts == sorted(starts) and starts[0] == 0 and starts[-1] <= 160
    said = {head.split(". ", 1)[1].split(" (")[0]: words for head, words in parts}
    total = sum(len(w.split()) for w in said.values())
    assert 300 <= total <= 430, total
    assert said["The buyer"].startswith(NUMBER) and "approves a supplier's invoice" in said["The buyer"]
    assert "cannot prove it" in said["The problem"]
    assert "Every vendor keeps its own count." in said["The insight"] and "neutral meter for AI agent work: neither side keeps the count" in said["The insight"]
    assert said["The insight"].endswith(OUTCOME) and "no company holds it, and no oracle reports it" in said["The insight"]
    assert "56 of 63" in said["The evidence"] and "refused all 63" in said["The evidence"] and "the same bill, line for line" in said["The evidence"]
    numbers = read("docs/submission/NUMBERS.md")
    value = {what.split(":")[0].strip(): int(n) for what, n in re.findall(r"(?m)^\| \d \| ([^|]+) \| (\d+) \|", numbers)}
    assert f"paid {value['Payments between unrelated accounts']} times on devnet, in test money" in said["The evidence"]
    assert ("one other GitHub account" in said["The evidence"]) == (value["Outside payees"] == 1)
    # the team, plainly: one founder, what shipped, and who owns commercial, security and operations
    team = said["The team"]
    assert team.startswith("The team is one founder.") and "I shipped all of it" in team
    assert "I own commercial, security and operations as well, and today nobody else does." in team
    assert "Before the hackathon period I had built a different product, a shared memory for coding agents" in team
    model = said["The business"]
    assert "one fee" in model and "The check is free." in model and "released against a signed acceptance" in model
    assert "thirty cents on every hundred dollars" in model and "paid by the funder on top" in model and "The supplier never pays." in model
    # the limits: ONE sentence, the last; never a list of zeros anywhere in what is said
    assert said["The limits"] == f"The limits, in one sentence: {LIMITS}"
    everything = " ".join(said.values())
    assert ": 0." not in everything and len(re.findall(r"\b0\b", everything)) == 0
    for sorry in ("sorry", "unfortunately", "admit", "only a", "just a"):
        assert sorry not in everything.lower(), sorry


def test_the_first_screen_and_the_story_say_the_same_things():
    page = read("web/index.html")
    hero = page.split('<div class="hero-words">')[1].split("</form>")[0]
    assert hero.index("<h1") < hero.index(OUTCOME) < hero.index('id="hero-fact"') < hero.index('id="front-door"')
    story = read("docs/STORY.md")
    titles = re.findall(r"(?m)^\d\. \*\*(.+?)\*\*", story.split("## The ask")[0])
    assert titles == ["Buyer and supplier agree one task.", "A claimed success fails the condition.", "Valid work passes.",
                      "The payment executes.", "A replay pays nothing.", "Accounts get an export."]
    round_ = json.loads(read("web/demo_data.json"))
    for tx in (round_["fund"]["tx"], round_["paid"]["tx"], round_["replay"]["tx"]):
        assert tx in story and tx in read("web/story.js")
