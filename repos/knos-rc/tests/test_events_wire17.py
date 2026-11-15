"""The one log of events, wired under every recording mode: record (the relay), batch (`knos meter batch`), settle
(`knos audit export`) and shadow (`knos shadow`). Each writes to the log only when one is named (`--events`, or
KNOS_EVENTS), after its own record is made, and never fails because of it. Two writers are kept apart by a lock file.
Then the same evaluation by two modes and one deliverable invoiced twice: counted once, billed once, and
`knos statement make` says the same from the log."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from knos import cli, shadow, statement
from knos import events as E
from test_audit import ACME, month, world  # noqa: F401 - `world` is a fixture
from test_events import _ev
from test_shadow import BOOK

SRC = str(Path(__file__).resolve().parents[1] / "src")
WRITER = """
import sys
from pathlib import Path
from knos import events as E, ledger as L
path, who, n = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
print("ready", flush=True)
sys.stdin.readline()                        # both writers are started, then both are let go
for i in range(n):
    e = L.Evaluation(424242, 555000, f"{who * 1000 + i:064x}", f"{i:040x}", "ab" * 32, 0, False, 5)
    r = E.record(path, E.from_evaluation(e, "record", 202610, f"tx:{who}-{i}"))
    assert r.ok and len(r.added) == 1, r.json()
print("done", flush=True)
"""


class Clock:
    def __init__(self) -> None:
        self.now, self.slept = 0.0, []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_two_processes_appending_at_once_lose_no_event_and_the_chain_verifies(tmp_path):
    path, n = tmp_path / "events.jsonl", 25
    env = {**os.environ, "PYTHONPATH": SRC}
    with E.locked(path):            # held while both start: both then wait for the same lock, at the same time
        procs = [subprocess.Popen([sys.executable, "-c", WRITER, str(path), str(who), str(n)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=env, encoding="utf-8") for who in (1, 2)]
        assert [p.stdout.readline().strip() for p in procs] == ["ready", "ready"]
        for p in procs:
            p.stdin.write("go\n")
            p.stdin.flush()
    ended = [p.communicate(timeout=120) for p in procs]
    assert [p.returncode for p in procs] == [0, 0], ended
    log, wrong = E.read(path.read_text(encoding="utf-8"))
    assert wrong == [] and len(log.events) == 2 * n and [e.seq for e in log.events] == list(range(2 * n))       # every line follows the one before it
    assert {e.evidence for e in log.events} == {f"tx:{who}-{i}" for who in (1, 2) for i in range(n)}             # and no event was lost
    assert not E.lock_of(path).exists() and E.load(path).head == log.head


def test_a_held_lock_is_waited_for_then_given_up_on_and_a_lock_left_by_a_dead_writer_is_taken_away(tmp_path):
    path, clock = tmp_path / "events.jsonl", Clock()
    one = list(E.from_evaluation(_ev(1), "record", 202610, "tx:a"))
    with E.locked(path) as lock:
        assert lock == E.lock_of(path) and lock.read_text(encoding="utf-8").split()[0] == str(os.getpid())
        with pytest.raises(E.Busy, match="is being written by another process"):
            E.record(path, one, wait=1.0, clock=clock, sleep=clock.sleep)
        assert clock.slept and sum(clock.slept) >= 1.0 and max(clock.slept) <= 0.2 and not path.exists()      # bounded: it tried, a little later each time
    assert not E.lock_of(path).exists()
    assert len(E.record(path, one).added) == 2
    # a writer died holding the lock: once the lock is older than a writer ever holds it, the next writer removes it
    E.lock_of(path).write_text("99999 0\n", encoding="utf-8")
    with pytest.raises(E.Busy):
        E.record(path, E.from_evaluation(_ev(2), "record", 202610, "tx:b"), wait=0.0)
    old = E.lock_of(path).stat().st_mtime - E.LOCK_STALE - 5
    os.utime(E.lock_of(path), (old, old))
    assert len(E.record(path, E.from_evaluation(_ev(2), "record", 202610, "tx:b"), wait=0.0).added) == 2
    assert not E.lock_of(path).exists() and not list(tmp_path.glob("*.stale")) and len(E.load(path).events) == 4
    # the best-effort entry the modes call: no log named, nothing happens; a log that cannot be written is one line, never an error
    said: list[str] = []
    assert E.keep(None, lambda: one) is None and E.where(None, {}) is None and E.where(None, {"KNOS_EVENTS": "x.jsonl"}) == Path("x.jsonl")
    assert E.where("given.jsonl", {"KNOS_EVENTS": "x.jsonl"}) == Path("given.jsonl")
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not a log\n", encoding="utf-8")
    assert E.keep(bad, lambda: one, said.append) is None and "was not written" in said[0] and bad.read_text(encoding="utf-8") == "not a log\n"
    assert E.keep(path, lambda: 1 / 0, said.append) is None and len(said) == 2 and not E.lock_of(path).exists()


def _meter(capsys, *args: str) -> tuple[int, str]:
    capsys.readouterr()
    rc = cli.main(["meter", *args])
    return rc, capsys.readouterr().out


def test_a_batch_is_taken_into_the_log_when_one_is_named_and_the_command_is_the_same_without(capsys, tmp_path, monkeypatch):
    monkeypatch.delenv("KNOS_EVENTS", raising=False)
    given, log = tmp_path / "evals.txt", tmp_path / "events.jsonl"
    given.write_text("\n".join(_ev(i).audience() for i in (1, 2)) + "\n", encoding="utf-8")
    rc, plain = _meter(capsys, "batch", str(given), "--ledger", str(tmp_path / "a.jsonl"), "--month", "2026-10")
    assert rc == 0 and not log.exists() and sorted(p.name for p in tmp_path.iterdir()) == ["a.jsonl", "evals.txt"]            # no log named: none written
    rc, said = _meter(capsys, "batch", str(given), "--ledger", str(tmp_path / "b.jsonl"), "--month", "2026-10", "--events", str(log))
    assert rc == 0 and said.replace("b.jsonl", "a.jsonl") == plain and (tmp_path / "b.jsonl").read_bytes() == (tmp_path / "a.jsonl").read_bytes()
    book = E.load(log)
    assert [(e.kind, e.source) for e in book.events] == [("evaluation", "batch"), ("acceptance", "batch")] * 2
    assert [e.id for e in book.events] == [e.id for e in E.from_ledger((tmp_path / "b.jsonl").read_text(encoding="utf-8"))]
    # KNOS_EVENTS names the log when --events does not; a log that does not check stops nothing
    monkeypatch.setenv("KNOS_EVENTS", str(tmp_path / "env.jsonl"))
    assert _meter(capsys, "batch", str(given), "--ledger", str(tmp_path / "c.jsonl"), "--month", "2026-10")[0] == 0 and len(E.load(tmp_path / "env.jsonl").events) == 4
    (tmp_path / "env.jsonl").write_text("{}\n", encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["meter", "batch", str(given), "--ledger", str(tmp_path / "d.jsonl"), "--month", "2026-10"]) == 0
    assert "was not written" in capsys.readouterr().err and (tmp_path / "d.jsonl").read_bytes() == (tmp_path / "a.jsonl").read_bytes()


def test_a_shadow_run_is_taken_into_the_log_when_one_is_named(tmp_path):
    text = "acme/app#1,12.5\nacme/app#1,12.5\n"
    plain = shadow.run(text, shadow.recorded(BOOK))
    log = tmp_path / "events.jsonl"
    st = shadow.run(text, shadow.recorded(BOOK), events=log, named="INV-7", month="2026-10")
    assert st == plain and [(e.kind, e.source) for e in E.load(log).events] == [(e.kind, "shadow") for e in E.from_shadow(st, "INV-7", "2026-10")]
    assert shadow.run(text, shadow.recorded(BOOK), events=log, named="INV-7", month="2026-10") == plain and len(E.load(log).events) == len(list(E.from_shadow(st, "INV-7", "2026-10")))


def test_an_audit_export_is_taken_into_the_log_when_one_is_named(capsys, world, tmp_path, monkeypatch):  # noqa: F811
    from knos import audit
    monkeypatch.delenv("KNOS_EVENTS", raising=False)
    args = ["audit", "export", "--owner", str(ACME), "--from", "2026-09-01", "--to", "2026-09-30", "--format", "csv"]
    capsys.readouterr()
    assert cli.main(args) == 0
    plain, log = capsys.readouterr().out, tmp_path / "events.jsonl"
    assert cli.main([*args, "--events", str(log)]) == 0 and capsys.readouterr().out == plain
    rows = audit.parse(plain)[1]
    want = list(E.from_audit(rows))
    assert want and [(e.kind, e.source, e.id, e.amount) for e in E.load(log).events] == [("settlement", "settle", e.id, e.amount) for e in want]


def test_the_relay_takes_a_confirmed_evaluation_into_the_log_when_knos_events_names_one(tmp_path, monkeypatch):
    from _meter import BUYER, Meter
    from knos.settle.v2 import meter
    from test_relay2 import USDC, Net, go, token
    c = Meter()
    net = Net(c)
    c.open(c.new_mint(), BUYER, 5 * USDC)
    log = tmp_path / "events.jsonl"
    monkeypatch.delenv("KNOS_EVENTS", raising=False)
    first = c.aud("b" * 40, verdict=1, rate=2 * USDC)
    net.spent()
    r = go((c, net), token(c, first, file="attest.yml", repository_owner_id=BUYER))
    assert r["ok"] and not log.exists()                                        # no log named: the relay writes none
    monkeypatch.setenv("KNOS_EVENTS", str(log))
    aud = c.aud("c" * 40, verdict=1, rate=2 * USDC)
    r = go((c, net), token(c, aud, file="attest.yml", repository_owner_id=BUYER))
    assert r["ok"] and r["month"] == meter.yyyymm(c.now())
    book = E.load(log)
    assert [(e.kind, e.source, e.evidence) for e in book.events] == [("evaluation", "record", f"tx:{r['sigs'][-1]}"), ("acceptance", "record", f"tx:{r['sigs'][-1]}")]
    assert [e.id for e in book.events] == [e.id for e in E.from_records([aud], r["month"])] and book.events[0].month == r["month"]
    # a log that cannot be written is never in the relay's way
    log.write_text("{}\n", encoding="utf-8")
    assert go((c, net), token(c, c.aud("d" * 40, verdict=0, rate=2 * USDC), file="attest.yml", repository_owner_id=BUYER))["ok"]


def test_one_evaluation_by_record_and_by_batch_and_one_deliverable_invoiced_twice_is_one_billable_deliverable(capsys, tmp_path, monkeypatch):
    monkeypatch.delenv("KNOS_EVENTS", raising=False)
    log, e = tmp_path / "events.jsonl", _ev(7)
    # record: what the relay does after the meter confirmed the evaluation
    assert E.keep(log, lambda: E.from_records([e.audience() + " sigRecord"], 202610)).ok
    # batch: the same evaluation in the buyer's ledger file
    given = tmp_path / "evals.txt"
    given.write_text(e.audience() + "\n", encoding="utf-8")
    assert _meter(capsys, "batch", str(given), "--ledger", str(tmp_path / "ledger.jsonl"), "--month", "2026-10", "--events", str(log))[0] == 0
    # shadow: the supplier's invoice bills one pull request on two lines
    st = shadow.run("acme/app#1,12.5,Acme Agents\nacme/app#1,12.5,Acme Agents\n", shadow.recorded(BOOK), events=log, named="INV-7", month="2026-10")
    assert [r["class"] for r in st["lines"]] == ["clean", "duplicate"]
    book, wrong = E.read(log.read_text(encoding="utf-8"))
    assert wrong == []
    got = E.statement(book, 202610)
    assert got["accepted_deliverables"] == 1                                            # ONE billable deliverable
    twice = [d for d in book.dupes() if d["kind"] == "evaluation"]
    assert len(twice) == 1 and [s["source"] for s in twice[0]["sources"]] == ["record", "batch"]     # one duplicate evaluation, with both sources
    assert twice[0]["sources"][0]["evidence"] == "tx:sigRecord" and twice[0]["sources"][1]["evidence"].startswith("batch:")
    assert got["evaluations"]["accepted"] == 2 and got["repeats_not_counted"] == 2      # the meter's and the checks', each once; the repeat and its acceptance not again
    assert got["line_states"] == {"agreed": 1, "disputed": 0, "duplicate": 1, "insufficient_evidence": 0}       # one duplicate invoice line
    # `knos statement make` from that log shows the same
    capsys.readouterr()
    assert cli.main(["statement", "make", str(log), "--out", str(tmp_path / "ap"), "--invoice", "INV-7", "--date", "2026-10-31", "--currency", "USD"]) == 0
    said = capsys.readouterr().out
    made = json.loads((tmp_path / "ap" / "ap-statement.json").read_text(encoding="utf-8"))
    assert made["source"] == "events" and made["accepted_deliverables"] == 1 and [ln["state"] for ln in made["lines"]] == ["agreed", "duplicate"]
    assert made["lines"][1]["duplicate_of"] == "line 1" and made["lines"][0]["deliverable"] == made["lines"][1]["deliverable"]
    assert [ln["amount"] for ln in made["lines"]] == ["12.50", "12.50"] and made["totals"]["duplicate"] == {"lines": 1, "amount": "12.50"}
    [repeat] = [d for d in made["repeats"] if d["kind"] == "evaluation"]
    assert repeat["id"] == twice[0]["id"] and [s["source"] for s in repeat["sources"]] == ["record", "batch"]
    assert "duplicate" in said and statement.verify(made) == (True, "same")
    answers = dict(statement.answers(made))
    assert answers["Authorised"].startswith("1 deliverable accepted in the log this month") and f"evaluation {repeat['id']} by record and batch, counted once" in answers["Arrived twice"]
    assert answers["Already billed"].startswith("1 line, 12.50 USD: line 2 (line 1)")
    capsys.readouterr()
    assert cli.main(["statement", "show", str(tmp_path / "ap" / "ap-statement.json")]) == 0 and "by record and batch, counted once" in capsys.readouterr().out.replace("\n", " ")
    # a shadow run's evidence and a month's archive are read as before: the log is told apart by its first line
    assert not statement.is_events(b'{"invoice": "x", "answers": {}}') and statement.is_events(log.read_bytes())
