"""Write conformance/vectors/ledger.v2.json from src/knos/ledger.py. Run once per version of the format: the vectors
of a published version never change (manifest.json names their hash).

    PYTHONPATH=src python conformance/make_ledger2.py
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from knos import ids
from knos import ledger as L

HERE = Path(__file__).resolve().parent
BUYER, SELLER, MONTH = 424242, 555000, 202610


def h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def ev(i: int, verdict: str = "accepted", rate: int = 2_000_000, **more) -> L.Evaluation:
    return L.Evaluation(BUYER, SELLER, h(f"order {i}"), h(f"commit {i}")[:40], h("policy"), i % 3, verdict == "accepted", rate, verdict,
                        more.pop("evaluator", "judge@1"), more.pop("run", str(1000 + i)), currency=more.pop("currency", "USDC"),
                        evidence=more.pop("evidence", h(f"token {i}")), **more)


def obj(e: L.Evaluation, seq: int = 0, month: int = MONTH) -> dict:
    return dict(zip(L.FIELDS, L.event_fields(e, month, seq)))


def main() -> None:
    cases: list[dict] = []

    def add(op: str, name: str, input_: dict, expect: dict) -> None:
        cases.append({"id": f"ledger2/{len(cases) + 1}", "op": op, "name": name, "input": input_, "expect": expect})

    full = ev(1, inv=ids.invoice_line(str(SELLER), "INV-7", 3), stl="")
    paid = replace(ev(2), stl=ids.settlement(ev(2).dlv, "chain", "5sig"))
    bare = L.Evaluation(BUYER, SELLER, h("order 3"), h("commit 3")[:40], h("policy"), 0, False, 0)
    words = ev(4, "insufficient_evidence", evaluator="juge-é@2", run="run/9")
    for name, e, seq in (("every field stated", full, 0), ("a settled, accepted evaluation", paid, 3), ("a line that states no verdict in words, currency, evidence, evaluator or run: "
                         "the empty texts are hashed", bare, 0), ("a verdict that is neither accepted nor rejected, and text outside ASCII", words, 18446744073709551615)):
        o = obj(e, seq)
        add("ledger2.event_bytes", name, {"event": o}, {"output": L.encode_event(tuple(o[k] for k in L.FIELDS)).hex()})
        add("ledger2.leaf", name, {"event": o}, {"output": L.leaf2(tuple(o[k] for k in L.FIELDS)).hex()})
    o = obj(full)
    for name, change, why in (("a verdict that is not one of the four words", {"verdict": "passed"}, "verdict"),
                              ("an amount with a leading zero", {"amount": "02000000"}, "one way to write a number"),
                              ("a deliverable id that is not the id of the order and milestone", {"deliverable_id": "dlv_" + "0" * 24}, "ids are recomputed"),
                              ("an evaluation id that is not the id of the run stated", {"run": "1002"}, "ids are recomputed"),
                              ("an order in upper case", {"order": o["order"].upper()}, "lowercase hex"),
                              ("an evidence digest that is not 64 hex characters", {"evidence": "abc"}, "32 bytes or empty"),
                              ("a month of five digits", {"month": "20261"}, "six digits")):
        add("ledger2.event_bytes", name, {"event": {**o, **change}}, {"refused": True, "why": why})
    less = dict(o)
    del less["currency"]
    add("ledger2.event_bytes", "a field left out", {"event": less}, {"refused": True, "why": "eighteen fields, all present"})

    five = [ev(i, v) for i, v in zip(range(10, 15), ("accepted", "rejected", "insufficient_evidence", "disputed", "accepted"))]
    fixes = [L.Correction(BUYER, five[0].id.hex(), MONTH, 0, "withdrawn").key.hex(), L.Correction(SELLER, five[1].id.hex(), MONTH, 0, "verdict", verdict="accepted").key.hex()]
    for name, events, keys in (("one event", five[:1], []), ("two events", five[:2], []), ("three events: the last has no sibling and is carried up", five[:3], []),
                               ("five events", five, []), ("five events given in another order: the same root", five[::-1], []),
                               ("five events and two corrections", five, fixes), ("the corrections given in another order and one twice", five, [fixes[1], fixes[0], fixes[1]])):
        evs = [obj(e) for e in events]
        add("ledger2.root", name, {"events": evs, "corrections": keys}, {"output": L.merkle_root2([tuple(x[k] for k in L.FIELDS) for x in evs], [bytes.fromhex(k) for k in keys]).hex()})
    add("ledger2.root", "three events in batch 1: another root, the sequence is hashed", {"events": [obj(e, 1) for e in five[:3]], "corrections": []},
        {"output": L.batch(five[:3], 1, MONTH).root.hex()})
    # the swap: two evaluations at one price, one accepted; then the other one accepted. Count, accepted and value are the same.
    a, b = ev(20, "accepted", 2_000_000), ev(21, "rejected", 2_000_000)
    a2, b2 = replace(a, verdict="rejected", accepted=False), replace(b, verdict="accepted", accepted=True)
    for name, pair in (("the swap pair, the first accepted", (a, b)), ("the swap pair, the second accepted: another root (in format 1 the two are one root, "
                       + L.batch((a, b), 0, MONTH, format=1).root.hex() + ")", (a2, b2))):
        add("ledger2.root", name, {"events": [obj(e) for e in pair], "corrections": []}, {"output": L.batch(pair, 0, MONTH).root.hex()})
    assert L.batch((a, b), 0, MONTH, format=1).root == L.batch((a2, b2), 0, MONTH, format=1).root and L.batch((a, b), 0, MONTH).root != L.batch((a2, b2), 0, MONTH).root
    add("ledger2.root", "one event twice", {"events": [obj(five[0]), obj(five[0])], "corrections": []}, {"refused": True, "why": "each evaluation once"})
    add("ledger2.root", "one evaluation with two verdicts", {"events": [obj(five[0]), obj(replace(five[0], verdict="rejected", accepted=False))], "corrections": []},
        {"refused": True, "why": "a batch says one thing about each evaluation"})
    add("ledger2.root", "an event with a verdict that is not one of the four", {"events": [{**obj(five[0]), "verdict": "ok"}], "corrections": []}, {"refused": True, "why": "verdict"})

    book = L.load(L.dump([L.batch(five, 0, MONTH)]))
    old = L.batch(five, 0, MONTH, format=1)
    for n, e in enumerate(book[0].evals):
        p = L.prove(book, e.id)
        said: dict = {"event": dict(zip(L.FIELDS, p.event or ())), "index": p.index, "size": p.size, "path": [x.hex() for x in p.path], "root": p.root.hex()}
        add("ledger2.check_proof", f"leaf {p.index} of five", said, {"output": True})
        if n == 0:
            flip = "rejected" if said["event"]["verdict"] == "accepted" else "accepted"
            add("ledger2.check_proof", "the same path with another verdict", {**said, "event": {**said["event"], "verdict": flip}}, {"output": False})
            add("ledger2.check_proof", "the same path with another amount", {**said, "event": {**said["event"], "amount": "2000001"}}, {"output": False})
            add("ledger2.check_proof", "the same path with another currency", {**said, "event": {**said["event"], "currency": "EURC"}}, {"output": False})
            add("ledger2.check_proof", "another size", {**said, "size": 6}, {"output": False})
            add("ledger2.check_proof", "another index", {**said, "index": (p.index + 1) % 5}, {"output": False})
            add("ledger2.check_proof", "against the format 1 root of the same five", {**said, "root": old.root.hex()}, {"output": False})
            p1 = L.prove(L.load(L.dump([old])), e.id)
            add("ledger2.check_proof", "a format 1 path and root for the same evaluation", {**said, "index": p1.index, "size": p1.size, "path": [x.hex() for x in p1.path],
                                                                                           "root": p1.root.hex()}, {"output": False})
            add("ledger2.check_proof", "an event that is not well formed", {**said, "event": {**said["event"], "verdict": "ok"}}, {"output": False})
    data = {"format": "ledger2", "version": 2,
            "about": "The meter's batch commitment, format 2 (src/knos/ledger.py; docs/CONFORMANCE.md, Ledger, format 2). An event is eighteen texts: " + ", ".join(L.FIELDS)
                     + ". Its bytes: 'knos.event' 0x00, 0x02, 0x12, then each text in that order as its length in bytes (u32 big-endian) and its UTF-8 bytes. "
                       "leaf = sha256('knos.leaf.2' 0x00 || bytes); node = sha256('knos.node.2' 0x00 || left || right); a correction's leaf = sha256('knos.fix.2' 0x00 || key); "
                       "root = sha256('knos.root.2' 0x00 || number of leaves, u32 big-endian || top). Leaves: the events in ascending order of sha256(order, 32 bytes || artifact, "
                       "40 characters || policy, 32 bytes || milestone, u32 little-endian), each once, then the corrections' keys ascending, each once. The tree splits at the "
                       "largest power of two below the number of leaves. Every hash is lower-case hex.",
            "cases": cases}
    (HERE / "vectors" / "ledger.v2.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(len(cases), hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest())


if __name__ == "__main__":
    main()
