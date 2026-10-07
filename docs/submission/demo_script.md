# Demo (three minutes): one story in six beats

**The neutral meter for AI agent work: neither side keeps the count.**

One continuous technical demonstration, the story of [STORY.md](../STORY.md): an invoice that does not reconcile; one
deliverable set up with its buyer, supplier, terms and price; a tampered submission refused; legitimate work
accepted; a replay and a conflicting judgment that change nothing; and two parties who rebuild the same bill, which
an outside consumer then verifies. The presentation is a separate page ([pitch_script.md](pitch_script.md)).

The spoken words are the lines that start with `>`: about 420 words, which is three minutes
(`tests/test_business_docs.py` counts them). A spoken number is in `docs/facts.json`.

## Four rules for the recording

- **Every step says on which program ids it ran.** `web/upgrades.json` and [MANIFEST.md](../MANIFEST.md) are read on
  the day, not this page. A step that ran on staging program ids carries the caption "Staging program ids on Solana
  devnet" for its whole length, and a step that ran in the local simulator carries "Local simulator: not devnet". No
  step is shown as a run on the public program ids that did not run there.
- **A step whose capability has run nowhere is cut, not staged.** The table below gives each capability's stage
  from `docs/capabilities.json`. The narration of the steps that remain is not changed to cover for a cut one.
- **A replay says it is a replay, and a faster recording says how much faster.** A shot of a run made earlier
  carries the caption "Replay of a run recorded earlier", with the run's address, for its whole length. A shot
  played faster than it happened carries "Recorded at N times speed" for its whole length. A workflow run takes
  longer than these beats, so beats three and four are replays at higher speed and carry both captions. The
  measured times are on the site's Numbers page, not in this video.
- **Everything shown is the real thing, and the money is test USDC.** A settlement carries the caption "Solana
  devnet. Test USDC." for its whole length. Each transaction shown can be found afterwards on the Numbers page
  (https://drexthealpha.github.io/Knos/#network), which is read from the programs' own logs.

Caption under the first shot, no narration: "Built during the hackathon: everything shown. Older work is listed in
docs/DISCLOSURE.md." The invoice of beat one is the site's sample: a made-up invoice from a made-up supplier, and
the screen says so. No real invoice has been run with anyone.

| beat | starts | ends | what it shows |
|---|---|---|---|
| one | (0:00) | (0:20) | an invoice that does not reconcile: seven lines, five exceptions |
| two | (0:20) | (0:45) | the deliverable, the authorised buyer, the supplier, the acceptance terms and the price |
| three | (0:45) | (1:25) | a tampered submission, the exact refusal and its evidence |
| four | (1:25) | (1:55) | legitimate work accepted, and the commercial record created |
| five | (1:55) | (2:25) | a replay and a conflicting judgment: no duplicate obligation or payment |
| six | (2:25) | (3:00) | buyer and supplier rebuild the same statement; an outside consumer verifies the receipt |

## The stage of each capability a beat needs

The last column is not typed: `python scripts/doc_claims.py --write` writes it from `docs/capabilities.json`, and
the check fails when it differs. No count of capabilities is given here; [CAPABILITIES.md](../CAPABILITIES.md) has
every one, and [MANIFEST.md](../MANIFEST.md) ties each to the build that is live.

| beat | capability | stage |
|---|---|---|
| one | `front_door` | tested locally |
| one | `shadow_mode` | tested locally |
| two | `fund_by_comment` | deployed on devnet |
| two | `work_orders` | exercised on devnet |
| three | `tests_mode` | exercised on devnet |
| three | `refusal_table` | tested locally |
| four | `honest_work_rate` | tested locally |
| four | `pay_on_merge` | deployed on devnet |
| four | `order_pay` | exercised on devnet |
| four | `four_verdicts_four_ids` | tested locally |
| five | `single_use_tokens` | exercised on devnet |
| five | `ledger_dedup` | tested locally |
| five | `order_quorum` | tested locally |
| six | `statements` | tested locally |
| six | `verify_without_chain` | tested locally |

## 1. An invoice that does not reconcile (0:00, 20 seconds)

**On screen.** The number. Then the site's first screen: "Try a sample" fills the box with an invoice of seven
lines, billed per merged pull request, and Check answers it: `Checked 7 lines. 5 exceptions.` The mark "Sample: a
made-up invoice from a made-up supplier." stays on screen.

> Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check. Here is what that does to
> an invoice. Seven lines, billed per merged pull request. Checked against GitHub's own record, two lines agree
> and five are exceptions. The supplier kept this count.

**Must be visible.** The seven lines in their groups, the five exceptions with their reasons, and the sample's mark.

## 2. The deliverable and its terms (0:20, 25 seconds)

**On screen.** An issue: the deliverable. The buyer's comment that funds it, and the reply: the order, its budget,
the acceptance terms and their hash. The account that funded it, and the supplier who takes it.

> So set one deliverable up before the work starts. The buyer authorises it with one comment: the price, and the
> acceptance terms, a suite of checks the supplier cannot edit. The terms are hashed into the order when it is
> funded. The supplier is whoever takes the issue. After that nobody can change them, not even the buyer.

**Must be visible.** The issue, the funding comment and who wrote it, the price, the terms and their hash.

## 3. A tampered submission is refused (0:45, 40 seconds)

**On screen.** A pull request that leaves the bug in place and edits the test that already existed. Plain CI:
green. The judge's comment: "The change edits or deletes a test that already existed.", with the file, the rule's
code `judge.existing-test-edited` and what to do next. The order's balance, unchanged. *Captions:
replay; speed.*

> First, a cheat. This submission does not fix the bug. It edits the test that already existed, so plain CI goes
> green. The judge takes the acceptance checks from the buyer's branch, as funded, and never from the submission.
> It refuses, in these words: the change edits or deletes a test that already existed. The refusal names the
> rule and the file, and tells the supplier what to do next. No money moves. In our benchmark 56 of
> 63 cheating pull requests passed plain CI, and the black-box check refused all 63.

**Must be visible.** The edited test, the green CI, the refusal word for word with its code, and the unchanged
balance.

## 4. Legitimate work is accepted (1:25, 30 seconds)

**On screen.** A second pull request: the fix, and a regression test of its own in a new file. The same judge:
accepted. The transaction, and the supplier's balance before and after. Then the record: the deliverable, the
evaluation, the invoice line and the settlement, each with its id. *Captions: replay; speed; devnet.*

> Now legitimate work. A second submission fixes the bug and brings its own regression test, in a new file. The
> same judge runs the same checks and accepts. GitHub signs that run. A Solana program checks the signature
> itself and releases the posted amount to the supplier, in test money on devnet. That acceptance is the
> commercial record: one deliverable, one evaluation, one invoice line, one settlement.

**Must be visible.** The fix and the added test, the verdict, the transaction's signature, the two balances, and
the four ids.

## 5. A replay and a conflicting judgment (1:55, 30 seconds)

**On screen.** A terminal: the token that paid beat four, sent again; the program's refusal (`E_REPLAY`); the
balance unchanged. The ledger, with the repeated evidence listed as a duplicate. Then an order that asks for two
judges: one judge's verdict alone, and two runs started by one account; nothing is paid. *Caption on the quorum
shots: simulator.*

> The same signed token, sent a second time: the program refuses it, because a token works once, and the balance
> does not move. The same evidence entered twice in the ledger is listed as a duplicate and billed once. Then a
> conflicting judgment. This order asks for two independent judges. One judge alone moves nothing, and one
> account that starts both runs counts as one judge. No second obligation, and no second payment.

**Must be visible.** The error as the program returns it; the balance not moving; the duplicate, listed; the
quorum's refusal, and the order's money still held.

## 6. Two parties, one bill, and an outside check (2:25, 35 seconds)

**On screen.** Two terminals, buyer and supplier, each running `knos meter reconcile` on its own ledger: the same
statement and the same digest. Then a third machine with the network off: `knos bundle verify` on the receipt
file alone, and its verdict. Then the front door. *Caption on the third machine: offline.*

> Last, the bill. At the end of the month the buyer and the supplier each rebuild the statement from their own
> copy of the ledger: the same lines, the same total, the same digest. Then someone who trusts neither. With
> only the receipt file, and the network off, they check GitHub's signature and the hash of the terms, and reach
> the same verdict. All of this ran on Solana devnet, in test money, and nobody has paid for it yet. The next
> invoice is yours. Neither side keeps the count.

**Must be visible.** The two commands, the two digests, equal; the offline check and its verdict; the address of
the site.

*On the day, which program ids each beat ran on is read again from `web/upgrades.json`. The two-judge refusal for
runs started by one account is in the knos_pay build of this release, which is not the build at the public id:
until it is, that shot runs in the local simulator and says so. A buyer, a pilot, an interview or revenue is said
only if it exists and the other party agrees to be named.*
