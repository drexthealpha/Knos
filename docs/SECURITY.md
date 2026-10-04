# Security model

Who has to be trusted for what, what a signed statement covers, and what it does not. What is said about a program
names the file or the test that backs it. The authority on what the programs do is the documentation at the top of
each source file in [`programs-v2`](../programs-v2).

This page describes Knos 0.3.13: `knos-pay` 2.1 and `knos-oidc` 2.1 (an upgrade of the second deployment at the same
addresses), and two new programs, `knos-meter` and `knos-passkey`. The upgrade was proposed and approved by the
multisig on 2026-10-04 07:17 UTC and can execute from 2026-10-06 07:17 UTC. Until it executes, the
deployed escrow and verifier are 0.3.12's, and what this page says about work orders, judges, any-issuer keys and
single-use pay tokens is not live yet ([section 8](#8-versions-and-what-is-live-when)). Knos runs on Solana devnet,
the money is test USDC, and no outside security firm has reviewed anything. Report a vulnerability privately:
[SECURITY.md](../SECURITY.md).

## The short version

- A work order's money sits in a token account of its own, owned by a program, `knos-pay`. It is not with Knos and
  not with the repository.
- The program pays only on a token that GitHub signed and that a second program, `knos-oidc`, verified on chain.
- GitHub signs which workflow ran, at which commit, in which repository, started by whom, by which event, and on
  which kind of runner. It does not sign what that workflow read. That the named checks passed, and who is paid, is
  the pinned workflow's own reading of GitHub's record.
- Who may ask for that signed statement is fixed when the order is funded: the order's own repository; for a public
  repository, also anyone who runs the pinned workflow by hand in a personal repository of their own; a judge
  repository the funder named; an arbiter the funder named. Each can go wrong in its own way
  ([section 2](#2-the-four-judges-who-is-trusted-in-each-and-what-each-could-do-wrong)).
- A statement moves the money of one order and nothing else.
- Until an outside review, Knos can change every program through a multisig, after a public 48-hour delay. Today
  one person holds every key of that multisig.

## Who you trust, and for what

| party | trusted for | not trusted for |
|---|---|---|
| **GitHub** | signing true statements about a workflow run; keeping its signing keys; answering its API truthfully; running a GitHub-hosted runner of a personal account on its own image | it cannot move money. It signs statements, and the programs check them |
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
own image. Two rules of the programs rest on that: the neutral judge (section 2, b) and Refresh by anyone
([section 5](#5-signing-keys-any-issuer-refresh-by-anyone-private-keys)). If GitHub changes this, both rules
become unsafe and need an upgrade.

## 2. The four judges: who is trusted in each, and what each could do wrong

Every judge's token is from the workflows the order pinned at funding, at the pinned commit, on a GitHub-hosted
runner, on the run's first attempt (`judge` in
[`programs-v2/knos_pay/src/order_judge.rs`](../programs-v2/knos_pay/src/order_judge.rs)). Then one of four. The
first valid token pays, and the order closes.

| judge | the run | who remains trusted | what it could do wrong |
|---|---|---|---|
| **a. The order's own repository** | `prove.yml`, in the repository the order names | that repository's maintainers and its runner. In an organisation on a paid plan the runner can be an image the organisation built | pay whoever it likes from this order, or never ask for the token. A sponsor who funds an issue in someone else's repository trusts that repository this far |
| **b. Neutral** (on unless the funder wrote `neutral off`; never for a private order) | `attest.yml`, started by hand (`workflow_dispatch`) by the account that owns the repository it ran in | GitHub, to run a personal account's job on its own image and to answer its API truthfully; the pinned `attest.yml` and the `knos` release it installs, which read the public record of the pull request | sign a payment that the pinned code wrongly allows. The person who starts the run is the person who gains, so a fault in that code, or in GitHub's record, is found by someone with a reason to look for it. It cannot sign what the record does not support |
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

**The fee.** The funder pays it on top of the amount: 2.5%, at least 0.40 and at most 25 whole units of the mint
(`order_fee` in [`lib.rs`](../programs-v2/knos_pay/src/lib.rs)). It waits in the order's account. At the payment,
the payees receive their full shares; the relayer that paid for the transaction receives a tip out of the fee (0.05,
or 0.30 when the transaction created a payee's token account); the rest goes to `FEE_OWNER`, an address of Knos's
that has one other power: it can lower the rate of the orders funded from one repository owner's Balances, under a
contract (`SetPlan`, between 0.5% and 2.5%, until an expiry). A refund returns amount and fee.

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
issuers it accepts. `knos-pay` and `knos-meter` accept GitHub's only.

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
The escrow is then refund-only. Getting out takes an upgrade of the verifier.

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
- **Who is told.** `knos status` fails while an upgrade is pending and prints it, and the site shows a banner with
  the buffer and the time it can run. Nothing pushes that notice to a funder: no comment is posted on repositories
  with open orders. The notice protects someone who looks.
- **Today every member key is the founder's.** So the delay, not the number of signers, is what protects users.
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
| live | yes, for the bounties funded there | yes | from the moment the upgrade executes |

The upgrade keeps every 2.0 instruction's bytes and behaviour, except four fixes that take effect for 2.0 bounties
too when it executes: whole-unit limits, the extension list, the Balance's side account, and single-use pay tokens.
Audiences of the new paths start `knos3:`, so no token of one generation is good for the other. `knos-meter` and
`knos-passkey` are new programs at their own addresses, live once the release run has deployed them. Neither calls
the escrow, so the relay carries their evaluations and withdrawals from then, before the upgrade executes.

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
| Knos disappears | no new key can be approved. Keys GitHub still publishes are kept alive by anyone | payments under those keys; refunds and withdrawals, for ever |

The three emergency tools, and their reach: a **pause** stops new funding and nothing else, for at most 7 days per
signature; a **revocation** stops one key and what it signed, for ever; an **upgrade** can change anything, 48 hours
after it is approved in public.

## 10. Recovery without GitHub, and without Knos

These need no token. Anyone can send them, and none reads the pause:

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
- **The release.** The list is `requirements/sign.txt` of this repository plus one line: the `knos` package of the
  release, by the sha256 of the file that was built ([`scripts/pinned_workflows.py`](../scripts/pinned_workflows.py)).
  So the commit of the workflows names the hash of everything a signing job installs.
- **Actions, by commit.** Every action in every workflow and example is named by a full commit
  ([`scripts/action_pins.json`](../scripts/action_pins.json)).
- **The programs, reproducibly.** What is deployed is the `solana-verify` build of this repository in a pinned
  image. [ASSURANCE.md](ASSURANCE.md) has the commands, and [DRILLS.md](DRILLS.md) prints the hash of the bytes on
  chain.

## 14. The sandbox (tests mode)

Payment without a merge is offered only when the acceptance bundle is black-box: the submission runs as a separate
process and only its output is compared ([TAMPER.md](TAMPER.md): of 63 cheating pull requests, plain CI passed 56,
in-process acceptance tests 7 and the black-box check none).

Everything that runs a pull request's code runs as another user (uid 65534) with an empty environment, and the
tests run with no network. The repository's own acceptance bundles are removed from the work tree before the
submission runs ([`src/knos/judge.py`](../src/knos/judge.py)). That is a separation between users on one machine,
not a virtual machine. A flaw in the runner's kernel or image that lets one user become another would let a pull
request write its own verdict. The dependency install does have the network.

## 15. Tokens: public, bound to one action, used once

A token is not a secret. A workflow without a relay key posts it as a comment, and anyone may carry it to the
chain. What it can do is fixed by its claims and its `aud`, and each works once:

| token | made single-use by |
|---|---|
| fund an order from a Balance (`knos3:fund`) | a marker account keyed by the hash of the token's signature. Tokens of one Balance may arrive in any order |
| pay an order (`knos3:pay`), a ruling (`knos3:rule`) | the order closes when it is paid. A standing order marks each pull request it has paid. A second order cannot be paid with it: the audience names the order's address |
| pay a 0.3.12 bounty (`knos2:pay`) | the same kind of marker: one token pays, or holds, exactly one bounty (`test_a_pay_token_pays_exactly_one_job`) |
| fund a 0.3.12 bounty (`knos2:fund`) | newer than the Balance's last. A later token that lands first makes an earlier one useless, and the funder comments again. Orders do not have this limit |
| bind a wallet | newer than the last binding |
| count an evaluation (`knosm:eval`) | a marker per work order, artifact, policy and milestone |

Every token stops working an hour after its expiry, and one dated more than five minutes ahead of the chain's clock
is refused. A marker can be closed, and its rent returned to whoever paid it, only once no token it stands for can
be accepted (`test_a_used_marker_is_closed_once_no_token_it_stands_for_can_be_accepted`).

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
carry it. No key of Knos's is named in the program. The program never calls the escrow, so the public relay carries
a withdrawal from the moment `knos-passkey` is deployed, whatever the escrow's version, and refuses one only on a
cluster where the program is not deployed (`test_a_passkey_withdrawal_request_is_simulated_then_sent_at_the_relays_cost`).
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

## Before mainnet

- **An outside review first.** `knos mainnet-check` prints every gate with its evidence. The last one, an outside
  review of the bytes on chain, fails today, on purpose.
- **Different program ids, Circle's mint, no faucet.** The released programs are devnet builds.
- **The cap stays** at 500 per order until the review. After it the upgrade authority is removed.

## Known limits

The first three cannot be removed. They come with the design.

1. **A signature authenticates a statement, not the truth.** GitHub signs that a workflow ran and what it asked
   for, not what it read.
2. **Passing checks and a merge do not show that the work is good.** Of the 63 cheating pull requests in
   [TAMPER.md](TAMPER.md), plain CI passed 56.
3. **Knos inherits GitHub's failures.** If GitHub signs something false, or a key of its leaks, the programs believe
   it until the key is revoked or expires. If GitHub is down, tokens wait.
4. **No outside security firm has reviewed anything.** The reviews so far are readers' reviews of the design, the
   source and the documents.
5. **One person can change the programs, after 48 hours.** Every member key of both multisigs is the founder's.
6. **Nothing is pushed to funders when an upgrade is proposed** (section 7).
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
15. **Tests mode has no second look.** A submission that passes the black-box check is paid.
16. **The sandbox is a user boundary, not a machine boundary.**
17. **The two jobs that cannot sign install by version, not by hash** (section 13).
18. **The policy file and the screening are the workflow's rules, not the chain's** (section 3).
19. **A private order still shows who paid whom, and how much** (section 12).
20. **A passkey wallet trusts the page that asks for the signature, and has no recovery** (section 17).
21. **The meter counts what the buyer's repository ran** (section 18).
22. **The paid token's issuer keeps its powers.** A freeze authority can freeze what is in escrow.
23. **An order holds between 5 and 500 units** until the review. A 0.3.12 bounty has no early exit.
24. **Several people can do the same work.** One pull request is merged and paid. `/knos take` reserves an order
    for one person for its `reserve` days, and several accounts can take turns.
25. **GitLab and other issuers are verified, not paid.** The escrow takes GitHub's tokens, and a private key's for
    its registrant's own private orders.
26. **Not run on the deployed programs yet:** [DRILLS.md](DRILLS.md) runs the safety paths on the deployed bytes in a
    simulator, and lists the rows that need real GitHub tokens and were not run. When 0.3.12 was released, no refund,
    key refresh or revocation had run on devnet itself. No instruction of this release had run on devnet when this
    page was written: the tests run them in a simulator, on builds made for testing.
27. **The assurance is the author's own.** [ASSURANCE.md](ASSURANCE.md) says what is tested, what is fuzzed, and
    what is not.
28. **Devnet only, and no outside buyer.** By 3 Oct 2026 no outside repository had funded a task.
