"""The acceptance receipt (docs/RECEIPT.md): the reference checker and the JSON Schema accept the five conformance
vectors and give their digests, both refuse every invalid one for the reason it names, the page prints a vector, and
scripts/sas_receipt.mjs computes the same digest and builds the attestation's instructions (when its package is there)."""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from knos import receipt

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "docs" / "receipt" / "vectors.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "docs" / "receipt" / "acceptance-receipt.v1.schema.json").read_text(encoding="utf-8"))
# the rules of an invalid vector that JSON Schema cannot express (sums, hashes, relations between fields)
BEYOND_SCHEMA = {"shares that do not add up to 10000", "payees who received more than was paid", "a repository judge in another repository",
                 "a scope that is not the repository's", "a private order with a public judge"}


def _changed(v: dict) -> dict:
    r = copy.deepcopy(VECTORS["valid"][v["of"]]["receipt"])
    for path, value in v["set"].items():
        at, *rest = path.split(".")
        node = r
        for step in [at, *rest][:-1]:
            node = node[int(step)] if isinstance(node, list) else node[step]
        last = [at, *rest][-1]
        node[int(last) if isinstance(node, list) else last] = value
    return r


def test_five_receipts_are_valid_and_have_the_digests_the_vectors_give():
    assert len(VECTORS["valid"]) == 5 and len({v["name"] for v in VECTORS["valid"]}) == 5
    for v in VECTORS["valid"]:
        assert receipt.check(v["receipt"]) is None, v["name"]
        assert receipt.digest(v["receipt"]) == v["sha256"], v["name"]
        assert json.loads(receipt.canonical(v["receipt"])) == v["receipt"] and b" " not in receipt.canonical(v["receipt"]).split(b'"job_workflow_ref"')[0]
    kinds = {v["receipt"]["judge"]["kind"] for v in VECTORS["valid"]}
    assert kinds == set(receipt.JUDGES) and any(v["receipt"]["repository"] is None for v in VECTORS["valid"])
    assert {len(v["receipt"]["payees"]) for v in VECTORS["valid"]} == {1, 2, 4}
    # the first one is a payment the test build of knos_pay made (the x402 example's fixture): the same order, amounts and wallet
    fx = json.loads((ROOT / "examples" / "x402_attested" / "fixtures.json").read_text(encoding="utf-8"))
    first = VECTORS["valid"][0]["receipt"]
    said = " ".join(fx["paid"]["logs"])
    assert first["order"] == fx["order"]["address"] and f"amount={first['payees'][0]['amount']} to={first['payees'][0]['to']}" in said
    assert f"paid={first['amounts']['paid']} of={first['amounts']['of']} fee={first['amounts']['fee']} tip={first['amounts']['tip']} judge=0" in said


def test_every_invalid_receipt_is_refused_for_its_reason():
    assert len(VECTORS["invalid"]) == 9 and BEYOND_SCHEMA <= {v["name"] for v in VECTORS["invalid"]}
    for v in VECTORS["invalid"]:
        why = receipt.check(_changed(v))
        assert why is not None and v["why"] in why, (v["name"], why)
    for junk in (None, [], "receipt", {}, {"type": receipt.TYPE}):
        assert receipt.check(junk) is not None


def test_the_json_schema_agrees_with_the_checker():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    ok = jsonschema.Draft202012Validator(SCHEMA)
    for v in VECTORS["valid"]:
        assert not list(ok.iter_errors(v["receipt"])), v["name"]
    for v in VECTORS["invalid"]:
        assert bool(list(ok.iter_errors(_changed(v)))) == (v["name"] not in BEYOND_SCHEMA), v["name"]
    assert SCHEMA["properties"]["judge"]["properties"]["kind"]["enum"] == list(receipt.JUDGES)
    assert set(SCHEMA["properties"]["judge"]["properties"]["claims"]["required"]) == set(receipt.CLAIMS)


def test_the_page_prints_the_first_vector_and_says_what_was_not_confirmed():
    page = (ROOT / "docs" / "RECEIPT.md").read_text(encoding="utf-8")
    shown = json.loads(re.search(r"## Version 1\n\n```json\n(.*?)\n```", page, re.S).group(1))
    assert shown == VECTORS["valid"][0]["receipt"] and VECTORS["valid"][0]["sha256"] in page
    assert "What was **not** confirmed" in page and "no attestation was sent to devnet from here" in page
    script = (ROOT / "scripts" / "sas_receipt.mjs").read_text(encoding="utf-8")
    sas = re.search(r'export const SAS = "(\w+)"', script).group(1)
    assert sas in page and "sas-lib" in json.loads((ROOT / "scripts" / "package.json").read_text(encoding="utf-8"))["optionalDependencies"]
    for name, code in re.findall(r'\["(\w+)", (\d+)\]', script.split("export const FIELDS")[1].split("];")[0]):
        assert f"`{name}`" in page, name


def test_the_script_builds_the_attestation_and_its_digest_is_the_python_one(tmp_path):
    node = shutil.which("node")
    if not node or not (ROOT / "scripts" / "node_modules" / "sas-lib").is_dir():
        pytest.skip("needs Node 20 and the packages: npm ci --prefix scripts")
    v = VECTORS["valid"][1]
    (tmp_path / "receipt.json").write_text(json.dumps(v["receipt"]), encoding="utf-8")
    authority = "4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo"
    done = subprocess.run([node, "scripts/sas_receipt.mjs", str(tmp_path / "receipt.json"), "--authority", authority], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["dry_run"] is True and out["receipt_sha256"] == v["sha256"] and out["program"] == "22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG"
    assert [i["name"] for i in out["instructions"]] == ["create credential", "create schema", "create attestation"]
    assert all(i["program"] == out["program"] and i["accounts"][0] == {"pubkey": authority, "signer": True, "writable": True} for i in out["instructions"])
    data = bytes.fromhex(out["instructions"][2]["data"])
    assert bytes.fromhex(v["sha256"]) in data and v["receipt"]["order"].encode() in data and v["receipt"]["transaction"]["signature"].encode() in data
    # --send without a key, and a file that is not a receipt, are refused before anything is asked of a cluster
    for args, said in ((["--send"], "--send needs --keypair"),):
        bad = subprocess.run([node, "scripts/sas_receipt.mjs", str(tmp_path / "receipt.json"), *args], cwd=ROOT, capture_output=True, text=True, timeout=120)
        assert bad.returncode == 1 and said in bad.stderr
    (tmp_path / "other.json").write_text("{}", encoding="utf-8")
    bad = subprocess.run([node, "scripts/sas_receipt.mjs", str(tmp_path / "other.json")], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert bad.returncode == 1 and "not a Knos acceptance receipt" in bad.stderr
