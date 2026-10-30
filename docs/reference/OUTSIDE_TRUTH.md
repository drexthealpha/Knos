<img src="../../web/brand/mark.svg" height="40" alt="Knos">

# Outside truth: open signals against 200 past SBIR awards

**In plain words.** We asked Knos's open-signals check about 200 past research awards whose outcome is known. It did no better than a coin: 47.5% right, where always guessing one side gets 50%. We publish it as measured.

| Measure | Value |
|---|---|
| Awards | 200: 100 commercialized, 100 not |
| Accuracy | 47.5% (base rate 50%) |
| Precision / recall | 47.1% / 40.0% |
| p, binomial vs base rate | 0.78 |
| p, Fisher's exact | 0.57 |

- **Population:** Defense Department SBIR/STTR Phase I awards, 2005 to 2014, with an abstract on sbir.gov.
- **Commercialized:** a granted US patent linked to the award's contract (Zenodo, 10.5281/zenodo.17018422). **Not:** no patent and no Phase II on the same topic.
- **What Knos saw:** one phrase, the award's title or the abstract's first sentence. OPEN counts as a prediction of commercialized.
- **Why it can fail:** open signals measure public attention today, not whether a 2010 defense prototype was patented. A patent is invention, not sales.
- **Since:** the refuse list now applies to demand checks, so ideas naming weapons would be refused, not scored.

Numbers, method and sources: [outside_truth.json](outside_truth.json). Run it again: `python scripts/outside_truth.py <sample.json> --public` (the sample is built from the two public datasets above).

## Crowdfunded launches: 250 held-out projects

**In plain words.** The same question on a public dataset of crowdfunded product launches: did a past project reach its goal? Here 78.8% of the held-out projects succeeded, so always guessing "successful" scores 78.8%. A predictor has to beat that, not 50%. Run 24 Oct 2026, 500 of 500 rows answered.

| Measure, held-out (n=250) | (a) Open signals | (b) Open signals + Qloo |
|---|---|---|
| Accuracy | 64.0% | 59.6% |
| Base rate | 78.8% | 78.8% |
| p, binomial vs base rate | 1.0 | 1.0 |
| p, Fisher's exact | 0.86 | 0.87 |
| Confusion (tp / fp / fn / tn) | 145 / 38 / 52 / 15 | 130 / 34 / 67 / 19 |
| OPEN means (tuned) | failed | failed |

- **Result:** neither predictor beats always guessing "successful". Adding Qloo lowered accuracy by 4.4 points. Like the SBIR result, a demand check is not a forecast of a campaign's outcome.
- **Sample:** 500 successful or failed projects launched 2019 to 2023, from the webrobots.io dump of 2026-10-12, drawn per main category in proportion (seed 0).
- **Split:** 250 tune, 250 held-out, half of each outcome on each side. The tune half picks one thing per predictor: whether OPEN means success or failure.
- **What Knos saw:** the name, the blurb and the category, at most about 200 characters. A refused idea counts as not OPEN.
- **Reading:** the dump is a scrape of the crowdfunding site's pages, not the full archive. Open signals measure attention today, not a 2021 campaign's backers.

Numbers, method and source: [the result file](kickstarter_truth.json).

### Tuned on the 250, scored once on the held-out 250

The same rows, now read as numbers instead of one verdict: Wikipedia views and Hacker News stories, the Qloo matches, the
leader's popularity, the top audience affinity, cities and price tier, and each category's success rate in the tune half.

A logistic model was fit on the 250 tune rows only, its cut-off set there too, and the held-out 250 were scored once.

| Measure, held-out (n=250) | (a) Open signals, tuned | (b) Open signals + Qloo, tuned |
|---|---|---|
| Accuracy | 76.8% | 78.0% |
| Base rate | 78.8% | 78.8% |
| p, binomial vs base rate | 0.80 | 0.66 |
| p, Fisher's exact | 0.056 | 0.14 |
| Confusion (tp / fp / fn / tn) | 183 / 44 / 14 / 9 | 190 / 48 / 7 / 5 |

- **Result:** tuning lifts both, and Qloo adds 1.2 points over the open signals, but neither beats always guessing "successful". Past funding outcomes are not what a demand check measures.

Numbers, weights and method: [the tuned result file](kickstarter_truth_tuned.json).

Run it again: `python scripts/test_kickstarter_truth.py <ks-sample.json>` (build the sample with `--build` from the dump above).

The tuned one: `--collect <ks-sample.json> <features.json>`, then `--tuned <ks-sample.json> <features.json>`.

## Crowdfunded launches: 300 projects ranked

**In plain words.** A ranking question this time: does the demand score put the projects that raised the most (pledged over goal) near the top? 300 new projects, none from the earlier 500. The rules were committed before the run, and it ran once.

| Measure (n=300) | Value |
|---|---|
| Spearman, (a) open signals | 0.113 |
| Spearman, (b) open signals + Qloo | 0.108 |
| Difference, (b) minus (a) | -0.006 |
| 95% interval, 2,000 paired bootstrap resamples (seed 1) | [-0.037, +0.025] |

- **Result:** The interval spans zero, so this test cannot tell whether Qloo helps the ranking.
- **Plan:** [qloo_lift_ranked_plan.md](qloo_lift_ranked_plan.md), sha256 `f5fc2b93dec35d813fd921962c85860a415dada508a266c274048340ea0d1da6`, committed before any row was scored.
- **Sample:** successful or failed projects launched 2019 to 2023 from the webrobots.io dump of 2026-10-12, drawn with seed 1.
- **Scores:** the two tuned models above, fit on the earlier 250 tune rows only; none of these 300 was used to fit them.

Numbers: [qloo_lift_ranked.json](qloo_lift_ranked.json). Run it again: `python scripts/test_qloo_lift_ranked.py --score <ks-sample.json> <ks-features.json> <lift-sample.json> <lift-features.json>`.

## Launch city against two baselines with no model: 30 kinds of business (30 Oct 2026)

The plan was committed before any Qloo call: [baseline_prereg_plan.md](baseline_prereg_plan.md) (sha256
5fdfe5705e8461c1aa81a7018c09048398891f02b9f1d3ab16e42c4f4e322028). The answer key is the where-demand test's, unchanged. Each ranking names 5 of the 110 metros of
at least 500,000 people per business type.

Knos with Qloo scored 0.087, Qloo popularity alone 0.053 and population 0.107 (overlap at 5, n 30,
574 Qloo calls). Against popularity alone Knos gained +0.033, interval [+0.007, +0.067]: Knos is ahead.

Against population Knos was -0.020, interval [-0.093, +0.047]: the test cannot tell them apart. Only 7 of
30 types brought heatmap metros; 1 type was never asked, by the plan's budget stop.

Numbers, per type and method: [the result file](baseline_prereg.json).

## Launch city, pre-registered: 134 kinds of business against the Census (30 Oct 2026)

The plan was committed before any call or prediction: [impact_prereg_plan.md](impact_prereg_plan.md) (sha256
6e08a9f488196f64da5f302c7f774bd31e2bf534c6adde2ef172073121e4dd13).

Knos's arm takes each business type's Qloo taste tags
and their heatmap, then ranks the 15 most populous metros by lift, the method the product now uses for its launch city.
Qloo answered every heatmap request with no cells (255 Qloo calls in all), so the Knos arm fell back to the population
order.

| sample | n | Claude alone | population | Knos with Qloo | placebo | Knos minus Claude, 95% interval |
|---|---|---|---|---|---|---|
| main | 67 | 0.319 | 0.096 | 0.096 | 0.096 | -0.224 [-0.301, -0.140] |
| replication | 67 | 0.382 | 0.069 | 0.069 | 0.069 | -0.313 [-0.388, -0.236] |

The plan's pass rule needs every interval above 0: this run fails it, and Knos loses to the model alone at naming
where a kind of business is dense. Raw numbers: [impact_prereg.json](impact_prereg.json).

## Where demand is: 30 kinds of business against the Census

**In plain words.** For 30 kinds of local business, each side named the 5 large US metros where that business is most
common per person. Census County Business Patterns 2023 gives the true top 10. Claude alone did better than Knos with
Qloo, and the interval stays below zero.

A heatmap of taste says where fans of a product cluster, which is a different
thing from where shops of that kind are dense.

| Measure (n=30 business types) | Value |
|---|---|
| Overlap at 5 with the Census top 10, Claude alone | 0.407 |
| Overlap at 5 with the Census top 10, Knos with Qloo | 0.193 |
| Difference, Knos minus Claude | -0.213 |
| 95% interval, 2,000 paired bootstrap resamples (seed 1) | [-0.360, -0.060] |

- **Plan:** [where_truth_plan.md](where_truth_plan.md), sha256 `86b76b6640ef74759d733c5cf12f4b2b126b59385f140b5423d18908cf4da0c0`, committed before either side predicted.
- **Truth:** establishments per 100,000 people (cbp23msa over Vintage 2023 population), among the 110 metros of at least 500,000 people.
- **Claude alone:** 2.1.267 (Claude Code), model claude-opus-5[1m]. It began 18 of its 30 answers with a sentence about data it could not fetch, and 4 named no metro; those lines count as misses.
- **Knos with Qloo:** the demand check's heatmap metros. 18 of 30 titles brought metros; the check refused "Museums" for being under 8 characters, which scores 0.

Numbers and every metro named: [where_truth.json](where_truth.json). Run it again: `python scripts/test_where_truth.py` (its four steps are in the file).

## Taste: which films a film's fans also love

**In plain words.** For 30 films, each side named the 5 films that the film's fans most likely also love. The truth
comes from MovieLens 32M: the films those fans rated highly far more often than everyone else did. This is the
question behind "they also love" in every Knos result.

Knos with Qloo scored a little higher than Claude alone, and
the interval spans zero, so this test cannot tell them apart.

| Measure (n=30 films) | Value |
|---|---|
| Overlap at 5 with the MovieLens top 10, Claude alone | 0.307 |
| Overlap at 5 with the MovieLens top 10, Knos with Qloo | 0.320 |
| Difference, Knos minus Claude | +0.013 |
| 95% interval, 2,000 paired bootstrap resamples (seed 3) | [-0.060, +0.087] |

- **Plan:** [taste_truth_plan.md](taste_truth_plan.md), sha256 `b65eb3d437acbec06eaea9c4064c81acada2c2aa3e73b55ea678128bd4438c01`, committed before either side predicted.
- **Data:** F. Maxwell Harper and Joseph A. Konstan (2015), "The MovieLens Datasets: History and Context", ACM Transactions on Interactive Intelligent Systems 5(4). 32,000,204 ratings by 200,948 people; the data is not in this repository.
- **Truth:** fans rated the film 4.5 or more; a candidate film needs 5,000 ratings and 300 fans who rated it 4.5 or more; the top 10 by lift over all users.
- **Claude alone:** 2.1.267 (Claude Code), model claude-opus-5[1m], web tools denied. 15 of its 150 lines matched no MovieLens title under the plan's mapping, so 11 films had fewer than 5 scored.
- **Knos with Qloo:** Knos's own Qloo client, search then insights for films; all 30 films resolved.

Numbers and every film named: [taste_truth.json](taste_truth.json).
