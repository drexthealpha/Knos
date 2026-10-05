"""The Buy page (web/buyer.js), its templates file, and the statement's exports (web/statements.js).

Three things are held here. web/buyer_templates.json is what scripts/buyer_templates.py writes from
knos.terms_templates, and the page's own sentence and comment for a template are the ones that file carries. The
statement's Export CSV and Export JSON are, byte for byte, `knos.audit.export` of the same owner and month (the
fixture is the month of tests/test_audit.py). And tests/web/buyer.mjs runs the page in headless Chromium with a
virtual authenticator: the line its passkey signs is then sent to the programs in LiteSVM by the relay, and funds the
order. The same run draws the console's views (web/console.js) from mocked chain data and counts the fields and clicks
of a governed order; docs/CONSOLE.md must state that count. No node, no `playwright` package or no browser: those
parts are skipped, with the reason.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import _posix
import pytest

from knos import audit, commands, terms_templates

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"          # where this project's machines keep Chromium; anywhere else playwright's default holds
SHOTS = os.environ.get("KNOS_BUYER_SHOTS", "")     # a folder for screenshots, when someone wants to look


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _site(tmp_path: Path) -> tuple[Path, dict]:
    """The site as the Pages build lays it out, and the environment its tests run in."""
    site = tmp_path / "site"
    env = _posix.environ({**os.environ, "PYTHON": _posix.path(sys.executable), "PYTHONPATH": str(ROOT / "src")})
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    built = subprocess.run([_posix.bash(), _posix.path(ROOT / "scripts" / "build_site.sh"), _posix.path(site), "c" * 40],
                           env=env, capture_output=True, text=True, timeout=120)
    assert built.returncode == 0, built.stdout + built.stderr
    return site, env


def _month(site: Path, out: Path) -> None:
    """One organisation's September as the site would hold it (audit/5001.json), and what `knos audit export` prints for it."""
    from test_audit import ACME, SEPT, later
    for path, text in _script("audit_statements").files(later(), [ACME]).items():
        (site / path).parent.mkdir(parents=True, exist_ok=True)
        (site / path).write_text(text, encoding="utf-8", newline="")
    out.mkdir(exist_ok=True)
    for fmt in ("csv", "json"):
        text = audit.export(later(), ACME, fmt, **SEPT)
        assert audit.verify(text) == []
        (out / f"expected.{fmt}").write_text(text, encoding="utf-8", newline="")


def test_the_templates_file_is_what_the_script_writes_from_the_templates():
    built = _script("buyer_templates").build()
    assert (ROOT / "web" / "buyer_templates.json").read_text(encoding="utf-8") == built, "run python scripts/buyer_templates.py"
    doc = json.loads(built)
    assert [t["name"] for t in doc["templates"]] == list(terms_templates.TEMPLATES) and doc["money"] == commands.MONEY
    for t in doc["templates"]:
        ex = json.loads((ROOT / "examples" / "terms" / f"{t['name']}.json").read_text(encoding="utf-8"))
        assert (t["sentence"], t["comment"], t["where"]) == (ex["sentence"], ex["comment"], ex["where"])
        assert t["assurance"] == ("black-box" if ex["terms"]["mode"] == "tests" else "in-process") and len(t["trusted"]) >= 4
        assert t["passkey"] == (not t["passkey_why_not"]) == (ex["terms"]["mode"] == "merge" and "vendor" not in ex["terms"] and "policy" not in ex["terms"])
    assert set(doc["assurance"]) == {"in-process", "black-box", "hermetic"}


RUN = """
import { readFileSync } from "node:fs";
import { sentenceOf, commentOf } from "./buyer.js";
import { auditExport } from "./statements.js";
const book = JSON.parse(readFileSync("buyer_templates.json", "utf8")), said = [];
for (const t of book.templates) said.push([t.name, sentenceOf(t.parts, book.money) === t.sentence, commentOf(t.parts, book.default_days) === t.comment, sentenceOf(t.parts, book.money), commentOf(t.parts, book.default_days)]);
const file = JSON.parse(readFileSync("audit/5001.json", "utf8")), out = {};
for (const [month, m] of Object.entries(file.months)) out[month] = { csv: (await auditExport(m.scope, m.lines, "csv")).text, json: (await auditExport(m.scope, m.lines, "json")).text };
console.log(JSON.stringify({ said, out }));
"""


def test_the_page_says_a_template_and_writes_a_statement_as_the_python_does(tmp_path: Path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    from test_audit import ACME, later
    site, env = _site(tmp_path)
    _month(site, tmp_path / "fixtures")
    (site / "run.mjs").write_text(RUN, encoding="utf-8")
    r = subprocess.run([node, "run.mjs"], cwd=site, capture_output=True, text=True, timeout=120, env=env, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    got = json.loads(r.stdout)
    # every template, with its own numbers: the sentence knos.terms_templates.sentence writes, the comment knos.commands reads
    assert [row[:3] for row in got["said"]] == [[name, True, True] for name in terms_templates.TEMPLATES], got["said"]
    # every month of the organisation, both formats: the bytes of knos.audit.export for that month
    assert set(got["out"]) == {"2026-09", "2026-10"}
    for month, last in (("2026-09", "2026-09-30"), ("2026-10", "2026-10-31")):
        for fmt in ("csv", "json"):
            want = audit.export(later(), ACME, fmt, f"{month}-01", last)
            assert got["out"][month][fmt].encode() == want.encode(), (month, fmt)
            assert audit.verify(got["out"][month][fmt]) == []


def test_the_buy_page_in_a_browser_and_its_signed_line_on_chain(tmp_path: Path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    site, env = _site(tmp_path)
    fixtures = tmp_path / "fixtures"
    _month(site, fixtures)
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "buyer.mjs"), str(site), str(fixtures), *([SHOTS] if SHOTS else [])], env=env, capture_output=True, text=True, timeout=600)
    if run.returncode == 0 and run.stdout.startswith("SKIP"):
        pytest.skip(run.stdout.strip()[5:])
    assert run.returncode == 0, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert "the Buy page holds" in run.stdout
    # the count of a governed order's fields and clicks, as the browser made one: docs/CONSOLE.md states the same number
    counted = re.search(r"GOVERNED ORDER: (\d+) fields, (\d+) clicks on the page", run.stdout)
    assert counted and f"**{counted[1]} fields and {counted[2]} clicks**" in (ROOT / "docs" / "CONSOLE.md").read_text(encoding="utf-8")
    # what the browser's passkey signed, carried by the relay to the programs: the order is funded, and a replay is refused
    pytest.importorskip("solders.litesvm")
    from solders.account import Account
    from _order import USDC
    from _pay2 import ChainLedger
    from test_passkey_fund import World
    from knos.settle.v2 import passkey_fund as pf
    from knos.settle.v2 import pay, relay
    line = (fixtures / "line.txt").read_text(encoding="utf-8")
    cmd = commands.parse(line, on_pull=False)
    assert isinstance(cmd, commands.PasskeyFund)
    q = pf.read_intent(cmd.intent)
    w = World()
    mint = w.svm.get_account(w.usdc)                      # Circle's devnet USDC, as the page names it: the harness's mint at that address
    w.svm.set_account(pay.USDC_DEVNET, Account(mint.lamports, bytes(mint.data), mint.owner))
    source = w.token_account(q.wallet, pay.USDC_DEVNET)
    w.mint_to(pay.USDC_DEVNET, source, 100 * USDC)
    w.token_account(pay.FEE_OWNER, pay.USDC_DEVNET)
    w.svm.warp_to_slot(q.expiry_slot - 100)               # the slot the browser's devnet said, an hour's worth before the intent ends
    assert w.data(q.wallet) is None                       # a wallet nobody opened: the relay opens it in the same transaction
    r = relay.passkey_fund(ChainLedger(w), w.payer, cmd.intent, 5550001, 7)
    assert r["ok"], r
    o = w.order(q.order)
    assert (o.amount, o.repo_id, o.issue, o.source, o.refund_to, o.mint) == (50 * USDC, 5550001, 7, q.wallet, q.wallet, pay.USDC_DEVNET)
    assert o.terms == pay.terms_hash(q.data[pf.FUND_MIN:]) and w.held(q.order) == 50 * USDC + o.fee == 100 * USDC - w.balance(source)
    again = relay.passkey_fund(ChainLedger(w), w.payer, line, 5550001, 7)
    assert not again["ok"] and "this funding was sent already" in again["why"]
