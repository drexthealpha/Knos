# Label 400 support messages

Budget: 40 test USDC, paid when the check passes. The deliverable is a file, not code.

**What to deliver.** `labels.csv` in the repository root: the header `id,label`, then one row for every message of
`data/items.csv`, with `label` one of `account`, `billing`, `bug`, `feature`. How you label is yours: by hand, with a
script, with a model. If a script made the file, commit it beside the file (the honest submission here has `label.py`).

**What we give you.** `data/items.csv`, the 400 messages, and `data/examples.csv`, 40 of them with the label our
support lead gave. A message can mention another topic in passing ("the two-factor code never arrives, since my last
invoice"): the label is what the customer is asking about.

**How it is judged.** The suite in `.knos/acceptance/1/` holds 120 more of the 400 messages with our labels. You are
not told which. It checks, in this order:

- the schema: the header, one row per message, no unknown id, no unknown label;
- accuracy on the 120 gold messages: at least 0.90;
- a floor for each class: recall at least 0.80 on the gold messages, so no class can be given up;
- no leakage: the 40 messages you were shown may not score more than 0.10 above the gold ones. A file that copies the
  40 visible answers and guesses the rest is refused by this rule whatever else it gets right.

Do not edit `.knos/`: a pull request that touches it is refused.

## What is in this folder

`solution/` scores 1.000 on the gold messages and 1.000 on the visible ones. `cheats/special_cases_visible/` copies the
40 visible answers and writes `billing` everywhere else: bundle 2 (the naive check: right shape, visible examples right)
accepts it; bundle 1 refuses it with accuracy 0.250, no recall on three classes, and a gap of 0.750.

[terms.json](terms.json) has the terms in one sentence and as funded. [evaluations.jsonl](evaluations.jsonl) has the
two evaluations as the meter counts them: the same order, policy (the hash of the terms) and milestone, a different
artifact (the submission's files), so two ids, one accepted and one rejected:

    id = sha256(order || artifact || policy || milestone)

**What this suite cannot check.** The 280 messages that are neither visible nor gold are judged only by inference from
the 120. The gold labels are taken as right; a wrong gold label is paid for or held against the labeller. And the gold
file is in this repository so that the example runs: the judge takes it out of the tree the submission is read from,
but a labeller who can read the repository can read it. For a file deliverable the bundle has to be somewhere the
labeller cannot read (a private repository), with only its hash in the terms. That arrangement is not exercised here.
