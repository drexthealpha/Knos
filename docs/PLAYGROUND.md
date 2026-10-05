# The playground

One public repository, [drexthealpha/knos-playground](https://github.com/drexthealpha/knos-playground), where a GitHub
account and nothing else is enough to try both sides of Knos. No wallet, nothing installed, nothing spent.

**Nobody outside has used it yet.** The numbers at the end of this page are the count, whatever they are.

## What a stranger does

**Fund a test task.** [Open the issue](https://github.com/drexthealpha/knos-playground/issues/new?template=fund-a-test-task.md)
and press **Submit new issue**. The template's text ends with the line `/knos fund 5 checks: none auto`. The workflow
reads that line as the issue is opened, GitHub signs that your account wrote it, and 5 test USDC go into an escrow on
Solana devnet for that issue. Knos answers in a comment.

The task is paid without a merge (`auto`), and an escrow holds such an order only from `knos_pay` 2.1 on. While devnet
runs an older build (`knos status`; the site's `upgrades.json`), the workflow funds nothing and says so in its comment:
that is what [issue 1](https://github.com/drexthealpha/knos-playground/issues/1) got on 2026-10-05.

**Take one.** Pick an [open issue](https://github.com/drexthealpha/knos-playground/issues), edit
[`words.py`](https://github.com/drexthealpha/knos-playground/edit/main/words.py) in the browser so that it prints the
words of a line in reverse order, and open the pull request with `Closes #<the issue's number>` in its description.
The checks in `.knos/acceptance/<number>/` run your file as a separate process on 21 recorded lines and compare what it
prints. When every answer matches, GitHub signs that it did and the escrow pays your account: to the wallet you bound
(`/knos address <address>`; the site's passkey wallet works), or held for your account for up to 180 days until you bind one.
Nobody merges, and no maintainer decides whether the work is good.

## What is test money

All of it. The devnet faucet mints the test USDC for each funding into a balance nobody can withdraw from
([`FaucetOpen`](../programs-v2/knos_pay/src/lib.rs)). It is worth nothing, and Knos earns nothing from it. The task is the same
every time and its cases are public, so a payment here shows that the mechanism ran, not that work was bought.

## The limits

| What | Limit | Who holds it |
|---|---|---|
| One funding | at most 100 test USDC | the program (`FAUCET_CAP`) |
| The whole repository | one faucet funding a minute | the program (`FUND_PERIOD`, error 90) |
| One playground task | 5 test USDC, funded only as the issue is opened, once | the workflow ([`playground.py`](../src/knos/playground.py)) |
| One account | 3 funded issues in a day (UTC) | the workflow, from GitHub's list of that account's issues |
| Issues with checks | numbers 1 to 200 | the repository; a release adds more |
| A first pull request from an account new to GitHub | waits for a maintainer to let its check run | GitHub (the least its approval setting allows) |

The program has no limit per account: that one is the workflow's, and the escrow takes a funding only from the
workflow at the commit it pins. Anywhere but the playground, `/knos fund` is for someone who can write to the repository.

## How it is counted

Three numbers, never added to each other, in [`outsiders.json`](https://drexthealpha.github.io/Knos/outsiders.json) and
in `stats.json` under `outsiders` ([`scripts/outsiders.py`](../scripts/outsiders.py)):

- **Outside funders**: accounts and wallets that are not Knos's and funded a task. A stranger who funds in the
  playground is one, shown apart as "outside funder, Knos repository, faucet money": the repository and the money are
  Knos's, and only the click was theirs.
- **Outside repositories**: repositories that are not Knos's in which an outside funder funded. The playground is
  never one.
- **Outside payees**: accounts that are not Knos's and were paid by a task somebody else funded. Solving your own
  task does not count.

What is Knos's is listed in [`scripts/own_github_ids.json`](../scripts/own_github_ids.json).
