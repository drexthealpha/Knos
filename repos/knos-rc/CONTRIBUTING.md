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
pytest -q -n auto                          # offline; runs both sets of programs in LiteSVM (a local Solana simulator) and the judge in five languages
node sdk/settle/test.mjs                   # the JavaScript client against the Python client's fixtures
python scripts/deadcode.py && vulture src/knos scripts --min-confidence 60     # nothing unused ships
python scripts/claims_check.py --offline   # every number in the README and on the site has a source
```

The suite refuses every non-loopback connection and gives each test its own home. It runs the real programs, real
git repositories and real test runners rather than mocks. Please keep it that way. The Go and Rust judge tests are
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

## Add a language to the judge

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

[docs/reference/RELEASE.md](docs/reference/RELEASE.md) is the whole order, with every command. In short: build the package once, lock its hash
in `requirements/sign.txt`, publish the pinned workflows, then make one commit, upload the package to PyPI, push, and
tag:

```bash
git tag v0.3.28 && git push origin v0.3.28
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
