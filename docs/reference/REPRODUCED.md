# Reproduced by Knos: knos.yml for research repositories

**In plain words.** A research repository says what it claims in one file, `knos.yml`. Knos runs the code again on a
second machine and on a held-out split: a data folder kept sealed from the authors, or data their own generator makes
from a seed Knos picks at run time (their code, a seed they never saw).

If every number comes back within the tolerance the authors set, the
repository gets a "Reproduced by Knos" badge and a public result page. If a number does not come back, the result goes
to the authors privately. Knos never publishes it.

This is not [REPRODUCE.md](REPRODUCE.md): that page is about checking Knos itself. This page is about checking someone's research.

## The file

```yaml
knos: 1
name: synthetic-centroid
entry: python train.py --split {split} --seed {seed} --data {data} --out {out}
data:
  generator: python make_data.py --seed {data_seed} --out {data}
  seed: 7
  protected: [results.json]
splits:
  public: test
  heldout: heldout
claims:
  - id: accuracy
    metric: accuracy
    expected: 0.8325
    tolerance: 0.02
    heldout_tolerance: 0.07
    reported: {file: results.json, key: accuracy}
compute:
  max_seconds: 600
authors:
  - github: someone
funding: https://example.org/pre-order     # optional; shown on a reproduced result page only
```

| field | meaning |
|---|---|
| `entry` | the command that computes the numbers. It writes a JSON object of metrics to `{out}` (also given as `KNOS_METRICS_OUT`) |
| `data.generator` | optional. Makes the data into `{data}` from `{data_seed}`. With it, Knos makes the held-out split itself, from a seed it picks at run time |
| `data.protected` | files the run must not change. `knos.yml` and every `reported` file are always protected |
| `claims` | each claim: the metric, the expected value, the tolerance (absolute), an optional wider `heldout_tolerance`, and optionally where the repository reports the number |
| `compute.max_seconds` | the budget for each run (at most 6 hours) |
| `authors` | who receives a private notice when a result is not reproduced |

The file is read by a small, strict parser of the YAML subset above (`src/knos/repro/spec.py`), so a `knos.yml` means
the same on every machine. Anything it does not know is an error, never a guess.

## The run

```
knos reproduce PATH [--spec knos.yml] [--heldout DIR] [--out DIR]
```

Two runs, each in a fresh copy of the repository, with an environment that carries no token, key or secret:

1. **re-run**: the public split, with the authors' data seed. This is the second machine.
2. **held-out**: the held-out split. Its data is a folder given with `--heldout` (kept sealed, never in the
   repository), or made by the generator from a seed Knos picks at run time. The result records only the seed's sha256.

A claim holds when its metric is within tolerance on both runs. The result is one of:

| result | when | public? |
|---|---|---|
| `reproduced` | every claim holds on both runs, no cheat rule fired | yes: result page, badge |
| `contested` | a claim missed, a metric was missing, or a cheat rule fired | **no**: kept private, with a notice for the authors |
| `failed` | the entry or the generator did not finish, or ran over budget | no |
| `incomplete` | there was no held-out split to run | no |

Cheat rules: `data_tamper` (a protected file changed during a run), `reported_mismatch` (the number the repository
publishes is not the number `knos.yml` claims), `metric_missing`.

## Private first

Every result is written to `<out>/private/` first: the result, the logs, and for anything not reproduced a
`NOTICE-TO-AUTHORS.md`. Knos sends nothing. Whoever ran the reproduction passes the notice to the authors. Only
`knos.repro.publish.publish` writes to `<out>/public/`, and it refuses any result that is not `reproduced`, whose
digest does not check, or that names a cheat. No flag changes this.

`tests/test_repro_privacy.py` holds it, including a disputed result edited to look reproduced.

## The badge

The badge is drawn by the same code as the "paid on proof" and "Knos-verified" badges (`knos.badge`). It says how many
claims held, that a held-out split was used, and the day. It is issued only from a result that checks; there is no other
way to get one. A reproduction says the stated numbers came back.

It does not say the method is sound.

A workflow can have GitHub sign a result: request an OIDC token with the audience `knos-research:<result sha256>`.
`knos.repro.publish.verify_signed` checks the pair with no network, using the same RS256 check as `knos reproduce --verify`.

## Try it

```
python -m knos.repro.example /tmp/ex && knos reproduce /tmp/ex                  # SYNTHETIC data: reproduced, badge
python -m knos.repro.example /tmp/bad --tamper && knos reproduce /tmp/bad       # inflated claim: contested, kept private
```

On 13 Oct 2026 the same command ran on a read-only checkout of the Knos repository itself (commit 99cc4e3e), with a spec
kept outside it.

It claimed that the playground referee's generated inputs catch every wrong solution in `tasks/` (72 of 72) and that every
reference passes its public examples (24 of 24): reproduced on the re-run and on a held-out seed.

The result file, the spec, its two scripts and `run.sh` to make them again are in
[evidence/repro-0329/](evidence/repro-0329/playground-judge.result.json).

Source: `src/knos/repro/`, tests `tests/test_repro_*.py`.
