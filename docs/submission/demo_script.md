# Demo (three minutes): six shots

One commercial story, start to finish: a buyer orders work, a submission fails, a submission passes, a replay is
refused, the two sides reconcile, and what outside use there has been is counted. Every shot is a screen recording
of the real thing on Solana devnet, in test USDC, with nothing staged, so that each transaction shown can be found
afterwards on the site's Numbers page (https://drexthealpha.github.io/Knos/#network), which is read from the
programs' own logs.

## Three rules for the recording

- **A shot whose capability has not run where the shot is recorded is cut, not staged.** On the public ids that
  means the stage the table below gives from `docs/capabilities.json` on the day; on staging ids it means a
  capability whose note there records the 0.3.14 staging rehearsal with its transaction. [CAPABILITIES.md](../CAPABILITIES.md)
  is the table. The narration of the shots that remain is not changed to cover for a cut one.
- **Every shot says which program ids it runs on.** The newer builds of the four programs are approved upgrade
  proposals, and the multisig's public delay decides when each can execute. Until a proposal has executed, its
  instructions are not on the public program ids: they were rehearsed on staging ids, which are other addresses on
  devnet, and the manifest counts no stage for that rehearsal (those capabilities are "tested locally"). The live
  state is in `web/upgrades.json`, and the recording is checked against it on the day, not against this page. A shot
  recorded on staging ids carries the caption "staging program ids on devnet" for its whole length.
- A number that only the release run can give is a slot, `[[stat: name]]`.

Caption under the first shot, no narration: "Built during the hackathon: everything shown. Older work is listed in
docs/DISCLOSURE.md."

| shot | starts | ends | what it shows |
|---|---|---|---|
| A | (0:00) | (0:30) | a buyer creates a work order in the console |
| B | (0:30) | (0:55) | a plausible submission fails, and the exact unmet condition is shown |
| C | (0:55) | (1:30) | a valid one passes: artifact, evidence, policy version, devnet transaction |
| D | (1:30) | (1:50) | a replay is attempted, and the component that refuses it is named |
| E | (1:50) | (2:25) | buyer and supplier reconcile to the same statement; a missing item becomes a dispute |
| F | (2:25) | (3:00) | commercial evidence, as it is today |

## Which program ids each shot can be recorded on

| shot | capability in `docs/capabilities.json` | while the proposal has not executed | after the proposal has executed |
|---|---|---|---|
| A | `buyer_page`, `terms_templates`, `work_orders`, `passkey_funder` | staging ids, captioned. On the public ids only the older path exists: fund by the comment `/knos fund` (`fund_by_comment`), which shows the same terms in the reply; say that it is the comment and not the console. | public ids |
| B | `check`, `pay_on_merge` | public ids. The check needs no program; the refusal to pay is the deployed escrow's. | public ids |
| C | `receipt`, `pay_on_merge`; `order_pay` for a work order | public ids for a task funded as a bounty; a work order only on staging ids, captioned | public ids, as a work order |
| D | `single_use_tokens` | staging ids, captioned, for the marker. On the public ids the same token is refused for a different reason, that the paid task is closed: if that is what is recorded, the narration names that reason and not the marker. | public ids: the marker |
| E | `statements`, `meter_batch`, `meter_seller_claim` | the two ledgers and the statement need no program at all; the two on-chain counts only on staging ids, captioned | public ids |
| F | none: it reads the chain and sends nothing | public ids | public ids |

## The stage of each capability a shot needs

The last column is not typed: `python scripts/doc_claims.py --write` writes it from `docs/capabilities.json`, and
the check fails when it differs.

| shot | capability | stage |
|---|---|---|
| A | `console` | tested locally |
| A | `buyer_page` | tested locally |
| A | `terms_templates` | tested locally |
| A | `work_orders` | tested locally |
| A | `passkey_funder` | tested locally |
| B | `check` | tested locally |
| B | `pay_on_merge` | deployed on devnet |
| C | `receipt_five_parts` | tested locally |
| C | `receipt` | tested locally |
| C | `order_pay` | tested locally |
| D | `single_use_tokens` | tested locally |
| E | `statements` | tested locally |
| E | `meter_batch` | tested locally |
| E | `meter_seller_claim` | tested locally |

## A. A buyer creates a work order (0:00, 30 seconds)

**On screen.** The console. The buyer picks a terms template and the form fills, each field in plain words: the
deliverable (an issue's address and its milestone); the budget, and under it what she will pay, the amount and
the fee on top with the fee as a share of the amount; the acceptance criteria (the checks that must pass, the
paths that may change, the deadline); the beneficiary rule (who is paid: the author of the accepted pull request,
or the wallets she names and their shares); the evaluator (which pinned workflow judges it, at which commit, and
whether a neutral run from the supplier's side may also sign). She changes one value and funds it. The order's
account in the explorer, and the log line that carries the hash of the terms.

**Narration.** This is the person who will have to approve the supplier's invoice. Before any work starts she
writes down what she is buying, what it may cost, what decides that it is done, who gets paid, and who judges.
She can read every one of those. They are hashed into the order now, and nobody can change them afterwards: not
her, and not the supplier.

**Must be visible.** Budget, criteria, beneficiary rule and evaluator, all readable without opening a file. The
effective fee before she funds. The same hash in the page and in the explorer.

## B. A plausible submission fails (0:30, 25 seconds)

**On screen.** A pull request for the deliverable. It looks right: the description says "all tests pass", and the
change is in the allowed paths. The check `test` is red at its head commit. She merges it anyway. The workflow
runs. Knos's comment on the pull request: not accepted, the required check `test` concluded failure at this
commit. The order: still open, the money still in it, nothing counted as accepted.

**Narration.** This submission says the tests pass. One did not. She merges it all the same, and nothing is
accepted and nothing is paid. The refusal names the one condition that was not met, the check and the commit, in
a sentence. The money has not moved.

**Must be visible.** The words of the claim, the name of the unmet condition, and the unchanged balance.

## C. A valid one passes (0:55, 35 seconds)

**On screen.** A second pull request: `test` is green. She merges it. Then the receipt on one screen, which keeps
five things apart: what the issuer authenticated (the repository, the workflow file, its pinned commit, the run);
what the evaluator observed (the artifact, as the head commit and its digest, and each named check with its
conclusion); which policy produced the verdict (the terms, their hash and the policy version); who authorised the
money and under which limit; and what remains trusted. Then Knos's comment with the transaction, and the explorer:
the verifier program checking the signature, the escrow paying the posted amount to the supplier.

**Narration.** This one meets the terms. The receipt says what was delivered, the evidence, which version of the
policy judged it, and who authorised the payment. It also says what is still taken on trust: the forge signed
which workflow ran, at which commit, in which repository. It did not sign what the workflow read. And here is the
transaction on devnet: the supplier is paid the posted amount, in test USDC, and the buyer paid the fee on top.

**Must be visible.** Artifact, evidence, policy version and the transaction's signature; the line that says what
the signature does not cover; the supplier's balance before and after.

## D. A replay is attempted (1:30, 20 seconds)

**On screen.** A terminal. The pay token of shot C, unchanged, sent again. The refusal as the program returns it.
The supplier's balance: unchanged. The marker account for that token in the explorer.

**Narration.** Now the same signed token, sent a second time. It is refused, and the component that refuses it is
the escrow program, `knos-pay`, on chain. The first use created a marker account for that token, and no
instruction accepts a token whose marker exists. The relay did not stop it, and neither did the site: anyone can
send this transaction, and the program is what says no.

**Must be visible.** The error as the program returns it, the program's name, and the balance not moving.

*If this is recorded on the public ids before the newer escrow build has executed, the last two sentences of the
narration are replaced by: "It is refused by the escrow program, `knos-pay`, because the task it pays is already
closed. The marker rule that refuses every replayed token is in the newer build, which is shown here on staging
ids."*

## E. Buyer and supplier reconcile (1:50, 35 seconds)

**On screen.** Two terminals side by side, labelled buyer and supplier. Each holds its own ledger file for the
month. The buyer's ledger has been made to leave out one accepted deliverable, on purpose, and the caption says
so. `knos meter reconcile` is run on both sides: the same statement, to the last unit, counting only what both
ledgers have and describe alike. Under it, on both screens, the item the buyer left out, listed by its id as held
by the supplier only: a dispute line, not an invoice line. Then the two counts of the month on chain, the buyer's
and the supplier's, which differ by that one.

**Narration.** At the end of the month each side computes the statement from its own records. They get the same
statement. We removed one accepted deliverable from the buyer's ledger to show what happens: it does not vanish,
and it does not slip onto the invoice. Both sides see it by name, as a dispute to settle between them. The
supplier did not need the buyer's file to know the counts differ, because both counts are public.

**Must be visible.** The two statements, equal. The missing item named on both screens. The caption that the
omission was deliberate.

## F. Commercial evidence, as it is today (2:25, 35 seconds)

**On screen.** The site's Numbers page, the rows for accounts that are not Knos's. Then the price book, with the
Pilot line. Then the list of what does not exist, from docs/DISCLOSURE.md.

**Narration.** Here is the commercial evidence, counted from the chain, and it is small. Funders other than Knos,
with their own tokens: 0. One outside account has been paid, for 3 pull requests, on tasks Knos funded itself.
That shows the path works between two accounts. It is not demand. There is no buyer, no pilot and no revenue, and
nobody has been asked yet. Everything you saw moved test money. What I can sell while this stays on devnet is
software: a 30-day pilot that reconciles one buyer's invoices from its suppliers. Nobody has bought it, and there
is no company yet to send the invoice. One person holds every key, behind a public 48-hour delay, and there has
been no outside security review.

**Must be visible.** The outside rows of the Numbers page as they are on the day, and the Pilot line of the price
book as printed in docs/MARKET.md.

*On the day, the two counts in this narration are read again from the chain and from `docs/facts.json`. If an
outside account has funded an order, the count is changed to what it is. A buyer, a pilot or revenue is said only
if it exists and the other party agrees to be named.*
