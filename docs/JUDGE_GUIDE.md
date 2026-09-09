# Judge Guide - Knos (5 minutes)

Every claim on this page maps to a file, a test, or a live artifact. Nothing
here is asserted without one of the three. Where something is not true yet,
it says so.

## Nothing to install: the evidence is a web page

**[drexthealpha.github.io/Knos](https://drexthealpha.github.io/Knos/)**

Every number on it is fetched from `docs/evidence/*.json` in this repository,
so nothing there is hand-typed and nothing can drift from what the scripts
regenerate. The twelve on-chain hashes link to the explorer for the chain each
is documented against.

## Run it first

```bash
pip install "git+https://github.com/drexthealpha/Knos"
knos demo
```

[`knos` on PyPI](https://pypi.org/project/knos/) is the last cut release,
0.1.8. This installs from the repository instead, because the paragraphs below
describe what is on `main` - the learned hold, `knos who`, and the ten beats -
and a page documenting a command the install does not have is worse than a
longer command.

It will still report `0.1.8` as its version. That is the last number cut, and
it stays until the next release because the Claude Desktop extension pins
`knos==<that version>`, which has to resolve on PyPI.

About fifty seconds on a throwaway repo, ending with the store deleted and every
refusal gone. Every line is a real call, not a transcript -
[`tests/test_demo.py`](../tests/test_demo.py) asserts the live values appear.

Beat 7 is the one to watch if you are checking the gate. A separate
interpreter, started with nothing but the repo path, prints its own pid, the
repo's commit hash and the wall clock, and then reads back what an earlier
process wrote. Beat 8 shows what the store learned about which agents finish
what they claim. Beat 9 deletes it and re-runs every refusal. Cold-start
recall and the deletion test are therefore the same unbroken minute and a
half, rather than two claims made in prose.


## Everything the memory decides, in one table

Sixteen patterns, not one. Each is a read of the store that changes what
happens next, and each row names the function and the test rather than
describing a capability.

| | where | what it decides | held by |
|---|---|---|---|
| **A claim** | [`memory.claim_if_free`](../src/knos/memory.py) | one agent gets the work; the rest are told who has it | [`test_collide.py`](../tests/test_collide.py) |
| **A withhold** | [`mcp._held`](../src/knos/mcp.py) | whether the asking agent is answered at all | [`test_intent.py`](../tests/test_intent.py) |
| **A guard** | [`guard.check`](../src/knos/guard.py) | whether the file is written to disk at all | [`test_guard.py`](../tests/test_guard.py) |
| **A rename it survives** | [`guard._renamed_out_of`](../src/knos/guard.py) | moving the file does not launder the claim | [`test_rename_bypass.py`](../tests/test_rename_bypass.py) |
| **A money gate** | [`gate.decide`](../src/knos/gate.py) | whether real USDC leaves the machine | [`test_gate.py`](../tests/test_gate.py) |
| **A spending right** | [`record.may_spend`](../src/knos/record.py) | *who* may spend, from what they finished before | [`test_spender.py`](../tests/test_spender.py) |
| **A learned hold** | [`record.holds_for`](../src/knos/record.py) | how long the next claim is worth, per agent | [`test_record.py`](../tests/test_record.py) |
| **A blast radius** | [`decide.supersede`](../src/knos/decide.py) | work under a reversed decision is held until somebody looks | [`test_decide.py`](../tests/test_decide.py) |
| **A rule its file dropped** | [`rules.still_says`](../src/knos/rules.py) | whether a rule is still quoted, and the line it is cited at | [`test_fresh_rules.py`](../tests/test_fresh_rules.py) |
| **A symbol that moved** | [`code.still_defines`](../src/knos/code.py) | whether a line number is still the one to print | [`test_fresh_code.py`](../tests/test_fresh_code.py) |
| **A promoted record** | [`record.standing`](../src/knos/record.py) | how long a hold is worth, and whether an agent may spend | [`test_promotion.py`](../tests/test_promotion.py) |
| **A notice before the first question** | [`start_hook.main`](../src/knos/start_hook.py) | whether an agent is told who holds what before it opens anything | [`test_start_hook.py`](../tests/test_start_hook.py) |
| **A seal** | [`seal.check`](../src/knos/seal.py) | an entry cannot be edited, or dropped, unnoticed | [`test_seal.py`](../tests/test_seal.py) |
| **A reconstruction** | [`rewind.at`](../src/knos/rewind.py) | who held what at a moment that has already passed | [`test_rewind.py`](../tests/test_rewind.py) |
| **A ledger of refusals** | [`worth.tally`](../src/knos/worth.py) | what the store has actually prevented here | [`test_worth.py`](../tests/test_worth.py) |
| **A portable record** | [`share.restore`](../src/knos/share.py) | decisions survive a fresh clone; live holds deliberately do not | [`test_restore.py`](../tests/test_restore.py) |

None of these is a place the store is written and never read again - that is
the shape the gate calls a wrapper. Every row is the store being *consulted*
and something different happening because of what it said. Delete
`memory.db` and all sixteen become the same line: it goes ahead.

## The gate, in the order you check it

Everything that touches the store is in one file, `src/knos/memory.py` — the
client calls below, plus one raw-SQL write noted underneath them, which is
where the claim itself is taken. Between them that is the whole critical path.

| | where | what |
|---|---|---|
| **write** | [`memory.py:223`](../src/knos/memory.py#L223) `write_event` | every fact, claim, stand-down and override, into COLD |
| **write** | [`memory.py:297`](../src/knos/memory.py#L297) `set_entity` | a topic, file or person, into WARM |
| **write** | [`memory.py:395`](../src/knos/memory.py#L395) `set_state` | the live claim, into HOT |
| **write** | [`memory.py:340`](../src/knos/memory.py#L340) `set_state` | what the session is focused on, into HOT |
| **write** | [`memory.py:648`](../src/knos/memory.py#L648) `set_reference` | the repo's own rules, into REFERENCE |
| **write** | [`memory.py:312`](../src/knos/memory.py#L312) `archive_entity` | superseded wording, into ARCHIVE |
| **read** | [`memory.py:249`](../src/knos/memory.py#L249) `read_events` | the journal - and `record.holds_for` counts it to set the next hold |
| **read** | [`memory.py:345`](../src/knos/memory.py#L345) `get_state` | the live claim - the withhold and the guard both start here |
| **read** | [`memory.py:303`](../src/knos/memory.py#L303) `get_entity` | what is known about one thing, before answering |
| **read** | [`memory.py:664`](../src/knos/memory.py#L664) `search` | every tier, for a question |
| **read** | [`memory.py:653`](../src/knos/memory.py#L653) `get_reference` | the rules, before the guard refuses a path |


One write does not go through the client, and it is the most important one.
`claim_if_free` takes the claim as a compare-and-swap in raw SQL, at
[`memory.py:452`](../src/knos/memory.py#L452) - one
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

The same beat then starts **two** processes at the same instant, both reaching
for one piece of work:

```
$ two processes, same instant, both claim "the settlement path"
    pid 12984 Claude Code | TOOK IT
    pid 16976 Cursor | refused, held by Claude Code
```

Different pids, and the loser is refused by name. Nothing passes between those
two except the store - which is the coordination claim happening rather than
being asserted. `python scripts/collide.py` does it sixteen ways and counts
zero double-grants in 128 attempts; this is the two-process version you can
watch.

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

12 of 12 receipts resolve on the chain each is documented against.
```

Eight on Base mainnet, every one of them with real USDC in its logs, and three
on Sepolia for the access contract. The script exits non-zero if any hash fails
to resolve, so it is worth running rather than reading.

It also carries its own cautionary note. The first version asked mainnet for
all eleven and reported three missing, which reads exactly like fabricated
evidence - those three are the Sepolia contract transactions, correctly
labelled and correctly absent from mainnet. A checker pointed at the wrong
chain manufactures the failure it claims to have found.

## The record of who overrode whom cannot be quietly edited

```bash
knos verify
```

Every journal entry is chained to the last one its writer made. Alter one, or
remove one, and the rest of that writer's chain stops adding up, and `knos
verify` names the writer and the entry.

Two halves, not equal, and worth separating rather than rounding up:

| | caught | why |
|---|---|---|
| an entry **edited** | always, every entry | the link is over the entry's own contents |
| an entry **deleted** | only inside a chain of more than one | a gap needs a line either side to show |

Facts knos read out of your code carry a file and a line as their source, so
each is its own chain of one - an edit still breaks it, a deletion has nothing
left to notice. The facts that record what agents *did* carry the agent as the
writer, and those are the sequences with length, which is where deleting a line
would be worth somebody's while. `knos verify` prints both numbers, and
`test_a_lone_entry_is_sealed_against_editing_but_not_deletion` pins the weaker
half so it cannot quietly be claimed as the stronger one.

That matters because an override is the only thing in knos an agent does
against somebody else's work, and the only cost it carries is being written
down under its own name. A record that can be edited afterwards carries no
cost at all.

The chain is per writer rather than one global chain, because knos is a
multi-process product - sixteen agents racing one claim is a test here - and a
single chain forks the moment two of them append in the same instant. A fork
is indistinguishable from tampering, and an alarm that fires during ordinary
work is worse than no alarm. `test_two_writers_in_the_same_instant_do_not_look_like_tampering`
pins that.

Stated plainly: this is tamper-**evident**, not tamper-proof. Whoever holds the
file could rewrite a whole chain from the beginning. What they cannot do is
change one line in the middle and have it pass. The tests in
[`tests/test_seal.py`](../tests/test_seal.py) edit and delete rows in the
SQLite file directly rather than going through any knos API.

## The only question that is about then

```bash
knos at "2026-09-08 14:00"
knos at 2h
```

Every other part of knos answers about now: the claim, the withhold, the
guard, the gate. This answers the question people actually have *after* two
agents collide - what did the machine know, and who was holding what.

```
60 minutes ago
  the risk guard - Claude Code
    taken 13:42, held 30 min of the 39 it had earned
  What the store had been told by then:
    13:44  the risk guard refuses unknown assets
```

It is a reconstruction rather than a guess, and one detail is what makes the
difference. A claim with no recorded close was live for exactly the hold its
agent had earned **by that moment** - not the hold it has earned since. An
agent that spent Monday abandoning work and Tuesday finishing it has two
different holds, and reconstructing Monday with Tuesday's number produces a
confident, wrong account of the thing somebody is trying to understand.
`test_the_hold_used_is_the_one_earned_by_then` forces those two numbers apart
and fails if the wrong one is used.

Two more refusals to guess, both tested: a time it cannot parse is said so
rather than silently chosen, and the journal's thousand-entry floor is
reported rather than reconstructing an empty machine and calling that history.

Read-only, and it invents no storage: the claim events, the notes and the
reversals were all written for their own reasons and each carries the time it
happened.

## The memory decides who may spend, not only what was bought

Every other refusal in `gate.decide` is about the **topic**: somebody is
mid-change on it, a decision under it was reversed, the store already has it.
There is one about the **agent**, and it is the only question here whose wrong
answer costs real money.

On a machine several agents share, the budget is one pocket. An agent that buys
an input and then drops the work bought nothing, and it will do it again in
half an hour. So `record.may_spend` reads the same journal `record.holds_for`
does, and an agent that has taken work here three or more times and closed less
than a third of it does not spend.

```
$ python scripts/budget.py
  trusted  bought  10  refused   0  spent $0.055  of which $0.044 on work that was dropped
  learned  bought   8  refused  19  spent $0.044  of which $0.000 on work that was dropped
```

The percentage saved is the weaker number and it is in the JSON. The claim is
the other column: **the money that moved went to work somebody finished**, and
the agents that finish things were never stopped.

Four things keep it from being a bad rule, each with a test in
[`tests/test_spender.py`](../tests/test_spender.py):

- a new agent spends freely - refusing on no evidence is the failure the
  record module is written against;
- one bad afternoon is not a record, so it takes three;
- an abandoner still gets answers the store already paid for, because refusing
  those would be spite rather than thrift;
- finishing work earns the money back, and the refusal says how.

Stated rather than implied: this is not a security boundary. An agent picks its
own name. It is what an agent said about itself, held against what it did last
time, applied at the one point where being wrong is expensive - the same trust
model as every other claim in knos.

It is also load-bearing in the literal sense. Delete the store and the shared
card is handed to anybody again: `test_it_dies_with_the_store`.

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

## The cap binds, and it decides what knos can answer

The most useful thing measured today was that `knos point` could not finish on
this repository - the one knos was built in.

Sibyl's free tier is 5 MB, and a fact costs about 5.5 KB of it once indexed:
the store keeps the row, a full-text copy of the text, and a second shadow
index. So five megabytes is roughly **one thousand facts**, not five megabytes
of prose. That is Sibyl's schema rather than anything knos chooses, and it
means the cap binds on ordinary repositories instead of being theoretical.

It used to bind in the worst possible place. Sessions were read before commits
and a transcript is unbounded - thousands of turns, growing daily - while
commits are capped at 500 and are the only source that says *why* something
was done. First come, first served is the wrong rule when one of the queues
never ends:

| `knos point` on this repo | commits read | session turns read |
|---|---|---|
| sessions first, as it was | **0** of 62 | 1,075 |
| commits first, at most a third of the cap | **62** of 62 | 994 |

Seven and a half per cent of the transcript, for the entire record of why
anything was done. `COMMIT_SHARE` in [`answer.py`](../src/knos/answer.py) is a
named constant because a third is a judgement call rather than a measurement,
and anybody who disagrees with it should be able to find it.
[`test_cap_share.py`](../tests/test_cap_share.py) fails with "kept 0 of 12
commits" if the order goes back.

The message shown when the store fills used to end with "read one folder
instead: `knos point <repo>/src`". Sessions are read per repo and not per
folder, so following that advice reads exactly the same turns and fills the
store again after a second wait. It names the source now.

## Every strength, and where you can watch it

`knos demo` is one command on a throwaway repo it deletes afterwards, about
fifty seconds. Eleven beats:

| # | beat | what it proves | code |
|---|---|---|---|
| 1 | a deleted rule stops being quoted | citations are re-checked, not repeated | [`rules.still_says`](../src/knos/rules.py) |
| 2 | one agent claims work | the compare-and-swap | [`memory.claim_if_free`](../src/knos/memory.py) |
| 3 | the second is refused | the answer itself is withheld, not a warning | [`mcp._held`](../src/knos/mcp.py) |
| 4 | its edit is refused | the write never lands | [`guard.check`](../src/knos/guard.py) |
| 5 | buy → free → refused | the record decides whether money moves | [`gate.decide`](../src/knos/gate.py) |
| 6 | a reversed decision holds work under it | blast radius | [`decide.supersede`](../src/knos/decide.py) |
| 7 | `knos export` writes a committable record | the repo-level loop | [`share.write`](../src/knos/share.py) |
| 8 | **a new interpreter recalls it** | **the gate: cold-start, commit hash and clock on screen** | [`core.Claims`](../src/knos/core.py) |
| 9 | holds each agent earned, and `knos at` | the learned hold, and a past moment | [`record.holds_for`](../src/knos/record.py) |
| 10 | a private path: you see it, your agent does not | no result **and no notice** | [`private.visible`](../src/knos/private.py) |
| 11 | **delete the store** | every refusal above reverts | [`test_sibyl_is_load_bearing.py`](../tests/test_sibyl_is_load_bearing.py) |

### What the one command deliberately does not show

Naming these is the point of the table. A judge who finds them missing should
find them listed here first.

| not in `knos demo` | where it is instead | why |
|---|---|---|
| **a real payment on Base** | `python scripts/live_gate.py --spend`, and `knos receipts` | the demo runs on a throwaway repo and spends nothing; beat 5 shows the *decision*, not a settlement |
| **Base Sepolia grant/revoke** | `knos share ./src --with <name>`, [`Access.sol`](../contracts/src/Access.sol) | it needs a second identity and ~30s of chain round-trips; it is a beat in [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) instead |
| **the Virtuals ACP job** | [job 75659](https://basescan.org/tx/0x756b867b2b1165bfe674025a82d21cd765378a40ab226274bd555abf0065bd64), and `@KnosWireBot` on Telegram | a live ACP job takes minutes to dispatch |
| **`knos restore`** | [`test_restore.py`](../tests/test_restore.py), 12 tests | beat 7 writes the file; a fresh clone reading it back needs a second checkout |
| **`knos why`** | run it yourself - it counts *your* transcripts | it measures the machine it runs on, so a recording of mine says nothing about yours |
| **`knos worth`** | run it on a repo you have used | it is zero on a throwaway repo, which is the honest answer and a dull beat |

**The multiplier depends on the first two rows.** The rule is that a stack
counts when a judge sees it doing real work in the demo, and `knos demo` shows
neither a payment nor a grant. The recording has to include one of:
`scripts/live_gate.py --spend` (a real x402 settlement, refused in the middle
by the record), or `knos receipts` resolving all twelve hashes against the
chain, or the Telegram bot buying something live. Without one of them on tape,
the on-chain work is documented rather than demonstrated.

## Every way in, and what each one is

Six reviews called this a narrow product. They were reading a README whose
heading says "Three ways in" - written when there were three. Everything here
was checked rather than remembered:

| way in | what it is | checked |
|---|---|---|
| **MCP server** | four tools over stdio, no network, no account | `tests/test_mcp.py`, and the tool set is asserted over a real stdio client |
| **CLI** | ~25 commands - `point`, `ask`, `claim`, `done`, `who`, `why`, `worth`, `at`, `receipts`, `verify` | `knos help <command>` for each, asserted by `tests/test_cli.py` |
| **`knos connect`** | writes the config for **four clients**: Claude Code, Cursor, Claude Desktop, OpenCode | [`cli.py`](../src/knos/cli.py), [`docs/connect.md`](connect.md) |
| **`knos guard --install`** | the write-blocking hook, into Cursor and OpenCode | [`guard.py`](../src/knos/guard.py) |
| **Claude Desktop extension** | `knos.mcpb`, manifest 0.4, one click | [`extension/manifest.json`](../extension/manifest.json) |
| **Claude Code plugin** | a `PreToolUse` hook on Edit/Write/NotebookEdit | [`plugins/knos/hooks/hooks.json`](../plugins/knos/hooks/hooks.json) |
| **GitHub Action** | zero install, comments on a pull request that touches claimed work | [`action/action.yml`](../action/action.yml) |
| **Telegram bot** | the one surface a person uses with nothing installed | [`agent/bot.ts`](../agent/bot.ts) |
| **Virtuals ACP provider** | sells one answer out of the store; job 75659 settled on Base | `knos receipts` |
| **x402 buyer** | pays for what it does not know, on Base mainnet | `knos receipts`, [`live-gate.json`](evidence/live-gate.json) |
| **`knos-hermes`** | knos as a Hermes `MemoryProvider`, its own package | [PyPI](https://pypi.org/project/knos-hermes/) |

And the distribution, which is not a surface but is the same question:

| | |
|---|---|
| PyPI `knos` | published, **9 releases**, latest 0.1.8 |
| PyPI `knos-hermes` | published, 0.1.0 |
| MCP directory | [awesome-mcp-servers#13480](https://github.com/punkpeye/awesome-mcp-servers/pull/13480), **merged** by the owner into a 94.5k-star index |
| MCP registry | `server.json`, `io.github.drexthealpha/knos` |
| Glama | `glama.json` |
| Base Sepolia | `Access.sol` deployed, granted and revoked - three receipts |

**What this does not claim.** None of these has retained users; the count is
still zero and [`PMF.md`](PMF.md) says so. Breadth of surface is not adoption,
and a judge should read this table as "the work exists and runs", not as
evidence that anybody depends on it.

## The same claim with the simulation taken out

`promotion_bench.py` is seeded and says so. This is the identical argument
against real money: one agent, one endpoint, one price, and the only thing
that changes between rounds is what the store knows about that agent.

| round | what the store knew | it did | cost |
|---|---|---|---|
| 1 | nothing about this agent | **paid** on Base | $0.001 |
| 2 | four claims taken, none closed | **refused by the record** | $0.000 |
| 3 | the same four, now closed | **free, the store already had it** | $0.000 |

Total moved: **$0.001**. The receipt is
[0x7df644ad5b66665d...](https://basescan.org/tx/0x7df644ad5b66665d724dbb4f6567df6f189baa1350bdb383f628cfc50e71084e) and `knos receipts` reads it out
of [`live-gate.json`](evidence/live-gate.json) rather than from a hash typed
into the verifier - a pinned copy went stale on the very next run, which is
the same fault this repo spent the day removing from its answers.

Round 2 is the measurement. The money that did not move is the whole claim,
and the refusal is quoted in the store's own words: *"the Telegram bot has
taken 4 pieces of work here and closed 0."*

**This is cents, not a season.** The wallet behind it holds under a dollar, so
this establishes that the promoted record is wired to real USDC in a shipped
product - the Telegram bot, which is also the Virtuals ACP provider - and not
how the number scales. Anyone comparing it to a thousand-forecast run with a
funded treasury is comparing the right things and should reach the obvious
conclusion.

## What the promoted record is worth, and where it is not worth much

An agent's record is written to the journal as it happens, promoted into a
canonical WARM entity once there are two observations, pooled with a
thirty-minute prior while the evidence is thin, weighted lighter the longer
that agent has been quiet, and archived out of WARM after a season - coming
back the next time it claims anything. `record.py` owns all of it and the
journal stays the audit trail, so `knos at` still reconstructs a past moment
from what was written at the time rather than from a running total.

`python scripts/promotion_bench.py` runs 200 seeded working
months, three arms, same dice:

| arm | blocked minutes | wasted spend |
|---|---|---|
| blind - the store deleted | 8,105 | $6.72 |
| the journal ratio alone | 4,325 | $0.77 |
| the promoted record | 4,292 | $0.63 |

Memory against no memory is the gate's own question and it is not close:
**100.0%** of seeds waited less, and the
mean saving is 3,814 minutes
with a 5th percentile of 3,136.

**Promotion against the old ratio is a much smaller claim, and it depends
entirely on one number.** The journal is a window - the last thousand rows,
shared with every fact knos read out of the repo - so how much it forgets
decides how much the durable record adds. Swept rather than asserted:

| journal window | journal wasted | promoted wasted |
|---|---|---|
| 10 events | $4.60 | $0.62 |
| 20 events | $1.73 | $0.62 |
| 40 events | $0.77 | $0.62 |
| 80 events | $0.66 | $0.62 |
| 160 events | $0.65 | $0.62 |
| 320 events | $0.64 | $0.62 |

At a tight window promotion is worth **7.4x**; at a wide one it is
worth **1.03x**, which is nothing. The promoted column does not
move, because it does not read a window. So this is worth having on a busy
repo whose store is under pressure - which is the repo knos was built in,
where `knos point` fills the 5 MB tier - and close to pointless on a quiet one.

**It is a simulation.** No model, no real money: agent reliabilities are the
input assumption and are listed in the file. It shows what the rule does given
that behaviour, which is weaker than a live economic run and is labelled that
way wherever it appears. An earlier version of the bench had no window at all,
which gave the journal a perfect memory and made promotion look like pure
cost; that was a broken experiment and it stays in the record.

## How often two agents are really working at once

Everything else about the problem this addresses was asserted. Claude Code
writes a timestamped transcript per session and knos already reads them, so
`python scripts/concurrency.py` counts the windows in which two or more
different sessions each did something. On this machine, over
5,866 real turns across 11 sessions:

<!-- counted: docs/evidence/concurrency.json -->

| window | with any agent working | with two or more |
|---|---|---|
| 1 minute | 4,042 | 458 (11.3%) |
| 5 minutes | 1,977 | 194 (9.8%) |
| 15 minutes | 984 | 97 (9.9%) |
| 30 minutes | 590 | 59 (10.0%) |
<!-- /counted -->

Four widths, because a share that only holds at one of them is a property of
the bucketing rather than of the day. It does not move.

**Check it against your own week.** `knos why` runs the same count over the
transcripts on the machine you are reading this on:

```
knos why
```

Offline, writes nothing, and prints the share at four window widths. If you
have never run two agents at once it says exactly that and tells you knos is
probably not for you. That case is tested (`tests/test_why.py`) because a tool
that only speaks up when the number flatters it is an advert.

**Read it for what it is.** This is the precondition for a collision and not a
collision rate: two sessions in the same minute may be nowhere near each other
in the tree, and nothing here claims they met. It is also one developer's
machine - the one knos was built on - so it is evidence about that working day
and not a population estimate. The script publishes counts only; no transcript
content and no session identifiers go into the file. Run it on your own
machine, where the number can actually decide something for you.

## Where knos stops being worth running

Every other number here comes from a simulation whose parameters somebody
chose, and you should discount them accordingly. `duplicated.json` is the
exception: four durations, measured by a clock, on the machine that wrote the
file. `python scripts/duplicated.py` writes it again, and the daily workflow
already does.

<!-- measured: docs/evidence/duplicated.json -->

| | measured |
|---|---|
| the compare-and-swap that refuses a claim | 0.78 ms |
| one MCP tool call, which opens the store and closes it | 43.2 ms |
| a cold `knos` command, the slowest path here | 141 ms |
| one real source file of this repo, read and parsed | 5.8 ms |
<!-- /measured -->

So a tool call pays for itself once it prevents **7.4** files of
duplicated work, and a cold command at **24.2**. Below that,
coordinating costs more than colliding, which is the honest shape of this and
is why the break-even is published rather than the ratio alone.

Read as a single number - the whole cold path against one file - this comes
out *against* knos, and the first version of the script reported exactly that.
Taking it apart is what made it useful: almost all of the cost is opening the
store, not coordinating. The work measured is a read and a parse - a real agent also
sends the file to a model, which this machine cannot measure without a
network, so those break-evens are ceilings.

## Every citation was checked before it was printed

Two of the sources knos answers from name a line in a file somebody is still
editing: the instruction files, and code structure. Both used to print a line
number from when the repo was last read. Both were reproduced failing - a rule
deleted from `CLAUDE.md` still being quoted at a line that had become
`## Style`, and a function still cited at `pay.py:1` after five lines were
added above it - and both now re-read the file at the moment the answer is
built:

- the file still says it, at a different line - the new line is printed
- the file no longer says it - it is not offered at all
- the file cannot be read - the citation stands, because not being able to
  check is not evidence against

The other sources are not checked, deliberately. A commit and a past session
are historical records cited by an identifier that cannot move; re-reading the
file a commit touched would not make its message truer. That is the whole
invariant: **every citation knos prints was either verified as it was printed,
or is a record whose identifier cannot change.**

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

`knos worth` is the same thing from the user's side rather than the judge's.
Every refusal in this product is invisible when it works, so a person has no
way to tell it apart from a product doing nothing - which is how it gets
uninstalled. It counts the collisions that were refused, out of the
stand-down and override records written at the time, and when there are none
it says knos is not earning its place here rather than finding a flattering
number to print.


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

- **No retained users.** Nobody has adopted Knos and kept it. 1,039 PyPI
  downloads in a week against 1 star is automated traffic, not people.
  What does exist is external validation of a different kind: **three pull
  requests merged into third-party repositories** by their maintainers
  ([caura#1299](https://github.com/caura-ai/caura/pull/1299),
  [drt#1098](https://github.com/drt-hub/drt/pull/1098),
  [stacktale#231](https://github.com/stacktale/stacktale/pull/231)), five more
  open, four closed on the merits, and
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
