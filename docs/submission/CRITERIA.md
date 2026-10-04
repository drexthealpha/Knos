# How the submission answers what the judges ask

Two lists apply. Colosseum's hackathon page lists seven factors its judges weigh
([colosseum.com/hackathon](https://colosseum.com/hackathon), read 4 Oct 2026; the questions below are quoted from
it; the page says its hackathons are "startup competitions"). The official rules list six criteria. Each gets one paragraph here: what the submission can show, and what it
cannot. Where the honest answer is "not yet", that is the answer.

## The seven factors on Colosseum's page

### Founder + Market Fit

> "Does the team have the right skills and experience to succeed in this market, and why is it motivated to solve
> this problem?"

One person, under a pseudonym, who works with coding agents every day and built this because his own agents
reported passing tests that had not passed. The evidence of skill is the repository: a verifier for RS256 tokens
written for Solana's compute limits, four programs, and tests that are run in public. What is missing is the other
half of this market: the founder has not sold to an engineering or finance leader, and has not yet spoken to one
about this. The plan for that is [INTERVIEWS.md](INTERVIEWS.md); the ask includes a co-founder who has.

### Insight

> "Does the founding team have some unique insight based on their deep understanding of the problem space? Is there
> a new technology, or a new trend that creates an opportunity for their startup to succeed?"

The new trend: work is starting to be priced per outcome, and the seller keeps the count. For code, unlike for support tickets, a
third party already records the outcome and signs statements about it: the forge records the merge and the checks
and signs a CI run. So the count can belong to neither side, and a program can check the signature without an
oracle. We measured why it matters: of 241 merged agent pull requests whose description said tests pass, 30 had a
failed check at the head commit ([BENCH.md](../BENCH.md)). The limit of the insight is stated wherever it is used:
the forge signs which workflow ran, not what it read.

### Product + Execution

> "How well does the product work? How does it stack up against the competition?"

A bounty works on devnet, end to end, in test USDC: funding by a comment, a refusal that names the failed check, a
payment on the forge's signature, and a refund that needs nobody's permission. What this release adds is tested
locally and is not on devnet yet: a work order with its terms hashed at funding; one single-use rule for every
token; an order that pays the first pull request its black-box suite passes, with no merge, so that an agent finds
work, takes it, submits it and is paid with no human step (shown in a test against stand-ins for GitHub and the
chain, not on devnet); a Buy page where a passkey funds the order; the count in batches, with the seller's own
count beside the buyer's; and a statement both sides compute. [`docs/capabilities.json`](../capabilities.json) is
the index of evidence ([the table](../CAPABILITIES.md)): for each capability, whether it is implemented, tested,
deployed, exercised on devnet, or reproduced by someone else, and the file that shows it. Nothing in it is recorded
as exercised or reproduced yet, and the demo cuts any shot whose capability is not exercised on the day.
Against the competition ([COMPARE.md](../COMPARE.md)): MergePay is on a mainnet with real USDC and no platform fee,
and is ahead there; its condition is the merge alone. Knos adds named checks and paths fixed at funding, a seller
who can settle without the buyer, a black-box check, and a count with no escrow. Knos has no outside security
review and has never run with real money.

### Potential Market Size

> "How big is the total addressable market for this project? Is it already large, or small but growing rapidly?
> What will be the impact of this project on the growth rate of their market?"

We do not multiply a large number by a share. [MARKET.md](../MARKET.md) gives the adjacent market with a source for
every figure: vendors that already bill per accepted outcome, the revenue of coding-agent sellers, IT services
spending, and buyers who already pay strangers per outcome in stablecoins. It then states the revenue formula
(qualified customers × annual platform price + billable evaluations × realised unit price), what 1 billion USD a
year would require line by line as arithmetic with the reality beside each line, and the first milestone, 1 million
USD of fees. Every input of that formula is zero today.

### Founder Communication

> "Are the founders communicating the product vision clearly and capable of growing the product's user base?"

One sentence on every surface: Knos is the neutral count and settlement for software work priced per outcome. The
pitch is five beats in under three minutes ([pitch_script.md](pitch_script.md)), the demo is a shot list of real
screens ([demo_script.md](demo_script.md)), and every number in either has a source that a script checks
(`scripts/claims_check.py`). The documents say what is not done in the same place as what is. Growing a user
base is unproven: the free check is the distribution, and nobody outside Knos is known to run it.

### Viability

> "Can this project become a scalable, sustainable business?"

The settlement fee alone cannot carry it: the code is MIT and a fork can charge nothing. The plan charges for what
a fork cannot copy (neutrality, the record, a contract with an accountable party, capital) and is honest that Knos
has little of each today. The order is count first, because it needs no customer money on chain and can be
invoiced off chain; settlement second, which needs mainnet, an outside review and legal advice; capital third. The
unit economics are in [MARKET.md](../MARKET.md), including the one that did not work, a meter whose rent exceeded
its price, and the batch mode that replaces it. What would make it not viable is there too: nobody wanting a
neutral count is first on the list.

### Traction

> "Does the product already have demand or revenue?"

No. There is no revenue, and test USDC is not money. Counted from the chain: no account other than Knos's has
funded an order with its own tokens. One outside contributor wrote three pull requests that were paid on devnet,
for bounties Knos funded itself; that shows the path working between two accounts, not demand. No buyer has been
interviewed, there is no letter of intent and no pilot. The site's Numbers page shows the live counts with Knos's
own accounts kept apart, and the submission will say whatever those counts are on the day.

## The six criteria in the rules

### Functionality

The whole path runs on Solana devnet, and the programs are tested in a simulator instruction by instruction. The
release corrects a defect found before its build went live: a pay token could pay a re-funded order twice
([SECURITY.md](../SECURITY.md), section 15). Now every instruction that takes a signed token creates one single-use
marker, and a test replays every accepted token against every instruction. A second test drives a random state
machine of orders, tokens and replays: run on the 0.3.13 build it finds that double payment, and on this build it
finds no broken invariant in the seeds the tests run. All of that is in a simulator. What is not shown: the
corrected build on devnet, mainnet load, and an outside review. Acceptance itself is decided by a pinned workflow off chain; the chain verifies who signed.

### Potential impact

If work is sold per outcome, someone has to count the outcomes, and today the seller does. The impact is a count
both sides can check and terms neither can change, for any seller and any forge whose CI signs its runs. The size
of that is argued, with sources and without a share-of-market multiplication, in [MARKET.md](../MARKET.md). The
impact so far is none: nobody outside Knos uses it.

### Novelty

Signatures, escrow and outcome pricing all exist, and MergePay verified GitHub's signature on a chain before Knos
did ([COMPARE.md](../COMPARE.md)). What is new here: a verifier on Solana for any RS256 workload identity that other programs can
read; named checks and allowed paths hashed into the order at funding; a seller who can settle without the buyer;
payment on a black-box check, which refused all 63 cheating pull requests in our benchmark while 56 of them passed
plain CI ([TAMPER.md](../TAMPER.md)); and a count of accepted outcomes with no escrow, where the supplier's own count
sits beside the buyer's.

### UX

A maintainer funds with one comment and no wallet on devnet, and a seller is paid without doing anything after the
merge. This release adds, tested locally and not yet on devnet: a Buy page where a buyer picks a template and funds
with a passkey, needing no SOL because a relayer pays the transaction fee (run in a headless browser with a virtual
passkey); and four tools with which an agent holding its own key finds, takes, submits and collects, which post
nothing until the agent's operator turns them on.
The chain is what makes that possible: no party holds the money in between, and nobody has to be trusted to
release it. What is not good yet: with real money a funder would need USDC; there is no payout to a bank; and the
person this is now for, someone approving a supplier's invoice, has a statement and an export but no product
built around their day.

### Open source

MIT. The verifier is a separate program with an interface other Solana programs call, with examples in the
repository ([COMPOSE.md](../COMPOSE.md)). The receipt has a published schema. Anyone can relay, and the program pays
whoever does. What is not there: no outside program is known to use the verifier yet.

### Business plan

The price book, the cost of each unit, the fee actually collected under the tiers, the arithmetic of 1 billion USD
a year with a reality check beside each line, the first milestone, the phases with the gate to each, and what a
zero-fee fork can and cannot copy are in [MARKET.md](../MARKET.md). It is tokenless. Its weakest points are stated
in it: no buyer has been asked, no company exists to sign a contract, escrow and money transmission need legal
advice that has not been taken, and one person holds every key and the one GitHub account the workflows live in
([DEPENDENCY.md](DEPENDENCY.md)).
