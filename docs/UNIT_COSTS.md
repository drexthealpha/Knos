# Unit costs: what one unit costs Knos to deliver

**The neutral meter for AI agent work: neither side keeps the count.**

The price book ([MARKET.md](MARKET.md), section 3) says what a unit is sold for. This page says what one costs to
deliver, and how much it may cost if the line is to keep a gross margin of 90% or of 95%.

Two labels, and nothing in between. **[measured]** is a number this repository holds, with the file. **[budget,
not measured]** is a target nobody has observed: nothing has been sold, so no cost here was ever incurred for a
customer. Every USD figure from the chain is lamports converted at one price of SOL, stated below.

`knos bill margin month.json docs/unit_costs.json` prints a month's revenue, direct cost and gross margin line by
line from [`unit_costs.json`](unit_costs.json), which holds the unit costs this page arrives at. Under them it
prints the three leaks below with their numbers, who earns what at the floor under both builds of the program,
what a small outcome pays by itself and netted, and the second worked customer.

## Gross margin is not operating margin

**Every margin on this page is a gross margin.** Gross margin is revenue less the direct cost of delivering it,
over revenue: chain fees, storage, relay time, and the onboarding and support a customer uses.

Operating margin subtracts more: building the product, selling it, and administering a company. Operating margin
= gross margin − (those costs ÷ revenue). A gross margin of 85% is therefore an operating margin under 85% as soon
as anyone is paid to build or sell.

No operating cost is known. Nobody is employed, nothing has been sold and no company exists. So this page prints
no operating margin, and `knos bill margin` prints none: its output says "gross" on every margin. A line is held
to a gross margin of 95% here because a lower one leaves no room for the costs this page cannot count.

## The inputs

| input | value | label and source |
|---|---|---|
| SOL | 120.82 USD | **[vendor page]** [CoinGecko](https://www.coingecko.com/en/coins/solana) showed 120.82 and [Coinbase](https://www.coinbase.com/price/solana) 120.81, read 6 Oct 2026. [METER.md](METER.md) and MARKET.md take 121.50, read two days earlier; the figures differ by under 1% |
| A transaction | 5,000 lamports a signature | **[vendor page]** [Solana docs](https://solana.com/docs/core/fees) |
| A hosted runner | 0.006 USD a minute, Linux, 2 cores | **[vendor page]** [GitHub, Actions runner pricing](https://docs.github.com/en/billing/reference/actions-runner-pricing), read 6 Oct 2026. Standard runners are free in public repositories ([GitHub, Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), read 6 Oct 2026) |
| Object storage | 0.015 USD a GB a month; a write 0.0000045 USD; egress free | **[vendor page]** [Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing/), read 6 Oct 2026 |
| Retention | 7 years | **[assumption]** no contract sets it |
| A support hour | 75 USD; ten minutes a ticket, so 12.50 USD a ticket | **[assumption]** nobody is employed |
| A support hour, from public wages | 43.20 USD: a median wage of 30.24 USD an hour over wages' 70.0% share of what an employer pays | **[public statistics]** [BLS, computer support specialists](https://www.bls.gov/ooh/computer-and-information-technology/computer-support-specialists.htm) (median, May 2025) and [BLS, employer costs for employee compensation](https://www.bls.gov/news.release/ecec.nr0.htm) (private industry, June 2026), read 8 Oct 2026. A floor: no management, tools or office |

## 1. Chain fees

| unit | lamports | USD | label |
|---|---|---|---|
| One batch of evaluations: 3 transactions, one signature each | 15,000 | 0.0018 | **[measured]** the count of transactions, [METER.md](METER.md), "What an evaluation costs in each mode" |
| One evaluation in a batch of 5,000 | 3 | 0.00000036 | **[measured]** the same, divided |
| One evaluation recorded by itself | 15,000, and 1,097,280 locked for up to a month | 0.0018, and 0.133 locked | **[measured]** the same page. It costs nine tenths of the 0.002 price, so the price assumes batches |
| The month's Ledger account, per buyer and seller | 1,137,920, once | 0.137 | **[measured]** rent the clusters answered on 4 Oct 2026 |
| **The default delivery: one anchored batch for one buyer and supplier in a month** | 15,000 + 1,137,920 = 1,152,920 | 0.1393 | **[measured]** the two rows above, added. It does not grow with the count |
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

Storage is not what limits the gross margin: a bundle kept for seven years is a hundred-thousandth of the 3 USD fee on a
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
| One evaluation past the free ones | 0.002 | 0.0002 | 0.0001 | 0.00005 in all **[budget, not measured]**, of which storage 0.00000047 **[measured]**; and 0.1393 a month for each supplier's batch **[measured]** |
| Acceptance on a deliverable of 20,000, the worked customer's | 60.00 | 6.00 | 3.00 | reconciled off chain: storage **[measured]**, and 0.10 for exceptions **[budget, not measured]** |
| Acceptance on 10,000 settled at 0.20%, by contract above the month's first million | 20.00 | 2.00 | 1.00 | reconciled off chain: 0.10 for exceptions **[budget, not measured]** on each deliverable, and storage **[measured]** |
| Acceptance on a release of 1,000 on chain | 3.00 | 0.30 | 0.15 | 0.0072 of chain fees **[measured in the simulator]**, the relayer's tip, and 0.10 for exceptions **[budget, not measured]** |
| Acceptance at the floor: a release of 16.66 or less | 0.05 | 0.005 | 0.0025 | the relayer's tip is the whole fee: the fee owner earns nothing |
| One record lookup | 0.10 | 0.010 | 0.005 | 0.01 **[budget, not measured]**: at the 90% ceiling, over the 95% one. `knos record serve` is the server; anyone runs it and Knos hosts none, so Knos carries no cost and budgets no revenue ([RECORD.md](RECORD.md)) |
| Control, Team, a year | 25,000 | 2,500 | 1,250 | not budgeted |
| Control, Business, a year | 100,000 | 10,000 | 5,000 | 15,000 of onboarding and support **[budget, not measured]**: a gross margin of 85%, under both. The target is 7,000: 93% gross (leak 3) |

## The budget today against what the price book requires

Each unit's cost to deliver: what [`unit_costs.json`](unit_costs.json) budgets today, what the price book allows it
to cost if the line is to keep a gross margin of 95%, and the design that has to close the gap. `knos bill margin`
prints this table under the leaks, from `knos.billing.gaps`; `tests/test_billing.py` holds it to these figures.
Every figure but the chain fees is **[budget, not measured]**; nothing has been sold.

| unit | budget today | what the price book requires | how the requirement is reached | gap | the design that closes it |
|---|---|---|---|---|---|
| One evaluation delivered, free ones included | 0.00005 | 0.0000893 | the second worked customer: 0.002 × 900,000 billable × 5%, less five monthly batches of 0.1393, over 1,000,000 delivered | none at that volume; at the first worked customer's 110,000 a month the requirement is 0.0000091 (leak 1) | one anchored batch a supplier a month (`knos meter batch`); each side reconciles itself (`knos meter reconcile`); no person in the routine path |
| One accepted deliverable, reconciled off chain | 0.10 | 0.02, a target | at 0.02 a deliverable keeps 95% from 133.34 at 0.30% (200.00 at 0.20%); at 0.10 only from 666.67 (1,000.00) | 0.08 | exceptions are self-service: a difference is a named line the two parties settle (`knos statement verify`); outcomes under 20 USD are netted into one release; a person deciding a dispute is a separate service at a separate price |
| One record lookup | 0.01 | 0.005 | 0.10 × 5% | 0.005 | anyone runs `knos record serve`; Knos hosts none, so Knos carries no cost and books no revenue ([RECORD.md](RECORD.md)) |
| Control, Business, a year of onboarding and support | 15,000 | 5,000 | 100,000 × 5% | 10,000; the target of 7,000 leaves 2,000 (leak 3) | self-service onboarding: one pinned workflow file, `knos shadow` on the first invoice, `knos preflight` for suppliers; support is pooled |
| Control, Team, a year of onboarding and support | not budgeted | 1,250 | 25,000 × 5% | unknown | the same self-service path; a Team account gets no named person |
| The chain fees of one release at the 0.05 floor, when Knos relays | 0.0072 **[measured in the simulator]** | 0.0025 | 0.05 × 5% | 0.0047 (leak 2) | netting: one release a payee a period; an outside relayer pays the chain fees out of its tip |

The largest gaps are people, not machines: 10,000 USD a year on a Business account, and 0.08 on each accepted
deliverable. Both close only if routine onboarding and routine exceptions need no person from Knos. Neither has
been tried with a customer; the first Pilot is where both are counted ([PILOT.md](PILOT.md)).

## The gross fee is not the cash Knos keeps

What knos_pay takes at release is the **gross protocol fee**. The cash Knos keeps is smaller, and the steps
between them are a rule, `knos.billing.cash_kept`, held by a test:

**cash kept = gross fee − the tips outside relayers take out of it − discounts and volume rebates − credits for
disputed, reversed or failed work − channel commissions on what is left.**

What is left can be below zero, and is shown so. **A fee counter on chain is not company cash:** it counts the
gross fee in the fee owner's token accounts, before any of those steps, and on devnet it is test money, 0 revenue.

An example, not a customer: 100 releases of 1,000 test USDC by outside relayers under knos_pay 2.2, ten of them a
payee's first payment. The discount (10%), the credit (one reversed release, 3.00) and the channel's share (20% of
what is left) are **[assumption]**.

| step | USD |
|---|---|
| Gross fee: 100 × 3.00 | 300.00 |
| Relayer tips: 90 × 0.05 + 10 × 0.30 | −7.50 |
| Discount: 10% of 292.50 | −29.25 |
| Credit for a reversed release | −3.00 |
| Channel: 20% of 260.25 | −52.05 |
| **Cash kept** | **208.20, 69.40% of the gross fee** |

`knos bill margin` prints this example under the table above.

## The leaks

Three lines earn less than a gross margin of 95%. Each is fixed by design here, or stated with its number and the
design that would fix it. `knos bill margin` prints all three for any month.

### 1. The Meter and the free evaluations

The last budget put 0.0002 USD on every evaluation, so the free 100,000 cost 20 USD a month and the worked
customer's Meter line earned 20 and cost 22. The budget assumed nothing about delivery. This one does: **the
monthly batch is the default.** One anchored batch for each buyer and supplier, 0.1393 USD a month, whatever the
count. The chain's cost per evaluation is that divided by the count, and tends to zero.

| component of one evaluation | USD | label |
|---|---|---|
| Chain, in the month's batch | 0.1393 a supplier a month, not per evaluation | **[measured]** section 1 |
| Keeping its ledger event seven years | 0.00000047 | **[measured]** section 3 |
| Writing it to object storage, if each event were one write | 0.0000045 | **[budget, not measured]** arithmetic at the vendor's list price; no bill was read |
| Relay, ingestion and monitoring | the rest of 0.00005 | **[budget, not measured]** |
| Support | nothing: reconciliation is self-service (section 4) | **[budget, not measured]** |
| **In all** | **0.00005** | **[budget, not measured]** a quarter of the last budget |

The worked customer, with five suppliers: 110,000 × 0.00005 + 5 × 0.1393 = 6.20 USD a month against 20.00 of
revenue. The Meter line's gross margin is 69.0%, and it reaches 90% at 138,000 evaluations a month.

**What 95% needs, and whether today's cost meets it.** That customer is billed for 10,000 evaluations and is
delivered 110,000: the free allowance is the leak, not the chain.

| the worked customer's Meter line, a month | USD | per delivered evaluation | meets 95% gross |
|---|---|---|---|
| Revenue: 10,000 billable × 0.002 | 20.00 | | |
| What a gross margin of 95% allows: 20.00 × 5% | 1.00 | 0.0000091 | |
| The measured part: 110,000 × 0.00000047 of storage + 5 × 0.1393 of batches **[measured]** | 0.75 | 0.0000068 | yes: 96.3% gross |
| The whole budget: 110,000 × 0.00005 + 5 × 0.1393 **[budget, not measured]** | 6.20 | 0.0000563 | no: 69.0% gross |

So the answer has two halves. **The cost that is measured meets it:** batching puts the chain at 0.1393 USD a
supplier a month whatever the count, and a ledger event is 370 bytes. **The cost that is budgeted does not, at
this volume:** relay, ingestion and monitoring are budgeted at the rest of 0.00005 an evaluation, and nobody has
measured them. The shortfall is 6.20 − 1.00 = 5.20 USD a month on a customer who pays 10,753.33.

At scale the ceiling is 0.002 × 5% = 0.0001 USD for each billable evaluation. The budget of 0.00005 meets a gross
margin of 95% from 213,930 evaluations a month (0.0001 n − 10 = 0.00005 n + 0.6965), and at a million a month the
line is 1,800.00 against 50.70: 97.2% gross.

**The design that fixes it** is the one already in the tree, and one measurement that is not: one anchored batch
for each supplier a month (`knos meter batch`), compact events, reconciliation each side runs itself
(`knos meter reconcile`), and no person in the routine path. What is missing is a bill: the cost of relay and
ingestion for one evaluation has to be read from a real month before the 0.00005 is anything but a budget.

**The free tier still costs.** An organisation that stays inside the free 100,000 pays nothing and costs at most
12 × 100,000 × 0.00005 = 60 USD a year, and 1.67 USD a year more for each supplier it counts with. The worked
customer's five suppliers make it 68.36. **That is acquisition cost**, not gross margin, and it is a ceiling: an
organisation that runs fewer evaluations costs less.

### 2. The floor

The fee is the funder's, on top of the amount. Out of it the relayer takes a tip, 0.05, or 0.30 when the paying
transaction created the payee's token account (0.18 USD of rent the relayer puts up, **[measured]**), and never
more than the fee. The fee owner keeps the rest. In test USDC, from the constants of each build
(`knos bill margin` prints both tables; `knos status` says which build is live):

**knos_pay 2.1, the build live on 7 Oct 2026** (three tiers and a floor of 0.40):

| release | fee | as a share | relayer's tip | fee owner | first payment: tip | less 0.18 of rent | fee owner |
|---|---|---|---|---|---|---|---|
| 5.00 | 0.40 | 8.00% | 0.05 | 0.35 | 0.30 | 0.12 | 0.10 |
| 20.00 | 0.50 | 2.50% | 0.05 | 0.45 | 0.30 | 0.12 | 0.20 |
| 100.00 | 2.50 | 2.50% | 0.05 | 2.45 | 0.30 | 0.12 | 2.20 |
| 1,000.00 | 25.00 | 2.50% | 0.05 | 24.95 | 0.30 | 0.12 | 24.70 |

**knos_pay 2.2, proposed on that day** (0.30% of the amount, at least 0.05):

| release | fee | as a share | relayer's tip | fee owner | first payment: tip | less 0.18 of rent | fee owner |
|---|---|---|---|---|---|---|---|
| 5.00 | 0.05 | 1.00% | 0.05 | 0.00 | 0.05 | −0.13 | 0.00 |
| 20.00 | 0.06 | 0.30% | 0.05 | 0.01 | 0.06 | −0.12 | 0.00 |
| 100.00 | 0.30 | 0.30% | 0.05 | 0.25 | 0.30 | 0.12 | 0.00 |
| 1,000.00 | 3.00 | 0.30% | 0.05 | 2.95 | 0.30 | 0.12 | 2.70 |

Under 2.2 **the fee owner earns nothing on a release of 16.66 or less**, and
nothing on a payee's first payment of 100.00 or less. On a first payment of 20 or less
the relayer does not recover the rent it put up. Small releases one by one are carried, not earned on. Under
2.1 the floor of 0.40 leaves the fee owner 0.35 on every release, at the price of 8.00% on a release of 5.

**Who pays the relayer's tip.** The funder, under both builds, and only through the fee: the fee is charged on
top of the amount, the tip comes out of the fee, and it is never more than the fee. The payee is paid the amount
in full. Nothing is added for the tip. Under 2.1 the floor of 0.40 covers the tip eight times over; under 2.2 the
floor of 0.05 is the tip, so on a release of 5 the relayer is paid and the fee owner is not.

**Netting is the fix.** Outcomes under 20 USD accumulate and settle as one release per payee per period:

| an outcome of 0.99 | fee | as a share |
|---|---|---|
| charged by itself | 0.05, the floor | 5.05% |
| one of 100 to one payee in a period, netted into one release of 99.00 | 0.30 for the release | 0.30% |
| the only one to its payee in the period | 0.05, the floor once | 5.05% |

From 17 such outcomes to one payee the rate is the fee and not the floor (counted as knos_pay counts, in base units: 17 x 0.99 = 16.83, and 0.30% of it is 0.05049, above the floor of 0.05). Netting is reconciled off chain; the
program has no instruction for it, and on chain the least order is 5 test USDC.

The same remedy at the least order the program takes, under 2.2, 100 outcomes of 5.00 to one payee in a period:

| 100 outcomes of 5.00 | releases | the funder's fee | relayers' tips | fee owner |
|---|---|---|---|---|
| released one by one | 100 | 5.00 | 5.00 | 0.00 |
| netted into one release of 500.00 | 1 | 1.50 | 0.05 | 1.45 |

The funder pays less, the relayer is paid for the one transaction it sends, and the fee owner earns
([NETTING.md](NETTING.md); `knos net`). What netting costs is time: the payee waits for the period to close.

### 3. Control at the budget

15,000 USD a year of onboarding and support for a 100,000 USD plan is a **gross** margin of 85%: gross, before
anything it costs to sell the plan or build the product. For 90% the people on one Business customer must cost
10,000 USD a year; for 95%, 5,000. At 75 USD an hour that is 66 hours a year, five and a half a month. So
self-service has to remove two thirds of the budgeted support, and nothing shows that it does. None of the three
figures is measured.

**The target is 7,000 USD a year: a gross margin of 93%.** That is 8,000 less than the budget, and 93 hours a year
at 75 USD an hour where the budget has 200. It is still short of 95%, which needs 5,000. The design that has to
replace the hours is self-service onboarding, and each part of it exists as a command or a file today:

| what a person does in the budget | what replaces it | where |
|---|---|---|
| installs the workflow in each repository | the buyer copies one pinned workflow file | [`examples/`](../examples), [INSTALL.md](INSTALL.md) |
| answers a supplier asking why a change was refused | `knos preflight` says, before anything is submitted, what the order will hold the change to | [`src/knos/preflight.py`](../src/knos/preflight.py) |
| walks the buyer through a first invoice | `knos shadow <invoice>` counts it against the forge's own record, with no setup | [PILOT.md](PILOT.md), "How it starts: shadow mode" |
| settles a routine difference | each side recomputes the month; a difference is a named line | section 4 |

Nobody has onboarded a customer with them, so the 7,000 is **[budget, not measured]** like the 15,000. The first
Pilot is where the hours get counted.

**What 5,000 USD a year buys.** It is what a 100,000 USD Control account may cost to deliver and keep a gross margin
of 95%. In hours of a person, before any tool, chain fee or storage:

| an hour of support | hours a year | hours a month |
|---|---|---|
| 75 USD, the assumption above | 66.7 | 5.6 |
| 43.20 USD, from public wages (the inputs) | 115.7 | 9.6 |

A first installation, a first invoice walked through and a quarterly review use that up. **Automated onboarding
is therefore an economic requirement, not a convenience:** every routine step a person takes for a customer has
to become a command the customer runs. `knos bill margin --sensitivity docs/unit_costs.json` and
`knos.billing.support_hours` print these figures.

The worked customer's first month, at these costs: revenue 10,753.33, direct cost 1,260.20, gross margin 88.3%
(Control 85.0%, Meter 69.0%, Acceptance 99.8%). `tests/test_billing.py` holds the command to those figures.

## Micro-outcomes: a different delivery

An outcome of 0.99 USD is a real price: it is what Intercom lists for one Fin outcome
([intercom.com/pricing](https://www.intercom.com/pricing), read 7 Oct 2026). What Knos earns on one, and what it may
cost to deliver, from the price book's constants (`knos.billing`; `tests/test_business_docs.py` computes every figure
in this table):

| on one outcome of 0.99 | USD |
|---|---|
| Acceptance, 0.30% (netted with the payee's other small outcomes, so the 0.05 floor is paid once per release, not per outcome) | 0.00297 |
| Meter, one evaluation past the free ones | 0.002 |
| **What Knos earns** | **0.00497** |
| the most it may cost to deliver at a gross margin of 90% | 0.000497 |
| **the most it may cost to deliver at a gross margin of 95%** | **0.000249** |
| the same at 95% while the evaluation is still one of the month's 100,000 free ones (0.00297 earned) | 0.000149 |

So at 95% gross the direct cost of one micro-outcome must stay below about 0.00025 USD. Against the budget today:

- **The evaluation fits.** 0.00005 **[budget, not measured]** is about a fifth of the ceiling: one anchored batch a
  supplier a month, and no person in the path.
- **An accepted deliverable does not.** Its budget of 0.10 **[budget, not measured]** is about 402 times the
  ceiling, and even its target of 0.02 is about 80 times it. That cost is a person looking at an exception; at
  0.99 an outcome cannot carry one.
- **Netting moves transfers, not evaluation cost.** It turns a hundred releases into one, so the floor and the
  chain fees are paid once (leak 2). It does not make one outcome cheaper to judge or to dispute: each is still
  evaluated, and each difference is still a line someone settles.

What that means: high-value deliverables and micro-outcomes need different delivery. A deliverable of thousands
carries a person on its exceptions. A micro-outcome is judged by the check alone; its exceptions are handled in
bulk or as the separate, separately priced dispute service, never one by one inside the 0.30%. No micro-outcome has
been delivered for anyone, so none of these costs is measured.

## A second customer, worked

*(An example at the price book's prices. No such customer exists.)* Business plan, 1,000,000 evaluations a month,
120 million USD of accepted value a year in twelve even months, reconciled off chain, no record lookups.

| line | arithmetic | USD a year |
|---|---|---|
| Control, Business | | 100,000 |
| Acceptance | 12 × (1,000,000 × 0.30% + 9,000,000 × 0.20%) | 252,000 |
| Meter | 12 × 900,000 × 0.002 | 21,600 |
| Record | budgeted at zero | 0 |
| **What the customer pays** | 100,000 + 252,000 + 21,600 | **373,600** |

What it costs to deliver, with five suppliers and deliverables of 20,000 (6,000 in the year), at the unit costs
above: Control 15,000 + Meter 12 × (1,000,000 × 0.00005 + 5 × 0.1393) = 608.36 + Acceptance 6,000 × 0.10 = 600:
**16,208.36, a gross margin of 95.7%.** A gross margin of 95% allows 18,680. With Control at its target of 7,000
the cost is 8,208.36 and the gross margin 97.8%. Every cost in that sum but the batches is a budget.

**The hurdle.** Three to one on 373,600 is 1,120,800 USD a year of benefit to the buyer. That is a hurdle to be
measured in a pilot, not a claim: nothing shows that any buyer gets it, and no buyer has been asked
([PILOT.md](PILOT.md), "The benefit to demand before buying").

`knos bill estimate --plan business --evaluations 1000000 --accepted 120000000` prints the lines, and
`tests/test_billing.py` holds the year, its twelve months and the gross margin to these figures.

## Counted once: three accounting rules

Each is a test in `tests/test_billing.py`.

1. **An annual commitment is drawn down by use.** A month's Meter, Acceptance and Record charges come out of it;
   only what it does not cover is charged on top. It is never a second revenue line beside the use it pays for:
   a year of 1,300 USD a month of use under a 24,000 USD commitment is 24,000 USD, not 39,600.
2. **The relayer's tip and the chain costs it pays are the relayer's.** On a release on chain the funder pays the
   fee on top; the relayer takes its tip out of it and pays the transactions. With an outside relayer Knos counts
   the rest of the fee as revenue and none of the chain costs; when Knos relays, it counts the whole fee and the
   chain costs. Never the fee as revenue and the tip as a cost as well. `knos.billing.release_split`, knos_pay 2.2:

| a release of 1,000 | fee | tip | Knos's revenue | Knos's direct cost | the relayer's revenue | the relayer's cost |
|---|---|---|---|---|---|---|
| an outside relayer | 3.00 | 0.05 | 2.95 | 0.0000 | 0.05 | 0.0072 |
| an outside relayer, a payee's first payment | 3.00 | 0.30 | 2.70 | 0.0000 | 0.30 | 0.1872 |
| Knos relays | 3.00 | 0.05 | 3.00 | 0.0072 | 0.00 | 0.0000 |
| Knos relays, a payee's first payment | 3.00 | 0.30 | 3.00 | 0.1872 | 0.00 | 0.0000 |

3. **Money held or passed on is never revenue.** A reserve the customer funds, rent that returns and a supplier's
   principal are listed apart on an invoice (`held`), in no line and not in the total.

On devnet all of it is test money: 0 revenue.

## The comparison a buyer will make

| who | unit | price | source |
|---|---|---|---|
| Amazon Web Services, Bedrock AgentCore | a custom evaluation | 1.50 USD per 1,000: 0.0015 each, "model usage billed separately" | **[vendor page]** [pricing](https://aws.amazon.com/bedrock/agentcore/pricing/), read 6 Oct 2026 and again 8 Oct 2026 |
| The same, built-in evaluators | tokens | 0.0024 USD per 1,000 input tokens, 0.012 per 1,000 output tokens | the same page |
| The same, Policy | an authorization request | 0.000025 USD | the same page, read 7 Oct 2026 and again 8 Oct 2026 |
| Knos, Meter | an evaluation past 100,000 a month | 0.002 USD | [MARKET.md](MARKET.md), section 3; proposed, nobody has paid it |

The Meter costs a third more than the cloud's evaluation call. What it adds that an evaluation call does not:

- **A count both sides can recompute.** Buyer and supplier each keep a ledger; the chain holds the month's root.
- **Deduplication.** The same evidence sent twice is one evaluation, and a retry Knos caused is free.
- **Retention.** The evidence is kept so that a receipt verifies later without Knos.
- **A signed acceptance.** A third party signed the run that judged the work; the terms were fixed before it.

If a buyer needs none of the four, the cloud's call is cheaper and Knos has nothing to sell it. Counting alone
will face price pressure, and the Meter is not where Knos expects to earn ([MARKET.md](MARKET.md), "The
competition, stated plainly").

## What the customer pays in all

The fee is one part of four.

| part | who carries it | what is known |
|---|---|---|
| Fees | the buyer | the price book; the worked customer pays 130,240 USD a year |
| The customer's own compute | the buyer or the supplier, on its runners | 16 s of a runner for an evaluation at p50; 0.0016 USD at list price in a private repository, nothing in a public one |
| Integration | the buyer and each supplier | not measured; one workflow file for each repository |
| Exceptions | the buyer's and the supplier's people | not measured; the Pilot counts them |

Knos runs no customer test. The tests run on the customer's runners, on the customer's bill. That keeps the cost
out of Knos's gross margin. **It is not a saving for the customer:** the customer paid for those minutes before Knos and
pays for them after.

## What is not known

- What a relay costs for private repositories. No bill has been read.
- What a batch costs on a cluster. The count of transactions is measured; a run on devnet is not.
- What a real evidence bundle weighs. The one measured is a recorded fixture.
- How many tickets a million evaluations raise. Nobody has run a million.
- What relay, ingestion and monitoring cost for one evaluation. The 0.00005 is a budget.
- Whether a relayer will carry a payee's first payment of 20 or less at a loss. None has been asked.
- Priority fees on mainnet.
