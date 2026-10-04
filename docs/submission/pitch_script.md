# Pitch (under three minutes)

Narration in the founder's own voice, about 430 words: a little under three minutes read aloud at an even pace. The times in the
headings are where each part starts at that pace. A number written out here is in `docs/facts.json` with its source,
and `python scripts/claims_check.py` checks it. A number that only the release run can measure is a slot,
`[[stat: name]]`: `python scripts/bench_docs.py --slots` lists the ones still open, and nothing is recorded until
they are filled.

## The measurement, and a payment (0:00)

*On screen: the Agent PR Index, then a merge on GitHub and its payment landing in the explorer.*

In 826 repositories I took the first pull request by a coding agent that said its tests pass. In 147 a check had
failed. In 80, a test or a build. Now this one: merged, and its author paid. From merge to paid took
24 seconds, the median over 36 payments on devnet. Nobody
approved that payment.

## The insight (0:23)

A description is not evidence, so nobody can pay an agent on its word. But GitHub already records the result: who
opened the pull request, what its checks concluded, who merged it. It signs statements about a workflow run, and a
Solana program can check that signature by itself. So money can move on GitHub's signature, not on the
seller's word.

## The product (0:47)

*On screen, one clip: a comment funds, a merge, the payment; then the workflow deleted, and the seller's own run.*

Knos pays for software work on signed acceptance. A buyer funds a work order with one comment and names the checks
that must pass. Those terms are fixed on chain before the work. When a pull request that meets them is merged, a
pinned workflow reads GitHub's record, GitHub signs the run, and the program pays the author in full. The buyer pays
the fee on top. If the buyer deletes the workflow after merging, the seller runs the pinned one himself and is still paid.

## Evidence (1:21)

It runs on Solana devnet, in test money. 1,617 tests pass. Refund, key expiry, the pause and a
time-locked upgrade were drilled against the deployed bytes. Outside funders so far: 0.

## Why now (1:33)

Billing per outcome has started. This September a vendor began charging per merged change, and it counts the merges
itself. Support agents are sold per resolution, counted by the seller. Nobody neutral counts. GitHub's signature is
a count neither side owns.

## The business (1:50)

Four lines. The check is free. Settlement: the funder pays two and a half percent on top. The meter: a neutral
count for vendors who bill per result, five cents an evaluation. Controls for organisations, by contract. The code
is MIT. A fork starts with no record: every payment, receipt and rank sits under these addresses. It has to run its
own relay and keep its own keys attested. Whether customers pay for that is unproven.

## The limits (2:20)

Devnet only. No outside security review. One person holds every upgrade key, behind a public
48-hour delay. In a private repository a buyer can still withhold. And GitHub signs that a workflow ran, not what
it read.

## The ask (2:35)

Three asks. A place in the accelerator. Design partners: two vendors that bill per merge and want
a count their customers trust. And an outside security review, so this can go to mainnet.

I'm drexthealpha. That is a pseudonym, and the work is public.

*Closing card:* Knos pays for software work on signed acceptance: terms fixed before the work, a GitHub-signed run attests they were met, a Solana program settles.
