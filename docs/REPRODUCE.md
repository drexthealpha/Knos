# Reproduce Knos yourself

**Nobody outside has done this yet.** No capability in [capabilities.json](capabilities.json) is `reproduced`, and
[`reproductions/`](../reproductions) is empty. This page is how the first one gets there without anyone taking the
maintainer's word, or yours.

## Three lines

By hand, on any machine with Python 3.10 or later (a report on your screen and in `report.json`; not signed):

```
pipx run --spec knos knos reproduce
```

Signed by GitHub, in a repository of your own (this is the one that counts):

1. Fork [drexthealpha/Knos](https://github.com/drexthealpha/Knos) and enable Actions in the fork, or copy
   [`examples/knos-reproduce.yml`](../examples/knos-reproduce.yml) to `.github/workflows/` of any repository of yours.
2. Actions > **knos reproduce** > **Run workflow**.
3. Download the run's artifact `knos-reproduction` and send the file in it (below).

It needs no secret, no wallet and no money, and it writes nothing to your repository.

## What each check proves

`knos reproduce` runs a fixed list against public things only: Solana devnet, GitHub's published keys, the public
upgrade feed, and one public pull request. Each check ends `pass`, `fail` or `skipped` (it could not be asked from
there); only `pass` counts for anything.

| check | what it does | what a pass proves | capabilities |
|---|---|---|---|
| `payment` | Reads one named payment from devnet (the `order_pay` transaction of capabilities.json), takes the signed token out of the transactions that carried it, and verifies it again on your machine: the RS256 signature against the key the chain holds (at an address only that key derives) and against the key GitHub publishes under the same id while GitHub still publishes it; that the token's audience names this order and these payees; that the terms the order logged when it was funded hash to the terms hash in the audience. | A work order on devnet paid the accounts a GitHub-signed run named, under terms fixed before the work. You checked the signatures; nobody told you. | `order_pay` |
| `programs` | Hashes the bytes devnet runs at each pinned program id, reads the upgrade multisig and its proposals from the chain, and holds both against the [upgrade feed](https://drexthealpha.github.io/Knos/upgrades.json) the release names. A pending upgrade passes when the buffer waiting on chain hashes to the build the feed names and the chain gives its execution time; an executed one when the program runs that build. | The programs are upgradeable only through a multisig with a public 48-hour delay, and what is announced is what is waiting or running. The live state is the feed, so this holds before and after an upgrade executes. | `upgrade_delay`, `upgrade_feed` |
| `simulator` | From a source checkout only: runs `tests/test_double_pay.py` and the random state machine `tests/test_invariants_machine.py` at its default budget on the local simulator. | No token pays twice and the stated money invariants hold over random sequences, on the committed program builds. | `single_use_tokens`, `invariants_state_machine` |
| `claim` | Runs `knos check` on one named, merged public pull request (SciML/SciMLBase.jl#1574) and compares the verdict with the one recorded in [agent_pr_ci.json](agent_pr_ci.json). | The free claim check gives the recorded answer from GitHub's own record: the description says tests pass, and a check failed at the head commit. | `check` |
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

Open a pull request to drexthealpha/Knos that adds the file as `reproductions/<owner>-<repo>-<run id>.json` and
nothing else. The run's page prints the text to use; the template is
[`reproduction.md`](../.github/PULL_REQUEST_TEMPLATE/reproduction.md) (append `?template=reproduction.md` to the
pull request's URL). The result of the check is on the pull request's checks, with its reasons on the run's page; a
pull request from a fork is given a read-only token, so it is not a comment.

A check that failed is a bug, not a reproduction: open an issue and attach `report.json`. The last question in the
template, what was awkward or broken on the way, is the part nobody inside can answer.

## How long it takes

Measured on 5 October 2026 (two runs of `payment` and `programs`, one of `simulator`) against the public devnet RPC, from a Linux machine with 2 shared CPUs:

| check | time |
|---|---|
| `payment` | 3.5 s and 5.0 s |
| `programs` | 4.7 s and 7.8 s |
| `simulator` (source checkout, 8 tests) | 11.8 s |
| `claim` | not measured: GitHub's API could not be reached from where this was written |
| `own_repo` | not measured |
| the whole workflow in a fork | not measured: nobody has run it yet |

The public RPC throttles; a check that could not be asked says so and ends `skipped`. Run it again, or give `--rpc`.
