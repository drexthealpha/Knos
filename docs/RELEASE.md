# How a Knos release is made

ONE commit and ONE push to `drexthealpha/Knos`. Everything that can fail is done before that commit, in staging or on
the operator's machine, and every command below can be run again after a failure: each reads what is already there
and does only what is missing.

This page is the plan for 0.3.19. The tools enforce the order: a step run too early stops and says which step comes
first.

0.3.19 changes no program: `programs-v2/`, `programs/`, `idl/` and the test builds are byte for byte those of 0.3.18,
and the two builds that tree made (knos_oidc 2.2, knos_pay 2.2) are proposals 7 and 8 of the upgrade multisig
already. So this release proposes nothing, and it waits for nothing. What the release run does, in order, each thing
once:

1. **`status --want 2.2`: have proposals 7 and 8 executed?**
   `python scripts/exercise_public.py status --rpc https://api.devnet.solana.com --want 2.2 --json` names each live
   build by its hash and exits 0 only when knos_oidc and knos_pay run the builds of proposals 7 and 8.
2. **If 0: the after rounds, then `record`, before the commit.** `python scripts/exercise_public.py run --phase
   after --rpc <rpc> --keys <keys>`, then `record --keys <keys> --rpc <rpc>` ("0.3.19: the after rounds", below).
3. **If 3: ship without them.** Nothing is marked exercised, no version moves, and the same two commands run on a
   later day. Exit 1 is neither: read what it printed before anything else.
4. **Either way, `run --resume`** finishes what 0.3.18's rounds left for the chain's clock, when its time has come: the
   holdback's release, and the refund of the second order of the round `order`. It prints, per round, `due now` or
   `not due before <time>`, and sends only what is due.
5. **PyPI, ONE commit, ONE push**, the tag, by the order below: the test count; the wheel; the lock; PyPI; the
   cutoff; the workflows, committed and pushed in their own repository; the stamp; the small repositories; `verify`;
   the private gate (`ship_check`); ONE commit; ONE push; the tag.
6. **No `propose`.** `python scripts/exercise_public.py propose ...` refuses in this release, before it reads
   anything: `refused: this release proposes nothing.` The sections below that describe a proposal set are the record
   of how proposals 7 and 8 were made, kept for the next release that changes a program.
7. **The crates and the npm package: only from a machine that is already signed in** ("Publishing the crates and the
   npm package"). No account is created and no sign-in is started by the release run.
8. **The repository as a stranger is served it**, logged out ("After the push: logged out", below).

**Nothing in the release waits for a clock.** A round that needs time records `needs time: <when>` and is finished
by `--resume` on another day.

## 0.3.19: the after rounds

Before proposals 7 and 8 execute, once, while knos_pay 2.1 is still live:

```
python scripts/exercise_public.py run --phase before --rpc https://api.devnet.solana.com --keys <keys>
```

It funds two orders of the run's own wallet under 2.1 (the 2.1 fee on each), one open for six hours past the
arranged execution and one for half an hour past it, and keeps each order's account byte for byte. An order that is
reserved for someone else is never used for this: the step reads only the orders its own evidence file funded. If
it was not run in time, the step `stored_fee` says `cannot` and why; the order the 0.3.18 round funded under 2.1
still goes back with its stored fee through `run --resume`.

After they execute (`status --want 2.2` exits 0), and only then (otherwise: exit 3, `nothing was sent`):

```
python scripts/exercise_public.py run --phase after --rpc https://api.devnet.solana.com --keys <keys> [--neutral <owner>/<repo>]
python scripts/exercise_public.py record --keys <keys> --rpc https://api.devnet.solana.com
```

| step | what it sends and checks | how it can end |
|---|---|---|
| `stored_fee` | the two orders funded under 2.1 read as written; a proof pays one, the other goes back at its deadline, each with the fee it was funded with | `ok`; `needs run: prove.yml` (no proof yet); `needs time`; `cannot` (no order was funded before) |
| `one_rate` | three wallet orders: the fee read from each order's account is the one rate with its floor; all three go back after a minute | `ok`; `cannot` (the wallet cannot carry them) |
| `one_owner` | a quorum of two, one owner behind both runs: nothing is paid, and the relay's answer (the workflow's comment) says why | `ok`; `needs run: prove.yml and attest.yml` |
| `two_owners` | a quorum of two, two owners: pays | `ok`; `cannot: needs a second repository owner` unless `--neutral` names a repository of another owner, which is read and never written to |
| `earlier_marker` | a marker of the order before counts for nothing for one funded again | `ok` on the simulator; `cannot` on devnet, whose clock cannot be arranged |
| `grace` | an order with the presentation grace and a two-minute deadline: its refund right after the deadline is refused on chain; when the grace is over it goes back | `ok`; `needs time: <the end of the grace>` |
| `strict` | a NaN claim under a private key of the run's own wallet is refused by the verifier's not-JSON error; the same token with a number is verified | `ok` |
| `es256` | the run's own wallet registers a P-256 key as its private key; a token that key signed, as long as one transaction carries, is verified in one transaction; the same token again is refused because its account exists | `ok` |
| `after_close` | every order of these steps still open goes back at its deadline | `ok`; `needs time` |

`record` moves a stage only on a transaction that succeeded at a public program id, and a program's version only
where the hash read at its public id is the build of its proposal (the feed's entry for proposal 7 or 8, or the
multisig's own word that it executed together with how the build's hash begins). The same steps run end to end on
the local simulator, with no key and no network: `python scripts/exercise_public.py run --simulate --phase after
--out <file>` starts on the test build of the live source, funds the two orders, upgrades in place and runs the
rest; `tests/test_exercise_public.py` runs it.

**Rounds other modules bring.** `run --phase after` is the one command for 2.2: after the steps above it runs every
registered round of that phase. A round is a file of `scripts/exercise_rounds/` with `ROUND = {"name", "needs",
"caps", "phase"}`, a `run(book, st)` for the public ids and a `simulate(book, st)` for `--simulate`
(`python scripts/exercise_public.py list` prints each with what it needs). Each round ends with a code of its own,
printed as `<name>: exit <code>: <why>` and kept in the evidence file:

| code | means |
|---|---|
| 0 | done |
| 1 | failed: the command exits 1 too |
| 3 | not run or not finished, for that round only: a prerequisite is not met or is one the script does not know, a forge's run or the chain's clock is waited for, or it cannot be done from here |

The prerequisites a round may name: a program (`knos_oidc`, `knos_pay`, `knos_meter`, `knos_passkey`: the public id
runs this version's build), `pay-2.2`, `neutral` (`--neutral` was given), `note:<name>` (`note <name> key=value` was
run) and `public`. `net-reserve`, `private` and `judge` have a place kept: until a file fills one it ends 3 and
says so. `run --only <name>` runs one round alone and exits with its code. A round whose `ROUND` says `"alone": True`
runs only that way: `pause`, which stops new funding at the public knos_pay for everyone while it runs, is passed by
`run`, `run --resume` and `run --phase after`, each of which says so. With `--phase`, `--only <step>` runs one step of
the phase and nothing else (`run --phase after --only grace`). `tests/test_exercise_public_rounds.py`.

**Throughput, measured.** Once per release, on devnet, with a wallet that holds devnet SOL:

```
python scripts/load.py measure --relays 4 --orders 40 --wallet <keypair> --write
```

Four relays, each with a fee payer of its own derived from the wallet's key, fund 40 orders twice: with no account
in common, and with one shared writable account that stands for the fee account. It records confirmed transactions
a second, retries and failures for each, refunds every order and sends each relay's SOL back. Each relay is lent
0.012 SOL for each order it funds each way, and 0.01 more; a run that died is swept by `measure --relays 4 --orders 0`.
[LOAD.md](LOAD.md) prints it as "Measured on devnet (date)", apart from the derived bound; until it has run, that
page says nothing is measured. `--simulate` runs the same path here and gives no rate.

**The site and the feed.** `python scripts/upgrade_feed.py --published` reads the multisig and then the site's own
`upgrades.json`, and exits 1 with one line per proposal the site is behind on. The site's copy is written when the
site is built, so after a proposal is made or executed it is behind until the pages workflow has run:
`gh workflow run network.yml --repo drexthealpha/Knos --ref main`, then the same command again.

**The scheduled run.** `bash scripts/schedule_upgrade.sh --show` says what is arranged, whether the key files and
the Node packages are there now, and the log's last lines. `bash scripts/schedule_upgrade.sh --verify` is a dry
trigger: it starts what the timer starts (a login shell with a bare environment, then the env file), installs the
Node packages when they are missing, loads them, sends nothing, and exits 0 when the run would start. The run
itself does the same check first: with `scripts/node_modules` missing it runs `npm ci --prefix scripts
--omit=optional` and goes on; when the packages cannot be had it sends nothing and ends with exit 1 and one line
starting `stopped:`. Every line it writes into `<key folder>/upgrade-run.log` starts with the time.

Nobody has to be logged on to Windows at the minute. Under WSL the Windows task starts the run at the time, as soon
as possible after a start that was missed (the machine was off or asleep: `StartWhenAvailable`), and at this Windows
user's next logon from the time on, for 14 days. No password is stored: the task runs in the user's own session,
which is why the logon trigger is there. The way to run with nobody logged on and no stored password (logon type
S4U) is not used, because such a task has "no access to either the network or encrypted files"
([Microsoft's task schema](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-logontype-simpletype))
and the run needs the cluster. A second start after a run that executed every proposal logs one line and sends
nothing (`<key folder>/upgrade-run.done`; `--run --force` runs it again). To check the task:
`schtasks.exe /Query /TN KnosUpgrade /V /FO LIST` (Last Result 267011: it has not run yet; 0: the run ended well),
then `bash scripts/schedule_upgrade.sh --show`, whose `done:` line says whether a run executed every proposal. The
logon trigger has not fired on a real machine yet: `tests/test_schedule_upgrade.py` checks the task's file.

## After the push: logged out

What a stranger is served is checked without a session, from a shell with no GitHub token in its environment:

```
curl -sS -o /dev/null -w "%{http_code}\n" https://github.com/drexthealpha/Knos                  # 200: public. 404: private, or renamed
curl -sS https://raw.githubusercontent.com/drexthealpha/Knos/main/README.md | sha256sum
git show HEAD:README.md | sha256sum                                                             # the same hash as the line above
curl -sS https://raw.githubusercontent.com/drexthealpha/Knos/main/README.md | head -n 30         # read the first screen as it is served
```

Then the repository's page in a private browser window: the README renders, its first screen is the one of the
commit, every link on it opens, and the release named `v0.3.19` is the latest. Fine: all four. Not fine: the hash
differs (the push did not land, or a cache: wait a minute and run it again) or the page asks to sign in.

## Why there is an order

Four things depend on each other, and only one order satisfies all of them.

- The jobs that sign install by hash. Their list is the last line of `requirements/sign.txt`: the knos wheel by
  its sha256.
- The workflows a repository calls are published at ONE commit of `drexthealpha/knos-workflows`, and that commit
  holds the list. So the commit exists only after the wheel does.
- This repository names that commit in `examples/`, in its own `knos.yml`, in `docs/` and on the site.
- The jobs that sign nothing install knos from PyPI with a cutoff, `UV_EXCLUDE_NEWER`. uv takes no file uploaded
  after that time, knos included. So the cutoff is written only once PyPI has the wheel. The `cutoff` command of
  `scripts/pinned_workflows.py` asks PyPI when it took the locked wheel and writes that time plus ten minutes. So
  PyPI comes before the commit of the workflows. 0.3.25 set its cutoff by hand, to midnight. Its wheel
  reached PyPI at 03:00:44 UTC. uv could not see it, so every job that installs knos from PyPI failed there.
  `tests/test_release_order.py` fails when a cutoff comes before the upload its note names, or was set by hand.

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

This section is the record of how 0.3.18 made proposals 7 and 8. 0.3.19 proposes nothing: `propose` refuses.

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

Run `python scripts/diagrams.py render` before the version bump: the bump writes README.pypi.md, which shows each of
README.md's diagrams as its picture in docs/diagrams/ at the tag (PyPI does not draw Mermaid).

```
python scripts/diagrams.py render                # before the version bump: a picture of every Mermaid diagram
python scripts/bump_version.py --check 0.3.18    # every manifest, lock file and install line names it; the program crates name 0.3.14
python scripts/bench_docs.py --set tests_passing=<passed> --source "<the run>"    # the test count: see below
python scripts/release.py wheel                  # dist/knos-0.3.18-py3-none-any.whl and the sdist, built ONCE
python scripts/pinned_workflows.py lock dist/knos-0.3.18-py3-none-any.whl --write    # its hash, into requirements/sign.txt
export UV_PUBLISH_TOKEN=<a PyPI token for the knos project>         # read by uv, never printed
python scripts/release.py publish                 # uploads THAT wheel and the sdist; waits until PyPI's index lists the wheel
python scripts/pinned_workflows.py cutoff         # UV_EXCLUDE_NEWER: ten minutes after PyPI took the wheel, into the workflows
python scripts/release.py workflows <checkout of knos-workflows>     # the published set with that lock and cutoff, committed there
git -C <checkout of knos-workflows> push         # the commit must exist on GitHub before anything names it
python scripts/pinned_workflows.py stamp <that commit>               # the examples, knos.yml, docs/ and the site name it
python scripts/small_repos.py build knos-task <checkout>             # and knos-playground, knos-attest, knos-claim-org: commit and push each
python scripts/release.py verify <checkout of knos-workflows>        # versions, the lock, the cutoff, the wheel built again, the pin
```

**PyPI before the workflows.** The wheel is final once it is locked. Run the checks under "The test count" (below)
before `publish`. A file on PyPI can never be replaced, so a change inside the wheel (`src/knos`, `terms/`,
`README.pypi.md`) after `publish` is a new version. The cutoff, the workflows, the stamp and the small repositories change nothing inside the wheel.
The small repositories are pushed only after `publish`: the workflows they call install the release from PyPI.
`pinned_workflows.py cutoff` refuses until PyPI serves exactly the locked wheel, and writes nothing then. Until the
cutoff names this release, `release.py workflows`, `pinned_workflows.py check` and `release.py verify` refuse and say
"Upload the wheel first".

**0.3.26.** The tree handed over carries the cutoff written for 0.3.25 (`2026-10-10T03:11:00Z`, ten minutes after
0.3.25's wheel reached PyPI). It is right for the 0.3.25 pin. The 0.3.26 release run writes the new cutoff with
`python scripts/pinned_workflows.py cutoff`, after `publish` has put the 0.3.26 wheel on PyPI, and before
`release.py workflows`.

**The test count.** The documents give one count of tests, and it is defined as the tests that passed in CI on the
staging tree of the release, not a count made on anyone's machine. The tree handed over still carries the count of
the release before. Take `<passed>` and the skipped count from the `pytest` job (ubuntu-latest, Python 3.12) of the
last green `tests.yml` run on staging, and write it with its source:

```
python scripts/bench_docs.py --set tests_passing=<passed> --source "pytest (ubuntu-latest, 3.12) of tests.yml run <run id> on drexthealpha/knos-rc <commit>, the staging tree of this release: <passed> passed, <skipped> skipped, https://github.com/drexthealpha/knos-rc/actions/runs/<run id>"
python scripts/bench_docs.py --check && python scripts/doc_claims.py
python scripts/release_manifest.py --check        # docs/MANIFEST.md is what the tree gives: source, built bytes, capabilities, limits
python scripts/truth_check.py                     # no document or page contradicts the capability list, the source or the price book
python scripts/rate_claims.py                     # every latency or throughput figure has its sample size, its program ids and its date
python scripts/stale_check.py                     # no public file states a retired figure as current
python scripts/public_face.py --check             # every description of Knos in this tree is the one sentence
python scripts/judges.py --check                  # docs/JUDGES.md keeps its rules, and docs/judges.json is that page
python -m knos.enforce --check                    # docs/ENFORCEMENT.md is the table the code gives
python scripts/archive_verify.py --check          # the recorded run of the stand-alone verifier is what a run gives now
```

After the packages are published and the repository's description is set, the same sentence is read back from where
people see it. This asks PyPI, the MCP registry, glama.ai and GitHub, and prints the command that corrects each one
that still serves older words (`glama.json` has no description field: glama.ai indexes the README by itself):

```
python scripts/public_face.py --remote
```

It rewrites `docs/bench.json`, `docs/facts.json` and the sentence in `docs/submission/SUBMISSION.md`. (The tree
collects 2,639 tests with `pytest --collect-only -q tests`; a collected test is not a passed one, and that figure is
written nowhere else.)

`verify` builds the wheel once more from the stamped tree and compares it with the lock. If it differs, something
that is part of the wheel changed after the lock, and PyPI holds the locked wheel already: undo the change (`git
diff`), or release a new version.

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

## The ONE push, then the tag

```
python scripts/release.py pypi-check              # PyPI serves the locked wheel, and its index lists it
git push origin main                              # the ONE push
git tag v0.3.26 && git push origin v0.3.26        # starts release.yml
```

`publish` ran before the workflows (above). It refuses unless `dist/` holds the locked wheel and this tree builds that
wheel. A file on PyPI can never be replaced: if PyPI already has this version with another hash, the only way on is a
new version.

The wheel goes up before the push because the moment the commit is public, the workflows it pins install
`knos==0.3.26` by that hash. If PyPI did not have the file yet, every signing job would fail until it did. It goes up
before the workflows too, because their cutoff is written from the time PyPI took it ("Why there is an order").

**Push only once PyPI's index lists the wheel.** PyPI answers from two places: the page of a version shows an
upload at once, and the index an installer resolves from (`https://pypi.org/simple/knos/`) is a cached page that
showed 0.3.15 a few minutes later. The push went out in between, and the first runs on the new commit failed: the
index had "no version of" the release they asked for. `publish` asks that index every 20 seconds, for 10 minutes at
most, and ends with "Do NOT push yet" when the file is still not listed; `python scripts/release.py pypi-check --wait
600` asks again.

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

Three packages, each published: `knos-oidc-interface` 0.3.14 and `knos-pay-interface` 0.3.14 on crates.io
([knos-oidc-interface](https://crates.io/crates/knos-oidc-interface),
[knos-pay-interface](https://crates.io/crates/knos-pay-interface)) and `knos-settle` 0.3.20 on npm
([knos-settle](https://www.npmjs.com/package/knos-settle)), all three by hand by the owner on 8 October 2026. On
4 October 2026 all three names were free: `https://crates.io/api/v1/crates/<name>` and
`https://registry.npmjs.org/knos-settle` each answered 404.

After the first version, `release.yml` publishes them with no stored secret (the jobs `crates-trusted` and
`npm-trusted`): the registry exchanges the run's GitHub OIDC token for a credential that lives minutes, and npm
records provenance. But both registries let a trusted publisher be configured only on a package that exists
([crates.io](https://blog.rust-lang.org/2025/07/11/crates-io-development-update-2025-07/): "you'll need to publish
your first release manually"; [npm](https://docs.npmjs.com/trusted-publishers): the setting is on the package's own
page). So the first version of each is published by hand, once, by the owner, signed in to each registry. That is
the only step here that needs a person and an account, and it was done on 8 October 2026 for all three.

Before anything is uploaded, on the release commit (each prints what would be uploaded and uploads nothing):

```
(cd crates/knos-oidc-interface && cargo publish --dry-run --locked)
(cd crates/knos-pay-interface  && cargo publish --dry-run --locked)
(cd sdk/settle && node test.mjs && npm pack --dry-run && npm publish --dry-run)
```

0.3.19 makes this first publish if and only if the release machine is ALREADY signed in to the registry, and it
finds that out without starting a sign-in:

```
[ -n "${CARGO_REGISTRY_TOKEN:-}" ] || [ -s "${CARGO_HOME:-$HOME/.cargo}/credentials.toml" ] && echo "crates.io: signed in" || echo "crates.io: not signed in: skip the crates"
npm whoami >/dev/null 2>&1 && echo "npm: signed in as $(npm whoami)" || echo "npm: not signed in: skip knos-settle"
```

Signed in: after the tag's tests passed, the two `cargo publish --locked` lines and the `npm publish` line below,
without the `login` and `logout` lines around them. Not signed in: nothing is published, no account is created,
`cargo login` and `npm login` are not run, and the jobs stay green with their notice. The crates are published at
the version they are held at (0.3.14: `scripts/bump_version.py`, `PROGRAMS_FROZEN`), since their bytes did not change.

The first publish by the owner, signing in for it:

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

### Registries: is this machine signed in, and the commands in order

`python scripts/release.py registry-plan` prints, for each package, whether it packs, and then one line per
registry: `OK` with the commands in order, or `blocked` with the reason. It starts no sign-in and reads no token.
Add `--online` to ask each registry which versions it has.

"Already signed in" means exactly this, and nothing more:

| registry | signed in when | not signed in looks like |
|---|---|---|
| crates.io | `CARGO_REGISTRY_TOKEN` is set, or `cargo login` has stored a token: `${CARGO_HOME:-~/.cargo}/credentials.toml` exists and is not empty | `crates.io: blocked: not signed in: CARGO_REGISTRY_TOKEN is not set and .../credentials.toml is missing or empty` |
| npm | `npm whoami` answers with a user name | `npm: blocked: not signed in: \`npm whoami\` did not answer with a name (ENEEDAUTH)`; the 0.3.19 run saw `ENEEDAUTH` in WSL and `E401` on Windows |

When a registry says `OK`, in this order (the two interface crates are held at 0.3.14, and do not depend on each
other; `--dry-run` first, each time):

```
(cd crates/knos-oidc-interface && cargo publish --dry-run --locked) && (cd crates/knos-oidc-interface && cargo publish --locked)
(cd crates/knos-pay-interface  && cargo publish --dry-run --locked) && (cd crates/knos-pay-interface  && cargo publish --locked)
(cd sdk/settle && node test.mjs && npm publish --dry-run && npm publish --access public)
python scripts/release.py registry-plan --online        # each version is now on its registry: nothing to publish
```

When a registry says `blocked`, nothing is published there and the release goes on: no `cargo login`, no
`npm login`, no account. The 0.3.19 run was signed in to neither registry; the first versions went up by hand on
8 October 2026, from a machine signed in to both.

A package is published at ITS OWN version. `knos-settle` moves with every release, so its version is the tag's.
The two interface crates are among the crates `scripts/bump_version.py` holds (`PROGRAMS_FROZEN`, at `FROZEN_AT`), so
during such a release their version is NOT the tag's, on purpose. The publishing jobs ask one rule
(`python scripts/release.py registry-plan`): the version is the tag's or the held one, anything else is red; a
package that is not on its registry yet, and a version the registry already has, are green with a notice; only a
version the registry lacks is published. (In 0.3.15 the job compared a held crate with the tag and could never pass.)

Besides the registries, the crates still install as git dependencies and the client from the release's tarball
([INSTALL.md](INSTALL.md)).

## After the pending upgrade: the ONE proposal set

This section is the record of how 0.3.18 made proposals 7 and 8. 0.3.19 proposes nothing: `propose` refuses.

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
60 and 90 seconds, 195 seconds in all, inside a 6-minute step timeout, and then it fails as before. Any other install
error is red at once. A run that stays in its install longer than that has written no heartbeat, and the watchdog
cancels and replaces it ([RELAY.md](RELAY.md)).

The start of the next run is asked again when GitHub answers it with a 5xx or a 429, or does not answer: after 2, 4,
8, ... seconds, or what `Retry-After` says (`python -m knos.proof.chain start`; up to 3 times in the handover step
and 6 in the last). In the 0.3.19 run one HTTP 500 to that start ended the chain until it was started by hand. And a
job that is not part of the chain, `watchdog`, starts a chain when no run of one is queued or in progress: on the
workflow's timer and on every event that starts the workflow (a token announced, a `knos` run ended), with no
secret. Should two starts be taken, the older run goes on and the other ends at its first step. Neither has run on
GitHub yet: `tests/test_worker_chain.py` and `tests/test_workflows2.py` test them here.

A run that fails starts no next run, by design. If the chain has stopped and no event or timer has started it:

```
gh run list --repo drexthealpha/Knos --workflow worker.yml --limit 5     # is any run going?
gh workflow run worker.yml --repo drexthealpha/Knos --ref main           # start the chain: leave the input `after` empty
```

Re-running the failed run restarts nothing: a second attempt of a run relays nothing and starts nothing (its first
attempt is taken to have started the next run), so "Re-run failed jobs" goes green and the chain stays stopped. The
watchdog starts a chain when none is alive, but its timer is a scheduled run, and a scheduled run can be delayed
([GitHub's documentation of `schedule`](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule));
after a release, look once and start it by hand.

Right after the push, start the watchdog once so the chain does not wait for GitHub's timer:

```
gh workflow run watchdog.yml --repo drexthealpha/Knos
```

## After the tag: the first real runs

1. **The pinned workflows are republished** (the `release.py workflows` step and its push, above): check that the
   pinned commit of `drexthealpha/knos-workflows` holds this release's set. 0.3.21's `/knos reserve` and the
   hermetic judge exist only once they are republished at 0.3.21.
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
| `release.py verify`: the wheel differs from the lock | a file inside the wheel changed after the lock | before `publish`: `release.py wheel`, lock again, then the order again from `publish`. After `publish`: PyPI holds the locked wheel, so undo the change (`git diff`) or release a new version |
| `pinned_workflows.py cutoff`: PyPI does not serve the wheel yet | `publish` has not run, or did not finish | `python scripts/release.py publish`, then `cutoff` again; it wrote nothing |
| `release.py workflows` or `verify`: "Upload the wheel first" | the cutoff was written for an earlier release, so uv would not see this one | `publish`, then `pinned_workflows.py cutoff` |
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
| the scheduled run ends `stopped: the upgrade run did not start and nothing was sent: ...` | the Node packages of `scripts/` were missing and `npm ci` could not install them (no npm on the run's PATH, or no network) | `npm ci --prefix scripts`, then `bash scripts/schedule_upgrade.sh --run`; `--verify` shows the same before the time comes |
| `status --want 2.2` exits 3 | proposal 7 or 8 has not executed; the line names which, in the multisig's word | ship without the after rounds; run them on a later day |
| `run --phase after` prints `nothing was sent` and exits 3 | the public ids do not run the builds of proposals 7 and 8 | the same: later |
| `upgrade_feed.py --published` exits 1 | the site was built before a proposal was made or executed | `gh workflow run network.yml --repo drexthealpha/Knos --ref main`, then the same command |
| the scheduled run CANNOT START: a key file cannot be read | the drive or mount that holds it was not there | mount it (open a terminal: the profile does), then `bash scripts/schedule_upgrade.sh --run` |
