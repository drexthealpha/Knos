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
    # `programs` is the public program ids and nothing else: the four of program_ids.json and upgrade_gate's declare_id!
    public = {**{n: ids[n] for n in ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey")}, "upgrade_gate": "2DfVEuBMWvvh3kXZaQwk2SoszJsoV1PTiK1VGCkB55HW"}
    assert cap.public_ids() == public and {n: p["id"] for n, p in DATA["programs"].items()} == public
    for c in DATA["capabilities"]:
        assert set(c) <= {"id", "what", "stage", "evidence", "note"} and {"id", "what", "stage", "evidence"} <= set(c), c["id"]
        assert c["stage"] in (None, *cap.STAGES) and c["what"].endswith(".") and set(c["evidence"]) <= set(cap.STAGES)
    assert len(BY_ID) == len(DATA["capabilities"]) >= 40


def test_every_stage_has_its_evidence():
    assert cap.problems(DATA) == []
    assert cap.main(["check"]) == 0


# What the 0.3.14 rehearsal ran on devnet, on staging deployments of this build (docs/CAPABILITIES.md): not the public ids
REHEARSED = {"work_orders", "order_pay", "single_use_tokens", "fee_tiers", "reserve_cancel", "warranty_revert", "order_auto_accept", "tests_mode",
             "order_quorum", "order_challenge", "meter_batch", "meter_seller_claim", "passkey_funder", "passkey_fund_relay", "buyer_page",
             "x402_knos_order"}
# the rehearsal's own addresses (knos_oidc, knos_pay, knos_meter, knos_passkey): never evidence of a stage
STAGING_IDS = {"iosu8ARUNvvruHPCcMWQ5rqsnJewzBxcPXajSpoHqXd", "FJJtqcRjQ9ATx37sBTCLUBxBqLUA9aQgSTLAsZynqtnH",
               "7MzKH2Mm7hUD4g9SdCMmL1MR4SBPBUaZXP4RwiFs8ZGo", "8YwdomJwYQJV7adkqgNyehdZ3tZhpTsp6SFUNfTsKKxk"}


def test_nothing_is_deployed_or_exercised_on_a_program_that_is_not_a_public_id():
    """The release's rule: nothing is marked deployed or exercised that is not on the public program ids, at the version
    devnet runs there. A staging deployment of a build (the 0.3.14 rehearsal's) is in no `programs` entry and in no
    capability's evidence; what ran there is in the note, and the capability is `tested`."""
    public = cap.public_ids()
    assert not STAGING_IDS & set(public.values())
    assert not any(n.endswith("_staging") or p["id"] in STAGING_IDS for n, p in DATA["programs"].items())
    for c in DATA["capabilities"]:
        ev = c["evidence"]
        assert not (STAGING_IDS & {str(v) for e in ev.values() for v in e.values()}), c["id"]
        if c["stage"] in ("deployed", "exercised", "reproduced"):
            dep, p = ev["deployed"], DATA["programs"][ev["deployed"]["program"]]
            assert public[dep["program"]] == dep["id"] == p["id"], c["id"]
            assert p["versions"].index(dep["version"]) <= p["versions"].index(p["on_chain"]), c["id"]
        if c["stage"] in ("exercised", "reproduced"):
            assert cap.ids_of(c) == "public" and ev["exercised"].get("ids", "public") == "public", c["id"]


def test_the_manifest_claims_no_more_than_is_true_today():
    """2.1 of knos_pay and knos_oidc is proposed, not executed: on the public programs what it adds is tested and no
    more. What the release's rehearsal ran on devnet ran on staging programs of its own, never on a public one: those
    capabilities are `tested`, and each one's note gives its transaction and says it was a staging rehearsal. Nothing is
    exercised, and no document links an outside run, so nothing is reproduced."""
    if DATA["programs"]["knos_pay"]["on_chain"] != "2.0":
        pytest.skip("the upgrade has executed and scripts/exercise_public.py record moved the manifest; tests/test_exercise_public.py holds what record may write")
    assert DATA["programs"]["knos_pay"]["on_chain"] == DATA["programs"]["knos_oidc"]["on_chain"] == "2.0"
    assert DATA["programs"]["knos_meter"]["on_chain"] == DATA["programs"]["knos_passkey"]["on_chain"] == "1.0"
    for cid in ("seller_settle", "neutral_attest", "arbiter_rule", "top_up", "assign", "plans", "org_balance_limits", "verify_any_issuer", "holdback_release"):
        assert BY_ID[cid]["stage"] == "tested", cid
    assert {c["stage"] for c in DATA["capabilities"]} <= {None, "implemented", "tested", "deployed"}
    assert {c["id"] for c in DATA["capabilities"] if c["stage"] == "exercised"} == set()
    assert all(c["evidence"]["deployed"]["version"] in ("2.0", "1.0") for c in DATA["capabilities"] if c["stage"] == "deployed")
    rehearsal = (ROOT / cap.FULL).read_text(encoding="utf-8").split("## The 0.3.14 rehearsal on devnet", 1)[1]
    assert all(i in rehearsal for i in STAGING_IDS)
    for cid in REHEARSED:
        c = BY_ID[cid]
        assert c["stage"] == "tested" and set(c["evidence"]) == {"implemented", "tested"}, cid
        assert c["note"].startswith("Rehearsed on ") and "staging deployment" in c["note"] and "not on the public program ids" in c["note"], cid
        [sig] = cap._SIG.findall(c["note"])
        assert sig in rehearsal, cid
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
    # a staging deployment is never evidence: not as a program, not as deployed evidence, not as an exercised run
    staging = {"program": "knos_pay_staging", "id": "FJJtqcRjQ9ATx37sBTCLUBxBqLUA9aQgSTLAsZynqtnH", "version": "2.1"}
    listed = copy.deepcopy(DATA)
    listed["programs"]["knos_pay_staging"] = {"id": staging["id"], "versions": ["2.1"], "on_chain": "2.1"}
    cases["programs.knos_pay_staging: not a public program"] = listed
    rehearsed = _with("work_orders", stage="exercised", evidence={**BY_ID["work_orders"]["evidence"], "deployed": staging, "exercised": {"signature": sig}})
    rehearsed["programs"]["knos_pay_staging"] = listed["programs"]["knos_pay_staging"]
    cases["deployed: knos_pay_staging FJJtqcRjQ9ATx37sBTCLUBxBqLUA9aQgSTLAsZynqtnH is not a public program id"] = rehearsed
    cases["exercised: the transaction ran on staging program ids"] = rehearsed
    cases["deployed: knos_pay_staging FJJtqcRjQ9ATx37sBTCLUBxBqLUA9aQgSTLAsZynqtnH is not a public program id: a staging deployment is never evidence for deployed"] = _with(
        "work_orders", stage="deployed", evidence={**BY_ID["work_orders"]["evidence"], "deployed": staging})
    cases["deployed: knos_pay FJJtqcRjQ9ATx37sBTCLUBxBqLUA9aQgSTLAsZynqtnH is not a public program id"] = _with(       # a public name at another address
        "work_orders", stage="deployed", evidence={**BY_ID["work_orders"]["evidence"], "deployed": {**staging, "program": "knos_pay"}})
    cases["exercised: `ids` says 'staging'; only `public` is evidence"] = _with(
        "fund_by_comment", stage="exercised", evidence={**BY_ID["fund_by_comment"]["evidence"], "exercised": {"signature": sig, "ids": "staging"}})
    moved = copy.deepcopy(DATA)
    moved["programs"]["knos_pay"]["id"] = staging["id"]
    cases["programs.knos_pay: the address is not its public program id"] = moved
    for said, data in cases.items():
        assert any(said in line for line in cap.problems(data)), (said, cap.problems(data))
    assert cap.main(["check"]) == 0 and cap.ids_of(rehearsed["capabilities"][[c["id"] for c in rehearsed["capabilities"]].index("work_orders")]) == "staging"
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
    # README.md names the capabilities above `tested` under their stage and sends the rest to the document, which has one row each
    block = text[text.index(cap.START):text.index(cap.END)]
    above = [c for c in DATA["capabilities"] if c["stage"] in cap.STAGES[2:]]
    assert all(f"`{c['id']}`" in block for c in above) and block.count("`") == 2 * len(above) + 2      # and the manifest's name, once
    assert "**Reproduced by someone else:** none recorded yet." in block and f"]({cap.FULL})" in block
    exercised = block[block.index("**Exercised on devnet:**"):block.index("**Deployed on devnet:**")]
    now = [c["id"] for c in DATA["capabilities"] if c["stage"] == "exercised"]
    assert all(f"`{cid}`" in exercised for cid in now) and exercised.count("`") == 2 * len(now)
    assert not now and "**Exercised on devnet:** none recorded yet." in block
    # README.md and the document say that a stage above `tested` is a run at a public program id, and where the rehearsal is
    assert block.count(cap.PUBLIC_ONLY) == 1 and full[full.index(cap.START):full.index(cap.END)].count(cap.PUBLIC_ONLY) == 1
    assert {cap.ids_of(c) for c in DATA["capabilities"] if c["stage"] == "exercised"} <= {"public"} and cap.ids_of(BY_ID["pay_on_merge"]) is None
    # what the rehearsal ran is tested locally, never exercised or deployed: README.md names none of it
    assert not any(f"`{cid}`" in block for cid in REHEARSED)
    assert "`pay_on_merge`" in block and "`work_orders`" not in block
    rows = full[full.index(cap.START):full.index(cap.END)]
    assert all(f"| {BY_ID[cid]['what']} | tested locally | " in rows for cid in REHEARSED) and "_staging" not in rows
    assert all(c["what"] in rows for c in DATA["capabilities"]) and rows.count("\n| ") == len(DATA["capabilities"]) + 1
    assert "](../programs-v2/knos_pay/src/order.rs)" in rows
    # a manifest that changed is seen, written, and then the same again
    for rel in ("README.md", "docs/capabilities.json", cap.FULL):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    data = _with("work_orders", what="A work order, said another way.", stage=None, evidence={})
    (tmp_path / "docs" / "capabilities.json").write_text(json.dumps(data), encoding="utf-8")
    assert cap.render(tmp_path, check=True) == [cap.FULL] and "said another way" not in (tmp_path / cap.FULL).read_text(encoding="utf-8")
    assert cap.render(tmp_path) == [cap.FULL] and cap.render(tmp_path) == []
    assert "A work order, said another way. | not built |" in (tmp_path / cap.FULL).read_text(encoding="utf-8")
    # a capability that leaves a stage above `tested` leaves README.md too
    data = _with("pay_on_merge", stage="tested")
    (tmp_path / "docs" / "capabilities.json").write_text(json.dumps(data), encoding="utf-8")
    assert "README.md" in cap.render(tmp_path) and "`pay_on_merge`" not in (tmp_path / "README.md").read_text(encoding="utf-8")


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
