# Measurements

Every number Knos states about itself, with the command that reproduces it. Nothing here is modelled. A row that
says "measured at release" has not been measured yet, and no estimate stands in for it.

The text between `<!-- bench:... -->` marks is written by `python scripts/bench_docs.py` from
[`bench.json`](bench.json) and [`backtest.json`](backtest.json); `tests/test_bench_docs.py` fails when a block and
its source differ.

## How often agents say "tests pass" when a check failed

<!-- bench:market -->
**Agent PR Index, 2026-10-02:** in 826 repositories, the first pull request by an AI coding agent whose description said tests or CI pass had **a failed check of any kind in 147 (17.8%)** (95% Wilson interval 15.3%–20.6%). Counting every such pull request instead of one per repository, it is 660 of 2,431 (27.1%); that figure leans on a few busy repositories, so the per-repository one is the one to quote. Pull requests created 2026-06-04 – 2026-10-01 whose CI had finished at the head commit; 9,207 on repositories owned by the pull request's author or the person who assigned the agent were left out. A failed check is GitHub's record, not a judgment of why it failed. The list is published as `index.json` on the Pages site. A new scan is scheduled every 6 hours (`.github/workflows/index.yml`) and replaces the published list only when it has finished, so the date above says which scan these numbers are from.

| agent | repositories | first claiming PR per repository: any check failed | 95% interval | every claiming PR | every claiming PR: any check failed |
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

| agent | repositories | first claiming PR per repository: any check failed | first claiming PR per repository: a test or build check failed | 95% interval | every claiming PR | every claiming PR: a test or build check failed |
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
| tasks funded | 55 |
| tasks paid | 46 |
| tasks funded with their own tokens by someone other than Knos, both deployments | 0 |
| of those, paid to someone other than the funder | 0 |
| funders among them | 0 |
| funders who funded again after one of their tasks was paid | 0 |
| repositories that are not Knos's in which an outside funder funded a task (scripts/outsiders.py) | 0 |
| accounts and wallets that are not Knos's, paid by a task somebody else funded (scripts/outsiders.py) | 1 |
| payments timed from the merge, over the public relay's log (n) | 42 |
| seconds from the merge to the payment, median (p50) | 25 |
| seconds from the merge to the payment, 95th percentile (p95) | 58 |
| the day of the oldest of those payments (UTC) | 2026-10-02 |
| the day of the newest | 2026-10-06 |
| of those payments, made by the first deployment's escrow | 2 |
| of those payments, made by the second deployment's escrow | 40 |
| seconds from the funding comment to the funded task, median | 45 |

Merge to paid is defined as: seconds from the merge (GitHub's merged_at of the pull request) to the block time of the Solana transaction that paid, one sample per successful pay line of the public relay log, over its newest 500 such lines, both deployments, all time. A line is left out when the chain's history that was read does not show its transaction or GitHub does not give the merge time; `not_timed` counts those. p50 is the median, p95 and p90 are by nearest rank. One function measures it (`measure` in `scripts/network_stats.py`); this table, `docs/facts.json`, the site's Numbers page (`stats.json`) and `latency.json` all state that function's output.

Read from the site's `stats.json` of 2026-10-07 00:56 UTC (`python scripts/bench_docs.py --stats stats.json`).
<!-- /bench:devnet -->

The site's [Numbers section](https://drexthealpha.github.io/Knos/#network) shows today's count, read from the
escrows' own logs, with Knos's own accounts kept apart from everyone else's.

### First deployment

<!-- bench:devnet1 -->
Read from the escrow's own logs on devnet on 3 Oct 2026: 23 transactions in all, the last at 14:19 UTC on 2 Oct 2026. 11 bounties funded, 6 paid, 1 vetoed, 2 claims, 0 refunded, 5 still open. Every one of the 6 payments was Knos's own account paying itself to prove the path; 0 went to anyone else. The median from the funding transaction to the paying one was 159 seconds over those 6 payments (the first deployment's public program ids, knos_pay `9UzPFbh2A4e4sEPgngKG523FfYLnQ3qPfFVfFTTAdfDi` and knos_oidc `vpWym9azbPU5f2PH2a6n8c4RfmsyUeW2dMuWr1DSHcE`, programs/program_ids.json; read 3 Oct 2026). 3 of the open bounties are the ones another account's pull requests answer (issues #29, #30 and #31 of this repository, 25, 10 and 15 test USDC; pull requests #32, #33 and #34); they had not been merged when this was read.
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

## Decision time

`knos decide` answers accepted, rejected or insufficient evidence the moment the forge's signed token is in hand, by the reads a relay makes before it spends a fee (`knos.settle.v2.relay.precheck`), and writes a provisional receipt. A provisional receipt never authorises payment; the final receipt names it and replaces it ([LOAD.md](LOAD.md), "The five clocks").

<!-- decide:time -->
Measured on 2026-10-07 by `python scripts/decide_bench.py --write` on this machine: Intel(R) Core(TM) i3-10110U CPU @ 2.10GHz, 4 CPUs, Linux x86_64, Python 3.12.3; load average 2.4 when it began (other work shared the machine when that is near or above its CPUs, and every figure is then slower than on an idle one). The chain is LiteSVM with the committed test builds, in the same process: no network. On devnet, four runs of the 0.3.18 command (the relay's whole precheck, on real fund tokens over the shared public RPC) took 4.3 to 32.6 s: a first reading, not a sample. The 0.3.19 split was timed there on 24 real tokens: the tables after this block.

| decision | what is timed | n | p50 | p95 | slowest | every sample said | target at p95 (a target, not a measurement) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fresh, accepted | a fund token never seen: signature checked, chain read | 40 | 3.0 ms | 5.1 ms | 67.4 ms | accepted | under 2000 ms |
| fresh, rejected | a pay token for an issue with nothing in escrow: signature checked, chain read | 40 | 1.7 ms | 3.9 ms | 5.8 ms | rejected | under 2000 ms |
| cached, accepted | the same fund token again, the chain's answers kept (`knos.decide.Cached`) | 40 | 2.5 ms | 4.0 ms | 5.3 ms | accepted | under 200 ms |
| no chain | the token alone, `ledger=None`: insufficient evidence, or rejected | 40 | 1.1 ms | 1.8 ms | 2.6 ms | insufficient evidence | under 200 ms |
| free check | the conclusions of three named checks, no token | 40 | 0.1 ms | 0.2 ms | 0.2 ms | accepted | under 200 ms |
| offline, accepted | the fund token against kept key lists: signature, claims, terms; nothing read (`knos.decide.offline`) | 40 | 1.6 ms | 2.5 ms | 2.6 ms | accepted | under 100 ms |
| chain check | one request to the simulated chain and the updated answer (`knos.decide.chain_check`, `after_chain`) | 40 | 1.2 ms | 2.0 ms | 2.6 ms | accepted | under 100 ms |
| offline, warm | the fund token through a `knos.decide.Decider` built before it arrived (what `--stream` runs for each line): the evidence in hand to the provisional receipt | 40 | 1.6 ms | 2.3 ms | 2.7 ms | accepted | under 100 ms |

Requests to an RPC endpoint for one fund token, counted through an endpoint that only counts (`round_trips()`): before the split, the relay's whole precheck made 4 calls of the ledger (1 now, 1 simulate, 2 infos), each at least one request, one after another, and fetched the issuer's key list besides; the chain check makes 1 (1 infos: one getMultipleAccounts), with a timeout of 2 s, and the offline half makes none.

The whole offline command in a new process each time (`python -m knos.decide --token-file ... --no-chain`: interpreter start, imports, decision, receipt written), n 10: p50 473 ms, p95 586 ms, slowest 586 ms; of that, inside the command p50 310 ms, p95 336 ms. Every run said: Provisional: rejected (token expired) (the simulator's clock is not this machine's, so its token is past its time for the command; the signature and the key lookup are the same work). The command says the two parts of that apart: loading the rules (the relay's module and the Solana types, paid once a process) p50 282 ms, p95 317 ms; the decision itself p50 2.4 ms, p95 4.3 ms. The 100 ms target is for the decision once the rules are loaded and the evidence is in hand; a new process for every token does not meet it here.

What `python -m knos.decide` imports, by `python -X importtime` (the median of 5 new processes, each module's own time summed): deciding on a token offline, 238 modules in 407 ms, typer not loaded, the relay's rules loaded (they are the rules it decides by); the free check, 94 modules in 93 ms, typer not loaded, the relay's rules not loaded. Before 0.3.19 the same command loaded typer for every answer: on this machine, idle, 151 modules in 94 ms for the free check and 268 in 165 ms for a token.

One process that stays up (`python -m knos.decide --stream`, a token a line), n 40, each line's own time from the line in hand to its provisional receipt: p50 1.6 ms, p95 2.2 ms, slowest 2.3 ms (the first line also runs each rule for the first time). The process loaded the rules once, in 310 ms, before the first line. Every line said: rejected (token expired) (the simulator's clock again). The target for this path is under 100 ms at p95, and it is met here.

Real tokens (a file of `scripts/replay_tokens.py --capture`, each with the key set of its day, the clock one second after its `iat`), decided warm, n 44: p50 2.1 ms, p95 3.5 ms, slowest 10.4 ms; 44 accepted; 0 lines skipped.
<!-- /decide:time -->

**On devnet, the 0.3.19 command** ([RELAY.md](RELAY.md), "Measuring the 0.3.18 path on devnet", step 4: `KNOS_CLUSTER=devnet python -m knos.decide --token-file token.txt --out provisional.json`, then the same with `--full`), run on 2026-10-07 between 13:19 and 14:07 UTC on the operator's machine (WSL, 2 CPUs, over the shared public RPC `api.devnet.solana.com`), once on each of 24 real GitHub-signed tokens of that day, every one at most an hour old: 11 of the release run's own rounds and 13 that other steps of the same run posted in drexthealpha's repositories. The figures are the command's own (`decided in N ms (offline A ms, chain check B ms in 1 request)`); the interpreter's start is not in them. Fewer than 30 tokens, so the samples are given as they are, not as a distribution.

What that 356 ms was (24 tokens, 2026-10-07; program ids not recorded by that run: the command reads the pinned public ids unless `KNOS_PROGRAM_IDS` names a staging deployment): a new process for each token, so the offline figure (A) held the loading of the rules (the relay's module and the Solana types under it) as well as the decision. Since 0.3.20 the command prints the two apart (`rules loaded in L ms, offline A ms`), and `knos decide --stream` is one process that stays up and decides on each line of its input: the block above has both, measured on the machine it names. Neither has been timed on devnet yet. The release run does it with `python scripts/replay_tokens.py --capture drexthealpha/knos-e2e --out tokens.jsonl` and `python scripts/decide_bench.py --tokens tokens.jsonl --write` (real tokens, decided warm on the operator's machine), and step 4 of [RELAY.md](RELAY.md) again for the new process and the chain check.

| half | n | fastest | median | slowest |
| --- | --- | --- | --- | --- |
| offline (A): signature against the kept key lists, claims, terms | 24 | 170 ms | 356 ms | 863 ms |
| chain check (B): one getMultipleAccounts, left after 2 s | 23 answered, 1 not answered in 2 s | 687 ms | 854 ms | 1,801 ms |
| `--full` (N): the relay's whole precheck, the 0.3.18 path | 24 | 6.0 s | 9.1 s | 15.6 s |

23 of the 24 tokens had been carried to the chain before they were decided here, so both commands answered from what the chain already showed; one (a meter claim) was decided before its relayer carried it, and its provisional receipt said its batch was the next the chain takes. The three fund tokens whose orders had been paid since were accepted by the chain half ("used already: what it asks for is done") and rejected by `--full` ("a fund token works once"). Three meter tokens, decided before the fix of this release, were said by the chain half to be "unused": knos_meter keeps no marker for them, and the chain half now reads the pair's Ledger account instead.

| token | where it was posted | decided before or after the chain took it | A, ms | B, ms | N, ms | provisional | `--full` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fund | knos-e2e-202610020250#2 | after | 863 | 745 | 6020 | accepted | rejected |
| fund | knos-e2e-202610020250#3 | after | 357 | 903 | 7985 | accepted | rejected |
| pay | knos-e2e-202610020250#2 | after | 339 | 829 | 9618 | accepted | accepted |
| pay | knos-e2e-202610020250#3 | after | 199 | 795 | 8844 | accepted | accepted |
| meter batch | knos-e2e-202610020610#25 | after | 537 | 892 | 10423 | accepted | accepted |
| meter claim | knos-e2e-202610020610#25 | after | 344 | 825 | 10212 | accepted | accepted |
| meter batch | knos-e2e-202610020610#25 | after | 219 | 942 | 7872 | accepted | accepted |
| meter claim | knos-e2e-202610020610#25 | before | 170 | 935 | 10597 | accepted | accepted |
| fund | knos-e2e#234 | after | 302 | 995 | 9202 | accepted | rejected |
| pay | knos-e2e#235 | after | 505 | 1322 | 12047 | accepted | accepted |
| pay (neutral attest) | knos-attest#1 | after | 629 | 2005 (not answered in 2 s) | 10184 | accepted | accepted |
| fund | knos-e2e, comment 6039034066 | after | 654 | 1159 | 7439 | accepted | accepted |
| pay | knos-e2e, comment 6039086119 | after | 569 | 955 | 7925 | accepted | accepted |
| fund | knos-playground, comment 6038768371 | after | 184 | 1502 | 15626 | accepted | accepted |
| fund | knos-playground, comment 6038794650 | after | 182 | 1608 | 8231 | accepted | accepted |
| fund | knos-playground, comment 6038825053 | after | 181 | 687 | 8287 | accepted | accepted |
| fund | knos-playground, comment 6038847607 | after | 183 | 720 | 8059 | accepted | accepted |
| fund | knos-playground, comment 6038858790 | after | 233 | 699 | 7960 | accepted | accepted |
| fund | knos-playground, comment 6038889632 | after | 426 | 765 | 8965 | accepted | accepted |
| fund | knos-playground, comment 6038906197 | after | 395 | 764 | 8447 | accepted | accepted |
| fund | knos-playground, comment 6038967955 | after | 355 | 1801 | 11373 | accepted | accepted |
| fund | knos-rc, comment 6038879894 | after | 616 | 819 | 10453 | accepted | accepted |
| fund | knos-rc, comment 6039629748 | after | 433 | 854 | 9549 | accepted | accepted |
| fund | knos-relay-rc, comment 6038623582 | after | 548 | 844 | 10157 | accepted | accepted |

## Every latency, apart

No single number says how fast a payment is. Six waits, each with its own sample and its own owner; none is a sum of others.

<!-- latency:separate -->
Stages: `python scripts/latency_stages.py --separate --rpc https://api.devnet.solana.com --write`, run on 2026-10-07 22:42 UTC against the relay log of drexthealpha/Knos: 47 payments of 2026-10-02 to 2026-10-07. Decision, here: `python scripts/decide_bench.py --write`, run on 2026-10-07: 40 decisions for each row, the chain simulated in the same process (LiteSVM, no network). Decision, on devnet: `KNOS_CLUSTER=devnet python -m knos.decide --token-file token.txt --out provisional.json` of 0.3.19, once on each of 24 real GitHub-signed tokens, a new process for each, on the operator's machine (WSL, 2 CPUs) over api.devnet.solana.com on 2026-10-07 between 13:19 and 14:07 UTC; the figures are the command's own, and in 0.3.19 its offline figure held the loading of the rules (the table of 24 below).

| latency | what is timed | measured | n | p50 | p95 | p99 | worst | whose wait |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| evidence arrival | workflow scheduling: the merge to the start of the workflow run | devnet, public program ids, 11 of 47 payments | 11 | 2 s | 1184 s | none: fewer than 100 samples | not kept | the forge's: starting a runner |
| evidence arrival | relay pickup: the token's comment to a relay taking it up | devnet, public program ids, 11 of 47 payments | 11 | 3 s | 28 s | none: fewer than 100 samples | not kept | Knos's own: a relay finding the token |
| evaluation | evaluation: the start of the run to the token's comment | devnet, public program ids, 11 of 47 payments | 11 | 18 s | 33 s | none: fewer than 100 samples | not kept | the forge's runner: the judging job, then the forge signs what it found |
| decision | warm: the token in hand to the provisional receipt, the rules loaded before it arrived (`knos decide --stream`) | here, on one machine, no network (Intel(R) Core(TM) i3-10110U CPU @ 2.10GHz, 4 CPUs, Linux x86_64, Python 3.12.3; load average 2.4 when it began (other work shared the machine when that is near or above its CPUs, and every figure is then slower than on an idle one)) | 40 | 1.6 ms | 2.3 ms | none: fewer than 100 samples | 2.7 ms | Knos's own, all of it |
| decision | a new process for each token: the rules loaded, then the offline decision | devnet, 2026-10-07, program ids not recorded: 24 real tokens | 24 | 356 ms | none: fewer than 30 samples | none: fewer than 100 samples | 863 ms | Knos's own, all of it |
| decision | the chain check after it: one request, left behind after 2 s | devnet, 2026-10-07, program ids not recorded: 23 real tokens | 23 | 854 ms | none: fewer than 30 samples | none: fewer than 100 samples | 1801 ms | Knos's own, all of it |
| chain confirmation, at `confirmed` | submission: pickup to the block of the first transaction | devnet, public program ids, 11 of 47 payments | 11 | 2 s | 6 s | none: fewer than 100 samples | not kept | the cluster's, and the relay's sends |
| chain confirmation, at `confirmed` | confirmation: that block to the block of the paying transaction | devnet, public program ids, 11 of 47 payments | 11 | 2 s | 8 s | none: fewer than 100 samples | not kept | the cluster's, and the relay's sends |
| finality, at `finalized` | finality: the last confirmation to the cluster finalizing it | not recorded | not recorded | not recorded | not recorded | not recorded | not recorded | the cluster's; no relay waits for it |
| payout | the paying transaction's block to test USDC in the payee's token account | not a wait: the paying transaction is the payout | - | - | - | - | - | nobody's |
| payout | to a bank account | not applicable: no bank route | - | - | - | - | - | nobody's |

The one number a person feels, the merge to the payment, on the public program ids (2026-10-07 reading): p50 25 s, p95 65 s, p99 none: fewer than 100 samples, worst not kept, over the 47 payments that completed and could be timed; it is not the sum of the rows above, which are different samples (a stage is timed only where the relay's log line carries it). The payments that failed or never completed are in the next table, not in these percentiles.

Every payment asked for, on the public program ids, the failed and the unfinished counted (scripts/latency_stages.py --rpc https://api.devnet.solana.com --json on the public relay log of drexthealpha/Knos, 6 October 2026, 14:58 to 15:06 UTC):

| pay attempts | count | what is counted |
| --- | --- | --- |
| asked for | 53 | pull requests whose payment the public relay log has a line for |
| completed | 44 of 53 (83.0%) | a line says ok |
| never completed | 9 of 53 (17.0%) | no line says ok: no wait is timed for them, and no percentile counts them |
| completed only after a failed line | 1 | asked again with a fresh token, then ok |
| log lines that failed | 13 of 57 (22.8%) | one line per token a relay answered for |
| ok lines that took more than one try | 0 | |

Why they failed: that reading kept the counts and not the reasons. The release run's command keeps each line's reason (`stages.attempts.reasons` in docs/bench.json) and prints it here.

The same reading timed 41 of the 44 completed payments from the merge: p50 25 s, p95 58 s, p99 none: fewer than 100 samples, worst 1220 s.

The release run measures every row with a sample again, on the live relay log and devnet, and rewrites this block: `python scripts/latency_stages.py --separate --rpc https://api.devnet.solana.com --write` (GH_TOKEN for GitHub's rate limit), then `python scripts/decide_bench.py --write` for the decision here. `python scripts/latency_stages.py --separate --recorded` prints this table from docs/bench.json with no network.
<!-- /latency:separate -->
