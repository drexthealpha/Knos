"""The claims Knos can prove (near/claims/claims.json): each paper's link finds its claim, each claim's locked test is a
file whose sha256 a job locks, and that test passes agent A's code and fails agent B's, run the way the checker runs it."""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "apps" / "wanted"), str(ROOT / "near" / "agents")]

from knos_wanted import near_live  # noqa: E402


def test_every_claim_has_a_real_paper_link_and_a_locked_test():
    claims = json.loads((ROOT / "near" / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"]
    assert len(claims) >= 4 and len({c["name"] for c in claims}) == len(claims)
    import common
    tests = common.tests()
    for c in claims:
        sha = hashlib.sha256((ROOT / "near" / "agents" / "job" / c["test"]).read_bytes()).hexdigest()
        assert tests[sha] == c["test"]
        links = ["https://doi.org/" + c["doi"]] + ([f"https://arxiv.org/abs/{c['arxiv']}"] if c.get("arxiv") else [])
        for link in links:
            assert near_live.claim_look(link)["name"] == c["name"], link


def test_each_locked_test_passes_agent_a_and_fails_agent_b(tmp_path):
    for c in near_live.CLAIMS:
        a, b = near_live._solutions(c)
        test = near_live.CLAIMS[c]["test"]
        for code, should_pass in ((a, True), (b, False)):
            d = tmp_path / f"{c}-{should_pass}"
            d.mkdir()
            shutil.copy(ROOT / "near" / "agents" / "job" / test, d / test)
            (d / "solution.py").write_text(code, encoding="utf-8")
            p = subprocess.run([sys.executable, "-E", "-s", "-B", test], cwd=d, capture_output=True, text=True, timeout=60)
            said = (p.stdout + p.stderr).strip().splitlines()[-1]
            assert (p.returncode == 0) == should_pass, (c, should_pass, said)
            assert said.startswith("Passed: " if should_pass else "Failed: "), said
