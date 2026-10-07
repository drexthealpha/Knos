# Pitch (under three minutes, seven beats)

**The neutral meter for AI agent work: neither side keeps the count.**

The presentation: the buyer, the problem, the insight, the evidence, the team, the business, and the limits in one
sentence. The technical demonstration is a separate page ([demo_script.md](demo_script.md)), and a clip cut from it
keeps its captions.

The spoken words are the lines that start with `>`: about 340 words, about two and a half minutes read aloud at an even pace
(`tests/test_site_scripts.py` counts them). The time in each heading is where the beat starts.

A spoken number is in `docs/facts.json` with its source, and `python scripts/claims_check.py` checks it. Beat four
is read against the chain and [NUMBERS.md](NUMBERS.md) on the day of recording and says the numbers as they are
then. A buyer, a pilot or an interview is said only if it exists and the other party agrees to be named. The limits
are one sentence, the last one, and no number is read out as a list; every limit is in
[DISCLOSURE.md](../DISCLOSURE.md) and every count in [NUMBERS.md](NUMBERS.md).

## 1. The buyer (0:00)

*On screen: the number; then an invoice for agent work, seven lines, and the person who approves it.*

> Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check. Each was merged anyway.
> Our buyer is the person who approves a supplier's invoice for agent work, and answers for it.

## 2. The problem (0:20)

*On screen: two counts of the same month, side by side, that differ.*

> That person cannot tell which lines were delivered. The supplier, who did deliver, cannot prove it. So an
> invoice stays open while two companies argue over whose count is right.

## 3. The insight (0:40)

*On screen: the refused submission with its reason, the balance unchanged; then the accepted one and the payment.*

> Every vendor keeps its own count. The seller meters the work, and the seller writes the bill. Knos is the
> neutral meter for AI agent work: neither side keeps the count. The buyer fixes the price and the acceptance
> terms before the work starts. GitHub signs the run that judged it. A Solana program checks that signature
> itself and releases the money: no company holds it, and no oracle reports it. Buyers and suppliers close
> invoices on evidence both can verify.

## 4. The evidence (1:15)

*On screen, from the demo: the refusal word for word; the two terminals with one statement; the Numbers page.*

> What we measured. A submission that edits the test instead of fixing the bug: plain CI passed 56 of 63 such
> cheats, and Knos refused all 63, each with its reason. Buyer and supplier each rebuild the statement from
> their own ledger and get the same bill, line for line. And outside me: one other GitHub account was paid 3
> times on devnet, in test money, for pull requests it wrote on tasks I funded.

## 5. The team (1:50)

*On screen: the dated history in DISCLOSURE.md.*

> The team is one founder. I shipped all of it: the programs, the judge, the ledger and the site. I own
> commercial, security and operations as well, and today nobody else does. Before the hackathon period I had
> built a different product, a shared memory for coding agents; this one was written inside the period.

## 6. The business (2:15)

*On screen: the price book.*

> The business is one fee. The check is free. Knos earns when value is released against a signed acceptance:
> thirty cents on every hundred dollars, collected by the program, paid by the funder on top. The supplier
> never pays.

## 7. The limits (2:35)

*On screen: the limits as one line; then the front door.*

> The limits, in one sentence: Solana devnet, test money, one person holds every key, no outside review, and
> nobody has paid.

*Closing card:* The neutral meter for AI agent work: neither side keeps the count.
