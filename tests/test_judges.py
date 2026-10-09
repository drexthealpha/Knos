"""docs/JUDGES.md is the one page a judge reads, and docs/judges.json is the same page as data (scripts/judges.py).

The one sentence, then the pitch line, then the number; at most 350 words and one table; the six criteria in the
rules and the seven factors Colosseum's page lists, each one sentence and one link; days to approve defined and not
measured; five lines of what is not real yet, with the numbers docs/submission/NUMBERS.md prints; no fee printed, because the public program ids charge
what the live build charges. README, STORY, WHY and the presentation say why Solana in the same words.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHY_SOLANA = "Money is released with no custodian, and the count is anchored where neither side can alter it."


def _judges():
    spec = importlib.util.spec_from_file_location("judges_script", ROOT / "scripts" / "judges.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def flat(rel: str) -> str:
    return " ".join(read(rel).split())


def test_the_page_is_one_page_thirteen_rows_five_zeros_and_the_file_is_the_page():
    j = _judges()
    assert j.problems() == []
    page, data = read("docs/JUDGES.md"), json.loads(read("docs/judges.json"))
    assert len(j.WORD.findall(j.prose(page))) <= 350 and page.count("\n|---") == 1
    lines = [line for line in page.splitlines() if line.strip()]
    assert lines[1] == "**The neutral meter for AI agent work: neither side keeps the count.**"
    assert lines[2] == j.PITCH == data["pitch"]                                          # the pitch line is the second line
    assert lines[3] == "Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check."
    assert [r["thing"] for r in data["rows"]] == j.JUDGED and len(data["rows"]) == 13
    assert set(data) == {"title", "sentence", "pitch", "number", "claim", "why_solana", "source", "columns", "rows", "wait", "not_real", "entry", "page"}
    for row in data["rows"]:
        assert set(row) == {"id", "thing", "sentence", "link", "label"}             # the shape web/judges.js reads
        assert row["link"].startswith("https://") and len(j.WORD.findall(row["sentence"])) <= 22, row["thing"]
        assert row["sentence"] in page and row["sentence"].count(". ") == 0             # one sentence
    assert data["rows"][0]["link"] == f"https://explorer.solana.com/tx/{json.loads(read('web/demo_data.json'))['paid']['tx']}?cluster=devnet"
    assert len(data["not_real"]) == 5 and data["why_solana"] == WHY_SOLANA == j.WHY_SOLANA
    assert "black-box check refused all 63" in page and "this check" not in page



def test_a_judge_enters_through_the_manifest_and_the_witnessed_transaction_and_everything_else_is_one_click():
    j = _judges()
    page, data = read("docs/JUDGES.md"), json.loads(read("docs/judges.json"))
    first = data["entry"]
    # "Start here" comes after the four lines and before the table; its first link is the manifest's chain
    assert page.index("## Start here") < page.index("\n|") and first["manifest"].endswith("docs/MANIFEST.md")
    assert "source, build hash, deployed version, transactions, fee schedule" in page
    # the witnessed transaction: each step's link, in the order it happened, on devnet and in its own repository
    assert [w["label"] for w in first["witnessed"]] == j.WITNESSED
    assert all(w["link"].startswith(("https://explorer.solana.com/tx/", "https://github.com/drexthealpha/knos-witness/")) for w in first["witnessed"])
    assert all(w["link"].endswith("?cluster=devnet") for w in first["witnessed"] if "explorer" in w["link"])
    assert first["yourself"].endswith("examples/witnessed/README.md") and (ROOT / "examples" / "witnessed" / "README.md").exists()
    # what that run was, plainly: an own repository, test money, and what it needed
    start = flat("docs/JUDGES.md").split("## Start here")[1].split("## ")[0]
    assert "own repository, test USDC" in start and "three workarounds" in start and "no lines" in start
    # the README's judge link is the page whose first entry this is, and its "For a judge" part carries the same links
    readme = read("README.md")
    assert "](docs/JUDGES.md)" in readme.split("</h1>", 1)[1].split("\n## ", 1)[0]
    judge = readme.split("\n## For a judge\n", 1)[1].split("\n## ", 1)[0]
    assert judge.index("](docs/MANIFEST.md)") < judge.index(first["witnessed"][0]["link"]) and "three workarounds" in judge
    assert all(f"[{w['label']}]({w['link']})" in judge for w in first["witnessed"]) and len([x for x in judge.splitlines() if x.strip()]) == 3


def test_the_zeros_are_the_numbers_page_and_no_fee_or_missing_thing_is_claimed():
    page = flat("docs/JUDGES.md")
    numbers = read("docs/submission/NUMBERS.md")
    value = {what.split(":")[0].strip(): int(n) for what, n in re.findall(r"(?m)^\| \d \| ([^|]+) \| (\d+) \|", numbers)}
    zeros = page.split("## What is not real yet")[1]
    for said, row in ((r"(\d+) interviews", "Buyer interviews held"), (r"(\d+) letters of intent", "Letters of intent"),
                      (r"(\d+) outside funders", "Outside funders"), (r"(\d+) outside repositories", "Outside repositories"),
                      (r"paid (\d+) times", "Payments between unrelated accounts"), (r"(\d+) reproductions", "Reproductions signed by GitHub"),
                      (r"(\d+) outside programs reading the verifier", "Outside programs reading the verifier")):
        assert int(re.search(said, zeros).group(1)) == value[row], row
    assert ("One outside payee" in zeros) == (value["Outside payees"] == 1)
    assert "devnet and test USDC only" in zeros and "one person holds every key" in zeros and "no security review" in zeros
    # no rate is printed: the page is true before and after an approved upgrade changes the live fee
    assert not re.search(r"\d(\.\d+)?\s*(%|bps)", page) and "this page prints no rate" in page
    # the measured time is said with its sample, and the wait a buyer has is said to be unmeasured
    bench = json.loads(read("docs/bench.json"))
    assert "From merge to paid took 25 seconds at the median, over 42 payments on devnet." in page and "25" in json.dumps(bench)
    assert "It has not measured it with any buyer, so no figure for it is given here." in page
    for word in ("audit", "customer says", "pilot customer", "immutable", "trustless"):
        assert word not in page.lower(), word


def test_why_solana_is_said_in_the_same_words_and_the_first_customer_is_explicit():
    for rel in ("README.md", "docs/STORY.md", "docs/WHY.md", "docs/JUDGES.md"):
        assert f"Why Solana: {WHY_SOLANA}" in flat(rel) or f"In one line: {WHY_SOLANA}" in flat(rel), rel
    assert f"Why Solana? {WHY_SOLANA}" in " ".join(line[1:].strip() for line in read("docs/submission/pitch_script.md").splitlines() if line.startswith(">"))
    first = read("README.md").split("</h1>", 1)[1].split("\n## ", 1)[0]
    assert "](docs/JUDGES.md)" in first and "](JUDGES.md)" in read("docs/README.md") and "](JUDGES.md)" in read("docs/STORY.md")
    why = read("docs/WHY.md").split("## The first customer, and who is not one")[1].split("\n## ")[0]
    five = re.findall(r"(?m)^\d\. \*\*(.+?)\*\*", why)
    assert five == ["It buys measurable outcomes from several outside suppliers.", "It has recurring disputes or duplicate billing.",
                    "It can define acceptance before delivery.", "It spends enough that the savings exceed the cost.",
                    "It has a budget owner who will hand over invoices."]
    assert "Who is not a customer, today:" in why and why.split("Who is not a customer, today:")[1].count("\n- ") >= 5
    assert "Nobody has bought anything" in why and "no saving has been measured with any buyer" in why
    assert "**Days to approve, not seconds to pay.**" in why and "Knos has not measured that wait with any buyer" in " ".join(why.split())


def test_the_check_fails_when_the_page_and_the_file_part(tmp_path):
    j = _judges()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "submission").mkdir()
    for name in ("JUDGES.md", "judges.json", "BENCH.md", "TAMPER.md", "COMPOSE.md", "MARKET.md", "TEAM.md", "WHY.md", "MANIFEST.md",
                 "UNIT_COSTS.md", "submission/NUMBERS.md", "submission/pitch_script.md"):
        shutil.copy(ROOT / "docs" / name, tmp_path / "docs" / name)
    assert j.problems(tmp_path) == []
    page = tmp_path / "docs" / "JUDGES.md"
    text = page.read_text(encoding="utf-8")
    page.write_text(text.replace("refused all 63", "refused every one of 63"), encoding="utf-8")
    assert any("judges.json is not what" in line for line in j.problems(tmp_path))
    page.write_text(text.replace("| Novelty |", "| Newness |"), encoding="utf-8")
    assert any("the rows are" in line for line in j.problems(tmp_path))
    page.write_text(text.replace("5. Neutrality:", "Neutrality:"), encoding="utf-8")
    assert any("4 lines under" in line for line in j.problems(tmp_path))
    page.write_text(text.replace("Not measured. ", "It took 3 days. "), encoding="utf-8")
    assert any("days to approve" in line for line in j.problems(tmp_path))
    page.write_text(text.replace("| Traction |", "| Demand |"), encoding="utf-8")
    assert any("the rows are" in line for line in j.problems(tmp_path))
    page.write_text(text.replace("[The release manifest](MANIFEST.md)", "[The release manifest](BENCH.md)"), encoding="utf-8")
    assert any("its first link is the release manifest" in line for line in j.problems(tmp_path))
    page.write_text(text.replace("[paid](", "[settled]("), encoding="utf-8")
    assert any("witnessed transaction" in line for line in j.problems(tmp_path))


def test_the_seven_factors_are_colosseums_and_traction_says_the_zeros():
    j = _judges()
    data = json.loads(read("docs/judges.json"))
    factors = {r["thing"]: r for r in data["rows"][6:]}
    assert list(factors) == j.FACTORS
    assert "https://colosseum.com/hackathon" in read("docs/JUDGES.md")
    traction = factors["Traction"]["sentence"]
    for zero in ("Outside funders 0", "outside repositories 0", "interviews 0", "revenue 0"):
        assert zero in traction, zero
    assert factors["Traction"]["link"].endswith("docs/submission/NUMBERS.md")
    assert factors["Potential market size"]["sentence"].startswith("Not counted")
    wait = data["wait"]
    assert j.DAYS in wait and "Not measured." in wait and not re.search(r"\d+(\.\d+)? days", wait)
