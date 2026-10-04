# Market, money, and what can stop this

**Knos is the neutral count and settlement for software work priced per outcome: terms fixed before the work, a signed CI run attests they were met, a Solana program counts it or pays it.**

Nine parts: who buys and who sells; the adjacent market, with every source; the price book; what each sale costs
to deliver; the revenue formula and the fee actually collected; what 1 billion USD a year would require, as
arithmetic; what a zero-fee fork can and cannot copy, and the moats; the phases and what devnet can show; and what
can stop this.

Every outside figure carries its link and one of three labels: **[vendor page]** (the seller's own price list or
product page), **[press]** (reported by someone else, often from an unnamed source), **[company-reported]** (the
company's own statement of its results; audited only where it is a public company's filing). Each was read on
4 Oct 2026 unless it says otherwise. **[measured]** is ours, with where. **[assumption]** has no source. The rest is
arithmetic on those inputs. Nothing here is a forecast. Knos runs on Solana devnet and its money is test USDC. No
real money has moved, and nobody has bought anything.

## 1. Who buys, and who sells

**The buyer is the person accountable for approving a supplier's invoice**: an engineering leader or a finance
owner at a company that buys software work per outcome from an agent vendor or an agency. The question that person
has to answer is whether the invoice can be approved, explained afterwards, and shown to follow the company's own
rules. For each line they need: what was ordered and at what price, which acceptance terms applied, which artifact
was evaluated, who evaluated it, what passed and what failed, whether it was billed before, and what a later
revert changes.

**The second user is the supplier**: an agent vendor or an agency. A supplier needs acceptance terms that cannot be
changed after the work, a count it can check itself, and a way to be paid, or to show what is owed, when the buyer
does nothing.

**The smallest case is a maintainer with a 20 USDC bounty on an issue.** It is where the product was first proven,
and it is not the market: every open bounty on every board came to 64,291 USD on 2 Oct 2026
([BountyOS](https://bountyos.rovidev.com/en/github-bounty-board/), read that day), and 2.5% of that is 1,607 USD.

What each of them gets today:

| who | what Knos gives them | where it is |
|---|---|---|
| Buyer | Terms hashed into the order when it is funded: named checks, allowed paths, the workflow commit. A count of accepted outcomes that neither side keeps. A statement both sides compute to the same totals. | `knos-pay` orders; `knos-meter`; `knos statement` and the ledger files each side keeps |
| Supplier | Terms nobody can change after funding. Settlement without the buyer after a merge in a public repository. Its own count of the month on chain, beside the buyer's. | `knos settle --neutral`; `ClaimBatch` in `knos-meter` |
| Maintainer | One comment funds an issue; one merge pays it. | `/knos fund` |

What neither gets yet: private repositories under a contract, money a bank accepts, single sign-on, a company
that answers for the service, an outside security review. [CONTROLS.md](CONTROLS.md) has the list.

## 2. The adjacent market

### Vendors already bill per accepted outcome, and each counts its own

| vendor | the unit it bills | price | who counts | source |
|---|---|---|---|---|
| Sourcegraph, Agentic Batch Changes | "you pay per changeset merged into your codebase" | not published | Sourcegraph | **[vendor page]** [changelog, 14 Sep 2026](https://sourcegraph.com/changelog/agentic-batch-changes-ga) |
| GitStart | "you only pay for merged PRs" | not published | GitStart | **[vendor page]** as listed by [Y Combinator](https://www.ycombinator.com/companies/gitstart) |
| Intercom, Fin | a "Fin outcome" | from 0.99 USD | Intercom | **[vendor page]** [pricing](https://www.intercom.com/pricing) |
| Zendesk, AI agents | an "automated resolution": resolved "without any escalation to a human agent" | 1.50 USD committed, 2.00 USD pay-as-you-go | Zendesk | **[vendor page]** [pricing](https://www.zendesk.com/pricing/) |
| Salesforce, Agentforce | a conversation, or Flex Credits per action | 2 USD per conversation; 500 USD per 100,000 Flex Credits | Salesforce | **[vendor page]** [pricing](https://www.salesforce.com/agentforce/pricing/) |

In every row the seller keeps the count the buyer is billed on. That is the gap. Two people who sell or study
these contracts say so:

- "Attribution disputes are where these contracts fall apart. Outcome-based pricing only scales where both parties
  can agree on attribution" (Sidharth Ramsinghaney, Director of Strategy and Operations at Twilio; **[press]**
  [CIO, 16 Jun 2026](https://www.cio.com/article/4184688/it-hurtles-toward-the-great-enterprise-pricing-reset.html),
  read 3 Oct 2026).
- Zendesk's president on the edge cases: "If the AI resolves 90% of the problem, but 10% goes to a human agent, we
  don't count it." (**[press]**
  [Channel Dive, 31 Aug 2026](https://www.channeldive.com/news/agentic-ai-outcome-pricing-models-zendesk-gartner/829209/),
  read 3 Oct 2026). The seller decides them.

For code, the count can be wrong in a way we measured. Of 241 merged agent pull requests whose description said
tests or CI pass, 30 (12.4%) had a failed check at the head commit **[measured]**
([agent_pr_ci.json](agent_pr_ci.json), `summary.one_pr_per_repo`; [BENCH.md](BENCH.md), "Merged anyway"; 95%
interval 8.9% to 17.2%). A vendor that bills per merge bills those. A count that reads the checks from the
system of record does not.

Code has what support does not: a third party that already records the result and signs statements about it.
GitHub and GitLab record the merge and the checks, and sign a CI run. Knos counts and settles on that signature,
for any seller, in the buyer's own system of record.

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

## 3. The price book

| Line | Unit | Price |
| --- | --- | --- |
| Check | pull request checked | free |
| Meter | attested evaluation | 10,000 a month free, then 0.05 USD; 0.02 on a committed-volume plan |
| Settle | dollar settled, paid by the funder on top | 2.5% of the first 1,000, 1% from 1,000 to 50,000, 0.5% above; minimum 0.40; plans 0.5 to 1.5% |
| Control | organisation | 25,000 USD a year entry, 80,000 organisation tier (nobody has bought it) |
| Advance | dollar advanced on accepted work waiting on a holdback | 1 to 3%, by a financier who takes the assignment (`Assign`); Knos charges nothing today |
| Assurance | dollar warranted | a premium for the warranty that refunds a reverted order; not priced until there is loss history |

Relayer tip: 0.05, or 0.30 on a payee's first payment, out of the fee.

Where each price is fixed:

- **Check.** Nowhere: it is free. The claim check, the Stop hook, the MCP tools, the Agent PR Index and on-chain
  verification cost nothing, and they are the distribution.
- **Meter.** In `knos-meter`. It moves no customer money: it counts attested evaluations and takes its fee from
  credits the customer prepaid. A billable evaluation is one work order, one artifact, one policy and one
  milestone: a retry or a duplicate is free, and a rejection is billable, because evaluating it took the same work.
  A committed-volume rate is a `Plan` the program holds for one owner; the commitment itself is a contract off
  chain.
- **Settle.** In `knos-pay`. The fee is marginal: each rate applies only to the part of the amount inside its
  tier. It is escrowed on top of the amount when the order is funded and leaves only when someone is paid; a refund
  returns amount and fee. A Plan lowers the first tier's rate for one owner. On devnet an order holds between 5
  and 100,000 test USDC; a build for real money decides its own cap. The second deployment is upgradeable only
  through a multisig with a public 48-hour delay, until an outside review, so any change to these constants is
  public two days before it can run.
- **Control.** In a contract. Nothing on chain enforces it, and the software it covers is in this repository under
  the MIT licence. What is sold is policy, budgets, private repositories, statements, exports, and a party that
  answers for the service. That party does not exist yet.
- **Advance.** In nobody's price list. A payee assigns the payment of an order to another wallet (`Assign`), and
  whoever paid them early collects it. The 1 to 3% is what such a financier would charge **[assumption]**; no
  advance has been made.
- **Assurance.** Not priced. An order can already hold back a share for a warranty period and return it if the work
  is reverted; a premium for a warranty that refunds the whole order needs a history of losses, and there is none.

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
| The funder pays | 102.50 | the amount and 2.5% on top |
| The payee receives | 100.00 | the posted amount, in full |
| The relayer's tip, out of the fee | 0.05 | 0.30 when the paying transaction creates the payee's token account |
| Knos keeps | 2.45 | 2.20 on a payee's first payment |

What the relayer spends against that tip: signatures, and on a payee's first payment the rent of a token account
of 165 bytes, 1,488,440 lamports, 0.181 USD. Carrying one token to the
chain took 7 transactions and 35,000 lamports (0.0043 USD) on the first deployment **[measured]**, and 2
transactions on the second **[measured in the simulator]**; a relayer's cost on the second deployment is not
measured on devnet ([BENCH.md](BENCH.md), "What a relayer pays"). Priority fees, which a busy mainnet may need,
are in no measurement.

So the chain is not the cost of a settlement. The costs are people: support, compliance, an outside review. None
of them exists yet and none is measured.

### 1 million metered evaluations in a month

A customer with 1,000,000 evaluations in a month has 990,000 billable ones: 49,500 USD at 0.05, 19,800 USD at 0.02.

| | individual mode (`Record`) | batch mode (`RecordBatch`) |
|---|---|---|
| What is written | One marker account of 88 bytes per evaluation, so that a retry is free | No account per evaluation. One signed token carries the count, the totals and a Merkle root of a batch; one Ledger account of 96 bytes per buyer, seller and month holds the totals and a running hash |
| Rent per evaluation | 1,097,280 lamports, 0.1333 USD: 2.7 times the 0.05 price | none |
| Rent for the month | 1,097.28 SOL, 133,320 USD, locked at the month's end. The program returns all of it to the relayer from two hours into the next month (`CloseMark`), so it is working capital, not a cost | 1,137,920 lamports, 0.14 USD, once, and kept: the Ledger is the record and is never closed |
| Signatures | 3 transactions per evaluation: 15 SOL, 1,822.50 USD | 3 transactions per batch: at 5,000 evaluations a batch, 200 batches, 0.003 SOL, 0.36 USD |
| Chain cost per evaluation | 0.0018 USD spent, and 0.1333 USD locked for up to a month | 0.00000036 USD |
| Where the detail lives | on chain, one account each | in a ledger file each side keeps; the chain holds the root, so either side can prove one evaluation was counted, and neither can change the month afterwards |

Batch mode exists so that rent no longer exceeds the price. Individual mode stays for an evaluation that has to
stand on chain by itself. The supplier's own count of the same month (`ClaimBatch`) costs the supplier's relayer
the same signatures and one more Ledger account, and no fee. Neither mode's cost has been measured on devnet.

**The gross-margin budget.** At 0.02 per evaluation, a gross margin of 80% **[assumption: a target]** leaves 0.004
USD per evaluation to deliver it. In batch mode the chain takes 0.00000036 of that. What has to fit in the rest and
is not measured: storing and serving the ledgers, running a relay, and support. Running the customer's tests is not
in it: they run in the customer's own CI, on the customer's bill.

## 5. Revenue, and the fee actually collected

**Revenue opportunity = qualified customers × annual platform price + billable evaluations × realised unit price,**
and, once real money settles, **+ orders × the fee collected on each.**

Each input has to be shown, and none is today: qualified customers are 0, billable evaluations are 0, and the
realised unit price is unknown, because the free allowance and committed-volume plans come off the list price
first.

The settlement line is not "volume × a percentage". The tiers and the floor decide what an order pays:

| order | fee the funder adds | as a share of the order | to Knos | to Knos on a payee's first payment |
|---|---|---|---|---|
| 5 | 0.40 | 8% (the minimum) | 0.35 | 0.10 |
| 20 | 0.50 | 2.5% | 0.45 | 0.20 |
| 100 | 2.50 | 2.5% | 2.45 | 2.20 |
| 1,000 | 25.00 | 2.5% | 24.95 | 24.70 |
| 5,000 | 65.00 = 25 + 1% of 4,000 | 1.3% | 64.95 | 64.70 |
| 50,000 | 515.00 = 25 + 1% of 49,000 | 1.03% | 514.95 | 514.70 |
| 100,000 | 765.00 = 515 + 0.5% of 50,000 | 0.765% | 764.95 | 764.70 |

Under a Plan at 0.5% the first tier pays 5, not 25: a 5,000 order pays 45 and a 50,000 order pays 495. The same
volume therefore yields very different revenue by order size: 1 million USD settled is 25,000 USD of fees in
orders of 100, 13,000 in orders of 5,000 and 10,300 in orders of 50,000.

## 6. What 1 billion USD a year would require

**This is arithmetic, not a forecast.** It says what would have to be true, at the price book's own prices, and
puts the reality beside each line. Nothing in it has happened.

| line | what it needs | price | revenue | reality check | today |
|---|---|---|---|---|---|
| Control | 3,000 organisations under contract | 80,000 USD a year each | 240 million | Datadog reported about 4,310 customers above 100,000 USD of annual recurring revenue at the end of 2025 (**[company-reported]**, [results for 2025](https://investors.datadoghq.com/news-releases/news-release-details/datadog-announces-fourth-quarter-and-fiscal-year-2025-financial)) | 0 organisations; nobody has bought it |
| Meter | 12 billion billable evaluations a year | 0.02 realised | 240 million | 32.9 million a day: 46% of the 71 million jobs GitHub Actions ran a day in December 2025. Each must be a real commercial evaluation, after the free allowance | 0 evaluations by anyone but Knos |
| Settle | 8 million orders of 5,000 USD: 40 billion USD settled | 65 USD an order (1.3%) | 520 million | 9.9 times the 4.03 billion USD bought through Upwork in 2025; 2.5% of Gartner's 1.57 trillion USD of IT services. In orders of 50,000 the same volume pays 412 million | 0 USD of real money |
| Advance, Assurance | | not priced | 0 | Knos charges nothing for an advance and has no loss history to price a warranty | 0 |
| **Total** | | | **1,000 million** | | **0** |

Reading it:

- The two lines that need no customer money on chain, Control and Meter, come to 480 million. Without any
  settlement revenue the formula of section 5 reaches 1 billion at 6,250 organisations and 25 billion billable
  evaluations a year, which is 96% of GitHub Actions' December 2025 job rate. That is not a plan.
- At the list price of 0.05 the meter line needs 4.8 billion evaluations, not 12 billion. Committed-volume
  customers pay 0.02, so 0.02 is the honest price to plan on.
- Customer money in escrow, refundable rent and a financier's advances are never revenue.

**The first milestone is 1 million USD of fees a year.** Three ways to it, none reached:

| way | what it takes | needs mainnet |
|---|---|---|
| Control | 40 organisations at the 25,000 USD entry price, or 13 at 80,000 | no: a subscription invoiced off chain |
| Meter | 50 million billable evaluations a year at 0.02 (137,000 a day), or 20 million at 0.05 | no, for the subscription; the count itself is on chain |
| Settle | 40 million USD settled in orders of 1,000 or less (2.5%), or 15,385 orders of 5,000 (76.9 million USD settled) | yes |

## 7. What a fork can copy, and the moats

Knos is MIT. Anyone can deploy the same programs with every fee set to zero, and MergePay already charges no
platform fee ([COMPARE.md](COMPARE.md)).

**What a zero-fee fork can copy:** all of the code; the verifier, which is free for any program to read; the
public settlement fee, since the program tips whoever relays and anyone can relay at no loss; and the public
payment history, which anyone can read from the chain. Settlement alone will be priced toward zero.

**What it cannot copy:**

| | why a fork does not have it | what Knos has of it today |
|---|---|---|
| **Neutrality** | A count run by the vendor is the vendor's count again, which is what the buyer objected to. A count run by the forge is not neutral between forges or between its own agent and others. | A design that makes it checkable: the supplier's own count sits on chain beside the buyer's. One operator, who is one person. |
| **The record** | Orders in flight finish at the program addresses they were funded at, and the history of who delivered, who reverted and who paid accumulates there. A fork starts at zero. | A small record, all of it Knos's own activity on devnet. |
| **A contract with an accountable party** | Procurement signs with a legal entity that answers for support, security reports and uptime. Code cannot sign. | None. No company has been formed. |
| **Capital** | Advancing money on accepted work and warranting it take a balance sheet and a loss history. | None. Knos advances nothing. |

A third party's fork is as neutral as Knos is. What separates them then is the record and the contract, which is
why those have to be earned early.

**The moats, in the order they form:**

1. **Distribution inside the agent loop.** The free check runs where the claim is made: the Stop hook and the MCP
   tools in the agent's session, and a check on the pull request. It forms first because it costs the user nothing.
2. **The record.** Each counted evaluation and each settled order adds to a public history of which agents and
   vendors deliver.
3. **The terms standard.** If buyers ask suppliers for the same acceptance receipt, a supplier integrates once and
   reaches every such buyer.
4. **Neutrality across issuers.** The verifier takes any issuer that signs RS256 tokens; a forge cannot be neutral
   between itself and another forge, and a vendor cannot be neutral about its own invoice.
5. **Capital.** Underwriting from the settlement record. It forms last, and only if the record is large.

None of the five exists at a scale that defends anything today.

## 8. The phases, and what devnet can show

Count first, settle second, capital third. The count needs no customer money on chain, so it can be sold before
any mainnet deployment. The gates are targets we set **[assumption]**, not commitments from anyone.

| phase | what ships | who buys | the gate to the next phase |
|---|---|---|---|
| 0. Proof, on devnet | The free check; the meter beside real invoices; settlement in test USDC | Nobody pays. Design partners use it. | Outside accounts funding orders on devnet, and one vendor or agency running the meter beside its own invoice count |
| 1. Count | Meter and Control as subscriptions invoiced off chain; private repositories; an outside security review; the verifier and the meter on mainnet | Vendors that bill per accepted change, and their customers | 10 paying organisations and a published review |
| 2. Settle | Escrow on mainnet with real USDC; bank money in and out through a licensed partner; milestones | Teams that already pay per outcome in stablecoins, then agencies | 50 million USD settled in a year |
| 3. Capital | Advance and Assurance priced from the settlement record | Agencies and their financiers | Losses below premiums for four quarters |

**What devnet can show:** that the product works end to end; use by accounts that are not Knos's; a supplier and
a buyer computing the same statement; reproducible refusals and refunds; and subscription revenue, because Meter
and Control hold no customer money and can be invoiced off chain while the programs stay on devnet. No such
subscription has been sold.

**What devnet cannot show:** settlement revenue, because test USDC is not money; behaviour under mainnet load and
priority fees; or a ledger a customer can rely on, since devnet carries no guarantee that its history is kept.
That is why every receipt can also be kept off chain ([RECEIPT.md](RECEIPT.md)).

**Tokenless.** Knos has no token and plans none. Revenue is subscriptions and fees in USD and USDC.

**Legal advice.** Holding money in escrow and paying it out for others may be money transmission, and the rules
differ by country and by state. Legal advice is needed before any real money moves. **None has been taken.**
[REGULATION.md](REGULATION.md) says what was read and what was not.

## 9. What can stop this

| what | why it could | what Knos does about it | what Knos cannot do |
|---|---|---|---|
| **Nobody wants a neutral count** | The vendors of section 2 sell on their own count today, and their customers accept it. | Makes the count free to try: 10,000 evaluations a month cost nothing, and the meter runs beside the vendor's invoices without changing them. | Create the dispute. If buyers do not object to the seller's count, there is no Meter business. |
| **GitHub ships it** | GitHub owns the record Knos reads. A request for bounties on issues has been open since 6 Jul 2021 ([discussion 4517](https://github.com/orgs/community/discussions/4517)). | Takes signed statements from other issuers. Stays neutral between agents: GitHub sells an agent of its own, so it would be counting its own sales. | Stop it, or outlast it on public repositories. Knos also depends on GitHub's tokens and API, and on one GitHub account ([submission/DEPENDENCY.md](submission/DEPENDENCY.md)). |
| **A payment rail adds acceptance** | The rails have the distribution. x402 reports 75.41 million transactions and 24.24 million USD in 30 days ([x402.org](https://x402.org), read 3 Oct 2026). It is pay before access, with no check of delivery. The draft ERC-8183 has a slot for one: an evaluator address that "alone may mark the job completed" ([EIP](https://eips.ethereum.org/EIPS/eip-8183), read 3 Oct 2026). | Builds the evaluator, not the rail: the verifier is free for any program to read. | Match a rail's reach. |
| **Zero-fee copies** | MIT, and MergePay charges no platform fee. Algora charges 9% ([pricing](https://algora.io/pricing), read 3 Oct 2026), so the direction of prices is down. | Section 7: prices on what a fee constant does not carry. | Keep a percentage on public settlement once someone relays as well for less. |
| **The attestor gap** | The issuer signs which workflow ran, at which commit, in which repository. It does not sign what the workflow read. | Pins the workflow by commit; requires a hosted runner and a first attempt; lets the supplier have the pinned workflow read the public record from a repository of its own. | Prove the reading without trusting the forge's hosted runners. A private order trusts the repository its funder named as judge ([SECURITY.md](SECURITY.md)). |
| **Regulation** | Escrow and payout may be money transmission. Paying contractors brings tax reporting. Paying anyone brings sanctions law. | Holds no key to an order's money in normal operation; screens a payout address; exports every payment. | Give a legal opinion. None has been taken. Until an outside review the programs are upgradeable through the multisig, which weakens any claim that Knos does not control the money. |
| **One person** | One founder holds every upgrade key and the one GitHub account the pinned workflows live in. | A public 48-hour delay on every upgrade; refunds that need neither GitHub nor Knos; the plan in [submission/DEPENDENCY.md](submission/DEPENDENCY.md). | Be an organisation before it is one. |
| **Paid work for strangers has failed before** | Bountysource left at least 21,702.10 USD of completed work unpaid ([boehs.org, 3 May 2024](https://boehs.org/node/bountysource), read 3 Oct 2026). curl ended its bug bounty in January 2026 to "remove the incentive for people to submit crap and non-well researched reports" ([The Register, 21 Jan 2026](https://www.theregister.com/2026/01/21/curl_ends_bug_bounty/), read 3 Oct 2026). | No company holds the money. Acceptance is named checks fixed before the work. The free check marks a false "tests pass" before a person reads the pull request. The business is not the board. | Remove the review, or make a small market large. |

## What is not known

- Whether any vendor or buyer wants a neutral count enough to pay for it. Nobody has been asked:
  [submission/INTERVIEWS.md](submission/INTERVIEWS.md) is the kit for asking.
- Whether anyone will fund a second order with real money. There is no outside funder.
- The realised price of an evaluation, and what a batch costs on a cluster. Neither is measured.
- What relaying costs on mainnet. Priority fees are in no measurement.
- What share of the spend on coding agents would move to payment per accepted outcome. No source gives it.
- The price of a merged change. Sourcegraph and GitStart do not publish theirs.
- How these payments are regulated and taxed. No legal advice has been taken.
- What a company's security or procurement review would say ([CONTROLS.md](CONTROLS.md)).
- When a security firm will review the programs, and what it will cost. None has.
