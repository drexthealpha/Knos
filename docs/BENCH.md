# Measurements

Every number Knos states about itself, with the command that reproduces it. Nothing here is modelled. A row that
says "measured at release" has not been measured yet, and no estimate stands in for it.

The text between `<!-- bench:... -->` marks is written by `python scripts/bench_docs.py` from
[`bench.json`](bench.json) and [`backtest.json`](backtest.json); `tests/test_bench_docs.py` fails when a block and
its source differ.

## How often agents say "tests pass" when a check failed

<!-- bench:market -->
**Agent PR Index, 2026-10-02:** in 826 repositories, the first pull request by an AI coding agent whose description said tests or CI pass had **a failed check of any kind in 147 (17.8%)** (95% Wilson interval 15.3%–20.6%). Counting every such pull request instead of one per repository, it is 660 of 2,431 (27.1%); that figure leans on a few busy repositories, so the per-repository one is the one to quote. Pull requests created 2026-06-04 – 2026-10-01 whose CI had finished at the head commit; 9,207 on repositories owned by the pull request's author or the person who assigned the agent were left out. A failed check is GitHub's record, not a judgment of why it failed. The list is published as `index.json` on the Pages site. A new scan is scheduled every 6 hours (`.github/workflows/index.yml`) and replaces the published list only when it has finished, so the date above says which scan these numbers are from.

| agent | repositories | first claiming PR: any check failed | 95% interval | all claiming PRs | any check failed |
|---|---|---|---|---|---|
| GitHub Copilot coding agent | 341 | 85 (24.9%) | 20.6%–29.8% | 787 | 194 (24.7%) |
| Devin | 78 | 13 (16.7%) | 10.0%–26.5% | 520 | 270 (51.9%) |
| Claude GitHub app | 182 | 17 (9.3%) | 5.9%–14.4% | 716 | 68 (9.5%) |
| Claude Code | 191 | 17 (8.9%) | 5.6%–13.8% | 206 | 17 (8.3%) |
| OpenAI Codex | 40 | 17 (42.5%) | 28.5%–57.8% | 202 | 111 (55.0%) |
| **all** | **826** | **147 (17.8%)** | **15.3%–20.6%** | 2,431 | 660 (27.1%) |
<!-- /bench:market -->

<!-- bench:market-tests -->
**Counting only failed tests and builds:** a failed check is not always a failed test. In **80 of the 826 repositories (9.7%)** (95% Wilson interval 7.9%–11.9%) one of the failed checks was, by its name, a test, build, lint or type-check job. In the other 67 of the 147 no failed check had such a name: deploy previews, title and label gates, review bots, coverage thresholds, security scanners, and jobs whose names do not say what they run (`check`, `validate`). Over every pull request it is 440 of 2,431 (18.1%). So "said tests pass while a check failed" is 17.8% of repositories, and "while a test or build check failed" is 9.7%; names decide the second, so read it as the cautious figure, not an exact one.

| agent | repositories | any check failed | a test or build check failed | 95% interval | all claiming PRs | a test or build check failed |
|---|---|---|---|---|---|---|
| GitHub Copilot coding agent | 341 | 85 (24.9%) | 46 (13.5%) | 10.3%–17.5% | 787 | 98 (12.5%) |
| Devin | 78 | 13 (16.7%) | 8 (10.3%) | 5.3%–19.0% | 520 | 229 (44.0%) |
| Claude GitHub app | 182 | 17 (9.3%) | 6 (3.3%) | 1.5%–7.0% | 716 | 19 (2.7%) |
| Claude Code | 191 | 17 (8.9%) | 6 (3.1%) | 1.4%–6.7% | 206 | 6 (2.9%) |
| OpenAI Codex | 40 | 17 (42.5%) | 15 (37.5%) | 24.2%–53.0% | 202 | 88 (43.6%) |
| **all** | **826** | 147 (17.8%) | **80 (9.7%)** | **7.9%–11.9%** | 2,431 | 440 (18.1%) |
<!-- /bench:market-tests -->

Method: `scripts/agent_pr_ci.py` (the claim patterns and the CI verdict) and `scripts/agent_pr_index.py` (the scan and
the index). A pull request counts only if its description claims tests or CI pass and its CI had finished at the head
commit. Pull requests on repositories owned by the author, or by the person who assigned the agent, are left out: a
person's own repository is not a market observation. The agent's own session check runs are not counted as CI. A
failed check is a check run that concluded `failure`, `timed_out` or `startup_failure`, or a commit status of
`failure` or `error`. Whether a failed check is a test or a build is decided from its name (`TESTISH_RE` and
`ANCILLARY_RE` in `scripts/agent_pr_ci.py`), on the failed check names each record lists (at most ten). `index.json`
publishes both counts under names that say which is which, `any_check_failed` and `test_or_build_check_failed`, with
their definitions in the file. The published list has a Merkle root; `python scripts/agent_pr_index.py check --out
index.json` recomputes it, and `python scripts/bench_docs.py --from index.json` recounts the tables above from the
list. The first, smaller sample (303 pull requests, 55 with a failed check, 18.2%, collected 1 Oct 2026) is kept in
`docs/agent_pr_ci.json`.

What this does not show: that the agents lied. A description can be written before CI finishes. It shows that the
description is not evidence.

### Merged anyway

`python scripts/backtest.py --index index.json` writes `docs/backtest.json`.

<!-- bench:backtest -->
Of the 303 pull requests in the sample read on 2026-10-01 (created 2026-07-03 – 2026-09-30; `docs/agent_pr_ci.json`) whose description said tests or CI pass and whose CI had finished, 241 had been merged. **30 of those 241 (12.4%)** (95% Wilson interval 8.9%–17.2%) had a failed check at the head commit. A Knos bounty whose terms required that check would not have paid the merge. In 16 of them (6.6% of the merged) a failed check was a test or a build by its name. 6 more had no failed check but a cancelled one, which a bounty that required it counts as failed. Without the repositories the pull request's author owns it is 29 of 199 (14.6%). A pull request with a failed check was merged less often than one without: 30 of 55 (54.5%) against 211 of 248 (85.1%); 12 and 21 were still open when read.

| agent | merged | any check failed | 95% interval | a test or build check failed |
|---|---|---|---|---|
| GitHub Copilot coding agent | 44 | 15 (34.1%) | 21.9%–48.9% | 7 (15.9%) |
| Devin | 43 | 5 (11.6%) | 5.1%–24.5% | 3 (7.0%) |
| Claude GitHub app | 85 | 5 (5.9%) | 2.5%–13.0% | 3 (3.5%) |
| Claude Code | 22 | 2 (9.1%) | 2.5%–27.8% | 0 (0.0%) |
| OpenAI Codex | 47 | 3 (6.4%) | 2.2%–17.2% | 3 (6.4%) |
| **all** | 241 | 30 (12.4%) | 8.9%–17.2% | 16 (6.6%) |

What this cannot show:

- How long pull requests stayed open: docs/agent_pr_ci.json records when each was created and whether it was open, closed or merged when it was read, not when it was closed or merged, and index.json records neither. `backtest.py fetch` reads those times from GitHub.
- The merges of the whole index: index.json lists no merge state. It is known for 72 of its 2,431 pull requests (docs/agent_pr_ci.json, for the pull requests in both).
- Whether the check was failing at the moment of the merge: CI was read at the head commit on the day of the scan. A check re-run later shows its last result, and a check can fail after a merge.
- Why a check failed, or whether the maintainer saw it: a failed check is GitHub's record, not a judgment. any_check_failed counts deploy previews and label gates; test_or_build_check_failed is decided from check names.
- Agent pull requests in general: these are pull requests whose description claims tests or CI pass, the newest per agent and date window that GitHub's search returned, not a random sample.
- What a bounty would have changed: none of these pull requests had one, so which checks its terms would have required is not known. This counts merges with a failed check, not payments refused.
<!-- /bench:backtest -->

<!-- backtest_paid:begin -->
### Paid elsewhere, and a check had failed

`python scripts/backtest_paid.py` (with a GitHub token) writes `docs/backtest_paid.json`: of the merged pull requests that were paid a bounty on Algora or Opire (labels and commands: [Algora](https://remotion.dev/bounties), [Opire](https://github.com/abdulmajeedsualihu/Autokey/issues/1)), how many had a failed check at the commit that was merged.

Read 2026-10-04: 48 closed bounty issues created 2026-01-08 – 2026-10-04, 41 merged pull requests linked from them, 17 of them paid by the platform's own account of it (24 had no such comment and are left out). **At the head commit, 4 of 15 (26.7%) had a failed check** (95% Wilson interval 10.9%–51.9%). At the commit the merge made: 5 of 16 (31.2%, 14.2%–55.6%). At either: 7 of 15 (46.7%, 24.8%–69.9%).

| platform | issues | merged pull requests | paid | classified at the head | failed at the head |
|---|---|---|---|---|---|
| Algora | 47 | 40 | 17 | 15 | 4 |
| Opire | 1 | 1 | 0 | 0 | 0 |

What this cannot show:

- How a platform marks a PAID bounty: neither platform documents what its bot writes on GitHub when it pays. `paid` is the rule in DEFINITIONS; a bounty paid without a bot comment is counted as `unpaid`
- Money: no amount is read. A comment can say paid for a tip, and a bounty can be paid in parts
- Whether the check was failing when the maintainer merged: CI is read as it is on the day of the run. A check re-run later shows its last result, and a check can fail after a merge (`failed_at_merge`)
- Which checks a Knos bounty on these issues would have required: none of them had one. This counts merges with a failed check, not payments refused
- Bounties in general: these are the newest closed issues per window that GitHub's search returned for the platform's label (and, for Opire, text), not a random sample, and only public repositories
<!-- backtest_paid:end -->

## The verifier on chain (knos-oidc)

Both deployments verify a token the same way: the token is written into an account, then its RSA signature is
checked in steps, each step in a transaction of its own (two do not fit in one). An RSA-2048 key (all four of
GitHub's) takes two steps of 8 squarings. An RSA-4096 key (one of GitLab's three) takes six, of 2, 3, 3, 3, 4 and 1
squarings: the last step also hashes the token, decodes it and reads its claims, work that grows with the token, so
it gets one squaring (`step_plan` in [`src/knos/settle/oidc.py`](../src/knos/settle/oidc.py)).

### Second deployment (`programs-v2`)

`pytest -q -s tests/test_oidc2_chain.py` prints these, in LiteSVM, against the test build of this source. A test
build differs from the build that is deployed in the keys and pins it trusts, not in its arithmetic.

<!-- bench:verify2 -->
| token | key | transactions | compute units of each |
|---|---|---|---|
| 1,893 bytes, a GitHub token as the tests make it, with a payment's audience | RSA-2048 | 2 | 763,497 and 839,351 |
| 3,500 bytes | RSA-2048 | 2 | 773,798 and 919,995 |
| 8,192 bytes, the longest the program takes | RSA-2048 | 2 | 802,003 and 1,153,122 |
| 2,237 bytes, a GitLab token as the tests make it | RSA-4096 | 6 | 913,936 to 1,200,547 |
| 3,499 bytes | RSA-4096 | 6 | 921,492 to 1,209,190 |
| 8,191 bytes, the longest under RSA-4096 | RSA-4096 | 6 | 951,036 to 1,235,926 |
| 8,189 bytes, the costliest claims we could build | RSA-4096 | 6 | 949,843 to 1,285,266 |

The limit is 1,400,000 compute units per transaction; the costliest step here leaves 114,734. Each figure is for a token account whose address the program finds at its first try, and is the lowest of 9 runs of the tests. Every further try costs 1,500 more in each step: about half of all tokens need none, a quarter need one. Measured on 3 Oct 2026 with the committed test builds in `tests/fixtures` (`knos_oidc_v2_test.so`, `knos_pay_v2_test.so`), made by cargo build-sbf 3.0.0 (platform-tools v1.51).

The key instructions are small next to a verification: Refresh 21,022, Approve 773, Revoke 767.
<!-- /bench:verify2 -->

The compiler matters. The committed test builds were made with cargo build-sbf 3.0.0. CI
(`.github/workflows/program.yml`) builds the programs again with agave 2.3.13 before it runs the same tests, and
prints its own figures in every run. The binaries that are deployed are a third build, the reproducible one
(`solana-verify`, image 2.3.11). Another compiler spends another number of compute units, so the figures above are
not the deployed build's. What holds for every build is what the tests assert: each step of each token here
verifies, which it cannot do above the limit.

### First deployment (`programs`)

`pytest -q -s tests/test_oidc_chain.py tests/test_oidc_gate.py`.

<!-- bench:verify1 -->
| token | key | transactions | compute units of each |
|---|---|---|---|
| 1,734 bytes, a GitHub token as the tests make it | RSA-2048 | 2 | 778,986 and 848,363 |
| 4,092 bytes, with the longest names GitHub allows | RSA-2048 | 2 | 794,939 and 970,506 |
| 8,192 bytes, the longest the program takes | RSA-2048 | 2 | 824,403 and 1,209,372 |
| 1,421 bytes, a GitLab token as the tests make it | RSA-4096 | 6 | 912,854 to 1,199,524 |
| 8,191 bytes, the longest under RSA-4096 | RSA-4096 | 6 | 959,960 to 1,278,017 |
| 8,189 bytes, the costliest claims we could build | RSA-4096 | 6 | 960,222 to 1,350,931 |
| another program reads a verified token (`examples/oidc_gate`) | | part of its own | 21,632 |

The limit is 1,400,000 compute units per transaction; the costliest step here leaves 49,069. Each figure is for a token account whose address the program finds at its first try, and is the lowest of 8 runs of the tests. Every further try costs 1,500 more in each step: about half of all tokens need none, a quarter need one. Measured on 3 Oct 2026 with the committed test build in `tests/fixtures` (`knos_oidc_test.so`).
<!-- /bench:verify1 -->

**A correction to 0.3.11.** That release's client sent the six RSA-4096 steps as 2, 3, 3, 3, 3 and 2 squarings. With
two squarings the last step ran out of compute units once a GitLab token passed about 5,000 bytes: in the test it
fits at 4,499 bytes, where the last step takes 1,374,044, and fails at 5,499. 0.3.11's table had one RSA-4096 row,
for a short token, while its limits said tokens up to 8,192 bytes are accepted; under RSA-4096 the client of that
release could not verify the long ones. The plan is the client's choice, not the program's, so the first deployment
is unchanged and every size verifies with the plan above
(`test_the_4096_bit_plan_fits_a_token_of_any_size_and_the_old_plan_ran_out`).

## Correctness of the RSA arithmetic

The two deployments share `rsa.rs` byte for byte, and each is tested on its own. `claims.rs` differs since 0.3.13:
the second deployment's reader sees a second copy of a claim under an escaped spelling of its name, and the first
deployment's cannot be changed.

- **Wycheproof** (Google's test vectors for RSA PKCS#1 v1.5 signatures, SHA-256), run against the program's own
  arithmetic by `cargo test --release` in `programs/knos_oidc` and in `programs-v2`: 517 vectors, for 2048- and
  4096-bit keys. All 14 valid signatures verify; all 499 invalid ones are refused; the 2 marked "acceptable" are
  refused; 2 use a public exponent other than 65537, which the program does not support, and are skipped.
- **Differential test against OpenSSL** (`test_the_chain_agrees_with_a_reference_rsa_library_on_random_tokens`, in
  `tests/test_oidc_chain.py` and `tests/test_oidc2_chain.py`): 60 random tokens, each also with one random bit
  flipped in its payload or signature. The program and OpenSSL (through `cryptography`) agree on all 120.
- **Forgeries** (`test_every_forgery_is_refused`, in both files): claims or signature changed after signing; signed
  by another key; `alg` set to HS256 or none; another issuer or a look-alike issuer; `iss` given twice; `exp`
  missing or a string; a payload that is not one JSON object; a fourth part; a short signature; a signature of 0,
  1, the modulus or more. Each is refused with the error it should get.

What each of these can show. The vectors show that the arithmetic and the padding check agree with a published set
of hard cases. The differential test shows agreement with another implementation on random inputs. The forgery list
shows that the cases someone thought of are refused. None of them shows the absence of a fault nobody thought of.
This is testing, not an outside review. There has been none; `knos mainnet-check` fails on that line on purpose.

## The escrow (knos-pay)

### Second deployment (`programs-v2`)

`pytest -q -s tests/test_pay2_chain.py` prints one run's figures.

<!-- bench:pay2 -->
| instruction | lowest | median | highest |
|---|---|---|---|
| Pay, a later payment from the same funder | 62,138 | 66,912 | 80,406 |
| Pay, the payee's first payment (creates their record and the funder's marker) | 74,389 | 79,163 | 92,657 |
| Pay, a Token-2022 mint with the stablecoins' extensions, first payment from this funder | 75,098 | 79,855 | 94,858 |
| Pay with no wallet known (the bounty is held) | 34,010 | 34,010 | 41,510 |

Compute units of knos-pay, the token program's share included, over 320 payments of each kind: the test file run 20 times, each run on a fresh chain with 16 payments of each kind (3 Oct 2026). A payment to a wallet took 62,138 to 94,858. The spread is not noise: Pay derives the addresses it pays through (the payee's binding and record, the funder's marker, the vault and its authority), and each costs 1,500 for every try after the first.

The other instructions, highest seen in those 20 runs: FundBalance 93,329; FaucetOpen 50,545; FaucetOpen and FundBalance in one transaction 141,002; FundWallet 61,568; Settle 42,490; Settle with a Token-2022 mint 61,270; Refund 22,288; Bind 49,737; Withdraw 22,792; Withdraw with a Token-2022 mint 27,722; OpenBalance 32,646; OpenBalance with a Token-2022 mint 45,524; SetBalance 2,495; Pause 10,748; InitFaucet 18,136.
<!-- /bench:pay2 -->

**Random walk** (`KNOS_FUZZ_N=2500 KNOS_FUZZ_SEED=<seed> pytest -q -s tests/test_pay2_chain.py -k random_walk`; 600
steps in the default suite; four walks of 2,500 in `program.yml` on every change and nightly, each from a seed of its
own): random funding from balances and from wallets, pay tokens, wrong pay tokens, settles, binds, refunds, withdrawals,
top-ups and clock jumps, in an SPL Token mint and a Token-2022 mint. After every step, for each mint, the vault holds
exactly the amounts of the open and held jobs. At the end every job that is left is refunded with no token, and both
vaults are empty: funded = paid + fees + refunded. A failure prints its seed and step.

<!-- bench:walk2 -->
Last runs (3 Oct 2026): 4 walks of 2,500 steps, seeds 1, 2, 3 and 4, 10,000 steps in all: 0 violations. Funded 248,917, paid 203,117.85, fees 5,218.15, refunded 40,581: every token that entered left by one of the three.
<!-- /bench:walk2 -->

### First deployment (`programs`)

`pytest -q -s tests/test_pay_chain.py`.

<!-- bench:pay1 -->
| instruction | lowest | highest |
|---|---|---|
| Pay (check the token's claims against the job, credit the author, take the fee, close the job) | 55,332 | 61,332 |
| Claim | 37,990 | 44,247 |

Compute units, over 11 runs of one payment and one claim each (3 Oct 2026).
<!-- /bench:pay1 -->

**Random walk** (`KNOS_FUZZ_N=10000 KNOS_FUZZ_SEED=<seed> pytest -q -s tests/test_pay_chain.py -k random_walk`):
random funds, pay tokens, wrong pay tokens, settles, vetoes, refunds, claims and clock jumps. After every step the vault
holds exactly what the open jobs and the unclaimed payments add up to.

<!-- bench:walk1 -->
Last 10,000-step run: 0 violations. Seed 1, 3 Oct 2026: funded 129,783.00, claimed 31,808.83, fees 817.30, refunded 91,244.00; the rest was still in the vault, in open jobs and in money not yet claimed, when the walk ended.
<!-- /bench:walk1 -->

## What a relayer pays

A relayer carries a GitHub-signed token to the chain and pays the transaction fees. It decides nothing.

**First deployment**, measured with a 2,100-byte token (`tests/test_settle_relay.py` drives the same path). Its
relay sends every instruction in a transaction of its own. The real GitHub Actions tokens we captured were 2,086 to
2,276 bytes, so writing one takes 3 transactions of 880 bytes each:

| step | transactions | fees (lamports) | rent the relayer puts up |
|---|---|---|---|
| fund (a maintainer's comment) | 7 | 35,000 | the job account, 2,672,640, returned when the job is paid or refunded; once per repository, 1,002,240 for its rate account; once per mint ever, 2,039,280 for the vault |
| pay (a merge) | 7 | 35,000 | once per payee, 1,113,600 for their public record; 1,224,960 for their balance account, returned at their claim |
| claim | 7 | 35,000 | once per address, 2,039,280 for the claimer's token account |

So a bounty to someone who had been paid before, in a repository that had funded before, cost a relayer 105,000
lamports (0.000105 SOL) end to end. A first payout to a new person cost about 3,150,000 more, once. The rent
figures are the local test chain's; [MARKET.md](MARKET.md), section 2, has today's lower ones.

**Second deployment.** A bounty or a work order is two tokens, not three: the payment goes straight to a wallet, so
there is no claim. A person who gives no address binds a wallet once, with a third token.

**Two transactions per token.** Measured in LiteSVM on 3 Oct 2026, with the test builds
(`pytest -q -s tests/test_relay2.py -k transactions_waits`). Where the cluster takes 4,096-byte transactions and
`knos-pay` 2.1 answers, the relay sends a token in two: the whole token and the first `Step`, then the last `Step`,
the escrow's instruction and `Close`. Not measured on devnet: no 2.1 instruction had run there when this was written.

| path | transactions | compute units in all | in the larger transaction |
|---|---|---|---|
| verify only (a token of about 1,700 bytes) | 2 | 1,604,287 | 832,908 |
| fund from a Balance | 2 | 1,731,410 | 953,065 |
| fund, the faucet opened on the way | 2 | 1,829,533 | 1,055,590 |
| pay to the address in the token | 2 | 1,756,951 | 984,107 |
| pay to a bound wallet | 2 | 1,762,494 | 978,217 |
| pay held (no wallet known) | 2 | 1,686,257 | 914,487 |
| bind a wallet | 2 | 1,694,279 | 917,050 |
| bind, then settle the held bounty | 2 | 1,755,820 | 983,875 |
| a key registered | 2 | 1,795,076 | 1,017,282 |
| a key refreshed | 2 | 1,644,634 | 872,027 |
| refund of an unpaid bounty (no token) | 1 | 19,294 | 19,294 |
| settle of a held bounty (no token) | 1 | 60,809 | 60,809 |

The figures move by a few thousand with the addresses involved. Where 4,096-byte transactions are not accepted the
relay falls back to 1,232-byte ones: a token of up to 1,756 bytes then takes three transactions, and the real
GitHub tokens we captured (2,086 to 2,276 bytes) take four, two of them sent side by side
(`tests/test_relay2.py::test_how_long_a_token_each_write_carries`). The first deployment's relay takes 7 for a fund
or a pay token and 6 for a claim, in the same test file.

**Work orders** (`pytest -q -s tests/test_order_chain.py -k compute_units`, one run, 3 Oct 2026): `FundOrderWallet`
50,868 compute units. `PayOrder` to one payee whose token account it creates: 152,374, in a transaction of 807
bytes. To four such payees: 345,997, in 1,401 bytes, which is more than a 1,232-byte transaction holds. The test
requires every one to stay under 400,000.

**What a payment pays the relayer.** `PayOrder` sends the relayer 0.05 of the mint out of the fee, or 0.30 when the
transaction created a payee's token account (`TIP`, `TIP_FIRST` in `programs-v2/knos_pay/src/lib.rs`). A 0.3.12
bounty pays the relayer nothing.

**Marker rent comes back.** A token that works once leaves a marker account, and the relayer puts up its rent.
`CloseMarker` returns it to whoever paid, once no token the marker stands for can be accepted
(`tests/test_order_terms.py::test_a_used_marker_is_closed_once_no_token_it_stands_for_can_be_accepted`).

**The meter** (`pytest -q -s tests/test_meter_chain.py -k what_a_relayer_pays`, 3 Oct 2026): one billable
evaluation is the transactions that verify the token and one `Record` of 609 bytes and 81,357 compute units. Its
marker is 88 bytes. The simulator held 1,503,360 lamports of the relayer's rent for it; at 5,080 lamports a byte,
the rate [MARKET.md](MARKET.md) cites for a cluster, that is 1,097,280 (computed, not measured). It is locked
until two hours into the next month and then returned in full by `CloseMark` (1,710 compute units each, 26 to a
transaction).

**The passkey wallet.** `tests/test_passkey_chain.py` requires a withdrawal to stay under 40,000 compute units of
`knos-passkey`. Two withdrawals read from that test's chain on 3 Oct 2026 used 14,121 (in one transaction with
`Open` and the destination's token account, 920 bytes) and 14,116 (alone, 774 bytes). The signature itself is
checked by Solana's secp256r1 instruction, outside that count.

A token that is refused costs nothing when a read can tell, which is the usual case: a relay reads the chain before
it spends a fee (`precheck` in [`src/knos/settle/relay.py`](../src/knos/settle/relay.py)). It pays fees for a
refused token only when it takes the signature check on chain to tell. The token account's rent always comes back.

## Measured on devnet

<!-- bench:devnet -->
| the second deployment on devnet | measured |
|---|---|
| tasks funded | 49 |
| tasks paid | 40 |
| tasks funded with their own tokens by someone other than Knos, both deployments | 0 |
| of those, paid to someone other than the funder | 0 |
| funders among them | 0 |
| funders who funded again after one of their tasks was paid | 0 |
| payments timed from the merge, over the public relay's log | 36 |
| seconds from the merge to the payment, median | 24 |
| seconds from the merge to the payment, 90th percentile | 54 |
| seconds from the funding comment to the funded task, median | 48 |

Read from the site's `stats.json` of 2026-10-04 07:51 UTC (`python scripts/bench_docs.py --stats stats.json`).
<!-- /bench:devnet -->

The site's [Numbers section](https://drexthealpha.github.io/Knos/#network) shows today's count, read from the
escrows' own logs, with Knos's own accounts kept apart from everyone else's.

### First deployment

<!-- bench:devnet1 -->
Read from the escrow's own logs on devnet on 3 Oct 2026: 23 transactions in all, the last at 14:19 UTC on 2 Oct 2026. 11 bounties funded, 6 paid, 1 vetoed, 2 claims, 0 refunded, 5 still open. Every one of the 6 payments was Knos's own account paying itself to prove the path; 0 went to anyone else. The median from the funding transaction to the paying one was 159 seconds. 3 of the open bounties are the ones another account's pull requests answer (issues #29, #30 and #31 of this repository, 25, 10 and 15 test USDC; pull requests #32, #33 and #34); they had not been merged when this was read.
<!-- /bench:devnet1 -->

That block is the reading before the three pull requests were merged. They were merged later on 3 Oct 2026 and the
first deployment paid them (`release.outside_prs_merged_and_paid` in [`bench.json`](bench.json)); with those, the two
deployments had made 15 payments when their logs were read at 16:04 UTC that day ([COMPARE.md](COMPARE.md)).

Both programs of the first deployment had no upgrade authority when their program data was read on 3 Oct 2026.
`python scripts/claims_check.py` reads it again.

The first devnet run also found what the local chain could not: a transaction gets 200,000 compute units unless it
asks for more, and the local test chain did not enforce that. Every transaction the relay sends now asks for the
limit it needs (`src/knos/chain.py`).

## The judge

- **Tamper benchmark**: [TAMPER.md](TAMPER.md), regenerated by `python scripts/tamper_bench.py`: 21 cheating pull
  requests against three judges, in each of three sample repositories (Python, JavaScript and Ruby).
- **Languages**: `tests/test_judge_langs.py` judges an honest fix, a no-op and a cheat in Node, Go, Rust and Ruby
  repositories, with a plain command, and with the black-box check. The Python runner is the tamper benchmark's
  first sample.
- **Sandbox**: the same file runs a pull request whose code tries to overwrite the judge's output file from inside
  the sandbox. It cannot, and an honest fix still passes. On a machine with no sandbox, a judge told to require one
  refuses to run.

## The suite

`pytest -q` (offline; the tests refuse every non-loopback connection). `node sdk/settle/test.mjs` checks the
JavaScript client against the Python client byte for byte. `node tests/web/site.mjs <site>` drives the built site in
headless Chromium against a mocked GitHub and Solana.
