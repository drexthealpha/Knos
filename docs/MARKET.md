# Market, money, and what can stop this

**The neutral meter for AI agent work: neither side keeps the count.**

Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check ([backtest.json](backtest.json)).
Of first agent pull requests that claimed passing tests, 17.8% had a failed check (147 of 826 repositories in the
Agent PR Index; [BENCH.md](BENCH.md)).

Both figures count failed checks. Neither is invoice leakage: a failed check is not always a failed test or a
false claim, and neither says what share of any buyer's spend is lost.

Nine parts: who buys and who sells; the adjacent market and the competition, with every source; the price book;
what each sale costs to deliver; the addressable market as a formula, and the fee a release actually pays; one
customer worked through, what a buyer must get back, how one customer expands, and the first steps; what a fork
can copy, why a fork at zero fee does not take it, and the moats in
the order they could form; devnet as test mode, and the phases; and what can stop this.

Every outside figure carries its link and one of three labels: **[vendor page]** (the seller's own price list or
product page), **[press]** (reported by someone else, often from an unnamed source), **[company-reported]** (the
company's own statement of its results; audited only where it is a public company's filing). Each was read on
4 Oct 2026 unless it says otherwise (5 or 6 Oct 2026 where the line says so). **[measured]** is ours, with where. **[assumption]** has no source. The rest is
arithmetic on those inputs. Nothing here is a forecast. Knos runs on Solana devnet and its money is test USDC. No
real money has moved, nobody has bought anything, and no buyer or supplier has been asked.

What the buyer hears first: **close a supplier's invoice with evidence both sides can check.**

## 1. Who buys, and who sells

**The market is agent work billed per outcome**: a merged change, a resolved conversation, an accepted milestone,
priced by the unit and invoiced by the supplier who did it. Section 2 names vendors that bill this way today, with
their prices. A bounty on one issue is the smallest example of it: one buyer, one outcome, one payment.

**The buyer is the person accountable for approving a supplier's invoice**: an engineering leader or a finance
owner at a company that buys software work per outcome from an agent vendor or an agency. The question that person
has to answer is whether the invoice can be approved, explained afterwards, and shown to follow the company's own
rules. Their questions, line by line: what did we buy, from whom, at what price; which evidence establishes
acceptance; was this deliverable billed before; did the approver have authority; what happens on a revert or a
dispute; can finance reproduce the statement next quarter; and who answers when the service fails. To the last
one the answer today is: nobody but the founder.

Three words are used the same way everywhere. A **deliverable** is the commercially meaningful thing bought: an
order and a milestone. It has one identity whatever number of pull requests carry it. An **evaluation** is one run
of an acceptance policy on one artifact for one deliverable (customer, order, artifact, policy version,
milestone); it is the Meter's billable unit. An **accepted outcome** is a deliverable whose evaluation passed: it
is what a vendor's per-outcome price multiplies, one per deliverable, however the work was split.

**The second user is the supplier**: an agent vendor or an agency. A supplier needs acceptance terms that cannot be
changed after the work, a count it can check itself, and a way to be paid, or to show what is owed, when the buyer
does nothing.

**The smallest example is a maintainer with a 20 USDC bounty on an issue.** It is where the product was first
proven, and it is not the size of the market: every open bounty on every board came to 64,291 USD on 2 Oct 2026
([BountyOS](https://bountyos.rovidev.com/en/github-bounty-board/), read that day), and 0.30% of that is 193 USD.

What each of them gets today:

| who | what Knos gives them | where it is |
|---|---|---|
| Buyer | Terms hashed into the order when it is funded: named checks, allowed paths, the workflow commit. A count of accepted outcomes that neither side keeps. A statement both sides compute to the same totals. | `knos-pay` orders; `knos-meter`; `knos statement` and the ledger files each side keeps |
| Supplier | Terms nobody can change after funding. Settlement without the buyer after a merge in a public repository. Its own count of the month on chain, beside the buyer's. | `knos settle --neutral`; `ClaimBatch` in `knos-meter` |
| Maintainer | One comment funds an issue; one merge pays it. | `/knos fund` |

What neither gets yet: private repositories under a contract, money a bank accepts, single sign-on, a company
that answers for the service, an outside security review. [CONTROLS.md](CONTROLS.md) has the list. Some rows of
the table above name instructions of the 2.1 and 1.1 builds; whether those are live on the public program ids is
in `web/upgrades.json`, and [CAPABILITIES.md](CAPABILITIES.md) gives each capability's stage.

## 2. The adjacent market

### Vendors already bill per accepted outcome, and each counts its own

| vendor | the unit it bills | price | who counts | source |
|---|---|---|---|---|
| Sourcegraph, Agentic Batch Changes | "you pay per changeset merged into your codebase" | not published: the post sends the reader to its Enterprise Portal for credit rates | Sourcegraph | **[vendor page]** [changelog, 14 Sep 2026](https://sourcegraph.com/changelog/agentic-batch-changes-ga), read 6 Oct 2026 and again 7 Oct 2026 |
| GitStart | "you only pay for merged PRs" | not published | GitStart | **[vendor page]** as listed by [Y Combinator](https://www.ycombinator.com/companies/gitstart) |
| Intercom, Fin | a "Fin outcome" | from 0.99 USD ("From $0.99 per Fin outcome") | Intercom | **[vendor page]** [pricing](https://www.intercom.com/pricing), read 6 Oct 2026 and again 7 Oct 2026 |
| Zendesk, AI agents | an "automated resolution": resolved "without any escalation to a human agent" | 1.50 USD committed, 2.00 USD pay-as-you-go | Zendesk | **[vendor page]** [pricing](https://www.zendesk.com/pricing/), read 6 Oct 2026 and again 7 Oct 2026 |
| Salesforce, Agentforce | a conversation, or Flex Credits per action | 2 USD per conversation; 500 USD per 100,000 Flex Credits, an action taking 20 | Salesforce | **[vendor page]** [pricing](https://www.salesforce.com/agentforce/pricing/), read 6 Oct 2026 and again 7 Oct 2026 |

In every row the seller keeps the count the buyer is billed on. That is the gap. These five prices show that
sellers price by outcome. They do not show that any buyer wants a separate neutral meter: nobody has been asked.
Two people who sell or study these contracts say so:

- "Attribution disputes are where these contracts fall apart. Outcome-based pricing only scales where both parties
  can agree on attribution" (Sidharth Ramsinghaney, Director of Strategy and Operations at Twilio; **[press]**
  [CIO, 16 Jun 2026](https://www.cio.com/article/4184688/it-hurtles-toward-the-great-enterprise-pricing-reset.html),
  read 3 Oct 2026).
- Zendesk's president on the edge cases: "If the AI resolves 90% of the problem, but 10% goes to a human agent, we
  don't count it." (**[press]**
  [Channel Dive, 31 Aug 2026](https://www.channeldive.com/news/agentic-ai-outcome-pricing-models-zendesk-gartner/829209/),
  read 3 Oct 2026). The seller decides them.

For code, the count can be wrong in a way we measured. Of 241 merged agent pull requests whose description said
tests or CI pass, 30 had a failed check at the head commit: 12.4% **[measured]** (95% interval 8.9% to 17.2%).
The pull requests and each one's checks are in [agent_pr_ci.json](agent_pr_ci.json) (303 with finished CI, read on
1 Oct 2026); the count of the merged ones is in [backtest.json](backtest.json), `sample.merged.overall`, and
[BENCH.md](BENCH.md), "Merged anyway", prints it. **That is a count of failed checks, not of money.** A failed
check is not always a failed test, a defect or a false claim; no buyer's invoices have been read; and nothing here
says what share of anyone's spend was paid for work that did not meet its terms. It is not a promise that any buyer
saves anything.

Code has what support does not: a third party that already records the result and signs statements about it.
GitHub and GitLab record the merge and the checks, and sign a CI run. Knos counts and settles on that signature,
for any seller, in the buyer's own system of record.

### Where the same count applies next

Code comes first because its artifacts, checks and workload identities are already signed by a third party. Each
further kind of work follows only where evidence of acceptance exists that neither side wrote.

| kind of work | the outcome that is billed | the evidence a neutral count needs | in Knos today |
|---|---|---|---|
| Software delivery | an accepted change, migration, fix or milestone | the commit, the agreed tests, deployment evidence, a revert or warranty window | the product: [OUTCOMES.md](OUTCOMES.md), "Funded by a comment, paid by the suite" and "A Kubernetes cluster signs an outcome" |
| Customer operations | a resolution, as the contract defines it | the customer's events, the escalation history, a reopening window, an agreed resolution policy | [OUTCOMES.md](OUTCOMES.md) gives its stage and what a signing system of record would have to do |
| Data operations | an accepted transformation or labelled dataset | provenance, schema checks, sampling rules, quality thresholds | nothing |
| Back-office processing | a completed reconciliation or an approved transaction | events from the system of record, authority checks, how an exception was resolved | nothing |
| Agent services bought by other agents | an accepted API call or workflow deliverable | an identity that works across providers, outcome evidence, usage and contract terms | one example of an agent paying an agent on a signed result ([`examples/agent_pays_agent`](../examples/agent_pays_agent)); no customer |

Five rows, one of them built. No figure sizes any of them here, and [OUTCOMES.md](OUTCOMES.md) is the only place
that says what stage an outcome other than a merged change has reached.

### How much agent work there is

| what | figure | label and source |
|---|---|---|
| Cursor's annualised revenue | above 4 billion USD in early June 2026 | **[press]**, "a person familiar with the matter": [Dealroom, 9 Jun 2026](https://dealroom.co/news/134107-cursor-tops-4b-annualized-revenue/) |
| Claude Code's run-rate revenue | "over $2.5 billion" | **[company-reported]**, not audited: [Anthropic, 12 Feb 2026](https://www.anthropic.com/news/anthropic-raises-30-billion-series-g-funding-380-billion-post-money-valuation) |
| Devin's annual recurring revenue | 492 million USD | **[company-reported]** by Cognition and not audited, read in **[press]**: [TechJack, 28 May 2026](https://techjacksolutions.com/ai-brief/cognition-ai-raises-1b-at-26b-valuation-as-devins-arr-report/) |
| Pull requests on GitHub that involve an agent | "1 in 3" | **[company-reported]**: Satya Nadella on Microsoft's earnings call of 29 Jul 2026 ([transcript](https://www.fool.com/earnings/call-transcripts/2026/08/07/microsoft-msft-q4-2026-earnings-call-transcript/)) |
| GitHub Actions jobs | 71 million a day | **[company-reported]**: [GitHub, 11 Dec 2025](https://github.blog/news-insights/product-news/lets-talk-about-github-actions/) |
| Enterprise spend on generative AI in 2025 | 37 billion USD, 4.0 billion of it on coding | **[company-reported]** research by an investor: [Menlo Ventures, 9 Dec 2025](https://menlovc.com/perspective/2025-the-state-of-generative-ai-in-the-enterprise/) |

These are revenue run rates of three sellers, one count of activity and one estimate of spend. They are different
measures of different years, and they are not added. Almost all of that revenue is billed by the seat or by the
token today.

### Software work that is already paid on acceptance

| what | figure | label and source |
|---|---|---|
| IT services spending worldwide, 2026 | 1.57 trillion USD (forecast) | **[press]** release of an analyst's forecast: [Gartner, 27 Jul 2026](https://www.gartner.com/en/newsroom/press-releases/2026-07-27-gartner-forecasts-worldwide-it-spending-to-grow-14-point-2-percent-in-2026-totaling-6-point-37-trillion) |
| Work bought through Upwork, 2025 | 4.03 billion USD of gross services volume; Upwork's revenue 787.8 million USD. Revenue ÷ volume is 19.6%: our division, not a rate Upwork states. | **[company-reported]**, a public company's results: [Upwork, results for 2025](https://investors.upwork.com/news-releases/news-release-details/upwork-reports-fourth-quarter-and-full-year-2025-financial) |
| Paid to security researchers through Immunefi | "$140M+" across "650+ protocols" | **[company-reported]**, not audited: [immunefi.com](https://immunefi.com) |
| Paid through Superteam Earn | 15.9 million USD in total | **[company-reported]**, not audited: the site's own [statistics](https://superteam.fun/api/homepage/stats), field `totalInUSD` |

The last two rows are buyers who already pay strangers per outcome in stablecoins and need no bank. They are the
shortest path from devnet to real settlement.

No source says what part of any of these would move to a neutral count or to payment on signed acceptance. The
part that goes through Knos today is zero. We do not multiply any of them by a share.

### Beyond code: neutral measurement of agent work priced per outcome

The meter is not a GitHub feature. The verifier takes any RS256 workload identity, which is the token format of
GitLab CI, of the cloud providers' workload identity and of most enterprise identity providers. Any system of
record that can sign "this workload ran and produced this result" can feed the count. The support rows of the
first table above are the same dispute as code, at larger volume: a resolution the seller counts and the buyer
pays for.

The hard part: code has a third party that already signs the result, and support does not. Each new kind of work
needs its own signed system of record, an agreed definition of the outcome (what a resolution is, how long it may
be reopened), and an acceptance policy someone maintains. That is one attestor at a time. None beyond code exists
in Knos today; [OUTCOMES.md](OUTCOMES.md) has three worked examples and their stage.

The analogue is advertising. Sellers of advertising counted their own impressions, and measurement by a company
that neither buys nor sells the advertising became a business of its own:

| company | what it sells | revenue | free cash flow | label and source |
|---|---|---|---|---|
| DoubleVerify | independent measurement and verification of digital advertising | 748.3 million USD in 2025 | 172.7 million USD in 2025: 211.2 million of cash from operations less 38.5 million of property and equipment, 23% of revenue | **[company-reported]**, a public company's results: "Total revenue of $748.3 million, an increase of 14%", and "Free cash flow" of 172,654 thousand USD in its reconciliation table: [DoubleVerify's release of its 2025 results, 26 Feb 2026](https://s206.q4cdn.com/961864615/files/doc_financials/2025/q4/DoubleVerify-Q4-FY25-Earnings-Release.pdf), the file its [investor site](https://ir.doubleverify.com) serves, read 6 Oct 2026 |
| Integral Ad Science | the same | 530.1 million USD in 2024, the last full year it reported as a listed company | not read | **[company-reported]**: [IAS, 28 Feb 2025](https://www.stocktitan.net/news/IAS/ias-reports-fourth-quarter-and-full-year-2024-financial-1k4428b0o95b.html), read 5 Oct 2026; taken private since ([PE Hub](https://www.pehub.com/novacap-completes-take-private-buyout-of-media-measurement-platform-integral-ad-science-private/)) |

**This is an analogue, not proof.** Those are two companies in another industry. They show that buyers have paid
a third party to count what a seller bills. They show too what the business keeps: the larger of them turned 23% of its revenue into free cash flow, with
a sales force and a product organisation. They do not show that buyers of agent work will pay, and no figure here
is a size for Knos's market.

### The competition, stated plainly

Counting what an agent does and moving money for it are both sold already, by companies far larger than Knos.
Each row was read on the vendor's own page on 7 Oct 2026, and every price in it was the same as on the earlier
reading.

| who | what it sells | source |
|---|---|---|
| Amazon Web Services, Bedrock AgentCore, Evaluations | a custom evaluation at 1.50 USD per 1,000, "model usage billed separately"; built-in evaluators at 0.0024 USD per 1,000 input tokens and 0.012 per 1,000 output tokens | **[vendor page]** [pricing](https://aws.amazon.com/bedrock/agentcore/pricing/), read 6 Oct 2026 and again 7 Oct 2026 |
| The same, Policy | an authorization request at 0.000025 USD; writing a policy from plain language at 0.13 USD per 1,000 input tokens | the same page, read 7 Oct 2026 |
| Stripe, Billing | subscription and usage billing at 0.7% of billing volume; its Meters API is part of that price, "with up to 100M events per month included" | **[vendor page]** [pricing](https://stripe.com/billing/pricing), read 5 Oct 2026 and again 7 Oct 2026 |
| Stripe, agentic commerce | sellers offer products through agents and take machine payments for API calls (it names the x402 protocol); an agent pays from a wallet its user controls. The page states no separate price | **[vendor page]** [documentation](https://docs.stripe.com/agentic-commerce), read 7 Oct 2026 |
| MergePay | payment on merge with "No platform fee": a relayer fee the funder sets, 0.03 USD an award by default, against about 0.016 USD of gas | **[vendor page]** [mergepay.fun](https://mergepay.fun), read 6 Oct 2026 and again 7 Oct 2026 |

So "we meter agents and move payments" is not a difference. A cloud platform meters the agents that run on it,
and a billing company bills what its customer, the seller, reports. In both the count belongs to one side or to
that side's vendor.

**Generic agent metering will face price pressure.** A cloud lists an evaluation at 0.0015 USD and a policy
decision at 0.000025; a billing company includes a hundred million metered events a month in its percentage; a
payment on merge is sold with no platform fee. The Meter's 0.002 is a third more than the cloud's evaluation
call and will not hold as a price for counting alone. Knos does not plan on it holding.

What Knos is that they are not, in three lines:

- The acceptance is reproducible by anyone: terms fixed before the work, evidence a third party signed.
- It is the same record for every supplier, whatever platform its agents run on.
- Each side's count stands beside the other's, so a difference is a named dispute and not an invoice line.

**The difference Knos has to earn is independent acceptance across vendors, including the disagreements.** The
price that follows from it is Acceptance, on the dollar, and not the Meter: what an evaluation call does not give
is a count both sides can recompute, deduplication, retention, and a signed acceptance
([UNIT_COSTS.md](UNIT_COSTS.md), "The comparison a buyer will make").

## 3. The price book

| Line | Unit | Price | Who pays | Where it is enforced |
| --- | --- | --- | --- | --- |
| Check | pull request or artifact checked | free, forever | nobody | nowhere |
| Meter | evaluation | 100,000 a month free per organisation, then 0.002 USD | buyer | prepaid credits |
| Acceptance | dollar released or reconciled against a signed acceptance | 0.30%; by contract 0.20% on monthly value above 1M (the rate never goes below 0.20%); small tickets are netted: outcomes under 20 USD accumulate and settle as one release per payee per period, charged 0.30% of the netted amount with the 0.05 floor once per release; no cap | funder, on top of the amount | knos_pay at release (on chain: 0.30% and the floor; volume rates are a rebate by contract, off chain) |
| Record | lookup of a supplier's delivery record through the machine-priced API | 0.10 USD a lookup, paid per call by the caller (an agent, a marketplace, an underwriter) through the knos-order/x402 flow; the public record page and its file stay free | the buyer, marketplace or insurer reading it | `knos record serve` (anyone runs it; Knos hosts none); budgeted at ZERO revenue until someone buys it |
| Control | organisation, per year | Team 25,000; Business 100,000; Enterprise from 400,000 (not deliverable yet: it needs single sign-on, private deployment and support that do not exist) | buyer | contract |
| Pilot | one buyer, two suppliers, 30 days, one reconciled invoice | 2,500 USD, credited against year one | buyer | contract |

These are proposed prices. Nobody has paid any of them, and nobody has been asked whether they would. Nothing has
been sold; there is no legal entity to invoice from; on devnet every fee is test money and zero revenue.

**The rule: Knos never charges the party being rated.** A supplier pays nothing to be counted, to
keep its ledger, to verify a receipt or to appear in the Agent PR Index. The rated party never pays for its
rating, for a better score or for the resolution of a false verdict. The buyer pays, or nobody does.

**Connecting a supplier costs nothing.** There is no fee per supplier, at any number of suppliers: a fee there
would tax the reuse of a supplier by a second buyer, which is the first thing section 7 says has to be earned.

Acceptance is one line where an earlier price book had two. It replaces the percentage on settlement and the
percentage on reconciled invoice value, and the cap that went with the second is gone.

Three things changed in this book, each because the arithmetic of the last one did not hold
([UNIT_COSTS.md](UNIT_COSTS.md), "The leaks"):

- **The rate never goes below 0.20%.** The 0.10% tier above 10 million a month is withdrawn.
  **A 0.20% floor is a pricing policy, not a law.** Nothing enforces it but a contract Knos would have to win. It
  holds only while a buyer gets more from a signed acceptance than the fee costs and no alternative is cheaper in
  all: a billing company at 0.7% of volume with metering included, and a fork that charges nothing, are both
  alternatives.
- **Small tickets are netted.** A floor of 0.05 on every outcome is 5.05% of a 0.99 outcome. Outcomes under 20
  USD accumulate, and settle as one release per payee per period: 0.30% of the netted amount, the floor once.
- **Record is priced for a machine.** 0.10 USD a lookup, paid per call by whoever reads it. There is no
  subscription.

### The billing rule

**A month's invoice = Control + Meter + Acceptance on value reconciled off chain + Record lookups.**

- **Never twice.** Value released on chain paid its Acceptance fee there, to the program, at release. The
  invoice leaves it out. A customer-month says which accepted deliverables the program released.
- **The volume rates are marginal and by contract.** A Control plan is the contract. A month's accepted value is
  laid end to end, value released on chain first: the first 1,000,000 USD pays 0.30% and what lies above it pays
  0.20%. No rate is lower than 0.20%. Each deliverable pays the rate of the part of the month it lies in, and at
  least 0.05 USD. There is no cap.
- **Small tickets are netted.** An accepted outcome under 20 USD that names its payee is not charged by itself.
  A payee's small outcomes of a period are one release: 0.30% of the netted amount, and the 0.05 floor once for
  the release. A hundred outcomes of 0.99 to one payee pay 0.30 netted, where one by one they would pay 5.00. One
  such outcome alone in a period still pays the floor. An outcome that names no payee is charged by itself.
- **The rebate.** The program takes 0.30% of every release whatever the month's volume. What the volume rates
  would not have taken is credited on the invoice. On devnet that is a credit against test money.
- No charge for a duplicate, an infrastructure failure or a retry Knos caused.
- An accepted deliverable is counted once, however many evaluations it took.
- A rejection that ran correctly is an evaluation, not an outcome: the Meter counts it and Acceptance does not.
- **Once, whichever rail pays.** A deliverable released by the program paid there; one paid by a bank transfer
  or any other rail pays on the invoice. The same deliverable listed under both is charged once.
- **A rail's own charge is not Knos's price.** A bank's wire fee or a network's fee is listed apart from the
  software price, in no line of it and not in its total (`rail_charges`; the invoice prints `payable` beside
  `total`).
- **The credit rule.** Value that is disputed or reversed never carries an Acceptance charge: in the month it was accepted it is left out of the reconciled value, and when it was accepted in an earlier month the fee it was charged, 0.30% of it unless the earlier invoice shows less, is credited on the next invoice.
- Limits are shown before work starts: `knos bill estimate` and the calculator on the site's Pricing page print a
  year from five inputs: the plan, evaluations a month, accepted value, the share of it released on chain, and
  record lookups.
- Commitments are sold by the year and drawn down by use. A price by the year is billed in twelve parts that add up
  to it to the cent; a month's Meter, Acceptance and Record charges come out of what is left of a commitment, and
  only what the commitment does not cover is charged on top. A commitment and the use it pays for are never both
  counted.

The rule is code: [`src/knos/billing.py`](../src/knos/billing.py) takes a customer-month and returns the invoice
with every line and the rule that produced it (`knos bill explain month.json`). `knos bill margin month.json
docs/unit_costs.json` prints the same month's revenue, direct cost and gross margin line by line
([UNIT_COSTS.md](UNIT_COSTS.md)). The site's calculator and the Python are tested against one file of years and
months worked by hand ([`tests/data/billing_vectors.json`](../tests/data/billing_vectors.json)). No program on
chain computes Control, a Record lookup or the volume rates.

**Why Acceptance is a price on value.** A flat price per evaluation cannot grow with the value it accepts: an
evaluation that accepts a 12 USD change and one that accepts a 40,000 USD milestone both cost 0.002 USD at the
Meter. Acceptance is charged on the dollar, once, when a signed acceptance releases or reconciles it: 0.04 USD
would be the rate on the first and the floor makes it 0.05; the second pays 120 USD.

**What the program takes at release, shown before funding.** One rate and a floor, for jobs and orders alike:
`fee = max(0.05, floor(amount × 30 / 10,000))` in the token's base units. The funder pays it on top of the amount.

| release | fee | as a share |
|---|---|---|
| 5 | 0.05 | 1.00% |
| 20 | 0.06 | 0.30% |
| 100 | 0.30 | 0.30% |
| 1,000 | 3 | 0.30% |
| 5,000 | 15 | 0.30% |
| 100,000 | 300 | 0.30% |

A release under 16.67 pays the floor, which is more than 0.30% of it: 5 test USDC pays 1.00%. The relayer's tip
comes out of the fee and is never more than the fee. On devnet the fee is test money: zero real revenue.

Where each price is fixed:

- **Check.** Nowhere: it is free, and stays free. The claim check, the Stop hook, the MCP tools, the Agent PR
  Index and on-chain verification cost nothing, and they are the distribution.
- **Meter.** In prepaid credits. It moves no customer money: it counts evaluations. Sending the same evidence
  again is not another evaluation. An evaluation that rejects is billable, because evaluating it took the same
  work; a Knos failure is not. The 0.002 covers processing the attestation, keeping the evidence and reconciling
  the count. It does not cover running the customer's tests or an agent's inference: those run in the customer's
  own CI, on the customer's bill. `knos-meter` on devnet is unchanged in this release and still holds the last
  price book's constants in test credits ([METER.md](METER.md)); the price here is the contract's.
- **Acceptance.** In `knos-pay`, at release: 0.30% and the floor, taken on top of the amount when someone is paid;
  a refund returns amount and fee. Under a contract a `Plan` can lower the rate for one owner; the program's own
  bound is 0.10%, and the price book's contracts go no lower than 0.20%. No such contract exists. Netting is
  reconciled off chain: on chain the least order is 5 test USDC, and each release pays the floor. Value a buyer and a supplier reconcile off chain is invoiced off chain at the
  same rate, by `src/knos/billing.py`, and needs no customer money on chain. On devnet an order holds between 5
  and 100,000 test USDC; a build for real money decides its own cap. The second deployment is upgradeable only
  through a multisig with a public 48-hour delay, until an outside review, so any change to these constants is
  public two days before it can run.
- **Record.** Through `knos record serve`, a server anyone runs and Knos hosts none of: a supplier's delivery
  record is also a static file, and the public record page and its file stay free. Revenue from lookups is
  budgeted at zero until someone buys one. The price is for a lookup by a machine: an agent, a marketplace or an
  underwriter pays 0.10 USD for the call, through the same order flow that pays for work ([X402.md](X402.md)).
- **Control.** In a contract. Nothing on chain enforces it, and the software it covers is in this repository under
  the MIT licence. What is sold is policy, budgets, private repositories, statements, exports, and a party that
  answers for the service. That party does not exist yet. Team is one business unit; Business is several
  suppliers with approval workflows and accounting exports; Enterprise is not deliverable.
- **Pilot.** In an invoice, off chain: one buyer, two suppliers, 30 days, one reconciled invoice, and the findings
  as numbers. Its price is credited against year one if the buyer goes on. It starts in shadow mode: the count runs beside the
  invoices the buyer already receives and changes nothing. [PILOT.md](PILOT.md) is the offer in full.
- **Not offered: index data, an advance, assurance.** The Agent PR Index is free. An order can already hold back a
  share for a warranty period and return it if the work is reverted, and a payee can assign an order's payment to
  another wallet; pricing an advance or a warranty needs a history of losses, a licence and real money, and there
  is none of the three.

## 4. What each sale costs to deliver

Inputs:

- A Solana transaction costs 5,000 lamports per signature **[vendor page]**
  ([Solana docs](https://solana.com/docs/core/fees)).
- An account must hold rent for its bytes. The figure used here is what the clusters answer: on 4 Oct 2026
  `getMinimumBalanceForRentExemption` returned 1,097,280 lamports for 88 bytes, 1,137,920 for 96 and 1,488,440 for
  165 **[measured]**, which is (128 + bytes) × 5,080 lamports. [METER.md](METER.md), "What an evaluation costs in
  each mode", says which cluster answered which and has the same arithmetic in full; this page and that one use the
  same numbers. (The local simulator the tests run in charges more per byte; no figure here comes from it.)
- SOL is taken at 121.50 USD: [CoinGecko](https://www.coingecko.com/en/coins/solana) and
  [Coinbase](https://www.coinbase.com/price/solana) quoted 121.49 and 121.46 on 4 Oct 2026, as METER.md records.
  Every USD figure below moves with it.
- The meter's tables count 3 transactions of one signature each for one signed token, two that verify it and one
  for the meter's instruction, as METER.md does: 15,000 lamports, 0.0018 USD.

### A 100 USDC order

| | USDC | note |
|---|---|---|
| The funder pays | 100.30 | the amount and 0.30% on top |
| The payee receives | 100.00 | the posted amount, in full |
| The fee | 0.30 | the relayer's tip comes out of it and is never more than it |

What the relayer spends against that tip: signatures, and on a payee's first payment the rent of a token account
of 165 bytes, 1,488,440 lamports, 0.181 USD. Carrying one token to the
chain took 7 transactions and 35,000 lamports (0.0043 USD) on the first deployment **[measured]**, and 2
transactions on the second **[measured in the simulator]**; a relayer's cost on the second deployment is not
measured on devnet ([BENCH.md](BENCH.md), "What a relayer pays"). Priority fees, which a busy mainnet may need,
are in no measurement.

So the chain is not the cost of a settlement. The costs are people: support, compliance, an outside review. None
of them exists yet and none is measured.

### 1 million metered evaluations in a month

A customer with 1,000,000 evaluations in a month has 900,000 billable ones: 1,800 USD at 0.002.

| | individual mode (`Record`) | batch mode (`RecordBatch`) |
|---|---|---|
| What is written | One marker account of 88 bytes per evaluation, so that a retry is free | No account per evaluation. One signed token carries the count, the totals and a Merkle root of a batch; one Ledger account of 96 bytes per buyer, seller and month holds the totals and a running hash |
| Rent per evaluation | 1,097,280 lamports, 0.1333 USD: 67 times the 0.002 price | none |
| Rent for the month | 1,097.28 SOL, 133,320 USD, locked at the month's end. The program returns all of it to the relayer from two hours into the next month (`CloseMark`), so it is working capital, not a cost | 1,137,920 lamports, 0.14 USD, once, and kept: the Ledger is the record and is never closed |
| Signatures | 3 transactions per evaluation: 15 SOL, 1,822.50 USD | 3 transactions per batch: at 5,000 evaluations a batch, 200 batches, 0.003 SOL, 0.36 USD |
| Chain cost per evaluation | 0.0018 USD spent, and 0.1333 USD locked for up to a month | 0.00000036 USD |
| Where the detail lives | on chain, one account each | in a ledger file each side keeps; the chain holds the root, so either side can prove one evaluation was counted, and neither can change the month afterwards |

Batch mode exists so that rent no longer exceeds the price. Individual mode stays for an evaluation that has to
stand on chain by itself. The supplier's own count of the same month (`ClaimBatch`) costs the supplier's relayer
the same signatures and one more Ledger account, and no fee. Neither mode's cost has been measured on devnet.

**Gross margin, not operating margin.** Every margin in this document and in [UNIT_COSTS.md](UNIT_COSTS.md) is
gross: revenue less the direct cost of delivering it. Operating margin also subtracts building, selling and
administering, and none of those costs is known, so none is printed.

**The gross-margin budget.** At 0.002 per evaluation, a gross margin of 90% **[assumption: a target]** leaves
0.0002 USD per evaluation to deliver it, and 95% leaves 0.0001. The monthly batch is the default delivery: one
anchored batch for each buyer and supplier, 0.14 USD a month whatever the count, so the chain's cost per
evaluation tends to zero. The budget for the rest is 0.00005 USD an evaluation, and it is not measured: storing
and serving the ledgers, running a relay, and monitoring. The free 100,000 a month cost the same to deliver, at
most about 60 USD a year for each organisation at that budget: that is acquisition cost, and it is said as one.
Running the customer's tests is not in it: they run in the customer's own CI, on the customer's bill.
[UNIT_COSTS.md](UNIT_COSTS.md) has every unit, what is measured and what is a budget, and the ceilings.

## 5. The addressable market, and the fee actually collected

We do not call IT services spending, or the revenue of the coding-agent sellers, Knos's market. The addressable
market is built from accounts that can be named:

**qualified organisations × contract value + billable evaluations × realised price,**
and, once real money settles, **+ value released × the Acceptance rate.**

**What makes an organisation qualified.** All four, each checkable in a first conversation:

1. **Measurable spend** on work bought per outcome from outside suppliers (agent vendors, agencies, contractors
   paid per merged change or per milestone), from two suppliers at least.
2. **Acceptance criteria explicit enough to write down** before the work: checks that must pass, paths that may
   change, a milestone. Work judged by taste does not qualify.
3. **A buyer with authority**: the person who approves the supplier's invoice and can sign for a tool.
4. **A problem worth another system**: disputed lines, duplicate billing, or days between acceptance and approval
   that somebody already complains about.

Each input has to be shown, and none is today: qualified organisations are 0 because nobody has been asked,
billable evaluations are 0, and the realised price is unknown, because the free allowance and annual
commitments come off the list price first. No source counts organisations that meet the four conditions, so this page
prints no total.

The Acceptance line is close to "value × 0.30%", and the floor is where it is not:

| release | fee the funder adds | as a share of the release |
|---|---|---|
| 5 | 0.05 | 1% (the floor) |
| 20 | 0.06 | 0.3% |
| 100 | 0.30 | 0.3% |
| 1,000 | 3.00 | 0.3% |
| 5,000 | 15.00 | 0.3% |
| 100,000 | 300.00 | 0.3% |

So 1 million USD released is 3,000 USD of fees in releases of 100 or of 100,000, and 10,000 USD in releases of 5.
The relayer's tip comes out of each fee. All of it is test money while settlement is on devnet.

What is and is not revenue:

- A subscription under a signed annual contract is recurring revenue. There is none.
- Metered evaluations are consumption: revenue when invoiced, not recurring revenue. There is none.
- Customer money in escrow, prepaid credits not yet used, rent that returns, money a financier advances and the
  payments a customer makes to its suppliers are never Knos's revenue.

## 6. One customer, worked; how one customer expands; the first steps

**One customer on the Business plan** *(an example at the price book's prices; no such customer exists)*:
110,000 evaluations a month and 10 million USD a year of accepted supplier invoices, reconciled off chain, none of
it released on chain. That is 833,333 USD a month, under the first million, so all of it pays 0.30%.

| line | arithmetic | USD a year |
|---|---|---|
| Control, Business | | 100,000 |
| Meter | (110,000 − 100,000) × 0.002 × 12 | 240 |
| Acceptance | 10,000,000 × 0.30% | 30,000 |
| **What the customer pays** | 100,000 + 240 + 30,000 | **130,240** |

`knos bill estimate --plan business --evaluations 110000 --accepted 10000000` prints the same lines. However many
suppliers that customer connects, the lines are the same.

**A second customer on the Business plan** *(an example; no such customer exists)*: 1,000,000 evaluations a
month and 120 million USD a year of accepted value in twelve even months, reconciled off chain. Each month's 10
million crosses the first million, so 9 million of it pays 0.20% by contract. Record lookups are budgeted at zero.

| line | arithmetic | USD a year |
|---|---|---|
| Control, Business | | 100,000 |
| Acceptance | 12 × (1,000,000 × 0.30% + 9,000,000 × 0.20%) | 252,000 |
| Meter | 12 × 900,000 × 0.002 | 21,600 |
| **What the customer pays** | 100,000 + 252,000 + 21,600 | **373,600** |

Three to one on that price is 1,120,800 USD a year. **That is a hurdle to be measured in a pilot, not a claim.**
[UNIT_COSTS.md](UNIT_COSTS.md), "A second customer, worked", has what it costs to deliver: a gross margin of 95.7%
at today's budgets.

**The first customer to look for** is the one for whom that hurdle could be true. It meets the four conditions
of section 5, and three more that make the first sale short: the work is code in repositories a forge already
signs for; the person who approves the suppliers' invoices does it by hand today; and it can start in shadow
mode, with no change to how anyone is paid. Nobody matching that has been asked.

### What a buyer must get back

That customer needs a measured reason to spend it. The rule a buyer should hold Knos to is a benefit of three
times the price, measured on the buyer's own data: 390,720 USD a year against 130,240. The benefit is measured
in pilots, never derived from the public failed-check statistics. Where it would have
to come from: hours spent preparing and checking suppliers' invoices, invoice lines disputed or paid twice, work
paid for that did not meet its acceptance terms, and days between acceptance and approval. An hour saved counts
only when it lowers what the buyer spends or lets it not hire. **Nobody has measured
any of these with Knos, and Knos has not shown that benefit.** The [Pilot](PILOT.md) exists to measure them once,
for 2,500 USD, before anyone is asked for an annual contract.

The fee is not the whole of what the customer pays. Its total cost is the fees, its own compute (the tests run on
its runners), the integration, and the exceptions its people still handle. Moving tests onto the customer's
runners is a cost Knos does not carry, not a saving for the customer ([UNIT_COSTS.md](UNIT_COSTS.md)).

**How one customer expands.** Five steps, each of which the customer takes for its own reasons. None has
happened.

| step | what happens | what it costs the customer | the measure |
|---|---|---|---|
| 1. Land in shadow mode | The free count runs beside one supplier's invoices for a period. No money moves through Knos and no process changes. | nothing | organisations with a shadow count running |
| 2. Convert on the first disputed line | The first statement that names a line both sides have to settle is what a Pilot is bought for. | 2,500 USD, credited against year one | shadow counts that became a Pilot |
| 3. Expand by supplier | Each further supplier is connected once, by the buyer. | nothing: connecting a supplier costs nothing | suppliers per buyer |
| 4. Expand by vertical | A second kind of work with its own signed record (support resolutions, data operations) opens a second budget in the same company. | a second policy, and its evaluations | kinds of work per buyer |
| 5. Expand by usage | The customer's agents do more work, and the count and the accepted value grow with them. | Meter and Acceptance | billable evaluations and accepted value per buyer, period on period |

Every measure reads zero today.

**What a first sale needs.** No mainnet: Control, Meter, Acceptance on value reconciled off chain and the Pilot
are software billed off chain. It needs a legal entity to invoice from and one organisation to say yes. Today there is no
entity and nobody has been asked.

## 7. What a fork can copy, and the moats in the order they could form

Knos is MIT. Anyone can deploy the same programs with every fee set to zero, and MergePay already charges no
platform fee ([COMPARE.md](COMPARE.md)).

**What a zero-fee fork can copy:** all of the code; the verifier, which is free for any program to read; the
public settlement fee, since the program tips whoever relays and anyone can relay at no loss; and the public
payment history, which anyone can read from the chain. Settlement alone will be priced toward zero, which is why
the fee is on a signed acceptance and not on moving the money.

### Why a fork at zero fee does not take it

The fee has to buy something a fork lacks. Four things, and each reads zero today:

- **Inclusion in the canonical delivery record.** Suppliers with a record that a second buyer read: 0.
- **Contracts citing terms by hash.** Contracts outside Knos's own that cite a published terms template: 0.
- **The registry of admitted issuers.** Issuers admitted at the request of someone who is not Knos: 0.
- **Neutrality shown by outside key holders.** Outside key holders on the multisig: 0.

A fork can set the fee to zero in an afternoon. It cannot copy a record it is not in, a contract that names
another hash, or a key somebody else holds. Neither can Knos claim them yet: the table below is the same four as
work to be done.

**What a fork does not start with** is not something Knos has either. Each of the four below is an advantage only
once it exists. They are listed in the order they could form, each with the measure that would show it, and every
measure reads zero today.

| order | what would have to be earned | why code alone does not give it | how it would be measured | today |
|---|---|---|---|---|
| 1 | **Supplier reuse** | A supplier that has integrated one acceptance format for one buyer can serve the next buyer without new work. It starts with the free check, because a supplier integrates once. It is worth something only when buyers who do not know each other ask for the same format. | Suppliers with accepted outcomes under two or more unrelated buyers; the share of a supplier's outcomes that came from a buyer after its first. | 0 suppliers; 0 buyers |
| 2 | **The terms standard, cited by hash** | An order's terms are a document with a hash. If contracts between buyers and suppliers name a Knos terms template by its hash, changing the meter means renegotiating the contract. A fork can copy the templates; it cannot copy the contracts that cite them. | Orders and contracts, outside Knos's own, that cite a published terms template by its hash; templates cited by two or more unrelated buyers. | 0 |
| 3 | **The delivery record** | Which suppliers deliver, which are reverted, which disputes were upheld. A fork starts at zero; so does Knos. | Accepted outcomes, reverts and disputes per supplier, with the sample size beside each; buyers who say they used the record to choose a supplier. | Knos's own activity on devnet only |
| 4 | **Neutrality** | A count run by the vendor is the vendor's count again. A count run by one person is that person's. Neutrality cannot be bought as a certificate: it has to show in who holds the keys, who can appeal, and whether a customer can leave with its records. | Outside signers on the multisig; an outside review; more than one independent evaluator; a customer that exported its records and verified them without Knos. | one operator, who holds every key; no review |

Two things are needed before any of the four and are not moats: **buyers that come back** (a buyer who funds a
second period without being asked; measured as repeat buyer spend, 0 today) and **an accountable party** (a legal
entity that signs a contract and answers a support request; none today, and one person).

None of the four should be called a moat until its measure is above zero for accounts that are not Knos's.

### The loop, link by link, as it is measured today

The loop that would make the four above form: a buyer adopts; its suppliers integrate; a supplier reuses the
integration with another buyer; the acceptance format spreads; the record improves decisions; more buyers adopt.
A larger log of events is not a network effect. Each new participant has to make Knos more useful to the ones
already there, and each link has one counter ([`scripts/network_loop.py`](../scripts/network_loop.py),
`tests/test_network_loop.py`):

| link | the evidence that would show it | counter | today |
|---|---|---|---|
| Suppliers reuse the integration | suppliers paid by two or more unrelated buyers | `suppliers_two_buyers`, from the job records | 0 |
| Buyers arrive through a supplier | buyers whose first paid job paid a supplier another buyer had already paid | `buyers_through_supplier`, from the job records | 0 |
| The format spreads | software that is not Knos's and reads or writes the receipt format | `receipt_implementations`, kept by hand with a link | 0 |
| The record improves decisions | buyers who say they chose or dropped a supplier on its record | `decisions_from_record`, kept by hand | 0 |
| Buyers keep what they built | buyers with paid jobs in two or more different months | `repeat_buyers`, from the job records | 0 |
| Trust is shown by others | report files from a run in someone else's repository | `reproductions_signed`, the files of `reproductions/` | 0 |

The three counters read from job records count only accounts that are not Knos's, by the rules of
[`scripts/outsiders.py`](../scripts/outsiders.py). That script measured 0 repositories that are not Knos's in
which an outside funder funded a task ([submission/NUMBERS.md](submission/NUMBERS.md)), and with no outside buyer
each of the three is 0 by arithmetic.
The chain was not read to write this table. Two accounts of one company would count as two buyers: nothing here
sees common ownership.

A direct sales force and a custom integration for each customer would spend the operating margin a low cost of delivery leaves room for. So the links that matter
most are the second and third: buyers that suppliers bring, and software that speaks the format without Knos.

## 8. Devnet is Knos's test mode

A payments company onboards a customer in a test mode first: integrate there, with money that is not money, and
change one setting later. Devnet is that mode for Knos. Every integration starts here, and the evidence is
portable: a receipt verifies from GitHub's signatures with no chain ([RECEIPT.md](RECEIPT.md)), so nothing a
customer keeps depends on devnet's history, which Solana does not promise to keep
([clusters](https://solana.com/docs/references/clusters)).

| can be real while the programs stay on devnet | is a demonstration |
|---|---|
| Control, Meter, Acceptance on value reconciled off chain and the Pilot: software billed off chain in ordinary money. Nothing has been sold, and there is no legal entity to invoice from. | Acceptance at release: escrow and settlement. The money is test USDC. |
| A Pilot on a buyer's own repositories and its real invoices. None has been run. | Every fee the program takes: test money, zero revenue. It is not sellable until a mainnet deployment, which is not planned before an outside review. |
| The count: evaluations of real work, signed by the forge, in ledgers each side keeps. | Cost, congestion and reliability under mainnet load and priority fees. |
| Use by accounts that are not Knos's, a supplier reused by a second buyer, a statement both sides compute. All zero today. | Security against an attacker who risks real money. |
| Records a customer keeps and verifies without the cluster. | Devnet as the ledger of record. It is not one. |

Count first, settle second, capital third. The count needs no customer money on chain, so it can be sold before
any mainnet deployment. The gates are targets we set **[assumption]**, not commitments from anyone.

| phase | what ships | who buys | the gate to the next phase |
|---|---|---|---|
| 0. Proof, in test mode | The free check; the meter in shadow beside real invoices; settlement in test USDC; the Pilot | Nobody has paid. There is no design partner. | Outside accounts funding orders on devnet, and one vendor or agency running the meter beside its own invoice count |
| 1. Count | Meter and Control as subscriptions invoiced off chain; private repositories; an outside security review; the verifier and the meter on mainnet | Vendors that bill per accepted change, and their customers | 10 paying organisations and a published review |
| 2. Settle | Escrow on mainnet with real USDC; bank money in and out through a licensed partner; milestones | Teams that already pay per outcome in stablecoins, then agencies | 50 million USD settled in a year |
| 3. Capital | Advance and Assurance, which are not offered today, priced from the settlement record | Agencies and their financiers | Losses below premiums for four quarters |

Until settlement is real, a customer pays its suppliers the way it already does, through its bank. Knos records
the settlement status of each deliverable as paid outside Knos, payable, held, refunded, or a devnet
demonstration, and says which.

**Tokenless.** Knos has no token and plans none. Revenue is subscriptions and fees in USD and USDC.

**Legal advice.** Holding money in escrow and paying it out for others may be money transmission, and the rules
differ by country and by state. Legal advice is needed before any real money moves. **None has been taken.**
[REGULATION.md](REGULATION.md) says what was read and what was not.

## 9. What can stop this

| what | why it could | what Knos does about it | what Knos cannot do |
|---|---|---|---|
| **Nobody wants a neutral count** | The vendors of section 2 sell on their own count today, and their customers accept it. | Makes the count free to try: 100,000 evaluations a month cost nothing, and in shadow mode the meter runs beside the vendor's invoices without changing them. | Create the dispute. If buyers do not object to the seller's count, there is no Meter business. |
| **GitHub ships it** | GitHub owns the record Knos reads. A request for bounties on issues has been open since 6 Jul 2021 ([discussion 4517](https://github.com/orgs/community/discussions/4517)). | Takes signed statements from other issuers. Stays neutral between agents: GitHub sells an agent of its own, so it would be counting its own sales. | Stop it, or outlast it on public repositories. Knos also depends on GitHub's tokens and API, and on one GitHub account ([submission/DEPENDENCY.md](submission/DEPENDENCY.md)). |
| **A cloud platform or a billing company adds acceptance** | Section 2: they already sell agent identity, policy, evaluation, payments and usage billing, and they have the customers. | Stays independent of every vendor of agents and every platform they run on, which a platform cannot be about its own. | Match their distribution, or stop a buyer from deciding that its platform's count is good enough. |
| **A payment rail adds acceptance** | The rails have the distribution. The x402 site showed 75.41 million transactions and 24.24 million USD of volume for its last 30 days ([x402.org](https://www.x402.org), read 6 Oct 2026); larger cumulative figures quoted elsewhere are not used here. It is pay before access, with no check of delivery. The draft ERC-8183 has a slot for one: an evaluator address that "alone may mark the job completed" ([EIP](https://eips.ethereum.org/EIPS/eip-8183), read 3 Oct 2026). | Builds the evaluator, not the rail: the verifier is free for any program to read. | Match a rail's reach. |
| **Zero-fee copies** | MIT, and MergePay charges no platform fee. Algora charges a "9% service fee" ([pricing](https://algora.io/pricing), read 6 Oct 2026), so the direction of prices is down. | Section 7: one fee of 0.30% on a signed acceptance, no fee for connecting a supplier, and the four things a fork lacks, which Knos lacks too. | Keep any percentage if the record, the cited terms, the issuers and the outside key holders stay at zero. |
| **The attestor gap** | The issuer signs which workflow ran, at which commit, in which repository. It does not sign what the workflow read. | Pins the workflow by commit; requires a hosted runner and a first attempt; lets the supplier have the pinned workflow read the public record from a repository of its own. | Prove the reading without trusting the forge's hosted runners. A private order trusts the repository its funder named as judge ([SECURITY.md](SECURITY.md)). |
| **Regulation** | Escrow and payout may be money transmission. Paying contractors brings tax reporting. Paying anyone brings sanctions law. | Holds no key to an order's money in normal operation; screens a payout address; exports every payment. | Give a legal opinion. None has been taken. Until an outside review the programs are upgradeable through the multisig, which weakens any claim that Knos does not control the money. |
| **One person** | One founder holds every upgrade key and the one GitHub account the pinned workflows live in. | A public 48-hour delay on every upgrade; refunds that need neither GitHub nor Knos; the plan in [submission/DEPENDENCY.md](submission/DEPENDENCY.md). | Be an organisation before it is one. |
| **Paid work for strangers has failed before** | Bountysource left at least 21,702.10 USD of completed work unpaid ([boehs.org, 3 May 2024](https://boehs.org/node/bountysource), read 3 Oct 2026). curl ended its bug bounty in January 2026 to "remove the incentive for people to submit crap and non-well researched reports" ([The Register, 21 Jan 2026](https://www.theregister.com/2026/01/21/curl_ends_bug_bounty/), read 3 Oct 2026). | No company holds the money. Acceptance is named checks fixed before the work. The free check marks a false "tests pass" before a person reads the pull request. The business is not the board. | Remove the review, or make a small market large. |

## What is not known

- Whether any vendor or buyer wants a neutral count enough to pay for it. Nobody has been asked:
  [submission/INTERVIEWS.md](submission/INTERVIEWS.md) is the kit for asking.
- Whether anyone will fund a second order with real money. There is no outside funder.
- Whether the three-to-one benefit of section 6 exists for any customer. Nobody has measured it.
- Whether anyone would pay Acceptance, and whether 0.30%, the volume rates and the floor are the right numbers. Nobody has been asked.
- Whether the unit costs of [UNIT_COSTS.md](UNIT_COSTS.md) hold. Most are budgets, not measurements.
- How many organisations meet the four conditions of section 5. No source counts them.
- The realised price of an evaluation, and what a batch costs on a cluster. Neither is measured.
- What relaying costs on mainnet. Priority fees are in no measurement.
- What share of the spend on coding agents would move to payment per accepted outcome. No source gives it.
- The price of a merged change. Sourcegraph and GitStart do not publish theirs.
- How these payments are regulated and taxed. No legal advice has been taken.
- What a company's security or procurement review would say ([CONTROLS.md](CONTROLS.md)).
- When a security firm will review the programs, and what it will cost. None has.
