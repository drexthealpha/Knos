# Security model

Who has to be trusted for what, what a signed statement covers, and what it does not. What is said about a program
names the file or the test that backs it. The authority on what the programs do is the documentation at the top of
each source file in [`programs-v2`](../programs-v2).

This page describes Knos 0.3.14: `knos-pay` 2.1 and `knos-oidc` 2.1 (an upgrade of the second deployment at the same
addresses), `knos-meter` 1.1 and `knos-passkey` 1.1. The 2.1 builds that 0.3.13 proposed never ran: a defect was
found in the proposed escrow during its 48-hour delay ([section 15](#15-tokens-public-bound-to-one-action-used-once)),
and this release withdraws those proposals and proposes corrected builds in their place. Until the new proposal
executes, the deployed escrow and verifier are 0.3.12's, and what this page says about work orders, judges,
any-issuer keys, GitLab and the single-use rule is not live ([section 8](#8-versions-and-what-is-live-when)).
This page names no time for a proposal. Whether one is still pending, has run or was replaced, and from when it can
run, is read from the chain by `knos status` and by the site's
[upgrade record](https://drexthealpha.github.io/Knos/upgrades.json); [`web/upgrades.json`](../web/upgrades.json) is the
committed copy, of the time it names.

Knos runs on Solana devnet and the money is test USDC. **Nobody outside Knos has reviewed the security of
anything here:** not the programs, the workflows, the relay, the clients, the site or these documents. What the
programs guarantee about money, one sentence each with its test, is in [INVARIANTS.md](INVARIANTS.md); who can
change the programs is in [GOVERNANCE.md](GOVERNANCE.md). Report a vulnerability privately:
[SECURITY.md](../SECURITY.md).

## The short version

- A work order's money sits in a token account of its own, owned by a program, `knos-pay`. It is not with Knos and
  not with the repository.
- The program pays only on a token that GitHub signed (or, for an order of a GitLab project, gitlab.com) and that a
  second program, `knos-oidc`, verified on chain. Every such token is accepted once, by one instruction.
- GitHub signs which workflow ran, at which commit, in which repository, started by whom, by which event, and on
  which kind of runner. It does not sign what that workflow read. That the named checks passed, and who is paid, is
  the pinned workflow's own reading of GitHub's record.
- Who may ask for that signed statement is fixed when the order is funded: the order's own repository; for a public
  repository, also anyone who runs the pinned workflow by hand in a personal repository of their own; a judge
  repository the funder named; an arbiter the funder named. Each can go wrong in its own way
  ([section 2](#2-the-four-judges-who-is-trusted-in-each-and-what-each-could-do-wrong)).
- A statement moves the money of one order and nothing else.
- Until an outside review, Knos can change every program through a multisig, after a public 48-hour delay. Today
  one person holds every key of that multisig, so the delay is notice and not a second opinion
  ([GOVERNANCE.md](GOVERNANCE.md)).

## Who you trust, and for what

| party | trusted for | not trusted for |
|---|---|---|
| **GitHub** | signing true statements about a workflow run; keeping its signing keys; answering its API truthfully; running a GitHub-hosted runner of a personal account on its own image | it cannot move money. It signs statements, and the programs check them |
| **GitLab** (gitlab.com), for an order of a GitLab project only | the same, for a pipeline: signing true claims, keeping its keys, answering its API | it cannot move money, and its tokens act on no GitHub repository's order |
| **Solana** | running the programs as written | |
| **The judge of an order** (one of four, section 2) | everything a pay token says beyond GitHub's signature | any order but the one it judges |
| **The pinned workflows and the `knos` release they install** | reading GitHub's record as the terms say. They are fixed by commit and by hash, so they are the same code for everyone | |
| **Knos** (drexthealpha) | until the outside review: not misusing the upgrade multisig; approving new keys; registering other issuers' keys | it cannot add a signing key alone, pay or redirect an order, change an order's terms, or block a refund or a withdrawal. Changing a program or a price takes the 48-hour delay |
| **A relayer** (the job itself, Knos's public worker, or anyone) | being there: it carries tokens to the chain and pays the fees | it cannot change where money goes. A payment tips it out of the fee |
| **The issuer of the token that is paid** (a stablecoin's issuer) | what its mint lets it do to every holder, such as freezing an account | |

## 1. What GitHub signs, and what only the workflow derives

**What GitHub signs.** A workflow run can ask GitHub for a token. GitHub signs these claims in it, among others
(`github` in [`programs-v2/knos_pay/src/gh.rs`](../programs-v2/knos_pay/src/gh.rs) reads them):

| claim | what it says |
|---|---|
| `job_workflow_ref`, `job_workflow_sha` | which workflow file the job came from, and the commit that fixes that file's content |
| `repository_id`, `repository_owner_id` | the repository the run happened in, and its owner, as numbers that survive a rename |
| `actor_id`, `event_name` | which account started the run, and how: a push, a comment, a schedule, or by hand (`workflow_dispatch`) |
| `run_attempt` | whether this is the run's first attempt. A re-run keeps the first actor's name whoever starts it |
| `runner_environment` | `github-hosted` or `self-hosted`: the kind of runner. It does not name the machine or its image |
| `iat`, `exp` | when the token was issued and when it expires (five minutes later) |
| `aud` | a text the workflow chose. GitHub signs that this run asked for it, not that it is true |

`knos-oidc` checks GitHub's RSA signature over the whole token on chain
([`programs-v2/knos_oidc/src/lib.rs`](../programs-v2/knos_oidc/src/lib.rs), instruction `Step`).

**What only the workflow derives.** Everything in `aud`. For the payment of an order it is
`knos3:pay:<order address>:<head commit>:<terms hash>:<mode>:<pull request>:<payees>`. The pinned workflow found the
merged pull request, read its checks from GitHub's API, worked out who is paid and where, and asked for that text.
GitHub's signature covers the asking. The reading happened on the runner.

**Why the runner matters.** In August 2026 a researcher showed that an organisation on a paid plan can create a
GitHub-hosted "larger runner" with an image of its own, give it the name of a standard runner label, and have it
serve jobs pinned to that label. The token still says `github-hosted`
([research note](https://github.com/amiller/github-zktls/blob/master/tasks/substitution-demo/research-note.md),
runs of 21–24 Aug 2026; [GitHub community discussion 205732](https://github.com/orgs/community/discussions/205732)).
So pinning a workflow file and its commit fixes the code that was asked to run. It does not fix the machine, when
the repository belongs to such an organisation. A personal account cannot have larger runners
([GitHub's documentation](https://docs.github.com/en/actions/reference/runners/github-hosted-runners): they are for
organisations and enterprises on paid plans), so a `github-hosted` run in a repository a person owns is on GitHub's
own image. [ATTESTOR.md](ATTESTOR.md) states this gap exactly and the five ways of narrowing it, of which two
exist here. Two rules of the programs rest on that: the neutral judge (section 2, b) and Refresh by anyone
([section 5](#5-signing-keys-any-issuer-refresh-by-anyone-private-keys)). If GitHub changes this, both rules
become unsafe and need an upgrade.

**GitLab.** The verifier has checked gitlab.com's signature since 2.0; from this release the escrow reads GitLab's
claims too, so a GitLab project can fund an order and be paid on a merge to a protected branch. The claims it
reads are GitLab's own names for the same facts
([GitLab's documentation of the ID token](https://docs.gitlab.com/ci/secrets/id_token_authentication/)):
`project_id` and `namespace_id` (the project and its owner, as numbers), `user_id` (who started the pipeline),
`pipeline_source` (how), `ref` and `ref_protected` (the branch, and whether it is protected), `ci_config_ref_uri`
and `ci_config_sha` (which pipeline definition ran, fixed by commit, as `job_workflow_ref` and `job_workflow_sha`
are for GitHub) and `sha`. Scopes and ids are namespaced by issuer, so a GitLab project id can never be taken for a
GitHub repository id. What is trusted is the same in kind: gitlab.com signs which pipeline ran, not what it read,
and a project's maintainers control its runners. The rule about personal accounts and runner images above is a
rule of GitHub's; nothing equivalent was established for GitLab, so the neutral judge and Refresh by anyone remain
GitHub-only. The source of [`knos_pay`](../programs-v2/knos_pay/src) says exactly which claims each instruction
requires.

## 2. The four judges: who is trusted in each, and what each could do wrong

Every judge's token is from the workflows the order pinned at funding, at the pinned commit, on a GitHub-hosted
runner, on the run's first attempt (`judge` in
[`programs-v2/knos_pay/src/order_judge.rs`](../programs-v2/knos_pay/src/order_judge.rs)). Then one of four. The
first valid token pays, and the order closes.

| judge | the run | who remains trusted | what it could do wrong |
|---|---|---|---|
| **a. The order's own repository** | `prove.yml`, in the repository the order names | that repository's maintainers and its runner. In an organisation on a paid plan the runner can be an image the organisation built | pay whoever it likes from this order, or never ask for the token. A sponsor who funds an issue in someone else's repository trusts that repository this far |
| **b. Neutral** (on unless the funder wrote `neutral off`; never for a private order) | `attest.yml`, started by hand (`workflow_dispatch`) by the account that owns the repository it ran in | GitHub, to run a personal account's job on its own image and to answer its API truthfully; the pinned `attest.yml` and the `knos` release it installs. For an order with a black-box suite the run executes that suite again itself, in a job that cannot sign, and signs only on its own result; for an order paid on its merge it reads the checks' conclusions from the public record, and its verdict says which of the two it did (section 20) | sign a payment that the pinned code wrongly allows. For a merge-mode order it also repeats a check conclusion that was wrong in the buyer's repository: it reads that conclusion and does not run the check. The person who starts the run is the person who gains, so a fault in that code, or in GitHub's record, is found by someone with a reason to look for it. It cannot sign what the record does not support |
| **c. A judge repository** the funder named | `prove.yml` or `attest.yml`, in that repository | that repository's maintainers and its runner, entirely. This is how a private order is paid | pay whoever it likes from this order, or never ask |
| **d. The arbiter** the funder named | `attest.yml`, started by hand by the arbiter in a repository he owns, with a ruling (`knos3:rule:<order>:<payees>`) | one GitHub account, and whoever controls it | rule for either side, or for a third party, with no pull request. He cannot name himself among the payees, and a Balance's order cannot name its funder or its owner as arbiter. He can also never rule: the order then goes back at its deadline |

Tests: `test_a_seller_pays_himself_after_the_buyers_repository_deleted_its_workflow`,
`test_what_a_neutral_run_cannot_do`, `test_a_public_order_that_names_a_judge_repository_is_paid_from_it_too`,
`test_the_arbiter_an_order_named_rules_who_is_paid`, `test_what_a_ruling_cannot_do` and
`test_the_arbiter_is_neither_the_funder_nor_a_payee` in
[`tests/test_order_judges.py`](../tests/test_order_judges.py).

**What changed for the seller.** In 0.3.12 only the buyer's repository could ask for the pay token, so a buyer who
removed the workflow before merging took the work and paid nothing. With judge b, after a merge in a public
repository the seller asks himself: `knos settle --neutral <pull request URL>` starts the pinned `attest.yml` in a
repository of his own, and the program pays on that run. Deleting the workflow, or the repository's Actions, no
longer withholds the payment.

**What a buyer can still do.**

- Not merge. The merge is the acceptance, and it stays with the buyer.
- Fund with `neutral off`. The reply to the funding comment says so, and the order shows it on chain, before anyone
  starts work.
- Pay someone else first. The buyer's own repository is judge a, and the first valid token pays. A buyer who
  controls the repository can have it sign for another payee before the seller's run lands.
- Change the record the neutral run reads, where GitHub lets a maintainer change it before the seller's run:
  the assignment of the issue, for one.
- In a **private repository**: withhold. No public record exists for a neutral run to read. The buyer can remove
  the seller's access and never run the judge. What is left to the seller is the arbiter, if the order named one,
  and the order's deadline.
- Cancel an open order, once: the deadline becomes at most 7 days away. A valid pay token inside the notice still
  pays. If the order was reserved for a seller when it was cancelled, the kill fee fixed at
  funding (at most 20% of the amount) goes to that seller before the refund.

**What a buyer cannot do:** change the terms after funding, take the money out before the deadline or the end of a
notice, stop a payment once its token exists, or take one back. Money held back for a warranty returns to the
funder only on a token that names a revert inside the warranty (`Revert` in
[`order_terms.rs`](../programs-v2/knos_pay/src/order_terms.rs)): from the order's own repository (judge a), from a
neutral run by hand that read the public record (judge b), or from the order's judge repository (judge c); never from
the arbiter. When the token is the buyer's own repository's, the holdback is money the seller trusts that repository
with. The share is fixed at funding, at most 50%, for at
most 90 days.

**What a seller can do to a buyer.** Deliver work that passes the named checks and is merged, and be paid, whatever
the work is worth. Reserve an order with `/knos take` and do nothing for its `reserve` days. In tests mode, pass a
black-box check made of fixed examples with a stub: the check must use generated inputs
([TAMPER.md](TAMPER.md)).

## 3. The terms: what must be true, fixed at funding

An order's terms are a small JSON document ([`src/knos/terms.py`](../src/knos/terms.py)):

```json
{"accept":"","checks":[{"app":15368,"name":"test"}],"deny":[".github/**",".knos/**"],"mode":"merge","paths":[],"reserve":7,"v":1}
```

- `checks`: the checks that must have passed at the pull request's last commit, each with the GitHub App that must
  have produced it (`0`: a commit status of that name; `-1`: any source).
- `paths`: when not empty, every changed file must match one of these globs. `deny`: no changed file may match one
  of these. By default a pull request may not change `.github/**` or `.knos/**`.
- `accept`: in tests mode, the hash of the funder's black-box acceptance bundle in `.knos/acceptance/<issue>/`.
- `reserve`: how many days a `/knos take` reservation lasts.

**They cannot be edited.** The funding instruction carries the JSON, stores its sha256 in the order and logs the
JSON (`knos3:terms`). A pay token must carry the same hash or the program refuses it. The options of an order are
fixed in the same instruction: neutral or not, a holdback and its warranty, a kill fee, an arbiter, a judge
repository, a standing rate (`opts` in [`order.rs`](../programs-v2/knos_pay/src/order.rs)). `TopUp` adds money and
changes nothing else.

**Where the checks come from**, decided once at funding: the names the funder wrote; else the checks the
repository's `.knos/policy.yml` names; else the default branch's required status checks; else every check that ran
to an end on the default branch's latest commit. Knos's own jobs are never among them. A repository with no checks
gets none, and the reply says so: "your merge alone is the acceptance".

**The six states of evidence.** When the pay token is asked for, each required check is in exactly one state at the
pull request's last commit (`evidence` in `terms.py`): `passed`, `failed`, `skipped`, `pending`, `absent`
(a check of the same name from another app is not it) or `unreadable`. Only `passed` for every required check, with
every changed file in scope, is acceptance. Anything else pays nothing, and the comment names the check and its
state. What a pull request's description says never changes what is required
([`tests/test_terms.py`](../tests/test_terms.py)).

**The policy file.** `.knos/policy.yml` on the default branch says who may fund, the cap per order, a monthly
budget, the payees and vendors allowed, default checks, standing offers, and warranty defaults
([`src/knos/policy.py`](../src/knos/policy.py)). The workflow reads it at funding and at payout and refuses with
the line of the rule. A policy that cannot be read is a refusal, never a permissive policy
(`test_a_refusal_never_becomes_a_permissive_policy`). It is enforced by the workflow, not by the chain: it binds the
order's own repository (judge a) and the neutral run, which use the same code, and it does not bind a repository
that pins other workflows.

**Screening.** Before a payout the workflow checks the address against the United States Treasury's list of
sanctioned digital currency addresses ([`src/knos/screen.py`](../src/knos/screen.py)). A listed address is refused
and the order is held. When the list cannot be had, the answer is "not screened", never "clean". This too is the
workflow's rule, not the chain's.

## 4. Who is paid, where, and the fee

Decided in [`src/knos/who.py`](../src/knos/who.py), from facts GitHub authenticates:

- A pull request a person opened pays that person.
- A pull request a bot account opened (a coding agent) pays a person or an organisation only on an act GitHub
  authenticates: the issue is assigned to exactly one person; else a maintainer wrote `/knos pay @login`; else a
  person named in the pull request's assignees wrote `/knos mine`. A standing offer pays the one vendor it names.
- A maintainer can share one payment between up to four people before the merge (`/knos split`). The shares are in
  the token and must add up to the whole.
- The pull request must close the issue ([`src/knos/closing.py`](../src/knos/closing.py)).

**Prose never decides.** A line in the description or in a commit pays nobody. An edited comment never counts.

**Where it is paid.** The pinned workflow asks for the wallet bound to the payee's GitHub account; else the address
in the payee's own newest, unedited `/knos address` comment; else none. The program pays, in this order: the wallet
the payee assigned this order's payment to (`Assign`, signed by the payee's bound wallet); else the address the
token carries; else the bound wallet. So the address in a token comes before a binding: the judge is trusted with
it, like everything else in the token. A relayer cannot leave an assignment or a binding out: the instruction
requires the accounts where they would be.

**Binding a wallet is by hand.** A person: a repository named `knos-claim` in their own account, the pinned claim
workflow, started by hand. An organisation: the same in a repository the organisation owns, started by a member
(`BindOrg`). GitHub's claims do not say whether an owner is a person or an organisation, so `BindOrg` never
replaces a binding a person made himself (`test_a_collaborator_cannot_rebind_a_person_who_bound_his_own_wallet`).

**A held payment.** One payee with no address and no bound wallet: the order is held for that payee for 180 days.
The funder cannot take it back in that time. When they bind a wallet, anyone can send `SettleOrder`. After 180
days it goes back to the funder.

**The fee.** The funder pays it on top of the amount: 0.30% of the amount, at least 0.05 of a whole unit of the
mint, no maximum; one rate, no tiers, jobs and orders alike (a job's comes out of its amount). That is the rule of
knos_pay 2.2, the build in this tree. **The public program charges the 0.3.14 fee until the upgrade to knos_pay 2.2
executes**: 2.5% of the first 1,000 whole units, 1% to 50,000, and 0.5% above; at least 0.40; no maximum (a job: 2.5%,
at least 0.05). Which rule is charged is the program's own answer to its Version instruction (2 from knos_pay 2.2
on): `knos status` says which build runs, and the site, the client ([`fees.py`](../src/knos/fees.py)) and the SDK
(`v2.feeRule`) show the fee of the build that is live. Orders funded before the upgrade keep the rate fixed at their
funding. The fee is one pure function in
[`lib.rs`](../programs-v2/knos_pay/src/lib.rs), tested at its edges. It waits in the order's account. At the payment,
the payees receive their full shares; the relayer that paid for the transaction receives a tip out of the fee (0.05,
or 0.30 when the transaction created a payee's token account); the rest goes to `FEE_OWNER`, an address of Knos's
that has one other power: it can lower the rate of the orders funded from one repository owner's Balances, under a
contract (`SetPlan`, until an expiry: a rate between 0.10% and 0.30% from knos_pay 2.2 on; before it, the first
tier's rate, between 0.5% and 2.5%). A refund returns amount and fee.

## 5. Signing keys: any issuer, refresh by anyone, private keys

`knos-oidc` accepts a token only under a key it holds
([`pins.rs`](../programs-v2/knos_oidc/src/pins.rs), [`lib.rs`](../programs-v2/knos_oidc/src/lib.rs)).

**Genesis.** The program holds the sha256 of GitHub's four signing keys of 2 Oct 2026 as constants. Anyone can
register one of those four, and no other key, without an attestation.

**A new key of GitHub's or GitLab's needs GitHub's own signature.** A run of the pinned rotate workflow reads the
issuer's published keys and asks GitHub for a token whose `aud` names the new key's hash. The program accepts it
only from the pinned workflow at a pinned commit, on a GitHub-hosted runner, started by the schedule or by hand, in
one of two repositories of one personal account (GitHub id 142920951, drexthealpha), and only while the key that
verified that token is itself usable (`test_an_attestation_counts_only_while_the_key_that_verified_it_is_usable`).

**Any other RS256 issuer** comes in the same way (`RegisterIssuerKey`): the same run fetched
`<issuer>/.well-known/openid-configuration` and its key set over TLS and named the issuer's URL and the key. The
program stores the URL with the issuer's first key, and `Step` requires a token's `iss` to be that URL. Who is
trusted for such a key: GitHub's signature, the name resolution and the certificate of the issuer's site at the
moment of that fetch, the one account whose run counts, and the guardian. A program that reads tokens chooses which
issuers it accepts. `knos-pay` accepts GitHub's and gitlab.com's; `knos-meter` accepts GitHub's only.

**A one-day delay, then the guardian's approval.** A key admitted by an attestation verifies nothing for a day and
nothing at all until the guardian approves it. An attestation alone admits no key, and the guardian alone admits
no key.

**Thirty days, unless attested again.** Every key expires 30 days after it was registered or last attested.
`Refresh` moves the expiry to 30 days from now, never earlier.

**Refresh by anyone.** For `Refresh`, and never for registering a key, the attestation may come from anyone: the same
pinned workflow, started by hand in a repository owned by the person who started it
(`test_anyone_refreshes_a_key_from_a_repository_of_his_own_and_nobody_registers_one_that_way`). So the keys an
issuer still publishes stay alive without Knos's account or its schedule. A new key still needs the pinned account
and the guardian.

**Revocation is for ever.** The guardian can revoke any key. No instruction clears the mark. Every instruction of
`knos-pay` and `knos-meter` that takes a token also takes the key's account and refuses the token once that key is
revoked or expired.

**Private keys, and their one consumer.** Any wallet can register a key with no attestation (`RegisterPrivateKey`),
for an issuer no public runner can reach, such as a company's own GitHub Enterprise Server. Nobody vouches for such
a key: it says what its registrant says. The key account and every token it verifies are marked private, with the
registrant's address. Such a token attests nothing in the verifier, `knos-meter` counts nothing under it, and the
interface crate's `read` refuses it. One instruction accepts it: `PayOrder`, for a private order funded from a
Balance that the same wallet opened. The token is then the word of the wallet whose money it pays out
(`test_a_private_order_of_a_balance_is_paid_under_the_key_its_authority_registered`,
`test_what_a_token_under_a_key_that_is_not_githubs_cannot_do`).

**When keys run out.** If no usable key of GitHub's is left, nothing can be verified and nothing can be attested.
The escrow is then refund-only. Getting out takes an upgrade of the verifier. [GOVERNANCE.md](GOVERNANCE.md),
section 8, says who refreshes, how anyone can, and what follows if nobody does; [DRILLS.md](DRILLS.md) has the
funder's steps.

**Refresh by anyone still needs one account to exist.** The pinned rotate workflow is a file in a repository of
the account drexthealpha. A run "by anyone" calls that file. If the account were suspended, GitHub could not fetch
it, nobody could make the attestation, and every key would expire within 30 days
([GOVERNANCE.md](GOVERNANCE.md), section 9).

## 6. The guardian

The guardian is the vault of a second Squads multisig with no time lock, so that a revocation is not delayed
(`GUARDIAN` in `pins.rs` and in [`programs-v2/knos_pay/src/lib.rs`](../programs-v2/knos_pay/src/lib.rs)).

| the guardian can | the guardian cannot |
|---|---|
| approve a key that an attestation admitted | add a key alone |
| revoke any key, for ever | undo a revocation, or change a delay or an expiry |
| refuse new funding for at most 7 days at a time | move money, pay an order, or change where one is paid |
| | block a refund, a withdrawal, or a payment whose token was verified under a key that is still good |

So the guardian can stop the system, and it cannot take from it. [DRILLS.md](DRILLS.md) runs the pause, the
revocation and a proposed, waited, executed and cancelled upgrade against the deployed bytes, and says which
signatures it simulated.

## 7. The upgrade authority

The upgrade authority of all four programs is the vault of a Squads multisig
(`upgrade_authority` and `upgrade_multisig` in [`program_ids.json`](../programs-v2/program_ids.json)).

- **A 48-hour time lock.** An upgrade can run 172,800 seconds after the vote that approved it, and not before. In
  that time the proposal and the new program's bytes are on chain for anyone to read, and the members can cancel it.
- **No config authority.** No single key can change the members, the threshold or the delay.
- **A record of the build.** [`examples/upgrade_gate`](../examples/upgrade_gate) writes a record on chain only when
  GitHub signed that Knos's own `program.yml`, at a commit of `main` or of a release tag, built exactly these bytes.
  `scripts/governance.mjs upgrade propose` refuses a buffer that has no record unless it is told `--ungated`, and
  `knos status` says whether a pending upgrade's buffer has one. The record says which commit to read. It does not
  say the commit is good, and the multisig itself does not require it: the refusal is in the script.
- **Who is told.** `knos status` fails while an upgrade is pending and prints it, and the site shows a banner on
  every view with the buffer and the time it can run. Every proposal is also written to
  [`web/upgrades.json`](../web/upgrades.json) and to an Atom feed beside it (`upgrades.xml`), with the program, the
  proposed build's hash, its source commit, the earliest time it can run and its status, so that a funder can
  subscribe once instead of looking ([`scripts/upgrade_feed.py`](../scripts/upgrade_feed.py)). The feed is
  rewritten when the site is built. Nothing is pushed beyond that: no comment is posted on repositories with open
  orders. The notice protects someone who looks or who subscribed.
- **Today every member key is the founder's.** The multisig is 2-of-3 and one person holds all three keys. So the
  delay gives notice, not independent oversight: nobody else must agree and nobody else can refuse
  ([GOVERNANCE.md](GOVERNANCE.md) has what an independent signer would check and how one would be added; none has
  agreed).
- **The delay has been used once.** The 2.1 build proposed by 0.3.13 carried a defect that was found during its 48
  hours; it never ran, and the release of 0.3.14 cancels its proposal and proposes a corrected build (section 15).
- **What an upgrade could do: anything**, including taking every vault and every order's money. The delay is the
  protection.
- **On devnet the multisig program is itself upgradeable.** Squads v4 has no upgrade authority on mainnet. On devnet
  its program data names one, `HM5y4mz3Bt9JY9mr1hkyhnvqxSH4H2u2451j7Hc2dtvK`, which we take to be Squads' own key
  (read from both clusters on 3 Oct 2026). A devnet time lock is only as strong as that.

What the 48 hours are good for: a Balance's wallet can withdraw its unspent money at once. Money already in an
order cannot leave early except by a cancellation, which takes up to 7 days. So the notice protects Balances, and
orders whose deadline falls inside it.

## 8. Versions, and what is live when

| | first deployment ([`programs`](../programs)) | second deployment, 2.0 (0.3.12) | second deployment, 2.1 (this release) |
|---|---|---|---|
| can it be changed | no: neither program has an upgrade authority | through the multisig, after 48 hours | the same |
| the unit | a bounty | a bounty | a work order; 2.0 bounties finish as they were funded |
| who may sign a payment | the funder's repository | the funder's repository | one of four judges (section 2) |
| the fee | from the payment | from the payment | paid by the funder on top |
| after the pay token | a veto window | final at once | final at once, but for a holdback the funder set at funding |
| the fee's size | 2.5% | 2.5% | tiers: 2.5%, 1%, 0.5%; at least 0.40. From knos_pay 2.2 (in this tree, not live until its upgrade executes): 0.30%, at least 0.05, for jobs and orders alike; orders funded before the upgrade keep the rate fixed at their funding |
| the most one holds | 500 | 500 | 100,000 on devnet |
| what makes a token single-use | see [`programs`](../programs) | the bounty closing; a fund token by being newer than the Balance's last | one marker rule for every token (section 15) |
| live | yes, for the bounties funded there | yes | from the moment the upgrade executes |

2.1 was first proposed by 0.3.13 and never executed. The 2.1 of this release is the corrected build: the same
version name, different bytes, a new proposal and a new 48 hours. Release builds of every program in `programs-v2`
are compiled with `overflow-checks = true` from this release; before it, arithmetic the source did not check
explicitly would have wrapped silently.

The upgrade keeps every 2.0 instruction's bytes and behaviour, except these fixes that take effect for 2.0 bounties
too when it executes: whole-unit limits, the extension list, the Balance's side account, and the single-use rule
for every token.
Audiences of the new paths start `knos3:`, so no token of one generation is good for the other. `knos-meter` and
`knos-passkey` are programs at their own addresses, live once the release run has deployed them. The meter never
calls the escrow, and a passkey wallet's withdrawal does not either, so the relay carries evaluations and
withdrawals from then, before the upgrade executes. A passkey wallet's `Fund` does call the escrow's
`FundOrderWallet`, so it works only once 2.1 is live.

Mainnet will be different program ids and Circle's mint. Nothing is deployed there.

## 9. When something goes wrong

| what happens | what the system does | what still works |
|---|---|---|
| One of GitHub's signing keys leaks | the guardian revokes it. Tokens it verified stop at once. An order waits for a token under a good key | everything else |
| GitHub is down, or changes its tokens | tokens wait. Nothing is paid | refunds at the deadline, withdrawals, releases of a holdback |
| No key is attested for 30 days | every key expires. The escrow is refund-only. Anyone can prevent this for the keys GitHub still publishes (section 5) | refunds, withdrawals, held orders whose payee has a bound wallet |
| A fault is found in a program | the guardian can refuse new funding, 7 days at a time. A fix is an upgrade: public, and 48 hours away | payments, refunds, withdrawals, bindings |
| The upgrade keys are stolen | a hostile upgrade is public for 48 hours before it can run. The members can cancel it | withdrawals of Balances at once; orders as section 7 says |
| The buyer's repository deletes its workflow after a merge | nothing, by itself. In a public repository the seller starts the neutral run (section 2) | the payment |
| Knos's public relay stops | tokens wait as comments | anyone can relay with `knos relay`, and a payment tips whoever does; a repository with a relay key relays its own |
| Knos's GitHub account is suspended | the published workflows cannot be fetched, so no new token is signed for an order that pinned them; no key can be refreshed | refunds, withdrawals, settlements to a bound wallet, releases. A funded order can only be refunded ([GOVERNANCE.md](GOVERNANCE.md), section 9) |
| Devnet is reset | every account is gone: programs, orders, Balances, keys, the multisigs | nothing on chain. It is test money. The programs are deployed again and funders fund again ([DRILLS.md](DRILLS.md)) |
| Knos disappears | no new key can be approved. Keys GitHub still publishes are kept alive by anyone | payments under those keys; refunds and withdrawals, for ever |

The three emergency tools, and their reach: a **pause** stops new funding and nothing else, for at most 7 days per
signature; a **revocation** stops one key and what it signed, for ever; an **upgrade** can change anything, 48 hours
after it is approved in public.

## 10. Recovery without GitHub, and without Knos

These need no token. Anyone can send them, and none reads the pause ([INVARIANTS.md](INVARIANTS.md), invariant 6,
says exactly what a sender needs):

- **Refund.** An order with no payment by its deadline goes back where it came from, amount and fee
  (`test_an_order_goes_back_to_its_funder_after_the_deadline_and_not_before`).
- **Withdraw.** The wallet that opened a Balance takes its unspent money back at any time.
- **Settle to a bound wallet,** for a held order whose payee has a wallet.
- **Release.** After the warranty, anyone sends the holdback to the wallets the order recorded.
- **A passkey wallet's withdrawal** needs only the passkey.

## 11. A Balance, mints and extensions

**A Balance and its limits.** A Balance is money a wallet set aside for the orders of one GitHub owner. Its wallet
sets, and only its wallet changes: a cap per order; up to four GitHub accounts that may spend it by comment; and, in a
side account (`SetBalanceX`), a limit per day, a limit in total, up to eight repositories that alone may spend it, and
the one commit of the pinned workflows that may spend it (`test_a_balance_with_a_side_account_enforces_all_of_it`).
Only that wallet takes unspent money back.

What the limits do not do. A Balance with no side account has only the cap per order: the side account is the
wallet's choice. With none, whoever can change the workflow files on the default branch of any repository of that
owner can make the owner's next comment fund any issue there. With one, the damage of a compromised repository is
bounded by the day's limit and the list of repositories. A wallet-funded order needs no Balance and trusts nobody
but the judge it names.

**Bounds.** An order holds between 5 and 100,000 whole units on devnet. The upper bound is a devnet number: a
mainnet build decides its own cap, and none has been decided.

**Mints and extensions.** Limits and the fee floor are in whole units of the mint, read from the mint's decimals
(`test_a_jobs_bounds_and_fee_floor_are_whole_units_of_its_mint`). The public record counts money as real only in
Circle's USDC (devnet `4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU`, mainnet
`EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`). The faucet's mint and every other mint count as test
(`test_the_record_counts_real_money_only_in_circles_usdc`).

Money enters only in an SPL Token mint, or a Token-2022 mint whose every extension is on a list
(`ALLOWED` in [`token.rs`](../programs-v2/knos_pay/src/token.rs)): the extensions that change nothing about who
holds how much or whether a transfer goes through. A transfer hook (even one that names only an authority), a
transfer fee (even of zero), a permanent delegate, a default account state, Pausable, and every extension the
program does not know are refused, including ones added to Token-2022 later
(`test_money_enters_only_in_a_mint_whose_every_extension_is_on_the_list`). Money leaving is never held to these
rules: what entered can go out. A mint's issuer keeps its freeze authority, and no program can take that away.
`knos-meter` takes credits only in Circle's USDC.

## 12. Private repositories: exactly what the chain shows

A private order is driven from one ATTESTOR repository the organisation chose
([`examples/knos-attestor.yml`](../examples/knos-attestor.yml)): its policy file names the private repositories it
may attest for, its runs (started by hand or by its schedule) read them through a token the organisation gave it,
check nothing out, and write only comments there. The order is funded from the organisation's Balance, which must
list the attestor, and is paid on a run in the attestor (judge c). The salt and the terms live in a comment on the
private issue, where only people with access can read them; if that comment is deleted the order cannot be paid and
returns at its deadline. A public attestor's policy file names its targets: keep the attestor private if the names
themselves are secret. For a private order the chain shows:

- the amount, the fee, the mint, the deadline and the options;
- the Balance it came from, with the GitHub id of the organisation and of the account that commented;
- the judge repository's id and, in the tokens, its name, the branch, the commit of the pinned workflows and the
  account that started each run;
- a hash of the scope (the private repository's id and the issue, with a 32-byte salt) and a hash of the terms;
- at the payment: each payee's GitHub id, the wallet paid, a number derived from the salt in place of the pull
  request's, and the hash of the accepted commit (which says nothing to anyone without access to the repository);
- the arbiter's GitHub id, if one was named.

It does not show the private repository's name or id, the issue's number, the names of the checks, or the path
globs. `test_a_balance_funds_a_private_order_from_its_judge_repository_and_nothing_of_the_repository_is_public`
scans the order's account, both tokens and every log line for them. The salt keeps the scope from being guessed
from a known repository id. Anyone who knows the organisation's id sees that it paid, how much, and whom.

Nothing is posted in public only when the repository relays its own tokens, with a Solana key in its secrets
(`KNOS_RELAY_KEY`). That key pays fees and decides nothing.

## 13. The supply chain

- **The workflows, by commit.** An order records the repository that holds the workflows and their commit. The
  published workflows take no inputs that name code: a caller chooses when they run, never what they do.
- **A funder can pin other workflows than Knos's.** A seller can read what an order pins on chain before starting.
  The neutral judge and the policy file mean what this page says only for the published workflows.
- **Signing jobs install by hash.** Every job that asks GitHub for a token (`fund.yml`, the `settle` and `attest`
  jobs of `prove.yml`, `attest.yml`) installs `knos` and everything it needs from a list of sha256 hashes written
  into the workflow at the pinned commit, with `--require-hashes`, and restores and saves no Actions cache. What
  those commands import is the standard library and `solders` (`tests/test_signing_path.py`).
- **The judge job's boundary.** One job runs a pull request's code: `judge`, in tests mode. It has no id-token and
  no secret, its token can only read the repository, and it uses no cache. It, and the `review` job that writes the
  check's comment, install `knos` by version, not by hash. So a dependency published after the release could run
  in those two jobs. Neither can sign. What the `attest` job takes from `judge` is one fact, that it succeeded.
- **The hermetic judge, an option.** A repository can instead name the judge's image by its sha256 digest, so that
  what judges a submission is fixed by content and nothing is installed by version when the job runs. It is not the
  default: an order that does not ask for it is judged as the line above says.
- **The release.** The list is `requirements/sign.txt` of this repository plus one line: the `knos` package of the
  release, by the sha256 of the file that was built ([`scripts/pinned_workflows.py`](../scripts/pinned_workflows.py)).
  So the commit of the workflows names the hash of everything a signing job installs.
- **Actions, by commit.** Every action in every workflow and example is named by a full commit
  ([`scripts/action_pins.json`](../scripts/action_pins.json)).
- **The programs, reproducibly.** What is deployed is the `solana-verify` build of this repository in a pinned
  image. [ASSURANCE.md](ASSURANCE.md) has the commands, and [DRILLS.md](DRILLS.md) prints the hash of the bytes on
  chain.
- **From source to chain.** docs/PROVENANCE.md follows each program from source commit to build hash to the hash on
  chain to its upgrade proposal; a link the repository does not record is printed as MISSING.
- **Two of the builds before the upgrade have no build record.** The knos_oidc and knos_pay builds that ran at the
  public ids until proposals 3 and 4 executed have no build record at the upgrade gate, so nothing on chain ties
  those builds to a commit; knos_meter's and knos_passkey's have one. The four builds that run there now, those of
  proposals 3 to 6, each have one ([PROVENANCE.md](PROVENANCE.md)).

## 14. The sandbox (tests mode)

Payment without a merge is offered only when the acceptance bundle is black-box: the submission runs as a separate
process and only its output is compared ([TAMPER.md](TAMPER.md): of 63 cheating pull requests, plain CI passed 56,
in-process acceptance tests 7 and the black-box check none).

Everything that runs a pull request's code runs as another user (uid 65534) with an empty environment, and the
tests run with no network. The repository's own acceptance bundles are removed from the work tree before the
submission runs ([`src/knos/judge.py`](../src/knos/judge.py)). That is a separation between users on one machine,
not a virtual machine. A flaw in the runner's kernel or image that lets one user become another would let a pull
request write its own verdict. The dependency install does have the network. The hermetic option (section 13)
fixes the judge's image by digest; it does not turn the user boundary into a machine boundary.

## 15. Tokens: public, bound to one action, used once

A token is not a secret. A workflow without a relay key posts it as a comment, and anyone may carry it to the
chain. What it can do is fixed by its claims and its `aud`, and it does it once.

**One rule for every token `knos_pay` takes.** Each instruction that takes a signed token creates the marker account
`["used", sha256(the token's signature)]` once it has decided to accept the token and before it changes anything
else, and refuses the token with error 91 when that marker already exists. The marker is named by the token alone,
not by the order, the job or the wallet the token is about. So the same token is never accepted twice, by the same
instruction or by another one, whatever the other accounts hold by then.

| instruction | token | what a second use of the same token does |
|---|---|---|
| `FundOrderBalance` | fund an order from a Balance (`knos3:fund`) | refused. Tokens of one Balance may arrive in any order |
| `PayOrder` | pay an order (`knos3:pay`), a ruling (`knos3:rule`) | refused, also when the order was paid and a later funding put a new order at the same address, and also when the first use only held the order for a payee without a wallet |
| `Revert` | return a holdback (`knos3:revert`) | refused, also for the holdback of a later order at the same address |
| `Reserve` | take an order (`knos3:take`) | refused, also after the reservation has run out |
| `Cancel` (a Balance's order) | give notice (`knos3:cancel`) | refused, also for a later order at the same address |
| `Pay` | pay a 0.3.12 bounty (`knos2:pay`) | refused: one token pays, or holds, exactly one bounty |
| `FundBalance` | fund a 0.3.12 bounty (`knos2:fund`) | refused. It must also be newer than the Balance's last: a later token that lands first makes an earlier one useless, and the funder comments again. Orders do not have this limit |
| `Bind`, `BindOrg` | bind a wallet | refused. It must also be newer than the last binding |
| `FaucetOpen` (devnet only) | the fund token of a faucet Balance | refused. The faucet marks the token as minted on, and the funding instruction that follows is the one thing that still takes it; after that it is used |

`knos_meter` counts an evaluation (`knosm:eval`) once by its own marker, per work order, artifact, policy and
milestone.

**An order's `not_before` is the chain's time at its funding** (less 30 seconds for clock difference), never a
token's issue time. A pay, take or cancel token issued before an order was funded is refused by that order, so an
order funded again at an address does not inherit the tokens of the order that was there before.

**What 0.3.13's build did not hold.** In the build tagged 0.3.13, `PayOrder` made no marker, and an order funded from
a Balance took its `not_before` from the fund token's issue time. An order's address is the same for every funding
of one issue from one Balance under one number. So with two fund comments on one issue, relaying the second fund
token after the first order was paid re-created the order at the same address, and the pay token that had paid the
first order paid the second too: a payee received 200 on a 100 order, and the Balance lost 205. `Revert`, `Reserve`
and `Cancel` took their tokens without a marker in the same way. This was found before that build went live on any
cluster, only test USDC was ever involved, and that build is not the one proposed for upgrade. It is fixed here by
the two rules above. `tests/test_double_pay.py` reproduces the
sequence and requires the second payment to be refused, the payee to hold 100 and the Balance to be down 100 and
one fee; it also sends every token-taking instruction's accepted token a second time, with the accounts as they are
and with the accounts made again, and requires that no token account anywhere changes.

**What this costs.** Every instruction that takes a token pays the rent of one 41-byte marker (from the relayer,
returned later) and about 40,000 more compute units than without one: `PayOrder` to one payee measured 115,036
units before and 154,764 after, in the simulator (the later figure also has overflow checks on).

Every token stops working an hour after its expiry, and one dated more than five minutes ahead of the chain's clock
is refused. A marker stores who paid its rent and the time after which no instruction could accept its token
anyway; from then `CloseMarker` closes it and returns the rent to whoever paid it
(`test_a_used_marker_is_closed_once_no_token_it_stands_for_can_be_accepted`,
`test_a_marker_gives_its_rent_back_once_no_instruction_could_take_the_token`).

## 16. The check, its memory, the Stop hook and the MCP tools

**The check** on pull requests is advice. No payment depends on it.

**What it remembers.** The check keeps what it learned (a rule this repository's history made required) as comments
in an issue labelled `knos-memory`. Only comments that GitHub Actions itself wrote there, and that nobody edited,
are read ([`src/knos/proof/memory.py`](../src/knos/proof/memory.py)). A run with a read-only token, such as the
check on a pull request from a fork, writes nothing. Closing the issue makes Knos forget. A payment depends on the
order's terms alone.

**The Stop hook.** `knos init` adds a Stop hook to coding agents on a machine. When the agent's last message claims
that tests pass, CI is green, a release or a bare "done", Knos runs that check itself and blocks the stop if it
fails. It is a local aid: a person can remove it, and an agent run without hooks does not have it. What it learns
stays in Sibyl's store on your machine ([`src/knos/store.py`](../src/knos/store.py)).

**The MCP tools** hold no key and send nothing. The ones that act return the exact comment or transaction for a
person or an agent to send. Whatever a repository or an account wrote is returned in a field named `untrusted`, cut
short, and the server's own sentences never repeat it ([`src/knos/mcp.py`](../src/knos/mcp.py)).

## 17. The passkey wallet

A payee with no wallet app can be paid at an address derived from a WebAuthn passkey
([`programs-v2/knos_passkey`](../programs-v2/knos_passkey)). Money leaves it only on an assertion of that passkey
that names the mint, the destination, the amount and a number used once. Solana's own secp256r1 instruction checks
the signature; the program checks what was signed. Nobody signs the transaction but its fee payer, so a relay can
carry it. No key of Knos's is named in the program. A withdrawal never calls the escrow, so the public relay carries
one from the moment `knos-passkey` is deployed, whatever the escrow's version, and refuses one only on a
cluster where the program is not deployed (`test_a_passkey_withdrawal_request_is_simulated_then_sent_at_the_relays_cost`).

**Funding with a passkey (1.1).** A funder who has only a passkey can fund an order: `Fund` moves test USDC from
the passkey wallet into an order of `knos-pay` (a call to `FundOrderWallet`), on an assertion over a challenge that
binds the hash of the order's terms, the amount and a slot after which the assertion is no longer accepted. A
relayer pays the transaction fee, so the funder needs no SOL and no wallet app. What the funder cannot see is the
same as for a withdrawal: the authenticator shows the site, not the terms or the amount, so the page is trusted to
have hashed what it showed. The order refunds to the passkey wallet.
On devnet the site shows and withdraws Circle's USDC and the faucet's test USDC, which a bounty funded by comment pays.

What is trusted:

- **The device and its keychain.** Whoever can use the passkey can empty the wallet. A passkey that is lost is
  lost money: the program has no recovery.
- **The page that asks for the signature.** The authenticator shows which site asks, not what is being signed. The
  amount and the destination are inside a hash. A page on the passkey's site that lies about them gets a valid
  assertion. The site is static files in this repository, served by GitHub Pages.
- **The site's name.** A passkey works only on the site it was made on. If that name is lost, so is the way to use
  the passkey.

Use it for small amounts paid out soon, and bind a wallet you hold the key to for anything else.

## 18. The meter

`knos-meter` moves no customer money. It counts evaluations that GitHub signed and takes its own fee from credits
somebody prepaid ([`programs-v2/knos_meter`](../programs-v2/knos_meter)).

- An evaluation is a run of the pinned `attest.yml` or `prove.yml` in a repository of the **buyer**: the
  workflow file and the commit the buyer's credits pin (OpenCredits), first attempt, GitHub-hosted runner. So the
  count says what the buyer's own run found. A buyer whose repository never runs it is not counted, and the seller
  then has GitHub's public record and no count.
- The published path is `attest.yml` with the kind `eval` (`knos attest --kind eval`; the caller is
  [`examples/knos-attest.yml`](../examples/knos-attest.yml)), started in a repository of the buyer for a pull request
  in a repository of that same owner. The verdict is GitHub's record of what the buyer did with it: merged is
  accepted, closed unmerged is rejected, an open one is not evaluated. The seller is its author, the artifact its
  head commit, the policy the hash of that one rule (`EVAL_POLICY` in [`src/knos/flow.py`](../src/knos/flow.py)).
  The work order, the milestone and the rate are the buyer's inputs. The token is posted as `knos-eval:` on the
  "knos tokens" issue of the run's repository, where the relay finds it
  (`test_attest_eval_signs_one_evaluation_for_the_meter_from_the_buyers_own_record_and_posts_it_as_knos_eval`).
  `prove.yml` signs no evaluation in this release: the program accepts it, and nothing published asks it to.
- The relay carries an evaluation from the moment `knos-meter` is deployed. The meter never calls the escrow, so it
  does not wait for the escrow's upgrade (`test_an_evaluation_is_recorded_by_the_meter_once_and_what_it_would_refuse_costs_nothing`).
  It reads tokens verified by the verifier at the address in its own source, the deployed one.
- A billable evaluation is one work order, artifact, policy and milestone. A retry or a duplicate is free. A
  rejection is billed (`test_an_evaluation_is_billed_and_counted_once_and_a_retry_is_free`,
  `test_a_rejection_is_billed`).
- The rate in the count is what the token declares. The meter does not check it against a contract.
- A statement is recomputed from the program's logs alone (`test_the_counters_equal_the_logs`).
- `FEE_OWNER` receives the fees and can lower one owner's rate. It cannot change a count or take credits. Credits
  never go below zero, and only the wallet that opened them withdraws them.
- A token under a private key, a revoked key or an expired key counts nothing.

**Batch mode (1.1).** A single evaluation writes one account, whose rent is more than the evaluation's price. A
batch writes none per evaluation: `RecordBatch` takes one signed token that carries the buyer, the seller, the
month, a sequence number, the count, how many were accepted, their value and a 32-byte Merkle root, and adds them to
one Ledger account per buyer, seller and month, which keeps totals and a running hash of every batch.

- A batch token is taken once: its sequence number must be the Ledger's next.
- The fee is the count times the rate beyond the month's free allowance, from Credits, and a batch Credits cannot
  pay is refused whole.
- **The program stores the root and does not check it.** It cannot see the evaluations. That the root covers the
  evaluations it claims is checked off chain, by anyone who holds the ledger file
  ([`src/knos/ledger.py`](../src/knos/ledger.py)): every root and the running hash are recomputed and compared with
  the chain, and one evaluation's inclusion can be proved.
- **A buyer can leave events out.** The count is the buyer's. `ClaimBatch` is the seller's own count, from a
  repository the seller owns, written beside it at no fee. Two different counts on chain show that the sides
  disagree; which events are missing is found by comparing the two ledger files, not by the program.

## 19. Paid without a merge, challenged, and judged by more than one

Three options of a work order in knos_pay 2.1 change who has to say yes before money moves. Each is the funder's
choice at funding: it is in the order's options, which the fund token (or the funding wallet's own signature)
fixes, and it cannot be changed afterwards. None of the three has run on devnet: the tests
(`tests/test_order_auto.py`, `tests/test_order_quorum.py`) run them in a simulator, on builds made for testing.

**Auto-accept (`/knos fund ... auto`, flag 32).** The first pull request that passes the order's black-box
acceptance suite is paid, unmerged, to its author. The program takes it only on an order funded in tests mode
(mode 1), which is the mode the pinned workflow gives only to a black-box bundle; funding an `auto` order in
merge mode is refused. The token's audience is `knos3:auto:<order>:<head sha>:<terms hash>:1:<pr>:<payee>`, from
the pinned `prove.yml` run in the order's own repository.

- What the buyer trusts: the pinned suite at the pinned commit. That is the workflow file at the commit the order
  recorded (it decides that the bundle is black-box, that the head is still the pull request's, that the changed
  paths are within the terms, and who the author is) and the acceptance bundle whose hash is in the terms. No
  merge, review, label or comment is asked, and none can stop the payment short of the deadline or a cancel's
  notice.
- What the program enforces: the order's own repository and pinned workflow, a first attempt, the order's terms
  hash, one payee, the order's deadline, and, while the order is reserved, that the payee is the taker. The token
  is used once, like every token. The first passing pull request closes the order; a second token finds nothing
  open. An order funded without `auto` refuses every such token.
- What it does not: a pull request that fools the suite is paid. The measured count for the black-box judge is
  0 of 63 cheating pull requests in Knos's own suite ([TAMPER.md](TAMPER.md)), which is a count for that suite
  and not a proof. A funder who wants a second look combines `auto` with a holdback and a warranty, so that part
  of the money can still be challenged, or with a quorum.

**Challenge (Revert, instruction 19).** While an order is in its warranty, its holdback and the fee on it are
still in the order. For an order that allows a neutral run, anyone can challenge the payment: he starts the pinned
`attest.yml` by hand (kind `revert`) in a repository of his own. It reads GitHub's record of the order's repository
and signs `knos3:revert:<order>:<head sha>` only when a commit on the default branch after the merge reverts the paid
pull request's merge commit (its message says `This reverts commit <merge sha>`, as `git revert` and GitHub's Revert
button write it). It does not run the acceptance checks on the head again, and it signs nothing for a pull request
that was not merged, so an `auto` payment, which is made unmerged, cannot be challenged by a neutral run today: only
the program would take such a token. Revert then returns everything the order still holds to its funder. After the
warranty the same token is refused and Release pays the holdback. Rehearsed on devnet on the staging programs in
0.3.14: a `quorum 2` order with a 20% holdback, its merge reverted, a neutral run by an account that was not its
funder, and Revert returned the holdback and its fee.

- No bond is asked of a challenger. A bond prices false challenges; here a false challenge cannot be made, because
  the token is GitHub's signature over a run of the pinned file at the pinned commit on a GitHub-hosted runner,
  and that file decides what it signs, not the person who started it. A challenge costs one transaction fee and
  the rent of the token's marker.
- Limits. What was already paid stays paid: a challenge returns the holdback only. The order keeps no record of
  the head it paid, so that the head a challenge names is the one that was paid is the pinned workflow's word,
  not the program's. An order funded with `neutral off` is challenged only from its own or its judge repository.
  A judge that is not deterministic can fail a head it passed before; the hermetic judge pinned by image digest
  is the answer to that, and it is not required by the program.

**Quorum (`/knos fund ... quorum 2` or `quorum 3`, the two high bits of the flags).** PayOrder pays only when
that many distinct judges have each passed the same artifact: the same head commit, terms, mode, pull request and
payees. The judges are a. the order's own repository's run, b. a neutral run, c. the judge repository the order
names. Each judge before the last leaves a marker `["q", order, kind]`; the last one pays. Two tokens of the same
kind count once. A marker's rent goes back to whoever paid it (CloseMarker) once its order is no longer the open
order it was made for. A marker left by an earlier order at the same address counts for nothing.

- The three marker accounts are fixed addresses and all three are always passed, so a relayer can neither count
  one judge's marker as another's nor hide one to use up the last judge's token without paying.
- A neutral run counts toward a quorum only as a third party's: not one in the order's own repository, and not
  one started by the account that funded the order or owns its Balance.
- Limits. GitHub does not sign who a person is beyond an account id, so two accounts of one person are two
  judges: a quorum raises the cost of a false payment, it does not prove independence. The judge repository is
  the funder's choice. A quorum is refused at funding when the order cannot have that many judges, on a standing
  order and on a private order. The arbiter's ruling pays without a quorum, as both sides accepted at funding.

Compute, measured in the simulator (it varies by a few thousand units with the addresses involved): PayOrder on an
auto token about 90,000 units, or about 176,000 when it creates the payee's token account; a challenge 86,000 to
98,000; PayOrder on an order with a quorum about 120,000 for a judge who is recorded and about 176,000 for the
one who pays and creates the payee's token account.

**What is built end to end, and what has run.** Every step from the funding comment to the payment exists in code
and is tested against stand-ins for GitHub and the chain; none of it has run on a cluster.

- Funding. `/knos fund ... auto` and `quorum 2` are parsed (`src/knos/commands.py`); the workflow's fund word puts
  them into the order's options, which the fund token signs, and the reply says both in plain sentences
  (`src/knos/flow.py`, `tests/test_flow_orders.py`). `auto` is refused, with what to add, when the issue has no
  black-box acceptance checks; a quorum is refused when the order cannot have that many judges. A public order has
  two (its own repository's run and a neutral run), so `quorum 3` is refused by a comment today: the third judge
  is a judge repository, which only a private order names, and a private order takes neither option.
- Payment. The pinned `prove.yml` is unchanged in its jobs, events and permissions: the judge job runs the
  submission with no id-token, and the attest job, which checks nothing out and runs none of that code, asks
  GitHub for one token. `knos settle --tests` chooses its audience: `knos3:auto` when the order has the flag and
  the pull request is open, `knos3:pay` otherwise. The token is posted for the relay as a pay token is, and the
  relay carries it (`src/knos/settle/v2/relay.py`).
- Who is paid. On an `auto` order an open pull request pays its author, and that author may be an agent's own
  GitHub account (type Bot); such an account may also reserve the order with `/knos take`. Everywhere else a bot's
  pull request still pays a person, by a maintainer's assignment or `/knos pay`, and `/knos take` is refused to a
  bot. The pull request must still close the issue, a maintainer's `/knos reject` still stops it, and an issue
  someone else holds is still theirs. These are the workflow's rules; of them the program holds only the last
  (the taker, while the order is reserved).
- Not done. Nothing in this section has run on devnet: not a funding with either option, not an `auto` payment,
  not a quorum, not a challenge. The programs that take these tokens are not deployed, and the pinned workflows
  repository does not yet publish the `prove.yml` that asks for a `knos3:auto` token: it is republished at
  release. A second judge's run for a quorum is started by hand (`knos settle --neutral`); nothing starts it for
  an open pull request. An agent's account with no bound wallet is paid only at the address in its own
  `/knos address` comment on the pull request, and the reply to that comment still reads as a refusal.

## 20. A neutral judge that runs the suite again

GitHub signs which workflow ran, at which commit, in which repository, started by whom. It does not sign what that
workflow read. Until 0.3.15 a neutral run (judge b, section 2) reached every verdict by reading: the conclusions of
the checks at the merged commit, through GitHub's API. A check in the buyer's repository that was wrong, or that
someone with write access there had made say "success", was repeated by the neutral judge, not caught. And an order
paid by its acceptance checks (tests mode) took no neutral run at all: only its own repository ran the suite.

**What changed, with no change to any program.** The pinned `attest.yml` now has two jobs
([`.github/workflows/attest.yml`](../.github/workflows/attest.yml), `knos attest` in
[`src/knos/flow.py`](../src/knos/flow.py)).

- `rerun` has a read-only token, no `id-token` permission and no secret. For an order paid by its acceptance checks
  it reads the order on Solana and the pull request, fetches two commits from the order's public repository by
  their ids (the commit the pull request was merged onto, and the commit that was merged), checks that the bundle
  in `.knos/acceptance/<issue>/` at the first one hashes to the `accept` of the funded terms, and runs the suite
  itself: in the judge's sandbox (section 14), or in a container of the image the terms name by digest. It writes
  a verdict and fails unless the suite passed.
- `attest` starts only when `rerun` succeeded. It checks nothing out, runs no git and takes no artifact. It
  receives the verdict as text in an environment variable and treats it as written by a job that ran a stranger's
  code: one JSON object of fixed fields, each held to a shape, at most 8,192 characters. It reads the order, the
  pull request and the bundle again itself, and asks GitHub for the token only when the verdict passed and names
  this order, repository, pull request, issue, base commit, head commit and bundle hash, with the terms' image when
  they name one. The token and its audience are what the program accepts today: `knos3:pay:...` with the order's
  own mode.
- `refused` starts only when `rerun` failed after it reached a verdict. It has no `id-token` permission. It runs the
  same command with that verdict, which refuses it, and posts the verdict on the "knos tokens" issue with the sentence
  that says why nothing was signed.

**What the verdict records.** `reexecuted` (true or false), `passed`, `assurance` (`black-box` or `hermetic`),
`image` (`ref` and the `digest` the runtime reported), `artifact` (a hash of each of the two trees, the ones
`knos judge rerun` compares), `order`, `repository`, `pull`, `issue`, `head`, `base`, `accept`, `reasons`,
`sentence`, and `environment`: the repository and run it happened in, the runner's operating system, architecture
and image version, and the `knos` version. It is kept as the run's artifact `knos-verdict-<attempt>` (`verdict.json`), it is
the job output `verdict`, and it is posted as a comment that starts `knos-verdict: ` beside the token on the "knos
tokens" issue. GitHub's signature covers none of it: the token says which workflow ran and where, and the verdict
is that workflow's own account of how it decided.

**An order paid on the merge is not re-executed.** Its terms name checks that are the repository's own (its CI),
and nothing outside that repository can run them. The neutral run keeps reading their conclusions, and its verdict
says `reexecuted: false` with the sentence "this judge read the buyer repository's check results; it did not run
them". The same holds for any other check that the terms of a tests-mode order name beside the suite: the suite is
run again, those are read.

**What the second environment adds.**

- An independent execution. The suite runs on a GitHub-hosted runner in the attester's repository, under the
  attester's account. Nothing the buyer configures reaches it: not the buyer's workflow files, runner, secrets,
  cache, branch protection or check results.
- A check result that lies is no longer enough. With `quorum 2` on an order paid by its checks, the buyer's own
  run and a neutral run must each pass the same commit, and the neutral one has run the suite itself. When the suite
  fails there, the neutral run signs nothing and the order does not pay
  (`tests/test_attest_rerun.py::test_with_a_quorum_of_two_the_buyers_green_checks_alone_pay_nothing_when_the_second_run_fails`).
- A record of how the verdict was reached, which a receipt can show beside the verdict.

**What it does not add.**

- A second suite. It is the same bundle, by its hash. A suite that is wrong is wrong twice: a check that a stub
  passes in the buyer's repository is passed by the same stub in the attester's.
- A second GitHub. Both runs are GitHub-hosted runners, the commits are fetched from GitHub, and the order's
  record is read through GitHub's API. A fault in GitHub's runner image, or a GitHub that served other bytes for a
  commit id, is common to both. (A commit id is a hash of its content and git names what it fetched by that
  hash, so other bytes under the same id would need a collision in the hash git uses.)
- A second copy of Knos. Both judges run the pinned workflow at the commit the order recorded, and the same
  `knos` release. A fault in that code is common to both.
- Independence of people. GitHub signs an account id, not who a person is. The program counts a neutral run toward
  a quorum only when it is not in the order's own repository and was not started by the account that funded the
  order or owns its Balance, and that is all it can know. **Two accounts of one person are one judge**: a buyer who starts the neutral
  run from a second account of his own has two tokens and one opinion. Whoever relies on a quorum has to know who
  controls each account; no field on chain says it.
- A deterministic judge. A suite that draws its inputs at random draws new ones in the second run. Without an image
  in the terms the two runners can differ in what is installed.
- Without a quorum, a second judge at all: the first valid token pays (section 2), so on an order with no quorum
  the buyer's own run alone still pays, and the re-execution only gives the seller a way to be paid that does not
  rest on the buyer's check results.

**What the run costs and what it risks for the attester.** The first job runs code from a pull request in the
attester's repository. It has what the judge job of `prove.yml` has and no more: a token that reads, no secret, the
sandbox's separate user with no network. Limit 16 applies to it as it does there: the sandbox is a user boundary,
not a machine boundary. A submission that escaped it could write the verdict the next job reads; that job then
still checks the order, the merge, the scope, the payee and the bundle hash itself, but it would take the suite's
"passed" from the forged text. This is the trust judge a already places in its own judge job.

**What is not done.** None of this has run on GitHub or on a cluster. It is tested against stand-ins for GitHub and
the chain, the program's side in a simulator, and the real judge once on a sample tree
([`tests/test_attest_rerun.py`](../tests/test_attest_rerun.py)); the workflow file is checked by actionlint and by
[`tests/test_workflows2.py`](../tests/test_workflows2.py), and its fetch and sandbox steps have not been run on a
runner. Whether the work-order instructions are live on the public program ids is in `web/upgrades.json`. The
pinned workflows repository must publish this `attest.yml` before any order can pin it: it is republished at
release, and an order funded earlier is held to the older file at the commit it recorded, which does not
re-execute. A neutral run is still started by hand. The program does not know whether a neutral token came from a
run that re-executed: it accepts a token from the pinned file at the pinned commit, and what that file does is fixed
by that commit. An `auto` payment made before the merge is not re-executed by a neutral run, which judges merged
pull requests only. This section narrows limit 15 below ("tests mode has no second look") for orders that ask for a
quorum; it does not remove it.

## Where untrusted code runs

The rule: a pull request's code and its tests never run in a job that can ask GitHub for a signed statement
(`id-token: write`) or that holds a credential that can write to the repository; and what the job that signs takes
from the job that ran such code is data it checks again, never an instruction. This section is the audit of the
workflows a repository installs (`fund.yml`, `prove.yml`, `check.yml` and `attest.yml`, published to
`drexthealpha/knos-workflows` by [`scripts/pinned_workflows.py`](../scripts/pinned_workflows.py)), of the two files that
call them (`knos.yml`, `knos-check.yml`) and of `hermetic.yml`, job by job, and what this release changed.
[`tests/test_workflows2.py`](../tests/test_workflows2.py) holds the shape and
[`tests/test_verdict_gate.py`](../tests/test_verdict_gate.py) the hostile cases.

GitHub's own guidance is the same rule in other words: code from a pull request "is only ever inspected as data and
never executed" where a privileged token exists, a `workflow_run` workflow "should treat artifacts uploaded by other
workflows as untrusted data"
([securely using `pull_request_target`](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)),
the job token gets "the minimum required permissions", and "pinning an action to a full-length commit SHA is currently
the only way to use an action as an immutable release"
([secure use reference](https://docs.github.com/en/actions/reference/security/secure-use)). No workflow of Knos uses
`pull_request_target`.

**Every job.** "Code" is anything of a repository on the job's disk. Every action is named by a full commit
([`scripts/action_pins.json`](../scripts/action_pins.json)); every job runs on the label `ubuntu-24.04`.

| Workflow, job | Code it has and runs | Token permissions | Signs | What it takes from another job, and how it is checked |
| --- | --- | --- | --- | --- |
| `fund.yml` `command` | none: no checkout; `knos` installed by hash | contents read; issues and pull requests write; checks, statuses, actions read; id-token | yes | nothing |
| `prove.yml` `settle` | none; `knos` by hash | the same | yes | nothing |
| `prove.yml` `review` | none; `knos` by version | the same without id-token | no | nothing. Its outputs `tests`, `pull`, `head` name an issue, a pull request and a commit |
| `prove.yml` `judge` | the default branch (checkout, no credential kept) and the pull request's head as plain files; **runs the pull request's code**, in the sandbox | contents read | no | `pull`, `head`, `tests` from `review`: the first two held to digits and hex before use, all three passed as arguments and never inside a script |
| `prove.yml` `attest` | none; `knos` by hash | as `settle` | yes | from `judge`: that it succeeded, and the output `verdict`, read by the step before the command (below). From `review`: the three names, which the command reads again from GitHub |
| `check.yml` `claims` | none; `knos` by version | read only | no | nothing |
| `attest.yml` `rerun` | two commits of the order's public repository as plain files, fetched with no credential; **runs the pull request's code**, in the sandbox or the terms' image | contents read (given to the plan step alone) | no | nothing |
| `attest.yml` `attest` | none; `knos` by hash | contents read; issues write; id-token | yes | from `rerun`: the output `verdict`, held to a strict shape by one step and then to the order, pull request, commits and bundle by the command (section 20) |
| `attest.yml` `refused` | none; `knos` by hash | contents read; issues write | no | the same verdict, to post why nothing was signed |
| `knos.yml`, `knos-check.yml` (callers) | none: each job is one call to a published workflow at a full commit | what the called jobs need between them | through the call | nothing. A called job can only have less than its caller grants, and `judge` asks for contents read |
| `hermetic.yml` `container` (staging only, not published) | Knos's own repository, on a push to its `main` | contents read | no | nothing |

**What the audit found.**

1. *No job has both a pull request's code and the id-token, or a write to the repository's contents.* That held
   before this release and is now one test over every published job.
2. *`prove.yml`: the job that signs trusted one unbound fact from the job that ran the code.* `attest` started when
   `judge` ended in success, and nothing said which pull request, commit or bundle that success was about except the
   run they shared. **Fixed** (below).
3. *`attest.yml`: the verdict was read by one lenient parser.* A key given twice, or characters outside plain
   ASCII, were accepted as whatever the parser made of them. **Fixed**: a step holds the text to one reading first.
   The verdict of that workflow still carries sentences (`sentence`, `reason`, `reasons`, `environment`); they are
   posted, cleaned, in a comment and never decide anything. Removing them is a change to `knos attest` that this
   release does not make.
4. *`attest.yml`: the verdict's artifact had one name for every attempt of a run.* A job run again would write
   into, or fail on, the earlier attempt's artifact. **Fixed**: the name carries the attempt. Nothing downloads that
   artifact; the job that signs reads the job output. Two calls of `attest.yml` in one run still share a name: the
   second upload fails, its job fails, and nothing is signed for it.
5. *The jobs that run code or sign nothing install `knos` by version, not by hash,* with dependencies no newer than
   a date, and the two judges add `pytest` and `pip` unpinned. **Not fixed.** None of these jobs can sign, and what
   `review` hands on is read again from GitHub; but a wrong package there could make a judge say "passed". Locking
   them by hash needs a second lock file written at release, which is release tooling and not workflow shape.
6. *The machine is named by a label, not a digest.* A GitHub-hosted runner's image cannot be chosen by digest; the
   verdict records the image's version as the machine reports it, which nothing signs. The container the hermetic
   judge starts is named by digest (section 13). `hermetic.yml` named `ubuntu-latest` and used the Actions cache;
   it now names `ubuntu-24.04` and uses none.
7. *The sandbox is a user boundary inside one virtual machine* (section 14). GitHub does not let a container job
   choose its network ("The `--network` and `--entrypoint` options are not supported":
   [running jobs in a container](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/run-jobs-in-a-container)),
   so the network is cut where the code starts: a network namespace of its own (`unshare -n`), or `--network none`
   for the container the judge starts itself. Code that broke out of it to root would own the judge's machine: its
   exit status and its verdict. **Not fixable in workflow shape**; what such code could then do is bounded below.
8. *In `attest.yml` `rerun` one step holds the job's read token and a later step runs the code.* The token is not
   given to that step, and the code runs as another user with no network, so it can neither read nor use it short
   of the escape in 7. The token reads public data only. Not changed.

**The fix in `prove.yml`.** After the suite passed, `judge` writes one line of JSON, its only output: `v`, `kind`,
`passed`, `repository_id`, `run`, `attempt`, `workflow_sha`, `pull`, `issue`, `head`, `base`, `accept` (the hash of
the acceptance checks it ran), `changed` and `changed_count` (a hash and a count of the paths it was told the pull
request changed), `runner` and `image`. Every value is a boolean, a bounded whole number or a string of a closed
shape (a commit id, a sha256, one word of a list); none is free text. In `attest`, the step before the command
([`src/knos/verdict_gate.py`](../src/knos/verdict_gate.py)) runs no pull request code, asks GitHub for no token, and:

- reads the line strictly: at most 2,048 bytes, printable ASCII, one object, each key once, exactly those keys;
- holds it to what the job knows itself: this repository, this run (an earlier attempt of it at most), this
  workflow commit, and the pull request, issue and head commit `review` named, on this run's base commit;
- works out again, from GitHub's record: that the commit is still the pull request's head; the hash of
  `.knos/acceptance/<issue>/` on the base commit, file by file; which runner those files call for; what the pull
  request changed (GitHub's comparison of the two commits), and what the judge's own rule, `classify_path`, says of
  each path. A path the rule refuses, a bundle or a runner other than the base commit's, or a list of paths other
  than GitHub's ends the job. A comparison lists at most 300 files
  ([REST: compare two commits](https://docs.github.com/en/rest/commits/commits#compare-two-commits)); beyond that
  the pull request's own list is classified, up to the 3,000 files GitHub lists
  ([REST: list pull request files](https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files)), and the
  judge's list is not compared.

Only then does `knos settle --tests` run. It derives the audience itself from GitHub and the chain, as before, and
is never handed the verdict. A verdict for another pull request, commit, issue, repository or run, a link or an
oversized file in its place, and an artifact with a second file in it are each a test.

**What a judge machine that was taken over can still do.** Say "passed" for the one pull request, at the one
commit, against the one bundle its run was started for, when the suite did not pass. Nothing else: not another pull
request, order, commit or payee, and not a path the rule refuses. That one bit is the judge machine's word, and no
workflow shape removes it; a second judge that runs the suite itself does (section 20, and a quorum, section 19).

**For a repository that installed an earlier commit of the workflows.** Nothing changes until it names the new
commit: the old files, and the release they install, stay as they were. At the new commit the inputs, secrets,
outputs, job names and permissions are the same. What differs: `judge` has an output; `attest` has one more step
and can refuse for the reasons above; the artifact of `attest.yml` is named `knos-verdict-<attempt>`.

## Two findings from the adversarial tests, fixed in this release's `knos_pay` build

Both were found by the adversarial tests of the release before. Both are fixed in the `knos_pay` build of this
release. That build is proposed after the release and is not live at the public id until its proposal executes
([`web/upgrades.json`](../web/upgrades.json)); until then the public program behaves as the findings say.

1. **Quorum counted repositories, not people.** On an order funded from a wallet with quorum 2, one forge account
   that could start the run in the order's repository and the run in the neutral repository satisfied both.
   Enforced by the new build: judges are counted by repository owner, so two repositories of one owner are one
   judge; and the neutral judge must differ from both sides in owner and in the actor who started the run.
2. **Low: a judge's marker outlived its order by a second.** A quorum-2 order paid and funded again at the same
   address within the same clock second inherited the earlier judge marker, so one new token then paid. Enforced by
   the new build: a marker is bound to the funding of the order it was made under, and counts for no other.

What no program can enforce: that two accounts are two people. One person with two forge accounts and two owners
is two judges to the chain. The receipt still records whether evaluators share a controller (`same_controller`,
[RECEIPT.md](RECEIPT.md)); a buyer who needs two independent parties names a neutral repository it does not
control and reads that field.

The tests are no longer ignored and run with the others in
[`programs-v2/handlers/tests/adversarial.rs`](../programs-v2/handlers/tests/adversarial.rs):
`finding_one_account_that_starts_both_runs_is_one_judge_not_two` and
`finding_a_marker_of_the_order_before_does_not_count_for_one_funded_again_in_the_same_second`. In
`programs-v2/handlers`, `cargo test --release --test adversarial` shows both passing on the program as built from
this tree. [INVARIANTS.md](INVARIANTS.md) lists them with the other adversarial tests.

## Before mainnet

- **Every gate is in [MAINNET.md](MAINNET.md).** Mainnet is not planned for this release.
- **An outside review first.** `knos mainnet-check` prints every gate with its evidence. The last one, an outside
  review of the bytes on chain, fails today, on purpose.
- **Different program ids, Circle's mint, no faucet.** The released programs are devnet builds.
- **The cap** is 100,000 per order on devnet. A mainnet build decides its own; none is decided.
- **After the review** the verifier, `knos-oidc`, is frozen: its upgrade authority is removed. The escrow,
  `knos-pay`, stays upgradeable only through the multisig with its public 48-hour delay, so that a defect in the
  program that holds money can be fixed in place. [GOVERNANCE.md](GOVERNANCE.md), section 7, says what that costs.

## Known limits

The first three cannot be removed. They come with the design.

1. **A signature authenticates a statement, not the truth.** GitHub signs that a workflow ran and what it asked
   for, not what it read.
2. **Passing checks and a merge do not show that the work is good.** Of the 63 cheating pull requests in
   [TAMPER.md](TAMPER.md), plain CI passed 56.
3. **Knos inherits GitHub's failures.** If GitHub signs something false, or a key of its leaks, the programs believe
   it until the key is revoked or expires. If GitHub is down, tokens wait.
4. **Nobody outside Knos has reviewed the security of anything:** not the programs, the workflows, the relay, the
   clients, the site or these documents.
5. **One person can change the programs, after 48 hours.** Both multisigs are 2-of-3 and every member key is the
   founder's. No independent signer exists ([GOVERNANCE.md](GOVERNANCE.md)).
6. **An upgrade's notice is pulled, not pushed.** A banner, `knos status` and a feed to subscribe to; no comment on
   repositories with open orders (section 7).
7. **New keys need one account and the guardian.** Keys GitHub still publishes can be kept alive by anyone. A key
   GitHub adds later, and every other issuer's key, needs Knos's account and the guardian's approval. If GitHub
   replaced all four keys at once and Knos were gone, the escrow would become refund-only.
8. **The neutral judge rests on a rule of GitHub's:** that a personal account's hosted runner is GitHub's own
   image. It also rests on the pinned code being right, with the party that gains free to try it.
9. **The buyer's own repository can pay someone else first** (section 2).
10. **In a private repository a buyer can still withhold.** What is left is the arbiter, if one was named.
11. **An arbiter is one account,** fixed at funding. He can rule wrongly, or not at all.
12. **A holdback returns to the funder on the funder's own repository's word.**
13. **A Balance with no side account trusts every repository of its owner** (section 11).
14. **A maintainer can pay a friend.** The record counts a payment apart only when funder and payee are the same.
15. **The second look covers black-box suites only, and has not run on GitHub.** A neutral run executes an order's
    black-box suite again before it signs (section 20). For an order paid on its merge it reads the checks'
    conclusions and runs nothing. The buyer's own run alone still pays, a neutral run is started by hand, and the
    program cannot tell a token of a run that re-executed from one that only read. The two-job `attest.yml` is
    tested locally; it has never run on GitHub.
16. **The sandbox is a user boundary, not a machine boundary.**
17. **The two jobs that cannot sign install by version, not by hash** (section 13).
18. **The policy file and the screening are the workflow's rules, not the chain's** (section 3).
19. **A private order still shows who paid whom, and how much** (section 12).
20. **A passkey wallet trusts the page that asks for the signature, and has no recovery** (section 17).
21. **The meter counts what the buyer's repository ran** (section 18).
22. **The paid token's issuer keeps its powers.** A freeze authority can freeze what is in escrow.
23. **An order holds between 5 and 100,000 units on devnet.** A 0.3.12 bounty has no early exit.
24. **Several people can do the same work.** One pull request is merged and paid. `/knos take` reserves an order
    for one person for its `reserve` days, and several accounts can take turns.
25. **GitLab is paid; other issuers are verified, not paid.** The escrow takes GitHub's and gitlab.com's tokens, and
    a private key's for its registrant's own private orders. The neutral judge is GitHub-only (section 1).
26. **Not run on the deployed programs yet:** [DRILLS.md](DRILLS.md) runs the safety paths on the deployed bytes in a
    simulator, and lists the rows that need real GitHub tokens and were not run. When 0.3.12 was released, no refund,
    key refresh or revocation had run on devnet itself. No instruction of this release had run on devnet when this
    page was written: the tests run them in a simulator, on builds made for testing.
27. **The assurance is the author's own.** [ASSURANCE.md](ASSURANCE.md) says what is tested, what is fuzzed, and
    what is not; its section "Fuzzing, mutation testing and model checking: the state of each" has the differential
    test of the verifier and the fuzz targets, and [`fuzz.json`](fuzz.json) is the recorded run.
28. **Devnet only, and no outside buyer.** By 3 Oct 2026 no outside repository had funded a task.
29. **Everything depends on one personal GitHub account** that hosts the pinned workflows, the rotate workflow and
    the relay. If it is suspended, funded orders can only be refunded and keys run out within 30 days
    ([GOVERNANCE.md](GOVERNANCE.md), section 9). The move to an organisation account is planned and not done.
30. **A meter batch's Merkle root is not checked on chain** (section 18).
31. **The feed of upgrade proposals is as fresh as the site's last build** (section 7).
32. **Every stated invariant has a test, and the tests leave things out;** [INVARIANTS.md](INVARIANTS.md), "Not yet
    tested, in one list", says what: a deployment whose verifier is another program, orderings of four and more
    moves (sampled, not enumerated), `RefundOrder` and two racing relayers on a running cluster, and, in the state
    machine, standing orders, kill fees, assigned payments, a second relayer and a second mint.
33. **Until `knos-oidc` 2.2 is live, the claim reader accepts some issuer-signed payloads that are not strict JSON.**
    2.1 finds the claims it reads and steps over every other value by its brackets and quotes, so a payload the
    issuer's key really signed that a JSON library refuses (a literal cut short, `NaN`, a comment, a control
    character in a string; 13 shapes in the differential test) verifies. Nobody without the issuer's key can make
    such a token, and GitHub and GitLab sign JSON; but two readers of one verified payload can disagree about it.
    2.2 (Knos 0.3.16) checks every byte of the header and the payload against RFC 8259, refuses a name that appears
    twice in the top-level object, and takes at most 64 levels and 128 top-level members: the 13 shapes are refused,
    and the differential test has no class outside its rule ([ASSURANCE.md](ASSURANCE.md), "The claim reader: strict
    since 2.2"; [`fuzz.json`](fuzz.json)). 2.2 is proposed after the push of Knos 0.3.18; until that
    proposal has executed after its 48-hour delay, devnet runs an earlier verifier (2.1, since proposal 3
    executed), and [`web/upgrades.json`](../web/upgrades.json) says which is live. What stays: the
    strict rule is this project's reading of RFC 8259 (a name twice inside a nested object is not looked for), and
    `knos-pay` 2.1 and the interface crate still step over the values they do not read (2.2's strict reader is a
    file only the verifier calls, so that `knos-pay` stays the build it is); they read only payloads the verifier
    has verified, which under 2.2 are strict JSON: no other payload reaches the account they read.
