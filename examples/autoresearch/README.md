# Autoresearch, minimal example (SYNTHETIC data, CPU, about a minute)

A researcher's folder for `knos.autoresearch`. Everything here is a demonstration on synthetic data.

    program.md            what the researcher wants, in plain English
    idea.md               the starting idea
    task.json             the terms: the one editable file, metric, time budget, keep / re-run / graduation bars, data
    train.py              the ONE file an agent edits (the baseline: linear logistic regression, standard library)
    referee/sealed.json   the referee's sealed seed for the hidden sets; task.json commits to its sha256.
                          SAMPLE ONLY: it is in the repository so anyone can reproduce the run, which means anyone who
                          reads it can see the hidden sets. A real referee keeps it off the agent's machine.

Run it (no key, no network; the default proposer is deterministic):

    PYTHONPATH=src python -m knos.autoresearch run examples/autoresearch --out /tmp/ar --iterations 12

With a coding agent proposing instead (its own login/key; Knos neither reads nor stores it):

    PYTHONPATH=src python -m knos.autoresearch run examples/autoresearch --proposer "cmd:claude -p"

Outputs: `/tmp/ar/results.tsv` (one row per experiment), `/tmp/ar/best_train.py`, `/tmp/ar/summary.json`, and the
record in `/tmp/ar/record/`.
