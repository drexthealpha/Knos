# How the submission answers what the judges ask

Colosseum's hackathon page lists seven factors its judges weigh
([colosseum.com/hackathon](https://colosseum.com/hackathon), read 5 Oct 2026; the question under each heading
below is quoted from it). The same page says teams "must disclose all relevant past development work in the
submission form"; that is [DISCLOSURE.md](../DISCLOSURE.md). The official rules list six criteria as well. Each
gets one paragraph here: what the submission can show, and what it cannot. Where the honest answer is "not yet",
that is the answer.

No count of capabilities is given on this page. How far each capability has got (implemented, tested, deployed,
exercised on devnet, reproduced by someone else) is in [CAPABILITIES.md](../CAPABILITIES.md), written from
[`docs/capabilities.json`](../capabilities.json), and which builds are live on the public program ids is in
`web/upgrades.json`.

## The seven factors on Colosseum's page

### Founder + Market Fit

> "Does the team have the right skills and experience to succeed in this market, and why is it motivated to solve
> this problem?"

Evidence only. For: one person shipped everything in this repository, with coding agents, in public, and the
dated history is in [DISCLOSURE.md](../DISCLOSURE.md) and [TEAM.md](../TEAM.md); he works with coding agents every
day, which is where the problem comes from, since his own agents reported passing tests that had not passed; he
measured that problem on public data before building for it ([BENCH.md](../BENCH.md)); and he found and disclosed
a double-payment defect in his own build during its upgrade delay, before it ran
([SECURITY.md](../SECURITY.md), section 15). Against: he is pseudonymous; he has never sold to an engineering or
finance leader, who is the buyer; he has not spoken to one about this; he has run no security review and no
service for a customer. So the fit is with the supplier's side of this market and with the engineering, and not
yet with the buyer's side. [TEAM.md](../TEAM.md) names the three roles the plan needs first and says that none is
hired or committed.

### Insight

> "Does the founding team have some unique insight based on their deep understanding of the problem space?"

Work is starting to be priced per outcome, and the seller keeps the count. For code, unlike for support tickets, a
third party already records the outcome and signs statements about it: the forge records the merge and the checks
and signs a CI run. So the count can belong to neither side. We measured why it matters: of 241 merged agent pull
requests whose description said tests pass, 30 had a failed check at the head commit
([BENCH.md](../BENCH.md)). The second half of the insight is about what is bought: the unit is a deliverable, an
order and a milestone, and not a pull request, so that splitting one piece of work into many pull requests does
not multiply the bill. The limit is stated wherever the insight is used: the forge signs which workflow ran, not
what it read. Whether buyers object to the seller's count enough to pay for another is not known.

### Product + Execution

> "How well does the product work? How does it stack up against the competition?"

On the public program ids on devnet, in test USDC, a task is funded by a comment, a submission whose required
check failed is refused with the check named, a valid one is paid on the forge's signature, and an unfulfilled
task refunds without anyone's permission. Work orders, the batched count with the supplier's own count beside the
buyer's, funding by passkey and the single-use rule for every token were rehearsed on staging program ids, which
are not the public ones, so the manifest holds them at "tested locally"; they reach the public ids only when their
approved upgrade proposals execute, and `web/upgrades.json` says whether they have. [CAPABILITIES.md](../CAPABILITIES.md) gives the stage of each, and the demo cuts any shot whose
capability is not at the stage it needs on the day. Against the competition ([COMPARE.md](../COMPARE.md)):
MergePay is on a mainnet with real USDC and no platform fee, and is ahead there; its condition is the merge
alone. Knos adds terms fixed at funding, a supplier who can settle without the buyer, a black-box check, and a
count with no escrow. Knos is not cheaper on a small order, has no outside security review, and has never run
with real money. Nobody outside Knos is known to have reproduced any of it.

### Potential Market Size

> "How big is the total addressable market for this project? Is it already large, or small but growing rapidly?"

We do not multiply a large number by a share, and we print no revenue scenario. [MARKET.md](../MARKET.md) gives
the adjacent market with a source for every figure: vendors that already bill per accepted outcome and count
their own, the revenue of coding-agent sellers, IT services spending, and buyers who already pay strangers per
outcome. None of those is Knos's market: its market is what buyers would spend on acceptance, reconciliation and
controls, and no source gives that. What the document does state is the revenue formula, one customer worked
through at the price book's prices, and the first milestone: 40 organisations at the entry price. Every input of
the formula is zero today.

### Founder Communication

> "Are the founders communicating the product vision clearly and capable of growing the product's user base?"

One sentence on every surface, and one thing the buyer hears first: close a supplier's invoice with evidence both
sides can check. The pitch puts the buyer and the problem first and the cryptography last
([pitch_script.md](pitch_script.md)); the demo is six shots of one commercial story
([demo_script.md](demo_script.md)); and every number in either has a source that a script checks
(`scripts/claims_check.py`). The documents say what is not done in the same place as what is. Growing a user
base is unproven: no buyer has heard any of this, and nobody outside Knos is known to run the free check.

### Viability

> "Can this project become a scalable, sustainable business?"

Not shown. What can be said: the settlement fee alone cannot carry it, because the code is MIT and a fork can
charge nothing, and while the programs are on devnet a settle fee is test money. What can earn real money on
devnet is software, invoiced off chain: the Meter, Control and a 30-day [Pilot](../PILOT.md). None has been sold,
and there is no legal entity to invoice from. The unit economics are in [MARKET.md](../MARKET.md), including the
one that did not work, a meter whose rent exceeded its price, and the batch mode that replaces it. The advantages
a fork would lack (suppliers that reuse one integration across unrelated buyers, buyers that return, short
onboarding) are written there as things to be earned, each with the measure that would show it, and each measure
reads zero. What would make it not viable is there too: nobody wanting a neutral count is first on the list.

### Traction

> "Does the product already have demand or revenue? If so, how durable are its revenue and user base?"

No. There is no revenue, and test USDC is not money. Counted from the chain: no account other than Knos's has
funded an order with its own tokens. One outside contributor wrote three pull requests that were paid on devnet,
for bounties Knos funded itself; that shows the path working between two accounts, not demand. With no revenue
and no outside funder there is nothing whose durability could be judged. No buyer has been
interviewed, there is no letter of intent, and nobody has bought or been offered the Pilot. The site's Numbers
page shows the live counts with Knos's own accounts kept apart, and the submission will say whatever those counts
are on the day.

## The six criteria in the rules

### Functionality

The path of a bounty runs on the public program ids on devnet, and the programs are tested in a simulator
instruction by instruction. The 0.3.14 build corrects a defect found in the build before it, before that build ran anywhere: a pay
token could pay a re-funded order twice ([SECURITY.md](../SECURITY.md), section 15). In the corrected build every
instruction that takes a signed token creates one single-use marker, a test replays every accepted token against
every instruction, and a second test drives a random state machine of orders, tokens and replays that finds the
double payment in the older build and no broken invariant in this one, in the seeds the tests run. That build was
rehearsed on staging program ids, not the public ones; whether it is live on the public ids is in `web/upgrades.json`. What is not
shown: mainnet load, and an outside review. Acceptance itself is decided by a pinned workflow off chain; the
chain verifies who signed.

### Potential impact

If work is sold per outcome, someone has to count the outcomes, and today the seller does. The impact would be an
invoice that the person approving it can defend: a count both sides can check and terms neither can change, for
any seller and any forge whose CI signs its runs. The impact so far is none: nobody outside Knos uses it.

### Novelty

Signatures, escrow and outcome pricing all exist, and MergePay verified GitHub's signature on a chain before Knos
did ([COMPARE.md](../COMPARE.md)). What is new here is the combination, for two parties who do not trust each
other's count: terms hashed into the order at funding; a supplier who can settle without the buyer; payment on a
black-box check, which refused all 63 cheating pull requests in our benchmark while 56 of them passed plain CI
([TAMPER.md](../TAMPER.md)); a count with no escrow where the supplier's own count sits beside the buyer's; and a
statement the two sides compute separately, in which a disagreement becomes a named dispute and not an invoice
line. The verifier on Solana takes any RS256 workload identity and other programs can read it.

### UX

A maintainer funds with one comment and no wallet on devnet, and a supplier is paid without doing anything after
the merge. For the buyer there is a console page where an order is written from a template and funded with a
passkey, needing no SOL because a relayer pays the transaction fee; its stage is in
[CAPABILITIES.md](../CAPABILITIES.md). What is not good yet: nobody outside Knos has been watched using any of
it, so there is no measure of whether a budget owner completes an order unaided; with real money a funder would
need USDC; and there is no payout to a bank.

### Open source

MIT. The verifier is a separate program with an interface other Solana programs call, with examples in the
repository ([COMPOSE.md](../COMPOSE.md)). The receipt has a published schema. Anyone can relay, and the program
pays whoever does. What is not there: no outside program is known to use the verifier, and nobody outside Knos
has published a reproduction.

### Business plan

The price book, the effective fee of each order size, what each unit costs to deliver, one customer worked
through, the first milestone, the phases with the gate to each, and what a zero-fee fork can and cannot copy are
in [MARKET.md](../MARKET.md); the one offer for money is [PILOT.md](../PILOT.md); who is needed is
[TEAM.md](../TEAM.md). It is tokenless. Its weakest points are stated in it: no buyer has been asked, no company
exists to sign a contract or send an invoice, escrow and money transmission need legal advice that has not been
taken, and one person holds every key and the one GitHub account the workflows live in
([DEPENDENCY.md](DEPENDENCY.md)).
