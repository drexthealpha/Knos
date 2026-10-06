# Buyer-interview kit

A kit for the founder: whom to talk to, what to ask, the tally, and a one-page letter of intent to offer at the
end of a conversation that went well. **No conversation has happened yet.**

The aim is to learn whether the person who approves a supplier's invoice for software work wants a count that
neither side keeps, and whether a supplier wants acceptance terms that cannot be changed after the work.

## The tally

| what | count |
|---|---|
| People asked for a conversation | 0 |
| Conversations held with a buyer | 0 |
| Conversations held with a supplier | 0 |
| Said no to the trial, with a reason | 0 |
| Said no to the trial, with no reason | 0 |
| Said yes to a shadow count | 0 |
| Shadow counts run on a real invoice | 0 |
| Letters of intent signed | 0 |

The rules of the tally:

- **A no is counted.** Every conversation adds to a row on the day it happens, and a no adds to its row exactly
  as a yes does. The reasons given for a no are published with the count, in the person's words, without a name.
- A person who did not answer is counted in the first row and in no other.
- A polite "interesting" is neither a yes nor a no: it adds to "held" and to nothing else.
- A row changes only with the other party's agreement to be counted. Three rows are also constants in
  `docs/facts.json` (`by_hand`: buyer interviews, shadow counts, letters of intent), and
  [NUMBERS.md](NUMBERS.md) is written from them; `tests/test_business_docs.py` fails when this table and those
  constants differ.

## The ten kinds of organisation to talk to

Buyers first, because the buyer has the budget. For each: who to ask for, and why they might care.

| | kind of organisation | the person | why they might care |
|---|---|---|---|
| 1 | A company that buys agent-made changes from a vendor that bills per merged change | the engineering leader who signs off the vendor's invoice | the invoice rests on the vendor's own count |
| 2 | The same company's finance side | the finance owner or controller who approves the spend | has to explain each line to an auditor |
| 3 | A vendor that bills per merged change or per accepted task | the head of product or of revenue | a customer who disputes the count; a neutral count as something to sell with |
| 4 | A software agency or outsourcer paid per milestone | the delivery lead | acceptance terms that change after delivery; late payment |
| 5 | A company that buys from such an agency | the engineering manager who accepts the milestones | "done" argued in email |
| 6 | A team that runs its own fleet of coding agents and charges product teams for it | the platform lead | an internal count the product teams accept |
| 7 | A protocol team or foundation that pays grants on shipped milestones | the grants lead | judging every submission by hand |
| 8 | A team that runs a bug bounty or an audit contest | the security lead | paying strangers per outcome already, in stablecoins |
| 9 | An open-source company that posts bounties on its issues | a maintainer with a budget | the smallest case: review time and low-quality submissions |
| 10 | A marketplace or platform where agents take paid work | the founder or product lead | an acceptance step it does not want to build or to be the judge of |

Where to find them: the vendors publish that they bill per outcome ([MARKET.md](../MARKET.md), section 2), and
their customers appear in their public case studies; foundations and bounty programmes list their sponsors
publicly. Ask for twenty minutes. Do not pitch in the first fifteen.

## The five questions

Ask about what they did last time, not what they would do. Write down their words.

1. **"Take the last invoice you approved, or sent, for software work priced per result. How was the number of
   results on it arrived at, and who checked it?"**
   Listen for: whose system produced the count; whether anyone on the other side could reproduce it.
2. **"Tell me about the last time the two sides did not agree that something was done, or how many were done. What
   happened, and how long did it take?"**
   Listen for: a real dispute with a date and a cost. If there has never been one, say so in the notes: that is the
   most important answer in the kit.
3. **"What were the acceptance terms, where were they written down, and did they change after the work started?"**
   Listen for: terms in a contract annex, in a ticket, in someone's head; who could change them.
4. **"Who has to approve it before it is paid, and what do they need to see? What would they refuse to sign?"**
   Listen for: the budget owner; finance, security and procurement requirements; a private repository; a named
   party that answers for the service; where the data may live.
5. **"If both sides could compute the same count from the CI record, with the terms fixed before the work, what
   would that be worth to you in a month, and whose budget would pay for it?"**
   Listen for: a number and a budget line, or the honest absence of one. Then show the thing, not before.

After the fifth question, and only then, show the claim check and one statement that two sides computed. Ask:
"Would you run this beside your next invoice for a month, at no cost?" Offer the letter only if they say yes.

What to write down afterwards, the same day: the date, the kind of organisation (not its name, unless they agreed),
the five answers in their words, yes or no to the trial, and yes or no to the letter.

## What not to do

- Do not count a conversation as demand. Count a signed letter as intent and an invoice paid as demand.
- Do not name anyone in public without their written agreement.
- Do not promise mainnet, an audit, a team or a date that does not exist. The limits are in
  [MARKET.md](../MARKET.md) and [SECURITY.md](../SECURITY.md); hand them over.

## Letter of intent (template, one page)

A letter of intent here is not a contract. It says what the signer means to try, and it binds nobody to pay.
Fill in the brackets; delete what does not apply; change nothing else without saying so to the signer.

> **Letter of intent: a trial of a neutral count for work priced per outcome**
>
> Date: [date]
>
> From: [organisation], [name and role of the person signing]
>
> To: the maintainer of Knos (github.com/drexthealpha/Knos)
>
> 1. **What we do today.** We [buy / sell] software work priced per [merged change / accepted task / milestone]
>    [from / to] [kind of counterparty; a name only if they agree]. The count on the invoice is produced by
>    [whom].
>
> 2. **What we intend to try.** For [one month / one billing period], starting on or about [date], we intend to
>    run the Knos count beside our existing invoice for [repository, project or contract], on Solana devnet, and to
>    compare the two counts at the end. Nothing about our existing invoicing changes during the trial.
>
> 3. **What we would need before using it for real.** [For example: private repositories; an outside security
>    review; a legal entity to contract with; invoices in our currency; data kept in our own storage.]
>
> 4. **What it would be worth.** If the trial shows [the result that would matter to us], we would consider paying
>    for it [from which budget; a range if we can give one, or "not yet known"].
>
> 5. **What this letter is not.** It is not a contract, a purchase order or a commitment to pay. No money moves
>    under it. The trial runs on a test network with test tokens. Either side can stop at any time, for any reason.
>    Knos is one person's open-source project, with no company behind it today, no outside security review and no
>    legal advice taken; we have been told so.
>
> 6. **Naming.** Knos [may / may not] say publicly that [organisation] signed this letter. Knos [may / may not]
>    publish the two counts of the trial, [with / without] our name.
>
> Signed: [name], [role], [organisation]
