# Contributing

Contributions are welcome and unpaid, unless the issue shows a funded order.
A funded order pays test USDC on Solana devnet, which has no monetary value.
Do not post a wallet address for payment: Knos pays only the address a payee binds to a funded order.

Funded work is listed by `knos work list`. An issue with no funded order pays nothing, whatever a comment on it says. The issues labelled `knos-relay` and `knos-memory`, and the one titled "knos tokens", are logs that a workflow writes. They are not tasks.

Knos is one product: a bounty that pays when its pull request is merged and the checks you named have passed. GitHub signs a record of that run, and a program on Solana checks the signature.
Changes that delete something are the most welcome kind.

## Run the tests

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
pytest -q -n auto                          # offline; runs both sets of programs in LiteSVM (a local Solana simulator) and the referee in five languages
node sdk/settle/test.mjs                   # the JavaScript client against the Python client's fixtures
python scripts/deadcode.py && vulture src/knos scripts --min-confidence 60     # nothing unused ships
python scripts/claims_check.py --offline   # every number in the README and on the site has a source
```

The suite refuses every non-loopback connection and gives each test its own home. It runs the real programs, real
git repositories and real test runners rather than mocks. Please keep it that way. The Go and Rust referee tests are
skipped when those toolchains are not installed.

## Change a program

There are two deployments. `programs/` is the first: it is on devnet with no upgrade authority, so its source must
stay byte for byte what was deployed. Do not change it. `programs-v2/` is the second, where every new bounty is
funded. It can be changed only through a [multisig](docs/WORDS.md#multisig) (several keys that must agree, all held by
the founder today), after a public 8-day wait (in force since 11 Oct 2026; 48 hours before). This holds until an
outside review. So a change there reaches devnet 8 days after it is approved in public.

```bash
bash scripts/build_programs_v2.sh          # needs cargo build-sbf; refreshes tests/fixtures/*_v2_*.so and their pins
cd programs-v2 && cargo test --release     # the Wycheproof vectors and the programs' unit tests
pytest -q -s tests/test_oidc2_chain.py tests/test_pay2_chain.py            # prints the compute units of each step
KNOS_FUZZ_N=2500 KNOS_FUZZ_SEED=1 pytest -q -s tests/test_pay2_chain.py -k random_walk    # a seed repeats a walk
python scripts/settle_fixtures.py          # if an address, an audience or an instruction changed
python scripts/bench_docs.py               # if a measured number changed: docs/bench.json first, then this
```

If you change an instruction's bytes, update four places in this order: the notes at the top of the program,
`src/knos/settle/v2` (the client the tests use), `idl/`, and `sdk/settle/index.js`. The fixtures and
`tests/test_idl.py` tell you whether they still agree. `scripts/build_programs.sh` rebuilds the first
deployment's test binaries from its unchanged source.

## Add a language to the referee

`src/knos/judge.py`: a runner is one function that takes a sandbox `Box` and returns a `Run` (test ids and states,
which ids are the acceptance checks, and the ids of the hidden tests that catch a cheat: the sentinel and canary tests). Add its test directories and protected paths
beside the others, and a test in `tests/test_judge_langs.py` with an honest fix, a no-op and a cheat.

## A good pull request

- One thing, with a test that fails before it and passes after.
- If its description says tests pass, they pass: this repository runs its own check on pull requests.
- No number in the README or on the site without an entry in `docs/facts.json`.

Some issues carry a bounty (`/knos fund` by a maintainer). Knos's reply on the issue states its terms: the checks
that must pass and the files a pull request may change. The merged pull request that meets those terms is paid on
devnet, in test USDC. It is paid to the wallet you linked to your GitHub account, by hand on GitHub or with
`knos claim <address>`. Or it is paid to the wallet you name on the pull request with `/knos address <address>`.
Knos never puts a wallet address in a link, because a link's address could be someone else's. If you name no wallet,
the payment is kept for you for 180 days.
`/knos take` on the issue reserves it for you.

## Release

[CONTRIBUTING.md](CONTRIBUTING.md) is the whole order, with every command. In short: build the package once, lock its hash
in `requirements/sign.txt`, publish the pinned workflows, then make one commit, upload the package to PyPI, push, and
tag:

```bash
git tag v0.4.0 && git push origin v0.4.0
```

`.github/workflows/release.yml` then runs every test on that commit. Only if all of them pass does it publish
anything. It rebuilds the package and checks that it matches the locked hash and the file on PyPI (it uploads nothing
to PyPI). Then it creates the GitHub release with the npm package, lists `knos mcp` in the MCP registry, attaches the
Gemini CLI extension, publishes to crates.io and npm when their tokens are set, and rebuilds the site. Every one of
those jobs needs the test job of the same run, so tagging early only starts the tests earlier, and a commit whose
tests fail publishes nothing. A job added to that workflow must need `tests` too (`tests/test_release_gate.py` fails
if one does not).

## Licence

MIT. By contributing you agree your contribution is under the same licence.

## How a Knos release is made

This page is how a release is made: the order of the steps and the command for each. It is ONE commit and ONE push
to `drexthealpha/Knos`. Everything that can fail is done before that commit. Every command below can be run again
after a failure: each reads what is already there and does only what is missing.

The tools enforce the order: a step run too early stops and says which step comes first.

`<version>` below is the version being released, such as `0.3.27`.

Changing a program on devnet is a separate job, done by the holder of the upgrade keys: how a program is proposed,
replaced and scheduled is in [GOVERNANCE.md](docs/reference/GOVERNANCE.md). A release changes no program unless its notes say so.

### Why there is an order

Four things depend on each other, and only one order satisfies all of them.

- The jobs that sign install by hash. Their list is the last line of `requirements/sign.txt`: the knos wheel by
  its sha256.
- The workflows a repository calls are published at ONE commit of the `workflows-<sha12>` tags of `drexthealpha/Knos` (the
  same commits as the old home `drexthealpha/knos-workflows`), and that commit
  holds the list. So the commit exists only after the wheel does.
- This repository names that commit in `examples/`, in its own `knos.yml`, in `docs/` and on the site.
- The jobs that sign nothing install knos from PyPI with a cutoff, `UV_EXCLUDE_NEWER`. uv takes no file uploaded
  after that time, knos included. So the cutoff is written only once PyPI has the wheel. The `cutoff` command of
  `scripts/pinned_workflows.py` asks PyPI when it took the locked wheel and writes that time plus ten minutes. So
  PyPI comes before the commit of the workflows. A cutoff set by hand once came before its wheel reached PyPI, and
  every job that installs knos from PyPI failed. `tests/test_release_order.py` fails when a cutoff comes before the
  upload its note names, or was set by hand.

So the wheel is built first and once, from the final tree, and nothing inside the wheel names the commit of the
workflows (`src/knos` never does, and `README.md`, which is the wheel's description, is not a file the stamp
writes).

The wheel built before the stamp and the wheel built after it are the same file: `tests/test_release_order.py`
builds both and compares them.

The build is reproducible: `SOURCE_DATE_EPOCH` is fixed in `scripts/release.py`, and the build backend and what it
needs are installed by hash from `requirements/build.txt`.

### The commit

In the tree that is going to be the release, in this order. Run `python scripts/diagrams.py render` before the
version bump: the bump writes README.pypi.md, which shows each of README.md's diagrams as its picture in
docs/diagrams/ at the tag (PyPI does not draw Mermaid).

```
python scripts/diagrams.py render                # before the version bump: a picture of every Mermaid diagram
python scripts/bump_version.py --check <version> # every manifest, lock file and install line names it
python scripts/bench_docs.py --set tests_passing=<passed> --source "<the run>"    # the test count: see below
python scripts/release.py wheel                  # dist/knos-<version>-py3-none-any.whl and the sdist, built ONCE
python scripts/pinned_workflows.py lock dist/knos-<version>-py3-none-any.whl --write    # its hash, into requirements/sign.txt
export UV_PUBLISH_TOKEN=<a PyPI token for the knos project>         # read by uv, never printed
python scripts/release.py publish                 # uploads THAT wheel and the sdist; waits until PyPI's index lists the wheel
python scripts/pinned_workflows.py cutoff         # UV_EXCLUDE_NEWER: ten minutes after PyPI took the wheel, into the workflows
git worktree add ../knos-workflows-branch workflows                  # once: a worktree of the `workflows-<sha12>` tags of this repository
python scripts/release.py workflows ../knos-workflows-branch         # the published set with that lock and cutoff: committed, tagged workflows-<sha12>, pushed
                                                  # (the push: the commit must exist on GitHub before anything names it)
python scripts/pinned_workflows.py stamp <that commit>               # the examples, knos.yml, docs/ and the site name it
python scripts/small_repos.py fold                                   # templates/knos-task, knos-attest, knos-claim, knos-claim-org and the playground: in this commit
python scripts/small_repos.py build knos-playground <checkout>       # NOT since the 0.3.34 branch: the old playground stays frozen at 0.3.28 until it is deleted
python scripts/release.py verify ../knos-workflows-branch             # versions, the lock, the cutoff, the wheel built again, the pin
git commit                                        # the ONE commit, with no trailer and no other flag
```

**PyPI before the workflows.** The wheel is final once it is locked. Run the checks under "The test count" (below)
before `publish`. A file on PyPI can never be replaced, so a change inside the wheel (`src/knos`, `terms/`,
`README.pypi.md`) after `publish` is a new version. The cutoff, the workflows, the stamp and the small repositories
change nothing inside the wheel.

The small repositories are pushed only after `publish`: the workflows they call
install the release from PyPI. `pinned_workflows.py cutoff` refuses until PyPI serves exactly the locked wheel, and
writes nothing then. Until the cutoff names this release, `release.py workflows`, `pinned_workflows.py check` and
`release.py verify` refuse and say "Upload the wheel first".

**The test count.** The documents give one count of tests: the tests that passed in CI on the tree of the release,
not a count made on anyone's machine. Take `<passed>` and the skipped count from the `pytest` job (ubuntu-latest,
Python 3.12) of the last green `tests.yml` run on that tree, and write it with its source:

```
python scripts/bench_docs.py --set tests_passing=<passed> --source "pytest (ubuntu-latest, 3.12) of tests.yml run <run id> on <repository> <commit>: <passed> passed, <skipped> skipped, <link to the run>"
python scripts/bench_docs.py --check && python scripts/doc_claims.py
python scripts/release_manifest.py --check        # docs/reference/MANIFEST.md is what the tree gives: source, built bytes, capabilities, limits
python scripts/truth_check.py                     # no document or page contradicts the capability list, the source or the price book
python scripts/rate_claims.py                     # every latency or throughput figure has its sample size, its program ids and its date
python scripts/stale_check.py                     # no public file states a retired figure as current
python scripts/public_face.py --check             # every description of Knos in this tree is the one sentence
python -m knos.enforce --check                    # docs/reference/COMPANIES.md#enforcement is the table the code gives
python scripts/archive_verify.py --check          # the recorded run of the stand-alone verifier is what a run gives now
```

`bench_docs.py --set` rewrites `docs/bench.json` and `docs/facts.json`. (A collected test is not a passed one:
`pytest --collect-only` gives a larger figure, written nowhere.)

After the packages are published and the repository's description is set, the same sentence is read back from where
people see it. This asks PyPI, the MCP registry, glama.ai and GitHub, and prints the command that corrects each one
that still serves older words (`glama.json` has no description field: glama.ai indexes the README by itself):

```
python scripts/public_face.py --remote
```

`verify` builds the wheel once more from the stamped tree and compares it with the lock. If it differs, something
that is part of the wheel changed after the lock, and PyPI holds the locked wheel already: undo the change (`git
diff`), or release a new version.

Two rules:

- **Every fix made while testing the release is in the one commit.** The tree for the next release is built from
  the PUBLIC commit, so a fix that stayed outside it is lost and the same failure comes back one release later.
  Before the commit, go through the list of fixes and find each one in the release tree.
- **Never pass `--no-verify`,** to this commit or to any push of a release. A hook that stops the commit is a
  finding: fix what it found.

### The ONE push, then the tag

```
python scripts/release.py pypi-check              # PyPI serves the locked wheel, and its index lists it
git push origin main                              # the ONE push
git tag v<version> && git push origin v<version>  # starts release.yml
```

`publish` ran before the workflows (above). It refuses unless `dist/` holds the locked wheel and this tree builds that
wheel. A file on PyPI can never be replaced: if PyPI already has this version with another hash, the only way on is a
new version.

The wheel goes up before the push because the moment the commit is public, the workflows it pins install
`knos==<version>` by that hash. If PyPI did not have the file yet, every signing job would fail until it did.

It goes up before the workflows too, because their cutoff is written from the time PyPI took it ("Why there is an
order").

**Push only once PyPI's index lists the wheel.** PyPI answers from two places: the page of a version shows an
upload at once, but the index an installer reads (`https://pypi.org/simple/knos/`) is a cached page that can lag by
minutes. A push made in between makes the first runs on the new commit fail.

`publish` asks that index every 20
seconds, for 10 minutes at most, and ends with "Do NOT push yet" when the file is still not listed;
`python scripts/release.py pypi-check --wait 600` asks again.

### What the tag starts

`release.yml` uploads nothing to PyPI. On the tagged commit it

1. runs the whole test workflow (the gate: every later job needs it);
2. builds the wheel again and fails unless it is the locked one, so the commit holds the sources of the wheel it
   names;
3. asks PyPI for the wheel of this version and fails loudly unless PyPI serves a file with exactly the locked hash
   and its index lists that file;
4. creates the GitHub release with the wheel, the sdist, `sign.txt` and the JavaScript client's tarball; lists the
   MCP server in the registry; attaches the Gemini extension; publishes to crates.io and npm once each package's
   first version is there (see "Publishing the crates and the npm package"); starts the site's build.

### Publishing the crates and the npm package

Three packages, each published: `knos-oidc-interface` 0.3.14 and `knos-pay-interface` 0.3.14 on crates.io
([knos-oidc-interface](https://crates.io/crates/knos-oidc-interface),
[knos-pay-interface](https://crates.io/crates/knos-pay-interface)) and `knos-settle` 0.3.20 on npm
([knos-settle](https://www.npmjs.com/package/knos-settle)), all three by hand by the owner on 8 October 2026.

After the first version, `release.yml` publishes them with no stored secret (the jobs `crates-trusted` and
`npm-trusted`): the registry exchanges the run's GitHub OIDC token for a credential that lives minutes, and npm
records provenance.

But both registries let a trusted publisher be configured only on a package that exists
([crates.io](https://blog.rust-lang.org/2025/07/11/crates-io-development-update-2025-07/): "you'll need to publish
your first release manually"; [npm](https://docs.npmjs.com/trusted-publishers): the setting is on the package's own
page). So the first version of each is published by hand, once, by the owner, signed in to each registry.

That is the only step here that needs a person and an account, and it was done on 8 October 2026 for all three.

Before anything is uploaded, on the release commit (each prints what would be uploaded and uploads nothing):

```
(cd crates/knos-oidc-interface && cargo publish --dry-run --locked)
(cd crates/knos-pay-interface  && cargo publish --dry-run --locked)
(cd sdk/settle && node test.mjs && npm pack --dry-run && npm publish --dry-run)
```

A first publish by hand is made only if the release machine is ALREADY signed in to the registry, and it finds that
out without starting a sign-in:

```
[ -n "${CARGO_REGISTRY_TOKEN:-}" ] || [ -s "${CARGO_HOME:-$HOME/.cargo}/credentials.toml" ] && echo "crates.io: signed in" || echo "crates.io: not signed in: skip the crates"
npm whoami >/dev/null 2>&1 && echo "npm: signed in as $(npm whoami)" || echo "npm: not signed in: skip knos-settle"
```

The crates are published at the version they are held at (0.3.14: `scripts/bump_version.py`, `PROGRAMS_FROZEN`),
since their bytes did not change. The first publish by the owner, signing in for it:

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

From then on, `crates-trusted` and `npm-trusted` publish. They need crates.io's `rust-lang/crates-io-auth-action`
(pinned in `scripts/action_pins.json`) and npm 11.5.1 or later on Node 22.14 or later (the job installs Node 24
and stops with a plain message if npm is older).

A crate or package that is not on its registry yet is skipped with one line that names this section; a version the
registry already has is left alone. The token jobs (`crates`, `npmjs`) remain as a fallback and do nothing while
`CARGO_REGISTRY_TOKEN` and `NPM_TOKEN` are unset; leave them unset.

A version number, once published, can never be used again on either registry: a mistake is fixed by a new version.

#### Registries: is this machine signed in, and the commands in order

`python scripts/release.py registry-plan` prints, for each package, whether it packs, and then one line per
registry: `OK` with the commands in order, or `blocked` with the reason. It starts no sign-in and reads no token.
Add `--online` to ask each registry which versions it has.

"Already signed in" means exactly this, and nothing more:

| registry | signed in when | not signed in looks like |
|---|---|---|
| crates.io | `CARGO_REGISTRY_TOKEN` is set, or `cargo login` has stored a token: `${CARGO_HOME:-~/.cargo}/credentials.toml` exists and is not empty | `crates.io: blocked: not signed in: CARGO_REGISTRY_TOKEN is not set and .../credentials.toml is missing or empty` |
| npm | `npm whoami` answers with a user name | `npm: blocked: not signed in: \`npm whoami\` did not answer with a name (ENEEDAUTH)` |

When a registry says `OK`, in this order (the two interface crates are held at 0.3.14, and do not depend on each
other; `--dry-run` first, each time):

```
(cd crates/knos-oidc-interface && cargo publish --dry-run --locked) && (cd crates/knos-oidc-interface && cargo publish --locked)
(cd crates/knos-pay-interface  && cargo publish --dry-run --locked) && (cd crates/knos-pay-interface  && cargo publish --locked)
(cd sdk/settle && node test.mjs && npm publish --dry-run && npm publish --access public)
python scripts/release.py registry-plan --online        # each version is now on its registry: nothing to publish
```

When a registry says `blocked`, nothing is published there and the release goes on: no `cargo login`, no
`npm login`, no account. Each registry had no version until the first versions went up by hand on
8 October 2026, from a machine signed in to both.

A package is published at ITS OWN version. `knos-settle` moves with every release, so its version is the tag's. The
two interface crates are among the crates `scripts/bump_version.py` holds (`PROGRAMS_FROZEN`, at `FROZEN_AT`), so
during such a release their version is NOT the tag's, on purpose.

The publishing jobs ask one rule (`python scripts/release.py registry-plan`): the version is the tag's or the held
one, anything else is red; a package that is not on its registry yet, and a version the registry already has, are
green with a notice; only a version the registry lacks is published.

Besides the registries, the crates still install as git dependencies and the client from the release's tarball
([INSTALL.md](docs/reference/INSTALL.md)).

### Nothing after the push goes into a commit

What happens after the push does not exist when the commit is made. No committed file states it, and no step of this
page writes one into a file afterwards:

- The documents name no time for a pending program upgrade. They point at `knos status`, which reads the chain, and
  at the site's `upgrades.json`. `web/upgrades.json` in the repository is a copy that says when it was made
  (`generated`).
- `python scripts/doc_claims.py` (run by the tests) fails when a document names a time for an upgrade that
  `web/upgrades.json` does not give for a pending proposal, when a count of capabilities is not the manifest's, and
  when a slot is unfilled. So the ONE commit is complete, and checked, before the push.
- What the chain says after the push is published by the site's build (`.github/workflows/network.yml` runs
  `scripts/upgrade_feed.py` and `scripts/network_stats.py`), never by a second commit. The manifest's `on_chain`
  versions move in the next release's commit, with `python scripts/capabilities.py check --rpc`.

### After the push: the worker's chain of runs

The public worker (`worker.yml`) is a chain: each run starts the next. The first run on a new release installs that
release by hash. Its install step waits when PyPI's index does not list the release yet: for that one error, 15, 30,
60 and 90 seconds, 195 seconds in all, inside a 6-minute step timeout, and then it fails.

Any other install error is red at once. A run that stays in its install longer than that has written no heartbeat,
and the watchdog cancels and replaces it ([RELAY.md](docs/reference/RELAY.md)).

The start of the next run is asked again when GitHub answers it with a 5xx or a 429, or does not answer: after 2, 4,
8, ... seconds, or what `Retry-After` says (`python -m knos.proof.chain start`; up to 3 times in the handover step
and 6 in the last).

A job that is not part of the chain, `watchdog`, starts a chain when no run of one is queued or in progress: on the
workflow's timer and on every event that starts the workflow (a token announced, a `knos` run ended), with no
secret.

Should two starts be taken, the older run goes on and the other ends at its first step.

A run that fails starts no next run, by design. If the chain has stopped and no event or timer has started it:

```
gh run list --repo drexthealpha/Knos --workflow worker.yml --limit 5     # is any run going?
gh workflow run worker.yml --repo drexthealpha/Knos --ref main           # start the chain: leave the input `after` empty
```

Re-running the failed run restarts nothing: a second attempt of a run relays nothing and starts nothing (its first attempt is taken to have started the next run), so
"Re-run failed jobs" goes green and the chain stays stopped.

The watchdog starts a chain when none is alive, but its timer is a scheduled run, and a scheduled run can be delayed ([GitHub's documentation of
`schedule`](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule)); after a release, look once
and start it by hand.

Right after the push, start the watchdog once so the chain does not wait for GitHub's timer:

```
gh workflow run watchdog.yml --repo drexthealpha/Knos
```

### After the push: logged out

What a stranger is served is checked without a session, from a shell with no GitHub token in its environment:

```
curl -sS -o /dev/null -w "%{http_code}\n" https://github.com/drexthealpha/Knos                  # 200: public. 404: private, or renamed
curl -sS https://raw.githubusercontent.com/drexthealpha/Knos/main/README.md | sha256sum
git show HEAD:README.md | sha256sum                                                             # the same hash as the line above
curl -sS https://raw.githubusercontent.com/drexthealpha/Knos/main/README.md | head -n 30         # read the first screen as it is served
```

Then the repository's page in a private browser window: the README renders, its first screen is the one of the
commit, every link on it opens, and the release named `v<version>` is the latest. Fine: all four.

Not fine: the hash differs (the push did not land, or a cache: wait a minute and run it again) or the page asks to
sign in.

### After the tag: the first real runs

1. **The pinned workflows are republished** (the `release.py workflows` step and its push, above): check that the
   pinned commit of the `workflows-<sha12>` tags of `drexthealpha/Knos` holds this release's set. A new workflow command exists for users
   only once it is republished.
2. **The knos-verify action and the reproduce workflow** ([`integrations/workflows/knos-verify.yml`](integrations/workflows/knos-verify.yml),
   [`examples/knos-reproduce.yml`](examples/knos-reproduce.yml), [REPRODUCE.md](docs/reference/REPRODUCE.md)): a run that this
   release changed is run once for real before anyone else is asked to rely on it.
3. **Only then a pull request to another project's repository:** after that
   project's own test suite passed on the patch. A suite that fails, even the way their unpatched branch fails, is
   not a pass, and nothing is opened.
4. **The tag's own commit is written down.** A commit cannot name itself, so the tagged tree lists its tag in
   [`scripts/action_pins.json`](scripts/action_pins.json) with `KNOS_RELEASE_SHA` for the commit
   (`scripts/bump_version.py` adds the key; `--check` says when it is missing). The first commit after the tag
   replaces it with what `git rev-parse '<the tag>^{commit}'` prints, and only that commit may move the action step of
   [`.github/workflows/supplier.yml`](.github/workflows/supplier.yml) to it. Until then a supplier who calls
   `supplier.yml` at this release's tag runs the workflow of this release and, inside it, the action at the earlier
   tag's commit the file names: say so if asked which code checked a pull request.

None of these runs is written into this release's commit ("Nothing after the push goes into a commit").

### What can go wrong, and what then

| What | What it means | What to do |
|---|---|---|
| `release.py verify`: the wheel differs from the lock | a file inside the wheel changed after the lock | before `publish`: `release.py wheel`, lock again, then the order again from `publish`. After `publish`: PyPI holds the locked wheel, so undo the change (`git diff`) or release a new version |
| `pinned_workflows.py cutoff`: PyPI does not serve the wheel yet | `publish` has not run, or did not finish | `python scripts/release.py publish`, then `cutoff` again; it wrote nothing |
| `release.py workflows` or `verify`: "Upload the wheel first" | the cutoff was written for an earlier release, so uv would not see this one | `publish`, then `pinned_workflows.py cutoff` |
| `release.py publish`: PyPI has this version with another hash | a different wheel was uploaded earlier | a new version: bump, and the whole order again |
| `release.py publish` ends with "Do NOT push yet" | PyPI's index does not list the wheel yet | do not push; `python scripts/release.py pypi-check --wait 600` until it does |
| `release.yml` build: not the locked wheel | the tagged commit does not build the wheel it names | do not move the tag: fix on main, release a new version |
| `release.yml` pypi: PyPI does not serve the wheel | the push happened before `publish` | run `release.py publish` from the machine that holds `dist/`, then re-run the failed jobs |
| `release.yml` crates-trusted or npm-trusted is red | a package's version is neither the tag's nor the one `bump_version.py` holds it at | fix the version on main and release a new version; a held crate or a package not on its registry is green |
| the worker's first run after the push is red, and no run follows | its install failed, and a failed run starts nothing | "After the push: the worker's chain of runs": start the chain by hand; a re-run does not |
| `upgrade_feed.py --published` exits 1 | the site was built before a proposal was made or executed | `gh workflow run network.yml --repo drexthealpha/Knos --ref main`, then the same command |

## Rollback: taking a release back

What to do, surface by surface, when a release of Knos must be taken back. Everything is on Solana devnet with test
USDC. One person holds every key, account and vote named here today: there is no other maintainer, and outside key
holders today are 0 ([TRUST.md](docs/TRUST.md)).

So "who can run it" is that one maintainer in every row, with the credential the row names.

Rule one: **never move or delete a published tag, and never try to replace a published file.** PyPI and npm refuse a
second upload of a version, and the workflows a commit pins install the package by version and hash.

Taking a release back always means two things: mark the bad version, and publish the previous code as the next
version.

### The surfaces

| surface | fastest safe step | what it does, and what it does not | credential |
|---|---|---|---|
| PyPI (`knos`) | yank the version | installers skip it, except where it is pinned with `==` | PyPI owner of `knos` |
| npm (`knos-settle`) | `npm deprecate` | every install of it warns; it stays installable | npm owner of `knos-settle` |
| crates.io | nothing in this release | the interface crates stay at 0.3.14 on crates.io; this release uploads no crate | crates.io owner |
| git tag and GitHub release | revert on `main`, release the next version | the tag stays; the next tag carries the fix | write access to the repository |
| the site (GitHub Pages) | revert on `main`; the `pages` workflow redeploys | the site is built from `main` only | write access |
| the relay (`worker.yml`) | disable two workflows | Knos's relay stops; anyone can still relay | admin of the repository |
| the programs | guardian pause of new funding | refuses new funding for at most 7 days; payments, refunds and withdrawals go on | 2 of 3 guardian keys |
| the programs, code | an upgrade back to the previous build | waits for the time lock: 8 days (in force since 11 Oct 2026) | 2 of 3 upgrade member keys |

### 1. PyPI: yank

On `https://pypi.org/manage/project/knos/releases/`: **Options** next to the version, **Yank**, and give the reason
(it is shown on the release page and to installers). A yank is not a deletion: installers ignore a yanked release
unless it is the only one that matches a `==` or `===` specifier ([PyPI:
yanking](https://docs.pypi.org/project-management/yanking/), [the file yanking
specification](https://packaging.python.org/en/latest/specifications/file-yanking/)).

So `pip install knos` falls back to the version before, while every workflow that pins `knos==<version>` by hash
keeps installing it. That is wanted: a pinned workflow keeps working until its pin moves.

A file on PyPI can never be replaced (see the release section above), so the fix is the next version:

```
git revert --no-edit <the release commit>              # on main
python scripts/bump_version.py <next version>          # writes the version everywhere
python scripts/bump_version.py --check
python scripts/release.py wheel                        # then the order above ("The commit"): lock, publish,
python scripts/release.py publish                      # cutoff, workflows, stamp; publish needs UV_PUBLISH_TOKEN set
git commit                                             # the one commit, after the cutoff and the stamp
python scripts/release.py pypi-check                   # PyPI's index lists the wheel: only then the push
git push origin main
git tag v<next version> && git push origin v<next version>     # starts release.yml
```

### 2. npm: deprecate

```
npm deprecate knos-settle@<version> "<what is wrong>; use <previous version>"
npm deprecate knos-settle@<version> ""                 # takes the warning back
```

Only an owner of the package can run it, from a machine signed in to npm (`npm whoami` answers with a name); the
release workflow publishes without a stored token and cannot deprecate. A deprecated version stays installable and
warns on install ([npm deprecate](https://docs.npmjs.com/cli/v11/commands/npm-deprecate)).

`npm unpublish` is not the way back: after 72 hours it needs no dependents, fewer than 300 downloads in the last week
and a single owner, and a version number once used can never be used again ([npm unpublish
policy](https://docs.npmjs.com/policies/unpublish/)).

### 3. The git tag, the GitHub release and the site

The tag stays where it is. On the GitHub release of the bad version, untick "Set as the latest release" and say in its
notes which version replaces it. The fix is the revert and the next release (section 1).

Pinned copies of the workflows on the `workflows-<sha12>` tags of `drexthealpha/Knos` move only when a new set is
built and committed there (`python scripts/release.py workflows DIR`, then `stamp SHA`), as the release section above
describes.

The site is built from `main` by `.github/workflows/network.yml` (workflow `pages`) on every push that touches `web/`,
every 30 minutes, and when `release.yml` starts it. A reverted `web/` on `main` is therefore the only change that
sticks; to deploy it at once, run the `pages` workflow by hand (Actions, `pages`, **Run workflow**).

### 4. The relay

There is no pause flag in the relay. Two ways stop Knos's own relay, and either is undone by reversing it:

- **Disable the workflows** `always-on worker` (`worker.yml`) and `relay watchdog` (`watchdog.yml`) on the repository's
  Actions page (**...**, **Disable workflow**). Both must go: the watchdog starts a worker run when none holds the
  chain.
- **Remove the secrets** `KNOS_RELAY_KEY` and `KNOS_WORKER_KEY`. Every relay step then prints "no KNOS_RELAY_KEY
  secret: skipped" and sends nothing. The key file itself stays with the maintainer.

What it does not stop: the relay decides nothing, and anyone can carry a token with `knos relay --token-file` and a
key of their own ([RELAY.md](docs/reference/RELAY.md)). A token posted while the relay is stopped can expire before it is carried;
running the workflow that minted it again gives a fresh one.

### 5. The programs

**Pause new funding** (knos_pay; the guardian multisig, 2 of 3 keys):

```
node scripts/governance.mjs guardian pause 604800      # 7 days, the most one pause allows
node scripts/governance.mjs guardian pause 0           # lifts it
```

While paused, new funding is refused (error 96); payments, refunds, withdrawals and binds go on, and every open order
keeps the terms and the fee stored when it was funded. A pause can be set again when it runs out.

**Upgrade back to the previous build** (the upgrade multisig, 2 of 3 member keys). It waits for the time lock: 8
days on chain, in force since 11 Oct 2026 ([GOVERNANCE.md](docs/reference/GOVERNANCE.md)).
With the 8-day lock, a 7-day pause does not cover the wait by itself: set it again before it ends.

```
python scripts/exercise_public.py status --rpc https://api.devnet.solana.com      # which build runs now, by hash
git checkout <the tag that built the previous version>
bash scripts/drill_upgrade.sh --from-devnet            # rehearse on a local validator first
bash scripts/deploy_v2.sh --propose --replace          # KNOS_CHANGES names the program(s) to take back
node scripts/governance.mjs upgrade execute <index> --expect-hash <build hash>     # after the lock
```

`deploy_v2.sh --propose` waits for the build's record at the upgrade gate; a build made on a release tag has one.
`--ungated` is for an emergency only and says so in the proposal.

Orders funded under the later build keep their stored terms and fee. **Not drilled:** an upgrade back to an older
build of knos_pay; the previous build must read every account the later one wrote, and that is to be shown on a
local validator before it is proposed.

### What is not covered

- The first deployment (`programs/`) has no upgrade authority and no pause: it cannot be taken back.
- The MCP registry listing and the Gemini extension move with the next release; there is no step that withdraws one.
- No drill of this page has been run end to end.
