"""The claims Knos can prove (near/claims/claims.json): each paper's link finds its claim, each claim's locked test is a
file whose sha256 a job locks, and that test passes agent A's code and fails agent B's, run the way the checker runs it."""
import hashlib
import json
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
        links = [near_live.link_of(c)] + ([f"https://arxiv.org/abs/{c['arxiv']}"] if c.get("arxiv") else [])   # a source with no DOI: its page
        for link in links:
            assert near_live.claim_look(link)["name"] == c["name"], link


def test_each_locked_test_passes_agent_a_and_fails_agent_b(tmp_path):
    """Run as the checker runs it (near/agents/checker.py run_test): the claim's module name, its data next to the test,
    its time limit. The first four tests print "Passed: " or "Failed: "; the space, simulation and hardware tests (U7)
    print their own lines, unchanged."""
    import checker
    for c in near_live.CLAIMS:
        a, b = near_live._solutions(c)
        test = near_live.CLAIMS[c]["test"]
        for code, should_pass in ((a, True), (b, False)):
            f = tmp_path / f"{c}-{should_pass}.py"
            f.write_text(code, encoding="utf-8")
            ok, said, _secs = checker.run_test(f, test)
            assert ok == should_pass, (c, should_pass, said)
            if c in ("hyperloglog", "jump-hash", "xor-filter", "morris-counter"):
                assert said.startswith("Passed: " if should_pass else "Failed: "), said


def test_an_ai_reviewer_can_only_make_a_verdict_stricter():
    f = near_live.final_verdict
    assert f(True) and f(True, True)                      # no reviewer, or one that agrees: the test decides
    assert not f(True, False)                             # a pass the reviewer rejects becomes a fail
    assert not f(False, True) and not f(False)            # a fail stays a fail, whatever the reviewer says
