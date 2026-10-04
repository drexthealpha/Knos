# Governance: who can change what, today

This page says who can change the programs and the keys they trust, what stands between that power and a user's
money, and what is planned. It describes Knos 0.3.14 on Solana devnet with test USDC. [SECURITY.md](SECURITY.md) is
the security model; [INVARIANTS.md](INVARIANTS.md) is what the programs guarantee while they are unchanged.

**The short version.** One person can change every program, 48 hours after saying so in public. Both multisigs are
2-of-3 over the same three member keys, and all three are the founder's. So the 48-hour delay gives **notice**. It does not give
independent oversight: nobody else has to agree, and nobody else can refuse. No outside signer exists, and nobody
has agreed to become one.

## 1. Who can change what

| what | who, today | how fast | what limits it |
|---|---|---|---|
| The code of `knos_pay`, `knos_oidc`, `knos_meter`, `knos_passkey` | the upgrade multisig: 2 of 3 keys, all the founder's | 48 hours after the vote that approves it | the delay, and that the proposal and its bytes are public for those 48 hours. An upgrade can do anything, including taking every order's money |
| The upgrade multisig's own members, threshold and delay | the same 2 of 3 | the same 48 hours | it has no config authority: only a vote changes it |
| Which signing keys the verifier accepts | a new key: an attestation from one of two repositories of one personal GitHub account, then a day, then the guardian's approval. A refresh of a key the issuer still publishes: anyone (section 7) | a day and the guardian's vote | constants in [`pins.rs`](../programs-v2/knos_oidc/src/pins.rs) |
| Revoking a key; pausing new funding for at most 7 days | the guardian multisig: 2 of 3 keys, all the founder's | at once (no time lock) | it has no instruction that moves money, and cannot block a refund, a withdrawal or a payment under a good key |
| The guardian multisig's own members | the same 2 of 3 | at once | no config authority |
| A contract fee rate for one repository owner | `FEE_OWNER`, one key of Knos's | at once | only downward, between 0.5% and 2.5%, until an expiry |
| An order's terms, payee, amount or deadline after funding | nobody | | the program has no such instruction; a change takes an upgrade |
| The first deployment ([`programs`](../programs)) | nobody | | neither program has an upgrade authority |

Read it yourself: `knos status` prints both multisigs as the chain has them (members, threshold, delay, config
authority) and every pending proposal; `node scripts/governance.mjs show --check` does the same from the Squads
accounts. On devnet the Squads program itself has an upgrade authority, which is Squads' and not ours
([SECURITY.md](SECURITY.md), section 7).

## 2. What the 48 hours are, and are not

- **They are notice.** From the approving vote, the proposal, the buffer with the new bytes, and (when the build
  came from the release workflow) the upgrade gate's record of the commit it was built from are on chain.
  The site shows a banner on every view. [`web/upgrades.json`](../web/upgrades.json) and the Atom feed
  `web/upgrades.xml` list every proposal with its program, build hash, source commit, earliest execution time and
  status, so a funder can follow the feed instead of visiting the site
  ([`scripts/upgrade_feed.py`](../scripts/upgrade_feed.py)). The feed is rewritten when the site is built, so it
  is as fresh as the last build; the banner and `knos status` read the chain directly.
- **What a funder can do inside them.** Withdraw a Balance at once (`Withdraw`, the wallet signs). Cancel a
  wallet-funded order (`Cancel`, the wallet signs): its deadline becomes at most 7 days away, which is longer than
  48 hours, so the order's money is still in the program when the upgrade runs unless its deadline was already
  near. An order funded from a Balance by comment is cancelled by a comment in its repository. So the notice fully
  protects Balances, and protects orders only when their deadline falls inside it.
- **They are not oversight.** The same person proposes, approves and executes. A second approval by the same person
  is a second key, not a second opinion.
- **Nothing is sent to anyone.** No comment is posted on repositories with open orders, and no email exists. The
  notice reaches someone who looks, or who subscribed to the feed.

## 3. The delay doing its job: 0.3.13's build was replaced before it ran

Knos 0.3.13 proposed new builds of `knos_oidc` (proposal 1) and `knos_pay` (proposal 2). Both were approved on
2026-10-04 07:17 UTC and could have run from 2026-10-06 07:17 UTC. During that delay a defect was found in the
proposed `knos_pay`: a pay token that had paid an order could pay a second order funded later for the same issue
at the same address ([SECURITY.md](SECURITY.md), section 15). The build never ran, so no order was ever exposed to
it. 0.3.14 withdraws both proposals and proposes corrected builds in their place, which start a new 48 hours.

Two things to take from this. The defect was found by reading and testing during the delay, which is the use the
delay is for. And it was not found by an independent signer, because there is none: had nobody looked, one person
could have executed the defective build on schedule.

The chain is the record of this, not this page: in `web/upgrades.json` proposals 1 and 2 read `replaced` once the
cancelling votes are on chain, and `pending` until then.

## 4. An independent signer: what they would be asked to do

Nobody holds this role. This section is the job description, written so that the day a person agrees there is
nothing left to invent.

**Before voting for an upgrade, an independent signer checks four things, on their own machine:**

1. **The bytes.** Download the proposal's buffer (`solana program dump <buffer> buffer.so`), hash it
   (`solana-verify get-executable-hash buffer.so`), and compare with a build they made themselves from the proposed
   commit ([ASSURANCE.md](ASSURANCE.md) has the commands). The hash the proposer printed is not evidence.
2. **The gate record.** The account `["build", program, hash]` of [`examples/upgrade_gate`](../examples/upgrade_gate)
   exists and names a commit: GitHub signed that Knos's own `program.yml`, on a commit of `main` or of a release
   tag, built exactly these bytes. `knos status` and the feed print it. A proposal made with `--ungated` has none,
   and then the signer's own rebuild is the only evidence.
3. **The diff.** `git diff <the deployed commit>..<the proposed commit> -- programs-v2/`. In particular: the list
   "WHERE MONEY CAN GO" at the top of `knos_pay/src/lib.rs`; that `RefundOrder`, `Refund` and `Withdraw` still need
   no token and no key of Knos's; the constants of `pins.rs` (the genesis keys, the pinned workflows, the attesting
   account, the guardian); the program ids; and every new instruction's signer and owner checks.
4. **The tests at that commit.** The `program.yml` run of the proposed commit passed, and the release notes say
   what changed and why.

Then they vote (`node scripts/governance.mjs approve upgrade <index>`), or they do not. If anything is wrong after
approval, they vote to cancel (`node scripts/governance.mjs cancel upgrade <index>`).

**For the guardian,** before approving a key: fetch the issuer's published key set themselves, compute the
sha256 of the key's modulus, and compare it with the hash in the proposal.

**What they are not asked to do:** hold anyone's money (no member key can move an order), judge the product, or
be available at short notice for anything but a revocation.

## 5. The procedure to add one

It waits on a person. No one has agreed, so none of these steps has been taken.

1. The person makes a Solana key on a device they alone control and sends its address over a channel where the
   founder can confirm it is theirs.
2. A config transaction of the upgrade multisig replaces one of the founder's three keys with theirs, so that the
   multisig stays 2-of-3 with two of the founder's keys and one independent: Squads v4's `ConfigTransaction` with
   the actions `AddMember` and `RemoveMember` ([Squads v4](https://github.com/Squads-Protocol/v4)).
   `scripts/governance.mjs` has no command for this yet; it is written when there is a key to add.
3. The founder's two votes approve it. The multisig's own 48 hours apply. The proposal shows in `knos status` as
   "a change to the upgrade multisig itself".
4. After it runs, `node scripts/governance.mjs show --check` and `knos status` print the new member list, and
   this page and [DISCLOSURE.md](DISCLOSURE.md) name the signer, if they agree to be named.
5. The same for the guardian multisig, with no delay.

**One independent key of three does not yet bind the founder,** who still holds two. The step that does is the
next one: two independent keys of three, or a threshold of 3 of 3 with a recovery rule. Which of the two is not
decided; it will be decided with the first signer, and written here.

## 6. Separating who deploys from who approves

Today one person builds the program, writes the buffer, proposes the upgrade, casts both votes and executes it.

The target, once a second person exists: the key that writes buffers and creates proposals has the Squads
permission to initiate and no vote; the keys that vote do not deploy. Squads v4 gives each member its own
permissions (initiate, vote, execute), so the split is enforced by the multisig and not by a promise. Until a
second person exists the split would be two keys of one person, which separates nothing, so it has not been made.

What already separates a build from the person who proposes it is the gate: `scripts/governance.mjs upgrade
propose` refuses a buffer whose bytes GitHub's runner did not build from a commit of this repository. That check is
in the script. The multisig itself would execute an ungated proposal.

## 7. The long-term upgrade model

This is a decision, with its cost stated.

- **`knos_oidc`, the verifier, is frozen after an outside review:** its upgrade authority is removed, and from
  then nobody can change which signatures it accepts or how it checks them. The verifier is small, does one thing,
  and is what every other program relies on.
- **`knos_pay`, the escrow, stays upgradeable behind the public 48-hour delay.** It holds the money and has the
  most code, and a defect in it must be fixable in place. The one in section 3 is the example.
- **`knos_meter` and `knos_passkey`:** not decided. They stay behind the same delay until it is.

What freezing costs. A frozen program's defects cannot be patched in place. A fault in the verifier would then be
answered by deploying a new verifier at a new address and upgrading `knos_pay` to read it, 48 hours away, with the
guardian revoking keys in the meantime. The constants in `pins.rs` freeze with the program: the genesis keys, the
guardian's address, the pinned rotate workflow and the account whose runs admit new keys. So the dependency on one
GitHub account (section 9) has to be resolved **before** the freeze, not after it.

None of this has happened. No outside review has been done or commissioned, so both programs are upgradeable
today, by one person.

## 8. Keys and procedures

**What the repository defines.** `scripts/governance.mjs` reads a key folder (`--keys`, default `.knos-keys`, never
committed): `member-1.json` to `member-3.json` for each multisig's votes, `payer.json` for fees, and the two create
keys that fix the multisigs' addresses. Every command reads the chain first and can be run again after a failure.

| procedure | command | who must act |
|---|---|---|
| propose an upgrade | `bash scripts/deploy_v2.sh --propose` (builds, waits for the gate record, proposes and approves) | 2 member keys |
| execute it after 48 hours | `node scripts/governance.mjs upgrade execute <index>` | any member |
| cancel one | `node scripts/governance.mjs cancel upgrade <index>` | 2 member keys |
| approve a new signing key | `node scripts/governance.mjs guardian approve <issuer> <key hash>` | 2 guardian keys |
| revoke a key, for ever | `node scripts/governance.mjs guardian revoke <issuer> <key hash>` | 2 guardian keys |
| pause new funding, at most 7 days | `node scripts/governance.mjs guardian pause <seconds>` | 2 guardian keys |
| rehearse all of the above | `bash scripts/drill_upgrade.sh --from-devnet` ([DRILLS.md](DRILLS.md)) | drill keys, on a local validator |

**What is not written anywhere:** how the founder stores the three member keys, whether copies exist, what happens to
them if the founder cannot act, and a rotation schedule. There is no hardware security module and no key ceremony.
This page cannot supply those: they are the founder's to write. If the founder's keys are lost, no program can be
upgraded, no new signing key can be approved, and no key can be revoked; payments under the keys that are still
alive, refunds and withdrawals go on.

**The 30-day key refresh.** Every signing key in the verifier expires 30 days after it was registered or last
attested.

- **Who normally does it.** The rotate workflow runs every day on a schedule in two repositories of the account
  drexthealpha, and the public relay sends `Refresh` at most once a day for each key the issuer still publishes.
- **Anyone can do it** (in the 2.1 verifier). The attestation: run the pinned workflow
  `drexthealpha/knos-oidc-rotate/.github/workflows/rotate.yml`, at the commit in `rotate_sha2` of
  [`program_ids.json`](../programs-v2/program_ids.json), by hand (`workflow_dispatch`) from a repository of your
  own personal account, with `id-token: write`. Sending it: `Refresh` is open to anyone; `knos relay --token-file`
  carries the token with any key that holds a little SOL. Such a run refreshes keys; it never registers one.
- **Being warned.** `knos status` fails when a key has less than 7 days left, and says which.
- **If nobody does.** Keys expire one by one, 30 days after each one's last attestation. A token under an expired
  key is refused. An expired key comes back when it is attested again, as long as the attestation is verified under
  some other key that is still usable. When the last usable key of GitHub's expires, nothing can be verified and
  nothing can be attested: no order can be funded by comment or paid, and the escrow is refund-only
  ([DRILLS.md](DRILLS.md) has the funder's steps). From there the only way back is an upgrade of the verifier
  through the multisig, 48 hours away, and after the verifier is frozen, a new verifier and an upgrade of the
  escrow.

## 9. The dependency on one personal GitHub account

The pinned workflows, the rotate workflow, the release workflow that feeds the upgrade gate, the public relay and
the site all live in repositories of one personal GitHub account, drexthealpha. GitHub can suspend an account. If
it does:

| what | why it stops | what still works |
|---|---|---|
| Funding by comment, and every pay, take, cancel and revert token of an order that pinned the published workflows | a repository's job calls `drexthealpha/Knos/.github/workflows/...` at a commit, and GitHub cannot fetch a workflow from a suspended account, so no run starts and no token is signed | an order that pinned workflows in another repository (a funder may pin a copy of its own) is not affected |
| Key refresh and new keys | the pinned rotate workflow is in the same account: nobody can make the attestation, so "refresh by anyone" stops too | keys already refreshed last until their 30 days end |
| The public relay | it is a scheduled workflow in the same account | anyone relays with `knos relay`; but with no new tokens there is little to carry |
| The upgrade gate | `program.yml` runs there | an upgrade can still be proposed `--ungated`, with only the members' own rebuild as evidence |
| The site and its feed | GitHub Pages of the same account | the chain, `knos status` from an installed package, any RPC endpoint |

**So a funded order that pinned the published workflows can only be refunded. Exactly how:**

1. **An open order funded from a wallet:** the funding wallet signs `Cancel` (no token). The deadline becomes at
   most 7 days away. After it, anyone sends `RefundOrder`; the amount and the fee return to the funding wallet.
2. **An open order funded from a Balance:** `Cancel` needs a token, which cannot be made. Wait for the order's own
   deadline; then anyone sends `RefundOrder`, and the amount and the fee return to the Balance.
3. **A Balance:** its wallet signs `Withdraw` at any time, for everything not in an order.
4. **An order held for a payee who has since bound a wallet:** anyone sends `SettleOrder`; the payee is paid. A
   payee who has not bound one cannot (binding needs a workflow in the same account); after 180 days the order
   returns to the funder with `RefundOrder`.
5. **An order in its warranty:** a revert needs a token and cannot be made. After the warranty anyone sends
   `Release`, and the holdback goes to the seller.
6. **Sending any of these** needs a Solana key with a little SOL and an RPC endpoint, and nothing of Knos's or
   GitHub's: `KNOS_RELAY_KEY=<key> knos relay` makes one pass and sends every refund, settlement and release that is
   due. The package is installed from PyPI, not from GitHub.

The step-by-step version for a funder, with what each step shows, is in [DRILLS.md](DRILLS.md). Work that was
accepted but not yet paid when the account was suspended is not paid: the seller's remedy is outside the program.

**The plan.** Move the workflows and the relay to an organisation account with at least two owners.

- The pinned workflows are named in the programs by repository and commit (`ROTATE_REF`, `CLAIM_REF`), and each
  order stores the repository it pinned. So the move is an upgrade of `knos_oidc` and `knos_pay` that accepts the
  organisation's repositories beside the old ones; orders funded before it keep their old pin until they close.
  The old repositories stay where they are for that long.
- The relay moves by running the same workflow in the organisation; it holds one fee-paying key and nobody's
  money.
- **One part is not solved.** The run that admits a *new* signing key must be on a runner GitHub itself controls.
  A personal account cannot have runners with its own image; an organisation on a paid plan can
  ([SECURITY.md](SECURITY.md), section 1). So the attesting account cannot simply become an organisation. The
  options are an organisation that stays on the free plan, or several independent personal accounts of which more
  than one must attest. Neither is chosen.
- **An organisation with one owner changes little:** it depends on that owner's account. The second owner is a
  person, and that person does not exist yet. This move, the independent signer and the verifier's freeze all
  wait on the same thing.

Not done: the organisation does not exist, and no repository has moved.

## 10. What is missing, in one list

- An independent signer on either multisig. Nobody has agreed to be one.
- A second person for any duty: review, deploy, approve, relay, respond.
- An outside review of anything. The verifier's freeze waits on it.
- A written description of how the member keys are stored and recovered.
- A notice pushed to funders. The feed and the banner are pulled, not pushed.
- An organisation account for the workflows and the relay, and an answer for the attesting account.
- A legal entity that owns any of this ([DISCLOSURE.md](DISCLOSURE.md)).
