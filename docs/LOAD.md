# Load: many orders open at once

<!-- written by scripts/load.py from docs/load.json; change the numbers there by running it, not here -->

The claim this page tests: 1,000 funded orders open at once, each settled in under a minute of submission, with no order paid twice and none lost. The second half (paid once, none lost) is measured. The first half (a minute) is derived from what was measured, and holds or does not hold depending on how many relayers carry the tokens; the table below says which.

Everything in the first three sections was **measured in the local simulator** (LiteSVM, the same virtual machine a validator runs, with the test builds in `tests/fixtures`). **Compute units are exact**: a cluster charges the same program the same units. **Wall-clock time on a cluster is derived** from those units and Solana's published limits; it was not observed.

## 1. Paid once, none lost (1,000 orders)

`python scripts/load.py --local 1000` on 2026-10-04 (seed 314). 1,000 orders on 1,000 different repositories and issues were funded from one Balance by tokens the harness signs with the test key, and all were open before the first was paid. They were then paid in a shuffled order, four in five to one payee and one in five to two. Every 10th fund token and every 10th pay token was sent a second time at once; every 50th order's fund token and pay token were sent again after the order had closed.

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

The measured builds: `knos_oidc_v2_test.so` sha256 `0eabd34789c3dbbc`, `knos_pay_v2_test.so` sha256 `70f6f6097052b0d4`.

## 2. What one order costs

| Stage | Transactions per order | Compute units per order p50 | p95 | max | Largest transaction (CU) | Bytes per order p50 | Largest transaction (bytes) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Token verification (knos_oidc), two tokens | 10 | 3,280,855 | 3,314,293 | 3,388,219 | 870,382 | 7,091 | 1,196 |
| Fund (FundOrderBalance) | 1 | 133,965 | 140,235 | 147,753 | 147,753 | 748 | 748 |
| Pay (PayOrder) | 1 | 172,319 | 243,901 | 261,850 | 261,850 | 808 | 1,006 |

What each number is:

- **Stage.** An order needs two tokens, one that funds it and one that pays it. *Token verification* is every knos_oidc transaction for both: the token written into its account in pieces, then the RSA signature checked in steps. *Fund* and *Pay* are the one knos_pay transaction each token is then handed to.
- **Transactions per order.** Successful transactions of that stage for one order. Refused duplicates are not counted here.
- **Compute units per order.** The sum, over those transactions, of what the runtime reports each consumed (the whole transaction, the programs it calls included). p50, p95 and max are over the orders (nearest rank).
- **Largest transaction.** The most one transaction of the stage consumed; a transaction may use 1,400,000. And the most one weighed, signatures included; a cluster takes 1,232 bytes.
- **Bytes per order.** The sum of the signed transactions' sizes.

## 3. What that allows on a cluster (derived)

Solana's limits: a block holds 100M compute units (60M until SIMD-0286; mainnet has had the larger blocks since 29 July 2026, devnet since earlier), the transactions that write any one account may use 12M of a block, and a block is produced every 400 ms. Sources: [Solana: 100M CU blocks (SIMD-0286), which also states the 12M per-account limit](https://solana.com/upgrades/100m-cu-blocks), [Agave's block cost limits (development branch)](https://github.com/anza-xyz/agave/blob/master/cost-model/src/block_cost_limits.rs), [Solana: slots of 400 ms](https://solana.com/docs/core/transactions/confirmation). The two sources disagree on one figure: Solana's page says the per-account limit stays at 12M, while the development branch of the Agave validator carries 24,000,000 for that constant (read on 4 October 2026). This page uses 12M, the published figure for the live clusters; with 24M the per-relayer, per-Balance and fee-account rates below double.

One order costs 3,603,217 compute units in all (the mean of the measured orders). The accounts that every transaction of a stage writes, and so the ones that cap it:

- **Token verification (knos_oidc), two tokens**: the relayer's own account, which pays the transaction fee (one per relayer).
- **Fund (FundOrderBalance)**: the Balance's side account (one per funder); the Balance's token account (one per funder); the funder's Balance (one per funder); the relayer's own account, which pays the transaction fee (one per relayer).
- **Pay (PayOrder)**: the fee account (FEE_OWNER's token account of the mint) (one per mint, for every relayer and funder); the relayer's own account, which pays the transaction fee (one per relayer); the relayer's token account, where its tip arrives (one per relayer).

So there are three points of contention, and the shared vault is not one of them: each order's money is in its own token account, which only that order's transactions write.

1. **A relayer's own account.** Everything a relayer sends writes the account that pays its fees, so one relayer fits 12M units in a block: **8.33 orders a second**, verification included. Verification is nearly all of it, and it is the only stage more relayers speed up.
2. **The fee account.** Every PayOrder of a mint writes the one fee account, whoever relays it: at most **162.5 payments a second** in that mint, however many relayers there are.
3. **A Balance.** Every order funded from one Balance writes it: at most 223.8 fundings a second per Balance. Orders funded from different Balances, or by wallets, do not share it.

Time for 1,000 orders submitted at once, all from one Balance, if the block held nothing else and was packed perfectly:

| Relayers | Blocks (100M) | Seconds | Orders a second | Bound by | All settled within a minute | Seconds with 60M blocks |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 301 | 120.4 | 8.3 | the relayers' own accounts | no | 120.4 |
| 4 | 76 | 30.4 | 32.9 | the relayers' own accounts | yes | 30.4 |
| 16 | 37 | 14.8 | 67.6 | the block | yes | 24.4 |

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
