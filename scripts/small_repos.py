"""The four small repositories a release publishes besides the pinned workflows, each written from this repository's
own files, byte for byte, with nothing in them that is not derived from the sources here.

    python scripts/small_repos.py list                 the repositories and what each is for
    python scripts/small_repos.py build NAME DIR       write the repository NAME into DIR (a checkout of it, or any folder)
    python scripts/small_repos.py check NAME DIR       exit 1 unless DIR holds exactly that
    python scripts/small_repos.py tree NAME            the git tree id a commit of it must have
    python scripts/small_repos.py settings NAME        the GitHub API calls that give NAME its settings (a dry run: it
                                                       prints them); with --apply it makes them through `gh api`

    knos-task       drexthealpha/knos-task: the template the site's "a task with no repository" makes a repository
                    from (web/task.js, TEMPLATE). It holds Knos's two caller workflows, so that the issue the site then
                    opens can be funded with a comment and the pull request that solves it is judged and paid. It also
                    holds examples/knos-reproduce.yml, so "Use this template" and "Run workflow" are the whole
                    reproduction (docs/REPRODUCE.md).
    knos-playground drexthealpha/knos-playground: NOT a template. The one repository where an account that cannot
                    write may fund a test task from the devnet faucet (src/knos/playground.py has the limits). It
                    holds the two callers, an issue template whose text carries the fund line, a starter file, and
                    the starter task's black-box acceptance checks under every issue number from 1 to
                    playground.SLOTS: a stranger's issue gets whatever number is next and cannot add files, and a
                    task with no checks could only be paid by a merge. docs/PLAYGROUND.md is what a stranger reads.
    knos-attest     drexthealpha/knos-attest: the template a seller makes his own `knos-attest` repository from. It
                    holds examples/knos-attest.yml: a run by hand there asks GitHub to sign that an order's terms
                    were met (`knos settle --neutral` and the site start it).
    knos-claim-org  drexthealpha/knos-claim-org: the template an ORGANISATION makes its `knos-claim` repository from. It
                    holds examples/knos-claim-org.yml, which calls the pinned claim workflow with kind org. (A person's
                    template is drexthealpha/knos-claim, which `knos claim` uses.)

knos-task, knos-attest and knos-claim-org are template repositories on GitHub (`settings` sets `is_template` through PATCH /repos/{owner}/{repo},
https://docs.github.com/en/rest/repos/repos#update-a-repository). Build them AFTER `pinned_workflows.py stamp`:
the callers name the commit of the published workflows, and a caller that still held the placeholder would call
nothing. The output has no date and no name in it: the same sources give the same tree (scripts/pinned_workflows.py,
tree_id), so anyone can check that what is published is what this repository says.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER = "drexthealpha"


def _pub():
    spec = importlib.util.spec_from_file_location("pinned_workflows", Path(__file__).with_name("pinned_workflows.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = ROOT
    return mod


TASK_README = """# knos-task

A repository for one piece of paid work, made from this template by the "task with no repository" form on the
[Knos](https://github.com/drexthealpha/Knos) site.

What happens here:

To reproduce what Knos says it does, with nothing installed: press **Use this template**, then in your new repository
open **Actions**, choose **knos reproduce** and press **Run workflow**. GitHub signs the report
([how](https://github.com/drexthealpha/Knos/blob/main/docs/REPRODUCE.md)).

For a task:

1. You open an issue that says what you want built, and add the acceptance files the form made
   (`.knos/acceptance/<issue>/`): pairs of an input and the answer it must get.
2. You fund the issue with a comment, `/knos fund <amount> tests`. The money goes into an escrow on Solana, and the
   terms are fixed at that moment.
3. Anyone opens a pull request that solves it. Knos runs the solution on every recorded input in a sandbox. When every
   answer matches, GitHub signs that it did, and the escrow pays the author. No merge and no decision of yours is
   needed, and nobody can change the terms afterwards.

The files in `.github/workflows/` are copied from
[drexthealpha/Knos/examples](https://github.com/drexthealpha/Knos/tree/main/examples): Knos's two callers, and
`knos-reproduce.yml`, which runs only when you start it by hand. Their comments say what each trigger does and what the
file can and cannot do in this repository. They need no secret.

On Solana devnet today, in test USDC.
"""

PLAYGROUND_README = """# knos-playground

Try [Knos](https://github.com/drexthealpha/Knos) from both sides with a GitHub account and nothing else. Nothing is
installed, and no wallet is needed.

**Fund a test task.** [Open the issue](https://github.com/drexthealpha/knos-playground/issues/new?template=fund-a-test-task.md)
and press **Submit new issue**. Its text holds the line `{fund}`: 5 test USDC from the devnet faucet go into an
escrow on Solana for that issue, and Knos answers in a comment.

**Take one.** Pick an [open issue](https://github.com/drexthealpha/knos-playground/issues),
[edit `{task}`](https://github.com/drexthealpha/knos-playground/edit/main/{task}) in the browser so that it prints the
words of a line in reverse order, and open the pull request with `Closes #<the issue's number>` in its description.
The checks in `.knos/acceptance/<number>/` run your file as a separate process and compare what it prints. When every
answer matches, GitHub signs that it did and the escrow pays you: to the wallet you bound, or held for your account
until you bind one. Nobody merges and nobody decides.

The limits: an issue is funded only as it is opened, with at most {most} test USDC; one account funds at most {per_day}
in a day (UTC); the faucet serves this repository once a minute; issues 1 to {slots} have checks. A first pull request
from an account that is new to GitHub waits until a maintainer lets its check run.

It is test money: the faucet mints it, nobody can withdraw it from the faucet's balance, and it is worth nothing.
What is counted, and how: [docs/PLAYGROUND.md](https://github.com/drexthealpha/Knos/blob/main/docs/PLAYGROUND.md).

On Solana devnet today, in test USDC.
"""

ISSUE_TEMPLATE = """---
name: Fund a test task
about: Put 5 test USDC from the devnet faucet on a starter task. Press Submit; nothing is installed or spent.
title: "Playground: reverse the words of a line"
---
Submitting this funds one test task with 5 test USDC from the devnet faucet: no wallet, nothing installed, nothing of yours spent.
The task: make `{task}` print the words of a line in reverse order. Anyone may solve it, and the checks decide, not a person.

{fund}
"""

ISSUE_CONFIG = """blank_issues_enabled: false
contact_links:
  - name: What the playground is, its limits, and how it is counted
    url: https://github.com/drexthealpha/Knos/blob/main/docs/PLAYGROUND.md
    about: One screen.
"""

PULL_TEMPLATE = """Closes #

<!-- Put the number of the task you took after the # above. That is how the escrow knows which task this solves. -->
"""

STARTER = """# The playground's starter task: print the words of one line in reverse order, one space between them.
#
#     input:   the quick brown fox        output:   fox brown quick the
#
# As it is, this prints the line as it came. Change the last line, open a pull request with "Closes #<the task's
# number>" in its description, and the checks in .knos/acceptance/<number>/ run this file and compare what it prints.
import sys

words = sys.stdin.readline().split()
print(" ".join(words))
"""

ATTEST_README = """# knos-attest

Ask GitHub to sign that a [Knos](https://github.com/drexthealpha/Knos) work order's terms were met, so that the person
who did the work can ask for the payment himself.

1. Press **Use this template** and create the repository in **your own account**, named `knos-attest`, public.
2. In your new repository open **Actions**, choose **knos attest**, press **Run workflow**, and say which repository
   the pull request is in, its number, and the order (its address is on the order's page). Or run
   `knos settle --neutral <pull request url>`, which starts the same run.
3. The run reads GitHub's public record of that pull request and the order on Solana. If the record supports it,
   GitHub signs a statement that names the order, the pull request and the commit, and a relayer carries it to
   Solana, where the escrow pays.

It needs no secret, checks out no code and changes nothing anywhere. What it can do is written at the top of
[the file](.github/workflows/knos-attest.yml), and why a run started by hand in your own repository is trusted.

On Solana devnet today, in test USDC.
"""

CLAIM_ORG_README = """# knos-claim (for an organisation)

Name the Solana address that [Knos](https://github.com/drexthealpha/Knos) pays your GitHub **organisation** at.
A personal account uses [drexthealpha/knos-claim](https://github.com/drexthealpha/knos-claim) instead.

1. Press **Use this template** and create the repository in **the organisation**, named `knos-claim`.
2. Give write access to it only to the people you trust with where the organisation's payments go: everyone who can
   start a workflow by hand here can name the address.
3. In the new repository open **Actions**, choose **knos claim**, press **Run workflow**, and paste the address
   yourself.
4. The run asks GitHub for a signed statement that a member started it in the organisation's repository and names
   that address, and posts it on an issue. A relayer carries it to Solana. From then on what is owed to the
   organisation through Knos is paid to that address.

Run the workflow again with another address to change it. Nothing else starts a claim: no push, no link, no
repository description.

The workflow needs no secret and cannot read or change code. What it can do is written at the top of
[the file](.github/workflows/knos-claim.yml).

On Solana devnet today, in test USDC.
"""

# name -> (what it is for, {path in the repository: a source file here, or the text itself})
REPOS: dict[str, tuple[str, dict[str, str | Path]]] = {
    "knos-task": ("the template the site's task form makes a repository from, and the one-click reproduction", {
        ".github/workflows/knos.yml": Path("examples/knos-workflow.yml"),
        ".github/workflows/knos-check.yml": Path("examples/knos-check.yml"),
        ".github/workflows/knos-reproduce.yml": Path("examples/knos-reproduce.yml"),
        "README.md": TASK_README, "LICENSE": Path("LICENSE")}),
    "knos-playground": ("where anyone funds a test task from the faucet and anyone takes one", {
        ".github/workflows/knos.yml": Path("examples/knos-workflow.yml"),
        ".github/workflows/knos-check.yml": Path("examples/knos-check.yml"),
        ".github/ISSUE_TEMPLATE/fund-a-test-task.md": ISSUE_TEMPLATE,
        ".github/ISSUE_TEMPLATE/config.yml": ISSUE_CONFIG,
        ".github/pull_request_template.md": PULL_TEMPLATE,
        "words.py": STARTER, "README.md": PLAYGROUND_README, "LICENSE": Path("LICENSE")}),
    "knos-attest": ("the template a seller makes his attest repository from", {
        ".github/workflows/knos-attest.yml": Path("examples/knos-attest.yml"),
        "README.md": ATTEST_README, "LICENSE": Path("LICENSE")}),
    "knos-claim-org": ("the template an organisation makes its knos-claim repository from", {
        ".github/workflows/knos-claim.yml": Path("examples/knos-claim-org.yml"),
        "README.md": CLAIM_ORG_README, "LICENSE": Path("LICENSE")}),
}


# What each repository is on GitHub besides its files: [(method, path under repos/OWNER/NAME, {field: value})].
# is_template and has_issues: https://docs.github.com/en/rest/repos/repos#update-a-repository. The approval policy
# (whose pull requests from a fork wait for a maintainer before a workflow runs; this is the least GitHub allows):
# https://docs.github.com/en/rest/actions/permissions, "Set fork PR contributor approval permissions for a repository".
_TEMPLATE = [("PATCH", "", {"is_template": True, "has_issues": True})]
SETTINGS: dict[str, list[tuple[str, str, dict]]] = {
    "knos-task": _TEMPLATE, "knos-attest": _TEMPLATE, "knos-claim-org": _TEMPLATE,
    "knos-playground": [("PATCH", "", {"is_template": False, "has_issues": True, "has_wiki": False, "has_projects": False}),
                        ("PUT", "/actions/permissions/fork-pr-contributor-approval", {"approval_policy": "first_time_contributors_new_to_github"})],
}


def _playground():
    """src/knos/playground.py: where the playground is and what its limits are."""
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from knos import playground
    finally:
        sys.path.remove(str(ROOT / "src"))
    return playground


def starter_cases() -> list[dict]:
    """The starter task's recorded cases: inputs from knos.accept's generator at a fixed seed (ASCII ones: what a
    process reads from a pipe does not depend on the judge's locale then), each with its words in reverse order."""
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from knos import accept
    finally:
        sys.path.remove(str(ROOT / "src"))
    return [{"input": line, "output": " ".join(reversed(line.split()))} for line in accept.inputs("text", 40, 16) if line.isascii()]


def slots() -> dict[str, bytes]:
    """`.knos/acceptance/<n>/` for every issue number the playground has checks for: the bundle `knos accept init`
    writes (black-box by knos.judge.black_box, or this raises), the same cases under each number."""
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from knos import accept
    finally:
        sys.path.remove(str(ROOT / "src"))
    p, cases, out = _playground(), starter_cases(), {}
    for n in range(1, p.SLOTS + 1):
        for rel, data in accept.bundle(n, ["python3", p.TASK], cases, "text", 16).items():
            out[f".knos/acceptance/{n}/{rel}"] = data
    return out


def tree_id(files: dict[str, bytes]) -> str:
    """The id git gives the tree that holds exactly these files (plain files, mode 100644): pinned_workflows.tree_id's
    answer, computed once per folder (that one walks every file again for every file, which 600 files do not allow)."""
    def obj(kind: bytes, body: bytes) -> bytes:
        return hashlib.sha1(kind + b" " + str(len(body)).encode() + b"\0" + body).digest()  # noqa: S324 - git's object id

    def tree(inside: dict[str, bytes]) -> bytes:
        blobs, folders = {}, {}
        for rel, data in inside.items():
            name, _, rest = rel.partition("/")
            if rest:
                folders.setdefault(name, {})[rest] = data
            else:
                blobs[name] = data
        entries = [(name.encode(), b"100644", obj(b"blob", data)) for name, data in blobs.items()]
        entries += [(name.encode() + b"/", b"40000", tree(sub)) for name, sub in folders.items()]     # git orders a folder as if its name ended in a slash
        return obj(b"tree", b"".join(mode + b" " + key.rstrip(b"/") + b"\0" + oid for key, mode, oid in sorted(entries)))
    return tree(files).hex()


def files(name: str) -> dict[str, bytes]:
    """Every file of the repository `name`, by its path there."""
    if name not in REPOS:
        raise SystemExit(f"there is no repository {name} here: {', '.join(REPOS)}")
    out = {rel: (ROOT / src).read_bytes() if isinstance(src, Path) else src.encode("utf-8") for rel, src in REPOS[name][1].items()}
    if name == "knos-playground":
        p = _playground()
        said = {"fund": p.FUND, "task": p.TASK, "most": p.MOST // 1_000_000, "per_day": p.PER_DAY, "slots": p.SLOTS}
        for rel in (".github/ISSUE_TEMPLATE/fund-a-test-task.md", "README.md"):
            out[rel] = out[rel].decode("utf-8").format(**said).encode("utf-8")
        out.update(slots())
    problems = wrong(name, out)
    if problems:
        raise SystemExit(f"{name} cannot be published as it is: " + "; ".join(problems))
    return out


def wrong(name: str, out: dict[str, bytes]) -> list[str]:
    """Why these files must not be published, one line each: a caller that names no real commit, or one the programs do not pin."""
    pub, said = _pub(), []
    ids = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
    for rel, data in out.items():
        text = data.decode("utf-8")
        if pub.PLACEHOLDER in text:
            said.append(f"{rel} still says {pub.PLACEHOLDER}: stamp the published commit first (python scripts/pinned_workflows.py stamp <sha>)")
        for workflow, ref in pub.NAMED.findall(text):
            if ref != pub.pin():
                said.append(f"{rel} calls {workflow} at {ref}, and the examples name {pub.pin()}")
        for ref in re.findall(r"knos-oidc-rotate/\.github/workflows/claim\.yml@(\w+)", text):
            if ref != ids["claim_sha_org"]:
                said.append(f"{rel} calls the claim workflow at {ref}, and the escrow takes an organisation's claim at {ids['claim_sha_org']}")
    return said


def calls(name: str) -> list[list[str]]:
    """The `gh api` commands that give the repository `name` its settings, each as an argv."""
    out = []
    for method, path, fields in SETTINGS[name]:
        argv = ["gh", "api", "-X", method, f"repos/{OWNER}/{name}{path}"]
        for key, value in fields.items():        # -F sends true and false as JSON booleans, -f a string as it is
            argv += ["-F" if isinstance(value, bool) else "-f", f"{key}={str(value).lower() if isinstance(value, bool) else value}"]
        out.append(argv)
    return out


def settings(name: str, apply: bool = False, run=subprocess.run) -> int:
    """Print the calls; with `apply`, make them. Without it nothing leaves this machine."""
    for argv in calls(name):
        print(shlex.join(argv))
        if apply:
            got = run(argv, capture_output=True, text=True, encoding="utf-8")
            if got.returncode:
                print(f"GitHub refused it: {(got.stderr or got.stdout).strip()[:300]}")
                return 1
    template = SETTINGS[name][0][2]["is_template"]
    print(f"{'Set' if apply else 'A dry run: nothing was sent. With --apply this sets'} {OWNER}/{name}: "
          f"{'a template repository' if template else 'not a template'}, issues on.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write and check the small repositories a release publishes.")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="the repositories and what each is for")
    for command, text in (("build", "write the repository into a folder"), ("check", "exit 1 unless the folder holds exactly the repository"), ("tree", "print its git tree id"),
                          ("settings", "print the GitHub API calls that set the repository's settings; --apply makes them")):
        one = sub.add_parser(command, help=text)
        one.add_argument("name", choices=sorted(REPOS))
        if command in ("build", "check"):
            one.add_argument("dir")
        if command == "settings":
            one.add_argument("--apply", action="store_true", help="make the calls through `gh api` (the account must own the repository)")
    a = ap.parse_args(argv)
    if a.command == "settings":
        return settings(a.name, a.apply)
    if a.command == "list":
        for name, (what, _files) in REPOS.items():
            print(f"{OWNER}/{name}: {what} ({len(files(name))} files, tree {tree_id(files(name))})")
        return 0
    want = files(a.name)
    if a.command == "tree":
        print(tree_id(want))
        return 0
    folder = Path(a.dir)
    if a.command == "check":
        said = _pub().differences(folder, want)
        for line in said:
            print(f"{a.dir}: {line}")
        print(f"{a.dir} is {OWNER}/{a.name} as this repository writes it, byte for byte (tree {tree_id(want)})." if not said else
              f"{a.dir} is not {OWNER}/{a.name}. Write it again: python scripts/small_repos.py build {a.name} {a.dir}")
        return 1 if said else 0
    for rel in sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and ".git" not in p.relative_to(folder).parts) if folder.is_dir() else []:
        if rel not in want:
            (folder / rel).unlink()                 # the repository holds these files and nothing else
    for rel, data in want.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_bytes(data)
    print(f"Wrote {OWNER}/{a.name} ({len(want)} files, tree {tree_id(want)}) into {a.dir}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
