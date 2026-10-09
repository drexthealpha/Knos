# How the submission answers what the judges ask

**The neutral meter for AI agent work: neither side keeps the count.**

Colosseum's hackathon page lists seven factors its judges weigh
([colosseum.com/hackathon](https://colosseum.com/hackathon), read 5 Oct 2026; the question under each heading
below is quoted from it). The same page says teams "must disclose all relevant past development work in the
submission form"; that is [DISCLOSURE.md](../DISCLOSURE.md). The official rules list six criteria as well. Each
gets one paragraph here: what the submission can show, and what it cannot. The round those paragraphs refer to
is told once, in seven steps with the evidence under each, in [STORY.md](../STORY.md). A judge's one page is
[JUDGES.md](../JUDGES.md).

No count of capabilities is given on this page. How far each capability has got (implemented, tested, deployed,
exercised on devnet, reproduced by someone else) is in [CAPABILITIES.md](../CAPABILITIES.md), written from
[`docs/capabilities.json`](../capabilities.json), and which builds are live on the public program ids is in
`web/upgrades.json`; [MANIFEST.md](../MANIFEST.md) puts both on one page for this release, with the outstanding
limits. The numbers about outside use are in [NUMBERS.md](NUMBERS.md), zeros included.

## The seven factors on Colosseum's page

### Founder + Market Fit

> "Does the team have the right skills and experience to succeed in this market, and why is it motivated to solve
> this problem?"

Half. The motivation is first-hand: the founder works with coding agents every day, and his own agents reported
passing tests that had not passed. He measured that on public data before building for it
([BENCH.md](../BENCH.md)), shipped everything here in public with a dated history
([DISCLOSURE.md](../DISCLOSURE.md)), and found and disclosed a double-payment defect in his own build during its
upgrade delay, before it ran ([SECURITY.md](../SECURITY.md), section 15). Before this window, his earlier product,
on the memory engine Knos still uses, took first place of 92 teams at the Sibyl Labs hackathon (Sep 2026, 126.9
points, [leaderboard](https://hack.sibyllabs.org/leaderboard)). That is fit with the supplier's side of
this market and with the engineering. The buyer is the person who approves a supplier's invoice, and with that
person there is no fit yet: he has never sold to one, has not spoken to one about this, has not worked in
procurement or finance, has run no service for a customer, and is pseudonymous, which a procurement process may
refuse. [TEAM.md](../TEAM.md) says so, names the three roles the plan needs first, and says that none is hired,
approached or committed.

### Insight

> "Does the founding team have some unique insight based on their deep understanding of the problem space?"

Work is starting to be priced per outcome, and the seller keeps the count. For code, unlike for support tickets, a
third party already records the outcome and signs statements about it: the forge records the merge and the checks
and signs a CI run. So the count can belong to neither side. We measured why it matters: of 241 merged agent pull
requests whose description said tests pass, 9 had a failed test, build, lint or type-check job at the head commit and
19 a failed check of any kind ([index_review.json](../index_review.json)), so a buyer paying per merge on that sample
would have paid for those 19. The second
half is about what is bought: the unit is a deliverable, not a pull request, so splitting one piece of work into
many pull requests does not multiply the bill. The third is about price: a flat price per evaluation cannot grow
with the value it verifies, which is why a price on the outcome billing verified is proposed
([MARKET.md](../MARKET.md), section 3). The limit is stated wherever the insight is used: the forge signs which
workflow ran, not what it read. Whether buyers object to the seller's count enough to pay for another is not
known.

### Product + Execution

> "How well does the product work? How does it stack up against the competition?"

On Solana devnet, in test USDC: a task is funded, a submission whose required check failed is refused with the
check named, a valid one is paid on the forge's signature, a replayed token is refused, and an unfulfilled task
refunds without anyone's permission. Which of these runs on the public program ids on a given day is not stated
here: [CAPABILITIES.md](../CAPABILITIES.md) gives each capability's stage and `web/upgrades.json` the live builds,
and the demo captions each step with the program ids it ran on. From merge to paid took 26 seconds at the
median, over 51 payments on devnet; the demo's replays are captioned and are not evidence of speed. Against the competition
([COMPARE.md](../COMPARE.md)): cloud platforms and billing companies already meter agents and move payments, with
customers and real money, so that is not a difference; the difference is acceptance independent of every vendor,
and nobody has yet paid for that. MergePay is on a mainnet with real USDC and no platform fee, and is ahead
there. Knos is not cheaper on a small order, has no outside security review, and has never run with real money.
Nobody outside Knos is known to have reproduced any of it.

### Potential Market Size

> "How big is the total addressable market for this project? Is it already large, or small but growing rapidly?"

Not known. [MARKET.md](../MARKET.md) builds the addressable
market as qualified organisations times contract value, plus billable evaluations times the realised price, and
says what makes an organisation qualified: measurable spend on work bought per outcome, acceptance criteria that
can be written down, a buyer with authority, and a problem worth another system. No source counts those
organisations, so no total is printed. What is sourced: vendors that already bill per accepted outcome and count
their own; the revenue of coding-agent sellers, almost all of it billed by the seat or the token today; and one
precedent from another industry, independent measurement of advertising, where two companies each report several
hundred million USD a year. So the market is small today and depends on outcome pricing spreading, beyond code as
well. That is a bet.

### Founder Communication

> "Are the founders communicating the product vision clearly and capable of growing the product's user base?"

One sentence and one number on every surface: of 241 merged agent pull requests that claimed passing tests, 30
had a failed check. One page tells the story in seven steps with the evidence under each
([STORY.md](../STORY.md)); the demonstration follows the same transaction in seven beats and three minutes, and the presentation is a
separate script ([demo_script.md](demo_script.md), [pitch_script.md](pitch_script.md)), with a caption on any shot that is a
replay or is played faster than it happened; and every number in them has a source that a script checks
(`scripts/claims_check.py`). The other documents sit behind one map ([../README.md](../README.md)). Growing a
user base is unproven: no buyer has heard any of this, and nobody outside Knos is known to run the free check.

### Viability

> "Can this project become a scalable, sustainable business?"

Not shown. Devnet is the test mode, and what can be real while the programs stay there is software invoiced off
chain: Control, the Meter, the Acceptance fee on value reconciled off chain, and a 30-day [Pilot](../PILOT.md) that
starts free in shadow mode. Escrow and every fee the program collects on devnet are a demonstration in test money. None of the software has been
sold, and there is no legal entity to invoice from. One customer is worked at these prices in [MARKET.md](../MARKET.md): an example, not a forecast.
The code is MIT, so a fork can charge nothing; what it would lack has to be earned, in the order it could form:
supplier reuse, a terms standard cited by hash, a delivery record, neutrality. Each has a measure in
[MARKET.md](../MARKET.md), and each measure reads zero. One rule is published with the prices: Knos never charges
the party being rated. What would make it not viable is there too: nobody wanting a neutral count is first.

### Traction

> "Does the product already have demand or revenue? If so, how durable are its revenue and user base?"

No. There is no revenue, and test USDC is not money. [NUMBERS.md](NUMBERS.md) has the nine numbers about outside
use with today's value of each: no account other than Knos's has funded a task with its own tokens; no buyer has
been interviewed; there is no letter of intent, no shadow count, no reproduction by anyone else, and no outside
program known to read the verifier. One outside contributor wrote three pull requests that were paid on devnet,
for bounties Knos funded itself; that shows the path working between two accounts, not demand. With no revenue
and no outside funder there is nothing whose durability could be judged. The submission will say whatever those
numbers are on the day.

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

A buyer pastes an invoice on the first screen and gets the count and every mismatch, with no install and no
sign-up. A maintainer funds with one comment and no wallet on devnet, and a supplier is paid without doing
anything after the merge. For the buyer there is a console page where an order is written from a template and funded with a
passkey, needing no SOL because a relayer pays the transaction fee; its stage is in
[CAPABILITIES.md](../CAPABILITIES.md). What is not good yet: nobody outside Knos has been watched using any of
it, so there is no measure of whether a budget owner completes an order unaided; with real money a funder would
need USDC; and there is no payout to a bank.

### Open source

MIT. The verifier is a separate program with an interface other Solana programs call, with examples in the
repository ([COMPOSE.md](../COMPOSE.md)). The interface crates are on crates.io
([knos-oidc-interface](https://crates.io/crates/knos-oidc-interface) and
[knos-pay-interface](https://crates.io/crates/knos-pay-interface), 0.3.14), and the JavaScript client is on npm
(`npm install knos-settle`, [knos-settle](https://www.npmjs.com/package/knos-settle), 0.3.20). The x402 scheme is open upstream as a draft pull request
([x402-foundation/x402#3731](https://github.com/x402-foundation/x402/pull/3731)) with no maintainer reply yet. The
receipt has a published schema. Anyone can relay, and the program pays whoever does. What is not there: no outside program is known to use the verifier, and nobody outside Knos
has published a reproduction.

### Business plan

The price book, the effective fee of each order size, what each unit costs to deliver, the addressable market
as a formula, one customer worked through and how it would expand, the first steps, devnet as test mode, and
what a zero-fee fork can and cannot copy are in [MARKET.md](../MARKET.md); the one offer for money is [PILOT.md](../PILOT.md); who is needed is
[TEAM.md](../TEAM.md). It is tokenless. Its weakest points are stated in it: no buyer has been asked, no company
exists to sign a contract or send an invoice, escrow and money transmission need legal advice that has not been
taken, and one person holds every key and the one GitHub account the workflows live in
([DEPENDENCY.md](DEPENDENCY.md)).

## Six evidence targets

Targets, not results. Each row says what would count and where today's value is read; none is met unless that
source says so, and nothing in the submission implies otherwise. A seventh was a change to the code and is in this
release's list in [CHANGELOG.md](../../CHANGELOG.md): the batch commitment that hashes each complete event, and the
two quorum findings, with their regression tests kept.

| | target | what would count | where today's value is read |
|---|---|---|---|
| 1 | A release manifest | one page mapping source, deployed builds, capabilities and outstanding limits | [MANIFEST.md](../MANIFEST.md): published with this release, and `--check` holds it to its sources |
| 2 | An independent reproduction | an unrelated developer's signed report in `reproductions/` | [NUMBERS.md](NUMBERS.md), row 7 |
| 3 | Real buyer and supplier invoice reconciliations | a shadow count on a real invoice, recording disagreements and correct approvals as well as rejected lines | [NUMBERS.md](NUMBERS.md), row 9 |
| 4 | A paid commercial engagement | one [Pilot](../PILOT.md) bought; it needs a legal entity to invoice from | [DISCLOSURE.md](../DISCLOSURE.md), "No paying customer" |
| 5 | External composition | a consumer outside this repository that reads the verifier or verifies a receipt | [NUMBERS.md](NUMBERS.md), row 8 |
| 6 | Founder and market fit, shown by customer understanding | conversations with the person who approves a supplier's invoice, each counted with its no | [NUMBERS.md](NUMBERS.md), row 5; prior development is disclosed in [DISCLOSURE.md](../DISCLOSURE.md) |
