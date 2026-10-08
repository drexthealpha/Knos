"""What a paid record lookup adds to the free file (src/knos/record_answer.py, docs/RECORD.md section 5): a signature
with an expiry that is checked offline, a summary computed the same way for every supplier, and the supplier's history
only to a reader the supplier granted. tests/test_record_api.py serves it against a funded order."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("solders")

from solders.keypair import Keypair  # noqa: E402

from knos import events, ids, record_answer as ra, record_page  # noqa: E402
from knos.proof import history  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "docs" / "records"
T = "ab" * 32
OPERATOR, SUPPLIER, READER, OTHER = (Keypair.from_seed(bytes([n]) * 32) for n in (81, 82, 83, 84))
NOW = 1_790_000_000


class Memory:
    def __init__(self):
        self.held: dict = {}

    def put(self, category, name, body):
        self.held[category, name] = dict(body)

    def rows(self, category):
        return [(n, b) for (c, n), b in sorted(self.held.items()) if c == category]


def _log() -> events.Log:
    """Supplier 77: two accepted, one rejected, one disputed, one accepted then voided by a correction."""
    log, out = events.Log(), []
    for key, verdict, month in ((1, "accepted", 202607), (2, "accepted", 202608), (3, "rejected", 202608), (4, "accepted", 202609), (5, "disputed", 202609)):
        dlv = ids.deliverable("order-a", key)
        ev = events.evaluation(dlv, f"commit{key}", T, "repository@v1", key, verdict, "record", supplier="77", month=month, evidence=f"tx:sig{key}")
        out.append(ev)
        if verdict == "accepted":
            out.append(events.acceptance(dlv, "record", supplier="77", month=month, evaluation=ev.id, evidence=f"tx:sig{key}"))
    assert not events.ingest(log, out).conflicts
    voided = next(e for e in log.events if e.kind == "acceptance" and e.deliverable == ids.deliverable("order-a", 4))
    events.ingest(log, [events.correction(voided.id, void=True, reason="reverted in warranty", month=202609)])
    return log


def _memory() -> Memory:
    store = Memory()
    history.supplier_event(store, "acme/app", "vendor-x", 5, "accepted", T, at=1.0)
    history.supplier_event(store, "acme/app", "vendor-x", 6, "rejected", T, at=2.0)
    history.appeal_outcome(store, "acme/app", "ap1", "accepted", "vendor-x", 6, reason="the test was mine", terms=T, at=3.0)
    history.supplier_event(store, "globex/site", "vendor-x", 2, "accepted", T, at=4.0)
    history.supplier_event(store, "acme/app", "someone-else", 9, "accepted", T, at=5.0)
    return store


def _record() -> dict:
    return record_page.build("vendor-x", log=_log(), supplier_ids=("77",), store=_memory(), repos=("acme/app", "globex/site"), as_of="2026-10-01")


def _past() -> dict:
    times = [{"deliverable": "a", "delivered": 0, "accepted": 600}, {"deliverable": "b", "delivered": 100, "accepted": 100 + 7200},
             {"deliverable": "c", "delivered": 0, "accepted": 3 * 86_400}]
    return ra.history("vendor-x", log=_log(), supplier_ids=("77",), store=_memory(), repos=("acme/app", "globex/site"), times=times, as_of="2026-10-01")


def _reply(doc=None, **kw) -> dict:
    doc = doc or _record()
    given = {"reader": str(READER.pubkey()), "read_time": NOW - 2, "slot": 4242, "produced": NOW, "key": OPERATOR, **kw}
    return {"record": doc, "answer": ra.answer(doc, **given)}


def test_the_summary_is_the_same_arithmetic_for_every_supplier_with_the_indexs_interval_and_no_score():
    s = ra.summary(_record())
    o = s["orders"]
    assert s["score"] is None and "Not a rating of defect-free work" in s["note"]
    assert (o["accepted"]["k"], o["accepted"]["n"], o["rejected"]["k"], o["disputed"]["k"]) == (2, 4, 1, 1)
    assert (o["reverted"]["k"], o["reverted"]["n"], o["overturned"]["k"], o["overturned"]["n"]) == (1, 5, 1, 1)
    assert o["accepted"]["share"] == 0.5 and o["accepted"]["ci95"] == ra.wilson(2, 4) == [0.15, 0.85]
    assert ra.wilson(0, 0) is None and ra.summary(record_page.build("nobody"))["orders"]["accepted"] == {"k": 0, "n": 0, "of": "deliverables with a verdict", "share": None, "ci95": None}
    # every committed record gets the same keys, and the public interval is the one the index published
    files = sorted(RECORDS.glob("*.json"))
    assert files
    shapes = set()
    for path in files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        got = ra.summary(doc)
        shapes.add(json.dumps({k: sorted(v) if isinstance(v, dict) else None for k, v in got.items()}, sort_keys=True))
        if doc["public"] and doc["public"]["sample"]:
            assert got["public"]["failed_at_merge"]["ci95"] == doc["public"]["ci95"], path.name
            assert got["public"]["failed_at_merge"]["n"] == doc["public"]["sample"]
    assert len(shapes) == 1


def test_the_history_holds_what_the_free_file_lacks():
    past, free = _past(), _record()
    f = past["fields"]
    assert tuple(f) == ra.FIELDS and ra.check_history(past, "vendor-x") is None and ra.check_history(past, "other") is not None
    assert f["per_buyer"]["by_repository"] == [
        {"buyer": "acme", "repository": "acme/app", "accepted": 1, "rejected": 1, "appealed": 1, "overturned": 1},
        {"buyer": "globex", "repository": "globex/site", "accepted": 1, "rejected": 0, "appealed": 0, "overturned": 0}]
    assert [m["month"] for m in f["per_buyer"]["by_month"]] == ["2026-07", "2026-08", "2026-09"]
    assert f["disputes"]["appeals"] == [{"id": "ap1", "repository": "acme/app", "pull_request": 6, "state": "accepted", "reason": "the test was mine", "why": "", "at": 3}]
    assert [d["deliverable"] for d in f["disputes"]["disputed"]] == [ids.deliverable("order-a", 5)]
    assert len(f["corrections"]) == 1 and f["corrections"][0]["void"] is True and f["corrections"][0]["reason"] == "reverted in warranty"
    assert f["time_to_accept"] == {"n": 3, "unit": "seconds", "min": 600, "p50": 7200, "p90": 259_200, "max": 259_200,
                                   "buckets": {"under_1_hour": 1, "under_1_day": 1, "under_7_days": 1, "7_days_or_more": 0}}
    assert ra.history("vendor-x", as_of="2026-10-01")["fields"]["time_to_accept"]["n"] == 0
    assert past == _past()                                             # the same inputs, the same bytes
    text = record_page.canon(free)
    assert "the test was mine" not in text and "by_repository" not in text and "time_to_accept" not in text
    tampered = {**past, "fields": {**f, "corrections": []}}
    assert ra.check_history(tampered) == "the history does not hash to the sha256 it states"


def test_a_signed_answer_is_fresh_then_stale_and_an_unsigned_or_changed_one_is_told_apart():
    reply = _reply()
    a = reply["answer"]
    assert a["key"] == str(OPERATOR.pubkey()) and a["expires"] == NOW + ra.TTL and a["read"] == {"time": NOW - 2, "slot": 4242, "source": a["read"]["source"]}
    assert a["root"]["record_sha256"] == reply["record"]["sha256"] and a["availability"]["uptime"] == "none" and "zero" in a["budget"]
    assert ra.verify(reply, NOW + 10)["state"] == "fresh" and ra.verify(reply, NOW + 10, str(OPERATOR.pubkey()))["state"] == "fresh"
    assert ra.verify(reply, NOW + ra.TTL)["state"] == "fresh"
    late = ra.verify(reply, NOW + ra.TTL + 1)
    assert late["state"] == "stale" and "expired 1 seconds ago" in late["why"]
    assert ra.verify(reply, NOW + 10, str(OTHER.pubkey()))["state"] == "invalid"
    assert ra.verify(reply, NOW - 3600)["state"] == "invalid"                        # an answer from the future
    unsigned = _reply(key=None)
    assert unsigned["answer"]["signature"] is None and ra.verify(unsigned, NOW + 10)["state"] == "unsigned"
    assert ra.verify(json.loads((RECORDS / "codex.json").read_text(encoding="utf-8")), NOW)["state"] == "unsigned"      # the free file
    assert ra.verify({"nothing": 1}, NOW)["state"] == "invalid"
    # a longer life, a later read, another reader, a dropped signature key: none passes
    for change in ({"expires": NOW + 10 ** 6}, {"read": {**a["read"], "slot": 9}}, {"reader": str(OTHER.pubkey())}, {"key": str(OTHER.pubkey())}):
        assert ra.verify({**reply, "answer": {**a, **change}}, NOW + 10)["state"] == "invalid", change
    # a signed answer moved onto another record, and a summary that is not the record's
    other = json.loads((RECORDS / "codex.json").read_text(encoding="utf-8"))
    assert ra.verify({**reply, "record": other}, NOW + 10)["state"] == "invalid"
    forged = ra.answer(reply["record"], reader="r", read_time=NOW, slot=None, produced=NOW, key=None)
    forged["summary"] = {**forged["summary"], "score": 99}
    assert ra.verify({"record": reply["record"], "answer": forged}, NOW)["state"] == "invalid"
    # someone who strips the signature gets "unsigned", never "fresh"
    assert ra.verify({**reply, "answer": {**a, "key": None, "signature": None}}, NOW + 10)["state"] == "unsigned"
    assert all(ra.lines(ra.verify(r, NOW + 10)) for r in (reply, unsigned))


def test_history_goes_only_to_the_reader_the_supplier_granted_and_only_the_fields_it_named():
    doc, past, me, key = _record(), _past(), str(READER.pubkey()), str(SUPPLIER.pubkey())
    none = _reply(doc, past=past)["answer"]
    assert all(h == {"granted": False, "state": "not granted", "what": ra.FIELD_WORDS[f]} for f, h in none["history"].items())
    assert "the test was mine" not in json.dumps(none) and none["root"]["history_sha256"] is None and none["grant"]["refused"] == "no grant was shown"
    g = ra.grant(SUPPLIER, "vendor-x", me, ["disputes", "corrections"], NOW - 60, NOW + 86_400)
    assert ra.check_grant(g, "vendor-x", me, key, NOW) == (["corrections", "disputes"], None)
    for shown, supplier, reader, held, at, why in (
            (g, "vendor-x", str(OTHER.pubkey()), key, NOW, "another reader"), (g, "codex", me, key, NOW, "another supplier"),
            (g, "vendor-x", me, key, NOW + 86_401, "not in force"), (g, "vendor-x", me, key, NOW - 61, "not in force"),
            (g, "vendor-x", me, None, NOW, "holds no key for the supplier"), (g, "vendor-x", me, str(OTHER.pubkey()), NOW, "not signed by the supplier's key"),
            ({**g, "fields": list(ra.FIELDS)}, "vendor-x", me, key, NOW, "not signed by the supplier's key"),
            (ra.grant(OTHER, "vendor-x", me, ["disputes"], NOW - 60, NOW + 60), "vendor-x", me, key, NOW, "not signed by the supplier's key"),
            (None, "vendor-x", me, key, NOW, "no grant was shown")):
        got = ra.check_grant(shown, supplier, reader, held, at)
        assert got[0] == [] and why in got[1], why
    with pytest.raises(ValueError):
        ra.grant(SUPPLIER, "vendor-x", me, ["everything"], NOW, NOW + 1)
    fields, why = ra.check_grant(g, "vendor-x", me, key, NOW)
    reply = _reply(doc, past=past, granted=fields, grant_doc=g)
    h = reply["answer"]["history"]
    assert h["disputes"]["data"] == past["fields"]["disputes"] and h["corrections"]["state"] == "released"
    assert h["per_buyer"]["state"] == h["time_to_accept"]["state"] == "not granted" and "data" not in h["per_buyer"]
    assert reply["answer"]["root"]["history_sha256"] == past["sha256"] and reply["answer"]["grant"]["sha256"] == ra.sha(g)
    assert ra.verify(reply, NOW + 1)["state"] == "fresh"
    assert _reply(doc, granted=fields, grant_doc=g)["answer"]["history"]["disputes"]["state"] == "nothing on file"
    assert "never pays" in reply["answer"]["who_pays"]


def test_the_commands_verify_grant_and_write_the_history(tmp_path, capsys):
    typer = pytest.importorskip("typer")
    from typer.testing import CliRunner

    from knos import badge, record_api
    app = typer.Typer()
    badge.register(app)
    run = CliRunner()
    key = tmp_path / "supplier.json"
    key.write_text(json.dumps(list(bytes(SUPPLIER))), encoding="utf-8")
    assert ra.load_key(key).pubkey() == SUPPLIER.pubkey()
    out = tmp_path / "g.json"
    done = run.invoke(app, ["record", "grant", "vendor-x", "--reader", str(READER.pubkey()), "--field", "disputes", "--key", str(key), "--days", "7",
                            "--at", str(NOW), "--out", str(out)])
    assert done.exit_code == 0, done.output
    g = json.loads(out.read_text(encoding="utf-8"))
    assert ra.check_grant(g, "vendor-x", str(READER.pubkey()), str(SUPPLIER.pubkey()), NOW + 7 * 86_400)[0] == ["disputes"]
    log_path = tmp_path / "events.jsonl"
    events.record(log_path, list(_log().events))
    done = run.invoke(app, ["record", "history", "vendor-x", "--events", str(log_path), "--id", "77", "--as-of", "2026-10-01", "--out", str(tmp_path / "h")])
    assert done.exit_code == 0, done.output
    past = json.loads((tmp_path / "h" / "vendor-x.history.json").read_text(encoding="utf-8"))
    assert ra.check_history(past, "vendor-x") is None and len(past["fields"]["corrections"]) == 1
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps(_reply()), encoding="utf-8")
    assert run.invoke(app, ["record", "verify", str(reply), "--at", str(NOW + 5), "--operator", str(OPERATOR.pubkey())]).exit_code == 0
    assert run.invoke(app, ["record", "verify", str(reply), "--at", str(NOW + ra.TTL + 5)]).exit_code == 1
    assert ra.main(["verify", str(reply), "--at", str(NOW + ra.TTL + 5)]) == 1 and "Stale" in capsys.readouterr().out
    reply.write_text(json.dumps(_reply(key=None)), encoding="utf-8")
    assert ra.main(["verify", str(reply), "--at", str(NOW), "--json"]) == 1 and json.loads(capsys.readouterr().out)["state"] == "unsigned"
    # knos record serve --health reaches the server's own command with its own options
    got: list = []
    import pytest as _p
    mp = _p.MonkeyPatch()
    try:
        mp.setattr(record_api, "main", lambda argv=None: got.append(argv) or 0)
        assert run.invoke(app, ["record", "serve", "--health"]).exit_code == 0
        assert run.invoke(app, ["record", "serve", "offer.json", "--key", "k.json", "--memory", "m"]).exit_code == 0
    finally:
        mp.undo()
    assert got == [["--health"], ["offer.json", "--key", "k.json", "--memory", "m"]]


class Clock:
    """A chain that answers the two calls health makes."""
    def __init__(self, ok=True):
        self.ok = ok

    def now(self):
        if not self.ok:
            raise RuntimeError("the cluster's clock could not be read")
        return NOW

    def account(self, _address):
        return (777).to_bytes(8, "little") + bytes(24) + NOW.to_bytes(8, "little") if self.ok else None


def test_health_says_whether_it_can_answer_whether_it_signs_and_that_nothing_is_promised(tmp_path):
    from knos import record_api
    up = record_api.Server({}, Clock(), RECORDS, key=OPERATOR, ttl=120)
    status, _h, body = up.handle("/health", {})
    assert status == 200 and body["ok"] and body["signing"] and body["key"] == str(OPERATOR.pubkey()) and body["chain"] == {"ok": True, "time": NOW, "slot": 777}
    assert body["ttl_seconds"] == 120 and body["promise"]["uptime"] == "none" and "promises nothing" in body["promise"]["words"]
    assert body["records"] == len(list(RECORDS.glob("*.json"))) and body["counts_survive_restart"] is False
    for down in (record_api.Server({}, Clock(False), RECORDS), record_api.Server({}, Clock(), tmp_path)):
        status, _h, body = down.handle("/health", {})
        assert status == 503 and not body["ok"] and body["signing"] is False
    # an operator may state its own promise in the offer; the default is none
    mine = record_api.Server({"availability": {"uptime": "99% a month", "words": "Ours."}}, Clock(), RECORDS)
    assert mine.health()["promise"]["uptime"] == "99% a month" and mine.health()["promise"]["support"] == "none"


def test_the_document_sets_the_free_file_beside_the_paid_answer_and_budgets_no_revenue():
    text = (ROOT / "docs" / "RECORD.md").read_text(encoding="utf-8")
    for needle in ("| | the free file | the paid answer |", "budget: zero revenue until someone buys it", "knos record verify", "knos record grant",
                   "knos record serve --health", "not granted", "Not a rating of defect-free work", "never pays", ra.ANSWER, ra.GRANT, ra.HISTORY):
        assert needle in text, needle
    for f in ra.FIELDS:
        assert f"`{f}`" in text, f
    assert "nothing the free file lacks" not in text
    page = (ROOT / "web" / "supplier_record.js").read_text(encoding="utf-8")
    assert 'data-sr="built"' in page and "Unsigned" in page
