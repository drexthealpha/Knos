# Knos: the submission

**The neutral meter for AI agent work: neither side keeps the count.**

Of 241 merged agent pull requests claiming passing tests, 9 failed a test, build, lint or type check.

Of first agent pull requests that claimed passing tests, 17.8% had a failed check (147 of 826 repositories).

- Story: [../STORY.md](../STORY.md), the number, one task in seven steps with its evidence, and what the project needs next
- This release on one page: [../MANIFEST.md](../MANIFEST.md), the source, the build live at each public program id, every capability's stage, the limits
- Site: [drexthealpha.github.io/Knos](https://drexthealpha.github.io/Knos/)
- Code, at the release tag: [`github.com/drexthealpha/Knos/tree/v0.3.26`](https://github.com/drexthealpha/Knos/tree/v0.3.26) (MIT)
- A judge's one page, at the same tag: [docs/JUDGES.md](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/JUDGES.md)
- Network: Solana devnet. The money is test USDC. Entered for: the Solana ecosystem track and the Public Good Prize.

What is in this folder:

| file | what it is |
|---|---|
| this file | the text for each field of the form, each under its limit of a thousand characters, and the checklist for the day of submission |
| [../STORY.md](../STORY.md) | the one page: the number, the seven steps with the evidence under each, and the ask |
| [../MANIFEST.md](../MANIFEST.md) | the release manifest, written by a script: source, the build live at each public program id, pending proposals, every capability's stage with its evidence, the outstanding limits |
| [NUMBERS.md](NUMBERS.md) | the nine numbers about outside use, each with today's value, zeros included |
| [`pitch_script_120.md`](pitch_script_120.md) | the presentation for the form, under two minutes: the finding, one transaction, the founder's record, the business, the limits in one sentence, the ask; `scripts/video/render.py --script` renders it |
| [pitch_script.md](pitch_script.md) | the longer presentation, under three minutes: the Agent PR Index finding, one transaction in seven steps, the evidence, the founder's record, the business, the limits in one sentence, and the ask |
| [demo_script.md](demo_script.md) | the technical demonstration, three minutes in seven beats, the refusal first, each captioned with the program ids it ran on |
| [CRITERIA.md](CRITERIA.md) | one paragraph for each factor Colosseum lists, founder and market fit included, and for each criterion in the rules; then six evidence targets, as targets |
| [../PILOT.md](../PILOT.md) | the one offer for money: a 30-day pilot for one buyer and its suppliers, and what blocks it |
| [../TEAM.md](../TEAM.md) | who builds Knos today, and the three roles the plan needs first, none hired |
| [../GOVERNANCE.md](../GOVERNANCE.md) | who can change what today, and three plans: an outside key holder, a two-owner organisation, the verifier frozen after an outside review |
| [../DISCLOSURE.md](../DISCLOSURE.md) | what existed before the competition and what was built during it, by date; and what does not exist |
| [DEPENDENCY.md](DEPENDENCY.md) | the plan for the dependency on one personal GitHub account |
| [INTERVIEWS.md](INTERVIEWS.md) | the kit for buyer conversations: whom to ask, what to ask, the tally with every no counted, and a letter of intent to offer |
| [weekly_update.md](weekly_update.md) | the one-minute weekly update |
| [../CAPABILITIES.md](../CAPABILITIES.md) | the index of evidence: every capability, the stage it has reached (implemented, tested locally, deployed, exercised on devnet, reproduced by someone else) and the file that shows it |

What each release changes is in [../../CHANGELOG.md](../../CHANGELOG.md), and each capability stands at the stage
[../MANIFEST.md](../MANIFEST.md) gives it and no higher. This release changes no program. The demonstration is one
independently witnessed transaction ([demo_script.md](demo_script.md)); a judge's one page is
[../JUDGES.md](../JUDGES.md), with the six criteria and the seven factors Colosseum's page lists.

A number that only the release run can measure is a slot, `[[stat: name]]`; `python scripts/bench_docs.py --slots`
lists the ones still open. Every field is under a thousand characters, and `tests/test_business_docs.py` counts them. Three fields state facts about the founder that nothing in the repository can back;
each says so, and the founder confirms it before pasting.

## Which link goes in which field

A copy of the repository's front page that a reader or a fetcher cached earlier can show an older release, with
another product's description. So every link given to a judge is one whose content never changes or that no cache
holds: the release tag, a file at that tag, or the site. Never the bare repository address.

| Field of the form | What goes in it |
|---|---|
| GitHub repository | [`github.com/drexthealpha/Knos/tree/v0.3.26`](https://github.com/drexthealpha/Knos/tree/v0.3.26), the release tag |
| Presentation video | the founder's YouTube, Loom or Vimeo upload of the render of [`pitch_script_120.md`](pitch_script_120.md) |
| Product-demo video | the founder's YouTube, Loom or Vimeo upload of the render of [demo_script.md](demo_script.md) |
| `liveProductLink` | the text of that field below: the site first, then the tag, the judges' page at the tag, the package |
| any other place the form takes a link | the judges' page at the tag: [`docs/JUDGES.md` at `v0.3.26`](https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/JUDGES.md) |

The form takes video links from YouTube, Loom or Vimeo only (the form's own help text, read signed in on 9 Oct 2026),
so a release's attached video is not a link it accepts. [CHECKLIST.md](CHECKLIST.md) lists what only the founder can
fill in.

## Checklist for the day of submission

- [ ] **Confirm the Solana ecosystem track is selected in the form.** A submission with no track selected is not
      in that track. Its prizes are awarded in addition to the overall awards
      ([colosseum.com/worldsfair](https://colosseum.com/worldsfair), read 8 Oct 2026).
- [ ] **Confirm the Public Good Prize is entered in the form,** on the case that the verifier is a
      separate MIT program any Solana program can call ([../COMPOSE.md](../COMPOSE.md)) and the conformance kit lets
      anyone check an implementation. If the form has no place to enter it, the founder asks Colosseum before the
      deadline how to be considered, and says so here.
- [ ] **The repository link in the form is the release tag, not the moving branch:**
      [`github.com/drexthealpha/Knos/tree/v0.3.26`](https://github.com/drexthealpha/Knos/tree/v0.3.26), the tag of
      the version `pyproject.toml` names, which `release.yml` builds from, and beside it the site, [drexthealpha.github.io/Knos](https://drexthealpha.github.io/Knos/). Open both
      signed out.
- [ ] **What predates the window is stated in the form** (`repoContext` below). The window is 14 Sep to
      12 Oct 2026 ([colosseum.com/worldsfair](https://colosseum.com/worldsfair)). Before it: Knos 0.1, a different
      product (shared memory for coding agents on Sibyl Labs' memory engine), released 1 to 7 Sep 2026 and worked on
      until 12 Sep; it took first place at the Sibyl Labs hackathon (first of 92 teams, 126.9 points), whose build window was 1 to 10 Sep
      ([leaderboard](https://hack.sibyllabs.org/leaderboard)). That result is the founder's track record, not part
      of this entry. Its memory engine is used by Knos today (`knos.proof.history`); 0.1% of the lines at 0.3.25
      date from before the window ([../DISCLOSURE.md](../DISCLOSURE.md)).
- [ ] **The founder enters the disclosure in the submission form itself, not only in this repository.**
      Colosseum's page asks teams to "disclose all relevant past development work in the submission form"
      ([colosseum.com/hackathon](https://colosseum.com/hackathon)). The field `repoContext` below is that text: the
      work before the window (Knos 0.1, a different product), the 0.1% of lines that survive from it, and that the
      commits were written with coding agents. Nothing in this repository can do this step: the founder pastes it
      into the form and ticks this box.
- [ ] Both videos open for someone who is not signed in. The presentation is the render of
      [`pitch_script_120.md`](pitch_script_120.md) and ends before two minutes; the demo is no longer than three.
- [ ] `python scripts/release_manifest.py --check` passes, and [../MANIFEST.md](../MANIFEST.md) has been read on the day:
      no field and no shot says a build is live that the manifest does not.
- [ ] Every shot that is a replay, or is played faster than it happened, carries its caption for its whole length.
- [ ] Every step of the demo is captioned with the program ids it ran on: staging program ids until
      `web/upgrades.json` shows the pending upgrade executed and a step has run on the public ones.
- [ ] Every slot of [NUMBERS.md](NUMBERS.md) holds the number its source gives on the day, zeros included.
- [ ] The repository link opens for someone who is not signed in.
- [ ] `python scripts/bench_docs.py --slots` prints no open slot, and `python scripts/claims_check.py` passes.
- [ ] `python scripts/capabilities.py check --rpc` passes, and every field and every shot says of a capability
      only the stage `docs/capabilities.json` gives it on the day, on the program ids `web/upgrades.json` says are
      live. No field states a count of capabilities: [../CAPABILITIES.md](../CAPABILITIES.md) is the count.
- [ ] `web/upgrades.json` has been read on the day. A step of the demo shows only what ran, on the program ids
      its caption names; a step whose capability has run nowhere is cut, not staged.
- [ ] The three fields marked "the founder confirms this" have been read and are true on the day.
- [ ] Beat seven of the pitch and the last beat of the demo have been read against the chain on the day: if an outside account has
      funded an order since this was written, the count is updated from `docs/facts.json`; if a conversation has
      happened, it is added only with the other party's agreement to be named.
- [ ] Every team member is registered on colosseum.com. Today the team is one person.
- [ ] Each entry's needs, Grand Prize, Solana track and Public Good, are ticked in [CHECKLIST.md](CHECKLIST.md).

## Built in the window, and before it

The window is 14 Sep to 12 Oct 2026. Each date below is the day git first records the path
(`git log --diff-filter=A --format=%ad --date=short -- <path>`).

| Built in the window | First recorded |
| --- | --- |
| The first escrow, which checks GitHub's OIDC signature on chain (`programs/`) | 1 Oct 2026 |
| The Agent PR Index and the site (`scripts/agent_pr_index.py`, `web/`) | 1 Oct 2026 |
| What Knos remembers, kept in the Sibyl engine (`src/knos/proof/history.py`) | 1 Oct 2026 |
| knos_oidc and knos_pay, the second deployment (`programs-v2/`) | 3 Oct 2026 |
| The merged pull request count (`scripts/backtest.py`) and the workflow flow (`src/knos/flow.py`) | 3 Oct 2026 |
| The meter: knos_meter, the ledger (`src/knos/ledger.py`), knos_passkey | 4 Oct 2026 |
| The statement both sides compute (`src/knos/statement.py`) | 6 Oct 2026 |

Before the window: Knos 0.1.0 to 0.1.8 (tags `v0.1.0` to `v0.1.8`, 1 to 7 Sep 2026), a different product: shared
memory for coding agents on one machine. It ran on Sibyl Labs' memory engine, `sibyl-memory-client`, a dependency
since 0.1.0. Knos reuses that engine for what it remembers; the engine is not new work, and neither is the
founder's record with it. One complete transaction is told in [TRANSACTION.md](TRANSACTION.md).

## whatBuilding

The neutral meter for AI agent work: neither side keeps the count. When agent work is sold per outcome, the
seller counts the outcomes and the buyer pays on that count. With Knos the buyer fixes, before the work, the
budget and what decides that it is done: the checks that must pass and the paths that may change, hashed at
funding. A workflow at a pinned commit reads the forge's record, the forge signs that run, and a Solana program
verifies the signature. The outcome is then counted, with no money on chain, or paid in test USDC. Each side
keeps its own ledger and computes the same statement; a difference is a named dispute, not an invoice line. A
buyer starts with an invoice it already has: pasted on the site, it is set against the neutral count, every
mismatch named. Devnet is the test mode: the record verifies from GitHub's signatures with no chain. docs/CAPABILITIES.md has the stage
of every capability, and web/upgrades.json has which builds are live on the public program ids.

## whyNow

Of 241 merged agent pull requests that claimed passing tests, 9 had a failed test, build, lint or type-check job at
the head commit (3.7%, 95% interval 2.0% to 6.9%), and 19 a failed check of any kind (7.9%); the scan recorded 16 and 30;
11 of the 30 were excluded on a second reading ([index_review.json](../index_review.json)). Of first such pull
requests, 17.8% had one: 147 of 826 repositories, and in 80 of them (9.7%) it was a test or a build. Billing by outcome has begun, and the seller keeps the count: on 14 Sep 2026 one vendor started
billing per merged changeset, another advertises that customers pay only for merged pull requests, and support
agents are sold per resolution that the vendor itself counts. The person who approves that invoice has no count
of their own. The forge already records each result and signs statements about a CI run, so its signature is a
count that neither side owns. On Solana, checking that RSA signature takes two transactions.

## repoContext

The hackathon began on 14 Sep 2026. The public repository's history starts on 1 Sep 2026. Of its 229 commits up to
Knos 0.3.25, 83 predate the hackathon: Knos 0.1 (1 to 7 Sep 2026), more work on it until 12 Sep, and daily
automatic commits. Knos 0.1 was a different product, shared memory for coding agents built on Sibyl; it took
first place at the Sibyl Labs hackathon. By
`git blame` at the 0.3.25 commit, 0.1% of the lines (412 of 428,405) are older than the hackathon: the changelog
entries for Knos 0.1, the licence, package metadata and scaffolding. Every other line was last changed during it. Work on two experiments that never shipped began on
13 Sep; none of their code is in the repository. The commits were written with coding agents; I review and commit
each one. docs/DISCLOSURE.md has the history by date, what came from elsewhere, what does not exist, and the
commands that reproduce every count.

## marketValidation

None yet. No buyer or supplier has been interviewed, there is no letter of intent, no pilot, no shadow count,
and nobody has paid. NUMBERS.md prints each of those as a zero. What exists is a measurement, an offer and a
plan to ask. The measurement: of 241 merged agent pull requests whose description said tests pass, 9 had a
failed test, build, lint or type-check job at the head commit, each read again by hand. The buyer is whoever must approve a supplier's invoice and defend it
afterwards. An organisation is qualified when it has measurable spend on work bought per outcome, acceptance
criteria it can write down, a buyer with authority, and a problem worth another system; nobody has counted how
many there are. A maintainer's bounty is the smallest case and not the market: all open bounties on every board
came to 64,291 USD on 2 Oct 2026. The offer starts free, in shadow mode, and becomes a 30-day pilot
(docs/PILOT.md). The plan to ask is INTERVIEWS.md.

## traction

No traction is claimed beyond what the chain counts. Knos's own account funded every task paid so far, in test
USDC. By 3 Oct 2026 the two deployments had made 15 payments on devnet: 3 to one outside contributor, for bounties
Knos funded itself, and the rest to Knos's own accounts. When the release ran, 315 tasks had been
paid on the second deployment. Across both deployments, 0 paid tasks were funded by someone other than Knos with
their own tokens, by 0 funders, of whom 0 funded again. From merge to paid took 26 seconds at the median, over 51
payments. 4,323 tests pass. Buyers: none. Interviews: none. Letters of intent: none. Pilots: none, offered or
sold. Revenue: none; test USDC is not money. Outside reproductions: none known. NUMBERS.md has each of these with its
source; the site's Numbers page shows today's counts with Knos's own accounts kept apart.

## competition

Counting what an agent does and moving money for it are already sold: cloud platforms sell agent identity,
policy, evaluation and payments, and billing companies sell usage billing. So metering agents and moving
payments is not our difference. Each of them counts for one side: the platform for its own agents, the billing
system for the seller. Knos's difference is acceptance that is independent of every vendor, disagreements
included. Vendors that bill per accepted outcome count their own. GitHub's own controls gate a merge and move no
money. Bounty boards pay on a person's decision. MergePay verified GitHub's signature on an EVM chain before
Knos did on Solana; it is on a mainnet with real USDC, charges no platform fee, and is ahead there. Where Knos is
behind: devnet only, no outside security review, no payout to a bank, one person, and nobody outside has used
it. docs/COMPARE.md has every source.

## monetization

One fee, on value released against a signed acceptance (docs/MARKET.md). Check: free, forever. Meter: a monthly
free allowance per organisation, then a fraction of a cent an evaluation. Acceptance: thirty cents per hundred
dollars released or reconciled against a signed acceptance, less by contract at volume, no cap; the funder pays
it on top. On chain: 0.30%, minimum 0.05, from knos_pay 2.2 (before that upgrade: the 0.3.14 fee, minimum 0.40;
earlier orders keep their rate). It replaces the earlier settle and verify fees; connecting a supplier costs
nothing. Record: the public record is free; a priced lookup is served by whoever runs it, not by Knos. Control:
Team 25,000 USD a year; larger plans are not deliverable yet. Pilot: one buyer, two suppliers, 30 days, one
reconciled invoice, 2,500 USD, credited against year one. Knos never charges the party being rated. Nothing has been sold, there is
no legal entity to invoice from, and on devnet every fee is test money. No token.

## teamCommitment

One person, full time, under the handle drexthealpha, which is a pseudonym. In Sep 2026 my earlier product took
first place at the Sibyl Labs hackathon. I work with coding agents every day,
and this repository was built with them; I review and commit every change. I built it because my own agents told
me the tests passed when they had not. What I have not done: sold to the person who approves a supplier's
invoice, run a security review, or kept a service running for a customer. docs/TEAM.md names the three roles the
plan needs first: someone who has sold to engineering or finance leaders, a security lead to run an outside
review, and agent-vendor partnerships. None is hired, approached or committed. docs/GOVERNANCE.md has three
plans, none done: an outside key holder, a two-owner organisation for the pinned workflows, and the verifier
frozen after an outside review. What the project needs next: an outside key holder, first buyers to run a
shadow count, and an outside review.

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

https://drexthealpha.github.io/Knos/ is the product. Paste a supplier's invoice or name a public repository: the
page shows a neutral count and every mismatch, with no install, no wallet and no sign-up. A simulated round is
below it. From there: put the workflow file in a repository, fund an issue with one comment, and see every
payment the programs have made. This release's code: https://github.com/drexthealpha/Knos/tree/v0.3.26 (a
tag, so it never changes). A judge's one page: https://github.com/drexthealpha/Knos/blob/v0.3.26/docs/JUDGES.md (the same tag). The
package: https://pypi.org/project/knos/ (PyPI). Everything is on Solana
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
