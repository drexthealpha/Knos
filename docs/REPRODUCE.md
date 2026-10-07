# Reproduce Knos yourself

**Nobody outside has done this yet.** Outside reproductions: 0, which is the number of signed reports
[`reproductions/`](../reproductions) holds. No capability in [capabilities.json](capabilities.json) is `reproduced`.
This page is how the first one gets there without anyone taking the maintainer's word, or yours.

## Two clicks and one button

Three lines for a stranger. Nothing installed, no key, no wallet, no money (no fork? [**Use this template**](https://github.com/new?template_owner=drexthealpha&template_name=knos-task&name=knos-reproduce&visibility=public&owner=@me)
instead, below):

1. [Fork drexthealpha/Knos](https://github.com/drexthealpha/Knos/fork); in the fork open **Actions** and enable workflows.
2. Choose **knos reproduce** and press **Run workflow**.
3. When **knos reproduction, to send** is green, open its link and press **Create pull request**.

What the button does. The first run installs the released knos, runs `knos reproduce` against public things only and
has GitHub sign the report (below). The second,
[`knos-reproduction-send.yml`](../.github/workflows/knos-reproduction-send.yml), starts by itself when the first ends:
it puts the signed file on a branch `reproduction-<run id>` of your fork as `reproductions/<owner>-<repo>-<run id>.json`,
that file and nothing else, and prints a link that opens the pull request to drexthealpha/Knos with its title and text
filled in. The last press is yours because it has to be: a workflow's token is good for the repository the workflow is
in and for no other ([GitHub's documentation](https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication)),
so a run in your fork cannot open a pull request here. The link is GitHub's own form
([query parameters](https://docs.github.com/en/pull-requests/reference/using-query-parameters-to-create-a-pull-request)).

Without a fork: the template makes a repository of your own that already holds
[`knos-reproduce.yml`](../examples/knos-reproduce.yml) and has Actions on. Press **Create repository**, then
**Actions**, **knos reproduce**, **Run workflow**. A repository made from a template is no fork, so no pull request can
come from it: download the run's artifact `knos-reproduction` and send the file in it ("How to send it").

## Knos's own run

Until 0.3.19 nobody could run this path to its end from inside: the second workflow skipped in `drexthealpha`'s
repositories and the check refused the file, so the first complete run would have been a stranger's. An own run now
completes: the same signed file is put on the branch `reproduction-own-<run id>` as
`reproductions/own/<owner>-<repo>-<run id>.json` ([what that folder is](../reproductions/own/README.md)).

It is not a reproduction and is never counted as one. Every count reads `reproductions/*.json` and no deeper;
`knos.reproduce.verified(..., ours=True)` accepts in `own/` only a run that is Knos's own and gives it no capability;
an own run's file directly under `reproductions/` is refused as before. `reproductions/own/` holds 0 files today: the
release run files the first. A pull request that adds a file under `own/` is checked by `reproductions.yml` like a
stranger's (`scripts/capabilities.py reproduction --own`): it passes only for a run that is Knos's own, and says it
counts for nothing. Seen in staging: [an own run](https://github.com/drexthealpha/knos-rc/actions/runs/37628067412),
filed on its branch by the second workflow, and the check of its pull request green.

## From a terminal

On any machine with Python 3.10 or later (a report on your screen and in `report.json`; not signed):

```
pipx run --spec knos knos reproduce
```

It needs no secret, no wallet and no money, and it writes nothing to your repository.

## What each check proves

`knos reproduce` runs a fixed list against public things only: Solana devnet at the PUBLIC program ids, GitHub's
published keys, the public upgrade feed, the public record (`docs/provenance.json`, `docs/capabilities.json`, the
statement the site publishes and its evidence) and one public pull request. It reads; it sends no transaction. Each check ends `pass`, `fail` or `skipped` (it could not be asked from
there); only `pass` counts for anything.

| check | what it does | what a pass proves | capabilities |
|---|---|---|---|
| `payment` | Reads one named payment from devnet (the `order_pay` transaction of capabilities.json), takes the signed token out of the transactions that carried it, and verifies it again on your machine: the RS256 signature against the key the chain holds (at an address only that key derives) and against the key GitHub publishes under the same id while GitHub still publishes it; that the token's audience names this order and these payees; that the terms the order logged when it was funded hash to the terms hash in the audience. | A work order on devnet paid the accounts a GitHub-signed run named, under terms fixed before the work. You checked the signatures; nobody told you. | `order_pay` |
| `programs` | Hashes the bytes devnet runs at each pinned program id, reads the upgrade multisig and its proposals from the chain, and holds both against the [upgrade feed](https://drexthealpha.github.io/Knos/upgrades.json) the release names. A pending upgrade passes when the buffer waiting on chain hashes to the build the feed names and the chain gives its execution time; an executed one when the program runs that build. | The programs are upgradeable only through a multisig with a public 48-hour delay, and what is announced is what is waiting or running. The live state is the feed, so this holds before and after an upgrade executes. | `upgrade_delay`, `upgrade_feed` |
| `simulator` | From a source checkout only: runs `tests/test_double_pay.py` and the random state machine `tests/test_invariants_machine.py` at its default budget on the local simulator. | No token pays twice and the stated money invariants hold over random sequences, on the committed program builds. | `single_use_tokens`, `invariants_state_machine` |
| `claim` | Runs `knos check` on one named, merged public pull request (SciML/SciMLBase.jl#1574) and compares the verdict with the one recorded in [agent_pr_ci.json](agent_pr_ci.json). | The free claim check gives the recorded answer from GitHub's own record: the description says tests pass, and a check failed at the head commit. | `check` |
| `provenance` | Hashes the bytes devnet runs at each pinned program id and holds each to [provenance.json](provenance.json): the build it read there, or the one this release proposes (`next`). A program that runs a build newer than the record passes only when the upgrade feed names that build. | The deployed programs are the builds the record ties to a commit and a verified-build run ([PROVENANCE.md](PROVENANCE.md)). | `provenance_chain` |
| `payments` | Takes up to three payments [capabilities.json](capabilities.json) records at the PUBLIC program ids (`order_pay`, then `order_quorum` and `x402_knos_order`) and verifies each as `payment` does: the transaction, the token inside it, GitHub's signature, the audience, the terms hash. Skipped, and said, while the manifest records none: it records none today. | The payments Knos says it made at the public ids were made on a GitHub-signed token for that order. | `order_pay` |
| `statement` | Fetches the [statement the site publishes](https://drexthealpha.github.io/Knos/statement_sample.json) and makes it again from its evidence (`knos statement verify` does the same). The site's statement names its evidence by sha256 and does not carry it, so the evidence is taken from the same statement as the repository keeps it (`tests/data/statement/sept.json`), which is made again too. | The published statement is what its evidence gives: every line, total and hash. It is a sample: its buyer and supplier are made up. | `statements` |
| `own_repo` | Only with `--own-repo OWNER/NAME` and `GH_TOKEN`: one funded round in a repository of yours that has Knos installed ([INSTALL.md](INSTALL.md)): an issue funded by comment from the faucet Balance, a pull request, the merge, the payment. It opens and merges a pull request there, so it never runs unasked. | The whole flow works for someone who is not the maintainer, on test USDC. | `fund_by_comment`, `pay_on_merge` |

The payment in `payment` was made by the 0.3.14 release rehearsal on its own devnet deployment of the 2.1 build, which
CAPABILITIES.md names ("The 0.3.14 rehearsal on devnet"); the pinned program ids run what the feed says they run. From an installed wheel `simulator`
is skipped. To run it: clone the repository, `pip install -e '.[dev]'`, then `python -m knos reproduce --only simulator`.

`--only` takes a check's name or a capability id, `--rpc` another Solana RPC, `--out` where the report goes. The
report records the knos version, the platform, the Python version and, from a checkout, the commit.

## Why a report can be merged without trust

A report typed into a pull request proves nothing. So the workflow asks GitHub for a signed statement (an OIDC token)
whose audience is `knos-repro:<sha256 of report.json>`. GitHub puts into that token the repository, its owner, the
account that started the run and the run's id, and signs it. The job that asks for the token installs nothing and
runs no Knos code: it checks the report's sha256 and asks for that one audience.

The file in the artifact, `<owner>-<repo>-<run id>.json`, is the report and the token. When it arrives in a pull
request, [`reproductions.yml`](../.github/workflows/reproductions.yml) checks, running nothing from the pull request:

- the token carries GitHub's signature;
- its audience is the sha256 of the report in the file, so a report edited after signing is refused;
- the repository's owner and the account that started the run are not `drexthealpha` and not in
  [`scripts/own_github_ids.json`](../scripts/own_github_ids.json);
- no check failed, at least one passed, and the pull request adds that file and nothing else.

After that, `python scripts/capabilities.py check` verifies every file in `reproductions/` offline on every run,
against GitHub's keys archived in `scripts/github_oidc_keys.json`; `check --rpc` also asks GitHub for its keys. A
capability is `reproduced` only when it names such a file and a check that supports it passed there.

What this does not prove, said plainly: that your account is independent of Knos (only the listed own accounts are
refused), and that you ran the example unchanged (the token names your workflow file and its commit, which anyone can
read in your repository). A job definition signed by GitHub as unchanged needs a published reusable workflow; that is
not built.

## How to send it

From a fork there is nothing to do by hand: the second run prepared the pull request, and its page holds the link.

From any other repository: open a pull request to drexthealpha/Knos that adds the file as
`reproductions/<owner>-<repo>-<run id>.json` and nothing else. The run's page prints the text to use; the template is
[`reproduction.md`](../.github/PULL_REQUEST_TEMPLATE/reproduction.md) (append `?template=reproduction.md` to the
pull request's URL).

Either way the result of the check is on the pull request's checks, with its reasons on the run's page; a pull request
from a fork is given a read-only token, so it is not a comment.

A check that failed is a bug, not a reproduction: open an issue and attach `report.json`; the second run says so in
place of the link. The last question in the pull request's text, what was awkward or broken on the way, is the part
nobody inside can answer.

## How long it takes

Measured on 5 October 2026 (two runs of `payment` and `programs`, one of `simulator`) against the public devnet RPC, from a Linux machine with 2 shared CPUs:

| check | time |
|---|---|
| `payment` | 3.5 s and 5.0 s |
| `programs` | 4.7 s and 7.8 s |
| `simulator` (source checkout, 8 tests) | 11.8 s |
| `provenance`, `payments`, `statement` | not measured: new in this release, and no cluster could be reached from where they were written |
| `claim` | not measured: GitHub's API could not be reached from where this was written |
| `own_repo` | not measured |
| the whole workflow in a fork | not measured: nobody has run it yet |

The public RPC throttles; a check that could not be asked says so and ends `skipped`. Run it again, or give `--rpc`.
