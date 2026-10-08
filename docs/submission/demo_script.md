# Demo (three minutes): one transaction in seven beats

**The neutral meter for AI agent work: neither side keeps the count.**

One continuous technical demonstration that follows one transaction through a disagreement to its end. It opens on
the refusal: a submission that claimed success, and was not paid. Then the seven beats in order: buyer and supplier
agree the price, the acceptance terms, the deadline and the remedy; a submission fails the agreed check, and the
exact reason is given; the corrected submission passes; buyer and supplier each produce the same statement; a
replayed or duplicate line is refused; the payment executes; and a verifier that needs nothing from Knos checks
the result. The site plays the same seven, from recorded evidence. [STORY.md](../STORY.md) has the evidence under
each step, and the presentation is a separate page ([pitch_script.md](pitch_script.md)).

The spoken words are the lines that start with `>`: about 420 words, which is three minutes
(`tests/test_business_docs.py` counts them). A spoken number is in `docs/facts.json`. **No fee is spoken as a
number.** The public program ids charge whatever the build that is live there charges, and that changes when an
approved upgrade executes; beat six shows the fee read from the chain while it is recorded, and says only that.

## Five rules for the recording

- **Every step says on which program ids it ran.** `web/upgrades.json` and [MANIFEST.md](../MANIFEST.md) are read on
  the day, not this page. A step that ran on the public program ids carries "Public program ids on Solana devnet". A step that ran on staging program ids carries the caption "Staging program ids on Solana
  devnet" for its whole length, and a step that ran in the local simulator carries "Local simulator: not devnet". No
  step is shown as a run on the public program ids that did not run there.
- **A step whose capability has run nowhere is cut, not staged.** The table below gives each capability's stage
  from `docs/capabilities.json`. The narration of the steps that remain is not changed to cover for a cut one.
- **A replay says it is a replay, and a faster recording says how much faster.** A shot of a run made earlier
  carries the caption "Replay of a run recorded earlier", with the run's address, for its whole length. A shot
  played faster than it happened carries "Recorded at N times speed" for its whole length. A workflow run takes
  longer than these beats, so beats two and three are replays at higher speed and carry both captions. The
  measured times are on the site's Numbers page, not in this video.
- **A fee on screen is read from the chain at that moment.** The pricing page and `knos bill explain` show the fee of
  the build that is live on the public program ids; the recording shows that, and no fee is typed into a caption.
- **Everything shown is the real thing, and the money is test USDC.** A settlement carries the caption "Solana
  devnet. Test USDC." for its whole length. Each transaction shown can be found afterwards on the Numbers page
  (https://drexthealpha.github.io/Knos/#network), which is read from the programs' own logs.

Caption under the first shot, no narration: "Built during the hackathon: everything shown. Older work is listed in
docs/DISCLOSURE.md." **The refusal leads.** The first thing on screen after the title is the judge's refusal of beat
two, with its reason, held while the number is said; the limits are one line, in the last beat. The task is Knos's
own test task: no buyer and no supplier outside Knos has run one.

| beat | starts | ends | what it shows |
|---|---|---|---|
| one | (0:00) | (0:28) | the refusal first; then buyer and supplier agree price, acceptance terms, deadline and remedy |
| two | (0:28) | (1:00) | a submission that claims success fails the agreed check: payment withheld, with the exact reason |
| three | (1:00) | (1:16) | the corrected submission passes the same check |
| four | (1:16) | (1:38) | buyer and supplier each produce the same statement, with the same digest |
| five | (1:38) | (1:56) | a replayed token and a duplicate line: both refused, no second payment |
| six | (1:56) | (2:27) | the payment executes in test USDC, or a file for the buyer's own payables system |
| seven | (2:27) | (3:00) | a verifier with the network off checks the receipt; the deployment identity; the limits in one line |

## The stage of each capability a beat needs

The last column is not typed: `python scripts/doc_claims.py --write` writes it from `docs/capabilities.json`, and
the check fails when it differs. No count of capabilities is given here; [CAPABILITIES.md](../CAPABILITIES.md) has
every one, and [MANIFEST.md](../MANIFEST.md) ties each to the build that is live.

| beat | capability | stage |
|---|---|---|
| one | `fund_by_comment` | deployed on devnet |
| one | `work_orders` | exercised on devnet |
| two | `tests_mode` | exercised on devnet |
| two | `refusal_table` | tested locally |
| three | `honest_work_rate` | tested locally |
| four | `statements` | tested locally |
| five | `single_use_tokens` | exercised on devnet |
| five | `ledger_dedup` | tested locally |
| six | `pay_on_merge` | deployed on devnet |
| six | `order_pay` | exercised on devnet |
| six | `finance_exports` | tested locally |
| seven | `receipt` | tested locally |
| seven | `verify_without_chain` | tested locally |

## 1. The refusal, then the agreement (0:00, 28 seconds)

**On screen.** The title. Then, first, the judge's comment on a pull request: payment withheld, and the reason.
Then back to the start: an issue, which is the task. The buyer's comment that funds it, and the reply: the order,
its price, the acceptance terms and their hash, the deadline, and what happens if nothing is accepted by then: a
refund. The supplier who takes the issue. *Captions: replay; devnet.*

> Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check. This is one such claim,
> and it was not paid: the reason is on screen. Here is what was agreed before the work started. In one issue,
> buyer and supplier agree the price, the acceptance terms, the deadline and the remedy. The price and the
> acceptance terms are hashed into the order when it is funded.

**Must be visible.** The refusal before anything else; the issue, the funding comment and who wrote it, the price,
the terms and their hash, the deadline.

## 2. A claimed success fails the agreed check (0:28, 32 seconds)

**On screen.** A pull request whose description says the tests pass. It leaves the bug in place and edits the test
that already existed. Plain CI: green. The judge's comment: "The change edits a test that already existed.", with
the file, the rule's code `judge.protected-test-edited` and what to do next. The order's balance,
unchanged. *Captions: replay; speed.*

> The supplier's agent submits, and says the tests pass. Plain CI is green. But this submission does not fix the
> bug: it edits the test that already existed. The judge takes the acceptance checks from the buyer's branch, as
> funded, and never from the submission. The check fails, so payment is withheld, with the reason in these
> words: the change edits a test that already existed. In our benchmark plain CI passed 56 of 63 such cheats, and
> the black-box check refused all 63.

**Must be visible.** The claim, the edited test, the green CI, the refusal word for word with its code, and the
unchanged balance.

## 3. The corrected submission passes (1:00, 16 seconds)

**On screen.** A second pull request from the same supplier: the fix, and a regression test of its own in a new
file. The same judge, the same checks: accepted. *Captions: replay; speed.*

> The supplier corrects it. The second submission fixes the bug and brings its own regression test, in a new
> file. The same judge runs the same checks, and this time the check passes. GitHub signs that run.

**Must be visible.** The fix and the added test, the same check named in both verdicts, and the second verdict.

## 4. Two parties, one statement (1:16, 22 seconds)

**On screen.** Two terminals, buyer and supplier, each running `knos meter reconcile` on its own ledger: the same
statement and the same digest, side by side. *No caption: nothing here touches a chain.*

> Now two independent records. The buyer and the supplier each rebuild the statement from their own copy of the
> ledger, on their own machine. The same lines, the same total, the same digest. They reconcile, and neither of
> them kept the count: GitHub signed the evidence both started from.

**Must be visible.** The two commands and the two digests, equal.

## 5. A replay and a duplicate are refused (1:38, 18 seconds)

**On screen.** A terminal: a signed token that already paid, sent again; the program's refusal (`E_REPLAY`); the
balance unchanged. The ledger, with the repeated evidence listed as a duplicate. *Caption: devnet.*

> Replay. A signed token, sent a second time: the program refuses it, because a token works once. The balance
> does not move. The same evidence entered twice in the ledger is listed as a duplicate and billed once. No
> second payment.

**Must be visible.** The error as the program returns it; the balance not moving; the duplicate, listed.

## 6. The payment executes (1:56, 31 seconds)

**On screen.** The transaction, and the supplier's balance before and after. The fee line of the pricing page, read
from the chain while it is recorded. Then `knos statement export` on the approved statement, and the file it
writes. If the bank instruction file of `knos statement pay --rail bank` is in the build being recorded, that file
is shown as well, with the caption "Written locally. No bank has taken this file." *Captions: replay; devnet.*

> The payment executes. A Solana program checks GitHub's signature itself and releases the posted amount to the
> supplier, in test money on devnet: no company holds it. The fee on screen is the one the program charges
> today, read from the chain. A buyer who pays by bank does not need the chain for that: the approved statement
> exports as a file its payables system imports, one bill for each accepted deliverable.

**Must be visible.** The transaction's signature, the two balances, the fee as the chain gives it, the export
command and its file.

## 7. A verifier that needs nothing from Knos (2:27, 33 seconds)

**On screen.** The receipt file, and a machine with the network off: `knos bundle verify` on that file alone, and
its verdict. If the stand-alone verifier of `knos archive make` is in the build being
recorded, its one file is run on the exported archive instead, in an empty folder. Then
[MANIFEST.md](../MANIFEST.md): each public program id, the build it runs and the commit it was built from. Then
the limits, as one line of text. Then the front door. *Caption: offline.*

> Last, someone who trusts neither side. With the network off, a verifier checks GitHub's signature and the hash
> of the terms from the receipt file alone. For whoever audits it: the deployment identity. One page ties each
> public program id to the build it runs and the commit it was built from. The limits, in one line: Solana
> devnet, test money, one person holds every key, no outside review, and nobody has paid. The next invoice is
> yours. Neither side keeps the count.

**Must be visible.** The network off, the verify command and its verdict; the manifest's table of program ids and
hashes; the one line of limits; the address of the site.

*On the day, which program ids each beat ran on is read again from `web/upgrades.json`. A beat that did not run on
the public program ids says where it ran, in its caption. A buyer, a pilot, an interview or revenue is said only if
it exists and the other party agrees to be named.*
