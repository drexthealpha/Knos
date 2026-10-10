"""examples/consumer: a second application, in Node with no package, that decides from a receipt or a statement's
status file and the chain whether an order is paid, by which transaction, under which terms hash. Its own tests run
offline on a recorded order (node --test); here it also decides an order paid on a fresh LiteSVM harness, so the
recording cannot drift from what the programs as built print."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "examples" / "consumer"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="node is not installed: install Node 20 or later")


def _node(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(NODE), *args], cwd=ROOT, capture_output=True, encoding="utf-8", timeout=120)


def test_it_uses_nothing_of_knos_but_the_published_schema_and_idl():
    for name in ("consumer.mjs", "test.mjs"):
        text = (HERE / name).read_text(encoding="utf-8")
        imports = re.findall(r'^import .* from "([^"]+)";', text, re.M)
        assert imports and all(i.startswith("node:") or i == "./consumer.mjs" for i in imports), (name, imports)
        assert "sdk/settle" not in text and "knos-settle" not in text and "src/knos" not in text
    text = (HERE / "consumer.mjs").read_text(encoding="utf-8")
    assert '"idl", "knos_pay_v2.json"' in text and '"docs", "receipt"' in text


@needs_node
def test_the_node_tests_pass_offline():
    done = _node("--test", "--test-reporter=tap", "examples/consumer/test.mjs")
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-2000:]
    assert re.search(r"^# fail 0$", done.stdout, re.M) and re.search(r"^# pass (\d+)$", done.stdout, re.M)


def test_the_recorded_receipt_is_one_knos_itself_accepts():
    from knos import receipt
    made = json.loads((HERE / "fixtures" / "order_paid.json").read_text(encoding="utf-8"))
    assert receipt.check(made["receipt"]) is None
    assert json.loads((HERE / "fixtures" / "receipt.json").read_text(encoding="utf-8")) == made["receipt"]
    assert json.loads((HERE / "fixtures" / "status.json").read_text(encoding="utf-8")) == made["status"]


@needs_node
def test_it_decides_an_order_paid_on_a_fresh_harness(tmp_path):
    pytest.importorskip("solders.litesvm")
    spec = importlib.util.spec_from_file_location("consumer_record", HERE / "record.py")
    assert spec is not None and spec.loader is not None
    record = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(record)
    made = record.build()
    (tmp_path / "rec.json").write_text(json.dumps(made), encoding="utf-8")
    (tmp_path / "receipt.json").write_text(json.dumps(made["receipt"]), encoding="utf-8")
    (tmp_path / "status.json").write_text(json.dumps(made["status"]), encoding="utf-8")
    done = _node("examples/consumer/consumer.mjs", "receipt", str(tmp_path / "receipt.json"), "--recorded", str(tmp_path / "rec.json"), "--json")
    assert done.returncode == 0, done.stdout + done.stderr
    d = json.loads(done.stdout)
    r = made["receipt"]
    assert (d["paid"], d["order"], d["transaction"], d["terms_hash"]) == (True, r["order"], r["transaction"]["signature"], r["policy"]["terms_hash"])
    done = _node("examples/consumer/consumer.mjs", "status", str(tmp_path / "status.json"), "--recorded", str(tmp_path / "rec.json"))
    assert done.returncode == 0 and done.stdout.startswith("PAID: every payment on chain in the file"), done.stdout + done.stderr
    # one wallet changed in the receipt: the consumer says no, and names it
    r["payees"][0]["to"] = r["order"]
    (tmp_path / "receipt.json").write_text(json.dumps(r), encoding="utf-8")
    done = _node("examples/consumer/consumer.mjs", "receipt", str(tmp_path / "receipt.json"), "--recorded", str(tmp_path / "rec.json"))
    assert done.returncode == 1 and "NOT SHOWN PAID" in done.stdout and "knos_pay logged" in done.stdout
