# Pitch (under three minutes, six beats)

Narration in the founder's own voice, about 520 words: under three minutes read aloud at an even pace. The times in
the headings are where each beat starts at that pace. The order is deliberate: the buyer and the problem first,
what the product does for them second, who has said yes, the business, and only then how it works. The
cryptography is the last thing explained, not the first.

A number written out here is in `docs/facts.json` with its source, and `python scripts/claims_check.py` checks it.
A number that only the release run can measure is a slot, `[[stat: name]]`: `python scripts/bench_docs.py --slots`
lists the ones still open, and nothing is recorded until they are filled.

The third beat is written to be true on the day it was written. Read it against the chain on the day of recording
(the checklist in [SUBMISSION.md](SUBMISSION.md)), and change it only to what is true then.

The second beat's clip is cut from the demo. What it shows must be at the stage
[`docs/capabilities.json`](../capabilities.json) gives on the day, and on the program ids `web/upgrades.json` says
are live; what is not is cut from the clip and from the narration ([demo_script.md](demo_script.md) has the rule).

## 1. The buyer, and the problem (0:00)

*On screen: a supplier's invoice with a line "merged pull requests", and a person about to approve it.*

Somebody has to approve this invoice, and defend it afterwards. Software work is starting to be sold per outcome:
per merged change, per resolution. The supplier counts the outcomes, and the buyer pays on the supplier's count.
I measured what that count can hide. Of 241 merged pull requests by coding agents whose description said the
tests pass, 30 had a failed check at that commit. That is 12.4%. The person approving the invoice cannot see
that.

## 2. What they get (0:35)

*On screen, one clip from the demo: an order created, a submission refused with the unmet condition named, a valid
one accepted, the two statements side by side.*

Knos lets them close that invoice with evidence both sides can check. The buyer writes down, before the work,
what is being bought and what decides that it is done. A submission that says it passed and did not is refused,
and the refusal names the condition. A valid one is accepted, once, however the work was split. At the end of the
month the buyer and the supplier each compute the statement from their own records and get the same one. What
they disagree about shows up as a dispute, by name, not as a line on the invoice.

## 3. Who said yes (1:10)

*On screen: the site's Numbers page, the rows for accounts that are not Knos's.*

Here is who has said yes, counted from the chain. Funders other than Knos, with their own tokens: 0. One outside
account has been paid, for 3 pull requests, on tasks I funded myself. Buyers interviewed: none. Pilots: none.
Revenue: none.

## 4. The business (1:28)

*On screen: the price book.*

Checking is free, and it is the distribution. What I can sell today is software: a 30-day pilot for 2,500 dollars
that reconciles one buyer's invoices from its suppliers, then a yearly contract from 25,000. The first milestone
is 40 organisations at that price. Everything on chain is devnet and test money, so settlement earns nothing
real, and I do not count it. Nobody has bought anything, and there is no company yet to send an invoice.

## 5. How it works (1:58)

*On screen: the receipt, then the transaction in the explorer.*

The forge already records each result and signs statements about a CI run. A Solana program checks that signature
itself, then counts the outcome or pays the supplier. From merge to paid took 25 seconds at the median, over 39
payments on devnet. Each signed token is accepted once. What is still trusted
is on the receipt: the forge signs which workflow ran, not what it read.

## 6. The founder, and what is missing (2:20)

*On screen: the repository, then docs/TEAM.md.*

I'm drexthealpha. That is a pseudonym, and the work is public. I built this alone, with coding agents, because my
own agents told me the tests passed when they had not. I have not sold to the person who approves that invoice.
So the plan names three people it needs first: someone who has sold to engineering or finance leaders, a security
lead to run an outside review, and someone for partnerships with agent vendors. None is hired. In the next ninety
days: the conversations, one pilot, and the review.

*Closing card:* Knos is the neutral count and settlement for software work priced per outcome: terms fixed before the work, a signed CI run attests they were met, a Solana program counts it or pays it.
