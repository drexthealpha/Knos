"""The adapters (examples/adapters/, docs/ADAPTERS.md): workflow files that turn another system's event into the run that
attests a work order.

An adapter signs nothing. It writes one commit status and starts the repository's own Knos workflow by hand, which is
the pinned prove.yml (or, for the meter, the pinned attest.yml). So three things are checked of each file: it is a
workflow GitHub accepts (YAML, actionlint), it is safe to install (no token of GitHub's signature, nothing of an event
inside a script), and the run it starts is one the programs accept: the pinned workflow runs its signing job on that
event, and knos_pay takes that run's token, in LiteSVM. The same harness shows what is refused, with the program's own
error, for the direct paths docs/ADAPTERS.md lists under "needs a program change".
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import _posix
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ROOT / "examples" / "adapters"
DOC = ROOT / "docs" / "ADAPTERS.md"
FILES = sorted(ADAPTERS.glob("*.yml"))
PAY = ("deployment.yml", "release.yml", "workflow-run.yml", "attestation.yml", "linear.yml", "jira.yml", "notion.yml")
# the events each file runs on: what another system's event arrives as
EVENTS = {"deployment.yml": {"deployment_status"}, "release.yml": {"release"}, "workflow-run.yml": {"workflow_run"}, "attestation.yml": {"workflow_run"},
          "linear.yml": {"schedule", "workflow_dispatch"}, "jira.yml": {"repository_dispatch", "schedule", "workflow_dispatch"},
          "notion.yml": {"schedule", "workflow_dispatch"}, "meter.yml": {"deployment_status"}}
BOT = 41898282      # github-actions[bot]: the actor of a run that a workflow's own GITHUB_TOKEN started


def doc(path: Path) -> dict:
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    d["on"] = d.pop(True) if True in d else d["on"]     # YAML reads the key `on` as true
    return d


def step(path: Path) -> tuple[dict, dict]:
    """(the job, its last step: the one that starts the Knos run)."""
    (job,) = doc(path)["jobs"].values()
    return job, job["steps"][-1]


def test_the_adapters_are_the_ones_listed():
    assert [p.name for p in FILES] == sorted(EVENTS)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_an_adapter_parses_and_is_safe_to_install(path):
    d, text = doc(path), path.read_text(encoding="utf-8")
    assert set(d["on"]) == EVENTS[path.name]
    assert d["permissions"] == {} and "pull_request_target" not in d["on"] and "pull_request" not in d["on"]
    job, last = step(path)
    # it signs nothing: no token of GitHub's signature, no secret of Knos's, and no Knos workflow is named here (nothing to pin)
    assert "id-token" not in job["permissions"] and "knos-workflows" not in text and "KNOS_RELAY_KEY" not in text
    assert job["permissions"]["actions"] == "write" and all(v in ("read", "write") for v in job["permissions"].values())
    assert {k for k, v in job["permissions"].items() if v == "write"} <= {"actions", "statuses"}
    # nothing is checked out, and nothing of an event or a secret is written into a script: it arrives as an environment variable
    for s in job["steps"]:
        assert "uses" not in s, s
        assert "${{" not in s["run"], s["name"]
    assert job["env"]["GH_TOKEN"] == "${{ github.token }}" and job["runs-on"] == "ubuntu-24.04"
    # it says who authenticates what, in its own header
    head = text.split("\nname: ")[0]
    assert "authenticates" in head and "NOT authenticate" in head and "rusted" in head


def _actionlint() -> str | None:
    exe = os.environ.get("ACTIONLINT") or shutil.which("actionlint")
    if exe and Path(exe).is_dir():
        exe = str(Path(exe) / "actionlint")
    return exe if exe and Path(exe).is_file() else None


def test_actionlint_passes_on_every_adapter():
    exe = _actionlint()
    if not exe:
        pytest.skip("actionlint is not installed (put it on PATH, or name it in ACTIONLINT)")
    got = subprocess.run([exe, "-no-color", "-shellcheck=", "-pyflakes=", *(str(p.relative_to(ROOT)) for p in FILES)], cwd=str(ROOT),
                         capture_output=True, text=True, check=False)
    assert got.returncode == 0, got.stdout + got.stderr


# ---- the run an adapter starts is one the pinned workflows sign on ------------------------------------------------------

def _if(job: dict) -> str:
    return " ".join(str(job["if"]).split())


@pytest.mark.parametrize("name", PAY)
def test_a_pay_adapter_starts_the_repositorys_own_knos_workflow_which_settles_on_that_event(name):
    job, last = step(ADAPTERS / name)
    assert job["env"]["KNOS_WORKFLOW"] == "knos.yml" and 'gh workflow run "$KNOS_WORKFLOW" --repo "$R" -f pull="$n"' in last["run"]
    assert 'gh api -X POST "repos/$R/statuses/$head" -f state=success -f context="$CONTEXT"' in last["run"]
    # the installed file (examples/knos-workflow.yml) can be started by hand with a pull request's number ...
    installed = doc(ROOT / "examples" / "knos-workflow.yml")
    assert set(installed["on"]["workflow_dispatch"]["inputs"]) == {"pull"}
    settle = installed["jobs"]["settle"]
    assert "github.event_name == 'workflow_dispatch'" in _if(settle) and settle["uses"].split("@")[0].endswith("/.github/workflows/prove.yml")
    # ... and the pinned prove.yml's signing job runs on that event, and on none an adapter itself runs on
    signing = doc(ROOT / ".github" / "workflows" / "prove.yml")["jobs"]["settle"]
    assert signing["permissions"]["id-token"] == "write" and "github.event_name == 'workflow_dispatch'" in _if(signing)
    for event in EVENTS[name] - {"workflow_dispatch", "schedule"}:
        assert event not in _if(signing), event      # why an adapter cannot call prove.yml on its own event: docs/ADAPTERS.md says so
    # the status is not one Knos would ignore as its own, and it can be named in an order's terms
    from knos import terms
    context = job["env"]["CONTEXT"]
    assert not terms._knos_name(context) and f"checks: test, {context}" in (ADAPTERS / name).read_text(encoding="utf-8")
    built = terms.build(type("Fund", (), {"checks": (context,), "paths": (), "reserve": 7})(), required=[], check_runs=[], statuses=[])
    assert {"app": terms.ANY, "name": context} in built.terms["checks"]
    assert terms.evidence(built.terms, [], [{"context": context, "state": "success"}])[context] == "passed"
    assert terms.evidence(built.terms, [], [])[context] == "absent"


def test_the_meter_adapter_starts_the_repositorys_own_attest_workflow_with_an_evaluation():
    job, last = step(ADAPTERS / "meter.yml")
    assert 'gh workflow run "$KNOS_ATTEST" --repo "$R" -f repository="$R" -f pull="$n" -f order="$ORDER.$MILESTONE.$RATE" -f kind=eval' in last["run"]
    installed = doc(ROOT / "examples" / "knos-attest.yml")
    assert {"repository", "pull", "order", "kind"} <= set(installed["on"]["workflow_dispatch"]["inputs"])
    assert "eval" in installed["on"]["workflow_dispatch"]["inputs"]["kind"]["options"]
    from knos import flow
    assert flow._evaluation("ab" * 32 + "." + job["env"]["MILESTONE"] + ".2000000") == (bytes.fromhex("ab" * 32), 2, 2_000_000)
    # knos_meter reads no event claim at all: whatever event led to the attest run, the evaluation counts
    claims = re.search(r"t\.claims\(\s*\[(.*?)\]\)", (ROOT / "programs-v2" / "knos_meter" / "src" / "gh.rs").read_text(encoding="utf-8"), re.S).group(1)
    assert "run_attempt" in claims and "event_name" not in claims


# ---- and one the program accepts: knos_pay 2.1 in LiteSVM ---------------------------------------------------------------

def test_the_rules_the_document_quotes_are_the_programs():
    judge = (ROOT / "programs-v2" / "knos_pay" / "src" / "order_judge.rs").read_text(encoding="utf-8")
    for quoted in ('fn by_hand(g: &Gh) -> bool { g.event == b"workflow_dispatch" && g.actor_id != 0 && g.actor_id == g.owner_id }',
                   "if own && g.wf_file == PROVE { return Ok(Judge::Own); }",
                   "if named && (g.wf_file == PROVE || g.wf_file == ATTEST) { return Ok(Judge::Private); }",
                   "let neutral = o.is(F_NEUTRAL) && !o.is(F_PRIVATE) && by_hand(g);"):
        assert quoted in judge and quoted in DOC.read_text(encoding="utf-8"), quoted
    gh = (ROOT / "programs-v2" / "knos_pay" / "src" / "gh.rs").read_text(encoding="utf-8")
    assert "let signed = v.issuer == knos_oidc::pins::ISSUER_GITHUB || knos_oidc::registrant(&d).is_some_and(ours);" in gh


def test_knos_pay_takes_the_run_an_adapter_starts_and_refuses_the_direct_paths():
    pytest.importorskip("solders.litesvm")
    sys.path.insert(0, str(ROOT / "tests"))
    from _order import AUTHOR, REPO, USDC, OrderChain, code
    from solders.keypair import Keypair

    from knos.settle.v2 import pay

    c = OrderChain()
    wallet = Keypair().pubkey()
    payees = [(AUTHOR, 10_000, wallet)]
    c.token_account(wallet, c.usdc)

    # 1. what every pay adapter starts: prove.yml in the order's own repository, by `workflow_dispatch`, the actor the
    #    repository's own token (a bot, not the owner). Judge a names no event and no actor: paid.
    order = c.fund_wallet(amount=20 * USDC)
    assert c.pay(order, payees, event_name="workflow_dispatch", actor_id=BOT, repository_id=REPO), c.err
    assert c.balance(pay.ata(wallet, c.usdc)) == 20 * USDC and c.said("knos3:settled")[0].endswith("judge=0")

    # 2. the program would also take prove.yml's token on the adapter's own event (it reads none for judge a); it is the
    #    pinned prove.yml that does not sign on it (the test above). So that path needs a workflows change, not a program change.
    order = c.fund_wallet(amount=20 * USDC)
    assert c.pay(order, payees, event_name="deployment_status", actor_id=BOT, repository_id=REPO), c.err

    # 3. attest.yml called directly on the event, in the order's own repository: E_WORKFLOW (86), whatever the event
    neutral = c.fund_wallet(amount=20 * USDC, options=pay.opts(pay.F_NEUTRAL))
    for event in ("deployment_status", "release", "workflow_run", "repository_dispatch", "schedule"):
        assert not c.pay(neutral, payees, file="attest.yml", event_name=event, actor_id=BOT, repository_id=REPO) and code(c) == 86, event

    # 4. attest.yml on the event in someone's own repository, for a NEUTRAL order: E_CLAIMS (85): only a run started by
    #    hand by the repository's owner is judge b. The same claims with `workflow_dispatch` pay.
    mine = dict(file="attest.yml", actor_id=AUTHOR, repository_owner_id=AUTHOR, repository_id=700_700_700, repository=f"user{AUTHOR}/knos-attest")
    for event in ("deployment_status", "release", "workflow_run", "repository_dispatch", "schedule"):
        assert not c.pay(neutral, payees, event_name=event, **mine) and code(c) == 85, event
    # ... and a hand-started run whose actor is not the owner (what a workflow's own token starts) is not judge b either
    assert not c.pay(neutral, payees, event_name="workflow_dispatch", **{**mine, "actor_id": BOT}) and code(c) == 85
    assert c.pay(neutral, payees, event_name="workflow_dispatch", **mine), c.err


# ---- the script itself, against a stand-in for `gh` ---------------------------------------------------------------------

GH = r'''import json, os, sys
sys.stdout.reconfigure(newline="\n")      # LF on every OS, as the runner's gh writes
a = sys.argv[1:]
world = json.load(open(os.environ["WORLD"]))
def log(line):
    open(os.environ["LOG"], "a").write(line + "\n")
if a[0] == "workflow":
    log(" ".join(a)); sys.exit(0)
path = next(x for x in a[1:] if x.startswith(("repos/", "search/")))
if path == "search/issues":
    log("search " + next(x for x in a if x.startswith("q=")))
    print("\n".join(str(n) for n in world["pulls"])); sys.exit(0)
parts = path.split("/")
if "-X" in a and a[a.index("-X") + 1] == "POST" and parts[3] == "statuses":
    f = dict(x.split("=", 1) for x in a if "=" in x and not x.startswith("repos/"))
    world["status"].setdefault(parts[4], []).append(f["context"]); json.dump(world, open(os.environ["WORLD"], "w"))
    log(f"status {parts[4]} {f['context']} {f['state']}"); sys.exit(0)
if parts[3] == "pulls":
    pr = world["pulls"][parts[4]]
    print(pr["merge_commit_sha"] if "--jq" in a else json.dumps(pr)); sys.exit(0)
if parts[3] == "compare":
    base, head = parts[4].split("...")
    if head not in world["contains"]: sys.exit(1)
    print("ahead" if base in world["contains"][head] else "diverged"); sys.exit(0)
if parts[3] == "commits" and parts[-1] == "status":
    print("\n".join(world["status"].get(parts[4], []))); sys.exit(0)
if parts[3] == "commits":
    print(world["tags"][parts[4]]); sys.exit(0)
sys.exit(2)
'''
CURL = r'''import json, os, sys
sys.stdout.reconfigure(newline="\n")
a = " ".join(sys.argv[1:])
world = json.load(open(os.environ["WORLD"]))
open(os.environ["LOG"], "a").write("curl " + next(x for x in sys.argv[1:] if x.startswith("http")) + "\n")
for key, state in world["tracker"].items():
    if key in a:
        print(json.dumps({"fields": {"status": {"statusCategory": {"key": state}}}, "data": {"issue": {"state": {"type": state}}},
                          "properties": {"Status": {"status": {"name": state}}}})); sys.exit(0)
sys.exit(22)
'''


def play(tmp_path: Path, name: str, world: dict, **env) -> list[str]:
    """Runs the adapter's last step with stand-ins for `gh` and `curl`, in a POSIX bash (tests/_posix.py: Git's on
    Windows). Returns what they were asked to do."""
    bash = _posix.bash()
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    # each stand-in is a Python file run by this interpreter, through a two-line bash script named as the tool
    for tool, body in (("gh", GH), ("curl", CURL)):
        (bin_ / f"{tool}.py").write_text(body, encoding="utf-8")
        (bin_ / tool).write_text(f'#!/usr/bin/env bash\nexec "{_posix.path(sys.executable)}" "{_posix.path(bin_ / f"{tool}.py")}" "$@"\n',
                                 encoding="utf-8", newline="\n")
        (bin_ / tool).chmod(stat.S_IRWXU)
    if os.name == "nt":         # jq for Windows ends each line with CR LF; the runner's jq (Linux), which the step is
        jq = _posix.path(shutil.which("jq"))       # written for, with LF: the same jq, its lines ended as there
        (bin_ / "jq").write_text(f'#!/usr/bin/env bash\nset -o pipefail\n"{jq}" "$@" | tr -d \'\\r\'\n', encoding="utf-8", newline="\n")
    log, state = tmp_path / "log", tmp_path / "world.json"
    log.write_text("", encoding="utf-8")
    if not state.exists():
        state.write_text(json.dumps({"status": {}, "contains": {}, "tags": {}, "tracker": {}, **world}), encoding="utf-8")
    job, last = step(ADAPTERS / name)
    given = {k: str(v) for k, v in job["env"].items() if "${{" not in str(v)}
    # what Windows needs to start a program at all (Python reads SYSTEMROOT), and no other variable of this process
    system = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC") if os.name == "nt" and k in os.environ}
    got = subprocess.run([bash, "-c", last["run"]], cwd=str(tmp_path), capture_output=True, text=True, check=False,
                         env=_posix.environ({**system, "WORLD": str(state), "LOG": str(log), "MSYS_NO_PATHCONV": "1",   # Git's bash: arguments as written
                                             "R": "acme/app", **given, **env}, first=[bin_]))
    assert got.returncode == 0, got.stdout + got.stderr
    return [ln for ln in log.read_text(encoding="utf-8").splitlines() if not ln.startswith(("search", "curl"))]


def pull(n: int, **more) -> dict:
    return {"number": n, "title": f"Change {n}", "body": "", "head": {"sha": f"{n:040x}", "ref": f"change-{n}"}, "merge_commit_sha": f"{n + 100:040x}", **more}


@pytest.mark.skipif(not _posix.find() or not shutil.which("jq"), reason="needs bash and jq")
def test_a_deployment_marks_and_settles_the_pull_requests_it_contains_once(tmp_path):
    deployed = "d" * 40
    world = {"pulls": {"7": pull(7), "8": pull(8), "9": pull(9)}, "contains": {deployed: [pull(7)["merge_commit_sha"], pull(9)["merge_commit_sha"]]},
             "status": {pull(9)["head"]["sha"]: ["deployed/production"]}}      # #9 was said by an earlier run; #8 is not in this deployment
    did = play(tmp_path, "deployment.yml", world, SHA=deployed, URL="https://deploy.example/1")
    assert did == [f"status {pull(7)['head']['sha']} deployed/production success", "workflow run knos.yml --repo acme/app -f pull=7"]
    assert play(tmp_path, "deployment.yml", world, SHA=deployed, URL="https://deploy.example/1") == []      # the event again: nothing twice
    # a release names a tag, and the tag's commit is what must contain the merge; a commit GitHub cannot compare is not accepted
    (tmp_path / "world.json").unlink()
    world = {"pulls": {"7": pull(7), "8": pull(8)}, "tags": {"v1.2.0": deployed}, "contains": {deployed: [pull(8)["merge_commit_sha"]]}}
    assert play(tmp_path, "release.yml", world, TAG="v1.2.0", URL="https://github.com/acme/app/releases/v1.2.0") == [
        f"status {pull(8)['head']['sha']} released success", "workflow run knos.yml --repo acme/app -f pull=8"]
    (tmp_path / "world.json").unlink()
    assert play(tmp_path, "workflow-run.yml", {"pulls": {"7": pull(7)}}, SHA="e" * 40, URL="https://x") == []
    # the meter: one evaluation per contained pull request, under the adapter's milestone
    (tmp_path / "world.json").unlink()
    world = {"pulls": {"7": pull(7), "8": pull(8)}, "contains": {deployed: [pull(7)["merge_commit_sha"]]}}
    assert play(tmp_path, "meter.yml", world, SHA=deployed, ORDER="ab" * 32, RATE="2000000") == [
        f"workflow run knos-attest.yml --repo acme/app -f repository=acme/app -f pull=7 -f order={'ab' * 32}.2.2000000 -f kind=eval"]


@pytest.mark.skipif(not _posix.find() or not shutil.which("jq"), reason="needs bash and jq")
@pytest.mark.parametrize("name,context,named,done,env", [
    ("linear.yml", "tracker/linear-done", dict(title="ENG-12 faster parser"), "completed", dict(LINEAR_API_KEY="k")),
    ("jira.yml", "tracker/jira-done", dict(head={"sha": f"{7:040x}", "ref": "feature/proj-12-parser"}), "done",
     dict(JIRA_BASE_URL="https://acme.atlassian.net", JIRA_EMAIL="a@acme.example", JIRA_API_TOKEN="t", URL="https://acme.atlassian.net")),
    ("notion.yml", "tracker/notion-done", dict(body="Spec: https://www.notion.so/acme/Parser-" + "0123456789abcdef" * 2), "Done", dict(NOTION_TOKEN="t")),
])
def test_a_tracker_adapter_asks_the_tracker_and_believes_only_its_answer(tmp_path, name, context, named, done, env):
    key = {"linear.yml": "ENG-12", "jira.yml": "PROJ-12", "notion.yml": "0123456789abcdef" * 2}[name]
    world = {"pulls": {"7": pull(7, **named), "8": pull(8)}, "tracker": {key: "started"}}      # #8 names no issue
    assert play(tmp_path, name, world, **env) == []                                           # not done: nothing is said
    state = json.loads((tmp_path / "world.json").read_text(encoding="utf-8"))
    state["tracker"][key] = done
    (tmp_path / "world.json").write_text(json.dumps(state), encoding="utf-8")
    assert play(tmp_path, name, world, **env) == [f"status {7:040x} {context} success", "workflow run knos.yml --repo acme/app -f pull=7"]
    assert play(tmp_path, name, world, **env) == []
    # the tracker's API was asked about that issue, with the secret, and a dispatch's payload is read nowhere
    asked = [ln for ln in (tmp_path / "log").read_text(encoding="utf-8").splitlines() if ln.startswith("curl")]
    assert asked == [] or all(ln.startswith("curl https://") for ln in asked)
    assert "client_payload" not in step(ADAPTERS / name)[1]["run"] and "github.event" not in json.dumps(step(ADAPTERS / name)[0]["env"])


# ---- the document -----------------------------------------------------------------------------------------------------

def test_the_document_lists_every_adapter_with_what_is_authenticated_and_its_status():
    text = DOC.read_text(encoding="utf-8")
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in text.splitlines() if ln.startswith("| ") and "examples/" in ln]
    listed = {m for r in rows for m in re.findall(r"examples/adapters/([\w-]+\.yml)", r[1])}
    assert listed == {p.name for p in FILES}
    assert all(len(r) == 5 and r[4] in ("works with 2.1 as built", "needs a program change") for r in rows), [r for r in rows if len(r) != 5]
    assert any("examples/gitlab" in r[1] for r in rows)
    assert "## Needs a program change" in text
    for word in ("E_WORKFLOW", "E_CLAIMS", "HMAC", "Sigstore", "test USDC"):
        assert word in text, word
    for link in re.findall(r"\]\((\.\./[^)#]+)", text):
        assert (DOC.parent / link).exists(), link
