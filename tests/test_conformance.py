"""The conformance kit (conformance/): its vectors are the ones the manifest names, Knos's own Python passes every
case, the JavaScript client passes every case it implements, a wrong implementation is caught, and
docs/CONFORMANCE.md says what the kit holds."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "conformance"
spec = importlib.util.spec_from_file_location("conformance_run", KIT / "run.py")
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)
DOC = (ROOT / "docs" / "CONFORMANCE.md").read_text(encoding="utf-8")
PYTHON = [sys.executable, str(KIT / "impl" / "knos_python.py")]

# Kit version 1, written down a second time: a vector cannot be changed by editing the kit alone.
KIT_1 = {
    "receipt": "5164675d900fb75e421f29d37d58526403cd0a27b7773962be2a3db98bf94eea",
    "terms": "b761f7cb3fc7e2c7ea8a43231c2ec917b4f331cb1b436cfba2d67c982d9bd7cb",
    "ledger": "cc98067fd67431d239d1cebafa4841da0a71bf0953d61b4438f4bbaff21e61a4",
    "audiences": "b5e8429b6a00ec45169940ab0f14d4ff322b784552312090d8456324b4945466",
    "statement": "d0fbcb03167af48c8a3d0249bb5fa582af5d84fb744716a6cf996ffbce5b5b50",
}
# What the JavaScript client does not do (conformance/impl/knos_js.mjs says why); every other operation it passes.
JS_NOT_IMPLEMENTED = {"receipt.check", "receipt.verdict", "receipt.assurance", "statement.text"}


def test_the_vectors_are_the_ones_kit_version_1_names_and_every_case_is_well_formed():
    m = kit.manifest()
    named = {e["format"]: e["sha256"] for e in m["formats"]}
    assert m["kit"] == 4 and {k: named[k] for k in KIT_1} == KIT_1 and set(named) - set(KIT_1) == {"receipt4", "receipt5", "ids", "ledger2"}     # versions 2 to 4 added four, changed none
    assert named["receipt4"] == "8a7541ea1e249d438ae6e07572082e754087c62c275de57451fe6152975d8dc2"                # version 5 of the receipt did not touch version 4's vectors
    todo = kit.cases()
    assert len({c["id"] for c in todo}) == len(todo) == sum(e["cases"] for e in m["formats"])
    for e in m["formats"]:
        mine = [c for c in todo if c["format"] == e["format"]]
        assert {c["op"] for c in mine} == set(e["ops"]) and len(mine) == e["cases"] >= 8, e["format"]
        assert (KIT / e["file"]).resolve().is_file()
    for c in todo:
        assert set(c["expect"]) in ({"output"}, {"refused", "why"}, {"refused"}) and c["name"] and "." in c["op"]
    assert sum("refused" in c["expect"] for c in todo) >= 50                 # what must be refused is half of a format
    receipts = json.loads((ROOT / "docs" / "receipt" / "vectors.json").read_text(encoding="utf-8"))
    assert sum(len(receipts[g]) for g in m["formats"][0]["groups"]) == 44    # reused, not copied: the kit holds no receipt of its own
    assert not list(KIT.glob("vectors/receipt*"))
    four = json.loads((ROOT / "docs" / "receipt" / "vectors.v4.json").read_text(encoding="utf-8"))
    assert {v["verdict"] for v in four["valid_v4"]} == {"accepted", "rejected", "insufficient_evidence", "disputed"}
    assert all(v["authorises_payment"] == (v["verdict"] == "accepted") for v in four["valid_v4"]) and len(four["invalid_v4"]) >= 20
    billed = [c for c in todo if c["op"] == "ids.billed_once" and "output" in c["expect"]]
    assert any(len(c["input"]["evaluations"]) == 10 and len(c["expect"]["output"]) == 1 for c in billed)         # ten pull requests, one outcome
    assert any([e["verdict"] for e in c["input"]["evaluations"]] == ["accepted", "accepted"] and c["expect"]["output"] == [0] for c in billed)


def test_a_changed_vector_stops_the_run(monkeypatch):
    m = kit.manifest()
    m["formats"][1]["sha256"] = "0" * 64
    monkeypatch.setattr(kit, "manifest", lambda: m)
    with pytest.raises(kit.Changed, match="never change"):
        kit.cases()


def test_knos_python_passes_every_case_and_leaves_none_out():
    got = kit.run(PYTHON)
    for name, f in got["formats"].items():
        assert f["failed"] == [] and f["unsupported"] == 0 and f["passed"] == f["cases"], (name, f["failed"][:3], got["stderr"][-400:])
    assert got["unsupported_ops"] == []
    total = sum(f["cases"] for f in got["formats"].values())
    assert re.search(rf"^\| Python [^|]*\| {total} \| 0 \| 0 \|$", DOC, re.M)             # the page's own count
    done = subprocess.run([sys.executable, str(KIT / "run.py"), "--impl", " ".join(f'"{p}"' for p in PYTHON), "--require-all"],
                          capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert done.returncode == 0 and "FAILED" not in done.stdout and "not implemented" not in done.stdout, done.stdout + done.stderr


def _node():
    node = shutil.which("node")
    if not node:
        pytest.skip("needs Node")
    major = int(subprocess.run([node, "-p", "process.versions.node.split('.')[0]"], capture_output=True, text=True, encoding="utf-8", timeout=60).stdout.strip() or 0)
    if major < 22:
        pytest.skip("the adapter reads large whole numbers from the input's own text, which needs Node 22")
    return node


def test_the_javascript_client_passes_every_case_it_implements():
    got = kit.run([_node(), str(KIT / "impl" / "knos_js.mjs")])
    assert [x for f in got["formats"].values() for x in f["failed"]] == [], got["stderr"][-600:]
    assert set(got["unsupported_ops"]) == JS_NOT_IMPLEMENTED
    passed = {name: f["passed"] for name, f in got["formats"].items()}
    assert all(passed.values()), passed                                      # something of every format
    assert sum(passed.values()) == sum(f["cases"] - f["unsupported"] for f in got["formats"].values()) >= 70
    done, left = sum(passed.values()), sum(f["unsupported"] for f in got["formats"].values())
    assert re.search(rf"^\| JavaScript [^|]*\| {done} \| {left} \| 0 \|$", DOC, re.M)
    source = (KIT / "impl" / "knos_js.mjs").read_text(encoding="utf-8")
    adapter = set(re.findall(r'^  "([a-z_.0-9]+)":', source.split("const ADAPTER")[1], re.M))
    assert adapter == {"receipt.digest", "ledger.deliverable_id", "statement.hash"} | {c["op"] for c in kit.cases() if c["format"] in ("ids", "ledger2")}     # what the SDK has no function for
    by_adapter = sum(1 for c in kit.cases() if c["op"] in adapter)
    assert f"{done - by_adapter} are answered by functions `sdk/settle` exports and {by_adapter} by a few lines in the adapter" in DOC
    for op in adapter | JS_NOT_IMPLEMENTED:
        assert f"`{op}`" in DOC, op                                          # the page says which, by name


WRONG = '''import json, sys
for line in sys.stdin:
    c = json.loads(line)
    if c["op"] == "ledger.eval_id":
        print(json.dumps({"id": c["id"], "output": "00" * 32}))            # a wrong hash
    elif c["op"] == "terms.canonical":
        print(json.dumps({"id": c["id"], "output": {"json": "{}", "sha256": ""}}))   # accepts what must be refused
    elif c["op"] == "statement.hash":
        print(json.dumps({"id": c["id"], "refused": True}))                   # refuses what is valid
    elif c["op"] == "ledger.chain_hash":
        pass                                                                  # says nothing
    else:
        print(json.dumps({"id": c["id"], "unsupported": True}))
'''


def test_a_wrong_implementation_is_caught_case_by_case(tmp_path):
    impl = tmp_path / "wrong.py"
    impl.write_text(WRONG, encoding="utf-8")
    got = kit.run([sys.executable, str(impl)])
    why = {x["id"]: x["why"] for f in got["formats"].values() for x in f["failed"]}
    by_op = {c["id"]: c for c in kit.cases()}
    assert {by_op[i]["op"] for i in why} == {"ledger.eval_id", "terms.canonical", "statement.hash", "ledger.chain_hash"}
    assert any(w.startswith("answered") for w in why.values()) and any(w.startswith("accepted what must be refused") for w in why.values())
    assert "refused what is valid" in why.values() and "no answer" in why.values()
    assert got["formats"]["receipt"]["unsupported"] == got["formats"]["receipt"]["cases"] and got["formats"]["receipt"]["failed"] == []
    command = f'"{sys.executable}" "{impl}"'
    assert kit.main(["--impl", command, "--json"]) == 1
    only_unsupported = tmp_path / "nothing.py"
    only_unsupported.write_text('import json, sys\nfor line in sys.stdin:\n    print(json.dumps({"id": json.loads(line)["id"], "unsupported": True}))\n', encoding="utf-8")
    command = f'"{sys.executable}" "{only_unsupported}"'
    assert kit.main(["--impl", command, "--json"]) == 0 and kit.main(["--impl", command, "--json", "--require-all"]) == 1


def test_the_vectors_are_what_knos_computes_today():
    """The expected values were written once from this code; this holds the code to them (a format changed by accident
    fails here before it fails for someone else)."""
    sys.path.insert(0, str(ROOT / "src"))
    from knos import ledger, terms
    by_op: dict[str, list] = {}
    for c in kit.cases():
        by_op.setdefault(c["op"], []).append(c)
    for c in by_op["terms.hash"]:
        assert terms.canonical(c["input"]["terms"]).decode("ascii") == c["expect"]["output"]["json"]
        assert json.loads(c["expect"]["output"]["json"]) == c["input"]["terms"]            # terms.hash cases are already canonical
        assert len(c["expect"]["output"]["json"]) <= terms.MAX_BYTES
    text = next(c for c in by_op["statement.text"])
    assert ledger.statement(ledger.load(text["input"]["ledger"]), text["input"]["month"], rate=50_000, free=10_000) == text["expect"]["output"]      # the Meter price of the vector's day, which a statement prints
    assert any(c["input"]["statement"] == text["expect"]["output"] and c["expect"]["output"]["agrees"] for c in by_op["statement.hash"])
    empty = next(c for c in by_op["ledger.batch_root_any"] if not c["input"]["ids"])
    assert empty["expect"]["output"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"   # sha256 of nothing (RFC 6962)


def test_the_page_states_the_promise_narrowly_and_names_every_format_with_its_versions():
    m = kit.manifest()
    for e in m["formats"]:
        row = re.search(rf"^\| {e['format']} \| ([^|]+) \| (\d+) \|", DOC, re.M)
        assert row, e["format"]
        assert [int(v) for v in re.findall(r"\d+", row.group(1))] == e["versions"] and int(row.group(2)) == e["cases"]
        for op in e["ops"]:
            assert f"`{op}`" in DOC, op
    assert f"{sum(e['cases'] for e in m['formats'])} cases" in DOC
    for words in ("never change", "a new version number", "keeps reading", "What is not promised", "instruction layouts", "outside review"):
        assert words in DOC, words
    assert "nobody outside Knos has run" in DOC.lower() or "nobody outside knos has run" in DOC.lower()
