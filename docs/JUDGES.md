# For judges: one page

**The neutral meter for AI agent work: neither side keeps the count.**

Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check.

The claim: two parties who distrust each other compute the same bill from evidence a third party signed, and the
program releases the money on that signature.

Why Solana: Money is released with no custodian, and the count is anchored where neither side can alter it.
A receipt verifies with no chain; the chain is for the money and for the root.

## Six things judged, one link each

| judged | in one sentence | evidence |
|---|---|---|
| How well it works | A Solana program checked GitHub's signature itself and released the payment, on the public program ids, in test USDC. | [the paying transaction](https://explorer.solana.com/tx/59AfaYHTvWHhbAhiiNHCbCfEcGCxG1kCydJwfRNjZqry9bCnMF3ox6bd4P7favA9hjgzB5nk283g2Mdq3LruyNWV?cluster=devnet) |
| Potential impact | A buyer paying per merge on our sample would have paid for 30 pull requests whose checks failed. | [the measurement](BENCH.md) |
| Novelty | The black-box check refused all 63 cheating submissions, and plain CI passed 56 of them. | [the tamper benchmark](TAMPER.md) |
| User experience | A buyer pastes an invoice on the first screen and gets the count, with no install and no sign-up. | [the site](https://drexthealpha.github.io/Knos/) |
| Open source and composition | The code is MIT, and the verifier is a separate program that other Solana programs call. | [how to call it](COMPOSE.md) |
| Business plan | Knos earns one fee, on value released against a signed acceptance, and the supplier never pays. | [the price book and its costs](MARKET.md) |

The fee the public program ids charge today is read from the chain and shown on the site's pricing page; this
page prints no rate.

## Days to approve, not seconds to pay

From merge to paid took 25 seconds at the median, over 42 payments on devnet. A buyer does not wait for that. A
buyer waits for a person to approve the invoice, and that wait is the argument over whose count is right. Knos is
built to shorten that wait. It has not measured it with any buyer, so no figure for it is given here.

## What is not real yet

1. Money: Solana devnet and test USDC only. Mainnet is not touched.
2. Buyers: 0 interviews, 0 letters of intent, 0 paying customers, 0 revenue.
3. Outside use: 0 outside funders and 0 outside repositories. One outside payee was paid 3 times, on tasks Knos funded.
4. Outside checks: no security review, 0 reproductions by anyone else, 0 outside programs reading the verifier.
5. Neutrality: one person holds every key, and that person is the whole team.

Each count is read from [NUMBERS.md](submission/NUMBERS.md), and every limit is in [DISCLOSURE.md](DISCLOSURE.md).
The same transaction told in steps is [STORY.md](STORY.md); every other document is on [the map](README.md).
