# Market, money, and what can stop this

Seven parts: who has budget and urgency now; what Knos sells, what each sale costs to deliver, and what a zero-fee
fork takes; today's bottom-up beside what 1 billion USD a year would require; the sequence of expansion; what can
stop this; the funnel and the one test that matters; and what is not known.

Every input is labelled **[sourced]** (with its link; read on 3 Oct 2026 unless it says otherwise), **[measured]**
(with where), **[assumption]**, or **not measured**. The rest is arithmetic on those inputs. Nothing here is a
forecast. Knos runs on Solana devnet and its money is test USDC. No real money has moved.

## 1. Who has budget and urgency now

### Vendors already bill per outcome, and each counts its own outcomes

| vendor | the unit it bills | price | who counts |
|---|---|---|---|
| Sourcegraph, agentic batch changes | "you pay per changeset merged into your codebase" **[sourced]** ([changelog](https://sourcegraph.com/changelog/agentic-batch-changes-ga); Cloud, since 14 Sep 2026) | not published | Sourcegraph |
| GitStart | "you only pay for merged PRs" **[sourced]** ([Y Combinator's page](https://www.ycombinator.com/companies/gitstart)) | not published | GitStart |
| Intercom, Fin | an outcome: a resolution | 0.99 USD **[sourced, secondary]** ([Sacra](https://sacra.com/research/intercom), which also says Fin passed 100 million USD of annual recurring revenue) | Intercom |
| Zendesk | an "automated resolution": resolved "without any escalation to a human agent" | 1.50 USD committed, 2.00 USD pay-as-you-go **[sourced]** ([pricing](https://www.zendesk.com/pricing/)) | Zendesk |
| Salesforce, Agentforce | a conversation, or an action | 2 USD per conversation; 0.10 USD per action with Flex Credits **[sourced]** ([press release, 15 May 2025](https://www.businesswire.com/news/home/20250515332990/en/); later changes not checked) | Salesforce |

### The dispute is over who counts

- "Attribution disputes are where these contracts fall apart. Outcome-based pricing only scales where both parties
  can agree on attribution" **[sourced]** (Sidharth Ramsinghaney, Director of Strategy and Operations at Twilio, in
  [CIO, 16 Jun 2026](https://www.cio.com/article/4184688/it-hurtles-toward-the-great-enterprise-pricing-reset.html)).
- The seller decides the edge cases. Zendesk's president: "If the AI resolves 90% of the problem, but 10% goes to a
  human agent, we don't count it." In the same article Gartner's Tom Coshow says 19% of services buyers use
  outcome arrangements today **[sourced]**
  ([Channel Dive, 31 Aug 2026](https://www.channeldive.com/news/agentic-ai-outcome-pricing-models-zendesk-gartner/829209/)).
- For code, the count can be wrong in a way we measured. Of 241 merged agent pull requests whose description said
  tests or CI pass, 30 (12.4%) had a failed check at the head commit **[measured]** ([BENCH.md](BENCH.md), "Merged
  anyway"; 95% interval 8.9% to 17.2%). A vendor that bills per merge bills those. A count that reads the checks
  from GitHub's record does not.

Code has what support does not: a third party that already records the result and signs statements about it.
GitHub records the merge and the checks, and signs a workflow run. Knos counts and settles on that signature. The
buyer's own system of record does the counting, for any seller.

### The buyers, in order of urgency

| buyer | budget today | what they need from Knos | what is missing |
|---|---|---|---|
| A vendor that bills per merged change, and its customer | The contract already exists. Its size is not published by any vendor above. | A count neither side keeps (Meter), a statement both accept, privacy for private repositories (Control) | A first vendor. No outside party has used Meter. |
| Teams and foundations that hold USDC and pay strangers per outcome | Immunefi: "$140M+ paid" across "650+ protocols" **[sourced]** ([immunefi.com](https://immunefi.com)). Superteam Earn: 2,730+ sponsors, 15.9 million USD in total **[sourced]** ([superteam.fun/earn](https://superteam.fun/earn); [its stats](https://superteam.fun/api/homepage/stats), field `totalInUSD`) | Settlement on a merge and named checks, in place of judging every submission by hand (Settle) | Mainnet, and a review by a security firm. Neither exists. |
| Open-source companies that post bounties | Algora charges them 9% **[sourced]** ([pricing](https://algora.io/pricing)); every open bounty on every board came to 64,291 USD **[sourced]** ([BountyOS](https://bountyos.rovidev.com/en/github-bounty-board/), read 2 Oct 2026) | A lower fee, and payment on the day of the merge, not days later: from merge to payment took 24 seconds at the median, over 36 payments ([BENCH.md](BENCH.md)) | Money a bank accepts. Knos pays USDC. |
| Engineering teams with private repositories that buy fixed-scope changes from outside | Not measured. They pay by contract and invoice. | Budgets, policy, statements, exports, private settlement (Control) | A company that answers for the service: see [CONTROLS.md](CONTROLS.md) |

Bounties on issues are where Knos starts, not a business: 2.5% of every open bounty on every board is 1,607 USD.

### The larger money, which we do not multiply by a share

- Enterprises spent 37 billion USD on generative AI in 2025, 4.0 billion of it on coding tools **[sourced]**
  ([Menlo Ventures, 9 Dec 2025](https://menlovc.com/perspective/2025-the-state-of-generative-ai-in-the-enterprise/)).
- Cursor passed 4 billion USD of annualised revenue by early June 2026 **[sourced, unofficial]**: "a person
  familiar with the matter" ([Dealroom, 9 Jun 2026](https://dealroom.co/news/134107-cursor-tops-4b-annualized-revenue/)).
  That is a run rate in 2026; Menlo's figure is spend in 2025. They are not added.
- 4.03 billion USD of work was bought through Upwork in 2025, on which Upwork earned 787.8 million USD **[sourced]**
  ([Upwork, results for 2025](https://investors.upwork.com/news-releases/news-release-details/upwork-reports-fourth-quarter-and-full-year-2025-financial)).
- Gartner forecasts 1.57 trillion USD of IT services spending in 2026 **[sourced]**
  ([Gartner, 27 Jul 2026](https://www.gartner.com/en/newsroom/press-releases/2026-07-27-gartner-forecasts-worldwide-it-spending-to-grow-14-point-2-percent-in-2026-totaling-6-point-37-trillion)).
- GitHub Actions ran 71 million jobs a day in December 2025 **[sourced]**
  ([GitHub, 11 Dec 2025](https://github.blog/news-insights/product-news/lets-talk-about-github-actions/)).

No source says what part of any of these would move to payment on signed acceptance. The part that goes through
Knos today is zero.

## 2. What Knos sells, what each sale costs, and what a fork takes

### The price book

Knos sells four things, and one of them is free. A fifth, an advance, is sold by whoever advances the money.

| line | what is sold | price | free |
|---|---|---|---|
| Check | the claim check, the Stop hook, the MCP tools, the Index, on-chain verification | 0 | all of it |
| Settle | escrow and payout on signed acceptance | the funder pays the amount plus 2.5%, at least 0.40, at most 25 USDC; the payee receives the posted amount; 0.5% to 1.5% under a contract (a Plan) | |
| Meter | a neutral count of accepted outcomes for vendors who bill per result and buyers who audit them | 0.05 per billable evaluation, 0.02 at volume | 10,000 evaluations a month |
| Control | organisation policy as code, budgets, private repositories, statements, exports, screening | 25,000 USD a year; 80,000 with a volume commitment | 30 days |
| Advance | a third party pays the seller at acceptance and takes the assigned payment | set by whoever advances; Knos charges nothing | |

Where each price is fixed:

- **Settle.** In the escrow program. An order holds between 5 and 500 USDC until an outside review. The fee is
  escrowed on top of the amount when the order is funded and leaves only when someone is paid. A refund returns
  amount and fee. Below 16 USDC the 0.40 floor is the fee. The 25 USDC ceiling is reached at 1,000 USDC, so it
  binds only once the 500 cap is lifted. A contract rate is a `Plan` account that Knos sets for one repository
  owner until an expiry: the contract is off chain, the rate is on chain. Any change to the constants is an upgrade,
  public 48 hours before it can run.
- **Meter.** In a second program, `knos_meter`. It moves no customer money. It counts attested evaluations and
  takes its fee from credits the customer prepaid. A billable evaluation is one work order, one artifact, one
  policy and one milestone: a retry or a duplicate is free, and a rejection is billable.
- **Control.** In a contract. Nothing on chain enforces it. The software it covers is in this repository under
  the MIT licence.
- **Advance.** In nobody's price list. A payee signs their payment of one order over to another wallet. Whoever
  paid them early collects it.

### What each sale costs to deliver

Inputs. A Solana transaction costs 5,000 lamports for its signature **[sourced]**
([Solana docs](https://solana.com/docs/core/fees)). Solana holds (128 + bytes) × 5,080 lamports of rent against
each account **[sourced]** ([SIMD-0437](https://solana.com/upgrades/reduced-rent); devnet and mainnet RPC both
returned 1,488,440 lamports for 165 bytes on 2 Oct 2026). SOL is taken at 120 USD **[sourced]** (it traded between
117 and 124 USD on 2 Oct 2026; [CoinGecko](https://www.coingecko.com/en/coins/solana)).

| line | unit | what the unit costs | source |
|---|---|---|---|
| Check | one pull request checked | Nothing to Knos. It runs in the repository's own GitHub Actions job or on the user's machine. | by construction; the runner's minutes are not measured |
| Verification | one GitHub-signed token checked on chain | 2 transactions for an RSA-2048 key, 763,497 and 839,351 compute units; 6 for an RSA-4096 key **[measured]** | [BENCH.md](BENCH.md), "The verifier on chain" |
| Settle | one token carried to the chain | 7 transactions, 35,000 lamports, 0.0042 USD on the first deployment **[measured]**. On the second, with `knos-pay` 2.1 and 4,096-byte transactions: 2 transactions **[measured in the simulator]**; not measured on devnet. | [BENCH.md](BENCH.md), "What a relayer pays" |
| Settle | one payment instruction | 62,138 to 94,858 compute units **[measured]** | [BENCH.md](BENCH.md), "The escrow" |
| Settle | a payee's first payment | Rent the relayer puts up, once per person: a token account, 1,488,440 lamports (0.179 USD); a public record of 64 bytes, 975,360 (0.117 USD); a marker of 1 byte the first time a funder pays them, 655,320 (0.079 USD). Together 3,119,120 lamports, 0.374 USD. | arithmetic on the rent rule above |
| Meter | one billable evaluation | The verification, then one `Record` of 81,357 compute units **[measured in the simulator]**; not measured on devnet. Each evaluation also leaves a marker of 88 bytes so that a retry is free: (128 + 88) × 5,080 = 1,097,280 lamports of rent, 0.132 USD, which is more than the 0.05 price. The relayer puts that rent up, and the program returns all of it to that relayer from two hours into the next month (`CloseMark`). So an evaluation costs its relayer the signatures, and rent that is locked for up to a month and not spent. Whether that leaves a margin on a cluster is not measured. | [BENCH.md](BENCH.md), "What a relayer pays"; arithmetic on the rent rule above |
| Control | one organisation for a year | **Not measured.** The cost is people: support, a named party that answers for the service, the reports procurement asks for. None of it exists yet. | [CONTROLS.md](CONTROLS.md) |
| Advance | one advance | Nothing to Knos. The cost of the money is the advancer's. | |

Not in any row: priority fees, which a busy mainnet may need (not measured); the machine that runs a relay; and
GitHub Actions minutes, which are free on public repositories with standard runners and cost a private
repository's owner 0.006 USD a minute on a 2-core Linux runner beyond the minutes its plan includes **[sourced]**
([prices](https://docs.github.com/en/billing/reference/actions-runner-pricing), read 2 Oct 2026). Solana plans to
cut rent to 696 lamports per byte (same SIMD page, expected November 2026). The rents above would fall by 86%.

**Who is made whole on a Settle payment.** The relayer is whoever sends the transaction. The program pays it a tip
out of the fee: 0.05 USDC, or 0.30 when the transaction created the payee's token account. Knos receives the rest.

| order | fee the funder adds | to Knos when the payee was paid before | to Knos on a payee's first payment |
|---|---|---|---|
| 5 USDC | 0.40 | 0.35 | 0.10 |
| 20 USDC | 0.50 | 0.45 | 0.20 |
| 100 USDC | 2.50 | 2.45 | 2.20 |
| 500 USDC | 12.50 | 12.45 | 12.20 |

The 0.30 tip covers a new token account (0.179 USD at 120 USD per SOL). If the same payment also creates the
payee's record and the funder's marker, the three rents come to 0.374 USD and the tip is 0.074 short. The price of
SOL moves that either way. A relayer's transaction fees on the second deployment are not measured.

At the public 2.5%, 1 million USD of fees a year takes 40 million USD of settled payments a year.

### A fork with a zero fee

Knos is MIT. Anyone can deploy the same programs with the fee set to zero, and MergePay already charges none
([COMPARE.md](COMPARE.md)).

| line | what a zero-fee fork takes | what it cannot take |
|---|---|---|
| Check | Nothing. It is already free. | |
| Settle | The public fee. A fork needs a relay that runs and reports its latency. Since the program tips whoever relays, anyone can run one at no loss. So settlement alone will be priced toward zero. | Orders already funded on Knos's program ids finish there. A contract rate (a Plan) lets Knos meet a lower price for one owner without changing the public one. |
| Meter | The per-evaluation fee, the same way. | A count run by the vendor is the vendor's count again, which is the thing the buyer objected to. A fork run by a third party is as neutral as Knos is. |
| Control | Nothing today, because nothing is sold today. The code is in the repository. | A signed contract with a party that answers for the service. A fork can compete for the next one. |
| Advance | Nothing. Knos charges nothing. | |

Three things are not assets. The verifier is free for any program, a fork included. The payment history is public:
anyone can read it from the chain. And relaying pays whoever does it. What a customer would pay Knos for is an
operator that answers for the service. That is unproven: no customer has paid for anything.

## 3. Today's bottom-up, beside what 1 billion USD a year would require

### Today's bottom-up: 121,125 USD a year

Reachable buyers × eligible tasks a year × spend per task × adoption = settled volume. The fee is 2.5% of that,
paid by the funder. An eligible task is one on GitHub, with a fixed scope and checks, done by someone the buyer
does not already pay.

| scenario | reachable buyers | tasks a year, each | spend per task | adoption | settled a year | fees a year |
|---|---|---|---|---|---|---|
| A. Open-source companies that post bounties today | 100 **[sourced]**: Algora's home page says "100+ happy customers". It now leads with hiring, so this is a ceiling. | 25 **[assumption]** | 150 USD **[assumption]** | 20% **[assumption]** | 75,000 USD | 1,875 USD |
| B. Crypto teams and foundations that pay strangers per outcome | 3,380 **[sourced]**: 2,730+ sponsors on Superteam Earn and 650+ protocols on Immunefi. Overlap unknown. That they hold USDC is an **[assumption]**. | 25 **[assumption]** | 200 USD **[assumption]** | 5% **[assumption]** | 845,000 USD | 21,125 USD |
| C. Engineering teams buying fixed-scope changes from outside | 78,500 **[assumption]**: one in ten of Upwork's 785,000 active clients **[sourced]** | 25 **[assumption]** | 100 USD **[assumption]** | 2% **[assumption]** | 3,925,000 USD | 98,125 USD |

Sources for the buyers: [Algora](https://algora.io) (read 2 Oct 2026); Superteam Earn and Immunefi as in section 1;
[Upwork, results for 2025](https://www.globenewswire.com/news-release/2026/02/09/3234886/0/en/upwork-reports-fourth-quarter-and-full-year-2025-financial-results.html)
(read 2 Oct 2026).

- Together: 4,845,000 USD settled in 43,975 payments, and 121,125 USD of fees. Every task here is between 100 and
  200 USD, so the fee is 2.5% exactly: the floor and the ceiling do not apply.
- Of the 121,125, the tips go to whoever relays: 0.05 on each of 43,975 payments is 2,199 USD, more on first
  payments.
- Tasks a year and adoption have no source. 25 is one every two weeks. Adoption today is zero.
- Spend per task: of the 59 open bounties on all boards, 18 were under 50 USD, 14 from 50 to 149, 10 from 150 to
  499 and 17 of 500 or more **[sourced]** (BountyOS, read 2 Oct 2026). Knos caps an order at 500 USDC.
- Scenario C carries 81% of the total and rests on two assumptions with no source. Without it the figure is
  23,000 USD.

### What 1 billion USD a year would require

This is arithmetic. It says what would have to be true. It is not a forecast, and nothing in it has happened.

| line | volume needed | rate | revenue | today's anchor | today, through Knos |
|---|---|---|---|---|---|
| Settle | 30 billion USD settled a year | 1.5% | 450 million | 7.4 times the 4.03 billion USD bought through Upwork in 2025. 1.9% of Gartner's 1.57 trillion USD of IT services in 2026. At the 500 USDC cap, 60 million orders. | 0 USD of real money |
| Control | 3,000 organisations | 80,000 USD a year | 240 million | More organisations than Superteam Earn lists sponsors (2,730+), each paying 80,000 USD a year. | 0 organisations |
| Meter and Verify | 6.2 billion billable evaluations a year | 0.05 blended | 310 million | 24% of the jobs GitHub Actions ran at 71 million a day (25.9 billion a year). 70 times the agent pull requests one tracker counts in a year (1.7 million a week; [WHY.md](WHY.md), section 1). At the 0.02 volume price it is 15.5 billion. | 0 evaluations |
| **Total** | | | **1,000 million** | 8,256 times today's bottom-up | **121,125 USD, and that is a scenario, not revenue** |

Reading the two numbers side by side:

- **121,125 USD** is what the three scenarios give at the public price. **1 billion USD** is 8,256 times that.
- No row of the second table follows from the first. Bounties do not grow into 30 billion USD. The second table
  needs buyers the first does not contain: vendors who meter, companies under contract, and orders far above 500
  USDC.
- "Verify" is the meter counting attestations that are not merges: a deploy, an evaluation, an applied plan
  (section 4). Verifying on chain stays free. What is charged is the count.
- The line with the weakest footing is Meter and Verify: its unit cost is not measured (section 2).
- Revenue today is zero on every line.

## 4. The sequence of expansion

Each step uses what the one before it built. For each: what exists, and what would show that it works.

| step | what it is | what exists | what would show it works |
|---|---|---|---|
| 1. Code on GitHub | A work order on an issue: terms fixed before the work, a GitHub-signed run attests they were met, a Solana program settles. A bounty is the smallest work order. A standing order pays a rate per accepted change. | On devnet, in test USDC. Funded by Knos's own account only ([BENCH.md](BENCH.md), "Measured on devnet"). | Funders who are not Knos, with real money, funding again (section 6). |
| 2. Other issuers | The same verifier admits a signing key of any issuer that signs RS256 tokens and publishes its keys, behind the same delay, approval, expiry and revocation. GitHub Enterprise Server signs under its own host; GitLab signs RS256 **[sourced]** ([GitHub](https://docs.github.com/en/enterprise-server@latest/actions/reference/security/oidc), [GitLab](https://docs.gitlab.com/ci/secrets/id_token_authentication/)). | The verifier checks GitHub and GitLab tokens. The escrow pays public orders on GitHub's tokens only. No GitLab token has been verified on devnet. | A payment on devnet attested by an issuer that is not GitHub. |
| 3. Acceptance beyond code | The signed statement is about something other than a merge: a deploy that went green, an evaluation that passed, infrastructure that applied. Each needs its issuer admitted and a map from its claims to terms. | Payment without a merge exists for one case: a black-box test bundle, where the submission runs as a separate process and only its output is compared ([TAMPER.md](TAMPER.md)). Nothing has been paid on a deploy, an evaluation or an applied plan. | One payment for each, with a cheating submission refused. |
| 4. Advances against accepted work | A payee assigns the payment of an order to another wallet. A third party pays them early and collects it. | The assignment instruction. No advance has been made, and Knos makes none. | Someone other than Knos advancing money against an order, twice. |

Steps 2 to 4 widen what can be counted and paid. None of them brings a buyer by itself.

## 5. What can stop this

| what | why it could | what Knos does about it | what Knos cannot do |
|---|---|---|---|
| **GitHub ships it** | GitHub owns the record Knos reads. A request for bounties on issues has been open since 6 Jul 2021 **[sourced]** ([discussion 4517](https://github.com/orgs/community/discussions/4517)). | Takes signed statements from issuers other than GitHub (section 4). Stays neutral between agents: GitHub sells an agent of its own, so it would be counting its own sales. Settles outside GitHub's billing, to any wallet. | Stop it, or outlast it on public repositories: a native escrow would take that line. Knos also depends on GitHub's tokens and API, and has to change when they change. |
| **A payment rail adds acceptance** | The rails have the distribution. x402 reports 75.41 million transactions and 24.24 million USD in 30 days **[sourced]** ([x402.org](https://x402.org), 3 Oct 2026). It is pay before access, with no check of delivery. The draft ERC-8183 has the slot already: one evaluator address that "alone may mark the job completed" **[sourced]** ([EIP](https://eips.ethereum.org/EIPS/eip-8183); draft, created 25 Feb 2026). | Builds the evaluator, not the rail: the verifier is free for any program to read. | Match a rail's reach. If a rail ships its own check of CI tokens, Knos's is one of several. |
| **Zero-fee copies** | MIT, and MergePay charges no platform fee. | Section 2: a contract rate on chain, and lines a fee constant does not carry. | Keep a percentage on public settlement once someone relays as well for less. |
| **The attestor gap** | GitHub signs that a workflow ran. It does not sign what the workflow read. The statement is as honest as the runner and the repository it ran in. | Pins the workflow by commit. Requires a GitHub-hosted runner and a first attempt. Lets a funder's repository decide about that funder's money only. After a merge, lets the seller have the pinned workflow read GitHub's public record from a repository of the seller's own, so a buyer who deletes the workflow no longer withholds payment. | Prove the reading without trusting GitHub's hosted runners. There is no second, independent attestor. A private order trusts the repository its funder named as judge. ([SECURITY.md](SECURITY.md)) |
| **Regulation** | Holding and paying out money for others may be money transmission. Paying contractors brings tax reporting. Paying anyone brings sanctions law. | Holds no key to an order's money in normal operation. Screens a payout address against the OFAC list. Exports every payment for the payer's own records. ([REGULATION.md](REGULATION.md)) | Give a legal opinion. Counsel has not been asked. Until an outside review Knos can change the program through its multisig, which weakens any claim that it does not control the money. |
| **The history of bounty platforms** | They close. Bountysource left at least 21,702.10 USD of completed work unpaid ([boehs.org, 3 May 2024](https://boehs.org/node/bountysource)). Gitcoin retired its bounties; users had until 30 Jul 2023 to take their data ([Gitcoin](https://support.gitcoin.co/gitcoin-knowledge-base/misc/cgrants-bounties-and-hackathons-sunsetting-faq)). OnlyDust closed after 18 million USD in grants: "Low-skill contributors were flooding them with AI-generated code" ([onlydust.com](https://www.onlydust.com/)). Polar's founder on open bounties: "it's a race towards that cash, and so the contributions are of fairly low quality" ([Changelog 591](https://changelog.com/podcast/591)). All **[sourced]**. | No company holds the money. An order can be reserved for one person. Acceptance is named checks plus a merge, fixed before the work. The business is not the board: section 3 says a board is 1,607 USD. | Make a small market large, or make a buyer come back. |
| **Maintainer fatigue** | Money plus free submission floods the person who reads. curl ended its bug bounty in January 2026 to "remove the incentive for people to submit crap and non-well researched reports" **[sourced]** ([The Register, 21 Jan 2026](https://www.theregister.com/2026/01/21/curl_ends_bug_bounty/)). | The free check marks a false "tests pass" before a person reads the pull request. A reservation gives an issue to one person. A policy file says who may be paid. GitHub's own limits on pull requests still apply ([COMPARE.md](COMPARE.md)). | Remove the review. A funded issue still draws pull requests, and a maintainer still has to say no. |

## 6. The funnel, and the one test that matters

| stage | what is counted | today |
|---|---|---|
| 1. Installed | repositories whose workflows call the Knos check | not measured |
| 2. Funded | tasks that someone other than Knos funded with their own tokens | 0 **[measured]** |
| 3. Completed | of those, tasks paid to someone other than the funder | 0 **[measured]** |
| 4. Funded again | funders who funded another task after one of theirs was paid | 0 **[measured]** |

Stages 2 to 4 are read from the programs' own logs ([BENCH.md](BENCH.md), "Measured on devnet": the site's
`stats.json` of 3 Oct 2026, 16:04 UTC), with Knos's own accounts kept apart. Three payments on devnet went to a
GitHub account that is not Knos's. Knos funded those tasks itself, in test money, so they are not outside demand
and stage 2 does not count them.

**The one test: funders who are not Knos, funding a second task with real money. Today: zero.**

It cannot be passed on devnet, where the money is free. What each earlier result would mean:

- **Few install.** The check is not wanted. There is no business.
- **Many install, few fund.** Knos is a free check, and the escrow is a feature few need.
- **Funded, not completed.** The tasks or the terms are wrong: nobody takes them, or the checks refuse honest work.
- **Completed, not funded again.** A trial, not a habit.
- **Funded again, by funders who are not Knos, with real money.** A payment business. The number to watch is how
  many such funders there are and what each settles in a month.

## 7. What a seller keeps

The seller is a person running an agent, or working by hand, who is not on the buyer's payroll. The funder pays
the fee, so a 20, 100 or 500 USDC order pays 20, 100 or 500.

- Model cost per attempt: 1, 3 and 15 USD for those sizes **[assumption]**. The anchor is a published estimate of
  0.04 to 4.50 USD for a simple task and 0.08 to 13.50 USD for a medium one **[sourced]**
  ([KSPL Academy, 2 Jun 2026](https://academy.kspl.tech/blog/2026-06-02-ai-coding-agent-cost-ladder-2026); its own
  estimates, not measurements; read 2 Oct 2026).
- Attempts per accepted result = 1 ÷ merge rate. Published: 71.5% of 33,596 agent pull requests in repositories
  with more than 100 stars were merged **[sourced]** ([arXiv 2601.15195](https://arxiv.org/html/2601.15195)). That
  is every agent pull request, not strangers answering paid tasks, so it is the favourable case. For a stranger
  there is no published rate. One hunter's 30-day log gives about 15% **[sourced, one person's account]**
  ([dev.to, 1 Jun 2026](https://dev.to/zeroknowledge0x/the-open-source-money-map-every-way-developers-are-actually-making-money-in-2026-with-real-45ba)).

| order | paid | model cost per attempt | kept at 71.5% merged | kept at 15% merged |
|---|---|---|---|---|
| 20 USDC | 20 | 1 | 18.60 | 13.33 |
| 100 USDC | 100 | 3 | 95.80 | 80.00 |
| 500 USDC | 500 | 15 | 479.02 | 400.00 |

A person's time changes this. GitLab puts a manual review at 15 minutes of a senior engineer, about 25 USD
**[sourced]** ([GitLab, 19 Mar 2026](https://about.gitlab.com/blog/agentic-code-reviews-with-flat-rate-pricing)).
A seller who checks each attempt that carefully loses money on a 20 USDC order at any merge rate.

| risk | who bears it |
|---|---|
| Attempts that are not merged: model cost and time | the seller |
| A maintainer who never looks, or declines after reading the diff | the seller. A reservation removes the race with other sellers, not this. |
| A merged pull request that is not paid, because a funded check did not pass or a file was outside the allowed paths | the seller. The terms are public before the work starts. |
| A buyer who merges and then removes the workflow | the seller, only on an order that turned neutral attestation off. By default, after a merge, the seller can have the pay token produced from a repository of their own. |
| An order cancelled while the seller holds the reservation | the funder, up to the share named at funding (at most 20%); the rest, the seller |
| Money locked until the deadline, or until 7 days after a cancellation | the funder |
| Paying for work that passed weak checks | the funder, who chose the checks. A holdback and a warranty, set at funding, return part of it if the change is reverted in time. |
| Transaction fees, rent, and tokens that fail on chain | whoever relays, against the tip |
| GitHub wrong or down, a fault in a program, a program changed through the multisig | everyone ([SECURITY.md](SECURITY.md)) |
| What USDC is worth and where it can be spent | the seller |

## 8. What is not known

- Whether anyone will fund a second task with real money. There is no outside funder.
- Whether any vendor or buyer wants a neutral count enough to pay for it. Nobody has been asked.
- What a billable evaluation costs to record on a cluster, and so whether Meter has a margin at 0.05 or at 0.02. It is
  measured in the simulator only.
- What relaying costs on the second deployment and on mainnet. Priority fees are in no measurement.
- What share of the spend on coding agents would move to payment on acceptance. No source gives it.
- The merge rate for strangers who answer funded tasks. The only figure is one person's log.
- The price of a merged change. Sourcegraph and GitStart do not publish theirs.
- How many repositories have installed the check.
- How long a merge takes to become a payment across many repositories. On devnet, from merge to payment took
  24 seconds at the median, over 36 payments
  ([BENCH.md](BENCH.md)), all in Knos's own repositories.
- How many payees can turn USDC into money they can spend, and in which countries.
- How these payments are regulated and taxed. [REGULATION.md](REGULATION.md) says what was read and what was not.
  Counsel has not been asked.
- What a company's security or procurement review would say. [CONTROLS.md](CONTROLS.md) lists what exists and what
  does not.
- When a security firm will review the programs, and what it will cost. None has.
