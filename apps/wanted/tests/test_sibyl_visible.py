"""The Knos record's memory store (the sibyl_memory_client package) is seen where Knos uses it: the hosted MCP's
knos_memory_search hands on the store's verdict object and its code as the store gave them; every decision line Knos writes
is accepted by the Record (no kind it refuses), and the receipt says what the record kept of it ("In the Knos record:
<tier>, verdict <code>"); the store's paid self-learning is never called."""
import re
from pathlib import Path

from knos_wanted import agent, valley

ROOT = Path(__file__).resolve().parents[3]


class State:
    reports: dict = {}


def test_knos_memory_search_hands_on_sibyls_verdict_unchanged(monkeypatch):
    from knos.record import search as rsearch
    verdict = {"code": "no_match", "tokens": ["zebra"], "gate": "coverage_floor", "gate_drops": {"coverage_floor": 2}}
    monkeypatch.setattr(rsearch, "search", lambda q, root=None, **k: {"rows": [], "verdict": verdict, "said": "nothing matched"})
    got = agent.mcp(State(), {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "knos_memory_search", "arguments": {"q": "zebra"}}})
    out = got["result"]["structuredContent"]
    assert out["verdict"] == verdict and out["verdict_code"] == "no_match" and out["said"] == "nothing matched"


def test_the_ambiguity_line_and_the_archive_line_are_written_and_remembered():
    got = valley._journal("verdict", {"what": "ambiguity pattern resolved", "word": "fast", "reading": "under 2 s", "target": "p95"})
    assert got["recorded"] is True, got
    assert got["sibyl"]["tier"] == "COLD" and re.fullmatch(r"[0-9a-f]{64}", got["sibyl"]["hash"])
    assert got["sibyl"]["verdict"] is not None                  # the code Sibyl's own search gave for the line
    pid = "ab" * 32
    got = valley._journal("verdict", {"project": pid, "what": "project archived", "status": "cancelled"})
    assert got["recorded"] is True, got
    for kind in ("reference", "archive"):                       # the two kinds the Record refused before: said, not swallowed
        assert valley._journal(kind, {"what": "x"})["recorded"] is False


def test_valley_writes_only_kinds_the_record_accepts():
    from knos.record import journal
    src = (ROOT / "apps" / "wanted" / "knos_wanted" / "valley.py").read_text(encoding="utf-8")
    kinds = set(re.findall(r'_journal\("([a-z]+)"', src))
    assert kinds and kinds <= set(journal.KINDS), kinds - set(journal.KINDS)


def test_the_receipt_says_what_the_record_kept():
    js = (ROOT / "apps" / "wanted" / "knos_wanted" / "static" / "app.js").read_text(encoding="utf-8")
    assert "In the Knos record: ${esc(s.tier)}, verdict ${esc(s.verdict" in js and "sibylLine(p.sibyl)" in js and "sibylLine(got.sibyl)" in js
    assert '"sibyl")} |' in (ROOT / "apps" / "wanted" / "knos_wanted" / "valley.py").read_text(encoding="utf-8")    # the order hands it on


def test_sibyls_paid_learn_is_never_called():
    calls = [f"{p.relative_to(ROOT)}:{i}" for p in (ROOT / "src").rglob("*.py")
             for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
             if re.search(r"\b(client|MemoryClient\([^)]*\))\.learn\(", line) and not line.lstrip().startswith("#")]
    assert calls == []
