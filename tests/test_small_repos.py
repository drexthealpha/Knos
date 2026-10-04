"""The three small repositories a release publishes (scripts/small_repos.py): each is this repository's own files and a
README, the same bytes every time, and what the site, `knos settle --neutral` and the escrow expect of them."""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_small", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


r = _script("small_repos")
IDS = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
SOURCES = {"knos-task": {".github/workflows/knos.yml": "examples/knos-workflow.yml", ".github/workflows/knos-check.yml": "examples/knos-check.yml"},
           "knos-attest": {".github/workflows/knos-attest.yml": "examples/knos-attest.yml"},
           "knos-claim-org": {".github/workflows/knos-claim.yml": "examples/knos-claim-org.yml"}}


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_each_repository_is_the_sources_byte_for_byte_and_the_same_every_time(name, tmp_path, capsys):
    files = r.files(name)
    assert set(files) == {*SOURCES[name], "README.md", "LICENSE"}
    for rel, src in SOURCES[name].items():
        assert files[rel] == (ROOT / src).read_bytes(), rel
    assert files["LICENSE"] == (ROOT / "LICENSE").read_bytes()
    readme = files["README.md"].decode("utf-8")
    assert readme.startswith(f"# {name.replace('-org', '')}") and "https://github.com/drexthealpha/Knos" in readme and readme.rstrip().endswith("in test USDC.")
    assert not re.search(r"\d{4}-\d{2}-\d{2}|immutable|audit", readme)               # no date, and no claim the project does not make
    out = tmp_path / name
    (out / "stale").mkdir(parents=True)
    (out / "stale" / "old.txt").write_text("left from an earlier build", encoding="utf-8")
    assert r.main(["build", name, str(out)]) == 0 and r.main(["build", name, str(out)]) == 0
    assert {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()} == set(files)       # and nothing else
    assert r.main(["check", name, str(out)]) == 0
    # the tree a commit of it has is known from the sources alone
    subprocess.run(["git", "init", "-q", str(out)], check=True)
    subprocess.run(["git", "-C", str(out), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(out), "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-q", "-m", "x"], check=True)
    tree = subprocess.run(["git", "-C", str(out), "rev-parse", "HEAD^{tree}"], capture_output=True, text=True, check=True).stdout.strip()
    capsys.readouterr()
    assert r.main(["tree", name]) == 0 and capsys.readouterr().out.strip() == tree
    assert r.main(["check", name, str(out)]) == 0                                    # the .git folder is not part of it
    (out / "README.md").write_text(readme + "edited\n", encoding="utf-8")
    assert r.main(["check", name, str(out)]) == 1 and "README.md is not the file this repository publishes" in capsys.readouterr().out


def test_the_task_template_is_what_the_site_makes_a_repository_from_and_installs_knos_there():
    task = (ROOT / "web" / "task.js").read_text(encoding="utf-8")
    assert f'export const TEMPLATE = "{r.OWNER}/knos-task";' in task and "knos-task" in r.REPOS
    files = r.files("knos-task")
    pub = _script("pinned_workflows")
    # the two callers a repository installs, naming the one published commit: an issue there can be funded and judged
    assert files[".github/workflows/knos.yml"] == (ROOT / ".github" / "workflows" / "knos.yml").read_bytes()
    named = set(pub.NAMED.findall(files[".github/workflows/knos.yml"].decode("utf-8")))
    assert {n for n, _ in named} == {"fund.yml", "prove.yml"} and {ref for _, ref in named} == {pub.pin()}
    # the acceptance files the site adds go where the judge reads them, and the README says the same path
    assert ".knos/acceptance/<issue>/" in files["README.md"].decode("utf-8") and ".knos/acceptance/${number}" in task


def test_the_attest_template_is_the_callers_file_under_the_name_knos_settle_starts():
    flow = (ROOT / "src" / "knos" / "flow.py").read_text(encoding="utf-8")
    assert '"workflow", "run", "knos-attest.yml", "--repo", here' in flow and '/knos-attest"' in flow
    files = r.files("knos-attest")
    assert list(SOURCES["knos-attest"]) == [".github/workflows/knos-attest.yml"] and b"name: knos attest" in files[".github/workflows/knos-attest.yml"]
    assert "named `knos-attest`" in files["README.md"].decode("utf-8") and "knos settle --neutral" in files["README.md"].decode("utf-8")


def test_the_organisation_claim_caller_calls_the_pinned_claim_workflow_with_kind_org_by_hand_only():
    yaml = pytest.importorskip("yaml")
    text = (ROOT / "examples" / "knos-claim-org.yml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    doc["on"] = doc.pop(True, doc.get("on"))
    [job] = doc["jobs"].values()
    assert doc["name"] == "knos claim" and set(doc["on"]) == {"workflow_dispatch"} and doc["permissions"] == {}
    assert job["uses"] == f"drexthealpha/knos-oidc-rotate/.github/workflows/claim.yml@{IDS['claim_sha_org']}"
    assert job["with"] == {"address": "${{ inputs.address }}", "kind": "org"} and job["permissions"] == {"id-token": "write", "issues": "write"}
    lib = (ROOT / "programs-v2" / "knos_pay" / "src" / "order_judge.rs").read_text(encoding="utf-8")
    assert "CLAIM_SHA_ORG" in lib and '"/knos-claim"' in lib                # the escrow takes it from a repository of that name only
    said = "\n".join(ln for ln in text.splitlines() if ln.startswith("#"))
    assert "everyone with write access" in said and "by hand only" in said and "ORGANISATION" in said
    # the person's caller differs in the commit's kind and nothing a claim could be forged with
    person = yaml.safe_load((ROOT / "examples" / "knos-claim.yml").read_text(encoding="utf-8"))
    assert "kind" not in next(iter(person["jobs"].values()))["with"]
    assert r.files("knos-claim-org")[".github/workflows/knos-claim.yml"] == text.encode("utf-8")


def test_a_caller_that_names_no_published_commit_or_another_claim_commit_is_not_published(monkeypatch):
    pub = _script("pinned_workflows")
    files = r.files("knos-task")
    stale = {**files, ".github/workflows/knos.yml": files[".github/workflows/knos.yml"].replace(pub.pin().encode(), pub.PLACEHOLDER.encode())}
    assert any("still says KNOS_WORKFLOWS_SHA" in line for line in r.wrong("knos-task", stale))
    other = {**files, ".github/workflows/knos.yml": files[".github/workflows/knos.yml"].replace(pub.pin().encode(), b"1" * 40)}
    assert any(f"at {'1' * 40}, and the examples name {pub.pin()}" in line for line in r.wrong("knos-task", other))
    claim = r.files("knos-claim-org")
    moved = {**claim, ".github/workflows/knos-claim.yml": claim[".github/workflows/knos-claim.yml"].replace(IDS["claim_sha_org"].encode(), b"2" * 40)}
    assert any("the escrow takes an organisation's claim at" in line for line in r.wrong("knos-claim-org", moved))
    assert r.wrong("knos-task", files) == [] and r.wrong("knos-claim-org", claim) == []
    with pytest.raises(SystemExit, match="there is no repository knos-nothing"):
        r.files("knos-nothing")
