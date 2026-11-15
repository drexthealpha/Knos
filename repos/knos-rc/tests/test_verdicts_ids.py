"""Four verdicts and four ids on every surface (src/knos/ids.py, ledger.py, receipt.py, audit.py): the same parts give
the same id wherever it is written, an id of one kind is refused where another is expected, and a deliverable is
billed once however many evaluations accepted it. Hypothesis is not installed here, so the properties run over seeded
random cases."""
from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

import pytest

from knos import audit, cli, ids, receipt
from knos import ledger as L

ROOT = Path(__file__).resolve().parents[1]
BUYER, SELLER, MONTH = 424242, 555000, 202610
VECTORS3 = json.loads((ROOT / "docs" / "receipt" / "vectors.json").read_text(encoding="utf-8"))
VECTORS4 = json.loads((ROOT / "docs" / "receipt" / "vectors.v4.json").read_text(encoding="utf-8"))
SCHEMA4 = json.loads((ROOT / "docs" / "receipt" / "acceptance-receipt.v4.schema.json").read_text(encoding="utf-8"))
METER = (ROOT / "docs" / "reference" / "METER.md").read_text(encoding="utf-8")
KINDS = ("deliverable", "evaluation", "invoice_line", "settlement")


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _ev(order: int, artifact: int = 0, verdict: str = "", accepted: bool = True, milestone: int = 0, rate: int = 2_000_000, **more) -> L.Evaluation:
    """One evaluation: `verdict` in words (a new line), or "" and `accepted` (a line as 0.3.16 wrote it)."""
    return L.Evaluation(BUYER, SELLER, _h(f"order {order}"), hashlib.sha1(f"commit {order}.{artifact}".encode()).hexdigest(), _h("policy"), milestone,
                        verdict == "accepted" if verdict else accepted, rate, verdict, **more)


def _book(*batches, month: int = MONTH, corrections=None) -> list[L.Stored]:
    return L.load(L.dump(L.batch(evals, seq, month, (corrections or {}).get(seq, ())) for seq, evals in enumerate(batches)))


def _some(rng: random.Random, kind: str) -> tuple:
    text = lambda: "".join(rng.choice("abcxyz0189-/ é") for _ in range(rng.randint(0, 12)))  # noqa: E731
    return {"deliverable": lambda: (text(), rng.choice([text(), rng.randint(0, 99)])),
            "evaluation": lambda: (ids.deliverable(text(), text()), text(), text(), text(), rng.choice([text(), rng.randint(0, 10 ** 12)])),
            "invoice_line": lambda: (text(), text(), rng.choice([text(), rng.randint(0, 999)])),
            "settlement": lambda: (ids.deliverable(text(), text()), rng.choice(["chain", "bank", "other"]), text())}[kind]()


# -- 1. the same parts give the same ids ----------------------------------------------------------------------------------
def test_the_same_parts_give_the_same_id_and_other_parts_another():
    rng, seen = random.Random(1707), {}
    for _ in range(400):
        kind = rng.choice(KINDS)
        parts = _some(rng, kind)
        make = getattr(ids, kind)
        one = make(*parts)
        assert one == make(*parts) == make(*(str(p) for p in parts))        # the same call twice; a number is its decimal text
        assert ids.kind_of(one) == kind and re.fullmatch(rf"{ids.PREFIX[kind]}_[0-9a-f]{{24}}", one) and ids.expect(kind, one) == one
        assert seen.setdefault(one, (kind, tuple(str(p) for p in parts))) == (kind, tuple(str(p) for p in parts))      # no two sets of parts share an id
    assert ids.deliverable("ab", "c") != ids.deliverable("a", "bc")          # the parts are length-prefixed, so they cannot run together
    assert ids.deliverable("x", "1")[4:] != ids.invoice_line("x", "1", "")[4:]      # the kind is hashed too, not only prefixed


def test_one_deliverable_has_one_id_on_the_ledger_the_receipt_and_the_audit_export():
    r3 = VECTORS3["valid_v3"][0]["receipt"]
    r4 = receipt.build4(r3)
    order_hex = ids.order_scope(r3["order"])
    assert len(order_hex) == 64 and ids.order_scope(order_hex) == order_hex
    line = L.Evaluation(BUYER, SELLER, order_hex, r3["evaluator_observed"]["artifact"]["commit"], r3["policy"]["terms_hash"], 0, True, 20_000_000, "accepted",
                        evaluator=f"repository@{r3['evaluator_observed']['judge']['version']}", run=r3["issuer_authenticated"]["claims"]["run_id"],
                        stl=r4["ids"]["settlement"])
    row = audit.four_of({"order": r3["order"], "standing": 0, "pull_request": 12, "kind": "paid", "verdict": "accepted",
                         "transaction": r3["transaction"]["signature"]}, r4)
    assert line.ids() == r4["ids"]                                           # the ledger line and the receipt: the same four
    assert (row["deliverable_id"], row["evaluation_id"], row["settlement_id"]) == (r4["ids"]["deliverable"], r4["ids"]["evaluation"], r4["ids"]["settlement"])
    assert L.parse(line.line()) == line and json.loads(line.line())["dlv"] == r4["ids"]["deliverable"]
    again = receipt.build4(json.loads(json.dumps(r3)))
    assert again == r4 and receipt.digest(again) == receipt.digest(r4)       # rebuilt from the same facts: the same receipt
    # a standing order pays once per pull request: its milestone is the pull request, on both surfaces
    standing = receipt.build4(VECTORS3["valid_v3"][2]["receipt"])
    pr = standing["commercial_authorisation"]["deliverable"]["milestone"]
    assert pr and standing["ids"]["deliverable"] == ids.deliverable(ids.order_scope(standing["order"]), pr) == audit.four_of(
        {"order": standing["order"], "standing": 1, "pull_request": pr, "kind": "paid", "verdict": "accepted", "transaction": "x"})["deliverable_id"]


# -- 2. an id of one kind is refused where another is expected ------------------------------------------------------------
def test_an_id_of_one_kind_is_refused_where_another_is_expected():
    rng = random.Random(2203)
    made = {kind: [getattr(ids, kind)(*_some(rng, kind)) for _ in range(20)] for kind in KINDS}
    for want in KINDS:
        for got in KINDS:
            for an in made[got]:
                if got == want:
                    assert ids.expect(want, an) == an
                else:
                    with pytest.raises(ValueError, match="is expected here"):
                        ids.expect(want, an)
    for junk in ("", "dlv_", "dlv_" + "g" * 24, "DLV_" + "0" * 24, "dlv_" + "0" * 23, None, 7, "0" * 64):
        with pytest.raises(ValueError, match="not an id"):
            ids.expect("deliverable", junk)
    dlv, evl, inv, stl = (made[k][0] for k in KINDS)
    # a ledger line
    good = _ev(1, verdict="accepted", inv=inv, stl=stl)
    assert L.parse(good.line()) == good
    for field, wrong in (("inv", dlv), ("inv", stl), ("stl", inv), ("stl", evl), ("dlv", good.evl), ("evl", good.dlv)):
        with pytest.raises(L.Bad, match="is expected here"):
            L.parse({**json.loads(good.line()), field: wrong})
    with pytest.raises(L.Bad, match="is not the deliverable id of this line's own fields"):
        L.parse({**json.loads(good.line()), "dlv": dlv})
    with pytest.raises(L.Bad, match="authorises no payment"):               # a settlement on a line that is not accepted
        _ev(1, verdict="rejected", stl=stl)
    with pytest.raises(L.Bad, match="is expected here"):
        L.billed_once([(evl, "accepted")])
    # a receipt
    r4 = receipt.build4(VECTORS3["valid_v3"][0]["receipt"], invoice_line=inv)
    for field, wrong in (("deliverable", r4["ids"]["evaluation"]), ("evaluation", r4["ids"]["deliverable"]), ("invoice_line", r4["ids"]["settlement"]),
                         ("settlement", r4["ids"]["deliverable"])):
        why = receipt.check({**r4, "ids": {**r4["ids"], field: wrong}})
        assert why and f"ids.{field}" in why and "is expected here" in why
    with pytest.raises(ValueError, match="is expected here"):
        receipt.build4(VECTORS3["valid_v3"][0]["receipt"], invoice_line=dlv)
    # an audit row
    with pytest.raises(audit.Refused):
        audit.four_of({"order": r4["order"], "standing": 0, "pull_request": 12, "kind": "paid", "verdict": "accepted", "transaction": "another"}, r4)


# -- 3. a deliverable is billed once ------------------------------------------------------------------------------------------
def test_two_accepted_evaluations_of_one_deliverable_bill_once():
    c = L.canonical(_book([_ev(1, 0, "accepted"), _ev(1, 1, "accepted")]))
    n = L.numbers(c, MONTH)
    assert (n.evaluations, n.accepted, n.accepted_outcomes, n.value, n.outcome_value) == (2, 2, 1, 4_000_000, 2_000_000)
    roles = sorted(b.role for b in L.billing(c))
    assert roles == [L.ALTERNATE, L.OUTCOME] and sum(b.billed for b in L.billing(c)) == 1
    dlv = _ev(1).dlv
    assert L.billed_once([(dlv, "accepted"), (dlv, "accepted")]) == [0]


def test_however_the_evaluations_fall_each_deliverable_with_an_accepted_one_is_billed_exactly_once():
    rng = random.Random(1726)
    for _ in range(60):
        evals, used = [], set()
        for _n in range(rng.randint(1, 30)):
            order, artifact = rng.randint(1, 5), rng.randint(0, 4)
            if (order, artifact) not in used:
                used.add((order, artifact))
                evals.append(_ev(order, artifact, rng.choice(ids.VERDICTS)))
        rng.shuffle(evals)
        cut = sorted(rng.sample(range(1, len(evals)), min(len(evals) - 1, rng.randint(0, 3)))) if len(evals) > 1 else []
        batches = [evals[a:b] for a, b in zip([0, *cut], [*cut, len(evals)])]
        months = sorted(rng.choice((202610, 202611)) for _ in batches)
        ledger = L.load(L.dump(L.batch(b, sum(m == months[i] for m in months[:i]), months[i]) for i, b in enumerate(batches)))
        assert L.verify(ledger) == []
        c = L.canonical(ledger)
        won = {e.dlv for e in evals if e.stands == "accepted"}
        billed = [b for b in L.billing(c) if b.billed]
        assert sorted(b.entry.e.dlv for b in billed) == sorted(won)                       # once each, and only those
        assert all(b.entry.e.stands == "accepted" for b in billed)
        assert sum(L.numbers(c, m).accepted_outcomes for m in (202610, 202611)) == len(won)
        assert sum(L.numbers(c, m).accepted for m in (202610, 202611)) == sum(e.stands == "accepted" for e in evals)
        for b in L.billing(c):                                                             # nothing but the outcome is billed, whatever it is called
            assert b.billed == (b.role == L.OUTCOME) and (b.entry.e.stands == "accepted" or not b.billed)
        order = [(x.e.dlv, x.e.stands) for x in c.kept]
        assert [c.kept[i] for i in L.billed_once(order)] == [b.entry for b in billed]     # the rule for ids alone agrees with the ledger's
        for m in set(months):
            doc = L.statement_json(ledger, m)
            assert sum(doc["verdicts"].values()) == doc["evaluations"] == len(doc["lines"])
            assert doc["billed_deliverables"] == sorted(x["ids"]["deliverable"] for x in doc["lines"] if x["billed"]) and doc["accepted_outcomes"] == len(doc["billed_deliverables"])


def test_the_rules_for_a_retry_a_branch_a_reopened_ticket_and_ten_pull_requests():
    # a retry: the same deliverable and artifact, judged again under another run. A new evaluation, not billed again.
    first = _ev(1, 0, "rejected", run="1")
    retry = _ev(1, 0, "accepted", run="2")
    assert first.id == retry.id and first.evl != retry.evl and first.dlv == retry.dlv   # the program bills that id once; the two runs are two evaluations
    with pytest.raises(L.Bad, match="twice with different contents"):
        L.batch([first, retry], 0, MONTH)                                    # one batch says one thing of an id
    # ... so the retry's verdict reaches the ledger as a correction of the first, and the deliverable is billed once
    fix = L.Correction(SELLER, first.id.hex(), MONTH, 0, "verdict", verdict="accepted")
    c = L.canonical(_book([first], [_ev(2, 0, "rejected")], corrections={1: [fix]}))
    assert [(b.role, b.entry.e.stands) for b in L.billing(c)] == [(L.OUTCOME, "accepted"), (L.FIRST, "rejected")]
    again = L.canonical(_book([_ev(1, 0, "accepted")], [_ev(1, 0, "accepted", milestone=0, rate=2_000_000)]))      # the same line anchored twice
    assert L.numbers(again, MONTH).accepted_outcomes == 1 and len(again.kept) == 1 and len(again.dropped) == 1
    # an alternate branch: the first accepted one stands, later ones are evaluations
    c = L.canonical(_book([_ev(1, 0, "accepted")], [_ev(1, 1, "accepted"), _ev(1, 2, "rejected")]))
    assert [b.role for b in L.billing(c)] == [L.OUTCOME, L.ALTERNATE, L.ALTERNATE] and L.numbers(c, MONTH).accepted_outcomes == 1
    assert L.outcomes(c)[_ev(1).deliverable].e.artifact == _ev(1, 0).artifact
    # ten pull requests for one milestone: ten evaluations, one deliverable, one outcome
    ten = [_ev(1, i, "accepted" if i >= 4 else "rejected") for i in range(10)]
    c = L.canonical(_book(ten[:5], ten[5:]))
    n = L.numbers(c, MONTH)
    assert (n.evaluations, n.accepted_outcomes, len({e.dlv for e in ten}), len({e.evl for e in ten})) == (10, 1, 1, 10)
    assert sum(b.billed for b in L.billing(c)) == 1
    # a reopened ticket: inside the warranty a correction, never a new line; after it a new deliverable only if the terms say so
    day = 86_400
    assert L.reopened(1000, 1000 + 29 * day, 30 * day) == L.CORRECTION == L.reopened(1000, 1000 + 30 * day, 30 * day, new_after=True)
    assert L.reopened(1000, 1001 + 30 * day, 30 * day) == L.CLOSED and L.reopened(1000, 1001 + 30 * day, 30 * day, new_after=True) == L.NEW_DELIVERABLE
    assert L.reopened(1000, 1000, 0) == L.CORRECTION and L.reopened(1000, 1001, 0) == L.CLOSED
    for wrong in ((1000, 999, day), (-1, 5, day), (0, 5, -1)):
        with pytest.raises(L.Bad):
            L.reopened(*wrong)
    took_back = L.Correction(BUYER, _ev(1, 0).id.hex(), MONTH, 0, "verdict", verdict="disputed")       # the correction inside the warranty
    c = L.canonical(_book([_ev(1, 0, "accepted")], [_ev(3, 0, "accepted")], corrections={1: [took_back]}))
    n = L.numbers(c, MONTH)
    assert (n.evaluations, n.accepted_outcomes, n.disputed, len(c.kept)) == (2, 1, 1, 2)                # no new line; the outcome is taken back
    new = ids.deliverable(_ev(1).order, L.reopened_key(0, 1))
    assert new != _ev(1).dlv and ids.kind_of(new) == "deliverable" and L.reopened_key(0, 2) != L.reopened_key(0, 1)
    with pytest.raises(L.Bad):
        L.reopened_key(0, 0)
    # docs/reference/METER.md prints the rules this code keeps: every row of RULES, word for word
    for row in L.RULES:
        assert "| " + " | ".join(row) + " |" in METER, row[0]


# -- 4. the ledger counts four verdicts; the chain's batch does not change ---------------------------------------------------
def test_a_line_without_a_verdict_in_words_is_written_as_it_always_was():
    old = _ev(1, accepted=False)
    assert set(json.loads(old.line())) == {"accepted", "artifact", "buyer", "deliverable", "id", "milestone", "order", "policy", "rate", "seller"}
    assert old.stands == "rejected" and _ev(1).stands == "accepted" and L.parse(old.line()) == old
    for name in ("buyer.jsonl", "seller.jsonl"):                                             # the committed examples: the same bytes back
        text = (ROOT / "examples" / "meter" / name).read_text(encoding="utf-8")
        assert L.dump(s.batch() for s in L.load(text)) == text
    new = _ev(1, verdict="insufficient_evidence", evaluator="neutral@" + "c" * 40, run="77")
    got = json.loads(new.line())
    assert (got["accepted"], got["verdict"], got["dlv"], got["evl"], got["evaluator"], got["run"]) == (0, "insufficient_evidence", new.dlv, new.evl, new.evaluator, "77")
    assert new.id == old.id and new.entry()["ids"] == {"deliverable": new.dlv, "evaluation": new.evl, "invoice_line": None, "settlement": None}
    for wrong in ({"verdict": "passed"}, {"verdict": "accepted"}, {"verdict": ""}, {"verdict": 1}, {"evaluator": "x" * 201}):
        with pytest.raises(L.Bad):
            L.parse({**got, **wrong})
    with pytest.raises(L.Bad, match="also says its verdict"):
        L.parse({**json.loads(old.line()), "run": "77"})


def test_the_two_new_verdicts_are_not_accepted_on_chain_and_are_counted_apart_off_chain(capsys, tmp_path):
    evals = [_ev(1, 0, "accepted"), _ev(2, 0, "rejected"), _ev(3, 0, "insufficient_evidence"), _ev(4, 0, "disputed"), _ev(5, accepted=False)]
    b = L.batch(evals, 0, MONTH, format=1)
    plain = L.batch([_ev(i, accepted=i == 1) for i in range(1, 6)], 0, MONTH, format=1)               # the same five as 0.3.16 would have written them
    assert (b.count, b.accepted, b.value) == (5, 1, 2_000_000) == (plain.count, plain.accepted, plain.value)
    assert b.root == plain.root and L.batch_audience(b) == L.batch_audience(plain)           # the token GitHub signs is the same token
    assert re.fullmatch(r"knosm:batch:424242:555000:202610:0:5:1:2000000:[0-9a-f]{64}", L.batch_audience(b))
    assert set(json.loads(b.header())["batch"]) == {"accepted", "buyer", "count", "month", "root", "seller", "seq", "value"}
    ledger = L.load(L.dump([b]))
    assert L.verify(ledger) == [] and L.totals(ledger, MONTH) == L.totals(L.load(L.dump([plain])), MONTH)
    n = L.numbers(L.canonical(ledger), MONTH)
    assert n.four() == {"accepted": 1, "rejected": 2, "insufficient_evidence": 1, "disputed": 1} and sum(n.four().values()) == n.evaluations == 5
    assert b.count - b.accepted == n.rejected + n.insufficient_evidence + n.disputed          # on chain the three are one number
    text = L.statement(ledger, MONTH)
    assert text.startswith("knos meter statement,2\n") and "rejected_evaluations,2\ninsufficient_evidence_evaluations,1\ndisputed_evaluations,1\n" in text
    old = L.statement(L.load(L.dump([plain])), MONTH)
    assert old.startswith("knos meter statement,1\n") and "insufficient" not in old and "rejected_evaluations,4\n" in old
    doc = L.statement_json(ledger, MONTH)
    assert doc["type"] == L.STATEMENT_TYPE and doc["verdicts"] == n.four() and doc["text_sha256"] == re.search(r"^sha256,([0-9a-f]{64})$", text, re.M).group(1)
    assert [x["verdict"] for x in doc["lines"] if x["billed"]] == ["accepted"] and all(set(x["ids"]) == set(KINDS) for x in doc["lines"])
    assert all(ids.kind_of(x["ids"]["deliverable"]) == "deliverable" and ids.kind_of(x["ids"]["evaluation"]) == "evaluation" for x in doc["lines"])
    # the commands: the statement as JSON, the export's columns, reconcile's four counts
    path = tmp_path / "buyer.jsonl"
    path.write_text(L.dump([b]), encoding="utf-8", newline="\n")
    capsys.readouterr()
    assert cli.main(["meter", "statement", str(path), "--month", "2026-10", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == doc
    rows = L.export_csv(ledger).splitlines()
    assert rows[0].endswith(",verdict,deliverable_id,evaluation_id,invoice_line_id,settlement_id")
    assert sorted(r.split(",")[11] for r in rows[1:]) == sorted(e.stands for e in evals)
    seller = tmp_path / "seller.jsonl"
    theirs = [_ev(1, 0, "accepted"), _ev(2, 0, "rejected"), _ev(3, 0, "rejected"), _ev(4, 0, "disputed"), _ev(5, accepted=False)]
    seller.write_text(L.dump([L.batch(theirs, 0, MONTH)]), encoding="utf-8", newline="\n")
    r = L.reconcile(ledger, L.load(seller))
    assert [d.what for d in r.disputed] == [("verdict",)] and r.disputed[0].id == _ev(3).id       # insufficient against rejected: both 0 on chain, and still a difference
    assert r.rows[0].verdicts == {"accepted": 1, "rejected": 2, "insufficient_evidence": 0, "disputed": 1} and r.rows[0].accepted_outcomes == 1
    assert cli.main(["meter", "reconcile", str(path), str(seller), "--json"]) == 1
    said = json.loads(capsys.readouterr().out)
    assert said["statement"][0]["verdicts"] == r.rows[0].verdicts and said["disputed"][0]["buyer"]["verdict"] == "insufficient_evidence"
    assert said["disputed"][0]["seller"]["verdict"] == "rejected" and set(said["disputed"][0]["ids"]) == set(KINDS)
    close = L.close(ledger, L.load(seller), MONTH)
    assert close["state"] == "disputed" and close["buyer_ledger"]["insufficient_evidence"] == 1 and close["buyer_ledger"]["disputed"] == 1
    assert close["disputed"][0]["buyer"]["verdict"] == "insufficient_evidence" and "verdict" not in close["disputed"][0]["seller"]
    same = L.close(L.load(L.dump([plain])), L.load(L.dump([plain])), MONTH)                  # a month of the two old verdicts closes to the fields it always had
    assert set(same["buyer_ledger"]) == {"accepted_outcomes", "evaluations", "rejected", "anchored", "batches", "chain", "corrections"}


def test_a_correction_sets_a_verdict_to_any_of_the_four_and_an_old_correction_reads_as_before(capsys, tmp_path):
    e = _ev(1, 0, "accepted")
    old = L.Correction(BUYER, e.id.hex(), MONTH, 0, "verdict", False)
    assert json.loads(old.line()) == {"correction": {"accepted": 0, "batch": "202610.0", "by": BUYER, "id": e.id.hex(), "kind": "verdict"}}
    assert L.Correction.of(json.loads(old.line())) == old and old.stands == "rejected"
    for word in ids.VERDICTS:
        fix = L.Correction(BUYER, e.id.hex(), MONTH, 0, "verdict", verdict=word)
        assert json.loads(fix.line())["correction"]["verdict"] == word and "accepted" not in json.loads(fix.line())["correction"]
        assert L.Correction.of(json.loads(fix.line())) == fix and fix.key != old.key
        ledger = _book([e], [_ev(2, 0, "rejected")], corrections={1: [fix]})
        assert L.verify(ledger) == []
        n = L.numbers(L.canonical(ledger), MONTH)
        assert n.four() == {**dict.fromkeys(ids.VERDICTS, 0), "rejected": 1, word: 1 + (word == "rejected")}
        assert n.accepted_outcomes == (word == "accepted") and n.value == (2_000_000 if word == "accepted" else 0)
        t = L.totals(ledger, MONTH)
        assert (t.count, t.accepted, t.value) == (2, 1, 2_000_000)            # the chain's counters only went up: the batch said accepted, and still does
        assert f",verdict {word}\n" in L.statement(ledger, MONTH)
    for wrong in (dict(accepted=True, verdict="accepted"), dict(verdict="passed"), dict()):
        with pytest.raises(L.Bad):
            L.Correction(BUYER, e.id.hex(), MONTH, 0, "verdict", **wrong)
    with pytest.raises(L.Bad):
        L.Correction(BUYER, e.id.hex(), MONTH, 0, "duplicate", verdict="rejected")
    with pytest.raises(L.Bad):
        L.Correction.of({"correction": {"batch": "202610.0", "by": BUYER, "id": e.id.hex(), "kind": "verdict", "verdict": 0}})
    # the command: --verdict with one of the four words, or --accepted 1 or 0, never both
    path = tmp_path / "buyer.jsonl"
    path.write_text(L.dump([L.batch([e], 0, MONTH)]), encoding="utf-8", newline="\n")
    capsys.readouterr()
    assert cli.main(["meter", "correct", str(path), e.id.hex(), "--batch", "202610.0", "--kind", "verdict", "--verdict", "insufficient evidence"]) == 0
    waiting = (tmp_path / "buyer.jsonl.corrections").read_text(encoding="utf-8").splitlines()
    assert [L.Correction.of(json.loads(x)).stands for x in waiting] == ["insufficient_evidence"]
    for bad in (["--verdict", "disputed", "--accepted", "1"], ["--verdict", "approved"], []):
        assert cli.main(["meter", "correct", str(path), e.id.hex(), "--batch", "202610.0", "--kind", "verdict", *bad]) != 0
    capsys.readouterr()


# -- 5. the receipt: four verdicts, and only one of them authorises payment ----------------------------------------------------
def _changed(v: dict) -> dict:
    r = json.loads(json.dumps(VECTORS4["valid_v4"][v["of"]]["receipt"]))
    for path, value in v["set"].items():
        steps, node = path.split("."), r
        for step in steps[:-1]:
            node = node[int(step)] if isinstance(node, list) else node[step]
        node[int(steps[-1]) if isinstance(node, list) else steps[-1]] = value
    return r


def test_every_version_4_vector_checks_and_only_an_accepted_receipt_authorises_payment():
    assert receipt.VERSION == 4 and len(VECTORS4["valid_v4"]) == 12 and len(VECTORS4["invalid_v4"]) == 24
    seen = set()
    for v in VECTORS4["valid_v4"]:
        r = v["receipt"]
        assert receipt.check(r) is None and receipt.digest(r) == v["sha256"], v["name"]
        assert receipt.verdict_of(r) == v["verdict"] and receipt.authorises_payment(r) == v["authorises_payment"] == (v["verdict"] == "accepted")
        said = receipt.exposed(r)
        assert set(said) == {"artifact", "policy", "evidence_source", "evaluator", "verdict", "limitations"} and said["limitations"] == r["limitations"]
        assert len(r["limitations"]) >= 4 and all(s.endswith(".") and s[0].isupper() for s in r["limitations"])
        assert (r["transaction"] is None) == (r["ids"]["settlement"] is None)
        if v["verdict"] in ("rejected", "insufficient_evidence"):
            assert r["transaction"] is None and r["amounts"]["paid"] == "0" and receipt.as3(r) is None
            assert any("authorises no payment" in s for s in r["limitations"]) and any("No payment is recorded" in s for s in r["limitations"])
        text = "\n".join(receipt.render(r))
        assert f"Verdict: {ids.VERDICT_WORDS[v['verdict']]}." in text and ("authorises no payment" in text) == (v["verdict"] != "accepted")
        assert "What this evidence does not show" in text and r["ids"]["deliverable"] in text and text.endswith(f"Digest sha256:{v['sha256']}")
        seen.add(v["verdict"])
    assert seen == set(ids.VERDICTS)
    for v in VECTORS4["invalid_v4"]:
        why = receipt.check(_changed(v))
        assert why is not None and v["why"] in why, (v["name"], why)
    first = VECTORS4["valid_v4"][0]["receipt"]["limitations"][0]
    assert first.startswith("The issuer signs which workflow ran") and first.endswith("not what it read, ran or concluded.")


def test_the_version_4_schema_agrees_with_the_checker():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(SCHEMA4)
    ok = jsonschema.Draft202012Validator(SCHEMA4)
    for v in VECTORS4["valid_v4"]:
        assert not list(ok.iter_errors(v["receipt"])), v["name"]
    for v in VECTORS3["valid_v3"]:
        assert list(ok.iter_errors(v["receipt"]))                             # each version has its own schema
    by_schema = {v["name"] for v in VECTORS4["invalid_v4"] if list(ok.iter_errors(_changed(v)))}
    assert by_schema == {"a verdict that is none of the four", "a conclusion that is not a conclusion", "an evaluation id where the deliverable goes",
                         "a deliverable id where the settlement goes", "a settlement id where the invoice line goes", "a dispute by nobody",
                         "a field of no version"}                             # the rest are rules a schema cannot say
    assert SCHEMA4["properties"]["evaluator_observed"]["properties"]["verdict"]["enum"] == list(ids.VERDICTS)


def test_older_receipts_still_verify_and_say_the_same_six_things():
    for group, version in (("valid", 1), ("valid_v2", 2), ("valid_v3", 3)):
        for v in VECTORS3[group]:
            r = v["receipt"]
            assert r["version"] == version and receipt.check(r) is None and receipt.digest(r) == v["sha256"]
            assert receipt.verdict_of(r) == "accepted" and receipt.authorises_payment(r)
            said = receipt.exposed(r)
            assert said["verdict"] == "accepted" and said["evidence_source"]["kind"] == "issuer_token" and said["artifact"]["commit"]
            assert said["evaluator"]["kind"] in receipt.JUDGES and len(said["limitations"]) >= 4
            assert "\n".join(receipt.render(r)).startswith(f"Acceptance receipt, version {version}:")
    for v in VECTORS3["valid_v3"]:
        r4 = receipt.build4(v["receipt"])
        assert receipt.as3(r4) == v["receipt"] and receipt.as2(r4) == receipt.as2(v["receipt"])        # the older receipt is still in it, unchanged
        assert receipt.exposed(r4)["limitations"] == receipt.exposed(v["receipt"])["limitations"]
    assert not receipt.authorises_payment({"type": receipt.TYPE, "version": 4}) and not receipt.authorises_payment(None)


def test_a_dispute_names_who_when_and_the_receipt_it_contests():
    paid = receipt.build4(VECTORS3["valid_v3"][0]["receipt"])
    when = paid["transaction"]["time"] + 3600
    d = receipt.dispute(paid, role="buyer", by="424242", at=when, reason="The change does not fix the reported case.")
    assert receipt.check(d) is None and receipt.verdict_of(d) == "disputed" and not receipt.authorises_payment(d)
    assert d["disputed"] == {"by": {"role": "buyer", "id": "424242"}, "at": when, "reason": "The change does not fix the reported case.",
                             "contests": {"sha256": receipt.digest(paid), "verdict": "accepted"}}
    assert receipt.contested(d) == paid and d["ids"] == paid["ids"] and d["transaction"] == paid["transaction"]      # the money moved: that stays on record
    assert receipt.contested(paid) is None
    for wrong in (dict(role="auditor"), dict(by=""), dict(at=paid["transaction"]["time"] - 1), dict(reason="")):
        with pytest.raises(ValueError):
            receipt.dispute(paid, **{**dict(role="buyer", by="424242", at=when, reason="No."), **wrong})
    with pytest.raises(ValueError, match="not disputed already"):
        receipt.dispute(d, role="supplier", by="555000", at=when + 1, reason="It does.")
    with pytest.raises(ValueError):
        receipt.dispute(VECTORS3["valid_v3"][0]["receipt"], role="buyer", by="424242", at=when, reason="No.")       # an older receipt is written as version 4 first
    tampered = {**d, "disputed": {**d["disputed"], "contests": {"sha256": receipt.digest(paid), "verdict": "rejected"}}}
    assert "the digest of the receipt contested" in receipt.check(tampered)


def test_a_mirror_keeps_receipts_that_paid_nothing_beside_the_ones_that_paid(tmp_path):
    paid = receipt.build4(VECTORS3["valid_v3"][0]["receipt"])
    rejected = next(v["receipt"] for v in VECTORS4["valid_v4"] if v["verdict"] == "rejected")
    assert rejected["order"] == paid["order"]
    index = receipt.mirror_write([paid, rejected], tmp_path)
    rows = index["orders"][paid["order"]]
    assert sorted(r["sha256"] for r in rows) == sorted([receipt.digest(paid), receipt.digest(rejected)])
    assert {r["transaction"] for r in rows} == {None, paid["transaction"]["signature"]}
    assert receipt.mirror_write([rejected, paid], tmp_path) == index                              # the same receipts in any order: the same bytes
    held = receipt.mirror_find(str(tmp_path), paid["order"])
    assert len(held) == 2 and [receipt.authorises_payment(r) for r in held].count(True) == 1
    assert receipt.mirror_find(str(tmp_path), paid["transaction"]["signature"]) == [paid]
