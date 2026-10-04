"""The meter's ledger (src/knos/ledger.py): the evaluation id is the chain's, the Merkle tree is RFC 6962's, every
inclusion proof verifies and no changed leaf keeps the root, a ledger is checked against the chain's totals and running
hash, and reconciling a buyer's ledger with a seller's finds exactly the planted missing and disputed events and gives
both sides the same statement, byte for byte. Hypothesis is not installed here, so the properties run over seeded
random cases."""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import replace
from pathlib import Path

import pytest

from knos import cli
from knos import ledger as L

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "meter"
BUYER, SELLER = 424242, 555000


def _ev(i: int, accepted: bool = True, rate: int = 2_000_000, milestone: int = 0) -> L.Evaluation:
    h = lambda s: hashlib.sha256(s.encode()).hexdigest()  # noqa: E731
    return L.Evaluation(BUYER, SELLER, h(f"order {i}"), hashlib.sha1(f"commit {i}".encode()).hexdigest(), h("policy"), milestone, accepted, rate)


def _ledger(evals, sizes, month: int = 202610) -> list[L.Stored]:
    """A ledger of these evaluations cut into batches of these sizes, read back from its own text."""
    out, at = [], 0
    for seq, n in enumerate(sizes):
        out.append(L.batch(evals[at:at + n], seq, month))
        at += n
    return L.load(L.dump(out))


# -- the id ------------------------------------------------------------------------------------------------------------
def test_the_id_is_the_key_the_single_mode_bills_once():
    order, policy, artifact = bytes([0xA1]) * 32, bytes([0xB2]) * 32, "a" * 40
    # EvalAud::key in programs-v2/knos_meter/src/gh.rs: hashv(order, the artifact's 40 characters, policy, milestone u32 le)
    want = hashlib.sha256(order + artifact.encode() + policy + (3).to_bytes(4, "little")).digest()
    e = L.Evaluation(BUYER, SELLER, order.hex(), artifact, policy.hex(), 3, True, 2_000_000)
    assert e.id == want == L.eval_id(order, artifact, policy, 3)
    src = (ROOT / "programs-v2" / "knos_meter" / "src" / "gh.rs").read_text(encoding="utf-8")
    assert "hashv(&[&self.order, &self.artifact, &self.policy, &self.milestone.to_le_bytes()])" in src      # the rule this file copies has not moved


def test_the_id_and_the_audience_are_those_of_the_program_client():
    meter = pytest.importorskip("knos.settle.v2.meter")     # needs solders; the ledger itself does not
    for i, (milestone, accepted, rate) in enumerate([(0, True, 2_000_000), (7, False, 0), (2 ** 32 - 1, True, 1)]):
        e = _ev(i, accepted, rate, milestone)
        order, policy = bytes.fromhex(e.order), bytes.fromhex(e.policy)
        assert e.id == meter.eval_key(order, e.artifact, policy, milestone)
        aud = meter.eval_audience(BUYER, SELLER, order, e.artifact, policy, milestone, accepted, rate)
        assert e.audience() == aud and L.parse(aud) == e and meter.parse_audience(aud).key == e.id


def test_a_line_is_canonical_and_a_wrong_line_is_refused_in_words():
    e = _ev(1)
    line = e.line()
    assert line == json.dumps(json.loads(line), sort_keys=True, separators=(",", ":")) and " " not in line
    assert L.parse(line) == e and L.parse(json.loads(line)) == e
    o = json.loads(line)
    for change, said in [({"id": "0" * 64}, "is not the id"), ({"accepted": 2}, "accepted must be 1 or 0"), ({"accepted": True}, "accepted must be 1 or 0"),
                         ({"artifact": "A" * 40}, "40 lowercase hex"), ({"order": "ab"}, "64 lowercase hex"), ({"milestone": 2 ** 32}, "milestone"),
                         ({"buyer": 0}, "buyer"), ({"rate": -1}, "rate"), ({"rate": 1.5}, "rate")]:
        with pytest.raises(L.Bad, match=said):
            L.parse({**o, **change})
    with pytest.raises(L.Bad, match="needs accepted"):
        L.parse({k: v for k, v in o.items() if k != "policy"})
    with pytest.raises(L.Bad, match="audience is"):
        L.parse("knosm:eval:1:2:3")


# -- the tree ----------------------------------------------------------------------------------------------------------
def test_the_tree_is_rfc_6962():
    sha = lambda b: hashlib.sha256(b).digest()  # noqa: E731
    assert L.merkle_root([]).hex() == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"      # RFC 6962: the hash of nothing
    a, b, c = sorted(bytes([i]) * 32 for i in (1, 2, 3))
    la, lb, lc = (sha(b"\x00" + x) for x in (a, b, c))
    assert L.merkle_root([a]) == la
    assert L.merkle_root([b, a]) == sha(b"\x01" + la + lb)                                                  # sorted, whatever the order given
    assert L.merkle_root([c, a, b, a]) == sha(b"\x01" + sha(b"\x01" + la + lb) + lc)                        # split at the largest power of two; each id once
    assert L.inclusion_path([a, b, c], c) == (2, [sha(b"\x01" + la + lb)])


def test_every_proof_verifies_and_no_other_does():
    rng = random.Random(6962)
    for n in [*range(1, 34), 100, 257]:
        ids = sorted(rng.randbytes(32) for _ in range(n))
        root = L.merkle_root(ids)
        for m in (range(n) if n <= 33 else rng.sample(range(n), 12)):
            index, path = L.inclusion_path(ids, ids[m])
            assert index == m and L.check_proof(ids[m], m, n, path, root), (n, m)
            assert not L.check_proof(rng.randbytes(32), m, n, path, root)                   # another id
            assert not L.check_proof(ids[m], m, n, path + [bytes(32)], root)                # a longer path
            if path:
                assert not L.check_proof(ids[m], m, n, path[:-1], root)
                assert not L.check_proof(ids[m], m ^ 1, n, path, root)                      # another place
                flipped = [bytes([path[0][0] ^ 1]) + path[0][1:], *path[1:]]
                assert not L.check_proof(ids[m], m, n, flipped, root)
        assert not L.check_proof(ids[0], n, n, [], root) and not L.check_proof(ids[0], -1, n, [], root)


def test_any_changed_added_or_removed_leaf_changes_the_root():
    rng = random.Random(1)
    for n in (1, 2, 3, 8, 9, 64, 100):
        ids = [rng.randbytes(32) for _ in range(n)]
        root = L.merkle_root(ids)
        assert L.merkle_root(rng.sample(ids, n)) == root                                    # order given does not matter
        for m in rng.sample(range(n), min(n, 8)):
            for bit in (0, 255):
                changed = bytearray(ids[m])
                changed[bit // 8] ^= 1 << (bit % 8)
                assert L.merkle_root([*ids[:m], bytes(changed), *ids[m + 1:]]) != root
            assert L.merkle_root(ids[:m] + ids[m + 1:]) != root
        assert L.merkle_root([*ids, rng.randbytes(32)]) != root


# -- a batch and a ledger ----------------------------------------------------------------------------------------------
def test_a_batch_gives_the_root_the_totals_and_the_audience():
    evals = [_ev(1), _ev(2, accepted=False), _ev(3, rate=500)]
    b = L.batch([evals[2].line(), evals[0].audience(), evals[1], evals[0]], 4, "2026-10")      # any of the three forms; a retry counts once
    assert (b.buyer, b.seller, b.month, b.seq, b.count, b.accepted, b.value) == (BUYER, SELLER, 202610, 4, 3, 2, 2_000_500)
    assert b.root == L.merkle_root(e.id for e in evals) and [e.id for e in b.evals] == sorted(e.id for e in evals)
    assert L.batch_audience(b) == f"knosm:batch:{BUYER}:{SELLER}:202610:4:3:2:2000500:{b.root.hex()}"
    assert L.batch_audience(b, claim=True).startswith("knosm:claim:")
    with pytest.raises(L.Bad, match="twice with different contents"):
        L.batch([evals[0], replace(evals[0], accepted=False)], 0, 202610)
    with pytest.raises(L.Bad, match="one buyer and one seller"):
        L.batch([evals[0], replace(evals[1], seller=9)], 0, 202610)
    with pytest.raises(L.Bad, match="at least one"):
        L.batch([], 0, 202610)
    with pytest.raises(L.Bad, match="YYYY-MM"):
        L.batch(evals, 0, "2026-13")


def test_the_running_hash_is_the_specified_one():
    root = bytes([7]) * 32
    want = hashlib.sha256(L.ZERO + root + b"".join(n.to_bytes(8, "little") for n in (0, 3, 2, 2_000_500))).digest()
    assert L.chain_hash(L.ZERO, root, 0, 3, 2, 2_000_500) == want
    assert len({L.chain_hash(L.ZERO, root, *v) for v in [(0, 3, 2, 5), (1, 3, 2, 5), (0, 4, 2, 5), (0, 3, 3, 5), (0, 3, 2, 6)]}) == 5


def test_a_ledger_verifies_against_the_chain_and_any_change_is_found():
    evals = [_ev(i, accepted=i % 3 != 0) for i in range(1, 12)]
    ledger = _ledger(evals, [4, 4, 3])
    chain = L.ZERO
    for s in ledger:        # what the program does, batch by batch
        b = s.batch()
        chain = L.chain_hash(chain, b.root, b.seq, b.count, b.accepted, b.value)
    onchain = L.Totals(3, 11, sum(e.accepted for e in evals), sum(e.value for e in evals), chain)
    assert L.verify(ledger) == [] and L.verify(ledger, onchain) == [] and L.totals(ledger, 202610) == onchain
    assert L.Totals.of(json.loads(json.dumps(onchain.json()))) == onchain
    # the chain says something else
    assert any("count" in p for p in L.verify(ledger, replace(onchain, count=12)))
    assert any("running hash" in p for p in L.verify(ledger, replace(onchain, chain=bytes(32))))
    assert any("next_seq" in p for p in L.verify(ledger[:2], onchain))                         # a batch held back from the file
    # the file was changed
    text = L.dump(s.batch() for s in ledger).splitlines()
    flipped = replace(ledger[1].evals[0], accepted=not ledger[1].evals[0].accepted).line()
    at = text.index(ledger[1].evals[0].line())
    for changed, said in [(text[:at] + [flipped] + text[at + 1:], "the header says"),           # a verdict changed
                          (text[:at] + text[at + 1:], "a line was changed, added or removed"),  # a line removed
                          (text + [_ev(99).line()], "a line was changed, added or removed"),    # a line added
                          (text + [text[-1]], "written twice"),
                          (text[:5] + text[10:], "not 0 to 1")]:                                # a whole batch removed
        assert any(said in p for p in L.verify(L.load("\n".join(changed)), onchain)), said
    # one evaluation in two batches: only the ledger can show it, the chain has no account per evaluation
    twice = L.load(L.dump([L.batch(evals[:4], 0, 202610), L.batch(evals[3:6], 1, 202610)]))
    assert any("counted twice" in p for p in L.verify(twice))
    two_months = L.load(L.dump([L.batch(evals[:4], 0, 202610), L.batch(evals[4:], 0, 202611)]))
    assert L.verify(two_months) == [] and "say which one" in L.verify(two_months, onchain)[0]
    assert L.verify(two_months, L.totals(two_months, 202611), 202611) == []
    for text_, said in [("{}", "before any batch header"), ("not json", "line 1 is not JSON"), ('{"batch":{"seq":0}}', "a batch header has")]:
        with pytest.raises(L.Bad, match=said):
            L.load(text_)


def test_a_proof_from_a_ledger_holds_against_the_batch_root_and_survives_json():
    ledger = _ledger([_ev(i) for i in range(1, 30)], [16, 13])
    for s in ledger:
        for e in s.evals:
            p = L.prove(ledger, e.id)
            assert p.ok() and p.root.hex() == s.declared["root"] and (p.month, p.seq, p.size) == (s.month, s.seq, len(s.evals))
            assert L.Proof.of(json.loads(json.dumps(p.json()))) == p
            assert not replace(p, id=_ev(99).id).ok() and not replace(p, root=bytes(32)).ok()
    with pytest.raises(L.Bad, match="in no batch"):
        L.prove(ledger, _ev(99).id)


# -- two ledgers -------------------------------------------------------------------------------------------------------
def test_reconcile_finds_exactly_what_was_planted_and_both_sides_get_the_same_statement():
    rng = random.Random(2026)
    for case in range(40):
        n = rng.randint(1, 60)
        truth = [_ev(case * 1000 + i, accepted=rng.random() < 0.8, rate=rng.choice([0, 500, 2_000_000])) for i in range(n)]
        dropped = set(rng.sample(range(n), rng.randint(0, n // 4)))                           # the buyer leaves these out
        rest = [i for i in range(n) if i not in dropped]
        flipped = set(rng.sample(rest, rng.randint(0, len(rest) // 4)))                       # the buyer records another verdict
        extra = [_ev(case * 1000 + 900 + i) for i in range(rng.randint(0, 3))]                # only the buyer has these
        buyer_evals = [replace(truth[i], accepted=not truth[i].accepted) if i in flipped else truth[i] for i in rest] + extra
        if not buyer_evals:
            continue
        cut = lambda evals: [len(evals) - len(evals) // 2, len(evals) // 2] if len(evals) > 1 else [1]  # noqa: E731
        rng.shuffle(buyer_evals)
        seller_evals = rng.sample(truth, n)
        buyer, seller = _ledger(buyer_evals, cut(buyer_evals)), _ledger(seller_evals, cut(seller_evals))
        r = L.reconcile(buyer, seller)
        assert {e.id for _m, e in r.seller_only} == {truth[i].id for i in dropped}
        assert {e.id for _m, e in r.buyer_only} == {e.id for e in extra}
        assert {d.id for d in r.disputed} == {truth[i].id for i in flipped} and all(d.what == ("verdict",) for d in r.disputed)
        assert r.duplicates == {"buyer": (), "seller": ()}
        assert r.agreed == (not dropped and not flipped and not extra)
        agreed = [truth[i] for i in rest if i not in flipped]
        assert r.rows == (L.Row(202610, len(agreed), sum(e.accepted for e in agreed), sum(e.value for e in agreed), 0, len(extra), len(dropped), len(flipped)),)
        # whoever computes it, from files in whatever order: the same bytes
        again = L.reconcile(_ledger(rng.sample(buyer_evals, len(buyer_evals)), [len(buyer_evals)]), _ledger(rng.sample(truth, n), [n]))
        assert again.statement() == r.statement() and again.json() == r.json()
        body, last = r.statement().rsplit("sha256,", 1)
        assert hashlib.sha256(body.encode()).hexdigest() == last.strip()


def test_reconcile_names_a_rate_a_month_and_a_duplicate():
    evals = [_ev(i) for i in range(1, 7)]
    seller = _ledger(evals, [6])
    buyer = L.load(L.dump([L.batch([evals[0], replace(evals[1], rate=1), evals[2], evals[3]], 0, 202610), L.batch([evals[4], evals[5], evals[0]], 0, 202611)]))
    r = L.reconcile(buyer, seller)
    by = {d.id: d for d in r.disputed}
    assert by[evals[1].id].what == ("rate",) and by[evals[4].id].what == ("month",) and by[evals[5].id].what == ("month",) and len(by) == 3
    assert r.duplicates == {"buyer": (evals[0].id,), "seller": ()} and not r.agreed and not r.buyer_only and not r.seller_only
    assert [(x.month, x.count, x.disputed) for x in r.rows] == [(202610, 3, 1), (202611, 0, 2)]
    with pytest.raises(L.Bad, match="same buyer and seller"):
        L.reconcile(seller, _ledger([replace(evals[0], seller=7)], [1]))


def test_the_fee_is_the_price_books_after_the_free_ten_thousand():
    assert (L.FREE_PER_MONTH, L.RATE) == (10_000, 50_000)
    assert [L.fee(n) for n in (0, 9_999, 10_000, 10_001, 15_000)] == [0, 0, 0, 50_000, 250_000_000]
    assert L.fee(15_000, rate=20_000) == 100_000_000 and L.fee(5, free=2) == 150_000         # a committed-volume plan; allowance partly used elsewhere
    evals = [_ev(i) for i in range(12)]
    r = L.reconcile(_ledger(evals, [12]), _ledger(evals, [5, 7]), free=10)
    assert r.agreed and r.rows[0].fee == 100_000 and "\n202610,12,12,24000000,100000,0,0,0\n" in r.statement()
    assert (L.usd(250_000_000), L.usd(50_000), L.usd(0)) == ("250", "0.05", "0")


def test_export_is_one_row_per_evaluation():
    evals = [_ev(1), _ev(2, accepted=False)]
    rows = L.export_csv(_ledger(evals, [2])).splitlines()
    assert rows[0] == "month,seq,id,buyer,seller,order,artifact,policy,milestone,accepted,rate" and len(rows) == 3
    assert {r.split(",")[2] for r in rows[1:]} == {e.id.hex() for e in evals} and {r.split(",")[9] for r in rows[1:]} == {"0", "1"}


# -- the example and the commands --------------------------------------------------------------------------------------
def _run(capsys, *args: str) -> tuple[int, str]:
    capsys.readouterr()
    rc = cli.main(["meter", *args])
    return rc, capsys.readouterr().out


def test_the_example_ledgers_hold_alone_and_disagree_together(capsys):
    buyer, seller = L.load(EXAMPLES / "buyer.jsonl"), L.load(EXAMPLES / "seller.jsonl")
    assert L.verify(buyer) == [] and L.verify(seller) == []
    assert (EXAMPLES / "buyer.jsonl").read_text(encoding="utf-8") == L.dump(s.batch() for s in buyer)      # canonical as committed
    r = L.reconcile(buyer, seller)
    assert len(r.seller_only) == 1 and len(r.disputed) == 1 and not r.buyer_only and r.rows == (L.Row(202610, 5, 4, 8_000_000, 0, 0, 1, 1),)
    rc, said = _run(capsys, "reconcile", str(EXAMPLES / "buyer.jsonl"), str(EXAMPLES / "seller.jsonl"))
    assert rc == 1 and "only the seller has" in said and "differs in verdict" in said and r.statement() in said and "The two ledgers differ." in said
    rc, said = _run(capsys, "reconcile", str(EXAMPLES / "seller.jsonl"), str(EXAMPLES / "seller.jsonl"))
    assert rc == 0 and "202610,7,6,12000000,0,0,0,0" in said and "The two ledgers agree." in said
    # every number docs/METER.md quotes about the example is the example's
    doc = (ROOT / "docs" / "METER.md").read_text(encoding="utf-8")
    assert "".join(f"    {line}\n" for line in r.statement().splitlines()) in doc and r.seller_only[0][1].id.hex() in doc and r.disputed[0].id.hex() in doc
    for t in (L.totals(buyer, 202610), L.totals(seller, 202610)):
        assert t.chain.hex() in doc


def test_the_commands_build_verify_prove_and_export(capsys, tmp_path):
    events, ledger, proof = tmp_path / "events.txt", tmp_path / "ledger.jsonl", tmp_path / "proof.json"
    evals = [_ev(i) for i in range(1, 6)]
    events.write_text("\n".join(e.audience() for e in evals[:3]) + "\n", encoding="utf-8")
    rc, said = _run(capsys, "batch", str(events), "--ledger", str(ledger), "--month", "2026-10")
    b = L.batch(evals[:3], 0, 202610)
    assert rc == 0 and "Batch 0 of 202610: 3 evaluation(s), 3 accepted, value 6000000." in said and L.batch_audience(b) in said.replace("\n", "")
    events.write_text("\n".join(e.line() for e in evals[1:]) + "\n", encoding="utf-8")         # two new ones, two the ledger has
    rc, said = _run(capsys, "batch", str(events), "--ledger", str(ledger), "--month", "2026-10", "--claim")
    assert rc == 0 and "Left out 2 evaluation(s)" in said and "Batch 1 of 202610: 2 evaluation(s)" in said and "knosm:claim:" in said
    assert _run(capsys, "batch", str(events), "--ledger", str(ledger), "--month", "2026-10")[0] == 1          # nothing new: refused
    got = L.load(ledger)
    assert L.verify(got) == [] and [s.seq for s in got] == [0, 1]

    onchain = tmp_path / "onchain.json"
    onchain.write_text(json.dumps(L.totals(got, 202610).json()), encoding="utf-8")
    rc, said = _run(capsys, "verify", str(ledger), "--onchain", str(onchain))
    assert rc == 0 and "its totals and running hash are the chain's" in said
    onchain.write_text(json.dumps({**L.totals(got, 202610).json(), "count": 6}), encoding="utf-8")
    rc, said = _run(capsys, "verify", str(ledger), "--onchain", str(onchain))
    assert rc == 1 and "count: the ledger gives 5, the chain has 6" in said
    ledger.write_text(ledger.read_text(encoding="utf-8").replace('"accepted":1,"artifact"', '"accepted":0,"artifact"', 1), encoding="utf-8")
    rc, said = _run(capsys, "verify", str(ledger))
    assert rc == 1 and "does not hold" in said

    rc, said = _run(capsys, "prove", str(EXAMPLES / "seller.jsonl"), evals[0].id.hex())
    assert rc == 1 and "in no batch" in said
    some = L.load(EXAMPLES / "seller.jsonl")[1].evals[2]
    rc, said = _run(capsys, "prove", str(EXAMPLES / "seller.jsonl"), some.id.hex())
    assert rc == 0 and L.Proof.of(json.loads(said)).ok()
    proof.write_text(said, encoding="utf-8")
    rc, said = _run(capsys, "prove", "--check", str(proof))
    assert rc == 0 and "The proof holds" in said
    proof.write_text(json.dumps({**json.loads(proof.read_text(encoding="utf-8")), "id": evals[0].id.hex()}), encoding="utf-8")
    rc, said = _run(capsys, "prove", "--check", str(proof))
    assert rc == 1 and "does not hold" in said
    assert _run(capsys, "prove")[0] == 1

    rc, said = _run(capsys, "export", str(EXAMPLES / "buyer.jsonl"))
    assert rc == 0 and said == L.export_csv(L.load(EXAMPLES / "buyer.jsonl")) and said.count("\n") == 7
    rc, said = _run(capsys, "export", str(tmp_path / "none.jsonl"))
    assert rc == 1 and "Cannot read" in said


def test_the_ledger_needs_nothing_but_the_standard_library():
    import ast
    import sys
    tree = ast.parse((ROOT / "src" / "knos" / "ledger.py").read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | \
            {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and not n.level}
    assert names - {"typer"} <= set(sys.stdlib_module_names)        # typer only inside register(), for the commands
