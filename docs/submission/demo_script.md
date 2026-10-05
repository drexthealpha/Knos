# Demo (two minutes): one buyer's story in seven moments

**The neutral meter for AI agent work: neither side keeps the count.**

One buyer, start to finish: a billed change with a failed check; she fixes the budget and the terms; a submission
that fails is refused with the reason; valid work produces the record and a devnet payment; a replay cannot pay
twice and both sides derive the same statement; the record verifies with no chain and the remaining trust is
shown; and what is true today about outside use, with the offer.

The spoken words are the lines that start with `>`: about 300 words at most, which is two minutes, and
`tests/test_business_docs.py` counts them. A spoken number is in `docs/facts.json`.

## Four rules for the recording

- **Every moment says on which program ids it ran.** Knos 0.3.16 is released before the pending upgrade executes,
  so the builds that carry work orders, the single-use rule and the batched count have run on the staging program
  ids of the 0.3.14 rehearsal, and a moment that shows them carries the caption "Staging program ids on Solana
  devnet" for its whole length. `web/upgrades.json` is read on the day, not this page. No moment is shown as a run
  on the public program ids that did not run there.
- **A moment whose capability has run nowhere is cut, not staged.** The table below gives each capability's stage
  from `docs/capabilities.json`. The narration of the moments that remain is not changed to cover for a cut one.
- **A replay says it is a replay, and a faster recording says how much faster.** Any shot that shows a run made
  earlier carries the caption "Replay of a run recorded earlier", with the run's address, for its whole length.
  Any shot played faster than it happened carries "Recorded at N times speed" for its whole length. A workflow
  run takes longer than these moments, so moments three and four are replays at higher speed and carry both captions.
  Nothing in the video is offered as proof of how fast anything is: the measured times are on the site's Numbers
  page.
- **Everything shown is the real thing on Solana devnet, in test USDC.** Each transaction shown can be found
  afterwards on the Numbers page (https://drexthealpha.github.io/Knos/#network), which is read from the programs'
  own logs.

Caption under the first shot, no narration: "Built during the hackathon: everything shown. Older work is listed in
docs/DISCLOSURE.md."

| moment | starts | ends | what it shows |
|---|---|---|---|
| one | (0:00) | (0:15) | a real purchasing problem: a billed change with a failed check |
| two | (0:15) | (0:30) | the buyer fixes the budget and the terms |
| three | (0:30) | (0:50) | a submission that fails is refused, with the reason |
| four | (0:50) | (1:10) | valid work produces the record and a devnet payment |
| five | (1:10) | (1:30) | a replay cannot pay twice; both sides derive the same statement |
| six | (1:30) | (1:45) | the record verifies with no chain; the remaining trust is shown |
| seven | (1:45) | (2:00) | what is true today about outside use, and the offer |

## The stage of each capability a moment needs

The last column is not typed: `python scripts/doc_claims.py --write` writes it from `docs/capabilities.json`, and
the check fails when it differs. No count of capabilities is given here; [CAPABILITIES.md](../CAPABILITIES.md) has
every one.

| moment | capability | stage |
|---|---|---|
| one | `check` | tested locally |
| two | `console` | tested locally |
| two | `terms_templates` | tested locally |
| two | `work_orders` | tested locally |
| three | `pay_on_merge` | deployed on devnet |
| four | `receipt_five_parts` | tested locally |
| four | `order_pay` | tested locally |
| five | `single_use_tokens` | tested locally |
| five | `statements` | tested locally |
| six | `evidence_bundle` | tested locally |
| six | `receipt` | tested locally |

## 1. A billed change with a failed check (0:00, 15 seconds)

**On screen.** One public pull request from the measured sample ([agent_pr_ci.json](../agent_pr_ci.json)), as
GitHub shows it: written by an agent, the description says the tests pass, the state is merged, and a check at
the head commit is red. Beside it, an invoice line: "merged changes, billed per merge".

> This pull request was written by an agent. It says the tests pass. It was merged with this check failed.
> Billed per merge, it is a line on an invoice. In our sample, 30 of 241 were like it.

**Must be visible.** The words of the claim, the red check, the merged state, and the address of the pull request.

## 2. The buyer fixes the budget and the terms (0:15, 15 seconds)

**On screen.** The console. She picks a terms template: the deliverable, the budget and under it what she will
pay with the fee on top, the checks that must pass, the paths that may change, the deadline, who is paid. She
funds it. The hash of the terms in the page, and the same hash in the explorer.

> So before the work, the buyer writes down the budget and what decides that it is done: these checks, these
> paths, this deadline. They are hashed into the order when she funds it. Nobody can change them afterwards: not
> her, and not the supplier.

**Must be visible.** Budget, checks, paths and deadline, readable without opening a file; the effective fee
before she funds; the same hash twice.

## 3. A submission that fails is refused, with the reason (0:30, 20 seconds)

**On screen.** A pull request for the deliverable. The description says "all tests pass". The check `test` is red
at its head commit. She merges it anyway. Knos's comment: not accepted, the required check `test` concluded
failure at this commit. The order: still open, the money still in it. *Captions: replay; speed.*

> A submission arrives. It says the tests pass. One did not. She merges it anyway, and it is refused, with the
> reason: the check named test failed at this commit. Nothing is counted. No money moves.

**Must be visible.** The claim, the name of the unmet condition, and the unchanged balance.

## 4. Valid work produces the record and a devnet payment (0:50, 20 seconds)

**On screen.** A second pull request: `test` is green. She merges it. The record on one screen, in four linked
parts: the authorisation (buyer, supplier, scope, budget, who approved), the acceptance (artifact, policy
version, evaluator, evidence, verdict), the commercial record (the billable deliverable, the amount, the invoice
line), and the settlement status, which reads "devnet demonstration". Then the transaction in the explorer.
*Captions: replay; speed.*

> The next one meets the terms. Here is the record: what was delivered, the evidence, the policy that judged it,
> and who authorised it. And the payment on devnet, in test money: the supplier receives the posted amount.

**Must be visible.** Artifact, evidence, policy version, the transaction's signature, the words "devnet
demonstration", and the supplier's balance before and after.

## 5. A replay cannot pay twice; both sides derive the same statement (1:10, 20 seconds)

**On screen.** A terminal: the pay token of moment four, unchanged, sent again; the refusal as the program returns
it; the supplier's balance unchanged. Then two terminals, buyer and supplier, each running `knos meter reconcile`
on its own ledger: the same statement, to the last unit.

> Now the same signed token, sent again. The program refuses it: every token is taken once. At the end of the
> month each side computes the statement from its own ledger, and they get the same totals.

**Must be visible.** The error as the program returns it and the program's name; the balance not moving; the two
statements, equal.

## 6. The record verifies with no chain (1:30, 15 seconds)

**On screen.** A terminal with the network off, and the caption says so. The evidence bundle of moment four is
verified from the file alone, against GitHub's published keys as archived. Then the line of the receipt that says
what remains trusted.

> This record does not need the chain. Offline, it verifies from the signature GitHub made. And it says what is
> still trusted: GitHub signed which workflow ran, not what the workflow read.

**Must be visible.** That the network is off; the verification passing; the sentence about what the signature
does not cover.

## 7. What is true today, and the offer (1:45, 15 seconds)

**On screen.** The site's Numbers page, the rows for accounts that are not Knos's. Then the price book: Check,
and the Pilot line.

> What is true today. Funders other than Knos, with their own tokens: 0. One outside account has been paid, for 3
> pull requests, on tasks I funded myself. No buyer has been asked. The offer: run the count beside your own
> invoices, free. Knos is the neutral meter for AI agent work. Neither side keeps the count.

**Must be visible.** The outside rows of the Numbers page as they are on the day, and the price book as printed
in docs/MARKET.md.

*On the day, the counts in this narration are read again from the chain and from [NUMBERS.md](NUMBERS.md). If an
outside account has funded an order, the count is changed to what it is. A buyer, a pilot, an interview or
revenue is said only if it exists and the other party agrees to be named.*
