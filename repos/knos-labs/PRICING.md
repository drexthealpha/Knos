# Pricing

## Jobs

**2.5% of the price (at least 0.05 USDC), only when the work is accepted or proven** (or the review window passes in silence). Nothing on a rejection or a
refund, nothing to post, nothing to work. The fee is set in the escrow program and contract, and is the same for
everyone. Details and measured chain fees: [docs/ECONOMICS.md](docs/ECONOMICS.md).

**Sibyl Pro comes with every payment.** A buyer whose job is accepted has Sibyl Pro for the 30 days after it: Knos buys
it from that one fee (simulated on testnets; on mainnet it is built and locked until Sibyl Labs confirms resale).

## Margin per job (measured 1 Oct 2026; fee max(2.5%, 0.05 USDC) since 0.3.6)

| per 1 USDC job | Solana devnet | Tempo Moderato |
|---|---|---|
| Knos fee | 0.05 USDC | 0.05 USDC |
| network cost paid by Knos (the verifier's transaction) | $0.00075 (at an assumed $150/SOL) | $0.00023 |
| **Knos margin** | **$0.0493** | **$0.0498** |

Above 2 USDC the fee is 2.5%, so a 10 USDC job earns 0.25 USDC for the same network cost. How these numbers were
measured: [docs/ECONOMICS.md](docs/ECONOMICS.md).

## Coding-team plans

| plan | who | price per 30 days / per year |
|---|---|---|
| **Free** (MIT), forever | solo, offline; team registries of up to 3 keys; any public open-source repo | 0 (Sibyl's free tier, 5 MB) |
| **Pro** | individuals | **22 / 208 USDC, Sibyl Pro included** |
| **Team** | private registries with 4+ keys | **32 USDC per seat, Sibyl Pro included** |

What each plan includes:

- **Free:**
  - shared Sibyl memory built from your agents' past sessions and your commits;
  - file claims and the edit guard in every host, and the commit guard;
  - a team registry on Solana of up to 3 keys, with no server;
  - the Python SDK.
- **Pro adds:**
  - Sibyl Pro: no 5 MB cap, `knos learn` and `knos lint` (Sibyl's self-learning and memory linter);
  - the spend meter across Claude Code and Codex, and one cap across agents;
  - agent budgets enforced by the chain (Tempo Keychain limits per period, Solana delegates);
  - agent wallets for MPP and x402 payments.
- **Team adds:**
  - Sibyl Pro for the paying wallet, with every seat paid for recorded;
  - chain budgets for every agent;
  - private registries past 3 keys, and a records policy;
  - priority fixes.

**One payment.** Whatever a wallet pays Knos (Pro, a Team seat, or a job's fee), Knos buys that wallet Sibyl Pro for
the 30 days after the payment, from that payment. There is no second checkout and nobody pays Sibyl separately. On
testnets the purchase is simulated (and labelled so); on mainnet it is built and locked until Sibyl Labs confirms resale.

For comparison (read 30 Sep 2026): Sibyl Pro alone is $12 a month, Conductor Teams $60 per user (a different product),
Portkey $49 and Helicone $79 a month.

## Paying

No account and no card. `knos pro buy` prints a payment request and watches the chain for it:

- **Solana**: a Solana Pay link for USDC, payable from any Solana wallet (Phantom, Solflare, Backpack), from any
  country.
- **Tempo**: a `transferWithMemo` of USDC.e or pathUSD to `0x580C2842ec71C432D5d2fc4dDCDf37CE493FbB3A`, with the
  memo `knos pro buy` prints: `knos pro buy --chain tempo`.

The CLI checks the payment against the chain itself, over a public RPC:
- it succeeded;
- it carries this purchase's reference or memo;
- the Knos address received at least the price in an accepted stablecoin.

It then writes `~/.knos/licence.json`, and Sibyl Pro is bought for the paying wallet. Every payment is public on chain.

Paying another way (card, bank)? Write to zulibro1999@gmail.com for a signed licence code: `knos pro activate <code>`.

## Money-back

Within 30 days, send the transaction and the address to refund to (zulibro1999@gmail.com). The refund goes back on the same chain.

## Source

All of Knos is MIT, `src/knos/pro/` included: see [LICENSE](LICENSE).
