# Knos compared

What each alternative does, read from its own code, pages and chain on 2 Oct 2026; the boards' fees were read
again on 3 Oct 2026, and MergePay's and Algora's published fees again on 6 Oct 2026. The Knos row is the second deployment (`programs-v2`), at the version [capabilities.json](capabilities.json) records for each public id. Knos is on
Solana devnet and its money is test USDC; several of the others move real money today. Where another product is
ahead, this page says so.

**The neutral meter for AI agent work: neither side keeps the count.** Three comparisons follow from that. The first is with whoever keeps the count today. The second is with
the platforms and billing companies that already meter agents and move payments. The third, which most of this
page is about, is with the other ways to pay for a merged pull request. No count of capabilities is given here:
[CAPABILITIES.md](CAPABILITIES.md) has each one and its stage.

## On fee and on speed, Knos is not the best

**Knos is not the cheapest way to settle.** [MergePay](https://mergepay.fun) publishes "No platform fee": the
funder sets a relayer fee, 0.03 USD by default (its site, read 6 Oct 2026). Knos's fee from knos_pay 2.2 is 0.30%
of the amount with a minimum of 0.05, so a 100 USDC order pays 0.30 and a 5 USDC order pays 0.05 where MergePay's
funder pays 0.03: MergePay is cheaper at every size, ten times cheaper at 100, and its fee does not grow with the
order (5,000 pays 15.00 on Knos). Against a board that takes a percentage Knos is lower at every size it takes
([Algora](https://algora.io/pricing) publishes a "9% service fee", read 6 Oct 2026): the minimum makes a 5 USDC
order pay 1.00%, and from 16.67 up the fee is 0.30%. knos_pay 2.2 runs at the public program ids today. Orders
funded before the upgrade keep the rate fixed at their funding: an order funded under 2.1 keeps the fee stored then
(2.1 charged 2.5% of the first 1,000, 1% to 50,000 and 0.5% above, at least 0.40). `knos status` says which build runs.

**Knos is not the fastest.** MergePay's site says "4.5 seconds, merge to money", and its one award landed 9
seconds after the merge. Knos measured a median of 26 seconds from merge to payment, over 51 payments
([BENCH.md](BENCH.md)), on devnet.

Neither is the comparison that matters. A settlement fee can be copied at zero, and seconds stop mattering once
an invoice takes days to approve. **The comparison that matters is the count neither side keeps**: who counts the
accepted outcomes an invoice bills, whether the other side can rebuild that count, and what happens to a line the
two sides count differently. That is the next table. The count is priced apart from settlement
([MARKET.md](MARKET.md), section 3): on devnet a settle fee is test money and no revenue.

## Counting an accepted outcome

| | who counts | can the other side check the count | what fixes the terms | fee for the count |
|---|---|---|---|---|
| **A vendor that bills per accepted outcome** (per merged change, per resolution; [MARKET.md](MARKET.md), section 2) | The vendor, in its own system. | Only against the vendor's report. | The vendor's contract and its own definition of the unit. | Inside the vendor's price. |
| **The buyer's own tally** (a spreadsheet, a query over merged pull requests) | The buyer. | The supplier has to trust it, or keep a second tally and argue. | Whatever the two agreed in writing. | The buyer's time. |
| **Knos** (`knos-meter`) | A program, from tokens the forge signed for runs of a pinned workflow in the buyer's repository. The supplier's own count of the same month is recorded beside it from the supplier's runs. | Yes. Both counts are on chain; each side keeps a ledger file whose Merkle root the chain holds, and both compute the same statement or see which evaluations differ. | Named checks and allowed paths, hashed before the work. | Meter: the deployed `knos-meter` program charges 0.05 an evaluation after 10,000 free a month per owner, in test USDC. The price book proposes 100,000 free, then 0.002 USD; the program changes only through an upgrade. Acceptance: 0.30% of value released or reconciled against a signed acceptance, at least 0.05 a release, no cap ([MARKET.md](MARKET.md), the price book). Proposed prices: nobody has paid them. |

Where the others are ahead here: a vendor's count needs nothing installed and comes with a company that answers
for it. Knos's count trusts the forge's hosted runner and the pinned workflow's reading of the forge's record, runs
on devnet, and has been used by nobody but Knos.

## Platforms and billing companies

| | what it sells | whose count it is | source |
|---|---|---|---|
| **Amazon Web Services, Bedrock AgentCore** | Agent identity, policy, evaluations and payments, as priced services for agents that run on it. A custom evaluation is listed at 1.50 USD per 1,000. | The platform's, for the agents on the platform. | [pricing](https://aws.amazon.com/bedrock/agentcore/pricing/), read 5 Oct 2026 |
| **Stripe, Billing** | Subscription and usage billing at 0.7% of billing volume. | The seller's: it bills the usage its customer, the seller, reports. | [pricing](https://stripe.com/billing/pricing), read 5 Oct 2026 |
| **Knos** | Acceptance that is independent of every vendor: terms fixed before the work, a verdict from evidence the forge signed, one record for every supplier, and each side's count beside the other's. | Neither side's. A difference is a named dispute, not an invoice line. | this repository |

Where they are ahead: everywhere but independence. They have customers, companies that answer for the service,
real money, and the agents already run there. Metering agents and moving payments is what they sell, so it is not
what makes Knos different. The one thing a platform cannot be is neutral about the agents it hosts or sells, and a
billing system cannot be neutral about the seller who is its customer. Whether buyers want that neutrality enough
to pay for it is not known ([MARKET.md](MARKET.md), section 9).

## Paying for a merged pull request

| | who holds the money | what releases it | what is verified, and by whom | time from merge to paid | fee | who can change the rules | chain |
|---|---|---|---|---|---|---|---|
| **GitHub's own controls** (rulesets, required checks, required reviews, merge queue, the February and June 2026 pull request limits, Copilot code review) | Nobody. There is no money in them. | Nothing. They gate a merge, not a payment. | GitHub checks, before a merge, what the repository requires: named status checks (from a named app if set), approving reviews, code-owner review. A merge queue keeps those checks satisfied. Copilot code review can count as an approval when an admin turns that on (preview, off by default). | Not applicable. | None. | Repository and organisation admins. They set the rules and decide who may bypass them. | None. |
| **MergePay** | A contract on Arc. Anyone funds an issue from a wallet (`fund(...)`, native USDC). | A GitHub-signed token from its pinned workflow, relayed to `award()`. The award then waits for the payee to link a wallet; unlinked after 180 days, it goes back to the funders. | On chain, by the contract: GitHub's RSA signature, the issuer, expiry, `event_name`, the audience, `repository_id` and the workflow's ref. That the pull request was merged is decided by the workflow's own `if:`, not by a signed claim. There is no test or check condition. | 9 seconds on its one award (merged 07:56:18, awarded 07:56:27 UTC, 24 Sep 2026). Its site says 4.5 seconds. | No platform fee. A relayer fee the funder sets: 0.03 USDC by default, 1 USDC at most. | One key. `owner()` is the relayer's hot wallet, the key its relay service signs with (read on chain, 2 Oct 2026). It can propose a signing key, active after 3 days (funders may refund while one is pending), revoke a key at once, and transfer ownership. It cannot take escrowed money. A multisig owner is an open item on its roadmap. | Arc mainnet (chain id 5042) since 24 Sep 2026. Real USDC. |
| **Bounty boards** (Algora, Opire, BountyHub, TaskBounty) | Algora: its pages do not say the money is held before the work; the funder pays through Stripe when rewarding. Opire: nobody; the creator pays the developer through Stripe after accepting. BountyHub: the board, when the creator pays in advance. TaskBounty: not stated. | A person. Algora: the maintainer clicks Reward, or sets up auto-pay on merge. Opire and BountyHub: the bounty's creator decides whether the pull request meets the issue. TaskBounty: a run of the repository's tests and a new regression test in its own sandbox. | Nothing is signed by a third party. On Algora, Opire and BountyHub a person judges. TaskBounty runs tests in a sandbox it operates. | Algora: payout typically 1 to 3 business days after the payment. TaskBounty: 1 to 2 business days by bank, at once in USDC. Opire and BountyHub: not published. | Algora 9%. Opire 4% plus Stripe's fees. BountyHub 10%. TaskBounty 20%. | The board, through its terms, and the person paying. | None: Stripe, and PayPal on BountyHub. TaskBounty can pay out USDC on Base or Solana. |
| **Knos** (second deployment) | A Solana program (`knos-pay`). Each order's money sits in a token account of its own, at an address the program derives. A repository owner's prefunded Balance sits in a token account the program controls; only the wallet that opened it can withdraw it. | A GitHub-signed token from the workflow commit fixed at funding. The payee is paid in the transaction that verifies it. No veto after the merge. Money returns to the funder only at the deadline, after a cancellation with 7 days' notice, or from a holdback the funder set at funding. A refund needs no token. | On chain: GitHub's RSA signature (`knos-oidc`), then the order, the workflow file and its commit, the payees, the head commit and the hash of the terms fixed at funding (`knos-pay`). In the workflow, on a GitHub-hosted runner: that the pull request was merged, that every check named in the terms concluded `success` at its head commit, and that its changed files are inside the paths the terms allow. The workflow runs in the order's repository, or, after a merge, by hand in a repository of the seller's own, reading GitHub's public record. GitHub signs that this workflow ran there; it does not sign what the workflow read. | No waiting period: paid in the transaction that verifies the token. Before it come one GitHub Actions job and the relay. Measured: a median of 26 seconds from merge to payment, over 51 payments ([BENCH.md](BENCH.md)). | knos_pay 2.2, at the public ids: 0.30%, at least 0.05. On an order the funder pays it on top; the payee receives the posted amount. On a job (2.0) it comes out of the amount; the payee receives the amount minus the fee. A Plan on chain can lower the rate to 0.10%; the price book's contracts go no lower than 0.20%, and no contract exists. Nothing on a refund. An order funded under 2.1 keeps its stored fee. | One person, the founder: the upgrade multisig is 2 of 3 keys, all the founder's, with a public 48-hour delay. No outside review has been done or commissioned. A second multisig, the guardian (2 of 3 keys, also all the founder's), can approve or revoke a signing key and pause new funding for at most 7 days. It cannot add a key or move money. No instruction changes what must be true for payment after funding. | Solana devnet. Test USDC. |

## Where the others are ahead

- **MergePay** is on a mainnet and moves real USDC, since 24 Sep 2026. It charges no platform fee. Its one award
  landed 9 seconds after the merge. A new signing key waits 3 days there, and funders may take their money back
  while a key change is pending; on Knos the wait is 1 day, and a funder gets money back early only by cancelling
  with 7 days' notice. It also came before
  Knos: it verified GitHub's signature on a chain a week before Knos did so on Solana
  ([DISCLOSURE.md](DISCLOSURE.md)).
- **Bounty boards** pay ordinary money to bank accounts. Algora's pricing page says 120 countries and regions, and
  its home page says 100+ customers. Nobody on a board needs a wallet.
- **GitHub's own controls** are free, built in and already trusted by every repository that uses them. There is
  nothing to install.

## Where Knos differs

- **Checks are part of the payment condition.** The checks the funder named must have concluded `success` at the
  head commit of the merged pull request, and its changed files must stay inside the paths the funder allowed.
  Both are fixed at funding: the terms are logged on chain and their hash is stored with the job. MergePay's
  condition is the merge alone. On the boards a person judges.
- **The workflow is pinned by commit.** The program compares `job_workflow_sha`. MergePay's contract compares the
  workflow's ref, and its default ref is a tag (`@refs/tags/v1`, its `/api/config`).
- **No `pull_request_target`.** From 2 Nov 2026 GitHub blocks workflows triggered by `pull_request_target` in public
  repositories unless an admin adds a policy that allows it
  ([GitHub docs](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)).
  MergePay's contract accepts an award only from that event (`EVENT_MERGE` in `MergePay.sol`). Knos reads a
  merge from the `push` the merge makes.
- **Signing keys.** A new key needs GitHub's own signature, from a workflow at a fixed commit run in one of two
  repositories Knos owns. It then waits a day and needs the guardian's approval. Every key expires 30 days after
  it was last attested, and the guardian can revoke one. MergePay's owner proposes a key, and its keys do not
  expire.
- **The seller can produce the evidence.** After a merge, the seller can run the pinned workflow by hand in a
  repository of their own. It reads GitHub's public record of the pull request and asks GitHub to sign. A buyer who
  deletes the workflow from the repository no longer withholds payment. On MergePay the award comes from the
  workflow in the funded repository.
- **Funding by comment, or from any wallet.** A repository owner tops up a Balance from a wallet once; after that
  one comment funds an issue. Any wallet can also fund an order on an issue of any public repository, with no file
  in that repository.
- **On an order, the funder pays the fee.** The payee receives the amount that was posted. (On a job, the
  older 2.0 shape, the fee comes out of the amount.)
- **More than one payment shape.** A standing order pays a rate per accepted change. One payment can be split
  between up to four payees. A funder can hold part back for a warranty period. A payee can be an organisation.
- **Other issuers.** `knos-oidc` admits signing keys of any issuer that signs RS256 tokens, behind the same delay,
  approval, expiry and revocation, and any Solana program can read a verified token ([OIDC.md](OIDC.md)). The
  escrow pays public orders on GitHub's tokens only.
- **A count without an escrow.** Vendors that bill per merged change count their own merges
  ([MARKET.md](MARKET.md), section 1). `knos-meter` counts from GitHub's signed record, moves no customer money,
  and either side can recompute its statement from the program's logs. No vendor uses it yet.

Both records are small. MergePay's feed shows 4 bounties funded (2.25 USDC) and one award (0.47 USDC, to its own
author, on its own repository), read 2 Oct 2026. Knos's two deployments had made 15 payments on devnet when their logs were read on 3 Oct 2026 (16:04 UTC, with
`scripts/network_stats.py`); the site's Numbers page has the count now. Knos's own
account funded every one of those tasks, in test money. 3 payments have gone to another GitHub account
(`release.payments_between_unrelated_accounts` in [`bench.json`](bench.json)); every other one
went to Knos's own accounts. Tasks funded by anyone other than
Knos: 0.

## Where Knos is behind

- It is on devnet. No real money has moved.
- No security firm has audited anything. Until an outside review, Knos can change the second deployment through its multisig, after a public
  48-hour delay, and every member key of that multisig is the founder's.
- It charges a fee: 0.30%, at least 0.05, from knos_pay 2.2, which the public program runs. On an order the
  funder pays it on top of the amount; on a job it comes out of the amount. An order funded under 2.1 keeps the fee
  stored at its funding (2.5% of the first 1,000, 1% to 50,000, 0.5% above, at least 0.40). MergePay charges no platform fee, and its default relayer fee of 0.03 is lower than Knos's
  fee on any order.
- It is not the cheapest on any order. The 0.05 minimum makes a 5 USDC order pay 1.00%, and every order under
  16.67 pays more than 0.30%.
- Nothing it sells has been bought. The one offer for money, a 30-day [Pilot](PILOT.md), cannot be invoiced yet:
  there is no legal entity.
- Its speed is measured on few payments. From merge to payment took 26 seconds
  at the median, over 51 payments ([BENCH.md](BENCH.md)). MergePay has shown 9 seconds on its
  one award. On the first deployment the
  median from the funding transaction to the payment, over the 6 payments it had made by 2 Oct 2026, was 159
  seconds.
- A refund waits for the deadline, or for 7 days after a cancellation.
- It pays USDC on Solana. A passkey can be the wallet, so the payee needs no wallet app, but there is no payout to
  a bank. The boards pay bank accounts.
- No outside repository has funded a task through it.
- One person operates it ([CONTROLS.md](CONTROLS.md), [TEAM.md](TEAM.md)).

## What GitHub's own controls can and cannot do

They can block a merge:

- A ruleset can require named status checks, and name the app that must report them. It can require a number of
  approvals, a code owner's approval, and an approval from someone other than the last person to push
  ([available rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)).
- A merge queue keeps required checks satisfied on a busy branch. It is available in public repositories owned by
  an organisation, and in private ones on GitHub Enterprise Cloud
  ([merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)).
- Since [13 Feb 2026](https://github.blog/changelog/2026-02-13-new-repository-settings-for-configuring-pull-request-access/)
  a repository can turn pull requests off, or accept them from collaborators only. Since
  [17 Jun 2026](https://github.blog/changelog/2026-06-17-limit-open-pull-requests-for-users-without-write-access/)
  it can cap the open pull requests of each user without write access. Drafts do not count.
- Since [1 Sep 2026](https://github.blog/changelog/2026-09-01-copilot-code-review-can-now-approve-pull-requests/)
  Copilot code review can approve a pull request, and that approval counts toward the required number. It is a
  public preview and off by default.

None of them moves money. None makes a payment conditional on a merge, and none lets a stranger count on being
paid. The request for a bounty on issues has been open since 6 Jul 2021
([community discussion 4517](https://github.com/orgs/community/discussions/4517)). GitHub Sponsors pays a person
or an organisation, once or monthly, and is not tied to an issue or a merge
([GitHub Sponsors](https://docs.github.com/en/sponsors/getting-started-with-github-sponsors/about-github-sponsors)).

Knos uses these controls; it does not replace them. When a funder names no checks, a job's terms take the default
branch's required status checks. The free Knos check is one more status a ruleset can require.

## The buyer's real question

Do I need an escrow at all?

When better review or better CI is all a team needs, no. GitHub's required checks and the free Knos check are
enough, and the escrow adds nothing. A team that pays its own engineers already has a contract and a payroll; a
merge does not need to move money.

The escrow matters only when the person doing the work is not someone the buyer already pays: an outside
contributor, a stranger with an agent, a contractor with no contract. That person asks whether the money exists
and whether it can be taken back after the work is accepted. The buyer asks what exactly is being bought. The
escrow answers the first: the money is committed before the work and cannot be vetoed after the merge. The terms
answer the second: these checks, these paths, this deadline, fixed when the money went in.

## Other programs that verify GitHub's signature on a chain

On Solana we found none. Searches of crates.io on 2 Oct 2026 for `solana rs256` and `zklogin solana` returned no
crate, and web searches found no program that verifies an RS256, JWT or OIDC token on chain.

Elsewhere: MergePay (above) on Arc. `github-zktls` checks a Sigstore attestation of a GitHub Actions run in zero
knowledge on Base Sepolia; its README carries a notice dated 24 Aug 2026 that the construction "does not provide
the security it claims" ([repository](https://github.com/amiller/github-zktls)). Juno verifies GitHub Actions tokens
inside an Internet Computer canister, to authorise deployments, not payments
([write-up, 23 Feb 2026](https://daviddalbusco.com/blog/building-a-github-actions-integration-with-oidc-authentication)).

## Sources

All read on 2 Oct 2026. The fees of Algora, Opire, BountyHub and TaskBounty were read again on 3 Oct 2026, and
MergePay's site and Algora's pricing page again on 6 Oct 2026.

- MergePay: [repository](https://github.com/codeswithroh/mergepay) (`contracts/src/MergePay.sol`,
  `.github/workflows/award.yml`, README; first commit 23 Sep 2026, "Deploy to Arc mainnet" 24 Sep 2026);
  [site](https://mergepay.fun); its live [feed](https://mergepay.codeswithroh.workers.dev/api/feed) and
  [config](https://mergepay.codeswithroh.workers.dev/api/config); `owner()` read from `https://rpc.mainnet.arc.io`
  for contract `0xcff79B144833b36ca53b310C1Ad7854AF9Ff9EeD`.
- Algora: [pricing](https://algora.io/pricing), [home page](https://algora.io),
  [payments](https://algora.io/docs/payments), [bounty workflow](https://docs.algora.io/bounties/workflow). On
  2 Oct 2026 the pricing, payments and workflow pages loaded for us through one route and returned "page not found"
  through two others; the home page loaded every time and now leads with hiring. Treat Algora's figures as its
  last published ones.
- Opire: [terms of service](https://opire.dev/terms-of-service), last updated 24 Aug 2024.
- BountyHub: [bountyhub.dev](https://www.bountyhub.dev/), [pricing](https://www.bountyhub.dev/en/pricing).
- TaskBounty: [for agents](https://www.task-bounty.com/for-agents).
- Knos: this repository; the second deployment's addresses are in `programs-v2/program_ids.json`.
