"""A month of the meter that can be defended (src/knos/ledger.py): a deliverable is one accepted outcome however many
pull requests carried it; one function decides what counts once, across batches and against the individual mode; a
repeat that was anchored fails `verify` until a correction for it is anchored; a close is `agreed` or `disputed` with
the exact lines, never an invoice by accident; and one archive of the month verifies with no network and fails on any
changed byte. The GitHub tokens here are signed by a test key made from a fixed seed."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import random
import socket
from dataclasses import replace

import pytest

from knos import cli
from knos import ledger as L

BUYER, SELLER, MONTH, RATE = 424242, 555000, 202610, 2_000_000
_h = lambda s: hashlib.sha256(s.encode()).hexdigest()  # noqa: E731


def _ev(order: int, artifact: int = 0, accepted: bool = True, milestone: int = 0) -> L.Evaluation:
    """One evaluation of work order `order`; `artifact` is which pull request's commit carried it."""
    return L.Evaluation(BUYER, SELLER, _h(f"order {order}"), hashlib.sha1(f"commit {order}.{artifact}".encode()).hexdigest(), _h("policy"), milestone, accepted, RATE)


def _book(*batches, month: int = MONTH) -> list[L.Stored]:
    """A ledger read back from its own text. A batch is a list of evaluations, or (evaluations, corrections)."""
    out = []
    for seq, b in enumerate(batches):
        evals, fixes = b if isinstance(b, tuple) else (b, ())
        out.append(L.batch(evals, seq, month, fixes))
    return L.load(L.dump(out))


def _raw(*batches, month: int = MONTH) -> list[L.Stored]:
    """A ledger whose batches may hold what an earlier one already has, as a file put together by hand can."""
    return L.load(L.dump(L.batch(b, seq, month) for seq, b in enumerate(batches)))


# -- a test key, and tokens as GitHub signs them -----------------------------------------------------------------------
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Key:
    """RSA from a fixed seed, 1024 bits: no key file, the same key on every machine. Signs PKCS#1 v1.5 SHA-256."""
    def __init__(self, seed: str):
        rng = random.Random(seed)

        def prime() -> int:
            while True:
                c = rng.getrandbits(512) | (3 << 510) | 1
                if c % 65537 != 1 and all(c % p for p in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)) and all(pow(a, c - 1, c) == 1 for a in (2, 3, 5, 7)) and self._mr(c, rng):
                    return c
        p, q = prime(), prime()
        self.n, self.d = p * q, pow(65537, -1, math.lcm(p - 1, q - 1))

    @staticmethod
    def _mr(n: int, rng) -> bool:
        d, r = n - 1, 0
        while d % 2 == 0:
            d, r = d // 2, r + 1
        for _ in range(16):
            x = pow(rng.randrange(2, n - 1), d, n)
            if x in (1, n - 1):
                continue
            for _ in range(r - 1):
                x = x * x % n
                if x == n - 1:
                    break
            else:
                return False
        return True

    def jwk(self, kid: str) -> dict:
        return {"kty": "RSA", "alg": "RS256", "use": "sig", "e": "AQAB", "kid": kid, "n": _b64(self.n.to_bytes(128, "big"))}

    def token(self, kid: str, **claims) -> str:
        signed = _b64(json.dumps({"typ": "JWT", "alg": "RS256", "kid": kid}).encode()) + "." + _b64(json.dumps(claims).encode())
        t = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(signed.encode()).digest()
        em = b"\x00\x01" + b"\xff" * (128 - len(t) - 3) + b"\x00" + t
        return signed + "." + _b64(pow(int.from_bytes(em, "big"), self.d, self.n).to_bytes(128, "big"))


@pytest.fixture(scope="module")
def github():
    key = Key("knos meter close test key")
    return key, {"keys": [key.jwk("k1"), Key("another key nobody signs with").jwk("k2")]}


def _signed(key: Key, record: dict, owner: int, **over) -> str:
    return key.token("k1", **{"iss": L.GITHUB_ISSUER, "aud": L.close_audience(record), "repository": f"org{owner}/ledgers", "repository_owner_id": str(owner),
                              "run_id": "36905461215", "iat": 1793491200, "exp": 1793491500, **over})


# -- 1. the deliverable ------------------------------------------------------------------------------------------------
def test_a_deliverable_split_into_ten_pull_requests_is_one_accepted_outcome():
    ten = [_ev(1, artifact=i) for i in range(10)]                               # one order, one milestone, ten commits
    assert len({e.id for e in ten}) == 10 and len({e.deliverable for e in ten}) == 1
    assert ten[0].deliverable == hashlib.sha256(bytes.fromhex(ten[0].order) + (0).to_bytes(4, "little")).hexdigest()
    assert json.loads(ten[0].line())["deliverable"] == ten[0].deliverable       # every ledger line carries it
    n = L.numbers(L.canonical(_book(ten[:4], ten[4:])), MONTH)
    assert (n.evaluations, n.accepted_outcomes, n.rejected) == (10, 1, 0)
    assert (n.accepted, n.value, n.outcome_value) == (10, 10 * RATE, RATE)      # the chain's value adds ten rates; a per-outcome price multiplies one
    # nine attempts rejected and the tenth accepted: ten evaluations are billable, nine rejected, one outcome
    tries = [replace(e, accepted=i == 9) for i, e in enumerate(ten)]
    n = L.numbers(L.canonical(_book(tries)), MONTH)
    assert (n.evaluations, n.accepted_outcomes, n.rejected) == (10, 1, 9)
    # another milestone of the same order is another deliverable; and none accepted is no outcome
    n = L.numbers(L.canonical(_book(ten + [_ev(1, 0, milestone=1)], [_ev(2, 0, accepted=False)])), MONTH)
    assert (n.evaluations, n.accepted_outcomes, n.rejected) == (12, 2, 1)
    with pytest.raises(L.Bad, match="deliverable"):
        L.parse({**json.loads(ten[0].line()), "deliverable": "0" * 64})
    old = {k: v for k, v in json.loads(ten[0].line()).items() if k != "deliverable"}
    assert L.parse(old) == ten[0]                                               # a line written before 0.3.15 still reads


def test_a_deliverable_accepted_in_an_earlier_month_is_not_an_outcome_again():
    book = L.load(L.dump([L.batch([_ev(1, 0)], 0, 202610), L.batch([_ev(1, 1), _ev(2, 0)], 0, 202611)]))
    c = L.canonical(book)
    assert L.numbers(c, 202610).accepted_outcomes == 1
    n = L.numbers(c, 202611)
    assert (n.evaluations, n.accepted_outcomes) == (2, 1)                       # order 1 was already bought and accepted in October


def test_the_statement_shows_the_three_numbers_the_fee_and_the_outcome_value():
    ten = [_ev(1, artifact=i) for i in range(10)]
    text = L.statement(_book(ten + [_ev(2, 0, accepted=False)]), "2026-10", free=5)
    for line in ("state,open", "evaluations,11", "accepted_outcomes,1", "rejected_evaluations,1", "accepted_evaluations,10", f"meter_fee,{6 * L.RATE}",
                 f"value_of_accepted_evaluations,{10 * RATE}", f"value_of_accepted_outcomes,{RATE}", "anchored,11,in 1 batch(es)", "anchored_and_not_counted,0"):
        assert f"\n{line}" in text, line
    body, rest = text.split("sha256,", 1)
    assert hashlib.sha256(body.encode()).hexdigest() == rest.splitlines()[0]


# -- 2. one function decides what counts once ---------------------------------------------------------------------------
def test_canonical_keeps_the_first_and_lists_every_repeat_with_its_reason():
    e = [_ev(i) for i in range(1, 9)]
    book = _raw(e[:4], e[3:6], [e[0], e[6], e[7]])                 # e[3] again in batch 1; e[0] again in batch 2
    text = L.dump(s.batch() for s in book).splitlines()
    book = L.load("\n".join(text + [text[-1]]))                    # and the last line of batch 2 written twice
    c = L.canonical(book, individual=[e[5].id])                    # and e[5] was recorded singly as well
    assert [(x.month, x.seq) for x in c.kept if x.e.id in (e[3].id, e[0].id)] == [(MONTH, 0)] * 2          # the first by time stands
    assert len(c.kept) == 7 and e[5].id not in {x.e.id for x in c.kept}
    last = L.parse(text[-1]).id
    assert {(d.id, d.seq, d.reason) for d in c.dropped} == {(e[3].id, 1, L.BATCH), (e[0].id, 2, L.BATCH), (e[5].id, 1, L.SINGLY), (last, 2, L.WITHIN)}
    assert {d.id: d.first for d in c.dropped if d.reason == L.BATCH} == {e[3].id: (MONTH, 0), e[0].id: (MONTH, 0)}
    assert all(d.corrected is None for d in c.dropped)
    # the result does not depend on the order of the file's batches or of the lines in them
    shuffled = L.load("\n".join(line for s in reversed(book) for line in [L.canon({"batch": s.declared}), *reversed([x.line() for x in s.evals])]))
    assert L.canonical(shuffled, [e[5].id]) == c
    # nothing repeated: nothing dropped, and the numbers are the chain's
    clean = _book(e[:4], e[4:])
    assert L.canonical(clean).dropped == () and L.numbers(L.canonical(clean), MONTH).evaluations == L.totals(clean, MONTH).count == 8


def test_verify_fails_an_anchored_repeat_by_name_until_a_correction_is_anchored():
    e = [_ev(i) for i in range(1, 8)]
    twice = _raw(e[:4], e[3:6])
    bad = L.verify(twice)
    assert len(bad) == 1 and e[3].id.hex() in bad[0] and "already in batch 0 of 202610" in bad[0] and "billed it twice" in bad[0] and "knos meter correct" in bad[0]
    # recorded singly and in a batch: the chain cannot see it either
    clean = _book(e[:4], e[4:6])
    assert L.verify(clean) == []
    bad = L.verify(clean, individual=[e[4].id])
    assert len(bad) == 1 and e[4].id.hex() in bad[0] and "recorded singly" in bad[0]
    assert L.read_ids(f"{e[4].id.hex()}\n\n{e[5].audience()}\n{e[6].line()}\n") == [e[4].id, e[5].id, e[6].id]
    # the remedy: a correction in the next batch. The chain's counters stay; the ledger holds and the statement nets it
    fix = L.Correction(BUYER, e[3].id.hex(), MONTH, 1, "duplicate")
    fixed = L.load(L.dump([*(s.batch() for s in twice), L.batch([e[6]], 2, MONTH, [fix])]))
    assert L.verify(fixed) == [] and L.verify(fixed, L.totals(fixed, MONTH)) == []
    assert L.totals(fixed, MONTH).count == 8 and L.numbers(L.canonical(fixed), MONTH).evaluations == 7
    text = L.statement(fixed, MONTH)
    assert f"\nrepeat,{e[3].id.hex()},batch 1 of 202610,billed twice on chain, corrected in batch 2 of 202610\n" in text
    assert "\nanchored_and_not_counted,1\n" in text and f"\ncorrection,duplicate,{e[3].id.hex()},of batch 1 of 202610,in batch 2 of 202610,by {BUYER}\n" in text
    assert "billed twice on chain, not corrected" in L.statement(twice, MONTH)      # before the correction the statement says so
    single = L.load(L.dump([*(s.batch() for s in clean), L.batch([e[6]], 2, MONTH, [L.Correction(BUYER, e[4].id.hex(), MONTH, 1, "duplicate")])]))
    assert L.verify(single, individual=[e[4].id]) == [] and L.numbers(L.canonical(single, [e[4].id]), MONTH).evaluations == 6


# -- 3. corrections -----------------------------------------------------------------------------------------------------
def test_a_correction_is_anchored_under_its_own_leaf_and_changes_no_counter():
    e = [_ev(i) for i in range(1, 8)]
    plain = L.batch(e[4:], 1, MONTH, format=1)
    fix = L.Correction(SELLER, e[0].id.hex(), MONTH, 0, "verdict", False)
    carried = L.batch(e[4:], 1, MONTH, [fix])
    assert plain.root == L.merkle_root([x.id for x in e[4:]])                                   # no correction: the tree of 0.3.14, so anchored roots still verify
    assert carried.root != plain.root and (carried.count, carried.accepted, carried.value) == (plain.count, plain.accepted, plain.value)
    assert L.Correction.of(json.loads(fix.line())) == fix and fix.key == hashlib.sha256(fix.line().encode()).digest()
    book = _book(e[:4], (e[4:], [fix]))
    assert L.verify(book) == [] and book[1].corrections == [fix] and book[1].declared["root"] == carried.root.hex()
    p = L.prove(book, fix.key)                                                                  # anyone shows the correction is under the anchored root
    assert p.ok() and p.correction and p.root == carried.root and p.size == 4 and L.Proof.of(json.loads(json.dumps(p.json()))) == p
    assert not replace(p, correction=False).ok()                                                # and it cannot be passed off as an evaluation
    assert all(L.prove(book, x.id).ok() and not L.prove(book, x.id).correction for x in e)
    # a changed, added or removed correction no longer gives the root
    text = L.dump(s.batch() for s in book)
    for changed in (text.replace('"kind":"verdict"', '"kind":"withdrawn"').replace('"accepted":0,"batch"', '"batch"'), text.replace(fix.line() + "\n", ""),
                    text + L.Correction(BUYER, e[1].id.hex(), MONTH, 0, "withdrawn").line() + "\n"):
        assert any("a line was changed, added or removed" in why for why in L.verify(L.load(changed)))
    # a correction names an entry of an earlier batch of this ledger, and its issuer is one of the two parties
    for wrong, said in ((L.Correction(BUYER, e[5].id.hex(), MONTH, 0, "withdrawn"), "no earlier batch"), (L.Correction(BUYER, e[5].id.hex(), MONTH, 1, "withdrawn"), "no earlier batch"),
                        (L.Correction(7, e[0].id.hex(), MONTH, 0, "withdrawn"), "neither this ledger's buyer nor its seller")):
        assert any(said in why for why in L.verify(_book(e[:4], (e[4:], [wrong])))), said
    for o, said in (({"correction": {"batch": "202610.0", "by": BUYER, "id": e[0].id.hex(), "kind": "verdict"}}, "only a verdict correction carries accepted"),
                    ({"correction": {"batch": "202610", "by": BUYER, "id": e[0].id.hex(), "kind": "withdrawn"}}, "<yyyymm>.<seq>"),
                    ({"correction": {"batch": "202610.0", "by": BUYER, "id": e[0].id.hex(), "kind": "refund"}}, "duplicate, verdict or withdrawn")):
        with pytest.raises(L.Bad, match=said):
            L.Correction.of(o)


def test_the_statement_nets_a_wrong_verdict_and_a_withdrawal_and_names_who_issued_them():
    e = [_ev(i) for i in range(1, 7)]
    fixes = [L.Correction(BUYER, e[0].id.hex(), MONTH, 0, "verdict", False), L.Correction(SELLER, e[1].id.hex(), MONTH, 0, "withdrawn")]
    book = _book(e[:4], (e[4:], fixes))
    before, after = L.numbers(L.canonical(_book(e[:4], e[4:])), MONTH), L.numbers(L.canonical(book), MONTH)
    assert (before.evaluations, before.accepted_outcomes, before.rejected) == (6, 6, 0)
    assert (after.evaluations, after.accepted_outcomes, after.rejected) == (5, 4, 1)
    assert L.totals(book, MONTH).count == 6 and L.totals(book, MONTH).accepted == 6             # what the chain holds does not move
    text = L.statement(book, MONTH)
    assert f"\ncorrection,verdict,{e[0].id.hex()},of batch 0 of 202610,in batch 1 of 202610,by {BUYER},accepted 0\n" in text
    assert f"\ncorrection,withdrawn,{e[1].id.hex()},of batch 0 of 202610,in batch 1 of 202610,by {SELLER}\n" in text
    assert f"\nrepeat,{e[1].id.hex()},batch 0 of 202610,withdrawn, corrected in batch 1 of 202610\n" in text and "\nanchored_and_not_counted,1\n" in text
    record = L.close(book, book, MONTH)                                                         # both parties see every correction and its issuer
    assert sorted((x["kind"], x["by"], x["in"], x["of"], x["batch"]) for x in record["corrections"]) == sorted(
        (k, by, side, "202610.0", "202610.1") for side in L.ROLES for k, by in (("verdict", BUYER), ("withdrawn", SELLER)))


# -- 4. the close -------------------------------------------------------------------------------------------------------
def _two_sides():
    """A buyer that left one evaluation out, judged one differently and entered one twice; and a seller with all eight."""
    e = [_ev(i) for i in range(1, 9)]
    buyer = _raw(e[:4], [replace(e[4], accepted=False), e[5], e[6], e[0]])
    return e, buyer, _book(e[:5], e[5:])


def test_a_close_is_agreed_only_when_both_ledgers_say_the_same_after_dedup_and_corrections():
    e = [_ev(i) for i in range(1, 9)]
    buyer, seller = _book(e[:3], e[3:]), _book(e[:6], e[6:])                    # the same facts cut into other batches
    record = L.close(buyer, seller, "2026-10")
    assert record["state"] == "agreed" and record["disputed"] == [] and (record["buyer"], record["seller"], record["month"]) == (BUYER, SELLER, MONTH)
    assert record["buyer_ledger"] == {"accepted_outcomes": 8, "anchored": 8, "batches": 2, "chain": L.totals(buyer, MONTH).chain.hex(), "corrections": 0, "evaluations": 8, "rejected": 0}
    assert record["seller_ledger"]["chain"] == L.totals(seller, MONTH).chain.hex() != record["buyer_ledger"]["chain"]
    raw = L.close_bytes(record)
    assert L.read_close(raw) == record and L.close_bytes(L.close(list(reversed(buyer)), list(reversed(seller)), MONTH)) == raw     # the same bytes whoever computes it
    assert L.close_audience(record) == f"knosm:close:{BUYER}:{SELLER}:202610:{hashlib.sha256(raw).hexdigest()}"
    with pytest.raises(L.Bad, match="not a close record"):
        L.read_close(raw.replace(b'"agreed"', b'"disputed"'))
    with pytest.raises(L.Bad, match="not a close record"):
        L.read_close(json.dumps(record).encode())                               # not the canonical bytes: nobody signed that sha256
    with pytest.raises(L.Bad, match="neither ledger has a batch of 202611"):
        L.close(buyer, seller, 202611)
    # a buyer's repeat that it corrected: agreed, and the correction is in the record with its issuer
    again = L.load(L.dump([L.batch(e[:4], 0, MONTH), L.batch([e[3], e[4], e[5]], 1, MONTH),
                           L.batch(e[6:], 2, MONTH, [L.Correction(BUYER, e[3].id.hex(), MONTH, 1, "duplicate")])]))
    record = L.close(again, seller, MONTH)
    assert record["state"] == "agreed" and record["buyer_ledger"]["anchored"] == 9 and record["buyer_ledger"]["evaluations"] == 8
    assert record["corrections"] == [{"batch": "202610.2", "by": BUYER, "id": e[3].id.hex(), "in": "buyer", "kind": "duplicate", "of": "202610.1"}]
    one, other = L.statement(again, MONTH, record), L.statement(seller, MONTH, record)
    assert one.split("sha256,")[1].splitlines()[0] == other.split("sha256,")[1].splitlines()[0] and "state,agreed" in one       # both sides compare one hash
    assert one != other and "billed twice on chain, corrected in batch 2 of 202610" in one and "billed twice" not in other


def test_reconcile_and_close_count_by_the_one_rule_a_corrected_repeat_agrees_and_an_open_one_is_named():
    """`knos meter reconcile` reads each ledger through `canonical`, as the close and the statement do: the same two
    files cannot agree under one command and differ under the other."""
    e = [_ev(i) for i in range(1, 9)]
    seller = _book(e[:6], e[6:])
    open_repeat = L.load(L.dump([L.batch(e[:4], 0, MONTH), L.batch([e[3], e[4], e[5]], 1, MONTH), L.batch(e[6:], 2, MONTH)]))
    r = L.reconcile(open_repeat, seller)
    assert r.duplicates == {"buyer": (e[3].id,), "seller": ()} and not r.agreed and L.close(open_repeat, seller, MONTH)["state"] == "disputed"
    corrected = L.load(L.dump([L.batch(e[:4], 0, MONTH), L.batch([e[3], e[4], e[5]], 1, MONTH),
                               L.batch(e[6:], 2, MONTH, [L.Correction(BUYER, e[3].id.hex(), MONTH, 1, "duplicate")])]))
    r = L.reconcile(corrected, seller)
    assert r.agreed and r.duplicates == {"buyer": (), "seller": ()} and [(x.month, x.count) for x in r.rows] == [(MONTH, 8)]
    assert L.close(corrected, seller, MONTH)["state"] == "agreed"
    # a verdict one side corrected and an evaluation one side withdrew are differences reconcile names, as the close does
    fixed = _book(e[:6], (e[6:], [L.Correction(BUYER, e[0].id.hex(), MONTH, 0, "verdict", False), L.Correction(BUYER, e[1].id.hex(), MONTH, 0, "withdrawn")]))
    r = L.reconcile(fixed, seller)
    assert [(d.id, d.what, d.buyer.accepted, d.seller.accepted) for d in r.disputed] == [(e[0].id, ("verdict",), False, True)]
    assert [x.id for _m, x in r.seller_only] == [e[1].id] and not r.buyer_only and not r.agreed and L.close(fixed, seller, MONTH)["state"] == "disputed"
    # and once the seller's ledger carries the same two corrections, both commands agree again
    both = _book(e[:6], (e[6:], [L.Correction(BUYER, e[0].id.hex(), MONTH, 0, "verdict", False), L.Correction(BUYER, e[1].id.hex(), MONTH, 0, "withdrawn")]))
    r = L.reconcile(fixed, both)
    assert r.agreed and [(x.month, x.count, x.accepted) for x in r.rows] == [(MONTH, 7, 6)] and L.close(fixed, both, MONTH)["state"] == "agreed"


def test_a_disputed_close_names_the_exact_lines_and_is_never_an_invoice_silently():
    e, buyer, seller = _two_sides()
    record = L.close(buyer, seller, MONTH)
    assert record["state"] == "disputed"
    why = {(x["id"], x["why"].split(":")[0]) for x in record["disputed"]}
    assert why == {(e[7].id.hex(), "missing from the buyer's ledger"), (e[4].id.hex(), "verdict differs"), (e[0].id.hex(), "duplicate in the buyer's ledger")}
    verdict = next(x for x in record["disputed"] if x["why"] == "verdict differs")
    assert verdict["buyer"] == {"accepted": 0, "batch": "202610.1", "rate": RATE} and verdict["seller"] == {"accepted": 1, "batch": "202610.0", "rate": RATE}
    assert (record["buyer_ledger"]["evaluations"], record["seller_ledger"]["evaluations"]) == (7, 8)
    for book in (buyer, seller):
        with pytest.raises(L.Disputed, match="is in dispute .3 line.s.., so there are no totals to invoice"):
            L.statement(book, MONTH, record)
        text = L.statement(book, MONTH, record, disputed=True)
        assert "\nstate,disputed\n" in text and "\nnote,DISPUTED: this is not an invoice" in text
        assert all(f"\ndisputed,{x['id']},{x['why']}\n" in text for x in record["disputed"])        # every disputed line is marked
    # the other dispute kinds: one only the buyer has, a rate, and a month
    for b, s, said in ((_book(e[:3]), _book(e[:2]), "missing from the seller's ledger"), (_book([replace(e[0], rate=1)]), _book(e[:1]), "rate differs"),
                       (_book(e[:2]), L.load(L.dump([L.batch(e[:1], 0, MONTH), L.batch(e[1:2], 0, 202611)])), "month differs")):
        assert [x["why"] for x in L.close(b, s, MONTH)["disputed"]] == [said]
    # a close record of another ledger, or of a ledger that changed since, is not this statement's
    with pytest.raises(L.Bad, match="not of this ledger and month"):
        L.statement(_book(e[:2]), MONTH, record, disputed=True)
    with pytest.raises(L.Bad, match="cannot be closed"):
        L.close(L.load(L.dump(s.batch() for s in seller).replace('"accepted":1,"artifact"', '"accepted":0,"artifact"', 1)), seller, MONTH)
    with pytest.raises(L.Bad, match="same buyer and seller"):
        L.close(seller, L.load(L.dump([L.batch([replace(e[0], seller=9)], 0, MONTH)])), MONTH)


def test_each_side_signs_the_close_and_the_tokens_are_checked_against_the_keys_alone(github):
    key, jwks = github
    e = [_ev(i) for i in range(1, 5)]
    record = L.close(_book(e), _book(e[:2], e[2:]), MONTH)
    for role, owner in (("buyer", BUYER), ("seller", SELLER)):
        assert L.check_close_token(record, _signed(key, record, owner), jwks, role)["repository_owner_id"] == str(owner)
    good = _signed(key, record, BUYER)
    other = L.close(_book(e[:3]), _book(e[:3]), MONTH)
    head, body, sig = good.split(".")
    forged = _b64(json.dumps({**json.loads(base64.urlsafe_b64decode(body + "==")), "repository_owner_id": str(SELLER)}).encode())
    for token, role, rec, keys, said in ((good, "seller", record, jwks, "from a repository of GitHub id 424242"),         # the buyer cannot sign for the seller
                                         (good, "buyer", other, jwks, "signed for something else than this close record"),
                                         (_signed(key, record, BUYER, iss="https://example.invalid"), "buyer", record, jwks, "not issued by GitHub Actions"),
                                         (good, "buyer", record, {"keys": jwks["keys"][1:]}, "signature of any of the given keys"),
                                         (f"{head}.{forged}.{sig}", "seller", record, jwks, "signature of any of the given keys"),
                                         (Key("a stranger").token("k1", iss=L.GITHUB_ISSUER, aud=L.close_audience(record), repository_owner_id=str(BUYER)), "buyer", record, jwks,
                                          "signature of any of the given keys"),
                                         ("not a token", "buyer", record, jwks, "not a signed token")):
        with pytest.raises(L.Bad, match=said):
            L.check_close_token(rec, token, keys, role)
    assert L.keys_used(jwks, [good]) == {"keys": [jwks["keys"][0]]}             # an archive keeps the keys the tokens name, no others


# -- 5. one archive of a month -----------------------------------------------------------------------------------------
def _month(github):
    key, jwks = github
    e = [_ev(i) for i in range(1, 9)]
    buyer = L.load(L.dump([L.batch(e[:4], 0, MONTH), L.batch([e[3], e[4], e[5]], 1, MONTH), L.batch(e[6:], 2, MONTH, [L.Correction(BUYER, e[3].id.hex(), MONTH, 1, "duplicate")])]))
    seller = _book(e[:6], e[6:])
    record = L.close(buyer, seller, MONTH)
    texts = {"buyer": L.dump(s.batch() for s in buyer), "seller": L.dump(s.batch() for s in seller)}
    return record, texts, {"buyer": _signed(key, record, BUYER), "seller": _signed(key, record, SELLER)}, jwks


def test_a_month_archive_is_deterministic_verifies_with_no_network_and_fails_on_any_changed_byte(github, monkeypatch):
    record, texts, tokens, jwks = _month(github)
    blob = L.month_bundle(record, texts, tokens, jwks)
    assert blob == L.month_bundle(record, dict(reversed(list(texts.items()))), dict(reversed(list(tokens.items()))), {"keys": list(reversed(jwks["keys"]))})

    def no_network(*a, **k):
        raise AssertionError("verifying a month's archive opened a socket")
    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    got, done = L.verify_month(blob)
    said = "\n".join(done)
    assert got == record and "the buyer's ledger recomputes" in said and "the seller's ledger recomputes" in said
    assert "the close record is the one the two ledgers give: agreed" in said and "the buyer signed this close record" in said and "the seller signed this close record" in said
    # every file is where the byte is: one changed byte in each, and bytes all along the archive
    import io
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        spans = {m.name: (m.offset_data, m.size) for m in tar.getmembers()}
    assert set(spans) == {"MANIFEST.json", "close.json", "jwks.json", "buyer.jwt", "seller.jwt", "ledger.buyer.jsonl", "ledger.seller.jsonl", "corrections.buyer.jsonl",
                          "corrections.seller.jsonl"}
    spots = {at + size // 2 for at, size in spans.values() if size} | set(range(0, len(blob), 211)) | {len(blob) - 1}
    for at in sorted(spots):
        changed = blob[:at] + bytes([blob[at] ^ 1]) + blob[at + 1:]
        with pytest.raises(L.Bad):
            L.verify_month(changed)
    for cut in (blob[:-1], blob + b"\0", blob[:1024], b""):
        with pytest.raises(L.Bad):
            L.verify_month(cut)
    # one party's own archive: its ledger alone, and whoever has not signed is named
    alone, done = L.verify_month(L.month_bundle(record, {"seller": texts["seller"]}, {"seller": tokens["seller"]}, jwks))
    assert alone == record and any("only the seller's ledger is in the archive" in d for d in done) and any("the buyer has NOT signed" in d for d in done)
    # nothing is archived that would not verify: another month's ledger, a token of the wrong party
    with pytest.raises(L.Bad, match="not what the buyer's ledger in the archive gives"):
        L.month_bundle(record, {"buyer": texts["seller"]}, {}, jwks)
    with pytest.raises(L.Bad, match="from a repository of GitHub id"):
        L.month_bundle(record, texts, {"buyer": tokens["seller"]}, jwks)


# -- the commands -------------------------------------------------------------------------------------------------------
def _run(capsys, *args: str) -> tuple[int, str]:
    capsys.readouterr()
    rc = cli.main(["meter", *args])
    return rc, capsys.readouterr().out.replace("\n", " ")


def test_the_commands_correct_close_state_and_archive_a_month(tmp_path, capsys, github):
    key, jwks = github
    e = [_ev(i) for i in range(1, 9)]
    buyer, seller, close_file = tmp_path / "buyer.jsonl", tmp_path / "seller.jsonl", tmp_path / "close.json"
    buyer.write_text(L.dump(s.batch() for s in _raw(e[:4], e[3:6])), encoding="utf-8", newline="\n")       # e[3] anchored twice
    seller.write_text(L.dump(s.batch() for s in _book(e[:6], e[6:])), encoding="utf-8", newline="\n")
    rc, said = _run(capsys, "verify", str(buyer))
    assert rc == 1 and e[3].id.hex() in said and "billed it twice" in said
    rc, said = _run(capsys, "close", str(buyer), str(seller), "--month", "2026-10", "--out", str(close_file))
    assert rc == 1 and "202610 is DISPUTED" in said and "duplicate in the buyer's ledger" in said and "missing from the buyer's ledger" in said
    rc, said = _run(capsys, "statement", str(buyer), "--month", "2026-10", "--close", str(close_file))
    assert rc == 1 and "is in dispute" in said and "evaluations," not in said                               # no totals for a disputed month
    rc, said = _run(capsys, "statement", str(buyer), "--month", "2026-10", "--close", str(close_file), "--disputed")
    assert rc == 0 and "note,DISPUTED" in said and f"disputed,{e[6].id.hex()},missing from the buyer's ledger" in said

    assert _run(capsys, "correct", str(buyer), e[3].id.hex(), "--batch", "202610.5", "--kind", "duplicate")[0] == 1         # no such entry
    assert _run(capsys, "correct", str(buyer), e[3].id.hex(), "--batch", "202610.1", "--kind", "verdict")[0] == 1           # a verdict needs --accepted
    rc, said = _run(capsys, "correct", str(buyer), e[3].id.hex(), "--batch", "202610.1", "--kind", "duplicate")
    assert rc == 0 and "is waiting in" in said and (tmp_path / "buyer.jsonl.corrections").read_text(encoding="utf-8").count("\n") == 1
    assert _run(capsys, "correct", str(buyer), e[3].id.hex(), "--batch", "202610.1", "--kind", "duplicate")[0] == 0         # said twice: kept once
    events = tmp_path / "events.txt"
    events.write_text("\n".join(x.line() for x in e[:6]) + "\n", encoding="utf-8")
    rc, said = _run(capsys, "batch", str(events), "--ledger", str(buyer), "--month", "2026-10")
    assert rc == 1 and "1 correction(s) are waiting" in said and "at least one new evaluation" in said
    events.write_text("\n".join(x.line() for x in e[6:]) + "\n", encoding="utf-8")
    rc, said = _run(capsys, "batch", str(events), "--ledger", str(buyer), "--month", "2026-10")
    assert rc == 0 and "Batch 2 of 202610: 2 evaluation(s)" in said and "Carries 1 correction(s)" in said
    book = L.load(buyer)
    assert L.verify(book) == [] and len(book[2].corrections) == 1 and _run(capsys, "verify", str(buyer))[0] == 0

    rc, said = _run(capsys, "close", str(buyer), str(seller), "--month", "2026-10", "--out", str(close_file))
    assert rc == 0 and "202610 is AGREED" in said and "correction (duplicate)" in said and f"issued by GitHub id {BUYER}" in said
    record = L.read_close(close_file.read_bytes())
    rc, said = _run(capsys, "close", "--check", str(close_file))
    assert rc == 1 and "The buyer has not signed" in said and "NOT signed by both sides" in said
    for role, owner in (("buyer", BUYER), ("seller", SELLER)):          # what `knos meter close --sign` keeps beside the record, from each side's own run
        (tmp_path / f"close.json.{role}.jwt").write_text(_signed(key, record, owner) + "\n", encoding="ascii", newline="\n")
    (tmp_path / "close.json.jwks.json").write_text(json.dumps(jwks), encoding="utf-8")
    rc, said = _run(capsys, "close", "--check", str(close_file))
    assert rc == 0 and "The buyer signed" in said and "The seller signed" in said and "AGREED and signed by both sides" in said
    rc, said = _run(capsys, "statement", str(buyer), "--month", "2026-10", "--close", str(close_file))
    assert rc == 0 and "state,agreed" in said and "evaluations,8" in said and "accepted_outcomes,8" in said and "billed twice on chain, corrected in batch 2 of 202610" in said

    archive = tmp_path / "month.tar"
    rc, said = _run(capsys, "export", str(buyer), "--bundle", str(archive), "--close", str(close_file), "--as", "buyer", "--other", str(seller))
    assert rc == 0 and "signed by buyer, seller" in said
    first = archive.read_bytes()
    assert _run(capsys, "export", str(buyer), "--bundle", str(archive), "--close", str(close_file), "--other", str(seller))[0] == 0 and archive.read_bytes() == first
    rc, said = _run(capsys, "verify", str(archive), "--bundle")
    assert rc == 0 and "The archive holds" in said and "is AGREED" in said and "the seller signed this close record" in said
    archive.write_bytes(first.replace(e[0].id.hex().encode(), e[1].id.hex().encode(), 1))
    rc, said = _run(capsys, "verify", str(archive), "--bundle")
    assert rc == 1 and "does not verify" in said
    (tmp_path / "close.json.seller.jwt").write_text(_signed(key, record, BUYER) + "\n", encoding="ascii", newline="\n")       # the buyer signing as the seller
    assert _run(capsys, "close", "--check", str(close_file))[0] == 1
    assert _run(capsys, "export", str(buyer), "--bundle", str(tmp_path / "bad.tar"), "--close", str(close_file))[0] == 1 and not (tmp_path / "bad.tar").exists()


def test_signing_asks_github_for_the_close_audience_and_keeps_the_token_beside_the_record(tmp_path, capsys, github, monkeypatch):
    key, jwks = github
    e = [_ev(i) for i in range(1, 4)]
    record = L.close(_book(e), _book(e), MONTH)
    close_file = tmp_path / "close.json"
    close_file.write_bytes(L.close_bytes(record))
    from knos import flow
    asked = []

    def mint(audience: str, env=None) -> str:
        asked.append(audience)
        return _signed(key, record, SELLER)

    class Answer:
        def __enter__(self):
            import io
            return io.BytesIO(json.dumps(jwks).encode())

        def __exit__(self, *a):
            return False
    import urllib.request
    monkeypatch.setattr(flow, "mint", mint)
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=0: Answer() if url == L.GITHUB_JWKS else (_ for _ in ()).throw(AssertionError(url)))
    assert _run(capsys, "close", "--sign", str(close_file), "--as", "buyer")[0] == 1          # a run in the seller's repository cannot sign as the buyer
    assert not (tmp_path / "close.json.buyer.jwt").exists()
    rc, said = _run(capsys, "close", "--sign", str(close_file), "--as", "seller")
    assert rc == 0 and asked == [L.close_audience(record)] * 2 and "GitHub signed" in said
    assert json.loads((tmp_path / "close.json.jwks.json").read_text(encoding="utf-8")) == {"keys": [jwks["keys"][0]]}
    assert L.check_close_token(record, (tmp_path / "close.json.seller.jwt").read_text(encoding="ascii"), jwks, "seller")
    # --token: a token another job asked GitHub for is checked against the record and kept; GitHub is asked for none
    (tmp_path / "close.json.seller.jwt").unlink()
    (tmp_path / "token.jwt").write_text(_signed(key, record, SELLER) + "\n", encoding="ascii")
    rc, said = _run(capsys, "close", "--sign", str(close_file), "--as", "seller", "--token", str(tmp_path / "token.jwt"))
    assert rc == 0 and len(asked) == 2 and L.check_close_token(record, (tmp_path / "close.json.seller.jwt").read_text(encoding="ascii"), jwks, "seller")
    assert _run(capsys, "close", "--sign", str(close_file), "--as", "buyer", "--token", str(tmp_path / "token.jwt"))[0] == 1 and not (tmp_path / "close.json.buyer.jwt").exists()
    other = L.close(_book(e[:2]), _book(e[:2]), MONTH)                           # a token for another record is not this record's
    (tmp_path / "token.jwt").write_text(_signed(key, other, SELLER) + "\n", encoding="ascii")
    (tmp_path / "close.json.seller.jwt").unlink()
    assert _run(capsys, "close", "--sign", str(close_file), "--as", "seller", "--token", str(tmp_path / "token.jwt"))[0] == 1
    assert not (tmp_path / "close.json.seller.jwt").exists() and len(asked) == 2


def test_the_document_shows_what_the_example_ledgers_give():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    doc = (root / "docs" / "reference" / "METER.md").read_text(encoding="utf-8")
    buyer, seller = (L.load(root / "examples" / "meter" / f"{name}.jsonl") for name in L.ROLES)
    record = L.close(buyer, seller, 202610)
    assert record["state"] == "disputed" and all(f"IN DISPUTE {x['id']}: {x['why']}\n" in doc for x in record["disputed"])
    assert f"(sha256 {hashlib.sha256(L.close_bytes(record)).hexdigest()[:8]}...)" in doc
    shown = L.statement(seller, 202610).split("sha256,")
    assert "".join(f"    {line}\n" for line in shown[0].splitlines()) in doc and "".join(f"    {line}\n" for line in shown[1].splitlines()[1:]) in doc
    assert "knosm:close:<buyer>:<seller>:<yyyymm>:<sha256 of the close record>" in doc and "An on-chain close would need a\nprogram change and is not built." in doc
