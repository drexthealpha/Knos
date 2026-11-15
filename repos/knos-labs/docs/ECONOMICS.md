# Economics of Knos jobs

Every number here is either a rule in the escrow's code or comes from a command you can re-run. Devnet and Moderato
numbers are testnet numbers; mainnet fees will differ.

## Who pays what

| | buyer | worker | Knos |
|---|---|---|---|
| job accepted, released on proof, or review window passes in silence | the price | the price minus the fee, in the releasing transaction | max(2.5%, 0.05 USDC), fixed at init |
| job rejected inside the review window | nothing (full refund) | nothing | nothing |
| nothing delivered by the work deadline | nothing (full refund) | nothing | nothing |
| chain fees | post, accept or reject | claim, deliver | none |

Knos never holds job money: the price sits in a program-owned vault (Solana) or the contract (Tempo), and only the
escrow's rules move it. The fee goes to a fixed fee account set when the escrow was initialised.

## Minimum job and fee (0.3.4)

The escrow refuses a job under **1 USDC**, and the fee is **max(2.5%, 0.05 USDC)** (0.3.6; it was 5%). So a 1 USDC job pays Knos 0.05 USDC,
and a 10 USDC job pays 0.25 USDC. The escrow also refuses a job over its per-job cap, and refuses new posts while it
is paused.

## Per-job network cost and margin (measured 1 Oct 2026)

Each job below was a 1 USDC paid-on-proof job: post (naming a verifier), claim, deliver, then verify_release. Five
jobs were run on each chain.

| | Solana devnet | Tempo Moderato |
|---|---|---|
| transaction fees, all steps | 20,000 lamports = $0.0030 at an assumed $150/SOL | 1,170 pathUSD units = $0.00117 |
| job account rent (buyer, at post) | 1,752,600 lamports = $0.263 at $150/SOL (not reclaimed in 0.3.4) | none |
| paid by Knos (the verifier's transaction) | $0.00075 | $0.00023 |
| **Knos margin per 1 USDC job** | **$0.0493** | **$0.0498** |

The SOL price is an assumption, not a quote: at $100 the margin is $0.0495, and at $250 it is $0.0488. If Knos also
paid the buyer's side, as it does for its own task feed, the Solana job account's rent would exceed the 0.05 fee.
Closing settled job accounts to reclaim rent is listed under "Next" in the CHANGELOG.

## Chain fees (measured)

- Solana: one signature per transaction, 5,000 lamports, plus rent for the 153-byte job account, which the buyer pays
  at post. Run `knos bench jobs --live` to see each step on devnet.
- Tempo Moderato: the worker pays its own gas in pathUSD; the 0.3.1 measurement recorded about $0.0002 for claim and
  deliver and $0.00004 for accept (measurements in the repo history; re-run `knos bench jobs --tempo`).

## Settlement time (measured 1 Oct 2026, from Lagos to public RPC endpoints)

| step | Solana devnet, waiting for `finalized` | Solana devnet, `confirmed` | Tempo Moderato |
|---|---|---|---|
| post | 2.2 s | 2.6 s | 5.5 s (incl. approve) |
| accept (worker paid) | 2.6 s | 3.0 s | 2.6 s |

These are wall-clock times of the whole client call (reads, blockhash, send, wait). On devnet today `finalized` costs
nothing extra over `confirmed` (they are within 2 slots), so Knos waits for `finalized`, which cannot roll back.

## The worker's side

A worker sells finished work, not model access: it runs its own model on its own key (Knos never resells model
access). Its margin is the price minus its model cost and two transaction fees. Work that fails the brief's own checks
is never delivered, so a worker spends nothing on chain for a job it cannot do; the job's deadline then refunds the
buyer.

## Sibyl Pro, from the same payment

A buyer whose job is accepted has Sibyl Pro (memory with no cap) for the 30 days after that payment: Knos buys it from
the fee, and a later accepted job extends it (`knos jobs sibyl`). The same holds for Knos Pro and each Team seat. On
devnet and testnet the purchase is simulated and labelled; on mainnet it is built and locked until Sibyl Labs confirms
resale. On a small job the fee is less than a month of Sibyl Pro, so Knos pays the difference: a customer-acquisition
cost, not a margin.

## Where someone could be worse off

- A buyer can reject delivered work inside the review window and get a full refund. The rejection is public on chain
  (every agent's rejected count is in its record), so workers can avoid serial rejecters, but there is no appeal.
- A worker that claims and never delivers blocks the job until the deadline; the buyer waits, then is refunded.
- If the relay holding a deliverable disappears, the bytes are lost; the money still follows the escrow's rules.
- Testnet only: devnet USDC and pathUSD have no value. Mainnet is locked and capped at 500 USDC per job until an
  external audit.
