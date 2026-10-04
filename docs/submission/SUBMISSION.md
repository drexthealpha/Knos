# Knos: the submission

**Knos pays for software work on signed acceptance: terms fixed before the work, a GitHub-signed run attests they were met, a Solana program settles.**

- Site: [drexthealpha.github.io/Knos](https://drexthealpha.github.io/Knos/)
- Code: [github.com/drexthealpha/Knos](https://github.com/drexthealpha/Knos) (MIT)
- Network: Solana devnet. The money is test USDC. Track: Solana.

The text for each field of the form, each under a thousand characters. A number that only the release run can measure
is a slot, `[[stat: name]]`; `python scripts/bench_docs.py --slots` lists the ones still open. Three fields state
facts about the founder that nothing in the repository can back; each says so, and the founder confirms it before
pasting. The scripts for the two videos are [pitch_script.md](pitch_script.md) and [demo_script.md](demo_script.md);
the weekly update is [weekly_update.md](weekly_update.md).

## whatBuilding

Knos pays for software work on signed acceptance. A buyer funds a work order with one comment and names the checks
that must pass: `/knos fund 20 checks: test`. The terms are fixed on chain before the work. When a pull request that
meets them is merged, a workflow at a pinned commit reads GitHub's record and asks GitHub to sign that run. A Solana
program verifies GitHub's RSA signature on chain and pays the author the full amount; the buyer pays the fee on top.
If the buyer's workflow is gone after the merge, the seller runs the pinned workflow in a repository of his own and
is still paid. A second program counts accepted outcomes for vendors who bill per result, with no escrow. The
verifier is a program of its own: any Solana program can require a fact GitHub signed. It runs on devnet, in test
USDC. Until an outside review, I can change the programs only through a multisig with a public 48-hour delay.

## whyNow

Coding agents open pull requests in very large numbers, and a description is not evidence. In 826 repositories, the
first agent pull request that said tests pass had a failed check of some kind in 147 (17.8%), and a failed test or
build in 80 (9.7%). Billing by outcome has begun, and the seller keeps the count: on 14 Sep 2026 one vendor started
billing per merged changeset, another advertises that customers pay only for merged pull requests, and support
agents are sold per resolution that the vendor itself counts. Buyers have no count of their own. GitHub already
records each result and signs statements about a workflow run, so its signature is a count that neither side owns.
On Solana, checking that RSA signature takes two transactions.

## repoContext

The hackathon began on 14 Sep 2026. The public repository's history starts on 1 Sep 2026. Of its 209 commits up to
Knos 0.3.11, 83 predate the hackathon: Knos 0.1 (1 to 7 Sep 2026), more work on it until 12 Sep, and daily
automatic commits. Knos 0.1 was shared memory for coding agents built on Sibyl, and it won the Sibyl Labs
hackathon. By `git blame` at the 0.3.11 commit, 1.1% of the lines are older than the hackathon: the changelog
entries for Knos 0.1, the licence, package metadata and scaffolding. The other 98.9% were last changed between
30 Sep and 2 Oct 2026, and 0.3.12 and 0.3.13 were built after that. Work on two experiments that never shipped
began on 13 Sep; none of their code is in the repository. The commits were written with coding agents; I review and
commit each one. docs/DISCLOSURE.md has the lists, what came from elsewhere, and the commands that reproduce every
count.

## marketValidation

No interviews and no outside funder yet. This is what has been measured. The problem: of 241 merged agent pull
requests whose description said tests pass, 30 had a failed check at the head commit (12.4%). The buyers with
budget and urgency are vendors that bill per accepted change and the customers who audit them; the count is the
vendor's own today (docs/MARKET.md, section 1). The market for bounties on issues is small, and we say so: 64,291
USD was open across every board on 2 Oct 2026. One funnel decides whether this is a business: repositories that
install the check, those that fund a work order, orders paid, funders who fund again. The last stage cannot be read
on devnet, where the money is free. The go-to-market that needs no outreach is the free check and the public
record: every funded order is listed for agents, and every payment adds to a public rank.

## traction

No traction is claimed beyond these counts. Knos's own account funded every task paid so far, in test USDC. By
3 Oct 2026 the two deployments had made 15 payments on devnet: 3 to an outside contributor, for bounties Knos funded
itself, and the rest to Knos's own accounts. Tasks paid on the second deployment when the release ran: 40.
Across both deployments, 0 paid tasks were
funded by someone other than Knos with their own tokens, by 0 funders, of whom
0 funded again. From
merge to paid took 24 seconds at the median, over 36
payments. The site's Numbers page shows today's counts, read from the programs' own logs, with Knos's own accounts
kept apart from everyone else's.

## competition

GitHub's own controls (required checks, rulesets, the merge queue) gate a merge and move no money. Bounty boards
(Algora, Opire, BountyHub, TaskBounty) pay on a person's decision, or on a test run in the board's own sandbox.
MergePay verified GitHub's signature on an EVM chain before Knos did on Solana. It has been on a mainnet with real
USDC since 24 Sep 2026 and charges no platform fee, and it is ahead there. Its payment condition is the merge
alone. What Knos adds: the checks a funder names are part of the condition and are fixed at funding; after a merge
in a public repository the seller can settle without the buyer's workflow; a warranty and an arbiter can be set at
funding; the verifier takes any RS256 issuer; and a count without escrow for vendors who bill per result. Where
Knos is behind: devnet only, no outside security review, a 2.5% fee, no payout to a bank. docs/COMPARE.md has every
source.

## monetization

The price book (docs/MARKET.md). Check: free. Settle: the funder pays the amount plus 2.5%, at least 0.40 and at
most 25 USDC, and the payee receives the posted amount; 0.5% to 1.5% under a contract. Meter: 0.05 per billable
evaluation, 0.02 at volume, the first 10,000 a month free, from prepaid credits. Control (policy, budgets, private
repositories, statements, exports, screening): 25,000 USD a year, or 80,000 with a volume commitment. Nobody has
paid for any of it: the money on devnet is test money. Our own three scenarios add up to 121,125 USD of fees a
year. What 1 billion USD a year would require is printed beside that as arithmetic, not as a forecast. The code is
MIT, so a fork can set every fee to zero. It starts with no record, and has to run its own relay and keep its own
keys attested.

## teamCommitment

One person, full time, under the handle drexthealpha, which is a pseudonym. I work with coding agents every day,
and this repository was built with them; I review and commit every change. Before this hackathon I built Knos 0.1
(1 to 7 Sep 2026), shared memory for coding agents built on Sibyl, and it won the Sibyl Labs hackathon. I built what
is here because my own agents told me the tests passed when they had not. What I am asking for: a place in the
accelerator, design partners among vendors that bill per merge, and an outside security review of the programs, so
that they can go to mainnet.

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
