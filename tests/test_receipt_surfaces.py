"""The five parts wherever a receipt leaves Knos, and terms that require an assurance level before payment: a statement
line links its parts, the paid record answer carries them (and is invalid without them), and Knos Terms 3 can refuse a
payment below `checks.min_assurance`. Fixed data, no network, no clock."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_exports_match as M                                  # noqa: E402
import test_record_answer as RA                                 # noqa: E402
import test_statement as T                                      # noqa: E402

from knos import receipt, statement, terms3                     # noqa: E402
from knos import record_answer as ra                            # noqa: E402


def test_the_five_parts_are_one_list_everywhere():
    assert statement.FIVE == ra.FIVE == receipt.FIVE
    assert tuple(statement.LEVEL_SAYS) == receipt.LEVELS and statement.LEVEL_SAYS == receipt.LEVEL_WORDS
    assert terms3.ASSURANCE == tuple(x for x in receipt.LEVELS if x not in receipt.UNREACHABLE)


def test_every_statement_line_links_its_five_parts():
    st, noted = T.sept(), M.noted()
    lines = statement.lines_now(st, noted)
    assert all(receipt.five_missing(ln["parts"]) == [] for ln in lines)
    plain = [ln for ln in lines if ln["parts"]["receipt_sha256"] is None]
    assert plain and all("No receipt was read" in ln["parts"]["assurance"] or ln["parts"]["assurance"].startswith("Not evaluated") for ln in plain)
    linked = [ln for ln in lines if ln["parts"]["receipt_sha256"]]
    assert len(linked) == 1
    grn = next(e["grn"] for e in noted["events"] if e["type"] == "grn")
    assert linked[0]["parts"]["receipt_sha256"] == grn["receipt_of_goods"]["receipt_sha256"]       # the line links the receipt it was read from


def test_the_paid_record_answer_carries_its_five_parts_and_is_invalid_without_them():
    reply = RA._reply()
    a = reply["answer"]
    assert receipt.five_missing(a["parts"]) == [] and "authorises no payment" in a["parts"]["consequence"]
    assert ra.verify(reply, RA.NOW + 10)["state"] == "fresh"
    for cut in ("drop", "blank"):
        bad = copy.deepcopy(reply)
        if cut == "drop":
            del bad["answer"]["parts"]
        else:
            bad["answer"]["parts"]["assurance"] = ""
        got = ra.verify(bad, RA.NOW + 10)
        assert got["state"] == "invalid" and "five parts" in got["why"]
    unsigned = RA._reply(key=None)
    del unsigned["answer"]["parts"]
    assert ra.verify(unsigned, RA.NOW + 10)["state"] == "invalid"


def _floor(level: str) -> dict:
    doc = terms3.template("bug-fix")
    doc["checks"] = {**doc["checks"], "min_assurance": level}
    return terms3.validate(doc, strict=False)


def test_terms_can_require_an_assurance_level_for_payment():
    doc = _floor("rerun")
    assert "Nothing is paid below the assurance level `rerun`." in doc["checks"]["says"]
    assert terms3.payment_refusal(doc, "reported").startswith("The terms pay only at the assurance level `rerun`")
    assert terms3.payment_refusal(doc, "rerun") is None and terms3.payment_refusal(doc, "agreed") is None
    assert terms3.payment_refusal(doc, statement.NOT_EVALUATED) is not None
    assert terms3.payment_refusal(terms3.template("bug-fix"), "reported") is None              # terms without it pay as they did
    assert terms3.digest(terms3.template("bug-fix")) != terms3.digest(doc)                     # the floor is part of the version
    with pytest.raises(terms3.Refused, match="attested"):
        _floor("attested")
    assert terms3.diff(terms3.template("bug-fix"), doc) == [("checks", "The assurance level a payment needs changed: any before, rerun now.")]


def test_a_statement_payment_below_the_terms_floor_is_refused():
    st, noted = T.sept(), M.noted()
    lines = statement.lines_now(st, noted)
    low = next(ln for ln in lines if ln["state"] == "agreed" and ln["assurance"] == "reported")
    high = next(ln for ln in lines if ln["parts"]["receipt_sha256"])
    with pytest.raises(statement.Refused, match="assurance level `rerun`"):
        statement.pay(st, noted, low["invoice_line"], "bank", "BACS 1", "2026-10-05", terms_doc=_floor("rerun"))
    assert statement.pay(st, noted, low["invoice_line"], "bank", "BACS 1", "2026-10-05", terms_doc=_floor("reported"))["events"][-1]["reference"] == "BACS 1"
    if high["assurance"] in terms3.ASSURANCE:
        allowed = terms3.ASSURANCE[: terms3.ASSURANCE.index(high["assurance"]) + 1]
        assert statement.pay(st, noted, high["invoice_line"], "bank", "BACS 2", "2026-10-05", terms_doc=_floor(allowed[-1]))["events"][-1]["reference"] == "BACS 2"
    held = statement.pay(st, noted, low["invoice_line"], "bank", "BACS 3", "2026-10-05", state="held", terms_doc=_floor("agreed"))
    assert held["events"][-1]["state"] == "held"                                                # holding is not paying
