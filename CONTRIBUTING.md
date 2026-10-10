# Contributing

Contributions are welcome and unpaid, unless the issue shows a funded order.
A funded order pays test USDC on Solana devnet, which has no monetary value.
Do not post a wallet address for payment: Knos pays only the address a payee binds to a funded order.

Funded work is listed by `knos work list`. An issue with no funded order carries no payment, whatever a comment on it says; the issues labelled `knos-relay` and `knos-memory` and the one titled "knos tokens" are logs a workflow writes, not tasks.

Knos is one product: bounties that pay when the pull request is merged with the checks you named passing, attested by a GitHub-signed workflow run and verified on Solana.
Changes that delete something are the most welcome kind.

## Run the tests

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
pytest -q -n auto                          # offline; includes both deployments' programs in LiteSVM and the judge in five languages
node sdk/settle/test.mjs                   # the JavaScript client against the Python client's fixtures
python scripts/deadcode.py && vulture src/knos scripts --min-confidence 60     # nothing unused ships
python scripts/claims_check.py --offline   # every number in the README, site and submission has a source
```

The suite refuses every non-loopback connection and gives each test its own home. It runs the real programs, real
git repositories and real test runners rather than mocks. Please keep it that way. The Go and Rust judge tests are
skipped when those toolchains are not installed.

## Change a program

There are two deployments. `programs/` is the first: it is on devnet with no upgrade authority, so its source must
stay byte for byte what was deployed. Do not change it. `programs-v2/` is the second, where every new bounty is
funded. It is upgradeable only through a multisig with a public 48-hour delay, until an outside review, so a change
there reaches devnet as an upgrade, two days after it is approved in public.

```bash
bash scripts/build_programs_v2.sh          # needs cargo build-sbf; refreshes tests/fixtures/*_v2_*.so and their pins
cd programs-v2 && cargo test --release     # the Wycheproof vectors and the programs' unit tests
pytest -q -s tests/test_oidc2_chain.py tests/test_pay2_chain.py            # prints the compute units of each step
KNOS_FUZZ_N=2500 KNOS_FUZZ_SEED=1 pytest -q -s tests/test_pay2_chain.py -k random_walk    # a seed repeats a walk
python scripts/settle_fixtures.py          # if an address, an audience or an instruction changed
python scripts/bench_docs.py               # if a measured number changed: docs/bench.json first, then this
```

A change to an instruction's bytes must change the module documentation at the top of the program, then
`src/knos/settle/v2` (the client the tests use), then `idl/` and `sdk/settle/index.js`; the fixtures and
`tests/test_idl.py` will tell you whether they still agree. `scripts/build_programs.sh` rebuilds the first
deployment's test binaries from its unchanged source.

## Add a language to the judge

`src/knos/judge.py`: a runner is one function that takes a sandbox `Box` and returns a `Run` (test ids and states,
which ids are the acceptance checks, and the sentinel and canary ids). Add its test directories and protected paths
beside the others, and a test in `tests/test_judge_langs.py` with an honest fix, a no-op and a cheat.

## A good pull request

- One thing, with a test that fails before it and passes after.
- If its description says tests pass, they pass: this repository runs its own check on pull requests.
- No number in the README, the site or `docs/submission/` without an entry in `docs/facts.json`.

Some issues carry a bounty (`/knos fund` by a maintainer). Knos's reply on the issue states its terms: the checks
that must pass and the files a pull request may change. The pull request that is merged for it and meets those
terms is paid on devnet, in test USDC, to the wallet you bound to your GitHub account (by hand on GitHub, or with `knos claim <address>`; an address in a
link could be someone else's, so none is ever put in one) or named on the pull request (`/knos address <address>`). With neither, the payment is held for you for 180 days.
`/knos take` on the issue reserves it for you.

## Release

[docs/RELEASE.md](docs/RELEASE.md) is the whole order, with every command. In short: the wheel is built once from the
final tree, its hash is locked in `requirements/sign.txt`, the pinned workflows are published with that lock, their
commit is stamped into the tree, and then there is one commit, the wheel goes to PyPI, one push, and the tag:

```bash
git tag v0.3.26 && git push origin v0.3.26
```

`.github/workflows/release.yml` then runs the whole test workflow on that commit and, only when every job of it has
passed, builds the wheel again and holds it to the locked hash, checks that PyPI serves exactly that file (it uploads
nothing there), creates the GitHub release with the npm tarball, lists `knos mcp` in the MCP registry, attaches the
Gemini CLI extension, publishes to crates.io and npm when their tokens are set, and rebuilds the site. Every one of
those jobs needs the test job of the same run, so tagging early only starts the tests earlier, and a commit whose
tests fail publishes nothing. A job added to that workflow must need `tests` too (`tests/test_release_gate.py` fails
if one does not).

## Licence

MIT. By contributing you agree your contribution is under the same licence.
