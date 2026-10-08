"""The playground's tasks (tasks/) and the board that keeps them open and funded (scripts/task_board.py): every
reference passes its own checks, plausible wrong answers and a tampering pull request do not, and the board opens,
funds and reports within its limits against a forge and a chain that are both made up here."""
from __future__ import annotations

import base64
import calendar
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from knos import commands, judge, playground
from knos.settle.v2 import pay

ROOT = Path(__file__).resolve().parents[1]
posix = pytest.mark.skipif(os.name == "nt", reason="the judge's sandbox is the one prove.yml runs on ubuntu-latest")
NOW = calendar.timegm((2026, 10, 7, 12, 0, 0))
OWNER = {"login": "drexthealpha", "id": playground.OWNER_ID}
STRANGER = {"login": "stranger", "id": 4242}


def _script(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_tb", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tb = _script("task_board")
TASKS = tb.catalogue()
SLUGS = [t["slug"] for t in TASKS]


# ---- the tasks ----------------------------------------------------------------------------------------------------------------
def test_there_are_24_tasks_and_each_says_first_that_the_money_is_worth_nothing():
    assert len(TASKS) == 24 and len(set(SLUGS)) == 24 and len({t["file"] for t in TASKS}) == 24 and len({t["seed"] for t in TASKS}) == 24
    for t in TASKS:
        assert t["statement"].splitlines()[0] == "Test USDC, no monetary value." == tb.FIRST, t["slug"]
        assert (ROOT / "tasks" / t["slug"] / "start.py").read_text(encoding="utf-8").splitlines()[0] == "# Test USDC, no monetary value."
        assert tb.issue_body(t, playground.REPO).splitlines()[0] == tb.FIRST
        assert 2_000_000 <= t["amount"] <= 5_000_000 and t["amount"] <= playground.MOST
        assert t["amount"] >= pay.ORDER_MIN_AMOUNT                             # what the escrow holds at least: so every task pays 5 today
        assert t["labels"] == ["knos-funded", "good first issue", "help wanted"] and 1 <= t["deadline_days"] <= commands.MAX_DAYS
        cmd = commands.parse(tb.fund_line(t))
        assert isinstance(cmd, commands.Fund) and cmd.units == t["amount"] and cmd.days == t["deadline_days"] and cmd.auto is False      # the merge pays
        assert len(t["public"]) >= 3 and len(t["statement"].split()) <= 90                                                               # read in a minute
    assert (ROOT / "tasks" / "README.md").read_text(encoding="utf-8").splitlines()[0].endswith("Test USDC, no monetary value.")


def _runs(path: Path):
    """How the judge asks: the file as a separate process, the input on standard input."""
    def ask(_argv, stdin):
        got = subprocess.run([sys.executable, str(path)], input=stdin, capture_output=True, timeout=60)
        return got.returncode, got.stdout, got.stderr
    return ask


def _calls(path: Path):
    """The same answers without a process for each: for the fresh inputs, which are many."""
    spec = importlib.util.spec_from_file_location(f"cand_{path.parent.name}_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return lambda _argv, stdin: (0, (mod.solve(stdin.decode("utf-8")) + "\n").encode("utf-8"), b"")


@pytest.mark.parametrize("slug", SLUGS)
def test_the_reference_passes_three_wrong_answers_fail_and_tampering_is_refused(slug, tmp_path):
    task, folder = tb.load(slug), ROOT / "tasks" / slug
    files = tb.bundle(task, 7)
    assert files == tb.bundle(task, 7) and judge.black_box(files) == ""                 # the same bytes every time, and black-box
    assert set(files) == {"blackbox.py", "cases.json", "gen.py", "reference.py", "README.md"}
    for rel, data in files.items():
        (tmp_path / rel).write_bytes(data)
    spec = importlib.util.spec_from_file_location(f"bundle_{task['seed']}", tmp_path / "blackbox.py")
    box = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(box)
    recorded = json.loads(files["cases.json"])["cases"]
    assert len(recorded) >= 18 and recorded[:len(task["public"])] == task["public"]     # the examples a stranger sees are the first cases
    assert len(box.fresh(1)) >= 5 and box.fresh(1) == box.fresh(1) and box.fresh(1) != box.fresh(2)
    assert box.check(_runs(folder / task["reference"])) is None                         # as a process, every recorded case
    for seed in (1, 2, 3):
        assert box.check(_calls(folder / task["reference"]), seed=seed) is None         # and inputs nobody recorded
    for wrong in task["wrong"]:
        why = box.check(_runs(folder / wrong))
        assert why and "expected" in why, (wrong, why)                                  # a wrong answer, not a crash
    assert "expected" in box.check(_runs(folder / "start.py"))                          # the starting file is not a solution
    for rel in files:                                                                   # a pull request cannot touch what decides
        assert judge.classify_path(f".knos/acceptance/7/{rel}", {"runner": "blackbox"}) == "refused:terms"
    assert judge.classify_path(task["file"], {"runner": "blackbox"}) == "allowed"
    assert judge.classify_path(".github/workflows/knos-check.yml", {"runner": "blackbox"}) == "refused:workflow"


@posix
def test_the_judge_itself_pays_the_reference_and_refuses_a_wrong_answer_and_a_tampered_bundle(tmp_path):
    task = tb.load("roman")
    folder = ROOT / "tasks" / "roman"
    base = tmp_path / "base"
    for rel, data in {task["file"]: (folder / "start.py").read_bytes(), **{f".knos/acceptance/7/{k}": v for k, v in tb.bundle(task, 7).items()}}.items():
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        (base / rel).write_bytes(data)

    def pull(name: str, **edits: bytes) -> Path:
        import shutil
        out = tmp_path / name
        shutil.copytree(base, out)
        for rel, data in edits.items():
            (out / rel).write_bytes(data)
        return out
    good = judge.judge(base, pull("good", **{task["file"]: (folder / "reference.py").read_bytes()}), {"issue": "7"})
    assert good["passed"] and good["evidence"]["runner"] == "blackbox", good["reasons"]
    bad = judge.judge(base, pull("bad", **{task["file"]: (folder / "wrong_1.py").read_bytes()}), {"issue": "7"})
    assert not bad["passed"] and "acceptance::blackbox" in bad["reasons"][0]
    cheat = pull("cheat", **{task["file"]: (folder / "wrong_1.py").read_bytes(), ".knos/acceptance/7/blackbox.py": b"raise SystemExit(0)\n"})
    assert judge.judge(base, cheat, {"issue": "7"})["reasons"] == [
        "touches protected path .knos/acceptance/7/blackbox.py: the terms and the acceptance bundle are fixed at funding"]


def test_a_task_that_breaks_the_schema_is_not_loaded(tmp_path, monkeypatch):
    import shutil
    shutil.copytree(ROOT / "tasks" / "rle", tmp_path / "rle")
    monkeypatch.setattr(tb, "TASKS", tmp_path)
    assert tb.load("rle")["slug"] == "rle"
    spec = json.loads((tmp_path / "rle" / "task.json").read_text(encoding="utf-8"))
    for change, said in (({"amount": 6_000_000}, "from 2 to 5 test USDC"), ({"statement": "Reverse it."}, "first line"), ({"labels": ["bounty"]}, "labels are"),
                         ({"deadline_days": 0}, "deadline_days"), ({"wrong": ["wrong_1.py"]}, "three wrong"), ({"reference": "gone.py"}, "gone.py is not there")):
        (tmp_path / "rle" / "task.json").write_text(json.dumps({**spec, **change}), encoding="utf-8")
        with pytest.raises(tb.Stop, match=said):
            tb.load("rle")


# ---- a forge that is a dictionary ---------------------------------------------------------------------------------------------
class Forge:
    def __init__(self, first: int = 4):
        self.issues: list[dict] = []
        self.comments: dict[int, list[dict]] = {}
        self.files: dict[str, bytes] = {"words.py": b"print()\n",        # and the two callers, as a rebuild of the playground writes them
                                        ".github/workflows/knos.yml": (ROOT / "examples" / "knos-workflow.yml").read_bytes(),
                                        ".github/workflows/knos-check.yml": (ROOT / "examples" / "knos-check.yml").read_bytes()}
        self.commits: list[str] = []
        self.pulls: list[dict] = []
        self.pull_files: dict[int, list[dict]] = {}
        self.runs: list[dict] = []
        self.labels: set[str] = {"good first issue"}
        self.next, self.wrote, self.asked, self.day, self.fail_at = first, [], [], "2026-10-07", ""
        self._trees: dict[str, dict] = {}

    def issue(self, title: str, body: str, user: dict = OWNER, labels=("knos-funded",), state: str = "open", day: str | None = None) -> int:
        n, self.next = self.next, self.next + 1
        self.issues.append({"number": n, "title": title, "body": body, "user": user, "state": state, "labels": [{"name": x} for x in labels],
                            "created_at": f"{day or self.day}T09:00:00Z"})
        return n

    def __call__(self, method: str, path: str, body: dict | None = None):
        if method != "GET":
            if self.fail_at and self.fail_at in path:
                raise tb.Stop(f"GitHub answered 502 to {method} {path}")
            self.wrote.append((method, path))
        else:
            self.asked.append(path)
        where = path.split("?")[0].split("/")[3:]
        if method == "GET" and where == ["issues"]:
            return [] if "page=1" not in path else [i for i in reversed(self.issues) if any(x["name"] == "knos-funded" for x in i["labels"])]
        if method == "POST" and where == ["issues"]:
            assert body["body"].splitlines()[0] == tb.FIRST
            assert set(body["labels"]) <= self.labels, "GitHub would make the labels up with no description"
            return {"number": self.issue(body["title"], body["body"], labels=body["labels"])}
        if len(where) == 2 and where[0] == "issues" and method == "PATCH":
            assert body == {"state": "closed", "state_reason": "not_planned"}
            next(i for i in self.issues if i["number"] == int(where[1]))["state"] = "closed"
            return {}
        if len(where) == 3 and where[0] == "issues" and where[2] == "comments":
            if method == "GET":
                return self.comments.get(int(where[1]), [])
            self.comments.setdefault(int(where[1]), []).append({"user": OWNER, "body": body["body"]})
            return {}
        if where[:1] == ["labels"]:
            if method == "GET":
                return {"name": where[1]} if where[1].replace("%20", " ") in self.labels else None
            self.labels.add(body["name"])
            return {}
        if where[:1] == ["contents"]:
            key = "/".join(where[1:])
            data = self.files.get(key)
            if data is None:            # a folder: GitHub lists what is directly in it
                inside = {k[len(key) + 1:].split("/")[0]: k for k in self.files if k.startswith(key + "/")}
                return [{"type": "dir" if "/" in k[len(key) + 1:] else "file", "path": f"{key}/{name}"} for name, k in sorted(inside.items())] or None
            return {"content": base64.b64encode(data).decode()}
        if where[:2] == ["git", "ref"]:
            return {"object": {"sha": f"c{len(self.commits)}"}}
        if where[:2] == ["git", "commits"] and method == "GET":
            return {"tree": {"sha": f"t{len(self.commits)}"}}
        if where[:2] == ["git", "trees"]:
            assert body["base_tree"] == f"t{len(self.commits)}"
            self._trees["new"] = {e["path"]: e["content"].encode("utf-8") if "content" in e else e["sha"] for e in body["tree"]}
            assert all(v is None or isinstance(v, bytes) for v in self._trees["new"].values()), "a tree entry adds content or removes a path"
            return {"sha": "new"}
        if where[:2] == ["git", "commits"]:
            assert body["parents"] == [f"c{len(self.commits)}"] and body["tree"] == "new"
            return {"sha": "made", "message": body["message"]}
        if where[:2] == ["git", "refs"]:
            assert method == "PATCH" and body == {"sha": "made", "force": False}
            for rel, data in self._trees.pop("new").items():
                if data is None:
                    assert rel in self.files, "git refuses to remove a path the tree does not hold"
                    del self.files[rel]
                else:
                    self.files[rel] = data
            self.commits.append("made")
            return {}
        if where == ["actions", "runs"]:
            assert "status=action_required" in path
            return {"workflow_runs": self.runs if "page=1" in path else []}
        if where == ["pulls"]:
            return self.pulls if "page=1" in path else []
        if len(where) == 3 and where[0] == "pulls" and where[2] == "files":
            return self.pull_files.get(int(where[1]), []) if "page=1" in path else []
        raise AssertionError(f"the board asked the forge something it has no business asking: {method} {path}")


def payable(where, pull):
    """knos.tasks.why's answer for an order nothing stands in the way of: the chain the tests make up has only such orders."""
    return {"code": "retry", "said": f"Nothing read here stands in the way of {where}.", "fix": "", "note": tb.FIRST}


def run(forge: Forge, *argv: str, ask=None, now: float = NOW, why=payable) -> tuple[int, str, list[float]]:
    said, slept = [], []
    code = tb.main(list(argv), gh=forge, ask=ask or (lambda *a: pytest.fail("the chain was asked")), now=lambda: now, say=said.append, sleep=slept.append,
                   why=why)
    return code, "\n".join(said), slept


def test_a_plan_sends_nothing_and_says_the_budget_and_what_pays():
    forge = Forge()
    code, said, _ = run(forge, "plan")
    assert code == 0 and forge.wrote == []
    assert "0 funded tasks open, 0 half opened, 8 to open, for a target of 8." in said
    assert "Today (UTC): 0.00 test USDC opened of a budget of 45.00 test USDC; after this run" in said
    assert "No Balance was named: only the devnet faucet may pay" in said
    assert "open roman: 5.00 test USDC, fee 0.05 test USDC, 14 days" in said
    code, said, _ = run(forge, "open")                                       # no --apply: the same, and it says so
    assert code == 0 and forge.wrote == [] and "A dry run: nothing was sent." in said and 'would open an issue for roman: "Write a whole number as a Roman numeral"' in said
    code, said, _ = run(forge, "open", "--apply")                            # what pays is never assumed
    assert code == 1 and forge.wrote == [] and "say what pays" in said
    assert run(forge, "plan", "--repo", "octo/elsewhere")[0] == 1 and run(forge, "plan", "-n", "25")[0] == 1


def test_open_keeps_n_tasks_funded_and_a_second_run_does_nothing():
    forge = Forge()
    code, said, slept = run(forge, "open", "--apply", "--faucet")
    assert code == 0 and "8 tasks written" in said
    mine = [i for i in forge.issues]
    assert [i["number"] for i in mine] == list(range(4, 12)) and [tb.MARK.search(i["body"]).group(1) for i in mine] == SLUGS[:8]
    assert forge.labels >= set(tb.LABELS) and all({x["name"] for x in i["labels"]} == set(tb.LABELS) for i in mine)
    assert slept == [tb.PACE] * 7                                            # the faucet serves the repository once a minute
    assert len(forge.commits) == 8                                           # one commit for one task: its checks and its line on the board
    assert json.loads(forge.files["board.json"]) == {"v": 1, "tasks": {str(n): s for n, s in zip(range(4, 12), SLUGS)}}
    for n, slug in zip(range(4, 12), SLUGS):
        task = tb.load(slug)
        assert {k.split("/")[-1]: v for k, v in forge.files.items() if k.startswith(f".knos/acceptance/{n}/")} == tb.bundle(task, n)
        assert [c["body"] for c in forge.comments[n]] == [tb.fund_line(task)]
        order = [w for w in forge.wrote if w[1].endswith(f"issues/{n}/comments") or w[1].endswith("git/refs/heads/main")]
        assert forge.wrote.index((("POST", f"repos/{playground.REPO}/issues/{n}/comments"))) > [i for i, w in enumerate(forge.wrote) if w[1].endswith("git/refs/heads/main")][n - 4], order
    wrote = len(forge.wrote)
    code, said, slept = run(forge, "open", "--apply", "--faucet")
    assert code == 0 and len(forge.wrote) == wrote and slept == [] and "8 funded tasks open, 0 half opened, 0 to open" in said
    # one is solved and closed: the next run opens the next task of the catalogue, never one that is open or the one just done
    forge.issues[2]["state"] = "closed"
    forge.day = "2026-10-08"
    code, said, _ = run(forge, "open", "--apply", "--faucet", now=NOW + 86_400)
    assert code == 0 and tb.MARK.search(forge.issues[-1]["body"]).group(1) == SLUGS[8] and len([i for i in forge.issues if i["state"] == "open"]) == 8


def test_a_run_that_stopped_half_way_is_taken_up_where_it_stopped():
    forge = Forge()
    forge.fail_at = "git/trees"                                              # the issue is opened, then GitHub fails
    code, said, _ = run(forge, "open", "--apply", "--faucet", "-n", "2")
    assert code == 1 and "502" in said and len(forge.issues) == 1 and forge.commits == [] and forge.comments == {}
    forge.fail_at = "issues/5/comments"                                      # the second task's checks are committed, its funding fails
    code, said, _ = run(forge, "open", "--apply", "--faucet", "-n", "2")
    assert code == 1 and [i["number"] for i in forge.issues] == [4, 5] and len(forge.commits) == 2 and list(forge.comments) == [4]
    forge.fail_at = ""
    code, said, _ = run(forge, "plan", "-n", "2")
    assert "1 funded tasks open, 1 half opened, 0 to open" in said and "finish #5 rle: fund it" in said
    code, said, _ = run(forge, "open", "--apply", "--faucet", "-n", "2")
    assert code == 0 and len(forge.issues) == 2 and len(forge.commits) == 2 and [len(forge.comments[n]) for n in (4, 5)] == [1, 1]


def test_the_days_budget_stops_it_and_a_strangers_marker_opens_nothing():
    forge = Forge()
    code, said, _ = run(forge, "open", "--apply", "--faucet", "--budget", "12")      # roman 5.05, rle 5.05; caesar does not fit
    assert code == 0 and len(forge.issues) == 2
    assert "today's budget of 12.00 test USDC is used up to 10.10 test USDC: caesar (5.05 test USDC with its fee) waits for tomorrow (UTC)" in said
    code, said, _ = run(forge, "open", "--apply", "--faucet", "--budget", "12")      # the budget is counted from the issues, not from memory
    assert code == 0 and len(forge.issues) == 2 and "10.10 test USDC opened of a budget of 12.00 test USDC" in said
    forge.day = "2026-10-08"
    code, said, _ = run(forge, "open", "--apply", "--faucet", "--budget", "12", now=NOW + 86_400)
    assert len(forge.issues) == 4                                            # tomorrow: two more
    # an issue with the marker that the owner did not open is no task of the board's (a stranger cannot label, and this holds if one could)
    forge.issue("Fake", "x\n<!-- knos-task: wrap amount=5000000 days=14 -->", user=STRANGER)
    state = tb.read(forge, playground.REPO, playground.OWNER_ID)
    assert "wrap" not in {r["slug"] for r in state["rows"]} and len(state["rows"]) == 4


def test_the_five_tasks_that_are_not_code_open_first_paid_on_the_merge_within_the_days_budget(tmp_path):
    """`--kinds`: tasks/outside/ as funded issues. No checks are theirs: the starter task's checks under the issue's number
    go in the same commit as its line on the board, so the funding is merge mode, and a rebuild of the playground keeps it so."""
    from knos import tasks
    kinds = tb.kinds()
    assert [k["slug"] for k in kinds] == [tb.KIND + k for k in tasks.KINDS] and len(kinds) == 5
    for k in kinds:
        assert (ROOT / "tasks" / "outside" / f"{k['kind']}.json").read_text(encoding="utf-8") == tasks.kind_file(k["kind"])
        assert k["amount"] == 5_000_000 and k["statement"].startswith(tb.FIRST + "\n") and tb.fund_line(k) == f"/knos fund 5 days {tb.KIND_DAYS}"
    forge = Forge()
    for n in range(4, 9):                                                    # the starter task's checks, as small_repos.slots writes them
        forge.files.update({f".knos/acceptance/{n}/{name}": b"x\n" for name in ("README.md", "blackbox.py", "cases.json")})
    code, said, _ = run(forge, "plan", "--kinds", "-n", "1", "--budget", "12")
    assert code == 0 and forge.wrote == [] and "open outside-reproduce: 5.00 test USDC, fee 0.05 test USDC, 30 days" in said
    assert "today's budget of 12.00 test USDC is used up to 10.10 test USDC: outside-fund (5.05 test USDC with its fee) waits for tomorrow (UTC)" in said
    code, said, slept = run(forge, "open", "--apply", "--faucet", "--kinds", "-n", "1")
    assert code == 0 and "6 tasks written" in said and slept == [tb.PACE] * 5
    assert [tb.MARK.search(i["body"]).group(1) for i in forge.issues] == [k["slug"] for k in kinds] + [SLUGS[0]]
    for n, k in zip(range(4, 9), kinds):
        body = forge.issues[n - 4]["body"]
        assert body.splitlines()[0] == tb.FIRST and k["evidence"] in body and f"`outside/{k['kind']}/<your login>.json`" in body and "Closes #" in body
        assert not [f for f in forge.files if f.startswith(f".knos/acceptance/{n}/")], "a task that is not code keeps no checks: it is merge mode"
        assert [c["body"] for c in forge.comments[n]] == [f"/knos fund 5 days {tb.KIND_DAYS}"]
    assert {k.split("/")[-1] for k in forge.files if k.startswith(".knos/acceptance/9/")} == set(tb.bundle(tb.load(SLUGS[0]), 9))
    board = {int(k): v for k, v in json.loads(forge.files["board.json"])["tasks"].items()}
    assert board == {**{n: k["slug"] for n, k in zip(range(4, 9), kinds)}, 9: SLUGS[0]}
    wrote = len(forge.wrote)                                                 # a second run, with or without --kinds, opens nothing again
    for argv in (("--kinds",), ()):
        code, said, _ = run(forge, "open", "--apply", "--faucet", "-n", "1", *argv)
        assert code == 0 and len(forge.wrote) == wrote and "not in tasks/" not in said and "6 funded tasks open, 0 half opened, 0 to open" in said
    s = json.loads(run(forge, "status", "--json", "-n", "1")[1])
    assert [(t["issue"], t["kind"], t["file"], t["state"]) for t in s["tasks"][:2]] == [(4, "reproduce", "outside/reproduce/", "funding asked"),
                                                                                     (5, "shadow", "outside/shadow/", "funding asked")]
    assert s["tasks"][5]["kind"] == "code" and s["budget"]["opened"] == 6 * 5_050_000 and "A maintainer checks it and merges." in s["tasks"][0]["accept"]
    assert [t["kind"] for t in tasks.rows(s)] == [k["kind"] for k in kinds] + ["code"]
    # the release's rebuild of the playground keeps them merge mode: no checks under their numbers, the code task's own
    small = _script("small_repos")
    out = small.files("knos-playground", board)
    assert not [f for f in out if any(f.startswith(f".knos/acceptance/{n}/") for n in range(4, 9))]
    assert {f.split("/")[-1] for f in out if f.startswith(".knos/acceptance/9/")} == set(tb.bundle(tb.load(SLUGS[0]), 9))
    assert {f for f in out if f.startswith(".knos/acceptance/10/")} and out["board.json"] == forge.files["board.json"]


def test_a_task_whose_order_no_merge_can_pay_is_closed_with_the_chains_sentence_and_opened_again():
    """A release rebuilds the playground at the next commit of the workflows, and every order funded before names the
    commit before: no merge can pay it (knos-playground #6 to #13 in 0.3.20). The board reads each order back and
    opens the task again, within the day's budget."""
    from knos import tasks
    forge = Forge()
    run(forge, "open", "--apply", "--faucet", "-n", "3")
    assert [i["state"] for i in forge.issues] == ["open"] * 3
    asked = []

    def why(where, pull):
        asked.append((where, pull))
        if where.endswith("#5"):
            return tasks.explain({"where": where, "orders": [{"state": "open", "wf_public": True, "wf_sha": "b" * 40, "called": False}]})
        return payable(where, pull)
    forge.day = "2026-10-08"
    wrote = len(forge.wrote)
    code, said, _ = run(forge, "plan", "-n", "3", now=NOW + 86_400, why=why)
    assert code == 0 and len(forge.wrote) == wrote and sorted(asked) == [(f"{playground.REPO}#{n}", None) for n in (4, 5, 6)]
    assert (f"  stranded #5: The order on {playground.REPO}#5 was funded through commit bbbbbbbbbbbb of the public workflows, which the repository no "
            "longer calls, so the public worker's signed run cannot pay it. open --apply closes it with that sentence, and its task can be opened again.") in said
    assert "2 funded tasks open, 0 half opened, 1 to open" in said
    code, said, _ = run(forge, "open", "--apply", "--faucet", "-n", "3", now=NOW + 86_400, why=why)
    assert code == 0 and [i["state"] for i in forge.issues] == ["open", "closed", "open", "open"]
    assert forge.comments[5][-1]["body"].startswith(f"The order on {playground.REPO}#5 was funded through commit bbbbbbbbbbbb") and tb.FIRST in forge.comments[5][-1]["body"]
    assert tb.MARK.search(forge.issues[-1]["body"]).group(1) == SLUGS[3] and [c["body"] for c in forge.comments[7]] == [tb.fund_line(tb.load(SLUGS[3]))]
    asked.clear()                                                            # closed now: never read, never closed twice
    code, said, _ = run(forge, "open", "--apply", "--faucet", "-n", "3", now=NOW + 86_400, why=why)
    assert code == 0 and "3 funded tasks open, 0 half opened, 0 to open" in said and (f"{playground.REPO}#5", None) not in asked

    def down(where, pull):
        raise tasks.Stop("devnet did not answer")
    wrote = len(forge.wrote)
    code, said, _ = run(forge, "open", "--apply", "--faucet", "-n", "3", now=NOW + 86_400, why=down)
    assert code == 1 and len(forge.wrote) == wrote and "could not be read (devnet did not answer): nothing was sent" in said


@pytest.fixture(scope="module")
def chain():
    from _order import USDC, OrderChain
    c = OrderChain()
    return c, USDC


def test_it_never_funds_below_the_payers_reserve_read_from_the_program_in_the_simulator(chain):
    c, usdc = chain
    from solders.pubkey import Pubkey
    asked = []

    def ask(method, params):
        asked.append((method, params))
        return {"value": {"amount": str(c.balance(Pubkey.from_string(params[0])))}}
    held = tb.held(str(c.bal), ask)
    assert held == 100_000 * usdc and asked == [("getTokenAccountBalance", [str(pay.baltok_pda(c.bal))])]
    # the reserve leaves room for exactly two tasks (5.05 each), and the third is not opened
    reserve = held / usdc - 11
    forge = Forge()
    code, said, _ = run(forge, "open", "--apply", "--balance", str(c.bal), "--reserve", str(reserve), ask=ask)
    assert code == 0 and [tb.MARK.search(i["body"]).group(1) for i in forge.issues] == ["roman", "rle"]
    assert "The payer's Balance holds 100000.00 test USDC and keeps a reserve of 99989.00 test USDC." in said
    assert "caesar (5.05 test USDC with its fee) is not opened" in said
    # the program takes what the board counted: the amount and the fee on top leave the Balance when the order is funded
    before = c.balance(pay.baltok_pda(c.bal))
    c.fund_balance(901, 5 * usdc)
    assert before - c.balance(pay.baltok_pda(c.bal)) == tb.cost(tb.load("roman")) == 5_050_000
    # a reserve the Balance does not hold: nothing is opened; a chain that does not answer: nothing is opened
    empty = Forge()
    code, said, _ = run(empty, "open", "--apply", "--balance", str(c.bal), "--reserve", "100000", ask=ask)
    assert code == 0 and empty.issues == [] and "is not opened" in said
    code, said, _ = run(empty, "open", "--apply", "--balance", str(c.bal), ask=lambda *a: None)
    assert code == 1 and empty.wrote == [] and "devnet did not say what the Balance" in said
    assert run(empty, "open", "--apply", "--balance", "not-an-address", ask=ask)[0] == 1 and empty.wrote == []
    assert run(empty, "open", "--apply", "--balance", str(c.bal), "--faucet", ask=ask)[0] == 1 and empty.wrote == []


def test_status_lists_the_board_and_the_runs_that_wait_and_approves_nothing():
    forge = Forge()
    run(forge, "open", "--apply", "--faucet", "-n", "3")
    wrote = list(forge.wrote)
    forge.pulls = [
        {"number": 20, "title": "Roman numerals", "state": "open", "user": STRANGER, "body": "Closes #4", "head": {"sha": "aaa"}, "merged_at": None},
        {"number": 21, "title": "rle, and a little more", "state": "open", "user": {"login": "eve", "id": 666}, "body": "closes #5", "head": {"sha": "bbb"}, "merged_at": None},
        {"number": 22, "title": "caesar", "state": "closed", "user": STRANGER, "body": "Fixes #6", "head": {"sha": "ccc"}, "merged_at": "2026-10-07T10:00:00Z"},
        {"number": 23, "title": "own work", "state": "open", "user": OWNER, "body": "Closes #6", "head": {"sha": "ddd"}, "merged_at": None},
        {"number": 24, "title": "typo", "state": "open", "user": STRANGER, "body": "no task", "head": {"sha": "eee"}, "merged_at": None}]
    forge.runs = [{"head_sha": "aaa", "status": "action_required"}, {"head_sha": "bbb", "status": "action_required"}, {"head_sha": "zzz"}]
    forge.pull_files = {20: [{"filename": "tasks/roman.py", "status": "modified"}],
                        21: [{"filename": "tasks/rle.py", "status": "modified"}, {"filename": ".knos/acceptance/5/cases.json", "status": "modified"},
                             {"filename": ".github/workflows/knos.yml", "status": "modified"}]}
    code, said, _ = run(forge, "status", "--json")
    s = json.loads(said)
    assert code == 0 and forge.wrote == wrote                                # it reads; it writes nothing
    assert not any("approve" in p or "rerun" in p for p in forge.asked)
    assert s["v"] == 1 and s["read"] is True and s["repository"] == playground.REPO and s["at"] == "2026-10-07T12:00:00Z" and s["note"] == tb.FIRST
    assert [(t["issue"], t["slug"], t["amount"], t["currency"], t["deadline"], t["state"], t["pulls"]) for t in s["tasks"]] == [
        (4, "roman", 5_000_000, "test USDC", "2026-10-21T09:00:00Z", "funding asked", [20]), (5, "rle", 5_000_000, "test USDC", "2026-10-21T09:00:00Z", "funding asked", [21]),
        (6, "caesar", 5_000_000, "test USDC", "2026-10-21T09:00:00Z", "funding asked", [])]
    assert s["tasks"][0]["url"] == f"https://github.com/{playground.REPO}/issues/4" and s["budget"] == {"day": "2026-10-07", "limit": 45_000_000, "opened": 15_150_000}
    assert {k: s["outside_pulls"][k] for k in ("received", "merged", "accounts", "paid")} == {"received": 3, "merged": 1, "accounts": 2, "paid": None}
    assert [(w["pull"], w["by"], w["closes"]) for w in s["awaiting_approval"]] == [(20, "stranger", [4]), (21, "eve", [5])]
    assert s["awaiting_approval"][1]["files"] == [{"path": "tasks/rle.py", "status": "modified", "rule": "allowed"},
                                                  {"path": ".knos/acceptance/5/cases.json", "status": "modified", "rule": "refused:terms"},
                                                  {"path": ".github/workflows/knos.yml", "status": "modified", "rule": "refused:workflow"}]
    code, said, _ = run(forge, "status")
    assert "WAITS FOR APPROVAL: #21 by @eve" in said and "modified  .knos/acceptance/5/cases.json  [refused:terms]" in said
    assert "Nothing was approved." in said and "3 received from 2 accounts, 1 merged; paid is not read here" in said
    assert said.splitlines()[0].endswith("3 of 8 tasks open. Test USDC, no monetary value.")
    forge.runs = []
    assert "No pull request has a run waiting for approval." in run(forge, "status")[1]
    asked = len(forge.asked)                                                 # a build with no network asks nobody and says it read nothing
    code, said, _ = run(forge, "status", "--json", "--empty")
    assert code == 0 and len(forge.asked) == asked and json.loads(said) == {"v": 1, "read": False, "repository": playground.REPO, "note": tb.FIRST, "tasks": []}


def test_the_board_funds_only_through_the_public_pinned_workflows_and_says_so():
    """An order names the workflows it was funded through, and the public worker's run is signed for the public ones
    only: funded through a staging copy, a merged pull request is never paid. So `open` reads the callers first."""
    pub = _script("pinned_workflows")
    pin = pub.pin()
    forge = Forge()
    assert tb.unpinned(forge, playground.REPO) == [] and forge.wrote == []
    code, said, _ = run(forge, "plan", "-n", "2")
    assert code == 0 and "funds through the public pinned workflows: checked in the playground's own workflow files." in said
    public = forge.files[".github/workflows/knos.yml"]
    for staged, why in ((public.replace(b"drexthealpha/knos-workflows/", b"drexthealpha/knos-workflows-rc/"), "of drexthealpha/knos-workflows-rc, which is not the public drexthealpha/knos-workflows"),
                        (public.replace(pin.encode(), b"5" * 40), f"at 555555555555, and the published commit is {pin[:12]}"),
                        (b"on: push\njobs: {}\n", "calls no pinned workflow"), (None, "could not be read")):
        forge = Forge()
        if staged is None:
            del forge.files[".github/workflows/knos.yml"]
        else:
            forge.files[".github/workflows/knos.yml"] = staged
        assert staged != public and any(why in line for line in tb.unpinned(forge, playground.REPO)), why
        code, said, slept = run(forge, "open", "--apply", "--faucet", "-n", "2")
        assert code == 1 and forge.wrote == [] and slept == [] and "not public: " in said                 # no issue, no commit, no funding comment
        assert said.splitlines()[-1] == ("task board: nothing was sent: an order funded now would name workflows the public worker's run is not signed for, "
                                         "and no merge could pay it")
        s = json.loads(run(forge, "status", "--json")[1])
        assert s["workflows"]["public"] is False and why in " ".join(s["workflows"]["problems"])
        assert "NOT FUNDED THROUGH THE PUBLIC WORKFLOWS: " in run(forge, "status")[1]
    assert tb.unpinned(Forge(), playground.REPO, pin=pub.PLACEHOLDER, public=pub.REPO)[0].startswith("this checkout's examples name no published commit")


def test_the_boards_document_is_what_an_agent_reads_and_why_is_one_sentence():
    from knos import tasks
    forge = Forge()
    run(forge, "open", "--apply", "--faucet", "-n", "2")
    forge.pulls = [{"number": 22, "title": "roman", "state": "closed", "user": STRANGER, "body": "Fixes #4", "head": {"sha": "ccc"}, "merged_at": "2026-10-07T10:00:00Z"}]
    forge.comments[22] = [{"user": {"type": "Bot", "login": "github-actions[bot]"}, "body": "Knos: held for @stranger. 5.00 test USDC for issue #4 waits for them."}]
    doc = json.loads(run(forge, "status", "--json")[1])
    assert doc["workflows"] == {"public": True, "problems": []}
    assert doc["held"] == [{"pull": 22, "for": "stranger", "state": "held", "instruction": "comment `/knos address <your Solana address>` on the pull request",
                            "url": f"https://github.com/{playground.REPO}/pull/22",
                            "said": "Held for @stranger: comment `/knos address <your Solana address>` on the pull request. Test USDC, no monetary value."}]
    assert "HELD: #22 for @stranger: comment `/knos address <your Solana address>` on the pull request" in run(forge, "status")[1]
    first, second = tasks.rows(doc)
    assert (first["id"], first["file"], first["amount"], first["kind"]) == (f"{playground.REPO}#4", "tasks/roman.py", 5_000_000, "code")
    assert first["accept"] == tasks.ACCEPT == doc["tasks"][0]["accept"] and first["pays"] == tasks.PAYS and "test USDC" in first["pays"]
    took = tasks.take(doc, "rle", login="stranger", branch="rle")
    assert took["pull_request"]["body"] == "Closes #5" and took["steps"][0].startswith(f"Edit tasks/rle.py in a fork of {playground.REPO}")
    asked: list = []

    def why(where, pull):
        asked.append((where, pull))
        return tasks.explain({"where": where, "pull": pull, "merged": True, "closes": True, "orders": [{"state": "open", "wf_public": False, "wf_sha": "5" * 40}]})
    said: list[str] = []
    assert tb.main(["why", "drexthealpha/knos-e2e#25", "--pull", "38"], gh=forge, say=said.append, why=why) == 0 and asked == [("drexthealpha/knos-e2e#25", 38)]
    assert said == ["The order on drexthealpha/knos-e2e#25 was funded through a copy of the workflows that is not the public one (a staging copy), "
                    "so the public worker's signed run cannot pay it.\nFix: A maintainer comments `/knos tip <amount>` on the merged pull request #38; the old order "
                    "goes back to its funder at its deadline. Fund the next task only where the repository calls drexthealpha/knos-workflows at the published commit."]


def test_the_sites_build_writes_the_empty_board_without_solders():
    """scripts/build_site.sh runs `status --json --empty` with a bare python3 (tests.yml's web job installs no package):
    the script must not import knos.settle.v2.pay, and so solders, to say it read nothing."""
    blocked = ("import runpy, sys; sys.modules['solders'] = None; sys.argv = [sys.argv[1], 'status', '--json', '--empty']; "
               "runpy.run_path(sys.argv[0], run_name='__main__')")
    run = subprocess.run([sys.executable, "-c", blocked, str(ROOT / "scripts" / "task_board.py")], capture_output=True, text=True, encoding="utf-8",
                         env={**os.environ, "PYTHONPATH": ""}, timeout=60)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == {"v": 1, "read": False, "repository": playground.REPO, "note": tb.FIRST, "tasks": []}


# ---- the repository a release publishes keeps what the board wrote --------------------------------------------------------------
def test_the_playground_holds_every_tasks_starting_file_and_a_rebuild_keeps_the_boards_checks(tmp_path):
    small = _script("small_repos")
    plain = small.task_files()
    assert len([k for k in plain if k.endswith(".examples.json")]) == 24 and "board.json" not in plain
    for t in TASKS:
        assert plain[t["file"]] == (ROOT / "tasks" / t["slug"] / "start.py").read_bytes()
        assert json.loads(plain[f"tasks/{Path(t['file']).stem}.examples.json"]) == t["public"]
    with_board = small.task_files({9: "wrap", 4: "roman"})
    assert {k.split("/")[-1]: v for k, v in with_board.items() if k.startswith(".knos/acceptance/9/")} == tb.bundle(tb.load("wrap"), 9)
    assert with_board["board.json"] == tb.board_file({4: "roman", 9: "wrap"}) and small.board_of(tmp_path) == {}
    (tmp_path / "board.json").write_bytes(with_board["board.json"])
    assert small.board_of(tmp_path) == {4: "roman", 9: "wrap"}
    with pytest.raises(SystemExit, match="tasks/ has none of that name"):
        small.task_files({4: "gone"})
    # check.py, as the stranger runs it: the starting file fails its examples, the reference passes them
    (tmp_path / "tasks").mkdir()
    (tmp_path / "check.py").write_text(small.CHECK, encoding="utf-8")
    (tmp_path / "tasks" / "top_word.examples.json").write_bytes(plain["tasks/top_word.examples.json"])
    (tmp_path / "tasks" / "top_word.py").write_bytes(plain["tasks/top_word.py"])
    try_it = lambda *a: subprocess.run([sys.executable, str(tmp_path / "check.py"), *a], capture_output=True, text=True, encoding="utf-8")  # noqa: E731
    assert try_it("top-word").returncode == 1 and "expected 'the'" in try_it("top-word").stdout
    (tmp_path / "tasks" / "top_word.py").write_bytes((ROOT / "tasks" / "top-word" / "reference.py").read_bytes())
    assert try_it("top-word").returncode == 0 and "all 3 public examples agree" in try_it("top-word").stdout
    assert try_it().returncode == 2 and "one of: top-word" in try_it().stdout


# ---- honest counts ------------------------------------------------------------------------------------------------------------
def test_a_stranger_paid_for_a_knos_funded_task_is_an_outside_payee_and_never_an_outside_funder():
    rules = _script("outsiders")
    own = frozenset({playground.OWNER_ID})
    job = lambda issue, payee=0, state="open": {"repo": 77, "issue": issue, "by": playground.OWNER_ID, "owner": playground.OWNER_ID, "faucet": True,  # noqa: E731
                                                 "state": state, "payee": payee, "to": "wallet-of-payee" if payee else None, "source": "bal"}
    jobs = [job(4, 4242, "paid"), job(5), job(6, 4242, "paid"), {**job(9, 555, "paid"), "repo": 78}]
    pull = lambda n, uid, body, merged=None: {"number": n, "user": {"id": uid}, "body": body, "merged_at": merged}  # noqa: E731
    pulls = [pull(20, 4242, "Closes #4", "2026-10-07T10:00:00Z"), pull(21, 666, "closes #5"), pull(22, 4242, "Fixes #6", "2026-10-07T11:00:00Z"),
             pull(23, playground.OWNER_ID, "Closes #5"), pull(24, 666, "Closes #99"), pull(25, 777, "Closes #4", "2026-10-07T12:00:00Z")]
    got = rules.pulls(pulls, jobs, own, repo=77)
    assert {k: got[k] for k in ("measured", "received", "merged", "paid", "accounts", "payees", "funders", "summed")} == {
        "measured": True, "received": 4, "merged": 3, "paid": 2, "accounts": 3, "payees": 1, "funders": 0, "summed": False}
    # the three numbers of the page agree: the stranger is one payee, and nobody outside funded anything
    counted = rules.count([j for j in jobs if j["repo"] == 77], own, frozenset())
    assert (counted["funders"], counted["repositories"], counted["payees"]) == (0, 0, 1)
    # what was not read is not a zero
    for forge_side, chain_side in ((None, jobs), (pulls, None)):
        blank = rules.pulls(forge_side, chain_side, own, repo=77)
        assert blank["measured"] is False and blank["received"] is None and blank["paid"] is None
    assert "never" not in rules.PULL_DEFINITIONS["received"] and "outside PAYEE" in rules.PULL_DEFINITIONS["payees"]
