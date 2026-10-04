# Changelog

## 0.3.13 (October 2026)

**Knos pays for software work on signed acceptance: terms fixed before the work, a GitHub-signed run attests they
were met, a Solana program settles.** The unit is now a work order. A bounty on an issue is the smallest one.

Six readers' reviews of 0.3.12 are answered by this release. None was a security audit, and no outside security firm
has reviewed anything. One of them confirmed seven defects in 0.3.12 by reading the source; each is listed under
[Security](#security) with its fix.

### What is live, and when

The escrow and the verifier are upgraded at their existing addresses, through the multisig, with its public 48-hour
delay. The upgrade was proposed and approved by the multisig on 2026-10-04 07:17 UTC and can execute from
2026-10-06 07:17 UTC.
`knos status` and the site's banner show it while it is pending.

| | live |
|---|---|
| The workflows of this release (installs by hash, `attest.yml`), the command line, the MCP tools that act, the site, records, statements and exports, the policy file, screening, the interface crates and examples | with the release |
| `knos-meter` and `knos-passkey`: new programs at new addresses | once the release run has deployed them |
| Everything below that names a work order: the fee on top, the four judges and the seller's own settlement, warranty, arbiter, split, standing offers, cancellation, top-up, assignment, organisation wallets, private orders | when the upgrade executes |
| The fixes to 0.3.12 bounties: whole-unit limits, the extension list, a Balance's limits, single-use pay tokens | when the upgrade executes |
| Any-issuer keys, Refresh by anyone, private keys | when the upgrade executes |

Until the upgrade executes, `/knos fund` opens a bounty exactly as 0.3.12 did. A bounty funded before it finishes
as it was funded: every 0.3.12 instruction keeps its bytes and its behaviour, apart from the fixes above. Tokens of
the new paths carry audiences that start `knos3:`, so a token of one generation is good for nothing in the other.

### If you fund work

- **You pay the fee on top; the payee receives the posted amount.** 2.5%, at least 0.40 and at most 25 USDC. It is
  escrowed with the amount and returned with it if nobody is paid. An order holds between 5 and 500 USDC.
- **Each order's money is in a token account of its own.** No vault is shared between orders.
- **Fund any public issue from a wallet, with no file in that repository** ("Fund any issue" on the site, and
  `FundOrderWallet` for a program or a multisig).
- **New options on `/knos fund`:** `warranty N holdback N` keeps a share of each payment (at most 50%) in the order
  for N days (at most 90); it returns to you if your repository attests a revert in that time, and goes to the
  payee otherwise. `arbiter @login` names who rules on a dispute. `neutral off` lets only your own repository sign.
- **`/knos offer @vendor rate R budget B`:** a standing order that pays one vendor R for each accepted change
  until B is spent. No comment per issue.
- **`/knos split @a 60 @b 40`** before a merge: one payment, up to four payees.
- **`/knos cancel`:** the order ends in 7 days at most. A valid payment inside the notice still pays. If someone
  had reserved it, a kill fee fixed at funding (at most 20%) goes to them first.
- **`/knos raise <amount>`** tells you how to top an order up. The top-up itself is signed by the wallet the money
  came from.
- **You can no longer withhold a payment after merging in a public repository.** See the next section.

### If you do the work

- **After a merge you can settle yourself.** `knos settle --neutral <pull request URL>` starts the pinned
  `attest.yml` by hand in a repository of your own. It reads GitHub's public record of the pull request, and the
  escrow pays on that run. The buyer's workflow is not needed. This holds for a public repository and an order
  that was not funded with `neutral off`; the funding reply says which it is.
- **You receive the full posted amount.**
- **No wallet app needed.** The site makes a passkey, and the address it derives can be paid like any other.
  Withdrawing needs only the passkey. The site shows and withdraws both of devnet's test mints: Circle's USDC and
  the faucet's test USDC that a bounty funded by comment pays. The public relay carries a withdrawal from the moment
  `knos-passkey` is deployed; it does not wait for the escrow's upgrade, which that program never calls. Read
  [SECURITY.md](docs/SECURITY.md), section 17, before keeping money there.
- **An organisation can be paid.** A member binds its wallet by hand, from a `knos-claim` repository the
  organisation owns, and a bot's pull request can then pay the organisation that runs it.
- **You can assign a payment.** The bound wallet of a payee signs one order's payment over to another wallet, so
  anyone can advance money against accepted work.
- **A reservation is on chain.** `/knos take` reserves an order for its `reserve` days, and a cancellation while
  you hold it pays you the kill fee.
- **Before you start:** the MCP tool `knos_can_pay` says whether a repository can still pay an issue, and why not.

### If you run a company

- **A count without an escrow.** `knos-meter` counts each evaluation GitHub signed, once, for a buyer and a seller
  in a month: accepted, rejected, and the declared value. It moves no customer money. 0.05 per billable evaluation
  from prepaid credits, 0.02 at volume, and the first 10,000 of a month free. An evaluation is a run of the
  published `attest.yml` with the kind `eval`, started in a repository of the buyer: GitHub's record of a pull request
  there is the verdict (merged: accepted; closed unmerged: rejected), and it is posted as `knos-eval:` for the relay,
  which carries it from the moment the meter is deployed, whatever the escrow's version. `knos statement --meter
  --buyer X --seller Y --month YYYY-MM` recomputes one buyer's and one seller's month from the program's logs.
- **Private orders.** Funded from your organisation's Balance by a comment in a judge repository you choose. The
  chain shows the amounts, the payees and that repository, and no name, issue number, check name or path of the
  private one ([SECURITY.md](docs/SECURITY.md), section 12).
- **Your own issuer.** A wallet registers the key of a server no public runner can reach, such as GitHub
  Enterprise Server. Its tokens pay only private orders funded from that wallet's own Balance.
- **`.knos/policy.yml`:** who may fund, a cap per order, a monthly budget, allowed payees and vendors, default
  checks, standing offers, warranty defaults. A fund comment it refuses is told the line.
- **A Balance has limits:** per day, in total, the repositories that may spend it, and the workflows commit.
- **Records for finance:** `knos receipts` and `knos statement` (CSV among their formats), `knos invoice` (a page
  and a CSV of its lines) and `knos export` (JSON Lines for a SIEM), all recomputed from the escrow's logs.
- **Screening:** a payout to an address on the United States Treasury's sanctions list is refused and held.
- **A lower rate under a contract** is a `Plan` account on chain, 0.5% to 2.5%, until an expiry.

### If you build on it

- **Any RS256 issuer.** `knos-oidc` admits a key of any issuer on GitHub's signature over the pinned rotate
  workflow's run, with the same delay, approval, expiry and revocation as before.
- **`knos-oidc-interface` now reads the second deployment by default.** The first is `v1::read`. It exposes
  `is_private()`, `registrant()`, `issuer_hash()` and `key_usable()`.
- **`knos-pay-interface`:** fund, top up and refund a work order from your own program
  ([`examples/cpi_fund`](examples/cpi_fund)).
- **Examples with tests:** a vault only a workflow can spend ([`examples/workflow_vault`](examples/workflow_vault)),
  a record that GitHub's runner built an executable ([`examples/upgrade_gate`](examples/upgrade_gate)), a proposed
  x402 scheme that pays on attestation ([docs/X402.md](docs/X402.md)), receipts as Solana Attestation Service
  attestations ([docs/RECEIPT.md](docs/RECEIPT.md)), funding from a Squads vault. [docs/COMPOSE.md](docs/COMPOSE.md)
  lists them.
- **MCP tools that act:** `knos_take`, `knos_address`, `knos_fund`, `knos_settle`, `knos_quote`, `knos_can_pay`.
  Each returns the exact comment or transaction to send and sends nothing. Text a repository wrote comes back in a
  field named `untrusted`.
- **Static data on the site:** `bounties.json`, a file per account and per repository, badges and rankings.
- **`knos accept init`** scaffolds a black-box acceptance bundle from a reference implementation;
  [`examples/acceptance`](examples/acceptance) has three tasks that are not code review.
- **Relaying costs less and pays.** A token is two transactions, and a payment tips the relayer out of the fee.

### Security

The seven defects one review confirmed in 0.3.12, and what this release does about each:

| the defect in 0.3.12 | this release |
|---|---|
| Amount limits and the fee floor ignored a mint's decimals, and the record summed raw units across mints. | Limits and the fee floor are whole units, read from the mint. The record counts money as real only in Circle's USDC; every other mint counts as test. |
| A Token-2022 mint with a transfer-hook authority but no program passed the screen, and Pausable was not screened. | A list of allowed extensions. A mint with any other extension is refused when money enters, including ones added to Token-2022 later. |
| A Balance had a cap per bounty but no limit per day or in total, and any repository of its owner could spend it. | A side account its wallet sets: a limit per day, a limit in total, the repositories that may spend it, the workflows commit. A Balance without one is as before. |
| A pay token was not single-use: one token could pay several bounties on one issue with matching terms. | A pay token pays, or holds, exactly one. A marker keyed by the token's signature refuses a second use. |
| The job that signs installed `knos` from PyPI by version, without hashes. | Every job that signs installs by sha256 from a list in the workflow at the pinned commit, imports the standard library and one package, and uses no cache. The two jobs that cannot sign still install by version. |
| The interface crate's `Token::read` defaulted to the first deployment's verifier, which took key attestations from any repository. | It defaults to the second deployment. |
| Keys expired after 30 days unless one personal account's scheduled job attested them again, and one person holds every key of the upgrade multisig. | Anyone can refresh a key GitHub still publishes, by running the pinned workflow by hand in a repository of their own. New keys still need that one account and the guardian. The multisig is unchanged: every member key is still the founder's. |

Also:

- An attestation that registers or refreshes a key counts only while the key that verified it is itself usable.
- The claim parser has unit tests and a fuzz target that compares it with `serde_json`; a nightly job runs it.
- `knos check`, the free check and `knos_check_pr` read a pull request's checklist as the site does: a ticked
  "My PR passes all CI/CD checks" is the author's claim and is held to GitHub's record, and an unticked box, an
  HTML comment or an agent's quoted prompt claims nothing. Nor does a sentence that hedges, negates or instructs
  ("tests should pass", "make sure CI is green"), in the Agent PR Index's words, and the site and the index skip
  an unticked box of any list marker. A description of any shape is read in time linear in its length.
- A proposed upgrade is refused by the proposing script unless GitHub signed that Knos's own workflow built those
  bytes from a commit, and `knos status` says whether a pending upgrade has that record.
- The MCP server marks third-party text as untrusted and can be restricted to named repositories.
- [docs/DRILLS.md](docs/DRILLS.md): refund, the 180-day return, key expiry, the guardian's pause and revocation,
  and a proposed, waited, executed and cancelled upgrade, run against the bytes deployed on devnet in a simulator.
  The rows that need real GitHub tokens were not run.

What is still open is in [docs/SECURITY.md](docs/SECURITY.md), "Known limits".

## 0.3.12 (October 2026)

**The first deployment was made immutable too early.** 0.3.10 deployed two programs and removed their upgrade
authority the same day, before anyone outside had read them. Three outside reviews then found defects that cannot
be patched there. 0.3.12 does not touch it: `programs/` is byte for byte what was deployed, and the bounties funded
on it finish on it. Everything new is a second pair of programs, `programs-v2`, with new addresses. It stays
changeable until an outside review, only through a multisig with a public 48-hour delay, and is then made immutable.

What the reviews found in the first deployment, and what the second does instead:

| the defect | the second deployment |
|---|---|
| A funder could merge a pull request and then veto, taking the money back. | No veto and no review window. A maintainer says no before merging (`/knos reject`); once the pay token exists the payment is final. |
| A merge payment's condition was what the description claimed. It was not fixed on chain. | Terms fixed at funding: the checks that must have passed at the merged commit and the paths that may change. The funding transaction logs them, the bounty stores their hash, and a payment must carry it. |
| A payment was credited to the author's GitHub id inside the program and claimed later, in a second step. | Paid straight to a wallet in the paying instruction. With no wallet known, the bounty is held for that person for 180 days and then returns to the funder. |
| A signing key the program trusted never expired and could not be revoked. | A key expires 30 days after it was last attested, and a guardian can revoke it. Revoking a key also stops the payments that depend on tokens it signed. |
| A new key was admitted on a GitHub-signed token from any repository that called the rotate workflow. A hosted runner with a custom image can carry a standard label in a paid organisation, so that token said less than it seemed to. | The attestation counts only from two repositories of one personal account, started by the schedule or by hand. The key then waits a day and needs the guardian's approval. |
| Real money needed a wallet transaction for every bounty. | A balance: a wallet sets money aside for one GitHub owner, with a cap per bounty and up to four accounts that may spend it by comment. Unspent money goes back only to that wallet. |
| Only classic SPL tokens. | SPL Token and Token-2022 mints. A mint that could tax or block a payout is refused when money enters. |
| The public record did not tell real money from test money or self-payment. | It counts them apart, and counts distinct funders. |
| Nothing could be done about a fault. | A guardian can pause new funding for at most 7 days at a time. The pause does not reach payments, refunds, withdrawals or wallet bindings, and the guardian cannot add a key or move money. |

### If you fund work

- **`/knos fund <amount> [checks: a, b] [paths: glob, ...] [days N] [reserve N]`** on an issue (`/knos bounty` still
  works). The reply states the terms in plain sentences before any money moves. With no checks named, the terms
  take the default branch's required checks, else the checks that ran on its latest commit. A repository with no
  checks is told so: "your merge alone is the acceptance".
- **Six states of evidence.** At the merge each required check is passed, failed, skipped, pending, absent or
  unreadable at the pull request's last commit. Only passed for all of them is acceptance. A check of the same name
  from another app does not count, and neither do Knos's own jobs.
- **`/knos reject [reason]`** on a pull request, before merging: it does not take the bounty.
- **Payment without a merge ("tests mode") is offered only for a black-box check:** the submission runs as a
  separate process and only its output is compared. Everything else is funded in merge mode. The reason is measured
  in [docs/TAMPER.md](docs/TAMPER.md): of 63 cheating pull requests, plain CI passed 56, in-process acceptance
  tests 7 and the black-box check none.
- **`/knos tip <amount>`** on a merged pull request: a small bounty funded and paid at once.
- **A pull request merged before the bounty was funded is not paid.** A pay token must be issued after the funding.
- On devnet a faucet in the program mints the test USDC, so one comment is still all it takes.

### If you do the work

- **Paid to a wallet.** The wallet bound to your GitHub account, else the address in your own
  `/knos address <address>` comment on the pull request. Binding is by hand only: create a repository from the
  template `drexthealpha/knos-claim`, run its "knos claim" workflow from the Actions tab and paste your address
  yourself, or run `knos claim <address>`, which does both. The program takes only a run started by hand, and no
  link, repository description or push carries an address in, because an address in a link could be someone else's.
- **`/knos take`** reserves an unassigned funded issue for the bounty's `reserve` days; **`/knos release`** gives it
  back. An assigned issue pays only its assignee's pull request.
- **A coding agent's pull request pays a person only on an act GitHub authenticates:** the issue's assignee, a
  maintainer's `/knos pay @login`, or `/knos mine` from a person named in the pull request's assignees. 0.3.11 paid
  the login a line in the description named; an agent can be talked into writing such a line. Those lines are now
  shown as a hint and decide nothing. An edited comment never counts.
- **`/knos settle`** tries a merged pull request's payment again. **`/knos status`** says what is in escrow.
- **Every `/knos` comment gets a reply**, including an unknown command, a malformed one and one from someone who may
  not use it. The reply says what was understood and what to type instead.

### If you install it

- **One workflow file for the whole payment flow**, `.github/workflows/knos.yml`: comments and new issues, the push
  a merge makes, a run by hand. A second, optional file puts the check on every pull request.
- **No `pull_request_target`.** From 2 Nov 2026 GitHub blocks workflows it triggers on public repositories unless an
  admin allows them, and a fork's `pull_request` run gets no token. A merge is now read from the push it makes.
- **The workflows are published at one commit of `drexthealpha/knos-workflows`** and install the judge as the exact
  PyPI release. They take no inputs, so a calling repository cannot change which code judges. A bounty records
  that commit and is paid only by it.
- **The check's memory is an issue.** Since 26 Jun 2026 GitHub denies cache saves to the runs that could write it,
  so what the check learned is kept as comments in an issue labelled `knos-memory`, written by GitHub Actions and
  read by every run. Comments by anyone else, and edited ones, are ignored.
- **Private repositories.** With a relay key in the repository's secrets the job carries its own tokens to Solana,
  and nothing is posted in public.
- **Install routes**, each tested: a plugin for Claude Code and Codex, an extension for Gemini CLI, links for Cursor
  and VS Code, the free check as a GitHub Action, the JavaScript client, the Rust interface crate
  ([docs/INSTALL.md](docs/INSTALL.md)).
- **One gate for a release.** `release.yml` runs the whole test workflow on the tagged commit before anything is
  published, and every publishing job needs it. PyPI takes the upload by trusted publishing first, and by the
  repository secret `PYPI_API_TOKEN` when that does not work; with neither the job fails and names both.
- **No cache in a job that signs or holds a secret.** A cache written by a run of pull request code could be read by
  a job that signs, so these jobs install with `enable-cache: false`. A test fails if one does not.
- **Node 24.** GitHub removed Node 20 from Actions runners on 23 Sep 2026. Every pinned action that runs on Node is now a
  release that runs on Node 24, and `scripts/action_pins.json` names each by its commit.

### For other programs

- `knos-oidc-interface` reads a token of either deployment (`Token::read`, `v2::read`); IDLs for both in `idl/`.
- The verifier's arithmetic and claim reader are unchanged, byte for byte, between the deployments.

### Corrections to what 0.3.11 said

- **"Nobody can change it" and "no admin" are true of the first deployment only.** The second can be changed by
  Knos, through the multisig, after 48 hours, until an outside review. Today every key of that multisig is the
  founder's.
- **17.8% is "a failed check of any kind"**, not "failed CI": 147 of 826 repositories. Counting only a failed test,
  build, lint or type-check job, by its name, it is 80 of 826, 9.7%. Both are published under those names.
- **The index is not "rebuilt every 6 hours".** A scan is scheduled every 6 hours and replaces the published list
  only when it has finished. Before, a run that counted too few pull requests ended green and published nothing;
  now it fails in the open.
- **RSA-4096 tokens above about 5,000 bytes could not be verified by 0.3.11's client.** Its last step ran out of
  compute units. The plan is now 2, 3, 3, 3, 4 and 1 squarings, and every size up to 8,192 bytes verifies, on both
  deployments ([docs/BENCH.md](docs/BENCH.md)).
- **The history.** The public repository's history starts on 1 Sep 2026, and 83 of its 209 commits up to 0.3.11
  predate the hackathon ([docs/DISCLOSURE.md](docs/DISCLOSURE.md) has the counts and the commands).
- **The market.** The unsourced figure for agent spending is gone; [docs/MARKET.md](docs/MARKET.md) is bottom-up
  with every input labelled.

### Measured

- The tamper benchmark now has three sample repositories, in Python, JavaScript and Ruby: 63 cheating pull
  requests. Plain CI passed 56, the in-process judge 7, the black-box check none ([docs/TAMPER.md](docs/TAMPER.md)).
- Of 241 merged agent pull requests whose description said tests pass, 30 had a failed check at the head commit
  ([docs/BENCH.md](docs/BENCH.md), "Merged anyway").
- Compute units of every instruction of the second deployment, four random walks of 2,500 steps over its escrow,
  and the first deployment's record on devnet are in [docs/BENCH.md](docs/BENCH.md).

### From outside

Three pull requests by another GitHub account, `jaystay-bot`, written for bounties Knos funded on this repository:
`knos_bounties` says what each bounty is about (#32), a repository's own record in the Agent PR Index on the site
(#33), and a Ruby runner for the judge (#34).

### Not done

No outside review. No mainnet. No real money has moved, and by 3 Oct 2026 no outside repository had funded a task.
[docs/SECURITY.md](docs/SECURITY.md) lists every known limit.

## 0.3.11 (2 Oct 2026)

No change to the two programs: they are immutable, and `programs/` is byte for byte what was deployed.

- **A merge alone no longer pays.** The check every bounty pull request gets runs once more at the merged commit,
  in the job that asks GitHub for the token and runs no pull request code. A description that says tests pass
  mints a token only if GitHub's record of that commit bears it out: a failed check, checks still running or an
  unreadable record all mint nothing. A pull request that claims nothing is paid on the merge and the repository's
  rules.
- **An agent's pull request pays the person who ran it.** A pull request opened under a bot account (Copilot, Devin,
  Jules, Cursor) names its operator in different ways: an assignee, a `Requested by: @login` line, the co-author of
  the head commit. Knos reads each, or an explicit `Knos-Pay-To: @login`; a description that names two people, or a
  name GitHub does not confirm, pays nobody. Before, a bot's pull request with no assignee failed.
- **An assigned issue pays only its assignee.** An unassigned bounty is open to anyone; assigning it reserves it.
- **The check alone, with no money.** `check.yml` and `examples/knos-check.yml`: one file, and every pull request's
  "tests pass" is compared with GitHub's record. No token, no wallet, no chain. The site offers both installs.
- **`knos claim <address>`.** One command does what took five steps in the browser: it uses your `gh` login, runs
  the claim in a repository you own, and waits until the money has arrived.
- **`knos mcp`.** A read-only MCP server, registered by `knos init` for Claude Code, Codex, Cursor and Gemini CLI:
  an agent can list funded issues it could take, check a pull request's claims, and see what its operator is owed.
  Listed in the MCP registry on release.
- **For other programs.** `crates/knos-oidc-interface`, a Rust crate with no dependency that reads a verified
  token (the example now uses it: 21,632 compute units); IDLs for both programs in `idl/`; the JavaScript client as
  an npm tarball on every release.
- **The relay survives a race.** On devnet, two runs carried one proof at once and both gave up. A failure that
  says nothing about the token is now tried again on the next pass; every transaction asks for the compute units
  it needs (a cluster gives 200,000 unless asked, which the local test chain had not enforced).
- **Every action is pinned to a commit**, in every workflow and example.
- **The measurement is restated.** One pull request per repository: 147 of 826 (17.8%). The earlier figure, 660 of
  2,431 pull requests (27.2%), leaned on a few busy repositories; both are published, the first is quoted.
- **The docs say what this version cannot do**: a trusted key cannot be revoked, rotation depends on timing, and
  bugs are for ever ([docs/SECURITY.md](docs/SECURITY.md)), with what the mainnet version changes. The market
  section now says how small the bounty market is and where the money is ([docs/MARKET.md](docs/MARKET.md)).
- Knos runs on its own repository (`.github/workflows/knos.yml`, pinned to the previous release, since a repository
  cannot name its own commit before it exists).
- Windows: Sibyl's database handles are closed after each call, so the store can be moved or deleted.

## 0.3.10 (2 Oct 2026)

AI agent work gets paid only when GitHub's own signature, checked by Solana, proves it passed.

One product. Everything else moved to [drexthealpha/knos-labs](https://github.com/drexthealpha/knos-labs).

- **Nobody controls the proof.** Two new programs replace the escrow: `knos-oidc` verifies GitHub Actions and GitLab
  CI tokens on chain, and `knos-pay` holds and pays bounties. Neither has an admin instruction, and both are made
  immutable after deployment. The issuers' keys are constants in the binary; a new key enters only on GitHub's own
  signature, from a rotate workflow whose commit is fixed in the binary and which anyone can call.
- **Paid to a GitHub account.** A bounty is paid to the pull request author's GitHub user id. No wallet, stake or
  address is needed to do the work. The author claims later, to any address, by running one workflow in a
  repository they own.
- **Funded with one comment.** `/knos bounty 20` on an issue, or as a line of a new issue.
- **Paid on merge, in any language.** The default mode pays when a maintainer merges the pull request that closes
  the issue, an hour later unless a maintainer vetoes (the pull request's own description names the issue, so a
  wrong claim can be taken back). `review 0` pays at once.
- **A check on every bounty pull request**, running none of its code: the repo's CONTRIBUTING rules, what its
  history made required, and whether "tests pass" in the description is true at the head commit. This is the Stop
  hook's check at the place an agent cannot remove it.
- **Tests mode, hardened.** Python, Node, Go, Rust, any command, and a black-box runner whose verdict the pull
  request's code cannot touch. Pull request code runs in a sandbox: another user, an empty environment, no network
  during tests. The judge is the code at the workflow's own commit; the calling repository cannot swap it.
- **The real tokens fit.** Tokens up to 8,192 bytes (0.3.9 refused GitHub's real tokens: its limit was 2,048 and
  they are about 2,100 to 2,300). RSA-4096 for GitLab.
- **Tested like something that will not be changed.** 517 Wycheproof vectors, a differential test against OpenSSL,
  a 10,000-step random walk over the escrow, 21 cheating pull requests against three judges
  ([docs/BENCH.md](docs/BENCH.md), [docs/TAMPER.md](docs/TAMPER.md)).
- **A relayer cannot be made to burn money**: it refuses, by reading the chain, tokens that could not pay, before
  spending a fee, and always takes its rent back.
- **The site**: fund, read an escrow, see what is waiting for a GitHub account, claim, and the public numbers with
  outside use counted apart from Knos's own. A JavaScript client with no dependency (`sdk/settle`).
- **`knos mainnet-check`** now checks immutability and provenance. It fails on one line on purpose: no outside audit.
- **Removed**: the admin-registered escrow and its Squads multisig, coordination claims and the edit guard, the MCP
  server, budgets, Knos Pro, the jobs market, Tempo. `knos init` now installs only the Stop hook and removes what
  earlier versions installed.

## 0.3.9 (2 Oct 2026)

AI agent work gets paid only when GitHub's own signature, checked by Solana, proves it passed.

- **FundWithToken.** A bounty can be funded straight from a token account in one instruction.
- **Issuer registry, GitHub and GitLab.** The escrow keeps a registry of OIDC issuers and their keys; GitHub Actions
  and GitLab CI tokens are both accepted, each checked against its own registered issuer.
- **Program version check.** The client reads the deployed program's version and refuses to talk to one it does not
  know.
- **Verified build pin.** The program is built with solana-verify in docker, and `knos mainnet-check` compares that
  hash with the on-chain program hash.
- **Squads vault upgrade authority.** The devnet upgrade authority is the Squads v4 vault
  `4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo` (2-of-3, 300 s time lock). All 3 members are Knos keys today, so
  `knos mainnet-check` adds two gates that fail until an outside signer joins and the time lock is at least 24 h
  ([docs/SECURITY.md](docs/SECURITY.md)). Mainnet stays locked.
- **IDL on chain.** The escrow's IDL is published as a Program Metadata account.
- **Sibyl store in the judge.** The judge reads the repo's rules and past rejections from the Sibyl store before it
  rules.
- **Claims check.** `python scripts/claims_check.py` checks every number in the README's opening, the home page hero,
  the submission and the pitch script against devnet, GitHub or a file in the repo, and fails on any sentence with a
  number it does not cover. CI runs it on every push.

## 0.3.7 (1 Oct 2026)

AI agent work gets paid only when GitHub's own signature, checked by Solana, proves it passed.

- **GitHub's proof, verified on chain.** The escrow verifies GitHub Actions OIDC tokens itself.
  - The signature check is RSA-2048, done in Montgomery form in two transactions (1,148,681 and 1,193,853 compute
    units). The token is written through a buffer account first.
  - The program checks the issuer, the pinned `prove.yml` tag (`job_workflow_ref`), the repository, the ref and
    `aud = knos:<job>`. Each proof can be used once.
  - GitHub's 4 JWKS keys are registered on devnet; r2 is checked once, when a key is registered.
  - A "github" job pays the worker only on a verified token. With no proof by the deadline, the buyer gets the price
    back plus the claim stake.
  - Tests cover tampered claims and signatures, wrong keys, workflows, audiences, repositories and refs, and replay,
    plus a 10,000-step fuzz with 0 violations.
- **`prove.yml`, a reusable workflow.**
  - Job 1 runs `.knos/proof.toml`, read from the base branch, on the PR head with no token.
  - Job 2 runs no PR code. It mints a token for `knos:<job>` and calls `knos prove`.
  - `knos proof run` runs a repo's checks. Knos proves its own work with `prove-demo.yml`.
- **Front door, nothing to install.** The home page is "Paste an agent PR". Your browser asks GitHub directly and shows
  in 0.95–2.5 s whether the PR's "tests pass" is true at its head commit, along with that agent's record. "Protect
  this repo" opens GitHub's new-file page with the workflow already filled in: 2 clicks. The Agent PR Index (per
  agent: claimed green, actually failed) is rebuilt every 30 minutes into the Pages site, with no data commits, and
  each batch root is attested on devnet SAS.
- **Bonded PR bounties.**
  - A maintainer funds an issue; a 0 bounty is allowed.
  - An agent claims it with a stake, and the proof transaction pays the bounty plus the stake back.
  - The escrow takes several mints (AddMint).
  - A devnet-only faucet mints test USDC from a program-owned mint.
  - The web wallet is a passkey guarding a throwaway devnet gas key, topped up by `POST /gas`.
- **Sibyl on the money path.** Before a proof is minted, the checks recall the repo's rules from Sibyl:
  CONTRIBUTING.md, plus past rejections. `lint` fails a PR that breaks one and cites the line; `learn` makes each
  flagged rule a required check.
- **Compared against** CodeRabbit, Algora, Vouch, Virtuals ACP and Upwork ([docs/COMPARE.md](docs/COMPARE.md)).
- **Fee:** 2.5% everywhere. The pitch is Solana only.
- **Next** (not in 0.3.7):
  - LazorKit's paymaster with a call into the Knos escrow (untested; the gas-key wallet is used instead);
  - a Squads upgrade authority with a timelock, a solana-verify build, and the IDL on chain;
  - agent verdicts written to Solana Agent Registry reputation;
  - list 257-byte multi-mint jobs in the web app's "My jobs".

## 0.3.6 (1 Oct 2026)

AI agent work gets paid only when someone other than the agent proves it.

- **The escrow enforces proof (live on devnet).**
  - When a job names a verifier, the buyer cannot reject it; only the verifier (pass or fail) or the deadline settles
    it.
  - At the deadline, delivered work with no verdict pays the worker, and undelivered work refunds the buyer
    (`knos jobs settle`, which anyone may run).
  - A buyer cannot claim their own job.
  - A claim takes a worker stake (10% of the price, at least 0.1 USDC). The stake comes back on delivery and goes to
    the buyer if the claim times out.
  - Every settle closes the job account and returns its rent to the buyer.

  Every old attack test passes, plus one test per rule, along with a 10,000-step fuzz with 0 violations.
- **Built, tested and deployed in Actions** (`.github/workflows/program.yml`): a pinned, cached agave runs
  `cargo build-sbf`, the attack tests and the fuzz. Then, from main only, it upgrades the devnet escrow and prints the
  upgrade signature and the program hash. Nothing in the release path depends on a local machine.
- **The fee is max(2.5%, 0.05 USDC)** (it was 5%). A new admin instruction, LowerFee, can only lower the fee, never
  raise it.
- **Always on:** the reference worker and verifier run in public Actions every 5 minutes and settle jobs past their
  deadline. RPC calls back off on 429.
- **Measured on devnet** (1 Oct 2026):
  - A job posted from the web app was paid by its verifier 167.9 s after first visit, with nobody clicking accept.
  - A delivery that broke a recalled "no emojis" preference was rejected, citing line 2, and the buyer got 1.00 USDC
    back in the same transaction.
  - Upgrade `4Ze3XMVV…oidiYpQD`; program sha256 `92bdd991…70be71`.

- **A verified job's delivery is one envelope:** a copy sealed to the buyer and one to the verifier, both checked
  against the digest the chain commits to. The verifier reads exactly the work the buyer gets.
- **ERC-8183 on Tempo** ([docs/ERC8183.md](docs/ERC8183.md)): KnosEscrow on Moderato
  (`0x8B913C5946a4C1CD95089D7a563dB864d46b694E`) implements the ERC-8183 job interface with the Knos verifier rule.
  The evaluator can never be the provider, only the evaluator or expiry settles a funded job, and `claimRefund` after
  expiry cannot be blocked. The fee is 2.5%.
- **For builders:**
  - an Anchor-format IDL (`programs/knos_escrow/idl.json`, checked against the Python builders);
  - `@knos/escrow` (`sdk/escrow`, unpublished), with instruction builders tested byte for byte;
  - a CPI example (`examples/cpi_escrow`): an on-chain agent that claims and delivers a job.
- **Next:** move the devnet upgrade authority to a Squads multisig with a timelock, and have program.yml propose
  upgrades to it.

## 0.3.5 (1 Oct 2026)

AI agent work gets paid only when someone other than the agent proves it. The Stop hook for coding agents is the
free way in.

- **A verifier, wired.**
  - `knos jobs post --verify knos|KEY` names who decides.
  - `knos verify JOB` (or `--all --once`) re-runs the brief's checks: code briefs in a clean venv, plus the buyer's
    preferences recalled from Sibyl. It commits the evidence root and signs a pass or a fail. A delivery that
    contradicts a recalled preference fails, and the failure cites the line.
  - The web post form has a "Verified by" choice; the Knos reference verifier is the default.
- **Always-on worker workflow** (`.github/workflows/worker.yml`): the reference worker and verifier in public
  Actions. It finds the live relay from the devnet pointer memo. It runs by hand until its key secrets are set.
- **CI under 5 minutes** on pull requests:
  - uv with a cache, `pytest -n auto`, and the Solana CLI pinned and cached;
  - 10 property rounds on PRs (200 nightly);
  - mac and windows on 3.12 only, with Windows in two shards (the full matrix runs nightly);
  - superseded runs are cancelled.

  Per job, chain went from 829 s to 169 s, macOS 3.12 from 184 s to 68 s, Ubuntu 3.12 from 74 s to 39 s, and
  Windows 3.12 from 382 s to two parallel halves.
- **COMPARE.md** compares Knos with Upwork, Fiverr, Gitcoin, Virtuals ACP / ERC-8183, Devin and Codex on fee, time
  to payment, refund, who verifies, accounts and cost, from their own pages read 1 Oct 2026.
- **The pitch** is one sentence. Team claims, budgets, Pro and x402 stay in the code and in the reference docs.
- **Next** (not in 0.3.5):
  - **Escrow 0.3.5 is written but not shipped.** Its rules:
    - the buyer cannot reject a job that names a verifier;
    - delivered work with no verdict pays the worker at the deadline;
    - a buyer cannot claim their own job;
    - claims need a worker stake and time out;
    - every settle closes the job account and returns the rent.

    The program could not be built or upgraded on devnet in this release window, so devnet still runs the 0.3.4
    escrow. Until then, a failed verdict on devnet is a refund at the deadline.
  - Turn on the always-on worker's 5-minute schedule (it needs the worker and verifier key secrets), and show the
    measured pickup time on the web.
  - Measure first visit to first paid devnet job (target: under 60 s).
  - Map ERC-8183 onto the Tempo contract with the verifier rule.
  - An IDL, an npm `@knos/escrow`, and a CPI example.
  - Move the devnet upgrade authority to a Squads multisig with a timelock.

## 0.3.4 (1 Oct 2026)

AI agent work counts only when Knos proves it: your coding agent cannot say done, and a hired agent cannot get paid,
until the proof is real.

- **Proof hook.** `knos init` adds a Stop hook to Claude Code and Codex. It reads the agent's last message, and when
  that message claims something Knos cannot prove, the agent is not allowed to finish. Knos runs every check itself:
  - tests in a fresh venv;
  - every job of every CI run for HEAD (`gh run view`);
  - the PyPI version live;
  - each URL answering 200;
  - deleted files gone;
  - the commit author, with no AI trailers;
  - anything in `.knos/proof.toml`.

  After 3 blocks on unchanged evidence it lets the agent stop, with a warning. A PreToolUse guard refuses overwriting
  a file the agent never read, and deleting outside the repo.
- **Sibyl keeps each repo's proof history.** `knos proof learn` turns a past false "done" into a check that is
  required from then on, and `knos proof lint` flags claims the evidence contradicts. Replaying releases 0.3.0 to
  0.3.3:
  - with Sibyl, Knos blocks 0.3.1 and 0.3.2, whose CI failed, and passes 0.3.0 and 0.3.3;
  - with a null store and local pytest alone, it passes all four.
- **Paid on proof.** A job can name a verifier key. When the proof passes, the escrow releases with no human step;
  when it fails, the escrow refunds after the deadline; a dispute re-runs the checks. Every proven "done" can get a
  devnet SAS receipt (the Merkle root of its evidence) and a receipt page (`web/receipt.html`).
- **Guarded launch.** The escrow has a per-job cap and a pause switch. Mainnet stays locked.
- **Economics.** The minimum job is 1 USDC, and the fee is max(5%, 0.05 USDC). Measured margin per 1 USDC job: $0.049 on devnet and $0.050 on Moderato ([docs/ECONOMICS.md](docs/ECONOMICS.md)).
- **Security.** A threat model ([docs/SECURITY.md](docs/SECURITY.md)) and a nightly fuzz of 10,000 escrow steps in LiteSVM checking conservation, no double payout and no stuck funds.
- **Market number.** 18.2% of agent PRs that say tests pass had failing CI at that commit ([docs/BENCH.md](docs/BENCH.md)).
- **One benchmark source.** Every benchmark number in the docs is generated from `docs/bench.json`, and a test fails
  on drift. This fixes the 14→22 and 19/24 figures that disagreed between pages. Modelled baselines are labelled as
  models.
- **Licence.** Everything that can be judged is MIT: the hooks, the proof engine, the escrow, the SDKs, the receipts
  and the web app. Only the paid conveniences in `src/knos/pro/` are FSL-1.1-MIT.
- **Next** (not in 0.3.4):
  - `knos mainnet-check`, a solana-verify verified build, and moving the devnet upgrade authority to the Squads
    multisig (the multisig exists; the transfer has only been simulated).
  - Publish the Claude Code plugin marketplace and MCP registry listings, and fix the plugin's silent failure when
    `knos` is not on PATH.
  - A close instruction so settled job accounts return their rent.
- **Disclosure.**
  - Knos 0.1.0–0.1.8 (shared local memory for coding agents, with topic claims) was written and released 1–7 Sep
    2026, before 14 Sep, and won the Sibyl Labs hackathon.
  - Everything from 0.2.0 on was built from 29 Sep 2026.
  - Scope freezes on 8 Oct 2026.

## 0.3.3 (Oct 2026)

- **Installs everywhere again.** x402 payments on Solana are built in with solders (the same `exact` transaction the
  reference x402 client builds), so `knos[agentpay]` no longer pulls `solana<0.40`, which pinned solders below 0.28 and
  broke every install of `.[dev]` in 0.3.1 and 0.3.2.
- **Sibyl Pro comes with every payment.** Pro, a Team seat, or the 5% fee on an accepted job: the paying wallet has
  Sibyl Pro for the 30 days after that payment, bought by Knos from it (`knos.sibyl_pro`; simulated on testnets,
  built and locked on mainnet). Pro is 22 USDC / 30 days (208 / year) and Team 32 per seat, Sibyl Pro included. The
  second checkout, `sibyl upgrade` prompts and the $12 threshold are gone; `knos jobs sibyl` shows yours.
- **Recall is used.** Session ingest indexes every turn for `knos.recall`; MCP `search` and `sdk.Knos.recall` return
  what it finds; the reference worker remembers its deliveries and recalls similar past jobs into each prompt.
- **`knos work --tempo`** takes jobs on the Tempo escrow (Moderato) too, including the web app's passkey jobs.
- **The web app reads the chain itself.** Jobs, agents and payouts come from devnet in the browser, and post, accept
  and reject transactions are built there, so Pages works with no Knos server; the relay's current address is a
  devnet memo the app reads. The network view separates Knos's own task feed from everyone else's jobs.
- **Removed:** `knos serve` and `knos init --remote` (the 0.2 team server; teams are the Solana registry), the Sibyl
  bundle and second checkout, tier detection, TRACTION, and functions nothing called.
- Acceptance benchmark with a live Gemini worker (gemini-3.5-flash-lite): 19/24 with Sibyl memory, 1/24 without.

## 0.3.2 (Oct 2026)

- Web app: **pay with a passkey on Tempo**. No wallet, extension or seed phrase: a passkey on the device signs Tempo
  testnet transactions (viem `viem/tempo` WebAuthn accounts), Tempo's faucet funds it, and the job goes into the Knos
  escrow contract on Moderato. My jobs shows Tempo jobs with accept and reject.
- `knos.recall`: no-LLM recall over Sibyl. LongMemEval_s held-out (370 questions): 96.8% top-10 (was 81.5%),
  assistant-said 88.4% (was 51.8%), preferences 83.3% (was 50.0%), median 5,656 tokens.
- Reference worker: Gemini uses the native API with retries and a lite fallback (`gemini:gemini-3.8-flash`).

## 0.3.1 (Oct 2026)

Knos becomes the work network for AI agents: hire any AI agent in one step and pay only for work you accept.

### Jobs, paid only on acceptance
- `programs/knos_escrow`: a native Solana escrow program. Post (the price moves into a program-owned vault), claim
  (exactly one worker), deliver (the sealed deliverable's sha256 on chain), accept (95% to the worker, 5% fee, one
  transaction), reject inside the review window (full refund), release by anyone after a silent review window, refund
  after the work deadline. Deployed on devnet at `GwmbMFvyHHwHug5em9dv26oXz2zTgXKGsNdrBxPayRPq`. Tested in the Solana
  runtime (LiteSVM): 11 attacks, edge paths and a 1,000-step conservation fuzz, in about a second.
- `contracts/KnosEscrow.sol`: the same state machine on Tempo, with a guardian that can pause new posts and only ever
  lower a per-job cap (mainnet: 500 USDC until an external audit). Foundry tests incl. a 1,000-run fuzz; deployed on
  Moderato at `0x888d39bB186cC718481E98080Bdb5fd8Df27Ab49`; a Python client (`knos.jobs.tempo`).
- `knos jobs post|list|get|accept|reject|release|refund|prefs|perks|stats|serve|relay` and `knos work`, the reference
  worker: polls, claims, does the job with the operator's own model key (Anthropic, OpenAI, OpenRouter, Groq, Gemini,
  or the operator's own Claude Code / Codex), runs the brief's checks and the buyer's shared preferences locally, and
  never delivers work that fails them.
- Briefs and deliverables live on a content-addressed relay anyone can run; only hashes are on chain. Deliverables are
  sealed (PyNaCl sealed boxes) to the buyer's key, or to a key the web app derives from a wallet signature.
- MCP tools `post_job`, `find_jobs`, `claim_job`, `deliver_job`; Python `knos.jobs.api.serve(agent)` and TypeScript
  `Knos.work(agent)`: a worker in under 10 lines.
- Solana Actions (Blinks) for posting and reviewing a job; `knos jobs serve` hosts them with the network API, the
  relay and the web app on one port.
- `web/`: a static app (wallet-standard): hire, my jobs (open sealed work in the browser, accept, reject), every
  agent's record recomputed from job accounts, and the network. Dark and light.
- `knos bench jobs` (`--live` devnet, `--tempo` anvil).
- Settlement waits for `finalized` where it is within 2 slots of `confirmed` (measured, devnet today), otherwise
  `confirmed`; `knos doctor` says which.

### Memory that makes work accepted
- A buyer's standing preferences are captured as Sibyl `preference` entities, one tenant per wallet, on the buyer's
  machine, and shared with a worker only per job (`--share-memory`). On the 24-job acceptance benchmark: 72 of 72
  preferences recalled (was 54) and 22 of 24 jobs accepted (was 14). Held-out capture set: 21 of 24, no false hits.
- Brief lint before money moves; Sibyl Pro paid by Knos for every $12 of a buyer's fees (checkout simulated in this
  release: Sibyl's partner checkout is not live).

### Tests
- The default suite runs in under 3 minutes on 4 cores (`-n auto`); validator, live-network and long property runs
  are marked `chain`, `live` and `slow`.

## 0.3.0 (Oct 2026)

Knos becomes the coordination and memory layer for the agent economy: who works on what (claims), what is known
(Sibyl memory), what each agent may spend (budgets the chain enforces) and who did what (records anyone can verify).

### Teams on Solana, with no server
- `knos team create|add|remove|leave|status`, `knos team key export|import`. A team is one Solana Attestation Service
  credential (`knos-<16 hex>`), with its own schemas `knos.claim.v1`, `knos.renew.v1`, `knos.member.v1` and
  `knos.record.v1`, and `.knos/team.json` committed to the repo.
- Claims across machines and vendors. A claim is an attestation whose address comes from a salted hash of the unit,
  so two creates cannot both succeed. Overlapping units are ordered by (slot, address). Closes are
  compare-then-close with Lighthouse. Renewals never re-create. Lapsed claims are swept by chain time only.
- Property-tested on a local validator running the devnet-deployed SAS and Lighthouse: five signers, overlapping files
  and folders, a lagging RPC, dust on claim addresses and crashing claimers. Zero double winners and zero blocks of a
  winner (see docs/BENCH.md).
- Nothing in plaintext on chain: paths, repo, names and descriptions are salted hashes or sealed boxes.
- If the chain cannot be reached, edits go ahead locally with a one-line warning. Knos never blocks work on an
  outage.
- `knos mirror`: a background copy of the team's claims, so the guard reads a local table and not the chain.

### Guards everywhere
- Codex: a `PreToolUse` hook on `apply_patch` and Bash writes (`~/.codex/hooks.json`, and `.codex/hooks.json` in
  the repo).
- A git pre-commit and pre-push guard for anything no hook sees. Edit-time for hook tools; commit-time for raw shell
  writes.
- `knos init --team` commits the guard with the repo: `.claude/settings.json` hooks (cloud sessions run these), the
  plugin at project scope, `.codex/hooks.json` and the git hooks. `init --undo` restores every file byte for byte.
- A template for the Copilot cloud agent (`.github/hooks/knos.json.example`). One answer per `tool_use_id` when the
  plugin and repo hooks both run.
- Refusals end with "(Knos)".

### Budgets the chain enforces (Pro)
- `knos budget set <agent> 5/day --chain tempo` authorizes a Tempo AccountKeychain access key with a periodic limit
  and a single allowed call (`transferWithMemo`). `knos budget show` reads `getRemainingLimitWithPeriod`.
  `knos budget revoke` calls `revokeKey`.
- `knos budget set <agent> 20 --chain solana` sets an SPL delegate on a per-agent vault.
- Root keys are encrypted at rest (scrypt N=2^17 + AES-256-GCM). Passphrases are read only at an interactive terminal,
  never inside an agent or CI.

### Records
- One `knos.record.v1` per agent per day: counters plus a Merkle root over its salted events and new Sibyl journal
  entries. `knos agent record <agent>` checks them against the chain.

### Sibyl, load-bearing, and bought in the same command
- `knos learn` (Sibyl's self-learning into team playbooks under `.knos/playbooks/`, imported by every machine) and
  `knos lint` (Sibyl's linter, plus a cross-agent contradiction check built on Sibyl's multi_record search). Both
  call only `MemoryClient`, and on the free tier they say how to get Pro.
- Memory moved into Sibyl's own store (`~/.sibyl-memory/memory.db`, one tenant per repo), where Sibyl's account-wide
  free cap counts it. 0.2 stores are migrated once and kept as `memory.db.migrated`.
- `knos pro buy` then gets Sibyl Pro through Sibyl's own `sibyl upgrade` if Sibyl says you are on the free tier, and
  skips it for Pro and Staker accounts.

### Agents beyond code
- `knos.sdk`: `claim`, `release`, `remember`, `recall`, `budget`, `record`, with generic units (`task:`, `market:`,
  `wallet:`).
- `examples/langgraph_team.py`: two LangGraph agents on Sibyl's own `BaseStore`, never working the same task.

### Public numbers
- `scripts/network_stats.py` and the `network` workflow publish every Knos team on Solana to GitHub Pages,
  split by devnet and mainnet.
- `knos doctor` shows what is guarded and what is not.

## 0.2.1 (30 Sep 2026)

- macOS: a `ctags` that is not Universal Ctags (macOS ships BSD ctags) is no longer used; knos reads the code
  itself, so code-structure answers work on a stock Mac.
- Windows: a licence that expires "now" counts as expired (the clock can return the same instant twice).

## 0.2.0 (30 Sep 2026)

One product: shared memory, file claims and an edit guard for every coding agent on the machine, with Knos Pro for
spend and payments. Built 29 Sep - Oct 2026 on top of 0.1.8.

### Fixed (each has a regression test in `tests/test_v1_fixes.py`)
1. `knos point` deleted the store (and left its -wal/-shm files). Reading is now incremental and never deletes. Starting
   over is `knos reset --yes`, which backs up first.
2. The guard could block the agent holding a claim: the MCP server and the hooks disagreed on who an agent was. One
   identity now, (host, session), shared by MCP, hooks and CLI. The session hook records the session against the host
   process, and the server finds that process on Windows, macOS and Linux.
3. `done` released every claim in the repo. It releases only your own now; `knos done --all` asks first.
4. Claims matched words, so "update the readme" blocked `scripts/update_deps.py`. Claims are now path globs taken in
   one transaction (exactly one winner). A claim naming no resolvable file or symbol is advisory and never blocks.
5. Answers about claimed work were withheld, and `about` leaked them anyway. Nothing is withheld now: answers are
   annotated with who holds which files.
6. The server answered from the last repo anybody pointed at. It answers for the repo it runs in, or says there is
   none.
7. `knos demo` crashed, and errors printed as tracebacks. The console script is `main()`, and every error is one line
   with the fix.
8. `knos remember` said "Noted" when a full store had written nothing. It says so and exits 1.
9. `connect` crashed on some configs and pinned an interpreter path. `knos init` replaces it: it writes the `knos`
   command, backs up every file, never overwrites a file it cannot parse, runs a self-test, and undoes byte for byte.
10. Cursor's guard ran on reads. It guards edits only. The claim that "a pull request is told" is gone.

Also fixed:
- Cursor turns are dated when they were said, not by the database's mtime.
- A session in a parent folder no longer leaks into a child repo.
- Claude Code project folders with `.`, `_` or spaces in the path are found.
- A re-taken claim no longer counts as a new one.
- A search no longer rescans PATH for ctags each time; under WSL that was ~400 ms.

### Added
- `knos init [--undo] [--hosts]`, including Codex (`~/.codex/config.toml`).
- Codex sessions are read into memory.
- `knos claim -p`, `knos reset --yes`, `knos compact`, `knos board`, `knos bench`.
- Knos Pro (`src/knos/pro/`, FSL-1.1-MIT):
  - the spend meter (`knos spend`, from Claude Code and Codex logs);
  - one cap across tokens and agent payments (`knos budget`), enforced by the edit guard;
  - `knos pro buy` with Solana Pay (USDC) or Tempo (`transferWithMemo`), verified on chain;
  - signed licence codes;
  - agent budget wallets (`knos budget fund/agents/sweep`);
  - agents paying APIs over MPP (Tempo) and x402 (Solana) with `knos pay` and the `pay` tool.
- Knos Team: `knos serve`, a self-hosted server for claims, notes and one pooled spend cap across machines, joined with
  `knos init --remote`.
  - Seat tokens are stored as hashes.
  - Host names are checked against an allow-list, and it binds to loopback by default.
  - Every error comes back as JSON.
  - Machines fail open when the server is unreachable.

### Removed
The plane (gateway, control plane, on-chain program and TypeScript agents), withholding, overrides and stand-downs,
`knos changed/reconsider/held/at/verify/why/receipts`, the GitHub Action, and the Knos-own store: Sibyl is the only
memory store.
## 0.1.x (unreleased notes kept for history)

The length of a claim is learned. Every hold used to be thirty minutes,
whoever made it, which is wrong in both directions: an agent that closes its
work loses it mid-task, and an agent that claims and dies blocks the file for
the full half hour every time without the store getting any wiser. The hold is
now a function of the share of claims that agent has actually closed, read out
of the COLD journal - fifteen minutes for an agent that never finishes, forty
five for one that always does, and the old flat thirty for anyone knos has
seen fewer than twice. `knos who` shows the table.

Over one seeded working day with four agents, two of which mostly do not
finish: 29% less time blocked on work nobody was doing, in
`docs/evidence/contention.json`.

Fixed: renaming a claimed file walked straight past the guard. `git mv
risk_guard.py helper.py` and the edit went through, because the guard matched
the path's name against the claim's words. It now recognises the rename -
from git when git has spotted it, and otherwise by comparing the new file
against the committed bytes of the one that vanished. The first version of
that fix called every new untracked file a rename of the missing one, which
refused honest work with a sentence that was not true; both directions are
pinned in `tests/test_rename_bypass.py`.

The README was 1,058 lines and a 43 minute read. It is now about 130 lines,
and the long version moved unchanged to `docs/GUIDE.md`.

## 0.1.8

`knos demo` shows cold-start recall rather than describing it. A separate
interpreter, handed nothing but the repo path, prints its own pid alongside the
repo's commit hash and the wall clock and then reads back what an earlier
process wrote; the next beat deletes the store and every refusal stops. Recall
across a process boundary was always true and was never on screen, so the
strongest half of the argument rested on prose.

This is why the release exists. 0.1.7's README told you to run `knos demo` and
then described a beat that release did not have.

`scripts/collide.py` counts double-grants instead of asserting exclusion.
Sixteen operating-system processes reach for one topic at the same instant,
eight rounds: 0 double-grants in 128 attempts, every refusal naming the agent
actually holding it. The ablated condition is sharing rather than the file -
deleting the store proves nothing, because the next agent recreates it and the
lock works again. Give each agent its own memory instead, which is what an
agent has today, and all sixteen take the same work.

## 0.1.7

`knos demo` runs the whole product on a throwaway repo in about a minute and
then deletes its memory, so the last thing on screen is every refusal
stopping. Every line is a real call rather than a transcript, and the tests
assert the live values appear.

The memory now decides whether money moves. `knos.gate` is asked before any
purchase and answers one of four ways: it refuses to spend while somebody
holds the topic, refuses while the work rests on a reversed decision, serves
what was already bought for nothing, and only otherwise buys. Measured over an
ordinary day of five agents: 5.41x more expensive without the store.

`knos changed` reverses a decision and holds everything reasoned from it - the
edit is refused and the purchase is refused - until `knos reconsider` says
somebody looked. The old wording is archived rather than dropped. `knos held`
lists what is waiting.

`knos restore` rebuilds a repo's decisions from the `.knos/decisions.md` it
commits, so a fresh clone on a machine that has never run knos carries them.
Claims are deliberately not restored: a hold rebuilt elsewhere would assert a
collision that is not happening.

Also: the ablation grew to twelve arms with numbers in
`docs/evidence/ablation.json`, and a judge guide, verification, architecture,
memory-model and evidence ledger under `docs/`.

Fixed: the gate served the wrong asset. It searched rather than reading the
exact topic, so a store holding `market brief: BTC` answered a request for
`market brief: ETH` for free. Saving a cent by returning something true about
a different subject is worse than paying.

## 0.1.6

The bot never answers with silence. Anything it does not recognise - a typo'd
command, or a person saying hello - now gets a sentence and the list of what
does work. Falling off the end of the handler was indistinguishable from a
dead process.

A failed subprocess is no longer returned as though it were an answer. stdout
and stderr were collected into one string, so a Python traceback reached the
chat as content; they are separate now and the exit code decides which the
reader sees.

No path prints a seller's payload verbatim any more: the last fallback in the
formatter used to dump the raw body when it met an unfamiliar shape.

A reply cut at Telegram's length limit says that it was cut, instead of
stopping mid-word.

## 0.1.5

`knos guard --install` refuses the edit, not only the answer. Claude Code,
Cursor and OpenCode each run a hook before a tool call, and a hook can say no,
so an agent about to edit work another agent has claimed is stopped and told
who holds it. It also reads the rules this repo already gave knos and enforces
the ones a machine can check — a prohibition with a path in backticks. Off
until you run it, and `knos guard --uninstall` takes it back out. It fails
open: an unreadable store allows the edit.

`knos export --to <path>` writes the shared record where a repo already keeps
its decisions, instead of insisting on `.knos/decisions.md`. Anything knos
already reads back is still read back, and `knos export` says so plainly when
the path you chose is not.

The Claude Desktop extension now uses the `uv` runtime, so installing it no
longer asks you to find and paste a Python path.

## 0.1.4

Claims are a compare-and-swap: two agents reaching for the same work in the
same second cannot both hold it, and the loser is told who does. A full store
now refuses a claim in words instead of dropping it silently. `knos status`
reports the claims held and says FULL at 5 MB. The pull request Action reports
decisions as well as claims, takes a `github-token` input, and documents its
`pull_request_target` safety. `pytest` runs the critical path in about 25
seconds; `pytest -m ""` runs all of it.

`knos --version` prints the installed version, the same number the MCP
handshake reports — one value, read from package metadata, so the two cannot
drift apart.

`knos export` keeps the shared file to the readable part of a note. What an
agent pays for is a whole API response and the store still holds all of it,
but a decision record other people commit is not the place for a JSON body
and a receipt.

`.knos/decisions.md` is no longer ignored. The file the Action reads out of a
checkout could not be committed in this repository, which meant nothing here
could carry the record it asks other repositories to carry. The store and the
keys stay ignored.

The agent (`agent/bot.ts`) and the x402 payer (`src/knos/buy402.py`) are in
the repository. The README linked both and neither was there, so a clean
clone could not run what it was told to run.

**Use `drexthealpha/Knos/action@v0.1.4`.** `v0.1.3` was tagged before these
Action changes and serves the older file.

## 0.1.3

Declare MCP tool annotations (read-only, destructive, idempotent, open-world) on `search`, `about` and `remember`, and report the installed version in the handshake.
