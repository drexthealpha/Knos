# How a Knos release is made

ONE commit and ONE push to `drexthealpha/Knos`. Everything that can fail is done before that commit, in staging or on
the operator's machine, and every command below can be run again after a failure: each reads what is already there
and does only what is missing.

This page is the plan for 0.3.15. The tools enforce the order: a step run too early stops and says which step comes
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

## The chain: this release changes no program

0.3.15 is clients, workflows, the site, documents and tests. Nothing under `programs-v2/*/src` or `programs/` and no
committed program build changed by one byte. So, for this release:

- **Do not run `scripts/deploy_v2.sh`,** in any mode: nothing is deployed, nothing is proposed, nothing is withdrawn,
  and no staging deployment is made.
- **The four proposals of 0.3.14 stand as they are:** knos_oidc 2.1, knos_pay 2.1, knos_meter 1.1 and knos_passkey 1.1,
  approved through the upgrade multisig with its public 48-hour delay. The job that 0.3.14 scheduled executes them
  ("When the four proposals execute", below). This page names no time for it: `knos status` and
  [`web/upgrades.json`](../web/upgrades.json) hold the live state. Do not arrange the run again and do not cancel it:
  `bash scripts/schedule_upgrade.sh --show` says what is arranged, and that is all this release asks of that script.
- **Until each proposal executes,** devnet runs knos_oidc 2.0, knos_pay 2.0, knos_meter 1.0 and knos_passkey 1.0. The
  0.3.15 clients ask each program which build it runs and work with both, as the 0.3.14 clients do: what only the
  newer build has is refused before anything is sent, with a sentence that names the program and the version it needs.
- **The manifest moves only on evidence.** Every capability this release adds stops at `tested`: none has a
  program of its own, and nothing new was deployed, exercised or reproduced. The stages that wait for the upgrade
  move after it, by the steps of "When the four proposals execute".

How a program is proposed, replaced and scheduled is in [GOVERNANCE.md](GOVERNANCE.md) and in this page as 0.3.14
committed it (`git show v0.3.14:docs/RELEASE.md`); none of it is run now.

## Nothing after the push goes into a commit

The four proposals execute after this release is pushed, and the first real runs of what this release adds happen
after it too. What they show does not exist when the commit is made. No committed file states it, and no step of this
page writes one into a file afterwards:

- The documents name no time for a pending upgrade. They point at `knos status`, which reads the chain, and at the
  site's `upgrades.json`. `web/upgrades.json` in the repository is a copy that says of when it is (`generated`).
- `python scripts/doc_claims.py` (run by the tests) fails when a document names a time for an upgrade that
  `web/upgrades.json` does not give for a pending proposal, when a count of capabilities is not the manifest's, and
  when a slot is unfilled. So the ONE commit is complete, and checked, before the push.
- What the chain says after the push is published by the site's build (`.github/workflows/network.yml` runs
  `scripts/upgrade_feed.py` and `scripts/network_stats.py`), never by a second commit. The same holds when the
  proposals execute: the site and `knos status` say so at once. The manifest's `on_chain` versions and the stages
  that waited for them move in the next release's commit, with `python scripts/capabilities.py check --rpc`.
- The first run of the knos-verify action and of the reproduce workflow ("After the tag", below) are recorded the
  same way: by their links in the next release's manifest, not by a commit added to this one.

## The commit

In the staging tree that is going to be the release, in this order:

```
python scripts/bump_version.py --check 0.3.15    # every manifest, lock file, IDL and install line names it
python scripts/release.py wheel                  # dist/knos-0.3.15-py3-none-any.whl and the sdist, built ONCE
python scripts/pinned_workflows.py lock dist/knos-0.3.15-py3-none-any.whl --write    # its hash, into requirements/sign.txt
python scripts/release.py workflows <checkout of knos-workflows>     # the published set with that lock, committed there
git -C <checkout of knos-workflows> push         # the commit must exist on GitHub before anything names it
python scripts/pinned_workflows.py stamp <that commit>               # the examples, knos.yml, docs/ and the site name it
python scripts/small_repos.py build knos-task <checkout>             # and knos-attest, knos-claim-org: commit and push each
python scripts/release.py verify <checkout of knos-workflows>        # versions, the lock, the wheel built again, the pin
```

The published set differs from 0.3.14's in one file that matters to an order: `attest.yml` now has two jobs, the first
of which runs a black-box suite again and cannot sign ([SECURITY.md](SECURITY.md), section 20). It must be republished
by the `release.py workflows` step above before any order can pin it. An order funded earlier keeps the commit it
recorded, and that file does not re-execute.

`verify` builds the wheel once more from the stamped tree and compares it with the lock. If it differs, something
that is part of the wheel changed after the lock: nothing has been published yet, so find it and lock again.

Then the private gate (`ship_check.py`, kept outside the repository) on the tree, the ONE commit, and the gate once
more on the commit:

```
python ship_check.py --tree <the handed-over tree> --version 0.3.15 --workflows <checkout of knos-workflows>
git commit                                        # one commit, by the owner, with no trailer
python ship_check.py ... --committed
```

## The wheel, then the ONE push, then the tag

```
export UV_PUBLISH_TOKEN=<a PyPI token for the knos project>         # read by uv, never printed
python scripts/release.py publish                 # uploads THAT wheel and the sdist, then asks PyPI for the hash
git push origin main                              # the ONE push
git tag v0.3.15 && git push origin v0.3.15        # starts release.yml
```

`publish` refuses unless `dist/` holds the locked wheel, the tree is committed and the commit holds the lock. A file
on PyPI can never be replaced: if PyPI already has this version with another hash, the only way on is a new version.

The wheel goes up before the push because the moment the commit is public, the workflows it pins install
`knos==0.3.15` by that hash. If PyPI did not have the file yet, every signing job would fail until it did.

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

## After the tag: the first real runs

Three things in this release have run only in tests. Each is run once for real, in this order, before anyone else is
asked to rely on it:

1. **The pinned workflows are republished** (the `release.py workflows` step and its push, above): check that the
   pinned commit of `drexthealpha/knos-workflows` holds the two-job `attest.yml`.
2. **The knos-verify action, once, on a real pull request:** add
   [`integrations/workflows/knos-verify.yml`](../integrations/workflows/knos-verify.yml) to a repository, open a pull
   request, and read the check named `knos-verify` and its verdict. Until this run the manifest's `knos_verify_action`
   says it has never run on GitHub.
3. **The reproduce workflow, once:** [`examples/knos-reproduce.yml`](../examples/knos-reproduce.yml), started by hand
   ([REPRODUCE.md](REPRODUCE.md)). A run in an account of Knos's own shows that the workflow runs and that GitHub signs
   the report; it is refused as a reproduction, by design, and `reproductions/` stays empty until someone else sends one.
4. **Only then the pull requests to other projects' repositories** (the integrations of
   [INTEGRATIONS.md](INTEGRATIONS.md), a registry's list): what they offer has then run once outside the tests. If
   step 2 or 3 fails, fix it in a new version first and open nothing.

None of these runs is written into this release's commit ("Nothing after the push goes into a commit").

## When the four proposals execute

The run that 0.3.14 arranged executes the four proposals in the order of their indexes (knos_oidc, knos_pay,
knos_meter, knos_passkey), each only while its buffer holds the build that was proposed, and then runs `knos status`;
every line is in `<key folder>/upgrade-run.log`. `bash scripts/schedule_upgrade.sh --show` says what is arranged and
what the log holds. If the machine was off at that time, run it by hand: `bash scripts/schedule_upgrade.sh --run`. An
execution before its time is refused by the Squads program itself, and one that already happened is left alone.

After they have executed, and not before:

```
knos status                                       # each program answers with its newer version; nothing is pending
python scripts/capabilities.py check --rpc        # says which `on_chain` versions and stages the manifest must now move
```

Then the exercises of the handover notes (HANDOFF, kept with the release outside the repository, as `ship_check.py`
is): each instruction the newer builds add, once, at the public program ids, in test USDC. Their transactions are the
`exercised` evidence, on public ids, of the next release's manifest. Until then every document says what is true
before and after: the capabilities were rehearsed on staging ids, the manifest holds them at `tested` (only a public
program id is evidence for `deployed` or `exercised`, and `python scripts/capabilities.py check` refuses any other),
and the live state is in `web/upgrades.json`.

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
| the scheduled run says a proposal was NOT executed | too early, cancelled, or the machine was off | read the log; `bash scripts/schedule_upgrade.sh --run` |
| the knos-verify action or the reproduce workflow fails on its first real run | something the tests' stand-in for GitHub did not show | open no pull request elsewhere; fix it and release a new version |
| a batch or a passkey funding is answered `this needs knos_meter 1.1` (or `knos_passkey 1.1`) | its upgrade has not executed yet | nothing was sent; the same request works after the date in the answer |
| the scheduled run CANNOT START: a key file cannot be read | the drive or mount that holds it was not there | mount it (open a terminal: the profile does), then `bash scripts/schedule_upgrade.sh --run` |
