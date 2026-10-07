# Agent pays agent in 60 seconds: the shots

One terminal split in three (buyer, seller, evaluator) and one line of chain state under it. Every command is in
[README.md](README.md); every number on screen is one `tests/test_agent_pays_agent.py` asserts. Recorded on the
simulator unless the release run has made the devnet run; the caption says which, and says test USDC.

| # | seconds | on screen | caption (12 words at most) |
|---|---|---|---|
| 1 | 0 to 6 | `seller.mjs` starts; its board shows one task, 20.00 test USDC | A seller agent lists work. |
| 2 | 6 to 14 | `buyer.mjs`: `GET /tasks`, then the `402` with `scheme: knos-order` | The buyer gets a price: an escrow, not a transfer. |
| 3 | 14 to 22 | the funding transaction; chain line: order `escrowed`, seller balance 0.00 | The buyer funds the order. Nobody holds its key. |
| 4 | 22 to 30 | the delivery: `["apple","fig","kiwi","pear"]`; seller balance still 0.00 | Delivered. Still not paid. |
| 5 | 30 to 38 | `evaluator.mjs` prints `accepted: true`; the signed acceptance lands; seller balance 20.00 | A third party signs. The program pays. |
| 6 | 38 to 46 | run 2, `seller.mjs --wrong`: the delivery keeps its duplicates; `evaluator.mjs` prints `accepted: false` | Wrong work. No signature. |
| 7 | 46 to 54 | a signature from another workflow: refused; a refund before the deadline: refused; seller balance 0.00 | Nothing else releases it. |
| 8 | 54 to 60 | the clock passes the deadline; `refund`; buyer balance back to 100.00 | At expiry the buyer has everything back. |

Motion: the chain line changes state once per shot and nothing loops. Do not show: a wallet address before shot 3,
any figure about x402's volume (it is not Knos's), or the word "mainnet".
