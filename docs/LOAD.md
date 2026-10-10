# Load: many orders open at once

<!-- written by scripts/load.py from docs/load.json; change the numbers there by running it, not here -->

The claim this page tests: 1,000 funded orders open at once, each settled in under a minute of submission, with no order paid twice and none lost. The second half (paid once, none lost) is measured. The first half (a minute) is derived from what was measured, and holds or does not hold depending on how many relayers carry the tokens; the table below says which.

Everything in the first three sections was **measured in the local simulator** (LiteSVM, the same virtual machine a validator runs, with the test builds in `tests/fixtures`). **Compute units are exact**: a cluster charges the same program the same units. **Wall-clock time on a cluster is derived** from those units and Solana's published limits; it was not observed.

## 1. Paid once, none lost (1,000 orders)

`python scripts/load.py --local 1000` on 2026-10-07 (seed 314). 1,000 orders on 1,000 different repositories and issues were funded from one Balance by tokens the harness signs with the test key, and all were open before the first was paid. They were then paid in a shuffled order, four in five to one payee and one in five to two. Every 10th fund token and every 10th pay token was sent a second time at once; every 50th order's fund token and pay token were sent again after the order had closed.

| Check | Result |
| --- | --- |
| Orders open at the same time | 1,000 of 1,000 |
| Orders whose payees hold exactly the order's amount (paid once) | 1,000 of 1,000 |
| Orders paid twice or short | 0 |
| Left the Balance (funded), test USDC | 24,035.84 |
| Reached payees, test USDC | 23,958.00 |
| Fees, the relayer's tips included | 77.84 |
| Came back to the Balance (refunds) | 0.00 |
| paid + fees + refunds == funded | yes |
| Left in any order's account or the shared vault | 0.00 |
| Order accounts still open | 0 |
| Single-use markers of fund tokens present | 1,000 of 1,000 |
| Single-use markers of pay tokens present | 1,000 of 1,000 |
| Tokens sent twice at once, accepted the second time | 200 sent, 0 accepted |
| Tokens sent again after their order closed, accepted | 60 sent, 0 accepted |

The measured builds: `knos_oidc_v2_test.so` sha256 `cd9d7d681aea8083`, `knos_pay_v2_test.so` sha256 `28dc056375a56bf0`.

## 2. What one order costs

| Stage | Transactions per order | Compute units per order p50 | p95 | max | Largest transaction (CU) | Bytes per order p50 | Largest transaction (bytes) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Token verification (knos_oidc), two tokens | 10 | 3,226,281 | 3,259,537 | 3,335,400 | 849,126 | 7,091 | 1,196 |
| Fund (FundOrderBalance) | 1 | 132,555 | 141,450 | 152,062 | 152,062 | 748 | 748 |
| Pay (PayOrder) | 1 | 169,923 | 241,459 | 260,963 | 260,963 | 808 | 1,006 |

What each number is:

- **Stage.** An order needs two tokens, one that funds it and one that pays it. *Token verification* is every knos_oidc transaction for both: the token written into its account in pieces, then the RSA signature checked in steps. *Fund* and *Pay* are the one knos_pay transaction each token is then handed to.
- **Transactions per order.** Successful transactions of that stage for one order. Refused duplicates are not counted here.
- **Compute units per order.** The sum, over those transactions, of what the runtime reports each consumed (the whole transaction, the programs it calls included). p50, p95 and max are over the orders (nearest rank).
- **Largest transaction.** The most one transaction of the stage consumed; a transaction may use 1,400,000. And the most one weighed, signatures included; a cluster takes 1,232 bytes.
- **Bytes per order.** The sum of the signed transactions' sizes.

## 3. What that allows on a cluster (derived)

Solana's limits: a block holds 100M compute units (60M until SIMD-0286; mainnet has had the larger blocks since 29 July 2026, devnet since earlier), the transactions that write any one account may use 12M of a block, and a block is produced every 400 ms. Sources: [Solana: 100M CU blocks (SIMD-0286), which also states the 12M per-account limit](https://solana.com/upgrades/100m-cu-blocks), [Agave's block cost limits (development branch)](https://github.com/anza-xyz/agave/blob/master/cost-model/src/block_cost_limits.rs), [Solana: slots of 400 ms](https://solana.com/docs/core/transactions/confirmation). The two sources disagree on one figure: Solana's page says the per-account limit stays at 12M, while the development branch of the Agave validator carries 24,000,000 for that constant (read on 4 October 2026). This page uses 12M, the published figure for the live clusters; with 24M the per-relayer, per-Balance and fee-account rates below double.

One order costs 3,546,061 compute units in all (the mean of the measured orders). The accounts that every transaction of a stage writes, and so the ones that cap it:

- **Token verification (knos_oidc), two tokens**: the relayer's own account, which pays the transaction fee (one per relayer).
- **Fund (FundOrderBalance)**: the Balance's side account (one per funder); the Balance's token account (one per funder); the funder's Balance (one per funder); the relayer's own account, which pays the transaction fee (one per relayer).
- **Pay (PayOrder)**: the fee account (FEE_OWNER's token account of the mint) (one per mint, for every relayer and funder); the relayer's own account, which pays the transaction fee (one per relayer); the relayer's token account, where its tip arrives (one per relayer).

So there are three points of contention, and the shared vault is not one of them: each order's money is in its own token account, which only that order's transactions write.

1. **A relayer's own account.** Everything a relayer sends writes the account that pays its fees, so one relayer fits 12M units in a block: **8.46 orders a second**, verification included. Verification is nearly all of it, and it is the only stage more relayers speed up.
2. **The fee account.** Every PayOrder of a mint writes the fee account it names: at most **164.6 payments a second** through one fee account, however many relayers there are. The program takes any token account of the mint that FEE_OWNER owns, so K fee accounts (`knos relay fee-accounts`) lift this K times, up to the block's own limit (derived, not measured).
3. **A Balance.** Every order funded from one Balance writes it: at most 224.1 fundings a second per Balance. Orders funded from different Balances, or by wallets, do not share it.

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

### devnet, STAGING program ids (not the public ones), 2026-10-04: 200 orders, 8 senders

These 200 orders ran on the staging deployment, not on the public program ids: knos_oidc `iosu8ARUNvvruHPCcMWQ5rqsnJewzBxcPXajSpoHqXd`, knos_pay `FJJtqcRjQ9ATx37sBTCLUBxBqLUA9aQgSTLAsZynqtnH`. Every figure in this table is staging's; on the public program ids only the funding rate below was measured.

| Stage | Units finalized | Transactions | Failures | Retries | Transaction p50 s | p95 | p99 | worst | Unit p50 s | p95 | p99 | worst |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| verify | 200 of 200 | 600 | 0 of 600 | 0 | 51.12 | 112.73 | 158.58 | 207.44 | 73.18 | 140.04 | 184.79 | 207.44 |
| fund | 200 of 200 | 200 | 0 of 200 | 0 | 38.35 | 97.18 | 157.56 | 254.31 | 38.35 | 97.18 | 157.56 | 254.31 |
| refund | 200 of 200 | 200 | 0 of 200 | 0 | 36.43 | 49.89 | 68.21 | 113.95 | 36.43 | 49.89 | 68.21 | 113.95 |
| close | 200 of 200 | 200 | 0 of 200 | 0 | 34.51 | 55.22 | 62.19 | 74.16 | 34.51 | 55.22 | 62.19 | 74.16 |

Wallet `Dg2KBXnEBGMME7w1JFbnhZfzjNHJN9CWJmokGmfTuHMJ`, key account `4jtusKvDteVRsri9z3FCFUweZFRfRC9YhjeYj6YWjjN5`, mint `98G8AC2j1H1RHkBitQfVbRbtdwNR453ifrfpBZezmZe1`.

### Throughput with relays side by side: measured, and derived

`python scripts/load.py measure --relays N --orders M --wallet <keypair> --write`, run by the operator at release. N relays, each with a fee payer of its own, each fund their share of M orders one after another (a key signs for one thing at a time), twice: `apart`, where no two relays write an account in common, and `shared`, where every transaction also writes one token account. That account stands for the fee account, which every release of a mint writes whoever relays it. A rate is confirmed transactions divided by the seconds from the first submission to the last confirmation. PayOrder is not sent (the table above says why): this measures funding with and without one shared writable account, not payments.

#### Measured on devnet, public program ids, 2026-10-07: funding only (FundOrderWallet), no PayOrder; 4 relays, 40 orders each way

| | Confirmed | Seconds | Confirmed a second | Retries | Failures | Confirm p50 s | p95 | p99 | worst | Slots used | Most in one slot |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| apart: no account written by two relays | 40 of 40 | 87.73 | 0.46 | 0 | 0 of 40 | 6.21 | 15.11 | none: fewer than 100 samples | 16.83 | 31 | 3 |
| shared: every transaction also writes one token account, as every release writes the fee account | 40 of 40 | 76.3 | 0.52 | 0 | 0 of 40 | 4.16 | 15.13 | none: fewer than 100 samples | 15.18 | 36 | 2 |

The contention seen: the shared account's rate was 1.13 of the rate apart, with 0 more retries and 0 more failures. It cost 0.009084 SOL in fees and rent not recovered. Wallet `9ig9AXfoNrd5uPhdSFGujPoVsrxze5CGVFM6uusgQydG`, mint `7SeTJW6zrauJRzkDC7Bmrb6trZRSySVNBXJJbQyFNYaA`, shared account `ESfiEkuTtnyiHhLsrm71qphhQbnwdXdqdaTCGqsfypP`.

#### Measured on devnet, public program ids, 2026-10-08: end-to-end PayOrder: token verification, then the payment; 1 relay, 40 payments attempted

| Attempted | Paid | Carried first by another relay | Refused | Never completed | Seconds | Paid a second | Payment p50 s | p95 | p99 | worst |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 40 | 40 of 40 | 0 | 0 | 0 | 412.74 | 0.097 | 9.44 | 13.58 | none: fewer than 100 payments | 17.35 |

A payment's seconds run from its first submission to the relay's answer: the token written, GitHub's signature verified, then PayOrder. The fee payers were not kept in the record. A lane was then the repository's owner, and every token came from one owner: one lane, so ONE relay carried all of them, through one fee account. This is a one-relay figure, not a ceiling of the program. Source: the operator's release run of 0.3.21 on 8 Oct 2026 with its own wallets; the 40 pay tokens were signed in GitHub Actions run 37763004447; recorded from the run's report, which kept no fee payers.

#### Measured on devnet, public program ids, 2026-10-08: end-to-end PayOrder: token verification, then the payment; 4 relays, 40 payments attempted

| Attempted | Paid | Carried first by another relay | Refused | Never completed | Seconds | Paid a second | Payment p50 s | p95 | p99 | worst |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 40 | 40 of 40 | 0 | 0 | 0 | 211.27 | 0.189 | 11.45 | 22.61 | none: fewer than 100 payments | 34.9 |

A payment's seconds run from its first submission to the relay's answer: the token written, GitHub's signature verified, then PayOrder. The fee payers were not kept in the record. A pay token's lane was its order, so the tokens of 1 owner(s) spread over the relays; 4 fee account(s) of the mint, each order's fee to one. The relays paid 16, 8, 5 and 11 of the payments; the fee accounts took 14, 9, 9 and 8. Source: the operator's release run of 0.3.22 on 8 Oct 2026 with its own wallets; the 40 pay tokens were signed in GitHub Actions run 37833126115 of drexthealpha/knos-load; recorded from the run's report, which lists the 40 order ids and the four fee accounts; it kept no fee payers of the relays.

#### Measured on devnet, public program ids, 2026-10-09: end-to-end PayOrder: token verification, then the payment; 4 relays, 40 payments attempted; scenario hot-funder

| Attempted | Paid | Carried first by another relay | Refused | Never completed | Seconds | Paid a second | Payment p50 s | p95 | p99 | worst |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 40 | 40 of 40 | 0 | 0 | 0 | not recorded | 0.185 | 18.4 | 28.3 | none: fewer than 100 payments | 29.0 |

A payment's seconds run from its first submission to the relay's answer: the token written, GitHub's signature verified, then PayOrder. The fee payers were not kept in the record. A pay token's lane was its order, so the tokens of 1 owner(s) spread over the relays; 1 fee account(s) of the mint, each order's fee to one. Scenario hot-funder: every payment is of one funder's orders and writes ONE fee account, all relays at once: the write locks every payment shares. Retries: 0; failures: 0. Source: the operator's release run of 0.3.23 on 9 Oct 2026 with its own wallets, 4 relays, 40 pay tokens a scenario; recorded from the run's report, which kept the payments paid, the retries, p50, p95 and the worst, and the rate; it kept no fee payers, no run seconds and no split of the failures into refused and never completed.

#### Measured on devnet, public program ids, 2026-10-09: end-to-end PayOrder: token verification, then the payment; 4 relays, 40 payments attempted; scenario rpc-faults

| Attempted | Paid | Carried first by another relay | Refused | Never completed | Seconds | Paid a second | Payment p50 s | p95 | p99 | worst |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 40 | 40 of 40 | 0 | 0 | 0 | not recorded | 0.127 | 23.2 | 48.5 | none: fewer than 100 payments | 49.7 |

A payment's seconds run from its first submission to the relay's answer: the token written, GitHub's signature verified, then PayOrder. The fee payers were not kept in the record. A pay token's lane was its order, so the tokens spread over the relays; the number of fee accounts was not recorded. Scenario rpc-faults: 15% of submissions refused by the endpoint and 15% sent with the answer lost, each payment retried up to 3 times; a payment counts as paid only when the chain shows it, and a resend after a lost answer must be refused. Retries: 17; failures: 0. No payment was made twice. Source: the operator's release run of 0.3.23 on 9 Oct 2026 with its own wallets, 4 relays, 40 pay tokens a scenario; recorded from the run's report, which kept the payments paid, the retries, p50, p95 and the worst, and the rate; it kept no fee payers, no run seconds and no split of the failures into refused and never completed.

#### Measured on devnet, public program ids, 2026-10-09: end-to-end PayOrder: token verification, then the payment; 4 relays, 40 payments attempted; scenario priority-fee

| Attempted | Paid | Carried first by another relay | Refused | Never completed | Seconds | Paid a second | Payment p50 s | p95 | p99 | worst |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 40 | 40 of 40 | 0 | 0 | 0 | not recorded | 0.173 | 18.5 | 29.3 | none: fewer than 100 payments | 32.1 |

A payment's seconds run from its first submission to the relay's answer: the token written, GitHub's signature verified, then PayOrder. The fee payers were not kept in the record. A pay token's lane was its order, so the tokens spread over the relays; the number of fee accounts was not recorded. Scenario priority-fee: every transaction that has room carries a compute unit price (SetComputeUnitPrice), 10,000 micro-lamports unless --cu-price says otherwise. Retries: 0; failures: 0. No transaction of this run carried a price: the code of 0.3.23 skipped v1 transactions, so this is a plain run, not a priced one. Source: the operator's release run of 0.3.23 on 9 Oct 2026 with its own wallets, 4 relays, 40 pay tokens a scenario; recorded from the run's report, which kept the payments paid, the retries, p50, p95 and the worst, and the rate; it kept no fee payers, no run seconds and no split of the failures into refused and never completed. To be rerun: done by the 0.3.24 release on 9 Oct 2026: the next priority-fee row.

#### Measured on devnet, public program ids, 2026-10-09: end-to-end PayOrder: token verification, then the payment; 4 relays, 40 payments attempted; scenario priority-fee

| Attempted | Paid | Carried first by another relay | Refused | Never completed | Seconds | Paid a second | Payment p50 s | p95 | p99 | worst |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 40 | 40 of 40 | 0 | 0 | 0 | not recorded | 0.201 | 12.9 | 23.5 | none: fewer than 100 payments | 31.5 |

A payment's seconds run from its first submission to the relay's answer: the token written, GitHub's signature verified, then PayOrder. The fee payers were not kept in the record. A pay token's lane was its order, so the tokens spread over the relays; the number of fee accounts was not recorded. Scenario priority-fee: every transaction that has room carries a compute unit price (SetComputeUnitPrice), 10,000 micro-lamports unless --cu-price says otherwise. Retries: 0; failures: 0. Every PayOrder carried a compute unit price this time (0.3.24 writes it into version-1 messages). Source: the operator's release run of 0.3.24 on 9 Oct 2026 with its own wallets, 4 relays, 40 pay tokens a scenario; recorded from the run's report, which kept the payments paid, the retries, the duplicates refused, p50, p95 and the worst, and the rate; it kept no fee payers, no run seconds and no split of the failures into refused and never completed.

#### Measured on devnet, public program ids, 2026-10-09: end-to-end PayOrder: token verification, then the payment; 4 relays, 40 payments attempted; scenario burst (did not complete cleanly)

| Attempted | Paid | Carried first by another relay | Refused | Never completed | Seconds | Paid a second | Payment p50 s | p95 | p99 | worst |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 40 | 13 of 40 | 0 | not recorded | not recorded | not recorded | 0.039 | 264.5 | 300.3 | none: fewer than 100 payments | 300.3 |

A payment's seconds run from its first submission to the relay's answer: the token written, GitHub's signature verified, then PayOrder. The fee payers were not kept in the record. A pay token's lane was its order, so the tokens spread over the relays; the number of fee accounts was not recorded. Scenario burst: every relay sends all of its payments at once instead of one after another. Retries: 0; failures: 27. The 27 failures were HTTP 429 (the public endpoint's rate limit) and "Blockhash not found"; 0.3.23 sent each payment once. Source: the operator's release run of 0.3.23 on 9 Oct 2026 with its own wallets, 4 relays, 40 pay tokens a scenario; recorded from the run's report, which kept the payments paid, the retries, p50, p95 and the worst, and the rate; it kept no fee payers, no run seconds and no split of the failures into refused and never completed. To be rerun: done by the 0.3.24 release on 9 Oct 2026: the next burst row.

#### Measured on devnet, public program ids, 2026-10-09: end-to-end PayOrder: token verification, then the payment; 4 relays, 40 payments attempted; scenario burst (did not complete cleanly)

| Attempted | Paid | Carried first by another relay | Refused | Never completed | Seconds | Paid a second | Payment p50 s | p95 | p99 | worst |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 40 | 22 of 40 | 0 | not recorded | not recorded | not recorded | 0.077 | 262.5 | 278.3 | none: fewer than 100 payments | 278.3 |

A payment's seconds run from its first submission to the relay's answer: the token written, GitHub's signature verified, then PayOrder. The fee payers were not kept in the record. A pay token's lane was its order, so the tokens spread over the relays; the number of fee accounts was not recorded. Scenario burst: every relay sends all of its payments at once instead of one after another. Retries: 4; failures: 18. The 18 failures were RPC drops, timeouts and HTTP 408: answers lost on the way, which 0.3.24 did not send again. Source: the operator's release run of 0.3.24 on 9 Oct 2026 with its own wallets, 4 relays, 40 pay tokens a scenario; recorded from the run's report, which kept the payments paid, the retries, the duplicates refused, p50, p95 and the worst, and the rate; it kept no fee payers, no run seconds and no split of the failures into refused and never completed. To be rerun: done by the 0.3.25 release on 10 Oct 2026: the next burst row.

#### Measured on devnet, public program ids, 2026-10-10: end-to-end PayOrder: token verification, then the payment; 4 relays, 40 payments attempted; scenario burst

| Attempted | Paid | Carried first by another relay | Refused | Never completed | Seconds | Paid a second | Payment p50 s | p95 | p99 | worst |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 40 | 40 of 40 | 0 | 0 | 0 | 611.86 | 0.065 | 580.75 | 610.38 | none: fewer than 100 payments | 611.85 |

A payment's seconds run from its first submission to the relay's answer: the token written, GitHub's signature verified, then PayOrder. Each relay paid from a fee payer of its own (`8yDmQNFynGvC6vnxBKn2jBTHXvQ2229nditAQayWFcve`, `CaA4rWEF77JT8XCYSB3U8jcj3dGETDNBk5eyXgurNJAp`, `DEzBx5xkBbuEfzoRgJGTDdrfhnodXX8djdgBknYW5Jd`, `56QGy4NsYspMUVfqfVbC2JcjLgFprbu1RZS7GcbGywvK`), lent its SOL by wallet `9ig9AXfoNrd5uPhdSFGujPoVsrxze5CGVFM6uusgQydG` and swept back. A pay token's lane was its order, so the tokens of 1 owner(s) spread over the relays; 4 fee account(s) of the mint, each order's fee to one. The relays paid 8, 13, 8 and 11 of the payments. Scenario burst: every relay sends all of its payments at once instead of one after another; a payment the endpoint turns away (HTTP 429) or whose blockhash expired is sent again after a bounded wait with jitter, over a fresh blockhash. Retries: 73; failures: 0. Duplicates refused by the chain (a resend of a payment that had landed): 0. Fan-out (knos.settle.v2.fanout): every signed transaction went to 1 endpoint(s), 0 of them a second endpoint, the same bytes again every 2.0 s while no endpoint had taken them, confirmed by its signature's status (getSignatureStatuses), at most 60.0 s a transaction; 124 sends, 36 resends, 40 requests with no answer, 44 status polls. Sent through knos.settle.v2.fanout as this release fixed it before the run: one getSignatureStatuses a poll round for every transaction waiting, bytes sent again every 2 s only while no endpoint had taken them, each wait bounded in seconds as well as in polls. A first run on 10 Oct 2026 with the fan-out as it was before that fix (each transaction's status asked every 0.5 s, its bytes sent again every 2 s) was stopped after 22.8 minutes with 11 of 40 paid, every status request answered HTTP 429; it kept no record, and its 29 unpaid orders went back after their deadline. Source: the operator's release run of 0.3.25 on 10 Oct 2026 with its own wallets, 4 relays and 4 fee accounts; the 40 orders were funded from the run's own wallet in a mint made for the run (EdEeUeZxubezcCW3VHDtGKB9mScyF2Pz3MTD4xBycq1T), and their 40 pay tokens were signed in GitHub Actions run 38012410577 of drexthealpha/knos-load; one endpoint, https://api.devnet.solana.com: Solana lists one public devnet endpoint (https://solana.com/docs/references/clusters), so no second endpoint was given; the 40 order ids are in docs/load.json.

**One relay against 4, measured.** Devnet, public program ids: 40 of 40 payments in 211.27 s, 0.189 a second, with 4 relays and 4 fee accounts (2026-10-08), against 40 of 40 payments, 0.097 a second, through one relay and one fee account (2026-10-08): 1.95 times the rate. Both runs had one owner's tokens and waited for each payment's answer before a relay sent the next.

**Contention scenarios.** `python scripts/load.py measure --pay --scenario S` adds one kind of contention to the PayOrder run: `--simulate` here (faults injected on the way to the simulator), `--tokens ... --wallet ... --write` on devnet by the release, each with a row of its own.

| Scenario | What it measures | Simulated here | On devnet |
| --- | --- | --- | --- |
| hot-funder | every payment is of one funder's orders and writes ONE fee account, all relays at once: the write locks every payment shares | 40 of 40 paid, 4 relays, local simulator, 2026-10-09; every check holds; 2 accounts written by every relay, the one fee account among them; no rate | 40 of 40 paid, 0 failures, 0 retries, 0.185 a second; p50 18.4 s, p95 28.3 s, p99 none (fewer than 100), worst 29.0 s; 4 relays, devnet, public program ids, 2026-10-09 |
| rpc-faults | 15% of submissions refused by the endpoint and 15% sent with the answer lost, each payment retried up to 3 times; a payment counts as paid only when the chain shows it, and a resend after a lost answer must be refused | 40 of 40 paid, 4 relays, local simulator, 2026-10-09; every check holds; 12 retries; 7 sends refused, 5 answers lost, 5 resends refused by the program; no rate | 40 of 40 paid, 0 failures, 17 retries, 0.127 a second; p50 23.2 s, p95 48.5 s, p99 none (fewer than 100), worst 49.7 s; 4 relays, devnet, public program ids, 2026-10-09 |
| priority-fee | every transaction carries a compute unit price, 10,000 micro-lamports unless --cu-price says otherwise: SetComputeUnitPrice in a legacy transaction with room, the same lamports in a v1 transaction's message | 40 of 40 paid, 4 relays, local simulator, 2026-10-09; every check holds; priority fee 14,000 lamports a PayOrder at 10,000 micro-lamports, as charged; no rate | 40 of 40 paid, 0 failures, 0 retries, 0.201 a second; p50 12.9 s, p95 23.5 s, p99 none (fewer than 100), worst 31.5 s; 4 relays, devnet, public program ids, 2026-10-09 |
| burst | every relay sends all of its payments at once instead of one after another; a payment the endpoint turns away (HTTP 429) or whose blockhash expired is sent again after a bounded wait with jitter, over a fresh blockhash | 40 of 40 paid, 4 relays, local simulator, 2026-10-09; every check holds; 40 tokens verified and open at once; no rate | 40 of 40 paid, 0 failures, 73 retries, 0.065 a second; p50 580.75 s, p95 610.38 s, p99 none (fewer than 100), worst 611.85 s; 4 relays, devnet, public program ids, 2026-10-10 |

**Derived bound (not measured).** Section 3's arithmetic from the simulator's compute units and Solana's published limits: 8.46 orders a second per fee payer (verification included), 164.6 payments a second through one fee account (K accounts: K times that, up to the block), 224.1 fundings a second from one Balance. These are ceilings in an otherwise empty block. A measured rate above is of devnet on the day, with its own traffic, through one public endpoint, and each relay waits for a confirmation before it sends again: the two are different quantities, and neither is used in place of the other.

**What reduces shared writable state without a program change:**

| Way | State |
| --- | --- |
| Several fee payers | exists: `KNOS_RELAY_KEYS` (docs/RELAY.md). Each owner's tokens always pay from the same one of the keys, so the relays stop sharing the one account that pays the fees: the per-relayer ceiling of section 3 is per key. |
| One release for many small outcomes | exists: `knos net` (docs/NETTING.md) settles outcomes under 20 USD as one release per payee per period, so the fee account is written once per payee per period and not once per outcome. |
| One transaction for many evaluations | exists: the meter's RecordBatch counts a period's evaluations in one transaction and moves no money, so it does not write the fee account at all. |
| A fee account per mint | exists by construction: the fee account is the fee owner's token account OF THE ORDER'S MINT, so orders in two mints do not share it. Every order Knos has funded is in one mint, so this has not been used. |
| Several fee accounts for one mint | exists since 0.3.22, with no program change: PayOrder, SettleOrder and Release take any token account of the mint that FEE_OWNER owns (order_pay.rs `is_owned(fee_tok, token, mint, FEE_OWNER)`). `knos relay fee-accounts --k K` makes K-1 beside the associated one, and each order's payments use one of K, chosen by the order. Shown in the simulator on the 2.1 and 2.2 builds (tests/test_fee_shards.py); used on devnet by the 4-relay run of 8 Oct 2026 with K = 4 (its row above). |
| Pay work partitioned by order | exists since 0.3.22: a token that pays an order travels in that order's lane, so one owner's orders spread over N relays. Before, one owner's tokens were one lane and so one relay. Measured on devnet by the 4-relay run of 8 Oct 2026 (its row above, beside the one-relay row). |

## 5. The whole workflow

A chain rate is not the system's capacity. An order is also two workflow jobs, the requests each makes of GitHub with a token GitHub rations, the comments it posts, a token GitHub signs, a relay that carries it and a statement someone reads back. This section counts those and asks which limit a customer meets first. `python scripts/capacity.py --write` wrote it; `python scripts/capacity.py -R <repositories> -N <deliverables a day>` answers for any customer.

### What one word of the workflow asks of GitHub (counted)

Counted by running `command`, `settle` and `attest` of `src/knos/flow.py` against the tests' stand-in for api.github.com (`tests/_flow.py`), on the simplest order: one issue, one pull request, one payee with a bound wallet. It is a count of the code's requests, exact for that case; an order with more payees, more closing issues or a policy file reads more. It was not counted on GitHub itself.

| Word | Token carried by | Requests read | Requests written | Comments made | Tokens GitHub signs | Jobs |
| --- | --- | --- | --- | --- | --- | --- |
| command (`/knos fund`) | the job's own relay | 11 | 1 | 1 | 1 | 1 |
| settle (on the merge) | the job's own relay | 15 | 5 | 2 | 1 | 1 |
| attest (pay) | the job's own relay | 13 | 0 | 0 | 1 | 1 |
| attest (eval) | the job's own relay | 2 | 0 | 0 | 1 | 1 |
| command (`/knos fund`) | the public worker | 11 | 2 | 2 | 1 | 1 |
| settle (on the merge) | the public worker | 15 | 6 | 3 | 1 | 1 |

The job's own relay is the job sending the transactions itself with a fee key the repository keeps (`KNOS_RELAY_KEY`). Without the key the token is posted as a comment and the public worker carries it; the job then reads the worker's log every 3 s for up to 600 s. Those reads use the repository's own token and are not conditional, so each one counts.

### The budget of one deliverable (funded by a comment, paid on its merge)

| | The job's own relay | The public worker | Where the number is from |
| --- | --- | --- | --- |
| Workflow jobs | 2 | 2 | counted |
| GitHub requests with the repository's token, the work itself | 32 | 34 | counted |
| Reads of the relay log while waiting, at the median wait | 0 | 20 | derived: one read every 3 s for the median of merge-to-paid, 26 s |
| the same at the p95 wait (65 s) | 0 | 46 | derived |
| the same when no relay answers (600 s) | 0 | 404 | derived |
| Requests in all, at the p95 wait | 32 | 80 | counted + derived |
| Comments made in the repository | 3 | 5 | counted |
| Comments the public worker adds to its log | 0 | 2 | from the code (`ghrelay.once` logs a carried token at once) |
| Tokens GitHub signs (OIDC) | 2 | 2 | counted |
| Solana transactions | 12 | 12 | measured in the simulator (section 2) |
| Bytes of signed transactions | 8,647 | 8,647 | measured in the simulator (p50) |
| Compute units | 3,546,061 | 3,546,061 | measured in the simulator (mean) |
| Seconds from merge to paid | not timed apart | median 26, p95 65 | recorded on devnet, public program ids: 51 payments in the public relay's log, 2026-10-02 to 2026-10-09 (`docs/bench.json`) |
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
| 1 | 10 | the job's own relay | GITHUB_TOKEN requests an hour | 750 | yes | none |
| 1 | 10 | the public worker | GITHUB_TOKEN requests an hour | 300 | yes | none |
| 10 | 1,000 | the job's own relay | GITHUB_TOKEN requests an hour | 7,500 | yes | none |
| 10 | 1,000 | the public worker | the public relay's pass, at the serial rate recorded | 1,661 | yes | none |
| 100 | 100,000 | the job's own relay | concurrent jobs (Free plan) | 13,292 | **no** | the meter's statement, recomputed from the logs; concurrent jobs (Free plan); GITHUB_TOKEN requests an hour |
| 100 | 100,000 | the public worker | the public relay's pass, at the serial rate recorded | 1,661 | **no** | the public relay's pass, at the serial rate recorded; the meter's statement, recomputed from the logs; the public relay's log comments; concurrent jobs (Free plan); GITHUB_TOKEN requests an hour |

Every limit, for the largest of the three (100 repositories, 100,000 a day), soonest first. The waits it uses are merge-to-paid over 51 payments on the public program ids, 2026-10-02 to 2026-10-09:

| Limit | Whose | Binds at (a day) | From | What lifts it without a program change |
| --- | --- | --- | --- | --- |
| the public relay's pass, at the serial rate recorded (the public worker) | every customer of the public worker | 1,661 | 2 tokens a deliverable, counted as carried one after another; a token taken as the median of merge-to-paid, 26 s (recorded on devnet when the sweep carried one token at a time; it includes the runner's start, so the relay's own share is smaller and one relayer carries at least this many). The sweep now carries up to 4 tokens at once, the tokens of one owner in order (section 6): what that adds is not measured on devnet yet, so it is not counted here | the job's own relay; or several relayers (anyone can run one: the chain takes each token once, whoever carries it) |
| the meter's statement, recomputed from the logs | each buyer and seller, each month | 3,333 | `knos statement --meter` reads at most 100,000 transactions of a month's account, one RPC request each (src/knos/settle/v2/meter.py); a 30-day month, one evaluation a deliverable, one transaction an evaluation. Not a limit on the work: past it the month's account is still the count, and the recomputation from logs is cut short | batching the meter: one RecordBatch token carries up to 100,000 evaluations under one Merkle root, so a month is a few transactions whatever its volume |
| the public relay's log comments (the public worker) | every customer of the public worker | 6,000 | 2 tokens a deliverable, one log comment each (src/knos/proof/ghrelay.py posts a carried token's line at once); 500 content-generating requests an hour (GitHub) | the job's own relay with the repository's fee key (KNOS_RELAY_KEY): nothing is logged by the public worker; or several workers, each logging in a repository of its own (KNOS_RELAY_LOG_REPO) |
| concurrent jobs (Free plan) | the customer's account | 13,292 | 2 jobs a deliverable (counted), each taken as busy for the p95 of merge-to-paid, 65 s (recorded, 51 samples; a job's own time on the runner was not measured apart); 20 jobs at once (GitHub) | a larger plan (Pro 40, Team 60, Enterprise 500); self-hosted runners, which this limit does not count |
| GITHUB_TOKEN requests an hour (the public worker) | each repository | 30,000 | 80 requests a deliverable (26 reads and 8 writes counted, 46 polls of the relay log at the p95 wait); 1,000 an hour for a repository (GitHub) | the job's own relay (no polling); more repositories; GitHub Enterprise Cloud (15,000 an hour) |
| GITHUB_TOKEN requests an hour (the job's own relay) | each repository | 75,000 | 32 requests a deliverable (26 reads and 6 writes counted); 1,000 an hour for a repository (GitHub) | more repositories; GitHub Enterprise Cloud (15,000 an hour) |
| comments made in one repository (the public worker) | each repository | 240,000 | 5 comments a deliverable (counted); 500 content-generating requests an hour (GitHub) | more repositories; or the job's own relay, which posts no token comment |
| comments made in one repository (the job's own relay) | each repository | 400,000 | 3 comments a deliverable (counted); 500 content-generating requests an hour (GitHub) | more repositories |
| the fee key's own account (the job's own relay) | each fee key | 730,944 | 8.46 orders a second for one key that pays the fees (derived by scripts/load.py) | a fee key per repository or per team (KNOS_RELAY_KEY is a repository secret) |
| the fee account of the mint | every customer, every relayer | 14,221,440 | 164.6 payments a second in one mint (derived by scripts/load.py) | K fee accounts, no program change: PayOrder, SettleOrder and Release take ANY token account of the mint that FEE_OWNER owns (order_pay.rs `is_owned(fee_tok, token, mint, FEE_OWNER)`), so `knos relay fee-accounts --k K` makes K-1 more and each order's payments use one of K, chosen by the order (KNOS_FEE_SHARDS, KNOS_FEE_BASE); shown in the simulator on the 2.1 and 2.2 builds; used on devnet with K = 4 by the 4-relay PayOrder run of 8 Oct 2026 (section 4) |
| the Balance, one writable account | each Balance | 19,362,240 | 224.1 fundings a second for one Balance (derived by scripts/load.py from measured compute units and 12M units an account a block) | one Balance per team in place of one per organisation: a Balance's address is the owner's id, the wallet that opened it and the mint, and a funding comment spends the Balance that lists its commenter, so each team's wallet opens its own (`knos balance open`) and lists its own people. The hot account is split by configuration; every Balance keeps its own cap, and no order can take more than its Balance holds |

What this says. The public worker is a convenience for small volumes. The reads of its log that a waiting job makes are what uses up a repository's hourly requests first, and its own two limits are shared by every repository it serves. A customer past them relays in its own job with its own fee key, which removes the token comment, the polling and both shared limits at once. After that the limits are GitHub's, per repository and per account, long before they are Solana's. The fee account of the mint is moved by configuration too: K fee accounts, each order using one (no program change). Of all the bounds a single Balance's is the furthest away.

### Measured, recorded, derived

| What | How it is known |
| --- | --- |
| Compute units, transactions and bytes of an order; paid once, none lost | measured in the local simulator, 1,000 orders (sections 1 and 2) |
| Token verification, funding from a wallet, refund and close on a cluster | measured on devnet, STAGING program ids (not the public ones), 2026-10-04: 200 orders, 0 failures (section 4). PayOrder, funding from a Balance and the meter were not sent in that run |
| Seconds from merge to paid | recorded on devnet, 51 payments (`docs/bench.json`) |
| Requests, comments, tokens and jobs of a word | counted from the code against a stand-in for GitHub; not observed on GitHub |
| Limits of GitHub and of Solana | published by them, read on 2026-10-05 (links below); GitHub says its secondary limits may change without notice, and its page does not say whether the content limit is counted per repository for a workflow's token, which this page assumes |
| Cluster rates, the relay log polling, statement requests, every "binds at" | derived |
| Actions minutes, runner queue time apart from the rest, RPC requests per order, any GitHub limit actually being hit | not measured |

Sources: [GitHub: rate limits for the REST API (60 an hour unauthenticated, 5,000 authenticated, 1,000 per repository for GITHUB_TOKEN, 15,000 on Enterprise Cloud; secondary limits: 900 points a minute, 80 content-generating requests a minute and 500 an hour, "subject to change without notice")](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api); [GitHub: best practices for the REST API (a 304 to a conditional request sent with an Authorization header does not count against the primary limit; wait a second between writes)](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api); [GitHub: Actions limits (concurrent jobs on standard hosted runners: Free 20, Pro 40, Team 60, Enterprise 500; 500 workflow runs queued per 10 seconds per repository)](https://docs.github.com/en/actions/reference/limits); [GitHub: Actions billing (standard hosted runners are free in public repositories; included minutes a month: Free 2,000, Pro 3,000, Team 3,000, Enterprise Cloud 50,000)](https://docs.github.com/en/billing/concepts/product-billing/github-actions); [GitHub: search endpoints (30 requests a minute when authenticated)](https://docs.github.com/en/rest/search/search); [GitHub: OpenID Connect reference (the page that describes the token request; it states no rate limit, and none was measured here)](https://docs.github.com/en/actions/reference/security/oidc); [Solana: public RPC endpoints (100 requests per 10 seconds per IP, 40 for one method; "not intended for production applications")](https://solana.com/docs/references/clusters); [Solana: 100M CU blocks (SIMD-0286), which also states the 12M per-account limit](https://solana.com/upgrades/100m-cu-blocks).

## 6. The relay: where a payment's seconds go, and its queue

### The stages of a payment (recorded on devnet)

From `python scripts/latency_stages.py --rpc https://api.devnet.solana.com --json`, run on 6 October 2026 from 14:58 to 15:06 UTC against the public relay log (drexthealpha/Knos) and devnet: 41 payments of 2 to 5 October 2026. Every payment in it was made by the public program ids (the relay log's payments, read from their escrows' history). Each stage is timed only for the payments whose log line recorded it, so each row has its own n; a stage no line recorded says "not recorded", and no figure here is derived from another row.

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

### The five clocks

"How fast" is five clocks, and they are not added up here. Each row has its own sample and says where it was measured; percentiles of different samples do not add. A target is a target, not a measurement.

| clock | what is timed | measured | n | p50 | p95 | whose wait | target |
| --- | --- | --- | --- | --- | --- | --- | --- |
| work execution | workflow scheduling: the merge to the start of the workflow run | devnet, 5 of 41 payments | 5 | 2 s | 1184 s | GitHub's: starting a runner, and the job. Knos's share is the job's install and its reads | none set: the forge must run a job and sign, so this clock cannot reach zero |
| work execution | evaluation: the start of the run to the token's comment | devnet, 5 of 41 payments | 5 | 16 s | 24 s | GitHub's: starting a runner, and the job. Knos's share is the job's install and its reads | none set: the forge must run a job and sign, so this clock cannot reach zero |
| evidence availability | relay pickup: the token's comment to a relay taking it up | devnet, 5 of 41 payments | 5 | 2 s | 5 s | Knos's own, all of it: a relay finding the token (a pass over the comments every 3 s) | 0 s for a run that relays its own token; otherwise one pass |
| Knos decision processing | `knos decide`, fresh: the token in hand to the provisional receipt | locally, 40 decisions on one machine with the chain simulated in the same process: no network. Not measured on devnet in this row: the devnet sample stands under the table | 40 | 3.0 ms | 5.1 ms | Knos's own, all of it | targets on one machine with no network, not measurements: 100 ms at p95 for the offline decision once the evidence is in hand, 200 ms for a cached one. No target is set for a decision that reads a cluster: that took 4.3 to 32.6 s on devnet |
| Knos decision processing | `knos decide`, cached: the token in hand to the provisional receipt | locally, 40 decisions on one machine with the chain simulated in the same process: no network. Not measured on devnet in this row: the devnet sample stands under the table | 40 | 2.5 ms | 4.0 ms | Knos's own, all of it | targets on one machine with no network, not measurements: 100 ms at p95 for the offline decision once the evidence is in hand, 200 ms for a cached one. No target is set for a decision that reads a cluster: that took 4.3 to 32.6 s on devnet |
| chain inclusion, at `confirmed` | submission: pickup to the block of the first transaction | devnet, 5 of 41 payments | 5 | 2 s | 5 s | the cluster's, and the relay's sends: two verification transactions for a 2048-bit RSA key, then the payment | none set: measured apart, at this commitment level |
| chain inclusion, at `confirmed` | confirmation: that block to the block of the paying transaction | devnet, 5 of 41 payments | 5 | 3 s | 8 s | the cluster's, and the relay's sends: two verification transactions for a 2048-bit RSA key, then the payment | none set: measured apart, at this commitment level |
| chain inclusion, at `finalized` | finality: the last confirmation to the cluster finalizing it | not recorded | not recorded | not recorded | not recorded | the cluster's; no relay waits for it | none set |
| bank availability | not applicable: no bank route | not applicable: no bank route | - | - | - | not applicable: no bank route | not applicable: no bank route |

What was measured on devnet: 41 payments have a whole wait (first table). Only 5 of those 41 carry stage times in their log line, so every devnet row above is 5 payments, and its p95 is the slowest one of them. Chain inclusion is timed to the block of the paying transaction, read at the commitment level `confirmed`, which is the level the relay waits for; no payment's finality was recorded.

What was measured locally: `python scripts/decide_bench.py --write`, run on 2026-10-07: 40 decisions for each row, the chain simulated in the same process (LiteSVM, no network). Machine: Intel(R) Core(TM) i3-10110U CPU @ 2.10GHz, 4 CPUs, Linux x86_64, Python 3.12.3; load average 2.4 when it began (other work shared the machine when that is near or above its CPUs, and every figure is then slower than on an idle one). That is the time Knos's own code takes to decide; on a cluster every read of the chain adds a round trip: four runs of the 0.3.18 command on devnet took 4.3 to 32.6 s each; the 0.3.19 command, once on each of 24 real tokens, took a median of 356 ms offline (a new process for each token, so that figure included loading the rules), 854 ms for the chain check and 9.1 s for the whole precheck ([BENCH.md](BENCH.md), "Decision time").

What is a target and not a measurement: the last column. No decision has been timed on devnet by a benchmark (four `knos decide` runs on real fund tokens of the 0.3.18 release's public rounds took 4.3 to 32.6 s each over the shared public RPC: a first reading, not a sample), no payment has been carried there by the 0.3.18 relay, and the floor stays above zero: a forge must run a job and sign before there is anything to decide ([RELAY.md](RELAY.md), "The floor").

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

The same command runs a second part: `knos.proof.ghrelay.once`, the pass the public worker repeats every 3 s, which now queues what it reads and carries it with the queue's 4 workers. **This too is a local test of the queue, not an end-to-end benchmark**: GitHub and the chain are stand-ins and the clock is the test's own. The 41 payments recorded on devnet above (public program ids, 6 October 2026: p50 25 s, p95 58 s) were made by the serial sweep, before it was on the queue: no figure on this page times the queue on a cluster.

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

What changed after this drill was recorded (0.3.18): a pass reads the comments again every 3 s while a worker still waits for a confirmation, and a free worker carries what is new, so a comment posted meanwhile no longer waits for the slowest token of the pass (`tests/test_relay_speed.py`, on a stand-in chain; not measured on a cluster). The pass itself still returns when its last worker has answered.
