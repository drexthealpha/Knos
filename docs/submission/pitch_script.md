# Pitch (under three minutes, seven beats)

**The neutral meter for AI agent work: neither side keeps the count.**

Buyers and suppliers verify what AI work earned payment, then carry that evidence from authorisation through invoice approval to settlement.

The presentation: the buyer, the problem, the insight, the evidence, the team, the business, and the limits in one
sentence. The technical demonstration is a separate page ([demo_script.md](demo_script.md)): one transaction in
seven beats, from the agreement through a refused submission to a verifier that needs nothing from Knos. What is on
screen here is cut from those beats, in their order, and a clip keeps its captions. A judge's one page is
[JUDGES.md](../JUDGES.md).

The spoken words are the lines that start with `>`: about 420 words, under three minutes read aloud at an even pace
(`tests/test_site_scripts.py` counts them). The time in each heading is where the beat starts.

A spoken number is in `docs/facts.json` with its source, and `python scripts/claims_check.py` checks it. Beat four
is read against the chain and [NUMBERS.md](NUMBERS.md) on the day of recording and says the numbers as they are
then. **No fee is spoken as a number**: the public program ids charge what the build live there charges, which
changes when an approved upgrade executes, so beat six shows the fee read from the chain while it is recorded. A buyer, a pilot or an interview is said only if it exists and the other party agrees to be named. The limits
are one sentence, the last one, and no number is read out as a list; every limit is in
[DISCLOSURE.md](../DISCLOSURE.md) and every count in [NUMBERS.md](NUMBERS.md).

## 1. The buyer (0:00)

*On screen: the number; then an invoice for agent work, seven lines, and the person who approves it.*

> Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check. Each was merged anyway.
> Our buyer is the person who approves a supplier's invoice for agent work, and answers for it. With Knos,
> buyers and suppliers verify what AI work earned payment, then carry that evidence from authorisation through
> invoice approval to settlement.

## 2. The problem (0:28)

*On screen: two counts of the same month, side by side, that differ.*

> That person cannot tell which lines were delivered. The supplier, who did deliver, cannot prove it. So an
> invoice stays open while two companies argue over whose count is right.

## 3. The insight (0:40)

*On screen, demo beats one to three and six: the agreement; the refused submission with its reason, the balance
unchanged; the corrected one accepted; the payment.*

> Every vendor keeps its own count. The seller meters the work, and the seller writes the bill. Knos is the
> neutral meter for AI agent work: neither side keeps the count. The buyer fixes the price and the acceptance
> terms before the work starts. GitHub signs the run that judged it. A Solana program checks that signature
> itself and releases the money: no company holds it, and no oracle reports it. Why Solana? Money is released
> with no custodian, and the count is anchored where neither side can alter it. Buyers and suppliers close
> invoices on evidence both can verify.

## 4. The evidence (1:20)

*On screen, demo beats two, four, five and seven: the refusal word for word; the two terminals with one statement;
the refused replay; the verifier with the network off; then the Numbers page.*

> What we measured. A submission that edits the test instead of fixing the bug: plain CI passed 56 of 63 such
> cheats, and the black-box check refused all 63. Buyer and supplier each rebuild the statement from their own
> ledger and get the same bill, line for line. From merge to paid took 25 seconds at the median, on devnet. But
> an invoice waits on the person who approves it, not on the payment, and we have not measured that wait with a
> buyer. And outside me: one other GitHub account was paid 3 times on devnet, in test money, for pull requests
> it wrote on tasks I funded.

## 5. The team (2:05)

*On screen: the dated history in DISCLOSURE.md.*

> The team is one founder. I shipped all of it: the programs, the judge, the ledger and the site. I own
> commercial, security and operations as well, and today nobody else does. Before the hackathon period I had
> built a different product, a shared memory for coding agents; this one was written inside the period.

## 6. The business (2:27)

*On screen: the price book, and the fee the public program ids charge today, read from the chain.*

> The business is one fee. The check is free. Knos earns when value is released against a signed acceptance:
> a fee the program collects, paid by the funder on top. The rate on screen is the one the program charges
> today. The supplier never pays.

## 7. The limits (2:45)

*On screen: the limits as one line; then the front door.*

> The limits, in one sentence: Solana devnet, test money, one person holds every key, no outside review, and
> nobody has paid.

*Closing card:* The neutral meter for AI agent work: neither side keeps the count. Below it, the second line:
buyers and suppliers verify what AI work earned payment, then carry that evidence from authorisation through
invoice approval to settlement.
