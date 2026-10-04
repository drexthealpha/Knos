"""The three small repositories a release publishes besides the pinned workflows, each written from this repository's
own files, byte for byte, with nothing in them that is not derived from the sources here.

    python scripts/small_repos.py list                 the repositories and what each is for
    python scripts/small_repos.py build NAME DIR       write the repository NAME into DIR (a checkout of it, or any folder)
    python scripts/small_repos.py check NAME DIR       exit 1 unless DIR holds exactly that
    python scripts/small_repos.py tree NAME            the git tree id a commit of it must have

    knos-task       drexthealpha/knos-task: the template the site's "a task with no repository" makes a repository
                    from (web/task.js, TEMPLATE). It holds Knos's two caller workflows, so that the issue the site then
                    opens can be funded with a comment and the pull request that solves it is judged and paid.
    knos-attest     drexthealpha/knos-attest: the template a seller makes his own `knos-attest` repository from. It
                    holds examples/knos-attest.yml: a run by hand there asks GitHub to sign that an order's terms
                    were met (`knos settle --neutral` and the site start it).
    knos-claim-org  drexthealpha/knos-claim-org: the template an ORGANISATION makes its `knos-claim` repository from. It
                    holds examples/knos-claim-org.yml, which calls the pinned claim workflow with kind org. (A person's
                    template is drexthealpha/knos-claim, which `knos claim` uses.)

Each is a template repository on GitHub (`gh repo edit <name> --template`). Build them AFTER `pinned_workflows.py stamp`:
the callers name the commit of the published workflows, and a caller that still held the placeholder would call
nothing. The output has no date and no name in it: the same sources give the same tree (scripts/pinned_workflows.py,
tree_id), so anyone can check that what is published is what this repository says.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
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

1. You open an issue that says what you want built, and add the acceptance files the form made
   (`.knos/acceptance/<issue>/`): pairs of an input and the answer it must get.
2. You fund the issue with a comment, `/knos fund <amount> tests`. The money goes into an escrow on Solana, and the
   terms are fixed at that moment.
3. Anyone opens a pull request that solves it. Knos runs the solution on every recorded input in a sandbox. When every
   answer matches, GitHub signs that it did, and the escrow pays the author. No merge and no decision of yours is
   needed, and nobody can change the terms afterwards.

The two files in `.github/workflows/` are Knos's callers, copied from
[drexthealpha/Knos/examples](https://github.com/drexthealpha/Knos/tree/main/examples). Their comments say what each
trigger does and what the file can and cannot do in this repository. They need no secret.

On Solana devnet today, in test USDC.
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
    "knos-task": ("the template the site's task form makes a repository from", {
        ".github/workflows/knos.yml": Path("examples/knos-workflow.yml"),
        ".github/workflows/knos-check.yml": Path("examples/knos-check.yml"),
        "README.md": TASK_README, "LICENSE": Path("LICENSE")}),
    "knos-attest": ("the template a seller makes his attest repository from", {
        ".github/workflows/knos-attest.yml": Path("examples/knos-attest.yml"),
        "README.md": ATTEST_README, "LICENSE": Path("LICENSE")}),
    "knos-claim-org": ("the template an organisation makes its knos-claim repository from", {
        ".github/workflows/knos-claim.yml": Path("examples/knos-claim-org.yml"),
        "README.md": CLAIM_ORG_README, "LICENSE": Path("LICENSE")}),
}


def files(name: str) -> dict[str, bytes]:
    """Every file of the repository `name`, by its path there."""
    if name not in REPOS:
        raise SystemExit(f"there is no repository {name} here: {', '.join(REPOS)}")
    out = {rel: (ROOT / src).read_bytes() if isinstance(src, Path) else src.encode("utf-8") for rel, src in REPOS[name][1].items()}
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write and check the small repositories a release publishes.")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="the repositories and what each is for")
    for command, text in (("build", "write the repository into a folder"), ("check", "exit 1 unless the folder holds exactly the repository"), ("tree", "print its git tree id")):
        one = sub.add_parser(command, help=text)
        one.add_argument("name", choices=sorted(REPOS))
        if command != "tree":
            one.add_argument("dir")
    a = ap.parse_args(argv)
    if a.command == "list":
        for name, (what, _files) in REPOS.items():
            print(f"{OWNER}/{name}: {what} ({len(_files)} files, tree {_pub().tree_id(files(name))})")
        return 0
    want = files(a.name)
    if a.command == "tree":
        print(_pub().tree_id(want))
        return 0
    folder = Path(a.dir)
    if a.command == "check":
        said = _pub().differences(folder, want)
        for line in said:
            print(f"{a.dir}: {line}")
        print(f"{a.dir} is {OWNER}/{a.name} as this repository writes it, byte for byte (tree {_pub().tree_id(want)})." if not said else
              f"{a.dir} is not {OWNER}/{a.name}. Write it again: python scripts/small_repos.py build {a.name} {a.dir}")
        return 1 if said else 0
    for rel in sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and ".git" not in p.relative_to(folder).parts) if folder.is_dir() else []:
        if rel not in want:
            (folder / rel).unlink()                 # the repository holds these files and nothing else
    for rel, data in want.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_bytes(data)
    print(f"Wrote {OWNER}/{a.name} ({len(want)} files, tree {_pub().tree_id(want)}) into {a.dir}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
