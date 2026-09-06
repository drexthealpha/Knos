# Verification

Everything Knos claims, with the command or the link that settles it. If a
row here cannot be checked by someone who does not trust me, it should not
be in this file.

Re-verified 6 September 2026.

## 1. Memory is load-bearing

The claim: there is no second copy of a claim or of anything Knos was told.
Delete the store and the refusal is not degraded, it is impossible.

```bash
python scripts/ablation.py
```

| Arm | Store present | Store deleted |
|---|---|---|
| **Reversed decision: an edit resting on it** | **refused 12/12** | nothing is held |
| **Reversed decision: a purchase resting on it** | **refused 12/12** | nothing is held |
| **Reversed decision: the same edit after reconsidering** | **allowed 12/12** | - |
| **Spend: the same request a second time** | **paid again 0/12** | **paid again 12/12** |
| **Spend: the same request while somebody holds it** | **refused 12/12** | no claim survives |
| Withhold: a second agent asks about claimed work | refused 12/12 | refused 0/12 |
| Guard: an edit to claimed work | refused 12/12 | refused 0/12 |
| Action: a pull request touching a claimed topic | commented 12/12 | commented 0/12 |
| Paid: a bought answer, found by the next agent | kept 12/12 | kept 0/12 |

12 trials, seed 1337, written to `docs/evidence/ablation.json`.

Each arm runs the product's own code, not a reimplementation of it:
`mcp._held` for the withhold, `guard.check` for the edit, the Action's own
`read_claims` and `words` for the comment, and `knos remember`'s exact pair of
writes for the paid path.

Pinned by `tests/test_ablation.py`, which also re-runs the script end to end,
so the published numbers cannot drift away from the code.

Second, older proof of the same thing, kept because it is blunter:

```bash
pytest tests/test_sibyl_is_load_bearing.py
```

It deletes `~/.knos/<repo>/memory.db` mid-test and asserts the hold ends, the
answer disappears, and what the repo can be re-read for comes back - because
that part was never Knos's to lose.

## 1b. The memory decides whether money moves

`knos remember` after a purchase was only half of "nobody here pays twice".
The other half is looking before you buy, and `src/knos/gate.py` is that half.
Three verdicts, one of which costs money:

| The store says | What the agent does |
|---|---|
| somebody holds this topic | **refuses to spend.** The answer would be stale before it arrived |
| this was already bought | **serves it free**, and says where it came from |
| nothing known, nothing claimed | buys it, then writes it back |

Watch it happen, without spending anything, on a topic already in the store:

```
$ npm --prefix agent run bot -- "/brief ETH"
Looking up ETH. If this machine has not paid for it already, it costs $0.01 on Base.
ETH is at $2,452.13, down 2.16% in 24h.
...
Free. This machine already paid for it once (you said so, 2026-09-05), so nobody paid again.
```

And with a claim standing on it:

```
$ knos claim "market brief: ETH"
$ npm --prefix agent run bot -- "/brief ETH"
Withheld. The person you are working with said they are on market brief: ETH
right now, so knos is not the place you find out about it.
...
Nothing was bought. You are on this right now, so a paid answer would be out
of date before it arrived.
```

Pinned by `tests/test_gate.py`, including the one that matters most: a gate
that crashes answers "buy" rather than blocking the product, so a broken gate
can never become a gate that silently spends *or* a gate that stops the agent
working.

## 2. Base mainnet, real USDC

Four x402 purchases by the agent, each paying a live seller and writing what
it bought back into Sibyl. Re-checked against `base.drpc.org` on 6 Sep 2026:
every one is `status: 0x1` with the Base USDC contract
`0x833589fcd6edb6e08f4c7c32d4f71b54bda02913` in its logs.

| Transaction | Block | What was bought |
|---|---|---|
| [`0x80d984…d958c76`](https://basescan.org/tx/0x80d984d2e88332888a595f5476722bca9efbe7850fce4090b02f49154d958c76) | 50898966 | news, $0.001 |
| [`0xce109c…abd9a85e`](https://basescan.org/tx/0xce109c28781fec2ea12b8e115d59b1bfea219434379a30d472cf72b4abd9a85e) | 50898978 | market brief, $0.01 |
| [`0xa8e713…c0466103`](https://basescan.org/tx/0xa8e7135e6c41e6eb8ed5d15b5dbf5aafc5a8f748e9d16e08aa1ae6d9c0466103) | 50900244 | news, $0.001 |
| [`0x3a45e0…2e049a88b`](https://basescan.org/tx/0x3a45e0066fbf764731f98dab3f023ee2a690dc8923f08ae7f9cb4332e049a88b) | 50900265 | market brief, $0.01 |

Check any of them yourself:

```bash
curl -s -X POST https://base.drpc.org -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getTransactionReceipt",
       "params":["0xce109c28781fec2ea12b8e115d59b1bfea219434379a30d472cf72b4abd9a85e"]}'
```

**Why the last two exist.** The first receipts stored a settlement header cut
at 160 characters. Truncated base64 still decodes, to a 34-character string
that looks exactly like a transaction hash and resolves to nothing. That is
worse than no receipt, because it reads as evidence. `buy402._settlement` now
decodes the header and stores the transaction hash itself, and
`tests/test_pay.py` pins it - including a test asserting the old 160-character
cut produces a *different* hash, so the bug cannot come back quietly.

## 3. Virtuals ACP

- Provider, registered and listed:
  [agent `01a05b97-a776-760a-9165-e9893e4091dc`](https://app.virtuals.io/acp/agents/01a05b97-a776-760a-9165-e9893e4091dc)
- Job 75659, sold for 0.01 USDC, in both legs:
  [escrow funded](https://basescan.org/tx/0x756b867b2b1165bfe674025a82d21cd765378a40ab226274bd555abf0065bd64)
  and [provider paid](https://basescan.org/tx/0x95a84c44802d09e38ef920524f947dff0eb5a2fe972054fca97bfd989cbcea59)
- The answer it sold came out of the store, and the sale went back into it:

```
$ npm --prefix agent run bot -- /jobs
1 ACP sale(s), out of knos:

Sold an ACP job for 0.01 USDC. Asked: what does knos withhold?
```

**Honest limit:** the buyer was my own test agent. It is a real job on the
real marketplace with real money and it is not a customer.

## 4. The onchain access record

`Access.sol` records who may read a shared export, so neither machine has to
trust the other's copy. Base Sepolia, because it is optional and off by
default and putting it on mainnet would only cost money to prove the same
thing.

- [Contract `0x955fa320…6E52`](https://sepolia.basescan.org/address/0x955fa320D60D9172CF048141ed7eEE442da66E52)
- [deploy](https://sepolia.basescan.org/tx/0xdcc25ff7460a09a080ec32016b39121b6a34b741f03411bcfdc2ee2a93b31d21)
  · [grant](https://sepolia.basescan.org/tx/0x84e11e21315b51e9e6b6453d226a44bcabf5a80f4c0085ba6f5b56ed169a92b6)
  · [revoke](https://sepolia.basescan.org/tx/0xb3ea6920c0a7bf7fa9dde64e6f0c2275e149f976bf20c909098a2431417adfb4)
- `cd contracts && forge test` - 9 tests

## 5. The Action, having actually run

[Pull request #1](https://github.com/drexthealpha/Knos/pull/1) in this repo.
The check read `.knos/decisions.md`, matched a claim that was standing at the
time, named who held it, and exited 0. The comment is still on the thread.

It cannot fail a build. Every path through `main()` returns 0, and the entry
point catches anything `main()` lets escape:

```bash
pytest tests/test_shared_repo.py -k never_returns_non_zero
```

## 6. Distribution

| Where | What |
|---|---|
| [PyPI](https://pypi.org/project/knos/0.1.6/) | `pip install knos==0.1.6` |
| MCP registry | `io.github.drexthealpha/knos`, 0.1.6, `isLatest` |
| [Glama](https://glama.ai/mcp/servers/drexthealpha/Knos) | listed and scored |
| GitHub | `drexthealpha/Knos`, tag `v0.1.6` |

```bash
python -m venv v && v/bin/pip install knos==0.1.6
v/bin/python -c "from knos.core import Claims, holds; print(holds('the risk guard','guards'))"
# True
```

## 7. What the numbers are not

- **583 PyPI downloads in a week against 1 star and 0 watchers.** That ratio
  is automated traffic: Glama's Docker rebuilds, the registry crawler,
  mirrors, and my own clean-venv checks. It is not evidence of a user, and
  it is listed here so nobody has to discover that themselves.
- **No retained users.** Zero. That is the honest state.
- **The problem, however, is measured.** 100,057 open GitHub issues were
  sampled and classified; 1,254 describe agents colliding on the same work or
  losing decisions between runs. Method and counts:
  [`docs/evidence/`](evidence/). That is evidence the problem is real, not
  that anyone has chosen this answer to it.
- **Two upstream merges**, both from ordinary bug fixes rather than adoption:
  [`caura-ai/caura#1299`](https://github.com/caura-ai/caura/pull/1299) and
  [`drt-hub/drt#1098`](https://github.com/drt-hub/drt/pull/1098).
