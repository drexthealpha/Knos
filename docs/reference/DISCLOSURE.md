# Disclosure

This page says what was built when, what came from elsewhere, and what does not exist yet.

The repository's git history shows all of it, and [CHANGELOG.md](../../CHANGELOG.md) has every release.

## What was built when

The short form, by date. Times are UTC and are the commits' own (`git log`); a release's date is its release
commit's.

| when (UTC) | what |
|---|---|
| 1 Sep 2026 | the public repository's first commit |
| 1 to 7 Sep 2026 | Knos 0.1.0 to 0.1.8: shared local memory for coding agents, a different product |
| 7 to 12 Sep 2026 | more work on that product, never released |
| 13 Sep 2026 | two experiments begun outside this repository; none of their code is here |
| 14 to 29 Sep 2026 | automatic evidence commits, and 3 by hand for Knos 0.1; the two experiments ran until 28 Sep |
| 30 Sep 2026, 03:07 | Knos 0.2.0 (commit `54ce98a`), then 0.2.1 at 03:43 and 0.3.0 at 19:19 |
| 1 Oct 2026 | Knos 0.3.1 (08:57), 0.3.2 (09:55), 0.3.3 (12:06), 0.3.4 (15:12), then 0.3.5 to 0.3.7 |
| 2 Oct 2026 | Knos 0.3.9 (04:56), 0.3.10 (09:51: the first deployment on devnet), 0.3.11 (14:10, commit `f3dfd3d`) |
| 3 Oct 2026 | three pull requests by another account merged; Knos 0.3.12 (16:13: the second deployment) |
| 4 Oct 2026 | Knos 0.3.13 (09:02), Knos 0.3.14 (21:46, commit `6eb81dd`) |
| 5 Oct 2026 | Knos 0.3.15 (10:49, commit `72511b3`) and 0.3.16 (23:47, commit `50ecb05`) |
| 6 Oct 2026 | Knos 0.3.17 (20:00, commit `f03ec51`) |
| 7 Oct 2026 | Knos 0.3.18 (07:40, commit `f8bcd9d`) and 0.3.19 (15:47, commit `155b570`) |
| 8 Oct 2026 | Knos 0.3.20 (01:04, commit `fb77f4f`); the interface crates published on crates.io and the JavaScript client on npm (`npm install knos-settle`, [knos-settle](https://www.npmjs.com/package/knos-settle) 0.3.20) |
| 8 Oct 2026 | Knos 0.3.21 (09:59, commit `042b7dea`) and 0.3.22 (19:28, commit `c4350c97`) |
| 9 Oct 2026 | Knos 0.3.23 (04:59, commit `852e6135`) and 0.3.24 (13:20, commit `fb4217c1`) |
| 10 Oct 2026 | Knos 0.3.25 (02:43, commit `095f52ae`) |

To list the releases with their times from a full clone:

```
TZ=UTC git log --date=format-local:'%Y-%m-%d %H:%M' --format='%ad %h %s' | grep ' Knos 0\.'
```

## Before Knos 0.2

- **Knos 0.1.0 to 0.1.8**, 1–7 Sep 2026: a shared local memory for coding agents, with claims on topics and a guard
  on edits, built on Sibyl. It is a different product from the one here.
- Almost none of Knos 0.1 is in the tree. Its memory server, claims, edit guard, payment gate and integrations were
  removed in 0.2.0 and 0.3.10. They remain in the git history.
- One dependency carries over: Sibyl's memory client, which the referee and the local hook still use.

## The releases since

- **29 Sep – 2 Oct 2026, Knos 0.2.0 to 0.3.9** (first commit 30 Sep). 0.2.0 was built on top of 0.1.8. These
  versions tried claims enforced at edit time across agent vendors, agent budgets, a jobs market with held money,
  the Stop hook, the Agent PR Index, and a first payment program that verified GitHub's signature on chain but whose keys
  and workflows were registered by an admin. They are kept as they stood at 0.3.9 in
  [the tag `archive/labs` of drexthealpha/Knos](https://github.com/drexthealpha/Knos/tree/archive/labs), unmaintained. The Stop hook, the index and
  the referee are here.
- **Knos 0.3.10** (2 Oct 2026): the first deployment. Its two programs have no admin (`knos-oidc`, `knos-pay`), were deployed
  on devnet with no upgrade authority, and nobody can change them; payment to a GitHub account; the claim; the merge and tests modes with a veto
  window; the gate on every bounty pull request; the sandboxed referee for Python, Node, Go and Rust and its
  black-box mode; the relay; the JavaScript client; the site.
- **Knos 0.3.11** (2 Oct 2026): no change to the programs. A merge pays only when the pull request's claims hold
  at the merged commit; an agent's pull request pays the person who ran it; the check alone, with no money;
  `knos claim`; `knos mcp`; the interface crate, the IDLs and the npm tarball; every action pinned to a commit.
- **Knos 0.3.12**: the second deployment (`programs-v2`). Terms fixed at funding; no veto; payment straight to a
  wallet, in the transaction that verifies the pay token; balances funded from a wallet and spent by comment; classic
  and Token-2022 mints; signing keys that wait a day and expire; a guardian that can revoke a key or pause new
  funding for at most 7 days. It is upgradeable only through a multisig with a public 8-day delay, until an
  outside review. The first deployment keeps working for jobs funded on it.
- **Knos 0.3.13**: an upgrade of the second deployment through that multisig, and two new programs. Work orders in
  place of single bounties: each with a token account of its own, the fee paid by the funder on top of the amount,
  funding of any public issue from a wallet, standing orders, splits between payees, holdbacks and warranties,
  cancellation with notice, organisations as payees, and a payment that can be assigned. Attestation after a merge
  from a repository of the seller's own. `knos-meter`, which counts evaluations GitHub signed and holds no customer
  money. `knos-passkey`, a wallet made from a passkey. Signing keys of any RS256 issuer in the verifier. A policy
  file, statements and exports, and screening of payout addresses. Drills of the recovery paths on the deployed
  bytes.
- **Knos 0.3.14**: a correction and what follows from it. The payment program build that 0.3.13 proposed let one pay token
  pay a second order funded later for the same issue; it was found while the proposal waited out its time lock (then 48 hours), before the
  build ran, and that release withdrew that proposal and proposed a corrected one, in which every signed token is
  accepted once by one marker rule ([SECURITY.md](SECURITY.md), section 15). Also: overflow checks in release
  builds of every program; fee tiers in place of one rate, and a devnet cap of 100,000 per order; a batch mode of
  the meter with a seller's own count; funding from a passkey wallet; orders of GitLab projects; a hermetic referee
  by image digest; a feed of upgrade proposals; and the documents [INVARIANTS.md](INVARIANTS.md) and
  [GOVERNANCE.md](GOVERNANCE.md).
- **Knos 0.3.15**: no program changed. Clients, workflows, the site, documents and tests only;
  [CHANGELOG.md](../../CHANGELOG.md) has the list. The page on who builds Knos ([TRUST.md](../TRUST.md)) was written
  for it.
- **Knos 0.3.16 to 0.3.26** (5 to 10 Oct 2026): [CHANGELOG.md](../../CHANGELOG.md) has each list.

The story in short: we measured how often an agent's pull request said "tests pass" while a check had failed
(17.8% of repositories, on the first such pull request; 9 of 241 merged ones had a failed test, build, lint or type
check).

We then tried several products around that fact between 29 Sep and 2 Oct 2026, and kept the one that fixes it.

The commit history shows those turns.

`git log` and [CHANGELOG.md](../../CHANGELOG.md) are the dated record.

## Ideas and code from elsewhere

- **MergePay** ([github.com/codeswithroh/mergepay](https://github.com/codeswithroh/mergepay), first commit 23 Sep
  2026, on Arc mainnet since 24 Sep 2026) verifies GitHub's OIDC signature on an EVM chain, pays a GitHub user id,
  and links a wallet with a `workflow_dispatch` token from a repository the user owns. It did this before Knos.
  Knos first verified GitHub's signature on Solana in commit `cb3a1ac` (1 Oct 2026, Knos 0.3.7). We read MergePay
  on 2 Oct 2026. What we built after that follows or matches its design in these places: paying a GitHub id;
  binding a wallet with a token from a run in the user's own repository; holding an unbound payee's money for 180
  days and then returning it to the funder; reserving an issue by comment for 7 days; paying a person when a bot
  account opened the pull request; and a waiting time before a new signing key is active. No code was copied; the
  programs here are written for Solana from scratch.
- **Three pull requests by another GitHub account.** `jaystay-bot` wrote pull requests #32, #33 and #34 for
  bounties Knos funded on this repository on 2 Oct 2026: what `knos_bounties` says about each bounty, a
  repository's own record on the site, and a Ruby runner for the referee. That code is in the tree from 0.3.12, in
  commits under that account's name. The three were merged on 3 Oct 2026 and paid 48.75 test USDC in all.
- **Squads v4** is the multisig program that holds the second deployment's upgrade authority and its guardian
  role.
- **Shank** (Metaplex) is the format of the IDL files in `idl/`; they were written by hand from the programs'
  source, not generated.
- **Wycheproof** test vectors (Google, Apache-2.0) are in `programs/knos_oidc/tests/vectors/`, unmodified.
- **Sibyl** (`sibyl-memory-client`, by Sibyl Labs) is the memory engine, used as a dependency.
- Dependencies: `solana-program`, `solana-security-txt` (Rust); `typer`, `rich`, `solders` (Python). The web app
  loads `@wallet-standard/app` from a CDN only when a sponsor connects a wallet.
- The history and economics in [WHY.md](WHY.md) (the UCP 600, Akerlof, Spence, Holmström and Milgrom, and the
  studies cited there) are an argument, not a claim of endorsement.

## How the code is written

Commits in this repository were written with coding agents. Every commit is authored and reviewed by drexthealpha,
who is responsible for it. Commits carry no co-author trailers, because the author of record is the person who
reviewed and committed the change.

## Outstanding limits

Each limit is said once, on one line. No code can fix the first fourteen limits below: they need people, agreements or time. `python scripts/release_manifest.py`
copies these lines into [MANIFEST.md](MANIFEST.md).

- **No buyer has been interviewed.** Every statement here about what a buyer wants is reasoning from public sources.
- **No letter of intent.** Nobody has written that they would use or buy Knos.
- **No paying customer.** No price in the price book has been charged to anyone.
- **No pilot.** Nobody has run a pilot.
- **No outside funder.** Knos's own account funded every task, in test money. Since 0.3.11, 3 payments have gone to another GitHub account, for three pull requests it wrote.
- **Outside key holders today: 0.** Both multisigs are 2-of-3 and one person holds all three keys ([TRUST.md](../TRUST.md) says what changes it).
- **One person, pseudonymous:** no legal name is published.
- **No co-founder,** employee or adviser ([TRUST.md](../TRUST.md)).
- **No legal entity.** Nothing can sign a contract, send an invoice or be sued as Knos, and there are no terms of service.
- **No legal advice taken.** The section "Regulation" below is what the author read.
- **No outside review,** of the programs, the workflows, the relay, the clients, the site or the documents ([ASSURANCE.md](ASSURANCE.md)).
- **No shadow count.** The meter has never run beside anyone's invoices but Knos's own examples.
- **No outside program is known to read the verifier.** The interface and the examples are Knos's own ([COMPOSE.md](COMPOSE.md)).
- **No independent reproduction.** Nobody outside Knos has reported rebuilding the programs to the deployed hash, rerunning the benchmarks or running the drills.
- **No mainnet deployment.** Solana devnet and test USDC only; no real money has moved.
- **No second operator.** If that one person is unavailable, nobody answers a report or cancels a proposal.
- **No organisation account.** The pinned workflows and the relay live in one GitHub account ([GOVERNANCE.md](GOVERNANCE.md), section 6).
- **The first deployment cannot be changed,** so its known limits stay ([SECURITY.md](SECURITY.md)); the second changes only through a multisig with a public 8-day delay.

## When the count is wrong

Knos's count of accepted work can be wrong. This page lists the ways, and for each one who notices, what evidence exists, what
the software does about it, and what it does not do.

**Read this first.** This page describes mechanisms. It is not a contract and it is not legal advice. Today there is:

- **no legal entity.** Nothing can sign a contract, send an invoice or be sued as Knos ([DISCLOSURE.md](DISCLOSURE.md));
- **no warranty.** The software is offered as it is, under its licence. Nobody promises that a verdict is right;
- **no service commitment.** No uptime, no response time, no support hours, for the relay, the site or anything else;
- **no data-processing terms.** No agreement covers personal data, and none can be signed ([PRIVACY.md](PRIVACY.md));
- **no insurance, no indemnity, no refund from Knos.** Knos holds nobody's money and returns nobody's loss.

So when the count is wrong, the loss stays where the mechanisms below leave it. Nobody makes it good. Money on
devnet is test USDC, which is why this is acceptable today and would not be with real money.

### The kinds of wrong

| What went wrong | Who notices | What evidence exists | What the software does | What it does not do |
|---|---|---|---|---|
| **A referee accepted bad work** | the buyer, later: a revert, a failing build, an audit | the signed token (which workflow, which commit, which terms hash), the run's log, the order's log lines on chain | inside the warranty, a signed revert of the paid merge returns the holdback to the funder. In the meter, either side adds a `verdict` or `withdrawn` correction; it is recorded on chain with the next batch and subtracted in the monthly statement. A quorum, chosen at funding, asks two or three evaluators with different owners | return what was already paid. Outside the warranty, or with no holdback, nothing comes back. No one referees whether the work was good: the checks the buyer named did |
| **A referee rejected good work** | the supplier, at once: the verdict and its reasons are posted | the verdict with its reason codes, the commit, the terms hash, the run's log | `/knos appeal <reason>`: the verdict becomes disputed and the evaluator the terms name runs the work again; an overturned rejection can be paid ([DISPUTES.md](DISPUTES.md)). An appeal costs the supplier nothing | pay after the order's deadline. An appeal that ends too late, or one no evaluator hears, pays nothing: the money goes back to the funder. Nothing compensates the supplier for the delay |
| **Insufficient evidence** (a run could not tell) | both: the verdict is its own word, never read as a rejection or an acceptance | which check or file could not be read, by reason code | counts nothing and bills nothing. The work can be checked again at no cost; the supplier can appeal it | decide. A check that stays unreadable until the deadline leaves the work unpaid |
| **A duplicate** (one deliverable counted twice) | whoever reconciles: `knos meter reconcile` lists entries made more than once, per side | the evaluation's id in both batches; the deliverable's id, which a retry shares | on chain, a token is used once and an order pays once. In the meter, a `duplicate` correction is anchored in the next batch and the statement nets it; an accepted deliverable is billed once | undo a batch that was already anchored: the program's counters only go up, so the repeat stays on chain and is corrected beside it. A duplicate nobody reconciles is never found |
| **An issuer's signing key is compromised** | the issuer, or anyone watching its published keys | the key's id in every token it signed | the guardian revokes the key, for ever; a token under a revoked key counts nothing from then on. A new key waits a day and needs the guardian's approval | take back a payment the key already made. Tokens are not re-examined after the fact. If the guardian does not act, nothing revokes the key before it expires |
| **A relay outage past a deadline** | the supplier: the token was signed and nothing was paid | the token itself, posted as a comment, with its signing time | a token is not a secret: anyone can carry it with `knos relay`, and a repository can hold its own relay key | extend a deadline. The program refuses a token presented after the deadline, whoever was at fault, and the money goes back to the funder. Proof that the token existed in time changes nothing on chain |
| **A defect in a Knos program** | anyone: the source and the deployed bytes are public | the program's hash at its public id, the build that produced it, the transactions it executed ([PROVENANCE.md](PROVENANCE.md)) | the guardian can refuse new funding for 7 days at a time. A fix is an upgrade, public for 8 days before it can run. Refunds and withdrawals do not read the pause | repair what the defect already moved. No fund covers a loss, and no upgrade reverses a transaction. No outside firm has reviewed the programs ([ASSURANCE.md](ASSURANCE.md)) |

Two more, because they are the ones a careful reader asks next:

- **GitHub is wrong.** The count rests on GitHub's signature over a workflow run, and on GitHub's record of checks.
  If GitHub signs a false statement or loses a record, Knos cannot tell and does nothing. That trust is the design,
  and it is stated in [SECURITY.md](SECURITY.md).
- **The terms were wrong.** A buyer who names a check that proves little gets that check enforced exactly. The
  software holds the two sides to the terms; it does not say the terms were wise. `knos terms propose` drafts terms
  from what a repository's own checks did on its recent merges, and says where each line came from, so a weak line
  is at least visible ([TERMS.md](TERMS.md)).

### What is recorded when a count is corrected

A correction never rewrites anything. Each kind leaves the first record in place and adds a second one beside it:

| Correction | Where it is recorded | Who can issue it |
|---|---|---|
| an appeal, and how it ended | the appeal's record (the supplier's copy), the repository's memory, the reply on the pull request | the supplier opens it; the evaluator the terms name ends it |
| a `duplicate`, `verdict` or `withdrawn` line | the ledger, as its own entry in the next batch; GitHub signs a single fingerprint (the Merkle root) of that batch, which fixes the entry | the buyer or the seller of that ledger, each under their own id |
| a revert inside the warranty | the program's log: the holdback returned, to whom, on which signed commit | anyone, when the order allows a neutral run, with a token the pinned workflow signs only for a real revert |
| a revoked key | the key's account in the verifier program: revoked, with no instruction that clears it | the guardian |

A month's statement shows every disputed, duplicate and insufficient-evidence line as its own state, so a reader
of the statement sees that a number was contested and how it stands ([COMPANIES.md](COMPANIES.md#statements)).

### Where the loss falls today

Stated without softening, by case:

- Bad work accepted and paid, no holdback: **the buyer** bears it.
- Good work rejected, the appeal late or unheard: **the supplier** bears it.
- A token signed in time and carried late: **the supplier** bears it.
- A payment under a key later found compromised: **whoever funded the order** bears it.
- A defect in a program: **whoever's money it moved** bears it.
- In no case does Knos, or any person behind it, bear it. There is nobody to claim against.

Knos's fee follows accepted value, so Knos gains from an acceptance, wrong or right. It cannot cause one: no key of
Knos's signs a verdict, and its fee account can only receive fees and lower a rate. [DISPUTES.md](DISPUTES.md),
"Knos is paid on acceptance, and does not decide it", has the five rules and the test that checks them.

### What an accountable operator would have to sign for

None of this exists. It is the list a buyer's legal and finance teams would ask of whoever runs the meter for real
money:

1. **A named contracting entity,** with an address and a jurisdiction, that can be sued.
2. **Terms of service** that say what the service is, with a limit of liability stated as an amount.
3. **A liability position for each row of the table above:** which errors the operator makes good, up to what
   amount, and which stay with the parties.
4. **A service commitment:** availability of the relay and the referee, a time to respond to an incident, and a
   remedy when it is missed. Above all, what the operator owes when its own outage makes a token late.
5. **A data-processing agreement,** a list of subprocessors, retention periods and a way to answer a deletion
   request, given that an on-chain record cannot be deleted.
6. **A dispute procedure with a named last resort:** who decides when the evaluator the terms name does not
   answer, within what time, and under which law.
7. **Control of the upgrade and guardian keys by people who answer for them:** independent holders, a tested
   succession, and notice of every upgrade ([GOVERNANCE.md](GOVERNANCE.md)).
8. **An outside security review** of the programs and the referee, with its report published.
9. **Licensed handling of real money:** legal advice on held money and money transmission, and a regulated partner
   where the law asks for one ([DISCLOSURE.md](DISCLOSURE.md)).
10. **Insurance** for errors and for loss of funds, or a stated reason for having none.
11. **Support with a named owner:** who answers a supplier's finance operator about an unpaid, accepted invoice.

Until an operator signs for these, the accurate description of Knos is a set of public programs and tools that two
parties may choose to use between themselves, at their own risk.

## Regulation: what has been examined, and what has not

**This is not legal advice.** It was written by the person who built Knos, from public documents. No lawyer has
read it. Counsel is needed before any real money moves, and none has been asked. Knos runs on Solana devnet, and
its money is test USDC.

Three questions were examined, each only as far as one public source goes: whether holding money in a program is money transmission under
United States federal rules; what a payer owes in tax reporting when it pays a contractor; and what sanctions law asks before a payout.
Everything else is listed at the end as not examined.

Sources were read on 3 Oct 2026. The description of the product was last checked against the programs live on devnet on 10 Oct 2026
(knos_pay 2.2, knos_oidc 2.2); no source was read again for it, and no conclusion below was checked by anyone outside Knos.

### 1. Is the payment program money transmission?

#### What the product does

- A funder moves USDC into a token account that belongs to one order. The address is derived by the program. No
  person holds a key to it.
- The program pays the payee when it has verified a GitHub-signed token that matches the order's terms. With no
  payment by the deadline, anyone can send the refund, and it goes back to the funder.
- In normal operation Knos has no instruction that moves an order's money. Its guardian can pause new funding and
  revoke a signing key. It cannot pay, redirect or take ([SECURITY.md](SECURITY.md), section 6).
- Knos receives a fee, into its own token account, when an order is paid. The funder pays it on top of the amount:
  0.30% of the amount, at least 0.05 (knos_pay 2.2, live since 9 Oct 2026). An order funded before then keeps the
  older fee it was funded with. A refund returns it.
- An order holds at most 100,000 on devnet (the limit was 500 under the earlier build). A mainnet cap is not decided. The size of
  a single payment bears on every question on this page, and none was examined at that size.
- **Knos can change the program** through a multisig, after a public 8-day delay. An upgrade "could do anything,
  including taking every vault" ([SECURITY.md](SECURITY.md), section 7). The multisig is 2-of-3 and one person
  holds every member key today: no second person has to agree ([GOVERNANCE.md](GOVERNANCE.md)).
- **That does not end with an outside review.** The payment program stays upgradeable behind the delay after a
  review too ([SECURITY.md](SECURITY.md), "Before mainnet"). So Knos keeps the power to replace the program that holds
  the money, with notice.
- A funder with only a passkey can fund an order from a passkey wallet. A relayer, today Knos's, pays the network
  fee of that transaction; it cannot change the amount, the order or the destination, which the passkey signed.
- An order can belong to a GitLab project as well as to a GitHub repository. Nothing below depends on which.
- The meter (`knos_meter`) moves no customer money. It holds credits a customer prepaid to Knos for Knos's own
  fee, per evaluation or per batch of evaluations.

#### What the guidance says

FinCEN's guidance of 9 May 2019, FIN-2019-G001, "Application of FinCEN's Regulations to Certain Business Models
Involving Convertible Virtual Currencies"
([text](https://www.fincen.gov/sites/default/files/2019-05/FinCEN%20Guidance%20CVC%20FINAL%20508.pdf)):

| section | what it says |
|---|---|
| 4.2.1, wallets | How a wallet is treated depends on four things: "(a) who owns the value; (b) where the value is stored; (c) whether the owner interacts directly with the payment system where the CVC runs; and, (d) whether the person acting as intermediary has total independent control over the value." (CVC: convertible virtual currency, such as USDC.) |
| 4.2.1, users | "In so far as the person conducting a transaction through the unhosted wallet is doing so to purchase goods or services on the user's own behalf, they are not a money transmitter." |
| 4.2.2, multiple-signature wallets | A provider that "restricts its role to creating un-hosted wallets that require adding a second authorization key to the wallet owner's private key in order to validate and complete transactions" is "not a money transmitter because it does not accept and transmit value." If it "combines the services of a multiple-signature wallet provider and a hosted wallet provider", it is one. |
| 5.2.2, applications | Developing an application is "outside the definition of money transmission". But "if the developer of the DApp uses or deploys it to engage in money transmission, then the developer will qualify as a money transmitter." |
| 2, exemptions | A person who only provides "the delivery, communication, or network access services used by a money transmitter", and a person who accepts and transmits funds "only integral to the sale of goods or the provision of services, other than money transmission services", are exempt. |

#### What it does not say

The guidance has no passage on a payment program that holds money with no custodian and releases it on a
condition. Any conclusion for Knos is the author's inference, not the guidance's.

| pointing away from transmission | pointing toward it |
|---|---|
| The funder is buying a service on its own behalf (4.2.1, users). | Knos wrote the program and deployed it (5.2.2). |
| Knos holds no key to an order's money and cannot move it in normal operation (4.2.1, factor d). | Knos takes a fee from each payment. |
| The funder and the payee interact with the chain directly, or through a relay that decides nothing (factor c). | Until an outside review Knos can replace the program, after 8 days, and a replacement could move the money. That bears on "total independent control". |
| | Knos runs the public relay. A relay decides nothing, but today it is the one that carries the tokens, and for a passkey funder it also pays the network fee. |
| | One person holds every key that can replace the program. |

This is the first question for counsel. The answer may differ once independent people hold keys of the multisig,
and it does not go away after an outside review, because the payment program is meant to stay upgradeable.

#### Not examined

- State money-transmitter laws in the United States. The guidance does not cover them.
- Any other country's rules on payment services, electronic money or crypto-asset services.
- Whether prepaid meter credits are a stored-value product.
- Whether paying a funder's network fee, or holding money in a wallet derived from a funder's passkey, changes who
  is the intermediary.
- Whether an advance against an assigned payment is lending, and for whom.

### 2. Paying contractors: tax reporting

A work order paid to someone outside the funder's company is a payment for services. The funder is the payer. Knos
is not a party to the payment. That, too, is the author's reading and a question for counsel.

#### What was read

- **The payer, in the United States.** Form 1099-NEC is filed "for each person in the course of your business
  during the year to whom you have paid at least $2,000". The threshold rose to 2,000 USD for tax years that begin
  after 2025 ([IRS, instructions for Forms 1099-MISC and 1099-NEC, the IRS's own edition label (12/2026), read 10 Oct 2026](https://www.irs.gov/instructions/i1099mec)).
  Those instructions say nothing about a payment made in a digital asset. No IRS page was found that tells a payer
  how to report one.
- **The payee, in the United States.** "For payments you receive as an independent contractor, report the digital
  asset income on Schedule C", at "the fair market value as measured in U.S. dollars"
  ([IRS, digital assets](https://www.irs.gov/filing/digital-assets)). Form 1099-DA, on the same page, is for
  brokers, not for someone who pays a contractor.

#### What the product does

- It keeps a record a payer can file from. `knos receipts`, `knos statement` and `knos export` write, for each
  payment: the time, the repository, the payee, the amount, the fee and the transaction. CSV for finance, JSON
  Lines for a log system, an invoice per period ([`src/knos/records.py`](../../src/knos/records.py)). Everything in them is recomputed from the programs' own
  logs, so anyone can check a statement against the chain.
- An organisation's policy file can name who may be paid ([`src/knos/policy.py`](../../src/knos/policy.py)).

#### What the product does not do

- It collects no tax form and no taxpayer number. A payee is a GitHub account and an address. Knos gives the payer
  no name and no country.
- It withholds nothing and files nothing.
- It does not decide whether a payee is a contractor or an employee.
- It does not add up what one payer paid one payee in a year against a reporting threshold. With orders of up to
  100,000, one order can pass it.

#### Not examined

- Withholding on payments to people outside the United States.
- Value-added and sales taxes.
- Tax reporting in any other country.
- How Knos's own fee income is taxed.

### 3. Sanctions

#### What was read

The Office of Foreign Assets Control's "Sanctions Compliance Guidance for the Virtual Currency Industry", October
2021 ([text](https://ofac.treasury.gov/media/913571/download?inline)):

- "All U.S. persons are required to comply with OFAC regulations."
- OFAC "may impose civil penalties for sanctions violations generally based on a strict liability legal
  standard": a person "may be held civilly liable for sanctions violations even without having knowledge or reason
  to know it was engaging in such a violation."
- "In 2018, OFAC began including certain known virtual currency addresses as identifying information for persons
  listed on the SDN List."
- Companies should "employ tools sufficient to identify and block transactions associated with blocked persons,
  including transactions associated with those virtual currency addresses included on the SDN List."

Separately, the issuer of USDC can act on its own: "Circle reserves the right to 'block' certain USDC addresses"
([USDC terms, 12 Dec 2025](https://www.circle.com/legal/usdc-terms)). That control is Circle's, not Knos's.

#### What the product does

Before a workflow asks for a pay token, it checks the payout address against the digital-currency addresses on
OFAC's list ([`src/knos/screen.py`](../../src/knos/screen.py)). A listed address is refused, the reply says so, and
the money is held. When the list cannot be fetched the check says "not screened" and does not pretend to have
passed.

#### What the product does not do

- **It matches addresses, nothing else.** An address that is not on the list is not cleared. Nobody's name,
  country or ownership is checked. A GitHub account is not an identity document.
- **The program does not enforce it.** The check runs in the workflow. A funder may pin other workflows than the
  published ones, and a token from a workflow that does not screen is still a valid token.
- **No monitoring.** Nothing watches where money goes after a payout.
- **No identity checks of funders or payees**, and no programme, officer or training of the kind the guidance
  describes.

#### Not examined

- Whether Knos, a funder, or a relayer is the person who must comply for a given payment.
- Sanctions lists other than OFAC's.
- Anti-money-laundering rules beyond the question in section 1.

### 4. Other law, not examined

- Consumer protection, and the terms a funder and a payee would agree to. There are no terms of service.
- Data protection. A public chain keeps what is written to it for ever: GitHub account ids, addresses, amounts,
  and for a public order the repository and the terms. None of it can be erased on request
  ([SECURITY.md](SECURITY.md), "Data on chain").
- Securities and commodities law. Knos has no token and issues nothing.
- Employment law, where a standing order pays the same person month after month.
- Export controls.

### 5. Before real money

1. Counsel on sections 1 to 3, for the country Knos is run from and for the first customers' countries.
2. A decision, in writing, on who the payer of record is for a payment and who screens it.
3. A named legal entity as the operator, and terms of service. Neither exists today: Knos is one person, known
   publicly by a GitHub account, and no company has been formed ([DISCLOSURE.md](DISCLOSURE.md)).
4. A review of the programs by a security firm. No security firm has audited anything
   ([SECURITY.md](SECURITY.md)). That is a separate gate from this page, and `knos mainnet-check` fails on it on
   purpose.
5. Keys of the upgrade multisig held by more than one person, so that the question of control in section 1 has a
   different answer than "one person".
