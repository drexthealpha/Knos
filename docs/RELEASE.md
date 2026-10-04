# How a Knos release is made

ONE commit and ONE push to `drexthealpha/Knos`. Everything that can fail is done before that commit, in staging or on
the operator's machine, and every command below can be run again after a failure: each reads what is already there
and does only what is missing.

This page is the plan for 0.3.14. The tools enforce the order: a step run too early stops and says which step comes
first.

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

## Before the commit: the chain

The second deployment is upgradeable only through a multisig with a public 48-hour delay, until an outside
review. So the four programs that change are proposed, not deployed: knos_oidc and knos_pay to 2.1, knos_meter and
knos_passkey to 1.1. The upgrade vault holds all four (0.3.13 deployed the meter and the passkey wallet at 1.0 and
handed them over), and nothing is deployed for the first time in this release. All of it is on devnet, in test USDC.
The builds are the verified builds that `program.yml` made in staging (`KNOS_SO_DIR`), never a build of this machine.

0.3.13 proposed 2.1 builds of knos_oidc and knos_pay: proposals 1 and 2 of the upgrade multisig, approved, executable
from 2026-10-06 07:17 UTC, with a run arranged for 07:27 UTC that day. That build of knos_pay must not execute
([SECURITY.md](SECURITY.md), section 15). So the chain work of 0.3.14 is the section below, "Replacing a proposal
that must not execute", and its first two steps do not wait for anything else on this page.

The rehearsal is what it was:

```
bash scripts/deploy_v2.sh --localnet --keep      # a dry run of the plain deployment on a local validator, first
bash scripts/deploy_v2.sh --rc                   # the 2.1 builds of knos_oidc and knos_pay under staging ids of their own
export KNOS_PROGRAM_IDS=<key folder>/rc/program_ids.json    # the clients now talk to the staging programs
#   ... rehearse every new instruction here ...
unset KNOS_PROGRAM_IDS
bash scripts/deploy_v2.sh --rc-close             # the staging programs are closed; their SOL returns
```

`--rc` says which verifier the staging escrow trusts: the address is a constant of the build, so a staging escrow
built from the same sources reads tokens of the deployed verifier, not of the staging one. What needs no token, and
the staging verifier's own instructions, are rehearsed as they are; the token paths of the escrow need a staging
build with that constant changed (`KNOS_RC_SO_DIR`). `--rc` stages those two programs only: knos_meter 1.1 and
knos_passkey 1.1 are rehearsed on the local validator and in the tests (LiteSVM), not under staging ids on devnet.

## Replacing a proposal that must not execute

The commands, in this order. Each can be run again after a failure; each reads the chain first.

```
bash scripts/schedule_upgrade.sh --cancel        # 1. the timer for the old proposals is taken back
export KNOS_SO_DIR=<folder with knos_oidc.so, knos_pay.so, knos_meter.so, knos_passkey.so>    # 2. the verified builds
bash scripts/deploy_v2.sh --propose --replace    # 3. the old proposals are withdrawn, then this build is proposed, four times
bash scripts/schedule_upgrade.sh                 # 4. the executions, at the printed time plus ten minutes, unattended
python scripts/upgrade_feed.py --out web         # 5. web/upgrades.json and web/upgrades.xml say what the chain says now
```

1. `--cancel` removes the timer (systemd, at, or the Windows task) that would have run
   `node scripts/governance.mjs upgrade execute` on 2026-10-06 at 07:27 UTC. It sends nothing: the proposals are
   still approved on chain after it. Check: `bash scripts/schedule_upgrade.sh --show` prints `timer: none arranged`.
2. The verified builds are the four files of `program.yml`'s `verified-build` jobs (artifacts
   `<program>-v2-verified.so`), in one folder. Check each against the run's own line:
   `solana-verify get-executable-hash $KNOS_SO_DIR/knos_pay.so` is the hash the job printed.
3. `--propose --replace` first lists every proposal that can still run and would deploy another build of one of the
   four programs, and withdraws each by the member keys' votes, printing its index, its program and the hash of the
   build it carried (here: proposal 1, knos_oidc; proposal 2, knos_pay). An approved proposal is cancelled; the Squads
   program takes the cancelling votes inside the 48 hours as well as after them, and a cancelled proposal can never
   be executed. Only when the chain shows them withdrawn does it go on: a buffer for each program (named for the
   program and the build), the upgrade gate's record of each build, the four proposals, approved. A program that
   runs this build already is skipped (`runs this build already`). Without `--replace` the same command refuses
   while such a proposal stands and says to pass `--replace`: two approved proposals for one program would both
   execute. Check: `node scripts/governance.mjs show` prints `proposals        6 so far` for the upgrade multisig
   and the upgrade vault as the upgrade authority of all four programs; `knos status` lists proposals 3 to 6 as
   pending, each with `recorded by upgrade_gate` and the commit GitHub built it from, and no longer lists 1 and 2.
4. The new run is arranged for the time step 3 printed, plus ten minutes. It executes each of the four proposals only
   while the proposal's buffer holds the build that was proposed (`upgrade execute <index> --expect-hash <hash>`,
   the hash from `<key folder>/upgrade-schedule.json`): a run arranged for a build that was withdrawn since executes
   nothing of it. Check: `bash scripts/schedule_upgrade.sh --show` lists four proposals, each with its program and
   build, and one timer.
5. The feed is what people subscribed to: proposals 1 and 2 read `replaced` there and 3 to 6 `pending`, with the
   time from which they can run. Check: the last line it prints says `6 upgrade proposals, 4 pending`; commit both
   files with the release, or let the site's build write them.

When each step can run. Step 1 needs nothing but this checkout and the key folder: do it at once. Step 2 needs the run
of `program.yml` that built the release's sources (the builds are reproducible: staging's are the files that `main`'s
run builds again). Step 3 needs each build's record at the upgrade gate, and `program.yml`'s gate job writes that only
for a run on `main` or on a release tag of `drexthealpha/Knos`, so the proposing half of step 3 can only finish after
the ONE push below (it waits up to `KNOS_GATE_WAIT` seconds for the record, 1800 by default). The withdrawing half
does not wait for that. To withdraw before the push, and so before the old proposals' time, vote directly:

```
node scripts/governance.mjs cancel upgrade 1     # knos_oidc, the build of 0.3.13
node scripts/governance.mjs cancel upgrade 2     # knos_pay, the build that must not execute
python scripts/upgrade_feed.py --out web         # both read `cancelled` until this build is proposed, `replaced` after
```

Each prints `proposal <index> of the upgrade multisig is cancelled: it can never be executed.` With fewer member
keys than the threshold (2) it says how many votes are still missing, that the proposal can STILL be executed, and
exits 1. `knos status` then passes its line `upgrade proposal: nothing pending on the upgrade multisig`. After the
push, steps 3 to 5 run as written; `--replace` then finds nothing left to withdraw and says so.

`--propose` refuses a build that the upgrade gate has no record of (GitHub's signed statement that its runner built
exactly these bytes from a commit of this repository). `--propose --ungated` proposes it anyway and says so in
capitals; the members then have only their own rebuild to compare with.

What runs in the meantime. Until each proposal executes, devnet runs what it ran before: knos_oidc 2.0, knos_pay
2.0, knos_meter 1.0 and knos_passkey 1.0. Cancelling changes no program. From the approval, anyone can read the four
proposals on chain for 48 hours, `knos status` reports them as pending, and the members can cancel any
(`node scripts/governance.mjs cancel upgrade <index>`). The 0.3.14 clients ask each program which build it runs and
work with the old and the new one. For knos_pay that is its Version instruction, so 0.3.14 works against 2.0 until
the upgrade executes and against 2.1 after it. For the meter and the passkey wallet, everything 1.0 has (a single
evaluation's Record, credits, the wallet's Open and Withdraw) is sent to either build unchanged; what only 1.1 has
(the meter's batch and claim, the passkey wallet's Fund) is refused by the relay before anything is sent while 1.0
runs, with the sentence `this needs knos_meter 1.1, which executes on <date>` (or `knos_passkey`), the date read
from the proposal on chain. The same request goes through once the proposal has executed.

Room for the larger escrow. A program can be upgraded only to a build that fits its data account, and a deploy leaves
room for twice the first build. On 4 October 2026 devnet's knos_pay has room for 383,744 bytes (read from its data
account), and the build of this tree is larger: 403,672 bytes as `cargo build-sbf` makes it here (the verified build's
own size is the one that counts). The other three fit. So step 3 extends knos_pay's data account by the difference
before it hands the buffer to the vault, and prints that it does: the upgradeable loader's `ExtendProgram`, paid by
the fee payer (about 0.10 SOL of rent, which does not come back: `solana rent 19928` answered 0.10188448 SOL on devnet
that day). It changes no code. Anyone may send it while the cluster has not activated `ExtendProgramChecked`, and
`solana feature status` listed that as inactive on devnet that day; a validator started with that feature off, holding
devnet's knos_pay, took the instruction from a key that is not the upgrade authority. `solana program extend` is not
used for it: the command line (3.0.0) refuses a program whose upgrade authority is not the key it is given. If devnet
activates the feature before step 3 runs, only the upgrade vault can extend, the step stops with that sentence, and
the extension has to be a proposal of the multisig executed before the upgrade. Nothing in this repository makes that
proposal yet.

What this leaves behind: the two buffers of the withdrawn proposals stay on chain, owned by the upgrade vault, with
the SOL of their rent. Only a proposal of the vault can close them; nothing here does.

## The commit

In the staging tree that is going to be the release, in this order:

```
python scripts/bump_version.py --check 0.3.14    # every manifest, lock file, IDL and install line names it
python scripts/release.py wheel                  # dist/knos-0.3.14-py3-none-any.whl and the sdist, built ONCE
python scripts/pinned_workflows.py lock dist/knos-0.3.14-py3-none-any.whl --write    # its hash, into requirements/sign.txt
python scripts/release.py workflows <checkout of knos-workflows>     # the published set with that lock, committed there
git -C <checkout of knos-workflows> push         # the commit must exist on GitHub before anything names it
python scripts/pinned_workflows.py stamp <that commit>               # the examples, knos.yml, docs/ and the site name it
python scripts/small_repos.py build knos-task <checkout>             # and knos-attest, knos-claim-org: commit and push each
python scripts/release.py verify <checkout of knos-workflows>        # versions, the lock, the wheel built again, the pin
```

`verify` builds the wheel once more from the stamped tree and compares it with the lock. If it differs, something
that is part of the wheel changed after the lock: nothing has been published yet, so find it and lock again.

Then the private gate (`ship_check.py`, kept outside the repository) on the tree, the ONE commit, and the gate once
more on the commit:

```
python ship_check.py --tree <the handed-over tree> --version 0.3.14 --workflows <checkout of knos-workflows>
git commit                                        # one commit, by the owner, with no trailer
python ship_check.py ... --committed
```

## The wheel, then the ONE push, then the tag

```
export UV_PUBLISH_TOKEN=<a PyPI token for the knos project>         # read by uv, never printed
python scripts/release.py publish                 # uploads THAT wheel and the sdist, then asks PyPI for the hash
git push origin main                              # the ONE push
git tag v0.3.14 && git push origin v0.3.14        # starts release.yml
```

`publish` refuses unless `dist/` holds the locked wheel, the tree is committed and the commit holds the lock. A file
on PyPI can never be replaced: if PyPI already has this version with another hash, the only way on is a new version.

The wheel goes up before the push because the moment the commit is public, the workflows it pins install
`knos==0.3.14` by that hash. If PyPI did not have the file yet, every signing job would fail until it did.

## What the tag starts

`release.yml` uploads nothing to PyPI. On the tagged commit it

1. runs the whole test workflow (the gate: every later job needs it);
2. builds the wheel again and fails unless it is the locked one, so the commit holds the sources of the wheel it
   names;
3. asks PyPI for the wheel of this version and fails loudly unless PyPI serves a file with exactly the locked hash;
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

Until the first publish, the crates install as git dependencies and the client from the release's tarball
([INSTALL.md](INSTALL.md)).

## Two days later

At the time `--propose` printed, plus ten minutes, the scheduled run executes the four proposals in the order of
their indexes (knos_oidc, knos_pay, knos_meter, knos_passkey), each only while its buffer holds the build that was
proposed, and then runs `knos status`; every line is in `<key folder>/upgrade-run.log`. `bash scripts/schedule_upgrade.sh --show` says what
is arranged and what the log holds; `--cancel` takes the timer back. If the machine was off at that time, run it by
hand: `bash scripts/schedule_upgrade.sh --run`. An execution before its time is refused by the Squads program
itself, and one that already happened is left alone.

Under WSL the run is a Windows scheduled task, which starts the distribution: a timer inside WSL fires only while it
runs. Every timer starts the run through a login shell, and the run reads the key paths arranging wrote
(`<key folder>/upgrade-run.env`: paths, never a key); a key file it cannot read then (a drive that is not mounted)
stops it before anything is sent, and the log says which file.

## What can go wrong, and what then

| What | What it means | What to do |
|---|---|---|
| `release.py verify`: the wheel differs from the lock | a file inside the wheel changed after the lock | nothing is published yet: `release.py wheel`, lock again, build the workflows again, stamp again |
| `release.py publish`: PyPI has this version with another hash | a different wheel was uploaded earlier | a new version: bump, and the whole order again |
| `release.yml` build: not the locked wheel | the tagged commit does not build the wheel it names | do not move the tag: fix on main, release a new version |
| `release.yml` pypi: PyPI does not serve the wheel | the push happened before `publish` | run `release.py publish` from the machine that holds `dist/`, then re-run the failed jobs |
| `deploy_v2.sh` stops half way | a transaction was lost | run the same command again: the same buffer continues |
| the scheduled run says a proposal was NOT executed | too early, cancelled, or the machine was off | read the log; `bash scripts/schedule_upgrade.sh --run` |
| the scheduled run says a proposal `would deploy the build ..., and this run was arranged for the build ...` | the schedule is of a build that was withdrawn or replaced | nothing was sent; `bash scripts/schedule_upgrade.sh --cancel`, then arrange again after the next `--propose` |
| `deploy_v2.sh --propose` refuses: a proposal `would deploy another build than this one` | an older proposal for the same program can still run | "Replacing a proposal that must not execute": `--propose --replace` |
| `--propose --replace` says a proposal is `still not withdrawn` | fewer member keys than the threshold voted | it can STILL be executed: run it again with the member keys (`KNOS_MEMBERS`), before anything else |
| `--propose` stops: a program's data account `could not be extended` | the build is larger than the room, and the cluster lets only the upgrade authority extend | "Room for the larger escrow" above: the extension must be a proposal of the vault first; the other programs' proposals stand |
| a batch or a passkey funding is answered `this needs knos_meter 1.1` (or `knos_passkey 1.1`) | its upgrade has not executed yet | nothing was sent; the same request works after the date in the answer |
| the scheduled run CANNOT START: a key file cannot be read | the drive or mount that holds it was not there | mount it (open a terminal: the profile does), then `bash scripts/schedule_upgrade.sh --run` |
