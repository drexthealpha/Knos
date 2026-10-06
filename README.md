<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="web/brand/wordmark-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="web/brand/wordmark-light.svg">
    <img alt="Knos" src="web/brand/wordmark-light.svg" height="84">
  </picture>
</h1>

**The neutral meter for AI agent work: neither side keeps the count.**

Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check.

Check your own invoice: [drexthealpha.github.io/Knos](https://drexthealpha.github.io/Knos/)

`pip install knos && knos shadow invoice.csv`

## The number

241 merged pull requests by AI coding agents said tests or CI pass; 30 had a failed check at the head commit ([docs/backtest.json](docs/backtest.json), counted by `scripts/backtest.py`).
The second number: 17.8% of first such pull requests, 147 of 826 repositories ([docs/BENCH.md](docs/BENCH.md)). A failed check is GitHub's record, not a judgment of why it failed.

## One comment

1. A maintainer comments on an issue: `/knos fund 20 checks: test`. The terms are hashed into the order.
2. Someone opens a pull request and she merges it. Had `test` failed at that commit, the merge would pay nothing.
3. GitHub signs the workflow run, a Solana program checks that signature, and the author is paid in test USDC.

## Two ledgers

1. Buyer and supplier each keep their own ledger of the signed evaluations.
2. Each runs `knos meter reconcile` on its own copy and rebuilds the same statement.
3. A line is agreed, disputed, duplicate or insufficient evidence, and only an agreed line is billed ([docs/METER.md](docs/METER.md)).

## What is real today

<!-- bench:today -->
| What | Today | Read from |
|---|---|---|
| Runs on the public devnet program ids | token verification; a bounty funded by one comment, paid on merge, refunded at its deadline; one counted evaluation; a payee's passkey wallet | [docs/CAPABILITIES.md](docs/CAPABILITIES.md), the rows above "tested locally" |
| Tested here only | work orders, the ledger and its statements, the invoice check, the console, the exports, and every other capability | [docs/CAPABILITIES.md](docs/CAPABILITIES.md), the rows "tested locally" |
| Outside funders | 0 | [docs/submission/NUMBERS.md](docs/submission/NUMBERS.md), row 1 |
| Outside repositories | 0 | [docs/submission/NUMBERS.md](docs/submission/NUMBERS.md), row 2 |
| Outside payees | 1, on tasks Knos funded itself | [docs/submission/NUMBERS.md](docs/submission/NUMBERS.md), row 3 |
| Payments between unrelated accounts | 3, on tasks Knos funded itself | [docs/submission/NUMBERS.md](docs/submission/NUMBERS.md), row 4 |
| Buyer interviews held | 0 | [docs/submission/NUMBERS.md](docs/submission/NUMBERS.md), row 5 |
| Letters of intent | 0 | [docs/submission/NUMBERS.md](docs/submission/NUMBERS.md), row 6 |
| Reproductions signed by GitHub | 0 | [docs/submission/NUMBERS.md](docs/submission/NUMBERS.md), row 7 |
| Outside programs reading the verifier | 0 | [docs/submission/NUMBERS.md](docs/submission/NUMBERS.md), row 8 |
| Shadow counts published | 0 | [docs/submission/NUMBERS.md](docs/submission/NUMBERS.md), row 9 |
| Paying customers | 0 | [docs/DISCLOSURE.md](docs/DISCLOSURE.md) |
| Revenue | 0; test USDC is not money | [docs/MARKET.md](docs/MARKET.md) |
| Outside security review | none | [docs/ASSURANCE.md](docs/ASSURANCE.md) |
| Key holders | one person holds every key; an upgrade waits 48 hours in public | [docs/GOVERNANCE.md](docs/GOVERNANCE.md) |
| Network and money | Solana devnet, test USDC; mainnet is not touched | [docs/SECURITY.md](docs/SECURITY.md) |
<!-- /bench:today -->

## Read more

[docs/README.md](docs/README.md): every document, under six questions.

---

Below this line: records that scripts write from their sources, and the licence. Nothing here is typed by hand.

<!-- programs:start -->
| program | address | on devnet, as [`docs/capabilities.json`](docs/capabilities.json) records it |
|---|---|---|
| `knos-oidc`, the verifier | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` | runs `2.0` until its upgrade proposal has executed; `2.1` was proposed through the multisig and runs at this address only once that proposal has executed (the live state is in [`web/upgrades.json`](web/upgrades.json)); the 0.3.14 rehearsal ran it at a staging address of its own ([docs/CAPABILITIES.md](docs/CAPABILITIES.md)) |
| `knos-pay`, the escrow | `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k` | runs `2.0` until its upgrade proposal has executed; `2.1` was proposed through the multisig and runs at this address only once that proposal has executed (the live state is in [`web/upgrades.json`](web/upgrades.json)); the 0.3.14 rehearsal ran it at a staging address of its own ([docs/CAPABILITIES.md](docs/CAPABILITIES.md)) |
| `knos-meter`, the count | `FUMKkcE95x2kZUj1zZTCbgcYBmJ3WXPHL8pyA8J6anX` | runs `1.0` until its upgrade proposal has executed; `1.1` was proposed through the multisig and runs at this address only once that proposal has executed (the live state is in [`web/upgrades.json`](web/upgrades.json)); the 0.3.14 rehearsal ran it at a staging address of its own ([docs/CAPABILITIES.md](docs/CAPABILITIES.md)) |
| `knos-passkey`, a wallet from a passkey | `FQPX9i5kQxLYKZyyPgM2fVK9am3w1LSk1Cuoer1sSY85` | runs `1.0` until its upgrade proposal has executed; `1.1` was proposed through the multisig and runs at this address only once that proposal has executed (the live state is in [`web/upgrades.json`](web/upgrades.json)); the 0.3.14 rehearsal ran it at a staging address of its own ([docs/CAPABILITIES.md](docs/CAPABILITIES.md)) |
<!-- programs:end -->

This page names no time for an upgrade, so that it is true before and after one. Whether a proposal is pending, has
executed or was withdrawn is read from the chain by `knos status`, the site's banner and the site's
[upgrade record](https://drexthealpha.github.io/Knos/upgrades.json) ([`web/upgrades.json`](web/upgrades.json) is the
committed copy). The first deployment ([`programs`](programs)) has no upgrade authority and stays as a record; nothing
new is funded there.

<!-- capabilities:start -->
**Reproduced by someone else:** none recorded yet. **Exercised on devnet:** none recorded yet. **Deployed on devnet:** `verify_github`, `verify_gitlab`, `key_guardian`, `fund_by_comment`, `fund_from_wallet`, `pay_on_merge`, `hold_and_bind`, `refund`, `pause`, `meter_single`, `passkey_payee_wallet`, `upgrade_gate`. Everything else is tested locally, implemented or not built: [the table with the evidence](docs/CAPABILITIES.md) has one row for each capability, from [`docs/capabilities.json`](docs/capabilities.json). Deployed and exercised are counted only at the public program ids; what the 0.3.14 rehearsal ran at staging addresses of its own is in the note of each capability it ran, with its transaction.
<!-- capabilities:end -->

MIT, all of it. Built by drexthealpha. Its memory engine is [Sibyl](https://sibyllabs.org).
<!-- mcp-name: io.github.drexthealpha/knos -->
