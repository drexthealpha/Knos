# How a Knos release is made

ONE commit and ONE push to `drexthealpha/Knos`. Everything that can fail is done before that commit, in staging or on
the operator's machine, and every command below can be run again after a failure: each reads what is already there
and does only what is missing.

This page is the plan for 0.3.18. The tools enforce the order: a step run too early stops and says which step comes
first.

What the release run does for 0.3.18, in order, each thing once. Nothing in it waits on a clock:

1. **`status`: what do the public program ids run?** Proposals 3 to 6 (knos_oidc 2.1, knos_pay 2.1, knos_meter 1.1,
   knos_passkey 1.1) executed before this release's commit. `python scripts/exercise_public.py status` exits 0 when
   all four run those builds.
2. **If 0: the rounds, then `record`.** Every round of `scripts/exercise_public.py` on the PUBLIC ids, in test USDC.
   `record` writes the manifest, the documents and the demo from that PUBLIC evidence, and moves a program's version
   only where the hash on chain is its proposal's build.
3. **The staging rehearsal of BOTH new builds**: knos_oidc (strict JSON and ES256) and knos_pay (one fee of 0.30% with
   a floor of 0.05, and the two quorum fixes), on staging ids, with `python scripts/exercise_public.py rehearse --rc`.
4. **ONE commit**, PyPI, **ONE push**, the tag, by the order below: staging; the wheel; the lock; the workflows; the
   stamp; the test count; the private gate; ONE commit; PyPI; ONE push; the tag.
5. **`propose`: ONE proposal set, `[knos_oidc, knos_pay]`,** after the push, from the verified builds of the pushed
   commit; then `bash scripts/schedule_upgrade.sh`; then `knos status` shows both pending.
6. **Publishes no crate.** The four programs and the two interface crates are held at 0.3.14
   (`scripts/bump_version.py`, `PROGRAMS_FROZEN`), and neither interface crate is on crates.io
   ("Publishing the crates and the npm package").

**If `status` exits 3** (it should not now): steps 2 and 5 are skipped, nothing is marked exercised, the demo keeps
its staging label, and everything else ships, as 0.3.17 did. They are run later by the same commands.

**Nothing in the release waits for a clock.** A round that needs a day (a holdback's warranty) records
`needs time: <when>` and is finished by `--resume` on another day. The new proposals' own 48 hours are waited for by
nothing: the site and `knos status` say when they execute.

## Why there is an order

Three things name each other, and only one order satisfies all of them.

- The jobs that sign install by hash. Their list is the last line of `requirements/sign.txt`: the knos wheel by
  its sha256.
- The workflows a repository calls are published at ONE commit of `drexthealpha/knos-workflows`, and that commit
  holds the list. So the commit exists only after the wheel does.
- This repository names that commit in `examples/`, in its own `knos.yml`, in `docs/` and on the site.

So the wheel is built first and once, from the final tree, and nothing inside the wheel names the commit of the
workflows (`src/knos` never does, and `README.md`, which is the wheel's description, is not a file the stamp
writes). The wheel built before the stamp and the wheel built after it are the same file:
`tests/test_release_order.py` builds both and compares them. Until 0.3.12 the wheel was built by `release.yml`
after the tag, so the pin could only be committed afterwards, with a second push.

The build is reproducible: `SOURCE_DATE_EPOCH` is fixed in `scripts/release.py`, and the build backend and what it
needs are installed by hash from `requirements/build.txt`.

## Step 0: the four earlier proposals have executed

A CHECK, and neither the exercises below nor the proposal of the two new builds starts until it passes. 0.3.14
proposed four upgrades (proposals 3 to 6 of the upgrade multisig: knos_oidc, knos_pay, knos_meter and knos_passkey).
The new proposal set is made only after all four have executed, on top of them, and the exercises need the instructions
they add. The release itself does not need them: when the check does not pass, go on to "The commit" without the
exercises.

```
node scripts/governance.mjs show                  # both multisigs as the design fixes them, and how many proposals so far
knos status                                       # each of the four programs answers with its newer version
python scripts/upgrade_feed.py --check            # exit 1 while any proposal is pending; writes web/upgrades.json
python scripts/capabilities.py check --rpc        # which `on_chain` versions and stages the manifest must now move
```

- `upgrade_feed.py --check` exits 0, and `web/upgrades.json` gives proposals 3, 4, 5 and 6 the status `executed`:
  go on.
- Anything else (a proposal still `pending`, a program that answers with its older version, a cluster that does not
  answer): **the exercises and the proposal wait; the release does not.** Neither is run. `bash scripts/schedule_upgrade.sh --show` says what
  is arranged and what the run's log holds; if the machine was off at the time, `bash scripts/schedule_upgrade.sh
  --run` runs it by hand (an execution before its time is refused by the Squads program itself, and one that
  already happened is left alone). Then run step 0 again, before the commit if there is time and after the tag if
  there is not.

The manifest moves in the commit of the release that passes step 0, on that evidence: `capabilities.py check --rpc`
names every `on_chain` version to write, and the stages that waited for the upgrade move with the exercises of the
next section. A commit made before step 0 passes does not move it: its `on_chain` versions are the ones devnet runs
until proposals 3 to 6 execute.

## After the upgrade executes: from staging to public, in one tool

Proposals 3 to 6 have executed (the status of each entry in `web/upgrades.json` is `executed`). From then on
`scripts/exercise_public.py` does the whole move: it checks what the public ids
run, runs each round there in test USDC with the least the programs take (5.00 for an order, 1.00 for a job), keeps
what it sent and what it checked, and writes it into the manifest, the documents and the site's demo. Every step can
be run again: a step that is done is not sent a second time. `<keys>` is the key folder: `relayer.json` pays the
fees, `funder.json` is a wallet holding test USDC (Circle's devnet mint: 10.00 for the small rounds, and 1,530.00
more for the minute the `fees` round holds an order above 1,000.00; all of it comes back), and `exercise.json`, if
there, names the repository the rounds' comments are posted in (`{"repository": "owner/name", "repository_id": 123}`;
default `drexthealpha/knos-e2e`).

**1. What do the public ids run?**

```
python scripts/exercise_public.py status --rpc https://api.devnet.solana.com; echo "exit $?"
python scripts/exercise_public.py status --rpc https://api.devnet.solana.com --json     # the same as one object; `exit` is the code
```

Fine, exit 0: four lines such as `knos_pay 5y7i...: runs knos_pay 2.1, the build of proposal 4; hash 2ed301a2...;
last deployed in slot <n>`, then `all four run the upgraded builds: run the exercises`.

- **Exit 3** (`knos_meter 1.0: proposal 5 has not executed`, then `skip the exercises and ship the rest`): the upgrade
  has not executed for every program. Do not wait for it. Ship the release without steps 2 to 4: the manifest keeps
  its stages, the demo keeps replaying the staging rehearsal and says so, and nothing in the commit claims a run at a
  public id. Run steps 1 to 4 later, when `status` exits 0, and commit what `record` writes then. (When some of the
  four have executed, `run` still runs the rounds of those and skips the others with the reason.)
- **Exit 1** (`a build no file of this repository records`, or the cluster did not answer): stop. No round is run
  and no file is written until the hash is explained: `python scripts/provenance.py --rpc` prints what the gate holds
  for it.

**2. Run the rounds.**

```
python scripts/exercise_public.py run --rpc https://api.devnet.solana.com --keys <keys>
```

It prints one block per round. Fine looks like:

```
[expiry] A wallet funds a job and an order for one minute of work, tops the order up, and both go back whole.
  ok       a wallet funds a job with its own money: <signature>
  ...
[order] One order funded by a comment, paid on its proof; every second use refused; ...
  NEEDS A RUN of fund.yml: in drexthealpha/knos-e2e: open an issue, comment `/knos fund 5` on it TWICE, merge a pull request that closes it, and run this again within five minutes of the merge (`--resume`)
exercised: fund_from_wallet, refund, top_up
  order_pay: needs run: fund.yml
```

The `expiry` and `fees` rounds need no workflow and take about two minutes each (each waits out a one-minute
deadline). Most other rounds take tokens GitHub signs, so the first run prints, for each, exactly what to start; do
that, then:

```
python scripts/exercise_public.py run --rpc https://api.devnet.solana.com --keys <keys> --resume
```

| Round | What to start | What it checks | Capabilities |
|---|---|---|---|
| `expiry` | nothing | a wallet's job and order, funded for one minute, topped up, go back whole at the deadline | `fund_from_wallet`, `top_up`, `refund` |
| `order` | `/knos fund 5` twice on one issue; merge a pull request that closes it | the order holds its amount and its fee on top; the proof pays; the proof relayed again is answered with the first payment and sends nothing; the fund token sent again is refused with error 91 (a token works once) and funds nothing; the first proof does not pay a second funding of the same address; that second order goes back at its deadline | `work_orders`, `order_pay`, `single_use_tokens`, `verify_github` |
| `quorum` | `/knos fund 5 quorum 2 holdback 20 warranty 1`; merge; the pinned `attest.yml` by hand in a repository of another owner with `kind=pay`; revert the merge; `attest.yml` again with `kind=revert` | one judge of two pays nothing and moves nothing; the second pays four fifths; the neutral judge's revert returns the holdback and its fee | `order_quorum`, `neutral_attest`, `order_challenge`, `warranty_revert` |
| `auto` | `/knos fund 5 auto` on an issue with a black-box suite; a pull request that passes it, not merged | the author is paid on the check's token, with no merge | `order_auto_accept`, `tests_mode` |
| `meter` | `knos meter batch` and the pinned `attest.yml` with `kind=batch` (buyer) and `kind=claim` (seller) | both counts are on chain; how far apart they are | `meter_batch`, `meter_seller_claim` |
| `strict` | nothing yet | a signed token holding NaN is refused; skipped, with the reason, until the strict knos_oidc is live | none (a refusal alone moves no stage) |
| `fees` | nothing | a wallet funds an order of 1,500.00 for one minute: the fee is read from the order's account ON CHAIN and held to the rule of the build the public id runs, written out in the script and not taken from this tree's client (knos_pay 2.1: 30.00 on 1,500.00); the wallet paid the amount and that fee; it all goes back | `fee_tiers` |
| `holdback` | `/knos fund 5 holdback 20 warranty 1`; merge a pull request that closes it | the proof pays four fifths; a day later the holdback reaches the payee and the order closes. The first run ends `needs time: <when>`; `--resume` after it sends the release | `holdback_release` |
| `issuer` | `gh workflow run outcome-k8s.yml`; `gh run download <run id> -n outcome-k8s -D <keys>/outcome` | the cluster's token passes the verifier's rule offline, then knos_oidc verifies it under the cluster's key, which the relayer's wallet registers as a private key: what `python scripts/outcome_k8s.py chain --send` sends, each transaction kept | `outcome_not_code` |
| `x402` | `node examples/x402_attested/live.mjs run ...` ([X402.md](X402.md)); merge the seller's pull request; `note x402 fund=... paid=... order=...` | both transactions succeeded at the public knos_pay and name the order; the order is closed | `x402_knos_order` |
| `passkey` | a person, in a browser: the run prints the page and each button; `note passkey fund=<the transaction the page shows>` | that transaction succeeded and names knos_passkey and knos_pay at their public ids | `passkey_funder`, `passkey_fund_relay`, `buyer_page` |
| `appeal` | in `drexthealpha/knos-playground`: a pull request the order's terms refuse, then `/knos appeal <reason>` by its author; `note appeal pull=... fund=... answer=upheld` (or `overturned paid=...`) | the order was funded at the public knos_pay; the appeal's comment is on the pull request and was answered; an overturned refusal's payment succeeded there. An upheld appeal moves no money and no stage | `supplier_appeal` |
| `preflight` | `note preflight issue=<owner/name#n> tree=<a checkout of the refused branch>` | `knos preflight` ran with the memory engine on and recalled a refusal under the same terms. It sends nothing, so no stage moves | none |
| `gitlab` | nothing | `cannot: no project`: Knos has no project on gitlab.com | none |

`note` writes what a step done outside the script printed into `<keys>/outside.json`; the round then holds each
signature to the chain (it exists, it succeeded, it names the program at its public id). Nothing is taken on a
person's word:

```
python scripts/exercise_public.py note x402 --keys <keys> fund=<signature> paid=<signature> order=<address>
python scripts/exercise_public.py run --rpc https://api.devnet.solana.com --keys <keys> --resume --only x402
```

A refusal is sent without preflight so that it lands and fails on chain: its signature is evidence, and it costs the
relayer one fee. A round ends one of five ways, and `run` says which for every capability:

| The line | What it means | What to do |
|---|---|---|
| `exercised` | a transaction succeeded at the public id and what was checked held | `record` |
| `needs run: <workflow>` | a token only a forge signs, or a step only a person does, is missing; the line says exactly what to start | do it, then `--resume` |
| `needs time: <when>: ...` | the chain's clock (a warranty, a deadline of days) | nothing waits: go on; `--resume` after that time finishes it |
| `cannot: ...` | the release run has no means to do it (no GitLab project; a wallet without 1,530.00 test USDC; no second owner) | nothing: it is recorded as said, and no stage moves |
| `failed: ...` | something was not as expected | read the line; the round's capabilities keep the stage they had |

The usual cause of `failed` is a token older than five minutes: post the comments again and run
`... run --again order --since <the time now, as 2026-10-06T22:30:00Z> --resume`. The second order of the `order`
round goes back 14 days after its comment: `run` says `needs time: <day>`; run it again after that day. Nothing
else waits for it.

`python scripts/exercise_public.py list` prints every capability about a program with its round, or why it has none.
Eighteen still have no round (`no round is written for it yet`: among them `plans` and `pause`, which only the fee
owner's and the guardian's keys can send), and `verify_any_issuer` says `cannot`: no issuer other than GitHub and
GitLab has a key admitted at the public id.

**3. Write it down.**

```
python scripts/exercise_public.py record --keys <keys> --rpc https://api.devnet.solana.com
python scripts/provenance.py --rpc --record --write        # the execution transactions, read from the multisig
python scripts/capabilities.py check --rpc                 # every signature exists and succeeded; every refusal failed with its error
python scripts/demo_data.py --check && python scripts/provenance.py --check
```

`record` prints `moved to exercised: ...; versions on chain: knos_oidc 2.1, knos_pay 2.1, knos_meter 1.1,
knos_passkey 1.1`. It writes `docs/capabilities.json` (stage `exercised` only with a transaction that succeeded at a
public id; `on_chain` only for a program whose hash on chain is its proposal's build), `docs/CAPABILITIES.md` (the
table, and the section "The round on the public program ids" with every transaction), `web/demo_data.json` (the
demo then replays the public round: each step its own transaction, the refusal the real error 91; it says
`program ids of the round shown: public`), `web/upgrades.json` (read again from the multisig) and
`docs/provenance.json` with `docs/PROVENANCE.md` (the slot each build went live, the exercise transactions). A program
that did not run its proposal's build when the rounds ran keeps its version, its proposal's state and its
capabilities, and `record` says so and exits 1. The demo moves to the public round only when the `order` and the
`meter` rounds are both done; until then it says `staging`.

Then, in the same commit: the tests that describe the state before the upgrade
(`tests/test_capabilities.py::test_the_manifest_claims_no_more_than_is_true_today` skips itself once `on_chain`
moved), and `README.md`'s summary, which `record` renders with the table.

The proposal of the two new builds is not one of these steps. It names builds made from the pushed commit, so it
comes after the push: "After the pending upgrade: the ONE proposal set".

## The exercises on the public program ids

The last two releases could run what their builds add only on staging ids, and a staging id is never evidence
([`capabilities.json`](capabilities.json): a capability is `exercised` only by a transaction at a public program id).
Once step 0 has passed the public programs carry those instructions, and each exercise below is run once, in test
USDC, against the pinned ids (`KNOS_PROGRAM_IDS` unset), BEFORE the commit of the release that runs it. The rounds
of `scripts/exercise_public.py` (the section above) cover the first nine rows, run and recorded by one tool; the rows
after them are still run by hand. 0.3.18 runs them only when `status` exits 0 before its commit; when it does not,
they are the first steps of the next release.

**Each one's transaction signature goes into `docs/capabilities.json` before that one commit** (the capability's
`exercised` evidence; then `python scripts/capabilities.py check --rpc`, which asks devnet that each signature
exists and succeeded). An exercise that fails is a finding: fix it in staging, or
leave the capability at the stage it has evidence for. Nothing is ticked on a staging transaction.

| | Exercise | How it is run | Passes when | Capabilities |
|---|---|---|---|---|
| [ ] | a second payment of one order is refused | pay an order, then send the same pay token again: `python scripts/replay_tokens.py fund.txt proof.txt claim.txt --rpc https://api.devnet.solana.com` | the first is paid, the second is refused by the program | `single_use_tokens`, `order_pay` |
| [ ] | every token is taken once | the tokens the exercises below posted, replayed: `python scripts/replay_tokens.py --capture <owner/repository> --out tokens.jsonl`, then each line sent again with `knos relay` | every replay is refused; the relay log says so for each | `single_use_tokens` |
| [ ] | the fee of the LIVE build | the `fees` round: a wallet's order of 1,500.00 | the fee in the order's account on chain is the live build's rule (30.00 under knos_pay 2.1), not what this tree's client would compute | `fee_tiers` |
| [ ] | an auto order | `/knos fund 10 auto`; a pull request that passes the order's black-box suite | paid with no merge and no person's step | `order_auto_accept`, `tests_mode`, `agent_tools` |
| [ ] | a quorum | `/knos fund 10 quorum 2`; two distinct judges' runs | not paid after the first judgment, paid after the second | `order_quorum` |
| [ ] | a challenge inside the warranty | an order with `holdback 20 warranty 30`, paid; then the pinned `attest.yml` from another repository with kind `revert` | the holdback returns to the funder | `order_challenge`, `warranty_revert` |
| [ ] | the meter: a batch, the seller's claim, the reconcile | `knos meter batch`, then the pinned `attest.yml` with kind `batch` (the buyer) and kind `claim` (the seller), then `knos meter verify <ledger> --rpc https://api.devnet.solana.com` and `knos meter reconcile` | both counts are on chain, and `reconcile` exits 0 on the two ledgers | `meter_batch`, `meter_seller_claim` |
| [ ] | an order funded by a passkey | the site's Buy page: a passkey signs the funding line, and the public relay carries the comment | the order is funded and the relayer paid the fee; the same comment again is refused | `passkey_funder`, `passkey_fund_relay`, `buyer_page` |
| [ ] | x402 | `node examples/x402_attested/live.mjs run --rpc https://api.devnet.solana.com --key buyer.json --offer offer.json` ([X402.md](X402.md)) | the order is funded, the resource served, the order paid | `x402_knos_order` |
| [ ] | a receipt and its attestation | `knos receipt verify <order>`, then `node scripts/sas_receipt.mjs receipt.json --send --keypair <file>` | the receipt checks against the chain, and the attestation carries its digest | the receipt's capabilities |
| [ ] | a neutral re-execution: attested, and refused | the pinned two-job `attest.yml` on an order whose suite passes, and once on one whose suite fails; `knos judge rerun` on the first verdict | the first signs and pays; the second posts a refused verdict and signs nothing | `hermetic_judge`, the attest capabilities |
| [ ] | a budget set and checked | `knos budget set` (the wallet that opened the Balance signs), then `knos budget check` for an amount over the new limit and `knos budget show` | `check` exits 1 and names the rule; a funding over the limit is refused on chain | the budget capabilities |
| [ ] | an audit export | `knos audit export` for the organisation of the orders above, then `knos audit verify` on the file | `verify` passes, and a second export of the same period is the same bytes | the audit capability |
| [ ] | a bundle verified with no chain, of a PUBLIC payment | `knos bundle make` for one of the orders paid above, then `knos bundle verify --no-chain` on the file | the verdict is re-derived from GitHub's signature with no cluster asked | the bundle capabilities |
| [ ] | an order that is not for code | `/knos fund 500 checks: test, released` ([TAMPER.md](TAMPER.md), "Tasks that are not code"; the adapter in `examples/adapters/release.yml`) | paid when the signed event arrives | the adapter's capability |

Each command's own `--help` gives its arguments; an exercise run through a comment is run in a repository of
Knos's own, with the public worker relaying.

## The chain: ONE proposal set of two programs, proposed after the push

0.3.18 changes TWO programs, proposed together as one set, `[knos_oidc, knos_pay]`:

- **knos_oidc** is the build 0.3.17 made and rehearsed and could not propose: the strict JSON reader (`strict.rs`)
  and the `VerifyEs256` instruction (`programs-v2/knos_oidc/src/es256.rs`, [ES256.md](ES256.md)). Its source is byte
  for byte what the tree held.
- **knos_pay** charges one fee on an order, `max(0.05, floor(amount x 30 / 10,000))`, in place of the three tiers,
  and carries the two quorum fixes: two runs started by one account are one judge, and a judge's marker of an order
  that was paid counts for nothing on an order funded again at the same address, in the same second too.

knos_meter and knos_passkey stay the builds of proposals 5 and 6, and every program crate stays at the version
`scripts/bump_version.py` holds it at (`PROGRAMS_FROZEN`, `FROZEN_AT`): a crate's version is in its build's bytes.
One list says which programs the release changes, `RELEASE_CHANGES` in `scripts/provenance.py`; `propose`,
`scripts/deploy_v2.sh` (`KNOS_CHANGES`' default) and `tests/test_deploy_v2.py` hold to it.

**Before the commit, the staging rehearsal, as ONE command.** It needs the verified builds that are LIVE (the
artifacts of `program.yml`'s run on the v0.3.14 tag) and the verified builds of this release (the staging run's):

```
python scripts/exercise_public.py rehearse --rc --rpc https://api.devnet.solana.com --keys <keys> \
    --live-so-dir <the v0.3.14 run's builds> --so-dir <this release's builds>
```

What it does, in order, and what each step prints when fine:

| Step | What happens | Fine |
|---|---|---|
| deploy | `bash scripts/deploy_v2.sh --rc` puts the LIVE builds of knos_oidc and knos_pay under fresh staging ids (`<keys>/rc`) | `STAGING: knos_oidc <id> and knos_pay <id>, upgrade authority <payer> (the fee payer).` |
| `old_layout_fund` | a wallet funds an order of 5.00 on the live build | `ok  under the live build, a wallet funds an order of 5.00 with 0.40 on top` |
| upgrade | `deploy_v2.sh --rc` again with this release's builds: the staging ids are upgraded IN PLACE, every account left as it is | `knos_pay (staging) <id>: deployed, executable hash <the new build's>`, and the same line for knos_oidc |
| `old_layout_pay` | the order's account is byte for byte what it was, the new client reads the same amount and fee, and its proof pays it | `ok  the new build pays the order funded before the upgrade: 5.00, its fee as funded (0.40)` |
| `fees` | orders of 100.00 and 5.00 on the new build; the fee is read from each order's account | `an order of 100.00 is funded with a fee of 0.30 on top`, `an order of 5.00 is funded with a fee of 0.05 on top` |
| `one_owner` | a quorum of two; ONE account starts the order's own run and a neutral run in another repository it owns | the second token is refused, or accepted and not counted; either way `no money moved` and the order stays open |
| `two_owners` | the same with a neutral run another account started in a repository of its own | `ok  another account's neutral run in its own repository is the second judge: the order pays` |
| `same_second` | an order paid by two judges, its address funded again in the same second, then one judge's new token alone | no money moved |
| `close` | every order still open goes back at its deadline; then `deploy_v2.sh --rc-close` | `closed 2 staging program(s)` |

It ends with one line per step and one verdict: `the rehearsal passed: every step is ok, or cannot be done from here
and says why`. `the rehearsal FAILED` means the build is not proposed. Three things the run cannot do on devnet, and
says instead of working around them:

- `old_layout_pay`, `one_owner`: these need tokens GitHub signs for the STAGING order (a staging repository whose
  workflows read `KNOS_PROGRAM_IDS`). The step ends `needs run: ...`, staging stays open, and
  `rehearse --rc --resume ...` goes on after the runs. Orders of the rehearsal that wait for a run stay open one hour.
- `two_owners`: `cannot: needs a second repository owner`. Every repository the release run can start a workflow in
  is the founder's, and two runs of one owner are one judge. No second owner is invented.
- `same_second`: `cannot`: four transactions do not land in one second of devnet's clock at will.

Every step of the table but the two deployments runs end to end on the local simulator (the upgrade there replaces the program's bytes in place), on the committed test builds, with no key and no network:
`python scripts/exercise_public.py rehearse --rc --simulate` (the chain starts on the test build of the live source,
kept in `tests/fixtures/live/`, and is upgraded in place to this tree's). `tests/test_exercise_public.py` runs it.
The handler tests of `programs-v2/handlers` hold the two quorum fixes on the built program.

What the rehearsal of the knos_oidc build sends for ES256 (a key, the precompile and `VerifyEs256` in one
transaction, a signing input of 780 bytes and one of 781, an upper `s`, a second use) is steps 3 and 4 of
[ES256.md](ES256.md), "What the release run does"; 0.3.17 ran them on staging ids for this same build, and `--rc`
stages it again beside knos_pay. A staging deployment needs devnet SOL: the script checks the fee payer's balance
before it writes anything and stops, naming the amount, when it is short. The rent is that of twice each file,
(bytes + 128) x 6,960 lamports ([Solana's rent](https://solana.com/docs/core/fees#rent)), as the script's `afford`
computes it, and `--rc-close` returns it.

- **Before the commit, a check that TWO programs changed, in bytes, and no third.** The staging run of `program.yml`
  prints the executable hash of each verified build. knos_meter's and knos_passkey's must be the `build_hash` that
  `web/upgrades.json` gives for proposals 5 and 6. Found after the push, a difference stops `propose` at its plan
  with nothing sent.
- **Nothing is proposed before the push, nor before proposals 3 to 6 have executed.** A proposal names a build that
  GitHub's runner made from a commit of this repository, and that commit is the one this release pushes ("After the
  pending upgrade: the ONE proposal set", below).
- **Until the new proposals have executed,** devnet runs knos_oidc 2.1 and knos_pay 2.1, and an order's fee there is
  the three tiers. The 0.3.18 clients ask each program which build it runs and work with both: what only the newer
  build has is refused before anything is sent, with a sentence that names the program and the version it needs.

How a program is proposed, replaced and scheduled is in [GOVERNANCE.md](GOVERNANCE.md).

## Nothing after the push goes into a commit

The two new builds will be proposed after the push, and their proposals can execute 48 hours after their approval. What it shows does not exist when the commit is made. No committed file states it, and no step of this page writes one into
a file afterwards:

- The documents name no time for a pending upgrade. They point at `knos status`, which reads the chain, and at the
  site's `upgrades.json`. `web/upgrades.json` in the repository is a copy that says of when it is (`generated`).
- `python scripts/doc_claims.py` (run by the tests) fails when a document names a time for an upgrade that
  `web/upgrades.json` does not give for a pending proposal, when a count of capabilities is not the manifest's, and
  when a slot is unfilled. So the ONE commit is complete, and checked, before the push.
- What the chain says after the push is published by the site's build (`.github/workflows/network.yml` runs
  `scripts/upgrade_feed.py` and `scripts/network_stats.py`), never by a second commit. The same holds when the
  proposals execute: the site and `knos status` say so at once. The manifest's `on_chain` versions of knos_oidc and
  knos_pay and the stages that wait for them move in the next release's commit, with `python scripts/capabilities.py
  check --rpc`.
- What step 0 and the exercises show is the opposite case: it exists BEFORE the commit of the release that runs
  them, so it is in that commit. When 0.3.18's commit is made before step 0 passes, it holds neither.

## The commit

In the staging tree that is going to be the release, in this order:

```
python scripts/bump_version.py --check 0.3.18    # every manifest, lock file and install line names it; the program crates name 0.3.14
python scripts/bench_docs.py --set tests_passing=<passed> --source "<the run>"    # the test count: see below
python scripts/release.py wheel                  # dist/knos-0.3.18-py3-none-any.whl and the sdist, built ONCE
python scripts/pinned_workflows.py lock dist/knos-0.3.18-py3-none-any.whl --write    # its hash, into requirements/sign.txt
python scripts/release.py workflows <checkout of knos-workflows>     # the published set with that lock, committed there
git -C <checkout of knos-workflows> push         # the commit must exist on GitHub before anything names it
python scripts/pinned_workflows.py stamp <that commit>               # the examples, knos.yml, docs/ and the site name it
python scripts/small_repos.py build knos-task <checkout>             # and knos-playground, knos-attest, knos-claim-org: commit and push each
python scripts/release.py verify <checkout of knos-workflows>        # versions, the lock, the wheel built again, the pin
```

**The test count.** The documents give one count of tests, and it is defined as the tests that passed in CI on the
staging tree of the release, not a count made on anyone's machine. The tree handed over still carries the count of
the release before. Take `<passed>` and the skipped count from the `pytest` job (ubuntu-latest, Python 3.12) of the
last green `tests.yml` run on staging, and write it with its source:

```
python scripts/bench_docs.py --set tests_passing=<passed> --source "pytest (ubuntu-latest, 3.12) of tests.yml run <run id> on drexthealpha/knos-rc <commit>, the staging tree of this release: <passed> passed, <skipped> skipped, https://github.com/drexthealpha/knos-rc/actions/runs/<run id>"
python scripts/bench_docs.py --check && python scripts/doc_claims.py
python scripts/release_manifest.py --check        # docs/MANIFEST.md is what the tree gives: source, built bytes, capabilities, limits
```

It rewrites `docs/bench.json`, `docs/facts.json` and the sentence in `docs/submission/SUBMISSION.md`. (The tree
collects 2,639 tests with `pytest --collect-only -q tests`; a collected test is not a passed one, and that figure is
written nowhere else.)

`verify` builds the wheel once more from the stamped tree and compares it with the lock. If it differs, something
that is part of the wheel changed after the lock: nothing has been published yet, so find it and lock again.

Then the private gate (`ship_check.py`, kept outside the repository) on the tree, the ONE commit, and the gate once
more on the commit:

```
python ship_check.py --tree <the handed-over tree> --version 0.3.18 --workflows <checkout of knos-workflows>
git commit                                        # one commit, by the owner, with no trailer and no other flag
python ship_check.py ... --committed
```

Two rules, each learned from a release that broke it:

- **Every fix made in staging is in the one commit.** Staging goes green through fixes (0.3.15 took five). The tree
  handed over for the next release is built from the PUBLIC commit, not from staging, so a fix that stayed on staging
  is lost and the same failure comes back one release later: 0.3.15 had to apply again 0.3.14's fix to a
  compute-unit test, which the tree handed over had dropped. Before the commit, go through the list of fixes staging
  took and find each one in the release tree.
- **Never pass `--no-verify`,** to this commit or to any push of a release. The commit command is the plain one
  above. 0.3.15's commit carried the flag by mistake; it changed nothing only because that clone had no hooks. A hook
  that stops the commit is a finding: fix what it found.

## The wheel, then the ONE push, then the tag

```
export UV_PUBLISH_TOKEN=<a PyPI token for the knos project>         # read by uv, never printed
python scripts/release.py publish                 # uploads THAT wheel and the sdist, then asks PyPI for the hash and its index for the file
git push origin main                              # the ONE push, only after `publish` said "Next: git push"
git tag v0.3.18 && git push origin v0.3.18        # starts release.yml
```

`publish` refuses unless `dist/` holds the locked wheel, the tree is committed and the commit holds the lock. A file
on PyPI can never be replaced: if PyPI already has this version with another hash, the only way on is a new version.

The wheel goes up before the push because the moment the commit is public, the workflows it pins install
`knos==0.3.18` by that hash. If PyPI did not have the file yet, every signing job would fail until it did.

**Push only after `publish` printed "Next: git push".** PyPI answers from two places: the page of a version shows an
upload at once, and the index an installer resolves from (`https://pypi.org/simple/knos/`) is a cached page that
showed 0.3.15 a few minutes later. The push went out in between, and the first runs on the new commit failed: the
index had "no version of" the release they asked for. `publish` now asks that index every 20 seconds, for 10 minutes at most, and ends with
"Do NOT push yet" when the file is still not listed; `python scripts/release.py pypi-check --wait 600` asks again.

## What the tag starts

`release.yml` uploads nothing to PyPI. On the tagged commit it

1. runs the whole test workflow (the gate: every later job needs it);
2. builds the wheel again and fails unless it is the locked one, so the commit holds the sources of the wheel it
   names;
3. asks PyPI for the wheel of this version and fails loudly unless PyPI serves a file with exactly the locked hash
   and its index lists that file;
4. creates the GitHub release with the wheel, the sdist, `sign.txt` and the JavaScript client's tarball; lists the
   MCP server in the registry; attaches the Gemini extension; publishes to crates.io and npm once each package's
   first version is there (see "Publishing the crates and the npm package"); starts the site's build.

## Publishing the crates and the npm package

Three packages, none published yet: `knos-oidc-interface` and `knos-pay-interface` (crates.io) and `knos-settle`
(npm). On 4 October 2026 all three names were free: `https://crates.io/api/v1/crates/<name>` and
`https://registry.npmjs.org/knos-settle` each answered 404.

After the first version, `release.yml` publishes them with no stored secret (the jobs `crates-trusted` and
`npm-trusted`): the registry exchanges the run's GitHub OIDC token for a credential that lives minutes, and npm
records provenance. But both registries let a trusted publisher be configured only on a package that exists
([crates.io](https://blog.rust-lang.org/2025/07/11/crates-io-development-update-2025-07/): "you'll need to publish
your first release manually"; [npm](https://docs.npmjs.com/trusted-publishers): the setting is on the package's own
page). So the first version of each is published by hand, once, by the owner, signed in to each registry. That is
the only step here that needs a person and an account, and it has not been done.

Before anything is uploaded, on the release commit (each prints what would be uploaded and uploads nothing):

```
(cd crates/knos-oidc-interface && cargo publish --dry-run --locked)
(cd crates/knos-pay-interface  && cargo publish --dry-run --locked)
(cd sdk/settle && node test.mjs && npm pack --dry-run && npm publish --dry-run)
```

0.3.18 does not make this first publish: the two crates are held at 0.3.14 and their jobs are green with a notice.
The first publish, whenever the owner makes it, after a tag's tests passed:

```
cargo login                                    # opens crates.io: sign in with GitHub, create a token, paste it
(cd crates/knos-oidc-interface && cargo publish --locked)
(cd crates/knos-pay-interface  && cargo publish --locked)
cargo logout

npm login                                      # opens npmjs.com: sign in (two-factor authentication on)
(cd sdk/settle && node test.mjs && npm publish --access public)
npm logout
```

Then, once, on each registry:

| where | what to enter |
|---|---|
| crates.io, each crate's Settings, Trusted Publishing, Add (GitHub) | owner `drexthealpha`, repository `Knos`, workflow `release.yml`, no environment |
| npmjs.com, `knos-settle`, Settings, Trusted Publisher (GitHub Actions) | organization or user `drexthealpha`, repository `Knos`, workflow `release.yml`, no environment |

From the next tag on, `crates-trusted` and `npm-trusted` publish. They need crates.io's
`rust-lang/crates-io-auth-action` (pinned in `scripts/action_pins.json`) and npm 11.5.1 or later on Node 22.14 or
later (the job installs Node 24 and stops with a plain message if npm is older). A crate or package that is not on
its registry yet is skipped with one line that names this section; a version the registry already has is left
alone. The token jobs (`crates`, `npmjs`) remain as a fallback and do nothing while `CARGO_REGISTRY_TOKEN` and
`NPM_TOKEN` are unset; leave them unset. A version number, once published, can never be used again on either
registry: a mistake is fixed by a new version.

A package is published at ITS OWN version. `knos-settle` moves with every release, so its version is the tag's.
The two interface crates are among the crates `scripts/bump_version.py` holds (`PROGRAMS_FROZEN`, at `FROZEN_AT`), so
during such a release their version is NOT the tag's, on purpose. The publishing jobs ask one rule
(`python scripts/release.py registry-plan`): the version is the tag's or the held one, anything else is red; a
package that is not on its registry yet, and a version the registry already has, are green with a notice; only a
version the registry lacks is published. (In 0.3.15 the job compared a held crate with the tag and could never pass.)

Until the first publish, the crates install as git dependencies and the client from the release's tarball
([INSTALL.md](INSTALL.md)).

## After the pending upgrade: the ONE proposal set

The pushed commit changes `programs-v2/knos_pay` (and holds the knos_oidc build no proposal has carried yet), so
`program.yml` runs on main: it makes the verified build of each program and its `gate` job has GitHub sign the hash of
each, which a relayer records at the upgrade gate. Then, when `status` exits 0, ONE command proposes knos_oidc and
knos_pay together and nothing else:

```
gh run download <that program.yml run> --repo drexthealpha/Knos --dir builds     # one folder per artifact
mkdir so && cp builds/knos_*-v2-verified.so/knos_*.so so/                        # knos_oidc.so, knos_pay.so, knos_meter.so, knos_passkey.so
python scripts/exercise_public.py propose --rpc https://api.devnet.solana.com --keys <keys> --so-dir $PWD/so
bash scripts/schedule_upgrade.sh                 # ONE run that executes both, at the later time plus ten minutes, unattended
knos status                                      # both proposals, pending, with the time each can execute
```

The plan is read, never assumed: it is every program whose verified build in `--so-dir` is not the build its public
id runs, and it must be exactly `[knos_oidc, knos_pay]`. What `propose` prints when fine, in order:

1. `proposals 3 to 6 executed: knos_oidc runs 2.1, knos_pay runs 2.1, knos_meter runs 1.1, knos_passkey runs 1.1`.
2. For each of the two, its bytes against its data account: `knos_pay: this build is <n> bytes; its data account has
   room for <m> bytes: it fits`, or `<k> bytes short, so deploy_v2.sh extends the account first (no code changes; the
   fee payer pays the rent)`. The loader refuses an upgrade to a build larger than the account.
3. `the plan: propose [knos_oidc, knos_pay] as one set (knos_oidc <hash>, built from <commit> in run <n>; knos_pay
   <hash>, ...); knos_meter, knos_passkey run the builds of <so> already`.
4. The output of `scripts/deploy_v2.sh --propose`, which it runs with `KNOS_CHANGES="knos_oidc knos_pay"`: `the plan:
   propose knos_oidc knos_pay (this release changes: knos_oidc knos_pay)`; `knos_meter ...: runs this build already`
   and the same for knos_passkey; then for each of the two its buffer, the gate's record of the build, the proposal
   and the members' approvals.
5. `proposal <n> for knos_oidc (build <hash>, buffer <address>): can be executed from <day>` and the same line for
   knos_pay.
6. `next: bash scripts/schedule_upgrade.sh arranges ONE run that executes proposal <n> and proposal <n+1>, each only
   while its buffer holds the build above; then `knos status` shows them pending`.

It refuses, with nothing sent, in four cases, and says which:

- proposals 3 to 6 have not all executed (exit 3: run it again when they have; nothing else of the release waits);
- a third program's file in `--so-dir` is not byte for byte what is live (`The plan would be [knos_oidc, knos_pay,
  knos_meter]; it must be [knos_oidc, knos_pay]`): a rebuild whose bytes moved with a version string or a linked
  crate. The chain runs the verified build of the tag `bump_version.py` holds the crate at, so that tag's file goes
  into `--so-dir` in its place;
- one of the two is still the build that is live (`The plan would be [knos_oidc]`): the set is never split, so the
  verified build of this tree goes into `--so-dir`;
- the upgrade gate holds no record of one of the two builds: it is then not a verified build of `program.yml`.

`propose-oidc`, 0.3.17's command, still runs: it says it is `propose` now and does the same.

The builds it proposed are named in `docs/provenance.json` (`next`) on the operator's machine, so `status` knows them
once they are live and [PROVENANCE.md](PROVENANCE.md) gains the row of each new build (`python scripts/provenance.py
--write`); that file is committed with the next release.

`bash scripts/schedule_upgrade.sh` reads `<key folder>/upgrade-schedule.json`, which names both proposals, and
arranges one run: `node scripts/governance.mjs upgrade execute <index> --expect-hash <hash>` for each, in the order
of their indexes, then `knos status`. Fine: `arranged with ...: ... runs the upgrade at <time>`, and under it how to
see it and how to cancel it; `bash scripts/schedule_upgrade.sh --show` prints what is arranged.

If `deploy_v2.sh --propose` stops at its own plan instead (`stopped: knos_meter is not a program this release changes
...`), NOTHING was sent, and one of three things is true; the message says them. A rebuild is never proposed by
accident.

`--propose` refuses a build the upgrade gate has no record of; it waits for the record (`KNOS_GATE_WAIT`, 30 minutes
by default). `--ungated` is for an emergency only. `--replace` is not needed: no older proposal can still run after
step 0.

Until the execution anyone can read the proposals on chain, and the members can cancel one:
`node scripts/governance.mjs cancel upgrade <index>`. After it, `knos status` answers knos_oidc 2.2 and knos_pay 2.2.
None of this is written into a commit ("Nothing after the push goes into a commit").

## After the push: the worker's chain of runs

The public worker (`worker.yml`) is a chain: each run starts the next. The first run on a new release installs that
release by hash. Its install step waits when PyPI's index does not list the release yet: for that one error, 15, 30,
60, 120, 180 and 195 seconds, 10 minutes in all, and then it fails as before. Any other install error is red at once.

A run that fails starts no next run, by design. If the chain has stopped:

```
gh run list --repo drexthealpha/Knos --workflow worker.yml --limit 5     # is any run going?
gh workflow run worker.yml --repo drexthealpha/Knos --ref main           # start the chain: leave the input `after` empty
```

Re-running the failed run restarts nothing: a second attempt of a run relays nothing and starts nothing (its first
attempt is taken to have started the next run), so "Re-run failed jobs" goes green and the chain stays stopped. The
workflow's own timer starts a chain when no run is going, but a scheduled run can be delayed
([GitHub's documentation of `schedule`](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule));
after a release, look once and start it by hand.

## After the tag: the first real runs

1. **The pinned workflows are republished** (the `release.py workflows` step and its push, above): check that the
   pinned commit of `drexthealpha/knos-workflows` holds this release's set.
2. **The knos-verify action and the reproduce workflow** ([`integrations/workflows/knos-verify.yml`](../integrations/workflows/knos-verify.yml),
   [`examples/knos-reproduce.yml`](../examples/knos-reproduce.yml), [REPRODUCE.md](REPRODUCE.md)): a run that this
   release changed is run once for real before anyone else is asked to rely on it.
3. **Only then a pull request to another project's repository** ([INTEGRATIONS.md](INTEGRATIONS.md)): after that
   project's own test suite passed on the patch. A suite that fails, even the way their unpatched branch fails, is
   not a pass, and nothing is opened.

4. **The tag's own commit is written down.** A commit cannot name itself, so the tagged tree lists its tag in
   [`scripts/action_pins.json`](../scripts/action_pins.json) with `KNOS_RELEASE_SHA` for the commit
   (`scripts/bump_version.py` adds the key; `--check` says when it is missing). The first commit after the tag
   replaces it with what `git rev-parse '<the tag>^{commit}'` prints, and only that commit may move the action step of
   [`.github/workflows/supplier.yml`](../.github/workflows/supplier.yml) to it. Until then a supplier who calls
   `supplier.yml` at this release's tag runs the workflow of this release and, inside it, the action at the earlier
   tag's commit the file names: say so if asked which code judged a pull request.

None of these runs is written into this release's commit ("Nothing after the push goes into a commit").

## What can go wrong, and what then

| What | What it means | What to do |
|---|---|---|
| step 0: a proposal is still pending, or a program answers with its older version | the four earlier upgrades have not all executed | the exercises and the proposal set wait, the release does not: `bash scripts/schedule_upgrade.sh --show`, then step 0 again |
| `release.py verify`: the wheel differs from the lock | a file inside the wheel changed after the lock | nothing is published yet: `release.py wheel`, lock again, build the workflows again, stamp again |
| `release.py publish`: PyPI has this version with another hash | a different wheel was uploaded earlier | a new version: bump, and the whole order again |
| `release.py publish` ends with "Do NOT push yet" | PyPI's index does not list the wheel yet | do not push; `python scripts/release.py pypi-check --wait 600` until it does |
| `release.yml` build: not the locked wheel | the tagged commit does not build the wheel it names | do not move the tag: fix on main, release a new version |
| `release.yml` pypi: PyPI does not serve the wheel | the push happened before `publish` | run `release.py publish` from the machine that holds `dist/`, then re-run the failed jobs |
| `release.yml` crates-trusted or npm-trusted is red | a package's version is neither the tag's nor the one `bump_version.py` holds it at | fix the version on main and release a new version; a held crate or a package not on its registry is green |
| the worker's first run after the push is red, and no run follows | its install failed, and a failed run starts nothing | "After the push: the worker's chain of runs": start the chain by hand; a re-run does not |
| `propose` or `deploy_v2.sh --propose` stops at its plan | the plan is not exactly `[knos_oidc, knos_pay]` | nothing was sent; "After the pending upgrade: the ONE proposal set" says the cases |
| `rehearse --rc` ends `the rehearsal FAILED` | a step on the staging build was not as expected: a fee, an order funded before the upgrade, a quorum | the build is not proposed; fix it in staging and rehearse again. `bash scripts/deploy_v2.sh --rc-close` closes staging |
| a round ends `needs time: <when>` | the chain's clock: a warranty or a deadline | go on with the release; `run --resume` after that time |
| `deploy_v2.sh --propose`: the upgrade gate holds no record of this build | `program.yml`'s gate job or the relay has not finished, or the file is not the run's artifact | let the run finish and run it again; the buffer is written and stays |
| the scheduled run says a proposal was NOT executed | too early, cancelled, or the machine was off | read the log; `bash scripts/schedule_upgrade.sh --run` |
| the scheduled run CANNOT START: a key file cannot be read | the drive or mount that holds it was not there | mount it (open a terminal: the profile does), then `bash scripts/schedule_upgrade.sh --run` |
