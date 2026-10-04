"""examples/x402_attested and docs/X402.md: the proposed x402 "attested" scheme. The chain the example replays is what
the test build of knos_pay does now (the fixture is current), the example's own tests pass (a server and a client over
HTTP), the page states plainly that it is a proposal, and the messages it prints are the example's."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "examples" / "x402_attested"


def test_the_replayed_chain_is_what_knos_pay_does():
    pytest.importorskip("solders.litesvm")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "x402_fixture.py"), "--check"], capture_output=True, text=True, check=False,
                       env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    assert r.returncode == 0, r.stderr or r.stdout
    from knos.settle.v2 import pay
    fx = json.loads((HERE / "fixtures.json").read_text(encoding="utf-8"))
    o = pay.read_order(bytes.fromhex(fx["order"]["data"]))
    assert (str(o.address()), o.amount, o.fee, str(o.source), o.state) == (fx["order"]["address"], fx["amount"], fx["fee"], fx["buyer"], "open")
    assert fx["fee"] == pay.order_fee(fx["amount"]) and fx["paid"]["received"] == fx["amount"]            # the seller receives the amount whole
    assert fx["refunded"]["logs"] == [f"knos3:refunded order={fx['order']['address']} amount={fx['amount'] + fx['fee']}"]


def test_the_page_says_it_is_a_proposal_and_prints_the_examples_messages():
    page = (ROOT / "docs" / "X402.md").read_text(encoding="utf-8")
    assert "**This is a proposal. It is not part of x402**" in page.split("##")[0]
    blocks = {m.group(1): json.loads(m.group(2)) for m in re.finditer(r"<!-- message: (\w+) -->\s*```json\n(.*?)\n```", page, re.S)}
    assert blocks == json.loads((HERE / "messages.json").read_text(encoding="utf-8")) and len(blocks) == 5
    req = blocks["paymentRequired"]["accepts"][0]
    assert req["scheme"] == "attested" and set(req) == {"scheme", "network", "amount", "asset", "payTo", "maxTimeoutSeconds", "extra"}
    assert {"program", "order", "termsHash"} <= set(req["extra"]) and blocks["paymentPayload"]["payload"]["order"] == req["extra"]["order"]
    # node and sdk/settle only: no package of its own
    assert not (HERE / "package.json").exists()
    imports = {m for f in HERE.glob("*.mjs") for m in re.findall(r'from "([^"]+)"', f.read_text(encoding="utf-8"))}
    assert all(i.startswith(("node:", "./")) or i == "../../sdk/settle/index.js" for i in imports), imports


def test_the_example_runs_a_server_and_a_client():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: install Node 20 or later")
    done = subprocess.run([node, "--test", "--test-reporter=tap", "examples/x402_attested/test.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and re.search(r"^# pass 4$", done.stdout, re.M) and re.search(r"^# fail 0$", done.stdout, re.M), done.stdout[-3000:]
