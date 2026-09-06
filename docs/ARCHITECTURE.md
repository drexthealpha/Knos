# Knos - Architecture

One SQLite file per repository, four surfaces that read it, and a rule that
every one of them **refuses** rather than warns. This document is the shape of
that, and why each piece is where it is.

## System overview

```
        writes                         one store                      reads
  ---------------------          -------------------      ------------------------
  knos claim        -------\                              /------  MCP search / about
  knos remember     --------\                            /-------  guard.check (the edit)
  knos changed      ---------> ~/.knos/<repo>/memory.db <---------  gate.decide (the money)
  knos point        --------/     Sibyl Memory, 5 MB      \-------  knos export -> the Action
  the bot, after   ---------/                              \------  knos ask / status
  a purchase
```

Everything on the left writes. Everything on the right reads and, when the
store says so, **refuses**. There is no second copy of anything on the left, so
deleting the file does not degrade the right-hand column: it removes it.
Measured in [`scripts/ablation.py`](../scripts/ablation.py), nine arms.

## The one design decision everything else follows from

**A memory that only advises is ignored.**

Every comparable tool answers the question and attaches a warning. An agent
reads the answer and proceeds, because the answer is right there. So Knos does
not attach anything. When another agent holds the work, the answer is not in
the reply at all - only who has it. The refusal *is* the product; the store
exists to make the refusal possible.

That single decision explains the rest of this document: why the claim is a
compare-and-swap rather than a write, why the hold binds to a connection
rather than a name, why the guard is a client hook rather than an MCP tool,
and why the Action can never fail a build.

## Components

### 1. The store - the critical path

[`src/knos/memory.py`](../src/knos/memory.py) (662 lines) is the only thing
that talks to Sibyl. Everything else goes through it.

`claim_if_free` is the heart: one `INSERT ... ON CONFLICT DO UPDATE ... WHERE`
inside `BEGIN IMMEDIATE`. Two agents reaching for the same work in the same
second both write, and exactly one wins; the loser is handed the winner's
record rather than a failure. A plain `set_state` would have let both succeed
and the second would silently own it.

The 5 MB free-tier cap is checked in that path directly rather than left to
Sibyl's own gate, because a claim that quietly did not land is the one failure
the whole feature exists to prevent. A full store **refuses** a claim in words
(`tests/test_sibyl_is_load_bearing.py -k full_store`).

### 2. Retrieval

[`src/knos/answer.py`](../src/knos/answer.py) (542 lines). SQLite FTS5, no
embeddings, no model, no network
([`tests/test_no_network.py`](../tests/test_no_network.py)). Every answer is a
passage somebody actually wrote, with where it came from.

`same_subject` is the matcher used everywhere a claim has to cover a question:
shared word **stems**, not substrings. Substrings made a claim on a short word
warn about half the repo - "guard" fired on "safeguarding". Bare word overlap
then missed the obvious, because a claim on "parser" said nothing about
"parsing". Stems fixed both.

### 3. The withhold - the MCP surface

[`src/knos/mcp.py`](../src/knos/mcp.py) (430 lines). Three tools over stdio:
`search`, `about`, `remember`. No HTTP, no port, no account.

`_held` decides whether to answer. `_is_holder` decides whether the caller is
the one who claimed it, and it checks **both the name and the session**,
because a client tells Knos its own name and can say anything. The session is
the server process id - every client spawns its own Knos over its own pipe, so
it is something the claimer holds and a different client cannot borrow. An
agent asserting the holder's name is still refused
([`tests/test_core.py`](../tests/test_core.py)).

Overriding is allowed. It needs a stated reason, and the reason is written
into the journal under the agent's own name. A rule with no escape hatch gets
routed around; one with an audited escape hatch gets used honestly.

### 4. The guard - the refusal reaches the edit

[`src/knos/guard.py`](../src/knos/guard.py) (424 lines),
[`guard_hook.py`](../src/knos/guard_hook.py) (52 lines).

MCP cannot stop a tool call - it is a server, and the client decides. But
Claude Code, Cursor and OpenCode each run a **hook** before a tool executes,
and a hook can say no. `knos guard --install` writes the right shape for each
(`PreToolUse` with `permissionDecision: deny`, `preToolUse` with
`permission: deny`, a plugin that throws). Exit 2 is the refusal.

`guard_hook.py` is its own module and imports almost nothing, because it runs
before every single edit. It **fails open**: an unreadable store allows the
edit. The guard is a refinement on top of the claim, never a gate in front of
the disk.

### 5. Reversal with blast radius

[`src/knos/decide.py`](../src/knos/decide.py) (181 lines).

A claim is about who is moving now. A decision is about what was settled, and
it goes stale in silence. `knos changed` archives the old wording to Sibyl's
ARCHIVE tier, writes the new one under the same name, and marks everything on
the same subject **suspect**. Until each is reconsidered, the edit is refused
and the purchase is refused.

Reversing costs one command. Reconsidering costs one command. Carrying on
without looking is the only expensive path, and that asymmetry is the whole
mechanism.

### 6. The money gate

[`src/knos/gate.py`](../src/knos/gate.py) (109 lines).

Asked before any purchase. Three verdicts: **withheld** (somebody holds the
topic, so a bought answer is stale before it arrives), **suspect** (it rests
on a reversed decision), **have** (already bought, served free), and only
otherwise **buy**.

It fails towards `buy` on any error. A gate that crashes must not become a gate
that spends silently, and must not become a gate that stops the agent working.

### 7. The shared record and the Action

[`src/knos/share.py`](../src/knos/share.py) (189 lines),
[`action/knos_pr_check.py`](../action/knos_pr_check.py).

`knos export` writes `.knos/decisions.md` - plain markdown, committed to the
repo. The Action reads that file and comments on a pull request that touches
claimed work or a recorded decision. It needs **nothing installed** on the
other side and is standard library only.

It exits 0 on every path, including every failure path and every unexpected
one - the entry point catches whatever `main()` lets escape. A repo adopting
it is trusting it not to redden their build, and that promise has to hold for
the paths nobody thought of.

It is safe under `pull_request_target`: it reads only the committed file and
the pull request's own metadata, and never checks out or runs anything from
the head branch.

### 8. The embeddable core

[`src/knos/core.py`](../src/knos/core.py) (157 lines). The claim, the
connection-bound hold and the refusal, importable with no MCP, no CLI and no
daemon. It exists because almost nobody wants to run a separate server to get
a behaviour - they want it inside the tool they already have.

### 9. The commerce leg

[`agent/bot.ts`](../agent/bot.ts), [`buy402.py`](../src/knos/buy402.py),
[`pay.py`](../src/knos/pay.py), [`contracts/src/Access.sol`](../contracts/src/Access.sol).

A Telegram bot that is also a registered Virtuals ACP provider. It buys over
x402 on Base mainnet and sells answers out of this same store. **Optional and
off by default** - Knos works with it switched off, and nothing on the read
path touches a network either way.

## Why it is keyed on the git common directory

[`src/knos/paths.py`](../src/knos/paths.py). The store is keyed on
`git rev-parse --git-common-dir`, not `--show-toplevel`. A worktree returns its
own root from the latter, so a tool keyed that way fragments a repo's memory
once per worktree - which is precisely the setup where several agents are
working at once and coordination matters most.
[`tests/test_worktrees.py`](../tests/test_worktrees.py).

## Directory layout

```
src/knos/       the product: store, retrieval, withhold, guard, decide, gate
action/         the pull request check. Standard library only, exits 0 always
agent/          the Telegram bot, ACP provider, x402 buyer. Optional
contracts/      Access.sol, the onchain read record. Optional, testnet
scripts/        ablation.py, the measured numbers
docs/           this, the judge guide, verification, the demo script
tests/          281 tests, 24 on the critical path
```

## Anti-goals

Things deliberately not built, because each would cost something load-bearing.

- **No model, no embeddings.** Knos cannot answer a question whose words never
  appear, and that is the trade for every answer being a passage somebody
  wrote with a citation.
- **No server, no hosted surface.** Nothing on the read path touches a
  network, and that is a test rather than a promise. A hosted playground would
  be a better demo and a worse claim.
- **No hard lock.** An agent can override with a stated reason. A rule with no
  exit gets routed around silently; this one gets routed around loudly, in the
  journal, under a name.
- **No second store.** Every surface reads the one SQLite file. The moment
  anything caches its own copy, "delete it and the product dies" stops being
  true, and that sentence is the product.
