# Knos - Memory Model

How the five Sibyl tiers are used, what lives in each, and why that mapping is
not decoration. All of it is one file: `~/.knos/<repo>/memory.db`.

## Principles

1. **One store.** Every surface - the MCP tools, the guard, the money gate, the
   export the Action reads - goes through
   [`memory.py`](../src/knos/memory.py). No surface keeps its own copy. The
   moment one does, "delete it and the product dies" stops being true, and
   that sentence is the product.
2. **Different shapes of truth get different tiers.** A claim is about *now*
   and is overwritten. A decision is a named thing replaced in place. History
   is only ever appended to. Using one key-value bucket for all three would
   make every one of them wrong in a different way.
3. **Nothing derived is precious.** Commits, sessions and code structure are
   re-read from the repo on demand. What Knos was *told* has no second copy.
   That distinction is what makes the deletion test honest: half of it comes
   back, and the half that matters does not.
4. **Refusal, not advice.** The store exists so a surface can say no. If a
   tier's contents cannot change an outcome, it should not be written.

## Tiers

### HOT - the live claim

One row per topic, overwritten, expiring on its own.

- **Written by** `Memory.claim_if_free`, `Memory.working_on`
- **Read by** `mcp._held`, `guard.check`, `gate.decide`, `core.Claims`
- **Lifetime** `INTENT_HOLDS = 30` minutes, then it lapses whether or not
  anyone said `knos done`

The expiry is deliberate. A crashed agent must not be able to hold work for
ever, and a coordination tool whose stale locks outlive their owner gets
switched off within a week.

One row **per topic**, not one for the whole repo: two agents on genuinely
separate things can both hold, and a third asking about either is told about
that one only.

The write is a compare-and-swap, not a set. Two agents reaching for the same
work in the same second both write; exactly one wins.

### WARM - decisions and named things

One canonical record per thing, replaced in place, unique on
`(tenant_id, category, name)` at the schema level.

- **Categories** `topic` (decisions and notes), `suspect` (things resting on a
  reversed decision), `stood_down`, `overrode`
- **Written by** `Memory.note_thing`, via `knos remember`, `knos changed`, and
  the bot after a purchase
- **Read by** `answer.ask`, `knos export`, `decide.is_suspect`

This is the tier a `CLAUDE.md` would have held, except it is queryable, it
carries when it was written, and something reads it back to refuse on.

### COLD - the journal

Append-only. What was learned, when, and from which source.

- **Written by** `Memory.record`
- **Read by** `knos status`, `knos notes`, `answer.ask`

Every override lands here under the overriding agent's own name, as does every
stand-down and every reversal. It is the audit trail that makes an advisory
rule real: you can take claimed work, and the reason you gave is written down
where the person can read it.

### REFERENCE - facts that do not change

Repo structure and things re-derivable from the tree. Cheap to lose, so it is
the first thing that goes when the cap is close.

### ARCHIVE - superseded

The old wording of a reversed decision, and cleared suspicions.

- **Written by** `Memory.supersede`, via `decide.supersede` and
  `decide.reconsider`

This tier is why `knos changed` archives rather than overwrites. "Why did we
do it that way" has to stay answerable after the answer changes, and a
decision that is simply replaced destroys exactly the context somebody will
need in three weeks.
[`tests/test_decide.py`](../tests/test_decide.py) asserts the archived row is
there rather than the old note having been dropped.

## The 5 MB cap

Sibyl's free tier is 5 MB and Knos treats it as a hard cap rather than a
suggestion.

Sibyl re-measures the whole database on every write to keep the cap honest,
which is roughly 70% of the cost of writing one fact - and reading a repo
writes hundreds. So `_cap_gate` measures for real whenever the store is near
full and estimates while it is comfortably below (`relaxed` is 80% of the
cap). The cap is enforced exactly where it matters and guessed only where
guessing cannot cross it.

**A full store refuses a claim in words rather than dropping it.** That is the
one path where silently doing nothing would be worst: a claim that did not
land is a collision nobody was warned about.

## What a reversal does across the tiers

`knos changed "the risk guard" "unknown assets pass with a warning"`:

| Tier | What happens |
|---|---|
| ARCHIVE | the old wording is kept, with who changed it and when |
| WARM | the new wording takes the name |
| WARM (`suspect`) | everything on the same subject is marked, with was/now |
| COLD | the journal records the reversal and how many things it touched |

And then HOT is not touched at all - a reversal is not a claim - but the
`suspect` rows are read by `guard.check` and `gate.decide`, so the consequence
lands on the edit and on the money.

## Retrieval flow

1. `answer.ask` runs FTS5 over WARM and COLD.
2. Anything covered by a live HOT claim held by somebody else is **removed
   from the result** and replaced with who holds it. Not annotated. Removed.
3. What survives is returned with its source: a commit, a session and a date,
   or a file and a line.

No embeddings, no reranker, no model. The cost is that a question whose words
never appear cannot be answered. The benefit is that every answer is a passage
a human wrote, and that `tests/test_no_network.py` passes.

## Anti-goals

- **No vector search.** Stated as a limit in the judge guide rather than
  hidden.
- **No cross-machine sync.** `knos export` writes a file you commit; git is
  the transport. There is no server and nothing to run.
- **No second cache.** See principle 1.
- **No unbounded growth.** 5 MB, enforced, with a refusal rather than a drop.
