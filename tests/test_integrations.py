"""What a bounty or work platform takes from this repository (docs/INTEGRATIONS.md): the knos-verify action and its
script against a stand-in for GitHub, the offline receipt verifier in Python and in TypeScript on one set of cases,
and the badge a platform shows beside a paid bounty."""
from __future__ import annotations

import ast
import base64
import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from _hub import Hub, run
from _settle import modulus, sign_jwt, signing_key
from knos import badge

ROOT = Path(__file__).resolve().parents[1]
ACTION, HOOK, BADGE = ROOT / ".github" / "actions" / "knos-verify", ROOT / "integrations" / "webhook", ROOT / "integrations" / "badge"
HEAD, MERGE = "a" * 40, "b" * 40


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _project() -> str:
    return re.search(r'(?m)^version = "(\d+\.\d+\.\d+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8")).group(1)


# ---- the action ---------------------------------------------------------------------------------------------------------

def _hub(body: str, head_runs: list, merge_runs: list | None = None, merged: bool = False) -> Hub:
    pull = {"number": 7, "body": body, "head": {"sha": HEAD}, "merged": merged, "merge_commit_sha": MERGE if merged else None}
    answers = {"repos/octo/widgets/pulls/7": pull,
               f"repos/octo/widgets/commits/{HEAD}/check-runs": {"total_count": len(head_runs), "check_runs": head_runs},
               f"repos/octo/widgets/commits/{HEAD}/status": {"statuses": []}}
    if merge_runs is not None:
        answers |= {f"repos/octo/widgets/commits/{MERGE}/check-runs": {"total_count": len(merge_runs), "check_runs": merge_runs},
                    f"repos/octo/widgets/commits/{MERGE}/status": {"statuses": []}}
    return Hub(answers)


def test_the_action_is_one_composite_step_with_a_pinned_install_and_no_secret():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load((ACTION / "action.yml").read_text(encoding="utf-8"))
    assert doc["runs"]["using"] == "composite" and set(doc["outputs"]) == {"passed", "verdict", "json"}
    setup, step = doc["runs"]["steps"]
    assert re.fullmatch(r"astral-sh/setup-uv@[0-9a-f]{40}", setup["uses"]) and setup["with"]["enable-cache"] is False
    # Knos comes from PyPI at exactly this tree's version (scripts/bump_version.py keeps the line in step), and the
    # script is the file beside the action
    assert f'--with "knos=={_project()}"' in step["run"] and step["env"]["SCRIPT"] == "${{ github.action_path }}/verify.py"
    assert (ACTION / "verify.py").is_file()
    # every input reaches the shell through the environment, never by being pasted into the script
    assert "${{" not in step["run"] and all(v.startswith("${{ ") for v in step["env"].values())
    text = (ACTION / "action.yml").read_text(encoding="utf-8")
    assert "secrets." not in text and "id-token" not in text.split("runs:")[1] and "pull_request_target" not in text.split("runs:")[1]
    assert set(doc["inputs"]) == {"pull-request", "repository", "checks", "commit", "fail", "token"}


def test_the_example_workflow_names_this_release_and_asks_for_read_only_permissions():
    yaml = pytest.importorskip("yaml")
    path = ROOT / "integrations" / "workflows" / "knos-verify.yml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    job = doc["jobs"]["knos-verify"]                 # the job's name starts with "knos": Knos never counts its own job as evidence
    assert doc["permissions"] == {} and set(job["permissions"].values()) == {"read"}
    # scripts/bump_version.py must rewrite this line with each release: its PINS need
    # r"drexthealpha/Knos/\.github/actions/knos-verify@v" + V
    assert job["steps"][0]["uses"] == f"drexthealpha/Knos/.github/actions/knos-verify@v{_project()}"
    exe = os.environ.get("ACTIONLINT") or shutil.which("actionlint")
    if exe and Path(exe).is_dir():
        exe = str(Path(exe) / "actionlint")
    if not exe or not Path(exe).is_file():
        pytest.skip("actionlint is not installed (put it on PATH, or name it in ACTIONLINT)")
    got = subprocess.run([exe, "-no-color", "-shellcheck=", "-pyflakes=", str(path)], cwd=str(ROOT), capture_output=True, text=True, check=False)
    assert got.returncode == 0, got.stdout + got.stderr


def test_the_script_gives_a_verdict_from_githubs_record_of_the_commit(tmp_path, monkeypatch, capsys):
    v = _load(ACTION / "verify.py", "knos_verify_action")
    green = [run("test"), run("lint"), run("knos-verify", "failure")]            # Knos's own job is never evidence
    # a true claim and two named checks that passed
    got = v.verdict("octo/widgets#7", ["test", "lint"], get=_hub("Fixes #3. All tests pass.", green))
    assert got["passed"] and got["checks"] == {"test": "passed", "lint": "passed"} and got["claim"]["verdict"] == "true"
    assert (got["schema"], got["pr"], got["commit"], got["at"], got["reasons"]) == ("knos.verify/1", "octo/widgets#7", HEAD, "head", [])
    # a claim that GitHub's record contradicts: refused, and the failed check's name is only inside `untrusted`
    red = [run("test", "failure"), run("lint")]
    got = v.verdict("octo/widgets#7", [], get=_hub("CI is green.", red))
    assert not got["passed"] and got["claim"]["verdict"] == "false" and got["untrusted"]["failed_checks"] == ["test"]
    assert "test" not in json.dumps({k: got[k] for k in got if k != "untrusted"})
    # no claim, but a named check failed, was skipped, is still running or never ran: each said as what it is
    runs = [run("test", "failure"), run("lint", "skipped"), run("build", None, status="in_progress")]
    got = v.verdict("octo/widgets#7", ["test", "lint", "build", "docs"], get=_hub("A change.", runs))
    assert not got["passed"] and got["checks"] == {"test": "failed", "lint": "skipped", "build": "pending", "docs": "absent"}
    assert len(got["reasons"]) == 4 and got["claim"]["verdict"] == "no claim"
    # the merge commit of a merged pull request, and a pull request that has none
    got = v.verdict("octo/widgets#7", ["test"], "merge", get=_hub("A change.", red, [run("test")], merged=True))
    assert got["passed"] and (got["commit"], got["at"], got["checks"]) == (MERGE, "merge", {"test": "passed"})
    got = v.verdict("octo/widgets#7", ["test"], "merge", get=_hub("A change.", green))
    assert not got["passed"] and got["checks"] == {} and "not merged" in got["reasons"][0]

    # as the step runs it: the verdict on stdout, in the file, in the job summary and in the step's outputs
    out, summary, outputs = tmp_path / "v.json", tmp_path / "summary.md", tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    assert v.main(["--pr", "octo/widgets#7", "--checks", "test, lint", "--out", str(out)], get=_hub("Tests pass.", green)) == 0
    line = capsys.readouterr().out.strip()
    assert json.loads(line)["passed"] is True and out.read_text(encoding="utf-8") == line + "\n"
    assert outputs.read_text(encoding="utf-8").splitlines() == ["passed=true", f"verdict={line}", f"json={out}"]
    said = summary.read_text(encoding="utf-8")
    assert said.startswith("### Knos verify: passed") and "Named check 2: passed" in said and "lint" not in said
    # refused: exit 1, or 0 with --no-fail; GitHub unreadable: exit 2 and nothing decided
    assert v.main(["--pr", "octo/widgets#7", "--checks", "test"], get=_hub("x", red)) == 1
    assert v.main(["--pr", "octo/widgets#7", "--checks", "test", "--no-fail"], get=_hub("x", red)) == 0
    assert v.main(["--pr", "octo/widgets#8"], get=_hub("x", red)) == 2
    assert "Nothing was decided" in capsys.readouterr().err


# ---- the receipt verifier -----------------------------------------------------------------------------------------------

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _fixtures() -> dict:
    """The cases of integrations/webhook/fixtures.json, built from the same order tests/test_bundle.py pays: every
    one says what both verifiers must answer."""
    import test_bundle as tb
    from knos import bundle
    net = tb.Chain()
    _r, files = bundle.gather(net.call, net.events(), tb.ORDER, tb.host())
    token, terms, receipt = files["token.jwt"].decode(), files["terms.json"].decode(), json.loads(files["receipt.json"])
    key = json.loads(files["key.json"])
    jwks = {"keys": [{"kty": "RSA", "alg": "RS256", "use": "sig", "kid": key["kid"], "n": key["n"], "e": key["e"]}]}
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    mint = lambda **over: sign_jwt(signing_key(), {**claims, **over})  # noqa: E731
    head, body, sig = token.split(".")
    other = {**receipt, "payees": [{**receipt["payees"][0], "github_id": 1}]}
    cases = [
        ("the token, the receipt and the terms of one payment", {"token": token, "receipt": receipt, "terms": terms}, None, None),
        ("the token alone", token, None, None),
        ("the evidence as one JSON text, the receipt as text inside it", json.dumps({"token": token, "receipt": json.dumps(receipt)}), None, None),
        ("the bundle's own key.json as the keys", {"token": token}, None, key),
        ("every fact the platform expects", {"token": token, "receipt": receipt},
         {"repository_id": tb.REPO, "pull_request": tb.PR, "commit": tb.HEAD, "payee": tb.SELLER, "mode": "merge", "order": tb.ORDER}, None),
        ("one character of the signed claims changed", f"{head}.{body[:-2]}{'A' if body[-2] != 'A' else 'B'}{body[-1]}.{sig}", None, None),
        ("a token signed by a key that is not among the keys", token, None, {"keys": [{**jwks["keys"][0], "kid": "another"}]}),
        ("an unsigned token", f"{_b64(json.dumps({'alg': 'none', 'kid': 'k'}).encode())}.{body}.", None, None),
        ("not a token", "hello", None, None),
        ("a token another workflow asked GitHub for", mint(job_workflow_ref="mallory/pay-me/.github/workflows/prove.yml@refs/heads/main"), None, None),
        ("a token of another issuer", mint(iss="https://gitlab.com"), None, None),
        ("a token signed for something else than a Knos payment", mint(aud="knos3:fund:" + claims["aud"].split(":", 2)[2]), None, None),
        ("a receipt that names another token", {"token": token, "receipt": {**receipt, "issuer_authenticated": {**receipt["issuer_authenticated"], "token_sha256": "0" * 64}}}, None, None),
        ("a receipt whose payee is not the one the token names", {"token": token, "receipt": other}, None, None),
        ("a receipt of version 1", {"token": token, "receipt": {**receipt, "version": 1}}, None, None),
        ("terms that are not the ones hashed at funding", {"token": token, "receipt": receipt, "terms": terms.replace("src/**", "**")}, None, None),
        ("a receipt for another repository than the one expected", {"token": token, "receipt": receipt}, {"repository_id": 1}, None),
        ("a payee the platform did not expect", {"token": token}, {"payee": 1}, None),
        ("a workflow the platform pins by its tag", {"token": token}, {"workflow": "drexthealpha/Knos/.github/workflows/prove.yml@refs/tags/"}, None),
    ]
    v = _load(HOOK / "knos_verify.py", "knos_verify_hook")
    out = []
    for name, evidence, expect, keys in cases:
        got = v.verify(evidence, keys or jwks, expect)
        out.append({"name": name, "evidence": evidence, **({"expect": expect} if expect else {}), **({"jwks": keys} if keys else {}),
                    **{k: got[k] for k in ("ok", "refused", "why", "checked")}})
    return {"about": "Cases for knos_verify.py and knos-verify.ts: tests/test_integrations.py builds them and holds this file to them. "
                     "The key is a test key, never GitHub's.",
            "jwks": jwks, "facts": v.verify(token, jwks)["facts"], "cases": out}


def _text() -> str:
    return json.dumps(_fixtures(), indent=1, sort_keys=True) + "\n"


def test_the_python_verifier_accepts_a_real_bundles_evidence_and_refuses_each_change_with_its_reason():
    fx = _fixtures()
    answers = {c["name"]: (c["ok"], c["refused"]) for c in fx["cases"]}
    assert [name for name, (ok, _) in answers.items() if ok] == [
        "the token, the receipt and the terms of one payment", "the token alone", "the evidence as one JSON text, the receipt as text inside it",
        "the bundle's own key.json as the keys", "every fact the platform expects"]
    assert {name: why for name, (ok, why) in answers.items() if not ok} == {
        "one character of the signed claims changed": "token", "a token signed by a key that is not among the keys": "token",
        "an unsigned token": "token", "not a token": "token", "a token another workflow asked GitHub for": "issuer",
        "a token of another issuer": "issuer", "a token signed for something else than a Knos payment": "audience",
        "a receipt that names another token": "receipt", "a receipt whose payee is not the one the token names": "receipt",
        "a receipt of version 1": "receipt", "terms that are not the ones hashed at funding": "terms",
        "a receipt for another repository than the one expected": "expect", "a payee the platform did not expect": "expect",
        "a workflow the platform pins by its tag": "issuer"}
    import test_bundle as tb
    assert fx["facts"] == {"order": tb.ORDER, "commit": tb.HEAD, "terms_hash": fx["facts"]["terms_hash"], "mode": "merge", "pull_request": tb.PR,
                           "payees": [{"github_id": tb.SELLER, "bps": 10_000}], "repository_id": str(tb.REPO),
                           "workflow": "drexthealpha/Knos/.github/workflows/prove.yml@refs/heads/main", "workflow_sha": "c" * 40,
                           "iat": 1790000000, "exp": 1790000300}
    full = fx["cases"][0]
    assert len(full["checked"]) == 5 and all(not c["why"] for c in fx["cases"] if c["ok"]) and all(c["why"].endswith(".") for c in fx["cases"] if not c["ok"])
    # the file a platform vendors needs nothing but the standard library
    source = (HOOK / "knos_verify.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    used = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert used == {"__future__", "base64", "hashlib", "json", "re", "sys", "pathlib"}
    # a key shorter than 2048 bits is not a key
    weak = {"keys": [{**fx["jwks"]["keys"][0], "n": _b64((modulus(signing_key()) >> 1100).to_bytes(120, "big"))}]}
    assert _load(HOOK / "knos_verify.py", "knos_verify_hook").verify(full["evidence"], weak)["refused"] == "token"


def test_the_committed_fixtures_are_the_ones_the_tests_build():
    """To write the file again after a deliberate change: `python tests/test_integrations.py` (PYTHONPATH=src)."""
    assert (HOOK / "fixtures.json").read_text(encoding="utf-8") == _text()


def test_the_typescript_verifier_answers_every_case_as_the_python_one_does():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    major, minor = (int(x) for x in subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout.strip().lstrip("v").split(".")[:2])
    if (major, minor) < (22, 6):
        pytest.skip("node older than 22.6 cannot run a TypeScript file as it is")
    got = subprocess.run([node, "--experimental-strip-types", "--no-warnings", str(HOOK / "test.mjs")], capture_output=True, text=True, encoding="utf-8", check=False, cwd=str(ROOT))
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout.strip().splitlines()[-1]) == {"cases": 19, "failed": 0}
    source = (HOOK / "knos-verify.ts").read_text(encoding="utf-8")
    assert "import " not in re.sub(r"(?m)^//.*$", "", source) and "require(" not in source          # no dependency, not even the runtime's own modules


# ---- the badge ----------------------------------------------------------------------------------------------------------

REPO_BADGE = {"repo": "octo/widgets", "pr": None, "count": 3, "money": badge.TEST, "other": 0, "as_of": "2026-10-05"}
PULL_BADGE = {"repo": "octo/widgets", "pr": 12, "amount": "20.00", "money": badge.TEST, "date": "2026-10-05"}


def test_the_badge_a_platform_shows_is_the_one_knos_draws_and_links_to_the_repositorys_record():
    assert (BADGE / "paid-on-proof.svg").read_text(encoding="utf-8") == badge.svg(REPO_BADGE)
    assert (BADGE / "paid-pull-request.svg").read_text(encoding="utf-8") == badge.svg(PULL_BADGE)
    readme = (BADGE / "README.md").read_text(encoding="utf-8")
    assert badge.markdown(PULL_BADGE, "paid-pull-request.svg") in readme and badge.receipt_url("octo/widgets") in readme
    assert badge.comment_line(PULL_BADGE) in readme                      # the form with no file: shields.io draws it from the address
    assert "test USDC" in readme and "not a score" in readme


# ---- the document -------------------------------------------------------------------------------------------------------

def test_the_integrations_document_claims_no_platform_uses_knos():
    text = (ROOT / "docs" / "INTEGRATIONS.md").read_text(encoding="utf-8")
    assert "No platform named here uses Knos, has endorsed it or has been asked." in text
    for rel in re.findall(r"\]\((\.\./[^)#]+)", text):
        assert (ROOT / "docs" / rel).resolve().exists(), rel
    assert not re.search(r"\b(?:partner|endorsed by|trusted by|used by)\b", text.replace("has endorsed it", ""), re.I)


if __name__ == "__main__":
    (HOOK / "fixtures.json").write_text(_text(), encoding="utf-8", newline="\n")
