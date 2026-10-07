"""The supplier's kit (docs/RECORD.md): the record file, its badge, the receipt for an invoice, the one-line install.

A record counts work settled through Knos from the events log and from the supplier's memory (knos.proof.history),
keeps the Agent PR Index's row apart and labelled, lists the evidence behind every count, and is never a score. The
badge is drawn from the file and from nothing else, in the drawing every Knos badge uses; web/badge.js writes the
same bytes. tests/web/supplier_record.mjs holds the page and the first screen's strip."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from knos import badge, events, ids, pdf, record_page
from knos import receipt as rc
from knos.proof import history

ROOT = Path(__file__).resolve().parents[1]
INDEX = json.loads((ROOT / "docs" / "index.json").read_text(encoding="utf-8"))
NODE = shutil.which("node")
BROWSERS = "/opt/pw-browsers"
T = "ab" * 32


class Memory:
    """A store with the two calls knos.proof.history needs: what the Sibyl store gives, held in a dict."""

    def __init__(self):
        self.held: dict = {}

    def put(self, category, name, body):
        self.held[category, name] = dict(body)

    def rows(self, category):
        return [(n, b) for (c, n), b in sorted(self.held.items()) if c == category]


def _log() -> events.Log:
    """Four deliverables of supplier 77 over two months: two accepted, one rejected, one accepted then voided; and one
    of another supplier."""
    log = events.Log()
    out = []
    for key, verdict, month in ((1, "accepted", 202607), (2, "accepted", 202608), (3, "rejected", 202608), (4, "accepted", 202609)):
        dlv = ids.deliverable("order-a", key)
        ev = events.evaluation(dlv, f"commit{key}", T, "repository@v1", key, verdict, "record", supplier="77", month=month, evidence=f"tx:sig{key}")
        out.append(ev)
        if verdict == "accepted":
            out.append(events.acceptance(dlv, "record", supplier="77", month=month, evaluation=ev.id, evidence=f"tx:sig{key}"))
    other = ids.deliverable("order-b", 1)
    out.append(events.evaluation(other, "c", T, "repository@v1", 1, "accepted", "record", supplier="88", month=202609, evidence="tx:other"))
    report = events.ingest(log, out)
    assert not report.conflicts
    voided = next(e for e in log.events if e.kind == "acceptance" and e.deliverable == ids.deliverable("order-a", 4))
    events.ingest(log, [events.correction(voided.id, void=True, reason="reverted in warranty", month=202609)])
    return log


def _memory() -> Memory:
    store = Memory()
    history.supplier_event(store, "acme/app", "vendor-x", 5, "accepted", T, at=1.0)
    history.refused(store, "acme/app", T, 6, "judge.protected-test-edited", "tests/a.py", supplier="vendor-x", at=2.0)
    history.appeal_outcome(store, "acme/app", "ap1", "accepted", "vendor-x", 6, reason="the test was mine", terms=T, at=3.0)
    history.supplier_event(store, "acme/app", "someone-else", 9, "accepted", T, at=4.0)
    return store


def test_a_record_counts_the_log_once_a_deliverable_and_lists_the_evidence_behind_every_count():
    log = _log()
    doc = record_page.build("Vendor X", log=log, supplier_ids=["77"], as_of="2026-10-06")
    counts = {k: c["n"] for k, c in doc["orders"]["counts"].items()}
    assert counts == {"accepted": 2, "rejected": 1, "insufficient_evidence": 0, "disputed": 0, "appealed": 0, "overturned": 0, "reverted": 1}
    assert tuple(counts) == record_page.ORDER_COUNTS
    assert doc["orders"]["sample"] == 4 and doc["orders"]["period"] == {"from": "2026-07", "to": "2026-09", "unit": "month"}
    assert doc["orders"]["category"] == record_page.EVENTS_CATEGORY and doc["orders"]["label"] == "work settled through Knos"
    for name, c in doc["orders"]["counts"].items():
        assert c["n"] == len(c["evidence"]), name
        for e in c["evidence"]:        # the line, its hash in the chain, and where the issuer's evidence is
            assert log.hashes[e["line"]] == e["line_sha256"] and log.events[e["line"]].id == e["event"] and e["evidence"].startswith("tx:sig")
    assert doc["orders"]["counts"]["accepted"]["from"] == "events" and doc["orders"]["counts"]["appealed"]["from"] == "nothing on record"
    assert doc["orders"]["counts"]["reverted"]["evidence"][0]["reason"] == "reverted in warranty"
    assert doc["orders"]["parts"]["events"]["head"] == log.head and doc["orders"]["parts"]["memory"] == {"read": False, "why": "not given when this file was built"}
    assert doc["supplier"] == "vendor-x" and doc["public"] is None and record_page.check(doc) is None
    # another supplier's work is not in it, and the same inputs give the same bytes
    assert all(e["evidence"] != "tx:other" for c in doc["orders"]["counts"].values() for e in c["evidence"])
    assert record_page.text(doc) == record_page.text(record_page.build("Vendor X", log=_log(), supplier_ids=["77"], as_of="2026-10-06"))


def test_the_suppliers_memory_is_read_through_the_engine_and_never_added_to_the_log():
    store = _memory()
    alone = record_page.build("vendor-x", store=store, repos=["acme/app"], as_of="2026-10-06")
    counts = {k: (c["n"], c["from"]) for k, c in alone["orders"]["counts"].items()}
    assert counts["accepted"] == (1, "memory") and counts["rejected"] == (1, "memory") and counts["appealed"] == (1, "memory") and counts["overturned"] == (1, "memory")
    assert counts["reverted"] == (0, "nothing on record") and alone["orders"]["sample"] == 2 and alone["orders"]["category"] == record_page.MEMORY_CATEGORY
    assert alone["orders"]["counts"]["overturned"]["evidence"] == [{"repository": "acme/app", "pull_request": 6, "url": "https://github.com/acme/app/pull/6", "appeal": "ap1"}]
    assert "knos.proof.history" in alone["orders"]["parts"]["memory"]["source"] and alone["orders"]["parts"]["memory"]["repositories"] == ["acme/app"]
    assert history.supplier_record(store, "acme/app", "vendor-x")["accepted"] == alone["orders"]["counts"]["accepted"]["n"]
    # with both, accepted and rejected are the log's (the same work is not counted twice); appeals stay the memory's
    both = record_page.build("vendor-x", log=_log(), supplier_ids=["77"], store=store, repos=["acme/app"], as_of="2026-10-06")
    got = {k: (c["n"], c["from"]) for k, c in both["orders"]["counts"].items()}
    assert got["accepted"] == (2, "events") and got["rejected"] == (1, "events") and got["overturned"] == (1, "memory") and got["reverted"] == (1, "events")
    assert both["orders"]["sample"] == 4 and record_page.check(both) is None


def test_the_index_row_is_kept_apart_and_labelled_as_public_pull_requests():
    top = INDEX["weeks"][0]
    for row in top["rows"]:
        doc = record_page.build(row["agent"], index=INDEX)
        p = doc["public"]
        assert p["label"] == "from public pull requests, not from Knos orders" and p["category"] == record_page.PUBLIC_CATEGORY
        assert (p["sample"], p["failed_at_merge"], p["share"], p["ci95"], p["rank"]) == (row["merged"], row["failed_at_merge"], row["share"], row["ci95"], row["rank"])
        assert p["week"] == top["week"] and p["weeks"] == row["weeks"] and p["dispute"] == row["dispute"] and doc["as_of"] == top["read"]
        assert doc["orders"]["sample"] == 0 and all(c == {"n": 0, "from": "nothing on record", "evidence": []} for c in doc["orders"]["counts"].values())
        assert "score" not in json.dumps({k: v for k, v in doc.items() if k not in ("not_a_score", "limits")}).lower()
        assert doc["rule"] == record_page.RULE and doc["links"]["page"].endswith(f"#record={doc['supplier']}")
    assert record_page.build("nobody-measured", index=INDEX, as_of="2026-10-06")["public"] is None
    with pytest.raises(ValueError):
        record_page.slug("///")


def test_the_committed_records_are_what_the_index_gives_and_the_board_writes_them(tmp_path):
    want = record_page.index_records(INDEX)
    have = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "docs" / "records").iterdir()}
    assert have == want, "docs/records is behind docs/index.json: python scripts/agent_pr_index.py board"
    assert sorted(n for n in want if n.endswith(".json")) == sorted(f"{record_page.slug(r['agent'])}.json" for r in INDEX["weeks"][0]["rows"])
    for name, text in want.items():
        if name.endswith(".json"):
            assert record_page.check(json.loads(text)) is None, name
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "agent_pr_index.py"), "board", "--check"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    # a file somebody edited no longer checks
    doc = json.loads(want["codex.json"])
    doc["public"]["failed_at_merge"] = 0
    assert record_page.check(doc) == "the file does not hash to the sha256 it states"


def test_the_badge_is_drawn_from_the_record_states_its_sample_and_is_green_only_for_accepted_work():
    with_orders = record_page.build("Vendor X", log=_log(), supplier_ids=["77"], as_of="2026-10-06")
    b = record_page.badge_data(with_orders)
    assert (b["label"], b["message"], b["colour"]) == ("Knos-verified", "2 accepted, 1 reverted, sample 4, 2026-07 to 2026-09", "#1a7f37")
    public = record_page.build("codex", index=INDEX)
    p = public["public"]
    b = record_page.badge_data(public)
    assert b["label"] == "Knos record" and b["colour"] == "#57606a"
    assert b["message"] == f"no Knos orders yet; public PRs: {p['failed_at_merge']} of {p['sample']} had a failed check, week of {p['week']}"
    none = record_page.badge_data(record_page.build("new-vendor", as_of="2026-10-06"))
    assert (none["label"], none["message"], none["colour"]) == ("Knos record", "nothing on record, as of 2026-10-06", "#57606a")
    for doc in (with_orders, public):
        svg = record_page.badge_svg(doc)
        root = ET.fromstring(svg)
        assert root.get("height") == "20" and "<script" not in svg and "href" not in svg and "@font-face" not in svg
        assert record_page.RULE in svg and badge.MARK["d"] in svg        # one drawing: the Knos mark and the two halves of every badge
        assert record_page.badge_markdown(doc, "b.svg").endswith(f"](b.svg)]({doc['links']['page']})")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_site_draws_the_same_record_badge_byte_for_byte():
    docs = [record_page.build("Vendor X", log=_log(), supplier_ids=["77"], as_of="2026-10-06"), record_page.build("codex", index=INDEX),
            record_page.build("new-vendor", as_of="2026-10-06")]
    script = f"""
      import {{ recordBadgeSvg, recordBadge, recordBadgeMarkdown }} from {json.dumps((ROOT / "web" / "badge.js").as_uri())};
      const docs = {json.dumps(docs)};
      console.log(JSON.stringify(docs.map((d) => [recordBadgeSvg(d), recordBadge(d), recordBadgeMarkdown(d, "b.svg")])));
    """
    run = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0, run.stderr
    for doc, (svg, data, line) in zip(docs, json.loads(run.stdout)):
        assert svg == record_page.badge_svg(doc) and data == record_page.badge_data(doc) and line == record_page.badge_markdown(doc, "b.svg")


def test_the_commands_write_the_record_its_badge_and_the_receipt_for_an_invoice(tmp_path):
    from typer.testing import CliRunner

    from knos import cli
    log_path = tmp_path / "events.jsonl"
    events.record(log_path, [e for e in _log().events])
    out = tmp_path / "records"
    got = CliRunner().invoke(cli.app, ["record", "build", "Vendor X", "--out", str(out), "--events", str(log_path), "--id", "77", "--index", str(ROOT / "docs" / "index.json"),
                                       "--as-of", "2026-10-06"])
    assert got.exit_code == 0, got.output
    doc = json.loads((out / "vendor-x.json").read_text(encoding="utf-8"))
    assert record_page.check(doc) is None and doc["orders"]["counts"]["accepted"]["n"] == 2 and "2 accepted" in got.output
    assert (out / "vendor-x.svg").read_text(encoding="utf-8") == record_page.badge_svg(doc)
    image = tmp_path / "b.svg"
    got = CliRunner().invoke(cli.app, ["badge", "record", "vendor-x", "--records", str(out), "--out", str(image)])
    assert got.exit_code == 0 and image.read_text(encoding="utf-8") == record_page.badge_svg(doc)
    assert f"]({image.as_posix()})]({record_page.SITE}/#record=vendor-x)" in got.output
    assert CliRunner().invoke(cli.app, ["badge", "record", "nobody", "--records", str(out)]).exit_code != 0
    # the receipt: one page and its JSON, from an acceptance receipt that checks
    receipt = json.loads((ROOT / "docs" / "receipt" / "vectors.v4.json").read_text(encoding="utf-8"))["valid_v4"][0]["receipt"]
    source = tmp_path / "order.receipt.json"
    source.write_text(json.dumps(receipt), encoding="utf-8")
    got = CliRunner().invoke(cli.app, ["record", "receipt", str(source), "--invoice", "INV-7"])
    assert got.exit_code == 0, got.output
    made = json.loads((tmp_path / "order.receipt.verified.json").read_text(encoding="utf-8"))
    assert made["schema"] == "knos.invoice-receipt/1" and made["receipt_sha256"] == rc.digest(receipt) and made["invoice"] == "INV-7"
    assert made["verify"]["command"] == "knos receipt order.receipt.json" and made["verify"]["expect"] in got.output
    said = " ".join(pdf.texts((tmp_path / "order.receipt.verified.pdf").read_bytes()))
    for needle in ("Verified receipt for invoice INV-7", "Agreed", "Delivered", "Accepted", "Evaluator", "Evidence", "knos receipt order.receipt.json",
                   rc.digest(receipt), receipt["policy"]["terms_hash"], "20.00 test USDC", "repository at"):
        assert needle in said, needle
    assert record_page.invoice_pdf(made) == (tmp_path / "order.receipt.verified.pdf").read_bytes()        # the same receipt gives the same bytes
    # the command the page names does check that file, with no network
    assert CliRunner().invoke(cli.app, ["receipt", str(source)]).exit_code == 0
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({**receipt, "order": "x"}), encoding="utf-8")
    got = CliRunner().invoke(cli.app, ["record", "receipt", str(broken)])
    assert got.exit_code != 0 and not (tmp_path / "broken.verified.pdf").exists()


def test_the_receipt_for_an_invoice_is_one_page():
    receipt = json.loads((ROOT / "docs" / "receipt" / "vectors.v4.json").read_text(encoding="utf-8"))["valid_v4"][0]["receipt"]
    doc = record_page.invoice_receipt(receipt, "r.json")
    assert b"/Type /Pages /Count 1 " in record_page.invoice_pdf(doc)
    assert doc["accepted"]["verdict"] == "accepted" and doc["evaluator"]["kind"] == "repository" and doc["agreed"]["amount"] == "20.00"


def test_the_one_line_install_runs_the_free_check_posts_once_and_attaches_the_receipt():
    example = yaml.safe_load((ROOT / "examples" / "knos-supplier.yml").read_text(encoding="utf-8"))
    called = yaml.safe_load((ROOT / ".github" / "workflows" / "supplier.yml").read_text(encoding="utf-8"))
    on = example.get("on", example.get(True))
    assert on == {"pull_request": {"types": ["opened", "synchronize", "reopened", "edited"]}} and example["permissions"] == {}
    [(name, job)] = example["jobs"].items()
    assert name.startswith("knos") and set(job) == {"permissions", "uses"}       # one line: nothing is passed, no secret, no input
    line = f"uses: {job['uses']}"
    assert job["uses"].startswith("drexthealpha/Knos/.github/workflows/supplier.yml@v")
    assert line in (ROOT / "docs" / "RECORD.md").read_text(encoding="utf-8") and line in (ROOT / "web" / "supplier_record.js").read_text(encoding="utf-8")
    assert called.get("on", called.get(True)) == {"workflow_call": {}} and called["permissions"] == {}
    [(_, check)] = called["jobs"].items()
    assert check["permissions"] == job["permissions"] == {"contents": "read", "checks": "read", "pull-requests": "write"}
    assert check["name"].startswith("knos") and "id-token" not in json.dumps(called) and "secrets" not in json.dumps(called)
    steps = check["steps"]
    pins = json.loads((ROOT / "scripts" / "action_pins.json").read_text(encoding="utf-8"))["pins"]
    uses = [s["uses"] for s in steps if "uses" in s]
    assert len(uses) == 2 and uses[0].startswith("drexthealpha/Knos@") and len(uses[0].split("@")[1]) == 40
    assert uses[1] == f"actions/upload-artifact@{pins['actions/upload-artifact@v7']}"
    assert steps[0].get("continue-on-error") is True and steps[0]["id"] == "knos"
    post = next(s for s in steps if s.get("name") == "post the result once")["run"]
    assert "knos-supplier-check" in post and "-X PATCH" in post and "-X POST" in post and post.count("gh api") == 3
    assert "exit 1" in steps[-1]["run"] and steps[-1]["env"] == {"PASSED": "${{ steps.knos.outputs.passed }}"}
    # nothing of the pull request is checked out or run here
    assert "actions/checkout" not in json.dumps(called) and "pull_request_target" not in json.dumps(called)


def test_the_document_is_on_the_map_and_names_each_part_of_the_kit():
    text = (ROOT / "docs" / "RECORD.md").read_text(encoding="utf-8")
    for needle in ("knos record build", "knos badge record", "knos record receipt", "knos.supplier-record/1", "knos.proof.history",
                   "from public pull requests, not from Knos orders", "never pays", "Nothing in the file is a score"):
        assert needle in text, needle
    assert "(RECORD.md)" in (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    assert record_page.SCHEMA in (ROOT / "web" / "supplier_record.js").read_text(encoding="utf-8")


def _node(*args: str) -> subprocess.CompletedProcess:
    if not NODE:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    return subprocess.run([NODE, str(ROOT / "tests" / "web" / "supplier_record.mjs"), *args], env=env, capture_output=True, text=True, encoding="utf-8", timeout=170)


def test_the_strip_and_the_page_hold_their_word_budget_without_a_browser():
    run = _node()
    assert run.returncode == 0 and "all passed" in run.stdout, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))


def test_the_record_page_counts_up_shows_its_evidence_and_asks_nobody_else():
    run = _node("page")
    if run.returncode == 0 and "\nSKIP " in "\n" + run.stdout:
        pytest.skip(run.stdout.split("SKIP ", 1)[1].strip())
    assert run.returncode == 0 and "all passed" in run.stdout, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
