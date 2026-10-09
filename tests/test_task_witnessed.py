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

from knos import audit, commands, faucet, judge, statement, tasks
from knos.settle.v2 import pay as pay2
from test_audit import DAY, T0, U, funded, line, paid

ROOT = Path(__file__).resolve().parents[1]
LOGIN, ME = "stranger", 5001
DAYS = "2026-09-02"                                 # T0 + 1 day: the day the simulated chain holds the order
FUNDED, PAID, FAUCET, DEPOSIT, TOPUP = "F" * 64, "P" * 64, "A" * 64, "D" * 64, "T" * 64
ORDER = str(pay2.order_pda(bytes(32), pay2.USDC_DEVNET))           # an address in the order's place: the reply links it


def funded_reply(issue: int) -> str:
    """knos.flow `_funded_order`'s reply, as it is posted (the order linked by `_link(run, "order on Solana", "address", ...)`),
    with the memory's paragraph that `_proposed` may add."""
    order = f"[order on Solana](https://explorer.solana.com/address/{ORDER}?cluster=devnet)"
    return "\n\n".join((
        f"Knos: 5.00 test USDC from the balance `{'B' * 44}` is in escrow for issue #{issue} as a work order ({order}), 14 s after the comment. "
        "The funder pays Knos's fee of 0.05 test USDC on top, so whoever is paid receives the full amount.",
        "The acceptance checks decide. `auto`: the first pull request they pass is paid, with no merge.",
        f"To earn it: open a pull request whose description says `Fixes #{issue}`. Reserve it with `/knos reserve`.",
        "Memory: the last 2 work orders here were paid."))


BOT = "github-actions[bot]"          # who posts both the token and the reply: the workflow's GITHUB_TOKEN
# a caller workflow as the template writes it now, and as an earlier release's template wrote it (another pin)
CALLER = "jobs:\n  knos:\n    uses: drexthealpha/knos-workflows/.github/workflows/knos.yml@" + "b" * 40 + "\n"
OLD_CALLER = CALLER.replace("b" * 40, "a" * 40)


def fund_token() -> str:
    """The comment knos.flow `_relay_there` posts before the reply: the token GitHub signed, for a relayer to carry."""
    return ("knos-fund: eyJhbGciOiJSUzI1NiJ9.eyJhdWQiOiJrbm9zMzpmdW5kIn0.c2ln\nknos-terms: {\"auto\":true}\n\n"
            "<sub>knosrelay: GitHub signed this token for the one action it names. Anyone may carry it to Solana; Knos's public relay does.</sub>")


def pay_order_tx(sig: str, order: str, payee: int, amount: int, fee: int = 50_000, tip: int = 50_000, slot: int = 412_345_678,
                 at: int = T0 + DAY + 300, err=None) -> dict:
    """getTransaction's JSON (encoding json) of a knos_pay PayOrder, with the log lines order_pay.rs prints."""
    pid = str(pay2.PAY_ID)
    return {"slot": slot, "blockTime": at, "transaction": {"signatures": [sig], "message": {"accountKeys": ["R" * 44, order, "W" * 44, pid]}},
            "meta": {"err": err, "loadedAddresses": {"writable": [], "readonly": []}, "logMessages": [
                f"Program {pid} invoke [1]",
                f"Program log: knos3:paid order={order} pr=2 payee={payee} amount={amount} to={'W' * 44}",
                f"Program log: knos3:settled order={order} paid={amount} of={amount} fee={fee - tip} tip={tip} judge=9",
                f"Program {pid} success"]}}


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

    def __init__(self, folder: Path, replay_pays: bool = False, faucet_says_no: bool = False, exists: bool = False):
        super().__init__(tries=3, pause=0)
        self.folder, self.replay_pays, self.faucet_says_no = folder, replay_pays, faucet_says_no
        self.exists = exists                               # the repository is there already: an earlier run made it
        self.pull_open = False                             # the judge runs on a push to the pull request's branch
        self.moved: list[tuple] = []
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
        if isinstance(cmd, commands.Faucet):        # the faucet's own words (knos.faucet `_words`, `no`, `refuses`)
            if self.faucet_says_no:
                self._post(repo, issue, faucet.no("This account had test USDC from the faucet on 2026-09-01 10:00 UTC. One grant per 7 days: ask "
                                                  "again after 2026-09-08 10:00 UTC.").reply, "knos-bot")
            else:
                row = {"to": body.split()[-1], "units": faucet.AMOUNT, "state": "sent", "sig": FAUCET, "request": "r1", "forge": "github", "account": ME}
                self._post(repo, issue, faucet._words(row), "knos-bot")
        elif isinstance(cmd, commands.Fund):
            self.chain += funded("OrdW", T0 + DAY + 60, FUNDED, 5 * U, by=ME, issue=issue)
            self._post(repo, issue, fund_token(), BOT)          # the token comment comes first, as the same account
            self._post(repo, issue, funded_reply(issue), BOT)
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
            if self.exists:
                return 1, "GraphQL: Name already exists on this account (createRepository)"
            (Path(cwd) / W.NAME).mkdir()
            self.exists = True
            return 0, ""
        if a[:3] == ["gh", "repo", "clone"]:          # the repository an earlier run made (its callers at an earlier pin), or the template
            if a[3] == f"{LOGIN}/{W.NAME}" and self.exists:
                calls = Path(cwd) / a[4] / ".github" / "workflows"
                calls.mkdir(parents=True)
                (Path(cwd) / a[4] / ".git").mkdir()
                (calls / "knos.yml").write_text(OLD_CALLER, encoding="utf-8")
                (calls / "fund.yml").write_text(CALLER, encoding="utf-8")
                return 0, ""
            if a[3] == W.TEMPLATE:
                calls = Path(a[4]) / ".github" / "workflows"
                calls.mkdir(parents=True)
                for name in ("knos.yml", "fund.yml"):
                    (calls / name).write_text(CALLER, encoding="utf-8")
                return 0, ""
            return 1, f"GraphQL: Could not resolve to a Repository with the name '{a[3]}'."
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
            if path == "user" or (path == f"repos/{LOGIN}/{W.NAME}" and self.exists):
                return 0, json.dumps({"id": ME, "owner": {"id": ME}})
            if path == f"repos/{LOGIN}/{W.NAME}":
                return 1, "gh: Not Found (HTTP 404)"
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
            self.pull_open = True
            self._check(f"c{self.commits}")
            return 0, f"https://github.com/{LOGIN}/{W.NAME}/pull/2\n"
        if a[0] == "git":
            if a[1] == "commit":
                self.commits += 1
            if a[1] == "push" and "main" not in a and self.pull_open and f"c{self.commits}" not in self.runs:
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
        if a[:3] == ["knos", "statement", "settle-sync"]:     # the real command, given the payment's transaction as the chain holds it
            got = Path(a[3]).parent / "paid-tx.json"
            got.write_text(json.dumps({"jsonrpc": "2.0", "result": pay_order_tx(PAID, ORDER, ME, 5 * U)}), encoding="utf-8")
            a = [*a, "--tx", str(got)]
        if a[0] == "knos":           # events, statement, archive: the real command line
            got = subprocess.run([sys.executable, "-m", "knos", *a[1:]], cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=120)
            return got.returncode, got.stdout + got.stderr
        if a[0] == sys.executable:   # the archive's own verifier
            got = subprocess.run(a, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=120)
            return got.returncode, got.stdout + got.stderr
        return 1, f"not simulated: {a[:3]}"

    def ask(self, said):
        self.said.append(["ask", said])

    def top_up(self, source, payer, to, units):
        self.moved.append((Path(source).name, Path(payer).name, to, units))
        return TOPUP


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
    assert ["gh", "repo", "create", f"{LOGIN}/{W.NAME}", "--public", "--template", W.TEMPLATE, "--clone"] in world.said and "callers_updated" not in s
    assert (s["funded_tx"], s["paid_tx"], s["faucet_tx"], s["budget_tx"]) == (FUNDED, PAID, FAUCET, DEPOSIT)
    assert s["funded_order"] == ORDER and s["funded_reply"].endswith("#issuecomment-105")      # 104 is the token comment
    assert s["statements_agree"] is True and s["payments"] == 1
    # the statements carry the paid line, agreed (0.3.22's had none: the settle mode alone writes no invoice line)
    st = json.loads((tmp_path / "buyer" / W.STATEMENT).read_text(encoding="utf-8"))
    assert (s["statement_lines"], s["statement_state"]) == (1, "agreed") and len(st["lines"]) == 1
    assert (st["lines"][0]["state"], st["lines"][0]["amount"], st["lines"][0]["supplier"]) == ("agreed", "5.00", str(ME))
    assert s["buyer_statement"] == s["supplier_statement"] and len(s["buyer_statement"]) == 64
    # the line's four steps end settled: the paying transaction, read and checked, is beside the statement
    assert (s["settled_tx"], s["settled_slot"]) == (PAID, 412_345_678)
    done = json.loads((tmp_path / "buyer" / "ap-statement.status.json").read_text(encoding="utf-8"))["events"][-1]
    assert done["chain"] == {"signature": PAID, "slot": 412_345_678, "on": DAYS, "amount": "5.00", "fee": "0.05", "order": ORDER, "payee": str(ME), "to": "W" * 44}
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


def test_when_the_faucet_says_no_the_run_uses_the_own_key_named_or_stops_saying_so(tmp_path):
    world = World(tmp_path, faucet_says_no=True)
    _key({}, tmp_path)
    with pytest.raises(W.Stop, match=r"^the faucet said no \(This account had test USDC .* 7 days.*\): run again with --fund-from KEYFILE"):
        W.run(LOGIN, tmp_path, world, state={"day": DAYS})
    assert world.moved == []
    own = tmp_path / "own-key.json"
    own.write_text("[1]", encoding="utf-8")
    s = W.run(LOGIN, tmp_path, world, start="faucet", fund_from=own)
    assert world.moved[0] == ("own-key.json", "witness-key.json", s["address"], 10_000_000) and s["top_up_tx"] == TOPUP
    assert "faucet_tx" not in s and s["faucet_refused"].startswith("This account had test USDC")
    saved = (tmp_path / "witness-state.json").read_text(encoding="utf-8")
    assert "own-key" not in saved and "fund_from" not in saved                     # the key's file is never written down
    record = json.loads((tmp_path / W.NAME / "witness.json").read_text(encoding="utf-8"))
    assert record["top_up_tx"] == TOPUP and tasks.accepts("witness", record) == (True, "")


def test_a_second_run_uses_the_repository_made_before_with_the_templates_callers_and_a_branch_of_its_own(tmp_path):
    """0.3.23: `gh repo create` refuses a name that exists, so one account's second run stopped at its first step (and
    `--from key` left the actor, the owner and the clone unset), and the work's branch was always `witness-work`, the
    head of the earlier run's pull request."""
    world = World(tmp_path, exists=True)
    _key({}, tmp_path)
    s = W.run(LOGIN, tmp_path, world, state={"day": DAYS})
    assert s["done"] == [n for n, _f, _w in W.STEPS]
    assert not any(a[:3] == ["gh", "repo", "create"] for a in world.said)
    assert ["gh", "repo", "clone", f"{LOGIN}/{W.NAME}", W.NAME] in world.said
    calls = tmp_path / W.NAME / ".github" / "workflows"
    assert {f.name: f.read_text(encoding="utf-8") for f in calls.iterdir()} == {"knos.yml": CALLER, "fund.yml": CALLER}
    assert s["callers_updated"] == ["knos.yml"]                           # fund.yml was the template's already
    synced = world.said.index(["git", "commit", "-qm", f"Callers as the template {W.TEMPLATE} writes them"])
    assert world.said[synced + 1] == ["git", "push", "-q", "origin", "main"] and synced < world.said.index(["git", "add", ".knos"])
    assert ["git", "push", "-q", "-u", "origin", "witness-work-1"] in world.said
    assert not any("witness-work" in a for a in world.said)              # never the bare name an earlier run's pull request holds
    assert (s["actor_id"], s["repository_owner_id"], s["repository"]) == (ME, ME, f"https://github.com/{LOGIN}/{W.NAME}")
    record = json.loads((tmp_path / W.NAME / "witness.json").read_text(encoding="utf-8"))
    assert tasks.accepts("witness", record) == (True, "") and record["payments"] == 1
    # once the callers are the template's, the step commits nothing for them, and the clone in DIR is used as it is
    world.said.clear()
    again = W.repo({"dir": tmp_path, "repo": f"{LOGIN}/{W.NAME}", "login": LOGIN}, world)
    assert again["callers_updated"] == [] and not any(a[:2] == ["git", "commit"] for a in world.said)
    assert not any(a[:4] == ["gh", "repo", "clone", f"{LOGIN}/{W.NAME}"] for a in world.said)


def test_the_funding_reply_is_read_by_the_words_knos_writes():
    """The reply links the order's address, not a transaction: 0.3.21 and 0.3.22 read it as "nothing was funded"."""
    assert W.funding(funded_reply(7), 7) == ORDER
    assert W.funding(funded_reply(7).replace("as a work order", "as a private work order"), 7) == ORDER
    with pytest.raises(W.Stop, match="does not say the money is in escrow for #8"):
        W.funding(funded_reply(7), 8)
    for refused in ("Knos: nothing was funded. New funding is paused on Solana until 2026-10-09 08:25 UTC.",
                    "Knos: GitHub did not sign the request (timed out), so nothing was funded. Post the comment again.",
                    "Knos: not confirmed yet. GitHub signed the request (it is posted above) and no relayer carried it to Solana within 10 minutes."):
        with pytest.raises(W.Stop, match="^nothing was funded: Knos: "):
            W.funding(refused, 7)
    # the words are knos.flow's and knos.faucet's own: a change there fails here
    flow = (ROOT / "src" / "knos" / "flow.py").read_text(encoding="utf-8")
    assert "is in escrow for issue #{number} as a {'private ' if plan.get('attestor') else ''}work order ({order}), {took}." in flow
    assert 'order = _link(run, "order on Solana", "address",' in flow and 'return f"[{text}](https://explorer.solana.com/{kind}/{at}' in flow
    assert all(x in flow for x in ('"Knos: nothing was funded. ', "so nothing was funded.", '"Knos: not confirmed yet. '))
    assert W.FAUCET_NO.match(faucet.no("x").reply) and W.FAUCET_SENT.match(faucet._words({"to": "1" * 32, "units": 1, "state": "sent", "sig": "s"}))


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


def test_the_funding_reply_is_the_flows_and_never_the_token_comment_posted_before_it(tmp_path):
    """0.3.23's run read fund.yml's `knos-fund:` comment (posted first, by the same account) as the reply."""
    world = World(tmp_path)
    mine = world._post("me/r", 1, W.FUND_LINE)["id"]
    world._post("me/r", 1, fund_token(), BOT)
    got = W._reply(world, "me/r", 1, mine, W.FLOW_REPLY, other_than=LOGIN)
    assert got() is None                                    # the token alone: still waiting, never "nothing was funded"
    world._post("me/r", 1, funded_reply(1), BOT)
    said = got()
    assert said["body"] == funded_reply(1) and W.funding(said["body"], 1) == ORDER
    world2 = World(tmp_path)                                # a refusal after the token is read as the refusal
    mine = world2._post("me/r", 1, W.FUND_LINE)["id"]
    world2._post("me/r", 1, fund_token(), BOT)
    world2._post("me/r", 1, "Knos: nothing was funded. New funding is paused on Solana until 2026-10-09 08:25 UTC.", BOT)
    said = W._reply(world2, "me/r", 1, mine, W.FLOW_REPLY, other_than=LOGIN)()
    with pytest.raises(W.Stop, match="nothing was funded: Knos: nothing was funded. New funding is paused"):
        W.funding(said["body"], 1)
    assert not W.FLOW_REPLY.search(fund_token()) and W.FLOW_REPLY.search(commands.reply("malformed", "fund", why="no amount"))


def _one_line_statement() -> dict:
    ln = {"invoice_line": "inv_1", "state": "agreed", "amount": "5.00", "supplier": str(ME), "reference": f"tx:{PAID}", "deliverable": "dlv_1"}
    st = {"lines": [ln], "scale": 6, "source": "events", "date": DAYS, "sha256": "s" * 64}
    return st


def test_settle_sync_writes_the_paying_transaction_after_checking_amount_payee_and_order():
    st = _one_line_statement()
    ok = pay_order_tx(PAID, ORDER, ME, 5 * U)
    status, said = statement.settle_sync(st, None, {PAID: ok}.get, order=ORDER)
    assert said == [("inv_1", f"settled by {PAID} in slot 412345678: 5.00 to {ME}, fee 0.05")]
    steps, owed = statement.steps_of(st, st["lines"][0], status["events"])
    assert steps[3]["state"] == "done" and "slot 412345678" in steps[3]["said"] and not owed
    again, said = statement.settle_sync(st, status, {PAID: ok}.get, order=ORDER)    # twice changes nothing
    assert again == status and said == [("inv_1", "already settled")]
    for tx, why in ((pay_order_tx(PAID, ORDER, ME, 4 * U), "paid 4.00, and the line says 5.00"),
                    (pay_order_tx(PAID, ORDER, ME + 1, 5 * U), "someone other than the line's supplier"),
                    (pay_order_tx(PAID, "X" * 44, ME, 5 * U), f"paid no one from the order {ORDER}"),
                    (pay_order_tx(PAID, ORDER, ME, 5 * U, err={"InstructionError": [0, "Custom"]}), "failed on chain"),
                    (None, "did not give the transaction")):
        status, said = statement.settle_sync(st, None, {PAID: tx}.get, order=ORDER)
        assert status["events"] == [] and said[0][1].startswith("not settled") and why in said[0][1]


def test_settle_sync_finds_the_payment_among_the_orders_signatures_when_the_line_names_none():
    st = _one_line_statement()
    st["lines"][0]["reference"] = "issue 1"
    other = "Q" * 64
    txs = {other: pay_order_tx(other, "X" * 44, ME, 5 * U), PAID: pay_order_tx(PAID, ORDER, ME, 5 * U)}
    status, said = statement.settle_sync(st, None, txs.get, lambda order: [other, PAID], order=ORDER)
    assert status["events"][-1]["reference"] == PAID and said[0][1].startswith("settled by")
    _, said = statement.settle_sync(st, None, txs.get)
    assert said == [("inv_1", "not settled: its evidence names no transaction (give --order)")]
