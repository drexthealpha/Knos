# Pitch, the two-minute cut (the finding, one transaction, the founder, the business, where it stands, the ask)

**The neutral meter for AI agent work: neither side keeps the count.**

This is the presentation video for the form. The form's own help text says the presentation runs `Up to 2 minutes`
(read signed in on 9 Oct 2026); Colosseum's page asks for "a two-to-three-minute presentation video"
([colosseum.com/hackathon](https://colosseum.com/hackathon)). This cut ends before two minutes; the longer version is
[pitch_script.md](pitch_script.md). It keeps that version's order and sentences, fewer of them: the finding first,
one transaction, the founder's record, the business, where it stands, the ask.

The spoken words are the lines that start with `>`: about 255 words, read at the pace `tests/test_pitch_cut.py`
holds them to (`2.5` words a second, the pace of the render's estimate). Each part fits before the next one starts,
and the last ends before two minutes. A spoken number is in `docs/facts.json` with its source. **No fee is spoken as
a number**: the business part shows the rate the public program ids charge, read from the chain while it is recorded.

Render it with no one at the keyboard (Piper or edge-tts, Chromium and ffmpeg: see `scripts/video/render.py`):

```
python scripts/video/render.py --script docs/submission/pitch_script_120.md
```

The lines `<!-- ... -->` below tell the render what to show; a reader of this page never sees them. A page is
photographed once it has drawn (`wait:`, seconds after it loads): the Agent PR Index draws its table from its data,
and the price view asks the program for its fee, then is scrolled down to the row that answer fills. The render
stops before anything is recorded if the voice runs over the limit.

<!-- `title: Knos in two minutes` -->
<!-- `voice: piper:en_US-lessac-medium, edge:en-US-AriaNeural` -->
<!-- `limit: 120` -->

## 1. The finding (0:00)

*On screen: the Agent PR Index, one row per agent.*

<!-- `show: url https://drexthealpha.github.io/Knos/#index` -->
<!-- `wait: 12` -->

> Of 241 merged agent pull requests claiming passing tests, 9 failed a test, build, lint or type check. That is
> GitHub's own record at the head commit, and each was merged anyway. Somebody approved an invoice for that work.

## 2. One transaction, seven steps (0:18)

*On screen: the site's story, the seven steps in order.*

<!-- `show: url https://drexthealpha.github.io/Knos/#story` -->
<!-- `scroll: 2400` -->

> Knos is the neutral meter for AI agent work: neither side keeps the count. One transaction. Agree: the price and
> the acceptance terms are fixed first. Fails: the agent edits the test, not the bug; the check refuses it, and no
> money moves. Passes: the corrected work meets the same check. Statement: both sides rebuild the same bill from
> their own ledgers. Replay: the same proof twice pays nothing. Pay: GitHub signs the run that judged the work; a
> Solana program checks that signature itself and releases the money. Verify: anyone checks the receipt offline.
> Why Solana? Money is released with no custodian, and the count is anchored where neither side can alter it.

## 3. The founder (1:07)

*On screen: the Sibyl Labs leaderboard.*

<!-- `show: url https://hack.sibyllabs.org/leaderboard` -->

> I am one founder, and I built all of it. My earlier product, a shared memory for coding agents, took first place
> of 92 teams at the Sibyl Labs hackathon.

## 4. The business (1:21)

*On screen: the price book, and the rate the public program ids charge today, read from the chain.*

<!-- `show: url https://drexthealpha.github.io/Knos/#pricing` -->
<!-- `wait: 20` -->
<!-- `scroll: 540` -->

> The check is free. Knos earns one fee, paid by the funder on top, when value is released against a signed
> acceptance. The supplier never pays.

## 5. Where it stands (1:33)

*On screen: the Numbers view, Knos's own accounts kept apart.*

<!-- `show: url https://drexthealpha.github.io/Knos/#network` -->
<!-- `wait: 3` -->

> Where it stands, in one sentence: Solana devnet, test money, one person holds every key, no outside review,
> nobody has paid, and one other GitHub account was paid 3 times, on tasks I funded.

## 6. The ask (1:48)

*On screen: the front door, with the paste box.*

<!-- `show: url https://drexthealpha.github.io/Knos/` -->

> The ask: be the first buyer to run a real invoice through the check.
