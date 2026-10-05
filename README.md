<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="web/brand/wordmark-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="web/brand/wordmark-light.svg">
    <img alt="Knos" src="web/brand/wordmark-light.svg" height="84">
  </picture>
</h1>

**Knos is the neutral count and settlement for software work priced per outcome: terms fixed before the work, a signed CI run attests they were met, a Solana program counts it or pays it.**

A work order is a task, its budget and the terms that decide whether it is done, fixed before the work starts. A
bounty on an issue is the smallest work order. When the work is merged, a workflow run that GitHub signs says whether
the terms were met, and a Solana program checks that signature itself before it pays. No person holds the money in
between.

**Who it is for.** The buyer is the person who has to approve a supplier's invoice for software work: an engineering
leader or a finance owner buying per accepted change from an agent vendor or an agency. The supplier is the second
user: it needs acceptance terms nobody can change after the work, and a way to be paid when the buyer does nothing.
A maintainer with a 20 USDC bounty is the smallest case, not the market ([docs/MARKET.md](docs/MARKET.md)). It all
runs on Solana devnet, in test USDC; nobody outside Knos has funded an order with their own tokens or bought anything.

1. **A verifier on Solana for any RS256 workload identity**, readable by other programs ([docs/OIDC.md](docs/OIDC.md)).
2. **Named checks and allowed paths are hashed into the order at funding.** Nothing changes them afterwards.
3. **A seller can settle without the buyer**, after a merge in a public repository.
4. **Payment on a black-box check:** of 63 cheating pull requests, 56 passed plain CI and 0 passed it ([docs/TAMPER.md](docs/TAMPER.md)).
5. **A neutral count of accepted outcomes with no escrow:** the supplier's count sits on chain beside the buyer's.

<!-- recording: the release puts the poster image on the next line, linked to the same file -->
**Recording:** [one work order, from its funding to its payment](https://github.com/drexthealpha/Knos/releases/latest/download/demo.mp4). A release with no recording has no such file.

**Try it in one minute, with no wallet.** Open [drexthealpha.github.io/Knos](https://drexthealpha.github.io/Knos/).
Three buttons under the first form each put a real input in it and show the result:
- **A claim that is true:** an agent's pull request says its tests pass, and GitHub's own checks agree.
- **A claim that is false:** a pull request says it passes all CI, and a check of its latest commit failed.
- **A task that was paid:** the transaction on devnet that paid a task; Knos's own account paid itself, in test USDC.

The smallest case, end to end (a company buying from a vendor uses the same order, or the count alone, with no escrow):

1. **A work order.** A maintainer comments on an issue: `/knos fund 20 checks: test`. The money goes into a token
   account of this order alone, the fee on top of it. The terms are logged on chain and nothing changes them.
2. **An acceptance.** Someone opens a pull request, a person or a coding agent, and she merges it. Had `test` failed
   at that commit, her merge would pay nothing, and a comment would name the check that failed.
3. **A payment.** A workflow at a pinned commit reads GitHub's record of the merge and asks GitHub to sign what it
   found. A Solana program checks that signature and pays the author's wallet. If her repository's workflow does
   not do this, the seller can: he runs the pinned `attest.yml` in a repository of his own
   (`knos settle --neutral <pull request URL>`), and the program pays on that run too.

Two options are fixed at funding, both off unless the funder asks. A **warranty**: `warranty 14 holdback 20` keeps
that share of each payment in the order for that many days, and returns it to the funder if the work is reverted in
that time. An **arbiter**: `arbiter @login` names a person both sides accept, who rules who is paid when they disagree.

## Why

Coding agents open pull requests by the million, and a pull request's own description is not evidence.

<!-- bench:headline -->
**Agent PR Index, 2026-10-02.** In 826 repositories, the first pull request by an AI coding agent whose description said tests or CI pass had:

- **a failed check of any kind** at its head commit in 147 (17.8%; 95% interval 15.3% to 20.6%);
- **a failed test, build, lint or type-check job** in 80 (9.7%; 95% interval 7.9% to 11.9%). Names decide this one, so read it as the cautious figure.

Of the 241 merged agent pull requests in the smaller sample that records merges, 30 (12.4%) had a failed check while their description said tests pass. A failed check is GitHub's record, not a judgment of why it failed.
<!-- /bench:headline -->

So nobody pays an agent on its word. Agents are mostly billed by the seat or by the token, and vendors that have
started to bill per accepted change count the changes themselves ([docs/MARKET.md](docs/MARKET.md), section 2).
Code has what most agent work lacks: a third party that already records the result. GitHub records who opened a
pull request, what its checks concluded and who merged it, and it signs statements about a workflow run. A letter
of credit works the same way: the bank pays against a document a third party signed, never against the seller's
word. Here the document is GitHub's signed token and the bank is a program. [docs/WHY.md](docs/WHY.md) has the
argument and its sources.

One limit belongs next to that picture. GitHub signs which workflow ran, at which commit, in which repository,
started by whom, and on which kind of runner. It does not sign what the workflow read. That the checks passed is the
pinned workflow's own reading of GitHub's record. [docs/SECURITY.md](docs/SECURITY.md) says who is still trusted in
each case, and what each could do wrong.

## How it works

**Install.** One workflow file in the repository, `.github/workflows/knos.yml`
([examples/knos-workflow.yml](examples/knos-workflow.yml)). It needs no secret, and nothing in the repository holds
a key or money. A second, optional file puts a check on every pull request
([examples/knos-check.yml](examples/knos-check.yml)). A buyer who owns no repository of the work funds from the
site instead, once the upgrade below has executed: "Fund any issue" takes the address of any public issue and a
wallet, and needs no file in that repository.

**Fund with terms.** The repository's owner, or someone the owner lets spend its balance, comments on an issue:

```
/knos fund 20 checks: test, build paths: src/** days 30 reserve 3 warranty 14 holdback 20 arbiter @login
```

Only the amount is needed. The rest are the terms, fixed at that moment:

- `checks`: the checks that must have passed at the merged pull request's last commit. With none named, Knos takes
  the checks the repository's `.knos/policy.yml` names, else the default branch's required status checks, else
  every check that ran to an end on the default branch's latest commit. A repository with no checks gets none, and
  the reply says so: "your merge alone is the acceptance".
- `paths`: the files a pull request may change. By default it may not change `.github/**` or `.knos/**`, so it
  cannot edit what judges it.
- `days`: how long the money waits for a payment before it goes back (14 by default, 90 at most).
- `reserve`: how many days a contributor's `/knos take` holds the issue (7 by default).
- `warranty` and `holdback`: days, and the share in percent that waits through them (at most 90 days and 50%).
- `arbiter`: who rules on a dispute. `neutral off`: only the funder's own repository may sign the payment.

Other comments: `/knos offer @vendor rate 12 budget 100` is a standing order that pays one vendor that rate for each
accepted change until the budget is spent. `/knos split @a 60 @b 40` shares one payment between up to four people.
`/knos cancel` ends an order with 7 days' notice, and a valid payment inside the notice still pays. `/knos help`
lists the rest, and every comment that starts with `/knos` gets a reply.

On devnet a faucet inside the program mints the test USDC, so the comment is all it takes. With a token of real
value the owner first sets money aside from a wallet: a Balance for one GitHub owner, with a cap per order, limits
per day and in total, the repositories that may spend it, and up to four other GitHub accounts that may spend it by
comment. Only that wallet can take unspent money back out.

**Who is paid, and where.** The person who opened the pull request. When a bot account opened it (a coding agent),
a person or an organisation is paid only on an act GitHub authenticates: the issue is assigned to them, a
maintainer wrote `/knos pay @login`, they are an assignee of the pull request and wrote `/knos mine`, or the
order was a standing offer to that vendor. A line in the description never decides. The money goes to the wallet
bound to that GitHub account, else to the address in their own `/knos address <address>` comment. With neither, the
order is held for them for 180 days and then goes back to the funder. A payee with no wallet app can use a passkey:
the site makes one, and a program on Solana pays out on that passkey's signature.

**No payment.** With no payment by the deadline, the amount and the fee go back where they came from. A refund
needs no token, so it works whatever happens to GitHub or to Knos.

**Paid without a merge, for a black-box check only.** The funder's check sits in `.knos/acceptance/<issue>/` before
funding and is fixed by its hash in the terms. The submission runs as a separate process in a sandbox and only its
output is compared. The reason is measured in [docs/TAMPER.md](docs/TAMPER.md): of 63 cheating pull requests, plain
CI passed 56, acceptance tests that run in the same process as the code passed 7, and the black-box check passed
none.

**Counted without an escrow.** A buyer who pays a vendor by invoice can still have a neutral count. `knos-meter`
records each evaluation GitHub signed, accepted or rejected, once, and either side can recompute a month's count
from the program's logs (`statement` in [`src/knos/settle/v2/meter.py`](src/knos/settle/v2/meter.py)). It moves no
customer money.

## What exists nowhere else

Read on 2 Oct and 3 Oct 2026. [docs/COMPARE.md](docs/COMPARE.md) has the neighbours, the method, and where they are
ahead. "Nowhere else" means: not in anything we found, and the page lists what we read.

- **One verifier on Solana for any RS256 workload identity.** `knos-oidc` verifies an OpenID Connect token signed
  with RS256 on chain, and any other program can read the verified claims. GitHub's keys are built in. A key of
  any other issuer (GitLab, a company's own GitHub Enterprise Server, another CI system) is admitted on GitHub's
  signature over a pinned workflow run that fetched it, then waits a day and needs a guardian's approval. We found
  no other program on Solana that verifies an RS256, JWT or OIDC token. On an EVM chain MergePay verified GitHub's
  signature first.
- **Named checks as a condition of payment, fixed at funding.** The checks that must have passed at the merged
  commit, and the paths that may change, are hashed into the order when the money goes in. On MergePay the
  condition is the merge alone. On the bounty boards a person judges.
- **A payment the buyer cannot withhold after a merge.** On a public repository the seller can ask GitHub for the
  signed statement himself, from the same pinned workflow, and the program accepts it. In the products we read, the
  buyer or the board decides the payout.
- **Payment on a black-box check, by a program.** One board, TaskBounty, also pays on a test run, in a sandbox it
  operates. Here the sandbox is in the funder's workflow and a program pays.
- **A neutral count of accepted outcomes, on chain, with no escrow.** No vendor uses it yet.

## What runs today, and where

Everything is on **Solana devnet**, and the money is **test USDC**. Mainnet is not touched.

<!-- programs:start -->
| program | address | on devnet, as [`docs/capabilities.json`](docs/capabilities.json) records it |
|---|---|---|
| `knos-oidc`, the verifier | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` | runs `2.0`; `2.1` is proposed through the multisig and runs at this address only once its proposal has executed; the 0.3.14 rehearsal ran it at a staging address of its own ([docs/CAPABILITIES.md](docs/CAPABILITIES.md)) |
| `knos-pay`, the escrow | `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k` | runs `2.0`; `2.1` is proposed through the multisig and runs at this address only once its proposal has executed; the 0.3.14 rehearsal ran it at a staging address of its own ([docs/CAPABILITIES.md](docs/CAPABILITIES.md)) |
| `knos-meter`, the count | `FUMKkcE95x2kZUj1zZTCbgcYBmJ3WXPHL8pyA8J6anX` | runs `1.0`; `1.1` is proposed through the multisig and runs at this address only once its proposal has executed; the 0.3.14 rehearsal ran it at a staging address of its own ([docs/CAPABILITIES.md](docs/CAPABILITIES.md)) |
| `knos-passkey`, a wallet from a passkey | `FQPX9i5kQxLYKZyyPgM2fVK9am3w1LSk1Cuoer1sSY85` | runs `1.0`; `1.1` is proposed through the multisig and runs at this address only once its proposal has executed; the 0.3.14 rehearsal ran it at a staging address of its own ([docs/CAPABILITIES.md](docs/CAPABILITIES.md)) |
<!-- programs:end -->

This page names no time for an upgrade, so that it is true before and after one: whether a proposal is pending, has
executed or was withdrawn, and from when it can run, is read from the chain by `knos status`, the site's banner and
the site's [upgrade record](https://drexthealpha.github.io/Knos/upgrades.json) ([`web/upgrades.json`](web/upgrades.json)
is the committed copy, of the time it names). Knos waits out its own 48-hour delay like anyone else. While a program
runs its older version, it behaves as 0.3.12 described it: the fee comes out of the payment, only the funder's
repository can sign, and there is no work order, seller's settlement, any-issuer key or single-use pay token.

Knos can change all four programs only through a Squads multisig whose vault
(`CKCrTBN542pVhizxuSPVg8tvdnPooNxt9B7o97VuTjz2`) is their upgrade authority, and only after that public 48-hour delay,
until an outside review. Every member key of that multisig is still the founder's, so the delay, not the number of
signers, is what protects a user. A second multisig, the guardian (`AT1aKj1DpgaWerxmS4YjDkNpWPNUtCCKVDvxLhFxg5Jc`),
can approve or revoke a signing key and pause new funding for at most 7 days. It cannot add a key or move money. The
first deployment ([`programs`](programs), 0.3.10 and 0.3.11) has no upgrade authority and stays as the record of those
releases; nothing new is funded there. No outside security firm has examined anything. 0.3.15 changes no program; what
its tests found and left open is in [CHANGELOG.md](CHANGELOG.md).

<!-- capabilities:start -->
**Every capability and how far it has got** ([the table with the evidence](docs/CAPABILITIES.md), from [`docs/capabilities.json`](docs/capabilities.json); a stage needs its evidence and the stages below it). **Reproduced by someone else:** none recorded yet. **Exercised on devnet:** none recorded yet. **Deployed on devnet:** `verify_github`, `verify_gitlab`, `key_guardian`, `fund_by_comment`, `fund_from_wallet`, `pay_on_merge`, `hold_and_bind`, `refund`, `pause`, `meter_single`, `passkey_payee_wallet`, `upgrade_gate`. **Tested locally:** `check`, `install_by_pull_request`, `terms_templates`, `stop_hook`, `mcp_tools`, `agent_tools`, `verify_any_issuer`, `work_orders`, `order_pay`, `tests_mode`, `order_auto_accept`, `order_challenge`, `order_quorum`, `hermetic_judge`, `holdback_release`, `warranty_revert`, `seller_settle`, `neutral_attest`, `arbiter_rule`, `reserve_cancel`, `top_up`, `assign`, `advance_by_assignment`, `standing_order`, `org_balance_limits`, `org_wallet`, `plans`, `fee_tiers`, `single_use_tokens`, `private_attestor`, `meter_batch`, `meter_seller_claim`, `passkey_funder`, `passkey_fund_relay`, `buyer_page`, `gitlab_pay`, `relay`, `adapters`, `canary`, `load_local_1000`, `invariants_state_machine`, `rust_handler_tests`, `receipt`, `evidence_bundle`, `receipt_mirror`, `sas_receipt`, `x402_example`, `x402_knos_order`, `cpi_fund`, `oidc_gate`, `upgrade_delay`, `upgrade_feed`, `policy`, `screening`, `statements`, `badge`, `audit_export`, `agent_pr_index`, `agent_weekly_rates`, `mainnet_check`, `deliverable_identity`, `meter_corrections`, `meter_period_close`, `ledger_dedup`, `receipt_five_parts`, `evaluator_independence_record`, `verify_without_chain`, `budget_controls_cli`, `console`, `observer_view`, `relay_journal_and_retries`, `dependency_drills`, `workflow_capacity_model`, `reproduction_kit`, `neutral_reexecution`, `doc_claims_check`, `agent_index_weekly_scan`, `opt_in_profiles`, `outcome_examples`, `knos_verify_action`, `webhook_verifier`, `agent_host_routes`, `oidc_differential`, `fuzz_rsa_diff_target`, `cli_lazy_start`, `site_cache`, `live_round_view`, `brand`. **Implemented:** `gitlab_ci_example`, `kani_fee_conservation`. **Not built:** none recorded yet. Deployed and exercised are counted only at the public program ids; what the 0.3.14 rehearsal ran at staging addresses of its own is in the note of each capability it ran, with its transaction.
<!-- capabilities:end -->

## Install

[docs/INSTALL.md](docs/INSTALL.md) lists every route with its exact commands:

- **A repository:** the workflow file above, or only the free check as a GitHub Action.
- **A terminal:** `pip install knos`, then `knos --help`.
- **Coding agents:** `knos init` adds a Stop hook and an MCP server for the agent hosts INSTALL lists; there are also
  a plugin, an extension and one-click links. The hook runs the check itself when an agent says tests pass or it is
  done. The MCP tools read and return the exact comment or transaction; they hold no key and send nothing.
- **Other programs:** Rust crates that read a verified token and fund a work order, the programs' IDLs, a
  JavaScript client, and worked examples ([docs/COMPOSE.md](docs/COMPOSE.md), [docs/OIDC.md](docs/OIDC.md)).

## Prices

| Line | Unit | Price |
| --- | --- | --- |
| Check | pull request checked | free |
| Meter | evaluation | 10,000 a month free per organisation, then 0.05 USD; 0.02 on a committed-volume plan |
| Control | organisation | 25,000 USD a year entry, 80,000 organisation tier (nobody has bought it) |
| Settle | dollar settled, paid by the funder on top | 2.5% of the first 1,000, 1% from 1,000 to 50,000, 0.5% above; minimum 0.40 |
| Pilot | one buyer and its suppliers, 30 days | 2,500 USD, invoiced off chain: reconcile the buyer's accepted work from more than one supplier, name every mismatch between acceptance and billing, deliver a statement both sides verify (nobody has bought it; there is no legal entity to invoice from yet) |
| Advance, Assurance | | not offered; needs loss history |

Relayer tip: 0.05, or 0.30 on a payee's first payment, out of the fee. Nobody has bought anything.
A small order pays more than the first rate: 5 pays the 0.40 minimum, which is 8%. On devnet the settle fee is test
money. [docs/MARKET.md](docs/MARKET.md) has the effective fee by order size, what each sale costs, one example
customer worked through, the first milestone and what a fork can copy; [docs/PILOT.md](docs/PILOT.md) is the Pilot in full.

## Limits

[docs/SECURITY.md](docs/SECURITY.md) has all of them. The ones to know first:

- **Devnet, test USDC, no outside review.** `knos mainnet-check` fails on that line on purpose.
- **Nothing has been bought by an outsider.** By 3 Oct 2026 no outside repository had funded a task. Knos's own
  account funded every task that was paid. The site's Numbers page shows today's counts.
- **A signature authenticates a statement, not the truth.** GitHub signs that a pinned workflow ran, not what it
  read. A funder's own repository that lies can pay whom it likes, from its own orders only.
- **The seller's own settlement covers public repositories.** For a private repository the buyer can still withhold
  by revoking access. What remains is the arbiter, if the order named one, and the public record.
- **A passed check is not good work.** An order buys what its terms say, and the funder chose the terms.
- **Knos inherits GitHub's failures.** If GitHub signs something false or is down, the programs believe it or wait.
- **One person can change the programs, after 48 hours,** until the outside review.
- **An order holds from 5 to 100,000 test USDC** on devnet. A mainnet build sets its own cap.
- **The payout is USDC on Solana.** There is no card, bank transfer or invoice payment in, and no bank payout.

## What is in this repository

| | |
|---|---|
| [`programs-v2`](programs-v2) | The four programs above: `knos_oidc`, `knos_pay`, `knos_meter`, `knos_passkey`. Each file's first lines say what it does, instruction by instruction. |
| [`programs`](programs) | The first deployment of the verifier and the escrow, exactly as deployed. |
| [`.github/workflows`](.github/workflows) | `fund.yml`, `prove.yml`, `attest.yml`, `check.yml`: the workflows a repository calls, published at one pinned commit of `drexthealpha/knos-workflows`. An order records that commit. |
| [`src/knos`](src/knos) | What the workflows run, the judge, the relay anyone can run, the policy reader, receipts and statements, the Stop hook and the MCP server. |
| [`crates`](crates), [`idl`](idl), [`sdk/settle`](sdk/settle), [`examples`](examples) | What another team builds on: interface crates, IDLs, a JavaScript client with no dependency, and example programs with their tests. |
| [`web`](web) | The site. It reads GitHub and Solana in the browser; there is no Knos server. |
| [`docs`](docs) | [SECURITY](docs/SECURITY.md) (who is trusted for what, every known limit), [ASSURANCE](docs/ASSURANCE.md) (the rules the tests enforce, where a reviewer should start), [DRILLS](docs/DRILLS.md) (safety paths run on the deployed bytes), [BENCH](docs/BENCH.md) (every measured number), [MARKET](docs/MARKET.md), [COMPARE](docs/COMPARE.md), [WHY](docs/WHY.md), [OIDC](docs/OIDC.md), [COMPOSE](docs/COMPOSE.md), [INSTALL](docs/INSTALL.md), [DISCLOSURE](docs/DISCLOSURE.md), [METER](docs/METER.md) (deliverables, corrections, closing a month, a statement both sides verify), [RECEIPT](docs/RECEIPT.md) and [PRIVACY](docs/PRIVACY.md), [GOVERNANCE](docs/GOVERNANCE.md), [INVARIANTS](docs/INVARIANTS.md), [ADAPTERS](docs/ADAPTERS.md), [LOAD](docs/LOAD.md), [X402](docs/X402.md), [CONTROLS](docs/CONTROLS.md), [REGULATION](docs/REGULATION.md), [RELAY](docs/RELAY.md), [OPERATIONS](docs/OPERATIONS.md). New in 0.3.15: [CONSOLE](docs/CONSOLE.md) (the operator's screen: budgets, billed before or not, exceptions, a receipt's five parts), [PILOT](docs/PILOT.md) (the 30-day reconciliation, step by step), [OUTCOMES](docs/OUTCOMES.md) (three outcomes that are not a merged pull request), [REPRODUCE](docs/REPRODUCE.md) (run the checks in a repository of your own and have GitHub sign the report), [INTEGRATIONS](docs/INTEGRATIONS.md) (the verify action, a webhook verifier, the badge), [TEAM](docs/TEAM.md) (who answers today: the founder alone). [INDEX](docs/INDEX.md) is the Agent PR Index by week. |

## History

Knos 0.1 (1–7 Sep 2026, before this hackathon) was shared memory for coding agents built on Sibyl. 0.2 and 0.3.0–0.3.9
(29 Sep – 2 Oct) tried coordination, budgets and a jobs market before the measurement above showed where the problem
was ([drexthealpha/knos-labs](https://github.com/drexthealpha/knos-labs)). 0.3.10 to 0.3.14 are the two deployments,
work orders, the count and single-use tokens. 0.3.15 is this release: it changes no program.
[docs/DISCLOSURE.md](docs/DISCLOSURE.md) says what was built when and what came from elsewhere;
[CHANGELOG.md](CHANGELOG.md) is the dated record.

MIT, all of it. Built by drexthealpha. Its memory engine is [Sibyl](https://sibyllabs.org).
<!-- mcp-name: io.github.drexthealpha/knos -->
