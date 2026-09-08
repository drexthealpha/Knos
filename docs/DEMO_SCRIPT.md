# Demo script - unedited, clock visible

One take. A terminal clock in shot the whole way through, so the run time is
checkable. Two panes: a terminal on the left, a file viewer on the right, per
Sibyl Labs' Builder Tip - **show the file, not just the claim**.

Nothing here is staged output. Every command is real and prints what it
prints.

## If you are recording this and you did not build it

You need three things: **Python 3.10 or newer, git, and a repo you actually
work in with at least one commit.** Nothing else. No account, no key, no
network - the read path opens no socket and that is
[a test](../tests/test_no_network.py), not a promise.

```bash
pip install "git+https://github.com/drexthealpha/Knos"
knos demo
```

That installs from the repository rather than PyPI on purpose. The last
release, 0.1.8, predates `knos who` and the ninth beat, so a recording made
against it would not match this script.

Do not be thrown by `knos --version` saying `0.1.8`: that is the last number
cut, and it stays until the next release because the desktop extension pins
it. What you have installed is whatever is on `main`.

That is the whole short route and it needs nothing of yours: it builds a
throwaway repo, does everything on that, and deletes it afterwards.

**Use your own repo for the long route.** It is a better film than a toy one,
because the claims land on real filenames and `knos ask` answers out of your
actual `CLAUDE.md` or `AGENTS.md`. Knos reads the repo; it does not change a
single file in it. The store lives in `~/.knos/<your repo>/memory.db`, outside
your tree, and `knos forget` removes it.

**One thing is off by default and you have to turn it on.**

```bash
knos guard --install
```

Without it, beat 3 - the refusal reaching the edit itself - silently does not
happen. The hook is not installed by `knos connect` on purpose, because a hook
that wrongly denies an edit is worse than no hook at all. `knos guard
--uninstall` takes it back out and it touches nothing else.

**Do not run beat 5 unless the wallet is yours and funded.** It spends real
USDC on Base mainnet. If you are recording on somebody else's behalf, skip it
and say the receipts are in `docs/VERIFICATION.md` - they resolve on-chain and
anybody can check them with `python scripts/verify_receipts.py`.

**Run `knos receipts` on camera, straight after the demo.** It takes about
fifteen seconds and it is the whole partner-stack argument in one shot: eleven
transactions resolved live against Base mainnet and Base Sepolia, block numbers
printed, USDC seen in the logs of all eight mainnet ones. No key, no account, no
wallet - so it is safe for anybody to run, unlike beat 5.

The judging rules want an executed on-chain action *shown in the demo*. This is
that action being resolved against the chain while the clock runs, rather than a
hash in a document that a judge has to go and check afterwards.

**Two moments must be in one unbroken take, whichever route you record.**

1. **A fresh process reading back earlier state.** In `knos demo` this is beat
   7: a separate interpreter prints its own pid next to the repo's commit hash
   and the wall clock, then reads back what an earlier process wrote. In the
   staged route it is opening a second agent window and watching it be refused.
2. **The store being deleted, and everything stopping.** Beat 9 of `knos
   demo`, or beat 6 of the staged route.

A cut between those two is the one edit that ruins the recording, because the
whole argument is that the second follows from the first.

**Keep a clock in shot.** A terminal clock, or `watch -n1 date` in a corner
pane. It is what makes the take checkably continuous.

**If something goes wrong on camera, keep rolling.** A refusal you did not
expect is worth more than a clean take - it is the product working. The only
failure worth restarting for is a command that errors out.

---

## The short route: one command, one take

`knos demo` now does the whole argument by itself, in about half a minute,
against a throwaway repo it deletes afterwards. Every line is a real call.

```bash
pip install "git+https://github.com/drexthealpha/Knos"
knos demo
```

Record that uncut, with a clock in shot, and the gate's two required pieces
of evidence are both in one continuous segment:

- **Beat 7, cold-start recall.** A separate interpreter, handed nothing but
  the repo path, prints its own pid next to the repo's commit hash and the
  wall clock, then reads back what an earlier process wrote. That is a fresh
  session recalling earlier state with an on-screen commit hash, which is what
  the rules ask for in those words.
- **Beat 9, the deletion test.** The store is deleted on camera and every
  refusal is re-run: the withhold gone, the edit allowed, the paid answer
  buying again, the held decisions released, and every agent's record
  forgotten.

Beat 8 in between is the part worth narrating over: the store showing which
agents finish what they claim, and the hold each has earned by it.

If you have four minutes and a funded wallet, the staged version below is the
better film - two real agent windows, a real purchase, the store visible in a
second pane. If you have one take and no appetite for something failing live,
record the command above.

---

## The long route: staged, two agents

## Before you start

```bash
pip install "git+https://github.com/drexthealpha/Knos"
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

Then the beat that makes memory expensive to lose. Run the **same command
again**:

```bash
npm --prefix agent run bot -- "/brief BTC"
```

```
Free. This machine already paid for it once, so nobody paid again.
```

No transaction. No Basescan link. The store answered, and the money stayed in
the wallet. Say it plainly: **the memory is what decided not to spend.**

Now claim it and try once more:

```bash
knos claim "market brief: BTC"
npm --prefix agent run bot -- "/brief BTC"
```

```
Withheld. ... Nothing was bought. You are on this right now, so a paid answer
would be out of date before it arrived.
```

**A claim did not warn about a purchase. It stopped one.**

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
And run `/brief BTC` once more: it **pays again**, on camera, for something
this machine had already bought.

Close on it:

> Delete the memory and this is not a worse version of the product. There is
> no product. That is what load-bearing means, and it is the whole argument.

## Beat 7 - the numbers, if there is time (3:45-4:00)

```bash
python scripts/ablation.py
```

| Arm | Store present | Store deleted |
|---|---|---|
| Spend: same request twice | paid again 0/12 | paid again 12/12 |
| Spend: while somebody holds it | refused 12/12 | no claim survives |
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
