# Unit costs: what one unit costs Knos to deliver

**The neutral meter for AI agent work: neither side keeps the count.**

The price book ([MARKET.md](MARKET.md), section 3) says what a unit is sold for. This page says what one costs to
deliver, and how much it may cost if the line is to keep a gross margin of 90% or of 95%.

Two labels, and nothing in between. **[measured]** is a number this repository holds, with the file. **[budget,
not measured]** is a target nobody has observed: nothing has been sold, so no cost here was ever incurred for a
customer. Every USD figure from the chain is lamports converted at one price of SOL, stated below.

`knos bill margin month.json docs/unit_costs.json` prints a month's revenue, direct cost and gross margin line by
line from [`unit_costs.json`](unit_costs.json), which holds the four unit costs this page arrives at.

## The inputs

| input | value | label and source |
|---|---|---|
| SOL | 120.82 USD | **[vendor page]** [CoinGecko](https://www.coingecko.com/en/coins/solana) showed 120.82 and [Coinbase](https://www.coinbase.com/price/solana) 120.81, read 6 Oct 2026. [METER.md](METER.md) and MARKET.md take 121.50, read two days earlier; the figures differ by under 1% |
| A transaction | 5,000 lamports a signature | **[vendor page]** [Solana docs](https://solana.com/docs/core/fees) |
| A hosted runner | 0.006 USD a minute, Linux, 2 cores | **[vendor page]** [GitHub, Actions runner pricing](https://docs.github.com/en/billing/reference/actions-runner-pricing), read 6 Oct 2026. Standard runners are free in public repositories ([GitHub, Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), read 6 Oct 2026) |
| Object storage | 0.015 USD a GB a month; a write 0.0000045 USD; egress free | **[vendor page]** [Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing/), read 6 Oct 2026 |
| Retention | 7 years | **[assumption]** no contract sets it |
| A support hour | 75 USD; ten minutes a ticket, so 12.50 USD a ticket | **[assumption]** nobody is employed |

## 1. Chain fees

| unit | lamports | USD | label |
|---|---|---|---|
| One batch of evaluations: 3 transactions, one signature each | 15,000 | 0.0018 | **[measured]** the count of transactions, [METER.md](METER.md), "What an evaluation costs in each mode" |
| One evaluation in a batch of 5,000 | 3 | 0.00000036 | **[measured]** the same, divided |
| One evaluation recorded by itself | 15,000, and 1,097,280 locked for up to a month | 0.0018, and 0.133 locked | **[measured]** the same page. It costs nine tenths of the 0.002 price, so the price assumes batches |
| The month's Ledger account, per buyer and seller | 1,137,920, once | 0.137 | **[measured]** rent the clusters answered on 4 Oct 2026 |
| One order, funded and paid: 12 transactions | 60,000 | 0.0072 | **[measured in the simulator]** [LOAD.md](LOAD.md): 10 transactions verify two tokens, one funds, one pays; 3,546,061 compute units ([load.json](load.json)) |
| A payee's first payment: a token account of 165 bytes | 1,488,440, once per payee | 0.180 | **[measured]** rent, as above; whoever relays puts it up |

Priority fees are in no measurement. Devnet charges none; a busy mainnet may.

## 2. Relay and runner time per token

The stages of a payment, recorded on devnet ([LOAD.md](LOAD.md), section 6; [load.json](load.json)). The stage
rows have 5 samples each, so a p95 is one payment.

| stage | p50 | p95 | whose machine | USD at 0.006 a minute, p50 and p95 |
|---|---|---|---|---|
| Evaluation: the workflow run that judges the work | 16 s | 24 s | the customer's runner | 0.0016 and 0.0024 |
| Relay: pickup, submission and confirmation | 2 + 2 + 3 = 7 s | 5 + 5 + 8 = 18 s | the relay's | 0.0007 and 0.0018 |

**[measured]** are the seconds. The USD column is arithmetic at GitHub's list price; no bill was read. The
public relay runs in a public repository, where a standard runner is free. A relay for private repositories
would be paid for, and what it costs is **[budget, not measured]**: 0.0007 USD a token is 35% of the Meter's 0.002
if every evaluation is relayed by itself, and a 5,000th of that in a batch.

## 3. Storage per evidence bundle

| what is kept | bytes | USD for 7 years | label |
|---|---|---|---|
| One acceptance bundle | 16,332 (2,948 compressed) | 0.0000206 | **[measured]** the bytes of [`tests/web/recorded/acceptance_bundle.json`](../tests/web/recorded/acceptance_bundle.json); 16,332 ÷ 10⁹ × 0.015 × 84 months |
| One ledger event | 370 | 0.00000047 | **[measured]** [`examples/meter/buyer.jsonl`](../examples/meter/buyer.jsonl): 2,956 bytes over 8 lines |

Storage is not what limits the margin: a bundle kept for seven years is a hundred-thousandth of the 3 USD fee on a
1,000 USD deliverable. A real bundle with logs attached may be far larger; none from a customer exists to measure.

## 4. Support

**[budget, not measured]** There is nobody to answer a ticket today.

One million evaluations earn at most 2,000 USD at the Meter, and less by the free 100,000. A gross margin of 90%
leaves 200 USD for everything it costs to deliver them. If support took all of it, that is 16 tickets at 12.50 USD:
one ticket for every 62,500 evaluations. At 95% it is 8 tickets.

So a person cannot settle a routine difference. **Routine reconciliation must be self-service:** each side
recomputes the month from its own ledger (`knos meter reconcile`), a statement is checked from two files
(`knos statement verify`), and a difference is a named line the two contracting parties settle between them.
A person from Knos deciding a dispute is a separate service at a separate price. It is not offered.

## The ceilings

The largest direct cost a unit may carry at its price: 10% of the price for a gross margin of 90%, 5% for 95%.

| unit | price | ceiling at 90% | ceiling at 95% | what it carries today |
|---|---|---|---|---|
| One evaluation past the free ones | 0.002 | 0.0002 | 0.0001 | 0.00000036 of chain fees and 0.00000047 of storage **[measured]**; relay, ingestion, monitoring and support **[budget, not measured]**: 0.0002 in all |
| Acceptance on a deliverable of 20,000, the worked customer's | 60.00 | 6.00 | 3.00 | reconciled off chain: storage **[measured]**, and 0.10 for exceptions **[budget, not measured]** |
| Acceptance on a release of 1,000 on chain | 3.00 | 0.30 | 0.15 | 0.0072 of chain fees **[measured in the simulator]**, the relayer's tip, and 0.10 for exceptions **[budget, not measured]** |
| Acceptance at the floor: a release of 16.67 or less | 0.05 | 0.005 | 0.0025 | 0.0072 of chain fees: over both ceilings before any tip |
| One record lookup | 0.25 | 0.025 | 0.0125 | 0.01 **[budget, not measured]**; the API is not built |
| Control, Team, a year | 25,000 | 2,500 | 1,250 | not budgeted |
| Control, Business, a year | 100,000 | 10,000 | 5,000 | 15,000 of onboarding and support **[budget, not measured]**: 85%, under both |

Three lines miss, and the table says so:

- **The floor.** A release at the floor does not cover its own transactions at a 90% margin, and a relayer's tip
  comes out of the same 0.05. Small releases are carried, not earned on.
- **The free evaluations.** The first 100,000 a month cost what any evaluation costs. At the budget that is 20
  USD a month for each organisation. The worked customer's Meter line earns 20 USD a month and costs 22.
- **Control at the budget.** 15,000 USD a year of people for a 100,000 USD plan is a margin of 85%.

The worked customer's first month, at these costs: revenue 10,753.33, direct cost 1,276.00, gross margin 88.1%
(Control 85.0%, Meter −10.0%, Acceptance 99.8%). `tests/test_billing.py` holds the command to those figures.

## The comparison a buyer will make

| who | unit | price | source |
|---|---|---|---|
| Amazon Web Services, Bedrock AgentCore | a custom evaluation | 1.50 USD per 1,000: 0.0015 each, "model usage billed separately" | **[vendor page]** [pricing](https://aws.amazon.com/bedrock/agentcore/pricing/), read 6 Oct 2026 |
| The same, built-in evaluators | tokens | 0.0024 USD per 1,000 input tokens, 0.012 per 1,000 output tokens | the same page |
| Knos, Meter | an evaluation past 100,000 a month | 0.002 USD | [MARKET.md](MARKET.md), section 3; proposed, nobody has paid it |

The Meter costs a third more than the cloud's evaluation call. What it adds that an evaluation call does not:

- **A count both sides can recompute.** Buyer and supplier each keep a ledger; the chain holds the month's root.
- **Deduplication.** The same evidence sent twice is one evaluation, and a retry Knos caused is free.
- **Retention.** The evidence is kept so that a receipt verifies later without Knos.
- **A signed acceptance.** A third party signed the run that judged the work; the terms were fixed before it.

If a buyer needs none of the four, the cloud's call is cheaper and Knos has nothing to sell it.

## What the customer pays in all

The fee is one part of four.

| part | who carries it | what is known |
|---|---|---|
| Fees | the buyer | the price book; the worked customer pays 130,240 USD a year |
| The customer's own compute | the buyer or the supplier, on its runners | 16 s of a runner for an evaluation at p50; 0.0016 USD at list price in a private repository, nothing in a public one |
| Integration | the buyer and each supplier | not measured; one workflow file for each repository |
| Exceptions | the buyer's and the supplier's people | not measured; the Pilot counts them |

Knos runs no customer test. The tests run on the customer's runners, on the customer's bill. That keeps the cost
out of Knos's margin. **It is not a saving for the customer:** the customer paid for those minutes before Knos and
pays for them after.

## What is not known

- What a relay costs for private repositories. No bill has been read.
- What a batch costs on a cluster. The count of transactions is measured; a run on devnet is not.
- What a real evidence bundle weighs. The one measured is a recorded fixture.
- How many tickets a million evaluations raise. Nobody has run a million.
- Priority fees on mainnet.
