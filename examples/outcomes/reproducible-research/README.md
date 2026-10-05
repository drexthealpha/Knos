# Did the new triage form change the time to first reply?

Budget: 90 test USDC, paid when the result is reproduced.

**What to deliver.** Two files in the repository root:

- `analysis.py`: `python3 analysis.py <seed>` reads the trial's rows on standard input (`arm,minutes`, arm is `control`
  or `treatment`) and prints one number, the effect in minutes (treatment minus control). Python 3, standard library
  only. Everything random must come from the seed.
- `RESULT.json`: `{"claim": "<one sentence>", "estimate": <the number>, "seed": 20261005}`, the number `analysis.py`
  prints for the order's seed, 20261005.

**What we give you.** `data/trial.csv`: 240 tickets, 120 in each arm, minutes to first reply.

**How it is judged.** The suite in `.knos/acceptance/1/` keeps its own copy of the trial and runs `analysis.py` in the
sandbox:

- reproduced: with seed 20261005 it prints the claimed estimate, within 0.000001 minutes;
- repeatable: a second run with the same seed prints the same number;
- computed: the suite adds a known number of minutes to every treatment-arm value (twice, with two amounts) and the
  estimate must move by that amount, within a tenth of it. An effect is a difference between the arms; a number that
  was pasted in, or read from a file instead of the input, does not move.

## What is in this folder

`solution/` claims -2.702083 minutes (the median of 2,000 bootstrap resamples) and is reproduced exactly; the estimate
moves by -3.250000 and +1.500000 when the arm is moved by those amounts. `cheats/pasted_result/` claims -6.4 and its
script prints that number whatever it reads: bundle 2 (the naive check: run the script once, compare with the claim)
accepts it; bundle 1 reproduces the pasted number too and refuses it at "computed", because the estimate moves by 0.

[terms.json](terms.json) has the terms in one sentence and as funded. [evaluations.jsonl](evaluations.jsonl) has the
two evaluations as the meter counts them: same order, policy (the hash of the terms) and milestone, a different
artifact, so two ids, one accepted and one rejected.

**What this suite cannot check.** That the method answers the question, that the rows are the trial's real
measurements, or that the seed and the method were not chosen after looking at many. It establishes that this script
gives this number on these rows and reacts to them; whether the number means what the claim says is a reader's
judgment. The same sandbox limits apply as to any black-box bundle (no network, standard library); an analysis that
needs other packages needs a judge image that holds them (examples/acceptance/hermetic).
