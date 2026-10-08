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
        {"id": "work_orders", "stage": "exercised", "evidence": {}},
        {"id": "private_work", "stage": "tested", "evidence": {}},
        {"id": "sketch", "stage": "implemented", "evidence": {}},
    ],
}
BILLING = '''METER_FREE = 100_000
METER_PRICE = Decimal("0.002")
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
             "README.md": "**Knos.**\n\nFour programs on Solana devnet.\n", "pyproject.toml": '[project]\nname = "knos"\nversion = "0.3.21"\n'}
    names = {"readme": "README.md", "market": "docs/MARKET.md", "controls": "docs/CONTROLS.md", "disclosure": "docs/DISCLOSURE.md",
             "pitch": "docs/submission/pitch_script.md", "page": "web/index.html", "script": "web/price.js", "caps": "docs/capabilities.json",
             "compare": "docs/COMPARE.md", "compose": "docs/COMPOSE.md", "assurance": "docs/ASSURANCE.md"}
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
                                  "Acceptance: 0.30%; by contract 0.20% above 1M. The fee is 0.30% of the amount.\n\nThe public id runs knos_pay 2.1.\n\n"
                                  "Meter: 100,000 evaluations a month free per organisation, then 0.002 USD.\n",
                 compose="Install `knos-settle` from npm: `npm install knos-settle@0.3.20`.\n\nThis release (0.3.21) adds a check.\n\n"
                         "Until knos_pay 2.2 executes, the public program charges the 0.3.14 fee; the quorum fixes are in 2.2.\n",
                 controls="`knos.approvals.gate` is asked by the funding workflow for a standing offer.\n",
                 readme="**Knos.**\n\n**Exercised on devnet:** `order_pay`. Four programs on Solana devnet. The manifest has 6 capabilities.\n")
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
    assert "has 6 capabilities, and this says 9" in found[0].against and "README.md:3 counts 4 programs" in found[1].against
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
        assert (ROOT / p.file).is_file() and p.line >= 1 and p.rule in {"stage", "calls", "price", "fee", "version", "count", "release", "live", "published"}


def test_a_capability_named_in_plain_words_as_tested_only_is_held_to_its_stage(tmp_path):
    """The README "today" table said work orders were tested here only while the manifest had them exercised."""
    root = _tree(tmp_path, readme="**Knos.**\n\n| What | Today |\n|---|---|\n| Tested here only | work orders, the ledger, and every other capability |\n"
                                  "| Exercised | top-ups |\n")
    found = _tool().problems(root)
    assert [(p.rule, p.file, p.line) for p in found] == [("stage", "README.md", 5)] and "`work_orders` is at stage \"exercised\"" in found[0].against


def test_a_page_that_names_an_older_release_as_the_current_one_is_found(tmp_path):
    root = _tree(tmp_path, assurance="This page is about the programs as Knos 0.3.14 has it.\n\nThe 0.3.14 fee was 2.5%.\n",
                 pitch="What this release (0.3.18) changes: a price book.\n\nWhat this release (0.3.21) changes: a checker.\n")
    found = [p for p in _tool().problems(root) if p.rule == "release"]
    assert [(p.file, p.line) for p in found] == [("docs/ASSURANCE.md", 1), ("docs/submission/pitch_script.md", 1)]
    assert "the current release is 0.3.21, and this names 0.3.14" in found[0].against


def test_a_fee_or_a_quorum_fix_said_to_hold_today_is_held_to_the_build_at_the_public_id(tmp_path):
    page = ("Today the public program charges 0.30% of the amount, at least 0.05.\n\nThe two quorum findings are fixed in the escrow.\n\n"
            "Once knos_pay 2.2 executes, the fee is 0.30%, at least 0.05, and the quorum is fixed.\n\n"
            "Today a 5 USDC order pays the 0.3.14 fee, at least 0.40.\n\nThe quorum defects are still live on the public ids.\n")
    tc = _tool()
    root = _tree(tmp_path, compare=page)
    assert [(p.rule, p.line) for p in tc.problems(root) if p.rule == "live"] == [("live", 1), ("live", 3)]   # 2.1 runs
    caps = json.loads(json.dumps(CAPS))
    caps["programs"]["knos_pay"]["on_chain"] = "2.2"
    (root / "docs" / "capabilities.json").write_text(json.dumps(caps), encoding="utf-8")
    found = [p for p in tc.problems(root) if p.rule == "live"]
    assert [p.line for p in found] == [7, 9] and "runs 2.2" in found[0].against                             # after the upgrade


def test_a_package_knos_published_said_to_be_unpublished_is_found_with_its_install_link(tmp_path):
    caps = json.loads(json.dumps(CAPS))
    caps["capabilities"][0]["note"] = "The interface crates and the JS SDK are not published yet."
    root = _tree(tmp_path, compose="**Not published yet.** Neither interface crate is on crates.io.\n\n`knos-settle` is not on npm.\n\n"
                                   "The deploy fee payer is not published.\n\nBefore 8 Oct the crates were not on crates.io.\n",
                 caps=json.dumps(caps, indent=1))
    found = [p for p in _tool().problems(root) if p.rule == "published"]
    assert [p.file for p in found] == ["docs/COMPOSE.md", "docs/COMPOSE.md", "docs/capabilities.json"]
    assert "https://www.npmjs.com/package/knos-settle" in found[1].against and "crates.io/crates/knos-oidc-interface" not in found[1].against
    assert "knos-oidc-interface 0.3.14 is on crates.io" in found[0].against


def test_none_published_and_neither_has_been_published_are_found_too(tmp_path):
    """docs/RELEASE.md said "Three packages, none published yet" and "Neither has been published" after all three were
    on their registries (8 Oct 2026): the words slipped past "not published". A sentence about the past still passes."""
    root = _tree(tmp_path, compose="Three packages, none published yet: the crates and `knos-settle`.\n\n"
                                   "The crates and the npm client: neither has been published.\n\n"
                                   "Each crate is published on crates.io.\n\nOn 4 October none was published on npm, before the first publish.\n")
    found = [p for p in _tool().problems(root) if p.rule == "published"]
    assert [(p.file, p.line) for p in found] == [("docs/COMPOSE.md", 1), ("docs/COMPOSE.md", 3)]
    assert "knos-settle 0.3.20 is on npm" in found[0].against and 'this says "none published"' in found[0].against


def test_an_old_meter_price_in_a_comparison_table_is_found_cell_by_cell(tmp_path):
    """COMPARE.md printed the earlier price book in one cell of a row whose other cell said "before the work"."""
    root = _tree(tmp_path, compare="| | terms | fee |\n|---|---|---|\n| **Knos** | hashed before the work | 10,000 evaluations a month free, then 0.05 USD; "
                                   "or 0.5% of the reconciled accepted invoice value, capped at 250 USD per deliverable |\n"
                                   "| Margin | Acceptance 99.8% gross margin | |\n")
    found = [p for p in _tool().problems(root) if p.rule == "price"]
    assert [p.line for p in found] == [3, 3, 3, 3]
    said = " ".join(p.against for p in found)
    assert "is 0.002 USD, and this says 0.05" in said and "is 100000, and this says 10,000" in said and "this says 0.5%" in said and "no cap" in said


def test_the_readme_today_table_is_generated_from_the_manifest_and_cannot_drift():
    import importlib.util as iu
    import sys
    spec = iu.spec_from_file_location("bench_docs_tool", ROOT / "scripts" / "bench_docs.py")
    bd = iu.module_from_spec(spec)
    sys.modules[spec.name] = bd
    spec.loader.exec_module(bd)
    rows = dict((a, b) for a, b, _c in bd.stage_rows(CAPS["capabilities"]))
    assert rows["Exercised at the public devnet program ids"] == "2 of 6: an order paying up to four payees, work orders"
    assert rows["Tested here only"] == "3 of 6, each with the test its row names" and rows["Reproduced by someone else"] == "0 of 6"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    caps = bd.capabilities()
    for name, said, _where in bd.stage_rows(caps):
        assert f"| {name} | {said} |" in readme, name
    assert sum(int(said.split(" of ")[0]) for _n, said, _w in bd.stage_rows(caps)) == len(caps)


def test_the_sdk_readme_and_registry_descriptions_are_held_to_the_price_book_too(tmp_path):
    """The SDK's README (npm shows it) and the descriptions in server.json and sdk/*/package.json escaped the checker."""
    root = _tree(tmp_path)
    (root / "sdk" / "settle").mkdir(parents=True)
    (root / "sdk" / "settle" / "README.md").write_text("# knos-settle\n\nA Record lookup costs 0.25 USD a lookup.\n\n"
                                                       "This release (0.3.20) adds a reader.\n", encoding="utf-8")
    (root / "sdk" / "settle" / "package.json").write_text('{\n  "name": "knos-settle",\n  "description": "A client. Meter: 100,000 evaluations '
                                                          'a month free, then 0.05 USD."\n}\n', encoding="utf-8")
    (root / "server.json").write_text('{"description": "The neutral meter. Record: 0.10 USD a lookup."}', encoding="utf-8")
    found = _found(root)
    assert found == [("price", "sdk/settle/README.md", 3), ("release", "sdk/settle/README.md", 5), ("price", "sdk/settle/package.json", 3)]


def test_words_no_document_uses_are_found_and_a_sourced_figure_about_another_company_is_not(tmp_path):
    root = _tree(tmp_path, market="# Market\n\nKnos is trustless.\n\nKnos reaches 1 billion USD of ARR.\n\n"
                                  "| company | revenue | free cash flow | source |\n|---|---|---|---|\n"
                                  "| Acme | 2 billion USD | 0.4 billion USD | [Acme, 2025](https://example.com/acme) |\n",
                 compose="# Programs\n\nThe second deployment is immutable.\n\nThe first deployment is immutable.\n\n"
                         "Delivery has zero latency.\n")
    found = [(p.file, p.line) for p in _tool().problems(root) if p.rule == "word"]
    assert found == [("docs/COMPOSE.md", 3), ("docs/COMPOSE.md", 7), ("docs/MARKET.md", 3), ("docs/MARKET.md", 5)]


def test_the_sdk_readme_claims_no_attestation_but_may_name_the_attest_command(tmp_path):
    """npm's page claimed "a GitHub-signed run attests": the word rule bans the claim, not `knos attest` or attest.yml."""
    root = _tree(tmp_path)
    (root / "sdk" / "settle").mkdir(parents=True)
    (root / "sdk" / "settle" / "README.md").write_text(
        "# knos-settle\n\nRun `knos attest` (the workflow `.github/workflows/attest.yml` runs it).\n\n"
        "A run of `attest.yml` with the kind `eval` (`knos attest --kind eval`) makes the token.\n\n"
        "A GitHub-signed run attests that the terms were met.\n", encoding="utf-8")
    found = [(p.file, p.line) for p in _tool().problems(root) if p.rule == "word"]
    assert found == [("sdk/settle/README.md", 7)]


def _script(name: str):
    import importlib.util as iu
    import sys
    spec = iu.spec_from_file_location(f"{name}_tool", ROOT / "scripts" / f"{name}.py")
    mod = iu.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_readme_names_this_release_from_pyproject_and_the_changelog_and_refuses_when_they_differ(tmp_path):
    """A reader served an old cached copy reads which release it is in the README's generated table."""
    bd = _script("bench_docs")
    what, said, where = bd.release_row()
    version = bd.re.search(r'(?m)^version = "([\d.]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8")).group(1)
    assert what == "This copy" and said.startswith(f"Release {version}, ") and "CHANGELOG.md" in where
    assert f"| {what} | {said} | {where} |" in (ROOT / "README.md").read_text(encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.3.99"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## 0.3.98 (October 2026)\n", encoding="utf-8")
    try:
        bd.release_row(tmp_path)
    except SystemExit as e:
        assert "0.3.99" in str(e) and "0.3.98" in str(e)
    else:
        raise AssertionError("a README naming a release the changelog has no entry for")


def test_every_index_figure_names_its_basis():
    """The Index has two bases: every claiming pull request, and the first one per repository. Each place says which."""
    index = (ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8")
    assert "Basis: every merged pull request that claimed passing tests" in index and "first such pull request per repository" in index
    assert json.loads((ROOT / "docs" / "index.json").read_text(encoding="utf-8"))["basis"]["counts"] == "every_merged_claiming_pr"
    assert "(not one per repository)" in (ROOT / "docs" / "index.atom").read_text(encoding="utf-8")
    bench = (ROOT / "docs" / "BENCH.md").read_text(encoding="utf-8")
    assert bench.count("first claiming PR per repository: any check failed") == 2 and "every claiming PR: any check failed" in bench
    head = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("\n## ", 1)[0]
    assert "superseded" in head and "docs/MARKET.md" in head
