# How a Knos release is made

ONE commit and ONE push to `drexthealpha/Knos`. Everything that can fail is done before that commit, in staging or on
the operator's machine, and every command below can be run again after a failure: each reads what is already there
and does only what is missing.

This page is the plan for 0.3.16. The tools enforce the order: a step run too early stops and says which step comes
first.

0.3.16 is released before proposals 3 to 6 of the upgrade multisig execute; the live state is in
`web/upgrades.json`. So step 0 and the exercises on the public program ids are not run for 0.3.16: they are the first
steps of the next release, and a script that refuses because those proposals have not executed is one of them. Nothing
is marked `exercised` or `deployed` in 0.3.16's commit, and knos_oidc 2.2 will be proposed after the pending upgrade
executes.

The order of 0.3.16, in one line: staging; the wheel; the lock; the workflows; the stamp; the private gate; ONE commit;
PyPI; ONE push; the tag. Once the pending upgrade has executed: step 0 (a check of the chain), the exercises on the
public program ids, and the ONE upgrade this tree's knos_oidc needs.

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

A CHECK, and neither the exercises below nor the proposal of knos_oidc 2.2 starts until it passes. 0.3.14 proposed
four upgrades (proposals 3 to 6 of the upgrade multisig: knos_oidc, knos_pay, knos_meter and knos_passkey). The 2.2
proposal is made only after all four have executed, on top of them, and the exercises need the instructions they
add. 0.3.16 itself is released before they execute, so for 0.3.16 this check is skipped.

```
node scripts/governance.mjs show                  # both multisigs as the design fixes them, and how many proposals so far
knos status                                       # each of the four programs answers with its newer version
python scripts/upgrade_feed.py --check            # exit 1 while any proposal is pending; writes web/upgrades.json
python scripts/capabilities.py check --rpc        # which `on_chain` versions and stages the manifest must now move
```

- `upgrade_feed.py --check` exits 0, and `web/upgrades.json` gives proposals 3, 4, 5 and 6 the status `executed`:
  go on.
- Anything else (a proposal still `pending`, a program that answers with its older version, a cluster that does not
  answer): **the exercises and the proposal wait.** Neither is run. `bash scripts/schedule_upgrade.sh --show` says what
  is arranged and what the run's log holds; if the machine was off at the time, `bash scripts/schedule_upgrade.sh
  --run` runs it by hand (an execution before its time is refused by the Squads program itself, and one that
  already happened is left alone). Then run step 0 again.

The manifest moves in the commit of the release that passes step 0, on that evidence: `capabilities.py check --rpc`
names every `on_chain` version to write, and the stages that waited for the upgrade move with the exercises of the
next section. 0.3.16's commit does not move it: its `on_chain` versions are the ones devnet runs until proposals 3 to 6
execute.

## The exercises on the public program ids

The last two releases could run what their builds add only on staging ids, and a staging id is never evidence
([`capabilities.json`](capabilities.json): a capability is `exercised` only by a transaction at a public program id).
Once step 0 has passed the public programs carry those instructions, and each exercise below is run once, in test
USDC, against the pinned ids (`KNOS_PROGRAM_IDS` unset), BEFORE the commit of the release that runs it. None of them
is run for 0.3.16, which is released before step 0 can pass.

**Each one's transaction signature goes into `docs/capabilities.json` before that one commit** (the capability's
`exercised` evidence; then `python scripts/capabilities.py check --rpc`, which asks devnet that each signature
exists and succeeded). An exercise that fails is a finding: fix it in staging, or
leave the capability at the stage it has evidence for. Nothing is ticked on a staging transaction.

| | Exercise | How it is run | Passes when | Capabilities |
|---|---|---|---|---|
| [ ] | a second payment of one order is refused | pay an order, then send the same pay token again: `python scripts/replay_tokens.py fund.txt proof.txt claim.txt --rpc https://api.devnet.solana.com` | the first is paid, the second is refused by the program | `single_use_tokens`, `order_pay` |
| [ ] | every token is taken once | the tokens the exercises below posted, replayed: `python scripts/replay_tokens.py --capture <owner/repository> --out tokens.jsonl`, then each line sent again with `knos relay` | every replay is refused; the relay log says so for each | `single_use_tokens` |
| [ ] | the fee's three tiers | an order above the first tier: comment `/knos fund 5000` on an issue; before it, `knos budget check` for the same amount | the fee charged is the amount `knos budget check` printed | `fee_tiers`, `work_orders` |
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

## The chain: ONE upgrade, proposed after the pending upgrade executes

0.3.16 changes ONE program: knos_oidc, to version 2.2. Nothing else under `programs-v2/*/src`, `programs/`, `idl/` or
`tests/fixtures/*.so` changes. knos_pay, knos_meter and knos_passkey stay the builds of proposals 4, 5 and 6, which
the chain runs once those have executed, and their crates stay at the version `scripts/bump_version.py` holds them at (`PROGRAMS_FROZEN`, `FROZEN_AT`): a
crate's version is in its build's bytes.

- **Before the commit, a staging rehearsal of 2.2:** `KNOS_SO_DIR=<the staging run's verified builds> bash
  scripts/deploy_v2.sh --rc` puts the build under staging ids of its own (`<key folder>/rc`), and
  `export KNOS_PROGRAM_IDS=<key folder>/rc/program_ids.json` points a client at it. It needs devnet SOL, and the
  script checks the fee payer's balance before it writes anything and stops, naming the amount, when it is short.
  For a build of the size of `tests/fixtures/knos_oidc_v2_real.so` (162,104 bytes): about 2.3 SOL stays in the staging
  program until `bash scripts/deploy_v2.sh --rc-close` returns it, and the check asks for about 4.6 SOL at the start
  (the buffer's part comes back when the deploy ends). The figures are the rent of twice the file,
  (bytes + 128) x 6,960 lamports ([Solana's rent](https://solana.com/docs/core/fees#rent)), as the script's `afford`
  computes it. `--rc` stages knos_pay beside it; when the staging ids of the last rehearsal are still open and hold
  this build of knos_pay, that program is skipped and costs nothing.
- **Before the commit, a check that ONE program changed, in bytes.** The staging run of `program.yml` prints the
  executable hash of each verified build. knos_pay's, knos_meter's and knos_passkey's must be the `build_hash` that
  `web/upgrades.json` gives for proposals 4, 5 and 6 (pending or executed, the feed names each build). knos_pay is the one to look at: it
  links knos_oidc's claim reader (`knos_oidc::claims`, by path in `programs-v2/knos_pay/Cargo.toml`), so a change
  there can move knos_pay's bytes though no line of knos_pay changed. If its hash differs, decide BEFORE the commit:
  either this release proposes knos_pay too and says so everywhere (two upgrades, `KNOS_CHANGES="knos_oidc
  knos_pay"`), or the change to knos_oidc is made where knos_pay does not link it. Found after the push, the same
  difference stops `--propose` at its plan with nothing sent.
- **Nothing is proposed before the push, nor before the pending upgrade has executed.** A proposal names a build that
  GitHub's runner made from a commit of this repository, and that commit is the one this release pushes ("After the
  pending upgrade: the ONE upgrade", below).
- **Until a 2.2 proposal has executed,** devnet runs an earlier knos_oidc: 2.0 until proposal 3 executes, and 2.1
  after it. The 0.3.16 clients ask each program which build it runs
  and work with both: what only the newer build has is refused before anything is sent, with a sentence that names
  the program and the version it needs.

How a program is proposed, replaced and scheduled is in [GOVERNANCE.md](GOVERNANCE.md).

## Nothing after the push goes into a commit

knos_oidc 2.2 will be proposed after the pending upgrade executes, and that proposal can execute 48 hours after its
approval. What it shows does not exist when the commit is made. No committed file states it, and no step of this page writes one into
a file afterwards:

- The documents name no time for a pending upgrade. They point at `knos status`, which reads the chain, and at the
  site's `upgrades.json`. `web/upgrades.json` in the repository is a copy that says of when it is (`generated`).
- `python scripts/doc_claims.py` (run by the tests) fails when a document names a time for an upgrade that
  `web/upgrades.json` does not give for a pending proposal, when a count of capabilities is not the manifest's, and
  when a slot is unfilled. So the ONE commit is complete, and checked, before the push.
- What the chain says after the push is published by the site's build (`.github/workflows/network.yml` runs
  `scripts/upgrade_feed.py` and `scripts/network_stats.py`), never by a second commit. The same holds when the
  proposal executes: the site and `knos status` say so at once. The manifest's `on_chain` version of knos_oidc and
  the stages that wait for 2.2 move in the next release's commit, with `python scripts/capabilities.py check --rpc`.
- What step 0 and the exercises show is the opposite case: it exists BEFORE the commit of the release that runs
  them, so it is in that commit. 0.3.16 runs neither.

## The commit

In the staging tree that is going to be the release, in this order:

```
python scripts/bump_version.py --check 0.3.16    # every manifest, lock file, IDL and install line names it
python scripts/release.py wheel                  # dist/knos-0.3.16-py3-none-any.whl and the sdist, built ONCE
python scripts/pinned_workflows.py lock dist/knos-0.3.16-py3-none-any.whl --write    # its hash, into requirements/sign.txt
python scripts/release.py workflows <checkout of knos-workflows>     # the published set with that lock, committed there
git -C <checkout of knos-workflows> push         # the commit must exist on GitHub before anything names it
python scripts/pinned_workflows.py stamp <that commit>               # the examples, knos.yml, docs/ and the site name it
python scripts/small_repos.py build knos-task <checkout>             # and knos-playground, knos-attest, knos-claim-org: commit and push each
python scripts/release.py verify <checkout of knos-workflows>        # versions, the lock, the wheel built again, the pin
```

`verify` builds the wheel once more from the stamped tree and compares it with the lock. If it differs, something
that is part of the wheel changed after the lock: nothing has been published yet, so find it and lock again.

Then the private gate (`ship_check.py`, kept outside the repository) on the tree, the ONE commit, and the gate once
more on the commit:

```
python ship_check.py --tree <the handed-over tree> --version 0.3.16 --workflows <checkout of knos-workflows>
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
git tag v0.3.16 && git push origin v0.3.16        # starts release.yml
```

`publish` refuses unless `dist/` holds the locked wheel, the tree is committed and the commit holds the lock. A file
on PyPI can never be replaced: if PyPI already has this version with another hash, the only way on is a new version.

The wheel goes up before the push because the moment the commit is public, the workflows it pins install
`knos==0.3.16` by that hash. If PyPI did not have the file yet, every signing job would fail until it did.

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

The first publish, after the tag's tests passed:

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

## After the pending upgrade: the ONE upgrade

The pushed commit changes `programs-v2/knos_oidc`, so `program.yml` runs on main: it makes the verified build of each
program and its `gate` job has GitHub sign the hash of each, which a relayer records at the upgrade gate. Then, once
step 0 has passed (proposals 3 to 6 executed, and not before):

```
gh run download <that program.yml run> --repo drexthealpha/Knos --dir builds     # one folder per artifact
mkdir so && cp builds/knos_*-v2-verified.so/knos_*.so so/                        # knos_oidc.so, knos_pay.so, knos_meter.so, knos_passkey.so
export KNOS_SO_DIR=$PWD/so
bash scripts/deploy_v2.sh --propose              # the plan first; then the buffer, the gate's record, the proposal, the approvals
bash scripts/schedule_upgrade.sh                 # the execution, at the printed time plus ten minutes, unattended
```

What `--propose` must print, and what each line means:

1. `the plan: propose knos_oidc (this release changes: knos_oidc)`. The plan is made before anything is withdrawn,
   written or proposed: for each of the four programs, the build in `KNOS_SO_DIR` against the build the chain runs.
2. `knos_pay ...: runs this build already`, and the same for knos_meter and knos_passkey: three lines. Their verified
   builds from this commit are the builds the chain runs, byte for byte.
3. For knos_oidc: its buffer, the gate's record of the build, the proposal and the members' approvals, and the time
   from which it can be executed, written to `<key folder>/upgrade-schedule.json`.

If the plan stops instead (`stopped: knos_pay is not a program this release changes ...`), NOTHING was sent, and one
of three things is true; the message says them. The earlier proposals have not all executed (step 0 was skipped:
wait). Or the file is a rebuild whose bytes moved though no line of that program did: a version string, or a crate it
links (knos_pay links knos_oidc: `programs-v2/knos_pay/Cargo.toml`). The chain runs the verified build of the tag
`bump_version.py` holds the crate at, so that tag's file goes into `KNOS_SO_DIR` in its place, and the release's
notes say at which tag that program is verified. Or the release does change that program: then it says so
(`KNOS_CHANGES="knos_oidc knos_pay"`), and there are two proposals, not one. A rebuild is never proposed by accident.

`--propose` refuses a build the upgrade gate has no record of; it waits for the record (`KNOS_GATE_WAIT`, 30 minutes
by default). `--ungated` is for an emergency only. `--replace` is not needed: no older proposal can still run after
step 0.

Until the execution anyone can read the proposal on chain, and the members can cancel it:
`node scripts/governance.mjs cancel upgrade <index>`. After it, `knos status` answers knos_oidc 2.2. None of this is
written into a commit ("Nothing after the push goes into a commit").

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

None of these runs is written into this release's commit ("Nothing after the push goes into a commit").

## What can go wrong, and what then

| What | What it means | What to do |
|---|---|---|
| step 0: a proposal is still pending, or a program answers with its older version | the four earlier upgrades have not all executed | the exercises and the 2.2 proposal wait: `bash scripts/schedule_upgrade.sh --show`, then step 0 again |
| `release.py verify`: the wheel differs from the lock | a file inside the wheel changed after the lock | nothing is published yet: `release.py wheel`, lock again, build the workflows again, stamp again |
| `release.py publish`: PyPI has this version with another hash | a different wheel was uploaded earlier | a new version: bump, and the whole order again |
| `release.py publish` ends with "Do NOT push yet" | PyPI's index does not list the wheel yet | do not push; `python scripts/release.py pypi-check --wait 600` until it does |
| `release.yml` build: not the locked wheel | the tagged commit does not build the wheel it names | do not move the tag: fix on main, release a new version |
| `release.yml` pypi: PyPI does not serve the wheel | the push happened before `publish` | run `release.py publish` from the machine that holds `dist/`, then re-run the failed jobs |
| `release.yml` crates-trusted or npm-trusted is red | a package's version is neither the tag's nor the one `bump_version.py` holds it at | fix the version on main and release a new version; a held crate or a package not on its registry is green |
| the worker's first run after the push is red, and no run follows | its install failed, and a failed run starts nothing | "After the push: the worker's chain of runs": start the chain by hand; a re-run does not |
| `deploy_v2.sh --propose` stops at its plan | a program this release does not change differs from the chain | nothing was sent; "After the pending upgrade: the ONE upgrade" says the three cases |
| `deploy_v2.sh --propose`: the upgrade gate holds no record of this build | `program.yml`'s gate job or the relay has not finished, or the file is not the run's artifact | let the run finish and run it again; the buffer is written and stays |
| the scheduled run says a proposal was NOT executed | too early, cancelled, or the machine was off | read the log; `bash scripts/schedule_upgrade.sh --run` |
| the scheduled run CANNOT START: a key file cannot be read | the drive or mount that holds it was not there | mount it (open a terminal: the profile does), then `bash scripts/schedule_upgrade.sh --run` |
