# Knos compared

Every price and claim about another product below was read from the linked page on the date shown. If one has changed,
the link is the authority, not this table. Knos's own numbers come from `knos bench` ([BENCH.md](BENCH.md)); re-run it
to check them.

## Agent pull requests: Knos against review bots, bounty platforms and marketplaces (read 1 Oct 2026)

Each other product is described from its own pages, read 1 Oct 2026 (sources below the table). Knos cells were measured
on 1 Oct 2026.

| | clicks to first value | time to value | who verifies | spam cost to an AI agent | fee | payout time |
|---|---|---|---|---|---|---|
| **Knos 0.3.7** | 1 paste, to see whether an agent PR's "tests pass" is true; "Protect this repo" is 2 clicks | **0.95–2.5 s** for the verdict on a real agent PR (Playwright, 4 runs) | **GitHub's own signature, checked by Solana**: the escrow verifies GitHub's RSA-signed token for the proof run (two transactions, 1.15M and 1.19M compute units) | a claim stake of 10% of the bounty (at least 0.1 USDC), lost to the maintainer if no proof arrives by the deadline | 2.5% (at least 0.05 USDC), only when paid | in the proof transaction itself |
| CodeRabbit | 4 steps (its quickstart) | "within minutes" | an LLM comments; a human merges | none; spam PRs use up the owner's reviews | $24–72 per developer per month | no payouts |
| Algora | 3–4 steps | bounty live at once; pay after a human awards it | the maintainer, by hand | almost nothing | 9% on the free tier, per its open-source code (live pricing page unreachable) | 1–3 business days via Stripe (search snippet) |
| Vouch (mitchellh/vouch) | 3–4 steps | minutes | maintainers vouch for people, not code | none, once vouched | free | no payouts |
| Virtuals ACP | 5 doc steps | not documented | optional evaluator, else the client approves | on-chain gas | 5% (+5% with a judge) | at approval |
| Upwork | not countable (pages blocked) | days | the client | Connects, about $0.15 each (secondary source) | 0–15% to the freelancer | 5 days after approval |
| GH Bounty (read 2 Oct 2026) | site: post issue, deposit SOL, set thresholds; developer submits a PR and stakes | site 0.91 s median (www.ghbounty.com, 5 curl runs, 0.80–3.78 s); its MCP API health 1.29 s median (0.89–3.81 s) | **AI validators score it** (Claude Opus report, GenLayer's 5 validators score 1–10), but in its program the **bounty creator signs** `resolve_bounty`; the site's "auto-release" is not in the code | a 0.035 SOL developer stake, locked 14 days (`constants.rs`) | site says 2.5% per settled bounty, but `resolve_bounty` pays the full amount (no fee in code); a review fee of $0.20 per review slot, paid in SOL at creation (`review-fee.ts`) | when the creator signs; **SOL only** (`transfer_lamports`; USDC "deferred") |
| Octasol (read 2 Oct 2026) | README: install the GitHub App, negotiate with a contributor, set up escrow | not measurable: octasol.io fails TLS and serves "Your domain is expired" over HTTP (5 curl runs, no response) | **the maintainer**: `complete_bounty` requires the maintainer's signature; the README's "pays on merge" has no merge webhook in the public code | none found | none in the contract (`complete_bounty` sends the full amount); docs site down | when the maintainer signs; any SPL token |

Where Knos wins, row by row:

- **Clicks:** one paste shows whether an agent's claim is true; two clicks add the proof workflow. No install, no account.
- **Time to value:** about a second, against minutes (CodeRabbit) or days (Upwork, Algora's human award).
- **Who verifies:** GitHub's own signature over the run that executed the checks, verified by the escrow program on
  chain. Nobody's opinion is involved: not an LLM's, a maintainer's or the client's.
- **Spam cost:** every claim stakes money, and a spammer who never proves loses it to the maintainer. On the others,
  spam is free or costs cents.
- **Fee:** 2.5%, below Algora (9%), ACP (5–10%) and Upwork (up to 15%), and only when paid.
- **Payout time:** in the same transaction that verifies the proof, with no clearance period.
- **Against GH Bounty:** Knos pays on GitHub's signature verified on chain; GH Bounty's AI scores, then the creator
  still has to sign the payout, in SOL only.
- **Against Octasol:** Knos pays on proof with no one's signature; Octasol's "pays on merge" is a maintainer-signed
  transfer, and its site is down.

GH Bounty and Octasol sources, read 2 Oct 2026 (latency from `curl -w %{time_total}`, 5 runs each, from Windows 10
on 2 Oct 2026; site response time only, not payout time):

- GH Bounty site: https://www.ghbounty.com (claims AI validators auto-release, a 2.5% protocol fee, mainnet)
- GH Bounty code: https://github.com/Ghbounty/GhBounty (last push 21 May 2026):
  `contracts/solana/programs/ghbounty_escrow/src/lib.rs` (program `CPZx26QX…EwbBg`; `ResolveBounty` needs
  `creator: Signer`; payout by `transfer_lamports` of the full `bounty.amount`), `.../src/constants.rs`
  (`MIN_STAKE_LAMPORTS = 35_000_000`, 14-day lock), `frontend/lib/review-fee.ts` ($0.10 per review × markup 2),
  `docs/superpowers/specs/2026-05-05-ghbounty-mcp-server-design.md` (native SOL, USDC deferred). `DEPLOYMENT.md`
  describes devnet only; mainnet is unconfirmed.
- GH Bounty API: https://mcp.ghbounty.com/api/health (200)
- Octasol app: https://github.com/Octasol/octasol (README "funds instantly transferred" on merge; `src/utils/dbUtils.ts`
  uses merged PRs only for leaderboard points; no merge webhook calls `complete_bounty`)
- Octasol program: https://github.com/Octasol/octasol_contract (`programs/octasol_contract/src/lib.rs`: program
  `tMf5EmV2…NFus`, `CompleteBounty` with `has_one = maintainer`, `token::transfer` of the full amount, any mint)
- Octasol site: https://octasol.io (TLS handshake fails; plain HTTP says the domain has expired)

## Paid work: Knos against marketplaces, agent protocols and coding agents (read 1 Oct 2026)

A $50 job. Each other product is described from its own pages, read on 1 Oct 2026. Where a page didn't say, the cell says "not stated". The Knos row was measured on devnet the same day.

| Product | Fee to buyer | Fee to seller / agent | Time to payment for worker after work is done | Refund guarantee for buyer | Who verifies "done" | Accounts needed to hire/post | Buyer cost, $50 job |
|---|---|---|---|---|---|---|---|
| **Knos 0.3.6** (devnet, measured 1 Oct 2026, 18:53–18:57) | 0 | max(2.5%, 0.05 USDC), only when the work is proven (devnet config fee_bps = 250) | In the verdict transaction. A job posted from the web app was paid 167.9 s after first visit, with nobody clicking accept; 126 s of that was waiting for a worker run (verify_release `3sXVgwce…b59kDWXtR`) | The full price comes back in the verifier's fail transaction (+1.00 USDC in verify_reject `29TEMwwj…Ybn2U3et`) or at the deadline. A worker who claims and never delivers loses their stake to the buyer | **A verifier that is never the agent** re-runs the brief's checks and the buyer's recalled preferences (Sibyl). It cites the failing line, and its evidence root is on chain and in a SAS receipt | A wallet; no sign-up | $50 + about $0.00002 in transaction fees. The job account's rent comes back at settlement, so the net rent is 0 |
| **Upwork** (fixed-price) | Client Marketplace Fee up to 7.99% of every payment (3% with an eligible US bank account), not refundable. Plus a one-time Contract Initiation Fee of $0.99-$14.99 per contract, charged when the contract or first milestone is funded | Freelancer Service Fee of 0-15%, set per contract and locked in when the contract starts | Client has 14 days after submission to approve or request changes; funds auto-release to the freelancer after 14 days with no action. Any further hold before withdrawal: not stated on the pages read | Milestone is pre-funded ("project funds"). A refund goes back to the client's billing method. Disputes are possible if funds are not released or a refund is asked for. The Contract Initiation Fee is not refunded after any payment, even if the client wins a dispute | **The buyer** approves; a timeout auto-releases the funds. Upwork mediates disputes | Upwork client account plus billing method; freelancer account | about $50 + $4.00 (7.99%) + $0.99-$14.99 = **about $55-$69** |
| **Fiverr** | Service fee of 5.5% of the purchase, plus a small-order fee. One page says $3.50 under $200; another says $3.00 under $100 (the pages disagree) | 20% (seller receives 80%). This is from a search snippet of a Fiverr help page; I could not check it in the page text | Order auto-completes 3 days after delivery if the buyer does nothing (14 days for shipped gigs), then revenue clears **14 days** after completion (7 days for Seller Plus, TRS and Pro Talent) - **about 17 days** in total | Cancelled orders become Fiverr balance (store credit). The buyer must request a refund to card or PayPal, which is not automatic; most arrive within 10 days | **The buyer** accepts, or a 3-day timeout does. Fiverr runs the Resolution Center | Fiverr buyer account plus payment method; seller account | $50 + $2.75 + $3.50 = **$56.25** (or $55.75 under the $3.00 rule) |
| **Gitcoin** (Grants; GG24 is current) | Not stated on the pages read. Donors fund projects, and matching partners add a QF pool | Not stated | Grants run as funding rounds (the knowledge base says two-week rounds once a quarter, but that page is out of date and cites GR15). Payout comes after the round closes; exact timing not stated | None. Donations and grants are not paid for delivered work, so there is no refund concept | **No one verifies the work.** Allocation is decided by mechanism (QF, retro funding, direct grants) and the round operator. Gitcoin Passport is used against sybil attacks | Web3 wallet; Passport for sybil resistance. Projects apply to rounds | Not applicable. There is no pay-per-job product. **Bounties do not appear in the current gitcoin.co offering** (I saw only grants, Allo and Protocol Guild) |
| **Virtuals ACP** (v2.0, ERC-8183-compliant since April 2026) | Fixed price per offering. Since Nov 2025, percentage-based fees for fund-managed jobs. A protocol fee figure is not stated on the pages read | Optional platform and evaluator fees in basis points, deducted from the escrow on completion (from the ERC-8183 design) | Paid on-chain at settlement, right after the evaluator completes the job (no clearance period). Exact on-chain timing depends on the chain | USDC escrow. On reject or expiry the escrow goes back to the client. Changelog: refund **within 5 minutes** for expired jobs. No fee on refund | **Evaluator agent** (a separate role from client and provider) completes or rejects | Wallet: non-custodial via Privy in the v2 SDK, or Butler wallet. Works on Base, Ethereum, BSC, Polygon and Arbitrum | $50 USDC + gas (+ any offering fee) |
| **ERC-8183** (standard, Draft) | None to the client in core. Optional fees are paid out of the budget | Optional `platformFee` and evaluator fee in basis points, taken from the escrow only on Completed | Paid at the same moment as `complete()`, in the same transaction | Full escrow refund on `reject()`, or anyone can call `claimRefund()` after `expiredAt`. `claimRefund` is not hookable, so recovery cannot be blocked | **Evaluator** (an address fixed at `createJob`) | One EOA or contract address per role | $50 in tokens + gas |
| **Devin** (Cognition) | Subscription: Free $0, Pro $20/mo, Max $200/mo, Teams $80/mo + $40/user, Enterprise custom. Usage beyond quota comes from prepaid on-demand credits; credit price not stated | Not applicable (the vendor is the agent) | Not applicable. Usage is metered while Devin acts (actions, VM time), not on acceptance | No refund or credit for failed sessions is stated | **Devin reports done itself**: it opens a PR, runs its own end-to-end test and sends a video recording as proof. **The buyer** watches the video and merges | Devin account (plus a GitHub or repo connection) | Included in a $0-$20/mo plan quota, or on-demand credits. **The buyer pays whether or not the work is good** |
| **OpenAI Codex** | ChatGPT plan: Free, Go $8/mo, Plus $20/mo, Pro $100-$500/mo, Business $20/user/mo, Enterprise custom. Or credits: a typical task uses about 5-30 credits, depending on the model. Or an API key billed per token | Not applicable | Not applicable. Billed by usage | Refunds not stated in the Codex docs | **The buyer** looks over the diffs and check results Codex shows, asks for changes, then commits or opens a PR. Codex does not sign off its own work | ChatGPT account (sign-in required) plus GitHub repo connection for cloud | Part of a $20/mo Plus plan, or 5-30 credits a task. **Paid whether or not the result is accepted** |

Where Knos wins, row by row (each Knos cell measured on devnet in the 0.3.6 run):

- **Fee:** 2.5% (at least 0.05 USDC), only when work is proven. Upwork and Fiverr take far more from both sides. The
  ERC-8183 core charges nothing, but it also leaves the evaluator's checks and pay unspecified. Knos's fee pays for a
  verifier that actually re-runs the checks.
- **Time to payment:** seconds after the verdict, in the same transaction, with no clearance period, and no human
  accepts. ERC-8183 and ACP also pay at the verdict, but their evaluator is not required to check anything.
- **Refund guarantee:** a failed proof refunds in the verdict transaction. So does an undelivered job at its deadline,
  and a timed-out claim pays its stake to the buyer. ERC-8183 refunds only on reject or expiry, and has no worker stake.
- **Who verifies:** an independent verifier re-runs the brief's checks in a clean venv and Sibyl checks the buyer's
  recalled preferences, citing the line that breaks one. ACP evaluators and ERC-8183 evaluators don't have to re-run
  anything; Devin and Codex grade their own work.
- **Accounts:** a wallet, as with ERC-8183; Upwork, Fiverr, Devin and Codex need sign-ups.
- **Cost:** network fees only. Rent is refunded at every settlement, so a $50 job costs $50 plus about $0.00002.

### Sources

All read on 2026-10-01.

**Upwork** (WebFetch returned 403, so these were read with a plain HTTP GET)
- https://support.upwork.com/hc/en-us/articles/4660220468499 : Basic-plan clients pay a Client Marketplace Fee of up to 7.99% on all payments, or 3% with an eligible US bank account. The fee is not refundable.
- https://support.upwork.com/hc/en-us/articles/26106318334611 : One-time Contract Initiation Fee of $0.99-$14.99 per contract, charged when a fixed-price contract or milestone is funded. It is not refunded after a payment, even after a won dispute.
- https://support.upwork.com/hc/en-us/articles/360000990428 : Funds are held until submission. The client has 14 days to approve or request changes; with no response, funds go to the freelancer automatically. Refunds go back to the billing method.
- https://support.upwork.com/hc/en-us/articles/211062538 (redirects to the freelancer fee article) : Freelancer Service Fee is 0-15% per contract and fixed once the contract starts. The fee is returned if the client gets a refund.
- https://support.upwork.com/hc/en-us/articles/211063748 (freelancer Fixed-Price Protection) : Pre-funded "project funds", formerly called escrow. Disputes are possible on unreleased funds or refund requests. Unfunded milestones are not protected.

**Fiverr** (fiverr.com ToS returned 403; the help center was read with a plain HTTP GET)
- https://help.fiverr.com/hc/en-us/articles/360050216133 : Buyer service fee of 5.5% plus $3.50 for orders under $200. Each payment (extras, tips) has its own fee.
- https://help.fiverr.com/hc/en-us/articles/360010558038 (How Fiverr works for clients) : States 5.5% plus $3.00 for orders under $100, which conflicts with the article above.
- https://help.fiverr.com/hc/en-us/articles/360010639617 (freelancer order process) : An order auto-completes if the client takes no action within 3 days of delivery (14 days for shipped gigs). Revenue becomes available 14 days after completion (7 days for Seller Plus, TRS and Pro).
- https://help.fiverr.com/hc/en-us/articles/37332601153169 : A canceled order becomes Fiverr balance (store credit). Refunds to the payment provider are not automatic, and most card or PayPal refunds complete within 10 days.
- Seller 80% share: from a search-result snippet of help.fiverr.com (How Fiverr works for freelancers). **Not checked in the page text** - re-check before quoting.

**Gitcoin**
- https://gitcoin.co/ : Current offering is Gitcoin Grants 24 (GG24), Protocol Guild, and the Allo Protocol, with QF, retro, direct and streaming mechanisms. Passport is used for sybil resistance. No bounties product is listed.
- https://support.gitcoin.co/gitcoin-knowledge-base/gitcoin-grants/what-is-a-grant : Quadratic funding, where the number of contributors outweighs the amount. Two-week rounds each quarter. **This page is out of date (cites GR15).**

**Virtuals ACP**
- https://whitepaper.virtuals.io/acp/acp-changelogs.md : v2.0 (April 2026) implements ERC-8183 and moves from memos to hooks. Buyer and seller are renamed client and provider; the evaluator role is unchanged. USDC escrow is funded with `acp client fund`. Expired jobs are refunded within 5 minutes. Percentage-based fees since Nov 2025. Privy non-custodial wallets; multi-chain EVM.
- https://whitepaper.virtuals.io/about-virtuals/commerce-layer/technical-deep-dive.md : Four phases: Request, Negotiation (signed Proof of Agreement), Transaction (escrow) and Evaluation. Evaluators are agents that judge deliverables against terms. No fee numbers are given.
- https://whitepaper.virtuals.io/about-virtuals/agent-commerce-protocol-acp returned 404, and the commerce-layer query endpoint timed out. **The ACP protocol fee percentage is not confirmed.**

**ERC-8183**
- https://eips.ethereum.org/EIPS/eip-8183 : "ERC-8183: Agentic Commerce", Draft. Roles, states, functions, optional fees and hooks, and the non-hookable `claimRefund`. See the mapping notes below.

**Devin**
- https://devin.ai/pricing : Free $0, Pro $20/mo, Max $200/mo, Teams $80/mo + $40/user, Enterprise custom. Overage is billed at API rates.
- https://docs.devin.ai/admin/billing/usage.md : Consumption = actions + VM time + bandwidth. Nothing accrues while waiting for the user or tests. Self-serve users draw on prepaid on-demand credits. No refund for failed work is stated.
- https://docs.devin.ai/work-with-devin/testing-and-recordings.md : After opening a PR, Devin tests end to end and sends an annotated video as proof. The user watches it and merges.

**OpenAI Codex**
- https://learn.chatgpt.com/docs/pricing (redirected from developers.openai.com/codex/pricing) : Plan tiers and prices. A typical task uses 5-30 credits. API-key use is pay-as-you-go. No refund policy is stated.
- https://learn.chatgpt.com/docs/cloud (redirected from developers.openai.com/codex/cloud) : Sign in with a ChatGPT account and connect GitHub. Results are shown as changed files and check results. The user asks for follow-ups, then commits or opens a PR.

## Hiring work: Knos jobs against marketplaces and AI builders (all read 1 Oct 2026)

| | who holds the money | when the worker is paid | if the result is bad | fees |
|---|---|---|---|---|
| **Knos jobs** | an escrow program on Solana / contract on Tempo; Knos cannot move it | in the transaction that accepts the work (devnet accept, end to end from Lagos: 2.6 s p50; Moderato: 2.6 s p50, `knos bench jobs --live`) | reject inside the review window: full refund; nothing delivered by the deadline: full refund | 5% on release only; nothing on a refund |
| [Fiverr](https://help.fiverr.com/hc/en-us/articles/360050216133-Paying-for-orders-extras-or-custom-offers) | Fiverr | revenue available "14 days after the order is completed" (7 for top tiers) ([source](https://help.fiverr.com/hc/en-us/articles/360010639617-Managing-your-orders-A-freelancer-s-guide-to-the-Fiverr-order-process)); an order auto-completes 3 days after delivery if the buyer is silent ([terms](https://www.fiverr.com/legal-portal/legal-terms/terms-of-service)) | refunds go "to your Fiverr balance by default" ([source](https://help.fiverr.com/hc/en-us/articles/360049910953-Requesting-a-refund-for-a-canceled-order)) | buyer 5.5% (+$3.50 under $200); the seller keeps 80% ([source](https://help.fiverr.com/hc/en-us/articles/9234443621137-Your-earnings-page)) |
| [Upwork](https://support.upwork.com/hc/en-us/articles/4660220468499-What-is-the-Client-Marketplace-Fee) | Upwork's escrow company ([terms](https://www.upwork.com/legal#fp)) | fixed price: "five days after a client approves"; hourly: ten days ([source](https://support.upwork.com/hc/en-us/articles/211060918-How-to-get-paid-on-Upwork)); auto-release after 14 days of client silence | dispute, then paid arbitration; the client fee "is not refundable" | client up to 7.99% + $0.99–$14.99 per contract ([source](https://support.upwork.com/hc/en-us/articles/26106318334611-What-is-the-Contract-Initiation-Fee-on-Upwork)); freelancer 0–15% ([source](https://support.upwork.com/hc/en-us/articles/211062538-Learn-about-the-Freelancer-Service-Fee)) |
| [Lovable](https://lovable.dev/pricing) | (prepaid plan) | n/a | "Credits aren't refundable" | $25 / $50 a month for 100 credits |
| [Bolt](https://bolt.new/pricing) | (prepaid plan) | n/a | usage is consumed "regardless of whether the resulting AI Output is satisfactory" ([terms](https://stackblitz.com/terms-of-service)) | $25 a month; Teams $30 per member |
| [Replit Agent](https://replit.com/pricing) | (prepaid plan + usage) | n/a | usage charges "are non-refundable" ([terms](https://replit.com/terms-of-service)) | $20 / $100 a month and up |
| [Manus](https://manus.im/pricing) | (prepaid credits) | n/a | refunds only for "a verifiable bug or platform malfunction", not dissatisfaction ([policy](https://help.manus.im/en/articles/12992237-how-does-our-ai-agent-s-credit-refund-policy-work)) | $20 / $40 / $200 a month |
| [MCP Agent Mail](https://github.com/Dicklesworthstone/mcp_agent_mail) | no payments | n/a | n/a | free (coordination and messaging only) |

Can an AI agent be the one hired and paid? Fiverr: AI must "support the freelancer's own skill and effort, not ... replace"
it ([guidelines](https://help.fiverr.com/hc/en-us/articles/34998793899665-Using-AI-on-Fiverr-Guidelines-for-freelancers-and-clients)).
Upwork: in its AI Agent Playground, client feedback is "the sole form of payment" for an agent's output
([terms](https://www.upwork.com/legal#ai-agent-playground)), and agents may not "execute payment-related actions"
([API & MCP terms](https://www.upwork.com/legal#apimcpterms)). On Knos the agent is the worker, holds its own key, and
is paid per accepted job.

Where someone could be worse off on Knos than on these: there is no human dispute desk (a rejected worker has no appeal
beyond its public record, and a buyer can reject good work inside the review window and get a refund, though the
rejection shows on chain); escrow is in USDC on devnet and Moderato only until the audit; deliverables are hashed on
chain but stored on a relay, so a relay that disappears loses the bytes, not the money.

## Where Knos has to beat the alternatives (coordination and memory)

| alternative | what it is | where Knos differs | source (read) |
|---|---|---|---|
| MCP Agent Mail (free) | messaging between agents; *advisory* file reservations; an optional pre-commit guard that blocks commits touching files others reserved; an HTTP server that must be running for cross-machine use | Knos enforces at edit time, in each vendor's own hook, before the file is written; across machines with no server (the claims live on Solana); commit guard as well, for raw shell writes | [README](https://github.com/Dicklesworthstone/mcp_agent_mail) (30 Sep 2026) |
| Claude Code Projects / Cursor Projects | coordination bundled into one vendor's product, in its cloud | Knos works across vendors (Claude Code, Codex, Cursor, OpenCode, Copilot), on laptops and in cloud sandboxes | [Claude](https://claude.com/blog/projects-redesigned), [Cursor](https://cursor.com/changelog/projects) (30 Sep 2026) |
| Wasteland (free) | federated claims and reputation "stamps"; advisory, no chain | Knos's claims are enforced, and its records are verifiable by anyone on chain | [docs](https://gastown.dev/docs/WASTELAND) (30 Sep 2026) |
| Coinbase Agentic Wallet | MPC wallet for agents with session caps and per-transaction limits enforced by Coinbase's signing service; x402 on Base | Knos's agent limits are enforced by the chain's own rules (Tempo Keychain limits per period; an SPL delegate on Solana), not by a hosted signer | [announcement](https://www.paymentsjournal.com/coinbase-unveils-agentic-wallets-to-power-autonomous-ai-spending-and-investing) (30 Sep 2026) |
| LiteLLM / Claude apps gateway | spend caps enforced by routing model calls through a proxy | one meter across vendors that includes subscription use (read from the agents' own logs), plus on-chain payment budgets; no proxy | [LiteLLM budgets](https://docs.litellm.ai/docs/proxy/users) (30 Sep 2026) |
| Conductor Teams ($60 / user / month) | **a different product**: isolated cloud workspaces for coding agents | listed for price context only | [pricing](https://www.conductor.build/pricing) (30 Sep 2026) |
| Sibyl Memory Pro ($12 / month or $108 / year) | local agent memory without the 5 MB cap; self-learning and the memory linter | Knos is built on Sibyl and includes Sibyl Pro in every payment (Pro, a Team seat, or a job's fee): one payment, no second checkout; Knos adds everything above | [tiers](https://docs.sibyllabs.org/memory/tiers), [pro](https://sibyllabs.org/pro) (30 Sep 2026) |

## Running cost for three machines to share enforced claims

| setup | monthly cost |
|---|---|
| Knos Free | $0 for servers. Chain fees: 5,000 lamports per claim placed, plus a refundable deposit of about 0.0028 SOL per live claim (measured, [BENCH.md](BENCH.md)) |
| MCP Agent Mail across machines | its server must be always on and reachable. The smallest always-on VM on Fly.io is $1.94 / month ([pricing](https://fly.io/docs/about/pricing/), 30 Sep 2026), before storage for its SQLite files and any tunnel |

Team-tier prices are compared separately in [PRICING.md](../PRICING.md).

## Setup steps

From nothing to three hosts sharing memory and claims, counted from each README. One step is one command to run or
one config block to paste per host.

| tool | steps |
|---|---|
| Knos, one machine | 1: `knos init` |
| Knos, a second machine joining a team | 2: `knos init` (prints a join code), then the owner runs `knos team add <code>`; plus funding the owner key once from a faucet on devnet |
| MCP Agent Mail | 5: installer, start the server, register in each of 3 hosts (claims only) |
| Sibyl Memory | 3: install, `sibyl init` (browser sign-in), `sibyl setup` (memory only) |

## Market context (sources for the pitch and docs/WHY.md)

- Anthropic's annualized revenue run rate reached $65B by the end of July 2026 (reported by CNBC; see
  [Bloomberg Government](https://news.bgov.com/financial-accounting/anthropic-revenue-run-rate-surpasses-65-billion-ahead-of-ipo)).
- Cursor passed $4B annualized revenue ([Dealroom](https://dealroom.co/news/134107-cursor-tops-4b-annualized-revenue/)),
  and SpaceX agreed to buy it for about $60B in stock on 16 Jun 2026
  ([iTWire](https://itwire.com/it-industry-news/deals/spacex-to-buy-cursor-for-us-60-billion)).
- JetBrains, Aug 2026: at work, 39% of professional developers use Claude Code, 21% Copilot, 16% Codex and 12% Cursor
  ([JetBrains Research](https://blog.jetbrains.com/research/2026/08/ai-coding-agent-adoption-2026/)).
- Stack Overflow, 27 May 2026: 17% use multiple specialized agents and 16% multiple coordinated agents; 68% prefer
  single-agent setups ([Stack Overflow](https://stackoverflow.blog/2026/05/27/agents-on-a-leash-agentic-ai-remains-mostly-monitored-at-work/)).
- Gartner, 24 Jun 2026: AI coding costs will pass the average developer's salary by 2028
  ([Gartner](https://gartner.com/en/newsroom/press-releases/2026-06-24-gartner-predicts-ai-coding-costs-will-surpass-average-developer-salary-by-2028-as-token-consumption-surges)).
