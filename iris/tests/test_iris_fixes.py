"""The IRIS fixes that need no IRIS image: the repository check on /proof (knos_iris.bridge.repo_mismatch, which
Knos.Iris.REST.Api calls through Embedded Python), and what the class, module and README sources must say.
    python -m pytest -q iris/tests/test_iris_fixes.py"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IRIS = ROOT / "iris"
sys.path[:0] = [str(ROOT / "src"), str(IRIS / "python")]

from knos_iris import bridge  # noqa: E402

FIX = IRIS / "fixtures"
CLS = IRIS / "src" / "Knos" / "Iris"


def _pass_run(full_name="example/shop"):
    body = json.loads((FIX / "checkruns" / "pass.json").read_text(encoding="utf-8"))
    body["repository"]["full_name"] = full_name
    return body


def _why(brief_id, brief, proof):
    return bridge.repo_mismatch(brief_id, json.dumps(brief), json.dumps(proof))


def test_proof_from_the_locked_repository_is_accepted():
    brief = json.loads((FIX / "briefs" / "code.json").read_text(encoding="utf-8"))
    assert _why("github:example/shop", brief, {"id": "github:example/shop", "kind": "checkrun", "payload": _pass_run()}) == ""
    assert _why("github:example/shop", brief, {"id": "github:example/shop", "kind": "checkrun", "payload": _pass_run("Example/Shop")}) == ""


def test_proof_from_another_repository_is_refused():
    brief = json.loads((FIX / "briefs" / "code.json").read_text(encoding="utf-8"))
    why = _why("github:example/shop", brief, {"id": "github:example/shop", "kind": "checkrun", "payload": _pass_run("attacker/fork")})
    assert "attacker/fork" in why and "example/shop" in why
    # a repository named at the top of the body counts the same
    assert _why("github:example/shop", brief, {"id": "github:example/shop", "repository": "attacker/fork", "payload": {}}) != ""


def test_the_brief_s_own_repository_field_wins_over_its_id():
    brief = {"repository": "lab/site-7", "milestones": []}
    assert _why("site-7", brief, {"payload": {"repository": {"full_name": "lab/site-7"}}}) == ""
    assert _why("site-7", brief, {"payload": {"repository": {"full_name": "lab/site-8"}}}) != ""


def test_a_proof_that_names_no_repository_or_a_brief_with_none_is_not_refused_here():
    assert _why("github:example/trap", {}, {"payload": {"check_run": {"id": 9, "name": "test", "conclusion": "success"}}}) == ""
    assert _why("lab-glucose", {"milestones": []}, {"kind": "observation", "payload": {"resourceType": "Observation"}}) == ""
    assert _why("github:example/shop", {}, {"payload": "MSH|^~\\&|not json"}) == ""


def test_api_refuses_a_mismatch_and_builds_the_trace_link_from_the_request():
    api = (CLS / "REST" / "Api.cls").read_text(encoding="utf-8")
    assert "RepoMismatch" in api and "409" in api
    assert "http://localhost:52773/csp" not in api
    assert 'CgiEnvs("HTTP_HOST")' in api and "KNOS_IRIS_PORTAL" in api


def test_three_429s_return_an_error_never_ok_with_an_empty_result():
    src = (CLS / "Adapter" / "SolanaRpcOutbound.cls").read_text(encoding="utf-8")
    assert 'if try=3 return $$$ERROR($$$GeneralError,"devnet RPC 429 three times")' in src
    assert "quit:try=3" not in src


def test_the_ipm_module_installs_outside_this_image():
    mod = (IRIS / "module.xml").read_text(encoding="utf-8")
    assert "/home/irisowner" not in mod
    for need in ("../src/knos/", "python/knos_iris/", "java/", "fixtures/"):
        assert f'Name="{need}"' in mod, need
    assert re.search(r"solders", (IRIS / "requirements.txt").read_text(encoding="utf-8"))
    setup = (CLS / "Setup.cls").read_text(encoding="utf-8")
    assert "ClassMethod Jar(" in setup and "javac" in setup


def test_readme_keeps_the_idea_link_in_plain_words():
    text = (IRIS / "README.md").read_text(encoding="utf-8")
    assert "https://ideas.intersystems.com/ideas/DPI-I-689" in text
    line = next(x for x in text.splitlines() if "DPI-I-689" in x)
    assert not re.search(r"contest|bonus|judge|prize|demo|hackathon", line, re.I), line
    assert "—" not in text and not re.search(r"escrow", text, re.I)
