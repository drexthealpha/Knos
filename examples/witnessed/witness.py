"""One transaction, start to end, witnessed by whoever runs it. Test USDC, no monetary value.

    python examples/witnessed/witness.py plan --login YOU           every step and what it leaves in public; sends nothing
    python examples/witnessed/witness.py run  --login YOU [--from STEP] [--dir DIR]
                                                                    the steps in order, as your GitHub account; stops at the
                                                                    first that fails and says why; --from goes on from a step
    python examples/witnessed/witness.py check witness.json         the record against the `witness` task's rules (no network)

Everything happens in a repository of YOUR account, made from the public template drexthealpha/knos-task, with your
own key: Knos opens nothing there. It needs `gh` logged in as you, `git`, and `pip install knos` (for `knos` and the
key). The steps:

    repo      your repository from the template (it holds the two public caller workflows and nothing secret)
    key       a Solana key made here, kept in DIR/witness-key.json: the address the faucet pays and the budget's owner
    sol       devnet SOL for that key's transaction fees (by hand: https://faucet.solana.com)
    faucet    20 test USDC from the playground's faucet issue, to that address
    budget    a balance for your account's repositories, filled with 10 of them (knos balance open, deposit)
    terms     an issue, its black-box acceptance checks committed (`knos.accept.bundle`: blackbox.py and cases.json),
              funded with `/knos fund 5 checks: none auto`: the terms are fixed then, and the checks alone pay
    fail      a pull request whose work is wrong; the judge job of the `knos review` run refuses it and says why
    pass      the corrected work on the same pull request; the judge passes, GitHub signs, the escrow pays, no merge
    replay    `/knos settle` again on the paid pull request: nothing more is paid
    buyer     the buyer's statement, from the chain alone (knos audit export, events, statement)
    supplier  the supplier's statement, made again from a second export: the same payable, the same hash
    archive   one archive of the evidence, checked by the stand-alone verifier inside it (python verify.py)
    record    witness.json committed to your repository: each step's public link

The record is what the playground's `witness` task asks for (tasks/outside/witness.json). Each step is a function of
(state, shell): tests/test_task_witnessed.py runs the whole sequence against a simulated GitHub and chain, and runs the
statement, archive and verifier steps for real.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Callable

TEMPLATE = "drexthealpha/knos-task"
PLAYGROUND = "drexthealpha/knos-playground"
NAME = "knos-witness"
FUND, BUDGET = "5", "10"
# The funding line as knos.commands reads it: `checks: none` names no CI check (the template has none to name; the
# acceptance checks are the test), and `auto` pays the first pull request those black-box checks pass, with no merge.
FUND_LINE = f"/knos fund {FUND} checks: none auto"
TASK, RUN = "words.py", ["python3", "words.py"]                     # what the judge runs in the pull request's tree
TX = re.compile(r"explorer\.solana\.com/tx/([1-9A-HJ-NP-Za-km-z]{64,90})")
WRONG = "import sys\nfor line in sys.stdin:\n    print(line.rstrip('\\n'))\n"                      # prints the line unchanged
RIGHT = "import sys\nfor line in sys.stdin:\n    print(' '.join(reversed(line.split())))\n"        # the words in reverse order
PAIRS = [("one two three", "three two one"), ("a b", "b a"), ("solo", "solo"), ("x  y   z", "z y x"), ("left right", "right left")]
STATEMENT = "ap-statement.json"


class Stop(Exception):
    """A step cannot go on. The message is the one sentence the person reads."""


class Shell:
    """How the steps reach the world: `run(argv, cwd)` -> (exit code, output); `wait` polls until `got()` is not None.
    Tests give another one."""

    def __init__(self, tries: int = 60, pause: float = 10.0):
        self.tries, self.pause = tries, pause

    def run(self, argv: list[str], cwd: Path | None = None, stdin: str | None = None) -> tuple[int, str]:
        got = subprocess.run(argv, cwd=cwd, input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=300)  # noqa: S603 - a fixed argv, no shell
        return got.returncode, (got.stdout or "") + (got.stderr or "")

    def wait(self, what: str, got: Callable[[], Any]) -> Any:
        for _ in range(self.tries):
            found = got()
            if found is not None:
                return found
            time.sleep(self.pause)
        raise Stop(f"waited {self.tries * self.pause:.0f} s for {what}; nothing came. Run again with --from at this step.")

    def ask(self, said: str) -> None:
        input(said + " Press Enter when it is done. ")


def _ok(shell: Shell, argv: list[str], cwd: Path | None = None, stdin: str | None = None) -> str:
    code, out = shell.run(argv, cwd, stdin)
    if code != 0:
        raise Stop(f"`{' '.join(argv[:4])} ...` failed: {' '.join(out.split())[:200] or 'it said nothing'}")
    return out


def _json(shell: Shell, path: str):
    return json.loads(_ok(shell, ["gh", "api", path]))


def _reply(shell: Shell, repo: str, issue: int, after: int, pattern: re.Pattern, other_than: str = "") -> Callable[[], dict | None]:
    """The first comment on `repo#issue` newer than comment id `after` that matches `pattern` (and, given `other_than`,
    was not written by that login: the answer to one's own comment, whatever it says)."""
    def got():
        for c in _json(shell, f"repos/{repo}/issues/{issue}/comments?per_page=100"):
            if other_than and str((c.get("user") or {}).get("login") or "").lower() == other_than.lower():
                continue
            if int(c.get("id") or 0) > after and pattern.search(str(c.get("body") or "")):
                return {"url": c.get("html_url"), "body": c.get("body"), "id": c.get("id")}
        return None
    return got


def _tx(text: str) -> str:
    """The transaction a reply links to."""
    found = TX.search(text)
    if not found:
        raise Stop("the reply names no transaction")
    return found.group(1)


def _comment(shell: Shell, repo: str, issue: int, body: str) -> int:
    """Post one comment; its id (the replies to wait for are newer)."""
    return int(json.loads(_ok(shell, ["gh", "api", f"repos/{repo}/issues/{issue}/comments", "-f", f"body={body}"]))["id"])


# ---- the steps ----------------------------------------------------------------------------------------------------------
def repo(s: dict, sh: Shell) -> dict:
    _ok(sh, ["gh", "repo", "create", s["repo"], "--public", "--template", TEMPLATE, "--clone"], s["dir"])
    return {"repository": f"https://github.com/{s['repo']}", "repository_owner_id": int(_json(sh, f"repos/{s['repo']}")["owner"]["id"]),
            "actor_id": int(_json(sh, "user")["id"])}


def key(s: dict, sh: Shell) -> dict:
    path = s["dir"] / "witness-key.json"
    if not path.exists():
        from solders.keypair import Keypair       # knos depends on solders
        path.write_text(json.dumps(list(bytes(Keypair()))), encoding="utf-8")
    from solders.keypair import Keypair
    return {"address": str(Keypair.from_bytes(bytes(json.loads(path.read_text(encoding="utf-8")))).pubkey()), "keypair": str(path)}


def sol(s: dict, sh: Shell) -> dict:
    sh.ask(f"Ask https://faucet.solana.com for 1 devnet SOL to {s['address']} (it pays this key's transaction fees).")
    return {}


def faucet(s: dict, sh: Shell) -> dict:
    found = _json(sh, f"repos/{PLAYGROUND}/issues?labels=faucet&state=open")
    if not found:
        raise Stop(f"{PLAYGROUND} has no open issue labelled faucet")
    n = int(found[0]["number"])
    mine = _comment(sh, PLAYGROUND, n, f"/knos faucet {s['address']}")
    said = sh.wait("the faucet's reply", _reply(sh, PLAYGROUND, n, mine, re.compile(re.escape(s["address"]) + r"[\s\S]*" + TX.pattern)))
    return {"faucet_reply": said["url"], "faucet_tx": _tx(said["body"])}


def budget(s: dict, sh: Shell) -> dict:
    _ok(sh, ["knos", "balance", "open", s["login"], "--keypair", s["keypair"]])
    out = _ok(sh, ["knos", "balance", "deposit", s["login"], BUDGET, "--keypair", s["keypair"]])
    found = TX.search(out)
    if not found:
        raise Stop("the deposit printed no transaction")
    return {"budget_tx": found.group(1)}


def terms(s: dict, sh: Shell) -> dict:
    body = "Print the words of each input line in reverse order. Witnessed transaction (examples/witnessed). Test USDC, no monetary value."
    made = json.loads(_ok(sh, ["gh", "api", f"repos/{s['repo']}/issues", "-f", "title=Reverse the words of a line", "-f", f"body={body}"]))
    n = int(made["number"])
    work = s["dir"] / NAME
    # Black-box checks, or `auto` is refused at funding: bare input and output files are not a judge. The bundle `knos
    # accept init` writes (blackbox.py runs the pull request's words.py through $KNOS_RUN and compares what it prints).
    from knos import accept         # knos is installed for this script (`pip install knos`)
    folder = work / ".knos" / "acceptance" / str(n)
    folder.mkdir(parents=True, exist_ok=True)
    for rel, data in accept.bundle(n, RUN, [{"input": given, "output": want} for given, want in PAIRS], "text", None).items():
        (folder / rel).write_bytes(data)
    for argv in (["git", "add", ".knos"], ["git", "commit", "-qm", f"Acceptance pairs for #{n}"], ["git", "push", "-q", "origin", "HEAD"]):
        _ok(sh, argv, work)
    mine = _comment(sh, s["repo"], n, FUND_LINE)
    said = sh.wait("the funding's reply", _reply(sh, s["repo"], n, mine, re.compile(r"\S"), other_than=s["login"]))
    if not TX.search(str(said["body"])):
        raise Stop(f"nothing was funded: {' '.join(str(said['body']).split())[:300]} ({said['url']})")
    return {"issue": n, "funded_reply": said["url"], "funded_tx": _tx(said["body"])}


def _checks(sh: Shell, s: dict) -> Callable[[], str | None]:
    """When every check run on the head has finished: when the last one did (the review starts after "knos check")."""
    def got():
        runs = _json(sh, f"repos/{s['repo']}/commits/{s['head']}/check-runs")["check_runs"]
        done = [r for r in runs if r.get("status") == "completed"]
        return None if not runs or len(done) < len(runs) else max(str(r.get("completed_at") or "") for r in done)
    return got


def _judged(sh: Shell, s: dict, after: str) -> Callable[[], tuple[str, str] | None]:
    """(conclusion, link) of the judge job that ran on this head. "knos check" on the pull request runs none of its code
    and passes wrong work too; the acceptance checks run in the judge job of the `knos review` run that its end starts
    (event workflow_run, so GitHub files that run under the default branch's commit, not the pull request's)."""
    def got():
        runs = _json(sh, f"repos/{s['repo']}/actions/runs?event=workflow_run&per_page=30")["workflow_runs"]
        for r in sorted(runs, key=lambda r: str(r.get("created_at") or "")):
            if str(r.get("created_at") or "") < after or r.get("status") != "completed":
                continue
            for job in _json(sh, f"repos/{s['repo']}/actions/runs/{r['id']}/jobs")["jobs"]:
                if str(job.get("name") or "").endswith("judge") and job.get("conclusion") in ("success", "failure"):
                    return str(job["conclusion"]), str(job.get("html_url") or r.get("html_url"))
        return None
    return got


def fail(s: dict, sh: Shell) -> dict:
    work = s["dir"] / NAME
    (work / TASK).write_text(WRONG, encoding="utf-8")
    for argv in (["git", "checkout", "-qb", "witness-work"], ["git", "add", "words.py"], ["git", "commit", "-qm", "Words, first try"],
                 ["git", "push", "-q", "-u", "origin", "witness-work"]):
        _ok(sh, argv, work)
    url = _ok(sh, ["gh", "pr", "create", "--repo", s["repo"], "--head", "witness-work", "--title", "Reverse the words",
                   "--body", f"Closes #{s['issue']}"], work).split()[-1]
    s["pull"], s["head"] = int(url.rstrip("/").rsplit("/", 1)[1]), _ok(sh, ["git", "rev-parse", "HEAD"], work).strip()
    got, link = sh.wait("the judge on the wrong work", _judged(sh, s, sh.wait("the checks on the wrong work", _checks(sh, s))))
    if got == "success":
        raise Stop(f"the judge passed work that is wrong: that is a finding, not a witnessed refusal. File it under the tamper task ({link}).")
    return {"pull_url": url, "failed_run": link}


def pass_(s: dict, sh: Shell) -> dict:
    work = s["dir"] / NAME
    mine = _comment(sh, s["repo"], s["pull"], f"/knos address {s['address']}")      # where the payment goes, said before it can be paid
    (work / TASK).write_text(RIGHT, encoding="utf-8")
    for argv in (["git", "add", "words.py"], ["git", "commit", "-qm", "Words, corrected"], ["git", "push", "-q"]):
        _ok(sh, argv, work)
    s["head"] = _ok(sh, ["git", "rev-parse", "HEAD"], work).strip()
    got, link = sh.wait("the judge on the corrected work", _judged(sh, s, sh.wait("the checks on the corrected work", _checks(sh, s))))
    if got != "success":
        raise Stop(f"the judge refused the corrected work: read {link}, fix words.py, and run again with --from pass")
    said = sh.wait("the payment", _reply(sh, s["repo"], s["pull"], mine, re.compile(r"paid[\s\S]*" + TX.pattern, re.I)))
    return {"passed_head": s["head"], "passed_run": link, "paid_reply": said["url"], "paid_tx": _tx(said["body"])}


def replay(s: dict, sh: Shell) -> dict:
    mine = _comment(sh, s["repo"], s["pull"], "/knos settle")
    said = sh.wait("the answer to the replay", _reply(sh, s["repo"], s["pull"], mine, re.compile(r"\S")))
    if TX.search(said["body"]) and _tx(said["body"]) != s["paid_tx"]:
        raise Stop(f"the replay was answered with a transaction other than the payment: {said['url']}")
    return {"replay_refused": said["url"]}


def _statement(s: dict, sh: Shell, side: str) -> str:
    folder = s["dir"] / side
    folder.mkdir(exist_ok=True)
    day = s.get("day") or time.strftime("%Y-%m-%d", time.gmtime())
    s["day"] = day
    _ok(sh, ["knos", "audit", "export", "--owner", s["login"], "--from", day, "--to", day, "--format", "csv", "--out", str(folder / "audit.csv")])
    log = folder / "events.jsonl"
    _ok(sh, ["knos", "events", "ingest", str(log), str(folder / "audit.csv"), "--from", "settle"])
    _ok(sh, ["knos", "statement", "make", str(log), "--out", str(folder), "--buyer", s["login"], "--supplier", s["login"], "--currency", "test USDC",
             "--date", day, "--invoice", f"witness-{s['issue']}"])
    st = json.loads((folder / STATEMENT).read_text(encoding="utf-8"))
    return str(st["sha256"])


def buyer(s: dict, sh: Shell) -> dict:
    return {"buyer_statement": _statement(s, sh, "buyer")}


def supplier(s: dict, sh: Shell) -> dict:
    mine = _statement(s, sh, "supplier")
    if mine != s["buyer_statement"]:
        raise Stop(f"the two statements differ ({s['buyer_statement'][:12]} and {mine[:12]}): `knos archive compare` names the line")
    return {"supplier_statement": mine, "statements_agree": True}


def archive(s: dict, sh: Shell) -> dict:
    out = s["dir"] / "witness.zip"
    _ok(sh, ["knos", "archive", "make", str(out), "--events", str(s["dir"] / "buyer" / "events.jsonl"),
             "--statement", str(s["dir"] / "buyer" / STATEMENT), "--sealed", s["day"]])
    unpacked = s["dir"] / "witness-archive"
    with zipfile.ZipFile(out) as z:
        z.extractall(unpacked)
    said = _ok(sh, [sys.executable, "-I", "verify.py"], unpacked)
    return {"archive": out.name, "verified": " ".join(said.split())[:300] or "passed"}


def payments(s: dict) -> int:
    """Paid lines in the buyer's export for this order: one, or the replay paid twice."""
    lines = (s["dir"] / "buyer" / "audit.csv").read_text(encoding="utf-8").splitlines()
    rows = csv.DictReader(lines[1:] if lines and lines[0].startswith("knos.audit-export,") else lines)     # (the line naming the version)
    return len({r.get("transaction") for r in rows if r.get("kind") == "paid" and str(r.get("issue")) == str(s["issue"])})


def record(s: dict, sh: Shell) -> dict:
    keep = ("actor_id", "repository", "repository_owner_id", "address", "faucet_reply", "faucet_tx", "budget_tx", "issue", "funded_reply", "funded_tx",
            "pull_url", "failed_run", "passed_head", "passed_run", "paid_reply", "paid_tx", "replay_refused", "buyer_statement", "supplier_statement", "statements_agree",
            "archive", "verified")
    doc = {"v": 1, "note": "Test USDC, no monetary value.", **{k: s[k] for k in keep if k in s}, "payments": payments(s)}
    work = s["dir"] / NAME
    (work / "witness.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for argv in (["git", "checkout", "-q", "main"], ["git", "pull", "-q"], ["git", "add", "witness.json"], ["git", "commit", "-qm", "The witnessed transaction"],
                 ["git", "push", "-q", "origin", "main"]):
        _ok(sh, argv, work)
    return {"record": f"https://github.com/{s['repo']}/blob/main/witness.json", "payments": doc["payments"]}


STEPS: list[tuple[str, Callable[[dict, Shell], dict], str]] = [
    ("repo", repo, "your repository, made from the public template"), ("key", key, "a key made here; its address is public from the next step"),
    ("sol", sol, "devnet SOL for fees, by hand"), ("faucet", faucet, "the faucet's reply on the playground, with its transaction"),
    ("budget", budget, "the deposit's transaction"), ("terms", terms, "the issue, its acceptance pairs, and the funding's reply with its transaction"),
    ("fail", fail, "the pull request and the judge job that refused it"), ("pass", pass_, "the passing judge job and the payment's reply with its transaction"),
    ("replay", replay, "the answer to a second /knos settle: no new payment"), ("buyer", buyer, "the buyer's statement and its hash"),
    ("supplier", supplier, "the supplier's statement: the same hash"), ("archive", archive, "the archive and what its own verifier said"),
    ("record", record, "witness.json in your repository"),
]


def run(login: str, folder: Path, shell: Shell, start: str = "repo", state: dict | None = None) -> dict:
    """Every step from `start` on, in order; the state is kept in DIR/witness-state.json after each, so --from goes on."""
    names = [n for n, _f, _w in STEPS]
    if start not in names:
        raise Stop(f"--from is one of: {', '.join(names)}")
    saved = folder / "witness-state.json"
    s = state if state is not None else (json.loads(saved.read_text(encoding="utf-8")) if saved.exists() else {})
    s.update(login=login, repo=f"{login}/{NAME}")
    for name, step, _what in STEPS[names.index(start):]:
        s["dir"] = folder
        s.update(step(s, shell))
        s.setdefault("done", [])
        s["done"] = [d for d in s["done"] if d != name] + [name]
        saved.write_text(json.dumps({k: v for k, v in s.items() if k != "dir"}, indent=1), encoding="utf-8")
    return s


def check(doc: dict) -> tuple[bool, str]:
    """The record against the `witness` task's rules (knos.tasks.accepts), when knos is installed."""
    from knos import tasks
    return tasks.accepts("witness", doc)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="One transaction, start to end, in a repository of your own. Test USDC, no monetary value.")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        one = sub.add_parser(name)
        one.add_argument("--login", required=True)
        one.add_argument("--dir", type=Path, default=Path("witness"))
        one.add_argument("--from", dest="start", default="repo")
    sub.add_parser("check").add_argument("record", type=Path)
    a = p.parse_args(argv)
    try:
        if a.cmd == "plan":
            print("Test USDC, no monetary value. Nothing is sent by `plan`.")
            for n, (name, _f, what) in enumerate(STEPS, 1):
                print(f"{n:>2}. {name:<9} leaves: {what}")
            return 0
        if a.cmd == "check":
            ok, why = check(json.loads(a.record.read_text(encoding="utf-8")))
            print("the record meets the witness task" if ok else f"not yet: {why}")
            return 0 if ok else 1
        a.dir.mkdir(parents=True, exist_ok=True)
        s = run(a.login, a.dir.resolve(), Shell(), a.start)
        print(f"Done. The record: {s['record']}. File it as outside/witness/{a.login}.json in a pull request to {PLAYGROUND}.")
        return 0
    except Stop as no:
        print(f"witness: {no}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
