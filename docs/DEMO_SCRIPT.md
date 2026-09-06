# Demo script - under 4 minutes, unedited, clock visible

One take. A terminal clock in shot the whole way through, so the run time is
checkable. Two panes: a terminal on the left, a file viewer on the right, per
Sibyl Labs' Builder Tip - **show the file, not just the claim**.

Nothing here is staged output. Every command is real and prints what it
prints.

## Before you start

```bash
pip install knos==0.1.6
cd <a repo you actually work in>
knos connect              # optional; only needed for the agent panes
knos guard --install      # optional; only needed for beat 3
```

Have `~/.knos/<repo>/memory.db` open in the file viewer pane, or a terminal
running `watch -n1 'ls -la ~/.knos/*/memory.db'`. The file has to be visible
for the last beat to land.

---

## Beat 1 - the failure, stated in one sentence (0:00-0:20)

Say it, do not caption it:

> Two agents are in this repo. One is rewriting the risk guard. The other is
> about to rewrite the same thing, and neither of them knows.

Show both agent windows open on the same folder. That is the whole setup.

## Beat 2 - the claim, and the refusal (0:20-1:10)

In agent A:

```
knos claim "the risk guard"
```

In agent B, ask about it - through the MCP tool, not the CLI, so it is the
agent being refused and not a person reading a warning:

> what do we know about the risk guard?

It comes back:

```
Withheld. the risk guard is being worked on right now, so knos is not the
place you find out about it. Ask them, or work on something else.

If you must have it anyway, call this again with override="your reason".
That is recorded against your name.
```

Say the line that matters: **it is not a warning attached to an answer. There
is no answer.**

## Beat 3 - the refusal reaches the edit (1:10-1:50)

Ask agent B to change the file:

> edit risk_guard.py and relax the unknown-asset check

The hook fires before the write. The tool reports the block; the file does not
change. Show the file's timestamp in the viewer pane not moving.

```
Blocked by knos: the risk guard is being worked on by Claude Code right now.
```

This is the beat most tools cannot do, because a claim that only decorates an
answer is advice. This one stops the edit.

## Beat 4 - the record leaves the machine (1:50-2:25)

```bash
knos export          # writes .knos/decisions.md
git add .knos/decisions.md && git commit -m "record what is in flight"
```

Open the file in the viewer pane. It is plain markdown; read one line of it
aloud.

Then show [pull request #1](https://github.com/drexthealpha/Knos/pull/1) in
the browser, where the Action already ran against this file, matched a
standing claim, named the holder, and exited 0. Say: **nobody on that side
installed anything.**

## Beat 5 - both partner stacks, on the same file (2:25-3:10)

```bash
npm --prefix agent run bot -- "/brief BTC"
```

It pays a live seller on Base mainnet over x402, prints the brief in plain
English, and ends with a Basescan link. Click the link on camera - the
transaction is real USDC and resolves.

```bash
npm --prefix agent run bot -- "/jobs"
```

One ACP sale, sold out of this same store. Say the honest version out loud:
**the buyer was my own test agent.** A judge will find that out; better it
comes from you.

Then, the point:

```bash
knos ask "market brief BTC"
```

The thing that was just bought comes back out of the store. **Paid once,
free to every agent on this machine afterwards.**

## Beat 6 - delete it (3:10-3:45)

```bash
rm ~/.knos/*/memory.db
```

Show the file disappear in the viewer pane. Then, in order, without cutting:

```bash
knos ask "market brief BTC"      # gone - it lived nowhere else
```

In agent B, ask about the risk guard again: **it answers.** The withhold is
not weaker, it is gone. Ask it to edit the file: **the edit goes through.**

Close on it:

> Delete the memory and this is not a worse version of the product. There is
> no product. That is what load-bearing means, and it is the whole argument.

## Beat 7 - the numbers, if there is time (3:45-4:00)

```bash
python scripts/ablation.py
```

| Arm | Store present | Store deleted |
|---|---|---|
| Withhold | refused 12/12 | refused 0/12 |
| Guard | refused 12/12 | refused 0/12 |
| Action | commented 12/12 | commented 0/12 |
| Paid | kept 12/12 | kept 0/12 |

---

## What not to do

- Do not claim users. There are none. If it comes up: *"the problem is
  measured - 1,254 of 100,057 sampled issues - the adoption is not."*
- Do not hide that the ACP buyer was your own agent.
- Do not cut. A cut in the deletion beat destroys the only thing that beat is
  for.
- Do not run beat 5 without funds in the wallet. Do a dry run first; a failed
  purchase on camera costs more than the brief is worth.
