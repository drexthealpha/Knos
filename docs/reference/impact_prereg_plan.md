# Launch-city impact test: the plan, fixed before any prediction

This file is committed, and its sha256 recorded, before any arm predicts anything and before any Qloo call. The test
runs once per sample. Its numbers are published in [OUTSIDE_TRUTH.md](OUTSIDE_TRUTH.md) and on How we test Knos,
beside D1 and E4, whatever they show.

Script: [scripts/test_impact_prereg.py](../../scripts/test_impact_prereg.py)

## The rules, as written before the run

K6 test_impact_prereg (Impact; needs Qloo answering)
- This replaces J4 if J4 did not run.
- Method: CHAMPION6 H7 (v0328\research\TASK-CHAMPION6-spec-2026-10-26.md), with these changes.
- Samples:
  - From the 6-digit NAICS codes in sectors 44-45, 71, 72 and 81 present in cbp23msa that D1 and H7 did not use, the main sample is random.Random(4).sample of 75 codes.
  - The replication sample is random.Random(5).sample of 75 more codes, disjoint from the main sample.
  - If fewer than 150 codes exist, split the codes that do exist in half with the same seeds and log the n.
- Arms:
  - (a) Claude alone, the D1 prompt;
  - (b) population alone, the top 5 CBSAs by POPESTIMATE2023;
  - (c) PRIMARY: the top 15 CBSAs by population, reranked by the lift method from H3, top 5;
  - (d) placebo: the same as (c), with lift values shuffled across CBSAs by random.Random(4);
  - (e) pure lift (H3), secondary.
- Before the run, change the product's launch-city ranking to method (c), so the test measures the product.
- Metric: overlap at 5 with the truth top 10.
- Statistics: paired bootstrap, 2,000 resamples, seed 4, giving 95% intervals for (c)-(a), (c)-(b) and (c)-(d).
- Commit the plan and its sha256 before any Qloo call or prediction. Run once per sample.
- Publish whatever it shows on How we test Knos and OUTSIDE_TRUTH.md, beside D1 and E4.
- If Qloo answers 429 at the start: BLOCKED, do not run. Retest once at the start of each later test until K9, then stop.
- Pass: on the main sample, the intervals (c)-(a) and (c)-(b) are both above 0, and (c)-(d) is above 0; the replication has the same sign. Either way, it is published.

The later rule that runs it (C10b):
- Run CHAMPION10's M8 and CHAMPION12's K6 pre-registered live test again, after A1 and N1, once, within 1,200 Qloo calls.
- Use the plan files exactly as committed. Never edit a plan.

### The rules it points to

H7 test_where_lift (new pre-registered test; needs Qloo answering)
- Same method as CHAMPION2 D1 (v0328\research\TASK-CHAMPION2-spec-2026-10-25.md section D1 and the C1 section it points to), with these changes: 30 NEW NAICS codes (none of D1's 30), chosen with Python random.Random(4).sample from 6-digit consumer codes in NAICS sectors 44-45, 71, 72 and 81 present in cbp23msa, listed in the plan before any prediction. Three arms: (a) Claude alone, same prompt; (b) population alone, top 5 candidate metros by POPESTIMATE2023; (c) Knos with Qloo using H3's lift ranking.
- Metric: overlap at 5 with the truth top 10; paired bootstrap 2,000 resamples, seed 4, intervals for (c)-(b) and (c)-(a).
- Commit the plan and its sha256 before any prediction. Run once. Publish on How we test Knos and OUTSIDE_TRUTH.md beside D1 and E4, whatever it shows, with one line saying this is the third outside test of Knos with Qloo and why the method changed (raw heatmap tracks popularity).
- If Qloo still answers 429 when this test starts: BLOCKED, do not run.
- Pass: interval (c)-(b) above 0. Either way, published.

H3, the lift ranking (method 2 is the one that runs: docs.qloo.com documents no heatmap request without an interest
signal, so no baseline heatmap is fetched; apps/wanted/knos_wanted/metros.py records the same):
- Rank launch metros by lift, not raw affinity. Method in this order: (1) if the current docs allow a heatmap request with no interest signal for the same filter.type and location, fetch it once per region (cache 30 days) and set cell lift = cell affinity / baseline cell affinity, matched by geohash; (2) otherwise set metro lift = mean cell affinity / (metro population share among candidate metros). Record which method ran.

D1 and the C1 rules it points to, as fixed in [where_truth_plan.md](where_truth_plan.md):

D1 test_where_truth (replaces C1; no API key, no account)
- Truth file: https://www2.census.gov/programs-surveys/cbp/datasets/2023/cbp23msa.zip (County Business Patterns 2023, metro areas, all NAICS levels). Layout: https://www2.census.gov/programs-surveys/cbp/technical-documentation/records-layouts/2018_record_layouts/metro-area-layout-2018.txt . Read the layout to find the area-code, NAICS and establishment-count columns; log the names you used.
- Population file: https://www2.census.gov/programs-surveys/popest/datasets/2020-2023/metro/totals/cbsa-est2023-alldata.csv . Columns CBSA, LSAD, POPESTIMATE2023. Keep rows whose LSAD is "Metropolitan Statistical Area".
- Download both into one new empty folder; parse with python -I; never run anything from inside the zip.
- Candidate metros: Metropolitan Statistical Areas with POPESTIMATE2023 of at least 500,000. Both predictors choose only from these.
- The 30 NAICS codes, the business-type phrase (official NAICS title), the claude -p prompt, the CBSA name matching, the Knos heatmap-to-CBSA method (TIGER/Line 2023 boundaries already shipped in commit c769b83), the overlap-at-5 metric and the 2,000-resample paired bootstrap are exactly as in TASK-CHAMPION-spec section C1.
- Truth per code: rate = establishments / POPESTIMATE2023 x 100,000; top 10. If a code has no row in cbp23msa, log it and drop that code from both arms (report n).
- Before any prediction: commit the plan file (this section, the C1 section it points to, the script path) and record its sha256.
- Knos arm uses the D2 launch-city method only for ranking (mean affinity per CBSA, CBSAs with at least 3 heatmap cells; if fewer than 5 such CBSAs, fill with CBSAs with 1-2 cells by mean affinity). An idea with no heatmap cells counts as overlap 0 for Knos.
- Run once. Publish the exact numbers (mean overlap each arm, difference, 95% interval, n, the plan sha256, the claude model and version) on the How we test Knos page and in docs/reference/OUTSIDE_TRUTH.md, whatever they show. No Qloo response bodies in public files: only the derived top-5 CBSA codes.

C1 test_where_truth
- Business types, exactly these 30 NAICS codes: 713940, 312120, 722515, 722511, 722513, 722410, 812111, 812112, 812113, 812910, 541940, 713110, 713120, 713910, 713950, 711130, 711110, 512131, 611610, 611620, 621310, 812199, 811192, 721110, 721191, 312130, 312140, 311811, 624410, 712110. Use each code's official NAICS title as the business-type phrase.
- Candidate metros: Metropolitan Statistical Areas with population of at least 500,000 in the ACS 1-year estimate for the same year as the CBP data. Both predictors choose only from these.
- Truth: Census County Business Patterns API, latest published year, geography metropolitan statistical area, field ESTAB for the code; rate = ESTAB / population x 100,000; top 10 per code. If a code is absent in that year's NAICS vintage, use the Census concordance equivalent and log the mapping.
- (a) Claude alone: claude -p with exactly: "From US metropolitan areas with at least 500,000 people, list the 5 where <NAICS title> businesses are most common per person. Reply with 5 metro area names, one per line, nothing else." Map names to CBSA codes by exact or fuzzy match against the candidate list; log the model name and version.
- (b) Knos: run the business-type phrase through Knos's normal demand-check path; take the Qloo heatmap cells, assign each to a CBSA using TIGER/Line 2023 CBSA boundaries, rank CBSAs in the candidate list by mean affinity, take the top 5.
- Metric: overlap at 5 = how many of the 5 are in the truth top 10, divided by 5. Mean over 30. Paired bootstrap, 2,000 resamples, 95% interval for (b) minus (a).
- Commit the plan file (this section copied plus the script path) and record its sha256 BEFORE any prediction is made. Run once. Publish the exact numbers on the How we test Knos page and docs/reference/OUTSIDE_TRUTH.md, whatever they show.

## Choices the rules leave open, fixed here

- The product's launch city is method (c) from the same commit as this plan: apps/wanted/knos_wanted/metros.py
  `launch()` takes the 15 most populous candidate metros and the highest lift among them, so the test measures what
  a person is shown.

### Data and truth

- Files: cbp23msa.zip (sha256 7c3afe15351e525bd1c1498a06018946b8f5fc9f70b87e2fc6f6df8c84800a1),
  cbsa-est2023-alldata.csv (a15cdfd3c6f1bdfe1430dcdf70ab9fcf039a2c629ff7584be6693e981d434a03) and the CBP reference
  titles naics2017.txt (959b8801c56df74a330bf02f853f7d389b1710d619fa5dd63577a36f783b7483), the same three D1 read.
  Every code below has its title in naics2017.txt.
- Truth, candidates, name matching and ties are D1's, run by the functions of scripts/test_where_truth.py: 110
  candidate metros, rate per 100,000 people, top 10, ties broken by CBSA code.

### The codes

- H7 never ran (Qloo answered 429 at its start, so it drew no codes). The codes D1 and H7 used are D1's 30.
- Eligible: the 6-digit codes of sectors 44-45, 71, 72 and 81 with a row in cbp23msa (154), minus the 20 of D1's
  codes among them. n eligible = 134. Every one has rows in candidate metros, so none is dropped.
- 134 is fewer than 150, so the split rule runs: each sample draws 134 // 2 = 67. Main:
  random.Random(4).sample(sorted eligible, 67). Replication: random.Random(5).sample(the 67 left, sorted, 67).
  Together they cover all 134 codes.

Eligible (sorted): 441110, 441120, 441210, 441222, 441228, 441310, 441320, 442110, 442210, 442291, 442299, 443141,
443142, 444110, 444120, 444130, 444190, 444210, 444220, 445110, 445120, 445210, 445220, 445230, 445291, 445292, 445299,
445310, 446110, 446120, 446130, 446191, 446199, 447110, 447190, 448110, 448120, 448130, 448140, 448150, 448190, 448210,
448310, 448320, 451110, 451120, 451130, 451140, 451211, 451212, 452210, 452311, 452319, 453110, 453210, 453220, 453310,
453910, 453920, 453930, 453991, 453998, 454110, 454210, 454310, 454390, 711120, 711190, 711211, 711212, 711219, 711310,
711320, 711410, 711510, 712120, 712130, 712190, 713210, 713290, 713920, 713930, 713990, 721120, 721199, 721211, 721214,
721310, 722310, 722320, 722330, 722514, 811111, 811112, 811113, 811118, 811121, 811122, 811191, 811198, 811211, 811212,
811213, 811219, 811310, 811411, 811412, 811420, 811430, 811490, 812191, 812210, 812220, 812310, 812320, 812331, 812332,
812921, 812922, 812930, 812990, 813110, 813211, 813212, 813219, 813311, 813312, 813319, 813410, 813910, 813920, 813930,
813940, 813990

Main sample (67, in drawn order): 453991, 712190, 445299, 811212, 813211, 448150, 445230, 442210, 441210, 452311,
711219, 812921, 448130, 811213, 811122, 442110, 446110, 711120, 711211, 451130, 448110, 811198, 445220, 811411, 444110,
447110, 445310, 441222, 713990, 811219, 811430, 812990, 447190, 445291, 445210, 813410, 813110, 713920, 811112, 451140,
443141, 813940, 448320, 721211, 451212, 454310, 446191, 812210, 721310, 813990, 812310, 811118, 813212, 448140, 441110,
812930, 711410, 811191, 454390, 811211, 452319, 453210, 448120, 453220, 453910, 445120, 446120

Replication sample (67, in drawn order): 711310, 722330, 441320, 812922, 811121, 813219, 446199, 721199, 813910,
812331, 444210, 444120, 453110, 711190, 813311, 453310, 711510, 443142, 712130, 811420, 441120, 445292, 453930, 448210,
444220, 811412, 812320, 442291, 444130, 454110, 713290, 811113, 722514, 811310, 813920, 813930, 811490, 442299, 453998,
454210, 444190, 721120, 813312, 722310, 451211, 451120, 813319, 713210, 452210, 445110, 722320, 711320, 451110, 448310,
441310, 812191, 713930, 441228, 446130, 453920, 711212, 812220, 712120, 811111, 721214, 448190, 812332

### The arms

- The 15 most populous candidates (POPESTIMATE2023, ties by CBSA code): 35620, 31080, 16980, 19100, 26420, 12060,
  47900, 37980, 33100, 38060, 14460, 40140, 41860, 19820, 42660.
- (a) Claude alone: D1's prompt with the code's title, run by test_where_truth.claude_arm (claude -p in an empty
  folder with no MCP servers, the first 5 non-empty reply lines, D1's matching).
- (b) Population: the first 5 of the 15.
- Knos's Qloo answer per code, from the operator's machine with the app's Qloo key read in memory from the Render
  service environment (never printed, stored or copied), at most 2 calls:
  1. GET /v2/tags with the parameters check.py's demand check sends for the title: filter.query = its content words
     (check.content_words, minus kind words and place nouns, at most 6), feature.semantic_search true,
     feature.typo_tolerance true, take 8.
  2. When check.py's own rule keeps a tag (its name shares a content word with the title; one per id and per name),
     GET /v2/insights with check._tag_map_q(first kept tag, no place): filter.type urn:heatmap,
     filter.location.query "United States", take 5, signal.interests.tags that tag. With no kept tag there is no
     second call.
  The first 50 cells are read (check.HEAT_CELLS). A map where every cell has one affinity (metros.flat) counts as no
  cells. Each cell is placed in a CBSA by metros.metro (TIGER/Line 2023 boundaries the app ships).
- (c) Primary: for each of the 15, lift = mean affinity of its cells / (its population / the 15's total population).
  Those with cells first by lift, then the rest (lift 0) by population; ties by population, then CBSA code. Top 5.
  With no cells, (c) equals (b).
- (d) Placebo: the 15 lift values of (c), in population order, shuffled by one random.Random(4) per sample, used
  code by code in drawn order; then ranked as (c), a shuffled 0 counting as no cell. Top 5.
- (e) Pure lift: metros.stats over the same cells (lift among the metros holding cells, those with at least 3 cells
  first), kept to the 110 candidates, top 5. No cells is overlap 0.
- Order of runs: --truth, then --claude, then --knos, then --score. --claude, --knos and --score refuse to start
  while this file is untracked or differs from HEAD, and print its sha256.

### Score and pass

- Overlap at 5 with the Census top 10, divided by 5, mean per sample per arm.
- Bootstrap per sample: one random.Random(4), 2,000 resamples of the sample's codes with replacement, each resample
  shared by (c)-(a), (c)-(b) and (c)-(d); percentile interval at the 50th and 1,950th sorted values.
- Pass, as K6 states: on the main sample the intervals for (c)-(a), (c)-(b) and (c)-(d) all lie above 0, and on the
  replication each of those three mean differences is above 0 (the same sign). A code missing from either arm, or a
  run that stopped early, is a FAIL.
- Output: docs/reference/impact_prereg.json with the plan sha256, n, Qloo call count, means, differences, intervals
  and per code only the CBSA codes of each arm's top 5 and the Census top 10. No Qloo response body is written there.

### Budget

- 134 codes x 2 = 268 Qloo calls at most. The script counts every request its own client sends (a cached answer is
  no request) and keeps the count in the private cache folder given on its command line, outside the repo.
- It refuses to start when the calls already counted plus 2 per code pass 1,000, and stops at 1,200.
- No retry. A 429 stops the run; a 429 on the first call is BLOCKED. Any other failed call counts as no cells.
