# program.md: what the researcher wants (plain English)

All data in this example is SYNTHETIC, generated from a seed by `knos.autoresearch.synth`.

I want a classifier that predicts `y` from six numbers `x0..x5` as accurately as possible on data it has never seen.

Rules for the agent:

- You may change exactly one file: `train.py`. Anything else you submit is refused.
- Standard library only (the allowed imports are `ALLOWED_IMPORTS` in `src/knos/autoresearch/judge.py`). No network and no files:
  read the data only through `knos_io.rows("train" | "val" | "predict")` and write predictions to `knos_io.output()`.
- Each run has a fixed time budget (20 seconds of CPU time). Stop training before it ends.
- You see `train.csv` and `val.csv`. The referee scores you on sealed data you never see, twice, with two seeds.
  A change is kept only when the referee says it beats the current best by more than 0.003.
- Before anyone is paid, the best version and the baseline are scored once more on a second sealed set that no
  experiment ever touched. The best must beat the baseline by at least 0.05 accuracy on both seeds.

Make one change at a time and say in one line what you changed.
