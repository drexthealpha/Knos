# Judge Guide - Knos (5 minutes)

Every claim on this page maps to a file, a test, or a live artifact. Nothing
here is asserted without one of the three. Where something is not true yet,
it says so.

## The 60 second version

1. Knos is one SQLite file per repo, in Sibyl Memory, shared by every coding
   agent on the machine.
2. An agent says what it is starting. That claim is a row in Sibyl.
3. A second agent asking about that work is **refused** - not warned. It is
   told who holds it and nothing else.
4. With `knos guard --install` the refusal reaches the **edit itself**: the
   hook exits 2 and the tool never writes the file.
5. `knos export` commits the same record to `.knos/decisions.md`, and a
   GitHub Action says it on the pull request, for people who installed nothing.
6. Reverse a decision and knos **holds every piece of work reasoned from
   it** - the edit is refused and the purchase is refused - until somebody
   says they have looked. The old wording is archived, not deleted.
7. The same store decides whether the agent **spends money**: it will not
   buy what it already has, and it refuses to buy at all while somebody
   holds the topic.
8. Delete the file and every one of those stops. Measured below, not asserted.

## The one thing to look at

```bash
pip install knos==0.1.6
git clone https://github.com/drexthealpha/Knos && cd Knos
python scripts/ablation.py
```

That is the whole argument, run against the real refusal code:

| Arm | Store present | Store deleted |
|---|---|---|
| **Reversed decision: an edit resting on it** | **refused 12/12** | nothing is held |
| **Reversed decision: a purchase resting on it** | **refused 12/12** | nothing is held |
| **Reversed decision: the same edit after reconsidering** | **allowed 12/12** | - |
| **Spend: the same request a second time** | **paid again 0/12** | **paid again 12/12** |
| **Spend: the same request while somebody holds it** | **refused 12/12** | no claim survives |
| Withhold: a second agent asks about claimed work | refused **12/12** | refused **0/12** |
| Guard: an edit to claimed work | refused **12/12** | refused **0/12** |
| Action: a pull request touching a claimed topic | commented **12/12** | commented **0/12** |
| Paid: a bought answer, found by the next agent | kept **12/12** | kept **0/12** |
| **Fresh machine: a decision, before `knos restore`** | - | **lost 12/12** |
| **Fresh machine: the same decision, after `knos restore`** | - | **back 12/12** |
| **Fresh machine: the claim that must NOT come back** | - | **stayed gone 12/12** |

The first two rows are the memory deciding whether money moves. With the store,
the second identical request costs nothing. Without it, the agent pays again
every single time. And while somebody holds the topic, it refuses to spend at
all - a bought answer would be stale before it arrived, and the holder is the
cheaper place to ask.

12 trials, seed 1337. Written to
[`docs/evidence/ablation.json`](evidence/ablation.json), pinned by
[`tests/test_ablation.py`](../tests/test_ablation.py) so it cannot drift
without the suite failing.

### What that is worth, in dollars

```bash
python scripts/spend.py
```

One ordinary day on one machine: **5 agents, 20 asks, 4 subjects.**

| | purchases | free | spent |
|---|---|---|---|
| **store present** | 4 | 16 | **$0.022** |
| **store deleted** | 20 | 0 | **$0.119** |

**5.41x more expensive without the memory.** Every verdict is a real call into
`gate.decide`, the same function the bot runs before spending. The dollars are
those verdicts times prices this agent has actually paid on Base mainnet - the
receipts are in [VERIFICATION.md](VERIFICATION.md). The multiplication is
stated rather than hidden: re-buying the same brief forty times would cost
$0.40 and prove nothing the verdict count does not.

Scale is the point rather than the cents. Four subjects and five agents is a
quiet day; the ratio is what a team pays for having no shared memory, and it
grows with every agent added.

**Memory is not a feature here. It is the mechanism.** There is no second
copy of a claim, so with the file gone the refusal is not weaker, it is
impossible.

## How it is built

- [ARCHITECTURE.md](ARCHITECTURE.md) - the four surfaces, why each is where it
  is, and the anti-goals.
- [MEMORY_MODEL.md](MEMORY_MODEL.md) - what lives in each of Sibyl's five
  tiers and why that mapping is load-bearing rather than decorative.

## Load-bearing map

| Claim | Code | Test |
|---|---|---|
| **The repo carries its own memory to a fresh machine** | `src/knos/share.py` `restore` | `tests/test_restore.py` |
| **A reversed decision holds everything that rested on it** | `src/knos/decide.py` | `tests/test_decide.py` |
| **Reconsidering releases it again** | `src/knos/decide.py` `reconsider` | `tests/test_decide.py` |
| **The memory decides whether money moves** | `src/knos/gate.py` | `tests/test_gate.py` |
| A claim is one row in Sibyl, overwritten, lapsing at 30 min | `src/knos/memory.py` `claim_if_free` | `tests/test_intent.py` |
| Two agents racing: exactly one wins | `src/knos/memory.py` `claim_if_free` | `tests/test_open_race.py` |
| The hold is bound to the connection, not the name | `src/knos/mcp.py` `_is_holder` | `tests/test_core.py` |
| A second agent is refused, and told who holds it | `src/knos/mcp.py` `_held` | `tests/test_sibyl_is_load_bearing.py` |
| The refusal reaches the edit, in three clients | `src/knos/guard.py` | `tests/test_guard.py` |
| Overriding is allowed, and recorded under your name | `src/knos/mcp.py` `_took_it_anyway` | `tests/test_intent.py` |
| The record is committed to the repo | `src/knos/share.py` | `tests/test_shared_repo.py` |
| The Action comments and can never fail a build | `action/knos_pr_check.py` | `tests/test_shared_repo.py -k never_returns_non_zero` |
| Nothing on the read path touches a network | `src/knos/answer.py` | `tests/test_no_network.py` |
| Private paths stay invisible to agents | `src/knos/private.py` | `tests/test_private.py` |
| Every worktree of a repo is one memory | `src/knos/paths.py` | `tests/test_worktrees.py` |
| A full store refuses a claim rather than dropping it | `src/knos/memory.py` | `tests/test_sibyl_is_load_bearing.py -k full_store` |
| Delete the store and the product stops | - | `tests/test_sibyl_is_load_bearing.py` |
| The claim as an importable library, no server | `src/knos/core.py` | `tests/test_core.py` |

Suite: **27 critical in under a minute**, **290 in full** (`pytest -m ""`).
Contract: **9 more** (`cd contracts && forge test`).

## Live artifacts

Every one of these is clickable and was produced by this code.

| What | Where |
|---|---|
| Base **mainnet** x402 purchase, real USDC | [`0x80d984…d958c76`](https://basescan.org/tx/0x80d984d2e88332888a595f5476722bca9efbe7850fce4090b02f49154d958c76) |
| Base **mainnet** x402 purchase, real USDC | [`0xce109c…4abd9a85e`](https://basescan.org/tx/0xce109c28781fec2ea12b8e115d59b1bfea219434379a30d472cf72b4abd9a85e) |
| Base **mainnet**, after the receipt fix | [`0xa8e713…c0466103`](https://basescan.org/tx/0xa8e7135e6c41e6eb8ed5d15b5dbf5aafc5a8f748e9d16e08aa1ae6d9c0466103) |
| Base **mainnet**, after the receipt fix | [`0x3a45e0…332e049a88b`](https://basescan.org/tx/0x3a45e0066fbf764731f98dab3f023ee2a690dc8923f08ae7f9cb4332e049a88b) |
| Virtuals ACP provider | [agent page](https://app.virtuals.io/acp/agents/01a05b97-a776-760a-9165-e9893e4091dc) |
| ACP job 75659, both legs | [escrow funded](https://basescan.org/tx/0x756b867b2b1165bfe674025a82d21cd765378a40ab226274bd555abf0065bd64) · [provider paid](https://basescan.org/tx/0x95a84c44802d09e38ef920524f947dff0eb5a2fe972054fca97bfd989cbcea59) |
| Access.sol, deployed | [contract](https://sepolia.basescan.org/address/0x955fa320D60D9172CF048141ed7eEE442da66E52) |
| The Action, having actually run | [pull request #1](https://github.com/drexthealpha/Knos/pull/1) |
| On PyPI | [knos 0.1.6](https://pypi.org/project/knos/0.1.6/) |
| In the MCP registry | `io.github.drexthealpha/knos` |
| Listed on Glama | [server page](https://glama.ai/mcp/servers/drexthealpha/Knos) |

All four mainnet receipts re-verified against `base.drpc.org` on 6 Sep 2026:
status `0x1`, USDC contract `0x8335…2913` in the logs. Full detail in
[VERIFICATION.md](VERIFICATION.md).

## Honest limits

Stated because a judge will find them anyway, and because the rest of the
page is worth more if this one is complete.

- **No retained users.** 1 star, 583 PyPI downloads in a week that are
  overwhelmingly CI and crawlers. Nobody has adopted this and kept it. The
  problem is evidenced; the demand for *this* answer is not.
- **The ACP job was bought by my own test agent.** It is a real job over the
  real marketplace with real USDC, and it is not a customer.
- **No hosted playground.** Knos is local-first on purpose: nothing on the
  read path touches a network (`tests/test_no_network.py`), so there is no
  server to click. The console path is the substitute -
  `npm --prefix agent run bot -- /status` runs the real handler against the
  real store.
- **Retrieval is lexical.** SQLite FTS5, no embeddings, no model. It cannot
  answer a question whose words never appear.
- **The guard is off until you run it.** `knos guard --install`, and it fails
  open: an unreadable store allows the edit.
- **Claims are advisory-with-teeth, not a lock.** An agent can override with
  a stated reason. The reason is written into the journal under its name.
- **34 external adoption PRs were opened and none merged.** They were the
  wrong shape and were withdrawn with an apology on each. Two PRs of a
  different shape have since merged upstream: `caura-ai/caura#1299`,
  `drt-hub/drt#1098`.
