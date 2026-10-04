# Weekly update (one minute)

Narration in the founder's own voice, about 140 words, over one screen recording. The number in the second part is
a slot, `[[stat: name]]`, filled from the release run.

## What shipped (0:00)

*On screen: the price book, then the two counts of one month side by side on chain.*

This week I changed what Knos is for. It is the neutral count and settlement for software work priced per outcome.
The buyer is the person who approves a supplier's invoice. I shipped a count that needs no money on chain, where
the supplier's own count sits beside the buyer's, and fees in tiers so that a large order pays a smaller share.

## One number (0:25)

*On screen: the site's Numbers page.*

From merge to paid took 25 seconds at the median, on devnet.

## The hardest problem, and the decision (0:30)

*On screen: the section of docs/SECURITY.md that says what holds now.*

Before the new build went live, a defect was found in it: one pay token could pay a re-funded order twice. The fix
is one rule for every token. This release cancels that upgrade and puts the fixed build through my own 48-hour delay.

## Next week (0:48)

Conversations with the people who approve these invoices. None has happened yet.
