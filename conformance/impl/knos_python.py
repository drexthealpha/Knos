"""Knos's own Python, as an implementation the conformance kit can run:

    python conformance/run.py --impl "python conformance/impl/knos_python.py"

Every operation is answered by the function the rest of Knos uses (src/knos/receipt.py, ids.py, terms.py, ledger.py and
settle/v2), except statement.hash: Knos writes a statement's hash and has no function that reads one back, so the few
lines below do what docs/CONFORMANCE.md says. Another implementation needs none of this file: only the protocol in
conformance/run.py.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from knos import ids as I, ledger as L, receipt, terms as T  # noqa: E402
from knos.settle.v2 import gate, meter, oidc, order_auto, pay  # noqa: E402


class Refuse(Exception):
    pass


def _b(hex_text: str) -> bytes:
    return bytes.fromhex(hex_text)


def _terms(i: dict):
    try:
        data = T.canonical(i["terms"])
    except T.Refused:
        raise Refuse from None
    return {"json": data.decode("ascii"), "sha256": hashlib.sha256(data).hexdigest()}


def _receipt_check(i: dict):
    if receipt.check(i["receipt"]) is not None:
        raise Refuse
    return True


def _receipt_verdict(i: dict):
    _receipt_check(i)
    return {"verdict": receipt.verdict_of(i["receipt"]), "authorises_payment": receipt.authorises_payment(i["receipt"])}


def _or_refuse(fn):
    def run(i: dict):
        try:
            return fn(i)
        except (ValueError, L.Bad):
            raise Refuse from None
    return run


def _event(o) -> tuple:
    """An event of ledger format 2 as the vectors write it (an object of the eighteen texts) in the order they are hashed in."""
    if not isinstance(o, dict) or set(o) != set(L.FIELDS):
        raise L.Bad("an event has exactly the eighteen fields")
    return tuple(o[k] for k in L.FIELDS)


def _event_ok(o) -> bool:
    try:
        return L.event_problem(_event(o)) is None
    except L.Bad:
        return False


def _parse_batch(i: dict):
    try:
        claim, b = L.parse_batch_audience(i["audience"])
    except L.Bad:
        raise Refuse from None
    return {"kind": "claim" if claim else "batch", "buyer_id": b.buyer, "seller_id": b.seller, "month": b.month, "seq": b.seq, "count": b.count,
            "accepted": b.accepted, "value": b.value, "root": b.root.hex()}


def _statement_hash(i: dict):
    text = i["statement"]
    if not text.startswith("knos meter statement,1\n") or "\nsha256," not in text:
        raise Refuse
    body, _, rest = text.partition("\nsha256,")
    computed = hashlib.sha256((body + "\n").encode("utf-8")).hexdigest()
    stated = rest.split("\n")[0]
    return {"sha256": computed, "stated": stated, "agrees": computed == stated}


def _payees(rows):
    return [tuple(r) for r in rows]


OPS = {
    "receipt.digest": lambda i: receipt.digest(i["receipt"]),
    "receipt.check": _receipt_check,
    "receipt.verdict": _receipt_verdict,
    "ids.deliverable": lambda i: I.deliverable(i["scope"], i["key"]),
    "ids.evaluation": lambda i: I.evaluation(i["deliverable"], i["artifact"], i["policy"], i["evaluator"], i["run"]),
    "ids.invoice_line": lambda i: I.invoice_line(i["supplier"], i["invoice"], i["line"]),
    "ids.settlement": lambda i: I.settlement(i["deliverable"], i["method"], i["reference"]),
    "ids.kind_of": lambda i: I.kind_of(i["id"]),
    "ids.expect": _or_refuse(lambda i: I.expect(i["kind"], i["id"])),
    "ids.order_scope": _or_refuse(lambda i: I.order_scope(i["order"])),
    "ids.verdict": _or_refuse(lambda i: I.verdict(i["word"])),
    "ids.billed_once": _or_refuse(lambda i: L.billed_once([(e["deliverable"], e["verdict"]) for e in i["evaluations"]])),
    "terms.hash": _terms,
    "terms.canonical": _terms,
    "ledger.eval_id": lambda i: L.eval_id(_b(i["order"]), i["artifact"], _b(i["policy"]), i["milestone"]).hex(),
    "ledger.deliverable_id": lambda i: L.deliverable_id(_b(i["order"]), i["milestone"]).hex(),
    "ledger.batch_root": lambda i: L.merkle_root([_b(x) for x in i["ids"]]).hex(),
    "ledger.batch_root_any": lambda i: L.merkle_root([_b(x) for x in i["ids"]], [_b(x) for x in i["corrections"]]).hex(),
    "ledger.check_proof": lambda i: L.check_proof(_b(i["id"]), i["index"], i["size"], [_b(x) for x in i["path"]], _b(i["root"]), i["correction"]),
    "ledger.chain_hash": lambda i: L.chain_hash(_b(i["before"]), _b(i["root"]), i["seq"], i["count"], i["accepted"], i["value"]).hex(),
    "ledger2.event_bytes": _or_refuse(lambda i: L.encode_event(_event(i["event"])).hex()),
    "ledger2.leaf": _or_refuse(lambda i: L.leaf2(_event(i["event"])).hex()),
    "ledger2.root": _or_refuse(lambda i: L.merkle_root2([_event(e) for e in i["events"]], [_b(x) for x in i["corrections"]]).hex()),
    "ledger2.check_proof": lambda i: _event_ok(i["event"]) and L.check_proof2(_event(i["event"]), i["index"], i["size"], [_b(x) for x in i["path"]], _b(i["root"])),
    "audience.knos2_fund": lambda i: pay.fund_audience(i["issue"], i["amount"], i["mode"], _b(i["terms"]), i["balance"], i["work_s"]),
    "audience.knos2_pay": lambda i: pay.pay_audience(i["repo_id"], i["issue"], i["payee_id"], i["head_sha"], _b(i["terms"]), i["mode"], i["address"]),
    "audience.knos2_bind": lambda i: pay.bind_audience(i["address"]),
    "audience.knos3_fund": lambda i: pay.order_fund_audience(i["issue"], i["amount"], i["mode"], _b(i["terms"]), i["balance"], i["work_s"], i["seq"], _b(i["options"])),
    "audience.knos3_pay": lambda i: pay.order_pay_audience(i["order"], i["head_sha"], _b(i["terms"]), i["mode"], i["pr"], _payees(i["payees"])),
    "audience.knos3_rule": lambda i: pay.rule_audience(i["order"], _payees(i["payees"])),
    "audience.knos3_bind": lambda i: pay.org_bind_audience(i["address"]),
    "audience.knos3_take": lambda i: pay.take_audience(i["order"], i["taker_id"], i["days"]),
    "audience.knos3_cancel": lambda i: pay.cancel_audience(i["order"]),
    "audience.knos3_revert": lambda i: pay.revert_audience(i["order"], i["head_sha"]),
    "audience.knos3_auto": lambda i: order_auto.auto_audience(i["order"], i["head_sha"], _b(i["terms"]), i["pr"], i["payee_id"], i["address"]),
    "audience.knosm_eval": lambda i: meter.eval_audience(i["buyer_id"], i["seller_id"], _b(i["order"]), i["artifact"], _b(i["policy"]), i["milestone"], i["accepted"], i["rate"]),
    "audience.knosm_batch": lambda i: meter.batch_audience(i["buyer_id"], i["seller_id"], i["month"], i["seq"], i["count"], i["accepted"], i["value"], _b(i["root"]), i["kind"]),
    "audience.knos_oidc_key": lambda i: oidc.rotate_audience(i["issuer"], int(i["modulus"], 16)),
    "audience.gate": lambda i: gate.audience(i["program"], _b(i["executable"])),
    "audience.parse_knosm_batch": _parse_batch,
    # (the vector was written at the Meter price of its day, which a statement prints: a vector never changes, so the price is given)
    "statement.text": lambda i: L.statement(L.load(i["ledger"]), i["month"], rate=50_000, free=10_000),
    "statement.hash": _statement_hash,
}


def main() -> int:
    out = sys.stdout
    if hasattr(out, "reconfigure"):
        out.reconfigure(encoding="utf-8", newline="\n")
    for line in sys.stdin.buffer.read().decode("utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        fn = OPS.get(case["op"])
        if fn is None:
            answer = {"unsupported": True}
        else:
            try:
                answer = {"output": fn(case["input"])}
            except Refuse:
                answer = {"refused": True}
        out.write(json.dumps({"id": case["id"], **answer}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
