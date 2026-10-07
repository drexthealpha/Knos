# Demo (three minutes): one task in six steps

**The neutral meter for AI agent work: neither side keeps the count.**

One continuous technical demonstration, the story of [STORY.md](../STORY.md), about one task. It opens on the
refusal: a submission that claimed success, and was not paid. Then the six steps in order: buyer and supplier agree
one task, its price and its acceptance terms; the submission that claims success fails the condition, and payment is
withheld with the reason; valid work passes and two independent records reconcile; the payment executes and the
supplier gets a portable receipt; a replay makes no second payment; and last the accounting export, the deployment
identity and the limits. The presentation is a separate page ([pitch_script.md](pitch_script.md)).

The spoken words are the lines that start with `>`: about 420 words, which is three minutes
(`tests/test_business_docs.py` counts them). A spoken number is in `docs/facts.json`.

## Four rules for the recording

- **Every step says on which program ids it ran.** `web/upgrades.json` and [MANIFEST.md](../MANIFEST.md) are read on
  the day, not this page. A step that ran on the public program ids carries "Public program ids on Solana devnet". A step that ran on staging program ids carries the caption "Staging program ids on Solana
  devnet" for its whole length, and a step that ran in the local simulator carries "Local simulator: not devnet". No
  step is shown as a run on the public program ids that did not run there.
- **A step whose capability has run nowhere is cut, not staged.** The table below gives each capability's stage
  from `docs/capabilities.json`. The narration of the steps that remain is not changed to cover for a cut one.
- **A replay says it is a replay, and a faster recording says how much faster.** A shot of a run made earlier
  carries the caption "Replay of a run recorded earlier", with the run's address, for its whole length. A shot
  played faster than it happened carries "Recorded at N times speed" for its whole length. A workflow run takes
  longer than these beats, so steps two and three are replays at higher speed and carry both captions. The
  measured times are on the site's Numbers page, not in this video.
- **Everything shown is the real thing, and the money is test USDC.** A settlement carries the caption "Solana
  devnet. Test USDC." for its whole length. Each transaction shown can be found afterwards on the Numbers page
  (https://drexthealpha.github.io/Knos/#network), which is read from the programs' own logs.

Caption under the first shot, no narration: "Built during the hackathon: everything shown. Older work is listed in
docs/DISCLOSURE.md." **The refusal leads.** The first thing on screen after the title is the judge's refusal of step
two, with its reason, held while the number is said; the limits are one line, in the last step. The task is Knos's
own test task: no buyer and no supplier outside Knos has run one.

| step | starts | ends | what it shows |
|---|---|---|---|
| one | (0:00) | (0:30) | the refusal first; then buyer and supplier agree one task, its price and its acceptance terms |
| two | (0:30) | (1:05) | a submission that claims success fails the condition: payment withheld, with the reason |
| three | (1:05) | (1:35) | valid work passes, and two independent records reconcile |
| four | (1:35) | (2:00) | the payment executes, and the supplier gets a portable receipt |
| five | (2:00) | (2:20) | a replay: no second payment |
| six | (2:20) | (3:00) | the accounting export, the deployment identity and the limits in one line |

## The stage of each capability a step needs

The last column is not typed: `python scripts/doc_claims.py --write` writes it from `docs/capabilities.json`, and
the check fails when it differs. No count of capabilities is given here; [CAPABILITIES.md](../CAPABILITIES.md) has
every one, and [MANIFEST.md](../MANIFEST.md) ties each to the build that is live.

| step | capability | stage |
|---|---|---|
| one | `fund_by_comment` | deployed on devnet |
| one | `work_orders` | exercised on devnet |
| two | `tests_mode` | exercised on devnet |
| two | `refusal_table` | tested locally |
| three | `honest_work_rate` | tested locally |
| three | `statements` | tested locally |
| four | `pay_on_merge` | deployed on devnet |
| four | `order_pay` | exercised on devnet |
| four | `receipt` | tested locally |
| four | `verify_without_chain` | tested locally |
| five | `single_use_tokens` | exercised on devnet |
| five | `ledger_dedup` | tested locally |
| six | `finance_exports` | tested locally |

## 1. The refusal, then the agreement (0:00, 30 seconds)

**On screen.** The title. Then, first, the judge's comment on a pull request: payment withheld, and the reason.
Then back to the start: an issue, which is the task. The buyer's comment that funds it, and the reply: the order,
its price, the acceptance terms and their hash. The supplier who takes the issue. *Captions: replay; devnet.*

> Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check. This is one such claim,
> and it was not paid: the reason is on screen. Here is what was agreed before the work started. A buyer and a
> supplier agree one task, in one issue. The buyer's comment fixes the price and the acceptance terms: a suite
> of checks the supplier cannot edit. The terms are hashed into the order when it is funded.

**Must be visible.** The refusal before anything else; the issue, the funding comment and who wrote it, the price,
the terms and their hash.

## 2. A claimed success fails the condition (0:30, 35 seconds)

**On screen.** A pull request whose description says the tests pass. It leaves the bug in place and edits the test
that already existed. Plain CI: green. The judge's comment: "The change edits a test that already existed.", with
the file, the rule's code `judge.protected-test-edited` and what to do next. The order's balance,
unchanged. *Captions: replay; speed.*

> The supplier's agent submits, and says the tests pass. Plain CI is green. But this submission does not fix the
> bug: it edits the test that already existed. The judge takes the acceptance checks from the buyer's branch, as
> funded, and never from the submission. The condition fails, so payment is withheld, with the reason in these
> words: the change edits a test that already existed. In our benchmark plain CI passed 56 of 63 such cheats, and this check refused all 63.

**Must be visible.** The claim, the edited test, the green CI, the refusal word for word with its code, and the
unchanged balance.

## 3. Valid work passes, and two records reconcile (1:05, 30 seconds)

**On screen.** A second pull request: the fix, and a regression test of its own in a new file. The same judge:
accepted. Then two terminals, buyer and supplier, each running `knos meter reconcile` on its own ledger: the same
statement and the same digest. *Captions: replay; speed.*

> Now valid work. A second submission fixes the bug and brings its own regression test, in a new file. The same
> judge runs the same checks, and the condition passes. GitHub signs that run. Then two independent records: the
> buyer and the supplier each rebuild the statement from their own copy of the ledger. The same lines, the same
> total, the same digest. They reconcile.

**Must be visible.** The fix and the added test, the verdict, the two commands and the two digests, equal.

## 4. The payment executes, with a portable receipt (1:35, 25 seconds)

**On screen.** The transaction, and the supplier's balance before and after. Then the receipt file, and a machine
with the network off: `knos bundle verify` on that file alone, and its verdict. *Captions: replay; devnet;
offline.*

> The payment executes. A Solana program checks GitHub's signature itself and releases the posted amount to the
> supplier, in test money on devnet: no company holds it. The supplier gets a receipt it can carry anywhere. With
> the network off, anyone can check the signature and the hash of the terms from that one file.

**Must be visible.** The transaction's signature, the two balances, the receipt file, the offline check and its
verdict.

## 5. A replay: no second payment (2:00, 20 seconds)

**On screen.** A terminal: the token that paid step four, sent again; the program's refusal (`E_REPLAY`); the
balance unchanged. The ledger, with the repeated evidence listed as a duplicate. *Caption: devnet.*

> Replay. The same signed token, sent a second time: the program refuses it, because a token works once. The
> balance does not move. The same evidence entered twice in the ledger is listed as a duplicate and billed once.
> No second payment.

**Must be visible.** The error as the program returns it; the balance not moving; the duplicate, listed.

## 6. The export, the deployment identity, the limits (2:20, 40 seconds)

**On screen.** `knos statement export` on the approved statement, and the file it writes. Then
[MANIFEST.md](../MANIFEST.md): each public program id, the build it runs and the commit it was built from. Then
the limits, as one line of text. Then the front door.

> For the accounts: the approved statement exports as a file a payables system imports, one bill for each
> accepted deliverable. For whoever audits it: the deployment identity. One page ties each public program id to
> the build it runs, its hash, and the commit it was built from. The limits, in one line: Solana devnet, test
> money, one person holds every key, no outside review, and nobody has paid. The next invoice is yours. Neither
> side keeps the count.

**Must be visible.** The export command and its file; the manifest's table of program ids and hashes; the one line
of limits; the address of the site.

*On the day, which program ids each step ran on is read again from `web/upgrades.json`. A step that did not run on
the public program ids says where it ran, in its caption. A buyer, a pilot, an interview or revenue is said only if
it exists and the other party agrees to be named.*
