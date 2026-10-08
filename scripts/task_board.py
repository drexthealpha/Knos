"""The task board: a fixed number of funded test tasks kept open in drexthealpha/knos-playground for whoever arrives.

    python scripts/task_board.py plan                  what `open` would do, and why it stops where it stops
    python scripts/task_board.py open [--apply] [--kinds]   do it; without --apply nothing leaves this machine; --kinds: the
                                                       five tasks that are not code as well (below)
    python scripts/task_board.py status [--json]       the board, and the pull requests whose runs wait for approval
    python scripts/task_board.py status --json --empty the same document with nothing read: what a build with no network writes
    python scripts/task_board.py why OWNER/REPO#N [--pull M]   one sentence: why a merged pull request was not paid, and what fixes it

The tasks are tasks/<slug>/ in this repository (tasks/README.md has the schema). Every one pays test USDC on Solana
devnet, which has no monetary value, and says so in its first line.

What `open` does for one task, in this order, and what makes a second run do nothing twice:

    1. opens the issue (title, statement, labels). Its text ends with a marker that names the task; a task whose marker
       is on an open issue is never opened again.
    2. commits the task's acceptance bundle to `.knos/acceptance/<issue number>/` and the issue's line to `board.json`,
       in ONE commit (git's own tree, commit and ref calls). An issue that `board.json` lists has its bundle.
    3. comments `/knos fund <amount> days <N>`: the repository's workflow reads the line and funds the work order with
       the bundle of step 2 as its terms. An issue with such a comment of the owner's is never funded again.

    A run that stopped between two steps is taken up at the step that is missing.

What bounds it, all printed by `plan`:

    target    N tasks open at once (default 8)
    budget    at most BUDGET test USDC opened in one UTC day (amount and fee), counted from the issues' own markers
    reserve   with `--balance <address>`: the Balance the owner's comment spends keeps at least RESERVE test USDC after
              everything this run would fund, or the run funds fewer and says so. Without it the board reads no
              Balance and funds only what the devnet faucet mints (`--faucet`), one a minute, which is the program's
              own limit (FUND_PERIOD): it never spends an amount it did not read.

ONLY THROUGH THE PUBLIC PINNED WORKFLOWS. An order names, when it is funded, the commit of the workflows whose signed
run may pay it. `open` reads the playground's own workflow files first (`unpinned`) and funds nothing unless every
reusable workflow they call is drexthealpha/knos-workflows at the commit this checkout's examples name: an order funded
through a staging copy is one the public worker cannot pay (that is why one merged pull request was not paid in
0.3.19). `plan` and `status` say the same check's result; `why` reads one order back from the chain (knos.tasks.why).

THE FIVE TASKS THAT ARE NOT CODE (`--kinds`; tasks/outside/<kind>.json, knos.tasks.KINDS). Each opens as a board issue
`outside-<kind>` that pays 5 test USDC on a maintainer's MERGE of the pull request filing its evidence, one file
outside/<kind>/<login>.json; the maintainer checks it with knos.tasks.accepts first. No acceptance bundle is theirs: the
starter task's checks under the issue's number are removed in the same commit as its line in board.json, so the funding
is merge mode. They are opened before the code tasks, count in the same day's budget, and not in the target.

A STRANDED TASK IS OPENED AGAIN. `plan` and `open` read each open funded issue's order from the chain (knos.tasks.why):
one funded through a commit of the workflows the playground no longer calls (every release rebuilds it at the next
commit), past its deadline, or no longer open can pay no merge. `plan` names it; `open --apply` closes it with that
sentence (its money goes back at its deadline) and the board opens the task again in a new issue, in the day's budget.

A HELD PAYMENT IS A STATE OF THE BOARD. `status` lists, under `held`, each merged pull request on a board task whose
payment waits for its author to say where it goes, with the one instruction for the payee: comment
`/knos address <your Solana address>` on the pull request.

`status` reads and prints. It lists each pull request whose workflow runs wait for a maintainer's approval (GitHub
holds the runs of a first-time contributor: https://docs.github.com/en/actions/how-tos/manage-workflow-runs/approve-runs-from-forks)
with the files its diff touches and what the judge's rule says of each path. It approves nothing: approving runs a
stranger's code, and that decision is a person's.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks"
FIRST = "Test USDC, no monetary value."
LABELS = ("knos-funded", "good first issue", "help wanted")
LABEL_WORDS = {"knos-funded": ("1a7f37", "Test USDC is held for this task on Solana devnet. It has no monetary value."),
               "good first issue": ("7057ff", "Good for newcomers"), "help wanted": ("008672", "Extra attention is needed")}
TARGET = 8                          # tasks open at once
BUDGET = 45_000_000                 # millionths of test USDC opened in one UTC day, fees included: a whole board of 8 at 5.05
RESERVE = 50_000_000                # millionths of test USDC a named Balance keeps
PACE = 65                           # seconds between two fundings: the faucet serves a repository once a minute (FUND_PERIOD = 60)
LEAST, MOST = 2_000_000, 5_000_000  # what the schema lets one task pay. The escrow holds a work order from 5 (ORDER_MIN_AMOUNT), so
                                    # every task written so far pays 5, and `plan` passes over one that asks for less and says so
BOARD = "board.json"                # in the playground: {"v": 1, "tasks": {"<issue number>": "<slug>"}}
MARK = re.compile(r"<!-- knos-task: ([a-z0-9-]+) amount=(\d+) days=(\d+) -->")
CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)\b", re.I)
KEYS = ("v", "slug", "title", "statement", "file", "run", "amount", "deadline_days", "labels", "public", "seed", "starting_files", "reference",
        "hidden", "wrong")
Forge = Callable[..., Any]
USES = re.compile(r"(?m)^\s*(?:-\s*)?uses:\s*['\"]?([\w.-]+/[\w.-]+)/\.github/workflows/([\w.-]+)@([^\s'\"#]+)")
CALLERS = (".github/workflows/knos.yml", ".github/workflows/knos-check.yml")      # the playground's two callers (scripts/small_repos.py)
HELD_SAYS = re.compile(r"^Knos: held for @([A-Za-z0-9-]{1,39})\.")                  # knos.ghwords: the reply to a merge that could pay nobody yet
INSTRUCTION = "comment `/knos address <your Solana address>` on the pull request"
KIND = "outside-"                   # the board's slug of a task that is not code: outside-<kind> (knos.tasks.KINDS)
KIND_DAYS = 30                      # days a task that is not code stays funded: each asks for a repository and a run of the taker's own


class Stop(Exception):
    """The board cannot go on. The message says why, in a sentence."""


def _src():
    """knos.playground, knos.accept, knos.judge and knos.settle.v2.pay from this checkout."""
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from knos import accept, judge, playground
        from knos.settle.v2 import pay
    finally:
        sys.path.remove(str(ROOT / "src"))
    return playground, accept, judge, pay


def _tasks():
    """knos.tasks from this checkout (standard library only): the words a task row carries, and `why`."""
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from knos import tasks
    finally:
        sys.path.remove(str(ROOT / "src"))
    return tasks


def _playground():
    """knos.playground alone, from this checkout: what every command needs. `status --empty` runs in the site's build,
    where solders (knos.settle.v2.pay) is not installed, so nothing else is imported before a command needs it."""
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from knos import playground
    finally:
        sys.path.remove(str(ROOT / "src"))
    return playground


# ---- the tasks ----------------------------------------------------------------------------------------------------------------
def load(slug: str) -> dict:
    """tasks/<slug>/task.json, checked against the schema. Raises Stop with the first thing that is wrong."""
    folder = TASKS / slug
    try:
        t = json.loads((folder / "task.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as why:
        raise Stop(f"tasks/{slug}/task.json cannot be read: {why}") from None
    said = [k for k in KEYS if k not in t]
    if said:
        raise Stop(f"tasks/{slug}/task.json lacks {', '.join(said)}")
    if t["slug"] != slug or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
        raise Stop(f"tasks/{slug}/task.json names the task {t['slug']!r}: the folder's name is the task's")
    if not str(t["statement"]).startswith(FIRST + "\n"):
        raise Stop(f"tasks/{slug}: the statement's first line is not {FIRST!r}")
    if not isinstance(t["amount"], int) or not LEAST <= t["amount"] <= MOST:
        raise Stop(f"tasks/{slug}: the amount is from 2 to 5 test USDC; {t['amount']!r} millionths is not")
    if not isinstance(t["deadline_days"], int) or not 1 <= t["deadline_days"] <= 90:
        raise Stop(f"tasks/{slug}: deadline_days is from 1 to 90")
    if tuple(t["labels"]) != LABELS:
        raise Stop(f"tasks/{slug}: the labels are {', '.join(LABELS)}")
    if not t["public"] or len(t["wrong"]) < 3 or list(t["starting_files"]) != [t["file"]] or t["run"] != ["python3", t["file"]]:
        raise Stop(f"tasks/{slug}: a task has public examples, three wrong solutions, and one starting file that its command runs")
    for rel in (t["reference"], t["hidden"], *t["wrong"], *t["starting_files"].values()):
        if not (folder / rel).is_file():
            raise Stop(f"tasks/{slug}/{rel} is not there")
    return t


def catalogue() -> list[dict]:
    """Every task, in the order the board opens them (by seed, which is the order they were written in)."""
    return sorted((load(p.parent.name) for p in TASKS.glob("*/task.json")), key=lambda t: (t["seed"], t["slug"]))


def kinds() -> list[dict]:
    """The five tasks that are not code puzzles (knos.tasks.KINDS: tasks/outside/<kind>.json holds the same text), each
    as a board task `outside-<kind>`: no acceptance bundle, paid on the merge of the pull request that files its evidence
    under outside/<kind>/. Raises Stop when one breaks a rule every task of the board keeps."""
    out = []
    for kind, spec in _tasks().KINDS.items():
        if not str(spec["statement"]).startswith(FIRST + "\n") or not LEAST <= spec["amount"] <= MOST or spec["currency"] != "test USDC":
            raise Stop(f"tasks/outside/{kind}.json: the statement's first line is {FIRST!r} and it pays 2 to 5 test USDC")
        out.append({"slug": KIND + kind, "kind": kind, "title": spec["title"], "statement": spec["statement"], "amount": spec["amount"],
                    "deadline_days": KIND_DAYS, "labels": list(LABELS), "file": f"outside/{kind}/", "evidence": spec["evidence"],
                    "needs": list(spec["needs"]), "doc": spec["doc"]})
    return out


def is_kind(task: dict) -> bool:
    return str(task.get("slug", "")).startswith(KIND)


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Stop(f"{path} is not a module")
    mod = importlib.util.module_from_spec(spec)
    kept, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = kept
    return mod


def cases(task: dict) -> list[dict]:
    """The recorded cases: the public examples, then the hidden generator's inputs at the task's seed, each with the
    reference's answer. The same every time."""
    _p, accept, _j, _pay = _src()
    folder = TASKS / task["slug"]
    solve = _module(folder / task["reference"], f"knos_task_ref_{task['seed']}").solve
    made = _module(folder / task["hidden"], f"knos_task_gen_{task['seed']}").inputs(random.Random(task["seed"]))
    seen: dict[str, None] = {}
    for line in [c["input"] for c in task["public"]] + list(made):
        seen.setdefault(line)
    return [{"input": line, "output": accept.norm(solve(line + "\n"))} for line in seen]


_JUDGE = '''"""Black-box acceptance for issue {issue}: the task "{slug}" of the Knos playground. Read README.md.

This file runs as the judge, outside the pull request's tree, and never loads the pull request's code. It runs
"$KNOS_RUN <command>" (which runs the command in the pull request's tree, inside the sandbox) on every recorded input
of cases.json, then on inputs gen.py makes from a seed drawn when this runs, and compares what the command prints with
what reference.py answers. Exit 0 means every case agrees."""
import importlib.util
import json
import os
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
SECONDS = 60
sys.dont_write_bytecode = True


def part(name):
    spec = importlib.util.spec_from_file_location("knos_" + name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def norm(text):
    return "\\n".join(line.rstrip() for line in text.replace("\\r\\n", "\\n").strip("\\n").split("\\n"))


def ask(argv, stdin):
    got = subprocess.run([os.environ["KNOS_RUN"], *argv], input=stdin, capture_output=True, timeout=SECONDS)
    return got.returncode, got.stdout, got.stderr


def fresh(seed):
    """Cases nobody has seen: the generator's inputs at this seed, answered by the reference now."""
    solve, known = part("reference").solve, {{c["input"] for c in SPEC["cases"]}}
    return [{{"input": line, "output": norm(solve(line + "\\n"))}} for line in dict.fromkeys(part("gen").inputs(random.Random(seed))) if line not in known]


def check(ask=ask, seed=None):
    """None when every case agrees, else one sentence about the first that does not. `seed` None: the recorded cases only."""
    for n, case in enumerate(SPEC["cases"] + (fresh(seed) if seed is not None else []), 1):
        at = "case %d, the input %s" % (n, repr(case["input"][:60]))
        try:
            code, out, err = ask(SPEC["run"], (case["input"] + "\\n").encode("utf-8"))
        except subprocess.TimeoutExpired:
            return "%s: the command took more than %d seconds" % (at, SECONDS)
        if code != 0:
            return "%s: the command exited %d: %s" % (at, code, " ".join(err.decode("utf-8", "replace").split())[-200:] or "it said nothing")
        got = norm(out.decode("utf-8", "replace"))
        if got != case["output"]:
            return "%s: it printed %s, expected %s" % (at, repr(got[:80]), repr(case["output"][:80]))
    return None


if __name__ == "__main__":
    seed = int.from_bytes(os.urandom(8), "big")
    why = check(seed=seed)
    if why:
        sys.exit("%s (fresh inputs: seed %d)" % (why, seed))
    print("every recorded case and every fresh one (seed %d) agrees" % seed)
'''

_README = """# Acceptance checks for issue {issue}: {title}

{first} Written by `scripts/task_board.py` of drexthealpha/Knos from `tasks/{slug}/` there.

`blackbox.py` is the judge. It runs `{run}` in the pull request's tree with one input on standard input, for each of
the {n} recorded inputs of `cases.json` and then for inputs `gen.py` makes from a seed drawn at that moment, and
compares what the command prints with what `reference.py` answers (trailing spaces and blank lines at the end are
ignored). Exit 0 means every case agrees. A failure names the seed, so the same inputs can be made again.

It is black-box: the pull request's code runs as a separate process and the judge never loads it. A pull request that
changes anything under `.knos/` is refused before any of this runs.

What it does not do: `reference.py` is here, in a public repository, so a pull request can copy it. That is accepted for
test money. The fresh inputs stop an answer table, not a copy.
"""


def bundle(task: dict, issue: int) -> dict[str, bytes]:
    """`.knos/acceptance/<issue>/` for this task: {name: content}, the same bytes every time. Black-box by knos.judge, or Stop."""
    _p, _accept, judge, _pay = _src()
    folder, recorded = TASKS / task["slug"], cases(task)
    spec = {"v": 1, "issue": issue, "task": task["slug"], "run": task["run"], "seed": task["seed"], "cases": recorded}
    files = {"blackbox.py": _JUDGE.format(issue=issue, slug=task["slug"]).encode("utf-8"),
             "cases.json": (json.dumps(spec, indent=1, ensure_ascii=False) + "\n").encode("utf-8"),
             "gen.py": (folder / task["hidden"]).read_bytes(), "reference.py": (folder / task["reference"]).read_bytes(),
             "README.md": _README.format(issue=issue, title=task["title"], first=FIRST, slug=task["slug"], run=" ".join(task["run"]), n=len(recorded)).encode("utf-8")}
    why = judge.black_box(files)
    if why:
        raise Stop(f"the bundle of {task['slug']} is not black-box (its checks {why})")
    return files


def fund_line(task: dict) -> str:
    """The comment that funds it: the amount, and the days until what was not paid goes back."""
    return f"/knos fund {task['amount'] // 1_000_000} days {task['deadline_days']}"


def cost(task: dict) -> int:
    """What funding it takes: the amount and the fee the funder pays on top (knos_pay: 30 basis points, at least 0.05)."""
    _p, _a, _j, pay = _src()
    return task["amount"] + pay.order_fee(task["amount"])


def issue_body(task: dict, repo: str) -> str:
    """What a stranger reads on the task: the money's worth first, the statement, the examples, and the two-minute path."""
    file, own = task["file"], f"tasks/{Path(task['file']).stem}.examples.json"
    rows = "\n".join(f"| `{c['input']}` | `{c['output'].replace(chr(10), ' / ')}` |" for c in task["public"])
    return (f"{task['statement']}\n\n| Input | Output |\n|---|---|\n{rows}\n\n"
            f"**Pays {task['amount'] // 1_000_000} test USDC** on Solana devnet when a pull request that passes the check is merged, "
            f"within {task['deadline_days']} days of the funding comment below.\n\n"
            "### Take it (two minutes)\n\n"
            f"1. [Edit `{file}`](https://github.com/{repo}/edit/main/{file}) in the browser: GitHub forks the repository for you. Write `solve`.\n"
            f"2. Open the pull request with `Closes #<this issue's number>` in its description.\n"
            f"3. The check runs your file as a separate process on the examples in [`{own}`](https://github.com/{repo}/blob/main/{own}) and on inputs you have not "
            f"seen. Try it first: `python3 check.py {task['slug']}`.\n"
            "4. A maintainer merges a pull request that passes, and the merge pays your GitHub account. Bind where it goes with one "
            "comment, `/knos address <your Solana address>`, or with the passkey wallet on the Knos site. Until you do, the payment is held for your account.\n\n"
            "A first pull request from an account new to GitHub waits until a maintainer lets its check run. Change only the one file: "
            "a pull request that touches `.knos/` or `.github/` is refused.\n\n"
            f"<!-- knos-task: {task['slug']} amount={task['amount']} days={task['deadline_days']} -->\n")


def kind_body(task: dict, repo: str) -> str:
    """The issue of a task that is not code: the money's worth first, what to do, the evidence and the one file it goes in."""
    doc = task["doc"]
    link = f"https://github.com/drexthealpha/Knos/{'blob' if '.' in Path(doc).name else 'tree'}/main/{doc}"
    fields = ", ".join(f"`{n}`" for n in task["needs"])
    return (f"{task['statement']}\n\nHow: [{doc}]({link}).\n\n"
            f"**The evidence a machine checks:** {task['evidence']}. As JSON, with the fields {fields}.\n\n"
            f"**Pays {task['amount'] // 1_000_000} test USDC** on Solana devnet when the pull request that files the evidence is merged, "
            f"within {task['deadline_days']} days of the funding comment below.\n\n"
            "### Take it\n\n"
            "1. Do the task, in a repository of your own account.\n"
            f"2. [Add one file](https://github.com/{repo}/new/main?filename={task['file']}YOUR-LOGIN.json), `{task['file']}<your login>.json`, "
            "holding the evidence. Change nothing else: a pull request that touches `.knos/` or `.github/` is refused.\n"
            "3. Open the pull request with `Closes #<this issue's number>` in its description.\n"
            "4. A maintainer checks the evidence (`knos.tasks.accepts`) and merges; the merge pays your GitHub account. Bind where it goes with one "
            "comment, `/knos address <your Solana address>`, or with the passkey wallet on the Knos site. Until you do, the payment is held for your account.\n\n"
            "It counts among the outside numbers only when your account is not one of Knos's own, and is shown as \"on tasks Knos funded itself\".\n\n"
            f"<!-- knos-task: {task['slug']} amount={task['amount']} days={task['deadline_days']} -->\n")


# ---- the forge ----------------------------------------------------------------------------------------------------------------
def _token() -> str:
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]
    try:
        got = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, encoding="utf-8", timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return got.stdout.strip() if got.returncode == 0 else ""


def github(method: str, path: str, body: dict | None = None):
    """GitHub's REST API: the answer as JSON. A read of a public repository needs no token; a write needs one."""
    token = _token()
    if method != "GET" and not token:
        raise Stop("no GitHub token (GH_TOKEN, GITHUB_TOKEN or `gh auth login`): nothing can be written")
    head = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "knos-task-board"}
    if token:
        head["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"https://api.github.com/{path}", data=json.dumps(body).encode("utf-8") if body is not None else None, headers=head, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as got:  # noqa: S310 - one fixed https host
            text = got.read().decode("utf-8")
    except urllib.error.HTTPError as why:
        if why.code == 404 and method == "GET":
            return None
        raise Stop(f"GitHub answered {why.code} to {method} {path}") from None
    except OSError as why:
        raise Stop(f"GitHub did not answer {method} {path}: {why}") from None
    return json.loads(text) if text.strip() else {}


def _pages(gh: Forge, path: str, most: int = 10) -> list[dict]:
    out: list[dict] = []
    for page in range(1, most + 1):
        got = gh("GET", f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
        rows = got.get("workflow_runs") if isinstance(got, dict) else got
        if not isinstance(rows, list):
            raise Stop(f"GitHub gave no list for {path}")
        out += [r for r in rows if isinstance(r, dict)]
        if len(rows) < 100:
            break
    return out


def rpc(method: str, params: list):
    """One call to Solana devnet's JSON RPC (KNOS_RPC_URL, else the public devnet endpoint)."""
    url = os.environ.get("KNOS_RPC_URL") or "https://api.devnet.solana.com"
    req = urllib.request.Request(url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as got:  # noqa: S310 - the operator's own RPC endpoint
            return json.loads(got.read().decode("utf-8")).get("result")
    except (OSError, ValueError) as why:
        raise Stop(f"devnet did not answer {method}: {why}") from None


def held(balance: str, ask: Callable = rpc) -> int:
    """Millionths of test USDC the Balance at this address holds: its own token account, read from the chain. Stop when
    the chain does not say: an amount that was not read is never spent."""
    _p, _a, _j, pay = _src()
    from solders.pubkey import Pubkey
    try:
        token = pay.baltok_pda(Pubkey.from_string(balance))
    except ValueError:
        raise Stop(f"{balance!r} is not an address") from None
    got = ask("getTokenAccountBalance", [str(token)])
    try:
        return int(got["value"]["amount"])
    except (TypeError, KeyError, ValueError):
        raise Stop(f"devnet did not say what the Balance {balance} holds (its token account {token}): nothing is funded from it") from None


def _pinned():
    """scripts/pinned_workflows.py: the public workflow repository and the commit this checkout's examples name."""
    spec = importlib.util.spec_from_file_location("pinned_workflows", Path(__file__).with_name("pinned_workflows.py"))
    if spec is None or spec.loader is None:
        raise Stop("scripts/pinned_workflows.py is not there")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = ROOT
    return mod


def unpinned(gh: Forge, repo: str, pin: str | None = None, public: str | None = None) -> list[str]:
    """Why funding in `repo` now would make an order the public worker cannot pay, one line each; [] when every reusable
    workflow its two callers call is the public repository's at the published commit. Reads two files; writes nothing."""
    pub = _pinned() if pin is None or public is None else None
    pin, public = pin or pub.pin(), public or pub.REPO
    said = []
    if not re.fullmatch(r"[0-9a-f]{40}", pin):
        return [f"this checkout's examples name no published commit ({pin}): stamp it first (python scripts/pinned_workflows.py stamp <sha>)"]
    for rel in CALLERS:
        got = gh("GET", f"repos/{repo}/contents/{rel}")
        try:
            text = base64.b64decode(got["content"]).decode("utf-8") if got else None
        except (KeyError, TypeError, ValueError):
            text = None
        if text is None:
            said.append(f"{rel} could not be read in {repo}")
            continue
        calls = USES.findall(text)
        if rel == CALLERS[0] and not calls:
            said.append(f"{rel} in {repo} calls no pinned workflow")
        for where, workflow, ref in calls:
            if where.lower() != public.lower():
                said.append(f"{rel} calls {workflow} of {where}, which is not the public {public}")
            elif ref != pin:
                said.append(f"{rel} calls {workflow} at {ref[:12]}, and the published commit is {pin[:12]}: rebuild the playground first "
                            "(python scripts/small_repos.py build knos-playground DIR)")
    return said


def held_rows(gh: Forge, repo: str, pulls: list[dict]) -> list[dict]:
    """Merged pull requests whose payment is held for the author: the workflow's own reply on the pull request says so,
    and no later reply of Knos says it was paid. Each with the one thing its payee does."""
    out = []
    for p in pulls:
        if not p.get("merged_at"):
            continue
        said = gh("GET", f"repos/{repo}/issues/{int(p['number'])}/comments?per_page=100")
        state, who = "", ""
        for c in said if isinstance(said, list) else []:
            body = str((c or {}).get("body") or "")
            if (c.get("user") or {}).get("type") != "Bot":
                continue
            m = HELD_SAYS.match(body)
            if m:
                state, who = "held", m.group(1)
            elif re.match(r"^Knos: paid\b", body, re.I):
                state = "paid"
        if state == "held":
            out.append({"pull": int(p["number"]), "for": who, "state": "held", "instruction": INSTRUCTION, "url": f"https://github.com/{repo}/pull/{int(p['number'])}",
                        "said": f"Held for @{who}: {INSTRUCTION}. Test USDC, no monetary value."})
    return sorted(out, key=lambda r: r["pull"])


# ---- what is there ------------------------------------------------------------------------------------------------------------
def _stamp(text) -> float:
    return datetime.datetime.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc).timestamp()


def _iso(when: float) -> str:
    return datetime.datetime.fromtimestamp(when, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read(gh: Forge, repo: str, owner_id: int) -> dict:
    """The board as the forge holds it: {"rows": every issue the board opened (open and closed), "listed": board.json's
    issue numbers}. A row: number, slug, amount, days, state, created, funded (the owner's fund comment is there)."""
    rows = []
    for i in _pages(gh, f"repos/{repo}/issues?state=all&labels=knos-funded&sort=created&direction=desc"):
        who = i.get("user")
        user: dict = who if isinstance(who, dict) else {}
        m = MARK.search(str(i.get("body") or ""))
        if "pull_request" in i or not m or user.get("id") != owner_id:        # a marker somebody else wrote opens nothing
            continue
        rows.append({"number": int(i["number"]), "slug": m.group(1), "amount": int(m.group(2)), "days": int(m.group(3)), "title": str(i.get("title") or ""),
                     "state": str(i.get("state") or "open"), "created": _stamp(i.get("created_at")), "funded": False})
    for r in rows:
        if r["state"] == "open":
            said = gh("GET", f"repos/{repo}/issues/{r['number']}/comments?per_page=100")
            r["funded"] = any(isinstance(c, dict) and (c.get("user") or {}).get("id") == owner_id and re.search(r"(?m)^/knos fund \d", str(c.get("body") or ""))
                              for c in (said if isinstance(said, list) else []))
    got = gh("GET", f"repos/{repo}/contents/{BOARD}")
    try:
        listed = json.loads(base64.b64decode(got["content"]).decode("utf-8"))["tasks"] if got else {}
    except (KeyError, TypeError, ValueError):
        raise Stop(f"{BOARD} in {repo} is not the board's file: nothing is written over it") from None
    return {"rows": rows, "listed": {int(k): str(v) for k, v in listed.items()}}


STRANDED = ("pin", "late", "closed")     # knos.tasks.explain's codes for an order on an open issue that no merge can pay


def stranded(state: dict, repo: str, why: Callable) -> dict[int, str]:
    """{issue: the chain's sentence} for each open, funded board issue whose money no merge can pay any more: funded
    through a commit of the workflows the playground no longer calls (a release rebuilt it at the next commit), past its
    deadline, or no longer open. `why(where, pull)` is knos.tasks.why, which reads the order from the chain."""
    out = {}
    for r in state["rows"]:
        if r["state"] != "open" or not r["funded"]:
            continue
        try:
            got = why(f"{repo}#{r['number']}", None)
        except Exception as no:  # noqa: BLE001 - knos.tasks.Stop and what the chain's client raises: an order that was not read is not judged
            raise Stop(f"the order of #{r['number']} could not be read ({' '.join(str(no).split())[:160]}): nothing was sent") from None
        if got.get("code") in STRANDED:
            out[r["number"]] = str(got["said"])
    return out


def plan(state: dict, now: float, target: int = TARGET, budget: int = BUDGET, reserve: int = RESERVE, balance: int | None = None,
         tasks: list[dict] | None = None, kinds_: list[dict] | None = None) -> dict:
    """What `open` would do. `balance`: millionths the named Balance holds, None when none was named (the faucet pays).
    `kinds_`: the tasks that are not code to keep open as well (`--kinds`), first, in the same budget and not in the target.
    Returns {"open": rows that are whole, "resume": rows missing a step, "new": tasks to open, "said": why it stops
    where it stops, "spent": opened today, "left": of today's budget}."""
    tasks = catalogue() if tasks is None else tasks
    least = _src()[3].ORDER_MIN_AMOUNT
    by_slug = {t["slug"]: t for t in tasks + kinds()}
    today = _iso(now)[:10]
    live = [r for r in state["rows"] if r["state"] == "open"]
    whole = [r for r in live if r["funded"] and r["number"] in state["listed"]]
    resume = [r for r in live if r not in whole]
    spent = sum(r["amount"] + _fee(r["amount"]) for r in state["rows"] if _iso(r["created"])[:10] == today)
    said: list[str] = []
    new: list[dict] = []
    funds = sum(r["amount"] + _fee(r["amount"]) for r in resume if not r["funded"])         # opened, counted in today's budget or an earlier day's; still to fund
    room = None if balance is None else balance - reserve - funds
    if room is not None and room < 0 and funds:
        said.append(f"the Balance holds {_usdc(balance)}: funding what is already open would leave less than the reserve of {_usdc(reserve)}, so nothing is funded")
        resume = [r for r in resume if r["funded"]]
    code = [r for r in state["rows"] if not is_kind(r)]
    last = max(code, key=lambda r: r["number"])["slug"] if code else None
    start = next((n + 1 for n, t in enumerate(tasks) if t["slug"] == last), 0)
    taken = {r["slug"] for r in live}
    live_code = len([r for r in live if not is_kind(r)])
    left = budget - spent
    stopped = False
    for t in list(kinds_ or []) + tasks[start:] + tasks[:start]:
        if not is_kind(t) and live_code + len([x for x in new if not is_kind(x)]) >= target:
            break
        if t["slug"] in taken:
            continue
        if t["amount"] < least:
            said.append(f"{t['slug']} pays {_usdc(t['amount'])} and the escrow holds a work order from {_usdc(least)}: it is passed over")
            continue
        price = cost(t)
        if price > left:
            said.append(f"today's budget of {_usdc(budget)} is used up to {_usdc(budget - left)}: {t['slug']} ({_usdc(price)} with its fee) waits for tomorrow (UTC)")
            stopped = True
            break
        if room is not None and price > room:
            said.append(f"the Balance holds {_usdc(balance)} and keeps a reserve of {_usdc(reserve)}: {t['slug']} ({_usdc(price)} with its fee) is not opened")
            stopped = True
            break
        new.append(t)
        left -= price
        room = None if room is None else room - price
    unknown = sorted({r["slug"] for r in live} - set(by_slug))
    if unknown:
        said.append(f"open on the board and not in tasks/: {', '.join(unknown)} (left as they are)")
        resume = [r for r in resume if r["slug"] in by_slug]
    count = live_code + len([x for x in new if not is_kind(x)])
    if not stopped and not said and count < target:
        said.append(f"every task of tasks/ is open: {count} of {target}")
    return {"open": whole, "resume": resume, "new": new, "said": said, "spent": spent, "left": left, "target": target, "budget": budget,
            "reserve": reserve, "balance": balance}


def _fee(amount: int) -> int:
    _p, _a, _j, pay = _src()
    return pay.order_fee(amount)


def _usdc(units: int | None) -> str:
    return "an amount that was not read" if units is None else f"{units / 1_000_000:.2f} test USDC"


def words(p: dict, repo: str) -> list[str]:
    """The plan in sentences, the limits first."""
    out = [f"{repo}: {len(p['open'])} funded tasks open, {len(p['resume'])} half opened, {len(p['new'])} to open, for a target of {p['target']}.",
           f"Today (UTC): {_usdc(p['spent'])} opened of a budget of {_usdc(p['budget'])}; after this run {_usdc(p['left'])} is left.",
           (f"The payer's Balance holds {_usdc(p['balance'])} and keeps a reserve of {_usdc(p['reserve'])}." if p["balance"] is not None else
            "No Balance was named: only the devnet faucet may pay, and it mints the test USDC of each funding.")]
    out += [f"  finish #{r['number']} {r['slug']}: " + ", ".join(w for w, missing in (("commit its checks", r["number"] not in p.get("listed", {r["number"]: 1})),
                                                                                       ("fund it", not r["funded"])) if missing) for r in p["resume"]]
    out += [f"  open {t['slug']}: {_usdc(t['amount'])}, fee {_usdc(_fee(t['amount']))}, {t['deadline_days']} days" for t in p["new"]]
    return out + [f"  stops: {s}" for s in p["said"]]


# ---- writing ------------------------------------------------------------------------------------------------------------------
def commit(gh: Forge, repo: str, files: dict[str, bytes], message: str, gone: list[str] | tuple = ()) -> str:
    """One commit on the default branch that holds these files, and not the files `gone` names: git's own blob-less tree
    call (an entry whose sha is null removes the path), a commit, the ref."""
    ref = gh("GET", f"repos/{repo}/git/ref/heads/main")
    held_at = gh("GET", f"repos/{repo}/git/commits/{ref['object']['sha']}") if ref else None
    if not ref or not held_at:
        raise Stop(f"{repo} has no branch main")
    tip, base = ref["object"]["sha"], held_at["tree"]["sha"]
    tree = gh("POST", f"repos/{repo}/git/trees", {"base_tree": base, "tree": [
        {"path": rel, "mode": "100644", "type": "blob", "content": data.decode("utf-8")} for rel, data in sorted(files.items())] + [
        {"path": rel, "mode": "100644", "type": "blob", "sha": None} for rel in sorted(set(gone) - set(files))]})
    made = gh("POST", f"repos/{repo}/git/commits", {"message": message, "tree": tree["sha"], "parents": [tip]})
    gh("PATCH", f"repos/{repo}/git/refs/heads/main", {"sha": made["sha"], "force": False})
    return str(made["sha"])


def open_tasks(gh: Forge, repo: str, p: dict, state: dict, apply: bool, say: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep,
               pace: float = PACE) -> list[dict]:
    """Carry the plan out (`apply`), or say what would be sent. Returns what was done: [{"issue", "slug", "did": [...]}]."""
    by_slug = {t["slug"]: t for t in catalogue() + kinds()}
    todo = [(r["number"], by_slug[r["slug"]], r["number"] in state["listed"], r["funded"]) for r in p["resume"]] + [(0, t, False, False) for t in p["new"]]
    if not apply:
        for number, t, has, funded in todo:
            say(f"would {'finish #%d' % number if number else 'open an issue for'} {t['slug']}: \"{t['title']}\", then `{fund_line(t)}`")
        say("A dry run: nothing was sent. With --apply this is done.")
        return []
    if todo:
        for name, (colour, about) in LABEL_WORDS.items():
            if gh("GET", f"repos/{repo}/labels/{name.replace(' ', '%20')}") is None:
                gh("POST", f"repos/{repo}/labels", {"name": name, "color": colour, "description": about})
    listed, done, funded_one = dict(state["listed"]), [], False
    for number, t, has, funded in todo:
        did = []
        if not number:
            number = int(gh("POST", f"repos/{repo}/issues", {"title": t["title"], "body": (kind_body if is_kind(t) else issue_body)(t, repo),
                                                             "labels": list(LABELS)})["number"])
            did.append("opened")
        if not has:
            listed[number] = t["slug"]
            if is_kind(t):      # merge mode: the starter task's checks under this number would make the funding a tests-mode order
                files, gone = {}, _folder(gh, repo, f".knos/acceptance/{number}")
            else:
                files, gone = {f".knos/acceptance/{number}/{rel}": data for rel, data in bundle(t, number).items()}, []
            files[BOARD] = board_file(listed)
            commit(gh, repo, files, f"Task #{number}: {t['slug']} (test USDC, no monetary value)", gone)
            did.append("its line on the board committed" + (f", {len(gone)} starter checks removed" if gone else "") if is_kind(t) else "checks committed")
        if not funded:
            if funded_one:
                sleep(pace)
            gh("POST", f"repos/{repo}/issues/{number}/comments", {"body": fund_line(t)})
            funded_one = True
            did.append("funding asked")
        say(f"#{number} {t['slug']}: {', '.join(did)}")
        done.append({"issue": number, "slug": t["slug"], "did": did})
    say(f"{len(done)} tasks written. The workflow answers each funding in a comment; `status` shows what is funded.")
    return done


def _folder(gh: Forge, repo: str, path: str) -> list[str]:
    """Every file under `path` on the default branch, [] when there is no such folder."""
    got = gh("GET", f"repos/{repo}/contents/{path}")
    if got is None:
        return []
    if not isinstance(got, list):
        raise Stop(f"{path} in {repo} is not a folder: nothing is written over it")
    out: list[str] = []
    for e in got:
        if isinstance(e, dict) and e.get("type") == "dir":
            out += _folder(gh, repo, str(e["path"]))
        elif isinstance(e, dict) and e.get("type") == "file":
            out.append(str(e["path"]))
    return sorted(out)


def board_file(listed: dict[int, str]) -> bytes:
    return (json.dumps({"v": 1, "tasks": {str(k): listed[k] for k in sorted(listed)}}, indent=1) + "\n").encode("utf-8")


# ---- status -------------------------------------------------------------------------------------------------------------------
def waiting(gh: Forge, repo: str) -> list[dict]:
    """Pull requests whose workflow runs wait for a maintainer's approval, each with the files its diff touches and what
    the judge's rule says of each path. Read only."""
    _p, _a, judge, _pay = _src()
    runs = _pages(gh, f"repos/{repo}/actions/runs?status=action_required", most=2)
    heads = {str(r.get("head_sha")) for r in runs}
    out = []
    for pull in _pages(gh, f"repos/{repo}/pulls?state=open") if heads else []:
        if str((pull.get("head") or {}).get("sha")) not in heads:
            continue
        files = _pages(gh, f"repos/{repo}/pulls/{pull['number']}/files", most=3)
        out.append({"pull": int(pull["number"]), "by": str((pull.get("user") or {}).get("login") or ""), "title": str(pull.get("title") or ""),
                    "closes": sorted({int(n) for n in CLOSES.findall(str(pull.get("body") or ""))}),
                    "url": f"https://github.com/{repo}/pull/{pull['number']}",
                    "files": [{"path": str(f.get("filename")), "status": str(f.get("status")),
                               "rule": judge.classify_path(str(f.get("filename")), {"runner": "blackbox"},
                                                           f.get("status") if f.get("status") in ("added", "removed") else "modified")} for f in files]})
    return sorted(out, key=lambda r: r["pull"])


def status(gh: Forge, repo: str, owner_id: int, now: float, target: int = TARGET, budget: int = BUDGET) -> dict:
    """The board as one JSON document: what the site's playground page draws (web/playground.js) and what a person reads."""
    tasks = _tasks()
    files = {t["slug"]: t["file"] for t in catalogue()}
    other = {t["slug"]: t for t in kinds()}
    wrong = unpinned(gh, repo)
    state = read(gh, repo, owner_id)
    pulls = [p for p in _pages(gh, f"repos/{repo}/pulls?state=all") if (p.get("user") or {}).get("id") != owner_id]
    board = {r["number"] for r in state["rows"]}
    on_board = [p for p in pulls if board & {int(n) for n in CLOSES.findall(str(p.get("body") or ""))}]
    rows = []
    for r in sorted((r for r in state["rows"] if r["state"] == "open"), key=lambda r: r["number"]):
        rows.append({"issue": r["number"], "slug": r["slug"], "title": r["title"], "amount": r["amount"], "decimals": 6, "currency": "test USDC",
                     "kind": other[r["slug"]]["kind"] if r["slug"] in other else "code",
                     "file": other[r["slug"]]["file"] if r["slug"] in other else files.get(r["slug"], ""),
                     "accept": f"The evidence, one file under {other[r['slug']]['file']}: {other[r['slug']]['evidence']}. A maintainer checks it and merges."
                               if r["slug"] in other else tasks.ACCEPT, "pays": tasks.PAYS,
                     "opened": _iso(r["created"]), "deadline": _iso(r["created"] + r["days"] * 86_400), "url": f"https://github.com/{repo}/issues/{r['number']}",
                     "state": "funding asked" if r["funded"] and r["number"] in state["listed"] else "being opened",
                     "pulls": sorted(int(p["number"]) for p in on_board if p.get("state") == "open" and r["number"] in {int(n) for n in CLOSES.findall(str(p.get("body") or ""))})})
    today = _iso(now)[:10]
    spent = sum(r["amount"] + _fee(r["amount"]) for r in state["rows"] if _iso(r["created"])[:10] == today)
    return {"v": 1, "read": True, "repository": repo, "at": _iso(now), "note": FIRST, "target": target, "tasks": rows,
            "budget": {"day": today, "limit": budget, "opened": spent},
            "outside_pulls": {"received": len(on_board), "merged": sum(1 for p in on_board if p.get("merged_at")), "accounts": len({(p.get("user") or {}).get("id") for p in on_board}),
                              "paid": None, "definition": "pull requests from accounts that are not the repository owner's that name a board task; "
                                                          "paid is read from the chain by scripts/outsiders.py, never here"},
            "workflows": {"public": not wrong, "problems": wrong},
            "held": held_rows(gh, repo, on_board), "awaiting_approval": waiting(gh, repo)}


def status_words(s: dict) -> list[str]:
    out = [f"{s['repository']} at {s['at']}: {len(s['tasks'])} of {s['target']} tasks open. {FIRST}"]
    for t in s["tasks"]:
        out.append(f"  #{t['issue']} {t['slug']}: {_usdc(t['amount'])}, until {t['deadline'][:10]}, {t['state']}"
                   + (f", pull requests {', '.join('#%d' % n for n in t['pulls'])}" if t["pulls"] else ""))
    out.append(f"Opened today (UTC {s['budget']['day']}): {_usdc(s['budget']['opened'])} of {_usdc(s['budget']['limit'])}.")
    o = s["outside_pulls"]
    out.append(f"Outside pull requests on board tasks: {o['received']} received from {o['accounts']} accounts, {o['merged']} merged; paid is not read here.")
    out.append("The playground calls the public pinned workflows: an order funded now is one the public worker can pay." if s["workflows"]["public"] else
               "NOT FUNDED THROUGH THE PUBLIC WORKFLOWS: " + "; ".join(s["workflows"]["problems"]) + ".")
    out += [f"HELD: #{h['pull']} for @{h['for']}: {h['instruction']} ({h['url']})." for h in s["held"]]
    if not s["awaiting_approval"]:
        out.append("No pull request has a run waiting for approval.")
    for w in s["awaiting_approval"]:
        out.append(f"WAITS FOR APPROVAL: #{w['pull']} by @{w['by']} ({w['url']}), closes {', '.join('#%d' % n for n in w['closes']) or 'no task'}. Its diff:")
        out += [f"    {f['status']:<9} {f['path']}  [{f['rule']}]" for f in w["files"]]
    if s["awaiting_approval"]:
        out.append("Nothing was approved. Approving runs the pull request's code: read the diff, then approve on GitHub yourself.")
    return out


def main(argv: list[str] | None = None, gh: Forge = github, ask: Callable = rpc, now: Callable[[], float] = time.time, say: Callable[[str], None] = print,
         sleep: Callable[[float], None] = time.sleep, why: Callable | None = None) -> int:
    playground = _playground()
    ap =argparse.ArgumentParser(description="Keep funded test tasks open in the playground. Test USDC, no monetary value.")
    sub = ap.add_subparsers(dest="command", required=True)
    for name, text in (("plan", "what `open` would do"), ("open", "open and fund tasks up to the target; --apply sends it"), ("status", "the board, and runs that wait for approval")):
        one = sub.add_parser(name, help=text)
        one.add_argument("--repo", default=playground.REPO)
        one.add_argument("-n", "--target", type=int, default=TARGET, help="tasks open at once")
        one.add_argument("--budget", type=float, default=BUDGET / 1_000_000, help="test USDC opened in one UTC day at most, fees included")
        if name != "status":
            one.add_argument("--reserve", type=float, default=RESERVE / 1_000_000, help="test USDC the named Balance keeps")
            one.add_argument("--balance", default=os.environ.get("KNOS_BOARD_BALANCE", ""), help="the address of the Balance the owner's comment spends")
            one.add_argument("--faucet", action="store_true", help="no Balance: the devnet faucet mints each funding")
            one.add_argument("--pace", type=float, default=PACE, help="seconds between two fundings")
            one.add_argument("--kinds", action="store_true", help="also keep the five tasks that are not code open (tasks/outside/), first, in the same budget")
        if name == "open":
            one.add_argument("--apply", action="store_true", help="send it (the account must own the repository)")
        if name == "status":
            one.add_argument("--json", action="store_true")
            one.add_argument("--empty", action="store_true", help="ask nobody: the document a build writes when it reads no board (scripts/build_site.sh)")
    one = sub.add_parser("why", help="why a merged pull request was not paid, and what fixes it")
    one.add_argument("where", help="the funded issue, as owner/repo#number")
    one.add_argument("--pull", type=int, default=0, help="the merged pull request's number")
    one.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.command == "why":
        tasks = _tasks()
        try:
            got = why(a.where, a.pull or None) if why is not None else tasks.why(a.where, a.pull or None)
        except tasks.Stop as no:
            say(f"task board: {no}")
            return 1
        say(json.dumps(got, indent=1, ensure_ascii=False) if a.json else f"{got['said']}\nFix: {got['fix']}")
        return 0
    budget = int(round(a.budget * 1_000_000))
    try:
        if a.repo.lower() != playground.REPO.lower():
            raise Stop(f"the board keeps tasks in {playground.REPO} and nowhere else")
        if a.command == "status" and a.empty:
            say(json.dumps({"v": 1, "read": False, "repository": a.repo, "note": FIRST, "tasks": []}, indent=1))
            return 0
        if a.command == "status":
            s = status(gh, a.repo, playground.OWNER_ID, now(), a.target, budget)
            say(json.dumps(s, indent=1, ensure_ascii=False) if a.json else "\n".join(status_words(s)))
            return 0
        if not 1 <= a.target <= len(catalogue()):
            raise Stop(f"the target is from 1 to {len(catalogue())}, the number of tasks in tasks/")
        if a.balance and a.faucet:
            raise Stop("name a Balance or say --faucet, not both")
        if a.command == "open" and a.apply and not a.balance and not a.faucet:
            raise Stop("nothing was sent: say what pays, `--balance <address>` (its reserve is kept) or `--faucet` (the devnet faucet mints it)")
        state = read(gh, a.repo, playground.OWNER_ID)
        lost = stranded(state, a.repo, why or _tasks().why)
        for r in state["rows"]:
            if r["number"] in lost:
                r["state"] = "stranded"         # not open for the plan: its money cannot pay a merge, so the task is opened again
        p = plan(state, now(), a.target, budget, int(round(a.reserve * 1_000_000)), held(a.balance, ask) if a.balance else None,
                 kinds_=kinds() if a.kinds else None)
        p["listed"] = state["listed"]
        for line in words(p, a.repo):
            say(line)
        for n, said in sorted(lost.items()):
            say(f"  stranded #{n}: {said} {'It is closed with that sentence' if a.command == 'open' and a.apply else 'open --apply closes it with that sentence'}, "
                "and its task can be opened again.")
        wrong = unpinned(gh, a.repo)
        for line in wrong:
            say(f"  not public: {line}")
        if a.command == "open" and a.apply and wrong:
            raise Stop("nothing was sent: an order funded now would name workflows the public worker's run is not signed for, and no merge could pay it")
        if not wrong:
            say("  funds through the public pinned workflows: checked in the playground's own workflow files.")
        if a.command == "open":
            if a.apply:
                for n, said in sorted(lost.items()):
                    gh("POST", f"repos/{a.repo}/issues/{n}/comments", {"body": f"{said} The money goes back to its funder at its deadline; "
                                                                            f"the task is opened again in a new issue. {FIRST}"})
                    gh("PATCH", f"repos/{a.repo}/issues/{n}", {"state": "closed", "state_reason": "not_planned"})
            open_tasks(gh, a.repo, p, state, a.apply, say, sleep, a.pace)
    except Stop as why:
        say(f"task board: {why}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
