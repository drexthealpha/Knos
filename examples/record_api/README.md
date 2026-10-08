# A supplier's record as a paid lookup: pay, then the JSON

A small server anyone can run. **Knos hosts none**: whoever runs it is its seller, and its price is its own. It
sells one thing, the lookup of a supplier's record ([docs/RECORD.md](../../docs/RECORD.md)), for 0.10 test USDC,
paid through the proposed x402 `knos-order` scheme of [`examples/x402_attested`](../x402_attested)
([docs/X402.md](../../docs/X402.md), "Record: a lookup priced for machines"). The record file itself stays free.

    python -m pytest -q tests/test_record_api.py        # two stand-in agents, the program itself, in LiteSVM
    python -m knos.record_api offer.json --records docs/records --memory .record-api --port 8402 --key operator.json
    python -m knos.record_api offer.json --health        # can it answer, does it sign, what is promised (nothing)

The second line is `knos record serve`. Revenue from lookups is budgeted at zero until someone buys one. It reads the chain from the RPC URL
every Knos command uses. It has been run against devnet once, on the operator's machine during Knos's own release
run (0.3.19): a wallet of that run [funded a pack](https://explorer.solana.com/tx/2Z9NtBn78XRfLaY928d34qZQxTFxZrGDxcEbBjwpWm9bqjTjcNgPtSrtFZDC3snMCvuWpWWPWqYnVWRkjZSj5rrd?cluster=devnet)
at the public knos_pay and got lookup 0 of 50; the same call again and another wallet's call got `402`. The order
stays in escrow until its deadline, because no judge for lookups exists.

| path | price | answer |
|---|---|---|
| `GET /records/<slug>.json` | free | the record file, as published |
| `GET /lookup/<slug>` | 0.10 test USDC | `402` with the order to fund; with a signed call, the record, what was served, and the answer |
| `GET /orders/<order>` | free | how many lookups the order bought and used |
| `GET /health` | free | whether it can answer, whether it signs, what its operator promises |

## What the paid answer adds

The free file is unsigned and says the day it was built. The paid answer ([docs/RECORD.md](../../docs/RECORD.md),
section 5) adds three things, and `knos record verify answer.json` checks it with no network:

- **Signed freshness.** With `--key` the operator signs the record's hash, the cluster time and slot it read, and an
  expiry. Without a key the answer says it is unsigned. Past its expiry it is stale.
- **A summary.** Every count as `k` of `n` with a 95% Wilson interval, the same for every supplier. No score.
- **History the supplier grants.** `--history <folder>` and `--suppliers <file>`: per-buyer breakdown, disputes and
  appeals, corrections, time to accept. A field is released only against the supplier's signed grant to the paying
  wallet (header `Record-Grant`, written by `knos record grant`). Without one it reads `not granted`.

The paid answer has been tested in the simulator; the one devnet run above was before it existed.

## How a call is paid

1. The caller asks with `Attested-Payer: <its wallet>` and gets `402` with a `PAYMENT-REQUIRED` header: the
   `knos-order` requirement, and beside it `extra.record` (the price, the lookups in a pack, the words to sign).
2. The caller checks it against its own limits (the program, the token, the most it pays, the terms' hash, the fee)
   and funds the order (`FundOrderWallet`). The money is in escrow.
3. The caller signs `knos-record:<order>:<n>:<slug>` with the wallet that funded the order, `n` counting that
   order's lookups from 0, and asks again with `PAYMENT-SIGNATURE`. It gets the JSON.

One order buys fifty lookups, not one. The smallest order `knos_pay` takes is 5.00, so a single order of 0.10 is
refused by the program (the test shows it). A pack costs 5.00 plus the order's fee: 0.05 under knos_pay 2.2, and
0.40 under the build that runs at the public ids until that upgrade executes.

## What is refused

- **A replayed payment.** A signed call whose `n` was already served. The count of each order is kept in the memory
  engine (`--memory`), so a server started again does not sell a lookup twice.
- **Another wallet's call.** An order's address is public. Only the wallet that funded it can spend it.
- **A call for another record, an order for another resource, an order with too little time, the fifty-first lookup.**
- **A record that is not there** gets `404`, and nothing is charged.

## When the seller is paid

The escrow pays the seller when the order's pinned judge signs an acceptance (`PayOrder`), the pack whole, and
returns everything to the caller after the deadline when none arrives (`RefundOrder`). The test runs both.

## What is not built

- **A judge for lookups.** No workflow exists that signs "these lookups were served". In the test a test key that
  only a test build trusts signs the acceptance. Until a judge exists a seller is paid only if the caller's chosen
  workflow accepts, so this is a demonstration of the flow and not a way to earn.
- **A refund of unused lookups.** `PayOrder` pays the order whole.
- **Netting across orders**, and any price below a pack.
- **A binding of a supplier to its key.** The operator's `--suppliers` file says which key a supplier grants with.
- **An availability promise.** The answer states the operator's: none.
- **A record built fresh for each lookup.** The server signs the files it was given and the time it read the chain.
- **A hosted server.** The one run on devnet was the operator's own, with its own wallets. Outside callers: 0.

## The offer file

What `knos.record_api.offer(...)` returns, as JSON: the seller's wallet and GitHub id, the token, the repository id
and issue the orders are scoped to, the workflow repository and commit that judges them, and the terms.

    python -c "import json; from knos import record_api as r; print(json.dumps(r.offer('<seller wallet>', <GitHub id>, '<mint>', <repository id>, <issue>, '<owner/workflows>', '<commit>', '<terms JSON>', url='http://127.0.0.1:8402')))" > offer.json
