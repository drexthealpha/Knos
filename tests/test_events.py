"""knos.events: one log under every recording mode. Deterministic, no network, no clock."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import random

import pytest

from knos import events as E
from knos import ids
from knos import ledger as L

BUYER, SELLER = 424242, 555000


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Key:
    """RSA from a fixed seed, 1024 bits: the same key on every machine. Signs PKCS#1 v1.5 SHA-256."""
    def __init__(self, seed: str):
        rng = random.Random(seed)

        def prime() -> int:
            while True:
                c = rng.getrandbits(512) | (3 << 510) | 1
                if c % 65537 != 1 and all(c % p for p in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)) and all(pow(a, c - 1, c) == 1 for a in (2, 3, 5, 7, 11, 13)):
                    return c
        p, q = prime(), prime()
        self.n, self.d = p * q, pow(65537, -1, math.lcm(p - 1, q - 1))

    def jwk(self, kid: str) -> dict:
        return {"kty": "RSA", "alg": "RS256", "use": "sig", "e": "AQAB", "kid": kid, "n": _b64(self.n.to_bytes(128, "big"))}

    def token(self, kid: str, **claims) -> str:
        signed = _b64(json.dumps({"typ": "JWT", "alg": "RS256", "kid": kid}).encode()) + "." + _b64(json.dumps(claims).encode())
        t = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(signed.encode()).digest()
        em = b"\x00\x01" + b"\xff" * (128 - len(t) - 3) + b"\x00" + t
        return signed + "." + _b64(pow(int.from_bytes(em, "big"), self.d, self.n).to_bytes(128, "big"))


@pytest.fixture(scope="module")
def github():
    key = Key("knos events test key")
    return key, {"keys": [key.jwk("k1"), Key("a key nobody signs with").jwk("k2")]}


def _ack(key: Key, log: E.Log, owner: int, **over) -> str:
    return key.token("k1", **{"iss": L.GITHUB_ISSUER, "aud": E.ack_audience(owner, len(log.events) - 1, log.head), "repository_owner_id": str(owner),
                              "iat": 1793491200, "exp": 1793491500, **over})


def _ev(n: int, accepted: bool = True, rate: int = 2_000_000, milestone: int = 0, artifact: int | None = None) -> L.Evaluation:
    return L.Evaluation(BUYER, SELLER, f"{n:064x}", f"{n if artifact is None else artifact:040x}", "ab" * 32, milestone, accepted, rate)


def _log(*evs: L.Evaluation, month: int = 202610) -> E.Log:
    log = E.Log()
    assert E.ingest(log, (x for e in evs for x in E.from_evaluation(e, "record", month, f"tx:{e.artifact[-4:]}"))).ok
    return log


# -- ids ----------------------------------------------------------------------------------------------------------------
def test_an_id_is_what_the_event_is_never_how_or_when_it_arrived():
    a, b = list(E.from_evaluation(_ev(1), "record", 202610, "tx:one")), list(E.from_evaluation(_ev(1), "batch", 202611, "batch:x"))
    assert [e.id for e in a] == [e.id for e in b] and [e.kind for e in a] == ["evaluation", "acceptance"]
    assert ids.kind_of(a[0].id) == "evaluation" and a[1].id.startswith("acc_") and ids.kind_of(a[1].id) is None
    assert a[0].stated() == b[0].stated() and a[0].line() != b[0].line()
    assert list(E.from_evaluation(_ev(2), "record", 202610))[0].id != a[0].id
    assert [e.kind for e in E.from_evaluation(_ev(1, accepted=False), "record", 202610)] == ["evaluation"]


# -- duplicates across modes ----------------------------------------------------------------------------------------------
def test_one_evaluation_recorded_singly_and_inside_a_batch_is_counted_once_with_both_sources():
    log = E.Log()
    one = E.ingest(log, E.from_records([_ev(1).audience() + " 5sigOfTheSingleRecord"], "2026-10"))
    assert one.ok and len(one.added) == 2 and not one.duplicates
    b = L.batch([_ev(1), _ev(2)], 0, 202610)
    two = E.ingest(log, E.from_ledger(L.dump([b])))
    assert two.ok and len(two.duplicates) == 2 and sum(1 for e in two.added if e.first is None) == 2       # evaluation 2 and its acceptance are new
    d = next(x for x in two.duplicates if x["kind"] == "evaluation")
    assert [s["source"] for s in d["sources"]] == ["record", "batch"] and d["counted_at"] == 0
    assert d["sources"][0]["evidence"] == "tx:5sigOfTheSingleRecord" and d["sources"][1]["evidence"] == f"batch:{BUYER}:{SELLER}:202610.0:{b.root.hex()}"
    st = E.statement(log, 202610)
    assert st["evaluations"]["accepted"] == 2 and st["accepted_deliverables"] == 2 and st["repeats_not_counted"] == 2
    assert {x["id"] for x in log.dupes()} == {x["id"] for x in two.duplicates}
    assert E.read(log.text())[1] == []


def test_the_same_arrival_again_writes_nothing():
    log = _log(_ev(1))
    before = log.text()
    r = E.ingest(log, E.from_evaluation(_ev(1), "record", 202610, "tx:" + _ev(1).artifact[-4:]))
    assert r.ok and r.known == 2 and not r.added and log.text() == before


def test_one_id_with_different_content_is_a_conflict_refused_and_reported():
    log = _log(_ev(1))
    before = log.text()
    r = E.ingest(log, E.from_evaluation(_ev(1, accepted=False), "batch", 202610, "batch:b"))       # the same run, said to have been rejected
    assert not r.ok and not r.added and log.text() == before
    (c,) = r.conflicts
    assert c["id"] == log.events[0].id and c["differs"] == ["verdict"] and c["kept"]["source"] == "record" and c["refused"]["source"] == "batch"
    assert c["kept"]["verdict"] == "accepted" and c["refused"]["verdict"] == "rejected"


def test_ten_evaluations_of_one_deliverable_are_one_acceptance():
    log = E.Log()
    r = E.ingest(log, (x for a in range(10) for x in E.from_evaluation(_ev(1, artifact=100 + a), "record", 202610, f"tx:{a}")))
    st = E.statement(log, 202610)
    assert r.ok and st["evaluations"]["accepted"] == 10 and st["accepted_deliverables"] == 1 and len(r.duplicates) == 9
    other_price = E.ingest(log, E.from_evaluation(_ev(1, artifact=999, rate=5), "record", 202610, "tx:z"))
    assert [c["differs"] for c in other_price.conflicts] == [["amount"]]


def test_what_is_not_an_event_is_refused_in_words():
    log = E.Log()
    wrong_id = E.Event("evl_" + "0" * 24, "evaluation", "record", deliverable=ids.deliverable("o", 0), evaluation="evl_" + "1" * 24, verdict="accepted")
    r = E.ingest(log, [wrong_id, E.Event("x", "payment", "record"), E.Event(ids.invoice_line("s", "i", 1), "invoice_line", "fax", invoice_line=ids.invoice_line("s", "i", 1)),
                       E.correction("evl_" + "2" * 24, verdict="rejected")])
    assert not r.added and len(r.refused) == 4 and not log.events
    assert "evaluation id" in r.refused[0]["why"] and "not a kind" in r.refused[1]["why"] and "recording mode" in r.refused[2]["why"] and "not an event of this log" in r.refused[3]["why"]


# -- the chain ----------------------------------------------------------------------------------------------------------
def test_verify_finds_a_removed_a_reordered_and_an_edited_line():
    log = _log(_ev(1), _ev(2), _ev(3, accepted=False))
    lines = log.text().splitlines()
    assert len(lines) == 5 and E.read(log.text())[1] == []
    assert json.loads(lines[0])["prev"] == E.ZERO and json.loads(lines[1])["prev"] == hashlib.sha256(lines[0].encode()).hexdigest()
    removed = E.read("\n".join(lines[:2] + lines[3:]) + "\n")[1]
    assert removed and "removed, reordered or edited" in removed[0] and removed[0].startswith("Line 2 ")
    swapped = E.read("\n".join([lines[0], lines[2], lines[1], *lines[3:]]) + "\n")[1]
    assert swapped and swapped[0].startswith("Line 1 ")
    edited = E.read(log.text().replace('"amount":2000000', '"amount":9000000', 1))[1]
    assert edited and edited[0].startswith("Line 1 ") and "does not follow" in edited[0]
    assert "not written in the canonical form" in E.read(lines[0].replace('"ack":null,', '"ack": null,') + "\n")[1][0]
    assert "not an event" in E.read(lines[0] + "\nnot json\n" + lines[1] + "\n")[1][0]


def test_lines_cut_from_the_end_are_found_only_with_the_head_you_kept():
    log = _log(_ev(1), _ev(2))
    cut = "\n".join(log.text().splitlines()[:2]) + "\n"
    assert E.read(cut)[1] == []                                                 # a shorter chain is still a chain
    assert "removed from the end" in E.read(cut, head=log.head)[1][0]
    assert "2 lines came after it" in E.read(log.text(), head=log.hashes[1])[1][0]


def test_the_file_is_only_ever_appended_to(tmp_path):
    path = tmp_path / "log.jsonl"
    log = _log(_ev(1))
    assert log.write(path) == 2 and log.write(path) == 0
    first = path.read_bytes()
    again = E.load(path)
    E.ingest(again, E.from_evaluation(_ev(2), "batch", 202610, "batch:b"))
    assert again.write(path) == 2 and path.read_bytes().startswith(first) and len(E.load(path).events) == 4
    path.write_bytes(path.read_bytes().replace(b'"supplier":"555000"', b'"supplier":"555001"', 1))
    with pytest.raises(L.Bad, match="does not check"):
        E.load(path)


# -- acknowledgements ---------------------------------------------------------------------------------------------------
def test_an_acknowledgement_is_a_signed_token_for_the_head(github):
    key, jwks = github
    log = _log(_ev(1), _ev(2))
    head, token = log.head, _ack(key, log, SELLER)
    assert E.ack_audience(SELLER, 3, head) == f"knosm:ack:{SELLER}:3:{head}"
    r = E.ingest(log, [E.acknowledgement(token)], jwks)
    assert r.ok and r.added[0].kind == "acknowledgement" and log.acknowledged() == {str(SELLER): 3}
    assert E.ingest(log, [E.acknowledgement(token)], jwks).known == 1
    assert E.read(log.text(), jwks)[1] == [] and E.read(log.text())[1] == []
    E.ingest(log, E.from_evaluation(_ev(3), "record", 202610, "tx:3"))            # the log goes on past the acknowledged head
    st = E.statement(log, 202610)
    assert st["acknowledged"] == {"upto": {str(SELLER): 3}, "covers_month": []}
    E.ingest(log, [E.acknowledgement(_ack(key, log, BUYER))], jwks)
    assert E.statement(log, 202610)["acknowledged"]["covers_month"] == [str(BUYER)]


def test_an_acknowledgement_nobody_signed_for_this_log_is_refused(github):
    key, jwks = github
    log = _log(_ev(1))
    good = _ack(key, log, SELLER)
    for token, keys, why in ((good, None, "needs the issuer's keys"),
                             (Key("a stranger").token("k1", iss=L.GITHUB_ISSUER, aud=E.ack_audience(SELLER, 1, log.head), repository_owner_id=str(SELLER)), jwks, "signature"),
                             (_ack(key, log, SELLER, repository_owner_id=str(BUYER)), jwks, "from a repository of GitHub id"),
                             (_ack(key, log, SELLER, iss="https://example.invalid"), jwks, "not issued by"),
                             (_ack(key, log, SELLER, aud=E.ack_audience(SELLER, 1, "ab" * 32)), jwks, "something in the acknowledged range was changed"),
                             (_ack(key, log, SELLER, aud=E.ack_audience(SELLER, 7, log.head)), jwks, "not before it"),
                             (good[:-6] + "AAAAAA", jwks, "signature")):
        try:                                                                      # what the token says of itself is refused on reading it, the rest on ingest
            said = E.ingest(log, [E.acknowledgement(token)], keys).refused[0]["why"]
        except L.Bad as bad:
            said = str(bad)
        assert why in said and len(log.events) == 2, why
    with pytest.raises(L.Bad, match="signed for something else"):
        E.acknowledgement(_ack(key, log, SELLER, aud=f"knosm:close:{BUYER}:{SELLER}:202610:{'ab' * 32}"))


def test_an_acknowledged_range_rewritten_with_every_hash_redone_is_still_found(github):
    key, jwks = github
    log = _log(_ev(1), _ev(2))
    E.ingest(log, [E.acknowledgement(_ack(key, log, SELLER))], jwks)
    forged = E.Log()                                                              # whoever holds the file changes an amount and redoes the whole chain
    for e in log.events:
        forged.append(E.replace(e, amount=1) if e.seq == 0 else e)
    assert forged.head != log.head
    said = E.read(forged.text(), jwks)[1]
    assert any("something in the acknowledged range was changed" in s and f"GitHub id {SELLER}" in s for s in said)
    assert any("acknowledged range was changed" in s for s in E.read(forged.text())[1])       # found without keys too: the token names the head


# -- corrections --------------------------------------------------------------------------------------------------------
def test_a_correction_is_an_event_and_nothing_is_rewritten(github):
    key, jwks = github
    log = _log(_ev(1), _ev(2))
    E.ingest(log, [E.acknowledgement(_ack(key, log, SELLER))], jwks)
    before, acc = log.text(), log.events[1]
    assert E.statement(log, 202610)["accepted_deliverables"] == 2
    fix = E.correction(acc.id, verdict="disputed", reason="the buyer contests it", month=202611)
    r = E.ingest(log, [fix])
    assert r.ok and log.text().startswith(before) and log.events[1] == acc and log.state(acc)[0] == "disputed"
    assert E.statement(log, 202610)["accepted_deliverables"] == 1 and E.statement(log, 202611)["corrections"] == [5]
    assert E.ingest(log, [fix]).known == 1
    E.ingest(log, [E.correction(acc.id, verdict="accepted", reason="resolved")])    # the latest correction is what holds
    assert log.state(acc)[0] == "accepted" and E.statement(log, 202610)["accepted_deliverables"] == 2
    E.ingest(log, [E.correction(log.events[2].id, void=True, reason="entered by mistake")])
    st = E.statement(log, 202610)
    assert st["voided"] == 1 and st["evaluations"]["accepted"] == 1 and E.read(log.text(), jwks)[1] == []
    assert not E.ingest(log, [E.correction(fix.id, void=True)]).ok                  # a correction is corrected by another one of the event, not of itself


# -- statements ---------------------------------------------------------------------------------------------------------
def _invoiced() -> E.Log:
    log = _log(_ev(1), _ev(2, accepted=False), _ev(3), _ev(4))
    d = [ids.deliverable(f"{n:064x}", 0) for n in range(6)]
    lines = [E.invoice_line("555000", "INV-7", 1, "import", deliverable=d[1], month=202610, amount=2_000_000, unit="units"),      # agreed
             E.invoice_line("555000", "INV-7", 2, "import", deliverable=d[2], month=202610, amount=2_000_000, unit="units"),      # rejected: disputed
             E.invoice_line("555000", "INV-7", 3, "import", deliverable=d[3], month=202610, amount=2_500_000, unit="units"),      # accepted at another price
             E.invoice_line("555000", "INV-7", 4, "import", deliverable=d[5], month=202610, amount=1_000_000, unit="units"),      # nothing known
             E.invoice_line("555000", "INV-7", 5, "import", deliverable=d[1], month=202610, amount=2_000_000, unit="units"),      # billed twice
             E.invoice_line("555000", "INV-8", 1, "import", deliverable=d[4], month=202611, amount=2_000_000, unit="units"),
             E.invoice_line("555000", "INV-9", 1, "import", deliverable=d[4], month=202612, amount=2_000_000, unit="units")]      # billed again a month later
    assert E.ingest(log, lines).ok
    return log


def test_a_statement_says_agreed_disputed_duplicate_or_insufficient_evidence_for_each_line():
    log = _invoiced()
    st = E.statement(log, "2026-10")
    assert [x["state"] for x in st["invoice_lines"]] == ["agreed", "disputed", "disputed", "insufficient_evidence", "duplicate"]
    assert set(st["line_states"]) == set(ids.LINE_STATES) and st["line_states"] == {"agreed": 1, "disputed": 2, "duplicate": 1, "insufficient_evidence": 1}
    assert st["amounts"]["units"] == {"billed": 9_500_000, "agreed": 2_000_000, "disputed": 4_500_000, "duplicate": 2_000_000, "insufficient_evidence": 1_000_000, "settled": 0}
    assert "accepted at 2000000 units" in st["invoice_lines"][2]["why"] and "rejected" in st["invoice_lines"][1]["why"]
    assert [x["state"] for x in E.statement(log, 202611)["invoice_lines"]] == ["agreed"]
    later = E.statement(log, 202612)["invoice_lines"]                              # the other month's line is found by the deliverable, not by reading that month
    assert [x["state"] for x in later] == ["duplicate"] and "already bills this deliverable" in later[0]["why"]
    assert E.statement(log, 202610) == st and E.statement(log, 202610, "nobody")["invoice_lines"] == []
    body = {k: v for k, v in st.items() if k != "sha256"}
    assert st["sha256"] == hashlib.sha256(L.canon(body).encode()).hexdigest() and st["head"] == log.head


def test_a_month_reads_its_own_lines_and_not_the_log():
    log = E.Log()
    for m in range(1, 13):
        E.ingest(log, (x for n in range(40) for x in E.from_evaluation(_ev(m * 1000 + n), "batch", 202600 + m, f"batch:{m}")))

    class Counting(list):
        read = 0

        def __getitem__(self, i):
            Counting.read += 1
            return super().__getitem__(i)

    log.events = Counting(log.events)
    st = E.statement(log, 202606)
    assert st["evaluations"]["accepted"] == 40 and len(log.events) == 960 and Counting.read == len(log.by_month[202606]) == 80


# -- the other modes ----------------------------------------------------------------------------------------------------
def test_a_shadow_statement_becomes_invoice_lines_and_evaluations():
    rows = [{"line": 1, "pr": "Acme/app#7", "amount": "120.00", "supplier": "Initech", "class": "clean", "merge_commit": "a" * 40, "duplicate_of": None},
            {"line": 2, "pr": "acme/app#8", "amount": "80.50", "supplier": "Initech", "class": "failed", "merge_commit": "b" * 40, "duplicate_of": None},
            {"line": 3, "pr": "acme/app#7", "amount": "120.00", "supplier": "Initech", "class": "duplicate", "merge_commit": "", "duplicate_of": 1},
            {"line": 4, "pr": "", "amount": "10.00", "supplier": "Initech", "class": "unreadable", "merge_commit": "", "duplicate_of": None}]
    shadow = {"kind": "knos-shadow-statement", "version": 1, "supplier": "Initech", "lines": rows}
    found = list(E.from_shadow(shadow, "INV-2026-10", "2026-10"))
    assert [e.kind for e in found] == ["invoice_line", "evaluation", "invoice_line", "evaluation", "invoice_line", "invoice_line"]
    assert found[0].id == ids.invoice_line("Initech", "INV-2026-10", 1) and found[0].amount == 12000 and found[2].amount == 8050 and found[0].unit == "cents"
    assert found[0].deliverable == found[4].deliverable == ids.deliverable("github:acme/app", "7") and found[5].deliverable == ""
    log = E.Log()
    assert E.ingest(log, found).ok and E.ingest(log, E.from_shadow(shadow, "INV-2026-10", "2026-10")).known == 6
    assert [x["state"] for x in E.statement(log, 202610)["invoice_lines"]] == ["agreed", "disputed", "duplicate", "insufficient_evidence"]
    assert E.statement(log, 202610)["amounts"]["cents"]["billed"] == 33050


def test_an_audit_exports_paid_lines_become_settlements_once():
    rows = [{"kind": "paid", "billing_key": "OrderAddr:FundTx:0", "paid_units": "1500000", "currency": "USDC", "transaction": "PayTx1", "supplier_ids": "555000", "date": "2026-10-03"},
            {"kind": "open", "billing_key": "", "paid_units": "0", "currency": "USDC", "transaction": "FundTx", "supplier_ids": "", "date": "2026-10-01"},
            {"kind": "refunded", "billing_key": "", "paid_units": "0", "currency": "USDC", "transaction": "RefTx", "supplier_ids": "", "date": "2026-10-04"}]
    (s,) = list(E.from_audit(rows))
    dlv = ids.deliverable("OrderAddr:FundTx", "0")
    assert s.kind == "settlement" and s.id == ids.settlement(dlv, "chain", "PayTx1") and s.amount == 1_500_000 and s.month == 202610 and s.source == "settle"
    log = E.Log()
    E.ingest(log, [s])
    again = E.ingest(log, [E.settlement(dlv, "chain", "PayTx1", 1_500_000, "USDC", "import", supplier="555000", month=202610, evidence="a bank file")])
    assert len(again.duplicates) == 1 and E.statement(log, 202610)["amounts"]["USDC"]["settled"] == 1_500_000


def test_the_import_mode_takes_short_forms_and_whole_events():
    dlv = ids.deliverable("order", 1)
    lines = [json.dumps({"evaluation": {"deliverable": dlv, "artifact": "c0ffee", "policy": "p1", "evaluator": "ci", "run": 4, "verdict": "passed"}, "supplier": "s", "month": "2026-10"}),
             json.dumps({"invoice_line": {"supplier": "s", "invoice": "A1", "line": 1}, "deliverable": dlv, "amount": 500, "unit": "cents", "month": 202610}),
             json.dumps({"settlement": {"deliverable": dlv, "method": "bank", "reference": "R-1", "amount": 500, "unit": "cents"}, "month": "2026-10"}),
             json.dumps({"correction": {"of": ids.evaluation(dlv, "c0ffee", "p1", "ci", 4), "verdict": "disputed", "reason": "contested"}})]
    log = E.Log()
    assert E.ingest(log, E.from_import(lines)).ok and [e.kind for e in log.events] == ["evaluation", "invoice_line", "settlement", "correction"]
    assert log.events[0].verdict == "accepted" and E.statement(log, 202610)["invoice_lines"][0]["state"] == "disputed"
    assert E.ingest(E.Log(), E.from_import(log.text().splitlines())).ok              # a log's own lines go in as they are
    with pytest.raises(L.Bad, match="line 1 is not an event to import"):
        list(E.from_import(['{"evaluation": {"deliverable": "x"}}']))


# -- export -------------------------------------------------------------------------------------------------------------
def test_an_export_is_rebuilt_from_its_log_and_any_changed_file_is_found(github):
    key, jwks = github
    log = _invoiced()
    E.ingest(log, [E.acknowledgement(_ack(key, log, SELLER))], jwks)
    files = E.export_files(log, jwks, refused='{"why":"x"}\n')
    assert {"events.jsonl", "acknowledgements.json", "jwks.json", "duplicates.json", "index.json", "manifest.json", "refused.jsonl",
            "statements/202610.json", "statements/202611.json", "statements/202612.json"} == set(files)
    assert [k["kid"] for k in json.loads(files["jwks.json"])["keys"]] == ["k1"] and json.loads(files["manifest.json"])["head"] == log.head
    assert json.loads(files["index.json"])["by_month"]["202611"] == log.by_month[202611]
    assert E.check_export(files) == [] and E.export_files(log, jwks, refused='{"why":"x"}\n') == files
    st = json.loads(files["statements/202610.json"])
    st["line_states"]["agreed"] = 5
    assert E.check_export({**files, "statements/202610.json": (L.canon(st) + "\n").encode()}) == ["statements/202610.json is not what the log gives: it was changed, or the log was."]
    cut = "".join(x + "\n" for x in files["events.jsonl"].decode().splitlines()[:-1]).encode()
    assert any("removed from the end" in s for s in E.check_export({**files, "events.jsonl": cut}))
    assert any("signature" in s for s in E.check_export({**files, "jwks.json": b'{"keys":[]}\n'}))
    assert E.check_export({"events.jsonl": b""}) == ["This is not an export as `knos events export` writes one."]


# -- the command line ---------------------------------------------------------------------------------------------------
def test_the_commands_ingest_verify_ack_dupes_and_export(tmp_path, github):
    typer = pytest.importorskip("typer")
    from typer.testing import CliRunner
    key, jwks = github
    app, help_lines = typer.Typer(), []
    E.register(app, help_lines)

    @app.command("other")
    def other() -> None: ...
    run, log = CliRunner(), tmp_path / "events.jsonl"
    (tmp_path / "singles.txt").write_text(_ev(1).audience() + " Sig1\n", encoding="utf-8")
    (tmp_path / "ledger.jsonl").write_text(L.dump([L.batch([_ev(1), _ev(2)], 0, 202610)]), encoding="utf-8")
    (tmp_path / "wrong.jsonl").write_text(L.dump([L.batch([_ev(1, accepted=False)], 1, 202610)]), encoding="utf-8")
    assert help_lines[0][0] == "events"
    a = run.invoke(app, ["events", "ingest", str(log), str(tmp_path / "singles.txt"), "--from", "record", "--month", "2026-10"])
    assert a.exit_code == 0 and a.output.startswith("2 counted, 0 already counted")
    b = run.invoke(app, ["events", "ingest", str(log), str(tmp_path / "ledger.jsonl"), "--from", "batch", "--json"])
    assert b.exit_code == 0 and json.loads(b.output)["counted"] == 2 and len(json.loads(b.output)["duplicates"]) == 2
    c = run.invoke(app, ["events", "ingest", str(log), str(tmp_path / "wrong.jsonl"), "--from", "batch"])
    assert c.exit_code == 1 and "conflict" in c.output and "verdict differ" in c.output and (tmp_path / "events.jsonl.refused.jsonl").exists()
    v = run.invoke(app, ["events", "verify", str(log)])
    assert v.exit_code == 0 and "6 lines check" in v.output and "by nobody yet" in v.output
    asked = run.invoke(app, ["events", "ack", str(log), "--as", str(SELLER)])
    book = E.load(log)
    assert asked.output.strip() == E.ack_audience(SELLER, 5, book.head)
    (tmp_path / "seller.jwt").write_text(_ack(key, book, SELLER), encoding="ascii")
    (tmp_path / "github.json").write_text(json.dumps(jwks), encoding="utf-8")
    k = run.invoke(app, ["events", "ack", str(log), "--token", str(tmp_path / "seller.jwt"), "--keys", str(tmp_path / "github.json")])
    assert k.exit_code == 0 and f"GitHub id {SELLER} acknowledged lines 0 to 5" in k.output
    assert [x["kid"] for x in json.loads((tmp_path / "events.jsonl.jwks.json").read_text(encoding="utf-8"))["keys"]] == ["k1"]
    v = run.invoke(app, ["events", "verify", str(log), "--head", E.load(log).head])
    assert v.exit_code == 0 and f"GitHub id {SELLER} up to line 5" in v.output and "NOT checked" not in v.output
    d = run.invoke(app, ["events", "dupes", str(log)])
    assert d.exit_code == 0 and "record tx:Sig1; batch batch:" in d.output and "2 events arrived more than once" in d.output and "1 arrivals were refused" in d.output
    s = run.invoke(app, ["events", "statement", str(log), "--month", "2026-10"])
    assert s.exit_code == 0 and json.loads(s.output)["accepted_deliverables"] == 2
    x = run.invoke(app, ["events", "export", str(log), "--out", str(tmp_path / "out")])
    assert x.exit_code == 0 and (tmp_path / "out" / "statements" / "202610.json").exists()
    assert run.invoke(app, ["events", "verify", str(tmp_path / "out")]).exit_code == 0
    log.write_bytes(log.read_bytes().replace(b'"verdict":"accepted"', b'"verdict":"rejected"', 1))
    bad = run.invoke(app, ["events", "verify", str(log)])
    assert bad.exit_code == 1 and "removed, reordered or edited" in bad.output


def test_the_measurement_script_runs_on_a_small_log():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("events_bench", Path(__file__).resolve().parent.parent / "scripts" / "events_bench.py")
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    got = bench.measure(400)
    assert got["events"] == 400 and got["counted"] + got["repeats"] == 400 and got == {**bench.measure(400), "seconds": got["seconds"]}
