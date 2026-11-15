"""Receipt version 6 (docs/reference/RECEIPT.md, Version 6): the same receipt as version 5, its upgrade multisig line
saying the 8-day time lock in force since 11 Oct 2026. Its vectors (docs/receipt/vectors.v6.json, conformance kit 5)
are written from the version 5 vectors here: `python tests/test_receipt_v6.py --write`. Versions 1 to 5 still check."""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from knos import receipt as rc  # noqa: E402

V5 = ROOT / "docs" / "receipt" / "vectors.v5.json"
FILE = ROOT / "docs" / "receipt" / "vectors.v6.json"
NOTE = ("Conformance vectors of the acceptance receipt, version 6 (docs/reference/RECEIPT.md, Version 6): each valid "
        "receipt is version 5's of the same index as version 6, the upgrade multisig's line saying the 8-day time lock. "
        "A reader must accept every valid receipt with its digest, verdict and assurance, and refuse every invalid one.")


def valid() -> list[dict]:
    out = []
    for v in json.loads(V5.read_text(encoding="utf-8"))["valid_v5"]:
        r = rc.build6(v["receipt"])
        out.append({"name": v["name"], "sha256": rc.digest(r), "verdict": v["verdict"], "authorises_payment": v["authorises_payment"],
                    "assurance": v["assurance"], "receipt": r})
    return out


def invalid() -> list[dict]:
    five = json.loads(V5.read_text(encoding="utf-8"))["invalid_v5"]
    ok = valid()
    signed = next(i for i, v in enumerate(ok) if rc.NEW_TRUST in v["receipt"]["trust_remaining"])
    t = ok[signed]["receipt"]["trust_remaining"]
    gone = [x for x in t if x != rc.NEW_TRUST]
    return [*five, {"name": "a version 6 receipt without the upgrade multisig's line", "of": signed, "set": {"trust_remaining": gone},
                    "why": "a signed receipt names the upgrade multisig and its 8-day time lock"}]


def _set(r: dict, changes: dict) -> dict:
    r = copy.deepcopy(r)
    for path, value in changes.items():
        steps, node = path.split("."), r
        for s in steps[:-1]:
            node = node[int(s)] if isinstance(node, list) else node[s]
        node[int(steps[-1]) if isinstance(node, list) else steps[-1]] = value
    return r


def test_the_vectors_are_the_ones_the_code_writes():
    assert json.loads(FILE.read_text(encoding="utf-8")) == {"note": NOTE, "valid_v6": valid(), "invalid_v6": invalid()}, "python tests/test_receipt_v6.py --write"


def test_every_valid_v6_receipt_checks_and_says_the_8_day_lock_and_every_invalid_one_is_refused():
    ok = valid()
    for v in ok:
        r = v["receipt"]
        assert r["version"] == 6 and rc.check(r) is None and rc.OLD_TRUST not in r["trust_remaining"]
        assert rc.verdict_of(r) == v["verdict"] and rc.authorises_payment(r) == v["authorises_payment"]
        assert rc.as5(r) == json.loads(V5.read_text(encoding="utf-8"))["valid_v5"][ok.index(v)]["receipt"]
    assert any(rc.NEW_TRUST in v["receipt"]["trust_remaining"] for v in ok)
    for v in invalid():
        assert rc.check(_set(ok[v["of"]]["receipt"], v["set"])) is not None, v["name"]


def test_older_versions_still_check_and_a_v6_with_the_old_line_is_refused():
    for f, group in (("vectors.json", "valid"), ("vectors.json", "valid_v2"), ("vectors.json", "valid_v3"),
                     ("vectors.v4.json", "valid_v4"), ("vectors.v5.json", "valid_v5")):
        for v in json.loads((ROOT / "docs" / "receipt" / f).read_text(encoding="utf-8"))[group]:
            assert rc.check(v["receipt"]) is None, (f, group, v["name"])
    r = next(v["receipt"] for v in valid() if rc.NEW_TRUST in v["receipt"]["trust_remaining"])
    old = {**r, "trust_remaining": [rc.OLD_TRUST if x == rc.NEW_TRUST else x for x in r["trust_remaining"]]}
    assert "8-day time lock" in rc.check(old)


def test_new_receipts_are_version_6():
    import inspect

    from knos import bundle, flow
    assert "rc.build6(rc.build5(" in inspect.getsource(bundle) and "rc.build6(rc.build5(" in inspect.getsource(flow)
    assert rc.trust_now("github", "merge", "repository")[-1] == rc.NEW_TRUST


if __name__ == "__main__" and "--write" in sys.argv:
    FILE.write_text(json.dumps({"note": NOTE, "valid_v6": valid(), "invalid_v6": invalid()}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print("wrote", FILE.name)


SCHEMA = ROOT / "docs" / "receipt" / "acceptance-receipt.v6.schema.json"


def schema() -> dict:
    five = json.loads((ROOT / "docs" / "receipt" / "acceptance-receipt.v5.schema.json").read_text(encoding="utf-8"))
    return {**five, "$id": five["$id"].replace(".v5.", ".v6."), "title": "Knos acceptance receipt, version 6",
            "description": "Version 5, its trust_remaining naming the upgrade multisig's 8-day time lock (the time lock in force since 11 Oct "
                           "2026); version 5 named the delay of its time. The lines are the ones knos.receipt.trust_now gives; `check` compares them.",
            "properties": {**five["properties"], "version": {"const": 6}}}


def test_the_schema_is_the_one_the_code_writes():
    assert json.loads(SCHEMA.read_text(encoding="utf-8")) == schema(), "python tests/test_receipt_v6.py --write"


def test_the_attestation_script_takes_a_version_6_receipt_and_attests_its_own_digest(tmp_path):
    """scripts/sas_receipt.mjs fields() reads a paid version 6 vector (its fields are version 5's) and attests the
    version 6 receipt's own digest. Needs Node, no package of the script's."""
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("needs Node")
    six = [v for v in json.loads(FILE.read_text(encoding="utf-8"))["valid_v6"] if v["receipt"]["transaction"] is not None]
    assert six, "no paid version 6 receipt among the vectors"
    code = ("import fs from 'node:fs';\n"
            f"import {{ fields }} from {json.dumps((ROOT / 'scripts' / 'sas_receipt.mjs').as_uri())};\n"
            f"const v = JSON.parse(fs.readFileSync({json.dumps(str(FILE))}, 'utf8'));\n"
            "console.log(JSON.stringify(v.valid_v6.filter((x) => x.receipt.transaction !== null)"
            ".map((x) => Buffer.from(fields(x.receipt).receipt_sha256).toString('hex'))));\n")
    (tmp_path / "fields6.mjs").write_text(code, encoding="utf-8")
    done = subprocess.run([node, str(tmp_path / "fields6.mjs")], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [v["sha256"] for v in six] == [rc.digest(v["receipt"]) for v in six]

if __name__ == "__main__" and "--write" in sys.argv:
    SCHEMA.write_text(json.dumps(schema(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print("wrote", SCHEMA.name)
