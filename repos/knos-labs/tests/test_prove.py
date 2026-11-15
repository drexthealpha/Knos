"""GitHub-proven jobs: prove.yml keeps untrusted pull request code and the OIDC token apart, `knos prove --job` refuses
a token the chain would refuse before it costs a transaction, and `knos proof run` is the check job's verdict."""

from __future__ import annotations

import base64
import json
import subprocess
import time
from pathlib import Path

import pytest

from knos.cli import main

ROOT = Path(__file__).resolve().parents[1]
JOB = "ab" * 32
AUD = f"knos:{JOB}:{'c' * 40}:{'d' * 64}:CVhqj6hcR1Vd6r1c7m1V1rQ2T5p3h7sQyYxWbF2kFqL"
REF = "drexthealpha/Knos/.github/workflows/prove.yml@refs/tags/v0.3.7"


def run(capsys, *args: str) -> tuple[int, str]:
    rc = main(list(args))
    got = capsys.readouterr()
    return rc, got.out + got.err


def _yaml(path: Path) -> dict:
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["on"] = doc.pop(True, doc.get("on"))   # YAML 1.1 reads the key `on` as True
    return doc


# ---- prove.yml ---------------------------------------------------------------------------------------------------

def test_prove_yml_is_a_reusable_workflow_taking_the_job_and_issue():
    doc = _yaml(ROOT / ".github" / "workflows" / "prove.yml")
    call = doc["on"]["workflow_call"]
    assert set(doc["on"]) == {"workflow_call"}
    assert call["inputs"]["job"]["required"] is True and call["inputs"]["issue"]["required"] is True
    assert call["secrets"]["KNOS_PROVER_KEY"]["required"] is False     # permissionless: the relay sends the token
    assert doc["permissions"] == {}


def test_check_judges_pr_code_without_any_token_it_could_misuse():
    check = _yaml(ROOT / ".github" / "workflows" / "prove.yml")["jobs"]["check"]
    assert check["permissions"] == {"contents": "read"}
    text = json.dumps(check)
    assert "secrets." not in text and "id-token" not in text
    co = next(s for s in check["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    assert co["with"]["ref"] == "${{ github.event.pull_request.base.sha }}"      # the base, not the PR
    assert co["with"]["persist-credentials"] is False
    runs = "\n".join(str(s.get("run", "")) for s in check["steps"])
    assert 'archive "$HEAD" | tar -x -C pr' in runs                               # PR source in its own dir
    assert "knos proof judge --base base --pr pr" in runs
    assert set(check["outputs"]) == {"passed", "head_sha", "checks_hash"}


def test_attest_runs_no_pr_code_and_mints_the_five_part_audience():
    jobs = _yaml(ROOT / ".github" / "workflows" / "prove.yml")["jobs"]
    attest = jobs["attest"]
    assert attest["needs"] == "check"
    assert attest["if"] == "needs.check.outputs.passed == 'true'"
    assert attest["permissions"] == {"id-token": "write"}
    co = [s for s in attest["steps"] if str(s.get("uses", "")).startswith("actions/checkout")]
    assert len(co) == 1 and co[0]["with"]["ref"] == "${{ github.event.pull_request.base.sha }}"
    assert co[0]["with"]["sparse-checkout"] == ".knos/acceptance/${{ inputs.issue }}"
    runs = "\n".join(str(s.get("run", "")) for s in attest["steps"])
    assert 'test "$got" = "$CHECKS"' in runs                                     # recomputed from the base
    assert "knos-payout:" in runs and 'knos proof aud --job "$JOB" --head "$HEAD"' in runs
    assert "audience=$aud" in runs and "ACTIONS_ID_TOKEN_REQUEST_URL" in runs
    up = next(s for s in attest["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact"))
    assert up["with"]["name"] == "knos-proof"
    envs = {k: v for s in attest["steps"] for k, v in (s.get("env") or {}).items()}
    assert envs["JOB"] == "${{ inputs.job }}" and envs["CHECKS"] == "${{ needs.check.outputs.checks_hash }}"
    assert envs["KNOS_MEMBER_KEY"] == "${{ secrets.KNOS_PROVER_KEY }}"
    assert 'knos prove --job "$JOB" --jwt-file' in runs
    assert "pip install --system \"knos==" in runs                  # knos from PyPI, never from the PR


def test_the_caller_template_uses_pull_request_target_and_a_pinned_commit():
    doc = _yaml(ROOT / "examples" / "knos-workflow.yml")
    assert {"pull_request_target", "issue_comment"} <= set(doc["on"])
    prove = doc["jobs"]["prove"]
    pin = prove["uses"].split("@")
    assert pin[0] == "drexthealpha/Knos/.github/workflows/prove.yml" and len(pin[1]) == 40   # a commit, never a tag
    assert prove["with"]["job"] == "${{ needs.job.outputs.id }}"
    assert prove["with"]["issue"] == "${{ needs.job.outputs.issue }}"
    assert prove["permissions"] == {"contents": "read", "id-token": "write"}
    finder = doc["jobs"]["job"]
    assert "pull_request.body" not in json.dumps(finder["steps"][0]["run"])   # via env, never inlined into a script
    assert not any(str(s.get("uses", "")).startswith("actions/checkout") for s in finder["steps"])


# ---- knos prove --job --------------------------------------------------------------------------------------------

def _jwt(**claims) -> str:
    body = {"aud": AUD, "iss": "https://token.actions.githubusercontent.com",
            "exp": int(time.time()) + 300, "job_workflow_ref": REF, "job_workflow_sha": "a" * 40, **claims}
    enc = [base64.urlsafe_b64encode(json.dumps(x).encode()).rstrip(b"=").decode() for x in ({"alg": "RS256"}, body)]
    return ".".join(enc + ["c2ln"])


@pytest.fixture()
def chain(monkeypatch, knos_home):
    from knos.jobs import market, net
    sent = []
    monkeypatch.setattr(net, "ledger", lambda: "LEDGER")
    monkeypatch.setattr(net, "key", lambda: "PAYER")
    monkeypatch.setattr(market, "prove_github",
                        lambda ledger, payer, job_id, jwt: sent.append((ledger, payer, job_id, jwt)) or ("SIG1", "SIG2"),
                        raising=False)
    return sent


def _token(tmp_path: Path, jwt: str) -> str:
    p = tmp_path / "token.txt"
    p.write_text(jwt + "\n", encoding="utf-8")
    return str(p)


def test_a_good_token_is_sent_and_both_signatures_printed(chain, tmp_path, capsys):
    jwt = _jwt()
    rc, said = run(capsys, "prove", "--job", JOB, "--jwt-file", _token(tmp_path, jwt))
    assert rc == 0, said
    assert chain == [("LEDGER", "PAYER", bytes.fromhex(JOB), jwt)]
    assert "SIG1" in said and "SIG2" in said


@pytest.mark.parametrize("claims,why", [
    ({"aud": AUD.replace(JOB, "cd" * 32)}, "audience"),
    ({"aud": f"knos:{JOB}"}, "audience"),                      # the old 2-part audience
    ({"aud": AUD[:-1] + "0"}, "payout"),
    ({"aud": "sts.amazonaws.com"}, "audience"),
    ({"iss": "https://evil.example"}, "issuer"),
    ({"exp": int(time.time()) - 5}, "expired"),
    ({"job_workflow_sha": ""}, "job_workflow_sha"),
    ({"job_workflow_sha": "v0.3.8"}, "job_workflow_sha"),
])
def test_a_token_the_chain_would_refuse_is_refused_before_sending(chain, tmp_path, capsys, claims, why):
    rc, said = run(capsys, "prove", "--job", JOB, "--jwt-file", _token(tmp_path, _jwt(**claims)))
    assert rc == 1
    assert "Not sent" in said and why in said
    assert chain == []


def test_not_a_jwt_and_half_the_options_are_refused(chain, tmp_path, capsys):
    rc, said = run(capsys, "prove", "--job", JOB, "--jwt-file", _token(tmp_path, "nope"))
    assert rc == 1 and "not a JWT" in said
    rc, said = run(capsys, "prove", "--job", JOB)
    assert rc == 1 and "--jwt-file" in said
    assert chain == []


def test_the_escrow_refusing_is_one_line(chain, monkeypatch, tmp_path, capsys):
    from knos.jobs import market

    def refuse(*a):
        raise RuntimeError("repo does not match the job")
    monkeypatch.setattr(market, "prove_github", refuse, raising=False)
    rc, said = run(capsys, "prove", "--job", JOB, "--jwt-file", _token(tmp_path, _jwt()))
    assert rc == 1 and "The escrow refused: repo does not match the job" in said
    assert "Traceback" not in said


def test_without_on_chain_verification_it_says_so(monkeypatch, knos_home, tmp_path, capsys):
    from knos.jobs import market, net
    monkeypatch.setattr(net, "ledger", lambda: "LEDGER")
    monkeypatch.setattr(net, "key", lambda: "PAYER")
    monkeypatch.delattr(market, "prove_github", raising=False)
    rc, said = run(capsys, "prove", "--job", JOB, "--jwt-file", _token(tmp_path, _jwt()))
    assert rc == 1 and "prove_github" in said


# ---- knos proof run ----------------------------------------------------------------------------------------------

def _repo(tmp_path: Path, toml: str) -> Path:
    repo = tmp_path / "repo"
    (repo / ".knos").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".knos" / "proof.toml").write_text(toml, encoding="utf-8")
    return repo


def test_proof_run_passes_when_every_check_passes(knos_home, tmp_path, capsys):
    repo = _repo(tmp_path, '[[check]]\nname = "a"\nrun = "exit 0"\n[[check]]\nname = "b"\nrun = "exit 0"\n')
    rc, said = run(capsys, "proof", "run", "--in", str(repo))
    assert rc == 0, said
    assert "custom:a" in said and "custom:b" in said and "proven" in said


def test_proof_run_fails_when_one_check_fails(knos_home, tmp_path, capsys):
    repo = _repo(tmp_path, '[[check]]\nname = "a"\nrun = "exit 0"\n[[check]]\nname = "b"\nrun = "exit 3"\n')
    rc, said = run(capsys, "proof", "run", "--in", str(repo))
    assert rc == 1
    assert "NO  custom:b" in said and "not proven" in said


def test_proof_run_reads_the_toml_it_is_given(knos_home, tmp_path, capsys):
    repo = _repo(tmp_path, '[[check]]\nname = "pr"\nrun = "exit 0"\n')   # what the pull request says
    base = tmp_path / "base.toml"
    base.write_text('[[check]]\nname = "base"\nrun = "exit 1"\n', encoding="utf-8")   # what the base branch says
    rc, said = run(capsys, "proof", "run", "--in", str(repo), "--toml", str(base))
    assert rc == 1 and "custom:base" in said and "custom:pr" not in said


def test_proof_run_with_no_checks_proves_nothing(knos_home, tmp_path, capsys):
    repo = _repo(tmp_path, 'tests = "pytest"\n')
    rc, said = run(capsys, "proof", "run", "--in", str(repo))
    assert rc == 1 and "nothing to prove" in said
