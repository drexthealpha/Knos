# Forecast grading plan (fixed 27 Oct 2026, before /forecasts/ was published)

This file is fixed by its sha256, which /forecasts/ shows. It is not edited after that page is published; a change would
be a new plan with a new date and a new sha256.

## What is forecast

For each recorded idea with a recorded model answer (the seven of the front door's cards that say
"Model alone says ... Qloo says ..."), three forecasts of the US metro where the idea's kind of business is densest:

| Arm | The forecast |
|---|---|
| Knos with Qloo | the launch city of the card's terms when Qloo's heatmap set one, else the first city Qloo named for the idea; with its pre-order target when the terms set one |
| Model alone | the city the model named when asked once with no Qloo data, as recorded with the card |
| Placebo | `random.Random(4)`, one `choice` per idea in the order of the table below, over the same candidate cities Knos chose among (the terms' metros, else Qloo's named cities), sorted by name |

## The outcome and when it is read

- Source: the first year of the U.S. Census Bureau's County Business Patterns (CBP) released after 27 Oct 2026.
  The Census CBP data page (https://www.census.gov/programs-surveys/cbp/data.html, last revised 16 Sep 2026) says
  "The most current CBP data are for reference year 2023" and "We do not have a planned release date for our 2024 data
  at this time". CBP 2024 is therefore the outcome year.
- Grading date: the day CBP 2024 is released. The page names no date, so none is set here; the grade is computed on
  that day and published beside this file.
- Population: the Census Vintage 2024 metro population estimates.

## The metric: hit at 5

For each idea, the metros (CBSAs, 2023 delineation) with at least 250,000 people are ranked by establishments of the
idea's NAICS code per 100,000 residents. An arm scores a hit when its city falls in one of the top 5. A city outside the
United States, or in no metro, is a miss. Each arm's score is its hits over the seven ideas, and the three are reported
side by side with no other adjustment.

| Idea | NAICS (2022) | Industry |
|---|---|---|
| a solar powered music festival | 711320 | Promoters of performing arts, sports and similar events without facilities |
| an AI recipe planner for families | 513210 | Software publishers |
| a crypto podcast for beginners | 516210 | Media streaming distribution services, social networks and other media networks and content providers |
| a probiotic kombucha brand | 312111 | Soft drink manufacturing |
| a recycled ocean plastic swimwear brand | 315250 | Cut and sew apparel manufacturing |
| a quantum physics book for kids | 513130 | Book publishers |
| a smart water bottle that glows to remind you to drink | 326160 | Plastics bottle manufacturing |
