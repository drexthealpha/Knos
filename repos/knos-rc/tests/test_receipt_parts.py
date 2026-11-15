"""The five parts of a receipt (knos.receipt.parts): Identity, Execution, Acceptance, Consequence, Assurance.

A view over receipts of version 4 and 5: nothing is added to a receipt and no version is new. tests/data/receipt_parts.json
holds receipts and what the view says of each; web/verifier.js reads the same receipts in the page and is held to the same
answer, word for word (here with node alone, and in tests/web/verifier.mjs).

    WRITE_RECEIPT_PARTS=1 pytest tests/test_receipt_parts.py       writes the file again
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from knos import receipt as rc

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "data" / "receipt_parts.json"
V4 = json.loads((ROOT / "docs" / "receipt" / "vectors.v4.json").read_text(encoding="utf-8"))["valid_v4"]
V5 = json.loads((ROOT / "docs" / "receipt" / "vectors.v5.json").read_text(encoding="utf-8"))["valid_v5"]


def _by(name: str) -> dict:
    return next(v["receipt"] for v in [*V4, *V5] if v["name"].startswith(name))


def _suite(r5: dict) -> dict:
    """The same version 5 receipt for an order paid on its acceptance suite: the vectors' evaluators ran one."""
    r = copy.deepcopy(rc.as4(r5))
    o = r["evaluator_observed"]
    r["policy"]["mode"] = "tests"
    r["trust_remaining"] = rc.trust_of(r["issuer_authenticated"]["provider"], "tests", o["judge"]["kind"])
    r["limitations"] = rc.limitations_of("issuer_token", o["verdict"], "tests", True, True)
    return rc.build5(r, r5["assurance"]["declared_related"])


def _cases() -> list[dict]:
    rows = [(v["name"], v["receipt"]) for v in [*V4, *V5]]
    rows += [("a suite decided and one evaluator outside the supplier's control ran it again", _suite(_by("rerun: an arbiter"))),
             ("a suite decided and two evaluators of different owners agree", _suite(_by("agreed: a neutral")))]
    return [{"name": name, "receipt": r, "parts": rc.parts(r)} for name, r in rows]


def test_the_file_of_cases_is_what_the_view_says_today():
    want = json.dumps({"about": "receipts of version 4 and 5 and what knos.receipt.parts says of each (tests/test_receipt_parts.py writes this)",
                       "cases": _cases()}, indent=1, sort_keys=True) + "\n"
    if os.environ.get("WRITE_RECEIPT_PARTS"):
        CASES.write_text(want, encoding="utf-8", newline="\n")
    assert CASES.read_text(encoding="utf-8") == want, "tests/data/receipt_parts.json is behind: WRITE_RECEIPT_PARTS=1 writes it"


def test_every_receipt_reads_in_five_parts_in_order_each_one_line():
    for case in _cases():
        got = case["parts"]
        assert [p["id"] for p in got["parts"]] == list(rc.FIVE) == ["identity", "execution", "acceptance", "consequence", "assurance"]
        assert got["kind"] == rc.PARTS_KIND and got["receipt"] == rc.digest(case["receipt"]) and got["version"] in (4, 5)
        for p in got["parts"]:
            assert p["title"] == rc.FIVE_TITLES[p["id"]] and p["asks"].endswith("?") and "\n" not in p["line"] and p["line"].endswith(".") and p["more"], case["name"]
        assert got["authorises_payment"] is rc.authorises_payment(case["receipt"])


def test_the_view_adds_nothing_to_the_receipt_and_makes_no_new_version():
    r = _by("reported: version 4's first")
    before = rc.canonical(r)
    rc.parts(r)
    assert rc.canonical(r) == before and rc.check(r) is None
    assert rc.TYPE == "knos.acceptance-receipt" and rc.check({**r, "version": 6}) is not None


def test_identity_says_issuer_repository_workflow_and_run_or_that_nobody_signed():
    r = _by("reported: version 4's first")
    cl = r["issuer_authenticated"]["claims"]
    ident = rc.parts(r)["parts"][0]
    assert ident["facts"]["signed"] and ident["facts"]["issuer"] == "https://token.actions.githubusercontent.com"
    assert (ident["facts"]["repository"], ident["facts"]["workflow"], ident["facts"]["run"]) == (cl["repository_id"], cl["job_workflow_ref"], cl["run_id"])
    assert ident["line"] == f"GitHub signed: workflow {cl['job_workflow_ref']} ran in repository {cl['repository_id']}, run {cl['run_id']}."
    none = rc.parts(_by("reported: a rejected run nobody signed"))["parts"][0]
    assert none["facts"]["signed"] is False and none["line"] == "Nobody signed: the evidence is the run's own record."


def test_execution_names_the_evaluator_and_its_inputs_by_hash():
    r = _suite(_by("agreed: a neutral"))
    ex = rc.parts(r)["parts"][1]
    o = r["evaluator_observed"]
    assert ex["facts"]["commit"] == o["artifact"]["commit"] and ex["facts"]["evaluator_version"] == o["judge"]["version"]
    assert [e["reexecuted"] for e in ex["facts"]["evaluators"]] == [True, True] and "2 of 2 ran the suite again." in ex["line"]
    assert ex["more"][0].startswith(f"Inputs by hash: commit {o['artifact']['commit']}; workflow {o['judge']['version']}; terms {r['policy']['terms_hash']}")


def test_acceptance_names_the_test_that_passed_and_the_terms_hash():
    r = _by("reported: version 4's first")
    acc = rc.parts(r)["parts"][2]
    assert acc["facts"]["terms_hash"] == r["policy"]["terms_hash"] and acc["facts"]["predicate"] == {"mode": "merge", "checks": r["evaluator_observed"]["checks"]}
    assert acc["line"].startswith("Accepted: a merge, and the named checks (build: passed, test: passed) passed, under terms ")
    assert rc.parts(_by("rejected: a check failed"))["parts"][2]["line"].startswith("Rejected: the acceptance suite the terms pin, and the named checks (build: passed, test: failed) did not pass")
    contested = rc.parts(_by("agreed and disputed"))["parts"][2]
    assert contested["facts"]["contested"] == {"by": "buyer", "was": "accepted"} and contested["line"].startswith("Disputed: ")


def test_consequence_says_what_became_payable_to_whom_in_which_order_or_that_nothing_did():
    r = _by("rerun: an arbiter")
    con = rc.parts(r)["parts"][3]
    assert con["facts"]["order"] == r["order"] and con["facts"]["payable"] == r["amounts"]["paid"] and con["facts"]["transaction"] == r["transaction"]["signature"]
    assert con["line"].startswith("50.00 of 50.00 paid to account 111, account 222, account 333, account 444 (test money on devnet), order ")
    none = rc.parts(_by("rejected: a check failed"))["parts"][3]
    assert none["facts"]["payable"] == "0" and none["facts"]["transaction"] is None and none["line"].startswith("Nothing became payable: order ")


def test_a_valid_signature_on_a_weak_test_reads_as_weak():
    """The receipt is valid, the issuer signed, the money moved: and the assurance line starts with WEAK and says why."""
    r = _by("reported: version 4's first")
    got = rc.parts(r)
    assert rc.check(r) is None and r["issuer_authenticated"] is not None and got["authorises_payment"] and got["weak"]
    a = got["parts"][4]
    assert a["line"].startswith("WEAK (reported): ") and a["facts"]["weak_because"] == [rc.O_REPORTED]
    assert rc.O_WORKFLOW in a["facts"]["outside"] and rc.O_OWN_REPO in a["facts"]["outside"] and rc.O_TERMS in a["facts"]["outside"]
    assert "The workflow file decides what it reads" in rc.O_WORKFLOW
    # a merge with no named check is the weakest acceptance there is, whoever ran what
    assert rc.O_MERGE in rc.parts(_by("rerun: an arbiter"))["parts"][4]["facts"]["weak_because"]


def test_an_evaluator_run_by_the_payee_is_said_in_those_words():
    got = rc.parts(_by("accepted and paid: a wallet funds with no limit; the neutral judge is run by a payee"))
    why = got["parts"][4]["facts"]["weak_because"]
    assert got["weak"] and any(s.startswith("The evaluator's account is the payee's: account ") for s in why), why
    one = rc.parts(_by("accepted and paid: a listed spender funds"))["parts"][4]["facts"]["weak_because"]
    assert any(s.startswith("The evaluators are one party: ") for s in one), one


def test_a_suite_run_again_outside_the_suppliers_control_is_not_weak_and_still_says_what_stayed_outside():
    for name, level in (("rerun: an arbiter", "rerun"), ("agreed: a neutral", "agreed")):
        got = rc.parts(_suite(_by(name)))
        a = got["parts"][4]
        assert not got["weak"] and a["facts"]["level"] == level and a["facts"]["weak_because"] == []
        assert a["line"] == f"{level.capitalize()}: {rc.LEVEL_WORDS[level]}. {rc.O_WORKFLOW}"
        assert a["facts"]["outside"] == [rc.O_WORKFLOW, rc.O_TERMS] and a["facts"]["trusted"] == rc.TRUSTED[level]


def test_an_unsigned_or_declared_related_receipt_is_weak_and_a_version_4_one_takes_the_declarations():
    assert rc.parts(_by("reported: a rejected run nobody signed"))["parts"][4]["facts"]["weak_because"][0] == rc.O_UNSIGNED
    related = _by("reported, not rerun: the terms declare")
    assert rc.parts(related)["parts"][4]["facts"]["level"] == "reported"
    four = rc.as4(_by("rerun: an arbiter"))
    assert rc.parts(four)["parts"][4]["facts"]["level"] == "rerun"
    assert rc.parts(four, related["assurance"]["declared_related"])["parts"][4]["facts"]["level"] == "reported"


def test_a_version_3_receipt_is_read_as_version_4_and_older_ones_are_refused_in_plain_words():
    old = json.loads((ROOT / "docs" / "receipt" / "vectors.json").read_text(encoding="utf-8"))
    assert rc.parts(old["valid_v3"][0]["receipt"])["version"] == 4
    with pytest.raises(ValueError, match="does not say who funded"):
        rc.parts(old["valid_v2"][0]["receipt"])
    with pytest.raises(ValueError):
        rc.parts({"type": rc.TYPE, "version": 5})


def _knos(*args: str, text: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1"}
    return subprocess.run([sys.executable, "-m", "knos", *args], input=text, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)


def test_knos_receipt_explain_prints_the_five_parts_and_json_gives_the_view(tmp_path):
    r = _by("reported: version 4's first")
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(r), encoding="utf-8")
    done = _knos("receipt", "explain", str(path))
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == rc.explain(r)
    heads = [line for line in done.stdout.splitlines() if line[:2] in ("1.", "2.", "3.", "4.", "5.")]
    assert [h.split(".")[1].strip() for h in heads] == ["Identity", "Execution", "Acceptance", "Consequence", "Assurance"]
    assert "   WEAK (reported): " in done.stdout
    as_json = _knos("receipt", "explain", "-", "--json", text=json.dumps({"receipt": r}))
    assert as_json.returncode == 0 and json.loads(as_json.stdout) == rc.parts(r)
    bad = _knos("receipt", "explain", "-", text=json.dumps({**r, "order": "x"}))
    assert bad.returncode == 1 and bad.stderr.startswith("not explained: ")
    assert _knos("receipt", "explain").returncode == 2
    assert _knos("receipt", str(path)).returncode == 0          # the file-only command is what it was


def test_the_page_reads_the_same_receipts_to_the_same_five_parts():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    done = subprocess.run([node, str(ROOT / "tests" / "web" / "receipt_parts.mjs"), str(ROOT / "web")], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"{len(_cases())} cases, 0 differ" in done.stdout
