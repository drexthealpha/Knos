"""scripts/truth_check.py: each rule finds a contradiction planted in a small tree, and passes the same tree without it."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tool():
    spec = importlib.util.spec_from_file_location("truth_check_tool", ROOT / "scripts" / "truth_check.py")
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = mod                      # dataclasses look their module up by name
    spec.loader.exec_module(mod)
    return mod


CAPS = {
    "programs": {"knos_pay": {"id": "P" * 32, "on_chain": "2.1"}},
    "capabilities": [
        {"id": "approval_chains", "stage": "tested", "evidence": {}, "note": "`knos approve`."},
        {"id": "record_lookup_paid", "stage": "tested", "evidence": {}},
        {"id": "order_pay", "stage": "exercised", "evidence": {}},
        {"id": "private_work", "stage": "tested", "evidence": {}},
        {"id": "sketch", "stage": "implemented", "evidence": {}},
    ],
}
BILLING = '''METER_PRICE = Decimal("0.002")
ACCEPT_RATE = Decimal("0.0030")
ACCEPT_TIERS = ((Decimal(0), ACCEPT_RATE), (Decimal(1_000_000), Decimal("0.0020")))
RECORD_PRICE = Decimal("0.10")
CONTROL = {"none": ZERO, "team": Decimal(25_000), "business": Decimal(100_000), "enterprise": Decimal(400_000)}
PILOT = Decimal(2_500)
'''
FEES = 'NEW = Rule("0.3.18", "2.2", pay.FEE_BPS, pay.FEE_MIN, 10, pay.FEE_BPS, pay.FEE_MIN)\nOLD = Rule("0.3.14", "2.1", 250, 400_000, 50, 250, 50_000)\n'


def _tree(tmp_path: Path, **docs: str) -> Path:
    files = {"docs/capabilities.json": json.dumps(CAPS, indent=1), "src/knos/billing.py": BILLING, "src/knos/fees.py": FEES,
             "src/knos/settle/v2/pay.py": "FEE_BPS = 30\n", "src/knos/approvals.py": "def gate():\n    return True\n",
             "src/knos/flow.py": "from knos import approvals\n\nok = approvals.gate()\n",
             "README.md": "**Knos.**\n\nFour programs on Solana devnet.\n"}
    names = {"readme": "README.md", "market": "docs/MARKET.md", "controls": "docs/CONTROLS.md", "disclosure": "docs/DISCLOSURE.md",
             "pitch": "docs/submission/pitch_script.md", "page": "web/index.html", "script": "web/price.js", "caps": "docs/capabilities.json"}
    files.update({names[k]: v for k, v in docs.items()})
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return tmp_path


def _found(root: Path) -> list[tuple[str, str, int]]:
    return [(p.rule, p.file, p.line) for p in _tool().problems(root)]


def test_a_tree_that_agrees_with_itself_has_no_contradiction(tmp_path):
    tc = _tool()
    root = _tree(tmp_path, market="# Prices\n\n| Record | 0.10 USD a lookup |\n| Control | Team 25,000; Business 100,000; Enterprise from 400,000 |\n\n"
                                  "Acceptance: 0.30%; by contract 0.20% above 1M. The fee is 0.30% of the amount.\n\nThe public id runs knos_pay 2.1.\n",
                 controls="`knos.approvals.gate` is asked by the funding workflow for a standing offer.\n",
                 readme="**Knos.**\n\n**Exercised on devnet:** `order_pay`. Four programs on Solana devnet. The manifest has 5 capabilities.\n")
    assert tc.problems(root) == []
    said: list[str] = []
    assert tc.main([], say=said.append, root=root) == 0 and said[-1].startswith("no contradiction in ")


def test_not_built_said_of_a_capability_that_is_tested_is_found_in_every_kind_of_file(tmp_path):
    root = _tree(tmp_path, market="# Prices\n\nIntro.\n\n| Record | the machine-priced API | API (not built: a static file today) |\n",
                 pitch="The check is free. Record: the public record is free; a hosted lookup is priced, not built.\n",
                 script='const rows = [\n  ["Record", "lookup", "API (not built: a static file today)"],\n];\n',
                 controls="Nothing here.\n\n`private_work` is planned, not shipped.\n\n`sketch` is not built past a first module.\n")
    assert _found(root) == [("stage", "docs/CONTROLS.md", 3), ("stage", "docs/MARKET.md", 5), ("stage", "docs/submission/pitch_script.md", 1),
                            ("stage", "web/price.js", 2)]                # `sketch` is only implemented: "not built past" contradicts nothing


def test_a_stage_claimed_above_the_manifests_is_found_and_the_true_one_is_not(tmp_path):
    root = _tree(tmp_path, readme="**Knos.**\n\n**Exercised on devnet:** `order_pay`, `private_work`. **Deployed on devnet:** `sketch`.\n",
                 disclosure="`approval_chains` is deployed on devnet.\n")
    tc = _tool()
    found = tc.problems(root)
    assert [(p.rule, p.file) for p in found] == [("stage", "README.md"), ("stage", "README.md"), ("stage", "docs/DISCLOSURE.md")]
    assert "`private_work`" in found[0].against and "exercised" in found[0].against and "`sketch`" in found[1].against
    assert not any("`order_pay`" in p.against for p in found)


def test_nothing_calls_it_said_of_a_function_the_source_calls_is_found_also_in_a_capabilitys_note(tmp_path):
    caps = json.loads(json.dumps(CAPS))
    caps["capabilities"][0]["note"] = "`knos approve record`. The funding workflow does not ask the gate yet, and an approval is a comment."
    root = _tree(tmp_path, controls="# Approvals\n\nA comment still funds.\n`knos.approvals.gate` is the question a workflow would ask; nothing calls it today.\n",
                 caps=json.dumps(caps, indent=1))
    tc = _tool()
    found = [p for p in tc.problems(root) if p.rule == "calls"]
    assert [(p.file, p.line) for p in found] == [("docs/CONTROLS.md", 4), ("docs/capabilities.json", found[1].line)]
    assert all("src/knos/flow.py calls approvals.gate()" in p.against for p in found)
    (root / "src" / "knos" / "flow.py").write_text("ok = True\n", encoding="utf-8")      # with no caller the sentence is true of the source
    assert [p for p in tc.problems(root) if p.rule == "calls"] == []


def test_a_price_that_is_not_the_price_books_is_found_and_a_past_price_or_a_cost_is_not(tmp_path):
    root = _tree(tmp_path, market="# Prices\n\n| Record | 0.25 USD a lookup |\n| Control | Team 20,000; Business 100,000 |\n\n"
                                  "Meter: 100,000 a month free per organisation, then 0.004 USD.\n\nThe pilot is 5,000 USD, credited against year one.\n\n"
                                  "Acceptance: 0.45% of value.\n\nThe earlier tier was Acceptance: 0.10% and is withdrawn.\n\n"
                                  "At that price a margin of 90% leaves 0.0002 USD per evaluation to deliver it.\n",
                 page="<p>Team 25,000</p>\n<td>0.10 USD a lookup</td>\n")
    tc = _tool()
    found = [p for p in tc.problems(root) if p.rule == "price"]
    assert [(p.file, p.line) for p in found] == [("docs/MARKET.md", 3), ("docs/MARKET.md", 4), ("docs/MARKET.md", 6), ("docs/MARKET.md", 8), ("docs/MARKET.md", 10)]
    assert "0.10 USD, and this says 0.25" in found[0].against and "0.2 or 0.3%" in found[4].against


def test_a_fee_rate_no_build_charges_is_found_and_both_builds_rates_pass(tmp_path):
    root = _tree(tmp_path, market="The fee is 0.30% of the amount, minimum 0.05.\n\nThe live build takes a 2.5% fee.\n",
                 pitch="The escrow takes a fee of 1.5% at release.\n")
    assert _found(root) == [("fee", "docs/submission/pitch_script.md", 1)]
    assert _tool().fee_rates(root) >= {"0.30", "2.50", "0.10"}


def test_a_version_said_to_be_live_that_the_public_id_does_not_run_is_found_and_a_pending_one_is_not(tmp_path):
    root = _tree(tmp_path, disclosure="The public id runs knos_pay 2.2 today.\n\nProposal 8 would deploy knos_pay 2.2, which then runs the new fee.\n\n"
                                      "LIVE: knos_pay 2.1.\n")
    assert _found(root) == [("version", "docs/DISCLOSURE.md", 1)]


def test_two_documents_that_count_differently_are_found_and_a_count_of_capabilities_is_held_to_the_rows(tmp_path):
    root = _tree(tmp_path, pitch="Five programs on Solana devnet, with no framework.\n\nThe suite: 3,366 passed.\n",
                 market="On CI 3,412 passed.\n\nKnos lists 9 capabilities.\n\nTwo programs were made immutable in the first deployment on devnet.\n")
    tc = _tool()
    found = tc.problems(root)
    assert [(p.rule, p.file, p.line) for p in found] == [("count", "docs/MARKET.md", 3), ("count", "docs/submission/pitch_script.md", 1),
                                                         ("count", "docs/submission/pitch_script.md", 3)]
    assert "has 5 capabilities, and this says 9" in found[0].against and "README.md:3 counts 4 programs" in found[1].against
    assert "docs/MARKET.md:1 counts 3412 tests passed" in found[2].against
    said: list[str] = []
    assert tc.main(["--json"], say=said.append, root=root) == 1 and len(json.loads(said[0])) == 3


def test_a_paragraphs_sentences_carry_the_line_they_start_on_and_a_fenced_block_is_not_read():
    tc = _tool()
    got = tc.statements_of("docs/X.md", "# T\n\nOne here. Two starts\nand ends here. Three.\n\n```\nnot built\n```\n- item one\n  goes on.\n| a | b |\n")
    assert [(s.line, s.text) for s in got] == [(3, "One here."), (3, "Two starts and ends here."), (4, "Three."), (9, "- item one goes on."), (11, "| a | b |")]


def test_the_checker_reads_this_tree_and_every_file_it_names_exists():
    tc = _tool()
    names = tc.files()
    assert {"README.md", "docs/CAPABILITIES.md", "docs/MARKET.md", "docs/CONTROLS.md", "docs/DISCLOSURE.md", "web/index.html"} <= set(names)
    assert any(n.startswith("docs/submission/") for n in names) and any(n.startswith("web/") and n.endswith(".js") for n in names)
    book = tc.price_book()
    assert book["record"] == "0.10" and book["meter"] == "0.002" and book["team"] == "25000" and book["pilot"] == "2500" and book["acceptance"] == "0.20,0.30"
    for p in tc.problems():                                               # whatever it finds, it points at a real line
        assert (ROOT / p.file).is_file() and p.line >= 1 and p.rule in {"stage", "calls", "price", "fee", "version", "count"}
