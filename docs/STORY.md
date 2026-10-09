# The story: one task, seven steps

**The neutral meter for AI agent work: neither side keeps the count.**

Of 241 merged agent pull requests claiming passing tests, 9 failed a test, build, lint or type check.

The count is in [backtest.json](backtest.json), made by `scripts/backtest.py` from the pull requests listed in
[agent_pr_ci.json](agent_pr_ci.json). A failed check is GitHub's record, not a judgment of why it failed.

The claim: two parties who distrust each other compute the same bill from evidence a third party signed, and the
program releases the money on that signature, with no company and no oracle in the middle.

Why Solana: Money is released with no custodian, and the count is anchored where neither side can alter it.
A receipt verifies with no chain; the chain is for the money and for the root.

Days to approve, not seconds to pay: from merge to paid took 26 seconds at the median, over 51 payments on devnet,
and a buyer does not wait for that. A buyer waits for a person to approve the invoice: days to approve, from the
day the invoice is received to the day it is approved. Knos has not measured that wait with any buyer, so no figure
for it is given. A judge's one page: [JUDGES.md](JUDGES.md).

## The seven steps

One task, start to finish. Each step has one piece of evidence: a file, a test or a transaction. The site plays the
same seven ([`web/story.js`](../web/story.js)), the round on its first screen lets a reader drive them
([`web/demo.js`](../web/demo.js): Agree, Fails, Passes, Statement, Replay, Pay, Verify), and
[the demonstration's script](submission/demo_script.md) tells the same seven on one clock of three minutes. The
script opens on the refusal of step 2.

1. **Buyer and supplier agree one task.** Price and acceptance terms come first.
   Evidence: [The funding transaction (devnet, public program ids)](https://explorer.solana.com/tx/177CEpZ8N4r5CGNjSEWBEouTTqMDwAao9LFzwSNYiFjJZUfJdtLDeusHbmmawWxzKLp1SozNAyNCEeGxSvvBm5s?cluster=devnet)
2. **A claimed success fails the condition.** Payment is withheld, with the reason.
   Evidence: [The tamper benchmark](TAMPER.md)
3. **Valid work passes.** The corrected submission meets the same check.
   Evidence: [The test that accepts correct work](../tests/test_tamper_bench.py)
4. **Both sides make the same statement.** Two independent records reconcile.
   Evidence: [The test that reconciles two ledgers](../tests/test_ledger.py)
5. **A replay pays nothing.** No second payment.
   Evidence: [The refused replay (devnet, public program ids)](https://explorer.solana.com/tx/4hCf7a3FpKiTexPUxX4jvPbYUUQMvgHmyjHSVjbUJ2yqe3srzxLJrsZ8QY4dpT2pt4VFSRJ4j4kQMwEcapvk3Rrp?cluster=devnet)
6. **The payment executes.** The supplier gets a portable receipt.
   Evidence: [The paying transaction (devnet, public program ids)](https://explorer.solana.com/tx/59AfaYHTvWHhbAhiiNHCbCfEcGCxG1kCydJwfRNjZqry9bCnMF3ox6bd4P7favA9hjgzB5nk283g2Mdq3LruyNWV?cluster=devnet)
7. **A verifier checks it offline.** The deployment identity is one page.
   Evidence: [The release manifest](MANIFEST.md)

The steps are told in the order the demonstration tells them. On the chain the replay of step 5 was sent after the
payment of step 6: it is the same token sent a second time, and the program refused it.

Then your own invoice: [check it](https://drexthealpha.github.io/Knos/). Nobody has paid for this yet.

**Public program ids.** The transactions of steps 1, 5 and 6 are one round on the public program ids, the round
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
