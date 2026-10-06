# The story: one round, eight steps

**The neutral meter for AI agent work: neither side keeps the count.**

Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check.

The count is in [backtest.json](backtest.json), made by `scripts/backtest.py` from the pull requests listed in
[agent_pr_ci.json](agent_pr_ci.json). A failed check is GitHub's record, not a judgment of why it failed.

## The round

Each step has one piece of evidence: a transaction, a test or a document. The site plays the same eight
([`web/story.js`](../web/story.js)).

1. **Buyer authorises.** One comment fixes the budget and terms before work starts.
   Evidence: [The funding transaction (devnet, staging program ids)](https://explorer.solana.com/tx/4zeX8845JQkkBgqvRqUgAYiMPNaSWQJsxDTGyayyKATQ1ZXeDTJDpuTrMzkCd4pT1E9rrbYHw6Z4vWRnb1FKhYCL?cluster=devnet)
2. **Supplier submits.** A correct fix arrives with its own regression test.
   Evidence: [The correct submissions and the test that runs them](../tests/test_tamper_bench.py)
3. **Accepted under the original terms.** The signed run pays the posted amount.
   Evidence: [The paying transaction (devnet, staging program ids)](https://explorer.solana.com/tx/63wT5rhYhEKbgmF5k8vEKdexzoCaXZCiDvRG2GQMGSMBBsc9avGfDw3izER9D6LHoe4ucJeinTBiWaWGWpnFWvfq?cluster=devnet)
4. **A tampered submission fails.** All 63 cheating pull requests were refused.
   Evidence: [The tamper benchmark](TAMPER.md)
5. **A duplicate settlement changes nothing.** The second try moves no money.
   Evidence: [The test that sends every accepted proof twice](../tests/test_double_pay.py)
6. **Both sides rebuild the same record.** Each ledger gives the same statement.
   Evidence: [The test that reconciles two ledgers](../tests/test_ledger.py)
7. **Finance approves the agreed lines.** The exception stays visible and unbilled.
   Evidence: [The four records and the exports](FINANCE.md)
8. **Your invoice next.** Paste it. Nobody has paid for this yet.
   Evidence: [Check your own invoice](https://drexthealpha.github.io/Knos/)

Steps 1 and 3 ran on the staging program ids of the 0.3.14 rehearsal ([CAPABILITIES.md](CAPABILITIES.md), "The
0.3.14 rehearsal on devnet"). Which builds the public program ids run is in
[`web/upgrades.json`](../web/upgrades.json). The money is test USDC.

## The ask

1. Needed: an outside key holder for both multisigs. Nobody has been asked.
2. Needed: first buyers to run a shadow count. None has run.
3. Needed: an outside review of the programs. None is commissioned.

What each would do is in [GOVERNANCE.md](GOVERNANCE.md), [PILOT.md](PILOT.md) and [ASSURANCE.md](ASSURANCE.md).

## Limits

[SECURITY.md](SECURITY.md) has all of them. The ones to know first:

- Devnet, test USDC, no outside review. `knos mainnet-check` fails on that line on purpose.
- A signature authenticates a statement, not the truth. GitHub signs which workflow ran, at which commit, in which repository. It does not sign what the workflow read.
- The seller's own settlement covers public repositories only.
- A passed check is not good work. An order buys what its terms say, and the funder chose the terms.
- Knos inherits GitHub's failures. If GitHub signs something false or is down, the programs believe it or wait.
- The payout is USDC on Solana. No card, no bank transfer, no bank payout.

Every other document: [README.md](README.md).
