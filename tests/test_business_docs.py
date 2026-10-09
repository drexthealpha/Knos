"""The business and submission documents: the one sentence, the price book, the two scripts (a three-minute demonstration and a presentation), the fields' limits,
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
NUMBER = "Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check"
SECOND = "Of first agent pull requests that claimed passing tests, 17.8% had a failed check"
OLD = "the neutral count and settlement for software work priced per outcome"
CARRY_ONE = ["docs/MARKET.md", "docs/WHY.md", "docs/COMPARE.md", "docs/PILOT.md", "docs/TEAM.md", "docs/submission/SUBMISSION.md",
             "docs/submission/pitch_script.md", "docs/submission/demo_script.md", "docs/submission/CRITERIA.md", "docs/submission/NUMBERS.md"]
MINE = [*CARRY_ONE, "docs/DISCLOSURE.md", "docs/GOVERNANCE.md", "docs/submission/DEPENDENCY.md", "docs/submission/INTERVIEWS.md",
        "docs/submission/weekly_update.md", "web/pricing.js", "web/price.js", "scripts/video/demo.shots.json"]
LIMIT_WORDS, LIMIT_FIELD = 300, 1000
BOOK = [tuple(row) for row in json.loads((ROOT / "tests" / "data" / "billing_vectors.json").read_text(encoding="utf-8"))["lines"]]     # the six lines of Price book 3, as src/knos/billing.py and web/price.js hold them
FIRST = "Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check"


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


def test_the_submission_opens_with_the_sentence_the_number_and_the_second_number():
    lines = [line for line in read("docs/submission/SUBMISSION.md").splitlines() if line.strip()]
    assert lines[0].startswith("# ") and lines[1] == f"**{ONE}**" and lines[2] == NUMBER + "." and lines[3].startswith(SECOND)
    merged = json.loads(read("docs/backtest.json"))["sample"]["merged"]["overall"]
    assert (merged["prs"], merged["any_check_failed"]["prs"]) == (241, 30)
    for rel in ("docs/submission/pitch_script.md", "docs/submission/demo_script.md"):                    # each script's first spoken words are the number
        assert " ".join(spoken(rel)).startswith(NUMBER + "."), rel
    bench = json.loads(read("docs/bench.json"))["market"]["index"]["overall"]["first_pr_per_repo"]       # the second line's figure and its sample
    assert (bench["repos"], bench["any_check_failed"]["repos"], bench["any_check_failed"]["share"]) == (826, 147, 0.178)
    for rel in ("docs/MARKET.md", "docs/WHY.md"):
        assert SECOND in flat(rel) and "147 of 826" in flat(rel)
        assert flat(rel).index(FIRST) < flat(rel).index(SECOND)            # the one number comes first, the 17.8% second


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

def test_the_price_book_is_the_six_lines_in_order_with_its_rule_and_the_billing_rule():
    market = read("docs/MARKET.md")
    rows = ["| " + " | ".join(row) + " |" for row in BOOK]
    assert "\n".join(["| Line | Unit | Price | Who pays | Where it is enforced |", "| --- | --- | --- | --- | --- |", *rows]) in market
    assert "**The rule: Knos never charges the party being rated.**" in market
    js = read("web/price.js")
    for line, unit, *_rest in BOOK:
        assert f'["{line}", "{unit}", ' in js, line
    assert [row[0] for row in BOOK] == ["Check", "Meter", "Acceptance", "Record", "Control", "Pilot"]
    said = " ".join(market.replace("**", "").split())
    assert "A month's invoice = Control + Meter + Acceptance on value reconciled off chain + Record lookups." in said
    for rule in ("Value released on chain paid its Acceptance fee there, to the program, at release. The invoice leaves it out.",
                 "No charge for a duplicate, an infrastructure failure or a retry Knos caused.",
                 "An accepted deliverable is counted once, however many evaluations it took.", "A rejection that ran correctly is an evaluation, not an outcome",
                 "Limits are shown before work starts", "Commitments are sold by the year and drawn down by use.", "There is no cap.",
                 "Connecting a supplier costs nothing.", "A commitment and the use it pays for are never both counted.",
                 "The rated party never pays for its rating, for a better score or for the resolution of a false verdict."):
        assert rule in said, rule
    from knos import billing
    assert billing.RULES["credit"] in said                                  # the credit rule is one sentence, the same in the code and the document
    # price book 3.1: the rate never goes below 0.20%, small tickets are netted, Record is priced per call
    for new in ("The rate never goes below 0.20%.", "The 0.10% tier above 10 million a month is withdrawn.", "No rate is lower than 0.20%.",
                "A payee's small outcomes of a period are one release: 0.30% of the netted amount, and the 0.05 floor once for the release.",
                "0.10 USD a lookup, paid per call by whoever reads it. There is no subscription."):
        assert new in said, new
    assert "0.10% above 10M" not in market and "or by subscription" not in market and "0.25 USD" not in market
    assert min(rate for _start, rate in billing.ACCEPT_TIERS) * 100 == billing.Decimal("0.20") and billing.RECORD_PRICE == billing.Decimal("0.10")
    assert "These are proposed prices. Nobody has paid any of them" in said
    assert "Nothing has been sold; there is no legal entity to invoice from; on devnet every fee is test money and zero revenue." in said


def test_the_lines_price_book_3_removed_are_in_no_price_document():
    gone = re.compile(r"\bVerify (?:charge|line|cap|is)|\| Verify \||\| Settle \||\| Supplier connection \||a Supplier connection|greater of Meter|capped at 250|cap of 250|0\.02 on an annual commitment|2\.5% of the first")
    for rel in ("docs/MARKET.md", "docs/PILOT.md", "docs/WHY.md", "docs/UNIT_COSTS.md", "web/pricing.js", "web/price.js", "src/knos/billing.py", "tests/data/billing_vectors.json"):
        found = gone.search(read(rel))
        assert not found, (rel, found.group(0))


def test_the_unit_problem_is_said_in_two_sentences_and_with_no_revenue_total():
    market = flat("docs/MARKET.md")
    said = ("A flat price per evaluation cannot grow with the value it accepts: an evaluation that accepts a 12 USD change and one that "
            "accepts a 40,000 USD milestone both cost 0.002 USD at the Meter. Acceptance is charged on the dollar, once, when a signed "
            "acceptance releases or reconciles it")
    assert said in market
    for total in ("1,000 million", "50 " + "bil" + "lion", "evaluations a year would", "6,000 paying", "3,000 organisations", "4,000 organisations",
                  "40 organisations", "125 on the Business", "of platform revenue", "8,000 customers", "free cash flow engine"):
        assert total not in market, total


def test_unit_costs_says_what_is_measured_what_is_a_budget_and_the_ceilings():
    raw, page = read("docs/UNIT_COSTS.md"), flat("docs/UNIT_COSTS.md")
    assert "UNIT_COSTS.md" in read("docs/README.md") and "[measured]" in page and "[budget, not measured]" in page
    for link in ("https://aws.amazon.com/bedrock/agentcore/pricing/", "https://docs.github.com/en/billing/reference/actions-runner-pricing",
                 "https://developers.cloudflare.com/r2/pricing/", "https://www.coingecko.com/en/coins/solana"):
        line = next(row for row in raw.splitlines() if link in row)
        assert "read 6 Oct 2026" in line, link
    # the ceilings are a tenth and a twentieth of each price
    for price, at90, at95 in (("0.002", "0.0002", "0.0001"), ("60.00", "6.00", "3.00"), ("3.00", "0.30", "0.15"), ("0.05", "0.005", "0.0025"),
                              ("0.10", "0.010", "0.005"), ("25,000", "2,500", "1,250"), ("100,000", "10,000", "5,000")):
        assert f"| {price} | {at90} | {at95} |" in raw, price
        value = float(price.replace(",", ""))
        assert abs(value * 0.10 - float(at90.replace(",", ""))) < 1e-9 and abs(value * 0.05 - float(at95.replace(",", ""))) < 1e-9
    # the measured figures are the repository's: lamports at the stated price of SOL, the bundle's bytes, the stage times
    sol = 120.82
    assert "| SOL | 120.82 USD |" in raw and f"{3 * sol / 1e9:.8f}" == "0.00000036" and f"{15_000 * sol / 1e9:.4f}" == "0.0018" and f"{60_000 * sol / 1e9:.4f}" == "0.0072"
    assert (ROOT / "tests" / "web" / "recorded" / "acceptance_bundle.json").stat().st_size == 16_332 and "| One acceptance bundle | 16,332 " in raw
    assert f"{16_332 / 1e9 * 0.015 * 84:.7f}" == "0.0000206" and "0.0000206" in raw
    load = read("docs/LOAD.md")
    assert "| evaluation | the start of the run to the token's comment | 5 | 16 s | 24 s |" in load and "| Solana transactions | 12 | 12 |" in load
    assert "Routine reconciliation must be self-service" in page and "It is not a saving for the customer" in page
    assert "1.50 USD per 1,000" in page and "The Meter costs a third more than the cloud's evaluation call." in page
    for adds in ("A count both sides can recompute.", "Deduplication.", "Retention.", "A signed acceptance."):
        assert adds in page, adds
    costs = json.loads(read("docs/unit_costs.json"))
    assert costs["sol_usd"]["usd"] == "120.82" and [costs["costs"][k]["usd"] for k in ("evaluation", "accepted_deliverable", "record_lookup", "control_year")] == ["0.00005", "0.10", "0.01", "15000"]
    assert "revenue 10,753.33, direct cost 1,260.20, gross margin 88.3%" in page


def test_unit_costs_states_the_three_leaks_with_their_sizes():
    """The Meter with the monthly batch as the default delivery and the free tier as acquisition cost; who earns what
    at the floor under both builds and what netting does to a 0.99 outcome; Control's margin said as gross."""
    raw, page = read("docs/UNIT_COSTS.md"), flat("docs/UNIT_COSTS.md")
    from knos import billing
    costs = json.loads(read("docs/unit_costs.json"))["costs"]
    sol = 120.82
    assert f"{(15_000 + 1_137_920) * sol / 1e9:.4f}" == "0.1393" == costs["pair_month"]["usd"] and "15,000 + 1,137,920 = 1,152,920 | 0.1393 |" in raw
    assert f"{1_488_440 * sol / 1e9:.2f}" == "0.18" == costs["payee_account"]["usd"]
    assert "the monthly batch is the default." in page and "110,000 × 0.00005 + 5 × 0.1393 = 6.20 USD a month" in page
    assert round(110_000 * 0.00005 + 5 * 0.1393, 2) == 6.20 and "12 × 100,000 × 0.00005 = 60 USD a year" in page and "That is acquisition cost" in page
    assert round(12 * (100_000 * 0.00005 + 5 * 0.1393), 2) == 68.36 and "make it 68.36" in page
    assert 0.00005 * 138_000 + 5 * 0.1393 <= 0.1 * 0.002 * 38_000 and "reaches 90% at 138,000 evaluations a month" in page
    for row in costs.values():                                             # two labels, and nothing in between
        assert row["kind"] in ("measured", "budget, not measured")
    for build in billing.floor_split():                                    # the two tables are what `knos bill margin` prints
        for r in build["rows"]:
            assert (f"| {r['amount']} | {r['fee']} | {r['share']} | {r['tip']} | {r['fee_owner']} | {r['first_tip']} | "
                    f"{r['first_relayer_net'].replace('-', '−')} | {r['first_fee_owner']} |") in raw, (build["build"], r["amount"])
    assert "the fee owner earns nothing on a release of 16.66 or less" in page and "first payment of 100.00 or less" in page
    n = billing.netting_example()
    assert (n["alone_share"], n["netted_share"], n["reaches_rate"]) == ("5.05%", "0.30%", 17)
    assert "| charged by itself | 0.05, the floor | 5.05% |" in raw and "| 0.30 for the release | 0.30% |" in raw and "From 17 such outcomes" in page
    assert "is a gross margin of 85%: gross, before" in page and "for 95%, 5,000" in page and 5_000 // 75 == 66 and "66 hours a year" in page
    assert (100_000 - 15_000) / 100_000 == 0.85 and "None of the three figures is measured." in page


def test_market_names_the_competitors_on_their_own_pages_and_says_metering_will_face_price_pressure():
    raw, market = read("docs/MARKET.md"), flat("docs/MARKET.md")
    for link, says in (("https://aws.amazon.com/bedrock/agentcore/pricing/", "1.50 USD per 1,000"), ("https://stripe.com/billing/pricing", "0.7% of billing volume"),
                       ("https://docs.stripe.com/agentic-commerce", "machine payments"), ("https://mergepay.fun", "No platform fee")):
        line = next(row for row in raw.splitlines() if link in row and row.startswith("|"))
        assert says in line and "7 Oct 2026" in line, link               # each confirmed on the vendor's own page that day
    assert "an authorization request at 0.000025 USD" in market and "Generic agent metering will face price pressure." in market
    three = raw.split("What Knos is that they are not, in three lines:")[1].split("**The difference")[0]
    assert len([row for row in three.splitlines() if row.startswith("- ")]) == 3 and "reproducible by anyone" in three
    assert "The benefit is measured in pilots, never derived from the public failed-check statistics." in market


def test_the_measured_twelve_percent_is_a_count_of_failed_checks_and_never_a_share_of_spend():
    merged = json.loads(read("docs/backtest.json"))["sample"]
    assert merged["source"] == "docs/agent_pr_ci.json" and (merged["merged"]["overall"]["prs"], merged["merged"]["overall"]["any_check_failed"]["prs"]) == (241, 30)
    prs = json.loads(read("docs/agent_pr_ci.json"))["prs"]
    assert len(prs) >= merged["prs"]                                    # the pull requests the count is made from are in the file the page names
    market = flat("docs/MARKET.md")
    assert "Of 241 merged agent pull requests whose description said tests or CI pass, 30 had a failed check at the head commit: 12.4%" in market
    assert "That is a count of failed checks, not of money." in market
    assert "It is not a promise that any buyer saves" in market and "agent_pr_ci.json" in market and "backtest.json" in market
    assert ("Both figures count failed checks. Neither is invoice leakage: a failed check is not always a failed test or a false claim, "
            "and neither says what share of any buyer's spend is lost.") in market
    lost = re.compile(r"(?:take|save|cut)s? 12(?:\.4)?% off|(?:12(?:\.4)?|17\.8)% (?:of (?:spend|billing|invoices?|the invoice)|leak)|"
                      r"(?:loses?|leaks?|overpa(?:ys?|id)|wastes?) (?:about |up to )?(?:12(?:\.4)?|17\.8)%|would have paid for 30", re.I)
    for rel in ("docs/MARKET.md", "docs/WHY.md", "docs/COMPARE.md", "docs/PILOT.md", "web/pricing.js", "web/price.js", "src/knos/billing.py"):
        found = lost.search(flat(rel) if rel.endswith(".md") else read(rel))
        assert not found, (rel, found.group(0))


def test_market_states_the_market_as_outcome_billed_work_and_sources_each_vendor_price_with_its_day():
    raw, market = read("docs/MARKET.md"), flat("docs/MARKET.md")
    assert "The market is agent work billed per outcome" in market and "A bounty on one issue is the smallest example of it" in market
    for link in ("https://www.intercom.com/pricing", "https://www.zendesk.com/pricing/", "https://www.salesforce.com/agentforce/pricing/",
                 "https://sourcegraph.com/changelog/agentic-batch-changes-ga", "DoubleVerify-Q4-FY25-Earnings-Release.pdf", "https://www.x402.org"):
        line = next(row for row in raw.splitlines() if link in row)
        assert "read 6 Oct 2026" in line, link                              # each was confirmed on the vendor's own page that day
    assert "This is an analogue, not proof." in market and "748.3 million USD in 2025" in market
    assert "172.7 million USD in 2025" in market and "23% of revenue" in market and round((211_183 - 38_529) / 748_300, 2) == 0.23       # revenue AND free cash flow, from its own release
    aws = next(row for row in raw.splitlines() if "https://aws.amazon.com/bedrock/agentcore/pricing/" in row)
    assert "1.50 USD per 1,000" in aws and "read 6 Oct 2026" in aws
    x402 = next(row for row in raw.splitlines() if "x402.org" in row)
    assert "75.41 million transactions and 24.24 million USD of volume for its last 30 days" in x402
    assert not re.search(r"x402[^|\n]{0,200}\b(?:cumulative volume of|50B|\$50)", raw)


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
    # one customer worked at the price book, and what a buyer must get back: three to one
    assert "| Meter | (110,000 − 100,000) × 0.002 × 12 | 240 |" in market and "| Acceptance | 10,000,000 × 0.30% | 30,000 |" in market
    assert "| What the customer pays | 100,000 + 240 + 30,000 | 130,240 |" in market and "390,720 USD a year against 130,240" in market
    assert (110_000 - 100_000) * 2 * 12 // 1000 == 240 and 10_000_000 * 30 // 10_000 == 30_000 and 100_000 + 240 + 30_000 == 130_240 and 130_240 * 3 == 390_720
    assert "### What a buyer must get back" in read("docs/MARKET.md") and "not a saving for the customer" in market
    # why a fork at zero fee does not take it: four things, each zero today, one line each
    fork = read("docs/MARKET.md").split("### Why a fork at zero fee does not take it")[1].split("**What a fork does not start with**")[0]
    lines = [row for row in fork.splitlines() if row.startswith("- **")]
    assert [row.split("**")[1] for row in lines] == ["Inclusion in the canonical delivery record.", "Contracts citing terms by hash.", "The registry of admitted issuers.",
                                                     "Neutrality shown by outside key holders."] and all(row.rstrip().endswith(": 0.") for row in lines)
    # what is sellable while the programs stay on devnet, and what is not
    assert ("Control, Meter, Acceptance on value reconciled off chain and the Pilot: software billed off chain in ordinary money. Nothing has been sold, "
            "and there is no legal entity to invoice from.") in market and "| Acceptance at release: escrow and settlement. The money is test USDC. |" in market
    assert "## 8. Devnet is Knos's test mode" in read("docs/MARKET.md")
    assert "| can be real while the programs stay on devnet | is a demonstration |" in market and "Every fee the program takes: test money, zero revenue." in market
    # the competition is stated with its sources, and the difference is the independence
    for link in ("https://aws.amazon.com/bedrock/agentcore/pricing/", "https://stripe.com/billing/pricing"):
        assert link in read("docs/MARKET.md") and link in read("docs/COMPARE.md"), link
    assert 'So "we meter agents and move payments" is not a difference.' in market
    assert "independent acceptance across vendors, including the disagreements" in market


def test_compare_says_knos_is_not_the_cheapest_or_the_fastest_and_what_comparison_matters():
    compare = flat("docs/COMPARE.md")
    assert "## On fee and on speed, Knos is not the best" in read("docs/COMPARE.md")
    assert "Knos is not the cheapest way to settle." in compare and 'publishes "No platform fee"' in compare and "https://mergepay.fun" in compare
    assert "Knos is not the fastest." in compare and "The comparison that matters is the count neither side keeps" in compare
    assert not re.search(r"hackathon|champion|\bwinner\b", compare, re.I)


def test_the_pilot_is_one_buyer_two_suppliers_thirty_days_credited_against_year_one_and_starts_in_shadow_mode():
    pilot = flat("docs/PILOT.md")
    assert read("docs/PILOT.md").splitlines()[0] == "# The Pilot: one buyer, two suppliers, 30 days, one reconciled invoice"
    assert "A Pilot is one buyer, two suppliers, 30 days, one reconciled invoice, and quantified findings." in pilot
    assert "The 2,500 USD is credited against year one." in pilot and "22,500 USD" in pilot and 25_000 - 2_500 == 22_500
    assert "## The benefit to demand before buying: three to one" in read("docs/PILOT.md") and "| × 3 | 390,720 USD a year |" in pilot
    assert "130,240 USD (Control Business 100,000 + Meter 240 + Acceptance 30,000" in pilot and "connecting a supplier costs nothing" in pilot
    assert "2,500 × 3 = 7,500 USD" in pilot and 2_500 * 3 == 7_500 and "Knos has not shown this benefit for anyone." in pilot
    assert "## How it starts: shadow mode" in read("docs/PILOT.md") and "A Pilot starts in shadow mode." in pilot
    assert "No shadow count has been run with anyone" in pilot and "nobody has bought it" in pilot.lower()


# ---- the two scripts -----------------------------------------------------------------------------------------------------

BEATS = ["one", "two", "three", "four", "five", "six"]
DEMO_SECONDS, WORDS_A_SECOND = 180, 2.5          # the demonstration's length, and the fastest an even reading goes


def said_in(rel: str) -> list[tuple[str, list[str]]]:
    """(heading, spoken words) for each part of a script that has spoken words."""
    out = []
    for part in read(rel).split("\n## ")[1:]:
        words = " ".join(line[1:].strip() for line in part.splitlines() if line.startswith(">")).split()
        if words:
            out.append((part.splitlines()[0], words))
    return out


def test_the_demonstration_is_three_minutes_of_speech_and_the_presentation_two_to_three():
    demo, pitch = spoken("docs/submission/demo_script.md"), spoken("docs/submission/pitch_script.md")
    assert 390 <= len(demo) <= 450, f"{len(demo)} spoken words"                              # about 420: three minutes
    assert 300 <= len(pitch) <= 430, f"{len(pitch)} spoken words"                            # two to three minutes
    assert "three minutes" in read("docs/submission/demo_script.md").splitlines()[0]
    assert "minutes" in read("docs/submission/pitch_script.md").splitlines()[0]
    assert "about 420 words" in flat("docs/submission/demo_script.md")


def test_the_interview_tally_is_all_zeros_counts_a_no_and_is_the_constants_a_person_keeps():
    kit = read("docs/submission/INTERVIEWS.md")
    tally = dict(re.findall(r"(?m)^\| ([A-Z][^|]+?) \| (\d+) \|$", kit.split("## The tally")[1].split("\n## ")[0]))
    assert len(tally) == 8 and "Said no to the trial, with a reason" in tally and "Said no to the trial, with no reason" in tally
    assert "**A no is counted.**" in kit and "a no adds to its row exactly as a yes does" in " ".join(kit.split())
    by_hand = json.loads(read("docs/facts.json"))["by_hand"]
    assert int(tally["Conversations held with a buyer"]) == by_hand["buyer_interviews_held"]
    assert int(tally["Shadow counts run on a real invoice"]) == by_hand["shadow_counts_published"]
    assert int(tally["Letters of intent signed"]) == by_hand["letters_of_intent"]
    if not any(by_hand[k] for k in ("buyer_interviews_held", "shadow_counts_published", "letters_of_intent")):
        assert set(tally.values()) == {"0"} and "**No conversation has happened yet.**" in kit


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


# ---- 0.3.20, the price book's parts: margins said correctly, the second customer, the rails, the loop --------------------

def test_every_margin_in_the_price_documents_is_labelled_gross():
    """Gross margin and operating margin are different: a percentage called a margin says gross, and no operating margin is printed."""
    for rel in ("docs/UNIT_COSTS.md", "docs/MARKET.md", "docs/PILOT.md"):
        lines = read(rel).splitlines()
        for n, line in enumerate(lines):
            for m in re.finditer(r"(?<!bill )\bmargins?\b", line, re.I):       # `knos bill margin` is a command's name
                said = (lines[n - 1] if n else "") + " " + line                 # the label is on the line or the one before it
                assert re.search(r"gross|operating", said, re.I), f"{rel}:{n + 1}: {line[:140]}"
    costs, market = flat("docs/UNIT_COSTS.md"), flat("docs/MARKET.md")
    assert "## Gross margin is not operating margin" in read("docs/UNIT_COSTS.md") and "Every margin on this page is a gross margin." in costs
    assert "this page prints no operating margin" in costs and "Gross margin, not operating margin." in market
    assert not re.search(r"operating margin of \d|\d+(?:\.\d+)?% operating", costs + market)


def test_the_three_leaks_are_fixed_by_design_or_stated_with_the_number_and_the_design():
    from knos import billing
    raw, page = read("docs/UNIT_COSTS.md"), flat("docs/UNIT_COSTS.md")
    costs = json.loads(read("docs/unit_costs.json"))
    month = {"plan": "business", "month": 1, "evaluations": 110_000, "suppliers": 5, "accepted": [{"deliverable": f"d{k}", "value": "20000.00"} for k in range(40)]}
    got = billing.margin(month, costs)
    k, c, m = got["leaks"]["meter"], got["leaks"]["control"], got["remedy"]
    # (a) the Meter: what 95% allows per delivered evaluation, the measured part, the budget, and where the budget meets it
    assert f"| 1.00 | {k['allowed_each']} | |" in raw and f"| 0.75 | {k['measured_each']} | yes: {k['gross_margin_measured_only']} gross |" in raw
    assert f"| 6.20 | {k['cost_each']} | no: {k['gross_margin']} gross |" in raw and not k["meets"] and k["measured_meets"]
    assert f"from {k['reaches_at']:,} evaluations a month" in page and "The cost that is measured meets it:" in page and "The cost that is budgeted does not, at this volume:" in page
    assert "1,800.00 against 50.70: 97.2% gross" in page
    # (b) Control: 15,000 is 85% gross; the target is 7,000, and what replaces the hours is named
    assert (c["cost"], c["gross_margin"], c["target_cost"], c["gross_margin_at_target"]) == ("15,000.00", "85.0%", "7,000.00", "93.0%")
    assert "The target is 7,000 USD a year: a gross margin of 93%." in page and 7_000 // 75 == 93 and "93 hours a year" in page and 15_000 // 75 == 200
    assert "self-service onboarding" in page and "`knos preflight`" in raw and "`knos shadow <invoice>`" in raw and "Nobody has onboarded a customer with them" in page
    assert costs["costs"]["control_year_target"]["usd"] == "7000"
    # (c) the floor: who pays the relayer's tip under both builds, and netting as the remedy with its numbers
    assert "Who pays the relayer's tip." in page and "The funder, under both builds, and only through the fee" in page
    a, b = m["one_by_one"], m["netted"]
    assert f"| released one by one | {a['releases']} | {a['fee']} | {a['tips']} | {a['fee_owner']} |" in raw
    assert f"| netted into one release of {b['amount']} | {b['releases']} | {b['fee']} | {b['tips']} | {b['fee_owner']} |" in raw
    assert "`knos bill margin` prints all three for any month." in page


def test_the_second_worked_customer_is_373_600_and_its_benefit_is_a_hurdle_not_a_claim():
    from knos import billing
    w = billing.second_customer(billing.unit_costs(json.loads(read("docs/unit_costs.json"))))
    assert (w["total"], w["hurdle"], w["direct_cost"], w["gross_margin"], w["cost_ceiling_at_95"]) == ("373,600.00", "1,120,800.00", "16,208.36", "95.7%", "18,680.00")
    for rel in ("docs/MARKET.md", "docs/UNIT_COSTS.md"):
        raw = read(rel)
        assert "| Acceptance | 12 × (1,000,000 × 0.30% + 9,000,000 × 0.20%) | 252,000 |" in raw and "| Meter | 12 × 900,000 × 0.002 | 21,600 |" in raw, rel
        assert "| **What the customer pays** | 100,000 + 252,000 + 21,600 | **373,600** |" in raw, rel
        assert "no such customer exists" in flat(rel).lower()
    assert "1,120,800 USD a year. That is a hurdle to be measured in a pilot, not a claim." in flat("docs/MARKET.md")
    costs = flat("docs/UNIT_COSTS.md")
    assert "16,208.36, a gross margin of 95.7%." in costs and "8,208.36 and the gross margin 97.8%" in costs and "| Record | budgeted at zero | 0 |" in read("docs/UNIT_COSTS.md")
    assert "That is a hurdle to be measured in a pilot, not a claim" in costs
    pilot = flat("docs/PILOT.md")
    assert "| × 3 | 1,120,800 USD a year |" in pilot and "Both lines are hurdles to be measured in a Pilot, not claims" in pilot
    assert "The first customer to look for" in flat("docs/MARKET.md")


def test_the_billing_rules_for_rails_and_the_floor_as_policy_are_said_in_the_price_book():
    from knos import billing
    market = flat("docs/MARKET.md")
    assert "Once, whichever rail pays." in market and "A rail's own charge is not Knos's price." in market and "`rail_charges`" in read("docs/MARKET.md")
    assert "A 0.20% floor is a pricing policy, not a law." in market and "Nothing enforces it but a contract" in market
    assert "rails" in billing.RULES and "once_any_rail" in billing.RULES
    record = next(row for row in BOOK if row[0] == "Record")
    assert record[4] == "`knos record serve` (anyone runs it; Knos hosts none); budgeted at ZERO revenue until someone buys it"
    assert "the API is not built" not in read("docs/UNIT_COSTS.md") and "not built: a static file" not in read("docs/MARKET.md") + read("web/price.js")


def test_market_shows_where_the_count_applies_next_and_the_competitors_reread_today():
    raw, market = read("docs/MARKET.md"), flat("docs/MARKET.md")
    table = raw.split("### Where the same count applies next")[1].split("### How much agent work there is")[0]
    rows = [line for line in table.splitlines() if line.startswith("| ") and not line.startswith("| kind") and not line.startswith("|---")]
    assert [r.split(" | ")[0].strip("| ") for r in rows] == ["Software delivery", "Customer operations", "Data operations", "Back-office processing",
                                                             "Agent services bought by other agents"]
    assert table.count("(OUTCOMES.md)") >= 3 and (ROOT / "docs" / "OUTCOMES.md").is_file() and (ROOT / "examples" / "agent_pays_agent").is_dir()
    assert "They do not show that any buyer wants a separate neutral meter" in market
    for link in ("https://www.intercom.com/pricing", "https://www.zendesk.com/pricing/", "https://www.salesforce.com/agentforce/pricing/",
                 "https://sourcegraph.com/changelog/agentic-batch-changes-ga", "https://aws.amazon.com/bedrock/agentcore/pricing/",
                 "https://stripe.com/billing/pricing", "https://mergepay.fun"):
        line = next(row for row in raw.splitlines() if link in row and row.startswith("|"))
        assert "7 Oct 2026" in line, link


def test_unit_costs_sets_the_budget_against_the_requirement_and_the_gross_fee_against_cash_kept():
    import knos.billing as billing
    raw, page = read("docs/UNIT_COSTS.md"), flat("docs/UNIT_COSTS.md")
    table = raw.split("## The budget today against what the price book requires")[1].split("## The gross fee is not the cash Knos keeps")[0]
    rows = [r for r in table.splitlines() if r.startswith("| ") and not r.startswith("| unit")]
    gaps = billing.gaps(billing.unit_costs(json.loads(read("docs/unit_costs.json"))))
    assert len(rows) == len(gaps)
    for row, g in zip(rows, gaps):                                       # the page and `knos bill margin` say the same budget and requirement
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert cells[1].startswith(g["budget"]) and cells[2].startswith(g["required"]), (row, g)
    assert "cash kept = gross fee − the tips outside relayers take out of it" in page and "A fee counter on chain is not company cash:" in page
    assert "| **Cash kept** | **208.20, 69.40% of the gross fee** |" in raw and billing.cash_example()["cash_kept"] == "208.20"


def test_market_builds_acceptance_bottom_up_and_reconfirms_the_three_competitors():
    raw, market = read("docs/MARKET.md"), flat("docs/MARKET.md")
    assert "customers × eligible purchased work per customer × adopted share × realised fee." in market
    table = raw.split("### The bottom-up formula, input by input")[1].split("## 6.")[0]
    inputs = [r for r in table.splitlines() if r.startswith("| ") and not r.startswith("| input")]
    assert [r.split(" | ")[0].strip("| ") for r in inputs] == ["Customers", "Eligible purchased work per customer", "Adopted share", "Realised fee"]
    assert all("**[assumption]**" in r or "**[measured]**" in r for r in inputs) and "Context, not the market." in market
    assert 10_000_000 * 30 // 10_000 == 30_000 and 10_000_000 // 2 * 20 // 10_000 == 10_000
    for link, says in (("https://stripe.com/newsroom/news/stripe-completes-metronome-acquisition", "14 Jan 2026"),
                       ("https://docs.cdp.coinbase.com/x402/seller/facilitator", "0.001 USD each"),
                       ("https://aws.amazon.com/bedrock/agentcore/pricing/", "1.50 USD per 1,000")):
        line = next(row for row in raw.splitlines() if link in row and row.startswith("|"))
        assert says in line and "8 Oct 2026" in line, link
    beyond = raw.split("What Knos sells beyond each, one line each:")[1].split("What Knos is that they are not")[0]
    assert len([r for r in beyond.splitlines() if r.startswith("| ") and not r.startswith("| who")]) == 3


def test_micro_outcomes_are_worked_from_the_price_book_and_say_netting_moves_transfers_not_evaluation_cost():
    from decimal import ROUND_HALF_UP, Decimal

    from knos import billing
    raw, page = read("docs/UNIT_COSTS.md"), flat("docs/UNIT_COSTS.md")
    part = raw.split("## Micro-outcomes: a different delivery")[1].split("\n## ")[0]
    value = billing.NET_EXAMPLE[0]
    accept = (value * billing.ACCEPT_RATE).normalize()                         # netted: the floor once per release, not per outcome
    earned = (accept + billing.METER_PRICE).normalize()
    at90, at95, free95 = earned * Decimal("0.10"), earned * (1 - billing.TARGET), accept * (1 - billing.TARGET)
    six = lambda d: str(d.quantize(Decimal("0.000001"), ROUND_HALF_UP))     # noqa: E731 - USD to the millionth, halves up
    assert (value, accept, earned) == (Decimal("0.99"), Decimal("0.00297"), Decimal("0.00497"))
    rows = dict(re.findall(r"(?m)^\| (.+?) \| (\S+) \|$", part))
    assert rows["Meter, one evaluation past the free ones"] == str(billing.METER_PRICE)
    assert [v.strip("*") for k, v in rows.items() if k.startswith("Acceptance")] == [str(accept)]
    assert rows["**What Knos earns**"] == f"**{earned}**" and rows["the most it may cost to deliver at a gross margin of 90%"] == six(at90)
    assert rows["**the most it may cost to deliver at a gross margin of 95%**"] == f"**{six(at95)}**" == "**0.000249**"
    assert any(k.startswith("the same at 95% while the evaluation is still one of the month's 100,000 free ones") and v == six(free95)
               for k, v in rows.items()) and billing.METER_FREE == 100_000
    assert "must stay below about 0.00025 USD" in page and round(at95, 5) == Decimal("0.00025")
    costs = billing.unit_costs(json.loads(read("docs/unit_costs.json")))
    evaluation, deliverable = Decimal(str(costs["evaluation"])), Decimal(str(costs["accepted_deliverable"]))
    assert (evaluation, deliverable) == (Decimal("0.00005"), Decimal("0.10"))
    assert round(evaluation / at95 * 5) == 1 and "about a fifth of the ceiling" in page                      # the evaluation fits
    assert f"about {round(deliverable / at95)} times the ceiling" in page and round(deliverable / at95) == 402
    assert f"target of {billing.DELIVERABLE_TARGET} is about {round(billing.DELIVERABLE_TARGET / at95)} times it" in page
    assert "Netting moves transfers, not evaluation cost." in page and "high-value deliverables and micro-outcomes need different delivery" in page
    assert "none of these costs is measured" in page and "https://www.intercom.com/pricing" in part
