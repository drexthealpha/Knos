"""The assurance level of a receipt (version 5) and of a statement line: computed from the evidence, never typed; the
control relationships the terms declare; and the goods-received note. docs/receipt/vectors.v5.json and the version 5
schema are written from here: `python tests/test_assurance.py --write`."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

import _assurance as A  # noqa: E402
from knos import receipt, statement  # noqa: E402

FILE = ROOT / "docs" / "receipt" / "vectors.v5.json"
SCHEMA = ROOT / "docs" / "receipt" / "acceptance-receipt.v5.schema.json"
NOTE = ("Conformance vectors of the acceptance receipt, version 5 (docs/reference/RECEIPT.md, Version 5). A reader must accept every receipt of `valid_v5`, compute its "
        "digest and say its `assurance` level from the receipt's own evidence, and refuse every one of `invalid_v5`: `of` is the index of the valid receipt it "
        "was made from and `set` the fields changed (dotted paths). `verdict` and `authorises_payment` are as in version 4.")


def valid() -> list[dict]:
    agreed = A.five("agreed")
    made = [
        ("reported: version 4's first receipt as version 5; the order's own repository judged and nobody ran the suite again", receipt.build5(A.V4[0]["receipt"])),
        ("rerun: an arbiter outside the order's repository, no payee's account, ran the suite itself", A.five("rerun")),
        ("agreed: a neutral evaluator of another owner ran it too, and both passed", agreed),
        ("rerun, not agreed: the terms declare the two evaluators' owners to be one party", A.five("agreed", [[9001, 31337]])),
        ("reported, not rerun: the terms declare the evaluator and a payee to be one party", A.five("rerun", [[31337, 222]])),
        ("reported: a rejected run nobody signed; no issuer is among the trusted", receipt.build5(A.V4[5]["receipt"])),
        ("agreed and disputed: the buyer contests it; the level is of the evidence and does not move",
         receipt.dispute(agreed, role="buyer", by="octo-buyer", at=agreed["transaction"]["time"] + 600, reason="The suite did not cover the change.")),
    ]
    return [{"name": name, "sha256": receipt.digest(r), "verdict": receipt.verdict_of(r), "authorises_payment": receipt.authorises_payment(r),
             "assurance": r["assurance"]["level"], "receipt": r} for name, r in made]


INVALID = [
    {"name": "a level typed higher than the evidence gives", "of": 0, "set": {"assurance.level": "agreed"}, "why": "computed from the evidence, not chosen"},
    {"name": "a level typed lower than the evidence gives", "of": 2, "set": {"assurance.level": "reported"}, "why": "computed from the evidence, not chosen"},
    {"name": "attested: defined, and nothing reaches it", "of": 2, "set": {"assurance.level": "attested"}, "why": "nothing recorded today reaches it"},
    {"name": "a trusted party left out", "of": 1, "set": {"assurance.trusted": []}, "why": "computed from the evidence, not chosen"},
    {"name": "the declared relationship dropped, the level kept", "of": 3, "set": {"assurance.declared_related": []}, "why": "computed from the evidence, not chosen"},
    {"name": "a declared relationship added to a receipt that agreed", "of": 2, "set": {"assurance.declared_related": [[9002, 31337]]}, "why": "computed from the evidence, not chosen"},
    {"name": "a declared group of one account", "of": 0, "set": {"assurance.declared_related": [[7]]}, "why": "two or more account ids"},
    {"name": "a declared group out of order", "of": 3, "set": {"assurance.declared_related": [[31337, 9001]]}, "why": "in rising order"},
    {"name": "no assurance at all", "of": 0, "set": {"assurance": None}, "why": "assurance is {level"},
    {"name": "a field more in assurance", "of": 0, "set": {"assurance.by": "the supplier"}, "why": "assurance is {level"},
    {"name": "version 4's rules still hold: an accepted receipt with a failed check", "of": 1, "set": {"evaluator_observed.verdict": "rejected"},
     "why": "authorises no payment and records none"},
    {"name": "a dispute that names another receipt", "of": 6, "set": {"disputed.contests.sha256": "0" * 64}, "why": "the digest of the receipt contested"},
]


def schema() -> dict:
    four = json.loads((ROOT / "docs" / "receipt" / "acceptance-receipt.v4.schema.json").read_text(encoding="utf-8"))
    ids = {"type": "array", "minItems": 2, "maxItems": 16, "uniqueItems": True, "items": {"type": "integer", "minimum": 1}}
    return {**four, "$id": four["$id"].replace(".v4.", ".v5."), "title": "Knos acceptance receipt, version 5",
            "description": "Version 4, with `assurance`: how much was verified (reported, rerun, agreed; attested is defined and no receipt may say it yet), who is "
                           "still trusted at that level, and the groups of account ids the terms declare to be one party. The level is computed from the "
                           "receipt's own evidence (knos.receipt.assurance_of); a schema cannot say that rule, `check` does.",
            "required": sorted([*four["required"], "assurance"]),
            "properties": {**four["properties"], "version": {"const": 5},
                           "assurance": {"type": "object", "additionalProperties": False, "required": ["declared_related", "level", "trusted"],
                                         "properties": {"level": {"enum": ["reported", "rerun", "agreed"]},
                                                        "trusted": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                                                        "declared_related": {"type": "array", "maxItems": 16, "items": ids}}}}}


def _changed(v: dict, of: list[dict]) -> dict:
    r = copy.deepcopy(of[v["of"]]["receipt"])
    for path, value in v["set"].items():
        at = r
        *way, last = path.split(".")
        for k in way:
            at = at[k]
        at[last] = value
    return r


def test_the_vectors_and_the_schema_are_the_ones_the_code_writes():
    assert json.loads(FILE.read_text(encoding="utf-8")) == {"note": NOTE, "valid_v5": valid(), "invalid_v5": INVALID}, "python tests/test_assurance.py --write"
    assert json.loads(SCHEMA.read_text(encoding="utf-8")) == schema()


def test_every_level_is_computed_from_the_evidence_and_each_names_who_stays_trusted():
    got = valid()
    assert [v["assurance"] for v in got] == ["reported", "rerun", "agreed", "rerun", "reported", "reported", "agreed"]
    for v in got:
        r = v["receipt"]
        assert receipt.check(r) is None and r["assurance"] == receipt.assurance_of(r, r["assurance"]["declared_related"])
        assert r["assurance"]["trusted"] and r["assurance"]["trusted"][-1] == receipt.TRUSTED[v["assurance"]][-1]
        assert receipt.as4(r)["version"] == 4 and receipt.check(receipt.as4(r)) is None                 # a reader of version 4 is given version 4
        said = "\n".join(receipt.render(r))
        assert f"Assurance: {v['assurance']} ({receipt.LEVEL_WORDS[v['assurance']]})." in said and "Still trusted at this level:" in said
    assert receipt.LEVELS == ("reported", "rerun", "agreed", "attested") and set(receipt.TRUSTED) == set(receipt.LEVELS) == set(receipt.LEVEL_WORDS)
    assert len({tuple(t) for t in receipt.TRUSTED.values()}) == 4                                       # each level trusts a different set
    assert got[5]["receipt"]["assurance"]["trusted"][0].startswith("Whoever keeps the run's own record")          # nobody signed: no issuer to trust
    for v in INVALID:
        why = receipt.check(_changed(v, got))
        assert why is not None and v["why"] in why, (v["name"], why)


def test_attested_is_defined_and_no_receipt_reaches_it():
    assert receipt.UNREACHABLE == ("attested",)
    for level in ("reported", "rerun", "agreed"):
        for r in (A.five(level), A.five(level, [[9001, 31337]])):
            assert r["assurance"]["level"] != "attested"
            assert "nothing recorded today reaches it" in receipt.check({**r, "assurance": {**r["assurance"], "level": "attested", "trusted": receipt.TRUSTED["attested"]}})


def test_two_evaluators_never_agree_when_their_owners_match_or_the_terms_declare_them_related():
    apart = A.three("agreed")
    judges = apart["evaluator_observed"]["evaluators"]
    assert [(e["kind"], e["owner_id"], e["actor_id"]) for e in judges] == [("neutral", 9001, 9002), ("arbiter", 31337, 31337)]         # each names its owner and its actor
    assert receipt.assurance_of(apart)["level"] == "agreed" and receipt.independence_of(judges)[0] is False
    for declared in ([[9001, 31337]], [[9002, 31337]], [[9001, 5], [5, 31337]], [[31337, 77], [77, 9002, 12]]):       # owners, a starter, or through a third account
        assert receipt.assurance_of(apart, declared)["level"] == "rerun", declared
        same, said = receipt.independence_of(judges, declared)
        assert same and "the terms declare accounts" in said and "one party" in said
        assert "DECLARED RELATED." in "\n".join(receipt.render(A.five("agreed", declared)))
    assert receipt.related([[9001, 5], [5, 31337], [8, 7]]) == [[5, 9001, 31337], [7, 8]]
    # the same owner: version 3 already says so, and no declaration is needed
    one = copy.deepcopy(apart)
    one["evaluator_observed"]["evaluators"][0].update(owner_id=31337)
    one["evaluator_observed"]["same_controller"], one["evaluator_observed"]["independence"] = receipt.independence_of(one["evaluator_observed"]["evaluators"])
    assert receipt.check(one) is None and one["evaluator_observed"]["same_controller"] is True and receipt.assurance_of(one)["level"] == "rerun"
    # an evaluator a payee runs, or one declared related to a payee, is not outside the supplier's control
    assert receipt.assurance_of(A.three("rerun"), [[31337, 444]])["level"] == "reported"
    mine = A.V3[1]["receipt"]                                                                          # the neutral judge is run by a payee
    mine = {**mine, "evaluator_observed": {**mine["evaluator_observed"], "evaluators": [{**mine["evaluator_observed"]["evaluators"][0],
                                                                                          "reexecution": A.ran(mine["issuer_authenticated"]["claims"])}]}}
    assert receipt.check(mine) is None and receipt.assurance_of(mine)["level"] == "reported"
    for bad in ("x", [[1]], [[1, "2"]], [[0, 4]], [1, 2]):
        with pytest.raises(ValueError, match="two or more account ids"):
            receipt.related(bad)


def test_older_receipts_still_verify_and_read_as_reported_unless_their_evidence_shows_more():
    old = json.loads((ROOT / "docs" / "receipt" / "vectors.json").read_text(encoding="utf-8"))
    seen = 0
    for group in ("valid", "valid_v2", "valid_v3"):
        for v in old[group]:
            assert receipt.check(v["receipt"]) is None and receipt.digest(v["receipt"]) == v["sha256"]
            assert receipt.assurance_of(v["receipt"])["level"] == "reported"
            seen += 1
    for v in A.V4:
        assert receipt.check(v["receipt"]) is None and receipt.digest(v["receipt"]) == v["sha256"] and receipt.assurance_of(v["receipt"])["level"] == "reported"
        five = receipt.build5(v["receipt"])
        assert receipt.as4(five) == v["receipt"] and receipt.verdict_of(five) == v["verdict"] and receipt.authorises_payment(five) == v["authorises_payment"]
        seen += 1
    assert seen == 27
    assert receipt.assurance_of(A.three("rerun"))["level"] == "rerun" and receipt.assurance_of(receipt.build4(A.three("agreed")))["level"] == "agreed"
    # the chain alone does not carry the runs' own words: a mirror's copy says reported
    assert receipt.chain_only(A.five("agreed"))["assurance"]["level"] == "reported"


# ---- the statement line and the goods-received note -----------------------------------------------------------------------

def _sept():
    import test_statement as T
    return T.sept(), T.status()


def test_every_statement_line_says_its_level_and_a_note_matches_three_legs_or_says_the_mismatch():
    st, s = _sept()
    assert [ln["assurance"] for ln in statement.lines_now(st, s)] == ["reported", "reported", "reported", statement.NOT_EVALUATED, "reported"]
    first, last = st["lines"][0]["invoice_line"], st["lines"][4]["invoice_line"]
    bare = statement.grn(st, s, first)
    assert bare["purchase_order"] is None and not bare["match"] and bare["mismatches"] == [statement.NO_ORDER["shadow"]]
    # the three legs from the payment's receipt: a match
    r = A.five("rerun", invoice_line=first, times=2)                                              # the order's price is 100.00
    note = statement.grn(st, s, first, r, "PO-2026-0931")
    assert note["match"] and note["mismatches"] == [] and note["reference"].startswith("grn_")
    po, goods, line = note["purchase_order"], note["receipt_of_goods"], note["invoice_line"]
    assert (po["number"], po["order"], po["terms_hash"], po["price"]) == ("PO-2026-0931", r["order"], r["policy"]["terms_hash"], "100.00") and po["approver"].startswith("wallet ")
    assert (goods["assurance"], goods["verdict"], goods["receipt_sha256"]) == ("rerun", "accepted", receipt.digest(r)) and goods["trusted"] == receipt.TRUSTED["rerun"]
    assert goods["controllers"] == [{"kind": "arbiter", "owner_id": 31337, "actor_id": 31337}] and goods["evidence"].startswith("issuer token ")
    assert (line["id"], line["amount"], line["state"]) == (first, "100.00", "agreed")
    text = statement.grn_lines(note)
    assert text[1].split("|")[0].strip() == "PURCHASE ORDER" and "RECEIPT OF GOODS" in text[1] and "INVOICE LINE" in text[1] and "MATCH" in text and "assurance rerun" in "\n".join(text)
    # each exact mismatch, in words
    small = statement.grn(st, s, first, A.five("rerun", invoice_line=first))
    assert small["mismatches"] == ["the invoice line bills 100.00; the order's price is 50.00"]
    other = statement.grn(st, s, first, A.five("rerun", times=2))
    assert len(other["mismatches"]) == 1 and other["mismatches"][0].startswith("nothing ties this receipt to this line")
    contested = receipt.dispute(r, role="buyer", by="octo", at=r["transaction"]["time"] + 5, reason="not what was ordered")
    assert statement.grn(st, s, first, contested)["mismatches"] == ["the receipt's verdict is disputed: it authorises no payment"]
    second = st["lines"][1]["invoice_line"]
    held = statement.grn(st, s, second, A.five("rerun", invoice_line=second, times=10))["mismatches"]
    assert len(held) == 1 and held[0].startswith("the invoice line is disputed: a check failed")
    twice = statement.grn(st, s, st["lines"][3]["invoice_line"])
    assert twice["mismatches"][1] == "no receipt of goods: no evaluation of this line is on record" and twice["mismatches"][2].startswith("the invoice line is duplicate")
    with pytest.raises(statement.Refused, match="not a valid acceptance receipt"):
        statement.grn(st, s, first, {**r, "assurance": {**r["assurance"], "level": "agreed"}})
    # recorded: the line, the CSV and the exports then carry the purchase order, the note and the level
    from knos import exports
    kept = statement.grn_record(st, s, last, "2026-10-04", A.five("agreed", invoice_line=last, times=2), "PO-2026-0932")
    now = statement.lines_now(st, kept)[4]
    assert (now["assurance"], now["po_reference"], now["grn_reference"]) == ("agreed", "PO-2026-0932", statement.grn_reference(st["lines"][4]))
    assert statement.grn(st, kept, last)["recorded"] == "2026-10-04" and statement.grn(st, kept, last)["match"]
    assert statement.HEAD[-3:] == ("assurance", "po_reference", "grn_reference") and exports.STATEMENT_GENERIC[-3:] == ("po_reference", "grn_reference", "assurance")
    assert statement.cells(st, kept)["rows"][4][-3:] == ["agreed", "PO-2026-0932", now["grn_reference"]] and "goods-received note,2026-10-04" in statement.as_csv(st, kept)
    generic = exports.write_statement("generic", st, kept).splitlines()
    assert exports.LABEL == "file export, not an integration" and exports.LABEL in generic[0] and generic[6].endswith(f"PO-2026-0932,{now['grn_reference']},agreed")
    for fmt in ("quickbooks", "netsuite"):
        memo = exports.write_statement(fmt, st, kept).splitlines()[-1]
        assert f"PO PO-2026-0932 | GRN {now['grn_reference']} | assurance agreed" in memo
    assert statement.verify(st)[0] and statement.verify(json.loads(statement.canonical(st)))[1] == "same"          # the statement itself did not change


def test_the_command_shows_a_note_and_records_one(tmp_path):
    typer = pytest.importorskip("typer")
    from typer.testing import CliRunner
    app = typer.Typer()
    statement.register(app)
    st, s = _sept()
    file, line = tmp_path / "ap-statement.json", st["lines"][0]["invoice_line"]
    file.write_bytes(statement.canonical(st))
    (tmp_path / "ap-statement.status.json").write_bytes(statement.canonical(s))
    (tmp_path / "receipt.json").write_text(json.dumps(A.five("rerun", invoice_line=line, times=2)), encoding="utf-8")
    run = CliRunner()
    bare = run.invoke(app, ["statement", "grn", str(file), "--line", line])
    assert bare.exit_code == 1 and "MISMATCH" in bare.output and "no purchase order on record" in bare.output
    done = run.invoke(app, ["statement", "grn", str(file), "--line", line, "--receipt", str(tmp_path / "receipt.json"), "--po", "PO-7", "--record", "--on", "2026-10-04"])
    assert done.exit_code == 0 and "MATCH" in done.output and "number PO-7" in done.output and "assurance rerun" in done.output, done.output
    again = run.invoke(app, ["statement", "grn", str(file), "--line", line, "--json"])
    assert again.exit_code == 0 and json.loads(again.output)["recorded"] == "2026-10-04" and json.loads(again.output)["purchase_order"]["number"] == "PO-7"
    assert ",rerun,PO-7,grn_" in (tmp_path / "ap-statement.csv").read_text(encoding="utf-8")
    assert run.invoke(app, ["statement", "verify", str(file)]).output.splitlines() == ["same", "ap-statement.csv: same", "ap-statement.pdf: same"]


def test_the_documents_say_the_levels_the_declared_list_and_the_note():
    doc = (ROOT / "docs" / "reference" / "RECEIPT.md").read_text(encoding="utf-8")
    for level in receipt.LEVELS:
        assert f"`{level}`" in doc
    for said in ("## Version 5", "computed from the evidence", "declared_related", "no receipt may say `attested`", "vectors.v5.json", "acceptance-receipt.v5.schema.json"):
        assert said in doc, said
    fin = (ROOT / "docs" / "reference" / "FINANCE.md").read_text(encoding="utf-8")
    for said in ("knos statement grn", "three-way match", "po_reference", "grn_reference", "assurance", "file export, not an integration"):
        assert said in fin, said


if __name__ == "__main__" and "--write" in sys.argv:
    FILE.write_text(json.dumps({"note": NOTE, "valid_v5": valid(), "invalid_v5": INVALID}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    SCHEMA.write_text(json.dumps(schema(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print("wrote", FILE.name, SCHEMA.name)
