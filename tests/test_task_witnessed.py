"""examples/witnessed/witness.py: the independently witnessed transaction, step by step, against a simulated GitHub and
chain. Every comment the script posts is read by knos.commands.parse, as the workflow reads it, and the simulated
funding asks what knos.flow asks of an `auto` order (black-box acceptance checks). "knos check" on the pull request
passes any work, as the real one does (it runs none of the pull request's code); the judge job runs the committed
blackbox.py for real on the submitted file. The statements, the archive and the stand-alone verifier inside it run for
real (`python -m knos`, `python -I verify.py`). No network, no clock, no sleep."""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from knos import audit, commands, judge, tasks
from test_audit import DAY, T0, U, funded, line, paid

ROOT = Path(__file__).resolve().parents[1]
LOGIN, ME = "stranger", 5001
DAYS = "2026-09-02"                                 # T0 + 1 day: the day the simulated chain holds the order
FUNDED, PAID, FAUCET, DEPOSIT = "F" * 64, "P" * 64, "A" * 64, "D" * 64


def _witness():
    spec = importlib.util.spec_from_file_location("witness_example", ROOT / "examples" / "witnessed" / "witness.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


W = _witness()


def tx(sig: str) -> str:
    return f"https://explorer.solana.com/tx/{sig}?cluster=devnet"


class World(W.Shell):
    """GitHub, the relay and the chain, as dictionaries. The check runs words.py on the committed pairs."""

    def __init__(self, folder: Path, replay_pays: bool = False):
        super().__init__(tries=3, pause=0)
        self.folder, self.replay_pays = folder, replay_pays
        self.comments: dict[tuple[str, int], list[dict]] = {}
        self.ids, self.commits, self.issues = 100, 0, 0
        self.runs: dict[str, list[dict]] = {}            # check runs by commit: only "knos check", which passes any work
        self.reviews: list[dict] = []                      # the `knos review` runs (event workflow_run), each with its jobs
        self.parsed: list[object] = []                     # what knos.commands made of each comment the stranger posted
        self.clock = 0
        self.chain = [line("balance", T0, "B1", owner=ME, authority="W" * 44, mint="M")]
        self.said: list[list[str]] = []

    def _post(self, repo: str, issue: int, body: str, user: str = LOGIN) -> dict:
        self.ids += 1
        c = {"id": self.ids, "body": body, "user": {"login": user}, "html_url": f"https://github.com/{repo}/issues/{issue}#issuecomment-{self.ids}"}
        self.comments.setdefault((repo, issue), []).append(c)
        return c

    def _at(self) -> str:
        self.clock += 1
        return f"2026-09-02T00:{self.clock // 60:02d}:{self.clock % 60:02d}Z"

    def _bot(self, repo: str, issue: int, body: str) -> None:
        cmd = commands.parse(body, on_pull=None if repo == W.PLAYGROUND else issue == 2)
        self.parsed.append(cmd)
        if isinstance(cmd, commands.Error):
            self._post(repo, issue, cmd.reply, "knos-bot")
            return
        if isinstance(cmd, commands.Fund):        # what knos.flow asks of an `auto` order: black-box checks on the default branch
            folder = self.folder / W.NAME / ".knos" / "acceptance" / str(issue)
            files = {f.name: f.read_bytes() for f in folder.iterdir()} if folder.is_dir() else {}
            if not cmd.auto or cmd.checks != () or not files or judge.black_box(files):
                self._post(repo, issue, "Knos: nothing was funded. `auto` pays the first pull request that passes the acceptance checks, "
                                        "without a merge, so those checks must be black-box.", "knos-bot")
                return
        if isinstance(cmd, commands.Faucet):
            self._post(repo, issue, f"Knos: 20 test USDC sent to `{body.split()[-1]}`.\n\nTransaction: {tx(FAUCET)}", "knos-bot")
        elif isinstance(cmd, commands.Fund):
            self.chain += funded("OrdW", T0 + DAY + 60, FUNDED, 5 * U, by=ME, issue=issue)
            self._post(repo, issue, f"Funded 5 test USDC for this issue under the terms fixed now. {tx(FUNDED)}", "knos-bot")
        elif isinstance(cmd, commands.Settle):
            if self.replay_pays:
                self.chain += paid("OrdW", T0 + DAY + 600, "Q" * 64, [(ME, 5 * U)], 5 * U, 5 * U, 0, pr=2)
                self._post(repo, issue, f"Paid again. {tx('Q' * 64)}", "knos-bot")
            else:
                self._post(repo, issue, "This order is already paid; nothing more is paid.", "knos-bot")

    def _check(self, head: str) -> None:
        """"knos check" passes (it runs no code); then the review's judge job runs the committed blackbox.py on words.py."""
        work = self.folder / W.NAME
        self.runs[head] = [{"name": "check / claims", "status": "completed", "conclusion": "success", "completed_at": self._at(),
                            "html_url": f"https://github.com/check/{head}"}]
        spec = importlib.util.spec_from_file_location("blackbox_" + head, work / ".knos" / "acceptance" / "1" / "blackbox.py")
        box = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(box)

        def ask(argv, stdin):           # $KNOS_RUN python3 words.py, in the pull request's tree
            assert argv == W.RUN
            got = subprocess.run([sys.executable, "-I", *argv[1:]], cwd=work, input=stdin, capture_output=True, timeout=60)
            return got.returncode, got.stdout, got.stderr
        ok = box.check(ask) is None
        n = len(self.reviews) + 1
        self.reviews.append({"id": n, "status": "completed", "created_at": self._at(), "html_url": f"https://github.com/run/{n}",
                             "jobs": [{"name": "review / knos review", "conclusion": "success", "html_url": f"https://github.com/run/{n}/review"},
                                      {"name": "review / judge", "conclusion": "success" if ok else "failure", "html_url": f"https://github.com/run/{head}"}]})
        if ok:
            self.chain += paid("OrdW", T0 + DAY + 300, PAID, [(ME, 5 * U)], 5 * U, 5 * U, 0, pr=2)
            self._post(f"{LOGIN}/{W.NAME}", 2, f"Paid 5 test USDC to @{LOGIN}. {tx(PAID)}", "knos-bot")

    def run(self, argv, cwd=None, stdin=None):
        self.said.append(list(argv))
        a = list(argv)
        if a[:3] == ["gh", "repo", "create"]:
            (Path(cwd) / W.NAME).mkdir()
            return 0, ""
        if a[:2] == ["gh", "api"]:
            path, fields = a[2], dict(f.split("=", 1) for f in a[4::2]) if "-f" in a else {}
            if "body" in fields and path.endswith("/comments"):
                repo, issue = re.fullmatch(r"repos/(.+)/issues/(\d+)/comments", path).groups()
                c = self._post(repo, int(issue), fields["body"])
                self._bot(repo, int(issue), fields["body"])
                return 0, json.dumps(c)
            if "title" in fields:
                self.issues += 1
                return 0, json.dumps({"number": self.issues})
            if path == "user" or path == f"repos/{LOGIN}/{W.NAME}":
                return 0, json.dumps({"id": ME, "owner": {"id": ME}})
            if path.startswith(f"repos/{W.PLAYGROUND}/issues?labels=faucet"):
                return 0, json.dumps([{"number": 3}])
            m = re.fullmatch(r"repos/(.+)/issues/(\d+)/comments\?per_page=100", path)
            if m:
                return 0, json.dumps(self.comments.get((m.group(1), int(m.group(2))), []))
            if path == f"repos/{LOGIN}/{W.NAME}/actions/runs?event=workflow_run&per_page=30":
                return 0, json.dumps({"workflow_runs": [{k: v for k, v in r.items() if k != "jobs"} for r in self.reviews]})
            m = re.fullmatch(rf"repos/{LOGIN}/{W.NAME}/actions/runs/(\d+)/jobs", path)
            if m:
                return 0, json.dumps({"jobs": self.reviews[int(m.group(1)) - 1]["jobs"]})
            m = re.fullmatch(r"repos/.+/commits/(\w+)/check-runs", path)
            if m:
                return 0, json.dumps({"check_runs": self.runs.get(m.group(1), [])})
            return 1, f"no such page {path}"
        if a[:3] == ["gh", "pr", "create"]:
            self._check(f"c{self.commits}")
            return 0, f"https://github.com/{LOGIN}/{W.NAME}/pull/2\n"
        if a[0] == "git":
            if a[1] == "commit":
                self.commits += 1
            if a[1] == "push" and "main" not in a and self.commits >= 3 and f"c{self.commits}" not in self.runs:
                self._check(f"c{self.commits}")
            return 0, f"c{self.commits}\n" if a[1] == "rev-parse" else ""
        if a[:3] == ["knos", "balance", "open"]:
            return 0, "opened"
        if a[:3] == ["knos", "balance", "deposit"]:
            return 0, f"deposited 10 test USDC: {tx(DEPOSIT)}"
        if a[:3] == ["knos", "audit", "export"]:
            out = Path(a[a.index("--out") + 1])
            out.write_text(audit.export(sorted(self.chain, key=lambda e: e["at"]), ME, "csv", first=DAYS, last=DAYS), encoding="utf-8")
            return 0, ""
        if a[0] == "knos":           # events, statement, archive: the real command line
            got = subprocess.run([sys.executable, "-m", "knos", *a[1:]], cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=120)
            return got.returncode, got.stdout + got.stderr
        if a[0] == sys.executable:   # the archive's own verifier
            got = subprocess.run(a, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=120)
            return got.returncode, got.stdout + got.stderr
        return 1, f"not simulated: {a[:3]}"

    def ask(self, said):
        self.said.append(["ask", said])


def _key(state: dict, folder: Path) -> None:
    """The key step without solders' randomness: a fixed key."""
    from solders.keypair import Keypair
    k = Keypair.from_seed(bytes(range(32)))
    (folder / "witness-key.json").write_text(json.dumps(list(bytes(k))), encoding="utf-8")


def test_the_whole_sequence_runs_in_order_leaves_a_link_for_each_step_and_the_record_meets_the_witness_task(tmp_path):
    world = World(tmp_path)
    _key({}, tmp_path)
    s = W.run(LOGIN, tmp_path, world, state={"day": DAYS})
    assert s["done"] == [n for n, _f, _w in W.STEPS]
    assert (s["funded_tx"], s["paid_tx"], s["faucet_tx"], s["budget_tx"]) == (FUNDED, PAID, FAUCET, DEPOSIT)
    assert s["statements_agree"] is True and s["payments"] == 1
    assert s["buyer_statement"] == s["supplier_statement"] and len(s["buyer_statement"]) == 64
    record = json.loads((tmp_path / W.NAME / "witness.json").read_text(encoding="utf-8"))
    assert record["note"] == "Test USDC, no monetary value." and record["repository"] == f"https://github.com/{LOGIN}/{W.NAME}"
    assert tasks.accepts("witness", record) == (True, "") and W.check(record) == (True, "")
    # the order of what reached the world: the wrong work was refused before the right work was pushed, and the replay came after the payment
    bodies = [c["body"] for cs in world.comments.values() for c in cs]
    assert bodies.index("/knos settle") > bodies.index(f"Paid 5 test USDC to @{LOGIN}. {tx(PAID)}")
    assert [j["conclusion"] for r in world.reviews for j in r["jobs"] if j["name"].endswith("judge")] == ["failure", "success"]
    assert [r[0]["conclusion"] for r in world.runs.values()] == ["success", "success"]        # "knos check" passed the wrong work too
    assert s["failed_run"] == "https://github.com/run/c2" and s["passed_run"] == "https://github.com/run/c3"
    # every comment the stranger posted is a command as knos.commands reads it, in the place it belongs
    assert [type(c).__name__ for c in world.parsed] == ["Faucet", "Fund", "Address", "Settle"]
    assert world.parsed[1] == commands.Fund(units=5_000_000, checks=(), auto=True)
    assert ["git", "push", "-q", "origin", "main"] == world.said[-1]                  # the record is the last thing published
    assert not any("drexthealpha/Knos" in " ".join(a) for a in world.said)               # nothing is opened on Knos's repository
    assert "passed" in s["verified"] or s["verified"]


def test_a_replay_that_pays_again_stops_the_run_or_fails_the_record(tmp_path):
    world = World(tmp_path, replay_pays=True)
    _key({}, tmp_path)
    with pytest.raises(W.Stop, match="other than the payment"):
        W.run(LOGIN, tmp_path, world, state={"day": DAYS})
    saved = json.loads((tmp_path / "witness-state.json").read_text(encoding="utf-8"))
    assert saved["done"][-1] == "pass"                                                  # --from replay goes on from here
    good = {"actor_id": ME, "repository_owner_id": ME, "funded_tx": FUNDED, "failed_run": "u", "paid_tx": PAID, "replay_refused": "u",
            "statements_agree": True, "verified": "passed"}
    assert tasks.accepts("witness", {**good, "payments": 2})[0] is False and tasks.accepts("witness", good)[0] is True
    with pytest.raises(W.Stop, match="--from is one of"):
        W.run(LOGIN, tmp_path, world, start="nowhere")


def test_plan_sends_nothing_and_names_every_step(capsys):
    assert W.main(["plan", "--login", LOGIN]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Test USDC, no monetary value.") and all(f" {name} " in out for name, _f, _w in W.STEPS)


def test_the_line_0_3_21_posted_is_refused_by_the_grammar_and_the_run_stops_on_the_reply(tmp_path, monkeypatch):
    world = World(tmp_path)
    _key({}, tmp_path)
    monkeypatch.setattr(W, "FUND_LINE", "/knos fund 5 tests")
    with pytest.raises(W.Stop, match="nothing was funded: .*`tests` is not something this command takes"):
        W.run(LOGIN, tmp_path, world, state={"day": DAYS})
    assert isinstance(world.parsed[-1], commands.Error) and FUNDED not in json.dumps(world.chain)


def test_bare_input_and_output_files_are_not_a_judge_so_auto_is_refused(tmp_path, monkeypatch):
    """What 0.3.21 committed: N.in and N.out. Not black-box, so an `auto` order cannot be funded on them."""
    from knos import accept
    world = World(tmp_path)
    _key({}, tmp_path)
    monkeypatch.setattr(accept, "bundle", lambda *_a: {"1.in": b"one two three\n", "1.out": b"three two one\n"})
    with pytest.raises(W.Stop, match="nothing was funded: .*black-box"):
        W.run(LOGIN, tmp_path, world, state={"day": DAYS})


def test_the_bundle_the_script_commits_is_black_box_and_tells_the_right_answer_from_an_echo(tmp_path):
    from knos import accept
    files = accept.bundle(1, W.RUN, [{"input": a, "output": b} for a, b in W.PAIRS], "text", None)
    assert judge.black_box(files) == "" and set(files) == {"blackbox.py", "cases.json", "README.md"}
    for rel, data in files.items():
        (tmp_path / rel).write_bytes(data)
    (tmp_path / "words.py").write_text(W.RIGHT, encoding="utf-8")
    accept.verify(files, [sys.executable, "-I", "words.py"], tmp_path, tmp_path)      # the right file passes; an echo does not
