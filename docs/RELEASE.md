# How a Knos release is made

ONE commit and ONE push to `drexthealpha/Knos`. Everything that can fail is done before that commit, in staging or on
the operator's machine, and every command below can be run again after a failure: each reads what is already there
and does only what is missing.

This page is the plan for 0.3.13. The tools enforce the order: a step run too early stops and says which step comes
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
review. So the two programs that change (knos_oidc and knos_pay, to 2.1) are proposed, not deployed, and the three
new programs are deployed and handed to the same vault at once. All of it is on devnet, in test USDC. The builds are
the verified builds that `program.yml` made in staging (`KNOS_SO_DIR`), never a build of this machine.

```
bash scripts/deploy_v2.sh --localnet --keep      # a dry run of every step below on a local validator, first
bash scripts/deploy_v2.sh --new                  # knos_meter, knos_passkey, upgrade_gate: deployed, then the vault holds them
bash scripts/deploy_v2.sh --rc                   # the 2.1 builds under staging ids of their own
export KNOS_PROGRAM_IDS=<key folder>/rc/program_ids.json    # the clients now talk to the staging programs
#   ... rehearse every new instruction here ...
unset KNOS_PROGRAM_IDS
bash scripts/deploy_v2.sh --rc-close             # the staging programs are closed; their SOL returns
bash scripts/deploy_v2.sh --propose              # buffers, the upgrade gate's record, both proposals, approved
bash scripts/schedule_upgrade.sh                 # the executions, at the printed time plus ten minutes, unattended
```

`--rc` says which verifier the staging escrow trusts: the address is a constant of the build, so a staging escrow
built from the same sources reads tokens of the deployed verifier, not of the staging one. What needs no token, and
the staging verifier's own instructions, are rehearsed as they are; the token paths of the escrow need a staging
build with that constant changed (`KNOS_RC_SO_DIR`).

`--propose` refuses a build that the upgrade gate has no record of (GitHub's signed statement that its runner built
exactly these bytes from a commit of this repository). `--propose --ungated` proposes it anyway and says so in
capitals; the members then have only their own rebuild to compare with.

From the approval, anyone can read both proposals on chain for 48 hours, `knos status` reports them as pending, and
the members can cancel either (`node scripts/governance.mjs cancel upgrade <index>`). The clients ask the program
which version it runs, so 0.3.13 works against 2.0 until the upgrade executes and against 2.1 after it.

## The commit

In the staging tree that is going to be the release, in this order:

```
python scripts/bump_version.py --check 0.3.13    # every manifest, lock file, IDL and install line names it
python scripts/release.py wheel                  # dist/knos-0.3.13-py3-none-any.whl and the sdist, built ONCE
python scripts/pinned_workflows.py lock dist/knos-0.3.13-py3-none-any.whl --write    # its hash, into requirements/sign.txt
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
python ship_check.py --tree <the handed-over tree> --version 0.3.13 --workflows <checkout of knos-workflows>
git commit                                        # one commit, by the owner, with no trailer
python ship_check.py ... --committed
```

## The wheel, then the ONE push, then the tag

```
export UV_PUBLISH_TOKEN=<a PyPI token for the knos project>         # read by uv, never printed
python scripts/release.py publish                 # uploads THAT wheel and the sdist, then asks PyPI for the hash
git push origin main                              # the ONE push
git tag v0.3.13 && git push origin v0.3.13        # starts release.yml
```

`publish` refuses unless `dist/` holds the locked wheel, the tree is committed and the commit holds the lock. A file
on PyPI can never be replaced: if PyPI already has this version with another hash, the only way on is a new version.

The wheel goes up before the push because the moment the commit is public, the workflows it pins install
`knos==0.3.13` by that hash. If PyPI did not have the file yet, every signing job would fail until it did.

## What the tag starts

`release.yml` uploads nothing to PyPI. On the tagged commit it

1. runs the whole test workflow (the gate: every later job needs it);
2. builds the wheel again and fails unless it is the locked one, so the commit holds the sources of the wheel it
   names;
3. asks PyPI for the wheel of this version and fails loudly unless PyPI serves a file with exactly the locked hash;
4. creates the GitHub release with the wheel, the sdist, `sign.txt` and the JavaScript client's tarball; lists the
   MCP server in the registry; attaches the Gemini extension; publishes to crates.io and npm when their tokens exist;
   starts the site's build.

## Two days later

At the time `--propose` printed, plus ten minutes, the scheduled run executes both proposals and then runs
`knos status`; every line is in `<key folder>/upgrade-run.log`. `bash scripts/schedule_upgrade.sh --show` says what
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
| the scheduled run CANNOT START: a key file cannot be read | the drive or mount that holds it was not there | mount it (open a terminal: the profile does), then `bash scripts/schedule_upgrade.sh --run` |
