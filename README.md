# Knos

<!-- mcp-name: io.github.drexthealpha/knos -->

[![The evidence, live](https://img.shields.io/badge/EVIDENCE-drexthealpha.github.io%2FKnos-3fb950?style=for-the-badge)](https://drexthealpha.github.io/Knos/)
[![Base mainnet](https://img.shields.io/badge/Base-mainnet_x402_%C3%97_8-0052FF?style=for-the-badge)](https://drexthealpha.github.io/Knos/#chain)
[![Virtuals ACP](https://img.shields.io/badge/Virtuals-ACP_job_75659-8B5CF6?style=for-the-badge)](https://app.virtuals.io/acp/agents/01a05b97-a776-760a-9165-e9893e4091dc)
[![Evidence reproduces](https://github.com/drexthealpha/Knos/actions/workflows/evidence.yml/badge.svg)](https://github.com/drexthealpha/Knos/actions/workflows/evidence.yml)

**Check every claim on this page without installing anything:
[drexthealpha.github.io/Knos](https://drexthealpha.github.io/Knos/)** — the
collision study, the twelve arms, the money gate and all eleven on-chain
receipts, each number read live out of the JSON the scripts wrote.

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

Every line it prints is a real call into the real code. The
[evidence page](https://drexthealpha.github.io/Knos/) is a page *about* the
product, not part of it: **nothing on the read path touches a network**, and
that is [a test](tests/test_no_network.py) rather than a promise. There is no
hosted knos, and there will not be one.

## Signals

| | Knos |
|---|---|
| Listed in the MCP directory | **yes** — [awesome-mcp-servers#13480](https://github.com/punkpeye/awesome-mcp-servers/pull/13480), merged by the owner into a 94.5k-star index |
| Code merged by third-party maintainers | **2** — [caura#1299](https://github.com/caura-ai/caura/pull/1299), [drt#1098](https://github.com/drt-hub/drt/pull/1098); **6** more open, including [repomix#1837](https://github.com/yamadashy/repomix/pull/1837) |
| Agents racing for one topic, real processes | **16**, **0** double-grants in 128 attempts; **15** unshared — [`collide.json`](docs/evidence/collide.json) |
| Onchain receipts that resolve | **11 of 11**, 8 on Base mainnet with USDC — `python scripts/verify_receipts.py` |
| Money spent on work that got dropped | **$0.044 to $0.000** — the gate reads who is asking, [`budget.json`](docs/evidence/budget.json) |
| Hold length learned per agent | **29% less** time blocked — [`contention.json`](docs/evidence/contention.json) |
| Evidence regenerated on a clean machine | **daily** in public CI — last run reproduced every figure identically |
| Record of who overrode whom | **chained per writer** — `knos verify` names an edited entry |
| Refusal that stops a filesystem write | **yes**, and renaming the file does not get past it |
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
knos receipts                      # every onchain claim, resolved live
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

## The load-bearing map

Every one of these is a read of the store that changes what happens next.
Delete `memory.db` and each line becomes the one after the arrow.

| the read | decides | without the store |
|---|---|---|
| [`mcp._held`](src/knos/mcp.py) | whether an agent is answered at all | it answers, and two agents edit the same thing |
| [`guard.check`](src/knos/guard.py) | whether a file is written to disk | the write lands |
| [`gate.decide`](src/knos/gate.py) | whether money moves | it buys the same answer again |
| [`record.holds_for`](src/knos/record.py) | how long the next claim survives | everyone is a stranger worth 30 minutes |
| [`decide.is_suspect`](src/knos/decide.py) | whether work under a reversed decision is held | it proceeds on wording that was withdrawn |
| [`seal.check`](src/knos/seal.py) | whether the record was edited | there is no record to check |

Every write and read into Sibyl is in one file, `src/knos/memory.py`, with
line numbers in the [judge guide](docs/JUDGE_GUIDE.md). The deletion test is
`pytest tests/test_sibyl_is_load_bearing.py`.

## How memory made this possible

Knos is not a tool that happens to save things. Take Sibyl out and there is no
product left to run.

The claim lives in the store, and that is the whole mechanism: one agent
writes down what it is changing, and the next agent whose question touches
that subject is handed the holder's name instead of an answer. The refusal is
not a rule enforced somewhere else in the code — it **is** a read of the
store, and it fails exactly when the read fails.

Three other things exist nowhere else: what you told it with `knos remember`,
the brief an agent paid for over x402 and wrote back, and the ACP job it sold.
Your commits and your `CLAUDE.md` are re-read after a delete. Those are not.

## Prior work

Knos is not a fork and not a clone. There is no upstream project and no
pre-existing memory layer that Sibyl was added to. Every line is original work
under MIT and the commit history is the whole record — written locally before
the window and first published on 1 September; everything after is dated in
the log.

**Dependencies, and what each is for.** Sibyl Memory (`sibyl-memory-client`)
is the store, and it is the load-bearing one. The MCP Python SDK provides the
server. `universal-ctags` is optional — without it knos falls back to a reader
it carries itself. The Virtuals ACP SDK and the `x402` client are used only by
`agent/`, which is the commerce leg rather than the product.

The longer version of all three: [`docs/GUIDE.md`](docs/GUIDE.md).

## What it cannot do

It does not stop a determined person, and it is not access control. It knows
what agents on **this machine** told it. It has **no retained users**. The
[ledger](docs/PMF.md) says so plainly, including the 34 pull requests that
were the wrong idea.

## Licence

MIT. The name is a Greek root for a thing known.

[![Knos MCP server](https://glama.ai/mcp/servers/drexthealpha/Knos/badges/score.svg)](https://glama.ai/mcp/servers/drexthealpha/Knos)
