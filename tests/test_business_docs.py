"""The business and submission documents: the one sentence, the price book, the two-minute scripts, the fields' limits,
the numbers about outside use held to the repository's own data, and the words that stay out of them.

Everything here reads files. Nothing runs a program or opens the network.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS, SUB = ROOT / "docs", ROOT / "docs" / "submission"
ONE = "The neutral meter for AI agent work: neither side keeps the count."
SECOND = "Of first agent pull requests that claimed passing tests, 17.8% had a failed check"
OLD = "the neutral count and settlement for software work priced per outcome"
CARRY_ONE = ["docs/MARKET.md", "docs/WHY.md", "docs/COMPARE.md", "docs/PILOT.md", "docs/TEAM.md", "docs/submission/SUBMISSION.md",
             "docs/submission/pitch_script.md", "docs/submission/demo_script.md", "docs/submission/CRITERIA.md", "docs/submission/NUMBERS.md"]
MINE = [*CARRY_ONE, "docs/DISCLOSURE.md", "docs/GOVERNANCE.md", "docs/submission/DEPENDENCY.md", "docs/submission/INTERVIEWS.md",
        "docs/submission/weekly_update.md", "web/pricing.js", "web/price.js", "scripts/video/demo.shots.json"]
LIMIT_WORDS, LIMIT_FIELD = 300, 1000
MOMENTS = ["one", "two", "three", "four", "five", "six", "seven"]
BOOK = [
    ("Check", "pull request checked", "free, forever"),
    ("Meter", "evaluation", "10,000 a month free per organisation, then 0.05 USD; 0.02 on a committed-volume plan"),
    ("Verify", "dollar of outcome billing the count verifies",
     "0.5% to 1.0%, the greater of this and the Meter fee, capped per deliverable (proposed; nobody has bought it)"),
    ("Control", "organisation, per year", "Team 25,000 USD; Business 80,000; Enterprise from 250,000 (Enterprise is not deliverable yet: "
     "it needs single sign-on, private deployment and support that do not exist)"),
    ("Supplier connection", "supplier connected to a buyer, per year",
     "5,000 USD each beyond the first five; the buyer pays; a supplier never pays to be counted"),
    ("Pilot", "one buyer and its suppliers, 30 days",
     "2,500 USD, credited against the first year of Control (nobody has bought it; no legal entity to invoice from yet)"),
    ("Settle", "dollar settled, paid by the funder on top",
     "2.5% of the first 1,000, 1% from 1,000 to 50,000, 0.5% above; minimum 0.40. On devnet this is test money: zero revenue"),
    ("Index data, Advance, Assurance", "", "not offered"),
]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def flat(rel: str) -> str:
    """A document with its emphasis marks removed and one space between words: what a sentence is looked for in."""
    return " ".join(read(rel).replace("**", "").split())


def spoken(rel: str) -> list[str]:
    """The words a script has someone say: its lines that start with `>`."""
    return " ".join(line[1:].strip() for line in read(rel).splitlines() if line.startswith(">")).split()


def seconds(clock: str) -> int:
    minutes, secs = clock.strip("()").split(":")
    return int(minutes) * 60 + int(secs)


# ---- the one sentence ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("rel", CARRY_ONE)
def test_the_one_sentence_is_in_every_business_document_and_the_old_one_in_none(rel):
    text = flat(rel)
    assert ONE in text and OLD not in text


def test_the_submission_opens_with_the_sentence_and_its_second_line():
    lines = [line for line in read("docs/submission/SUBMISSION.md").splitlines() if line.strip()]
    assert lines[0].startswith("# ") and lines[1] == f"**{ONE}**" and lines[2] == SECOND + "."
    bench = json.loads(read("docs/bench.json"))["market"]["index"]["overall"]["first_pr_per_repo"]       # the second line's figure and its sample
    assert (bench["repos"], bench["any_check_failed"]["repos"], bench["any_check_failed"]["share"]) == (826, 147, 0.178)
    for rel in ("docs/MARKET.md", "docs/WHY.md"):
        assert SECOND in flat(rel) and "147 of 826" in flat(rel)


# ---- words that stay out -------------------------------------------------------------------------------------------------

def test_the_two_revenue_words_appear_only_in_a_sourced_figure_about_another_company():
    # spelled in halves, so that this file does not hold them
    word = re.compile(r"\b(?:bil" + r"lion|AR" + r"R)\b")
    for rel in MINE:
        for n, line in enumerate(read(rel).splitlines(), 1):
            if word.search(line):
                assert "https://" in line and rel == "docs/MARKET.md", f"{rel}:{n}: {line[:120]}"
    for fact in json.loads(read("docs/facts.json"))["facts"]:
        if word.search(json.dumps(fact, ensure_ascii=False)):
            assert fact.get("source", "").startswith("https://"), fact["what"]


def test_no_business_document_states_a_count_of_capabilities_or_claims_what_does_not_exist():
    counted = re.compile(r"\b\d+ capabilities\b|\bcapabilities: \d")
    untrue = re.compile(r"\bour customers?\b|\baudited by\b|\bsigned letters? of intent\b(?! .{0,40}\b(?:no|none|0)\b)", re.I)
    for rel in MINE:
        if rel.endswith(".md"):
            text = flat(rel)
            assert not counted.search(text), rel
            assert not untrue.search(text), (rel, untrue.search(text).group(0))
    for rel in ("docs/MARKET.md", "docs/COMPARE.md", "docs/submission/CRITERIA.md", "docs/submission/demo_script.md", "docs/submission/NUMBERS.md"):
        assert "CAPABILITIES.md" in read(rel), rel


# ---- the price book ------------------------------------------------------------------------------------------------------

def test_the_price_book_is_the_eight_lines_in_order_with_its_rule():
    market = read("docs/MARKET.md")
    rows = [f"| {line} | {unit}{' ' if unit else ''}| {price} |" for line, unit, price in BOOK]
    assert "\n".join(["| Line | Unit | Price |", "| --- | --- | --- |", *rows]) in market
    assert "**The rule: Knos never charges the party being rated.**" in market
    js = read("web/price.js")
    for line, unit, _price in BOOK:
        assert f'["{line}", "{unit}", ' in js, line


def test_the_unit_problem_is_said_in_two_sentences_and_with_no_revenue_total():
    market = flat("docs/MARKET.md")
    said = ("A flat price per evaluation cannot grow with the value it verifies: an evaluation that accepts a 12 USD change and one that "
            "accepts a 40,000 USD milestone would cost the same 0.02 USD. So Verify is proposed as a price on the dollar of outcome billing "
            "the count verifies, with the Meter fee as its floor and a cap per deliverable so that the bill stays forecastable.")
    assert said in market
    for total in ("1,000 million", "50 " + "bil" + "lion", "evaluations a year would", "6,000 paying", "3,000 organisations", "4,000 organisations"):
        assert total not in market, total


def test_the_measured_twelve_percent_is_stated_as_what_the_sample_shows_and_not_as_a_saving():
    merged = json.loads(read("docs/backtest.json"))["sample"]
    assert merged["source"] == "docs/agent_pr_ci.json" and (merged["merged"]["overall"]["prs"], merged["merged"]["overall"]["any_check_failed"]["prs"]) == (241, 30)
    prs = json.loads(read("docs/agent_pr_ci.json"))["prs"]
    assert len(prs) >= merged["prs"]                                    # the pull requests the count is made from are in the file the page names
    market = flat("docs/MARKET.md")
    assert "Of 241 merged agent pull requests whose description said tests or CI pass, 30 had a failed check at the head commit: 12.4%" in market
    assert "A buyer paying per merge on that sample would have paid for 30 changes with a failed check." in market
    assert "It is not a promise that any buyer saves" in market and "agent_pr_ci.json" in market and "backtest.json" in market
    for rel in MINE:
        assert not re.search(r"(?:take|save|cut)s? 12(?:\.4)?% off", flat(rel) if rel.endswith(".md") else read(rel)), rel


def test_market_builds_the_market_from_accounts_and_lists_the_moats_in_order_each_with_a_measure():
    market = flat("docs/MARKET.md")
    assert "qualified organisations × contract value + billable evaluations × realised price" in market
    for condition in ("Measurable spend", "Acceptance criteria explicit enough to write down", "A buyer with authority", "A problem worth another system"):
        assert condition in market, condition
    moats = ["| 1 | Supplier reuse |", "| 2 | The terms standard, cited by hash |", "| 3 | The delivery record |", "| 4 | Neutrality |"]
    at = [market.index(m) for m in moats]
    assert at == sorted(at) and "| order | what would have to be earned | why code alone does not give it | how it would be measured | today |" in market
    steps = ["1. Land in shadow mode", "2. Convert on the first disputed line", "3. Expand by supplier", "4. Expand by vertical", "5. Expand by usage"]
    at = [market.index(s) for s in steps]
    assert at == sorted(at)
    assert "40 organisations on the Team tier at 25,000 USD are 1 million USD a year of platform revenue. 125 on the Business tier at 80,000 USD are 10 million." in market
    assert 40 * 25_000 == 1_000_000 and 125 * 80_000 == 10_000_000
    assert "## 8. Devnet is Knos's test mode" in read("docs/MARKET.md")
    assert "| can be real while the programs stay on devnet | is a demonstration |" in market and "Every settle fee: test money, zero revenue." in market
    # the competition is stated with its sources, and the difference is the independence
    for link in ("https://aws.amazon.com/bedrock/agentcore/pricing/", "https://stripe.com/billing/pricing"):
        assert link in read("docs/MARKET.md") and link in read("docs/COMPARE.md"), link
    assert 'So "we meter agents and move payments" is not a difference.' in market
    assert "independent acceptance across vendors, including the disagreements" in market


def test_the_pilot_is_credited_against_control_and_starts_in_shadow_mode():
    pilot = flat("docs/PILOT.md")
    assert "The price is credited against the first year of Control." in pilot and "22,500 USD" in pilot and 25_000 - 2_500 == 22_500
    assert "## How it starts: shadow mode" in read("docs/PILOT.md") and "A Pilot starts in shadow mode." in pilot
    assert "No shadow count has been run with anyone" in pilot and "nobody has bought it" in pilot.lower()


# ---- the two scripts -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("rel", ["docs/submission/pitch_script.md", "docs/submission/demo_script.md"])
def test_a_script_is_two_minutes_of_speech_at_most(rel):
    words = spoken(rel)
    assert 150 < len(words) <= LIMIT_WORDS, f"{rel}: {len(words)} spoken words"
    assert "two minutes" in read(rel).splitlines()[0]


def test_the_demo_is_one_buyers_story_in_seven_moments_that_end_at_two_minutes():
    demo = read("docs/submission/demo_script.md")
    rows = re.findall(r"(?m)^\| (\w+) \| (\(\d:\d\d\)) \| (\(\d:\d\d\)) \| (.+) \|$", demo)
    assert [r[0] for r in rows] == MOMENTS
    assert seconds(rows[0][1]) == 0 and seconds(rows[-1][2]) == 120
    assert all(seconds(a[2]) == seconds(b[1]) for a, b in zip(rows, rows[1:]))            # no gap and no overlap
    heads = re.findall(r"(?m)^## (\d)\. .+ \((\d:\d\d), (\d+) seconds\)$", demo)
    assert [int(h[0]) for h in heads] == list(range(1, 8))
    assert [(seconds(h[1]), int(h[2])) for h in heads] == [(seconds(r[1]), seconds(r[2]) - seconds(r[1])) for r in rows]
    for part in demo.split("\n## ")[-7:]:                                                 # every moment says what is shown, said and must be visible
        assert "**On screen.**" in part and "\n> " in part and "**Must be visible.**" in part
    story = ["a billed change with a failed check", "fixes the budget and the terms", "is refused, with the reason", "the record and a devnet payment",
             "a replay cannot pay twice; both sides derive the same statement", "verifies with no chain; the remaining trust is shown",
             "what is true today about outside use, and the offer"]
    assert [what for (_m, _a, _b, what), want in zip(rows, story) if want not in what] == []
    # 0.3.16 is released before the pending upgrade executes: what needs the newer builds ran on staging ids, and says so
    assert "**Every moment says on which program ids it ran.**" in demo and "No moment is shown as a run on the public program ids that did not run there." in " ".join(demo.split())
    assert '"Staging program ids on Solana devnet"' in " ".join(demo.split()) and "**A moment whose capability has run nowhere is cut, not staged.**" in demo
    assert '"Replay of a run recorded earlier"' in demo and '"Recorded at N times speed"' in " ".join(demo.split())


def test_the_shot_list_is_the_script_and_captions_every_replay_and_every_faster_shot():
    shots = json.loads(read("scripts/video/demo.shots.json"))
    demo = read("docs/submission/demo_script.md")
    rows = re.findall(r"(?m)^\| (\w+) \| \((\d:\d\d)\) \| \((\d:\d\d)\) \|", demo)
    assert [(s["moment"], s["start"], s["end"]) for s in shots["shots"]] == rows
    assert shots["limit_seconds"] == 120 == seconds(shots["shots"][-1]["end"]) and shots["program_ids"] == "staging"
    assert shots["captions"]["staging"] in " ".join(demo.split())                       # the staging caption is the script's own words
    for shot in shots["shots"]:
        assert set(shot["captions"]) <= set(shots["captions"])
        assert ("replay" in shot["captions"]) == (shot["kind"] == "replay") and ("faster" in shot["captions"]) == shot["faster"], shot["moment"]
    assert shots["captions"]["replay"] in demo and shots["captions"]["faster"] in " ".join(demo.split()) and shots["captions"]["first"] in " ".join(demo.split())
    # the moments the script says are replays are the ones the list marks
    assert "moments three and four are replays at higher speed" in " ".join(demo.split())
    assert [s["moment"] for s in shots["shots"] if s["kind"] == "replay"] == ["three", "four"]


# ---- the submission's fields and its numbers ---------------------------------------------------------------------------

def fields() -> dict[str, str]:
    text = read("docs/submission/SUBMISSION.md")
    parts = re.split(r"(?m)^## ([a-z][A-Za-z]+)$", text)[1:]
    return {name: " ".join(line for line in body.splitlines() if not (line.startswith("*") and line.rstrip().endswith("*"))).strip()
            for name, body in zip(parts[::2], parts[1::2])}


def test_every_field_of_the_form_is_under_its_limit():
    got = fields()
    assert list(got) == ["whatBuilding", "whyNow", "repoContext", "marketValidation", "traction", "competition", "monetization", "teamCommitment",
                         "externalContributors", "legalEntity", "investmentReceived", "liveToken", "liveProductLink", "chains", "chainUsage"]
    assert {name: len(" ".join(body.split())) for name, body in got.items() if len(" ".join(body.split())) >= LIMIT_FIELD} == {}
    assert got["whatBuilding"].startswith(ONE)
    assert "Knos never charges the party being rated." in " ".join(got["monetization"].split())
    assert "None yet." in got["marketValidation"] and "No traction is claimed" in got["traction"]


def test_the_numbers_table_states_the_value_of_each_as_the_repository_has_it():
    text = read("docs/submission/NUMBERS.md")
    assert "[[stat:" not in text                                                            # values, and no slot's name in their place
    table = text[text.index("<!-- bench:outside-use -->"):text.index("<!-- /bench:outside-use -->")]
    rows = {}
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0].isdigit():
            assert cells[2].isdigit() and cells[3], line
            rows[int(cells[0])] = (cells[1], int(cells[2]))
    assert sorted(rows) == list(range(1, 10))
    assert [rows[n][0].split(":")[0].strip() for n in sorted(rows)] == [
        "Outside funders", "Outside repositories", "Outside payees", "Payments between unrelated accounts", "Buyer interviews held",
        "Letters of intent", "Reproductions signed by GitHub", "Outside programs reading the verifier", "Shadow counts published"]
    bench = json.loads(read("docs/bench.json"))
    outside, release = bench["devnet"]["stats"]["outside"], bench["release"]
    assert rows[1][1] == outside["funders"] and rows[2][1] == outside["funded"]
    assert rows[4][1] == release["payments_between_unrelated_accounts"]["value"]
    payees = set(re.findall(r"to another GitHub account \((\d+)\)", release["payments_between_unrelated_accounts"]["source"]))
    assert rows[3][1] == len(payees) == 1
    reports = [p.name for p in (ROOT / "reproductions").glob("*.json")]
    assert rows[7][1] == len(reports)
    reproduced = [c["id"] for c in json.loads(read("docs/capabilities.json"))["capabilities"] if c["stage"] == "reproduced"]
    assert (reproduced == []) == (reports == [])
    # what only a person can supply is the constant a person keeps, and a zero until the disclosure stops saying there is none
    by_hand = json.loads(read("docs/facts.json"))["by_hand"]
    disclosure = flat("docs/DISCLOSURE.md")
    for n, name, sentence in ((5, "buyer_interviews_held", "No buyer has been interviewed."), (6, "letters_of_intent", "No letter of intent."),
                              (8, "outside_programs_reading_the_verifier", "No outside program is known to read the verifier."),
                              (9, "shadow_counts_published", "No shadow count.")):
        assert sentence in disclosure and rows[n][1] == by_hand[name] == 0, n


def test_criteria_answers_each_factor_on_the_page_in_one_paragraph():
    text = read("docs/submission/CRITERIA.md")
    seven = text.split("## The seven factors on Colosseum's page")[1].split("## The six criteria in the rules")[0]
    parts = re.split(r"(?m)^### (.+)$", seven)[1:]
    assert parts[::2] == ["Founder + Market Fit", "Insight", "Product + Execution", "Potential Market Size", "Founder Communication", "Viability", "Traction"]
    for name, body in zip(parts[::2], parts[1::2]):
        blocks = [b for b in body.strip().split("\n\n") if b.strip()]
        assert len(blocks) == 2 and blocks[0].startswith('> "') and not blocks[1].startswith(">"), name       # the quoted question, then one paragraph
    fit = parts[1]
    assert "there is no fit yet" in " ".join(fit.split()) and "pseudonymous" in fit and "none is hired" in " ".join(fit.split())
    assert "https://colosseum.com/hackathon" in text


def test_governance_and_team_state_their_plans_as_plans():
    governance, team = flat("docs/GOVERNANCE.md"), flat("docs/TEAM.md")
    assert "Three plans are on this page, and none of them is a fact." in governance
    for done in ("nothing: nobody has been asked", "nothing: the organisation does not exist", "nothing: no review has been done or commissioned"):
        assert done in governance, done
    assert "is frozen after an outside review, and not before" in governance
    assert "an organisation account with two owners" in governance
    assert "## What an outside key holder would do" in read("docs/TEAM.md") and "Nobody holds this role and nobody has been asked." in team
    assert "None of the three is hired, engaged, committed or in conversation." in team and "Create a GitHub organisation with two owners" in team
    assert [h for h in re.findall(r"(?m)^### (\d)\. ", read("docs/TEAM.md"))] == ["1", "2", "3"]
