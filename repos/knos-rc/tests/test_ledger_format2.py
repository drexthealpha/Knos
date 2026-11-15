"""Commitment format 2: a batch's root binds every field of every evaluation, not only the set of ids."""
from knos import ledger as L

ORDER_A, ORDER_B, POLICY = "11" * 32, "22" * 32, "33" * 32


def pair(first_accepted: bool):
    """Two evaluations at one price; exactly one is accepted."""
    return [L.Evaluation(424242, 555000, ORDER_A, "a" * 40, POLICY, 0, first_accepted, 2_000_000),
            L.Evaluation(424242, 555000, ORDER_B, "b" * 40, POLICY, 0, not first_accepted, 2_000_000)]


def test_swapping_which_of_two_equal_priced_evaluations_was_accepted_changes_the_root():
    one, other = L.batch(pair(True), 0, 202610), L.batch(pair(False), 0, 202610)
    assert (one.count, one.accepted, one.value) == (other.count, other.accepted, other.value) == (2, 1, 2_000_000)
    assert one.root != other.root and L.batch_audience(one) != L.batch_audience(other)


# -- everything below was written with format 2 in place ---------------------------------------------------------------
import hashlib  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
from dataclasses import replace  # noqa: E402

import pytest  # noqa: E402

from knos import cli, events, ids  # noqa: E402

BUYER, SELLER, MONTH = 424242, 555000, 202610
WORDS = ("accepted", "rejected", "insufficient_evidence", "disputed")


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _ev(i: int, verdict: str = "accepted", rate: int = 2_000_000, **more) -> L.Evaluation:
    return L.Evaluation(BUYER, SELLER, _h(f"order {i}"), _h(f"commit {i}")[:40], _h("policy"), i % 3, verdict == "accepted", rate, verdict,
                        more.pop("evaluator", "judge@1"), more.pop("run", str(1000 + i)), currency=more.pop("currency", "USDC"),
                        evidence=more.pop("evidence", _h(f"token {i}")), **more)


def _root(evals, seq: int = 0, month: int = MONTH, format: int = 2) -> bytes:
    return L.batch(evals, seq, month, format=format).root


def test_the_swap_keeps_the_root_in_format_1_and_changes_it_in_format_2():
    one, other = pair(True), pair(False)
    assert _root(one, format=1) == _root(other, format=1)                   # what format 1 binds: the ids, not which was accepted
    assert _root(one) != _root(other)
    a1, a2 = (L.batch_audience(L.batch(x, 0, MONTH, format=f)) for x, f in ((one, 1), (other, 1)))
    assert a1 == a2 and "not which evaluation was accepted" in L.BINDS[1]
    assert L.batch(one, 0, MONTH).format == L.FORMAT == 2                   # a new batch is format 2 unless asked otherwise


def test_the_leaf_is_the_canonical_bytes_written_out_by_hand():
    e = _ev(1, inv=ids.invoice_line("555000", "INV-7", 3))
    fields = L.event_fields(e, MONTH, 4)
    assert dict(zip(L.FIELDS, fields)) == {
        "deliverable_id": e.dlv, "evaluation_id": e.evl, "invoice_line_id": e.inv, "settlement_id": "", "verdict": "accepted", "amount": "2000000",
        "currency": "USDC", "buyer": "424242", "seller": "555000", "order": e.order, "milestone": "1", "policy": e.policy, "artifact": e.artifact,
        "evidence": e.evidence, "evaluator": "judge@1", "run": "1001", "month": "202610", "seq": "4"}
    raw = b"knos.event\x00" + bytes([2, 18]) + b"".join(len(x.encode()).to_bytes(4, "big") + x.encode() for x in fields)
    assert L.encode_event(fields) == raw and len(L.FIELDS) == 18
    leaf = hashlib.sha256(b"knos.leaf.2\x00" + raw).digest()
    assert L.leaf2(fields) == L.event_hash(e, MONTH, 4) == leaf
    assert L.batch([e], 4, MONTH).root == hashlib.sha256(b"knos.root.2\x00" + (1).to_bytes(4, "big") + leaf).digest()
    two = sorted([e, _ev(2)], key=lambda x: x.id)
    leaves = [L.event_hash(x, MONTH, 4) for x in two]
    node = hashlib.sha256(b"knos.node.2\x00" + leaves[0] + leaves[1]).digest()
    assert L.batch(two[::-1], 4, MONTH).root == hashlib.sha256(b"knos.root.2\x00" + (2).to_bytes(4, "big") + node).digest()   # sorted by evaluation id
    for bad in (fields[:-1], (*fields[:4], "passed", *fields[5:]), (*fields[:5], "02", *fields[6:]), ("dlv_" + "0" * 24, *fields[1:])):
        with pytest.raises(L.Bad):
            L.encode_event(bad)


def test_the_log_of_events_and_the_batch_use_one_definition():
    e = _ev(5)
    assert events.event_hash(e, "2026-10", 2) == L.event_hash(e, MONTH, 2).hex()
    b = L.batch([e, _ev(6, "rejected")], 2, MONTH)
    named = {x.evidence for x in events.from_ledger(L.dump([b]))}
    assert named == {f"batch:{BUYER}:{SELLER}:{MONTH}.2:{b.root.hex()}:event:{L.event_hash(x, MONTH, 2).hex()}" for x in b.evals}
    old = L.batch([e], 0, MONTH, format=1)
    assert {x.evidence for x in events.from_ledger(L.dump([old]))} == {f"batch:{BUYER}:{SELLER}:{MONTH}.0:{old.root.hex()}"}


def _mutations(rng: random.Random, evals: list) -> list:
    """Event lists that differ from `evals`: one field of one event, one event more, one less, verdicts swapped
    between two events of one price, an amount moved from one event to another."""
    i, j = rng.sample(range(len(evals)), 2)
    e, out = evals[i], []
    other = rng.choice([w for w in WORDS if w != e.stands])
    for change in ({"verdict": other, "accepted": other == "accepted", "stl": ""}, {"rate": e.rate + 1}, {"currency": "EURC"}, {"evidence": _h("another token")},
                   {"evaluator": "judge@2"}, {"run": e.run + "1"}, {"inv": ids.invoice_line("555000", "INV", rng.randrange(10 ** 6))},
                   {"buyer": BUYER + 1, "seller": SELLER}, {"policy": _h("policy 2")}, {"artifact": _h("x")[:40]}, {"order": _h("y")}, {"milestone": e.milestone + 1}):
        if "buyer" in change:
            out.append([replace(x, buyer=BUYER + 1) for x in evals])       # a batch is of one pair: the party changes on every line
        else:
            out.append([*evals[:i], replace(e, **change), *evals[i + 1:]])
    out.append([*evals, _ev(10_000 + rng.randrange(10 ** 6))])
    out.append(evals[:i] + evals[i + 1:])
    a, b = evals[i], replace(evals[j], rate=evals[i].rate, verdict="rejected" if evals[i].stands == "accepted" else "accepted",
                             accepted=evals[i].stands != "accepted")
    base = [x for k, x in enumerate(evals) if k not in (i, j)]
    out.append(("swap", [*base, a, b], [*base, replace(a, verdict=b.verdict, accepted=b.accepted), replace(b, verdict=a.verdict, accepted=a.accepted)]))
    if evals[i].rate > 1:
        out.append([replace(x, rate=x.rate - 1) if k == i else replace(x, rate=x.rate + 1) if k == j else x for k, x in enumerate(evals)])
    return out


def test_any_two_different_event_lists_have_different_format_2_roots():
    rng, seen = random.Random(20261006), 0
    for _ in range(60):
        n = rng.randrange(2, 12)
        evals = [_ev(k, rng.choice(WORDS), rng.choice([1, 500, 2_000_000])) for k in rng.sample(range(500), n)]
        seq = rng.randrange(4)
        root = _root(evals, seq)
        assert root == _root(rng.sample(evals, n), seq)                     # the order they are given in is not part of it
        assert root != _root(evals, seq + 1) and root != _root(evals, seq, MONTH + 1)       # the batch it is counted in is
        for m in _mutations(rng, evals):
            if m[0] == "swap":
                _name, before, after = m
                x, y = L.batch(before, seq, MONTH), L.batch(after, seq, MONTH)
                assert (x.count, x.accepted, x.value) == (y.count, y.accepted, y.value) and x.root != y.root
                assert _root(before, seq, format=1) == _root(after, seq, format=1)
            else:
                assert _root(m, seq) != root
                if sum(x.value for x in m) == sum(x.value for x in evals) and len(m) == n and [x.rate for x in m] != [x.rate for x in evals]:
                    seen += 1                                               # an amount moved, the total kept
    assert seen >= 20


def test_every_format_2_proof_holds_and_proves_that_deliverable_s_verdict_and_amount():
    rng = random.Random(7)
    for n in (1, 2, 3, 4, 5, 8, 13):
        evals = [_ev(k, rng.choice(WORDS), 100 + k) for k in range(n)]
        fix = [L.Correction(BUYER, evals[0].id.hex(), MONTH, 0, "withdrawn")] if n > 2 else []
        book = L.load(L.dump([L.batch(evals[:1], 0, MONTH), L.batch(evals[1:] or [_ev(99)], 1, MONTH, fix)]))
        assert L.verify(book) == []
        for e in book[1].evals:
            p = L.prove(book, e.id)
            assert p.ok() and p.format == 2 and p.root.hex() == book[1].declared["root"] and L.Proof.of(json.loads(json.dumps(p.json()))) == p
            f = dict(zip(L.FIELDS, p.event))
            assert (f["deliverable_id"], f["verdict"], f["amount"]) == (e.dlv, e.stands, str(e.rate))
            lie = dict(f, verdict="rejected" if f["verdict"] == "accepted" else "accepted")
            assert not replace(p, event=tuple(lie[k] for k in L.FIELDS)).ok()                   # the same path does not prove another verdict
            assert not replace(p, event=tuple(dict(f, amount=str(e.rate + 1))[k] for k in L.FIELDS)).ok()
            assert not replace(p, size=p.size + 1).ok() and not replace(p, index=(p.index + 1) % max(p.size, 2)).ok() or p.size == 1
            assert not replace(p, format=1, event=None).ok()                                   # never as a format 1 proof
        for c in fix:
            p = L.prove(book, c.key)
            assert p.ok() and p.correction and not replace(p, correction=False).ok()


def test_a_root_of_one_format_never_verifies_as_the_other():
    evals = [_ev(k) for k in range(5)]
    v1, v2 = L.batch(evals, 0, MONTH, format=1), L.batch(evals, 0, MONTH)
    assert v1.root != v2.root and "format" not in json.loads(v1.header())["batch"] and json.loads(v2.header())["batch"]["format"] == 2
    b1, b2 = L.load(L.dump([v1])), L.load(L.dump([v2]))
    assert L.verify(b1) == L.verify(b2) == [] and (b1[0].format, b2[0].format) == (1, 2)
    p1, p2 = L.prove(b1, evals[0].id), L.prove(b2, evals[0].id)
    assert p1.ok() and p2.ok() and "format" not in p1.json() and p2.json()["format"] == 2
    assert not replace(p2, root=v1.root).ok() and not replace(p1, root=v2.root).ok()
    assert not replace(p1, format=2, event=p2.event).ok() and not replace(p2, format=1, event=None).ok()
    assert not L.check_proof(evals[0].id, p2.index, p2.size, list(p2.path), v2.root) and not L.check_proof2(p2.event, p1.index, p1.size, list(p1.path), v1.root)
    # a writer who states the wrong format beside the root is found, in words: the format is inside what is hashed
    lied = L.dump([v1]).replace('"count":5,', '"count":5,"format":2,', 1)
    said = L.verify(L.load(lied))
    assert len(said) == 1 and "that is the root of these lines in format 1" in said[0]
    said = L.verify(L.load(L.dump([v2]).replace('"format":2,', "", 1)))
    assert len(said) == 1 and "that is the root of these lines in format 2" in said[0]
    with pytest.raises(L.Bad, match="reads no other"):
        L.load(L.dump([v2]).replace('"format":2', '"format":3', 1))
    with pytest.raises(L.Bad, match="twice"):
        L.merkle_root2([p2.event, p2.event])                               # a leaf given twice is refused, not folded
    three = [L.event_fields(e, MONTH, 0) for e in evals[:3]]
    last = sorted(three, key=L.event_key)[-1]
    assert L.merkle_root2(three) != L.merkle_root2(three[:2]) and L.seal2(3, b"x" * 32) != L.seal2(4, b"x" * 32)
    assert L.event_key(last) == max(e.id for e in evals[:3])


def test_migrate_adds_a_new_batch_that_names_the_old_one_and_rewrites_nothing(tmp_path):
    evals = [_ev(k, WORDS[k % 4]) for k in range(6)]
    old = L.dump([L.batch(evals[:4], 0, MONTH, format=1), L.batch(evals[4:], 1, MONTH, format=1)])
    path = tmp_path / "ledger.jsonl"
    path.write_text(old, encoding="utf-8", newline="\n")
    done = cli_run(["meter", "migrate", str(path), "--month", "2026-10"])
    assert done.exit_code == 0 and "not which evaluation was accepted" in done.output and "supersedes 202610.0:" in done.output
    text = path.read_text(encoding="utf-8")
    assert text.startswith(old) and text.count("\n") == old.count("\n") + 2                      # two new lines, nothing before them touched
    book = L.load(text)
    assert L.verify(book) == [] and [s.format for s in book] == [1, 1] and all(s.superseded for s in book)
    assert L.totals(book, MONTH) == L.totals(L.load(old), MONTH)            # the chain's numbers are the same numbers
    assert [c["superseded_by"]["root"] for c in L.commitments(book)] == [L.batch(evals[:4], 0, MONTH).root.hex(), L.batch(evals[4:], 1, MONTH).root.hex()]
    p = L.prove(book, evals[0].id)
    assert p.ok() and p.format == 2 and dict(zip(L.FIELDS, p.event))["verdict"] == "accepted" and L.prove(book, evals[0].id, 1).ok()
    assert "no format 1 batch left" in cli_run(["meter", "migrate", str(path)]).output and path.read_text(encoding="utf-8") == text
    shown = cli_run(["meter", "verify", str(path)])
    assert shown.exit_code == 0 and "not which evaluation was accepted" in shown.output and "re-committed in format 2" in shown.output
    # a batch that supersedes another and does not commit to its lines is found
    wrong = text.replace(book[0].superseded["root"], "0" * 64)
    assert any("supersedes it does not commit to these lines" in x for x in L.verify(L.load(wrong)))
    with pytest.raises(L.Bad, match="no lines of its own"):
        L.load(text + evals[5].line() + "\n")
    with pytest.raises(L.Bad, match="format 1 only"):
        L.prove(L.load(old), evals[0].id, 2)


def cli_run(args):
    from typer.testing import CliRunner
    return CliRunner().invoke(cli.app, args)


def test_reconcile_of_two_format_2_ledgers_names_omissions_duplicates_conflicts_and_corrections():
    e = [_ev(k) for k in range(8)]
    fix = L.Correction(BUYER, e[0].id.hex(), MONTH, 0, "verdict", verdict="rejected")
    buyer = L.load(L.dump([L.batch(e[:5], 0, MONTH), L.batch([e[5], e[1]], 1, MONTH, [fix])]))              # e[1] entered twice; a correction of e[0]
    theirs = [e[0], e[1], replace(e[2], currency="EURC"), replace(e[3], evidence=_h("other")), replace(e[4], rate=1), e[6]]
    seller = L.load(L.dump([L.batch(theirs, 0, MONTH)]))
    r = L.reconcile(buyer, seller)
    f = r.json()
    assert not r.agreed and r.complete and f["formats"] == {"buyer": [2], "seller": [2]} and f["compared"] == "every field of every evaluation"
    assert f["omissions"] == {"buyer": [e[6].id.hex()], "seller": [e[5].id.hex()]}                             # what each side left out
    assert f["duplicates"] == {"buyer": [e[1].id.hex()], "seller": []}
    assert {c["id"]: c["fields"] for c in f["conflicts"]} == {e[0].id.hex(): ["verdict"], e[2].id.hex(): ["currency"], e[3].id.hex(): ["evidence"],
                                                              e[4].id.hex(): ["amount"]}
    assert [(c["kind"], c["id"], c["of"], c["batch"], c["both"]) for c in f["corrections"]["buyer"]] == [("verdict", e[0].id.hex(), "202610.0", "202610.1", 0)]
    assert f["corrections"]["seller"] == []
    same = L.reconcile(seller, seller)
    assert same.agreed and same.json()["conflicts"] == [] and L.reconcile(seller, seller).statement() == same.statement()
    # with a format 1 ledger on one side only verdict, rate and month are compared, and the result says so
    old = L.load(L.dump([L.batch(theirs, 0, MONTH, format=1)]))
    loose = L.reconcile(buyer, old).json()
    assert "not which evaluation was accepted" in loose["compared"] and e[2].id.hex() not in {c["id"] for c in loose["conflicts"]}
