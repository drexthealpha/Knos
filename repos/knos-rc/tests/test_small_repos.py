"""The four small repositories a release publishes (scripts/small_repos.py): each is this repository's own files and a
README, the same bytes every time, and what the site, `knos settle --neutral` and the escrow expect of them."""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
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
SOURCES = {"knos-task": {".github/workflows/knos.yml": "examples/knos-workflow.yml", ".github/workflows/knos-check.yml": "examples/knos-check.yml",
                         ".github/workflows/knos-reproduce.yml": "examples/knos-reproduce.yml"},
           "knos-attest": {".github/workflows/knos-attest.yml": "examples/knos-attest.yml"},
           "knos-claim-org": {".github/workflows/knos-claim.yml": "examples/knos-claim-org.yml"}}


@pytest.mark.parametrize("name", sorted(r.REPOS))
def test_each_repository_is_the_sources_byte_for_byte_and_the_same_every_time(name, tmp_path, capsys):
    files = r.files(name)
    assert name in SOURCES or name == "knos-playground"
    assert name not in SOURCES or set(files) == {*SOURCES[name], "README.md", "LICENSE"}
    for rel, src in SOURCES.get(name, {}).items():
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


# ---- the one-click reproduction: the task template holds the workflow, and the repository is a template --------------------------
def test_the_task_template_holds_the_reproduction_workflow_so_use_this_template_and_run_workflow_is_all(capsys):
    yaml = pytest.importorskip("yaml")
    files = r.files("knos-task")
    doc = yaml.safe_load(files[".github/workflows/knos-reproduce.yml"].decode("utf-8"))
    assert doc["name"] == "knos reproduce" and set(doc.get(True) or doc.get("on")) == {"workflow_dispatch"}       # by hand only: a new repository runs nothing unasked
    readme, how = files["README.md"].decode("utf-8"), (ROOT / "docs" / "reference" / "REPRODUCE.md").read_text(encoding="utf-8")
    assert "**Use this template**" in readme and "**knos reproduce**" in readme and "**Run workflow**" in readme
    lead = how.split("## ", 2)[1]
    assert lead.startswith("Two clicks and one button") and f"https://github.com/new?template_owner={r.OWNER}&template_name=knos-task&name=knos-reproduce&visibility=public&owner=@me" in lead
    assert lead.index("Use this template") < lead.index("Run workflow") and how.index("Two clicks and one button") < how.index("pipx run")
    # the three templates are made templates through the API, and a dry run sends nothing
    assert r.main(["settings", "knos-task"]) == 0
    out = capsys.readouterr().out
    assert f"gh api -X PATCH repos/{r.OWNER}/knos-task -F is_template=true -F has_issues=true" in out and "A dry run: nothing was sent." in out
    assert all(r.SETTINGS[n][0][2]["is_template"] is True for n in ("knos-task", "knos-attest", "knos-claim-org")) and set(r.SETTINGS) == set(r.REPOS)
    sent = []

    def gh(argv, **kw):
        sent.append(argv)
        return subprocess.CompletedProcess(argv, 1 if len(sent) == 2 else 0, "", "HTTP 403: Resource not accessible")
    assert r.settings("knos-task", True, gh) == 0 and sent == r.calls("knos-task") and "Set drexthealpha/knos-task: a template repository" in capsys.readouterr().out
    assert r.settings("knos-playground", True, gh) == 1 and "GitHub refused it: HTTP 403" in capsys.readouterr().out      # a refusal stops it and says so


# ---- the playground: both sides with a GitHub account and nothing else -----------------------------------------------------------
def _rules():
    return r._playground()


def test_the_playground_holds_the_callers_a_template_that_funds_and_checks_for_every_slot():
    yaml = pytest.importorskip("yaml")
    p, files = _rules(), r.files("knos-playground")
    assert f"{r.OWNER}/knos-playground" == p.REPO and r.SETTINGS["knos-playground"][0][2]["is_template"] is False
    assert r.SETTINGS["knos-playground"][1] == ("PUT", "/actions/permissions/fork-pr-contributor-approval", {"approval_policy": "first_time_contributors_new_to_github"})
    for rel, src in ((".github/workflows/knos.yml", "examples/knos-workflow.yml"), (".github/workflows/knos-check.yml", "examples/knos-check.yml")):
        assert files[rel] == (ROOT / src).read_bytes()
    # a new issue whose description holds the fund line starts the command job: that is what the caller's condition reads
    caller = files[".github/workflows/knos.yml"].decode("utf-8")
    assert "issues:\n    types: [opened]" in caller and "contains(github.event.issue.body, '/knos fund')" in caller
    # the issue template: front matter GitHub reads, two lines of explanation, then the fund line on a line of its own
    template = files[".github/ISSUE_TEMPLATE/fund-a-test-task.md"].decode("utf-8")
    _, front, body = template.split("---\n", 2)
    meta = yaml.safe_load(front)
    assert set(meta) == {"name", "about", "title"} and meta["title"].startswith("Playground: ")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) == 3 and lines[2] == p.FUND and "test USDC" in lines[0] and p.TASK in lines[1]
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from knos import accept, commands, judge
    finally:
        sys.path.remove(str(ROOT / "src"))
    cmd = commands.parse(body)
    assert isinstance(cmd, commands.Fund) and cmd.units == p.MOST and cmd.auto and cmd.checks == ()
    assert yaml.safe_load(files[".github/ISSUE_TEMPLATE/config.yml"].decode("utf-8"))["blank_issues_enabled"] is False
    assert files[".github/pull_request_template.md"].startswith(b"Closes #")
    # checks under every number a stranger's issue can get, each black-box, the same cases in each
    slots = {rel for rel in files if rel.startswith(".knos/acceptance/")}
    assert slots == {f".knos/acceptance/{n}/{name}" for n in range(1, p.SLOTS + 1) for name in ("blackbox.py", "cases.json", "README.md")}
    tasks = {rel for rel in files if rel.startswith("tasks/")}                      # every task's starting file and public examples, and check.py to try them
    assert len(tasks) == 48 and {rel.rsplit(".", 1)[1] for rel in tasks} == {"py", "json"} and "check.py" in files and "board.json" not in files
    assert len(files) == 9 + 1 + 48 + 3 * p.SLOTS and r.FAUCET_WORKFLOW in files           # the two callers and the rest, the faucet workflow, the tasks, the slots
    for n in (1, 2, p.SLOTS):
        bundle = {name: files[f".knos/acceptance/{n}/{name}"] for name in ("blackbox.py", "cases.json", "README.md")}
        assert judge.black_box(bundle) == "" and bundle == accept.bundle(n, ["python3", p.TASK], r.starter_cases(), "text", 16)
        spec = json.loads(bundle["cases.json"])
        assert spec["issue"] == n and spec["run"] == ["python3", "words.py"] and spec["cases"] == r.starter_cases()
    cases = r.starter_cases()
    assert len(cases) >= 20 and all(c["input"].isascii() for c in cases) and sum(c["input"].split() != c["output"].split() for c in cases) >= 5
    assert r.starter_cases() == cases                                                  # a fixed seed: the same every time
    # the README says the limits the rules hold, and claims nobody
    readme = files["README.md"].decode("utf-8")
    assert f"at most {p.MOST // 10**6} test USDC" in readme and f"at most {p.PER_DAY}\nin a day" in readme and f"issues 1 to {p.SLOTS} have checks" in readme
    assert p.FUND in readme and "issues/new?template=fund-a-test-task.md" in readme and not re.search(r"\bhave (funded|used|tried)\b|\busers\b", readme)


def test_the_starter_file_fails_its_checks_and_one_changed_line_passes_them(tmp_path):
    p, files = _rules(), r.files("knos-playground")
    for name in ("blackbox.py", "cases.json"):
        (tmp_path / name).write_bytes(files[f".knos/acceptance/1/{name}"])
    spec = importlib.util.spec_from_file_location("playground_blackbox", tmp_path / "blackbox.py")
    judge_ = importlib.util.module_from_spec(spec)
    kept, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(judge_)
    finally:
        sys.dont_write_bytecode = kept
    starter = files[p.TASK].decode("utf-8")
    assert starter.rstrip().endswith('print(" ".join(words))')
    solved = starter.replace('print(" ".join(words))', 'print(" ".join(reversed(words)))')

    def runs(source):
        (tmp_path / p.TASK).write_text(source, encoding="utf-8")

        def ask(_argv, stdin):
            got = subprocess.run([sys.executable, str(tmp_path / p.TASK)], input=stdin, capture_output=True, timeout=30)
            return got.returncode, got.stdout, got.stderr
        return judge_.check(ask)
    assert runs(starter) is not None and runs(solved) is None


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_the_tree_id_is_the_one_the_pinned_workflows_script_computes(name):
    assert r.tree_id(r.files(name)) == _script("pinned_workflows").tree_id(r.files(name))


def test_the_release_plan_rebuilds_after_the_stamp_every_repository_that_calls_the_pinned_workflows():
    pub, plan = _script("pinned_workflows"), (ROOT / "docs" / "reference" / "RELEASE.md").read_text(encoding="utf-8")
    [step] = [ln for ln in plan.splitlines() if ln.startswith("python scripts/small_repos.py build ")]
    callers = [name for name in r.REPOS if any(pub.NAMED.search(data.decode("utf-8")) for data in r.files(name).values())]
    assert {"knos-task", "knos-playground", "knos-attest"} <= set(callers)          # each names the commit the stamp writes
    assert [name for name in callers if name not in step] == [] and plan.index("pinned_workflows.py stamp") < plan.index(step)
    # and the script's own page says which of them are templates (the playground is not one)
    first, second, third = (n for n in r.REPOS if r.SETTINGS[n][0][2]["is_template"])
    assert f"{first}, {second} and {third} are template repositories" in " ".join((r.__doc__ or "").split())


def test_a_rebuild_of_the_playground_keeps_the_faucet_workflow_and_it_is_the_workers_own_job():
    """The 0.3.19 run added a faucet-only workflow to the playground by hand; a rebuild would have dropped it. Now it is
    one of the playground's files, made from the worker's own `faucet` job, so it cannot drift from what was tested."""
    files = r.files("knos-playground")
    text = files[r.FAUCET_WORKFLOW].decode("utf-8")
    assert r.FAUCET_WORKFLOW == ".github/workflows/knos-faucet.yml" and files[r.FAUCET_WORKFLOW] == r.faucet_workflow()
    assert all(r.FAUCET_WORKFLOW not in r.files(name) for name in r.REPOS if name != "knos-playground")
    worker = (ROOT / ".github" / "workflows" / "worker.yml").read_text(encoding="utf-8")
    job = worker[worker.index("  faucet:\n"):].rstrip("\n")
    assert text.rstrip("\n").endswith(job) and "python -m knos.faucet --event" in job
    head = text[:text.index("jobs:\n")]
    assert "issue_comment:" in head and "schedule" not in head and "permissions:\n  contents: read\n" in head         # one trigger, nothing writable at the top
    assert "\n  relay:" not in text and "\n  event:" not in text and "\n  claims:" not in text and text.count("\n  faucet:\n") == 1
    assert "KNOS_FAUCET_KEY" in text and "test USDC, which has no\n# monetary value" in text and "issues: write" in job
    for line in text.splitlines():                                                                                    # every action by its commit
        if "uses:" in line:
            assert re.search(r"uses: [\w./-]+@[0-9a-f]{40}( |$)", line), line
