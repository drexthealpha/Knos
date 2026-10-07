"""Knos Terms 3 (src/knos/terms3.py): acceptance as a versioned contract of ten required fields.

A file missing a field is refused and the refusal names it; a line cannot say what its facts do not; a quorum needs
evaluators whose owners differ; the diff is by meaning; the order a document funds carries the document's hash; the
registry lists the published versions with their hashes, never rewrites one, and leaves every older file as it was.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from knos import terms, terms3, terms_registry, terms_templates

ROOT = Path(__file__).resolve().parents[1]
# what the registry held before Knos Terms 3: the sha256 of each older published file, as 0.3.17 shipped it
OLDER = {"bugfix/1.json": "bc24fd3aa23bf5f3732e97b11be0392e3a1d126452c91db818ce9985dddeffcc",
         "feature-blackbox/1.json": "b5393d15b76fc590755924bd1514e8e1fba160f1d8aa02ae78967fdeb48b49b0",
         "milestone/1.json": "710badc1d0aa0df0fde518b5cfd8879cec763801fbafb6f7166e7afa25ca71c3"}


def _script():
    spec = importlib.util.spec_from_file_location("terms_registry_script", ROOT / "scripts" / "terms_registry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _app():
    app = typer.Typer()
    terms_templates.register(app)
    return app


def test_each_template_answers_the_ten_questions_in_order():
    assert list(terms3.TEMPLATES) == ["bug-fix", "migration", "dataset-batch", "support-resolution"]
    for name in terms3.TEMPLATES:
        got = terms3.questions(terms3.template(name))
        assert [q["field"] for q in got] == list(terms3.NAMES) and len(got) == 10
        assert all(q["question"].endswith("?") and q["answer"].endswith(".") for q in got)


@pytest.mark.parametrize("field", terms3.NAMES)
def test_a_file_missing_a_field_is_refused_and_the_refusal_names_it(field):
    doc = terms3.template("migration")
    del doc[field]
    with pytest.raises(terms3.Missing) as why:
        terms3.validate(doc)
    assert why.value.fields == [field] and f"`{field}`" in str(why.value) and str(why.value).startswith("This terms 3 file is missing")


def test_every_missing_field_is_named_at_once_and_a_missing_line_too():
    doc = terms3.template("bug-fix")
    del doc["dispute"], doc["price"]
    with pytest.raises(terms3.Missing) as why:
        terms3.validate(doc)
    assert why.value.fields == ["dispute", "price"]
    doc = terms3.template("bug-fix")
    del doc["window"]["says"]
    with pytest.raises(terms3.Missing) as why:
        terms3.validate(doc)
    assert why.value.fields == ["window.says"]


def test_a_line_cannot_say_what_its_facts_do_not():
    doc = terms3.template("bug-fix")
    doc["price"]["amount"] = "500.00"                   # the facts changed, the line still says 50.00
    with pytest.raises(terms3.Refused, match=r"`price.says` does not say what the field holds. It must read: Pays 500.00 test USDC"):
        terms3.validate(doc)
    assert terms3.validate(doc, strict=False)["price"]["says"].startswith("Pays 500.00 test USDC")


def test_what_the_program_does_cannot_be_written_otherwise():
    for field, key, value, word in (("deadline", "late", "paid", "refuses a token presented after the deadline"),
                                    ("dispute", "money", "supplier", "an appeal moves nothing"),
                                    ("dispute", "no_answer", "pay", "returns the money to its funder"),
                                    ("price", "currency", "USD", "test USDC"), ("policy", "how", "edit", "a version never changes")):
        doc = terms3.template("bug-fix")
        doc[field][key] = value
        with pytest.raises(terms3.Refused, match=word):
            terms3.validate(doc, strict=False)


def test_a_quorum_needs_evaluators_whose_owners_differ():
    doc = terms3.template("dataset-batch")
    doc["evaluators"]["quorum"] = 2
    two = terms3.validate(doc, strict=False)
    assert "2 of them must accept the same work, and their owners differ." in two["evaluators"]["says"]
    doc["evaluators"]["list"] = [terms3._own("acme/widgets"), {**terms3._own("acme/judge"), "name": "second"}]
    doc["dispute"]["evaluator"] = "second"
    with pytest.raises(terms3.Refused, match="a quorum of 2 needs 2 evaluators whose owners differ; these have 1 owner"):
        terms3.validate(doc, strict=False)
    doc["evaluators"]["list"][1] = {**terms3._own("other/judge"), "name": "second"}
    assert terms3.validate(doc, strict=False)["evaluators"]["quorum"] == 2
    doc["evaluators"]["list"][1]["owner"] = "acme"      # an owner that is not its repository's
    with pytest.raises(terms3.Refused, match="its repository is owner/name and its owner is that owner"):
        terms3.validate(doc, strict=False)


def test_an_appeal_goes_where_the_code_can_take_it():
    doc = terms3.template("bug-fix")                    # paid on a merge: nothing to run again
    doc["dispute"]["evaluator"] = "own"
    with pytest.raises(terms3.Refused, match="has no suite to run again"):
        terms3.validate(doc, strict=False)
    doc = terms3.template("dataset-batch")              # decided by a suite: an evaluator runs it again
    doc["dispute"]["evaluator"] = "arbiter"
    with pytest.raises(terms3.Refused, match="runs it again, not to an arbiter"):
        terms3.validate(doc, strict=False)
    doc["dispute"]["evaluator"] = "nobody"
    with pytest.raises(terms3.Refused, match=r"names one of `evaluators.list` \(neutral, own\)"):
        terms3.validate(doc, strict=False)
    named = terms3.template("bug-fix")
    named["dispute"]["arbiter"] = "@octocat"
    assert "@octocat, the arbiter, rules" in terms3.validate(named, strict=False)["dispute"]["says"]


def test_the_version_is_the_hash_of_the_canonical_bytes_whatever_the_order():
    doc = terms3.template("migration")
    back = json.loads(json.dumps({k: doc[k] for k in reversed(list(doc))}))
    back["changes"]["protected"].reverse()
    back["evidence"]["sources"].reverse()
    assert terms3.digest(back) == terms3.digest(doc) == hashlib.sha256(terms3.canonical(doc)).hexdigest()
    assert terms3.canonical(doc).isascii() and b" " not in terms3.canonical(doc).split(b'"says"')[0]
    other = copy.deepcopy(doc)
    other["deadline"]["days"] = 31
    assert terms3.digest(terms3.validate(other, strict=False)) != terms3.digest(doc)


def test_the_diff_is_by_meaning_and_names_the_field():
    a, b = terms3.template("bug-fix"), terms3.template("migration")
    got = terms3.diff(a, b)
    assert [f for f, _s in got] == ["checks", "window", "changes", "price", "deadline"]
    assert ("price", "The price changed: 50.00 test USDC before, 100.00 test USDC now.") in got
    assert ("window", "The reopening window changed: nothing held, no reopening before; 20% held for 30 days now.") in got
    assert terms3.diff(a, json.loads(json.dumps({k: a[k] for k in reversed(list(a))}))) == []
    c = copy.deepcopy(a)
    c["evaluators"] = {"quorum": 2, "list": [terms3._own("acme/widgets"), {**terms3._own("other/judge"), "name": "second"}]}
    c["dispute"]["arbiter"] = "octocat"
    c["policy"]["may_change"] = ["@acme", "@acme/platform"]
    c["changes"]["may_add"] = ["docs/**"]
    said = terms3.diff(a, terms3.validate(c, strict=False))
    assert [f for f, _s in said] == ["changes", "dispute", "evaluators", "evaluators", "policy"]
    assert "How many evaluators must agree changed: 1 before, 2 now." in [s for _f, s in said]
    text = terms3.diff_text(a, b, "bug-fix", "migration")
    assert "5 differences." in text and "  - [deadline] The deadline changed: 14 days from funding before, 30 days now." in text
    assert terms3.diff_text(a, a).startswith("Nothing changed: both are version ")


def test_the_order_a_document_funds_carries_the_documents_hash():
    doc = terms3.template("bug-fix")
    order = terms3.order_terms(doc)
    assert order["contract"] == terms3.digest(doc) and order["mode"] == "merge" and order["paths"] == ["src/**", "tests/**"]
    assert [c["name"] for c in order["checks"]] == ["lint", "unit"] and len(terms.canonical(order)) <= terms.MAX_BYTES
    assert terms.parse(terms.canonical(order)) == order                       # the format the program's order hashes
    other = terms3.template("bug-fix")
    other["deadline"]["days"] = 15                                            # nothing the 600 bytes held before: the hash still moves
    assert terms.terms_hash(terms3.order_terms(terms3.validate(other, strict=False))) != terms.terms_hash(order)
    assert terms3.comment(doc) == "/knos fund 50 checks: lint, unit paths: src/**, tests/** days 14"
    assert terms3.comment(terms3.template("migration")) == "/knos fund 100 checks: unit holdback 20 warranty 30 days 30"


def test_terms_without_a_contract_keep_the_bytes_and_hashes_they_had():
    old = terms_templates.terms_of(terms_templates.get("bugfix"))
    assert "contract" not in old and terms.terms_hash(old) == "91c3adb2adc12c66beb852fe809a096d4dd7028c0bc77ec209b6879ca753f2e3"
    with pytest.raises(terms.Refused, match="contract is the hash of the terms 3 document"):
        terms.canonical({**old, "contract": "not a hash"})


def test_an_order_that_is_not_the_documents_is_said_field_by_field():
    doc = terms3.template("migration")
    o = terms3.options(doc)
    assert o == {"units": 100_000_000, "days": 30, "holdback": 20, "warranty": 30, "quorum": 1, "arbiter": "", "judges": ["acme/widgets"]}
    same = dict(units_=o["units"], days=30, holdback=20, warranty=30, quorum=1, order_terms_=terms3.order_terms(doc))
    assert terms3.check_order(doc, **same) == []
    assert terms3.check_order(doc, **{**same, "days": 90, "holdback": 0}) == [
        "The order's deadline is 90 days; the terms say 30.", "The order's holdback is 0 percent; the terms say 20."]
    assert terms3.check_order(doc, **{**same, "order_terms_": terms3.order_terms(terms3.template("bug-fix"))}) == [
        "The order's checks, paths or contract hash are not the ones this version of the terms gives."]
    assert terms3.check_order(doc, **same, arbiter="mallory") == ["The order's arbiter is mallory; the terms name none."]


def test_only_an_authorised_evaluator_is_named_and_an_appeal_has_a_window():
    doc = terms3.template("dataset-batch")
    assert terms3.evaluator_allowed(doc, terms3.GITHUB, "acme/widgets", terms3.PROVE + "@refs/heads/main") == "own"
    assert terms3.evaluator_allowed(doc, terms3.GITHUB, "third/judge", terms3.ATTEST, parties=("acme", "vendor")) == "neutral"
    assert terms3.evaluator_allowed(doc, terms3.GITHUB, "vendor/judge", terms3.ATTEST, parties=("acme", "vendor")) is None
    assert terms3.evaluator_allowed(doc, terms3.GITLAB, "acme/widgets", terms3.PROVE) is None
    assert terms3.evaluator_allowed(doc, terms3.GITHUB, "acme/widgets", "acme/widgets/.github/workflows/mine.yml") is None
    assert terms3.appeal_open(doc, 1_000, 1_000 + 7 * 86400) and not terms3.appeal_open(doc, 1_000, 1_001 + 7 * 86400)


def test_support_resolution_is_published_as_not_built_and_funds_nothing():
    doc = terms3.template("support-resolution")
    assert doc["built"] is False and doc["needs"] == "a signing system of record" and not terms3.built(doc)
    assert terms3.NOT_BUILT == "not built: needs a signing system of record"
    assert doc["evidence"]["sources"] == [] and doc["evaluators"]["list"] == []
    with pytest.raises(terms3.Refused, match="cannot fund an order: not built: needs a signing system of record"):
        terms3.order_terms(doc)
    built = terms3.template("bug-fix")
    built["evidence"]["sources"] = []
    with pytest.raises(terms3.Refused, match="nothing a third party signed counts"):
        terms3.validate(built, strict=False)


def test_the_registry_lists_every_version_with_its_hash_and_older_files_keep_theirs():
    rows = terms_registry.check3(ROOT / "terms")
    assert [(r["name"], r["version"]) for r in rows] == [("bug-fix", 1), ("dataset-batch", 1), ("migration", 1), ("support-resolution", 1)]
    for r in rows:
        text = (ROOT / "terms" / "3" / r["name"] / f"{r['version']}.json").read_text(encoding="utf-8")
        doc = json.loads(text)
        assert hashlib.sha256(text.encode()).hexdigest() == r["file_sha256"] and terms3.digest(doc) == r["hash"]
        assert r["cite"] == terms3.cite(doc) == f"Acceptance is governed by Knos Terms 3, {r['name']} version 1, sha256 {r['hash']}"
        assert r["comment"] == (terms3.comment(doc) if r["built"] else "") and terms_registry.verify3(doc, ROOT / "terms") == (r["hash"], [r])
    assert _script().build(write=False) == []                                # the registry is what the code publishes
    index = json.loads((ROOT / "terms" / "index.json").read_text(encoding="utf-8"))
    assert index["standard"] == "Knos Terms 1" and index["terms3"]["standard"] == "Knos Terms 3"
    for rel, sha in OLDER.items():                                           # the older files: byte for byte what they were
        assert hashlib.sha256((ROOT / "terms" / rel).read_bytes()).hexdigest() == sha
    assert len(terms_registry.check(ROOT / "terms")) == 5


def test_a_published_terms_3_file_is_never_rewritten(tmp_path, monkeypatch):
    reg = _script()
    root = Path(shutil.copytree(ROOT / "terms", tmp_path / "terms"))
    path = root / "3" / "migration" / "1.json"
    was = path.read_text(encoding="utf-8")
    path.write_text(was.replace('"days": 30', '"days": 31'), encoding="utf-8", newline="")
    with pytest.raises(terms_registry.Changed, match=r"terms/3/migration/1.json changed after it was published: restore it, and publish the change as version 2"):
        reg.build(root)
    path.write_text(was, encoding="utf-8", newline="")
    (root / "3" / "migration" / "7.json").write_text(was, encoding="utf-8")
    with pytest.raises(terms_registry.Changed, match="is not listed in terms/index.json"):
        terms_registry.check3(root)
    (root / "3" / "migration" / "7.json").unlink()
    longer = terms3.TEMPLATES["migration"]
    monkeypatch.setitem(terms3.TEMPLATES, "migration", lambda: terms3.validate({**longer(), "deadline": {"days": 45, "late": "refused"}}, strict=False))
    assert reg.build(root) == ["3/migration/2.json", "index.json"]
    assert path.read_text(encoding="utf-8") == was                           # version 1 stayed
    two = terms_registry.read3("migration", root=root)
    assert two["version"] == 2 and two["deadline"]["days"] == 45 and terms_registry.read3("migration", 1, root)["deadline"]["days"] == 30
    assert reg.build(root) == []


def test_knos_terms_verify_refuses_a_file_missing_a_field_and_says_which(tmp_path):
    app, run = _app(), CliRunner()
    doc = terms3.template("bug-fix")
    whole = tmp_path / "whole.json"
    whole.write_text(terms3.dumps(doc), encoding="utf-8")
    got = run.invoke(app, ["terms", "verify", str(whole)])
    assert got.exit_code == 0 and f"Knos Terms 3, bug-fix version 1, sha256 {terms3.digest(doc)}" in got.output
    assert "Who may appeal, and to whom? The supplier may appeal a rejection within 7 days" in got.output
    del doc["dispute"]
    part = tmp_path / "part.json"
    part.write_text(json.dumps(doc), encoding="utf-8")
    got = run.invoke(app, ["terms", "verify", str(part)])
    assert got.exit_code == 1 and got.output.startswith("This terms 3 file is missing `dispute` (who may appeal, to which evaluator, by when")
    mine = terms3.validate({**terms3.base("octo/app", name="octo/app"), "price": {"amount": "75.00", "currency": "test USDC"}}, strict=False)
    own = tmp_path / "own.json"
    own.write_text(terms3.dumps(mine), encoding="utf-8")
    got = run.invoke(app, ["terms", "verify", str(own)])
    assert got.exit_code == 0 and "Complete: all ten fields are there. It is not one of the published templates" in got.output
    unbuilt = tmp_path / "support.json"
    unbuilt.write_text(terms3.dumps(terms3.template("support-resolution")), encoding="utf-8")
    assert "This template cannot fund an order: not built: needs a signing system of record." in run.invoke(app, ["terms", "verify", str(unbuilt)]).output
    older = run.invoke(app, ["terms", "verify", "91c3adb2adc12c66beb852fe809a096d4dd7028c0bc77ec209b6879ca753f2e3"])
    assert older.exit_code == 0 and "Knos Terms 1, template bugfix version 1" in older.output          # the older format still verifies


def test_knos_terms_diff_shows_the_semantic_diff_between_versions(tmp_path):
    app, run = _app(), CliRunner()
    got = run.invoke(app, ["terms", "diff", "bug-fix", "migration@1"])
    assert got.exit_code == 0 and "[price] The price changed: 50.00 test USDC before, 100.00 test USDC now." in got.output
    two = terms3.template("bug-fix")
    two["version"], two["dispute"]["within_days"] = 2, 14
    path = tmp_path / "two.json"
    path.write_text(terms3.dumps(terms3.validate(two, strict=False)), encoding="utf-8")
    got = run.invoke(app, ["terms", "diff", "bug-fix", str(path)])
    assert "  - [dispute] The time to appeal changed: 7 days before, 14 days now.\n\n1 difference." in got.output
    mixed = run.invoke(app, ["terms", "diff", "bugfix", "bug-fix"])
    assert mixed.exit_code == 1 and "One of the two is Knos Terms 3 and the other is not" in mixed.output
    assert run.invoke(app, ["terms", "diff", "bugfix", "milestone"]).exit_code == 0                      # the older diff is as it was
