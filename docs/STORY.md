# The story: three minutes, six beats

**The neutral meter for AI agent work: neither side keeps the count.**

Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check.

The count is in [backtest.json](backtest.json), made by `scripts/backtest.py` from the pull requests listed in
[agent_pr_ci.json](agent_pr_ci.json). A failed check is GitHub's record, not a judgment of why it failed.

The claim: two parties who distrust each other compute the same bill from evidence a third party signed, and the
program releases the money on that signature, with no company and no oracle in the middle.

## The six beats

Each beat has one piece of evidence: a file, a test or a transaction. The site plays the same six
([`web/story.js`](../web/story.js)), and [the demonstration's script](submission/demo_script.md) times them.

1. **An invoice does not reconcile.** Seven lines; five are exceptions.
   Evidence: [The sample invoice](../examples/shadow/invoice.csv)
2. **Buyer authorises the deliverable.** One comment fixes price and terms first.
   Evidence: [The funding transaction (devnet, staging program ids)](https://explorer.solana.com/tx/4zeX8845JQkkBgqvRqUgAYiMPNaSWQJsxDTGyayyKATQ1ZXeDTJDpuTrMzkCd4pT1E9rrbYHw6Z4vWRnb1FKhYCL?cluster=devnet)
3. **A tampered submission is refused.** All 63 cheating pull requests were refused.
   Evidence: [The tamper benchmark](TAMPER.md)
4. **Legitimate work is accepted.** The signed run pays the posted amount.
   Evidence: [The paying transaction (devnet, staging program ids)](https://explorer.solana.com/tx/63wT5rhYhEKbgmF5k8vEKdexzoCaXZCiDvRG2GQMGSMBBsc9avGfDw3izER9D6LHoe4ucJeinTBiWaWGWpnFWvfq?cluster=devnet)
5. **A replay pays nothing.** Tokens work once. One judge is no quorum.
   Evidence: [The tests that replay tokens and split a quorum](../programs-v2/handlers/tests/adversarial.rs)
6. **Both sides rebuild one bill.** An outsider verifies the receipt offline.
   Evidence: [The test that reconciles two ledgers](../tests/test_ledger.py)

Then your own invoice: [check it](https://drexthealpha.github.io/Knos/). Nobody has paid for this yet.

**Staging program ids.** The transactions of beats 2 and 4 ran on the staging program ids of the 0.3.14 rehearsal
([CAPABILITIES.md](CAPABILITIES.md), "The 0.3.14 rehearsal on devnet"), not on the public ones; each link says so
until a run on the public ids replaces it. Which build each public program id runs is in
[MANIFEST.md](MANIFEST.md), from [`web/upgrades.json`](../web/upgrades.json). The money is test USDC.

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
