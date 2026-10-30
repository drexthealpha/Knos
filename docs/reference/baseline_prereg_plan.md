# Launch-city ranking against two baselines with no model: the plan, fixed before any data is read

This file is committed, and its sha256 written in the commit message, before the script asks Qloo anything. The test
runs once. Its numbers are published on How we test Knos and in [OUTSIDE_TRUTH.md](OUTSIDE_TRUTH.md), win or lose.

Script: [scripts/test_baseline_prereg.py](../../scripts/test_baseline_prereg.py)

## The answer key

The held-out Census key of the where-demand test ([where_truth_plan.md](where_truth_plan.md)), unchanged: 30 NAICS
business types, 110 Metropolitan Statistical Areas of at least 500,000 people, and per type the 10 metros where that
business is most common per person (County Business Patterns 2023 establishments over Vintage 2023 population).

## Knos with Qloo

Each ranking names 5 metros per business type, chosen only from the 110. For Knos, the official NAICS title goes
through the live demand check (POST /api/check, the reading as typed). The card's heatmap metros (terms.metros) keep
the product's own order: metros with at least 3 cells first, by lift, then the rest by lift. The first 5 candidates.

## The two baselines, with no model

- **Qloo popularity alone.** The same card's metros, ordered by the mean Qloo popularity of their heatmap cells
  (qloo_popularity), highest first, ties by cell count then CBSA code. No taste signal decides the order.
- **Population.** The 5 most populous candidates, the same 5 for every type.

A type whose card has no heatmap metro scores 0 for both Qloo rankings. Population still answers it.

## Metric and interval

Overlap at 5: how many of a ranking's 5 metros are in that type's Census top 10, divided by 5. Mean over the types.
Paired bootstrap over the types, 2,000 resamples, seed 1, 95% percentile interval of Knos minus each baseline.

Knos beats a baseline when that interval lies above 0. It loses when the interval lies below 0. Otherwise the test
cannot tell them apart.

## Budget and order

At most 600 Qloo calls in all, counted from each card's live calls. The script checks the types in the key's order
and stops before a check once 560 calls are spent; a type it never reaches scores 0 for both Qloo rankings and is
reported. Each check is asked once and never retried.
