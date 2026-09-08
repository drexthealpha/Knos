# Judge Guide - Knos (5 minutes)

Every claim on this page maps to a file, a test, or a live artifact. Nothing
here is asserted without one of the three. Where something is not true yet,
it says so.

## Nothing to install: the evidence is a web page

**[drexthealpha.github.io/Knos](https://drexthealpha.github.io/Knos/)**

Every number on it is fetched from `docs/evidence/*.json` in this repository,
so nothing there is hand-typed and nothing can drift from what the scripts
regenerate. The eleven on-chain hashes link to the explorer for the chain each
is documented against.

## Run it first

```bash
pip install "git+https://github.com/drexthealpha/Knos"
knos demo
```

[`knos` on PyPI](https://pypi.org/project/knos/) is the last cut release,
0.1.8. This installs from the repository instead, because the paragraphs below
describe what is on `main` - the learned hold, `knos who`, and the ninth beat -
and a page documenting a command the install does not have is worse than a
longer command.

It will still report `0.1.8` as its version. That is the last number cut, and
it stays until the next release because the Claude Desktop extension pins
`knos==<that version>`, which has to resolve on PyPI.

Ninety seconds on a throwaway repo, ending with the store deleted and every
refusal gone. Every line is a real call, not a transcript -
[`tests/test_demo.py`](../tests/test_demo.py) asserts the live values appear.

Beat 7 is the one to watch if you are checking the gate. A separate
interpreter, started with nothing but the repo path, prints its own pid, the
repo's commit hash and the wall clock, and then reads back what an earlier
process wrote. Beat 8 shows what the store learned about which agents finish
what they claim. Beat 9 deletes it and re-runs every refusal. Cold-start
recall and the deletion test are therefore the same unbroken minute and a
half, rather than two claims made in prose.


## The gate, in the order you check it

Everything that touches the store is in one file, `src/knos/memory.py` — the
client calls below, plus one raw-SQL write noted underneath them, which is
where the claim itself is taken. Between them that is the whole critical path.

| | where | what |
|---|---|---|
| **write** | [`memory.py:190`](../src/knos/memory.py#L190) `write_event` | every fact, claim, stand-down and override, into COLD |
| **write** | [`memory.py:256`](../src/knos/memory.py#L256) `set_entity` | a topic, file or person, into WARM |
| **write** | [`memory.py:354`](../src/knos/memory.py#L354) `set_state` | the live claim, into HOT |
| **write** | [`memory.py:299`](../src/knos/memory.py#L299) `set_state` | what the session is focused on, into HOT |
| **write** | [`memory.py:582`](../src/knos/memory.py#L582) `set_reference` | the repo's own rules, into REFERENCE |
| **write** | [`memory.py:271`](../src/knos/memory.py#L271) `archive_entity` | superseded wording, into ARCHIVE |
| **read** | [`memory.py:214`](../src/knos/memory.py#L214) `read_events` | the journal - and `record.holds_for` counts it to set the next hold |
| **read** | [`memory.py:304`](../src/knos/memory.py#L304) `get_state` | the live claim - the withhold and the guard both start here |
| **read** | [`memory.py:262`](../src/knos/memory.py#L262) `get_entity` | what is known about one thing, before answering |
| **read** | [`memory.py:598`](../src/knos/memory.py#L598) `search` | every tier, for a question |
| **read** | [`memory.py:587`](../src/knos/memory.py#L587) `get_reference` | the rules, before the guard refuses a path |


One write does not go through the client, and it is the most important one.
`claim_if_free` takes the claim as a compare-and-swap in raw SQL, at
[`memory.py:411`](../src/knos/memory.py#L411) - one
`INSERT ... ON CONFLICT DO UPDATE ... WHERE` inside `BEGIN IMMEDIATE`, so that
two agents reaching for the same work in the same instant cannot both be told
they have it. `set_state` would overwrite and both would win. Sixteen
processes racing it is `python scripts/collide.py`.

**Read back to change a decision, not just written.** That is the part that
separates this from a wrapper, and there are four places to look:

| the read | changes |
|---|---|
| [`mcp._held`](../src/knos/mcp.py) | whether an agent gets an answer at all |
| [`guard.check`](../src/knos/guard.py) | whether a file is written to disk |
| [`gate.decide`](../src/knos/gate.py) | whether money moves |
| [`record.holds_for`](../src/knos/record.py) | how long the next claim survives |

**Delete it and the product stops**, in one command:

```bash
pytest tests/test_sibyl_is_load_bearing.py
knos demo     # beat 9 deletes the store live and re-runs every refusal
```

**Cold-start recall** is beat 7 of `knos demo`: a separate interpreter, given
nothing but the repo path, printing its own pid with the repo's commit hash
and the wall clock before reading back what an earlier process wrote.

## Check the receipts yourself, in one command

```bash
knos receipts
```

Every onchain claim in this repository, resolved against the chain it is
documented against - no key, no account, public RPCs:

```
  ok  mainnet  x402 news $0.001   block 50898966  usdc
  ok  mainnet  x402 brief $0.01   block 50898978  usdc
  ...
  ok  sepolia  Access.sol deploy  block 46107972
  ok  sepolia  Access.sol         3434 bytes deployed at 0x955fa320...6E52

11 of 11 receipts resolve on the chain each is documented against.
```

Eight on Base mainnet, every one of them with real USDC in its logs, and three
on Sepolia for the access contract. The script exits non-zero if any hash fails
to resolve, so it is worth running rather than reading.

It also carries its own cautionary note. The first version asked mainnet for
all eleven and reported three missing, which reads exactly like fabricated
evidence - those three are the Sepolia contract transactions, correctly
labelled and correctly absent from mainnet. A checker pointed at the wrong
chain manufactures the failure it claims to have found.

## The memory changes what the memory does next

Every claim used to lapse after the same thirty minutes, whoever made it. That
is wrong twice: an agent that closes its work loses it mid-task, and an agent
that claims and dies blocks the file for the full half hour, every time,
without the store ever getting wiser.

The hold is now learned from one thing in the COLD journal - the share of
claims this agent actually closed:

```
never finishes   ->  15 minutes
unknown agent    ->  30 minutes   (the old flat default)
always finishes  ->  45 minutes
```

Over one seeded working day, four agents, two of which mostly do not finish:

```
$ python scripts/contention.py
  flat      48 claims taken,  21 attempts blocked,   273 minutes waiting
  learned   53 claims taken,  16 attempts blocked,   194 minutes waiting

  79 fewer minutes spent waiting on work nobody was doing (29% less).
```

Modest, and stated as modest. The rule is a ratio with a floor and a ceiling
rather than a decay-weighted trust model, because a trust model fitted to a
few dozen events would be a more impressive way of being wrong.

What makes it load-bearing: the record exists nowhere but the store. Delete it
and every agent is a stranger worth exactly thirty minutes again - which is
[a test](../tests/test_record.py), `test_the_learning_dies_with_the_store`.

## If you are looking for the soft spot

It is `.knos/decisions.md`. That file is committed, so a stranger writes it,
and `knos restore` reads it into the store that answers questions. One
hostile commit used to take 4.15 MB of the 5 MB free tier and stop the store
working for everything else; it is capped at 200 decisions now, notes are
truncated at 2,000 characters, control characters and direction overrides are
stripped, and nothing from a file ever overwrites what this machine decided
itself.

What is deliberately *not* claimed: restoring a decision that says "ignore all
previous instructions" puts that sentence in the store. Filtering text for
intent is not something this can honestly do, so instead every restored answer
carries `committed to the repo, not verified` as its source. The numbers and
the reasoning are in [`VERIFICATION.md`](VERIFICATION.md).

## The coordination number

Sixteen operating-system processes reach for the same topic in the same
instant, eight rounds, one connection each:

```
$ python scripts/collide.py
  ok  round 0: 1 took it, 15 refused, 15 told who holds it
  ...
  memory shared      0 double-grants in 128 attempts
  memory not shared  15 double-grants in 16 attempts
```

Zero, not few. A lock that holds most of the time hands two agents the same
file and lets the second overwrite the first, which is the failure this exists
to stop.

The second arm is the honest one. Deleting the store proves nothing about
coordination - the next agent recreates it and the lock works again - so the
ablated condition is *sharing*: every agent given its own memory, which is
what an agent has today. All sixteen then take the same work, each certain it
is alone.

Regenerated by [`tests/test_collide.py`](../tests/test_collide.py), which also
asserts the published figures match the ones in this page.

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
pip install "git+https://github.com/drexthealpha/Knos"
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

Suite: **27 critical in under a minute**, **294 in full** (`pytest -m ""`).
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
| Merged into a third-party repo | [caura#1299](https://github.com/caura-ai/caura/pull/1299) · [drt#1098](https://github.com/drt-hub/drt/pull/1098) |
| On PyPI | [knos 0.1.8](https://pypi.org/project/knos/0.1.8/) |
| In the MCP registry | `io.github.drexthealpha/knos` |
| Listed on Glama | [server page](https://glama.ai/mcp/servers/drexthealpha/Knos) |

All four mainnet receipts re-verified against `base.drpc.org` on 6 Sep 2026:
status `0x1`, USDC contract `0x8335…2913` in the logs. Full detail in
[VERIFICATION.md](VERIFICATION.md).

## Honest limits

Stated because a judge will find them anyway, and because the rest of the
page is worth more if this one is complete.

- **No retained users.** Nobody has adopted Knos and kept it. 841 PyPI
  downloads in a week against 1 star is automated traffic, not people.
  What does exist is external validation of a different kind: **two pull
  requests merged into third-party repositories** by their maintainers
  ([caura#1299](https://github.com/caura-ai/caura/pull/1299),
  [drt#1098](https://github.com/drt-hub/drt/pull/1098)), seven more open, and
  a measured problem - 1,254 of 100,057 sampled issues. Full ledger, including
  the 34 earlier pull requests that failed and were withdrawn:
  [PMF.md](PMF.md).
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
