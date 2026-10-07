# The story: one task, six steps

**The neutral meter for AI agent work: neither side keeps the count.**

Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check.

The count is in [backtest.json](backtest.json), made by `scripts/backtest.py` from the pull requests listed in
[agent_pr_ci.json](agent_pr_ci.json). A failed check is GitHub's record, not a judgment of why it failed.

The claim: two parties who distrust each other compute the same bill from evidence a third party signed, and the
program releases the money on that signature, with no company and no oracle in the middle.

## The six steps

One task, start to finish. Each step has one piece of evidence: a file, a test or a transaction. The site plays the
same six ([`web/story.js`](../web/story.js)), and [the demonstration's script](submission/demo_script.md) times
them and opens on the refusal of step 2.

1. **Buyer and supplier agree one task.** Price and acceptance terms come first.
   Evidence: [The funding transaction (devnet, public program ids)](https://explorer.solana.com/tx/177CEpZ8N4r5CGNjSEWBEouTTqMDwAao9LFzwSNYiFjJZUfJdtLDeusHbmmawWxzKLp1SozNAyNCEeGxSvvBm5s?cluster=devnet)
2. **A claimed success fails the condition.** Payment is withheld, with the reason.
   Evidence: [The tamper benchmark](TAMPER.md)
3. **Valid work passes.** Two independent records reconcile.
   Evidence: [The test that reconciles two ledgers](../tests/test_ledger.py)
4. **The payment executes.** The supplier gets a portable receipt.
   Evidence: [The paying transaction (devnet, public program ids)](https://explorer.solana.com/tx/59AfaYHTvWHhbAhiiNHCbCfEcGCxG1kCydJwfRNjZqry9bCnMF3ox6bd4P7favA9hjgzB5nk283g2Mdq3LruyNWV?cluster=devnet)
5. **A replay pays nothing.** No second payment.
   Evidence: [The refused replay (devnet, public program ids)](https://explorer.solana.com/tx/4hCf7a3FpKiTexPUxX4jvPbYUUQMvgHmyjHSVjbUJ2yqe3srzxLJrsZ8QY4dpT2pt4VFSRJ4j4kQMwEcapvk3Rrp?cluster=devnet)
6. **Accounts get an export.** The deployment identity is one page.
   Evidence: [The release manifest](MANIFEST.md)

Then your own invoice: [check it](https://drexthealpha.github.io/Knos/). Nobody has paid for this yet.

**Public program ids.** The transactions of steps 1, 4 and 5 are one round on the public program ids, the round
the site's demo replays (`web/demo_data.json`, written by `scripts/demo_data.py`). Which build each public program
id runs is in [MANIFEST.md](MANIFEST.md), from [`web/upgrades.json`](../web/upgrades.json). The money is test USDC.

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
