# Pitch (under three minutes, five beats)

Narration in the founder's own voice, about 480 words: under three minutes read aloud at an even pace. The times in
the headings are where each beat starts at that pace. A number written out here is in `docs/facts.json` with its
source, and `python scripts/claims_check.py` checks it. A number that only the release run can measure is a slot,
`[[stat: name]]`: `python scripts/bench_docs.py --slots` lists the ones still open, and nothing is recorded until
they are filled.

The third beat is written to be true on the day it was written. Read it against the chain on the day of recording
(the checklist in [SUBMISSION.md](SUBMISSION.md)), and change it only to what is true then.

The second beat's clip shows terms hashed into a work order, which devnet runs only once the upgrade has executed.
[`docs/capabilities.json`](../capabilities.json) is the index: what the clip shows must be at "exercised on devnet"
there on the day, and what is not is cut from the clip and from the narration. The last sentence of that beat says
what is tested and not yet on devnet; it is dropped, item by item, only as the manifest moves.

## 1. The problem, with a number (0:00)

*On screen: a supplier's invoice with a line "merged pull requests", then the measurement.*

Software work is starting to be sold per outcome: per merged change, per resolution. The seller counts the
outcomes, and the buyer approves the invoice on the seller's count. I measured what that count hides. Of 241
merged pull requests by coding agents whose description said the tests pass, 30 had a failed check at that commit.
That is 12.4%. A vendor that bills per merge bills for those. The person approving the invoice cannot see it,
and the supplier has no terms it can hold the buyer to either.

## 2. The demo (0:35)

*On screen, one clip: terms set, a submission refused with the failed check named, a valid one paid, the same token
refused the second time.*

Knos is the neutral count and settlement for software work priced per outcome. The buyer fixes the terms before
the work: the checks that must pass and the paths that may change. They are hashed into the order. A submission
that says it passed and did not is refused, and the refusal names the check. A valid one is merged; the forge signs
the CI run; a Solana program verifies that signature itself and pays the seller in full. From merge to paid took
25 seconds at the median, over 38 payments on devnet. Send the same token again and
it pays nothing. Tested and not yet on devnet: an order that pays an agent's passing pull request with no merge
and no person in between, and a batched count with the supplier's count beside the buyer's.

## 3. Who said yes (1:28)

*On screen: the site's Numbers page, the row for funders who are not Knos.*

Here is who has said yes, counted from the chain. Funders other than Knos, with their own tokens: 0. Of the
payments on devnet, 3 went to an outside contributor, for tasks Knos funded itself. Interviews with buyers: none
yet. Letters of intent: none yet. Paying pilots: none yet. The questions I will ask, and whom, are in the
repository.

## 4. The business (1:58)

*On screen: the price book.*

The check is free, and it is the distribution. The count comes first, because it needs no customer money on chain:
five cents an attested evaluation, two under a committed plan, and a yearly contract for an organisation.
Settlement is second: two and a half percent, falling in tiers, paid by the funder on top. Capital is third.
The code is MIT. A fork can copy the code and the fee. It cannot copy neutrality, the record, a contract with
someone accountable, or capital, and I have little of each today. It is devnet and test money, and nobody has
bought anything.

## 5. The founder, and the next ninety days (2:33)

*On screen: the repository, then the plan.*

I'm drexthealpha. That is a pseudonym, and the work is public. I built this alone, with coding agents, because my
own agents told me the tests passed when they had not. In the next ninety days: ten conversations with people who
approve these invoices and vendors who send them, and the count of who said yes, published. One vendor running the
meter beside its own invoices. An outside security review. And keys and workflows moved from one person's account
to an organisation with a second key holder.

*Closing card:* Knos is the neutral count and settlement for software work priced per outcome: terms fixed before the work, a signed CI run attests they were met, a Solana program counts it or pays it.
