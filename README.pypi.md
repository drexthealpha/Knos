<!-- Written by scripts/bump_version.py from README.md, with links pinned to the tag: edit README.md. -->
<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/drexthealpha/Knos/v0.3.25/web/brand/wordmark-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/drexthealpha/Knos/v0.3.25/web/brand/wordmark-light.svg">
    <img alt="Knos" src="https://raw.githubusercontent.com/drexthealpha/Knos/v0.3.25/web/brand/wordmark-light.svg" height="84">
  </picture>
</h1>

**The neutral meter for AI agent work: neither side keeps the count.**

Both sides close invoices on evidence both verify.

Of 241 merged agent pull requests claiming passing tests, 9 failed a test, build, lint or type check.

[Check](https://drexthealpha.github.io/Knos/) · [Judges](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/JUDGES.md)

## The claim

Two parties who distrust each other compute the same bill from evidence a third party signed.
The program releases the money on that signature, with no company and no oracle in the middle.

Limits, in one line: Solana devnet, test USDC, no outside users yet ([docs/DISCLOSURE.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/DISCLOSURE.md)).

## The meter: two ledgers, one bill

1. Buyer and supplier each keep their own ledger of the evaluations GitHub signed.
2. Each runs `knos meter reconcile` on its own copy and rebuilds the same statement, line for line.
3. A line's policy is met, or it is disputed, duplicate or without enough evidence; only a line whose policy is met is billed. Each line then shows its four steps: policy satisfied, parties accepted, payment authorised, settled ([docs/METER.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/METER.md)).

## The money: released on a signature

1. The buyer fixes the work, the budget and the acceptance terms before it starts; the terms are hashed into the order.
2. GitHub signs the workflow run that judged the work, and a Solana program checks that signature itself before it pays, in test USDC. The smallest example is a bounty: a maintainer comments `/knos fund 20 checks: test`, and a merge with `test` passing pays the author.
3. Why Solana: Money is released with no custodian, and the count is anchored where neither side can alter it. A receipt verifies with no chain.

## The number

Of 241 merged agent pull requests that claimed passing tests, 9 had a failed test, build, lint or type-check job at the head commit (3.7%, 95% interval 2.0% to 6.9%; [docs/backtest.json](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/backtest.json)); 19 had a failed check of any kind (7.9%).
The scan recorded 16 and 30; 11 of the 30 were excluded on a second reading: not merged into the default branch, or the failure or the claim did not hold ([docs/index_review.json](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/index_review.json), method [version 1](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/INDEX_METHOD.md), counted by `scripts/backtest.py`).
The second number: 17.8% of first such pull requests, 147 of 826 repositories ([docs/BENCH.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/BENCH.md)). A failed check is GitHub's record, not a judgment of why it failed.

## For a judge

Start at [the release manifest](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/MANIFEST.md): source, build hash, deployed version, transactions, fee schedule.
The witnessed transaction (9 Oct, Knos 0.3.23, own repository, test USDC, one step fixed by hand): [funded](https://explorer.solana.com/tx/3UaY22WKexigMpkVhibfeMdNgBiyybWm2Z4LuLskKGbNUDXV34yYWyH42atxFjELbrqSgoVs6TwpFzSQwhfXqzgM?cluster=devnet) · [wrong work refused](https://github.com/drexthealpha/knos-witness/actions/runs/37890511112/job/113690226126) · [paid](https://explorer.solana.com/tx/2PtmKUrQHKPARZE4nr35Te559NGQSG7tSHUfwzcKCAjL7gzvQ76fNTVLMWvq8mcZLxd27tbyTe31mCk2PxEGfAqa?cluster=devnet) · [replay paid nothing more](https://github.com/drexthealpha/knos-witness/pull/10#issuecomment-6075196710) · [the record](https://github.com/drexthealpha/knos-witness/blob/acaa854d241c2e030f521b6f5603c8f43c93bab6/witness.json).
Everything else is one click from [docs/JUDGES.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/JUDGES.md).

## What is real today

<!-- bench:today -->
| What | Today | Read from |
|---|---|---|
| This copy | Release 0.3.25, October 2026. A copy naming an older release, or another product, is out of date | [CHANGELOG.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/CHANGELOG.md); the newest: [PyPI](https://pypi.org/project/knos/) |
| Reproduced by someone else | 0 of 260 | [docs/CAPABILITIES.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/CAPABILITIES.md), the rows "reproduced by someone else" |
| Exercised at the public devnet program ids | 26 of 260: GitHub token verification, funding by one comment, funding from a wallet, pay on merge, refund at the deadline, pause, work orders, an order paying up to four payees, orders judged by hidden tests, auto-accepted orders, a holdback released after its warranty, top-ups, single-use tokens, one counted evaluation, a counted batch of evaluations, the seller's own count, a payee's passkey wallet, a passkey funder, the passkey relay, the site's Buy page, an x402 order, the upgrade gate, strict JSON in the verifier, an outcome that is not code, ES256 tokens in one transaction, the presentation grace | [docs/CAPABILITIES.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/CAPABILITIES.md), the rows "exercised on devnet" |
| Deployed at the public devnet program ids, no transaction recorded | 3 of 260: GitLab token verification, the key guardian, holding pay for a payee with no wallet | [docs/CAPABILITIES.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/CAPABILITIES.md), the rows "deployed on devnet" |
| Tested here only | 228 of 260, each with the test its row names | [docs/CAPABILITIES.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/CAPABILITIES.md), the rows "tested locally" |
| Written, not tested | 3 of 260 | [docs/CAPABILITIES.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/CAPABILITIES.md), the rows "implemented" |
| Outside funders | 0 | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/submission/NUMBERS.md), row 1 |
| Outside repositories | 0 | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/submission/NUMBERS.md), row 2 |
| Outside payees | 1, on tasks Knos funded itself | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/submission/NUMBERS.md), row 3 |
| Payments between unrelated accounts | 3, on tasks Knos funded itself | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/submission/NUMBERS.md), row 4 |
| Buyer interviews held | 0 | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/submission/NUMBERS.md), row 5 |
| Letters of intent | 0 | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/submission/NUMBERS.md), row 6 |
| Reproductions signed by GitHub | 0 | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/submission/NUMBERS.md), row 7 |
| Outside programs reading the verifier | 0 | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/submission/NUMBERS.md), row 8 |
| Shadow counts published | 0 | [docs/submission/NUMBERS.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/submission/NUMBERS.md), row 9 |
| Paying customers | 0 | [docs/DISCLOSURE.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/DISCLOSURE.md) |
| Revenue | 0; test USDC is not money | [docs/MARKET.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/MARKET.md) |
| Outside security review | none | [docs/ASSURANCE.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/ASSURANCE.md) |
| Key holders | one person holds every key; an upgrade waits 48 hours in public | [docs/GOVERNANCE.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/GOVERNANCE.md) |
| Network and money | Solana devnet, test USDC; mainnet is not touched | [docs/SECURITY.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/SECURITY.md) |
<!-- /bench:today -->

## Read more

`uvx knos shadow invoice.csv`: the same check from a terminal, on an invoice of your own.
[docs/STORY.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/STORY.md): one task in seven steps, each with its evidence.
[docs/MANIFEST.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/MANIFEST.md): this release on one page: source, the build live at each public program id, every capability's stage, the limits.
[docs/README.md](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/README.md): every document, under six questions.

---

Contact: open an issue; report a vulnerability privately (SECURITY.md).

Below: records that scripts write from their sources, and the licence. Nothing below is typed by hand.

<!-- programs:start -->
| program | address | on devnet, as [`docs/capabilities.json`](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/capabilities.json) records it |
|---|---|---|
| `knos-oidc`, the verifier | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` | runs `2.2` |
| `knos-pay`, the escrow | `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k` | runs `2.2` |
| `knos-meter`, the count | `FUMKkcE95x2kZUj1zZTCbgcYBmJ3WXPHL8pyA8J6anX` | runs `1.1` |
| `knos-passkey`, a wallet from a passkey | `FQPX9i5kQxLYKZyyPgM2fVK9am3w1LSk1Cuoer1sSY85` | runs `1.1` |
<!-- programs:end -->

This page names no time for an upgrade, so that it is true before and after one. Whether a proposal is pending, has
executed or was withdrawn is read from the chain by `knos status`, the site's banner and the site's
[upgrade record](https://drexthealpha.github.io/Knos/upgrades.json) ([`web/upgrades.json`](https://github.com/drexthealpha/Knos/blob/v0.3.25/web/upgrades.json) is the
committed copy). The first deployment ([`programs`](https://github.com/drexthealpha/Knos/tree/v0.3.25/programs)) has no upgrade authority and stays as a record; nothing
new is funded there.

<!-- capabilities:start -->
**Reproduced by someone else:** none recorded yet. **Exercised on devnet:** `verify_github`, `fund_by_comment`, `fund_from_wallet`, `pay_on_merge`, `refund`, `pause`, `work_orders`, `order_pay`, `tests_mode`, `order_auto_accept`, `holdback_release`, `top_up`, `single_use_tokens`, `meter_single`, `meter_batch`, `meter_seller_claim`, `passkey_payee_wallet`, `passkey_funder`, `passkey_fund_relay`, `buyer_page`, `x402_knos_order`, `upgrade_gate`, `oidc_strict_json`, `outcome_not_code`, `es256_tokens`, `presentation_grace`. **Deployed on devnet:** `verify_gitlab`, `key_guardian`, `hold_and_bind`. Everything else is tested locally, implemented or not built: [the table with the evidence](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/CAPABILITIES.md) has one row for each capability, from [`docs/capabilities.json`](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/capabilities.json). Deployed and exercised are counted only at the public program ids; what the 0.3.14 rehearsal ran at staging addresses of its own is in the note of each capability it ran, with its transaction.
<!-- capabilities:end -->

MIT, all of it. Built by drexthealpha. Its memory engine is [Sibyl](https://sibyllabs.org).
<!-- mcp-name: io.github.drexthealpha/knos -->
