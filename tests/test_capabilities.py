"""docs/capabilities.json: what Knos can do and how far each thing has got, held to its evidence."""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("capabilities", ROOT / "scripts" / "capabilities.py")
cap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cap)
DATA = cap.load()
BY_ID = {c["id"]: c for c in DATA["capabilities"]}


def test_the_manifest_has_the_shape_the_script_and_the_site_read():
    assert DATA["stages"] == list(cap.STAGES) == ["implemented", "tested", "deployed", "exercised", "reproduced"] and DATA["cluster"] == "devnet"
    ids = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
    assert {n: p["id"] for n, p in DATA["programs"].items() if n in ids} == {n: ids[n] for n in ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey")}
    for c in DATA["capabilities"]:
        assert set(c) <= {"id", "what", "stage", "evidence", "note"} and {"id", "what", "stage", "evidence"} <= set(c), c["id"]
        assert c["stage"] in (None, *cap.STAGES) and c["what"].endswith(".") and set(c["evidence"]) <= set(cap.STAGES)
    assert len(BY_ID) == len(DATA["capabilities"]) >= 40


def test_every_stage_has_its_evidence():
    assert cap.problems(DATA) == []
    assert cap.main(["check"]) == 0


# What the 0.3.14 rehearsal ran on devnet, on staging deployments of this build (docs/CAPABILITIES.md)
EXERCISED = {"work_orders", "order_pay", "single_use_tokens", "fee_tiers", "reserve_cancel", "warranty_revert", "order_auto_accept", "tests_mode",
             "order_quorum", "order_challenge", "meter_batch", "meter_seller_claim", "passkey_funder", "passkey_fund_relay", "buyer_page",
             "x402_knos_order"}


def test_the_manifest_claims_no_more_than_is_true_today():
    """2.1 of knos_pay and knos_oidc is proposed, not executed: on the pinned programs what it adds is tested and no
    more. What the release's rehearsal ran on devnet is exercised on a staging program of its own, never on a pinned
    one, with its transaction; nothing else is exercised, and no document links an outside run, so nothing is reproduced."""
    assert DATA["programs"]["knos_pay"]["on_chain"] == DATA["programs"]["knos_oidc"]["on_chain"] == "2.0"
    for cid in ("seller_settle", "neutral_attest", "arbiter_rule", "top_up", "assign", "plans", "org_balance_limits", "verify_any_issuer", "holdback_release"):
        assert BY_ID[cid]["stage"] == "tested", cid
    assert {c["stage"] for c in DATA["capabilities"]} <= {None, "implemented", "tested", "deployed", "exercised"}
    assert {c["id"] for c in DATA["capabilities"] if c["stage"] == "exercised"} == EXERCISED
    assert all(c["evidence"]["deployed"]["version"] in ("2.0", "1.0") for c in DATA["capabilities"] if c["stage"] == "deployed")
    ids = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
    pinned = {v for v in ids.values() if isinstance(v, str)}
    staging = {n: p for n, p in DATA["programs"].items() if n.endswith("_staging")}
    assert set(staging) == {"knos_pay_staging", "knos_meter_staging", "knos_passkey_staging"}
    assert all(p["id"] not in pinned and n not in ids and p["on_chain"] in p["versions"] for n, p in staging.items())
    rehearsal = (ROOT / cap.FULL).read_text(encoding="utf-8").split("## The 0.3.14 rehearsal on devnet", 1)[1]
    for cid in EXERCISED:
        ev = BY_ID[cid]["evidence"]
        assert ev["deployed"]["program"] in staging and "staging deployment" in BY_ID[cid]["note"], cid
        assert ev["exercised"]["signature"] in rehearsal, cid
    for cid in ("fund_by_comment", "pay_on_merge", "verify_github", "meter_single", "passkey_payee_wallet"):
        assert BY_ID[cid]["stage"] == "deployed", cid


def _with(cid: str, **change) -> dict:
    data = copy.deepcopy(DATA)
    next(c for c in data["capabilities"] if c["id"] == cid).update(change)
    return data


def test_a_stage_without_evidence_is_refused():
    wo = BY_ID["seller_settle"]     # a knos_pay 2.1 capability that is tested, no more
    sig = "5" * 87
    cases = {
        "stage deployed without deployed evidence": _with("seller_settle", stage="deployed"),
        "stage tested without tested evidence": _with("seller_settle", evidence={"implemented": wo["evidence"]["implemented"]}),
        "stage exercised without deployed evidence": _with("seller_settle", stage="exercised", evidence={**wo["evidence"], "exercised": {"signature": sig}}),
        "knos_pay 2.1 carries it, and devnet runs 2.0": _with("seller_settle", stage="deployed", evidence={
            **wo["evidence"], "deployed": {"program": "knos_pay", "id": DATA["programs"]["knos_pay"]["id"], "version": "2.1"}}),
        "is not a file of this repository": _with("seller_settle", evidence={**wo["evidence"], "implemented": {"path": "programs-v2/knos_pay/src/nothing.rs", "names": "fund_order"}}),
        "does not say 'test_an_order_flies'": _with("seller_settle", evidence={**wo["evidence"], "tested": {"test": "tests/test_order_chain.py", "names": "test_an_order_flies"}}),
        "is not a test file": _with("seller_settle", evidence={**wo["evidence"], "tested": {"test": "src/knos/flow.py", "names": "def "}}),
        "has tested evidence but says stage implemented": _with("seller_settle", stage="implemented"),
        "has implemented evidence but says stage None": _with("seller_settle", stage=None),
        "exercised: a transaction signature on devnet is needed": _with("fund_by_comment", stage="exercised", evidence={**BY_ID["fund_by_comment"]["evidence"], "exercised": {"signature": ""}}),
        "reproduced: a link to someone else's run": _with("fund_by_comment", stage="reproduced", evidence={
            **BY_ID["fund_by_comment"]["evidence"], "exercised": {"signature": sig}, "reproduced": {"url": "https://example.com/a-run-nobody-made"}}),
        "`what` is one plain sentence": _with("seller_settle", what="Orders. And more."),
    }
    for said, data in cases.items():
        assert any(said in line for line in cap.problems(data)), (said, cap.problems(data))
    # ... and with its evidence, a higher stage holds: nothing in the check is tied to today's stages
    ok = _with("fund_by_comment", stage="exercised", evidence={**BY_ID["fund_by_comment"]["evidence"], "exercised": {"signature": sig}})
    assert cap.problems(ok) == []


def test_the_chain_is_asked_for_the_version_and_for_every_signature():
    sig, other = "5" * 87, "6" * 87
    data = _with("fund_by_comment", stage="exercised", evidence={**BY_ID["fund_by_comment"]["evidence"], "exercised": {"signature": sig}})
    data = json.loads(json.dumps(data))
    next(c for c in data["capabilities"] if c["id"] == "pay_on_merge").update(stage="exercised", evidence={**BY_ID["pay_on_merge"]["evidence"], "exercised": {"signature": other}})
    pay = data["programs"]["knos_pay"]["id"]

    def rpc(version_logs, gone=(), failed=()):
        def ask(url, method, params):
            if method == "getAccountInfo":
                return {"value": None if params[0] in gone else {"executable": True}}
            if method == "simulateTransaction":
                return {"value": version_logs}
            return {"value": [None if s == other and "missing" in failed else {"err": {"InstructionError": [0, "Custom"]} if s in failed else None} for s in params[0]]}
        return ask
    v20 = {"err": {"InstructionError": [0, "InvalidInstructionData"]}, "logs": [f"Program {pay} invoke [1]", f"Program {pay} failed"]}
    v21 = {"err": None, "logs": [f"Program {pay} invoke [1]", "Program log: knos2:version 1"]}
    assert cap.chain_problems(data, "rpc", rpc(v20)) == []
    assert cap.chain_problems(data, "rpc", rpc(v21)) == ["knos_pay: devnet runs 2.1, the manifest says 2.0: move `on_chain`, then the stages that waited for it"]
    assert cap.chain_problems(data, "rpc", rpc(v20, gone={data["programs"]["knos_meter"]["id"]})) == [f"knos_meter: no program at {data['programs']['knos_meter']['id']} on devnet"]
    assert cap.chain_problems(data, "rpc", rpc(v20, failed={sig})) == [f"fund_by_comment: the transaction {sig[:12]}... failed"]
    assert cap.chain_problems(data, "rpc", rpc(v20, failed={"missing"})) == [f"pay_on_merge: the transaction {other[:12]}... is not on devnet"]
    assert any("did not reach the program" in line for line in cap.chain_problems(data, "rpc", rpc({"err": "AccountNotFound", "logs": []})))


def test_the_readme_and_the_document_are_what_render_writes(tmp_path):
    text, full = (ROOT / "README.md").read_text(encoding="utf-8"), (ROOT / cap.FULL).read_text(encoding="utf-8")
    assert text.count(cap.START) == text.count(cap.END) == full.count(cap.START) == full.count(cap.END) == 1
    assert cap.rendered(text, cap.summary(DATA)) == text and cap.rendered(full, cap.table(DATA, "../")) == full and cap.render(check=True) == []
    # README.md names every capability under its stage; the document has one row each, with the evidence
    block = text[text.index(cap.START):text.index(cap.END)]
    assert all(f"`{c['id']}`" in block for c in DATA["capabilities"]) and "**Reproduced by someone else:** none recorded yet." in block
    exercised = block[block.index("**Exercised on devnet:**"):block.index("**Deployed on devnet:**")]
    assert all(f"`{cid}`" in exercised for cid in EXERCISED) and exercised.count("`") == 2 * len(EXERCISED)
    deployed = block[block.index("**Deployed on devnet:**"):block.index("**Tested locally:**")]
    assert "`pay_on_merge`" in deployed and "`work_orders`" not in deployed
    rows = full[full.index(cap.START):full.index(cap.END)]
    assert all(c["what"] in rows for c in DATA["capabilities"]) and rows.count("\n| ") == len(DATA["capabilities"]) + 1
    assert "](../programs-v2/knos_pay/src/order.rs)" in rows
    # a manifest that changed is seen, written, and then the same again
    for rel in ("README.md", "docs/capabilities.json", cap.FULL):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    data = _with("work_orders", what="A work order, said another way.", stage=None, evidence={})
    (tmp_path / "docs" / "capabilities.json").write_text(json.dumps(data), encoding="utf-8")
    assert cap.render(tmp_path, check=True) == ["README.md", cap.FULL] and "said another way" not in (tmp_path / cap.FULL).read_text(encoding="utf-8")
    assert cap.render(tmp_path) == ["README.md", cap.FULL] and cap.render(tmp_path) == []
    assert "A work order, said another way. | not built |" in (tmp_path / cap.FULL).read_text(encoding="utf-8")
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "`work_orders`" in readme[readme.index("**Not built:**"):readme.index(cap.END)]


def test_the_site_module_renders_the_same_rows_and_filters_by_stage():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = """
import { renderCapabilities, tableHtml, counts, filtered, STAGES } from %s;
import { readFileSync } from "node:fs";
const data = JSON.parse(readFileSync(%s, "utf8"));
const select = { value: "all", onchange: null }, table = { innerHTML: "" };
const el = { innerHTML: "", querySelector: (q) => (q === ".capabilities-stage" ? select : table) };
renderCapabilities(el, data);
select.value = "deployed"; select.onchange();
const evil = { capabilities: [{ id: "x", what: "<img src=x onerror=alert(1)>.", stage: "tested", note: "<b>",
  evidence: { implemented: { path: "javascript:alert(1)" }, tested: { test: "../../x" } } }] };
console.log(JSON.stringify({ stages: STAGES, counts: counts(data), all: filtered(data, "all").length, rows: (table.innerHTML.match(/<tr data-stage="deployed"/g) || []).length,
  other: (table.innerHTML.match(/<tr data-stage="(?!deployed)/g) || []).length, options: (el.innerHTML.match(/<option /g) || []).length,
  none: tableHtml(data, "reproduced"), evil: tableHtml(evil) }));
""" % (json.dumps((ROOT / "web" / "capabilities.js").as_uri()), json.dumps(str(ROOT / "docs" / "capabilities.json")))
    out = json.loads(subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True, timeout=60).stdout)
    want = {s: sum(1 for c in DATA["capabilities"] if c["stage"] == s) for s in cap.STAGES}
    assert out["stages"] == list(cap.STAGES) and out["all"] == len(DATA["capabilities"])
    assert {s: out["counts"][s] for s in cap.STAGES} == want and out["counts"]["none"] == sum(1 for c in DATA["capabilities"] if c["stage"] is None)
    assert out["rows"] == want["deployed"] > 0 and out["other"] == 0 and out["options"] == 7
    assert "Nothing is at this stage yet." in out["none"]
    assert "<img" not in out["evil"] and "<b>" not in out["evil"] and "href=" not in out["evil"]       # text from the manifest is never markup, and only a plain path is linked
