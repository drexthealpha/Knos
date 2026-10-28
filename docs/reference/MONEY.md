<img src="../../web/brand/mark.svg" height="40" alt="Knos">

# Money: one fee config, graduation, splits, x402 and the revenue data

**In plain words.** Every Knos fee lives in one file, and the code reads it from there. When a claim passes, money for its next step and its first orders is held on devnet until the proof passes. When the work is accepted, everyone who helped is paid their share at once.

What is held, released and charged now: [the money page](https://knos.onrender.com/money).

How the money moves:

1. A verdict passes (works, wanted, makeable).
2. It opens held money for the milestone and a pre-order pool: knos_pay orders.
3. The referee workflow signs acceptance: the split is paid to the researcher, agent, lab and referee, and the fee goes to the treasury.
4. If the deadline passes first, the money and the fee go back to whoever paid.

**Revenue today: 0.** Knos runs on Solana devnet only. Every fee the program takes there is test money, and nothing
has been sold.

Every price below says whether it is **live** (the deployed program charges it on devnet), **proposed**
(the price book, nobody pays it yet), **decided** (a price set on 14 Oct 2026 or 23 Oct 2026; nobody pays
it yet) or a **placeholder** (a number not set yet).

## The one fee config: `config/fees.yaml`

Code reads it only through `knos.money.fees_config`:

```python
from knos.money import fees_config
cfg = fees_config.load()                 # validated; KNOS_FEES names another file
cfg.fee("bounty", 20_000_000)            # 60_000: base units of a 6-decimal mint, exactly knos_pay's order fee
cfg.bounty(20_000_000)                   # amount, fee, total the funder pays, fee_to "treasury"
cfg.price("verification", 10, used=0)    # count-based lines take the month's free uses first
cfg.split(100_000_003)                   # the contributor split, rounded as the program rounds
cfg.task_package(2_000_000_000)          # Knos's share and the maintainer's
cfg.platform("bounty_platform", 20_000_000)   # the 5% bounty fee: 60_000 on chain + 940_000 off chain = 1_000_000
cfg.decided()                            # every decided starting price, with its date and source
cfg.placeholders()                       # every number not set yet
```

The live lines repeat numbers compiled into `knos_pay` (`knos.settle.v2.pay`) and the proposed lines repeat the price
book (`knos.billing`). The loader **refuses** the file when one of them differs, so the file, the program and the price
book cannot drift apart: changing a live fee means upgrading the program through the multisig.

A decided line must say when it was decided, why, and its source, and it can never be marked live.

| line | rate or price | status | who pays, and where it goes |
|---|---|---|---|
| verification | 0.002 USD each after 100,000 a month; public repositories and self-hosting free | proposed | the buyer of hosted checks |
| payout | 0.30% of the amount, at least 0.05 | live | the funder, on top; the program sends it to the treasury at release |
| bounty (on chain) | 0.30%, at least 0.05 (a bounty is a work order) | live | the funder, on top; to the treasury; returned on a refund |
| bounty fee | 5% of the bounty, the 0.30% on-chain bounty fee included | decided | the funder; 0.30% by the program at payout, the rest (4.70%) invoiced off chain |
| lab order | 3% of the order, the 0.30% on-chain payout fee included | decided | 0.30% by the program at release, the rest (2.70%) invoiced off chain; who bears it is not decided |
| funding | 0 at funding: the program holds the payout fee and takes it only at release | live | nobody, until a release |
| graduation | 0.50% of the money released after graduation | decided | by contract, off chain, until a knos_pay build carries it |
| task package | 10% to Knos, 90% to the maintainer | decided | the lab that buys the package; off chain, by contract |
| x402 check | 0.02 USD each, in devnet USDC (test money), sold in packs of 250 (one 5.00 order) | decided | the agent that calls `/checks` |
| demand check | 10 a month free | decided | nobody; the monthly count is not enforced yet |
| deep demand check | 500 USD each, by card | decided | the company, from the day it exists; no company is formed yet, so nobody is charged |
| Ready brief, proof page | free | decided | nobody |
| release | 1% of money released on verified proof; the solver keeps 100% | decided | the company (the funder), on top, with the payment costs; on chain only after the timelocked upgrade, and the program charges 0.30% until then |

The product's prices (demand check, deep demand check, Ready brief, proof page, release) were decided on 23 Oct
2026. Deep checks are charged by card once the company exists; nobody is charged today. The company pays the payment
costs on top of the 1% release fee. The solver keeps 100% of what they are paid.

Cards cover milestones up to 500 USD; larger milestones are paid by bank transfer or in USDC.

The 1% is not live: the deployed `knos_pay` charges its payout fee, 0.30%, until a timelocked program upgrade carries
the new rate.

### Why the 5% bounty fee is not on chain (it needs a program upgrade)

knos_pay's fee is compiled into the deployed program: 0.30% of each release, at least 0.05 (`knos.settle.v2.pay`
FEE_BPS and FEE_MIN). The loader refuses a live line that says anything else, and no config can change what the program
takes.

So the bounty fee is modelled as two parts of one 5%: the program takes its 0.30% on chain at payout (the live `bounty`
line, sent to the treasury), and the rest is a `bounty_platform` line marked decided, collected off chain by invoice to
the funder. The funder pays 5% in all, not 5% on top of 0.30%.

The lab order fee works the same way on the `payout` line. Taking the whole 5% (or 3%) on chain needs a **program
upgrade** of knos_pay through the Squads vault; until then `cfg.platform(kind, amount)` says how much of each fee is on
chain and how much is off chain.

An order on an owner's Plan pays a lower on-chain rate, so its off-chain rest is larger; when the 0.05 floor alone
exceeds the whole fee, the off-chain rest is 0. Nothing collects the off-chain part today: there is no invoicing code,
and on devnet all of it is test money.

**The treasury** is the program's fee owner, `4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo`, a vault of the Squads
program. Fees land in token accounts it owns (`pay.fee_accounts(mint)`: the associated account and any seeded
shards). Only a Squads proposal of the vault moves them; nothing in Knos signs for it.

Out of each fee the relayer who
sends the payment keeps its tip (0.05, or 0.30 on a payee's first payment); the rest is the fee owner's
(`knos.billing.release_split`).

## Contributor splits

Every payout is shared among four roles, by fixed basis points (`splits.roles`, decided 14 Oct 2026: 60 researcher /
25 agents / 10 labs / 5 referees):

| role | basis points |
|---|---|
| researcher | 6000 |
| agent | 2500 |
| lab | 1000 |
| referee | 500 |

One knos_pay order pays one to four payees, so the split is the payee list of the referee's pay token
(`knos.splits.payees`). The program divides the amount: each share rounded down, the last payee the rest. A role that
took no part leaves its share to the others in proportion.

Nobody forwards money after the fact: the split is paid in the one transaction that pays the order.

## Graduation: the held milestone money and the pre-order pool

`knos.graduation.plan(verdict, claim_id=, repo_id=, amount=, contributors=)` refuses any verdict that did not pass all
three checks of the referee. For one that did, it plans two kinds of knos_pay work order:

- **the held milestone money**: a funder locks `amount` for the next milestone (the payout fee on top). The research
  repository's pinned `prove.yml` run, signed by GitHub and verified on chain, pays it to the split. After the
  deadline anyone can send RefundOrder and the funder gets the amount and the fee back.
- **the pre-order pool**: each buyer funds one order in the claim's pool scope. `graduation.pool(ledger, plan)` reads
  the pool from the chain (distinct buyers, amount locked in open orders still in time, and whether the bar of N buyers
  and X locked is met). It counts only the plan's own orders, in the mint the makers accept: the scope is public, so an
  order funded there with a worthless mint, other terms, another referee or other pinned workflows is listed as ignored; `graduation.demand_orders` hands it to the referee's demand book.

Both are **private** orders (`F_PRIVATE`, salted scope): they store no repository and no issue, so a claim never shows
up as a bounty on a GitHub issue. The salt is `sha256("knos-grad:" + claim id)`, derived from the public claim id on
purpose, so anyone can find a claim's held money and pool.

No token here pays backers out of revenue: a pre-order buys the product, and held money funds a milestone or comes
back.

### On devnet (13 Oct 2026)

`python -m knos.graduation.devnet` ran on the public knos_pay program with SYNTHETIC claims and a test mint of its own
(`CP6GfXRQeVhdgQHpLZ3Bb4CQwopFsdb3XSuwwdagoPJa`, 6 decimals, no freeze authority), from the wallet
`2x1YKK5uHktXLkg5aq6Z5nRV95AYg62dwLNp5YEAYBHu`:

| step | signature |
|---|---|
| claim A: held milestone money, 50 test units | `2G9C94R5rw66HxwRPRoenHMpuZPxHtu32w6fk2UixWdroBW4kBULaMEZVzk2i985pbbqEy7CuQknMpAw3WA2LrFP` |
| claim A: pre-order, 20 test units | `3A7NNa5M5wAHUSbwiHmdxYM7bySvxG3ykdSijCsYwsE4pQcwGtq5hsvmNtMgdCzKUqXrLGkWAxdmA8AottBQkJXu` |
| claim A: pre-order, 10 test units | `5yfwjKJSupwc93TsCyrXSZ8deax5PYn3u8oCCRntPKGXKqSJRHja8gp75dRgU1AifvS3LDEh5r6Htv8s5cFP5ka6` |
| claim B: pre-order with a 60 s deadline | `wf7AxxrXXAJT26BbX8WJwzNYZBn1ogxs6AtdVRRZ2eXYFEYrcpHYs3docaLw45TsGSK2bojxM578WLc9gnf8YwW` |
| claim B: refunded by another relayer, amount and fee | `4hoBffMGkCzDKWfNdr95VJd9odDF26RV3fps994B9tmtGRxEncQaqujXQuKmdqW7dkbc8MNtvfjMk6DdJ54RAwcs` |
| claim B again: pre-order | `62xKk3w85zrFNawRK97JTy7MMgSUnjCn8pjjUaTagnWxqNbdGj3A8VK2BNEYaRY7dPF1fQ1rVyihBNY4w89Pq4cJ` |
| claim B again: refunded by the sample | `2iHXMseNnNXhD3zcp9tKAtqqFv7wDzFdUsF6Fm7ZCZ3vKchvQFiYAdLRnjFffF5nqH2DmuH3cu2zictJkMv4ueNZ` |

The first refund of claim B was sent by a relayer the sample does not run, before the sample's own: anyone may refund an
order past its deadline. The payout of claim A needs a GitHub-signed token from the referee repository; the sample does
not fake one.

The payout path, with the four-way split and the fee, runs against the program's test build in LiteSVM
(`tests/test_money_graduation.py`).

## For agents: MCP, Hermes and x402

`knos.money.agent` has three tools in the MCP shape: `knos_fees`, `knos_graduate` and `knos_preorder`. They quote and
plan, and return the unsigned instruction the paying wallet signs itself; they never read a key. `agent.call(name,
args)` answers one, for an MCP server or a Hermes plugin (`ctx.register_tool`).

`python -m knos.money.x402 --plans <plans.json> --mint <mint>` runs the x402 endpoint (anyone runs it;
Knos hosts none), on the proposed `knos-order` scheme of [X402.md](X402.md):

- `GET /fees` and `GET /pool/<claim>`: free.
- `GET /preorder/<claim>`: `402` with a requirement to fund a pre-order in the pool; asked again with
  `PAYMENT-SIGNATURE` naming the order, `200` with the state `escrowed` once the chain shows it held in that pool.
- `GET /checks`: `402` for a pack of paid checks (the smallest order is 5.00, so a pack is 250 checks at 0.02); each call is signed by the funding
  wallet over `knos-check:<order>:<n>`, and a replay or a stranger's call is refused. The count of each order is kept
  in a state file (`--state`), written before the call is answered, so a restart does not sell a call again.

## The revenue data

`python -m knos.money.revenue --out <file>` writes the revenue data, in three parts kept apart:

- **measured**: the treasury's fee accounts and the sample's held money and pool, read from devnet when the file was
  written. All of it is test money. A part that was not read says so; it is never guessed.
- **schedule**: this config, each line with its status.
- **model**: revenue for volumes the reader types, at the config's rates. It is labelled a MODEL, its inputs start at
  0, and a model with no inputs says 0. Its payout line is a lower bound: the floor is charged on each release, and the
  model sees only the month's total and count. Bounties and lab orders are typed twice: in the value released (their
  on-chain 0.30% is in the payout line) and on their own lines, which count only the off-chain rest of the 5% and 3%.

## Knos Cloud credits

Everything stays open source (MIT) and self-hosting stays free. Knos Cloud would sell credits for hosted verification:
runners, sealed-test storage, receipts, and Gate for private repositories. The tier prices and the 10% bonus credit are
decided (14 Oct 2026); what one credit is worth (0.002 USD) and what each use consumes are still placeholders, so the
credit counts are too:

| tier | USD a month | USD of credit a month (10% bonus) | credits a month (placeholder) |
|---|---|---|---|
| Starter | 20 | 22 | 11000 |
| Pro | 100 | 110 | 55000 |
| Team | 200 | 220 | 110000 |
