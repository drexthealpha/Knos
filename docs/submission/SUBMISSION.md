# Knos: the submission

**Knos is the neutral count and settlement for software work priced per outcome: terms fixed before the work, a signed CI run attests they were met, a Solana program counts it or pays it.**

- Site: [drexthealpha.github.io/Knos](https://drexthealpha.github.io/Knos/)
- Code: [github.com/drexthealpha/Knos](https://github.com/drexthealpha/Knos) (MIT)
- Network: Solana devnet. The money is test USDC. Track: Solana.

What is in this folder:

| file | what it is |
|---|---|
| this file | the text for each field of the form, each under a thousand characters, and the checklist for the day of submission |
| [pitch_script.md](pitch_script.md) | the pitch video, in six beats: the buyer and the problem first, how it works last |
| [demo_script.md](demo_script.md) | the demo video: six shots with timestamps, and for each the program ids it can be recorded on |
| [CRITERIA.md](CRITERIA.md) | how the submission answers each factor Colosseum lists and each criterion in the rules, one paragraph each |
| [../PILOT.md](../PILOT.md) | the one offer for money: a 30-day pilot for one buyer and its suppliers, and what blocks it |
| [../TEAM.md](../TEAM.md) | who builds Knos today, and the three roles the plan needs first, none hired |
| [../DISCLOSURE.md](../DISCLOSURE.md) | what existed before the competition and what was built during it, by date; and what does not exist |
| [DEPENDENCY.md](DEPENDENCY.md) | the plan for the dependency on one personal GitHub account |
| [INTERVIEWS.md](INTERVIEWS.md) | the kit for buyer conversations: whom to ask, what to ask, and a letter of intent to offer |
| [weekly_update.md](weekly_update.md) | the one-minute weekly update |
| [../CAPABILITIES.md](../CAPABILITIES.md) | the index of evidence: every capability, the stage it has reached (implemented, tested locally, deployed, exercised on devnet, reproduced by someone else) and the file that shows it |

A number that only the release run can measure is a slot, `[[stat: name]]`; `python scripts/bench_docs.py --slots`
lists the ones still open. Three fields state facts about the founder that nothing in the repository can back;
each says so, and the founder confirms it before pasting.

## Checklist for the day of submission

- [ ] **Confirm the Solana ecosystem track is selected in the form.** A submission with no track selected is not
      in that track.
- [ ] Both videos open for someone who is not signed in, and neither is longer than three minutes.
- [ ] The repository link opens for someone who is not signed in.
- [ ] `python scripts/bench_docs.py --slots` prints no open slot, and `python scripts/claims_check.py` passes.
- [ ] `python scripts/capabilities.py check --rpc` passes, and every field and every shot says of a capability
      only the stage `docs/capabilities.json` gives it on the day, on the program ids `web/upgrades.json` says are
      live. No field states a count of capabilities: [../CAPABILITIES.md](../CAPABILITIES.md) is the count.
- [ ] `web/upgrades.json` has been read on the day. If a proposal has not executed, the fields below are already
      true as written; the demo's shots follow the "before" column of its table.
- [ ] The three fields marked "the founder confirms this" have been read and are true on the day.
- [ ] The "who said yes" beat of the pitch and shot F of the demo have been read against the chain on the day: if an outside account has
      funded an order since this was written, the count is updated from `docs/facts.json`; if a conversation has
      happened, it is added only with the other party's agreement to be named.
- [ ] Every team member is registered on colosseum.com. Today the team is one person.

## whatBuilding

Knos lets a buyer close a supplier's invoice with evidence both sides can check. Before the work, the buyer fixes what is bought and what decides
it is done: the checks that must pass and the paths that may change, hashed into the order at funding. A workflow
at a pinned commit reads the forge's record, the forge signs that run, and a Solana program verifies the signature
on chain. It then counts the outcome, with no money on chain, or pays the supplier in full, the buyer paying the
fee on top. Buyer and supplier each compute the month's statement from their own ledger; a difference shows as a
named dispute. Live on the public program ids on devnet: funding by comment, payment on a merge, refunds, the
single count. Work orders, the batched count, passkey funding and one single-use rule for every token were
rehearsed on staging ids, not the public ones, and go live when their approved upgrades execute (web/upgrades.json). docs/CAPABILITIES.md has each
stage. Test USDC only.

## whyNow

Coding agents open pull requests in very large numbers, and a description is not evidence. In 826 repositories, the
first agent pull request that said tests pass had a failed check of some kind in 147 (17.8%), and a failed test or
build in 80 (9.7%). Of 241 merged ones that said so, 30 had a failed check at the head commit (12.4%). Billing by outcome
has begun, and the seller keeps the count: on 14 Sep 2026 one vendor started billing per merged changeset, another
advertises that customers pay only for merged pull requests, and support agents are sold per resolution that the
vendor itself counts. The person who approves that invoice has no count of their own. The forge already records
each result and signs statements about a CI run, so its signature is a count that neither side owns. On Solana,
checking that RSA signature takes two transactions.

## repoContext

The hackathon began on 14 Sep 2026. The public repository's history starts on 1 Sep 2026. Of its 209 commits up to
Knos 0.3.11, 83 predate the hackathon: Knos 0.1 (1 to 7 Sep 2026), more work on it until 12 Sep, and daily
automatic commits. Knos 0.1 was a different product, shared memory for coding agents built on Sibyl. By
`git blame` at the 0.3.11 commit, 1.1% of the lines are older than the hackathon: the changelog entries for
Knos 0.1, the licence, package metadata and scaffolding. The other 98.9% were last changed between 30 Sep and
2 Oct 2026, and every release since was built after that. Work on two experiments that never shipped began on
13 Sep; none of their code is in the repository. The commits were written with coding agents; I review and commit
each one. docs/DISCLOSURE.md has the history by date, what came from elsewhere, what does not exist, and the
commands that reproduce every count.

## marketValidation

None yet. No buyer or supplier has been interviewed, there is no letter of intent, no pilot, and nobody has
paid. What exists is a measurement, an offer and a plan to ask. The measurement: of 241 merged agent
pull requests whose description said tests pass, 30 had a failed check at the head commit (12.4%), so a vendor
that bills per merge bills for those. The buyer is whoever must authorise a supplier's invoice and defend it
afterwards; the second user is the supplier, who needs terms that cannot change after the work. A maintainer's
bounty is the smallest case and not the market: all open bounties on every board came to 64,291 USD on
2 Oct 2026. The offer is a 30-day pilot (docs/PILOT.md): reconcile one buyer's accepted work from more than one
supplier, name every mismatch with billing, and deliver a statement both sides verify. The plan to ask is
INTERVIEWS.md. The free check is the distribution; software is sold first (docs/MARKET.md).

## traction

No traction is claimed beyond what the chain counts. Knos's own account funded every task paid so far, in test
USDC. By 3 Oct 2026 the two deployments had made 15 payments on devnet: 3 to one outside contributor, for bounties
Knos funded itself, and the rest to Knos's own accounts. When the release ran, 43 tasks had been
paid on the second deployment. Across both deployments, 0 paid tasks were funded by someone other than Knos with
their own tokens, by 0 funders, of whom 0 funded again. From merge to paid took 25 seconds at the median, over 39
payments. 1,905 tests pass. Buyers: none. Interviews: none. Letters of intent: none. Pilots: none, offered or
sold. Revenue: none; test USDC is not money. Outside reproductions: none known. The site's Numbers page
shows today's counts, read from the programs' own logs, with Knos's own accounts kept apart from everyone else's.

## competition

Vendors that bill per accepted outcome count their own outcomes; none offers a count the buyer can check. GitHub's
own controls (required checks, rulesets, the merge queue) gate a merge and move no money. Bounty boards (Algora,
Opire, BountyHub, TaskBounty) pay on a person's decision, or on a test run in the board's own sandbox. MergePay
verified GitHub's signature on an EVM chain before Knos did on Solana; it is on a mainnet with real USDC, charges
no platform fee, and is ahead there. Its payment condition is the merge alone. What Knos adds: named checks and
allowed paths fixed at funding; a seller who can settle without the buyer; a black-box check that refused all 63
cheating pull requests of our benchmark, 56 of which passed plain CI; a verifier for any RS256 issuer; and a count
with no escrow, where the seller's count sits beside the buyer's. Where Knos is behind: devnet only, no outside
security review, no payout to a bank, one person. docs/COMPARE.md has every source.

## monetization

The price book (docs/MARKET.md). Check: free. Meter: 10,000 evaluations a month free per organisation, then 0.05
USD, or 0.02 on a committed-volume plan. Control: 25,000 USD a year entry, 80,000 for the organisation tier.
Settle, paid by the funder on top: 2.5% of the first 1,000, 1% from 1,000 to 50,000, 0.5% above, minimum 0.40.
The effective fee is shown before funding, and Knos is not cheaper on a small order: a 5 USDC order pays 8%.
Pilot: 2,500 USD for one buyer and its suppliers for 30 days. Nobody has bought any of it. On devnet, Meter, Control and the Pilot are software and can be invoiced off chain; a settle
fee is test money, so settlement revenue is zero. There is no legal entity to invoice from yet. The first
milestone is 40 organisations at the entry price. The code is MIT, so a fork can charge nothing; what it would
lack must be earned and is measured: supplier reuse across unrelated buyers, repeat buyer spend, onboarding
time. Each is zero today. No token.

## teamCommitment

One person, full time, under the handle drexthealpha, which is a pseudonym. I work with coding agents every day,
and this repository was built with them; I review and commit every change. I built what is here because my own agents
told me the tests passed when they had not. What I have not done: sold to an engineering or finance leader, run a
security review, or kept a service running for a customer. docs/TEAM.md names the three roles the plan needs
first and what each would own in the first ninety days: someone who has sold to engineering or finance leaders, a
security lead to run an outside review, and agent-vendor partnerships. None is hired, approached or committed.
The pinned workflows and the relay live in my personal account; moving them to an organisation is a plan. What I am asking for: a place in the accelerator, introductions to buyers and vendors of
outcome-priced work, and an outside security review.

## externalContributors

One outside account, jaystay-bot, wrote three pull requests: #32 (`knos_bounties` says what each bounty is about),
#33 (a repository's own record in the Agent PR Index, on the site) and #34 (a Ruby runner for the judge). Each
answers a bounty Knos funded on its own repository through the first deployment on 2 Oct 2026, in test USDC: issues
#29, #30 and #31. All three were merged on 3 Oct 2026 and paid by the first deployment's escrow. Their code has been
in the package since 0.3.12, in commits under that account's name. These payments show the path working between two
accounts. They do not show demand: Knos funded the bounties.

## legalEntity

*The founder confirms this before pasting; nothing in the repository can back it.*

None. No company has been formed for Knos. It is one person's work, published under the MIT licence.

## investmentReceived

*The founder confirms this before pasting; nothing in the repository can back it.*

None.

## liveToken

*The founder confirms this before pasting.*

No. Knos has no token of its own. It pays in the token a funder chooses, and the one it is built for is USDC. On
devnet a faucet inside the program mints test USDC, which has no value.

## liveProductLink

https://drexthealpha.github.io/Knos/ is the product. Three buttons under the first form show a true claim, a false
claim and a paid task in one click, with no wallet. From there: put the workflow file in a repository, fund an
issue with one comment, and see every payment the programs have made. The code is at
https://github.com/drexthealpha/Knos and the package at https://pypi.org/project/knos/. Everything is on Solana
devnet, and the money is test USDC.

## chains

Solana, on devnet. Track: Solana.

## chainUsage

Four programs on Solana devnet, with no framework. `knos-oidc`
(`FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W`) verifies an RS256 OpenID Connect token on chain, in Montgomery
form, in two transactions for GitHub's keys, because one transaction's compute budget cannot hold the arithmetic.
`knos-pay` (`5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k`) is the escrow: it reads the verified claims, checks
them against the work order, and moves SPL Token or Token-2022 tokens from the order's own account to the payees,
the relayer's tip and the fee account, or back to the funder at the deadline. `knos-meter` counts signed
evaluations and takes a fee from prepaid credits. `knos-passkey` is a wallet whose key is a WebAuthn passkey,
checked through Solana's secp256r1 instruction. Every account is a PDA. Squads holds the upgrade authority, with a
48-hour time lock, and the guardian role. The site builds and reads transactions in the browser; there is no
server.
