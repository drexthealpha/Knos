# Knos

<!-- mcp-name: io.github.drexthealpha/knos -->

[![Knos MCP server](https://glama.ai/mcp/servers/drexthealpha/Knos/badges/score.svg)](https://glama.ai/mcp/servers/drexthealpha/Knos)

**One shared memory for every coding agent on your machine.** Two agents, or
two people, change the same thing without knowing it. Knos is the record of
who is on what — and it **refuses to answer** about work somebody else has
taken, and **refuses the edit** before the write lands.

## See it in one command

```bash
pip install "git+https://github.com/drexthealpha/Knos"
knos demo
```

From the repository: [PyPI](https://pypi.org/project/knos/) is the last cut
release and trails `main`.

Ninety seconds on a throwaway repo it deletes afterwards. A claim, a second
agent **refused**, an edit **blocked before the write**, a purchase that costs
nothing the second time, a reversed decision **holding the work under it**, a
**process that has never seen the repo** reading it all back with its own pid
and the commit hash on screen — and then the store is deleted and you watch
every one of those stop.

Every line it prints is a real call into the real code. There is no hosted
playground and there will not be one: **nothing on the read path touches a
network**, and that is [a test](tests/test_no_network.py) rather than a
promise. The local path is the playground.

## Signals

| | Knos |
|---|---|
| Listed in the MCP directory | **yes** — [awesome-mcp-servers#13480](https://github.com/punkpeye/awesome-mcp-servers/pull/13480), merged by the owner into a 94.5k-star index |
| Code merged by third-party maintainers | **2** — [caura#1299](https://github.com/caura-ai/caura/pull/1299), [drt#1098](https://github.com/drt-hub/drt/pull/1098), which invited a second |
| Open in real repositories | **6**, including [repomix#1837](https://github.com/yamadashy/repomix/pull/1837) (28k stars) |
| Agents racing for one topic, real processes | **16**, **0** double-grants in 128 attempts; **15** when the memory is not shared — [`collide.json`](docs/evidence/collide.json) |
| Onchain receipts that resolve | **11 of 11**, 8 on Base mainnet with USDC — `python scripts/verify_receipts.py` |
| Hold length learned per agent | **29% less** time blocked on work nobody was doing — [`contention.json`](docs/evidence/contention.json) |
| Ablation arms that die with the store | **12** |
| Refusal that stops a filesystem write | **yes** — and renaming the file does not get past it, [`test_rename_bypass.py`](tests/test_rename_bypass.py) |
| Retained users | **none.** [The full ledger](docs/PMF.md), including 34 pull requests that failed |

## Three ways in, none of them a server

**The Action** — zero install, never fails your build. It reads the
`.knos/decisions.md` a contributor commits and comments on a pull request that
touches claimed work. Drop this in `.github/workflows/knos-claims.yml`:

```yaml
on: [pull_request]
jobs:
  claims:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: drexthealpha/Knos/action@v0.1.8
```

**The library** — if you already ship a tool, import the claim instead of
running ours. No MCP, no CLI, no daemon:

```python
from knos.core import Claims

with Claims(repo=".", who="my-agent") as claims:
    took, holder = claims.take("the parser")
    if not took:
        print(f"{holder['who']} has it")
```

**The server** — `pip install knos && knos connect` puts it in front of Claude
Code, Cursor, OpenCode and Claude Desktop, with three tools: `search`,
`about`, `remember`.

## What breaks when you delete it

Everything. That is the point, and it is a test rather than a claim —
`pytest tests/test_sibyl_is_load_bearing.py`.

Delete `memory.db` and the withhold is gone, the edit is allowed, the paid
answer buys again, and the held decisions are released. There is no degraded
mode — there is no product.

## Check any of it yourself

```bash
python scripts/collide.py          # 16 processes, one topic, 0 double-grants
python scripts/verify_receipts.py  # every onchain claim, resolved
python scripts/ablation.py         # 12 arms
```

The refusals themselves: `pytest tests/test_intent.py tests/test_guard.py
tests/test_rename_bypass.py`. That the read path opens no socket:
`pytest tests/test_no_network.py`.

## Where everything else went

| | |
|---|---|
| Scoring this | [`docs/JUDGE_GUIDE.md`](docs/JUDGE_GUIDE.md) — every claim mapped to the test that proves it |
| How it works | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/MEMORY_MODEL.md`](docs/MEMORY_MODEL.md) |
| Proof and receipts | [`docs/VERIFICATION.md`](docs/VERIFICATION.md) |
| Who wants this, and who has not | [`docs/PMF.md`](docs/PMF.md) |
| The long version of this page | [`docs/GUIDE.md`](docs/GUIDE.md) |

## The two onchain parts

Both optional, both off by default. Knos runs with them switched off and
nothing on the read path touches a network.

- **Base** — purchases settle over x402 in real USDC on mainnet, and the
  receipt goes back into the store, so [the money gate](src/knos/gate.py)
  reads a Base transaction hash to decide whether to spend again.
- **Virtuals** — a Telegram bot that is also a registered ACP provider,
  selling one answer out of this store.

Details and every hash: [`docs/VERIFICATION.md`](docs/VERIFICATION.md).

## What it cannot do

It does not stop a determined person, and it is not access control. It knows
what agents on **this machine** told it. It has **no retained users**. The
[ledger](docs/PMF.md) says so plainly, including the 34 pull requests that
were the wrong idea.

## Licence

MIT. The name is a Greek root for a thing known.
