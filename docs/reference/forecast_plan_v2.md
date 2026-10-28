# Forecast plan, second version (fixed 28 Oct 2026, before any outcome)

The first plan (forecast_plan.md) named an outcome with no release date. This one names an outcome the Bureau of Labor
Statistics publishes on a date it has set: the Quarterly Census of Employment and Wages (QCEW) for the second quarter of
2026, released on Wednesday, 2 Dec 2026 at 10:00 ET (https://www.bls.gov/cew/release-calendar.htm, read on 28 Oct 2026).
The first plan is kept as it was.

## What is forecast

For each recorded idea, three forecasts of the county where its kind of business grows: Knos's pick (the launch place
its demand check named), the model's pick with no Qloo data, and a placebo. Each idea has one 6-digit NAICS code, below.
Only places in the United States are graded: the smart water bottle idea, whose Knos pick is outside the United States,
is listed as outside US data, not graded.

The placebo is drawn with Python's `random.Random(4)`, in the order of the table, from the 30 counties listed under
Placebo pool, and drawn again whenever the draw is Knos's own county.

## The outcome and the grade

- Source: the QCEW open data files, one per industry: `https://data.bls.gov/cew/data/api/2026/2/industry/<NAICS>.csv`
  and `https://data.bls.gov/cew/data/api/2025/2/industry/<NAICS>.csv`.
- Measure: private-ownership (`own_code` 5) establishments in the county (`qtrly_estabs`), second quarter of 2026 against
  the second quarter of 2025, as a percent change.
- A county with a disclosure code, or with 0 establishments in both quarters, has no data; a comparison that needs it is
  not counted, and is listed as no data.
- Per graded idea, Knos beats the placebo when its county's change is greater than the placebo's; the same for the model.
- Published: Knos against the placebo, and the model against the placebo, each as wins out of the ideas with data, with
  every idea's three changes and every loss. Nothing is dropped.

## The forecasts

The rows (each idea's three counties, its NAICS code and the day it was made) are held on the app's server, because
Knos's picks come from Qloo's answers, which are never stored in the site. The page /forecasts/ reads them from the
server when it is viewed and recomputes their sha256 in the browser. The sha256 of the rows, as canonical JSON (keys
sorted, no spaces), is:

`4be20f1e926259eb7ed2013465a702aeb377c0cd03603dfa12798b6453976401`

| Idea | NAICS | Industry | Model's county | Placebo |
|---|---|---|---|---|
| a solar powered music festival | 711320 | Promoters of performing arts, sports, and similar events without facilities | Riverside County, CA | Dallas County, TX |
| an ai recipe planner for families | 513210 | Software publishers | Franklin County, OH | Riverside County, CA |
| a crypto podcast for beginners | 516210 | Media streaming distribution services, social networks, and other media networks and content providers | Miami-Dade County, FL | Maricopa County, AZ |
| a probiotic kombucha brand | 312111 | Soft drink manufacturing | Travis County, TX | Suffolk County, NY |
| a recycled ocean plastic swimwear brand | 315250 | Cut and sew apparel manufacturing (except contractors) | San Diego County, CA | Clark County, NV |
| a quantum physics book for kids | 513130 | Book publishers | Boulder County, CO | Bexar County, TX |
| a smart water bottle that glows to remind you to drink | 326160 | Plastics bottle manufacturing | Maricopa County, AZ | not graded |

## Placebo pool

Los Angeles County, CA (06037), Cook County, IL (17031), Harris County, TX (48201), Maricopa County, AZ (04013), San Diego County, CA (06073), Orange County, CA (06059), Miami-Dade County, FL (12086), Dallas County, TX (48113), Kings County, NY (36047), Riverside County, CA (06065), Queens County, NY (36081), King County, WA (53033), Clark County, NV (32003), San Bernardino County, CA (06071), Tarrant County, TX (48439), Bexar County, TX (48029), Broward County, FL (12011), Santa Clara County, CA (06085), Wayne County, MI (26163), Alameda County, CA (06001), New York County, NY (36061), Philadelphia County, PA (42101), Middlesex County, MA (25017), Suffolk County, NY (36103), Sacramento County, CA (06067), Palm Beach County, FL (12099), Bronx County, NY (36005), Hillsborough County, FL (12057), Cuyahoga County, OH (39035), Travis County, TX (48453).
