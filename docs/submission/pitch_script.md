# Pitch (under three minutes, nine beats)

**The neutral meter for AI agent work: neither side keeps the count.**

The presentation: the customer, the insight, what was observed, the model, the founder. The technical
demonstration is a separate page ([demo_script.md](demo_script.md)), and a clip cut from it keeps its captions.

The spoken words are the lines that start with `>`: about 410 words, just under three minutes read aloud at an even pace
(`tests/test_business_docs.py` counts them). The time in each heading is where the beat starts.

A spoken number is in `docs/facts.json` with its source, and `python scripts/claims_check.py` checks it. Beat seven
is read against the chain and [NUMBERS.md](NUMBERS.md) on the day of recording and says the numbers as they are
then. A buyer, a pilot or an interview is said only if it exists and the other party agrees to be named. The limits
are one sentence, the last one; every one of them is in [DISCLOSURE.md](../DISCLOSURE.md).

## 1. The number (0:00)

*On screen: the number, then one public pull request from the sample: its description says the tests pass, it is
merged, and a check is red.*

> Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check. Each was merged anyway.

## 2. The customer (0:10)

*On screen: an invoice for agent work, seven lines; the person who approves it; the supplier who sent it.*

> Two people have this problem. One approves a supplier's invoice for agent work and cannot tell which lines were
> delivered. The other is the supplier, who did deliver and has to prove it.

## 3. The insight (0:25)

*On screen: two counts of the same month, side by side, that differ.*

> Every vendor keeps its own count. The seller meters the work, and the seller writes the bill. Knos is the
> neutral meter for AI agent work: neither side keeps the count.

## 4. A round (0:40)

*On screen, from the demo: the funding comment, the pull request with its regression test, the acceptance, the
payment; then two terminals with one statement.*

> One round. A buyer fixes the price and the acceptance terms before the work starts, with one comment. A
> supplier submits a fix with its own regression test. GitHub signs the run that judged it. A Solana program
> checks that signature itself and releases the money: no company holds it, and no oracle reports it. At the
> end of the month the buyer and the supplier each rebuild the statement from their own ledger, and they get the
> same bill, line for line.

## 5. The cheat (1:15)

*On screen: the refused submission with its reason; the balance unchanged.*

> Now a cheat: a submission that edits the test instead of fixing the bug. Plain CI passed 56 of 63 such
> cheats. Knos refused all 63, and each refusal says why.

## 6. The leaderboard (1:30)

*On screen: the Agent PR Index on the site's first screen; one row's dispute link; a supplier's record and badge.*

> This is the Agent PR Index: every week, for each coding agent, how often "tests pass" agreed with GitHub's own
> checks. No vendor can pay for a row, and any row can be disputed in public. A supplier with a good record gets
> it signed, to attach to an invoice.

## 7. Outside the founder (1:50)

*On screen: the nine rows of the site's Numbers page, as they are.*

> What exists outside me today. One other GitHub account was paid 3 times on devnet, in test money, for pull
> requests it wrote on tasks I funded. Outside funders: 0. Outside repositories: 0. Buyers interviewed: 0.
> Independent reproductions: 0. Those numbers are read from the chain and the repository, not from me.

## 8. The model (2:10)

*On screen: the price book.*

> The model is one fee. The check is free. Knos earns when value is released against a signed acceptance: thirty
> cents on every hundred dollars, collected by the program, paid by the funder on top. The supplier never pays.
> It starts with code, because a forge already signs its checks.

## 9. The founder, and the limits (2:30)

*On screen: the dated history in DISCLOSURE.md; then the front door.*

> I work with coding agents every day, and mine told me tests passed that had not. I measured it, then built
> this. Before the hackathon period I had built a different product, a shared memory for coding agents; this
> one was written inside the period. The limits, in one sentence: Solana devnet, test money, one person holds
> every key, and nobody has paid.

*Closing card:* The neutral meter for AI agent work: neither side keeps the count.
