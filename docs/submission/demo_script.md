# Demo (two minutes): one round in eight steps

**The neutral meter for AI agent work: neither side keeps the count.**

The story of [STORY.md](../STORY.md), shown: the number; a buyer authorises; a supplier submits a correct fix with a
regression test; it is accepted under the original terms; a tampered submission fails; a duplicate settlement
changes nothing; both sides rebuild the same record; finance approves the agreed lines and sees the exception; and
step eight is the viewer's own invoice.

The spoken words are the lines that start with `>`: about 280 words, which is two minutes
(`tests/test_business_docs.py` counts them). A spoken number is in `docs/facts.json`.

## Four rules for the recording

- **Every step says on which program ids it ran.** `web/upgrades.json` is read on the day, not this page. A step
  that ran on the staging program ids of the 0.3.14 rehearsal carries the caption "Staging program ids on Solana
  devnet" for its whole length. No step is shown as a run on the public program ids that did not run there.
- **A step whose capability has run nowhere is cut, not staged.** The table below gives each capability's stage
  from `docs/capabilities.json`. The narration of the steps that remain is not changed to cover for a cut one.
- **A replay says it is a replay, and a faster recording says how much faster.** A shot of a run made earlier
  carries the caption "Replay of a run recorded earlier", with the run's address, for its whole length. A shot
  played faster than it happened carries "Recorded at N times speed" for its whole length. A workflow run takes
  longer than these steps, so steps two, three and four are replays at higher speed and carry both captions. The
  measured times are on the site's Numbers page, not in this video.
- **Everything shown is the real thing on Solana devnet, in test USDC.** Each transaction shown can be found
  afterwards on the Numbers page (https://drexthealpha.github.io/Knos/#network), which is read from the programs'
  own logs.

Caption under the first shot, no narration: "Built during the hackathon: everything shown. Older work is listed in
docs/DISCLOSURE.md."

| step | starts | ends | what it shows |
|---|---|---|---|
| one | (0:00) | (0:20) | the number, and a buyer authorises a defined piece of work |
| two | (0:20) | (0:35) | a supplier submits a correct fix with a regression test |
| three | (0:35) | (0:50) | it is accepted under the original terms |
| four | (0:50) | (1:05) | a tampered submission fails |
| five | (1:05) | (1:20) | a duplicate settlement changes nothing |
| six | (1:20) | (1:35) | both sides rebuild the same record |
| seven | (1:35) | (1:50) | finance approves the agreed lines and sees the exception |
| eight | (1:50) | (2:00) | your invoice next: nobody has paid |

## The stage of each capability a step needs

The last column is not typed: `python scripts/doc_claims.py --write` writes it from `docs/capabilities.json`, and
the check fails when it differs. No count of capabilities is given here; [CAPABILITIES.md](../CAPABILITIES.md) has
every one.

| step | capability | stage |
|---|---|---|
| one | `fund_by_comment` | deployed on devnet |
| one | `work_orders` | tested locally |
| two | `honest_work_rate` | tested locally |
| three | `pay_on_merge` | deployed on devnet |
| three | `order_pay` | tested locally |
| three | `receipt_five_parts` | tested locally |
| four | `tests_mode` | tested locally |
| five | `single_use_tokens` | tested locally |
| five | `ledger_dedup` | tested locally |
| six | `statements` | tested locally |
| seven | `console` | tested locally |
| seven | `finance_exports` | tested locally |
| eight | `shadow_mode` | tested locally |

## 1. The number, and a buyer authorises (0:00, 20 seconds)

**On screen.** The number. Then one public pull request from the measured sample
([agent_pr_ci.json](../agent_pr_ci.json)), as GitHub shows it: the description says the tests pass, the state is
merged, a check at the head commit is red. Then an issue, and her comment: `/knos fund 20 checks: test`. The
order, with its budget and its terms.

> Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check. This is one of them,
> billed per merge. So the buyer authorises the next piece of work herself: one comment fixes the budget and the
> terms before the work starts.

**Must be visible.** The number, the red check and the merged state; the comment; the budget and the terms.

## 2. A supplier submits (0:20, 15 seconds)

**On screen.** A pull request for the deliverable: the fix, and the regression test it adds. The pinned workflow
run starts. *Captions: replay; speed.*

> A supplier submits. The fix is correct, and it brings its own regression test. Nothing is taken on the
> description: the run that judges it is pinned, and GitHub signs it.

**Must be visible.** The changed file, the added test, and the commit the workflow is pinned to.

## 3. Accepted under the original terms (0:35, 15 seconds)

**On screen.** The verdict: accepted. The record on one screen: the deliverable, the evidence, the policy version,
and the terms as funded. Then the transaction, and the supplier's balance. *Captions: replay; speed.*

> It is accepted under the original terms. Nobody changed them after funding. The record shows what was
> delivered, the evidence and the policy, and the supplier receives the posted amount, in test money on devnet.

**Must be visible.** The verdict, the terms unchanged since funding, the transaction's signature, and the balance
before and after.

## 4. A tampered submission fails (0:50, 15 seconds)

**On screen.** A second pull request that does not fix the bug and changes what the checks see. The verdict:
rejected, with the reason. The order's balance, unchanged. *Captions: replay; speed.*

> Now a tampered submission. It does not fix the bug; it changes what the checks see. It fails, and the comment
> names why. In our benchmark the black-box check refused all 63 cheating pull requests; 56 passed plain CI.

**Must be visible.** The verdict, the named reason, and the unchanged balance.

## 5. A duplicate settlement changes nothing (1:05, 15 seconds)

**On screen.** A terminal: the proof that paid step three, unchanged, sent again; the refusal as the program
returns it; the supplier's balance unchanged. Then the ledger, with the repeated evidence listed as a duplicate.

> The same signed proof, sent a second time. The program refuses it, and the balance does not move. The same
> evidence entered twice in the ledger is listed as a duplicate and counted once.

**Must be visible.** The error as the program returns it; the balance not moving; the duplicate, listed.

## 6. Both sides rebuild the same record (1:20, 15 seconds)

**On screen.** Two terminals, buyer and supplier, each running `knos meter reconcile` on its own ledger: the same
statement, line for line, and the same digest.

> At the end of the month the buyer and the supplier each rebuild the statement from their own ledger. Two
> machines, two copies, one record: the same lines and the same total.

**Must be visible.** The two commands, the two statements, and the two digests, equal.

## 7. Finance approves the agreed lines (1:35, 15 seconds)

**On screen.** The console's finance view of that statement: the agreed lines, approved and exported as bill
lines; one line marked disputed, with its reason, left out of the export.

> Finance opens that statement. The agreed lines are approved and exported as bill lines. One line is disputed:
> it stays visible as an exception, and it is not billed.

**Must be visible.** The agreed lines, the exception with its reason, and the export without it.

## 8. Your invoice next (1:50, 10 seconds)

**On screen.** The site's Numbers page, the rows for accounts that are not Knos's, zeros as they are. Then the
front door: the box where an invoice is pasted.

> Step eight is not a customer: nobody has paid. It is your invoice. Paste it on the site. Neither side keeps the
> count.

**Must be visible.** The outside rows of the Numbers page as they are on the day, and the address of the site.

*On the day, what step eight shows is read again from the chain and from [NUMBERS.md](NUMBERS.md). A buyer, a
pilot, an interview or revenue is said only if it exists and the other party agrees to be named.*
