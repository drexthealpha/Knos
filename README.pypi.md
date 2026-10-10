<!-- Written by scripts/bump_version.py from README.md, with links pinned to the tag: edit README.md. -->
<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/drexthealpha/Knos/v0.3.26/web/brand/wordmark-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/drexthealpha/Knos/v0.3.26/web/brand/wordmark-light.svg">
    <img alt="Knos" src="https://raw.githubusercontent.com/drexthealpha/Knos/v0.3.26/web/brand/wordmark-light.svg" height="84">
  </picture>
</h1>

**The neutral meter for AI agent work: neither side keeps the count.**

Pay AI agents only when your checks pass.

Of 241 merged agent pull requests claiming passing tests, 9 failed a test, build, lint or type check.

[Check](https://drexthealpha.github.io/Knos/) · [Judges](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/JUDGES.md)

## How it works

![You set the rules first. The money moves only when the work passes them.](https://raw.githubusercontent.com/drexthealpha/Knos/v0.3.26/docs/diagrams/readme-1.svg)

*You set the rules first. The money moves only when the work passes them.*

1. One comment on an issue (a task's page on GitHub) posts the task, your checks and the pay: `/knos fund 20 checks: test`.
2. An [AI agent](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#ai-agent) or a person sends the work as a [pull request](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#pull-request).
3. When the [checks](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#checks-ci) pass and you [merge](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#merge) the work, a program pays the worker.

## Try it in ten seconds

Open [the check](https://drexthealpha.github.io/Knos/#check) in your browser.
Paste the link to an AI agent's pull request.
It tells you whether the agent's checks really passed.
No pull request at hand? Press **Try a sample** to check a made-up invoice.
There is nothing to install, no sign-up, and nothing is sent to Knos.

## Why nobody can fudge the count

![GitHub signs which workflow ran, on which commit. Both sides rebuild the same bill, and a program pays.](https://raw.githubusercontent.com/drexthealpha/Knos/v0.3.26/docs/diagrams/readme-2.svg)

*GitHub signs which workflow ran, on which commit. Both sides rebuild the same bill, and a program pays.*

GitHub (where your code lives) [signs](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#signed) a [token](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#token-oidc) for each run of your checks.
The token proves which workflow ran, on which commit. Nobody else can make it.
A workflow is the script that runs your checks. A commit is one saved version of the code.
You and the other side each keep a copy of those signed runs.
Each side rebuilds the bill from its own copy, with `knos meter reconcile`.
The two bills match line for line, so neither side can change the count alone.
The money waits in a program on [Solana](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#solana), not with Knos. That program checks GitHub's signature before it pays.
Today one person can still change that program, after a public wait ([who can change what](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/GOVERNANCE.md)).
Today Knos earns a fee only when the work is accepted. A refund gives the fee back. So the meter is not yet fully neutral ([the plan to fix it](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/CHARTER.md)).
Why Solana: Money is released with no custodian, and the count is anchored where neither side can alter it.
A custodian is a company that holds your money for you.

## Is it real?

It runs on test money only: [test USDC](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#test-usdc) on Solana's practice network, [devnet](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#devnet).
There are no customers yet. Nobody has bought anything ([what is not real yet](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/DISCLOSURE.md)).
One person holds every key today. A change to the programs waits in public first.

<!-- bench:today -->
| What | Today | Read from |
|---|---|---|
| This copy | Release 0.3.26, October 2026. A copy naming an older release, or another product, is out of date | [CHANGELOG.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/CHANGELOG.md); the newest: [PyPI](https://pypi.org/project/knos/) |
| Reproduced by someone else | 0 of 271 | [docs/CAPABILITIES.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/CAPABILITIES.md), the rows "reproduced by someone else" |
| Exercised at the public devnet program ids | 26 of 271: GitHub token verification, funding by one comment, funding from a wallet, pay on merge, refund at the deadline, pause, work orders, an order paying up to four payees, orders judged by the buyer's black-box tests, auto-accepted orders, a holdback released after its warranty, top-ups, single-use tokens, one counted evaluation, a counted batch of evaluations, the seller's own count, a payee's passkey wallet, a passkey funder, the passkey relay, the site's Buy page, an x402 order, the upgrade gate, strict JSON in the verifier, an outcome that is not code, ES256 tokens in one transaction, the presentation grace | [docs/CAPABILITIES.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/CAPABILITIES.md), the rows "exercised on devnet" |
| Deployed at the public devnet program ids, no transaction recorded | 3 of 271: GitLab token verification, the key guardian, holding pay for a payee with no wallet | [docs/CAPABILITIES.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/CAPABILITIES.md), the rows "deployed on devnet" |
| Tested here only | 238 of 271, each with the test its row names | [docs/CAPABILITIES.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/CAPABILITIES.md), the rows "tested locally" |
| Written, not tested | 4 of 271 | [docs/CAPABILITIES.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/CAPABILITIES.md), the rows "implemented" |
| Outside funders | 0 | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/submission/NUMBERS.md), row 1 |
| Outside repositories | 0 | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/submission/NUMBERS.md), row 2 |
| Outside payees | 1, on tasks Knos funded itself | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/submission/NUMBERS.md), row 3 |
| Payments between unrelated accounts | 3, on tasks Knos funded itself | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/submission/NUMBERS.md), row 4 |
| Buyer interviews held | 0 | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/submission/NUMBERS.md), row 5 |
| Letters of intent | 0 | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/submission/NUMBERS.md), row 6 |
| Reproductions signed by GitHub | 0 | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/submission/NUMBERS.md), row 7 |
| Outside programs reading the verifier | 0 | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/submission/NUMBERS.md), row 8 |
| Shadow counts published | 0 | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/submission/NUMBERS.md), row 9 |
| Paying customers | 0 | [docs/DISCLOSURE.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/DISCLOSURE.md) |
| Revenue | 0; test USDC is not money | [docs/MARKET.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/MARKET.md) |
| Outside security review | none | [docs/ASSURANCE.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/ASSURANCE.md) |
| Key holders | one person holds every key; an upgrade waits 48 hours in public | [docs/GOVERNANCE.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/GOVERNANCE.md) |
| Network and money | Solana devnet, test USDC; mainnet is not touched | [docs/SECURITY.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/SECURITY.md) |
<!-- /bench:today -->

## For a judge

Start at [the release manifest](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/MANIFEST.md): the code, the build, what runs on devnet, the payments and the fees.
One run from start to end (9 Oct, Knos 0.3.23, own repository, test USDC, one step fixed by hand): [funded](https://explorer.solana.com/tx/3UaY22WKexigMpkVhibfeMdNgBiyybWm2Z4LuLskKGbNUDXV34yYWyH42atxFjELbrqSgoVs6TwpFzSQwhfXqzgM?cluster=devnet) · [wrong work refused](https://github.com/drexthealpha/knos-witness/actions/runs/37890511112/job/113690226126) · [paid](https://explorer.solana.com/tx/2PtmKUrQHKPARZE4nr35Te559NGQSG7tSHUfwzcKCAjL7gzvQ76fNTVLMWvq8mcZLxd27tbyTe31mCk2PxEGfAqa?cluster=devnet) · [replay paid nothing more](https://github.com/drexthealpha/knos-witness/pull/10#issuecomment-6075196710) · [the record](https://github.com/drexthealpha/knos-witness/blob/acaa854d241c2e030f521b6f5603c8f43c93bab6/witness.json).
Everything else is one click from [docs/JUDGES.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/JUDGES.md).

## The number

Knos read 241 merged pull requests by AI agents whose description said the tests pass. In 9 of them, a test, build, lint or type-check job had failed at the last commit (3.7%, 95% interval 2.0% to 6.9%; [docs/backtest.json](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/backtest.json)). 19 had a failed check of any kind (7.9%).
The first scan counted 16 and 30. A second reading by hand took out 11 of the 30: not merged into the default branch, or the failure or the claim did not hold ([docs/index_review.json](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/index_review.json), method [version 1](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/INDEX_METHOD.md), counted by `scripts/backtest.py`).
The second number: 17.8% of first such pull requests, 147 of 826 repositories ([docs/BENCH.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/BENCH.md)). A failed check is GitHub's record, not a judgment of why it failed.

## Words

Pull request, devnet, multisig and more, each in one plain line: [docs/WORDS.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md).

## Questions

### What is Knos?

Knos is the neutral meter for [AI agent](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#ai-agent) work. Neither side keeps the count.

### How does Knos pay an AI agent?

You post the task, your [checks](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#checks-ci) and the pay before work starts. When the checks pass and you [merge](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#merge), a [program](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#program) pays the agent.

### Does Knos use real money?

No. It runs on [devnet](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#devnet), Solana's practice network, with [test USDC](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#test-usdc) worth nothing.

### What does Knos cost?

Checking is free; paying adds 0.30%, at least 0.05 [test USDC](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#test-usdc). Jobs and tips take it out of the pay instead.

### Who holds the money?

A program on [Solana](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#solana) holds it, not Knos. Today one person can change that program, after a public wait.

### Can the buyer refuse to pay?

Not once the checks pass and the work is merged. Before that, the buyer still chooses whether to merge.

### What is a neutral meter?

A count of work that neither side keeps alone. A program checks GitHub's [signature](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/WORDS.md#signed) of which workflow ran, on which commit.

### How do I try Knos?

Open [the check](https://drexthealpha.github.io/Knos/check/) and paste an AI agent's pull request. It answers within ten seconds, with no sign-up.

## Read more

`uvx knos shadow invoice.csv`: the same check from a terminal, on an invoice of your own.
[docs/STORY.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/STORY.md): one task in seven steps, each with its evidence.
[docs/MANIFEST.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/MANIFEST.md): this release on one page: the code, what runs at each public program id, how far each capability has got, and the limits.
[docs/README.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/README.md): every document, under six questions.

---

Contact: open an issue; report a vulnerability privately (SECURITY.md).

Below: records that scripts write from their sources, and the licence. Nothing below is typed by hand.

<!-- programs:start -->
| program | address | on devnet, as [`docs/capabilities.json`](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/capabilities.json) records it |
|---|---|---|
| `knos-oidc`, the verifier | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` | runs `2.2` |
| `knos-pay`, the escrow | `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k` | runs `2.2` |
| `knos-meter`, the count | `FUMKkcE95x2kZUj1zZTCbgcYBmJ3WXPHL8pyA8J6anX` | runs `1.1` |
| `knos-passkey`, a wallet from a passkey | `FQPX9i5kQxLYKZyyPgM2fVK9am3w1LSk1Cuoer1sSY85` | runs `1.1` |
<!-- programs:end -->

This page names no time for an upgrade, so that it is true before and after one. Whether a proposal is pending, has
executed or was withdrawn is read from the chain by `knos status`, the site's banner and the site's
[upgrade record](https://drexthealpha.github.io/Knos/upgrades.json) ([`web/upgrades.json`](https://github.com/drexthealpha/Knos/blob/v0.3.26/web/upgrades.json) is the
committed copy). The first deployment ([`programs`](https://github.com/drexthealpha/Knos/tree/v0.3.26/programs)) has no upgrade authority and stays as a record; nothing
new is funded there.

<!-- capabilities:start -->
**Reproduced by someone else:** none recorded yet. **Exercised on devnet:** `verify_github`, `fund_by_comment`, `fund_from_wallet`, `pay_on_merge`, `refund`, `pause`, `work_orders`, `order_pay`, `tests_mode`, `order_auto_accept`, `holdback_release`, `top_up`, `single_use_tokens`, `meter_single`, `meter_batch`, `meter_seller_claim`, `passkey_payee_wallet`, `passkey_funder`, `passkey_fund_relay`, `buyer_page`, `x402_knos_order`, `upgrade_gate`, `oidc_strict_json`, `outcome_not_code`, `es256_tokens`, `presentation_grace`. **Deployed on devnet:** `verify_gitlab`, `key_guardian`, `hold_and_bind`. Everything else is tested locally, implemented or not built: [the table with the evidence](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/CAPABILITIES.md) has one row for each capability, from [`docs/capabilities.json`](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/capabilities.json). Deployed and exercised are counted only at the public program ids; what the 0.3.14 rehearsal ran at staging addresses of its own is in the note of each capability it ran, with its transaction.
<!-- capabilities:end -->

MIT, all of it. Built by drexthealpha. Its memory engine is [Sibyl](https://sibyllabs.org).
<!-- mcp-name: io.github.drexthealpha/knos -->
