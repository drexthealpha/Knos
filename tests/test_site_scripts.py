"""The two scripts and the shot list, as 0.3.20 shapes them (docs/submission/demo_script.md, pitch_script.md,
scripts/video/demo.shots.json, docs/STORY.md).

The demonstration is one transaction in seven beats and opens on the refusal: the first thing on screen after the
title. No fee is spoken as a number: the fee on screen is read from the chain while it is recorded. The
presentation opens on the finding, tells the same seven steps as one story, then the founder, the business, where it
stands in one sentence and the ask; no count is read out as a list of zeros. Everything here reads files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NUMBER = "Of 241 merged agent pull requests claiming passing tests, 9 failed a test, build, lint or type check."
OUTCOME = "Both sides close invoices on evidence both verify."
LIMITS = "Solana devnet, test money, one person holds every key, no outside review, and nobody has paid."
STEPS = ["one", "two", "three", "four", "five", "six", "seven"]
WHY_SOLANA = "Money is released with no custodian, and the count is anchored where neither side can alter it."
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


def test_the_demo_is_seven_beats_that_end_at_three_minutes_and_fit_their_time():
    demo = read("docs/submission/demo_script.md")
    assert "three minutes" in demo.splitlines()[0] and "seven beats" in demo.splitlines()[0]
    rows = re.findall(r"(?m)^\| (\w+) \| \((\d:\d\d)\) \| \((\d:\d\d)\) \| (.+) \|$", demo)
    assert [r[0] for r in rows] == STEPS
    assert seconds(rows[0][1]) == 0 and seconds(rows[-1][2]) == 180
    assert all(a[2] == b[1] for a, b in zip(rows, rows[1:]))                    # no gap, no overlap
    parts = said_in("docs/submission/demo_script.md")
    assert len(parts) == 7
    for (head, words), (_step, a, b, _what) in zip(parts, rows):
        assert f"({a}, {seconds(b) - seconds(a)} seconds)" in head, head
        assert len(words.split()) <= (seconds(b) - seconds(a)) * WORDS_A_SECOND + 5, (head, len(words.split()))
    total = sum(len(words.split()) for _h, words in parts)
    assert 390 <= total <= 450, total
    for part in demo.split("\n## ")[-7:]:
        assert "**On screen.**" in part and "\n> " in part and "**Must be visible.**" in part


def test_the_demo_leads_with_the_refusal_and_tells_the_seven_beats_in_order():
    demo = read("docs/submission/demo_script.md")
    flat = " ".join(demo.split())
    parts = demo.split("\n## ")[-7:]
    said = [words for _h, words in said_in("docs/submission/demo_script.md")]
    # the refusal is the first thing on screen after the title, and the first words are the number
    screen = " ".join(parts[0].split("**On screen.**")[1].split(">")[0].split())
    assert screen.startswith("The title. Then, first, the judge's comment on a pull request: payment withheld, and the reason.")
    assert "**The refusal leads.**" in demo and said[0].startswith(NUMBER) and "it was not paid" in said[0]
    assert "the price, the acceptance terms, the deadline and the remedy" in said[0] and "hashed into the order" in said[0]
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
    assert "the black-box check refused all 63" in said[1] and "this check" not in " ".join(said)
    assert said[2].startswith("The supplier corrects it.") and "the check passes" in said[2] and "GitHub signs that run." in said[2]
    assert "two independent records" in said[3] and "the same digest" in said[3] and "They reconcile" in said[3]
    assert "a token works once" in said[4] and said[4].endswith("No second payment.") and "`E_REPLAY`" in parts[4]
    assert said[5].startswith("The payment executes.") and "no company holds it" in said[5] and "exports as a file" in said[5]
    assert "the network off" in said[6] and "trusts neither side" in said[6] and "the deployment identity" in said[6] and "](../MANIFEST.md)" in parts[6]
    assert f"The limits, in one line: {LIMITS}" in said[6] and said[6].endswith("Neither side keeps the count.")
    # the fee is the live one: read from the chain while recording, and never a spoken number, so the script is true
    # before and after an approved upgrade changes what the public program ids charge
    assert "**No fee is spoken as a number.**" in flat and "The fee on screen is the one the program charges today, read from the chain." in said[5]
    for script in (said, [w for _h, w in said_in("docs/submission/pitch_script.md")]):
        everything = " ".join(script).lower()
        assert not re.search(r"\d+(\.\d+)?\s*(%|percent|bps|basis points)", everything) and "thirty cents" not in everything and "cents" not in everything
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
    assert "beats two and three are replays at higher speed" in flat and [s["moment"] for s in shots["shots"] if s["faster"]] == ["two", "three"]
    assert "money" in by["six"]["captions"] and "offline" in by["seven"]["captions"] and "no second payment" in by["five"]["shows"]
    assert "read from the chain" in by["six"]["shows"] and by["four"]["captions"] == []          # two local ledgers: no chain, no caption
    assert "docs/MANIFEST.md" in by["seven"]["shows"] and "limits as one line" in by["seven"]["shows"]


def test_the_pitch_opens_on_the_finding_tells_one_story_then_the_founder_the_zeros_and_the_ask():
    pitch = read("docs/submission/pitch_script.md")
    parts = said_in("docs/submission/pitch_script.md")
    heads = re.findall(r"(?m)^## (\d)\. (.+) \((\d:\d\d)\)$", pitch)
    assert [h[1] for h in heads] == ["The finding", "One transaction, seven steps", "The evidence", "The founder", "The business",
                                     "Where it stands", "The ask"]
    starts = [seconds(h[2]) for h in heads]
    assert starts == sorted(starts) and starts[0] == 0 and starts[-1] <= 170
    for (_n, _name, a), (_m, _next, b), (_h, words) in zip(heads, heads[1:], parts):          # each part fits before the next starts
        assert len(words.split()) <= (seconds(b) - seconds(a)) * WORDS_A_SECOND + 5, _name
    said = {head.split(". ", 1)[1].split(" (")[0]: words for head, words in parts}
    total = sum(len(w.split()) for w in said.values())
    assert 300 <= total <= 430 and total / WORDS_A_SECOND < 180, total                        # under three minutes at the script's pace
    assert seconds(heads[-1][2]) + len(said["The ask"].split()) / WORDS_A_SECOND <= 180
    # the finding: the one number, then its basis (GitHub's record, agents' own claims), then the Index
    finding = said["The finding"]
    assert finding.startswith(NUMBER) and "GitHub's own record" in finding and "Agent PR Index" in finding
    merged = json.loads(read("docs/backtest.json"))["sample"]["merged"]["overall"]
    assert (merged["prs"], merged["any_check_failed"]["prs"]) == (241, 30)
    # ONE story: the seven steps of the one transaction, named in order, the same seven as the story and the demonstration
    story = said["One transaction, seven steps"]
    steps = [re.search(rf"\b{name}: ", story) for name in ("Agree", "Fails", "Passes", "Statement", "Replay", "Pay", "Verify")]
    at = [m.start() for m in steps if m]
    assert len(at) == 7 and at == sorted(at)
    assert "neutral meter for AI agent work: neither side keeps the count" in story and "no company holds it, and no oracle reports it" in story
    assert f"Why Solana? {WHY_SOLANA}" in story and "the same bill, line for line" in story
    assert "56 of 63" in said["The evidence"] and "the black-box check refused all 63" in said["The evidence"]
    # days to approve, not seconds to pay: the measured time, and the wait that is not measured, said as not measured
    assert "From merge to paid took 26 seconds at the median, on devnet." in said["The evidence"]
    assert "an invoice waits on the person who approves it, not on the payment" in said["The evidence"] and "we have not measured that wait" in said["The evidence"]
    # the founder's record, spoken in one sentence, as TEAM.md and the facts file state it
    record = [s for s in re.split(r"(?<=\.) ", said["The founder"]) if "first place" in s]
    assert len(record) == 1 and "first place of 92 teams at the Sibyl Labs hackathon" in record[0] and "shared memory for coding agents" in record[0]
    assert "Knos's earlier product" in record[0] and "first place of 92 teams in the Sibyl Labs" in " ".join(read("docs/TEAM.md").split())
    assert said["The founder"].startswith("I am one founder, and I built all of it.")
    model = said["The business"]
    assert "The check is free." in model and "released against a signed acceptance" in model
    assert "a fee the program collects, paid by the funder on top" in model and "The supplier never pays." in model
    assert "The rate on screen is the one the program charges today." in model and "**No fee is spoken as a number**" in " ".join(pitch.split())
    # where it stands: ONE sentence, with the outside payee as NUMBERS.md counts it; never a list of zeros in what is said
    stands = said["Where it stands"]
    assert stands.startswith("Where it stands, in one sentence: Solana devnet, test money, one person holds every key, no outside review")
    assert stands.count(". ") == 0 and stands.endswith(".") and "nobody has paid" in stands
    numbers = read("docs/submission/NUMBERS.md")
    value = {what.split(":")[0].strip(): int(n) for what, n in re.findall(r"(?m)^\| \d \| ([^|]+) \| (\d+) \|", numbers)}
    assert f"paid {value['Payments between unrelated accounts']} times, in test money" in stands
    assert ("one other GitHub account" in stands) == (value["Outside payees"] == 1)
    # the ask: what STORY.md asks for, said last
    assert said["The ask"].startswith("The ask.") and "first buyer" in said["The ask"] and "outside key holder" in said["The ask"]
    assert "outside key holder" in read("docs/STORY.md").split("## The ask")[1]
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
                      "Both sides make the same statement.", "A replay pays nothing.", "The payment executes.", "A verifier checks it offline."]
    assert len(titles) == len(STEPS)                                        # the story's beats are the script's seven
    round_ = json.loads(read("web/demo_data.json"))
    for tx in (round_["fund"]["tx"], round_["paid"]["tx"], round_["replay"]["tx"]):
        assert tx in story and tx in read("web/story.js")
