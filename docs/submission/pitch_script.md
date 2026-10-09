# Pitch (under three minutes: the finding, one story, the founder, the business, where it stands, the ask)

**The neutral meter for AI agent work: neither side keeps the count.**

Buyers and suppliers verify what AI work earned payment, then carry that evidence from authorisation through invoice approval to settlement.

The presentation opens on the Agent PR Index finding, then tells ONE story: one transaction in seven steps (agree,
fails, passes, statement, replay, pay, verify), the same seven as the demonstration ([demo_script.md](demo_script.md)),
the site's story and [STORY.md](../STORY.md). Then the founder's record in one sentence, the business, where it
stands in one sentence, and the ask. What is on screen is cut from the demonstration's beats, in their order, and a
clip keeps its captions. A judge's one page is [JUDGES.md](../JUDGES.md); its first link is the release manifest.

The spoken words are the lines that start with `>`: about 420 words, under three minutes read aloud at an even
pace (`tests/test_site_scripts.py` counts them and checks each part fits before the next starts). The time in each heading is where the part starts.

A spoken number is in `docs/facts.json` with its source, and `python scripts/claims_check.py` checks it. The finding
is the count in [backtest.json](../backtest.json), made by `scripts/backtest.py` from the pull requests in
[agent_pr_ci.json](../agent_pr_ci.json); the per-agent rates are the weekly [Agent PR Index](../INDEX.md). The
founder's record is on [the leaderboard](https://hack.sibyllabs.org/leaderboard) and in [TEAM.md](../TEAM.md).
**No fee is spoken as a number**: the public program ids charge what the build live there charges, which changes
when an approved upgrade executes, so the business part shows the fee read from the chain while it is recorded. A
buyer, a pilot or an interview is said only if it exists and the other party agrees to be named. Where it stands is
one sentence and no count is read out as a list; every limit is in [DISCLOSURE.md](../DISCLOSURE.md) and every count
in [NUMBERS.md](NUMBERS.md).

## 1. The finding (0:00)

*On screen: the number and its basis; then the Agent PR Index, one row per agent.*

> Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check. That is GitHub's own record
> at the head commit, for pull requests AI coding agents opened between July and September, and each was merged
> anyway. Our weekly Agent PR Index counts it for each agent, and the rate differs widely between them. Somebody
> approved an invoice for that work.

## 2. One transaction, seven steps (0:26)

*On screen, the demonstration's seven beats in order: the agreement; the refusal with its reason, the balance
unchanged; the corrected submission accepted; the two terminals with one statement; the refused replay; the
payment, the fee read from the chain; the verifier with the network off.*

> Knos is the neutral meter for AI agent work: neither side keeps the count. Here is one transaction. Agree:
> buyer and supplier fix the price and the acceptance terms before the work starts. Fails: the agent edits the
> test instead of fixing the bug; the check refuses it, with the reason, and no money moves. Passes: the corrected
> work meets the same check. Statement: buyer and supplier each rebuild the bill from their own ledger, and get the
> same bill, line for line. Replay: the same proof sent twice pays nothing. Pay: GitHub signs the run that
> judged the work, and a Solana program checks that signature itself and releases the money: no company holds it,
> and no oracle reports it. Verify: anyone checks the receipt offline, with nothing from Knos. Why Solana? Money is
> released with no custodian, and the count is anchored where neither side can alter it.

## 3. The evidence (1:27)

*On screen: the tamper benchmark; then the Numbers page.*

> What we measured. Plain CI passed 56 of 63 submissions that edit the test, and the black-box check refused all 63.
> From merge to paid took 25 seconds at the median, on devnet. But an invoice waits on the person who approves it,
> not on the payment, and we have not measured that wait with a buyer.

## 4. The founder (1:50)

*On screen: the Sibyl Labs leaderboard; then the dated history in DISCLOSURE.md.*

> I am one founder, and I built all of it. Before this hackathon, I built Knos's earlier product, a shared memory
> for coding agents, and it took first place of 92 teams at the Sibyl Labs hackathon. Its memory engine still holds
> what Knos remembers.

## 5. The business (2:08)

*On screen: the price book, and the fee the public program ids charge today, read from the chain.*

> The check is free. Knos earns one fee, when value is released against a signed acceptance: a fee the program
> collects, paid by the funder on top. The rate on screen is the one the program charges today. The supplier never
> pays.

## 6. Where it stands (2:25)

*On screen: the limits as one line.*

> Where it stands, in one sentence: Solana devnet, test money, one person holds every key, no outside review, no
> outside funder, nobody has paid, and one other GitHub account was paid 3 times, in test money, on tasks I funded.

## 7. The ask (2:41)

*On screen: the front door, with the paste box.*

> The ask. Be the first buyer to run one real invoice through the check, or the first outside key holder. Both
> start from the link on screen.

*Closing card:* The neutral meter for AI agent work: neither side keeps the count. Below it, the second line:
buyers and suppliers verify what AI work earned payment, then carry that evidence from authorisation through
invoice approval to settlement.
