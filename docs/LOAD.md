# Load: many orders open at once

<!-- written by scripts/load.py from docs/load.json; change the numbers there by running it, not here -->

The claim this page tests: 1,000 funded orders open at once, each settled in under a minute of submission, with no order paid twice and none lost. The second half (paid once, none lost) is measured. The first half (a minute) is derived from what was measured, and holds or does not hold depending on how many relayers carry the tokens; the table below says which.

Everything in the first three sections was **measured in the local simulator** (LiteSVM, the same virtual machine a validator runs, with the test builds in `tests/fixtures`). **Compute units are exact**: a cluster charges the same program the same units. **Wall-clock time on a cluster is derived** from those units and Solana's published limits; it was not observed.

## 1. Paid once, none lost (1,000 orders)

`python scripts/load.py --local 1000` on 2026-10-06 (seed 314). 1,000 orders on 1,000 different repositories and issues were funded from one Balance by tokens the harness signs with the test key, and all were open before the first was paid. They were then paid in a shuffled order, four in five to one payee and one in five to two. Every 10th fund token and every 10th pay token was sent a second time at once; every 50th order's fund token and pay token were sent again after the order had closed.

| Check | Result |
| --- | --- |
| Orders open at the same time | 1,000 of 1,000 |
| Orders whose payees hold exactly the order's amount (paid once) | 1,000 of 1,000 |
| Orders paid twice or short | 0 |
| Left the Balance (funded), test USDC | 24,601.53 |
| Reached payees, test USDC | 23,958.00 |
| Fees, the relayer's tips included | 643.52 |
| Came back to the Balance (refunds) | 0.00 |
| paid + fees + refunds == funded | yes |
| Left in any order's account or the shared vault | 0.00 |
| Order accounts still open | 0 |
| Single-use markers of fund tokens present | 1,000 of 1,000 |
| Single-use markers of pay tokens present | 1,000 of 1,000 |
| Tokens sent twice at once, accepted the second time | 200 sent, 0 accepted |
| Tokens sent again after their order closed, accepted | 60 sent, 0 accepted |

The measured builds: `knos_oidc_v2_test.so` sha256 `cd9d7d681aea8083`, `knos_pay_v2_test.so` sha256 `575f1d38bab53a9e`.

## 2. What one order costs

| Stage | Transactions per order | Compute units per order p50 | p95 | max | Largest transaction (CU) | Bytes per order p50 | Largest transaction (bytes) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Token verification (knos_oidc), two tokens | 10 | 3,226,624 | 3,261,078 | 3,305,386 | 847,123 | 7,091 | 1,196 |
| Fund (FundOrderBalance) | 1 | 131,297 | 140,055 | 150,419 | 150,419 | 748 | 748 |
| Pay (PayOrder) | 1 | 171,052 | 245,406 | 262,932 | 262,932 | 808 | 1,006 |

What each number is:

- **Stage.** An order needs two tokens, one that funds it and one that pays it. *Token verification* is every knos_oidc transaction for both: the token written into its account in pieces, then the RSA signature checked in steps. *Fund* and *Pay* are the one knos_pay transaction each token is then handed to.
- **Transactions per order.** Successful transactions of that stage for one order. Refused duplicates are not counted here.
- **Compute units per order.** The sum, over those transactions, of what the runtime reports each consumed (the whole transaction, the programs it calls included). p50, p95 and max are over the orders (nearest rank).
- **Largest transaction.** The most one transaction of the stage consumed; a transaction may use 1,400,000. And the most one weighed, signatures included; a cluster takes 1,232 bytes.
- **Bytes per order.** The sum of the signed transactions' sizes.

## 3. What that allows on a cluster (derived)

Solana's limits: a block holds 100M compute units (60M until SIMD-0286; mainnet has had the larger blocks since 29 July 2026, devnet since earlier), the transactions that write any one account may use 12M of a block, and a block is produced every 400 ms. Sources: [Solana: 100M CU blocks (SIMD-0286), which also states the 12M per-account limit](https://solana.com/upgrades/100m-cu-blocks), [Agave's block cost limits (development branch)](https://github.com/anza-xyz/agave/blob/master/cost-model/src/block_cost_limits.rs), [Solana: slots of 400 ms](https://solana.com/docs/core/transactions/confirmation). The two sources disagree on one figure: Solana's page says the per-account limit stays at 12M, while the development branch of the Agave validator carries 24,000,000 for that constant (read on 4 October 2026). This page uses 12M, the published figure for the live clusters; with 24M the per-relayer, per-Balance and fee-account rates below double.

One order costs 3,547,375 compute units in all (the mean of the measured orders). The accounts that every transaction of a stage writes, and so the ones that cap it:

- **Token verification (knos_oidc), two tokens**: the relayer's own account, which pays the transaction fee (one per relayer).
- **Fund (FundOrderBalance)**: the Balance's side account (one per funder); the Balance's token account (one per funder); the funder's Balance (one per funder); the relayer's own account, which pays the transaction fee (one per relayer).
- **Pay (PayOrder)**: the fee account (FEE_OWNER's token account of the mint) (one per mint, for every relayer and funder); the relayer's own account, which pays the transaction fee (one per relayer); the relayer's token account, where its tip arrives (one per relayer).

So there are three points of contention, and the shared vault is not one of them: each order's money is in its own token account, which only that order's transactions write.

1. **A relayer's own account.** Everything a relayer sends writes the account that pays its fees, so one relayer fits 12M units in a block: **8.46 orders a second**, verification included. Verification is nearly all of it, and it is the only stage more relayers speed up.
2. **The fee account.** Every PayOrder of a mint writes the one fee account, whoever relays it: at most **162.5 payments a second** in that mint, however many relayers there are.
3. **A Balance.** Every order funded from one Balance writes it: at most 226.3 fundings a second per Balance. Orders funded from different Balances, or by wallets, do not share it.

Time for 1,000 orders submitted at once, all from one Balance, if the block held nothing else and was packed perfectly:

| Relayers | Blocks (100M) | Seconds | Orders a second | Bound by | All settled within a minute | Seconds with 60M blocks |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 296 | 118.4 | 8.4 | the relayers' own accounts | no | 118.4 |
| 4 | 74 | 29.6 | 33.8 | the relayers' own accounts | yes | 29.6 |
| 16 | 36 | 14.4 | 69.4 | the block | yes | 24.0 |

How it is derived: blocks = the largest of (all compute / the block limit), (all compute / relayers x 12M), (fund compute / 12M) and (pay compute / 12M), rounded up; seconds = blocks x 0.4. It is a floor on the time, not a forecast: it counts only the compute the transactions consumed (a cluster also charges signatures, write locks and data against the same limits), it assumes the relayers split the tokens evenly and that no other transaction is in the block, and it ignores that the transactions of one token must land one after another. With one relayer the claim of a minute does **not** hold for 1,000 orders arriving together; the table shows from how many relayers it does.

## 4. On a cluster (devnet)

`python scripts/load.py --devnet N --issuer-key issuer.pem --wallet <keypair> --write`, run by the operator at release. GitHub will not sign a thousand tokens on demand, so a test issuer signs them, and its key is registered as a private key of the operator's wallet (knos_oidc's RegisterPrivateKey). That decides what a cluster run can and cannot exercise:

| Stage | On the cluster | Why |
| --- | --- | --- |
| Token verification | exercised | knos_oidc verifies any RS256 issuer's tokens under a registered key |
| Fund | exercised, from a wallet | FundOrderWallet takes no token |
| Refund and close | exercised | every order is refunded after its deadline and every token account closed, so the run leaves nothing behind |
| Pay | **not exercised** | knos_pay takes a token GitHub did not sign only in PayOrder on a PRIVATE order funded from a Balance, under a key the Balance's own wallet registered; that order is funded by FundOrderBalance, which takes GitHub's tokens only, one per order. A test issuer cannot fund and pay N orders, so PayOrder was not sent on the cluster; its compute units are measured in the local simulator. |
| Fund from a Balance, the faucet | **not exercised** | FundOrderBalance and the faucet take GitHub's tokens only. The orders were funded by a wallet (FundOrderWallet), in a mint made for the run. |
| Meter | **not exercised** | knos_meter takes GitHub's tokens only. |

Latency is seconds from a transaction's first submission until the script first saw it `finalized` (it asks once a second), per transaction and per unit (a token: all its transactions; an order: its one). A retry is a transaction signed again because it did not land in time; a failure is one the cluster refused or lost.

### devnet, 2026-10-04: 200 orders, 8 senders

| Stage | Units finalized | Transactions | Failures | Retries | Transaction p50 s | p95 | p99 | Unit p50 s | p95 | p99 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| verify | 200 of 200 | 600 | 0 | 0 | 51.12 | 112.73 | 158.58 | 73.18 | 140.04 | 184.79 |
| fund | 200 of 200 | 200 | 0 | 0 | 38.35 | 97.18 | 157.56 | 38.35 | 97.18 | 157.56 |
| refund | 200 of 200 | 200 | 0 | 0 | 36.43 | 49.89 | 68.21 | 36.43 | 49.89 | 68.21 |
| close | 200 of 200 | 200 | 0 | 0 | 34.51 | 55.22 | 62.19 | 34.51 | 55.22 | 62.19 |

Wallet `Dg2KBXnEBGMME7w1JFbnhZfzjNHJN9CWJmokGmfTuHMJ`, key account `4jtusKvDteVRsri9z3FCFUweZFRfRC9YhjeYj6YWjjN5`, mint `98G8AC2j1H1RHkBitQfVbRbtdwNR453ifrfpBZezmZe1`.

## 5. The whole workflow

A chain rate is not the system's capacity. An order is also two workflow jobs, the requests each makes of GitHub with a token GitHub rations, the comments it posts, a token GitHub signs, a relay that carries it and a statement someone reads back. This section counts those and asks which limit a customer meets first. `python scripts/capacity.py --write` wrote it; `python scripts/capacity.py -R <repositories> -N <deliverables a day>` answers for any customer.

### What one word of the workflow asks of GitHub (counted)

Counted by running `command`, `settle` and `attest` of `src/knos/flow.py` against the tests' stand-in for api.github.com (`tests/_flow.py`), on the simplest order: one issue, one pull request, one payee with a bound wallet. It is a count of the code's requests, exact for that case; an order with more payees, more closing issues or a policy file reads more. It was not counted on GitHub itself.

| Word | Token carried by | Requests read | Requests written | Comments made | Tokens GitHub signs | Jobs |
| --- | --- | --- | --- | --- | --- | --- |
| command (`/knos fund`) | the job's own relay | 9 | 1 | 1 | 1 | 1 |
| settle (on the merge) | the job's own relay | 14 | 5 | 2 | 1 | 1 |
| attest (pay) | the job's own relay | 12 | 0 | 0 | 1 | 1 |
| attest (eval) | the job's own relay | 2 | 0 | 0 | 1 | 1 |
| command (`/knos fund`) | the public worker | 9 | 2 | 2 | 1 | 1 |
| settle (on the merge) | the public worker | 14 | 6 | 3 | 1 | 1 |

The job's own relay is the job sending the transactions itself with a fee key the repository keeps (`KNOS_RELAY_KEY`). Without the key the token is posted as a comment and the public worker carries it; the job then reads the worker's log every 3 s for up to 600 s. Those reads use the repository's own token and are not conditional, so each one counts.

### The budget of one deliverable (funded by a comment, paid on its merge)

| | The job's own relay | The public worker | Where the number is from |
| --- | --- | --- | --- |
| Workflow jobs | 2 | 2 | counted |
| GitHub requests with the repository's token, the work itself | 29 | 31 | counted |
| Reads of the relay log while waiting, at the median wait | 0 | 20 | derived: one read every 3 s for the median of merge-to-paid, 25 s |
| the same at the p95 wait (58 s) | 0 | 42 | derived |
| the same when no relay answers (600 s) | 0 | 404 | derived |
| Requests in all, at the p95 wait | 29 | 73 | counted + derived |
| Comments made in the repository | 3 | 5 | counted |
| Comments the public worker adds to its log | 0 | 2 | from the code (`ghrelay.once` logs a carried token at once) |
| Tokens GitHub signs (OIDC) | 2 | 2 | counted |
| Solana transactions | 12 | 12 | measured in the simulator (section 2) |
| Bytes of signed transactions | 8,647 | 8,647 | measured in the simulator (p50) |
| Compute units | 3,547,375 | 3,547,375 | measured in the simulator (mean) |
| Seconds from merge to paid | not timed apart | median 25, p95 58 | recorded on devnet: 41 payments in the public relay's log, 2026-10-02 to 2026-10-05 (`docs/bench.json`) |
| Actions minutes | not measured | not measured | a job's time on the runner was not recorded; standard runners are free in public repositories |
| RPC requests to send the transactions | not measured | not measured | |

Runner queue time: not apart in these samples; scripts/latency_stages.py splits the payments whose relay log line carries the stage fields: docs/RELAY.md, "Where a token waits".

What the public worker itself spends: every pass (one every 3 s) reads at most 122 repositories' newest comments, each a conditional request. GitHub does not count a conditional request it answers 304 when it carries an Authorization header, so a pass that finds nothing new costs nothing against the worker's 1,000 an hour; a repository with a new token costs 1 counted read, and the token 1 log comment. The search for repositories it does not know runs every 30 s, under the search limit of 30 a minute. A pass queues the tokens it reads and carries up to 4 at once, the tokens of one owner in the order GitHub issued them (section 6).

### The meter's statement (derived from the code)

`knos statement --meter` recomputes a month from the program's log lines: the month account's history 100 rows a request, one `getTransaction` for every transaction in it, and the account itself. It reads at most 100,000 transactions. Solana's public endpoints take 40 requests of one method per 10 seconds from one address, and say they are not for production.

| Evaluations a day | RPC requests for a 30-day month, one transaction an evaluation | With one batch a day |
| --- | --- | --- |
| 10 | 305 | 32 |
| 1,000 | 30,302 | 32 |
| 100,000 | 3,030,002 | 32 |

### Which limit binds first

For a customer with R repositories and N accepted deliverables a day, the work spread evenly over the repositories and over the day (an assumption: a busier hour lowers every figure in proportion; `--peak` sets it). "Binds at" is the N at which the limit is reached; the model is arithmetic on the numbers above and on the published limits, and none of these volumes was run. "Binds first" is among the limits on the work; the meter's statement is a limit on reading the count back, listed in the last column.

| Repositories | Deliverables a day | Token carried by | Binds first | Binds at (a day) | This volume fits | Limits this volume is past |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 10 | the job's own relay | GITHUB_TOKEN requests an hour | 827 | yes | none |
| 1 | 10 | the public worker | GITHUB_TOKEN requests an hour | 328 | yes | none |
| 10 | 1,000 | the job's own relay | GITHUB_TOKEN requests an hour | 8,275 | yes | none |
| 10 | 1,000 | the public worker | the public relay's pass, at the serial rate recorded | 1,728 | yes | none |
| 100 | 100,000 | the job's own relay | concurrent jobs (Free plan) | 14,896 | **no** | the meter's statement, recomputed from the logs; concurrent jobs (Free plan); GITHUB_TOKEN requests an hour |
| 100 | 100,000 | the public worker | the public relay's pass, at the serial rate recorded | 1,728 | **no** | the public relay's pass, at the serial rate recorded; the meter's statement, recomputed from the logs; the public relay's log comments; concurrent jobs (Free plan); GITHUB_TOKEN requests an hour |

Every limit, for the largest of the three (100 repositories, 100,000 a day), soonest first:

| Limit | Whose | Binds at (a day) | From | What lifts it without a program change |
| --- | --- | --- | --- | --- |
| the public relay's pass, at the serial rate recorded (the public worker) | every customer of the public worker | 1,728 | 2 tokens a deliverable, counted as carried one after another; a token taken as the median of merge-to-paid, 25 s (recorded on devnet when the sweep carried one token at a time; it includes the runner's start, so the relay's own share is smaller and one relayer carries at least this many). The sweep now carries up to 4 tokens at once, the tokens of one owner in order (section 6): what that adds is not measured on devnet yet, so it is not counted here | the job's own relay; or several relayers (anyone can run one: the chain takes each token once, whoever carries it) |
| the meter's statement, recomputed from the logs | each buyer and seller, each month | 3,333 | `knos statement --meter` reads at most 100,000 transactions of a month's account, one RPC request each (src/knos/settle/v2/meter.py); a 30-day month, one evaluation a deliverable, one transaction an evaluation. Not a limit on the work: past it the month's account is still the count, and the recomputation from logs is cut short | batching the meter: one RecordBatch token carries up to 100,000 evaluations under one Merkle root, so a month is a few transactions whatever its volume |
| the public relay's log comments (the public worker) | every customer of the public worker | 6,000 | 2 tokens a deliverable, one log comment each (src/knos/proof/ghrelay.py posts a carried token's line at once); 500 content-generating requests an hour (GitHub) | the job's own relay with the repository's fee key (KNOS_RELAY_KEY): nothing is logged by the public worker; or several workers, each logging in a repository of its own (KNOS_RELAY_LOG_REPO) |
| concurrent jobs (Free plan) | the customer's account | 14,896 | 2 jobs a deliverable (counted), each taken as busy for the p95 of merge-to-paid, 58 s (recorded, 41 samples; a job's own time on the runner was not measured apart); 20 jobs at once (GitHub) | a larger plan (Pro 40, Team 60, Enterprise 500); self-hosted runners, which this limit does not count |
| GITHUB_TOKEN requests an hour (the public worker) | each repository | 32,876 | 73 requests a deliverable (23 reads and 8 writes counted, 42 polls of the relay log at the p95 wait); 1,000 an hour for a repository (GitHub) | the job's own relay (no polling); more repositories; GitHub Enterprise Cloud (15,000 an hour) |
| GITHUB_TOKEN requests an hour (the job's own relay) | each repository | 82,758 | 29 requests a deliverable (23 reads and 6 writes counted); 1,000 an hour for a repository (GitHub) | more repositories; GitHub Enterprise Cloud (15,000 an hour) |
| comments made in one repository (the public worker) | each repository | 240,000 | 5 comments a deliverable (counted); 500 content-generating requests an hour (GitHub) | more repositories; or the job's own relay, which posts no token comment |
| comments made in one repository (the job's own relay) | each repository | 400,000 | 3 comments a deliverable (counted); 500 content-generating requests an hour (GitHub) | more repositories |
| the fee key's own account (the job's own relay) | each fee key | 730,944 | 8.46 orders a second for one key that pays the fees (derived by scripts/load.py) | a fee key per repository or per team (KNOS_RELAY_KEY is a repository secret) |
| the fee account of the mint | every customer, every relayer | 14,040,000 | 162.5 payments a second in one mint (derived by scripts/load.py) | NEEDS A PROGRAM CHANGE: PayOrder writes FEE_OWNER's one token account of the mint. The change would be for PayOrder to take any of K fee accounts (a seed of the fee-owner authority and an index, the index chosen by the relayer), all swept to the same owner; nothing off chain can spread it |
| the Balance, one writable account | each Balance | 19,552,320 | 226.3 fundings a second for one Balance (derived by scripts/load.py from measured compute units and 12M units an account a block) | one Balance per team in place of one per organisation: a Balance's address is the owner's id, the wallet that opened it and the mint, and a funding comment spends the Balance that lists its commenter, so each team's wallet opens its own (`knos balance open`) and lists its own people. The hot account is split by configuration; every Balance keeps its own cap, and no order can take more than its Balance holds |

What this says. The public worker is a convenience for small volumes. The reads of its log that a waiting job makes are what uses up a repository's hourly requests first, and its own two limits are shared by every repository it serves. A customer past them relays in its own job with its own fee key, which removes the token comment, the polling and both shared limits at once. After that the limits are GitHub's, per repository and per account, long before they are Solana's. The one bound here that configuration cannot move is the fee account of the mint; of all of them only a single Balance's is further away.

### Measured, recorded, derived

| What | How it is known |
| --- | --- |
| Compute units, transactions and bytes of an order; paid once, none lost | measured in the local simulator, 1,000 orders (sections 1 and 2) |
| Token verification, funding from a wallet, refund and close on a cluster | measured on devnet, 2026-10-04: 200 orders, 0 failures (section 4). PayOrder, funding from a Balance and the meter were not sent in that run |
| Seconds from merge to paid | recorded on devnet, 41 payments (`docs/bench.json`) |
| Requests, comments, tokens and jobs of a word | counted from the code against a stand-in for GitHub; not observed on GitHub |
| Limits of GitHub and of Solana | published by them, read on 2026-10-05 (links below); GitHub says its secondary limits may change without notice, and its page does not say whether the content limit is counted per repository for a workflow's token, which this page assumes |
| Cluster rates, the relay log polling, statement requests, every "binds at" | derived |
| Actions minutes, runner queue time apart from the rest, RPC requests per order, any GitHub limit actually being hit | not measured |

Sources: [GitHub: rate limits for the REST API (60 an hour unauthenticated, 5,000 authenticated, 1,000 per repository for GITHUB_TOKEN, 15,000 on Enterprise Cloud; secondary limits: 900 points a minute, 80 content-generating requests a minute and 500 an hour, "subject to change without notice")](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api); [GitHub: best practices for the REST API (a 304 to a conditional request sent with an Authorization header does not count against the primary limit; wait a second between writes)](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api); [GitHub: Actions limits (concurrent jobs on standard hosted runners: Free 20, Pro 40, Team 60, Enterprise 500; 500 workflow runs queued per 10 seconds per repository)](https://docs.github.com/en/actions/reference/limits); [GitHub: Actions billing (standard hosted runners are free in public repositories; included minutes a month: Free 2,000, Pro 3,000, Team 3,000, Enterprise Cloud 50,000)](https://docs.github.com/en/billing/concepts/product-billing/github-actions); [GitHub: search endpoints (30 requests a minute when authenticated)](https://docs.github.com/en/rest/search/search); [GitHub: OpenID Connect reference (the page that describes the token request; it states no rate limit, and none was measured here)](https://docs.github.com/en/actions/reference/security/oidc); [Solana: public RPC endpoints (100 requests per 10 seconds per IP, 40 for one method; "not intended for production applications")](https://solana.com/docs/references/clusters); [Solana: 100M CU blocks (SIMD-0286), which also states the 12M per-account limit](https://solana.com/upgrades/100m-cu-blocks).

## 6. The relay: where a payment's seconds go, and its queue

### The stages of a payment (recorded on devnet)

From `python scripts/latency_stages.py --rpc https://api.devnet.solana.com --json`, run on 6 October 2026 from 14:58 to 15:06 UTC against the public relay log (drexthealpha/Knos) and devnet: 41 payments of 2 to 5 October 2026. Each stage is timed only for the payments whose log line recorded it, so each row has its own n; a stage no line recorded says "not recorded", and no figure here is derived from another row.

| stage | from, to | n | p50 | p95 |
| --- | --- | --- | --- | --- |
| merge to paid, the whole wait | GitHub's `merged_at` to the block that paid | 41 | 25 s | 58 s |
| workflow scheduling | the merge to the start of the workflow run | 5 | 2 s | 1184 s |
| evaluation | the start of the run to the token's comment | 5 | 16 s | 24 s |
| relay pickup | the token's comment to a relay taking it up | 5 | 2 s | 5 s |
| submission | pickup to the block of the first transaction | 5 | 2 s | 5 s |
| confirmation | that block to the block of the paying transaction | 5 | 3 s | 8 s |
| finality | the last confirmation to the cluster finalizing it | not recorded | not recorded | not recorded |

Read it with its n. The whole wait is 41 payments; the stage rows are 5 of them, because the log lines of the other 36 carry no stage fields: for those payments every stage is not recorded, and their time is in the first row only. With 5 samples the 95th percentile by nearest rank is the slowest of them, so a p95 in a stage row is one payment, not a band. `python scripts/latency_stages.py --md` prints this table from the live log.

### The relay's queue (a local test of the queue, not a benchmark of the service)

`python scripts/queue_drill.py --write` (seed 314). **This is a local test of the queue, not an end-to-end service benchmark**: nothing is signed, no transaction is built, no cluster and no GitHub is asked, and the clock is the test's own. The chain is a stand-in that keeps one rule, the programs' single-use rule (a token is taken once; a second send is answered "already" and moves nothing). It says how the queue (`src/knos/settle/v2/relayq.py`) behaves, and nothing about seconds on a cluster.

200 entries of 20 payers were queued and carried by 4 workers. One worker was killed after it took an entry and before it sent; one entry's confirmation was held for 60 s of the test's clock while others went on.

| Check | Result |
| --- | --- |
| Entries done | 200 of 200 |
| Entries dead, or left open | 0, 0 |
| Sends to the chain | 200 (one an entry) |
| Entries sent twice | 0 |
| Entries the chain took, each once | 200 |
| Entries that left out of order within their payer's lane | 0 |
| Workers killed | 1 |
| Entries taken again after a lease of 180 s expired | 1 (the killed worker's) |
| At least 20 entries carried while the slow one was in flight | yes |

What it does not show: a kill between a send and its answer. Then the entry is sent a second time, and it is the program that refuses the repeat; `tests/test_relayq.py` runs that case against the stand-in, and `tests/test_relay_failures.py` runs a relay killed between its send and the confirmation on the programs as built (LiteSVM).

### The always-on sweep on the queue (the same local test, through the relay's own pass)

The same command runs a second part: `knos.proof.ghrelay.once`, the pass the public worker repeats every 3 s, which now queues what it reads and carries it with the queue's 4 workers. **This too is a local test of the queue, not an end-to-end benchmark**: GitHub and the chain are stand-ins and the clock is the test's own. The 41 payments recorded on devnet above (p50 25 s, p95 58 s) were made by the serial sweep, before it was on the queue: no figure on this page times the queue on a cluster.

12 tokens of 6 owners were posted; the confirmation of one took 60 s of the test's clock. Then two more were posted, and the pass that carried them was killed after it had sent one and before it noted anything.

| Check | Result |
| --- | --- |
| Tokens carried in the first pass | 12 of 12, with 12 sends |
| Tokens done before the slow one confirmed | 11 of the other 11 |
| Seconds from comment to answer on the test's clock: the slow one, the slowest other | 64, 15 |
| Most tokens in flight at once | 4 |
| Times two tokens of one owner were in flight together | 0 |
| Tokens the chain took out of their owner's order | 0 |
| The killed pass's token: sends, times the chain took it | 2, 1 (the second send was answered "already") |
| Tokens the chain took, and log lines | 14, 14 |

What one pass still does: it ends when its slowest token is answered, so a comment posted while a confirmation is awaited is read when that pass is over (up to the 60 s a relay waits for one confirmation), not 3 s later.
