"""Every benchmark number in the docs is generated from docs/bench.json: a doc that drifts fails here. Every number in
the pitch-facing text has a fact, and a number only the release run can measure is a slot until that run fills it."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _copy(tmp_path: Path, files) -> None:
    for rel in files:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes((ROOT / rel).read_bytes())


def _unfill(root: Path, bd, names) -> None:
    """Once the release has filled the slots, the copied documents state those facts with numbers. The tests below add
    statements of their own, so the facts they test are first taken back out of the copy: each sentence that states
    one of `names` (bd.FRAMES, read across line breaks) says "not measured" there instead of the number."""
    import re
    for rel in bd.public_text(root):
        doc = root / rel
        text = old = doc.read_text(encoding="utf-8")
        for name in names:
            for frame in bd.FRAMES[name]:
                text = re.sub(frame.replace(" ", r"\s+"), lambda m: m.group(0)[:m.start(1) - m.start(0)] + "not measured"
                              + m.group(0)[m.end(1) - m.start(0):], text)
        if text != old:
            doc.write_text(text, encoding="utf-8")


def test_docs_match_the_one_benchmark_source():
    assert _script("bench_docs").main(check=True) == 0


def test_every_pitch_number_has_a_fact_that_holds(capsys):
    """README, the home page, the submission and the three scripts say no number that docs/facts.json cannot back."""
    assert _script("claims_check").main(["--offline"]) == 0, capsys.readouterr().out


def test_a_number_without_a_fact_and_a_stale_fact_both_fail(tmp_path, monkeypatch, capsys):
    cc = _script("claims_check")
    facts = json.loads((ROOT / "docs" / "facts.json").read_text(encoding="utf-8"))["facts"]
    backing = {f.get("json") or f.get("file") for f in facts} - {None}
    assert "docs/TAMPER.md" in backing and "docs/bench.json" in backing
    _copy(tmp_path, {*cc.PITCH, "docs/facts.json", *backing, *cc.docs_of(facts)})
    monkeypatch.setattr(cc, "ROOT", tmp_path)
    assert cc.main(["--offline"]) == 0
    readme = tmp_path / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nUsed by 9,999 repositories.\n", encoding="utf-8")
    capsys.readouterr()
    assert cc.main(["--offline"]) == 1
    assert "'9,999' has no fact" in capsys.readouterr().out
    readme.write_text(readme.read_text(encoding="utf-8").replace("\nUsed by 9,999 repositories.\n", ""), encoding="utf-8")
    tamper = tmp_path / "docs" / "TAMPER.md"
    tamper.write_text(tamper.read_text(encoding="utf-8").replace("| **63** | **56** |", "| **63** | **57** |"), encoding="utf-8")
    assert cc.main(["--offline"]) == 1
    assert "does not have" in capsys.readouterr().out
    tamper.write_text(tamper.read_text(encoding="utf-8").replace("| **63** | **57** |", "| **63** | **56** |"), encoding="utf-8")
    assert cc.main(["--offline"]) == 0
    # a number a document says under a fact: the document must go on saying it, and the fact must go on holding
    doc_facts = [f for f in facts if "doc" in f]
    assert doc_facts and all(not cc.unsaid(f, {p: {t for t, _l in cc.numbers(p)} for p in cc.docs_of(facts)}) for f in doc_facts)
    one = next(f for f in doc_facts if isinstance(f["doc"], str) and len(f["say"]) == 1 and f["say"][0] == "121,125")
    page = tmp_path / one["doc"]
    page.write_text(page.read_text(encoding="utf-8").replace("121,125", "121,126"), encoding="utf-8")
    capsys.readouterr()
    assert cc.main(["--offline"]) == 1
    assert "no longer says ['121,125']" in capsys.readouterr().out


def test_every_slot_in_the_submission_is_one_the_script_knows_and_holds_no_digit():
    """A slot is filled by name, so a name nobody defined would stay open for ever; and a digit in a name would read
    as a number with no fact."""
    bd = _script("bench_docs")
    assert {name for _doc, name in bd.slots()} <= set(bd.SLOTS)
    assert all(name.replace("_", "").isalpha() and what for name, (what, _path) in bd.SLOTS.items())
    assert {path for _what, path in bd.DEVNET} >= {path for _what, path in bd.SLOTS.values() if path}


def test_the_release_fills_a_slot_once_with_its_number_and_a_fact(tmp_path, monkeypatch, capsys):
    bd, cc = _script("bench_docs"), _script("claims_check")
    facts = json.loads((ROOT / "docs" / "facts.json").read_text(encoding="utf-8"))["facts"]
    _copy(tmp_path, {*cc.PITCH, *bd.DOCS, "docs/facts.json", "docs/bench.json", "docs/backtest.json",
                     *({f.get("json") or f.get("file") for f in facts} - {None}), *cc.docs_of(facts)})
    sub = tmp_path / "docs" / "submission"
    for doc in sub.glob("*.md"):
        doc.unlink()                                    # only this test's file holds slots:
    for rel in bd.SLOTTED:                              # the other documents that may carry them say "not measured"
        if (tmp_path / rel).is_file():
            (tmp_path / rel).write_text(bd.SLOT.sub("not measured", (tmp_path / rel).read_text(encoding="utf-8")), encoding="utf-8")
    _unfill(tmp_path, bd, ("seconds_from_merge_to_paid", "payments_timed", "tests_passing"))
    (sub / "a.md").write_text("Median: [[stat: seconds_from_merge_to_paid]] seconds over [[stat: payments_timed]] payments.\n"
                              "[[stat: tests_passing]] tests pass. [[stat: outside_funders]] funders.\n", encoding="utf-8")
    stats = tmp_path / "stats.json"
    stats.write_text(json.dumps({"updated": "2026-10-05 10:00 UTC", "by_deployment": {"second": {"funded": 4, "completed": 3}},
                                 "outside": {"funded": 0, "completed": 0, "funders": None, "repeat_funders": 0},
                                 "latency": {"merge_to_paid": {"count": 3, "median": 41, "p90": 77},
                                             "comment_to_funded": {"median": 19}}}), encoding="utf-8")
    left = bd.fill(str(stats), root=tmp_path)
    text = (sub / "a.md").read_text(encoding="utf-8")
    assert text.startswith("Median: 41 seconds over 3 payments.\n")
    # a number stats.json does not have, and one only the release run can give, stay slots
    assert left == ["outside_funders", "tests_passing"] and "[[stat: tests_passing]] tests pass. [[stat: outside_funders]]" in text
    bench = json.loads((tmp_path / "docs" / "bench.json").read_text(encoding="utf-8"))
    assert bench["devnet"]["stats"]["latency"]["merge_to_paid"] == {"count": 3, "median": 41, "p90": 77}
    assert bench["devnet"]["stats"]["by_deployment"]["second"] == {"funded": 4, "completed": 3}
    said = {tuple(f["say"]): f for f in json.loads((tmp_path / "docs" / "facts.json").read_text(encoding="utf-8"))["facts"]}
    assert said[("41",)]["path"] == "devnet.stats.latency.merge_to_paid.median" and said[("41",)]["equals"] == 41
    # the release run's own number, with where it was measured
    assert bd.fill(given={"tests_passing": (1234, "pytest -q on the release commit")}, root=tmp_path) == ["outside_funders"]
    assert "1,234 tests pass." in (sub / "a.md").read_text(encoding="utf-8")
    bench = json.loads((tmp_path / "docs" / "bench.json").read_text(encoding="utf-8"))
    assert bench["release"]["tests_passing"] == {"value": 1234, "source": "pytest -q on the release commit"}
    assert bench["devnet"]["stats"]["latency"]["merge_to_paid"]["median"] == 41         # an earlier fill is kept
    fact = [f for f in json.loads((tmp_path / "docs" / "facts.json").read_text(encoding="utf-8"))["facts"] if f["say"] == ["1,234"]]
    assert fact and fact[0]["path"] == "release.tests_passing.value" and "pytest -q on the release commit" in fact[0]["what"]
    # the `devnet` block now shows what was measured, and says "measured at release" only where nothing was
    block = bd.devnet(bench["devnet"])
    assert "| tasks paid | 3 |" in block and "| seconds from the merge to the payment, median | 41 |" in block
    assert "| funders among them | measured at release |" in block and "2026-10-05 10:00 UTC" in block
    assert bd.main(root=tmp_path) == 0 and bd.main(check=True, root=tmp_path) == 0      # the blocks, written again
    assert "| tasks paid | 3 |" in (tmp_path / "docs" / "BENCH.md").read_text(encoding="utf-8")
    # a slot nobody defined fails the check that the suite runs
    (sub / "a.md").write_text("[[stat: made_up_number]] things.\n", encoding="utf-8")
    capsys.readouterr()
    assert bd.main(check=True, root=tmp_path) == 1 and "made_up_number" in capsys.readouterr().out
    # and a number filled only in a document that is not pitch-facing is held to that document
    _a_number_filled_only_outside_the_pitch_is_a_doc_fact_that_document_is_held_to(tmp_path / "outside")


def _tree(tmp_path: Path, bd, cc) -> None:
    """The public documents, the site's page and what the facts rest on, copied; every slot they hold closed."""
    facts = json.loads((ROOT / "docs" / "facts.json").read_text(encoding="utf-8"))["facts"]
    _copy(tmp_path, {*cc.PITCH, *bd.public_text(ROOT), "docs/bench.json", "docs/backtest.json", "docs/facts.json",
                     *({f.get("json") or f.get("file") for f in facts} - {None}), *cc.docs_of(facts)})
    for rel in bd.slot_files(tmp_path):
        (tmp_path / rel).write_text(bd.SLOT.sub("not measured", (tmp_path / rel).read_text(encoding="utf-8")), encoding="utf-8")


def test_the_documents_a_judge_opens_can_carry_slots_and_this_tree_states_each_fact_once():
    bd = _script("bench_docs")
    assert {"README.md", "docs/DISCLOSURE.md", "docs/WHY.md", "docs/COMPARE.md"} <= set(bd.SLOTTED)
    assert set(bd.FRAMES) <= set(bd.SLOTS) and bd.WHEN <= set(bd.SLOTS)
    assert "web/index.html" in bd.public_text() and bd.disagreements() == []
    # the facts the reviews found in two or three versions are each stated, and each in more than one document
    told = bd.said()
    assert len({doc for files in told["seconds_from_merge_to_paid"].values() for doc in files}) >= 4
    assert len({doc for files in told["upgrade_proposed"].values() for doc in files}) >= 3


def test_one_fact_has_one_value_across_every_document_and_the_site(tmp_path, capsys):
    bd, cc = _script("bench_docs"), _script("claims_check")
    _tree(tmp_path, bd, cc)
    _unfill(tmp_path, bd, ("seconds_from_merge_to_paid", "payments_timed"))
    why, readme, page = tmp_path / "docs" / "WHY.md", tmp_path / "README.md", tmp_path / "web" / "index.html"
    kept = {p: p.read_text(encoding="utf-8") for p in (why, readme, page)}
    assert bd.main(check=True, root=tmp_path) == 0, capsys.readouterr().out
    # a slot in one document and the same slot in another: one value, and it is not measured yet
    readme.write_text(kept[readme] + "\nFrom merge to paid took [[stat: seconds_from_merge_to_paid]] seconds.\n", encoding="utf-8")
    why.write_text(kept[why] + "\nThe median from merge to payment is\n[[stat: seconds_from_merge_to_paid]] seconds.\n", encoding="utf-8")
    assert bd.main(check=True, root=tmp_path) == 0, capsys.readouterr().out
    # a number in one document while another still holds the slot: two values
    why.write_text(kept[why] + "\nThe median from merge to payment is 57 seconds.\n", encoding="utf-8")
    capsys.readouterr()
    assert bd.main(check=True, root=tmp_path) == 1
    out = capsys.readouterr().out
    assert "seconds_from_merge_to_paid has 2 values" in out and "57 in docs/WHY.md" in out and "README.md" in out
    # the release fills the slots: every document then says the number docs/bench.json keeps
    why.write_text(kept[why] + "\nThe median from merge to payment is\n[[stat: seconds_from_merge_to_paid]] seconds.\n", encoding="utf-8")
    stats = tmp_path / "stats.json"
    stats.write_text(json.dumps({"updated": "2026-10-05 10:00 UTC", "latency": {"merge_to_paid": {"count": 31, "median": 19, "p90": 44}}}), encoding="utf-8")
    bd.fill(str(stats), root=tmp_path)
    assert bd.main(root=tmp_path) == 0                                                   # the generated blocks, written again
    assert "took 19 seconds" in readme.read_text(encoding="utf-8") and "is\n19 seconds" in why.read_text(encoding="utf-8")
    assert bd.main(check=True, root=tmp_path) == 0, capsys.readouterr().out
    # a document edited by hand afterwards, the site's page included, is two values again; so is one stale number everywhere
    page.write_text(kept[page].replace("</h1>", "</h1><p>From merge to paid took <b>110</b> seconds.</p>", 1), encoding="utf-8")
    capsys.readouterr()
    assert bd.main(check=True, root=tmp_path) == 1
    out = capsys.readouterr().out
    assert "110 in web/index.html" in out and "19 in README.md, docs/WHY.md" in out
    page.write_text(kept[page], encoding="utf-8")
    for doc in (readme, why):
        doc.write_text(doc.read_text(encoding="utf-8").replace("19 seconds", "21 seconds"), encoding="utf-8")
    capsys.readouterr()
    assert bd.main(check=True, root=tmp_path) == 1
    assert "seconds_from_merge_to_paid is 19 in docs/bench.json and 21 in README.md, docs/WHY.md" in capsys.readouterr().out
    # a sentence that states one fact with another fact's slot
    readme.write_text(kept[readme] + "\nFrom merge to paid took [[stat: payments_timed]] seconds.\n", encoding="utf-8")
    why.write_text(kept[why], encoding="utf-8")
    capsys.readouterr()
    assert bd.main(check=True, root=tmp_path) == 1 and "another fact's slot" in capsys.readouterr().out


def test_the_upgrade_is_one_time_and_the_moment_it_can_execute_is_48_hours_later_everywhere(tmp_path, monkeypatch, capsys):
    bd, cc = _script("bench_docs"), _script("claims_check")
    _tree(tmp_path, bd, cc)
    _unfill(tmp_path, bd, ("upgrade_proposed", "upgrade_executable"))
    readme, sec = tmp_path / "README.md", tmp_path / "docs" / "SECURITY.md"
    line = "\nThe upgrade was proposed on [[stat: upgrade_proposed]] and can execute from [[stat: upgrade_executable]].\n"
    for doc in (readme, sec):
        doc.write_text(doc.read_text(encoding="utf-8") + line, encoding="utf-8")
    for bad in ({"upgrade_executable": ("2026-10-07 14:05 UTC", "by hand")}, {"upgrade_proposed": ("5 October", "by hand")},
                {"upgrade_proposed": (20261005, "by hand")}):
        try:
            bd.fill(given=bad, root=tmp_path)
        except SystemExit as why:
            assert "upgrade_" in str(why)
        else:
            raise AssertionError(bad)
    assert line in readme.read_text(encoding="utf-8")                                    # nothing was filled
    assert bd.fill(given={"upgrade_proposed": ("2026-10-05 14:05 UTC", "governance.mjs upgrade propose, proposals 3 and 4")}, root=tmp_path) == []
    said = "The upgrade was proposed on 2026-10-05 14:05 UTC and can execute from 2026-10-07 14:05 UTC."
    assert said in readme.read_text(encoding="utf-8") and said in sec.read_text(encoding="utf-8")
    bench = json.loads((tmp_path / "docs" / "bench.json").read_text(encoding="utf-8"))["release"]
    assert bench["upgrade_proposed"]["value"] == "2026-10-05 14:05 UTC" and bench["upgrade_executable"]["value"] == "2026-10-07 14:05 UTC"
    assert bd.main(check=True, root=tmp_path) == 0, capsys.readouterr().out
    # the pitch-facing text is held to both times: they are not numbers without a fact, and a time nobody says is a stale fact
    monkeypatch.setattr(cc, "ROOT", tmp_path)
    assert cc.main(["--offline"]) == 0, capsys.readouterr().out
    readme.write_text(readme.read_text(encoding="utf-8").replace("2026-10-07 14:05 UTC", "2026-10-07 15:05 UTC"), encoding="utf-8")
    capsys.readouterr()
    assert bd.main(check=True, root=tmp_path) == 1 and "upgrade_executable has 2 values" in capsys.readouterr().out
    sec.write_text(sec.read_text(encoding="utf-8").replace("2026-10-07 14:05 UTC", "2026-10-07 15:05 UTC"), encoding="utf-8")
    assert bd.main(check=True, root=tmp_path) == 1
    assert "upgrade_executable is 2026-10-07 14:05 UTC in docs/bench.json and 2026-10-07 15:05 UTC in README.md, docs/SECURITY.md" in capsys.readouterr().out
    assert cc.main(["--offline"]) == 1 and "nothing says '2026-10-07 14:05 UTC' any more" in capsys.readouterr().out


def test_the_one_sentence_and_its_long_form_are_on_the_first_screen_of_the_readme_and_of_the_site():
    cc = _script("claims_check")
    for path in ("README.md", "web/index.html"):
        words = cc.words(path)
        assert cc.SENTENCE in words and cc.LONG in words and words.index(cc.SENTENCE) < words.index(cc.LONG), path
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    first = readme.split("\n## Why", 1)[0]
    assert cc.SENTENCE in first and "demo.mp4" in first and "Try it in one minute" in first and len(readme.splitlines()) < 260
    config = (ROOT / "web" / "config.js").read_text(encoding="utf-8")
    labels = [line.split('label: "', 1)[1].split('"', 1)[0] for line in config.splitlines() if 'label: "' in line]
    assert len(labels) == 3 and all(f"**{label}:**" in first for label in labels)      # the site's three buttons, by name


def _a_number_filled_only_outside_the_pitch_is_a_doc_fact_that_document_is_held_to(tmp_path):
    """A slot filled only in a document that is not pitch-facing (docs/ASSURANCE.md) gets a fact with "doc", so
    claims_check.py holds that document to the number instead of failing it as said nowhere."""
    bd, cc = _script("bench_docs"), _script("claims_check")
    assert bd.PITCH == cc.PITCH
    _tree(tmp_path, bd, cc)
    page = tmp_path / "docs" / "ASSURANCE.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nThe fuzzer tried [[stat: claim_parser_executions]] inputs.\n", encoding="utf-8")
    bd.fill(given={"claim_parser_executions": (1234567, "a run")}, root=tmp_path)
    fact = [f for f in json.loads((tmp_path / "docs" / "facts.json").read_text(encoding="utf-8"))["facts"]
            if f.get("path") == "release.claim_parser_executions.value"]
    assert fact and fact[0]["say"] == ["1,234,567"] and fact[0]["doc"] == "docs/ASSURANCE.md"
