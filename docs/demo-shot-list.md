# Demo shot list

Follow it top to bottom. Every command here was run on this machine on
5 September 2026 and produced the output shown, except the two marked
**spends money**, which are verified by their receipts rather than re-run.

**Before you start.** Touch each repo once (`cd` into it and run `git status`)
so OneDrive has rehydrated the files — a cold first read has been measured at
9s instead of 2s, and that difference is visible on camera. Close any stray
`knos` or `pytest` processes; two of them competing for the same store is what
produced a 51s outlier once before.

---

## Shot 1 — cold start, one continuous take. **Do not cut inside this shot.**

This is the pass/fail gate. If a judge cannot see a fresh session recall
something written earlier, in one unedited segment with the time or commit
visible, nothing else is scored.

```bash
git rev-parse HEAD          # commit hash on screen, unedited, before anything
date -u                     # and the clock
knos remember "the demo checkpoint is 5 September" --about demo
```

Now **quit the agent entirely** and open a new one. In the new session:

```
Ask knos what the demo checkpoint is.
```

It answers with the sentence and names the source. The hash and the clock are
already on screen from thirty seconds earlier, in the same take.

Then, still in one take:

```bash
rm ~/.knos/<repo>/memory.db
```

Ask again. It is gone. That is the deletion test the rules describe, run live.

---

## Shot 2 — the withhold hero. Strongest twenty seconds in the demo.

Two windows. Claude Code left, Cursor right.

**Claude Code:**
```
Use knos to remember you are rewriting the risk guard, and claim it.
```

**Cursor**, same question a person would actually ask:
```
Ask knos about the risk guard.
```

Cursor gets no answer:

```
Withheld. risk guard (held by Claude Code) is being worked on right now,
so knos is not the place you find out about it. Ask them, or work on
something else.
```

Say once, out loud: *"Not a warning attached to the answer. No answer."*

Then release it and show the answer come back:

```bash
knos done
```

---

## Shot 3 — the guard denies the edit. New in 0.1.5, stronger than shot 2.

Shot 2 refuses an answer. This refuses the **edit**.

```bash
knos guard --install     # says which clients it wired; Claude Code needs no restart
knos claim "the parser"
```

In Claude Code:
```
Edit src/knos/answer.py and add a comment at the top.
```

The edit is **blocked before it runs**, naming who holds it. Nothing else on
the list does this — every competitor's claim is advisory.

```bash
knos guard --uninstall   # show it comes back out cleanly
```

---

## Shot 4 — Builder Tip 02/04. Split screen, open the file.

Sibyl's tip: *"Show the file, not just the claim. An open file, read live on
screen, isn't unverifiable."* Do it exactly once — it converts every
`source:` line in the demo from an assertion into something watched.

Layout: **agent chat left, editor right.**

1. Ask the agent: `What are the rules here?`
2. It answers and cites a file and line, e.g. `AGENTS.md:3`.
3. **Open `AGENTS.md` in the right pane and scroll to line 3.** The sentence
   on screen is the sentence it just quoted.

Say: *"That came out of the file, not out of the chat history."*

---

## Shot 5 — Base, live. Grant, read, revoke.

```bash
knos share ./src --with alice.base.eth
knos unshare ./src --with alice.base.eth
```

Testnet, so it costs nothing. Have the contract open in a browser tab:
`0x955fa320D60D9172CF048141ed7eEE442da66E52` on Base Sepolia.

---

## Shot 6 — Virtuals and x402. **Spends money.**

Two ways to show this. Pick one.

**Cheapest, and enough:** show the receipts already on chain. All three
resolve — verified 5 September 2026:

- ACP job 75659, buyer funds escrow: `0x756b867b…65bd64`
- ACP job 75659, escrow releases to provider: `0x95a84c44…cbcea59`
- x402 payment for a brief: `0x2ce6af5c…4a14d9ca`

Open the agent page too — public, no account needed:
`app.virtuals.io/acp/agents/01a05b97-a776-760a-9165-e9893e4091dc`

**Live, if you want the money moving on camera** (costs $0.01):

```bash
cd agent
npx tsx bot.ts "/brief BTC"
```

It pays 0.01 USDC on Base mainnet, then writes what it bought back into the
store with `knos remember`, so the next agent on the machine gets it free.
Show that second half — the receipt landing in memory is the point, not the
payment.

**Say the honest line on camera:** every job traded through this was bought by
a test agent of mine. It proves the path executes. It is not demand.

---

## The bot, if you show it at all

Runs on the console with no Telegram account. In **PowerShell**, not Git Bash
— Git Bash rewrites a leading `/` into a Windows path and the command silently
does nothing:

```powershell
cd agent
npx tsx bot.ts "/help"
npx tsx bot.ts "/status"
npx tsx bot.ts "/jobs"
npx tsx bot.ts "/ask why does knos withhold claimed work"
```

`/news` and `/brief` spend money. The other four do not.

---

## Order and timing

| | Shot | Rough |
|---|---|---|
| 1 | Cold start, one take, delete the store | 0:00–1:00 |
| 2 | Withhold hero | 1:00–1:35 |
| 3 | Guard denies the edit | 1:35–2:05 |
| 4 | Split screen, open the cited file | 2:05–2:30 |
| 5 | Base grant → revoke | 2:30–2:50 |
| 6 | Virtuals + x402 receipts | 2:50–3:15 |

Under the 5-minute cap with room to breathe. If you have to cut one, cut 5 —
Base is the multiplier that is easiest to verify from the README links alone.
Never cut 1; it is the gate.

## What not to say

- Anything about the score, the multiplier, or the rubric.
- "Faster than git." It is not, on a small repo, and the README says so.
- Any suggestion that anyone outside this machine uses it. Nobody does.
